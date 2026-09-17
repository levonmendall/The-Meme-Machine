import json
import tempfile
import unittest
from pathlib import Path

from meme_machine.engine import GAS, RENT
from meme_machine.postgrad import buy_quote
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.store import Store

FIXTURE = Path(__file__).parent/'fixtures'/'postgrad_pumpswap_mainnet.json'


class Clock:
    def __init__(self,value):
        self.value=int(value)
    def __call__(self):
        return self.value


class CapturedAdapter:
    def __init__(self,doc,clock):
        self.graduation=doc['capture']['graduation']
        self.snapshot=doc['capture']['snapshot']
        self.clock=clock
    def graduation_snapshot(self,mint,now,priority=True):
        if mint != self.graduation['mint']:
            raise ValueError('fixture_mint')
        return dict(self.graduation)
    def pumpswap_snapshot(self,handoff,now,priority=True):
        if handoff.mint != self.snapshot['mint']:
            raise ValueError('fixture_mint')
        return dict(self.snapshot)


class CapturedDurableContinuation(unittest.TestCase):
    def test_captured_mainnet_handoff_and_quote_fill_existing_reservation(self):
        doc=json.loads(FIXTURE.read_text())
        graduation=doc['capture']['graduation']
        snapshot=doc['capture']['snapshot']
        now=max(int(graduation['available_time']),int(snapshot['available_time']))
        clock=Clock(now)
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'paper.db')
            store=Store(db,'prospective',100_000_000,'captured-mainnet-reference')
            amount=store.state['initial']//20
            quote=buy_quote(snapshot,amount)
            reservation=amount+GAS+RENT
            created=min(int(graduation['market_time']),int(snapshot['market_time']))-5
            due=created+2
            oid='captured-existing-reservation'
            with store.transaction('captured_upstream_authority'):
                s=store.state
                s['cash']-=reservation
                s['reserved']+=reservation
                s['orders'][oid]=dict(
                    status='reserved',mint=snapshot['mint'],related=snapshot['creator'],
                    reservation=reservation,budget=amount,
                    min_tokens=quote.output_amount*9900//10000,
                    created=created,due=due,slot=int(graduation['slot'])-1,
                    evidence={'authority':'preexisting continuation-v1 reservation'},
                    nomination={'id':'captured-reference'},
                )
            runtime=PumpSwapPaperRuntime(store,CapturedAdapter(doc,clock),clock=clock)
            self.assertEqual(runtime.fill_existing_order(oid),'settled')
            self.assertEqual(store.state['orders'][oid]['fill_snapshot']['pool'],snapshot['pool'])
            self.assertEqual(store.state['orders'][oid]['fill']['tokens'],quote.output_amount)
            self.assertEqual(store.state['positions'][snapshot['mint']]['surface'],'pumpswap')
            self.assertEqual(store.state['positions'][snapshot['mint']]['pool'],snapshot['pool'])
            self.assertEqual(store.state['reserved'],0)
            self.assertTrue(store.reconcile())
            store.close()

            store=Store(db,'prospective',100_000_000,'captured-mainnet-reference')
            self.assertEqual(store.state['positions'][snapshot['mint']]['surface'],'pumpswap')
            self.assertIn('postgrad_handoff',store.state['positions'][snapshot['mint']])
            self.assertTrue(store.reconcile())
            self.assertTrue(store.verify_archive())
            store.close()


if __name__ == '__main__':
    unittest.main()
