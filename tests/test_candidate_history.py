import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateDeadlineMissed,CandidateHistory


class CandidateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"candidate-history.sqlite"
        self.now=[1000.0]
        self.history=CandidateHistory(self.path,clock=lambda:self.now[0],worker_capacity=1)

    def tearDown(self):
        self.history.close();self.tmp.cleanup()

    def test_candidate_retention_has_no_count_cap(self):
        for i in range(256):
            self.history.observe("pump",f"mint-{i}",surface="pumpswap",
                observed_at=1000+i,decision_deadline=5000+i,metadata={"rank":i})
        self.assertEqual(self.history.telemetry()["candidates"],256)
        self.assertEqual(self.history.candidate("pump","mint-255")["metadata"]["rank"],255)

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

    def test_saturation_fails_before_a_candidate_can_be_starved_past_deadline(self):
        self.history.enqueue("meteora","occupier",kind="warmup",ready_at=1000,deadline=1100,
                             estimate_seconds=40)
        self.history.claim("worker-a",now=1000)
        urgent=self.history.enqueue("pump","urgent",kind="deep_watch",ready_at=1000,
                                    deadline=1010,estimate_seconds=20)
        with self.assertRaises(CandidateDeadlineMissed) as caught:
            self.history.claim("worker-b",now=1000)
        self.assertEqual(caught.exception.work["id"],urgent)
        self.assertEqual(self.history.db.execute(
            "SELECT status FROM work WHERE id=?",(urgent,)).fetchone()[0],"pending")

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
