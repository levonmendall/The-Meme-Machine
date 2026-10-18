"""Actual cold financial replay in explicit stopped read views, offline only."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime.native_restore_context import (
    NativeDependencyUnavailable, StoppedNativeReadContext)
from tests import test_pump_pons_capital_preparation as preparation


class StoppedNativeReadContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preparation.RuntimeIntegrationTests()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.writer, self.now, self.plan = self.fixture.fixture(owners=False, new_epoch=True)
        self.boundaries = []
        self.boundary_valid = True

    def context(self, *, extra=None, artifacts=None):
        snapshots = {}
        for path in (self.root / 'portfolio.sqlite', self.root / 'shared-capital.sqlite', *(extra or ())):
            db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
            self.addCleanup(db.close)
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            snapshots[path] = db
        def boundary():
            self.boundaries.append(True)
            return self.boundary_valid
        context = StoppedNativeReadContext(self.root, snapshots, validate_snapshot=boundary,
            deadline=time.monotonic() + 30, artifacts=artifacts)
        return context, snapshots

    def test_actual_cold_shared_and_legacy_replay_agree_without_writers_or_fallback_opens(self):
        context, snapshots = self.context()
        before = self.writer.ledger()
        traces = []
        for db in snapshots.values():db.set_trace_callback(traces.append)
        with patch('sqlite3.connect', side_effect=AssertionError('fallback open')), \
                patch('pathlib.Path.stat', side_effect=AssertionError('host identity probe')):
            proof = context.authenticate_authority()
            self.assertTrue(proof['conservation'])
            self.assertEqual(context.ledger(), before)
            detached = context.ledger()
            detached['cash'] = '1'
            self.assertEqual(context.ledger(), before)
            context.verify_boundary()
        self.assertEqual(self.writer.ledger(), before)
        self.assertFalse(any(sql.lstrip().split()[0].upper() in
            ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'COMMIT', 'BEGIN') for sql in traces))
        self.assertEqual(len(self.boundaries), 2)

    def test_projection_does_not_authenticate_without_original_full_replay(self):
        context, snapshots = self.context()
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'not_authenticated'):
            context.ledger()
        from meme_machine.shared_capital.runtime import RuntimeCapital
        with patch.object(RuntimeCapital, '_verify_replay', side_effect=ValueError('original replay failure')):
            with self.assertRaisesRegex(ValueError, 'original replay failure'):
                context.authenticate_authority()
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'not_authenticated'):
            context.ledger()

    def test_missing_or_writable_snapshot_is_rejected_before_any_reducer(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for transaction, readonly in ((False, True), (True, False)):
            with self.subTest(transaction=transaction, readonly=readonly):
                if db.in_transaction:db.rollback()
                db.execute('PRAGMA query_only=' + str(int(readonly)))
                if transaction:db.execute('BEGIN')
                with self.assertRaisesRegex(NativeDependencyUnavailable, 'readonly_snapshot'):
                    StoppedNativeReadContext(self.root, {self.root/'private.sqlite':db},
                        validate_snapshot=lambda:True, deadline=time.monotonic()+10)

    def test_unbounded_deadline_is_rejected_and_failed_close_retires_borrowed_view(self):
        context, snapshots = self.context(extra=self.native_books())
        for deadline in (float('nan'),float('inf')):
            with self.subTest(deadline=deadline):
                with self.assertRaisesRegex(NativeDependencyUnavailable,'snapshot_owner_required'):
                    StoppedNativeReadContext(self.root,snapshots,validate_snapshot=lambda:True,deadline=deadline)
        from meme_machine.runtime.native_restore_closure import PLANE
        db = snapshots[self.root/PLANE]
        self.assertIsNone(db.row_factory)
        context.pons_plane(self.root/PLANE)
        self.assertIs(db.row_factory,sqlite3.Row)
        self.boundary_valid = False
        with self.assertRaisesRegex(NativeDependencyUnavailable,'snapshot_changed'):
            context.close()
        self.assertIsNone(db.row_factory)
        self.assertTrue(db.in_transaction)
        self.assertEqual(db.execute('SELECT 1').fetchone(),(1,))
        with self.assertRaisesRegex(NativeDependencyUnavailable,'context_owner'):
            context.check()

    def test_outside_census_and_foreign_thread_cannot_borrow_a_handle(self):
        context, _ = self.context()
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'outside_census'):
            with context.database(self.root/'not-in-census.sqlite'):pass
        errors = []
        def foreign():
            try:context.check()
            except Exception as error:errors.append(error)
        owner = threading.Thread(target=foreign)
        owner.start();owner.join(2)
        self.assertFalse(owner.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIs(type(errors[0]), NativeDependencyUnavailable)
        self.assertIn('context_owner', str(errors[0]))

    def test_logical_identity_mapping_does_not_dereference_original_host_path(self):
        context, snapshots = self.context()
        # A future snapshot resolver supplies the same authenticated old identity
        # with an already-open pinned copy. No hash-bearing native body changes.
        logical = Path('/original-stopped-root')
        copied = StoppedNativeReadContext(logical,
            {logical/path.relative_to(self.root):db for path, db in snapshots.items()},
            validate_snapshot=lambda:True, deadline=time.monotonic()+10)
        with patch('pathlib.Path.resolve', side_effect=AssertionError('host resolution')), \
                patch('sqlite3.connect', side_effect=AssertionError('fallback open')):
            copied.authenticate_authority()
            self.assertEqual(copied.cohort_id, self.plan['seed']['epoch_id'])

    def test_final_boundary_failure_discards_provisional_scope_and_next_call_is_fresh(self):
        context, snapshots = self.context()
        old = context.authenticate_authority()
        self.boundary_valid = False
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'snapshot_changed'):
            context.verify_boundary()
        for db in snapshots.values():db.rollback()
        self.writer.command('next-stopped-publication', 'runtime_publish', {}, self.now)
        self.boundary_valid = True
        fresh, _ = self.context()
        current = fresh.authenticate_authority()
        self.assertGreater(current['events'], old['events'])
        self.assertNotEqual(current['journal_hash'], old['journal_hash'])

    def test_artifact_reads_use_only_the_preopened_readonly_descriptor_and_exact_hash(self):
        path = self.root/'retained.zlib'
        data = b'authenticated temporary artifact'
        path.write_bytes(data)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.addCleanup(os.close, fd)
        context, _ = self.context(artifacts={path:fd})
        with patch('pathlib.Path.read_bytes', side_effect=AssertionError('pathname read')):
            self.assertEqual(context.read_artifact(path, sha256=hashlib.sha256(data).hexdigest()), data)
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'artifact_hash'):
            context.read_artifact(path, sha256='0'*64)
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'outside_census'):
            context.read_artifact(self.root/'absent', sha256='0'*64)
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'artifact_changed'):
            context.read_artifact(path, sha256=hashlib.sha256(data).hexdigest(), maximum=len(data)-1)

    def test_writable_artifact_and_unknown_retained_owner_are_refused(self):
        path = self.root/'private'
        path.write_bytes(b'x')
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        self.addCleanup(os.close, fd)
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'readonly_required'):
            self.context(artifacts={path:fd})
        context, _ = self.context()
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'owner_unverified'):
            context.require_owner_stopped('boot:123:45')

    def test_scalar_duplicate_columns_and_complete_population_are_prebounded(self):
        path = self.root/'bounded.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE inputs(id TEXT,body TEXT)')
            db.execute('INSERT INTO inputs VALUES(?,?)', ('too-long-scalar', '{}'))
        context, snapshots = self.context(extra=(path,))
        with patch('meme_machine.runtime.native_restore_context.MAX_FIELD', 4):
            with self.assertRaisesRegex(NativeDependencyUnavailable, 'payload_bound'):
                context.bound_bodies(snapshots[path], ('inputs',))
        # All rows count even if an eventual semantic reader would filter them.
        snapshots[path].rollback()
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO inputs VALUES(?,?)', ('b', '{}'))
        snapshots[path].execute('BEGIN')
        with patch('meme_machine.runtime.native_restore_context.MAX_ROWS', 1):
            with self.assertRaisesRegex(NativeDependencyUnavailable, 'payload_bound'):
                context.bound_bodies(snapshots[path], ('inputs',))

    def test_one_fence_bound_stopped_owner_proof_is_reused_without_per_row_probes(self):
        context, _ = self.context()
        seen = []
        context._validate_owner = lambda identity: seen.append(identity) or True
        context.require_owner_stopped('boot:123:45')
        context.require_owner_stopped('boot:123:45')
        self.assertEqual(seen, ['boot:123:45'])
        context.close()
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'context_owner'):
            context.require_owner_stopped('boot:123:45')

    def native_books(self):
        import json
        from meme_machine.runtime.native_restore_closure import PAPERS, HISTORIES, COHORT, PLANE
        from meme_machine.runtime.directional_sleeve import open_sleeve, policies
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.lanes.pump.paper_accounting import PaperBook as CurrentPaper
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.runtime.policy_compatibility import active_hash
        from meme_machine.runtime.robinhood.plane import Plane
        epoch = self.plan['seed']['epoch_id']
        paths = []
        for lane in ('pump','pons'):
            (self.root/lane).mkdir(parents=True, exist_ok=True)
            with patch.dict(os.environ, {'MM_DIRECTIONAL_SLEEVE_DB':str(self.root/lane/'directional-sleeve.sqlite')}):
                sleeve = open_sleeve(lane, 125000)
                sleeve.close()
            paths.append(self.root/lane/'directional-sleeve.sqlite')
        for regime, relative in PAPERS.items():
            path = self.root/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            lane = regime.split('_')[0]
            strategy = next(name for name in policies(lane) if ('survivor' in name)==regime.endswith('_survivor'))
            paper = (CurrentPaper if regime=='pump_current' else PaperBook)(path, run_id=epoch,
                lane=strategy, policy_hash=active_hash(regime), initial=125000)
            paper.close()
            paths.append(path)
        for lane, relative in HISTORIES.items():
            path = self.root/relative
            history = (History if lane=='pump' else PonsHistory)(path,policy=active_hash(lane+'_survivor'))
            history.close()
            paths.append(path)
        capital = self.root/COHORT/'pons-selective-cohort-capital.sqlite'
        with patch.dict(os.environ, {'MM_DIRECTIONAL_SLEEVE_DB':str(self.root/'pons/directional-sleeve.sqlite')}):
            CohortCapital(capital, 125000)
        paths.append(capital)
        path = self.root/PLANE
        path.parent.mkdir(parents=True,exist_ok=True)
        plane = Plane(path)
        plane.checkpoint('pons_cohort', dict(owner='original-stopped:123:45',phase='running',cursor=0,
            result=dict(policy_hash=active_hash('pons_current'),qualifiers=[],lifecycles=[])))
        plane.close()
        paths.append(path)
        return paths

    def native_terminals(self, paths, *, pons_cancelled=False):
        """Real disposable native transactions/ACKs, no invented projections."""
        from dataclasses import replace
        from meme_machine.shared_capital.operational_candidate import ACTIVE_REGIMES
        from meme_machine.runtime.native_restore_closure import PAPERS, HISTORIES, COHORT, PLANE
        from meme_machine.runtime.directional_sleeve import open_sleeve, policies
        from meme_machine.runtime.directional_continuation import native_sync
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.lanes.pump.paper_accounting import PaperBook as CurrentPaper
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.runtime.policy_compatibility import active_hash
        from meme_machine.runtime.journal import digest
        from tests.shared_rally_support import observe_survivor
        epoch = self.plan['seed']['epoch_id']
        now = self.now
        for regime in ACTIVE_REGIMES:
            self.writer.owner(regime, 'offline-native-owner', os.getpid(), ready=True, at=now)
        identities = {}
        for lane in ('pump','pons'):
            regime = lane+'_survivor'
            strategy = next(name for name in policies(lane) if 'survivor' in name)
            identity = epoch+':stopped-'+regime
            candidate = 'asset:'+regime
            with patch.dict(os.environ, {'MM_DIRECTIONAL_SLEEVE_DB':str(self.root/lane/'directional-sleeve.sqlite')}):
                sleeve = open_sleeve(lane, 125000)
                observed = observe_survivor(sleeve,strategy,candidate,now)
                history = (History if lane=='pump' else PonsHistory)(self.root/HISTORIES[lane],policy=active_hash(regime))
                row = history.graduate(candidate,dict(at=now-12000,canonical_event='synthetic:'+candidate))
                history.append(candidate,through=now,events=[],points=[(now, '1')],complete=True)
                row = history.get(candidate)
                sleeve.reserve(identity,strategy=strategy,amount=1000,at=now,candidate=candidate,
                    generation=observed['generation'],regime=observed['regime'])
                book = PaperBook(self.root/PAPERS[regime],run_id=epoch,lane=strategy,
                    policy_hash=active_hash(regime),initial=125000)
                try:
                    book.reserve(identity,1000,now,dict(candidate=candidate,decision=observed['evidence']))
                    with sleeve.commit_fence(identity):
                        book.transition(identity,'filled',now+1,amount=1000,tokens=100,
                            evidence=dict(decision=observed['evidence']))
                    native_sync(book,sleeve,identity)
                    book.transition(identity,'settled',now+2,amount=1000)
                    from meme_machine.runtime.directional_sleeve import native_terminal
                    native_terminal(sleeve,identity,book._load(identity),now+2,verified=book.replay()['verified'])
                    row.update(position=None,state='settled',through=now+2)
                    history.save(row)
                finally:
                    book.close();history.close();sleeve.close()
            identities[regime] = identity
        from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify, STRATEGY_ID
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        from meme_machine.lanes.pump import runner
        signal = PumpAccelerationStrategyTests().strong_late(observed_at=now)
        snapshot = dict(slot=1,market_time=now,_runtime_recovery=dict(signal=signal.__dict__,
            mode=signal.phase,concentration=1500,confirmation_state=None,
            state=dict(creation=dict(mint=signal.mint,creator='creator'),pregrad_wallets=[],graduated=False),
            execution=dict(scope=runner.PUMP_SCOPE,addresses=['curve'])))
        book = CurrentPaper(self.root/PAPERS['pump_current'],run_id=epoch,lane=STRATEGY_ID,
            policy_hash=active_hash('pump_current'),initial=125000)
        life = PumpAccelerationPaperLifecycle(book=book,lifecycle_id=epoch+':stopped-pump-current',entry_evidence=snapshot)
        try:
            life.reserve(qualify(signal),1000,now)
            life.cancel('offline-no-fill',now+2)
            identities['pump_current'] = life.lifecycle_id
        finally:
            if life.sleeve is not None:life.sleeve.close()
            book.close()
        from tests.lanes.pons.test_pons_current_recovery import ReentryNativeReferenceTests
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.runtime.robinhood.plane import Plane
        vector = ReentryNativeReferenceTests().vector(now)
        vector['demand']['largest_buyer_flow_bps'] = 1500
        fixture = PartialAccountingTests()
        at = vector['evidence_available_at']
        identity = epoch+':stopped-pons-current'
        trial = self.root/COHORT/'trial-0.sqlite'
        with patch.dict(os.environ, {'MM_DIRECTIONAL_SLEEVE_DB':str(self.root/'pons/directional-sleeve.sqlite')}):
            capital = CohortCapital(self.root/COHORT/'pons-selective-cohort-capital.sqlite',125000)
            store = Store(trial)
            try:
                paper = SelectivePaper(store,STRATEGY_NAMESPACE,125000,delay=1,
                    natural_policy_hash=active_hash('pons_current'),on_commit=capital.observe)
                evaluation = dict(candidate={},vector=vector,token='token',curve='m',source_transaction='source',market_events=[])
                controller = LifecycleState.create(store,identity,evaluation,125000,20,opened_at=at+1,last_block=1)
                paper.controller_context = controller.checkpoint
                features = dict(fixture.features(at),token='token',source_transaction='source',
                    qualifying_vector_id=digest(vector),qualifying_vector_asof=vector['asof'])
                capital.reserve(identity,120,at=at,decision_hash=digest(features),trial_path=trial,
                    native_reservation_intent=dict(market='m',amount=100,gas_budget=20,now=at,features=features,kind='natural'))
                paper.reserve(identity,market='m',amount=100,gas_budget=20,now=at,features=features)
                if pons_cancelled:
                    position = paper.advance(identity,now=at+1,action='cancel',cancel_reason='confirmed_no_fill')
                else:
                    paper.advance(identity,now=at+1,action='entry',quote=fixture.quote(at+1,'buy',100,1000))
                    paper.advance(identity,now=at+2,action='exit_intent')
                    position = paper.advance(identity,now=at+3,action='exit',quote=fixture.quote(at+3,'sell',1000,110))
                capital.settle(identity,position,at=position['last_at'])
            finally:store.close()
        qualifier = dict(index=0,curve='m',token='token',source_transaction='source',vector=vector)
        lifecycle = dict(index=0,curve='m',token='token',lifecycle_id=identity,final_position=position,
            status='entry_failed' if pons_cancelled else 'settled')
        plane = Plane(self.root/PLANE)
        plane.checkpoint('pons_cohort',dict(owner='original-stopped:123:45',phase='running',cursor=0,
            result=dict(policy_hash=active_hash('pons_current'),qualifiers=[qualifier],lifecycles=[lifecycle])))
        plane.close()
        paths.append(trial)
        identities['pons_current'] = identity
        return identities

    def test_actual_four_empty_books_cold_replay_without_constructors_or_fallback_opens(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.runtime.robinhood.plane import Plane
        paths = self.native_books()
        context, snapshots = self.context(extra=paths)
        context._validate_owner = lambda identity: identity=='original-stopped:123:45'
        traces = []
        for db in snapshots.values():db.set_trace_callback(traces.append)
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')), \
                patch.object(PaperBook,'__init__',side_effect=AssertionError('native writer')), \
                patch.object(SleeveReservations,'__init__',side_effect=AssertionError('sleeve writer')), \
                patch.object(CohortCapital,'__init__',side_effect=AssertionError('capital writer')), \
                patch.object(Plane,'__init__',side_effect=AssertionError('Plane writer')), \
                patch('pathlib.Path.resolve',side_effect=AssertionError('host path resolution')):
            facts = _native_memory_facts(context)
        self.assertEqual(set(facts['facts']), {'pump_current','pump_survivor','pons_current','pons_survivor'})
        self.assertEqual(facts['capital']['positions'], 0)
        self.assertFalse(any(sql.split()[0].upper() in
            ('INSERT','UPDATE','DELETE','CREATE','DROP','BEGIN','COMMIT','ATTACH') for sql in traces))

    def test_full_closure_is_unknown_until_discovery_semantics_are_implemented(self):
        from meme_machine.runtime.native_restore_closure import validate_stopped_restore_closure
        context, _ = self.context(extra=self.native_books())
        context._validate_owner = lambda identity: True
        with self.assertRaisesRegex(NativeDependencyUnavailable, 'discovery_semantics_unimplemented'):
            validate_stopped_restore_closure(context)

    def test_actual_four_terminal_books_join_real_global_receipts_and_controller_memory(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts
        paths = self.native_books()
        identities = self.native_terminals(paths)
        context, snapshots = self.context(extra=paths)
        context._validate_owner = lambda identity: True
        traces = []
        for db in snapshots.values():db.set_trace_callback(traces.append)
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')):
            facts = _native_memory_facts(context)
        self.assertEqual(facts['capital']['positions'], 1)
        self.assertEqual(facts['facts']['pump_current']['qualifiers'], 1)
        self.assertEqual(facts['facts']['pons_current']['trials'], 1)
        self.assertEqual(facts['facts']['pump_survivor']['positions'], 1)
        self.assertEqual(facts['facts']['pons_survivor']['positions'], 1)
        self.assertEqual(len(identities), 4)
        self.assertFalse(any(sql.split()[0].upper() in
            ('INSERT','UPDATE','DELETE','CREATE','DROP','BEGIN','COMMIT','ATTACH') for sql in traces))
        restarted, _ = self.context(extra=paths)
        restarted._validate_owner = lambda identity: True
        self.assertEqual(_native_memory_facts(restarted),facts)

    def test_capital_crosscheck_prebounds_each_trial_body_before_native_json_decode(self):
        import json
        from meme_machine.runtime.native_restore_closure import COHORT
        from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
        from meme_machine.runtime import native_restore_context as ports
        paths = self.native_books()
        identities = self.native_terminals(paths)
        trial = self.root/COHORT/'trial-0.sqlite'
        native_id = identities['pons_current']
        def encoding(db,table,where,args,body):
            trigger = None
            if table=='records':
                trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='pons_selective_records_no_update'").fetchone()[0]
                db.execute('DROP TRIGGER pons_selective_records_no_update')
            db.execute('UPDATE '+table+' SET body=? WHERE '+where,(body,*args))
            if trigger:db.execute(trigger)
        for table in ('pons_selective_paper','records'):
            with self.subTest(table=table):
                with sqlite3.connect(trial) as db:
                    where, args = ('id=?',(native_id,)) if table=='pons_selective_paper' else (
                        'category=? AND id=?',(JOURNAL_CATEGORY,native_id+':3'))
                    original = db.execute('SELECT body FROM '+table+' WHERE '+where,args).fetchone()[0]
                    padded = original + ' '*32768
                    encoding(db,table,where,args,padded)
                context, snapshots = self.context(extra=paths)
                context.authenticate_authority()
                loads = json.loads
                def guarded(value, *args, **kwargs):
                    if value == padded:raise AssertionError('native JSON decoded before bounds')
                    return loads(value,*args,**kwargs)
                try:
                    with patch.object(ports,'MAX_FIELD',32768),patch.object(json,'loads',side_effect=guarded):
                        with self.assertRaisesRegex(NativeDependencyUnavailable,'capital_replay'):
                            context.capital(self.root/COHORT/'pons-selective-cohort-capital.sqlite')
                finally:
                    for db in snapshots.values():db.rollback()
                    with sqlite3.connect(trial) as db:
                        # Restore only this disposable whitespace encoding;
                        # all original decoded bodies and hashes are identical.
                        encoding(db,table,where,args,original)

    def test_actual_pons_never_filled_release_needs_no_fabricated_settled_position(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts
        paths = self.native_books()
        identities = self.native_terminals(paths,pons_cancelled=True)
        context, snapshots = self.context(extra=paths)
        context._validate_owner = lambda identity:identity=='original-stopped:123:45'
        before = self.writer.ledger()
        alias = before['native_aliases']['pons:'+identities['pons_current']]
        self.assertNotIn(alias,before['positions'])
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')):
            facts = _native_memory_facts(context)
        self.assertEqual(facts['facts']['pons_current']['trials'],1)
        self.assertEqual(self.writer.ledger(),before)

    def test_cold_shared_replay_stops_at_original_per_event_deadline_hook(self):
        from meme_machine.shared_capital.runtime import RuntimeCapital
        self.writer.command('deadline-second-real-event','runtime_publish',{},self.now)
        context, _ = self.context()
        original = RuntimeCapital._apply
        reduced = []
        def expire(reader,state,event):
            reduced.append(event['operation_id'])
            result = original(reader,state,event)
            context.deadline = time.monotonic()-1
            return result
        with patch.object(RuntimeCapital,'_apply',expire):
            with self.assertRaisesRegex(TimeoutError,'native_restore_deadline'):
                context.authenticate_authority()
        self.assertEqual(len(reduced),1)

    def test_public_projection_names_roles_and_never_grants_boot_or_history_authority(self):
        from meme_machine.runtime.native_restore_closure import inspect_stopped_restore_memory
        context, _ = self.context(extra=self.native_books())
        context._validate_owner = lambda identity: True
        value = inspect_stopped_restore_memory(context)
        self.assertEqual(len(value['four_regimes']),4)
        self.assertTrue(value['native_memory_reducer_ports_verified'])
        self.assertTrue(value['unimplemented_input_dependencies'])
        for key in ('native_input_closure_complete','current_native_resumability_verified',
                'current_economic_authority_verified','qualification_authority','funding_authority',
                'boot_authority','historical_handler_disposition_verified',
                'historical_drain_reclassified','safe_for_normal','raw_content_exported'):
            self.assertIs(value[key],False,key)
        self.assertEqual((value['provider_requests'],value['authoritative_writes']),(0,0))
        self.assertEqual(value['dependency_roles']['scout_watch_cursor_pipeline'],
            'ORIGINAL_FUNDING_CLOSED_STARTUP_REPAIR_INPUT')
        self.assertNotIn('facts',value)

    def test_genuine_pons_controller_group_change_fails_original_restore(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts, COHORT
        paths = self.native_books()
        identities = self.native_terminals(paths)
        with sqlite3.connect(self.root/COHORT/'trial-0.sqlite') as db:
            db.execute('INSERT INTO pons_selective_controller_groups VALUES(?,?,?)',
                (identities['pons_current'],'preholders','unrecorded-group'))
        context, _ = self.context(extra=paths)
        context._validate_owner = lambda identity: True
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')):
            with self.assertRaisesRegex(ValueError,'selective_controller_group_replay'):
                _native_memory_facts(context)

    def test_missing_native_trial_cannot_be_replaced_by_projection_or_another_open(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts, COHORT
        paths = self.native_books()
        self.native_terminals(paths)
        paths.remove(self.root/COHORT/'trial-0.sqlite')
        context, _ = self.context(extra=paths)
        context._validate_owner = lambda identity: True
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')):
            with self.assertRaisesRegex(NativeDependencyUnavailable,'capital_replay'):
                _native_memory_facts(context)

    def test_complete_survivor_point_population_rejects_orphan_even_with_valid_hash(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts, HISTORIES
        from meme_machine.runtime.journal import canonical, digest
        paths = self.native_books()
        price = canonical(dict(low='1',price='1',high='1'))
        with sqlite3.connect(self.root/HISTORIES['pump']) as db:
            db.execute('INSERT INTO points VALUES(?,?,?,?)', ('missing-native-candidate',1,price,
                digest(['missing-native-candidate',1,price])))
        context, _ = self.context(extra=paths)
        context._validate_owner = lambda identity: True
        with self.assertRaisesRegex(NativeDependencyUnavailable,'survivor_point_join'):
            _native_memory_facts(context)

    def test_missing_terminal_controller_receipt_keeps_original_continuation_required(self):
        import json
        from meme_machine.runtime.native_restore_closure import _native_memory_facts, PLANE
        from meme_machine.runtime.journal import canonical
        paths = self.native_books()
        self.native_terminals(paths)
        with sqlite3.connect(self.root/PLANE) as db:
            row = json.loads(db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()[0])
            row['result']['lifecycles'] = []
            db.execute("UPDATE runtime SET body=? WHERE key='pons_cohort'",(canonical(row),))
        context, _ = self.context(extra=paths)
        context._validate_owner = lambda identity: True
        with self.assertRaisesRegex(NativeDependencyUnavailable,'controller_continuation_required'):
            _native_memory_facts(context)

    def test_owner_unknown_refuses_before_any_process_probe_or_native_repair(self):
        from meme_machine.runtime.native_restore_closure import _native_memory_facts
        context, _ = self.context(extra=self.native_books())
        with patch('pathlib.Path.read_text',side_effect=AssertionError('unowned proc read')):
            with self.assertRaisesRegex(NativeDependencyUnavailable,'owner_unverified'):
                _native_memory_facts(context)


class StoppedPonsRetainedInterpretationTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from tests.lanes.pons.test_pons_candidate_plane import event
        from meme_machine.lanes.pons.abi import topic
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.broker = Broker(Path(temporary.name)/'plane', POLICY_HASH, clock=lambda:100.)
        self.addCleanup(self.broker.close)
        nomination = event()
        nomination['topics'] = [topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')]
        self.broker.enqueue(nomination)
        self.identity = self.broker.identity(nomination)

    def test_actual_retained_watch_is_read_only_and_repair_stays_explicit(self):
        from meme_machine.runtime.journal import canonical, digest
        broker = self.broker
        before = broker.plane.db.total_changes
        statements = []
        broker.plane.db.set_trace_callback(statements.append)
        broker.plane.db.execute('PRAGMA query_only=ON')
        with patch.object(broker, '_remember_watch', side_effect=AssertionError('write')):
            self.assertTrue(broker.retained_interpretation_ready(self.identity))
            broker.policy = dict(broker.policy, adapter_source='f'*64)
            with patch('meme_machine.runtime.policy_compatibility.require_external_flat',
                       side_effect=AssertionError('fallback external open')):
                self.assertFalse(broker.retained_interpretation_ready(self.identity))
        self.assertEqual(broker.plane.db.total_changes, before)
        self.assertFalse(any(sql.split()[0].upper() in
            ('INSERT','UPDATE','DELETE','CREATE','DROP') for sql in statements))

    def test_retired_watch_is_valid_but_crossed_identity_or_unsynced_order_is_not(self):
        import json
        from meme_machine.runtime.journal import canonical, digest
        broker = self.broker
        db = broker.plane.db
        raw, = db.execute('SELECT body FROM pons_current_watch').fetchone()
        watch = json.loads(raw)
        watch['latest_id'] = 'an interrupted sync'
        db.execute('UPDATE pons_current_watch SET body=?,hash=?', (canonical(watch),digest(watch)))
        self.assertFalse(broker.retained_interpretation_ready(self.identity))
        db.execute('DELETE FROM candidates')
        self.assertTrue(broker.retained_interpretation_ready(self.identity))
        watch['event']['address'] = '0x'+'34'*20
        db.execute('UPDATE pons_current_watch SET body=?,hash=?', (canonical(watch),digest(watch)))
        self.assertFalse(broker.retained_interpretation_ready(self.identity))


class StoppedCanonicalReferenceTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from tests.test_startup_archive_read_reuse import ArchiveCorpus
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'corpus'
        self.corpus = ArchiveCorpus(self, self.root)
        self.snapshots = {}
        for path in (self.corpus.source,self.corpus.consumer):
            db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None)
            self.addCleanup(db.close)
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            self.snapshots[path] = db
        fd = os.open(self.corpus.archive,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        self.addCleanup(os.close,fd)
        self.context = StoppedNativeReadContext(self.root,self.snapshots,
            artifacts={self.corpus.archive:fd},validate_snapshot=lambda:True,deadline=time.monotonic()+30)

    def test_actual_full_ack_hot_and_cold_events_use_only_borrowed_db_and_held_archive(self):
        history = self.context.candidate_history(self.corpus.consumer)
        traces = []
        for db in self.snapshots.values():db.set_trace_callback(traces.append)
        with patch('sqlite3.connect',side_effect=AssertionError('fallback open')), \
                patch('pathlib.Path.read_bytes',side_effect=AssertionError('pathname read')), \
                patch('pathlib.Path.stat',side_effect=AssertionError('pathname stat')):
            self.assertEqual(history.events('pump',self.corpus.mint), self.corpus.expected)
        self.assertFalse(any(sql.split()[0].upper() in
            ('INSERT','UPDATE','DELETE','CREATE','DROP','BEGIN','COMMIT','ATTACH') for sql in traces))
        self.corpus.unchanged()

    def test_changed_held_artifact_refuses_without_empty_result_or_ack(self):
        history = self.context.candidate_history(self.corpus.consumer)
        self.corpus.archive.write_bytes(b'changed retained artifact')
        try:
            with self.assertRaisesRegex(NativeDependencyUnavailable,'artifact_changed'):
                history.events('pump',self.corpus.mint)
            self.assertEqual(self.snapshots[self.corpus.consumer].execute(
                'SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0], len(self.corpus.refs))
        finally:self.corpus.archive.write_bytes(self.corpus.archive_bytes)

    def test_source_field_bounds_refuse_before_canonical_decode(self):
        history = self.context.candidate_history(self.corpus.consumer)
        with patch('meme_machine.runtime.native_restore_context.MAX_FIELD',1), \
                patch('meme_machine.solana_evidence_plane.decode_body',side_effect=AssertionError('decode before bound')):
            with self.assertRaisesRegex(NativeDependencyUnavailable,'payload_bound'):
                history.events('pump',self.corpus.mint)
