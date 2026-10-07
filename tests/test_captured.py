"""Real public captures validate protocol decoding, not prospective returns."""
import base64
import copy
import json
import struct
import unittest
from pathlib import Path
from meme_machine import pump
from tests.support import snapshot

FIX=Path(__file__).parent/'fixtures'


class Captured(unittest.TestCase):
    def test_real_trade(self):
        c=json.loads((FIX/'mainnet_trade.json').read_text())
        events=pump.trade_events(c['response'])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['mint'],'GqUH4TqR1dRXtvgdgDAEq3iRMjw6BD3nms35TV5vpump')
        self.assertFalse(events[0]['buy'])
        self.assertEqual(events[0]['amount'],78265222)
        self.assertEqual(events[0]['fees_lamports'],978316)
        self.assertEqual(events[0]['slot'],447633818)
    def test_real_accounts_and_quotes(self):
        c=json.loads((FIX/'mainnet_candidate_accounts.json').read_text())
        accounts=c['response']['value']
        curve=pump.curve(accounts[0]);supply,decimals=pump.mint_info(accounts[1])
        self.assertEqual(supply,curve.supply)
        self.assertEqual(decimals,6)
        self.assertFalse(curve.complete)
        self.assertEqual(pump.pda([b'bonding-curve',pump.un58(c['mint'])]),c['addresses'][0])
        rates=pump.fees(accounts[2],curve)
        self.assertEqual(rates,(95,30))
        tokens,cost,fees=pump.buy(curve,10_000_000,rates)
        output,exit_fees=pump.sell(curve,tokens,rates)
        self.assertGreater(tokens,0);self.assertLessEqual(cost,10_000_000)
        self.assertGreater(fees,0);self.assertLess(output,cost)
    def test_rpc_failures_and_forged_logs_are_not_trades(self):
        tx=json.loads((FIX/'mainnet_trade.json').read_text())['response']
        bad=copy.deepcopy(tx);bad['meta']['err']='failure'
        self.assertEqual(pump.trade_events(bad),[])
        bad=copy.deepcopy(tx)
        bad['meta']['logMessages']=[x.replace(pump.PROGRAM,pump.TOKEN_PROGRAM) for x in bad['meta']['logMessages']]
        self.assertEqual(pump.trade_events(bad),[])
    def test_transfer_tax_extensions_rejected(self):
        a=json.loads((FIX/'mainnet_candidate_accounts.json').read_text())['response']['value'][1]
        raw=bytearray(base64.b64decode(a['data'][0]));struct.pack_into('<H',raw,166,1)
        a['data'][0]=base64.b64encode(raw).decode()
        with self.assertRaisesRegex(ValueError,'unsupported transfer'):
            pump.mint_info(a)
    def test_fee_tier_boundary_and_graduation(self):
        snap=snapshot();c=pump.curve(snap['accounts'][0]);a=snap['accounts'][2]
        raw=bytearray(base64.b64decode(a['data'][0]));struct.pack_into('<I',raw,65,2)
        raw+=int(c.sol*c.supply//c.token).to_bytes(16,'little')+struct.pack('<QQQ',0,95,30)
        a['data'][0]=base64.b64encode(raw).decode()
        self.assertEqual(pump.fees(a,c),(95,30))
        raw=bytearray(base64.b64decode(snap['accounts'][0]['data'][0]));raw[48]=1
        snap['accounts'][0]['data'][0]=base64.b64encode(raw).decode()
        with self.assertRaisesRegex(ValueError,'unavailable'):
            pump.sell(pump.curve(snap['accounts'][0]),100,(95,30))
