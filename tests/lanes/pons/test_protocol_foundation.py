from dataclasses import asdict, replace
import copy
import tempfile
import unittest
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.evidence import Stamp, Store, ingest_batch
from meme_machine.lanes.pons.directional import Trade, features
from meme_machine.lanes.pons.protocols import Launch, PoolKey, prove_graduation, classify_discovery, decode_pons_launch, decode_curve_trade, PONS_LAUNCH, PONS_BUY
from meme_machine.lanes.pons.outcomes import Outcomes, summarize
from meme_machine.lanes.pons.paper import Paper, Quote
from meme_machine.lanes.pons.keccak import keccak256
from meme_machine.lanes.pons.liquidity import Bin, BinDelta, RamsesAdapter, apply_delta, case60, replay60
A, B, C, D, E = [f'0x{i:040x}' for i in range(1, 6)]

def stamp(at=120, **kw):
    return replace(Stamp(4663, 1, 'hash1', at, at, 'finalized', 'synthetic'), **kw)

def word(n):
    return '0x' + f'{n:064x}'

def feature_args():
    return dict(market=A, origin='pons_v2_curve', asof=120, launch_at=0, coverage_start=0, coverage_end=120, trades=[], liquidity=10000, previous_liquidity=9000, full_exit_depth=1000, entry_cost=100, round_trip_cost=5, state_stamp=stamp())

def graduation():
    launch = Launch(B, A, C, D, 'pons_v2_curve', E, 'source', stamp(100))
    key = PoolKey(B, C, 10000, 200, D)
    common = dict(stamp=asdict(stamp(120)), pool_id=key.pool_id())
    state = dict(common, factory=E, curve=A, token=B, phase=2, pool_manager=C)
    reg = dict(common, hook=D, curve=A, token=B)
    init = dict(common, key=asdict(key), pool_manager=C)
    return (launch, key, state, reg, init)

class EvidenceTests(unittest.TestCase):

    def setUp(self):
        self.s = Store(':memory:')

    def tearDown(self):
        self.s.close()

    def batch(self):
        event = dict(block=1, block_hash='hash1', log_index=0, transaction_hash='tx', address=A, removed=False, data='0x', topics=[])
        return dict(scope='directional', headers=[dict(stamp=asdict(stamp()), parent_hash='hash0', transactions=['tx'])], receipts=[dict(block_hash='hash1', transaction_hash='tx', logs=[event])], logs=[event], addresses={A}, observed_at=120, kind='synthetic')

    def test_duplicate_logs_deduplicate_atomically(self):
        batch = self.batch()
        batch['logs'] *= 2
        self.assertEqual(len(ingest_batch(self.s, **batch)), 1)
        self.assertEqual(self.s.cursor('directional'), (1, 'hash1'))

    def test_missing_log_fails_without_advancing(self):
        batch = self.batch()
        batch['logs'] = []
        with self.assertRaisesRegex(BoundaryError, 'missing_or_unexpected_logs'):
            ingest_batch(self.s, **batch)
        self.assertIsNone(self.s.cursor('directional'))

    def test_missing_receipt(self):
        batch = self.batch()
        batch['receipts'] = []
        with self.assertRaisesRegex(BoundaryError, 'missing_or_duplicate_receipts'):
            ingest_batch(self.s, **batch)

    def test_conflicting_logs(self):
        batch = self.batch()
        batch['logs'].append(dict(batch['logs'][0], data='0x01'))
        with self.assertRaisesRegex(BoundaryError, 'conflicting_logs'):
            ingest_batch(self.s, **batch)

    def test_reorg_and_nonfinalized_fail(self):
        batch = self.batch()
        batch['headers'][0]['stamp']['finality'] = 'sequencer'
        with self.assertRaisesRegex(BoundaryError, 'unfinalized'):
            ingest_batch(self.s, **batch)
        ingest_batch(self.s, **self.batch())
        batch = self.batch()
        batch['headers'][0]['stamp'].update(block=2, block_hash='hash2')
        with self.assertRaisesRegex(BoundaryError, 'reorg_parent_conflict'):
            ingest_batch(self.s, **batch)

    def test_removed_log(self):
        batch = self.batch()
        batch['logs'][0]['removed'] = True
        with self.assertRaisesRegex(BoundaryError, 'removed_log_reorg'):
            ingest_batch(self.s, **batch)

    def test_storage_bound_preserves_evidence(self):
        s = Store(':memory:', max_records=2)
        s.put('decision', 'a', {'x': 1})
        s.put('decision', 'b', {'x': 2})
        with self.assertRaisesRegex(BoundaryError, 'storage_capacity'):
            s.put('decision', 'c', {'x': 3})
        self.assertEqual(s.get('decision', 'a'), {'x': 1})
        with self.assertRaisesRegex(BoundaryError, 'conflicting_immutable'):
            s.put('decision', 'a', {'x': 9})
        s.close()

    def test_storage_transaction_rolls_back_cursor_and_logs(self):
        s = Store(':memory:', max_records=1)
        with self.assertRaisesRegex(BoundaryError, 'storage_capacity'):
            ingest_batch(s, **self.batch())
        self.assertEqual(s.db.execute('SELECT count(*) FROM records').fetchone()[0], 0)
        self.assertIsNone(s.cursor('directional'))
        s.close()

class ProtocolTests(unittest.TestCase):

    def test_ethereum_keccak_not_sha3(self):
        self.assertEqual(keccak256(b'').hex(), 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')
        self.assertEqual(keccak256(b'abc').hex(), '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45')

    def test_launch_and_curve_trade_decode(self):
        log = dict(address=E, topics=[PONS_LAUNCH, word(2), word(1), word(4)], data='0x' + ''.join((f'{v:064x}' for v in (3, 1, 4200))))
        launch = decode_pons_launch(log, stamp(), E)
        self.assertEqual((launch.token, launch.market, launch.quote), (B, A, C))
        trade = dict(address=A, topics=[PONS_BUY, word(4), word(4)], data='0x' + ''.join((f'{v:064x}' for v in (100, 200, 2, 3))))
        decoded = decode_curve_trade(trade, launch)
        self.assertEqual((decoded['quote'], decoded['tokens']), (100, 200))
        with self.assertRaisesRegex(BoundaryError, 'unverified'):
            decode_pons_launch(log, stamp(kind='natural'), E)

    def test_graduation_exact_pool_lineage(self):
        launch, key, state, reg, init = graduation()
        result = prove_graduation(launch, key=key, factory_state=state, registration=reg, initialization=init, asof=120)
        self.assertEqual(result['pregraduation_source'], 'source')
        self.assertEqual(result['market'], key.pool_id())

    def test_unrelated_v4_pool_rejected(self):
        launch, key, state, reg, init = graduation()
        reg['hook'] = E
        with self.assertRaisesRegex(BoundaryError, 'unrelated_v4'):
            prove_graduation(launch, key=key, factory_state=state, registration=reg, initialization=init, asof=120)

    def test_wrong_pool_id_rejected(self):
        launch, key, state, reg, init = graduation()
        state['pool_id'] = 'other'
        with self.assertRaisesRegex(BoundaryError, 'incorrect_pool_identity'):
            prove_graduation(launch, key=key, factory_state=state, registration=reg, initialization=init, asof=120)

    def test_v1_v2_and_nonpons_classification(self):
        for origin in ('pons_v1_v3', 'pons_v2_curve', 'non_pons_v4'):
            self.assertEqual(classify_discovery(origin=origin, asset_class='speculative', provenance=True, executable=True, kind='synthetic'), origin)
        for asset in ('tokenized_equity', 'stablecoin', 'wrapped_major', 'established'):
            self.assertEqual(classify_discovery(origin='non_pons_v4', asset_class=asset, provenance=True, executable=True, kind='synthetic'), 'excluded_' + asset)
