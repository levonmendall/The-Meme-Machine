"""Captured provider evidence, explicitly distinct from synthetic economics."""
import json
from pathlib import Path
import unittest

from robinhood_research import BoundaryError
from robinhood_research.evidence import Stamp
from robinhood_research.provider import Rpc


class CapturedProviderTests(unittest.TestCase):
    def setUp(self):
        self.report=json.loads((Path(__file__).parent/'fixtures/mainnet_read_summary.json').read_text())

    def test_captured_mainnet_identity_and_bounded_provider_evidence(self):
        r=self.report
        rpc=Rpc('https://fixture.invalid',transport=lambda *_:hex(r['chain_id']))
        self.assertEqual(rpc.verify_chain(),4663)
        self.assertEqual(r['provider']['requests'],15)
        self.assertEqual(r['provider']['failures'],{})
        self.assertEqual(r['receipts_verified'],3)
        self.assertTrue(r['historical_eth_call'])
        self.assertFalse(r['protocol_identity_verified'])

    def test_captured_finalized_lag_cannot_be_current_quote(self):
        r=self.report
        block=r['finalized']
        st=Stamp(4663,int(block['number'],16),block['hash'],int(block['timestamp'],16),
                 r['started_at'],'finalized','captured')
        with self.assertRaisesRegex(BoundaryError,'stale_state'):
            st.check(r['started_at'],5)
        # The same record is usable for historical indexing, not backdated entry.
        st.check(r['started_at'],86400)

    def test_captured_reads_do_not_claim_a_trade(self):
        self.assertEqual(self.report['natural_candidates'],0)
        self.assertEqual(self.report['paper_lifecycles'],0)
        self.assertEqual(self.report['dlmm_observations'],0)
