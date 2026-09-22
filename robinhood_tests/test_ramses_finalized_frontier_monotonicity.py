import unittest

from robinhood_research import BoundaryError
from robinhood_research.ramses_capture import BoundedMultiRpc


def header(block, *, hash_byte=None, timestamp=None, parent_byte=None):
    hash_byte=block%250+1 if hash_byte is None else hash_byte
    parent_byte=(block-1)%250+1 if parent_byte is None else parent_byte
    return {
        "number":hex(block),
        "hash":"0x"+format(hash_byte,"02x")*32,
        "parentHash":"0x"+format(parent_byte,"02x")*32,
        "timestamp":hex(block*10 if timestamp is None else timestamp),
    }


class FakeSession:
    def __init__(self, rows):
        self.rows=list(rows)
        self.calls=[]
    def call(self,method,params,scope="connectivity"):
        self.calls.append((method,params,scope))
        if not self.rows:
            raise AssertionError("unexpected provider call")
        value=self.rows.pop(0)
        if isinstance(value,BaseException):
            raise value
        return value


def rpc(rows):
    value=object.__new__(BoundedMultiRpc)
    value.rate_retries=0
    value.wrapper_retries=0
    value.rate_cooldown=0.0
    value.rate_limit_events=0
    value.rate_limit_sleep_seconds=0.0
    value._fake=FakeSession(rows)
    value._session=lambda _needed=1:value._fake
    return value


class FinalizedFrontierMonotonicityTests(unittest.TestCase):
    def test_verified_stale_finalized_tag_does_not_roll_campaign_backward(self):
        high=header(100,timestamp=1000)
        stale=header(99,timestamp=990)
        value=rpc([high,stale,high])
        self.assertEqual(
            value.call("eth_getBlockByNumber",["finalized",False],
                       scope="extended_frontier"),
            high,
        )
        recovered=value.call(
            "eth_getBlockByNumber",["finalized",False],
            scope="extended_frontier",
        )
        self.assertEqual(recovered,high)
        self.assertEqual(value.finalized_frontier_stale_responses,1)
        self.assertEqual(value.finalized_frontier_recovery_reads,1)
        self.assertEqual(
            value._fake.calls[-1],
            ("eth_getBlockByNumber",[hex(100),False],
             "extended_frontier_finalized_recovery"),
        )

    def test_stale_tag_fails_closed_when_prior_finalized_hash_no_longer_authenticates(self):
        high=header(100,timestamp=1000)
        stale=header(99,timestamp=990)
        changed=header(100,hash_byte=201,timestamp=1000)
        value=rpc([high,stale,changed])
        value.call("eth_getBlockByNumber",["finalized",False])
        with self.assertRaisesRegex(
                BoundaryError,"ramses_finalized_frontier_regression_unverified"):
            value.call("eth_getBlockByNumber",["finalized",False])

    def test_same_height_conflict_remains_fatal(self):
        high=header(100,timestamp=1000)
        conflict=header(100,hash_byte=202,timestamp=1000)
        value=rpc([high,conflict])
        value.call("eth_getBlockByNumber",["finalized",False])
        with self.assertRaisesRegex(
                BoundaryError,"ramses_finalized_frontier_conflict"):
            value.call("eth_getBlockByNumber",["finalized",False])

    def test_forward_height_timestamp_regression_remains_fatal(self):
        high=header(100,timestamp=1000)
        bad=header(101,timestamp=999)
        value=rpc([high,bad])
        value.call("eth_getBlockByNumber",["finalized",False])
        with self.assertRaisesRegex(
                BoundaryError,"ramses_finalized_frontier_timestamp_regression"):
            value.call("eth_getBlockByNumber",["finalized",False])

    def test_normal_advance_remains_unchanged(self):
        high=header(100,timestamp=1000)
        newer=header(101,timestamp=1010)
        value=rpc([high,newer])
        self.assertEqual(value.call(
            "eth_getBlockByNumber",["finalized",False]),high)
        self.assertEqual(value.call(
            "eth_getBlockByNumber",["finalized",False]),newer)


if __name__=="__main__":
    unittest.main()
