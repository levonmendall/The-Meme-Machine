"""Pure bounded native cohort metadata; no source or consumer authority."""
import unittest
from unittest.mock import patch
from meme_machine.runtime.economic_cohort import EconomicCohorts,checksum

NOW=1700000000.0


class EconomicCohortTests(unittest.TestCase):
    def meter(self):return EconomicCohorts('pump',dict(source_pid=123,run_identity='a'*32))

    def test_requires_complete_source_exact_economics_and_every_fanout_ack(self):
        meter=self.meter();meter.open('window',('program:pump',))
        row=('program:pump','event',checksum('body'),10,NOW)
        meter.arrivals('window',(row,row))
        obligations=(('one',*row[:2],checksum('first'),'consumer-1'),
            ('two',*row[:2],checksum('second'),'consumer-2'))
        meter.committed('window',((*row,True),),obligations)
        meter.seal('window',10,10,checksum('source'),complete=False)
        meter.acknowledged((('one',checksum('first')),('two',checksum('second'))))
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        self.assertEqual(meter.snapshot()['full_market_rate'],
            'UNKNOWN_REQUIRES_CONTIGUOUS_SOURCE_AND_FRESH_HEAD_CENSUS')

    def test_reconciles_only_after_final_ack_and_keeps_detached_summary(self):
        meter=self.meter();meter.open('window',('program:pump',))
        row=('program:pump','event',checksum('body'),10,NOW)
        meter.arrivals('window',(row,));meter.committed('window',((*row,False),),
            (('one',*row[:2],checksum('source'),'consumer'),))
        meter.seal('window',10,10,checksum('coverage'),complete=True)
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter.acknowledged((('one',checksum('source')),))
        result=meter.snapshot();self.assertEqual(result['completed_cohorts'],1)
        self.assertEqual(result['closed'][0]['replay_canonical'],1)
        self.assertEqual(result['closed'][0]['new_canonical'],0)
        result['closed'][0]['unique_economics']=999
        self.assertEqual(meter.snapshot()['closed'][0]['unique_economics'],1)
        meter.open('window',('program:pump',))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_bounds_and_conflicts_remain_unknown_with_no_partial_positive(self):
        for kind in ('bound','hash','ack','scope'):
            with self.subTest(kind=kind):
                meter=self.meter();meter.open('window',('program:pump',))
                row=('program:pump','event',checksum('body'),10,NOW)
                meter.arrivals('window',(row,))
                if kind=='bound':
                    with patch('meme_machine.runtime.economic_cohort.MAX_BYTES',meter.bytes):
                        meter.arrivals('window',(('program:pump','another',checksum('body'),10,NOW),))
                elif kind=='hash':meter.committed('window',((row[0],row[1],checksum('changed'),10,NOW,True),),())
                elif kind=='scope':meter.arrivals('window',(('foreign','event',checksum('body'),10,NOW),))
                else:
                    meter.committed('window',((*row,True),),(('one',*row[:2],checksum('source'),'consumer'),))
                    meter.acknowledged((('one',checksum('changed')),))
                result=meter.snapshot();self.assertEqual(result['state'],'UNKNOWN')
                self.assertFalse(result['funding_authority']);self.assertEqual(result['completed_cohorts'],0)


    def test_pons_native_history_publication_is_not_source_full_ack_completion(self):
        meter=EconomicCohorts('pons',dict(source_pid=123,stage='current'))
        meter.open('window',('curve',))
        row=('curve','block:tx:log',checksum('body'),10,NOW)
        meter.arrivals('window',(row,));meter.committed('window',((*row,True),),())
        meter.seal('window',10,10,checksum('bounded-query'),complete=False)
        result=meter.snapshot()
        self.assertEqual(result['active'][0]['canonical_publications'],1)
        self.assertEqual(result['active'][0]['native_new'],1)
        self.assertEqual(result['delivery_contract'],'PONS_CONSUMER_COMPLETION_UNESTABLISHED')
        self.assertEqual(result['completed_cohorts'],0)
        meter.acknowledged(())
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
