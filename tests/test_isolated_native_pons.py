"""Offline native Pons projection parity limits and retained failure regressions."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from meme_machine.operational.isolated_native_pons import (
    MAX_RANGE_BLOCKS, NAMESPACE, PROVENANCE, ROBINHOOD,
    PonsNativeProjection, PonsProjectionUnavailable,
)


CAPTURE = (Path(__file__).parent / 'lanes/pons/fixtures/'
           'public_log_timestamp_35915320840.json')


class CapturedPublicRpc:
    """The existing retained failure corpus; never opens a network transport."""
    def __init__(self, capture):
        self.capture = copy.deepcopy(capture)
        self.requests = []
        self.receipt_failure = None

    def call(self, endpoint, method, params):
        if endpoint != ROBINHOOD:
            raise AssertionError('nonfixed public endpoint')
        self.requests.append((endpoint, method, copy.deepcopy(params)))
        event = self.capture['event']
        if method == 'eth_getLogs':
            query = params[0]
            block = int(event['blockNumber'], 16)
            return [copy.deepcopy(event)] if int(query['fromBlock'],16) <= block <= int(query['toBlock'],16) else []
        if method == 'eth_getBlockByNumber':
            header = copy.deepcopy(self.capture['header'])
            header['number'] = params[0]
            return header
        if method == 'eth_getTransactionReceipt':
            if self.receipt_failure is not None:
                raise self.receipt_failure
            return copy.deepcopy(self.capture['receipt'])
        raise AssertionError('unexpected method')


class PonsNativeProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'pons'
        self.capture = json.loads(CAPTURE.read_text())
        self.block = int(self.capture['header']['number'], 16)
        self.observed_at = int(self.capture['header']['timestamp'], 16) + 3
        self.rpc = CapturedPublicRpc(self.capture)
        self.projection = PonsNativeProjection(self.root)
        self.addCleanup(self.projection.close)

    def consume(self, **kwargs):
        return self.projection.consume(self.block, self.block, self.rpc,
            observed_at=kwargs.get('observed_at', self.observed_at))

    def test_real_native_decode_candidate_history_and_explicit_partial_verdict(self):
        result = self.consume()
        snapshot = result['snapshot']
        self.assertEqual(result['durable_economic_added'], 1)
        self.assertEqual(snapshot['native_candidates']['unique_candidates'], 1)
        self.assertEqual(snapshot['scout']['market_cursor'], self.block)
        self.assertEqual(snapshot['decoded_cursor'], self.block)
        self.assertEqual(snapshot['verdict'], 'PARTIAL')
        self.assertFalse(snapshot['production_equivalent'])
        self.assertFalse(snapshot['full_market_readiness_proven'])
        self.assertFalse(snapshot['allocation_authority'])
        self.assertFalse(snapshot['canonical_completeness'])
        self.assertGreater(len(snapshot['parity_omissions']), 4)
        row = self.projection.plane.db.execute(
            'SELECT key FROM evidence WHERE namespace=?', (NAMESPACE,)).fetchone()
        value, provenance = self.projection.plane.evidence(NAMESPACE, row[0])
        self.assertEqual(provenance, PROVENANCE)
        # Original archived failure had blockTimestamp=0 in the public log;
        # actual native raw_event must use the corresponding header timestamp.
        self.assertEqual(value['raw_event']['event_at'], self.observed_at - 3)
        self.assertIn(value['economic']['side'], ('buy', 'sell'))
        self.assertGreater(value['economic']['quote'], 0)
        self.assertGreater(value['economic']['tokens'], 0)
        self.assertEqual(value['raw_event']['confirmation'], 'confirmed')
        self.assertTrue(all(endpoint == ROBINHOOD for endpoint, _, _ in self.rpc.requests))

    def test_replay_preserves_observation_deadline_and_corpus_without_duplicate_work(self):
        first = self.consume()['snapshot']
        deadline = self.projection.plane.db.execute('SELECT deadline FROM candidates').fetchone()[0]
        second = self.consume(observed_at=self.observed_at + 10)['snapshot']
        self.assertEqual(second['durable_economic_events'], 1)
        self.assertEqual(first['economic_corpus_sha256'], second['economic_corpus_sha256'])
        self.assertEqual(self.projection.plane.db.execute('SELECT deadline FROM candidates').fetchone()[0], deadline)
        self.assertEqual(second['native_candidates']['durable_candidate_generations'], 1)

    def test_native_reopen_preserves_pending_nominations_and_reads_real_history(self):
        before = self.consume()['snapshot']
        after = self.projection.reopen()
        self.assertEqual(before['economic_corpus_sha256'], after['economic_corpus_sha256'])
        self.assertEqual(before['pending_native_candidates'], after['pending_native_candidates'])
        self.assertEqual(after['history_reads_this_process'], before['history_reads_this_process'] + 1)
        self.assertEqual(len(after['restoration_seconds']), 2)
        self.assertEqual(after['decoded_cursor'], self.block)
        self.assertEqual(after['native_candidates']['complete_canonical_decisions'], 0)
        self.assertIsNone(self.projection.plane.db.execute('SELECT result FROM candidates').fetchone()[0])

    def test_receipt_identity_failure_preserves_raw_cursor_without_decoded_completion(self):
        self.rpc.capture['receipt']['transactionHash'] = '0x' + '00' * 32
        with self.assertRaisesRegex(Exception, 'raw_event_identity_disagreement'):
            self.consume()
        result = self.projection.snapshot()
        self.assertEqual(result['scout']['market_cursor'], self.block)
        self.assertIsNone(result['decoded_cursor'])
        self.assertEqual(result['durable_economic_events'], 0)
        self.assertFalse(result['incomplete']['complete'])
        self.assertEqual(result['native_candidates']['unique_candidates'], 1)

    def test_cancellation_preserves_disposable_work_and_incomplete_status(self):
        self.rpc.receipt_failure = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.consume()
        result = self.projection.snapshot()
        self.assertIsNone(result['decoded_cursor'])
        self.assertEqual(result['incomplete']['error_type'], 'KeyboardInterrupt')
        self.assertEqual(result['scout']['market_cursor'], self.block)

    def test_native_reorg_gap_is_retained_and_never_a_full_capacity_pass(self):
        self.consume()
        self.rpc.capture['header']['hash'] = '0x' + '11' * 32
        with self.assertRaisesRegex(Exception, 'scout_public_reorg'):
            self.consume()
        result = self.projection.snapshot()
        self.assertIsNotNone(result['scout']['market_gap'])
        self.assertFalse(result['incomplete']['complete'])
        self.assertEqual(result['verdict'], 'PARTIAL')

    def test_no_financial_books_shared_authority_or_canonical_history_are_created(self):
        self.consume()
        self.projection.reopen()
        tables = {r[0] for r in self.projection.plane.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {'paper', 'capital_positions', 'portfolio_journal',
                                   'shared_capital_projection', 'pons_current_history'})
        self.assertFalse(any('portfolio' in p.name or 'shared-capital' in p.name
                             or 'trial-' in p.name for p in self.root.iterdir()))
        self.assertEqual(self.projection.plane.db.execute(
            'SELECT COUNT(*) FROM receipt_obligations').fetchone()[0], 0)

    def test_range_capacity_and_noncontiguous_work_fail_before_rpc(self):
        with self.assertRaisesRegex(PonsProjectionUnavailable, 'range_bound'):
            self.projection.consume(0, MAX_RANGE_BLOCKS, self.rpc, observed_at=self.observed_at)
        self.assertEqual(self.rpc.requests, [])
        self.consume()
        prior = len(self.rpc.requests)
        with self.assertRaisesRegex(PonsProjectionUnavailable, 'noncontiguous_range'):
            self.projection.consume(self.block + 2, self.block + 2, self.rpc,
                                    observed_at=self.observed_at)
        self.assertEqual(len(self.rpc.requests), prior)

    def test_rejects_foreign_unmarked_or_financial_ancestor_state_and_symlinks(self):
        foreign = Path(self.temp.name) / 'foreign'
        foreign.mkdir(mode=0o700)
        (foreign / 'candidates.sqlite').touch()
        with self.assertRaisesRegex(PonsProjectionUnavailable, 'unmarked_state'):
            PonsNativeProjection(foreign)
        financial = Path(self.temp.name) / 'production'
        financial.mkdir(mode=0o700)
        (financial / 'portfolio.sqlite').touch()
        with self.assertRaisesRegex(PonsProjectionUnavailable, 'financial_ancestor'):
            PonsNativeProjection(financial / 'scratch')
        link = Path(self.temp.name) / 'linked'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(PonsProjectionUnavailable, 'symlink_refused'):
            PonsNativeProjection(link)

    def test_exclusive_owner_and_clean_reopen_after_close(self):
        self.consume()
        before = self.projection.snapshot()
        with self.assertRaises(BlockingIOError):
            PonsNativeProjection(self.root)
        self.projection.close()
        reopened = PonsNativeProjection(self.root)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.snapshot()['economic_corpus_sha256'], before['economic_corpus_sha256'])

