"""Real native SQLite commit points; no live source/census/financial claim."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.journal import canonical, digest
from meme_machine.runtime.native_commit_measurement import NativeCommitMeasurement, MAX_RECORDS
from meme_machine.runtime.robinhood.plane import Plane


class _CommitProbe:
    def __init__(self, db, collector, *, fail=None):
        self.db, self.collector, self.fail = db, collector, fail
        self.boundaries = []
    def __getattr__(self, name):
        return getattr(self.db, name)
    def execute(self, sql, *args):
        if sql == 'COMMIT':
            self.boundaries.append(('before',self.collector.snapshot()['observed_transactions']))
            if self.fail == 'before':
                raise sqlite3.OperationalError('offline commit failure')
        result=self.db.execute(sql,*args)
        if sql == 'COMMIT':
            self.boundaries.append(('returned',self.collector.snapshot()['observed_transactions']))
            self.returned_at=time.monotonic_ns()
            if self.fail == 'after':
                raise sqlite3.OperationalError('offline uncertain commit')
        return result


class NativeCommitSQLiteTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.collector=NativeCommitMeasurement(dict(offline_fixture=True))
        self.history=CandidateHistory(self.root/'history.sqlite',clock=lambda:1000)
        self.addCleanup(self.history.close)
        self.history._native_commit_observer=self.collector.attach('candidate_history')

    def event(self, identity, *, owner=None):
        return (owner or self.history).append_event('pump','mint',identity=identity,
            slot=10,transaction_index=0,event_index=0,market_time=1000,
            kind='pump_trade',payload=dict(offline=True))

    def counts(self):
        return self.collector.snapshot()['committed_row_counts']

    def test_outer_full_returns_before_observation_nested_releases_are_not_full(self):
        probe=_CommitProbe(self.history.db,self.collector);self.history.db=probe
        with self.history.transaction():
            self.event('a')
            with self.history.transaction(): self.event('b')
            self.assertEqual(self.counts()['history_event_rows'],0)
        self.assertEqual(probe.boundaries,[('before',0),('returned',0)])
        self.assertEqual(self.counts()['history_event_rows'],2)
        self.assertEqual(self.collector.snapshot()['observed_transactions'],1)
        self.assertGreaterEqual(self.collector.snapshot()['last_post_commit_observation_monotonic_ns'],probe.returned_at)
        with sqlite3.connect(self.history.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)

    def test_nested_rollback_discards_only_rolled_back_metadata(self):
        with self.history.transaction():
            self.event('kept-1')
            with self.assertRaisesRegex(ValueError,'rollback'):
                with self.history.transaction():
                    self.event('rolled-back')
                    raise ValueError('rollback')
            self.event('kept-2')
        self.assertEqual([r[0] for r in self.history.db.execute('SELECT identity FROM events ORDER BY identity')],
            ['kept-1','kept-2'])
        self.assertEqual(self.counts()['history_event_rows'],2)

    def test_outer_rollback_has_no_successful_commit_receipt(self):
        with self.assertRaisesRegex(ValueError,'rollback'):
            with self.history.transaction():
                self.event('rolled-back')
                raise ValueError('rollback')
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertEqual(self.counts()['history_event_rows'],0)
        self.assertIsNone(self.collector.snapshot()['last_post_commit_observation_monotonic_ns'])

    def test_failed_native_savepoint_cleanup_latches_loss_without_changing_original_error(self):
        class FailedRollback(_CommitProbe):
            def execute(self,sql,*args):
                if sql.startswith('ROLLBACK TO '):
                    raise sqlite3.OperationalError('offline rollback failure')
                return super().execute(sql,*args)
        self.history.db=FailedRollback(self.history.db,self.collector)
        with self.history.transaction():
            self.event('outer')
            with self.assertRaisesRegex(ValueError,'original native error'):
                with self.history.transaction():
                    self.event('rollback-was-not-confirmed')
                    raise ValueError('original native error')
        # Preserve the original native cleanup semantics, including its error
        # precedence. The measurement cannot claim the failed rollback worked.
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)
        self.assertTrue(self.collector.snapshot()['measurement_loss'])
        self.assertEqual(self.counts()['history_event_rows'],0)

    def test_real_commit_failure_preserves_exception_and_native_rollback(self):
        self.history.db=_CommitProbe(self.history.db,self.collector,fail='before')
        with self.assertRaisesRegex(sqlite3.OperationalError,'offline commit failure'):
            self.event('failed')
        self.assertFalse(self.history.db.in_transaction)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertEqual(self.counts()['history_event_rows'],0)

    def test_uncertain_postcommit_failure_never_invents_completion_clock(self):
        self.history.db=_CommitProbe(self.history.db,self.collector,fail='after')
        with self.assertRaisesRegex(sqlite3.OperationalError,'offline uncertain commit'):
            self.event('uncertain')
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        value=self.collector.snapshot()
        self.assertTrue(value['measurement_loss']);self.assertEqual(value['observed_transactions'],0)
        self.assertIsNone(value['last_post_commit_observation_monotonic_ns'])

    def test_external_transaction_cannot_publish_on_savepoint_release(self):
        self.history.db.execute('BEGIN IMMEDIATE')
        self.event('external')
        self.assertTrue(self.history.db.in_transaction)
        self.assertEqual(self.counts()['history_event_rows'],0)
        self.history.db.execute('COMMIT')
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertTrue(self.collector.snapshot()['measurement_loss'])

    def test_native_duplicates_and_qualified_refused_decisions_are_distinct(self):
        self.event('once');self.event('once')
        for qualified in (True,False):
            for _ in range(2):
                self.history.record_decision('pump','mint',mode='current',observed_at=1000,
                    qualified=qualified,decision=dict(offline=True,qualified=qualified))
        value=self.collector.snapshot();counts=value['committed_row_counts']
        self.assertEqual(counts['history_event_rows'],1)
        self.assertEqual(counts['qualified_decision_rows'],1)
        self.assertEqual(counts['refused_decision_rows'],1)
        for key in ('source_economic_events','source_verified_acks','economic_lambda',
                'economic_mu','economic_backlog','unique_candidate_generations','all_consumer_completion'):
            self.assertIsNone(value[key])
        self.assertEqual(value['cohort_closure'],'UNKNOWN')

    def test_authenticated_canonical_reference_is_one_reference_not_economic_census(self):
        source=self.root/'source.sqlite'
        record=dict(identity='native-source-id',scope='program:pump',kind='event',slot=10,
            transaction_index=0,event_index=0,market_time=1000,
            payload=dict(event=dict(event_type='trade',mint='mint',market_time=1000)))
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE canonical_evidence(identity TEXT PRIMARY KEY,body TEXT,hash TEXT,archive TEXT)')
            db.execute('INSERT INTO canonical_evidence VALUES(?,?,?,NULL)',
                (record['identity'],canonical(record),digest(record)))
        for _ in range(2):
            self.history.append_reference('pump','mint',record,path=source,
                identity='reference-id',kind='pump_trade')
        self.assertEqual(self.counts()['history_reference_rows'],1)
        self.assertEqual(self.counts()['history_event_rows'],0)
        self.assertIsNone(self.collector.snapshot()['source_economic_events'])

    def test_original_64_row_batches_and_economic_sql_unchanged(self):
        from tests.test_candidate_history import CandidateHistoryTests
        rows=CandidateHistoryTests().source_rows(130)
        reference=CandidateHistory(self.root/'reference.sqlite',clock=lambda:1000)
        self.addCleanup(reference.close)
        before=[];after=[]
        reference.db.set_trace_callback(before.append);self.history.db.set_trace_callback(after.append)
        reference.retain_pump_source_history(rows);self.history.retain_pump_source_history(rows)
        self.assertEqual(before,after)
        self.assertEqual(self.history.events('pump','batch-mint'),reference.events('pump','batch-mint'))
        self.assertEqual(sum(sql=='COMMIT' for sql in after),3)
        self.assertEqual(self.collector.snapshot()['observed_transactions'],3)
        self.assertEqual(self.counts()['history_event_rows'],130)
        self.history.retain_pump_source_history(rows)
        self.assertEqual(self.counts()['history_event_rows'],130)

    def test_overflow_never_drops_or_rejects_native_work(self):
        with self.history.transaction():
            for n in range(MAX_RECORDS+1): self.event(str(n))
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],MAX_RECORDS+1)
        self.assertTrue(self.collector.snapshot()['measurement_loss'])
        self.assertEqual(self.counts()['history_event_rows'],0)
        self.assertEqual(self.history._native_commit_observer.frames,[])

    def test_nonblocking_collector_contention_never_changes_native_commit(self):
        self.collector.lock.acquire()
        try: self.event('native-still-commits')
        finally: self.collector.lock.release()
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertTrue(self.collector.snapshot()['measurement_loss'])
        self.assertEqual(self.counts()['history_event_rows'],0)

    def test_observer_error_after_full_does_not_retry_or_rollback_native_work(self):
        # A real reducer failure after SQL COMMIT (rather than a fake successful
        # transaction) must leave exactly one native row and latch UNKNOWN.
        class BrokenDigest(bytes):
            def __add__(self,other):raise ValueError('offline reducer failure')
        self.collector.digest=BrokenDigest(32)
        probe=_CommitProbe(self.history.db,self.collector);self.history.db=probe
        self.event('committed-once')
        self.assertEqual(len(probe.boundaries),2)
        self.assertFalse(self.history.db.in_transaction)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertTrue(self.collector.lost.is_set())

    def test_pons_rollback_and_commit_failure_emit_no_dispositions(self):
        plane=Plane(self.root/'rollback-plane.sqlite',clock=lambda:1000)
        self.addCleanup(plane.close)
        plane._native_commit_observer=self.collector.attach('pons_plane')
        plane.db=_CommitProbe(plane.db,self.collector,fail='before')
        with self.assertRaises(sqlite3.OperationalError):
            plane.observe('pons:failed','pons','1',dict(offline=True),ordering=(1,),
                watermark=dict(block=1),interpretation=dict(policy='offline'),
                observed=1000,deadline=1005,priority=4)
        self.assertIsNone(plane.get('pons:failed'))
        self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0],0)
        self.assertEqual(self.counts()['pons_generation_dispositions'],0)

    def test_native_pons_generations_dispositions_and_consumption_are_separate(self):
        plane=Plane(self.root/'plane.sqlite',clock=lambda:1000)
        self.addCleanup(plane.close)
        plane._native_commit_observer=self.collector.attach('pons_plane')
        for n in (1,2):
            plane.observe('pons:token','pons',str(n),dict(offline=True,n=n),ordering=(n,),
                watermark=dict(block=n),interpretation=dict(policy='offline'),
                observed=1000,deadline=1005,priority=4)
            work=plane.claim(lane='pons')
            self.assertTrue(plane.finish(work,result=dict(offline=True,n=n)))
            self.assertTrue(plane.consume(work['id'],work['generation']))
            self.assertTrue(plane.consume(work['id'],work['generation']))
        rows=plane.db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0]
        self.assertEqual(self.counts()['pons_generation_dispositions'],rows)
        self.assertEqual(self.counts()['pons_candidate_consumptions'],2)
        self.assertEqual(plane.get('pons:token')['generation'],2)
        self.assertIsNone(self.collector.snapshot()['unique_candidate_generations'])
        self.assertEqual(self.collector.snapshot()['pons_pool_universe_closure'],'UNKNOWN')

    def test_two_native_commits_preempted_before_reducer_have_ordered_observation_clocks(self):
        peer=CandidateHistory(self.root/'peer.sqlite',clock=lambda:1000)
        self.addCleanup(peer.close)
        peer._native_commit_observer=self.collector.attach('candidate_history')
        entered=threading.Event();resume=threading.Event();done=threading.Event()
        errors=[]
        original=self.collector.lock
        class PreemptedLock:
            def acquire(inner,blocking):
                self.assertFalse(blocking)
                if threading.current_thread().name=='native-commit-a':
                    # The real COMMIT has returned, but another original owner
                    # gets scheduled before this owner acquires the reducer.
                    self.assertFalse(self.history.db.in_transaction)
                    entered.set()
                    if not resume.wait(2):raise TimeoutError('offline scheduling gate')
                return original.acquire(blocking)
            def release(inner):original.release()
        self.collector.lock=PreemptedLock()
        def publish(owner,identity):
            try:self.event(identity,owner=owner)
            except BaseException as error:errors.append(error)
            finally:
                if owner is peer:done.set()
        first=threading.Thread(target=publish,args=(self.history,'a'),name='native-commit-a')
        second=threading.Thread(target=publish,args=(peer,'b'),name='native-commit-b')
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            second.start();self.assertTrue(done.wait(2))
            second_observation=self.collector.last_post_commit_observation_monotonic_ns
        finally:
            resume.set();first.join(2)
            if second.ident is not None:second.join(2)
        self.assertFalse(first.is_alive());self.assertFalse(second.is_alive());self.assertEqual(errors,[])
        value=self.collector.snapshot()
        self.assertGreaterEqual(value['last_post_commit_observation_monotonic_ns'],second_observation)
        self.assertEqual(value['committed_row_counts']['history_event_rows'],2)
        self.assertFalse(value['measurement_loss'])
        for owner in (self.history,peer):
            self.assertEqual(owner.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)


class NativeCommitCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests import test_child_transport as child
        from tests import test_isolated_native_resources as sizing
        from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
        from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
        await child.ChildTransportTests.asyncSetUp(self)
        self.channel,_=await child.ChildTransportTests.connected(self)
        self.resources=IsolatedNativeResources(self.root/'private-native',
            sizing_facts=sizing.authenticated(sizing.receipt()),clock=lambda:1000)
        self.ports=NativeRunnerPorts(self.resources,self.channel)
        self.addCleanup(self.resources.close);self.addCleanup(self.ports.close)

    async def test_actual_parent_session_cap_owned_native_store_and_restart(self):
        self.assertEqual(self.resources.native_commit_snapshot()['status'],'DISABLED')
        self.resources.enable_native_commit_measurement(self.ports)
        history=self.resources.candidate_history()
        for n in range(20):
            history.record_decision('pump','mint',mode='current',observed_at=1000+n,
                qualified=True,decision=dict(offline=True))
            history.close()
            history=self.resources.candidate_history()
        value=self.resources.native_commit_snapshot()
        self.assertEqual(value['binding']['parent_transport_session'],self.channel.session)
        self.assertEqual(value['binding']['source_commit'],self.resources.facts.value()['source_commit'])
        self.assertEqual(value['committed_row_counts']['qualified_decision_rows'],20)
        self.assertEqual(value['active_stores'],1)
        self.assertFalse(value['measurement_loss'])
        self.assertFalse(self.physical.calls)
        for path in self.resources.root.glob('*.sqlite'):
            with sqlite3.connect(path) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(names&{'genesis','positions','journal','sleeve_genesis','portfolio_events'})

    async def test_parent_session_change_and_late_start_cannot_preserve_measurement(self):
        self.resources.enable_native_commit_measurement(self.ports)
        self.resources.candidate_history()
        with self.assertRaisesRegex(ValueError,'start_order'):
            self.resources.enable_native_commit_measurement(self.ports)
        original=self.channel.session
        try:
            self.channel.session='x'*43
            self.assertTrue(self.resources.native_commit_snapshot()['measurement_loss'])
        finally: self.channel.session=original
        self.assertTrue(self.resources.native_commit_snapshot()['measurement_loss'])

    async def test_optional_first_last_terminal_snapshots_cannot_exhaust_original_receipt_bound(self):
        from meme_machine.operational.isolated_native_source import _persist
        self.resources.enable_native_commit_measurement(self.ports)
        value=dict(financial_authority=False,padding='',first_progress=dict(native=True),
            last_progress=dict(native=True))
        encode=lambda body:json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        value['padding']='x'*(65536-len(encode(value)))
        original=encode(value)
        snapshot=self.resources.native_commit_snapshot()
        value['native_commit_observations']=snapshot
        value['first_progress']['native_commit_observations']=snapshot
        value['last_progress']['native_commit_observations']=snapshot
        self.assertGreater(len(encode(value)),65536)
        _persist(self.resources,value)
        self.assertEqual((self.resources.root/'native-execution.json').read_bytes(),original)
        self.assertEqual(encode(value),original)
        self.assertTrue(self.resources.native_commit_snapshot()['measurement_loss'])
        self.assertFalse(value['financial_authority'])
