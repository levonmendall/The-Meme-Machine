import json
import unittest
from pathlib import Path

from meme_machine import pump
from meme_machine.stream import PumpTape, websocket_url


class StreamTape(unittest.TestCase):
    def notification(self, signature='sig'):
        fixture=json.loads((Path(__file__).parent/'fixtures'/'mainnet_trade.json').read_text())
        tx=fixture['response']
        return {'jsonrpc':'2.0','method':'logsNotification','params':{'result':{
            'context':{'slot':tx['slot']},
            'value':{'signature':signature,'err':tx['meta']['err'],
                     'logs':tx['meta']['logMessages']}}}}

    def test_captured_finalized_notification_becomes_point_in_time_trade(self):
        note=self.notification('captured')
        tx={'slot':note['params']['result']['context']['slot'],
            'meta':{'err':None,'logMessages':note['params']['result']['value']['logs']}}
        decoded=pump.trade_events(tx)
        self.assertEqual(len(decoded),1)
        now=decoded[0]['market_time']+1
        tape=PumpTape(clock=lambda:now)
        tape.begin(now-60)
        self.assertEqual(tape.ingest_notification(note,now),1)
        self.assertTrue(tape.covered(now))
        rows=tape.window(decoded[0]['mint'],now)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],f"captured:{decoded[0]['index']}")
        self.assertEqual(rows[0]['available_time'],now)
        fresh,cursor=tape.events_since(0)
        self.assertEqual(fresh,rows)
        self.assertEqual(cursor,1)

    def test_disconnect_resets_coverage_and_requires_full_rewarm(self):
        tape=PumpTape(clock=lambda:200)
        tape.begin(100)
        self.assertTrue(tape.covered(200))
        tape.gap(200)
        self.assertFalse(tape.covered(260))
        tape.begin(261)
        self.assertFalse(tape.covered(320))
        self.assertTrue(tape.covered(321))

    def test_capacity_loss_fails_closed_for_complete_window(self):
        note=self.notification('one')
        tx={'slot':note['params']['result']['context']['slot'],
            'meta':{'err':None,'logMessages':note['params']['result']['value']['logs']}}
        now=pump.trade_events(tx)[0]['market_time']+1
        tape=PumpTape(max_events=1,clock=lambda:now)
        tape.begin(now-60)
        tape.ingest_notification(note,now)
        tape.ingest_notification(self.notification('two'),now)
        self.assertEqual(tape.status(now)['capacity_losses'],1)
        self.assertFalse(tape.covered(now))
        self.assertFalse(tape.covered(now+59))

    def test_http_rpc_path_maps_to_same_secure_websocket_endpoint(self):
        self.assertEqual(websocket_url('https://api.mainnet-beta.solana.com'),
                         'wss://api.mainnet-beta.solana.com')
        self.assertEqual(websocket_url('https://example.test/v2/key?x=1'),
                         'wss://example.test/v2/key?x=1')
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            websocket_url('http://example.test')


if __name__=='__main__':
    unittest.main()
