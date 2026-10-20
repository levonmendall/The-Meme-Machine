"""Managed Pons fresh storage and actual native decoding with offline RPC only."""
from copy import deepcopy
from concurrent.futures import Future
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational.managed_native_pons import ManagedPonsLane, private_root

CAPTURE = Path(__file__).parent/'lanes/pons/fixtures/public_log_timestamp_35915320840.json'
ENDPOINT = 'https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_MANAGED_FIXTURE'
GENERATION = 'independent-test-generation'


class ManagedNativePonsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.base = Path(self.tmp); self.root = self.base/'pons'; self.root.mkdir(mode=0o700)
        self.capture = json.loads(CAPTURE.read_text())
        self.block = int(self.capture['header']['number'],16)
        self.head = self.block-1; self.calls = []; self.fail_receipt = False
        self.receipt_hook = None
        profile = json.loads((Path(__file__).parents[1]/
            'operational/pump-first-release/deployment/paper-continuous.four-regime.json').read_text())
        profile['maximum_cpu_cores'] = '1'
        self.profile = self.base/'profile.json'; self.profile.write_text(json.dumps(profile)); self.profile.chmod(0o600)
        self.env = dict(MM_ROBINHOOD_READ_RPC_URL=ENDPOINT,
            MM_ROBINHOOD_STATE_DIR=str(self.root),MM_PROVIDER_DB=str(self.root/'provider.sqlite'),
            MM_RPC_CACHE_DB=str(self.root/'evidence.sqlite'),MM_RUNTIME_LANE='pons',
            MM_PONS_OBSERVATION_ROUTE='canonical_primary',MM_PROVIDER_OPERATION_MODE='CONTINUOUS',
            MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.profile))
        self.enterContext(patch.dict(os.environ,self.env,clear=True))
        from meme_machine.lanes.pons.provider_topology import configured_discovery_rpc
        self.enterContext(patch('meme_machine.lanes.pons.provider_topology.configured_discovery_rpc',
            side_effect=lambda *a,**kw:configured_discovery_rpc(*a,**kw,transport=self.transport)))
        self.cancel = threading.Event()
        self.lane = ManagedPonsLane(self.root,GENERATION,cancel=self.cancel.is_set)
        self.addCleanup(self.cleanup_lane)

    def cleanup_lane(self):
        self.cancel.set(); self.lane.close()

    def header(self,n):
        row = deepcopy(self.capture['header'])
        if n != self.block:
            row.update(number=hex(n),hash='0x'+hashlib.sha256(str(n).encode()).hexdigest(),
                       timestamp=hex(int(row['timestamp'],16)+n-self.block))
        return row

    def transport(self,method,params):
        self.calls.append((method,deepcopy(params)))
        if method == 'eth_chainId': return '0x1237'
        if method == 'eth_getBlockByNumber':
            return self.header(self.head if params[0]=='latest' else int(params[0],16))
        if method == 'eth_getBlockByHash':
            self.assertEqual(params[0],self.capture['header']['hash'])
            return deepcopy(self.capture['header'])
        if method == 'eth_getLogs':
            q = params[0]
            return [deepcopy(self.capture['event'])] if (
                int(q['fromBlock'],16)<=self.block<=int(q['toBlock'],16)) else []
        if method == 'eth_getTransactionReceipt':
            if self.receipt_hook: self.receipt_hook()
            if self.fail_receipt:
                from meme_machine.lanes.pons import BoundaryError
                raise BoundaryError('provider_http_429')
            return deepcopy(self.capture['receipt'])
        raise AssertionError('unexpected offline method')

    def enroll(self):
        self.assertEqual(self.lane.sample_head(),self.block-1)
        self.head = self.block; self.lane.sample_head()

    def consume(self):
        with patch.object(self.lane,'poll_candidate'):
            return self.lane.consume(self.block,self.block)

    def test_managed_native_decode_same_block_units_canonical_history_and_durable_replay(self):
        self.enroll(); interval = self.consume(); result = self.lane.snapshot()
        self.assertEqual((result['incoming'],result['durable'],result['backlog']),(1,1,0))
        self.assertEqual(result['economic_events'],1)
        self.assertTrue(interval['complete'])
        self.assertTrue(result['scope']['managed_admission'])
        self.assertFalse(result['scope']['financial_entries'])
        curve = self.capture['event']['address'].lower()
        history = self.lane.history.get(curve)
        self.assertEqual(history['block'],self.block)
        self.assertEqual(history['authority'],'canonical_receipt_authenticated_complete_log_ranges')
        replay = self.lane.replay(); self.assertTrue(replay['verified'])
        self.assertEqual(replay['economic_events'],1)
        self.assertEqual(sum(m=='eth_getTransactionReceipt' for m,p in self.calls),1)
        self.assertNotIn('OFFLINE_MANAGED_FIXTURE',json.dumps(result))

    def test_incomplete_receipt_keeps_scout_evidence_without_advancing_durable_blocks(self):
        self.enroll(); self.fail_receipt = True
        with self.assertRaises(Exception): self.consume()
        self.assertEqual(self.lane.cursor,self.block-1)
        self.assertEqual(self.lane.snapshot()['durable'],0)
        self.assertEqual(self.lane.snapshot()['economic_events'],0)
        self.assertEqual(self.lane.plane.checkpoint_read('pons_scout_market_cursor'),self.block)
        self.fail_receipt = False; self.consume()
        self.assertEqual(self.lane.snapshot()['durable'],1)
        self.assertTrue(self.lane.replay()['verified'])

    def test_managed_receipt_pins_publish_exact_reusable_rpc_evidence(self):
        self.enroll(); self.consume()
        tx = self.capture['event']['transactionHash']; bh = self.capture['event']['blockHash']
        reuse = self.lane.rpc.evidence_reuse
        key = reuse.key('eth_getTransactionReceipt',[tx],receipts={tx:bh})
        self.assertIsNotNone(reuse.store.get(reuse.domain,key))
        before = len(self.calls)
        self.lane.rpc.evidence_receipts = {tx:bh}
        self.assertEqual(self.lane.rpc.call('eth_getTransactionReceipt',[tx],scope='pons_selective_window'),
                         self.capture['receipt'])
        self.assertEqual(len(self.calls),before)

    def test_partial_native_batch_is_rejected_before_zipping_evidence(self):
        with patch.object(self.lane.rpc,'batch',return_value=[]):
            with self.assertRaisesRegex(ValueError,'native_batch_shape'):
                self.lane.sample_head()

    def test_receipt_hash_pins_survive_native_session_rotation(self):
        tx = self.capture['event']['transactionHash']; bh = self.capture['event']['blockHash']
        self.lane.rpc.evidence_receipts = {tx:bh}; self.lane.rpc.used = 190
        self.lane._batch([('eth_getTransactionReceipt',[tx])],'pons_selective_window')
        self.assertEqual(self.lane.rpc.evidence_receipts,{tx:bh})
        reuse = self.lane.rpc.evidence_reuse
        key = reuse.key('eth_getTransactionReceipt',[tx],receipts={tx:bh})
        self.assertIsNotNone(reuse.store.get(reuse.domain,key))

    def test_restart_refuses_hardlinks_and_nonprivate_state(self):
        self.lane.close(); marker = self.root/'managed-pons.json'
        marker.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'private_file_permissions'):
            ManagedPonsLane(self.root,GENERATION)
        marker.chmod(0o600)
        os.link(marker,self.base/'marker-copy')
        with self.assertRaisesRegex(ValueError,'private_file_permissions'):
            ManagedPonsLane(self.root,GENERATION)

    def test_numeric_canonical_fence_disagreement_never_publishes_completion(self):
        self.enroll()
        original = self.header
        def fork(n):
            value = original(n)
            if n==self.block: value['hash']='0x'+'99'*32
            return value
        self.header = fork
        with self.assertRaisesRegex(ValueError,'canonical_membership'):
            self.consume()
        self.assertEqual(self.lane.snapshot()['durable'],0)
        self.assertEqual(self.lane.snapshot()['economic_events'],0)

    def test_restart_retains_exact_generation_cursor_corpus_and_candidate_deadline(self):
        self.enroll(); self.consume(); before = self.lane.replay()
        candidates = [tuple(r) for r in self.lane.plane.db.execute('SELECT id,observed,deadline FROM candidates')]
        self.lane.close(); self.lane = ManagedPonsLane(self.root,GENERATION,cancel=self.cancel.is_set)
        self.assertEqual(self.lane.replay(),before)
        self.assertEqual(self.lane.cursor,self.block)
        self.assertEqual([tuple(r) for r in self.lane.plane.db.execute('SELECT id,observed,deadline FROM candidates')],candidates)
        self.assertEqual(self.lane.snapshot()['incoming'],1)
        with self.assertRaisesRegex(ValueError,'generation_marker'):
            private_root(self.root,'unrelated-generation')

    def test_cancel_before_provider_request_preserves_pending_coverage(self):
        self.enroll(); before = len(self.calls); self.cancel.set()
        with self.assertRaises(InterruptedError): self.consume()
        self.assertEqual(len(self.calls),before)
        self.assertEqual(self.lane.cursor,self.block-1)

    def test_corpus_corruption_is_not_a_replay_pass(self):
        self.enroll(); self.consume()
        self.lane.plane.db.execute("UPDATE managed_raw SET hash='incorrect'")
        with self.assertRaisesRegex(ValueError,'replay_raw_digest'): self.lane.replay()

    def test_market_writer_continues_while_real_candidate_worker_is_in_flight(self):
        self.enroll(); started = threading.Event(); release = threading.Event()
        def evaluation(*args,**kwargs):
            started.set(); release.wait(2)
            return dict(vector=dict(current_threshold_pass=False))
        def receipt():
            self.assertTrue(started.wait(1),'candidate hydration was serialized behind receipt persistence')
            self.assertFalse(self.lane.future.done())
        self.receipt_hook = receipt
        with patch('meme_machine.lanes.pons.pons_selective_acquisition.evaluate_candidate',side_effect=evaluation):
            try:
                self.lane.consume(self.block,self.block)
                self.assertEqual(self.lane.cursor,self.block)
                self.assertFalse(self.lane.future.done())
            finally: release.set()
            self.lane.future.result(timeout=2); self.lane.poll_candidate(submit=False)
        self.assertEqual(self.lane.counts['candidate_completed'],1)

    def test_native_current_failure_keeps_bounded_cause_and_source_without_changing_outcome(self):
        from meme_machine.lanes.pons.pons_natural_observation import _two_uints
        self.enroll(); self.consume()
        work = self.lane.broker.pop()
        self.assertIsNotNone(work)
        try:
            _two_uints('0x')
        except Exception as error:
            self.lane.future = Future(); self.lane.future.set_exception(error)
        self.lane.future_work = work; self.lane.future_started = time.monotonic()
        self.lane.poll_candidate(submit=False)
        snapshot = self.lane.snapshot()
        self.assertEqual(snapshot['failures'], {'qualification:natural_reserve_shape': 1})
        self.assertEqual(snapshot['candidate_outcomes'], {'authoritative_evidence_failure': 1})
        self.assertEqual(snapshot['failure_examples'], [dict(stage='qualification', count=1,
            reason_code='natural_reserve_shape', origin=dict(
                module='meme_machine.lanes.pons.pons_natural_observation',
                function='_two_uints', line=_two_uints.__code__.co_firstlineno + 3))])
        self.assertEqual(self.lane.counts['candidate_completed'], 0)
        row = self.lane.plane.get(work['key'])
        self.assertEqual(row['reason'], 'natural_reserve_shape')
        self.assertEqual(snapshot['durable_blocks'], 1)
        self.assertTrue(self.lane.replay()['verified'])

    def settle_candidate_error(self, work, error):
        self.lane.future = Future(); self.lane.future.set_exception(error)
        self.lane.future_work = work; self.lane.future_started = time.monotonic()
        self.lane.poll_candidate(submit=False)

    def claim_candidate(self, *, canonical_refresh=False):
        observed = time.time()
        self.lane.broker.clock = self.lane.plane.clock = lambda:observed
        self.lane.broker.enqueue(self.capture['event'], canonical_refresh=canonical_refresh)
        work = self.lane.broker.pop()
        self.assertIsNotNone(work)
        self.assertEqual(work['canonical_refresh'], canonical_refresh)
        return work

    def test_authenticated_horizon_retires_native_watch_and_survives_restart_without_completion(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS
        work = self.claim_candidate(canonical_refresh=True)
        curve = work['event']['address']; head = self.header(self.block+10)
        now = time.time(); head['timestamp'] = hex(int(now))
        launch = int(now)-ENTRY_THRESHOLDS['max_token_age_seconds']-1
        # Synthetic authenticated identity, as in the native recheck fixtures.
        # The real refreshed_current_candidate/evaluate_candidate boundary and
        # native Broker/Plane retirement execute; all transport seams are offline.
        self.lane.cache.remember_compiled(curve,'0x'+'11'*20,'0x6000',self.block,
            self.capture['header'],dict(runtime_sha256='offline_authenticated_identity'))
        self.lane.cache.remember_launch(curve,launch)
        ctx = self.lane.context
        with patch.object(acquisition.time,'time',return_value=now), \
                patch.object(acquisition.time,'monotonic',return_value=100.), \
                patch.object(ctx,'acquire',return_value=SimpleNamespace(telemetry=lambda:{})), \
                patch.object(ctx,'call',return_value=head),patch.object(ctx,'batch',return_value=[head]):
            try:
                acquisition.evaluate_candidate(self.lane.endpoint,work['event'],[],
                    strategy_capital_quote=10**18,evidence_context=ctx,canonical_refresh=True,
                    evidence_observed_at=now,evidence_observed_monotonic=100.)
            except BoundaryError as error:
                self.assertEqual(str(error),'strategy_horizon_expired')
                caught = error
            else:
                self.fail('native frozen horizon did not reject the old curve')
        proof = deepcopy(ctx.boundary_evidence)
        self.assertEqual((proof['launch_at'],proof['asof']),(launch,int(now)))
        self.settle_candidate_error(work,caught)
        snapshot = self.lane.snapshot(); row = self.lane.plane.get(work['key'])
        self.assertEqual((row['state'],row['reason']),('strategy_rejected','strategy_horizon_expired'))
        self.assertEqual(snapshot['candidate_outcomes'],{'strategy_rejected':1})
        self.assertEqual(snapshot['failures'],{})
        self.assertEqual(self.lane.counts['candidate_completed'],0)
        self.assertEqual(self.lane.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch').fetchone()[0],0)
        details = json.loads(self.lane.plane.db.execute(
            "SELECT details FROM transitions WHERE kind='strategy_rejected' ORDER BY seq DESC LIMIT 1").fetchone()[0])
        self.assertEqual(details['authenticated_evidence'],proof)
        self.lane.close(); self.lane = ManagedPonsLane(self.root,GENERATION,cancel=self.cancel.is_set)
        self.assertIsNone(self.lane.broker.pop())
        self.assertEqual(self.lane.plane.get(work['key'])['state'],'strategy_rejected')
        self.assertEqual(self.lane.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch').fetchone()[0],0)

    def test_horizon_boundary_without_proof_does_not_retire_watch_or_count_strategy_rejection(self):
        from meme_machine.lanes.pons import BoundaryError
        work = self.claim_candidate(canonical_refresh=True)
        self.lane.context.boundary_evidence = None
        self.settle_candidate_error(work,BoundaryError('strategy_horizon_expired'))
        snapshot = self.lane.snapshot()
        self.assertEqual(snapshot['candidate_outcomes'],{'authoritative_evidence_failure':1})
        self.assertEqual(snapshot['failures'],{'qualification:strategy_horizon_expired':1})
        self.assertEqual(self.lane.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch').fetchone()[0],1)
        self.assertEqual(self.lane.counts['candidate_completed'],0)

    def test_horizon_proof_cannot_retire_an_unrechecked_nomination(self):
        from meme_machine.lanes.pons import BoundaryError
        work = self.claim_candidate()
        self.lane.context.boundary_evidence = dict(boundary='strategy_horizon_expired',
            authentication_complete=True,identity={'runtime_sha256':'offline'},
            curve=work['event']['address'],launch_at=1,asof=1_000_000)
        self.settle_candidate_error(work,BoundaryError('strategy_horizon_expired'))
        snapshot = self.lane.snapshot()
        self.assertEqual(snapshot['candidate_outcomes'],{'authoritative_evidence_failure':1})
        self.assertEqual(snapshot['failures'],{'qualification:strategy_horizon_expired':1})
        self.assertEqual(self.lane.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch').fetchone()[0],1)
        self.assertEqual(self.lane.counts['candidate_completed'],0)

    def test_native_supersession_preserves_new_pending_generation_without_provider_failure(self):
        from meme_machine.lanes.pons import BoundaryError
        work = self.claim_candidate()
        newer = deepcopy(self.capture['event'])
        newer.update(blockNumber=hex(self.block+1),blockHash=self.header(self.block+1)['hash'],
            transactionHash='0x'+hashlib.sha256(b'newer-native-buy').hexdigest())
        self.lane.broker.enqueue(newer)
        before = self.lane.plane.get(work['key']); calls = len(self.calls)
        self.lane.context.generation_guard = lambda:self.lane.plane.current(work['work'])
        try:
            self.lane.context.batch([('eth_chainId',[])],'pons_natural')
        except BoundaryError as error:
            self.assertEqual(str(error),'candidate_generation_superseded')
            caught = error
        else:
            self.fail('superseded native work reached provider acquisition')
        self.settle_candidate_error(work,caught)
        after = self.lane.plane.get(work['key'])
        self.assertEqual({k:after[k] for k in ('generation','payload','state','pending')},
            {k:before[k] for k in ('generation','payload','state','pending')})
        self.assertGreater(after['generation'],work['work']['generation'])
        self.assertEqual(after['pending'],1); self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.lane.snapshot()['candidate_outcomes'],{'superseded':1})
        self.assertEqual(self.lane.snapshot()['failures'],{})
        self.assertEqual(self.lane.counts['candidate_superseded'],1)
        self.assertEqual(self.lane.counts['candidate_completed'],0)

    def test_authenticated_non_native_screen_keeps_native_proof_and_never_claims_qualification(self):
        from meme_machine.lanes.pons import BoundaryError
        proof = json.loads((Path(__file__).parent/
            'fixtures/robinhood/run369-pons-accounting.json').read_text())['deferrals'][1]['immutable_proof']
        work = self.claim_candidate()
        proof = dict(proof,curve=work['event']['address'])
        self.lane.context.boundary_evidence = proof
        self.settle_candidate_error(work,BoundaryError('natural_non_native_quote_not_supported'))
        snapshot = self.lane.snapshot(); row = self.lane.plane.get(work['key'])
        self.assertEqual(row['state'],'structural_excluded')
        self.assertEqual(snapshot['candidate_outcomes'],{'structural_excluded':1})
        self.assertEqual(snapshot['failures'],{})
        self.assertEqual(self.lane.counts['candidate_completed'],0)
        self.assertEqual(self.lane.counts['candidate_qualified'],0)
        details = json.loads(self.lane.plane.db.execute(
            "SELECT details FROM transitions WHERE kind='structural_excluded' ORDER BY seq DESC LIMIT 1").fetchone()[0])
        self.assertEqual(details['authenticated_evidence'],proof)

    def test_unproven_boundary_and_genuine_provider_capacity_remain_failures(self):
        from meme_machine.lanes.pons import BoundaryError
        work = self.claim_candidate()
        self.lane.context.boundary_evidence = dict(boundary='natural_non_native_quote_not_supported',
            authentication_complete=False,pair_token='0x'+'44'*20,decision_age_seconds=0)
        self.settle_candidate_error(work,BoundaryError('natural_non_native_quote_not_supported'))
        self.assertEqual(self.lane.plane.get(work['key'])['state'],'authoritative_evidence_failure')
        self.assertEqual(self.lane.snapshot()['failures'],
            {'qualification:natural_non_native_quote_not_supported':1})
        # A new real nomination gives a new attempt; the old proof is never
        # enough to turn a genuine provider 429 into a structural exclusion.
        newer = deepcopy(self.capture['event']); newer['transactionHash']='0x'+'ab'*32
        newer['logIndex']=hex(int(newer['logIndex'],16)+1)
        self.lane.broker.enqueue(newer); work = self.lane.broker.pop()
        self.assertIsNotNone(work)
        self.settle_candidate_error(work,BoundaryError('provider_http_429'))
        self.assertEqual(self.lane.plane.get(work['key'])['state'],'provider_capacity_defer')
        self.assertEqual(self.lane.snapshot()['failures'],
            {'qualification:natural_non_native_quote_not_supported':1,'qualification:provider_http_429':1})
        self.assertEqual(self.lane.snapshot()['candidate_outcomes'],
            {'authoritative_evidence_failure':1,'provider_capacity_defer':1})
        self.assertEqual(self.lane.counts['candidate_completed'],0)

    def test_failure_examples_never_emit_untrusted_exception_text_and_remain_bounded(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.operational.managed_native_pons import MAX_FAILURE_EXAMPLES
        self.lane.record_failure_example('qualification', BoundaryError(ENDPOINT))
        self.lane.record_failure_example('qualification', ValueError('natural_reserve_shape'))
        self.lane.record_failure_example('qualification', BoundaryError('natural_reserve_shape', ENDPOINT))
        snapshot = self.lane.snapshot()
        self.assertEqual(snapshot['failure_examples'], [dict(stage='qualification', count=3,
            reason_code='unclassified_native_failure', origin={})])
        self.assertNotIn(ENDPOINT, json.dumps(snapshot))
        self.assertNotIn('OFFLINE_MANAGED_FIXTURE', json.dumps(snapshot))
        for reason in ('stale_evidence_acquisition', 'candidate_generation_superseded',
                'natural_non_native_quote_not_supported', 'curve_runtime_length',
                'selective_evidence_batch_incomplete', 'trajectory_history_incomplete',
                'natural_reserve_shape', 'sample_gas_units_bounds', 'sample_invalid_gas_price'):
            self.lane.record_failure_example('qualification', BoundaryError(reason))
        snapshot = self.lane.snapshot()
        self.assertEqual(len(snapshot['failure_examples']), MAX_FAILURE_EXAMPLES)
        self.assertEqual(snapshot['failure_examples_dropped'], 2)
        self.lane.record_failure_example('qualification', BoundaryError('stale_evidence_acquisition'))
        self.assertEqual(self.lane.snapshot()['failure_examples'][1]['count'], 2)

    def test_foreign_state_and_financial_environment_are_rejected_before_provider_work(self):
        self.lane.close(); before = len(self.calls)
        with patch.dict(os.environ,dict(MM_SHARED_CAPITAL_DB='/original/financial.sqlite')):
            with self.assertRaisesRegex(ValueError,'inherited_authority_environment'):
                ManagedPonsLane(self.root,GENERATION)
        self.assertEqual(len(self.calls),before)
        (self.root/'foreign.sqlite').touch()
        with self.assertRaisesRegex(ValueError,'foreign_state'):
            ManagedPonsLane(self.root,GENERATION)

    def test_original_sibling_financial_and_unknown_recovery_records_remain_unchanged(self):
        original = self.base/'original'; original.mkdir()
        rows = dict(epoch='1000',historical_epoch='500',producer_terminal='UNAUTHENTICATED',
                    handlers=['UNKNOWN','UNKNOWN'])
        journal = original/'financial-and-recovery.json'; journal.write_text(json.dumps(rows))
        before = hashlib.sha256(journal.read_bytes()).hexdigest()
        self.enroll(); self.consume(); self.lane.replay()
        self.assertEqual(hashlib.sha256(journal.read_bytes()).hexdigest(),before)
        self.assertEqual(set(p.name for p in original.iterdir()),{'financial-and-recovery.json'})

    def test_original_provider_protection_priority_and_absolute_deadline_without_financial_entries(self):
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.lanes.pons.provider_admission import Admission, position_work
        # An ordinary discovery ticket is already waiting. The real governor
        # still admits protected reads first under the unchanged profile pace.
        clock = [100.0]; starts = []
        def sleep(seconds): clock[0] += seconds
        governor = Admission(self.base/'protection-simulation.sqlite',ENDPOINT,lane='pons',
                             clock=lambda:clock[0],sleeper=sleep)
        db = governor.connect()
        try:
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('discovery',governor.endpoint,50,100.,110.))
            db.execute('INSERT INTO queue_meta VALUES(?,?)',('discovery','pons'))
        finally: db.close()
        def transport():
            starts.append(clock[0]); clock[0] += .1
            return 'offline-protection-read'
        @position_work
        def protected():
            for _ in range(6):
                self.assertEqual(governor.invoke(transport,['eth_call'],'pons_protective_simulation',
                    deadline=103.),'offline-protection-read')
        protected()
        self.assertLess(clock[0],103.)
        self.assertTrue(all(b-a>=governor.interval-1e-8 for a,b in zip(starts,starts[1:])))
        db = governor.connect()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue WHERE id='discovery'").fetchone()[0],1)
            rows = [json.loads(r[0]) for r in db.execute('SELECT body FROM admissions')]
            self.assertEqual([r['priority'] for r in rows],[0]*6)
            self.assertTrue(all(r['deadline']<=103. for r in rows))
        finally: db.close()
        with self.assertRaisesRegex(BoundaryError,'admission_deadline'):
            position_work(lambda:governor.invoke(transport,['eth_call'],'pons_protective_simulation',
                                                 deadline=clock[0]))()
        self.assertEqual(len(starts),6)

    def test_external_stop_during_real_receipt_finishes_only_the_admitted_range(self):
        from meme_machine.operational.managed_native_pons import run_pons
        external=threading.Event();self.enroll()
        self.receipt_hook=external.set
        from meme_machine.operational.bounded_provider import Budget
        usage=self.base/'provider-usage.sqlite'
        Budget.create(usage,continuous=json.loads(self.profile.read_text()))
        def bind(*args,**kwargs):
            self.lane.cancel=kwargs['cancel']
            return self.lane
        def finish(**kwargs):
            self.lane.survivor_replay=dict(verified=True,events=0)
            self.lane.survivor_pool.shutdown(wait=True,cancel_futures=True)
            if kwargs.get('drain_callback') is not None:kwargs['drain_callback']()
            return self.lane.survivor_replay
        with patch.dict(os.environ,dict(MM_PROVIDER_USAGE_DB=str(usage))), \
                patch('meme_machine.operational.bounded_provider.install'), \
                patch('meme_machine.operational.managed_native_pons.ManagedPonsLane',side_effect=bind), \
                patch.object(self.lane,'poll_candidate'),patch.object(self.lane,'poll_survivor'), \
                patch.object(self.lane,'finish_survivor',side_effect=finish):
            result=run_pons(self.root,60,GENERATION,cancel=external.is_set)
        self.assertTrue(external.is_set())
        self.assertIsNone(result['error'])
        self.assertEqual((result['incoming_blocks'],result['durable_blocks'],result['backlog']),(1,1,0))
        self.assertTrue(result['replay']['verified'])
        self.assertEqual(result['durable_ranges'],1)
