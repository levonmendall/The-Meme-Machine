import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.lanes.meteora import dlmm, pump
from meme_machine.lanes.meteora.dlmm_paper import Replay, RESERVATION, CAPITAL, ENTRY_COST, EXIT_COST, RENT, prospective_reserve, monitoring_tick, inventory
from meme_machine.lanes.meteora.store import Store, IntegrityError, digest
from meme_machine.lanes.meteora.provider import RPC, Unavailable
from meme_machine.lanes.meteora.engine import Engine, Allocator
from tests.support import SCOUT, event as pump_event, evidence, snapshot as pump_snapshot, MINT
from tests.meteora_tape_fixtures import snapshot, change_account, POOL, VAULT_X

class Protocol(unittest.TestCase):

    def test_decoders_and_price(self):
        p = dlmm.validate(snapshot(), 100)
        self.assertEqual(p['active'], 0)
        self.assertEqual(len(p['bins']), 140)
        self.assertEqual(p['bins']['-1']['y'], 200000000)
        self.assertEqual(dlmm.price(0, 10), 1 << 64)
        self.assertEqual(dlmm.array_address(POOL, -1), dlmm.array_address(POOL, -1))
        for bid in (-1000, -2, -1, 1, 2, 1000):
            self.assertGreater(dlmm.price(bid, 10), 0)

    def test_fee_and_single_multi_bin(self):
        p = dlmm.validate(snapshot(), 100)
        self.assertEqual(dlmm.total_fee(p), 1000000)
        one, q = dlmm.swap(p, 1000000, True, 101)
        self.assertEqual((q['output'], q['fee'], q['protocol_fee']), (999000, 1000, 200))
        self.assertEqual(one['bins']['0']['x'], 200999000)
        self.assertEqual(p['bins']['0']['x'], 200000000)
        many, q = dlmm.swap(p, 450000000, True, 101)
        self.assertEqual([t['bin'] for t in q['traversed']], [0, -1, -2])
        self.assertEqual(many['bins']['-1']['y'], 0)
        self.assertGreater(q['fee'], 450000)

    def test_supported_scope_and_identity_fail_closed(self):
        base = snapshot()
        cases = [change_account(base, POOL, 82, b'\x01'), change_account(base, POOL, 36, b'\x01'), change_account(base, POOL, 120, pump.un58(SCOUT)), change_account(base, POOL, 880, b'\x01'), change_account(base, VAULT_X, 32, pump.un58(SCOUT)), change_account(base, dlmm.array_address(POOL, -1), 24, pump.un58(SCOUT)), change_account(change_account(base, dlmm.array_address(POOL, -1), 16, b'\x03'), dlmm.array_address(POOL, -1), 56 + 112, b'\x01')]
        for s in cases:
            with self.subTest(s=digest(s)), self.assertRaises((ValueError, KeyError)):
                dlmm.validate(s, 100)
        with self.assertRaises(ValueError):
            dlmm.scout(base, 121)
        with self.assertRaises(ValueError):
            dlmm.scout(base, 99)
        with self.assertRaises(ValueError):
            dlmm.scout(base, 100, dict(pool=POOL, x=SCOUT, y=dlmm.WSOL))
        del base['accounts'][dlmm.array_address(POOL, 0)]
        with self.assertRaises(KeyError):
            dlmm.validate(base, 100)

    def test_scout_non_authoritative_and_missing_research_explicit(self):
        candidate = dlmm.scout(snapshot(), 100)
        self.assertFalse(candidate['allocation_eligible'])
        self.assertIsNone(candidate['research']['volume'])
        self.assertEqual(candidate['pool'], POOL)
        with self.assertRaises(PermissionError):
            prospective_reserve(candidate, enabled=True)

    def test_provider_reuses_finalized_budget(self):
        snap = snapshot()
        calls = []

        def transport(req):
            calls.append(req)
            method = req['method']
            if method == 'getGenesisHash':
                result = pump.MAINNET
            elif method == 'getBlockTime':
                result = 100
            else:
                self.assertEqual(req['params'][1]['commitment'], 'finalized')
                result = dict(context=dict(slot=100), value=[snap['accounts'].get(k) for k in req['params'][0]])
            return dict(result=result)
        rpc = RPC('https://test.invalid', transport=transport, clock=lambda: 100)
        adapter = dlmm.Adapter(rpc)
        out = adapter.snapshot(POOL, 100)
        self.assertEqual(dlmm.validate(out, 100)['pool'], POOL)
        self.assertEqual(rpc.calls, 4)
        self.assertLessEqual(len(rpc.cache), 128)
        with self.assertRaises(Unavailable):
            adapter.swap_history(POOL, [100, 0, 0])
        with self.assertRaises(ValueError):
            adapter.discover([POOL] * 5, 100)

    def test_missing_traversal_does_not_modify_input(self):
        p = dlmm.validate(snapshot(), 100)
        before = digest(p)
        with self.assertRaises(Unavailable):
            dlmm.swap(p, 100000000000, True, 101)
        self.assertEqual(before, digest(p))
