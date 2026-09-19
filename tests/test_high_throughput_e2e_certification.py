import unittest

from tests.high_throughput_e2e_certification import run_certification


class HighThroughputEndToEndCertification(unittest.TestCase):
    def test_connected_high_throughput_certification(self):
        report=run_certification()
        self.assertTrue(report['success'])
        self.assertEqual(report['provider']['rotations'],3)
        self.assertEqual(report['provider']['minimum_interval_seconds'],0.5)
        self.assertEqual(report['evidence']['qualified'],3)
        self.assertTrue(report['stream']['rewarm_proven'])
        self.assertTrue(report['stream']['prewarm_candidate_rejected'])
        self.assertEqual(report['lifecycle']['settled_exits'],3)
        self.assertEqual(report['lifecycle']['pump_settlements'],2)
        self.assertEqual(report['lifecycle']['pumpswap_settlements'],1)
        self.assertEqual(report['lifecycle']['terminal_positions'],0)
        self.assertEqual(report['lifecycle']['terminal_reserved_lamports'],0)
        self.assertEqual(report['lifecycle']['terminal_rent_lamports'],0)
        self.assertTrue(report['accounting']['reconciled'])
        self.assertTrue(report['accounting']['archive_verified'])


if __name__=='__main__':
    unittest.main()
