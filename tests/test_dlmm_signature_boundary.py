"""Offline regressions for bounded DLMM signature start-boundary pagination."""
import unittest

from meme_machine.dlmm_tape import MAX_TRANSACTIONS
from meme_machine.provider import Unavailable
from tests import dlmm_boundary_acquisition as boundary


def sig(name, slot, index, err=None):
    return dict(signature=name, slot=slot, transactionIndex=index, err=err,
                confirmationStatus='finalized')


class _RPC:
    def __init__(self, first, second=None):
        self.first=list(first);self.second=None if second is None else list(second);self.calls=[]
    def call(self, method, params, priority):
        self.calls.append((method, params, priority))
        if method != 'getSignaturesForAddress':
            raise AssertionError(method)
        config=params[1]
        if 'before' not in config:
            return list(self.first)
        if self.second is None:
            raise AssertionError('unexpected fallback page')
        self.assert_before=config['before']
        return list(self.second)


class SignatureBoundary(unittest.TestCase):
    def test_first_page_boundary_needs_no_fallback(self):
        rpc=_RPC([sig('n2',102,2),sig('n1',101,1),sig('anchor',100,9)])
        proof=boundary.complete_signature_census(rpc,'pool',100,102)
        self.assertEqual([x['signature'] for x in proof],['n2','n1','anchor'])
        self.assertEqual(len(rpc.calls),1)

    def test_one_before_page_recovers_missing_start_boundary(self):
        first=[sig('n4',104,4),sig('n3',103,3),sig('n2',102,2),sig('n1',101,1)]
        second=[sig('anchor',100,9),sig('older',99,8)]
        rpc=_RPC(first,second)
        proof=boundary.complete_signature_census(rpc,'pool',100,104)
        self.assertEqual([x['signature'] for x in proof],['n4','n3','n2','n1','anchor'])
        self.assertEqual(len(rpc.calls),2)
        self.assertEqual(rpc.calls[1][1][1]['before'],'n1')
        self.assertEqual(rpc.calls[1][1][1]['limit'],64)

    def test_fallback_revealing_more_than_sixteen_still_fails_closed(self):
        first=[sig(f'a{i}',120-i,120-i) for i in range(10)]
        second=[sig(f'b{i}',110-i,110-i) for i in range(7)] + [sig('anchor',99,99)]
        rpc=_RPC(first,second)
        with self.assertRaisesRegex(Unavailable,'transaction_bound'):
            boundary.complete_signature_census(rpc,'pool',100,120)
        self.assertEqual(MAX_TRANSACTIONS,16)
        self.assertEqual(len(rpc.calls),2)

    def test_missing_boundary_after_single_fallback_remains_failure(self):
        first=[sig('n4',104,4),sig('n3',103,3)]
        second=[sig('n2',102,2),sig('n1',101,1)]
        rpc=_RPC(first,second)
        with self.assertRaisesRegex(Unavailable,'missing_start_boundary'):
            boundary.complete_signature_census(rpc,'pool',100,104)
        self.assertEqual(len(rpc.calls),2)

    def test_pagination_duplicate_is_not_silently_deduplicated(self):
        first=[sig('n2',102,2),sig('n1',101,1)]
        second=[sig('n1',101,1),sig('anchor',100,9)]
        rpc=_RPC(first,second)
        with self.assertRaisesRegex(Unavailable,'pagination_duplicate'):
            boundary.complete_signature_census(rpc,'pool',100,102)


if __name__=='__main__':unittest.main()
