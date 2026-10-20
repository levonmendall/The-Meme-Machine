"""Managed Pons fresh storage and actual native decoding with offline RPC only."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
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
