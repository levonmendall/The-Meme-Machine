import json
import unittest
from dataclasses import asdict
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import (
    OPENBOOK_V3, WSOL, _decode_open_orders, _decode_raydium_pool,
    _token_account, buy_quote, graduation_handoff, sell_quote,
)

FIXTURE = Path(__file__).parent/'fixtures'/'postgrad_raydium_mainnet.json'


class CapturedLegacyRaydium(unittest.TestCase):
    def test_captured_current_primary_pool_identity_reserves_and_quotes(self):
        doc = json.loads(FIXTURE.read_text())
        graduation = doc['graduation']
        snapshot = doc['snapshot']
        handoff = graduation_handoff(graduation, graduation['available_time'])
        self.assertEqual(asdict(handoff), doc['handoff'])

        record = doc['registry_record']
        self.assertEqual(snapshot['pool'], record['pool'])
        self.assertEqual(snapshot['mint'], record['mint'])
        self.assertTrue(record['current_pair_identity_verified'])
        self.assertFalse(record['direct_pump_withdraw_lineage_verified'])
        self.assertFalse(record['allocation_eligible'])

        accounts = snapshot['accounts']
        metadata = _decode_raydium_pool(snapshot['pool'], accounts['pool'], snapshot['mint'])
        self.assertEqual(metadata['market_program'], OPENBOOK_V3)
        self.assertEqual({metadata['base_mint'], metadata['quote_mint']}, {snapshot['mint'], WSOL})
        supply, decimals = pump.mint_info(accounts['mint'])
        self.assertEqual(supply, snapshot['state']['mint_supply'])
        self.assertEqual(decimals, snapshot['state']['decimals'])

        base_vault_amount = _token_account(
            accounts['base_vault'], metadata['base_mint'],
            token_program=(accounts['mint']['owner'] if metadata['base_mint'] == snapshot['mint'] else pump.TOKEN_PROGRAM))
        quote_vault_amount = _token_account(
            accounts['quote_vault'], metadata['quote_mint'],
            token_program=(accounts['mint']['owner'] if metadata['quote_mint'] == snapshot['mint'] else pump.TOKEN_PROGRAM))
        orders = _decode_open_orders(accounts['open_orders'], metadata['market_id'])
        effective_base = base_vault_amount + orders['base_total'] - metadata['base_need_take_pnl']
        effective_quote = quote_vault_amount + orders['quote_total'] - metadata['quote_need_take_pnl']
        if metadata['base_mint'] == snapshot['mint']:
            token_reserve, sol_reserve = effective_base, effective_quote
        else:
            token_reserve, sol_reserve = effective_quote, effective_base
        self.assertEqual(token_reserve, snapshot['state']['base_reserve'])
        self.assertEqual(sol_reserve, snapshot['state']['quote_reserve'])
        self.assertEqual(token_reserve, 25153410085016)
        self.assertEqual(sol_reserve, 36242914813688)

        buy = buy_quote(snapshot, 100_000_000)
        sell = sell_quote(snapshot, buy.output_amount)
        self.assertEqual(asdict(buy), doc['quote']['buy'])
        self.assertEqual(asdict(sell), doc['quote']['sell'])
        self.assertEqual(buy.fee_amount, 250000)
        self.assertEqual(buy.output_amount, 69228586)
        self.assertEqual(sell.output_amount, 99500077)
        self.assertEqual(buy.input_amount-sell.output_amount, 499923)

    def test_capture_preserves_lineage_limitation_and_no_authority(self):
        doc = json.loads(FIXTURE.read_text())
        self.assertIn('no direct Pump withdraw lineage', doc['provenance']['authority'])
        self.assertIn('no direct migration-event lineage', doc['registry_record']['verification']['limitation'])
        self.assertEqual(doc['provenance']['workflow'], 35187441898)
        self.assertEqual(doc['provenance']['artifact_id'], 10481694551)
        self.assertFalse(doc['snapshot']['source']['allocation_eligible'])
        self.assertFalse(doc['snapshot']['source']['direct_pump_withdraw_lineage_verified'])


if __name__ == '__main__':
    unittest.main()
