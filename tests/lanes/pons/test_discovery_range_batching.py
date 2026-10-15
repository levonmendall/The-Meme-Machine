"""Discovery throughput regressions; entirely synthetic, no provider access."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_cohort as cohort


def event(block,index=0):
    return dict(blockNumber=hex(block),transactionIndex="0x0",
                logIndex=hex(index),transactionHash="0x"+f"{block:064x}")


class Rpc:
    used=0
    primary_fallback=True
    def __init__(self,failure=None):
        self.batches=[];self.calls=[];self.failure=failure
    def batch(self,calls,*,scope):
        self.batches.append((calls,scope))
        if self.failure:raise BoundaryError(self.failure)
        return [self.page(params[0]) for method,params in calls]
    def call(self,method,params,*,scope):
        self.calls.append((method,params,scope))
        return self.page(params[0])
    @staticmethod
    def page(query):
        return [event(n) for n in range(int(query["fromBlock"],16),
                                       int(query["toBlock"],16)+1)]


class Feed:
    def __init__(self,frontier):
        self.frontier=frontier;self.reads=[]
    def wait_for_range_after(self,cursor,**kwargs):
        self.reads.append((cursor,kwargs))
        return min(cursor+kwargs["max_blocks"],self.frontier) if cursor<self.frontier else None


class DiscoveryBatchTests(unittest.TestCase):
    def test_candidate_work_does_not_accumulate_an_unread_log_frontier(self):
        # Twenty new blocks arrive while one candidate consumes its work time.
        # The former one-range loop advanced only ten and accumulated backlog.
        feed=Feed(100);rpc=Rpc();cursor=100;tape=[]
        with patch.object(cohort.time,"monotonic",return_value=100.0):
            for _ in range(20):
                feed.frontier+=20
                rpc,cursor,fresh=cohort._poll("unused",rpc,cursor,tape,feed,[])
                self.assertEqual(cursor,feed.frontier)
                self.assertEqual(len(fresh),20)
        self.assertEqual([int(x["blockNumber"],16) for x in tape],list(range(101,501)))
        self.assertEqual(len(rpc.batches),20)
        self.assertEqual(len(rpc.calls),0)
        for calls,scope in rpc.batches:
            self.assertEqual(scope,"pons_natural")
            self.assertEqual(len(calls),2)
            for method,params in calls:
                self.assertEqual(method,"eth_getLogs")
                self.assertEqual(int(params[0]["toBlock"],16)-int(params[0]["fromBlock"],16)+1,10)
                self.assertEqual(len(params[0]["topics"][0]),2)

    def test_cold_backlog_is_bounded_and_never_skips_a_range(self):
        feed=Feed(1000);rpc=Rpc();tape=[]
        with patch.object(cohort.time,"monotonic",return_value=100.0):
            _,cursor,fresh=cohort._poll("unused",rpc,100,tape,feed,[])
        self.assertEqual(cursor,140)
        self.assertEqual(len(rpc.batches),1)
        self.assertEqual(len(rpc.batches[0][0]),4)
        self.assertEqual([int(x["blockNumber"],16) for x in fresh],list(range(101,141)))
        self.assertEqual(tape,fresh)

    def test_range_collection_uses_one_original_poll_clock(self):
        now=[100.0];seen=[]
        def single(feed,cursor,rpc,*,timeout):
            seen.append(timeout)
            now[0]+=min(0.3,timeout)
            return cursor+10
        with patch.object(cohort.time,"monotonic",side_effect=lambda:now[0]),patch.object(
            cohort,"_next_single_discovery_end",side_effect=single):
            end=cohort._next_discovery_end(None,100,None,timeout=0.5)
        self.assertEqual(end,120)
        self.assertEqual(len(seen),2)
        self.assertAlmostEqual(seen[0],0.5)
        self.assertAlmostEqual(seen[1],0.2)
        self.assertAlmostEqual(now[0],100.5)

    def test_no_new_frontier_never_sends_a_log_request(self):
        rpc=Rpc()
        with patch.object(cohort.time,"monotonic",return_value=100.0):
            _,cursor,fresh=cohort._poll("unused",rpc,100,[],Feed(100),[])
        self.assertEqual((cursor,fresh),(100,[]))
        self.assertEqual((rpc.calls,rpc.batches),([],[]))

    def test_single_range_preserves_existing_single_transport(self):
        rpc=Rpc()
        rows=cohort._discovery_curve_events(rpc,101,110)
        self.assertEqual(len(rows),10)
        self.assertEqual(len(rpc.calls),1)
        self.assertEqual(rpc.batches,[])

    def test_authentication_failure_does_not_advance_cursor_or_retry(self):
        rpc=Rpc("provider_http_401");tape=[]
        with patch.object(cohort.time,"monotonic",return_value=100.0),patch.object(
            cohort,"_recover_discovery") as recover:
            with self.assertRaisesRegex(BoundaryError,"provider_http_401"):
                cohort._poll("unused",rpc,100,tape,Feed(140),[])
        self.assertEqual(tape,[])
        self.assertEqual(len(rpc.batches),1)
        recover.assert_not_called()

    def test_transient_batch_recovery_preserves_original_range_identity(self):
        failed=Rpc("provider_http_429");replacement=Rpc();tape=[]
        with patch.object(cohort.time,"monotonic",return_value=100.0),patch.object(
            cohort,"_recover_discovery",return_value=replacement) as recover:
            returned,cursor,fresh=cohort._poll("unused",failed,100,tape,Feed(140),[])
        self.assertIs(returned,replacement)
        self.assertEqual(cursor,140)
        self.assertEqual(failed.batches,replacement.batches)
        self.assertEqual(recover.call_args.args[2],100)
        self.assertEqual(len(tape),40)
        self.assertEqual(tape,fresh)

    def test_malformed_batch_fail_closed(self):
        for pages,reason in (([[]],"batch_shape"),([None,[]],"log_shape")):
            rpc=Rpc()
            with self.subTest(reason=reason),patch.object(rpc,"batch",return_value=pages):
                with self.assertRaisesRegex(BoundaryError,reason):
                    cohort._discovery_curve_events(rpc,101,120)

    def test_removed_or_future_log_never_advances_the_original_range(self):
        for bad in (event(121),dict(event(101),removed=True)):
            rpc=Rpc();tape=[]
            with patch.object(rpc,'batch',return_value=[[bad],[]]),patch.object(cohort.time,'monotonic',return_value=100.):
                with self.assertRaisesRegex(BoundaryError,'log_range_identity'):
                    cohort._poll('unused',rpc,100,tape,Feed(120),[])
            self.assertEqual(tape,[])

    def test_more_than_one_thousand_events_in_one_range_are_retained(self):
        rpc=Rpc();pages=[[],[event(111,i) for i in range(1025)]]
        with patch.object(rpc,'batch',return_value=pages):
            self.assertEqual(cohort._discovery_curve_events(rpc,101,120),pages[1])

    def test_batch_capacity_is_checked_before_transport(self):
        rpc=Rpc()
        with self.assertRaisesRegex(BoundaryError,"batch_capacity"):
            cohort._discovery_curve_events(rpc,101,141)
        self.assertEqual((rpc.calls,rpc.batches),([],[]))

    def test_more_than_one_thousand_events_across_distinct_valid_ranges_are_retained(self):
        rpc=Rpc()
        pages=[[event(101,i) for i in range(1000)],[event(111,i) for i in range(1000)]]
        with patch.object(rpc,"batch",return_value=pages):
            rows=cohort._discovery_curve_events(rpc,101,120)
        self.assertEqual(len(rows),2000)
        self.assertEqual(rows,pages[0]+pages[1])

    def test_invalid_observation_range_never_becomes_canonical(self):
        for returned in (100,99,111):
            with self.subTest(returned=returned),patch.object(cohort.time,"monotonic",return_value=100.0),patch.object(
                cohort,"_next_single_discovery_end",return_value=returned):
                with self.assertRaisesRegex(BoundaryError,"range_identity"):
                    cohort._next_discovery_end(None,100,None,timeout=0.5)


if __name__=="__main__":
    unittest.main()
