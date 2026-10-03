"""Causal source-starvation regressions with no market/provider I/O."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm
from meme_machine.lanes.meteora.dlmm_discovery import CampaignDiscovery
from tests.lanes.meteora import solana_dlmm_independent_v1 as strategy


def row(name):
    return dict(address=name,name=name,tvl=1000,is_blacklisted=False,
        token_x=dict(address=dlmm.WSOL),token_y=dict(address='token'),
        volume={'5m':100,'30m':1000},fees={'5m':1,'30m':10})

class DiscoverySchedulerTests(unittest.TestCase):
    def source(self,path,api,clock,**kw):
        return CampaignDiscovery(path,api=api,candidate=strategy._candidate,
            eligible=strategy._sol_pair,sorts=strategy.DISCOVERY_SORTS,
            pages=strategy.DISCOVERY_PAGES_PER_SORT,page_size=strategy.DISCOVERY_PAGE_SIZE,
            deadline=121,clock=lambda:clock[0],wall_clock=lambda:2800+clock[0],**kw)

    def test_blocked_consumer_does_not_starve_any_page_or_next_census(self):
        clock=[0.];calls=[];cycles=[threading.Event(),threading.Event()]
        release=threading.Event();counter=[0]
        def api(path,p):
            calls.append((clock[0],p['sort_by'],p['page']))
            return {'data':[row('first' if clock[0]==0 else 'new')]*250}
        def wait(delay):
            index=counter[0];counter[0]+=1
            if index<2:cycles[index].set()
            while not release.wait(.01):
                if source.stop.is_set():return True
            release.clear();clock[0]+=delay
        with tempfile.TemporaryDirectory() as td:
            source=self.source(Path(td)/'spool.sqlite',api,clock,wait=wait).start()
            try:
                self.assertTrue(cycles[0].wait(2))
                self.assertEqual(len(calls),6)
                # No consumer has advanced. Discovery must still run another cycle.
                release.set();self.assertTrue(cycles[1].wait(2))
                self.assertEqual(len(calls),12)
                self.assertEqual({x[0] for x in calls},{0.,60.})
                self.assertEqual(source.snapshot()['first_seen'],2)
                first=source.next_candidate();second=source.next_candidate()
                self.assertEqual([first['address'],second['address']],['first','new'])
                self.assertEqual(first['source_observed_at'],2800)
                self.assertEqual(first['discovery_queue_wait_seconds'],60)
                self.assertEqual(first['discovery_sort'],strategy.DISCOVERY_SORTS[0])
                self.assertEqual(source.snapshot()['pending'],0)
            finally:source.close()

    def test_first_handoff_precedes_full_census_and_discovery_record_precedes_handoff(self):
        clock=[0.];in_second=threading.Event();release_second=threading.Event()
        recording=threading.Event();release_record=threading.Event();received=threading.Event()
        result=[];calls=[]
        def api(path,p):
            calls.append(p)
            if len(calls)==2:
                in_second.set();release_second.wait(2)
            return {'data':[row('first')]*250}
        def discovered(*_):recording.set();release_record.wait(2)
        with tempfile.TemporaryDirectory() as td:
            source=self.source(Path(td)/'spool.sqlite',api,clock,on_discovered=discovered).start()
            consumer=threading.Thread(target=lambda:(result.append(source.next_candidate()),received.set()))
            consumer.start()
            try:
                self.assertTrue(recording.wait(2));self.assertFalse(received.wait(.05))
                release_record.set();self.assertTrue(in_second.wait(2));self.assertTrue(received.wait(2))
                self.assertEqual(result[0]['address'],'first');self.assertEqual(len(calls),2)
            finally:
                source.stop.set();release_record.set();release_second.set();consumer.join(2);source.close()

    def test_failed_page_does_not_skip_other_frozen_segments_and_pending_is_explicit(self):
        clock=[0.];calls=[]
        def api(path,p):
            calls.append((p['sort_by'],p['page']))
            if len(calls)==1:raise OSError('simulated')
            return {'data':[row('pool')]*250}
        with tempfile.TemporaryDirectory() as td:
            source=self.source(Path(td)/'spool.sqlite',api,clock,wait=lambda _:clock.__setitem__(0,121))
            source._produce()
            stats=source.snapshot()
            self.assertEqual(len(calls),6)
            self.assertEqual(stats['segment_status_counts'],{'acquired':5,'failed':1})
            self.assertEqual(stats['pending'],1);self.assertIsNone(stats['target_universe_count'])
            self.assertIsNone(source.next_candidate());source.close()

    def test_short_page_exhaustion_and_late_response_are_not_successful_pages(self):
        clock=[0.];calls=[]
        def api(path,p):
            calls.append(p)
            if len(calls)==2:clock[0]=121
            return {'data':[row('pool')]}
        with tempfile.TemporaryDirectory() as td:
            source=self.source(Path(td)/'spool.sqlite',api,clock);source._produce()
            stats=source.snapshot()
            self.assertEqual(stats['segment_status_counts'],{'acquired':1,'exhausted':1,'late_response':1,'not_observed':3})
            self.assertEqual(stats['first_seen'],1);source.close()

    def test_unexpected_producer_failure_fails_closed_and_process_dedup_resets(self):
        clock=[0.]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'spool.sqlite'
            source=self.source(path,lambda *_:{'data':[row('pool')]},clock,
                on_discovered=lambda *_:(_ for _ in ()).throw(ValueError('bad callback')))
            source._produce()
            with self.assertRaisesRegex(RuntimeError,'discovery_producer:ValueError'):source.next_candidate()
            with self.assertRaisesRegex(RuntimeError,'discovery_producer:ValueError'):source.close()
            source=self.source(path,lambda *_:{'data':[row('pool')]},clock,wait=lambda _:clock.__setitem__(0,121))
            source._produce();self.assertEqual(source.snapshot()['first_seen'],1);source.close()

if __name__=='__main__':unittest.main()
