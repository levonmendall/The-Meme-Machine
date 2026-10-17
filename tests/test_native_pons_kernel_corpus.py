"""Synthetic wire shapes pass unchanged native preparation, never a market proof."""
from collections import Counter
from pathlib import Path
import tempfile
import unittest

from meme_machine.lanes.pons.identity import metadata
from meme_machine.lanes.pons.pons_historical import Preparation,FORWARD_PLAN
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.operational.isolated_native_pons_kernel_corpus import (
    PonsKernelCorpus,PonsKernelFixtureRefused)


class _NativeWireRPC:
    """Local wire dispatcher; this has no socket/HTTP or allocation capability."""
    canonical_authority=True
    chain_verified=True
    provider_fingerprint='synthetic-kernel-pons-wire-not-mainnet'
    limit=200
    def __init__(self,corpus):
        self.corpus=corpus;self.used=0;self.methods=Counter()
    def batch(self,calls,*,scope):
        self.used+=len(calls)
        self.methods.update(method for method,_ in calls)
        return [self.corpus.rpc(method,params) for method,params in calls]
    def call(self,method,params,*,scope):return self.batch([(method,params)],scope=scope)[0]
    def telemetry(self):return dict(requests=self.used,physical_http_requests=0,transport_requests=0)


class NativePonsKernelCorpusTests(unittest.TestCase):
    def test_actual_forward_preparation_authenticates_all_four_deployments_and_checkpoint(self):
        corpus=PonsKernelCorpus(1792277501);rpc=_NativeWireRPC(corpus)
        with tempfile.TemporaryDirectory() as temporary:
            history=PonsHistory(str(Path(temporary)/'history.sqlite'),policy=POLICY_HASH)
            try:
                preparation=Preparation(history,lambda:rpc,forward_only=True,clock=lambda:corpus.started_at)
                plan=preparation.begin(enrollment_block=200)
                self.assertEqual(plan,history.get_meta(FORWARD_PLAN))
                self.assertEqual(len(plan['deployments']),4)
                self.assertEqual(plan['target'],corpus.header(200))
                self.assertEqual(plan['genesis_hash'],corpus.header(0)['hash'])
                self.assertEqual(plan['target']['parentHash'],corpus.header(199)['hash'])
                self.assertEqual(rpc.methods['eth_getCode'],4)
                preparation.discover_step()
                self.assertEqual(history.rows(),[])
                tables={row[0] for row in history.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertFalse(tables & {'genesis','positions','journal','capital_genesis',
                    'portfolio_events','shared_capital_events','shared_capital_projection'})
                self.assertEqual(corpus.counters()['economic_candidates'],'UNEXERCISED')
            finally:history.close()

    def test_previous_missing_deployer_is_not_silently_removed_from_native_batch(self):
        corpus=PonsKernelCorpus(1792277501)
        del corpus.codes[metadata('pons_deployer')['address'].lower()]
        rpc=_NativeWireRPC(corpus)
        with tempfile.TemporaryDirectory() as temporary:
            history=PonsHistory(str(Path(temporary)/'history.sqlite'),policy=POLICY_HASH)
            try:
                with self.assertRaisesRegex(PonsKernelFixtureRefused,'pons_method'):
                    Preparation(history,lambda:rpc,forward_only=True).begin()
                self.assertIsNone(history.get_meta(FORWARD_PLAN))
            finally:history.close()

    def test_original_native_header_parser_rejects_missing_parent_hash(self):
        corpus=PonsKernelCorpus(1792277501);rpc=_NativeWireRPC(corpus)
        header=corpus.header
        def missing_parent(number):
            value=header(number);value.pop('parentHash');return value
        corpus.header=missing_parent
        with tempfile.TemporaryDirectory() as temporary:
            history=PonsHistory(str(Path(temporary)/'history.sqlite'),policy=POLICY_HASH)
            try:
                with self.assertRaisesRegex(Exception,'historical_chain_identity|historical_header_identity'):
                    Preparation(history,lambda:rpc,forward_only=True).begin()
                self.assertIsNone(history.get_meta(FORWARD_PLAN))
            finally:history.close()

    def test_unknown_methods_and_out_of_range_headers_refuse(self):
        corpus=PonsKernelCorpus(1792277501)
        for method,params in (('eth_sendRawTransaction',['0x00']),
                ('eth_getTransactionReceipt',['0x'+'11'*32]),
                ('eth_getBlockByNumber',['0xc9',False])):
            with self.subTest(method=method),self.assertRaises(PonsKernelFixtureRefused):
                corpus.rpc(method,params)


if __name__=='__main__':unittest.main()
