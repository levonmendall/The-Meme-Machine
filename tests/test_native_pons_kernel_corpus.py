"""Synthetic wire shapes pass unchanged native preparation, never a market proof."""
from collections import Counter
import json
from pathlib import Path
import tempfile
import time
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
        self.corpus=corpus;self.used=0;self.methods=Counter();self.counts=Counter();self.per_scope=200
    def batch(self,calls,*,scope):
        self.used+=len(calls)
        self.counts[scope]+=len(calls)
        self.methods.update(method for method,_ in calls)
        return [self.corpus.rpc(method,params) for method,params in calls]
    def call(self,method,params,*,scope):return self.batch([(method,params)],scope=scope)[0]
    def receipt(self,tx,block_hash,*,scope):
        value=self.call('eth_getTransactionReceipt',[tx],scope=scope)
        if value['blockHash']!=block_hash:raise ValueError('synthetic_receipt_block_mismatch')
        return value
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

    def test_actual_current_decode_trajectory_window_and_history_publish_with_zero_sizing(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext,evaluate_candidate
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_HASH
        from meme_machine.runtime.robinhood.pons import Broker,durable_cache,shared_evidence_domain
        from meme_machine.lanes.pons.pons_natural_observation import MarketScout
        corpus=PonsKernelCorpus(int(time.time())-1,economic=True);rpc=_NativeWireRPC(corpus)
        endpoint='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_KERNEL_NO_CREDENTIAL'
        with tempfile.TemporaryDirectory() as temporary:
            broker=Broker(Path(temporary)/'pons.sqlite',CURRENT_HASH,source=endpoint)
            try:
                scout=MarketScout(broker.plane)
                found=scout.read_market(rpc,corpus.current_block,corpus.current_block,
                    nominate=lambda event,observed:broker.enqueue(event,now=observed,needs_work=True))
                self.assertEqual(len(found),1)
                context=SelectiveEvidenceContext(endpoint,cache=durable_cache(broker.plane,shared_evidence_domain(endpoint)))
                context.rpc=rpc
                result=evaluate_candidate(endpoint,found[0],found,strategy_capital_quote=0,
                    evidence_observed_at=time.time(),evidence_observed_monotonic=time.monotonic(),
                    evidence_context=context)
                self.assertFalse(result.get('screened_out',False),result.get('prospect_preflight'))
                self.assertEqual(len(result['market_events']),9)
                self.assertEqual({e['side'] for e in result['market_events']},{'buy','sell'})
                self.assertEqual(result['candidate']['decoded_event']['decoded']['name'],'CurveBuy')
                self.assertTrue(result['window_coverage']['complete'])
                retained=CurrentHistory(broker.plane,endpoint).get(corpus.current_curve)
                self.assertIsNotNone(retained)
                self.assertFalse(result['vector']['current_threshold_pass'])
                self.assertEqual(result['vector']['proposed_size']['amount_quote'],0)
                self.assertEqual(broker.plane.db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],1)
                self.assertEqual(broker.plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0],9)
                self.assertEqual(corpus.refused,0)
            finally:broker.close()

    def test_actual_scout_graduation_preparation_and_swap_decoder_publish_native_survivor_history(self):
        from meme_machine.lanes.pons.pons_natural_observation import MarketScout
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        from meme_machine.runtime.robinhood.plane import Plane
        corpus=PonsKernelCorpus(int(time.time())-1,economic=True);rpc=_NativeWireRPC(corpus)
        with tempfile.TemporaryDirectory() as temporary:
            plane=Plane(Path(temporary)/'pons.sqlite');history=PonsHistory(str(Path(temporary)/'history.sqlite'),policy=POLICY_HASH)
            try:
                scout=MarketScout(plane)
                scout.read_market(rpc,corpus.current_block,corpus.current_block)
                history.retain_graduations([e for _,e,_ in scout.events('graduation')],corpus.current_block)
                def provider():rpc.used=0;rpc.counts.clear();return rpc
                preparation=Preparation(history,provider,forward_only=True,observations=scout,clock=time.time)
                preparation.begin(enrollment_block=corpus.current_block)
                self.assertTrue(preparation.authenticate_step())
                row=history.get(corpus.survivor_token);self.assertIsNotNone(row)
                self.assertEqual(row['graduation']['transition']['market'],corpus.pool_id)
                corpus.publish(3)
                preparation.extend(corpus.header(corpus.top))
                # This is the actual native History append reducer, without a
                # fake Runtime/book or funding path; history_step requires its
                # exact history owner and invokes this bound original method.
                class NativeHistoryOwner:
                    _append_tape=Runtime._append_tape
                owner=NativeHistoryOwner();owner.history=history
                self.assertTrue(preparation.history_step(owner,corpus.survivor_token))
                points,events=history.facts(corpus.survivor_token,int(time.time()))
                self.assertEqual(len(events),1)
                self.assertTrue(events[0]['authenticated'])
                self.assertGreater(events[0]['quote'],0)
                self.assertGreater(len(points),1)
                self.assertEqual(history.get(corpus.survivor_token)['block'],corpus.top)
                self.assertEqual(corpus.refused,0)
            finally:history.close();plane.close()

    def test_native_economic_decoder_still_rejects_premature_synthetic_future_head(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons.pons import raw_event
        corpus=PonsKernelCorpus(int(time.time()),economic=True)
        corpus.publish(3)
        event=next(e for e in corpus.logs if int(e['blockNumber'],16)==corpus.top)
        receipt=corpus.rpc('eth_getTransactionReceipt',[event['transactionHash']])
        with self.assertRaisesRegex(BoundaryError,'future_event'):
            raw_event(metadata('uniswap_v4_manager')['abi'],event,address=event['address'],
                receipt=receipt,header=corpus.header(corpus.top),
                observed_at=corpus.started_at,confirmation='confirmed')

    def test_synthetic_raw_receipt_disagreement_still_fails_original_decoder(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons.pons import raw_event,curve_abi
        corpus=PonsKernelCorpus(int(time.time()),economic=True)
        event=next(e for e in corpus.logs if e['address']==corpus.current_curve)
        receipt=corpus.rpc('eth_getTransactionReceipt',[event['transactionHash']])
        receipt['logs']=[]
        with self.assertRaisesRegex(BoundaryError,'raw_event_identity_disagreement'):
            raw_event(curve_abi(),event,address=event['address'],receipt=receipt,
                header=corpus.header(int(event['blockNumber'],16)),
                observed_at=corpus.started_at,confirmation='confirmed')


class NativePonsNitroWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_nitro_frame_and_rpc_headers_share_one_bounded_immutable_chain(self):
        corpus=PonsKernelCorpus(int(time.time()))
        stream=await corpus.open()
        try:
            first=None
            for _ in range(3):
                _,raw=await stream.read()
                message=json.loads(raw)['messages'][0]['message']['message']['header']
                number=message['blockNumber'];header=corpus.rpc('eth_getBlockByNumber',[hex(number),False])
                self.assertEqual(message['timestamp'],int(header['timestamp'],16))
                self.assertEqual(int(corpus.rpc('eth_blockNumber',[]),16),number)
                self.assertEqual(corpus.rpc('eth_getBlockByNumber',['latest',False]),header)
                if first is None:first=header
            self.assertEqual(number,201)
            self.assertEqual(corpus.header(200),first)
            self.assertEqual(header['parentHash'],first['hash'])
            with self.assertRaises(PonsKernelFixtureRefused):corpus.header(number+1)
        finally:await stream.aclose()
        self.assertTrue(stream.closed)

    async def test_reopened_stream_retains_same_head_and_sequence_without_timestamp_rewrite(self):
        corpus=PonsKernelCorpus(int(time.time()))
        first=await corpus.open()
        try:
            _,raw=await first.read()
            initial=json.loads(raw)['messages'][0]
        finally:await first.aclose()
        initial_header=corpus.header(200)
        second=await corpus.open()
        try:
            _,raw=await second.read()
            later=json.loads(raw)['messages'][0]
            self.assertGreater(later['sequenceNumber'],initial['sequenceNumber'])
            self.assertEqual(corpus.header(200),initial_header)
        finally:await second.aclose()
        self.assertEqual(corpus.counters()['streams_closed'],2)


if __name__=='__main__':unittest.main()
