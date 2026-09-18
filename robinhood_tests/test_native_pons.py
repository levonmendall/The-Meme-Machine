import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from robinhood_research import BoundaryError
from robinhood_research.abi import decode_event
from robinhood_research.pons import CurveState, authenticate_curve, factory_record, curve_abi

CAPTURE=Path(__file__).parent/'fixtures/protocol_capture_35370277849.json'


class PonsNativeTests(unittest.TestCase):
    def setUp(self):
        self.capture=json.loads(CAPTURE.read_text())
        self.state=CurveState(1680000,10000000,680000,2000000,100,200,False,100,9900,14,120)

    def test_recompiled_real_curve_and_factory_record(self):
        for curve in self.capture['lanes']['pons']['curves']:
            auth=authenticate_curve(curve['address'],curve['code'],factory_record=factory_record(curve['factory_record']))
            self.assertEqual(auth['immutables']['feeBps'],100)
            self.assertFalse(auth['proxy'])

    def test_curve_impostor_and_wrong_factory_record(self):
        c=self.capture['lanes']['pons']['curves'][0]
        record=factory_record(c['factory_record'])
        record['curve']='0x'+'11'*20
        with self.assertRaisesRegex(BoundaryError,'provenance'):
            authenticate_curve(c['address'],c['code'],factory_record=record)
        with self.assertRaisesRegex(BoundaryError,'bytecode'):
            authenticate_curve(c['address'],'0x00'+c['code'][4:],factory_record=factory_record(c['factory_record']))

    def test_authentic_buy_sell_decoding(self):
        events=self.capture['lanes']['pons']['unverified_curve_activity']
        selected={c['address'] for c in self.capture['lanes']['pons']['curves']}
        names=set()
        for event in events:
            if event['address'] in selected:
                d=decode_event(curve_abi(),event)
                self.assertIn(d['name'],('CurveBuy','CurveSell'))
                names.add(d['name'])
                self.assertGreater(d['args']['fee'],0)
        self.assertEqual(names,{'CurveBuy','CurveSell'})

    def test_buy_fee_and_creator_tax(self):
        q=self.state.buy(10000,recipient_exempt=False)
        self.assertEqual(q['fee'],100)
        self.assertEqual(q['creator_tax'],200)
        self.assertEqual(q['tokens_out'],9700*10000000//1689700)

    def test_snipe_tax_decay_and_recipient(self):
        s=replace(self.state,timestamp=100)
        q=s.buy(10000,recipient_exempt=False)
        self.assertEqual(q['snipe_tax'],9600)
        self.assertEqual(s.buy(10000,recipient_exempt=True)['snipe_tax'],0)
        self.assertEqual(replace(s,timestamp=101).buy(10000,recipient_exempt=False)['snipe_tax'],4950)

    def test_partial_last_buy_refunds_and_stops_at_reserve(self):
        q=self.state.buy(100000000,recipient_exempt=False)
        self.assertEqual(q['tokens_out'],8000000)
        self.assertGreater(q['refund'],0)
        self.assertTrue(q['ready_to_graduate'])

    def test_full_position_sell_uses_reserves_and_output_fees(self):
        q=self.state.sell(200000)
        gross=200000*1680000//10200000
        self.assertEqual(q['quote_out'],gross-gross*100//10000-gross*200//10000)
        self.assertEqual(q['tokens_in'],200000)

    def test_virtual_quote_cannot_fabricate_exit(self):
        with self.assertRaisesRegex(BoundaryError,'impossible_full_position_exit'):
            replace(self.state,real_quote=1).sell(200000)

    def test_pending_and_completed_graduation_close_quotes(self):
        for s in (replace(self.state,graduated=True),replace(self.state,token_reserve=2000000)):
            with self.assertRaisesRegex(BoundaryError,'curve_closed'):
                s.sell(100)
            with self.assertRaisesRegex(BoundaryError,'curve_closed'):
                s.buy(100,recipient_exempt=False)

    def test_overflow_and_missing_exemption_fail(self):
        with self.assertRaisesRegex(BoundaryError,'overflow'):
            self.state.buy(2**256-1,recipient_exempt=False)
        with self.assertRaises(BoundaryError):
            self.state.buy(100,recipient_exempt=None)
