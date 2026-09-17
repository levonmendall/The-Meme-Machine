import copy
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from meme_machine import engine, fomo_shadow, pump
from meme_machine.fomo_shadow import (
    DirectDlmmEconomics,
    FomoCandidateAnnotator,
    FomoResearchLedger,
    FomoScanClient,
    FomoSignalBook,
    build_dlmm_research_vector,
    normalize_token_board,
)
from meme_machine.store import Store

FIXTURE = Path(__file__).parent / 'fixtures' / 'fomo_shadow_replay.json'
MINT2 = pump.b58(bytes([17]) * 32)
MINT3 = pump.b58(bytes([18]) * 32)


def board_payload(mint, rank=1, at=100):
    return {'at': at, 'items': [{'tokenAddress': mint, 'rank': rank}]}


def load_replay():
    payload = json.loads(FIXTURE.read_text())
    assert payload['fixture_kind'] == 'synthetic-provider-shaped-replay'
    assert payload['live_capture'] is False
    return payload


class FomoOfflineIntelligenceMilestone(unittest.TestCase):
    def test_replay_annotation_is_point_in_time_and_future_observations_do_not_leak(self):
        replay = load_replay()
        mint = replay['target_mint']
        book = FomoSignalBook()
        self.assertEqual(book.replay(replay['frames']), 5)

        early = book.annotate(mint, decision_at=109)
        self.assertTrue(early.available)
        self.assertEqual(early.status, 'available')
        self.assertEqual(early.missing_data_status, 'complete')
        self.assertEqual(early.trending_rank, 20)
        self.assertTrue(early.trending_present)
        self.assertEqual(early.most_held_rank, 9)
        self.assertTrue(early.most_held_present)
        self.assertIsNone(early.graduated_rank)
        self.assertFalse(early.graduated_present)
        self.assertIsNone(early.trending_rank_change)
        self.assertEqual(early.source_timestamp, 100)
        self.assertEqual(early.available_at, 103)
        self.assertEqual(len(early.provenance), 3)

        # This observation was already ingested into the replay book but was not
        # locally available until t=115, so it cannot change a t=109 decision.
        later = book.annotate(mint, decision_at=116)
        self.assertEqual(later.trending_rank, 5)
        self.assertEqual(later.trending_rank_change, 15)
        self.assertEqual(later.attention_acceleration, 100)
        self.assertNotEqual(later.state_id, early.state_id)

        before_graduation_availability = book.annotate(mint, decision_at=129)
        self.assertFalse(before_graduation_availability.graduated_present)
        after_graduation_availability = book.annotate(mint, decision_at=131)
        self.assertTrue(after_graduation_availability.graduated_present)
        self.assertEqual(after_graduation_availability.graduated_rank, 4)

    def test_stale_future_malformed_conflicting_and_missing_provenance_fail_closed(self):
        replay = load_replay()
        mint = replay['target_mint']
        book = FomoSignalBook()
        book.replay(replay['frames'])

        stale = book.annotate(mint, decision_at=400)
        self.assertFalse(stale.available)
        self.assertEqual(stale.status, 'stale')
        self.assertEqual(stale.freshness, 'stale')
        self.assertIsNone(stale.trending_rank)
        self.assertIsNone(stale.directional_attention_score)
        self.assertIsNone(stale.dlmm_flow_score)

        with self.assertRaisesRegex(ValueError, 'future_fomo_snapshot'):
            normalize_token_board(
                'trending',
                board_payload(mint, rank=1, at=200),
                observed_at=100,
                source='fixture:future',
            )
        with self.assertRaisesRegex(ValueError, 'invalid_solana_mint'):
            normalize_token_board(
                'trending',
                {'at': 100, 'items': [{'tokenAddress': '0x1234', 'rank': 1}]},
                observed_at=101,
                source='fixture:bad-mint',
            )
        with self.assertRaisesRegex(ValueError, 'duplicate_fomo_token'):
            normalize_token_board(
                'trending',
                {
                    'at': 100,
                    'items': [
                        {'tokenAddress': mint, 'rank': 1},
                        {'tokenAddress': mint, 'rank': 1},
                    ],
                },
                observed_at=101,
                source='fixture:duplicate',
            )
        with self.assertRaisesRegex(ValueError, 'conflicting_fomo_token'):
            normalize_token_board(
                'trending',
                {
                    'at': 100,
                    'items': [
                        {'tokenAddress': mint, 'rank': 1},
                        {'tokenAddress': mint, 'rank': 2},
                    ],
                },
                observed_at=101,
                source='fixture:duplicate-conflict',
            )
        with self.assertRaisesRegex(ValueError, 'fomo_conflicting_duplicate'):
            book.ingest(
                'trending',
                board_payload(mint, rank=6, at=110),
                observed_at=116,
                source='fixture:fomoscan-v2:trending:110',
            )
        with self.assertRaisesRegex(ValueError, 'fomo_time_regression'):
            book.ingest(
                'trending',
                board_payload(mint, rank=4, at=109),
                observed_at=117,
                source='fixture:time-regression',
            )
        with self.assertRaisesRegex(ValueError, 'missing_fomo_provenance'):
            FomoSignalBook().replay([
                {
                    'board': 'trending',
                    'observed_at': 101,
                    'payload': board_payload(mint, rank=1, at=100),
                }
            ])

    def test_candidate_annotation_is_additive_unavailable_safe_and_cannot_change_qualification(self):
        replay = load_replay()
        mint = replay['target_mint']
        candidate = {
            'mint': mint,
            'source': 'pump-market-native',
            'continuation_version': 'continuation-v1',
            'qualification': 'independent_demand',
        }
        baseline = copy.deepcopy(candidate)
        annotator = FomoCandidateAnnotator(FomoSignalBook())

        annotated = annotator.annotate_candidate(candidate, decision_at=109)
        self.assertEqual(candidate, baseline)
        self.assertFalse(annotated.fomo.available)
        self.assertEqual(annotated.fomo.status, 'unavailable')
        self.assertFalse(annotated.candidate_authority)
        self.assertFalse(annotated.order_authority)
        self.assertFalse(annotated.dlmm_authority)
        self.assertEqual(candidate['qualification'], 'independent_demand')
        self.assertNotEqual(candidate['qualification'], 'qualified')
        self.assertFalse(hasattr(annotated, 'qualification'))

        # Production qualification remains Fomo-free: the Fomo module is not an
        # Engine dependency and therefore cannot bypass a continuation-v1 gate.
        self.assertNotIn('fomo_shadow', inspect.getsource(engine))
        self.assertNotIn('from . import engine', inspect.getsource(fomo_shadow))
        self.assertNotIn('import engine', inspect.getsource(fomo_shadow))

    def test_annotation_cannot_reserve_orders_and_dlmm_remains_disabled(self):
        replay = load_replay()
        mint = replay['target_mint']
        book = FomoSignalBook()
        book.replay(replay['frames'])
        annotator = FomoCandidateAnnotator(book)

        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td) / 'state.db'), 'synthetic', 100_000_000, 'test')
            before_orders = copy.deepcopy(store.state['orders'])
            before_cash = store.state['cash']
            annotation = annotator.annotate_mint(mint, decision_at=109)
            self.assertTrue(annotation.fomo.available)
            self.assertEqual(store.state['orders'], before_orders)
            self.assertEqual(store.state['cash'], before_cash)
            allocator = engine.Allocator(store)
            self.assertEqual(
                allocator.allowed('dlmm', 1, mint, 'research-group', now=0),
                'dlmm_disabled',
            )
            store.close()

    def test_research_record_links_exact_decision_state_to_later_outcome(self):
        replay = load_replay()
        mint = replay['target_mint']
        book = FomoSignalBook()
        book.replay(replay['frames'])
        decision_state = book.annotate(mint, decision_at=109)
        later_state = book.annotate(mint, decision_at=131)
        self.assertNotEqual(decision_state.state_id, later_state.state_id)

        ledger = FomoResearchLedger(max_records=8)
        captured = ledger.capture_decision(
            'pump-candidate-001',
            decision_state,
            qualification_result='independent_demand',
            rejection_reasons=('independent_demand',),
            pump_entry=False,
        )
        final = ledger.finalize_outcome(
            'pump-candidate-001',
            graduation=True,
            realized_paper_result_lamports=-125_000,
            mfe_bps=420,
            mae_bps=-610,
            time_to_graduation_seconds=90,
            time_to_exit_seconds=480,
        )
        self.assertEqual(final.fomo_state_id, decision_state.state_id)
        self.assertEqual(final.fomo_state.trending_rank, 20)
        self.assertFalse(final.fomo_state.graduated_present)
        self.assertTrue(final.graduation)
        self.assertFalse(final.pump_entry)
        self.assertEqual(final.qualification_result, 'independent_demand')
        self.assertEqual(final.rejection_reasons, ('independent_demand',))
        self.assertEqual(final.realized_paper_result_lamports, -125_000)
        self.assertEqual(final.mfe_bps, 420)
        self.assertEqual(final.mae_bps, -610)
        self.assertEqual(final.time_to_graduation_seconds, 90)
        self.assertEqual(final.time_to_exit_seconds, 480)
        self.assertEqual(captured.fomo_state_id, final.fomo_state_id)

    def test_dlmm_bridge_requires_direct_economics_and_keeps_authority_separate(self):
        replay = load_replay()
        mint = replay['target_mint']
        book = FomoSignalBook()
        book.replay(replay['frames'])
        annotation = book.annotate(mint, decision_at=116)

        direct = DirectDlmmEconomics(
            pool=MINT2,
            base_mint=mint,
            quote_mint=MINT3,
            sampled_at=108,
            available_at=112,
            source='direct-meteora:synthetic-fixture',
            current_price=1.0,
            active_bin=42,
            liquidity_distribution=((41, 10_000), (42, 20_000), (43, 10_000)),
            tvl_lamports=1_000_000_000,
            recent_volume_lamports=250_000_000,
            historical_volume_lamports=5_000_000_000,
            fee_rate_bps=25,
            dynamic_fee_bps=5,
            fees_generated_lamports=1_250_000,
            volatility_bps=800,
            position_range=(40, 44),
            inventory_exposure_bps=5100,
            rebalance_cost_bps=12,
            withdrawal_cost_bps=8,
            executable_lp_pnl_lamports=55_000,
        )
        vector = build_dlmm_research_vector(annotation, direct)
        self.assertTrue(direct.direct_economics_authority)
        self.assertFalse(direct.allocation_authority)
        self.assertEqual(vector.dlmm_observation_id, direct.observation_id)
        self.assertEqual(vector.dlmm_pool, direct.pool)
        self.assertEqual(vector.trending_rank, 5)
        self.assertEqual(vector.trending_strength, annotation.trending_strength)
        self.assertEqual(vector.attention_acceleration, annotation.attention_acceleration)
        self.assertTrue(vector.direct_dlmm_economics_required)
        self.assertFalse(vector.dlmm_authority)
        self.assertFalse(vector.dlmm_allocation_enabled)
        self.assertFalse(vector.order_authority)
        self.assertFalse(hasattr(vector, 'tvl_lamports'))

        with self.assertRaisesRegex(TypeError, 'direct_dlmm_economics_required'):
            build_dlmm_research_vector(annotation, None)
        with self.assertRaisesRegex(ValueError, 'future_dlmm_observation'):
            build_dlmm_research_vector(
                annotation,
                DirectDlmmEconomics(
                    pool=MINT2,
                    base_mint=mint,
                    quote_mint=MINT3,
                    sampled_at=117,
                    available_at=118,
                    source='direct-meteora:future-fixture',
                ),
            )

    def test_observation_and_research_storage_are_bounded(self):
        book = FomoSignalBook(max_tokens=8, history_per_board=3)
        boards = ('trending', 'most-held', 'graduated')
        for index in range(120):
            mint = pump.b58(bytes([(index % 200) + 1]) * 32)
            at = 1000 + index
            book.ingest(
                boards[index % len(boards)],
                board_payload(mint, rank=(index % 50) + 1, at=at),
                observed_at=at,
                source=f'fixture:bounded:{index % len(boards)}',
            )
        status = book.status()
        self.assertLessEqual(status['tracked_tokens'], 8)
        self.assertLessEqual(status['retained_snapshots'], 9)
        self.assertLessEqual(
            status['retained_observations'],
            status['max_retained_observations'],
        )
        self.assertFalse(status['raw_provider_payloads_retained'])
        self.assertEqual(status['persistent_storage'], 'none')

        replay = load_replay()
        stable = FomoSignalBook()
        stable.replay(replay['frames'])
        annotation = stable.annotate(replay['target_mint'], decision_at=109)
        ledger = FomoResearchLedger(max_records=16)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'fomo-research.json'
            plateau_size = None
            for index in range(100):
                ledger.capture_decision(
                    f'candidate-{index:03d}',
                    annotation,
                    qualification_result='rejected',
                    rejection_reasons=('synthetic-research-only',),
                    pump_entry=False,
                )
                size = ledger.save(path)
                if index == 31:
                    plateau_size = size
            self.assertEqual(len(ledger.records), 16)
            self.assertIsNotNone(plateau_size)
            self.assertLessEqual(path.stat().st_size, 2048 + 16 * 8192)
            self.assertLess(abs(path.stat().st_size - plateau_size), 8192)
            self.assertFalse(ledger.status()['raw_provider_payloads_retained'])
            self.assertEqual(
                ledger.status()['persistence'],
                'bounded_atomic_snapshot',
            )

    def test_live_client_remains_inactive_and_ci_path_makes_zero_requests(self):
        client = FomoScanClient()
        status = client.status()
        self.assertFalse(status['enabled'])
        self.assertFalse(status['provider_spend_authorized'])
        self.assertEqual(status['requests'], 0)
        with mock.patch('meme_machine.fomo_shadow.urllib.request.urlopen') as urlopen:
            with self.assertRaisesRegex(RuntimeError, 'fomo_shadow_disabled'):
                client.fetch_board('trending')
            urlopen.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'fomo_provider_spend_not_authorized'):
            FomoScanClient(api_key='test-key', enabled=True)
        guarded = FomoScanClient(
            api_key='test-key',
            enabled=False,
            provider_spend_authorized=False,
        )
        self.assertNotIn('test-key', repr(guarded.status()))


if __name__ == '__main__':
    unittest.main()
