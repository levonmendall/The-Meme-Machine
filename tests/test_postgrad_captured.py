import json
import unittest
from dataclasses import asdict
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import (
    _decode_pumpswap_pool, _pumpswap_fee_rates, _token_account,
    buy_quote, graduation_handoff, pumpswap_pool, sell_quote,
)

FIXTURE = Path(__file__).parent/'fixtures'/'postgrad_pumpswap_mainnet.json'


class CapturedPostGraduation(unittest.TestCase):
    def test_captured_mainnet_pumpswap_identity_reserves_fees_and_quotes(self):
        doc = json.loads(FIXTURE.read_text())
        capture = doc['capture']
        graduation = capture['graduation']
        snapshot = capture['snapshot']
        expected_handoff = capture['handoff']

        handoff = graduation_handoff(graduation, graduation['available_time'])
        self.assertEqual(asdict(handoff), expected_handoff)
        self.assertEqual(pumpswap_pool(handoff.mint), snapshot['pool'])
        self.assertEqual(snapshot['pool'], 'GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J')

        accounts = snapshot['accounts']
        metadata = _decode_pumpswap_pool(snapshot['pool'], accounts['pool'], handoff.mint)
        supply, decimals = pump.mint_info(accounts['mint'])
        self.assertEqual(supply, snapshot['state']['mint_supply'])
        self.assertEqual(decimals, 6)
        base_reserve = _token_account(
            accounts['base_vault'], handoff.mint, authority=snapshot['pool'],
            token_program=accounts['mint']['owner'])
        raw_quote = _token_account(
            accounts['quote_vault'],
            'So11111111111111111111111111111111111111112',
            authority=snapshot['pool'], token_program=pump.TOKEN_PROGRAM)
        effective_quote = raw_quote + int(metadata['virtual_quote_reserves'])
        self.assertEqual(base_reserve, 649596913609305)
        self.assertEqual(effective_quote, 127506693554)
        self.assertEqual(base_reserve, snapshot['state']['base_reserve'])
        self.assertEqual(effective_quote, snapshot['state']['quote_reserve'])

        market_cap = effective_quote*supply//base_reserve
        rates = _pumpswap_fee_rates(accounts['fee_config'], market_cap, metadata['coin_creator'])
        self.assertEqual(list(rates), snapshot['state']['fee_parts_bps'])
        self.assertEqual(list(rates), [2, 93, 30])

        buy = buy_quote(snapshot, 100_000_000)
        sell = sell_quote(snapshot, buy.output_amount)
        self.assertEqual(asdict(buy), capture['quote']['buy'])
        self.assertEqual(asdict(sell), capture['quote']['sell'])
        self.assertEqual(buy.input_amount, 100_000_000)
        self.assertEqual(buy.output_amount, 502781926495)
        self.assertEqual(buy.fee_amount, 1234570)
        self.assertEqual(sell.output_amount, 97380002)
        self.assertEqual(buy.input_amount-sell.output_amount, 2619998)

    def test_fixture_is_read_only_evidence_not_strategy_authority(self):
        doc = json.loads(FIXTURE.read_text())
        self.assertIn('no order authority', doc['provenance']['authority'])
        self.assertEqual(doc['provenance']['workflow'], 35186308858)
        self.assertEqual(doc['provenance']['artifact_id'], 10481987603)


if __name__ == '__main__':
    unittest.main()
