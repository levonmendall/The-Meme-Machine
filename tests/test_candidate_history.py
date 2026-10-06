import tempfile
import unittest
from pathlib import Path

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


if __name__=="__main__":
    unittest.main()
