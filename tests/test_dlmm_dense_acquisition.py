"""Regression coverage for transaction-pressure bounded DLMM acquisition."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.dlmm_tape import MAX_TRANSACTIONS
from tests import dlmm_dense_acquisition as dense


class _RPC:
    def __init__(self, counts, start_slot=100):
        self.counts=list(counts);self.start_slot=start_slot;self.calls=[]
    def call(self, method, params, _required):
        self.calls.append((method,params))
        if method!='getSignaturesForAddress':
            raise AssertionError(method)
        count=self.counts.pop(0)
        rows=[dict(signature=f's{i}',slot=self.start_slot+i+1,err=None,
                   confirmationStatus='finalized') for i in range(count)]
        rows.reverse()
        rows.append(dict(signature='anchor',slot=self.start_slot,err=None,
                         confirmationStatus='finalized'))
        return rows[:dense.PRESSURE_CENSUS_LIMIT]


class DenseAcquisition(unittest.TestCase):
    def _clock(self):
        state={'t':0.0}
        def monotonic():return state['t']
        def sleep(seconds):state['t']+=seconds
        return state,monotonic,sleep

    def test_predictive_pressure_closes_before_old_eight_transaction_boundary(self):
        rpc=_RPC([2,4,8]);adapter=SimpleNamespace(rpc=rpc)
        state,monotonic,sleep=self._clock();current={'pool':dict(pool='pool',slot=100)}
        with patch.object(dense.time,'monotonic',monotonic),patch.object(dense.time,'sleep',sleep):
            boundary=dense._await_pressure_boundary(adapter,current,2.0)
        self.assertEqual(boundary['trigger'],'predictive_transaction_pressure')
        self.assertLess(boundary['counts']['pool'],8)
        policy=boundary['predictive_policy']['pool']
        self.assertGreaterEqual(policy['reserved_headroom'],10)
        self.assertLessEqual(policy['close_threshold'],6)
        self.assertEqual(rpc.calls[0][1][1]['limit'],MAX_TRANSACTIONS+1)

    def test_measured_endpoint_latency_never_reduces_predictive_reserve(self):
        fast=dense._predictive_close_policy([(0.5,1),(0.75,2)],1.0)
        slow=dense._predictive_close_policy([(0.5,1),(0.75,2)],2.0)
        self.assertGreaterEqual(slow['reserved_headroom'],fast['reserved_headroom'])
        self.assertLessEqual(slow['close_threshold'],fast['close_threshold'])

    def test_idle_market_closes_on_time_without_busy_polling(self):
        rpc=_RPC([0,0,0]);adapter=SimpleNamespace(rpc=rpc)
        state,monotonic,sleep=self._clock()
        current={'pool':dict(pool='pool',slot=100)}
        with patch.object(dense.time,'monotonic',monotonic),patch.object(dense.time,'sleep',sleep):
            boundary=dense._await_pressure_boundary(adapter,current,2.0)
        self.assertEqual(boundary['trigger'],'time')
        self.assertEqual(boundary['waited_seconds'],2.0)
        self.assertEqual(boundary['polls'],3)

    def test_hard_cap_visible_never_gets_relabelled_as_valid_chunk(self):
        rpc=_RPC([MAX_TRANSACTIONS+1]);adapter=SimpleNamespace(rpc=rpc)
        state,monotonic,sleep=self._clock()
        current={'pool':dict(pool='pool',slot=100)}
        with patch.object(dense.time,'monotonic',monotonic),patch.object(dense.time,'sleep',sleep):
            boundary=dense._await_pressure_boundary(adapter,current,2.0)
        self.assertEqual(boundary['trigger'],'hard_cap_visible')
        self.assertEqual(boundary['overflow'],('pool',))
        self.assertGreater(boundary['counts']['pool'],MAX_TRANSACTIONS)
        self.assertEqual(dense.PRESSURE_SOFT_LIMIT,10)


if __name__=='__main__':unittest.main()
