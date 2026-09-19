import base64
import struct
import unittest

from meme_machine import pump
from meme_machine.stream import PumpTape


def _s(value):
    raw=value.encode()
    return struct.pack("<I",len(raw))+raw


class PumpAccelerationStreamExtensions(unittest.TestCase):
    def create_log(self):
        mint=bytes([3])*32
        curve=bytes([4])*32
        user=bytes([5])*32
        creator=bytes([6])*32
        raw=bytearray(bytes([27,114,169,77,222,235,99,118]))
        raw+=_s("Token")+_s("TOK")+_s("https://example.invalid")
        raw+=mint+curve+user+creator
        raw+=struct.pack("<qQQQQ",100,1_000_000,30_000_000_000,800_000,1_000_000)
        return "Program data: "+base64.b64encode(raw).decode(),pump.b58(mint),pump.b58(curve)

    def test_create_event_is_prospectively_retained(self):
        log,mint,curve=self.create_log()
        tx={"slot":10,"meta":{"err":None,"logMessages":[
            f"Program {pump.PROGRAM} invoke [1]",log,f"Program {pump.PROGRAM} success",
        ]}}
        rows=pump.create_events(tx)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["mint"],mint)
        self.assertEqual(rows[0]["bonding_curve"],curve)
        self.assertEqual(rows[0]["initial_real_token_reserves"],800_000)

        note={"method":"logsNotification","params":{"result":{
            "context":{"slot":10},
            "value":{"signature":"sig","err":None,"logs":tx["meta"]["logMessages"]},
        }}}
        tape=PumpTape(clock=lambda:101)
        tape.begin(100)
        self.assertEqual(tape.ingest_notification(note,101),0)
        creation=tape.creation(mint)
        self.assertEqual(creation["initial_real_token_reserves"],800_000)
        self.assertEqual(tape.status(101)["creation_events"],1)

    def test_trade_event_exposes_point_in_time_reserve_state(self):
        import json
        from pathlib import Path
        fixture=json.loads((Path(__file__).parent/"fixtures"/"mainnet_trade.json").read_text())
        event=pump.trade_events(fixture["response"])[0]
        self.assertGreater(event["virtual_quote_reserves"],0)
        self.assertGreater(event["virtual_token_reserves"],0)
        self.assertGreaterEqual(event["real_quote_reserves"],0)
        self.assertGreaterEqual(event["real_token_reserves"],0)
        self.assertTrue(event["creator"])


if __name__=="__main__":
    unittest.main()
