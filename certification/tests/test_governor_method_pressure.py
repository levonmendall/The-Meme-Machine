import tempfile
import unittest
from unittest.mock import patch

from certification.governor import Governor


class GovernorMethodPressureTests(unittest.TestCase):
    def test_signature_rate_limit_is_method_scoped_without_global_cooldown(self):
        with tempfile.TemporaryDirectory() as td, patch(
            "certification.governor.time.monotonic", return_value=100.0
        ):
            g=Governor(td+"/governor.sqlite")
            g.rate_limited("solana",["getSignaturesForAddress"])
            status=g.status()
        provider=status["providers"][0]
        method=next(row for row in status["method_pressure"]
                    if row["method"]=="getSignaturesForAddress")
        self.assertEqual(provider["cooldown"],0)
        self.assertEqual(provider["rate_errors"],1)
        self.assertEqual(method["rate_errors"],1)
        self.assertEqual(method["rate_streak"],1)
        self.assertEqual(method["cooldown_remaining_seconds"],15.0)

    def test_other_rate_limits_keep_provider_wide_cooldown(self):
        with tempfile.TemporaryDirectory() as td, patch(
            "certification.governor.time.monotonic", return_value=100.0
        ):
            g=Governor(td+"/governor.sqlite")
            g.rate_limited("solana",["getTransaction"])
            status=g.status()
        provider=status["providers"][0]
        method=next(row for row in status["method_pressure"]
                    if row["method"]=="getTransaction")
        self.assertEqual(provider["cooldown"],108.0)
        self.assertEqual(provider["rate_errors"],1)
        self.assertEqual(method["cooldown_remaining_seconds"],8.0)

    def test_signature_backoff_does_not_raise_physical_ceiling(self):
        with tempfile.TemporaryDirectory() as td:
            g=Governor(td+"/governor.sqlite",interval=.5)
            self.assertEqual(g.interval,.5)
            with self.assertRaisesRegex(ValueError,"certification_rate_increase_forbidden"):
                Governor(td+"/faster.sqlite",interval=.49)


if __name__=="__main__":
    unittest.main()
