import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine import pump
from meme_machine.__main__ import tick_stream
from meme_machine.engine import Engine
from meme_machine.store import Store
from meme_machine.stream import PumpTape, websocket_url
from tests.support import SCOUT, evidence, event, snapshot


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
        self.assertEqual(websocket_url('https://solana.api.onfinality.io/public'),
                         'wss://solana.api.onfinality.io/public-ws')
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            websocket_url('http://example.test')

    def test_durable_tick_uses_only_post_warmup_scout_events_and_stream_window(self):
        class Tape:
            def __init__(self):
                self.cursor=7
                self.fresh=[]
            def status(self,now):
                return dict(covered=True,connected=True,warm_seconds=60,loss_until=0)
            def covered(self,now):
                return True
            def latest_sequence(self):
                return self.cursor
            def events_since(self,cursor):
                return list(self.fresh),self.cursor+len(self.fresh)
            def window(self,mint,now,max_slot=None):
                rows=evidence(now,mint=mint)['events']
                return [dict(x,slot=min(x['slot'],max_slot or x['slot'])) for x in rows]
        class RPC:
            calls=0;http_requests=0;failures=0;cache_hits=0;limit=120
            url='https://api.mainnet-beta.solana.com'
        class Adapter:
            rpc=RPC()
            def snapshot(self,mint,now,priority=False):
                return snapshot(now,mint=mint,slot=now)
            def concentration(self,mint,snap,priority=False):
                return 1000

        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[SCOUT])
            tape=Tape();adapter=Adapter()
            with patch('meme_machine.__main__.time.time',return_value=100):
                cursor=tick_stream(engine,adapter,tape,100,None)
            self.assertEqual(cursor,7)
            self.assertEqual(store.state['orders'],{})
            tape.fresh=[event(now=101)]
            with patch('meme_machine.__main__.time.time',return_value=101):
                cursor=tick_stream(engine,adapter,tape,101,cursor)
            self.assertEqual(store.state['funnel']['nominations'],1)
            self.assertEqual(store.state['funnel']['qualification_attempts'],1)
            self.assertEqual(store.state['funnel']['qualified'],1)
            self.assertEqual(store.state['orders']['nomination']['status'],'reserved')
            store.close()

    def test_durable_tick_stays_fail_closed_without_complete_stream_window(self):
        class Tape:
            def status(self,now):
                return dict(covered=False,connected=True,warm_seconds=20,loss_until=0)
        class RPC:
            calls=0;http_requests=0;failures=0;cache_hits=0;limit=120
            url='https://api.mainnet-beta.solana.com'
        class Adapter: rpc=RPC()
        with tempfile.TemporaryDirectory() as td:
            store=Store(str(Path(td)/'state.db'),'synthetic',100_000_000,'test')
            engine=Engine(store,[SCOUT])
            with patch('meme_machine.__main__.time.time',return_value=100):
                cursor=tick_stream(engine,Adapter(),Tape(),100,None)
            self.assertIsNone(cursor)
            self.assertGreaterEqual(store.state['entry_quarantine_until'],140)
            self.assertEqual(store.state['orders'],{})
            store.close()


if __name__=='__main__':
    unittest.main()