"""Global mint supply is endpoint metadata; pool accounting stays exact."""
import copy
import struct
import unittest

from meme_machine.lanes.meteora import dlmm, pump
from meme_machine.lanes.meteora.dlmm_tape import reconstruct
from meme_machine.lanes.meteora.provider import Unavailable
from meme_machine.lanes.meteora.store import digest
from tests.lanes.meteora import solana_dlmm_independent_v1 as strategy
from tests.lanes.meteora.dlmm_support import snapshot, change_account, POOL
from tests.lanes.meteora.test_dlmm_tape import interval
from tests.lanes.meteora.test_dlmm_safe_token2022 import token2022_mint


ANCHOR = [dict(signature='anchor', slot=99, transactionIndex=0,
               err=None, confirmationStatus='finalized')]
CURSOR = [100, 2**31-1, 2**31-1]


def empty_interval(sol_x=False):
    first = snapshot(sol_x=sol_x)
    first['kind'] = 'real'
    state = dlmm.validate(first, 100, 'real')
    end = copy.deepcopy(first)
    end.update(slot=102, market_time=102, available_time=102)
    return first, state, end


class MintSupplyReconstructionTests(unittest.TestCase):
    def test_off_pool_supply_change_preserves_authenticated_endpoint(self):
        for sol_x in (False, True):
            for delta in (-594625327, 500):
                with self.subTest(sol_x=sol_x, delta=delta):
                    first, start, end = empty_interval(sol_x)
                    side = 'y' if sol_x else 'x'
                    key = 'token_' + side + '_mint_info'
                    amount = start[key]['supply'] + delta
                    end = change_account(end, start[side], 36, struct.pack('<Q', amount))
                    tape = reconstruct(start, end, ANCHOR, {}, 102, CURSOR)
                    self.assertEqual(tape.events, ())
                    self.assertEqual(tape.terminal_adjustments, ())
                    self.assertEqual(tape.terminal[key]['supply'], amount)
                    self.assertEqual(tape.end_hash, digest(dlmm.validate(end, 102, 'real')))
                    self.assertEqual(start, dlmm.validate(first, 100, 'real'))

    def test_supply_change_preserves_swap_decisions_and_position_accounting(self):
        first, start, end, signatures, transactions = interval()
        baseline = reconstruct(start, end, signatures, transactions, 102, CURSOR)
        changed = change_account(end, start['x'], 36,
                                 struct.pack('<Q', start['token_x_mint_info']['supply'] - 12345))
        tape = reconstruct(start, changed, signatures, transactions, 102, CURSOR)
        self.assertEqual(tape.events, baseline.events)
        self.assertEqual(tape.terminal_adjustments, baseline.terminal_adjustments)
        self.assertNotEqual(tape.end_hash, baseline.end_hash)
        self.assertNotEqual(tape.lineage, baseline.lineage)
        policy = strategy.load_policy()
        candidate = dict(volume_acceleration=1.0, fee_acceleration=1.0)
        before = strategy.pre_entry_features(start, baseline, baseline.terminal, candidate, policy)
        after = strategy.pre_entry_features(start, tape, tape.terminal, candidate, policy)
        self.assertEqual(before, after)
        self.assertEqual(strategy.qualify(before, policy), strategy.qualify(after, policy))
        position = strategy._build_position(start, dict(half_width_bins=26), policy)
        expected = strategy._advance_position(position, baseline)
        actual = strategy._advance_position(position, tape)
        self.assertEqual(actual, expected)
        self.assertEqual(strategy._mark(actual), strategy._mark(expected))

    def test_supply_change_does_not_mask_mint_controls_or_pool_state(self):
        _, start, end = empty_interval()
        changed = change_account(end, start['x'], 36,
                                 struct.pack('<Q', start['token_x_mint_info']['supply'] - 12345))
        bad_program = copy.deepcopy(changed)
        bad_program['accounts'][start['x']]['owner'] = pump.TOKEN_2022
        cases = {
            'mint_authority': change_account(changed, start['x'], 0, struct.pack('<I', 1)),
            'decimals': change_account(changed, start['x'], 44, bytes([7])),
            'freeze_authority': change_account(changed, start['x'], 46, struct.pack('<I', 1)),
            'program': bad_program,
            'bin_inventory': change_account(changed, dlmm.array_address(POOL, 0), 56,
                                             struct.pack('<Q', 200000001)),
            'vault_inventory': change_account(changed, start['vault_x'], 64,
                                               struct.pack('<Q', start['vault_x_amount'] + 1)),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises((Unavailable, ValueError)):
                    reconstruct(start, value, ANCHOR, {}, 102, CURSOR)

    def test_token2022_supply_only_burn_keeps_extensions_exact(self):
        first = snapshot()
        first['kind'] = 'real'
        classic = dlmm.validate(first, 100, 'real')
        first = change_account(first, POOL, 880, bytes([1]))
        first['accounts'][classic['x']] = token2022_mint(((18, 64), (19, 4)))
        first['accounts'][classic['vault_x']]['owner'] = pump.TOKEN_2022
        start = dlmm.validate(first, 100, 'real')
        end = copy.deepcopy(first)
        end.update(slot=102, market_time=102, available_time=102)
        end = change_account(end, start['x'], 36, struct.pack('<Q', 999999999))
        tape = reconstruct(start, end, ANCHOR, {}, 102, CURSOR)
        self.assertEqual(tuple(tape.terminal['token_x_mint_info']['extensions']), (18, 19))
        for extensions in (((18, 64),), ((18, 64), (19, 4), (1, 108))):
            changed = copy.deepcopy(end)
            changed['accounts'][start['x']] = token2022_mint(extensions)
            with self.subTest(extensions=extensions):
                with self.assertRaises((Unavailable, ValueError)):
                    reconstruct(start, changed, ANCHOR, {}, 102, CURSOR)


if __name__ == '__main__':
    unittest.main()
