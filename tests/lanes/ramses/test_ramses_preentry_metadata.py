"""Offline regression from the preserved Ramses hour 35935431384.

Run with PYTHONPATH set to the composed Ramses lane. This test makes no RPCs.
The captured public annotation differs from the authoritative receipt annotation;
every other log field, receipt identity and block hash remains authoritative.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses import ramses_all_pool_lifecycle as lifecycle


FIXTURE = Path(__file__).parent / "fixtures" / "ramses_preentry_35935431384.json"


class ArchivedRpc:
    def __init__(self, case):
        self.case = case
        self.requests = []

    def receipts(self, identities, *, scope):
        self.requests.append(("receipts", identities, scope))
        return [deepcopy(self.case["receipt"]) for _ in identities]

    def blocks(self, numbers, *, scope):
        self.requests.append(("blocks", numbers, scope))
        return [deepcopy(self.case["header"]) for _ in numbers]


class RamsesCapturedPreentryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE.read_text())["cases"]

    def authenticate(self, case):
        rpc = ArchivedRpc(case)
        row = {"pool": case["pool"], "prehistory": case["expected_history"]}
        with patch.object(lifecycle, "_batch_logs", return_value=case["logs"]) as logs:
            history, auth = lifecycle._canonical_preentry_history(rpc, row, case["screen"])
        self.assertEqual(logs.call_args.args[:4], (
            rpc, case["screen"]["lookback_start_block"],
            case["screen"]["finalized_block"], case["pool"],
        ))
        self.assertEqual(logs.call_args.kwargs["scope"], "qualifier_auth")
        self.assertEqual(rpc.requests, [
            ("receipts", [(case["receipt"]["transactionHash"], case["receipt"]["blockHash"])], "qualifier_auth"),
            ("blocks", [int(case["header"]["number"], 16)], "qualifier_auth"),
        ])
        return history, auth

    def aligned(self, original):
        """Isolate each negative control from the separately demonstrated defect."""
        case = deepcopy(original)
        event = case["logs"][0]
        receipt_log = next(log for log in case["receipt"]["logs"]
                           if log["logIndex"] == event["logIndex"])
        event["blockTimestamp"] = receipt_log["blockTimestamp"]
        return case

    def test_captured_optional_timestamp_difference_authenticates_exact_history(self):
        for original in self.cases:
            with self.subTest(pool=original["pool"]):
                self.assertEqual(original["logs"][0]["blockTimestamp"], "0x0")
                history, auth = self.authenticate(deepcopy(original))
                self.assertEqual(history, original["expected_history"])
                self.assertTrue(auth["authenticated"])
                self.assertTrue(auth["identity_match"])
                self.assertEqual((auth["swap_logs"], auth["transactions"], auth["blocks"]), (1, 1, 1))

    def test_optional_timestamp_can_be_absent_without_changing_history(self):
        for original in self.cases:
            case = deepcopy(original)
            case["logs"][0].pop("blockTimestamp")
            with self.subTest(pool=case["pool"]):
                history, auth = self.authenticate(case)
                self.assertEqual(history, original["expected_history"])
                self.assertTrue(auth["authenticated"])

    def test_real_event_identity_payload_and_unknown_metadata_conflicts_fail_closed(self):
        original = self.cases[0]
        event = original["logs"][0]
        changed_data = event["data"][:-1] + ("1" if event["data"][-1] != "1" else "2")
        mutations = {
            "data": changed_data,
            "address": "0x" + "11" * 20,
            "blockHash": "0x" + "11" * 32,
            "transactionHash": "0x" + "22" * 32,
            "transactionIndex": hex(int(event["transactionIndex"], 16) + 1),
            "logIndex": hex(int(event["logIndex"], 16) + 1),
            "removed": True,
            "unexpectedExtension": "must-not-be-ignored",
        }
        for key, value in mutations.items():
            case = self.aligned(original)
            case["logs"][0][key] = value
            with self.subTest(field=key), self.assertRaises(BoundaryError):
                self.authenticate(case)

    def test_receipt_and_header_disagreement_still_fail_closed(self):
        for owner, key, value in (
            ("receipt", "status", "0x0"),
            ("receipt", "blockHash", "0x" + "11" * 32),
            ("receipt", "transactionHash", "0x" + "22" * 32),
            ("receipt", "transactionIndex", "0xffff"),
            ("header", "hash", "0x" + "33" * 32),
        ):
            case = self.aligned(self.cases[0])
            case[owner][key] = value
            with self.subTest(owner=owner, field=key), self.assertRaises(BoundaryError):
                self.authenticate(case)

    def test_conflicting_duplicate_remains_rejected(self):
        case = self.aligned(self.cases[0])
        duplicate = deepcopy(case["logs"][0])
        duplicate["data"] = duplicate["data"][:-1] + "1"
        case["logs"].append(duplicate)
        with self.assertRaisesRegex(BoundaryError, "qualifier_history_conflicting_duplicate"):
            self.authenticate(case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
