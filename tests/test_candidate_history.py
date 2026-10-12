import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateDeadlineMissed,CandidateHistory,_enable_wal


class CandidateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"candidate-history.sqlite"
        self.now=[1000.0]
        self.history=CandidateHistory(self.path,clock=lambda:self.now[0],worker_capacity=1)

    def tearDown(self):
        self.history.close();self.tmp.cleanup()

    def test_initial_journal_read_retries_real_startup_lock_without_writer_request(self):
        import sqlite3
        path=Path(self.tmp.name)/'startup.sqlite'
        # An exclusive opener also blocks journal-mode reads, the phase that
        # failed on the host. The existing deadline must cover that phase.
        opener=sqlite3.connect(path,isolation_level=None)
        db=sqlite3.connect(path,isolation_level=None)
        opener.execute('CREATE TABLE retained(value)')
        opener.execute('BEGIN EXCLUSIVE')
        waits=[];sql=[];db.set_trace_callback(sql.append)
        def release(seconds):
            waits.append(seconds);opener.execute('COMMIT')
        try:
            self.assertEqual(_enable_wal(db,seconds=1,sleeper=release),'wal')
            self.assertEqual(len(waits),1)
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0],1000)
            sql.clear()
            self.assertEqual(_enable_wal(db,seconds=1,sleeper=release),'wal')
            self.assertFalse(any('journal_mode=WAL' in row for row in sql))
        finally:db.close();opener.close()

    def test_initial_journal_read_zero_wait_and_nonbusy_errors_are_not_hidden(self):
        import sqlite3
        from unittest.mock import Mock
        busy=sqlite3.OperationalError('database is locked');busy.sqlite_errorcode=sqlite3.SQLITE_BUSY
        corrupt=sqlite3.OperationalError('malformed');corrupt.sqlite_errorcode=sqlite3.SQLITE_CORRUPT
        for error in (busy,corrupt):
            db=Mock();sleeper=Mock()
            def execute(sql):
                if sql=='PRAGMA journal_mode':raise error
                return Mock()
            db.execute.side_effect=execute
            with self.assertRaises(sqlite3.OperationalError) as caught:
                _enable_wal(db,seconds=0,sleeper=sleeper)
            self.assertIs(caught.exception,error);sleeper.assert_not_called()
            self.assertEqual(db.execute.call_args.args,('PRAGMA busy_timeout=0',))

    def test_initial_journal_read_contention_keeps_original_deadline(self):
        import sqlite3
        from unittest.mock import Mock
        error=sqlite3.OperationalError('locked');error.sqlite_errorcode=sqlite3.SQLITE_LOCKED
        db=Mock();now=[0.0];waits=[]
        def execute(sql):
            if sql=='PRAGMA journal_mode':raise error
            return Mock()
        def sleep(seconds):waits.append(seconds);now[0]+=seconds
        db.execute.side_effect=execute
        with self.assertRaises(sqlite3.OperationalError):
            _enable_wal(db,seconds=.12,monotonic=lambda:now[0],sleeper=sleep)
        self.assertAlmostEqual(sum(waits),.12)
        self.assertEqual(db.execute.call_args.args,('PRAGMA busy_timeout=120',))

    def test_kind_filter_resolves_only_requested_canonical_records_and_survives_restart(self):
        import sqlite3,json
        from meme_machine.runtime.journal import canonical,digest
        source=Path(self.tmp.name)/'source.sqlite'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE canonical_evidence(identity TEXT PRIMARY KEY,body TEXT,hash TEXT,archive TEXT)')
            for i,kind in enumerate(('create','trade','trade')):
                record=dict(identity=str(i),scope='program:pump',kind='event',slot=10+i,
                    transaction_index=i,event_index=0,market_time=1000,
                    payload={'event':{'event_type':kind,'mint':'mint','market_time':1000}})
                db.execute('INSERT INTO canonical_evidence VALUES(?,?,?,NULL)',
                    (str(i),canonical(record),digest(record)))
                db.commit()
                self.history.append_reference('pump','mint',record,path=source,identity=str(i),kind='pump_'+kind)
        self.history.append_event('pump','mint',identity='legacy',slot=9,transaction_index=0,
            event_index=0,market_time=999,kind='pump_create',payload={'event_type':'create','mint':'mint'})
        expected=[r for r in self.history.events('pump','mint') if r['kind']=='pump_create']
        with patch.object(self.history,'_reference_body',wraps=self.history._reference_body) as expand:
            self.assertEqual(self.history.events('pump','mint',kind='pump_create'),expected)
            self.assertEqual(expand.call_count,1)
            self.assertEqual(self.history.events('pump','mint',kind='pump_migration'),[])
            self.assertEqual(expand.call_count,1)
        self.assertEqual(self.history.events('pump','mint',kind='pump_create',through=999),expected[:1])
        self.history.close();self.history=CandidateHistory(self.path,clock=lambda:self.now[0])
        self.assertEqual(self.history.events('pump','mint',kind='pump_create'),expected)
        with sqlite3.connect(source) as db:
            db.execute("UPDATE canonical_evidence SET hash=? WHERE identity='0'",('f'*64,))
        with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
            self.history.events('pump','mint',kind='pump_create')

    def test_candidate_retention_has_no_count_cap(self):
        for i in range(256):
            self.history.observe("pump",f"mint-{i}",surface="pumpswap",
                observed_at=1000+i,decision_deadline=5000+i,metadata={"rank":i})
        self.assertEqual(self.history.telemetry()["candidates"],256)
        self.assertEqual(self.history.candidate("pump","mint-255")["metadata"]["rank"],255)

    def test_observed_pump_creation_reuses_original_identity_without_qualifying_or_caching_missing(self):
        from meme_machine.lanes.pump import runner
        from unittest.mock import Mock
        creation=dict(event_type='create',mint='mint',creator='original',market_time=1000)
        tape=Mock();tape.creation.return_value=creation;created={}
        first=runner._observed_creation(tape,created,'mint')
        self.assertIs(first,creation);self.assertEqual(created,{})
        created['mint']=dict(creation=first,pregrad_wallets=set(),graduated=False)
        for _ in range(1000):self.assertIs(runner._observed_creation(tape,created,'mint'),first)
        tape.creation.assert_called_once_with('mint')
        self.assertNotIn('qualified',created['mint']);self.assertFalse(created['mint']['graduated'])
        # Missing lineage is never negatively cached. Newly published evidence
        # remains discoverable through the original authenticated tape path.
        tape.creation.side_effect=[None,dict(creation,mint='new')]
        self.assertIsNone(runner._observed_creation(tape,created,'new'))
        self.assertEqual(runner._observed_creation(tape,created,'new')['mint'],'new')
        self.assertNotIn('new',created)
        tape.creation.side_effect=ValueError('candidate_history_corruption')
        with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
            runner._observed_creation(tape,created,'unverified')

    def source_rows(self,count=130):
        return [dict(identity='source-'+str(n),slot=10+n,transaction_index=1,event_index=0,
            market_time=1000+n,event=dict(mint='batch-mint',event_type='trade',market_time=1000+n,
                native_buy=n)) for n in range(count)]

    def test_source_history_has_bounded_full_commits_and_preserves_all_economics(self):
        rows=self.source_rows();commits=[]
        self.history.db.set_trace_callback(lambda sql:commits.append(sql) if sql=='COMMIT' else None)
        self.assertEqual(self.history.retain_pump_source_history(rows),130)
        self.assertEqual(len(commits),3)
        before=self.history.events('pump','batch-mint')
        self.assertEqual([r['payload']['native_buy'] for r in before],list(range(130)))
        self.assertEqual(self.history.retain_pump_source_history(rows),130)
        self.assertEqual(self.history.events('pump','batch-mint'),before)
        self.history.db.set_trace_callback(None)
        self.history.close();self.history=CandidateHistory(self.path,clock=lambda:self.now[0])
        self.assertEqual(self.history.events('pump','batch-mint'),before)

    def test_source_batch_failure_rolls_back_and_replay_retains_original_facts(self):
        rows=self.source_rows(8);original=self.history.append_event
        def broken(*args,**kw):
            if kw['identity']=='pump-source:source-4':raise RuntimeError('offline_commit_fault')
            return original(*args,**kw)
        with patch.object(self.history,'append_event',side_effect=broken):
            with self.assertRaisesRegex(RuntimeError,'offline_commit_fault'):
                self.history.retain_pump_source_history(rows)
        self.assertIsNone(self.history.candidate('pump','batch-mint'))
        self.assertEqual(self.history.events('pump','batch-mint'),[])
        self.assertEqual(self.history.retain_pump_source_history(rows),8)
        self.assertEqual(len(self.history.events('pump','batch-mint')),8)

    def test_current_reuses_only_matching_committed_tape_history_and_deadline_policy(self):
        from meme_machine.lanes.pump import runner
        rows=self.source_rows(1);rows[0]['event'].update(event_type='migration',pool='native-pool')
        horizon=max(runner.POLICY.max_postgrad_entry_age_s,600)
        count=self.history.retain_pump_source_history(rows,graduation_horizon=horizon)
        tape=SimpleNamespace(candidate_history_rows=rows,candidate_history_retained_count=count,
            candidate_history_retained_path=str(self.path.resolve()),candidate_history_graduation_horizon=horizon)
        with patch.object(runner,'CANDIDATE_HISTORY',self.history),patch.object(self.history,'retain_pump_source_history',wraps=self.history.retain_pump_source_history) as write:
            self.assertEqual(runner._retain_tape_history(tape),1);write.assert_not_called()
            tape.candidate_history_graduation_horizon=None
            self.assertEqual(runner._retain_tape_history(tape),1);write.assert_called_once()
            write.reset_mock();tape.candidate_history_graduation_horizon=horizon
            tape.candidate_history_retained_path='another-store'
            self.assertEqual(runner._retain_tape_history(tape),1);write.assert_called_once()
        self.assertEqual(self.history.candidate('pump','batch-mint')['decision_deadline'],1000+horizon)

    def test_readiness_without_waiters_retains_proofs_without_rescanning_them(self):
        scope='candidate:pump:program';db=self.history.db
        with self.history.transaction():
            db.executemany('INSERT INTO work_history_proofs VALUES(?,?,?,?,?,?)',
                [(str(n),scope,n,n,999,'a'*64) for n in range(10000)])
        steps=[];db.set_progress_handler(lambda:steps.append(1) or 0,1000)
        try:self.history.commit_history_readiness(scope,10000,10000,proof_hash='b'*64)
        finally:db.set_progress_handler(None,0)
        self.assertEqual(steps,[],'idle publication rescanned retained history')
        self.history.close();self.history=CandidateHistory(self.path,clock=lambda:self.now[0],worker_capacity=1)
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM work_history_proofs WHERE scope=?',(scope,)).fetchone()[0],10001)
        work=self.history.enqueue('pump','mint',kind='deep_watch',ready_at=1000,deadline=1020,estimate_seconds=1)
        self.history.wait_for_history(work,scope,10,12,retry_at=1010)
        self.history.commit_history_readiness(scope,10001,10001,proof_hash='c'*64,available=1001)
        self.assertIsNone(self.history.db.execute('SELECT 1 FROM work_history_requirements WHERE work_id=?',(work,)).fetchone())
        self.assertEqual(self.history.db.execute('SELECT deadline FROM work WHERE id=?',(work,)).fetchone()[0],1020)
        self.assertEqual(len(self.history.work_observations(kind='history_ready')),1)

    def test_waiting_work_still_requires_contiguous_point_in_time_proofs(self):
        scope='candidate:pump:mint'
        self.history.commit_history_readiness(scope,10,12,proof_hash='f'*64,available=1010)
        work=self.history.enqueue('pump','mint',kind='deep_watch',ready_at=1000,deadline=1020,estimate_seconds=1)
        self.history.wait_for_history(work,scope,10,12,retry_at=1015)
        self.history.commit_history_readiness(scope,10,10,proof_hash='a'*64,available=1001)
        self.assertIsNotNone(self.history.db.execute('SELECT 1 FROM work_history_requirements WHERE work_id=?',(work,)).fetchone())
        self.history.commit_history_readiness(scope,12,12,proof_hash='b'*64,available=1002)
        self.assertIsNotNone(self.history.db.execute('SELECT 1 FROM work_history_requirements WHERE work_id=?',(work,)).fetchone())
        self.history.commit_history_readiness(scope,11,11,proof_hash='c'*64,available=1003)
        self.assertIsNone(self.history.db.execute('SELECT 1 FROM work_history_requirements WHERE work_id=?',(work,)).fetchone())
        self.assertEqual(self.history.db.execute('SELECT deadline FROM work WHERE id=?',(work,)).fetchone()[0],1020)

    def test_economic_events_are_returned_in_canonical_order(self):
        self.history.observe("pump","mint",surface="pumpswap",observed_at=1000)
        rows=[
            dict(identity="b",slot=10,transaction_index=2,event_index=0,market_time=1001),
            dict(identity="a",slot=10,transaction_index=1,event_index=3,market_time=1001),
            dict(identity="c",slot=10,transaction_index=None,event_index=0,market_time=1001),
            dict(identity="z",slot=9,transaction_index=8,event_index=1,market_time=1000),
        ]
        for row in rows:
            self.history.append_event("pump","mint",kind="swap",payload={"id":row["identity"]},**row)
        self.assertEqual([r["identity"] for r in self.history.events("pump","mint")],
                         ["z","a","b","c"])

    def test_funding_outcome_requires_and_follows_qualification(self):
        with self.assertRaisesRegex(ValueError,"funding_without_decision"):
            self.history.record_funding("missing","pump","mint",status="denied",at=1002,
                                        reason="capital_occupied")
        decision=self.history.record_decision("pump","mint",mode="current",observed_at=1001,
            qualified=True,decision={"score":91,"reasons":[]})
        first=self.history.record_funding(decision,"pump","mint",status="denied",at=1002,
                                    reason="capital_occupied",details={"available":0})
        # Retries cannot manufacture a second outcome or mutate qualification.
        self.assertEqual(first,self.history.record_funding(
            decision,"pump","mint",status="denied",at=1003,
            reason="capital_occupied",details={"available":0}))
        with self.assertRaisesRegex(ValueError,"funding_outcome_conflict"):
            self.history.record_funding(decision,"pump","mint",status="funded",at=1004)
        row=self.history.funding_outcome(decision)
        self.assertEqual((row["status"],row["reason"]),("denied","capital_occupied"))
        qualified=self.history.db.execute("SELECT qualified FROM decisions WHERE id=?",(decision,)).fetchone()[0]
        self.assertEqual(qualified,1)

    def test_expensive_work_is_edf_and_never_dropped_by_capacity(self):
        later=self.history.enqueue("meteora","later",kind="warmup",ready_at=1000,deadline=1040,
                                   estimate_seconds=5,payload={"candidate":"later"})
        earlier=self.history.enqueue("pump","earlier",kind="deep_watch",ready_at=1000,deadline=1020,
                                     estimate_seconds=5,payload={"candidate":"earlier"})
        first=self.history.claim("worker-a",now=1000)
        self.assertEqual(first["id"],earlier)
        self.assertIsNone(self.history.claim("worker-b",now=1000))
        self.assertEqual(self.history.db.execute("SELECT status FROM work WHERE id=?",(later,)).fetchone()[0],
                         "pending")
        self.history.complete(earlier,now=1001)
        self.assertEqual(self.history.claim("worker-b",now=1001)["id"],later)

    def test_deadline_miss_is_explicit_infrastructure_failure(self):
        self.history.enqueue("pump","mint",kind="deep_watch",ready_at=1000,deadline=1005,
                             estimate_seconds=2)
        with self.assertRaises(CandidateDeadlineMissed):
            self.history.claim("worker",now=1006)

    def test_saturation_does_not_discard_a_still_feasible_candidate(self):
        self.history.enqueue("meteora","occupier",kind="warmup",ready_at=1000,deadline=1100,
                             estimate_seconds=40)
        self.history.claim("worker-a",now=1000)
        urgent=self.history.enqueue("pump","urgent",kind="deep_watch",ready_at=1000,
                                    deadline=1010,estimate_seconds=20)
        self.assertIsNone(self.history.claim("worker-b",now=1000))
        self.assertEqual(self.history.db.execute(
            "SELECT status FROM work WHERE id=?",(urgent,)).fetchone()[0],"pending")
        occupier=self.history.db.execute("SELECT id FROM work WHERE candidate='occupier'").fetchone()[0]
        self.history.complete(occupier,now=1001)
        self.assertEqual(self.history.claim("worker-b",now=1001)['id'],urgent)
        self.assertEqual(self.history.complete(urgent,now=1002)['status'],'complete')
        self.assertEqual(self.history.telemetry()['deadline_misses'],0)

    def test_conservative_estimate_cannot_preempt_an_unelapsed_deadline(self):
        identity=self.history.enqueue('meteora','feasible',kind='warmup',ready_at=1000,
                                      deadline=1020,estimate_seconds=147)
        self.assertEqual(self.history.claim('worker',now=1000)['id'],identity)
        self.assertEqual(self.history.complete(identity,now=1014)['status'],'complete')

    def test_late_completion_is_a_durable_deadline_failure(self):
        identity=self.history.enqueue('meteora','slow',kind='warmup',ready_at=1000,
                                      deadline=1020,estimate_seconds=5)
        self.history.claim('worker',now=1000)
        self.assertEqual(self.history.complete(identity,now=1021)['status'],'deadline_missed')
        self.assertTrue(self.history.work_observations(kind='deadline_missed')[0]
                        ['details']['completed_after_deadline'])

    def test_candidate_metadata_merges_across_promotion_and_reopens_concurrently(self):
        self.history.observe("pump","mint",surface="pump.fun",observed_at=1000,
                             metadata={"creator":"c"})
        self.history.observe("pump","mint",surface="pumpswap",observed_at=1010,
                             decision_deadline=1600,metadata={"pool":"p"})
        row=self.history.candidate("pump","mint")
        self.assertEqual(row["metadata"],{"creator":"c","pool":"p"})
        second=CandidateHistory(self.path,clock=lambda:self.now[0],worker_capacity=1)
        try:
            self.assertEqual(second.candidates(lane="pump")[0]["surface"],"pumpswap")
        finally:
            second.close()

    def test_pump_qualification_is_durable_before_zero_capital_denial(self):
        from meme_machine.lanes.pump import runner
        signal=runner.SignalVector(
            mint="funding-independent",observed_at=1000,surface="pump.fun",
            phase=runner.MODE_LATE_CURVE,curve_progress_bps=8200,
            curve_velocity_bps_per_s=80,curve_acceleration_bps_per_s2=5,
            independent_buyer_clusters=30,buyer_growth=8,
            repeat_buyer_clusters=4,repeat_buy_share_bps=3000,
            net_buy_share_bps=8500,concentration_bps=1500,extension_bps=2500,
            immediate_roundtrip_loss_bps=300,skilled_wallet_clusters=2,
            creator_quality_bps=7000,creator_history_launches=10,
            quote_relative_return_bps=800)
        qualified=runner.qualify(signal)
        self.assertTrue(qualified.qualified)
        prior=runner.CANDIDATE_HISTORY;runner.CANDIDATE_HISTORY=self.history
        try:
            decision=self.history.record_decision(
                "pump",signal.mint,mode=signal.phase,observed_at=signal.observed_at,
                qualified=True,decision={"qualification":"same-regardless-of-capital"})
            with patch.object(runner,"_current_pump_sizing",return_value=dict(
                    realized_equity=500,target=25,allocatable_target=0,available=0)):
                admitted=runner._reserve_position(
                    {"qualifiers":[],"funding_denials":[]},{},{},signal,qualified,
                    {"available_time":1001},runner.MODE_LATE_CURVE,1500,
                    decision_id=decision)
            self.assertFalse(admitted)
            self.assertEqual(self.history.funding_outcome(decision)["status"],"denied")
            stored=self.history.db.execute(
                "SELECT qualified FROM decisions WHERE id=?",(decision,)).fetchone()[0]
            self.assertEqual(stored,1)
            # Qualification itself has no capital input and remains byte-for-byte
            # identical under zero/normal/fully-committed funding snapshots.
            for available in (0,25,500):
                with patch.object(runner,"_current_pump_sizing",return_value=dict(
                        realized_equity=500,target=25,allocatable_target=min(25,available),
                        available=available)):
                    self.assertEqual(runner.qualify(signal),qualified)
        finally:
            runner.CANDIDATE_HISTORY=prior

    def test_pump_promotion_replays_ordered_pregraduation_economics(self):
        from meme_machine.lanes.pump import runner
        prior=runner.CANDIDATE_HISTORY;runner.CANDIDATE_HISTORY=self.history
        class Stream:
            def __init__(self):self.pools=[]
            def add_address(self,pool):self.pools.append(pool);return pool
        class Confirmations:
            def __init__(self):self.created=[];self.graduated=[]
            def observe_creation(self,row):self.created.append(row["mint"])
            def observe_graduation(self,mint,at):self.graduated.append((mint,at))
        try:
            rows=[
                dict(identity="create",slot=10,transaction_index=2,event_index=0,market_time=1000,
                     event=dict(event_type="create",mint="mint",market_time=1000,creator="creator")),
                dict(identity="trade",slot=11,transaction_index=1,event_index=3,market_time=1005,
                     event=dict(event_type="trade",mint="mint",market_time=1005,wallet="buyer",
                                real_token_reserves=5)),
                dict(identity="migration",slot=12,transaction_index=0,event_index=1,market_time=1010,
                     event=dict(event_type="migration",mint="mint",market_time=1010,pool="POOL")),
            ]
            self.assertEqual(runner._retain_pump_source_history(rows),3)
            persisted=self.history.events("pump","mint")
            self.assertEqual([r["kind"] for r in persisted],
                             ["pump_create","pump_trade","pump_migration"])
            self.assertTrue(all("transaction" not in r["payload"] and "meta" not in r["payload"]
                                for r in persisted))
            created={};postgrad={};stream=Stream();confirm=Confirmations()
            self.assertEqual(runner._restore_observed_pump_candidates(
                created,postgrad,stream,object(),confirm,1020),1)
            self.assertEqual(created["mint"]["pregrad_wallets"],{"buyer"})
            self.assertTrue(created["mint"]["graduated"])
            self.assertEqual(postgrad["mint"]["pool"],"POOL")
            self.assertEqual(stream.pools,["POOL"])
            self.assertEqual(confirm.created,["mint"])
            self.assertEqual(confirm.graduated,[("mint",1010)])
        finally:
            runner.CANDIDATE_HISTORY=prior


if __name__=="__main__":
    unittest.main()
