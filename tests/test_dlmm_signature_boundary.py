"""Offline regressions for bounded DLMM signature coverage pagination."""
import unittest

from meme_machine.dlmm_tape import MAX_TRANSACTIONS
from meme_machine.provider import Unavailable
from tests import dlmm_boundary_acquisition as boundary


def sig(name, slot, index, err=None):
    return dict(signature=name,slot=slot,transactionIndex=index,err=err,
                confirmationStatus='finalized')


class _RPC:
    def __init__(self,*pages):
        self.pages=[list(page) for page in pages]
        self.calls=[];self.sleeps=[]
    def sleep(self,seconds):
        self.sleeps.append(seconds)
    def call(self,method,params,priority):
        self.calls.append((method,params,priority))
        if method!='getSignaturesForAddress':
            raise AssertionError(method)
        index=len(self.calls)-1
        if index>=len(self.pages):
            raise AssertionError('unexpected census page')
        if index:
            self.assert_before=params[1].get('before')
        return list(self.pages[index])


class SignatureBoundary(unittest.TestCase):
    def test_first_page_boundary_needs_no_fallback(self):
        rpc=_RPC([sig('n2',102,2),sig('n1',101,1),sig('anchor',100,9)])
        proof=boundary.complete_signature_census(rpc,'pool',100,102)
        self.assertEqual([x['signature'] for x in proof],['n2','n1','anchor'])
        self.assertEqual(len(rpc.calls),1)

    def test_post_endpoint_pages_are_skipped_until_interval_and_boundary(self):
        # Two full pages are entirely newer than the authenticated endpoint. They
        # prove nothing about the interval and must not consume its 16-tx allowance.
        p1=[sig(f'p1-{i}',300-i,63-i) for i in range(64)]
        p2=[sig(f'p2-{i}',236-i,63-i) for i in range(64)]
        p3=[sig('newer',105,5),sig('i4',104,4),sig('i3',103,3),
            sig('i2',102,2),sig('i1',101,1),sig('anchor',100,9)]
        rpc=_RPC(p1,p2,p3);telemetry={}
        proof=boundary.complete_signature_census(rpc,'pool',100,104,telemetry)
        self.assertEqual([x['signature'] for x in proof],['i4','i3','i2','i1','anchor'])
        self.assertEqual(len(rpc.calls),3)
        self.assertEqual(rpc.sleeps,[boundary.CENSUS_PAGE_DELAY_SECONDS]*2)
        self.assertEqual(rpc.calls[1][1][1]['before'],'p1-63')
        self.assertEqual(rpc.calls[2][1][1]['before'],'p2-63')
        self.assertEqual(telemetry['post_endpoint_rows_skipped'],129)
        self.assertEqual(telemetry['combined_successful_post_start'],4)
        self.assertEqual(telemetry['boundary_slot'],100)
        self.assertTrue(telemetry['census_completed'])

    def test_actual_interval_over_sixteen_still_fails_closed(self):
        interval=[sig(f'i{i}',120-i,120-i) for i in range(17)]
        rpc=_RPC(interval+[sig('anchor',99,99)])
        with self.assertRaisesRegex(Unavailable,'transaction_bound'):
            boundary.complete_signature_census(rpc,'pool',100,120)
        self.assertEqual(MAX_TRANSACTIONS,16)

    def test_page_cap_fails_closed_without_fetching_seventeenth_page(self):
        pages=[]
        slot=5000
        for p in range(boundary.MAX_CENSUS_PAGES):
            pages.append([sig(f'p{p}-{i}',slot-i,63-i) for i in range(boundary.PAGE_LIMIT)])
            slot-=boundary.PAGE_LIMIT
        rpc=_RPC(*pages);telemetry={}
        with self.assertRaisesRegex(Unavailable,'census_page_bound'):
            boundary.complete_signature_census(rpc,'pool',1,10,telemetry)
        self.assertEqual(len(rpc.calls),boundary.MAX_CENSUS_PAGES)
        self.assertEqual(telemetry['census_rows_scanned'],boundary.MAX_CENSUS_ROWS)

    def test_short_exhausted_history_without_boundary_fails_closed(self):
        rpc=_RPC([sig('n2',104,2),sig('n1',103,1)])
        with self.assertRaisesRegex(Unavailable,'missing_start_boundary'):
            boundary.complete_signature_census(rpc,'pool',100,104)
        self.assertEqual(len(rpc.calls),1)

    def test_pagination_duplicate_is_not_silently_deduplicated(self):
        first=[sig(f'n{i}',200-i,63-i) for i in range(64)]
        second=[sig('n63',137,0),sig('anchor',100,9)]
        rpc=_RPC(first,second)
        with self.assertRaisesRegex(Unavailable,'pagination_duplicate'):
            boundary.complete_signature_census(rpc,'pool',100,104)

    def test_telemetry_describes_pages_without_changing_proof(self):
        first=[sig(f'p-{i}',170-i,63-i) for i in range(64)]
        second=[sig('i2',102,2),sig('i1',101,1),sig('anchor',100,9)]
        rpc=_RPC(first,second);telemetry={}
        proof=boundary.complete_signature_census(rpc,'pool',100,102,telemetry=telemetry)
        self.assertEqual([x['signature'] for x in proof],['i2','i1','anchor'])
        self.assertEqual(telemetry['first_page_count'],64)
        self.assertTrue(telemetry['fallback_attempted'])
        self.assertEqual(telemetry['census_pages_used'],2)
        self.assertEqual(telemetry['combined_successful_post_start'],2)
        self.assertTrue(telemetry['combined_has_start_boundary'])
        self.assertTrue(telemetry['census_completed'])

    def test_endpoint_slots_survive_page_bound_failure(self):
        boundary.ENDPOINT_DIAGNOSTICS.clear()
        pages=[]
        slot=5000
        for p in range(boundary.MAX_CENSUS_PAGES):
            pages.append([sig(f'p{p}-{i}',slot-i,63-i) for i in range(boundary.PAGE_LIMIT)])
            slot-=boundary.PAGE_LIMIT
        class Adapter:
            def __init__(self):
                self.rpc=_RPC(*pages)
            def snapshot(self,pool,now,priority=False,fresh=False):
                self.fresh=fresh
                return dict(slot=104,market_time=101,available_time=102)
        adapter=Adapter();start=dict(pool='pool',slot=100,time=100)
        with self.assertRaisesRegex(Unavailable,'census_page_bound'):
            boundary.capture_chunk(adapter,start,[100,2**31-1,2**31-1])
        item=boundary.ENDPOINT_DIAGNOSTICS[0]
        self.assertTrue(adapter.fresh)
        self.assertEqual((item['start_slot'],item['end_slot']),(100,104))
        self.assertTrue(item['slot_advanced'])
        self.assertEqual(item['census_pages_used'],boundary.MAX_CENSUS_PAGES)
        self.assertFalse(item['census_completed'])
        self.assertEqual(item['capture_error'],'dlmm_signature_census_page_bound')


if __name__=='__main__':
    unittest.main()
