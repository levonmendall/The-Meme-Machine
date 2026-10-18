"""Original native writer/failed-tail inputs; no recovered or ready fixtures.

Private acquisition/root ownership are explicit premises of the unit fixtures;
the actual anonymous/kernel issuance is exercised by test_normal_source_boot.
Real SQLite transactions, canonical ingestion and HandlerLedger/gap checks run.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_source_boot as boot
from meme_machine.operational import normal_source_registry as registry
from meme_machine.operational.normal_boot_record import canonical,digest,NormalBootUnavailable
from meme_machine.runtime.native_restore_context import StoppedNativeReadContext
from meme_machine.solana_selective_history import economic_records,PROGRAMS
from meme_machine.solana_selective_source import install,commit_scout_batch,scout_fact,SelectiveSource
from meme_machine.solana_source_drain import HandlerLedger,preserve_handlers
from meme_machine.solana_rolling_history import program_scope
from tests import test_normal_source_boot as source_fixtures
from tests.test_solana_closure import NOW
from tests.test_solana_selective_evidence import FIXTURE
from tests.test_scout_commit_batches import update


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=source_fixtures.SourceCurrentCensusTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.state=self.fixture.state;self.db=self.state.writer.db;self.cap=self.fixture.cap
        self.history=install(self.state);self.history.clock=lambda:NOW
        self.history.lifecycle.clock=lambda:NOW;self.state.writer.clock=lambda:NOW
        self.cap.begin(self.state,self.fixture.census())
        self.registry=registry.NativeSourceRegistry(self.state,self.cap)
        self.cap._registry=self.registry;self.history._normal_source_registry=self.registry
        self.root=self.fixture.root;self.boundary=True

    def value(self):return self.registry._generation(self.state)

    def opened(self,*,stream='1'*32,session='2'*32,plane='rolling',transport='websocket',
            scopes=None,lower=100):
        self.registry.open(self.state,stream=stream,session=session,plane=plane,
            transport=transport,scopes=scopes or [program_scope('pumpswap')],
            lower_slot=lower,filter_sha256='a'*64)
        return stream,session

    def context(self):
        db=sqlite3.connect(self.state.writer.path.as_uri()+'?mode=ro',uri=True,isolation_level=None)
        self.addCleanup(db.close);db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        return StoppedNativeReadContext(self.root,{self.state.writer.path:db},
            validate_snapshot=lambda:self.boundary,deadline=time.monotonic()+10),db

    def plan(self,context=None):
        context=context or self.context()[0]
        # Root-protected historical provenance/dead owner is a separate fixture
        # premise, never an assertion derived from a mutable JSON checksum.
        with patch.object(boot,'_authenticate_prior_provenance') as authenticated:
            result=registry.derive_failed_generation_plan(context)
        authenticated.assert_called_once()
        return result

    def failed_tail(self,*,terminal=True):
        stream,session=self.opened();self.registry.stopped(self.state,stream)
        ledger=HandlerLedger(self.cap.generation)
        async def fail():
            number=ledger.accept(stream,session,'websocket','candidate_logs','log_or_ack',NOW,
                slot=123,identity='retained-native-signature',scopes=[program_scope('pumpswap')])
            ledger.phase('LOG_BUFFER_WAIT');ledger.fail(number,ValueError('not persisted provider text'))
        asyncio.run(fail())
        with self.state.writer.transaction():
            self.history.gap(program_scope('pumpswap'),100,None,'candidate_live_disconnect_or_filter_rebuild')
            gap=self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
            retained=preserve_handlers(self.state,ledger,ledger.pending(session),
                dict(kind='CANDIDATE_GAPS',gap_ids=[gap]))
            ledger.preserved(retained)
            # The unchanged native join's empty frontier is below the callback
            # that failed before feed_log: only the actual handler retains123.
            from meme_machine.solana_candidate_join import CandidateTransactionJoin
            join=CandidateTransactionJoin({},set(),filtered_from_slot=100,clock=lambda:NOW)
            self.history._observation(None,'source_session_drain',dict(plane='rolling',session=session,
                **join.diagnostic(),replay_from_slot=100,handler_dispositions=retained,
                complete_history_claim=False))
            observation=self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
            self.registry.closed(self.state,session,observation)
        if terminal:
            body=self.fixture.census(terminal=True)
            body.update(state='RECOVERY_REQUIRED',accepted_handlers=1,settled_handlers=0,pending_handlers=1,
                handler_accounting=ledger.snapshot(),closed_sessions=1)
            self.cap.publish(self.state,body)
        return stream,session,gap

    def test_private_owner_restart_and_no_unowned_dictionary_can_issue_registry(self):
        with self.assertRaisesRegex(NormalBootUnavailable,'capability_required'):
            registry.NativeSourceRegistry(self.state,{})
        before=self.value()
        with self.assertRaisesRegex(NormalBootUnavailable,'generation_exists'):
            registry.NativeSourceRegistry(self.state,self.cap)
        self.assertEqual(self.value(),before)
        errors=[]
        def foreign():
            try:self.registry.open(self.state,stream='3'*32,session='4'*32,plane='rolling',
                transport='websocket',scopes=['program:pump'],lower_slot=1,filter_sha256='a'*64)
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=foreign);worker.start();worker.join(1)
        self.assertFalse(worker.is_alive());self.assertEqual(len(errors),1)
        self.assertIn('source_generation_owner',str(errors[0]))

    def test_genuine_initial_zero_frontier_is_atomic_bounded_and_not_missing(self):
        raw=self.db.execute("SELECT value FROM service_health WHERE key='source_generation_frontier'").fetchone()[0]
        value=registry.validate_publication_frontier(raw)
        self.assertEqual(value['identity_sha256'],self.cap.identity_sha256)
        self.assertEqual(value['generation'],self.cap.generation)
        self.assertEqual(value['initial_program_outbox_sequence'],
            self.value()['initial_frontiers']['program_outbox_sequence'])
        self.assertEqual(value['economic']['all']['records'],0)
        detached=registry.validate_publication_frontier(value)
        detached['economic']['all']['records']=9
        self.assertEqual(json.loads(raw)['economic']['all']['records'],0)
        for bad in (None,{},dict(value,extra=False),'x'*(registry.MAX_BODY+1)):
            with self.subTest(type=type(bad)),self.assertRaises(NormalBootUnavailable):
                registry.validate_publication_frontier(bad)
        crossed=deepcopy(value)
        crossed['economic']['all']=dict(records=1,batches=1,first_sequence=5,last_sequence=5,prefix_sha256='b'*64)
        crossed['economic']['programs']['program:pump']=deepcopy(crossed['economic']['all'])
        crossed['initial_program_outbox_sequence']['program:pump']=5
        with self.assertRaisesRegex(NormalBootUnavailable,'public_cut_crossed'):
            registry.validate_publication_frontier(crossed)

    def test_initial_frontier_failure_rolls_back_its_actual_generation_row(self):
        original=source_fixtures.SourceCurrentCensusTests();original.setUp()
        self.addCleanup(original.doCleanups);install(original.state)
        original.cap.begin(original.state,original.census())
        real=original.state.fence._health
        def failed(key,value):
            real(key,value)
            if key=='source_generation_frontier':raise RuntimeError('initial_frontier_failure')
        with patch.object(original.state.fence,'_health',side_effect=failed):
            with self.assertRaisesRegex(RuntimeError,'initial_frontier_failure'):
                registry.NativeSourceRegistry(original.state,original.cap)
        db=original.state.writer.db
        self.assertIsNone(db.execute("SELECT value FROM service_health WHERE key='source_generation_frontier'").fetchone())
        self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name=?",(registry.GENERATION_TABLE,)).fetchone())

    def test_original_batch_commit_and_rollback_share_one_full_transaction(self):
        self.opened(plane='scout',scopes=['scout:pump'])
        statements=[];self.db.set_trace_callback(statements.append)
        commit_scout_batch(self.state,[scout_fact(update(n),NOW) for n in range(1,9)],registry=self.registry)
        self.db.set_trace_callback(None)
        self.assertEqual(sum(sql=='COMMIT' for sql in statements),1)
        self.assertEqual(self.db.execute('PRAGMA synchronous').fetchone()[0],2)
        self.assertEqual(self.value()['planes']['scout']['frames'],8)
        before=self.value();rows=self.db.execute('SELECT * FROM market_observations ORDER BY rowid').fetchall()
        real=self.registry._save_generation
        def failed(state,body):real(state,body);raise RuntimeError('after_registry_update')
        with patch.object(self.registry,'_save_generation',side_effect=failed):
            with self.assertRaisesRegex(RuntimeError,'after_registry_update'):
                commit_scout_batch(self.state,[scout_fact(update(10),NOW)],registry=self.registry)
        self.assertEqual(self.value(),before)
        self.assertEqual(self.db.execute('SELECT * FROM market_observations ORDER BY rowid').fetchall(),rows)

    def test_original_outbox_census_hash_availability_and_rollback(self):
        rows=economic_records('pump',PROGRAMS['pump'],FIXTURE['pump'][0],endpoint_identity='a'*64,
            seen=NOW,source='alchemy_finalized_stream')
        self.history.ingest(rows)
        pending=self.db.execute('SELECT * FROM candidate_outbox ORDER BY sequence').fetchall()
        self.assertTrue(pending)
        def chain(selected):
            value='0'*64
            for row in selected:value=digest([value,list(row)])
            return value
        expected=chain(pending)
        value=self.value()['economic']['all']
        self.assertEqual((value['records'],value['batches'],value['prefix_sha256']),
            (len(pending),1,expected))
        self.assertEqual((value['first_sequence'],value['last_sequence']),(pending[0][0],pending[-1][0]))
        programs=self.value()['economic']['programs']
        for scope,part in programs.items():
            selected=[list(row) for row in pending if row[2]==scope]
            self.assertEqual(part['records'],len(selected))
            self.assertEqual(part['prefix_sha256'],chain(selected))
        self.history.ingest(rows);self.assertEqual(self.value()['economic']['all'],value)
        with self.assertRaisesRegex(RuntimeError,'original_outer_rollback'):
            with self.state.writer.transaction():
                self.db.execute('DELETE FROM candidate_outbox WHERE identity=?',(pending[0][1],))
                self.history._queue_events([row for row in rows if row.identity==pending[0][1]])
                raise RuntimeError('original_outer_rollback')
        self.assertEqual(self.value()['economic']['all'],value)
        self.assertEqual(self.db.execute('SELECT * FROM candidate_outbox ORDER BY sequence').fetchall(),pending)

    def test_program_prefixes_survive_native_batch_partitioning(self):
        other=SourceRegistryTests();other.setUp();self.addCleanup(other.doCleanups)
        rows=[row for family in ('pump','pumpswap') for row in economic_records(family,
            PROGRAMS[family],FIXTURE[family][0],endpoint_identity='a'*64,
            seen=NOW,source='alchemy_finalized_stream')]
        self.history.ingest(rows)
        for row in rows:other.history.ingest([row])
        first=self.value()['economic'];second=other.value()['economic']
        for left,right in [(first['all'],second['all']),*(
                (first['programs'][scope],second['programs'][scope]) for scope in registry.PROGRAM_SCOPES)]:
            self.assertEqual({key:value for key,value in left.items() if key!='batches'},
                {key:value for key,value in right.items() if key!='batches'})
        self.assertGreater(first['programs']['program:pump']['records'],0)
        self.assertGreater(first['programs']['program:pumpswap']['records'],0)

    def test_indexed_initial_native_prefix_is_retained_without_new_generation_relabel(self):
        original=source_fixtures.SourceCurrentCensusTests();original.setUp()
        self.addCleanup(original.doCleanups)
        history=install(original.state);history.clock=lambda:NOW;history.lifecycle.clock=lambda:NOW
        rows=economic_records('pump',PROGRAMS['pump'],FIXTURE['pump'][0],endpoint_identity='a'*64,
            seen=NOW,source='alchemy_finalized_stream')
        history.ingest(rows)
        top=history.db.execute('SELECT MAX(sequence) FROM candidate_outbox').fetchone()[0]
        original.cap.begin(original.state,original.census())
        active=registry.NativeSourceRegistry(original.state,original.cap)
        value=active._generation(original.state)
        self.assertEqual(value['initial_frontiers']['program_outbox_sequence']['program:pump'],top)
        self.assertIsNone(value['initial_frontiers']['program_outbox_sequence']['program:pumpswap'])
        self.assertEqual(value['economic']['all']['records'],0)
        history._normal_source_registry=active;history.ingest(rows)
        self.assertEqual(active._generation(original.state)['economic']['all']['records'],0)
        plan=history.db.execute('EXPLAIN QUERY PLAN SELECT sequence FROM candidate_outbox '
            'WHERE scope=? ORDER BY sequence DESC LIMIT 1',('program:pump',)).fetchall()
        self.assertTrue(any('candidate_outbox_scope' in row[3] for row in plan),plan)
        self.assertFalse(any('SCAN ' in row[3] or 'TEMP B-TREE' in row[3] for row in plan),plan)

    def test_closure_requires_actual_stop_and_checksum_bound_original_receipt(self):
        stream,session=self.opened()
        self.history._observation(None,'source_session_drain',dict(session=session,completed=100))
        observation=self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
        with self.assertRaisesRegex(NormalBootUnavailable,'closure_before_stop'):
            self.registry.closed(self.state,session,observation)
        self.registry.stopped(self.state,stream);self.registry.closed(self.state,session,observation)
        with self.assertRaisesRegex(NormalBootUnavailable,'closure_before_stop'):
            self.registry.closed(self.state,session,observation)
        self.assertEqual(self.db.execute('SELECT count(*) FROM '+registry.SESSION_TABLE).fetchone()[0],1)

    def test_all_queues_committed_does_not_erase_genuine_pre_feed_failed_handler(self):
        self.failed_tail();before=self.db.total_changes
        raw=self.db.execute('SELECT value FROM service_health WHERE key=?',(boot.KEY,)).fetchone()[0]
        plan=self.plan();value=plan.value()
        self.assertEqual(value['sessions'][0]['retained_upper_slot'],123)
        self.assertEqual(value['handlers'][0]['recovery']['gaps'][0]['lower_slot'],100)
        self.assertEqual(value['original_unknown_historical_handlers'],2)
        self.assertEqual(value['original_failure_state'],'RECOVERY_REQUIRED')
        self.assertEqual(value['failed_raw_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertTrue(value['sessions'][0]['fresh_authenticated_upper_required'])
        self.assertFalse(value['sessions'][0]['quiescent_final_frontier_verified'])
        self.assertFalse(value['recovery_complete']);self.assertFalse(value['funding_authority'])
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(self.db.execute('SELECT value FROM service_health WHERE key=?',(boot.KEY,)).fetchone()[0],raw)
        with self.assertRaisesRegex(NormalBootUnavailable,'previous_generation_unresolved'):
            boot.validate_prewrite_generation(self.db,root=self.root,source_inputs=self.cap.identity()['source_inputs'],
                unknown_historical_handlers=2)

    def test_initial_running_census_retains_later_failed_rows_as_unknown_crash_tail(self):
        self.failed_tail(terminal=False)
        value=self.plan().value()
        self.assertEqual(value['handler_population'],'UNKNOWN_CRASH_TAIL')
        self.assertEqual(len(value['handlers']),1)
        self.assertTrue(value['sessions'][0]['fresh_authenticated_upper_required'])
        self.assertFalse(value['terminal_census_retained'])

    def test_later_genuine_control_coverage_does_not_rewrite_failed_callback(self):
        from meme_machine.solana_selective_source import commit_control
        from meme_machine.solana_source_drain import preserve_control_recovery,complete_control_recovery
        from tests.test_candidate_commit_batches import frame
        stream,session=self.opened(plane='control',transport='yellowstone',scopes=['control:solana'])
        ledger=HandlerLedger(self.cap.generation)
        async def fail():
            number=ledger.accept(stream,session,'yellowstone','shared','block_meta',NOW,
                slot=100,scopes=['control:solana'])
            ledger.fail(number,ValueError('not retained'))
        asyncio.run(fail())
        required=preserve_control_recovery(self.state,100,101)
        retained=preserve_handlers(self.state,ledger,ledger.pending(session),dict(kind='CONTROL_REPLAY',**required))
        ledger.preserved(retained)
        with self.state.writer.transaction():
            for slot in (100,101,102):commit_control(self.state,frame(slot,logs=False))
            self.registry.committed(self.state,'control',[100,101,102])
            self.assertIsNone(complete_control_recovery(self.state,'control:solana'))
        self.registry.stopped(self.state,stream)
        body=self.fixture.census(terminal=True);body.update(state='RECOVERY_REQUIRED',
            accepted_handlers=1,settled_handlers=0,pending_handlers=1,handler_accounting=ledger.snapshot())
        body['queues']['control']=dict(accepted=3,committed=3,pending=0)
        self.cap.publish(self.state,body)
        value=self.plan().value();recovery=value['handlers'][0]['recovery']
        self.assertEqual(recovery['lower_slot'],100);self.assertEqual(recovery['upper_slot'],101)
        self.assertIsNone(recovery['current_obligation'])
        self.assertTrue(recovery['canonical_revalidation_required'])
        self.assertFalse(value['handlers'][0]['original_callback_completion'])
        self.assertEqual(value['original_failure_state'],'RECOVERY_REQUIRED')

    def test_unparsed_new_websocket_failure_has_only_registered_potential_scope(self):
        stream,session=self.opened()
        ledger=HandlerLedger(self.cap.generation)
        async def fail():
            number=ledger.accept(stream,session,'websocket','candidate_logs','log_or_ack',NOW)
            ledger.fail(number,ValueError('undecoded callback'))
        asyncio.run(fail())
        retained=preserve_handlers(self.state,ledger,ledger.pending(session),None)
        ledger.preserved(retained)
        self.registry.stopped(self.state,stream)
        body=self.fixture.census(terminal=True);body.update(state='RECOVERY_REQUIRED',
            accepted_handlers=1,settled_handlers=0,pending_handlers=1,handler_accounting=ledger.snapshot())
        self.cap.publish(self.state,body)
        value=self.plan().value();handler=value['handlers'][0]
        self.assertEqual(handler['scope_binding'],'REGISTERED_MAXIMUM_EFFECT_UNIVERSE')
        self.assertEqual(handler['potential_scopes'],[program_scope('pumpswap')])
        self.assertIsNone(handler['slot']);self.assertIsNone(handler['recovery'])
        self.assertTrue(value['sessions'][0]['fresh_authenticated_upper_required'])

    def test_missing_gap_or_changed_handler_and_eof_population_refuse(self):
        _,_,gap=self.failed_tail()
        self.db.execute('UPDATE candidate_gaps SET lo=200 WHERE id=?',(gap,))
        with self.assertRaisesRegex(NormalBootUnavailable,'handler_gap_changed'):self.plan()
        self.db.execute('UPDATE candidate_gaps SET lo=100 WHERE id=?',(gap,))
        self.db.execute('DELETE FROM '+registry.SESSION_TABLE)
        with self.assertRaisesRegex(NormalBootUnavailable,'population_changed'):self.plan()

    def test_read_scope_change_and_payload_bounds_refuse_before_body_decode(self):
        self.failed_tail();context,_=self.context();plan=self.plan(context)
        self.boundary=False
        with self.assertRaisesRegex(Exception,'snapshot_changed'):plan.value()
        self.boundary=True
        self.db.execute('UPDATE '+registry.SESSION_TABLE+' SET body=?',('x'*(registry.MAX_BODY+1),))
        with patch.object(registry,'_validate_session',side_effect=AssertionError('body reducer entered')):
            with self.assertRaisesRegex(NormalBootUnavailable,'input_bound'):self.plan()

    def test_terminal_and_plane_metadata_cannot_replace_missing_session_population(self):
        with self.state.writer.transaction():self.registry.committed(self.state,'rolling',[101])
        body=self.fixture.census(terminal=True);body['state']='RECOVERY_REQUIRED'
        body['queues']['rolling']=dict(accepted=1,committed=1,pending=0)
        self.cap.publish(self.state,body)
        with self.assertRaisesRegex(NormalBootUnavailable,'committed_plane_without_session'):self.plan()

    def test_same_native_eight_frame_and_sixty_five_locator_fixture_has_no_extra_batch_commits(self):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.solana_evidence_service import ServiceState
        from meme_machine.solana_selective_source import commit_candidate_batch,commit_control
        from tests.test_candidate_commit_batches import frame
        baseline=ServiceState(self.root/'baseline.sqlite',
            AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline_fixture_only'))
        self.addCleanup(baseline.close)
        old=install(baseline);old.clock=lambda:NOW;old.lifecycle.clock=lambda:NOW
        baseline.writer.clock=lambda:NOW
        frames=[frame(slot) for slot in range(100,108)]
        facts=[scout_fact(update(n),NOW) for n in range(1,66)]
        addresses={PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
        for state in (baseline,self.state):
            for value in frames:commit_control(state,value)
        self.opened(plane='rolling');self.opened(stream='3'*32,session='4'*32,plane='scout',scopes=['scout:pump'])
        def io():
            value=dict(line.split(':',1) for line in Path('/proc/self/io').read_text().splitlines())
            return {key:int(value[key]) for key in ('wchar','syscw','write_bytes')}
        costs={}
        for name,state,active in (('default',baseline,None),('registry',self.state,self.registry)):
            before=io();commits=state.writer.transaction_metrics['commit.calls'];started=time.monotonic()
            commit_candidate_batch(state,frames,addresses,'2'*32,publish=False,registry=active,plane='rolling')
            commit_scout_batch(state,facts[:64],registry=active)
            commit_scout_batch(state,facts[64:],registry=active)
            elapsed=time.monotonic()-started;after=io()
            costs[name]=dict(seconds=elapsed,commits=state.writer.transaction_metrics['commit.calls']-commits,
                **{key:after[key]-before[key] for key in before})
        for name,value in costs.items():self.assertEqual(value['commits'],3,name)
        tables=('canonical_evidence','rolling_economic_events','candidate_blocks','candidate_outbox',
            'candidate_history_outbox','candidate_pending_proofs','market_observations')
        for table in tables:
            self.assertEqual(sorted(self.db.execute('SELECT * FROM '+table).fetchall(),key=repr),
                sorted(old.db.execute('SELECT * FROM '+table).fetchall(),key=repr),table)
        self.assertEqual(self.value()['planes']['rolling']['frames'],8)
        self.assertEqual(self.value()['planes']['scout']['frames'],65)
        self.assertIsNone(baseline.writer.db.execute("SELECT name FROM sqlite_master WHERE name=?",
            (registry.GENERATION_TABLE,)).fetchone())
        print('NATIVE_SOURCE_REGISTRY_FIXED_FIXTURE_COST='+json.dumps(dict(
            fixture=dict(native_frames=8,scout_locators=65),costs=costs,
            scope='ONE_OFFLINE_FIXED_CORPUS_NOT_PRODUCTION_CAPACITY'),sort_keys=True),flush=True)


class RegistrySubscriptionOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_stream_registers_before_transport_constructor(self):
        fixture=SourceRegistryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None,
            normal_generation=fixture.cap)
        source.normal_registry=fixture.registry;source.stop=asyncio.Event()
        async def work(fn,*args,**kwargs):return fn(fixture.state)
        source.work=work
        async def handler(*args):raise AssertionError('no frame accepted')
        handler.source_session='3'*32;handler.source_plane='control';handler.source_scopes=('control:solana',)
        from meme_machine.yellowstone import geyser_pb2 as pb
        request=pb.SubscribeRequest(from_slot=100)
        def transport(*args,**kwargs):
            rows=fixture.db.execute('SELECT session FROM '+registry.SESSION_TABLE).fetchall()
            self.assertEqual(rows,[(handler.source_session,)])
            raise RuntimeError('original_transport_constructor')
        with self.assertRaisesRegex(RuntimeError,'original_transport_constructor'):
            await source.stream(SimpleNamespace(stream_stream=transport),request,handler,'shared')
        self.assertEqual(fixture.value()['sessions'],1)

