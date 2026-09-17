import inspect
import tempfile
import unittest
from pathlib import Path

from meme_machine import engine, pump
from meme_machine.fomo_shadow import (
    FomoScanClient,
    FomoSignalBook,
    normalize_token_board,
)
from meme_machine.store import Store
from tests.support import MINT

MINT2 = pump.b58(bytes([17]) * 32)
MINT3 = pump.b58(bytes([18]) * 32)


def board_payload(mint=MINT, rank=1, at=100):
    return {'at': at, 'items': [{'tokenAddress': mint, 'rank': rank}]}


class FomoShadowScaffold(unittest.TestCase):
    def test_token_board_normalization_is_solana_only_and_point_in_time(self):
        rows = normalize_token_board('trending', board_payload(rank=7, at=100), observed_at=101)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].mint, MINT)
        self.assertEqual(rows[0].rank, 7)
        self.assertEqual(rows[0].sampled_at, 100)
        self.assertEqual(rows[0].observed_at, 101)
        with self.assertRaisesRegex(ValueError, 'invalid_solana_mint'):
            normalize_token_board(
                'trending',
                {'items': [{'tokenAddress': '0x1234', 'rank': 1}]},
                observed_at=101,
            )
        with self.assertRaisesRegex(ValueError, 'future_fomo_snapshot'):
            normalize_token_board('trending', board_payload(at=200), observed_at=100)

    def test_scores_are_deterministic_research_only_and_have_no_authority(self):
        book = FomoSignalBook()
        book.ingest('trending', board_payload(rank=20, at=100), observed_at=100)
        book.ingest('trending', board_payload(rank=5, at=130), observed_at=130)
        book.ingest('most-held', board_payload(rank=10, at=130), observed_at=130)
        book.ingest('graduated', board_payload(rank=3, at=130), observed_at=130)

        score = book.score(MINT, now=131)
        again = book.score(MINT, now=131)
        self.assertEqual(score, again)
        self.assertTrue(score.available)
        self.assertEqual(score.trending_rank, 5)
        self.assertEqual(score.trending_rank_improvement, 15)
        self.assertGreater(score.directional_attention_score, 0)
        self.assertGreater(score.dlmm_flow_score, 0)
        self.assertTrue(score.research_only)
        self.assertFalse(score.directional_authority)
        self.assertFalse(score.dlmm_authority)
        self.assertFalse(score.order_authority)

        stale = book.score(MINT, now=400)
        self.assertFalse(stale.available)
        self.assertIsNone(stale.directional_attention_score)
        self.assertIsNone(stale.dlmm_flow_score)

    def test_book_is_bounded_and_rejects_time_regression(self):
        book = FomoSignalBook(max_tokens=2, history_per_board=2)
        book.ingest('trending', board_payload(MINT, 3, 100), observed_at=100)
        book.ingest('trending', board_payload(MINT, 2, 110), observed_at=110)
        book.ingest('trending', board_payload(MINT2, 4, 111), observed_at=111)
        book.ingest('trending', board_payload(MINT3, 5, 112), observed_at=112)
        self.assertLessEqual(len(book.history), 2)
        with self.assertRaisesRegex(ValueError, 'fomo_time_regression'):
            book.ingest('trending', board_payload(MINT3, 1, 90), observed_at=113)

    def test_live_client_is_inactive_without_explicit_spend_authority(self):
        client = FomoScanClient()
        status = client.status()
        self.assertFalse(status['enabled'])
        self.assertFalse(status['provider_spend_authorized'])
        self.assertEqual(status['requests'], 0)
        with self.assertRaisesRegex(RuntimeError, 'fomo_shadow_disabled'):
            client.fetch_board('trending')
        with self.assertRaisesRegex(ValueError, 'fomo_provider_spend_not_authorized'):
            FomoScanClient(api_key='test-key', enabled=True)

    def test_production_engine_and_dlmm_authority_remain_unchanged(self):
        self.assertNotIn('fomo_shadow', inspect.getsource(engine))
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td) / 'state.db'), 'synthetic', 100_000_000, 'test')
            allocator = engine.Allocator(store)
            self.assertEqual(
                allocator.allowed('dlmm', 1, MINT, 'research-group', now=0),
                'dlmm_disabled',
            )
            store.close()


if __name__ == '__main__':
    unittest.main()
