import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_all_pool_lifecycle import _batch_logs


class FakeRpc:
    def __init__(self, max_span=125):
        self.max_span=max_span
        self.accepted=[]

    def call(self, method, params, *, scope):
        self.assert_method = method
        row=params[0]
        start=int(row["fromBlock"],16)
        end=int(row["toBlock"],16)
        if end-start+1>self.max_span:
            raise BoundaryError("provider_range_too_large")
        self.accepted.append((start,end))
        # Deliberately reverse transaction/log ordering inside each accepted page;
        # _batch_logs must canonicalize the final event order.
        return [
            dict(blockNumber=hex(end), transactionIndex="0x1", logIndex="0x1"),
            dict(blockNumber=hex(start), transactionIndex="0x0", logIndex="0x0"),
        ]


class HistoricalFastLogsTests(unittest.TestCase):
    def test_recursive_split_has_exact_block_coverage_and_sorted_events(self):
        rpc=FakeRpc(max_span=125)
        rows=_batch_logs(
            rpc,1000,1999,"0x"+"11"*20,
            scope="test_history",
            topics=["0x"+"22"*32],
        )
        covered=[]
        for start,end in sorted(rpc.accepted):
            covered.extend(range(start,end+1))
        self.assertEqual(covered,list(range(1000,2000)))
        self.assertEqual(len(covered),len(set(covered)))
        keys=[
            (int(r["blockNumber"],16),int(r["transactionIndex"],16),int(r["logIndex"],16))
            for r in rows
        ]
        self.assertEqual(keys,sorted(keys))

    def test_empty_interval_makes_no_rpc_calls(self):
        rpc=FakeRpc()
        self.assertEqual(_batch_logs(rpc,5,4,"0x"+"11"*20),[])
        self.assertEqual(rpc.accepted,[])


if __name__=="__main__":
    unittest.main()
