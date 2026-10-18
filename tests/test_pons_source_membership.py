"""Original Pons acquisition/SQLite boundaries, with synthetic provider wire.

These stage observations never establish canonical economics, current/held pool
universe, complete consumer outcomes, financial authority or market capacity.
"""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_historical import Preparation,PLAN
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_natural_observation import MarketScout
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_HASH
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.provider_admission import fingerprint
from meme_machine.runtime.native_commit_measurement import NativeCommitMeasurement
from meme_machine.runtime.pons_economic_cohort import PonsEconomicCohorts
from meme_machine.runtime import pons_source_membership as source
from meme_machine.runtime.robinhood.pons import Broker
from tests import test_pons_factory_census as factory_fixture
from tests.test_pons_dense_v4_receipts import ENDPOINT
from tests.test_robinhood_scout import ObservationTape


class PonsSourceMembershipTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def factory(self,*,candidates=0):
        self.tape=Tape(candidates=candidates)
        self.tape.provider_fingerprint=fingerprint(ENDPOINT)
        self.history=PonsHistory(self.root/'native.sqlite',policy=POLICY_HASH)
        self.addCleanup(self.history.close)
        self.prep=Preparation(self.history,self.tape.provider,
            clock=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)+1)
        self.runtime=Runtime.__new__(Runtime);self.runtime.history=self.history
        self.runtime.economic_cohorts=None
        factory_fixture.PonsFactoryCensusTests.complete(self)
        meter=PonsEconomicCohorts('synthetic-source-stage',ENDPOINT)
        self.history.economic_cohorts=meter
        self.prep.resume()
        self.assertTrue(meter.snapshot()['source_membership']['factory_domain_installed'])
        return meter

    def advance(self):
        self.tape.top+=1
        self.prep.extend(self.tape.header(self.tape.top))
        return self.prep.discover_step()

    def scout(self,root,*,enabled=True):
        tape=ObservationTape(candidates=0);tape.provider_fingerprint=fingerprint(ENDPOINT)
        tape.top=tape.grad+3
        clock=lambda:float(int(tape.header(tape.top)['timestamp'],16))
        broker=Broker(root/'plane.sqlite',CURRENT_HASH,clock=clock,source=ENDPOINT)
        self.addCleanup(broker.close)
        meter=PonsEconomicCohorts('synthetic-source-stage',ENDPOINT) if enabled else None
        if meter is not None:broker.plane.economic_cohorts=meter
        scout=MarketScout(broker.plane)
        event=dict(address='0x'+'ab'*20,topics=[scout.curve_topics[0]],data='0x',
            blockNumber=hex(tape.grad),blockHash=tape.header(tape.grad)['hash'],
            transactionHash='0x'+'cd'*32,transactionIndex='0x0',logIndex='0x0')
        tape.logs=[event]
        return tape,broker,scout,meter,event

    @staticmethod
    def read(tape,broker,scout,first=None,last=None):
        return scout.read_market(tape,tape.grad if first is None else first,
            tape.top if last is None else last,
            nominate=lambda event,observed:broker.enqueue(event,now=observed,needs_work=True))

    def test_actual_factory_replay_and_next_native_packet_commit_extend_one_domain(self):
        meter=self.factory();before=meter.membership.snapshot()
        self.assertTrue(self.advance())
        value=meter.membership.snapshot()
        self.assertEqual(value['factory_through'],self.tape.top)
        self.assertEqual(value['factory_through_hash'],self.tape.header(self.tape.top)['hash'])
        self.assertEqual(value['committed_factory_bridges'],1)
        self.assertEqual(value['unresolved_factory_graduations'],0)
        self.assertNotEqual(before['factory_chain_sha256'],value['factory_chain_sha256'])
        self.assertFalse(value['full_universe_complete'])
        self.assertEqual(value['current_curve_consumer_closure'],'UNESTABLISHED')
        self.assertFalse(self.history.db.in_transaction)

    def test_real_history_savepoint_does_not_publish_before_outer_commit(self):
        meter=self.factory();top=self.tape.top
        with self.history.transaction():
            self.assertTrue(self.advance())
            self.assertEqual(meter.membership.snapshot()['factory_through'],top)
            self.assertTrue(self.history.db.in_transaction)
        self.assertEqual(meter.membership.snapshot()['factory_through'],top+1)
        self.assertEqual(meter.membership.snapshot()['committed_factory_bridges'],1)

    def test_new_native_launch_and_graduation_resolve_only_after_authentication_commit(self):
        meter=self.factory();target=self.tape.top+2
        # Extend the synthetic chain prospectively: the launch and graduation
        # occur strictly after the already authenticated empty factory prefix.
        # Original receipt/header/code/launch reducers authenticate all bodies.
        tape=Tape(candidates=1);tape.provider_fingerprint=fingerprint(ENDPOINT)
        tape.top=target;tape.launch_blocks[tape.tokens[0]]=target-1
        tape.logs=deepcopy(tape.logs[:4])
        for index,event in enumerate(tape.logs):
            block=target-1 if index==0 else target
            event.update(blockNumber=hex(block),blockHash=tape.header(block)['hash'])
        self.tape=tape;self.prep.provider=tape.provider
        self.prep.extend(tape.header(target));self.assertTrue(self.prep.discover_step())
        self.assertEqual(meter.membership.snapshot()['unresolved_factory_graduations'],1)
        for _ in range(12):
            if not self.history.pending_graduations():break
            self.prep.authenticate_step()
        self.assertFalse(self.history.pending_graduations())
        self.assertIsNotNone(self.history.get(tape.tokens[0]))
        value=meter.membership.snapshot()
        self.assertEqual(value['state'],'MEASURING',value)
        self.assertEqual(value['unresolved_factory_graduations'],0)
        self.assertEqual(value['native_outer_commits'],2)
        self.assertFalse(value['full_universe_complete'])

    def test_real_nested_rollback_discards_stages_without_changing_original_error(self):
        meter=self.factory();top=self.tape.top
        with self.assertRaisesRegex(ValueError,'native-rollback'):
            with self.history.transaction():
                self.advance()
                raise ValueError('native-rollback')
        value=meter.membership.snapshot()
        self.assertEqual(value['factory_through'],top)
        self.assertEqual(value['committed_factory_bridges'],0)
        self.assertEqual(value['state'],'UNKNOWN')
        self.assertEqual(self.history.get_meta(PLAN)['target']['number'],hex(top))
        self.assertFalse(self.history.db.in_transaction)

    def test_failed_factory_commit_cannot_advance_metadata_or_leave_transaction(self):
        meter=self.factory();top=self.tape.top
        self.tape.top+=1;self.prep.extend(self.tape.header(self.tape.top))
        self.history.db.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):self.prep.discover_step()
        finally:self.history.db.set_authorizer(None)
        value=meter.membership.snapshot()
        self.assertEqual(value['factory_through'],top)
        self.assertEqual(value['committed_factory_bridges'],0)
        self.assertEqual(value['state'],'UNKNOWN')
        self.assertFalse(self.history.db.in_transaction)

    def test_actual_scout_nomination_sql_and_provider_calls_are_unchanged(self):
        outputs=[];queries=[];statements=[]
        for enabled in (False,True):
            root=self.root/str(enabled);root.mkdir()
            tape,broker,scout,meter,event=self.scout(root,enabled=enabled)
            trace=[];broker.plane.db.set_trace_callback(trace.append)
            result=self.read(tape,broker,scout)
            broker.plane.db.set_trace_callback(None)
            statements.append(trace);queries.append(deepcopy(tape.request_log))
            candidate=broker.plane.get(broker.identity(event))
            self.assertEqual(candidate['deadline'],candidate['observed']+5)
            outputs.append((result,[tuple(r) for r in broker.plane.db.execute(
                'SELECT * FROM candidates ORDER BY id')],scout.events('curve')))
            if meter is not None:
                value=meter.membership.snapshot()
                self.assertEqual(value['broad_nomination_through'],tape.top)
                self.assertEqual(value['broad_nomination_ranges'],1)
                self.assertEqual(value['broad_nomination_contract'],'RAW_VARIANTS_NOT_CANONICAL_ECONOMICS')
                self.assertEqual(meter.snapshot()['active_cohorts'],0)
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(queries[0],queries[1]);self.assertEqual(statements[0],statements[1])

    def test_broad_final_commit_failure_retains_prior_page_and_never_publishes_cursor(self):
        tape,broker,scout,meter,_=self.scout(self.root)
        class FailSecondCommit:
            def __init__(self,db):self.db=db;self.commits=0
            def __getattr__(self,name):return getattr(self.db,name)
            def execute(self,sql,*args):
                if sql=='COMMIT':
                    self.commits+=1
                    if self.commits==2:raise sqlite3.OperationalError('offline-final-commit-failure')
                return self.db.execute(sql,*args)
        # Unlike a SQL authorizer callback, this boundary is hit even when the
        # first COMMIT statement has been cached by SQLite's statement cache.
        broker.plane.db=FailSecondCommit(broker.plane.db)
        # No nomination callback: the real page COMMIT is followed directly
        # by the native final cursor transaction.
        with self.assertRaisesRegex(sqlite3.OperationalError,'offline-final-commit-failure'):
            scout.read_market(tape,tape.grad,tape.top)
        self.assertEqual(len(scout.events('curve')),1)
        self.assertIsNone(broker.plane.checkpoint_read('pons_scout_market_cursor'))
        value=meter.membership.snapshot()
        self.assertIsNone(value['broad_nomination_through'])
        self.assertEqual(value['state'],'UNKNOWN')
        self.assertFalse(broker.plane.db.in_transaction)

    def test_gap_in_actual_native_cursor_calls_cannot_become_continuous_source(self):
        tape,broker,scout,meter,_=self.scout(self.root)
        self.read(tape,broker,scout,last=tape.grad)
        self.read(tape,broker,scout,first=tape.grad+2,last=tape.grad+2)
        self.assertEqual(broker.plane.checkpoint_read('pons_scout_market_cursor'),tape.grad+2)
        value=meter.membership.snapshot()
        self.assertEqual(value['state'],'UNKNOWN');self.assertEqual(value['reason'],'SOURCE_CHANGED')
        self.assertEqual(value['broad_nomination_through'],tape.grad)

    def test_original_reorganization_refuses_and_invalidates_old_measurement(self):
        tape,broker,scout,meter,_=self.scout(self.root)
        self.read(tape,broker,scout,last=tape.grad)
        tape.forks[tape.grad]=1
        with self.assertRaisesRegex(BoundaryError,'scout_public_reorg'):
            self.read(tape,broker,scout,first=tape.grad+1,last=tape.grad+1)
        self.assertEqual(meter.membership.snapshot()['reason'],'SOURCE_CHANGED')
        self.assertEqual(broker.plane.checkpoint_read('pons_scout_market_cursor'),tape.grad-1)

    def test_real_native_registration_matches_actual_authenticated_history_members(self):
        meter=self.factory(candidates=2)
        _,broker,scout,_,event=self.scout(self.root/'scout',enabled=False)
        broker.plane.economic_cohorts=meter;source.bind_plane(broker.plane)
        rows=self.history.rows();meter.membership.expect_watches(self.history,rows)
        observer=NativeCommitMeasurement(dict(fixture=True))
        broker.plane._native_commit_observer=observer.attach('pons_plane')
        for row in rows:
            scout.register_pool(row)
            self.assertFalse(broker.plane.db.in_transaction)
        meter.membership.seal_watches();value=meter.membership.snapshot()
        self.assertEqual(value['expected_watch_members'],2)
        self.assertEqual(value['committed_watch_members'],2)
        self.assertTrue(value['watch_census_complete'])
        # Pool registration is not one of the older row collector's economic
        # stages. Its original empty frames must still close without loss.
        self.assertEqual(observer.snapshot()['observed_transactions'],0)
        self.assertFalse(broker.plane._native_commit_observer.frames)
        self.assertFalse(observer.snapshot()['measurement_loss'])
        broker.enqueue(event,now=broker.plane.clock(),needs_work=True)
        self.assertGreater(observer.snapshot()['committed_row_counts']['pons_generation_dispositions'],0)
        self.assertFalse(broker.plane._native_commit_observer.frames)
        self.assertEqual(value['held_membership'],'UNESTABLISHED')
        self.assertFalse(value['full_universe_complete'])

    def test_failed_watch_commit_and_existing_insert_ignore_cannot_invent_witness(self):
        meter=self.factory(candidates=1)
        _,broker,scout,_,_=self.scout(self.root/'scout',enabled=False)
        rows=self.history.rows();scout.register_pool(rows[0])
        broker.plane.economic_cohorts=meter;source.bind_plane(broker.plane)
        meter.membership.expect_watches(self.history,rows)
        scout.register_pool(rows[0]);meter.membership.seal_watches()
        value=meter.membership.snapshot()
        self.assertEqual(value['committed_watch_members'],0)
        self.assertFalse(value['watch_census_complete'])
        broker.plane.db.execute('DELETE FROM pons_scout_pools')
        broker.plane.db.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' else sqlite3.SQLITE_OK)
        try:
            with self.assertRaises(sqlite3.DatabaseError):scout.register_pool(rows[0])
        finally:broker.plane.db.set_authorizer(None)
        self.assertEqual(broker.plane.db.execute('SELECT count(*) FROM pons_scout_pools').fetchone()[0],0)
        self.assertEqual(meter.membership.snapshot()['committed_watch_members'],0)
        self.assertEqual(meter.membership.snapshot()['state'],'UNKNOWN')

    def test_postcommit_observer_failure_preserves_native_return_and_nomination(self):
        tape,broker,scout,meter,event=self.scout(self.root)
        with patch.object(source._BroadCommit,'committed',side_effect=RuntimeError('observer-only')):
            result=self.read(tape,broker,scout)
        self.assertEqual(result,[event]);self.assertIsNotNone(broker.plane.get(broker.identity(event)))
        self.assertEqual(broker.plane.checkpoint_read('pons_scout_market_cursor'),tape.top)
        self.assertFalse(broker.plane.db.in_transaction)
        self.assertEqual(meter.membership.snapshot()['state'],'UNKNOWN')

    def test_dropped_or_bounded_hook_never_fakes_closed_economic_population(self):
        for mode in ('missing','bound'):
            root=self.root/mode;root.mkdir()
            tape,broker,scout,meter,event=self.scout(root)
            hook=patch.object(source,'broad_packet') if mode=='missing' else patch.object(source,'MAX_ROWS',0)
            with hook:self.read(tape,broker,scout)
            value=meter.membership.snapshot()
            self.assertIsNotNone(broker.plane.get(broker.identity(event)))
            self.assertEqual(broker.plane.checkpoint_read('pons_scout_market_cursor'),tape.top)
            self.assertIsNone(value['broad_nomination_through'])
            self.assertFalse(value['full_universe_complete'])
            self.assertEqual(value['canonical_economic_census'],'UNESTABLISHED')
            self.assertEqual(meter.snapshot()['completed_cohorts'],0)
