import unittest

from robinhood_research.evidence_queue import DeadlineEvidenceQueue


def event(i,block=100):
    return {
        "transactionHash":f"0x{i:064x}",
        "logIndex":hex(i),
        "blockNumber":hex(block),
        "transactionIndex":hex(i),
    }


class EvidenceQueueTests(unittest.TestCase):
    def test_burst_candidates_are_retained_and_ordered(self):
        q=DeadlineEvidenceQueue(limit=4,nominal_deadline_seconds=5)
        self.assertTrue(q.enqueue(event(2),now=10.0))
        self.assertTrue(q.enqueue(event(1),now=10.0))
        first=q.pop(now=10.2)
        second=q.pop(now=10.2)
        self.assertEqual(first["event"]["transactionIndex"],hex(1))
        self.assertEqual(second["event"]["transactionIndex"],hex(2))
        self.assertEqual(q.telemetry()["processed"],2)

    def test_expired_candidate_never_dispatches(self):
        q=DeadlineEvidenceQueue(limit=4,nominal_deadline_seconds=5)
        q.enqueue(event(1),now=10.0)
        self.assertIsNone(q.pop(now=15.1))
        self.assertEqual(q.telemetry()["expired_before_evidence"],1)

    def test_deadline_headroom_can_fail_closed_before_dispatch(self):
        q=DeadlineEvidenceQueue(limit=4,nominal_deadline_seconds=5)
        q.enqueue(event(1),now=10.0)
        self.assertIsNone(q.pop(now=14.7,minimum_remaining_seconds=0.5))
        self.assertEqual(q.telemetry()["deadline_insufficient"],1)

    def test_capacity_keeps_earlier_deadline(self):
        q=DeadlineEvidenceQueue(limit=1,nominal_deadline_seconds=5)
        q.enqueue(event(1),now=10.0)
        self.assertFalse(q.enqueue(event(2),now=11.0))
        row=q.pop(now=11.1)
        self.assertEqual(row["event"]["transactionHash"],event(1)["transactionHash"])
        self.assertEqual(q.telemetry()["capacity_skipped"],1)


if __name__=="__main__":
    unittest.main()
