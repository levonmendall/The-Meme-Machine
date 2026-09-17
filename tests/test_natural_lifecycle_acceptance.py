import unittest

from tests.natural_pumpswap_lifecycle import (
    _natural_order_packet,
    _prospective_admission,
    _seed_records,
)


class NaturalLifecycleAdmission(unittest.TestCase):
    def setUp(self):
        self.records = [
            dict(wallet='watch-wallet', eligible_after=100, source='watchlist'),
            dict(wallet='fixture-wallet', eligible_after=0, source='captured_fixture'),
        ]

    def test_only_strictly_post_admission_watchlist_nomination_is_valid(self):
        valid, record = _prospective_admission(
            self.records, dict(wallet='watch-wallet', market_time=101))
        self.assertTrue(valid)
        self.assertEqual(record['eligible_after'], 100)

        self.assertFalse(_prospective_admission(
            self.records, dict(wallet='watch-wallet', market_time=100))[0])
        self.assertFalse(_prospective_admission(
            self.records, dict(wallet='watch-wallet', market_time=99))[0])
        self.assertFalse(_prospective_admission(
            self.records, dict(wallet='fixture-wallet', market_time=101))[0])
        self.assertFalse(_prospective_admission(
            self.records, dict(wallet='unknown-wallet', market_time=101))[0])

    def test_acceptance_packet_publishes_admission_boundary(self):
        order = dict(
            nomination=dict(wallet='watch-wallet', market_time=101),
            evidence=dict(
                covered=True,
                snapshot=dict(kind='real', protocol='pump.fun', network='solana-mainnet'),
            ),
        )
        packet = _natural_order_packet(order, self.records)
        self.assertTrue(packet['prospective_admission_valid'])
        self.assertEqual(packet['scout_source'], 'watchlist')
        self.assertEqual(packet['scout_eligible_after'], 100)
        self.assertEqual(packet['scout_market_time'], 101)

    def test_live_seed_records_exclude_captured_fixture_sources(self):
        records = _seed_records()
        self.assertTrue(records)
        self.assertTrue(all(item['source'] == 'watchlist' for item in records))
        self.assertTrue(all('eligible_after' in item for item in records))


if __name__ == '__main__':
    unittest.main()
