"""Synthetic RPC wire fixtures exercise the real interval verifier. Not live proof."""
import base64
import copy
import struct
import tempfile
import unittest
from pathlib import Path
from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import transaction_swap,reconstruct,SWAP,EXACT_IN,EVENT_CPI
from meme_machine.dlmm_paper import Replay
from meme_machine.provider import Unavailable
from meme_machine.store import Store,digest
from tests.dlmm_support import snapshot,change_account,POOL


def encode_state(s,p,slot,now):
    s=copy.deepcopy(s);s.update(slot=slot,market_time=now,available_time=now,kind='real')
    s=change_account(s,POOL,40,struct.pack('<IIi',p['volatility_accumulator'],p['volatility_reference'],p['index_reference']))
    s=change_account(s,POOL,56,struct.pack('<q',p['last_update']))
    s=change_account(s,POOL,76,struct.pack('<i',p['active']))
    for index in s['array_indices']:
        key=dlmm.array_address(POOL,index);raw=bytearray(base64.b64decode(s['accounts'][key]['data'][0]))
        for i in range(70):
            b=p['bins'][str(index*70+i)];off=56+i*144
            struct.pack_into('<QQ',raw,off,b['x'],b['y'])
            for offset,field in [(16,'price'),(32,'supply'),(80,'fee_x'),(96,'fee_y')]:raw[off+offset:off+offset+16]=b[field].to_bytes(16,'little')
        s['accounts'][key]['data'][0]=base64.b64encode(raw).decode()
    return s


def transaction(p,amount,slot,now,signature='synthetic-signature'):
    post,q=dlmm.swap(p,amount,True,now)
    event=(SWAP+pump.un58(POOL)+bytes(32)+struct.pack('<iiQQ?QQ',q['start'],q['end'],amount,q['output'],True,q['fee'],q['protocol_fee'])+bytes(24))
    raw=sorted(EXACT_IN)[0]+struct.pack('<QQ',amount,1)
    tx=dict(slot=slot,blockTime=now,transaction=dict(signatures=[signature],message=dict(accountKeys=[POOL,dlmm.PROGRAM],
        instructions=[dict(programIdIndex=1,accounts=[0],data=pump.b58(raw))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=[dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+event))])],logMessages=[]))
    return post,tx


def interval():
    s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
    post,tx=transaction(p,450_000_000,101,101)
    end=encode_state(s,post,102,102)
    sigs=[dict(signature='synthetic-signature',slot=101,err=None,confirmationStatus='finalized'),
          dict(signature='anchor',slot=99,err=None,confirmationStatus='finalized')]
    return s,p,end,sigs,{'synthetic-signature':tx}


class Tape(unittest.TestCase):
    def test_connected_verified_interval_and_captured_store(self):
        start,p,end,sigs,txs=interval()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'capture.db';store=Store(path,'captured',100_000_000,'synthetic RPC verifier test')
            replay=Replay(store);replay.reserve('lp',start,100);replay.deposit('lp',start,100)
            tape=reconstruct(p,end,sigs,txs,102,store.state['liquidity_positions']['lp']['cursor'])
            replay.process_tape('lp',tape,102)
            self.assertEqual(store.state['liquidity_positions']['lp']['events'],1)
            self.assertTrue(replay.mark('lp',102)['resolved'])
            before=digest(store.state);store.close()
            store=Store(path,'captured',100_000_000,'synthetic RPC verifier test');replay=Replay(store)
            try:
                self.assertEqual(before,digest(store.state))
                with self.assertRaises(Unavailable):replay.process_tape('lp',tape,102)
                replay.exit_intent('lp','test',102);replay.withdraw('lp',102);replay.settle('lp',102)
                self.assertTrue(store.reconcile())
            finally:store.close()

    def test_terminal_is_validation_only_no_backward_inference(self):
        start,p,end,sigs,txs=interval()
        bad=change_account(end,dlmm.array_address(POOL,0),56,(999).to_bytes(8,'little'))
        with self.assertRaisesRegex(Unavailable,'terminal_state'):
            reconstruct(p,bad,sigs,txs,102,[100,2**31-1,2**31-1])
        self.assertEqual(p,dlmm.validate(start,100))

    def test_missing_mutation_ambiguous_order_and_history_fail_closed(self):
        _,p,end,sigs,txs=interval();cursor=[100,2**31-1,2**31-1]
        with self.assertRaisesRegex(Unavailable,'start_boundary'):reconstruct(p,end,sigs[:1],txs,102,cursor)
        with self.assertRaisesRegex(Unavailable,'missing'):reconstruct(p,end,sigs,{},102,cursor)
        more=[sigs[0],dict(signature='another',slot=101,err=None,confirmationStatus='finalized'),sigs[1]]
        with self.assertRaisesRegex(Unavailable,'same_slot'):reconstruct(p,end,more,txs,102,cursor)
        bad=copy.deepcopy(txs);bad['synthetic-signature']['transaction']['message']['instructions'][0]['data']=pump.b58(b'unknown!'+bytes(16))
        with self.assertRaisesRegex(Unavailable,'non_swap_mutation'):reconstruct(p,end,sigs,bad,102,cursor)

    def test_spoofed_events_and_host_fee_rejected(self):
        _,p,end,sigs,txs=interval();tx=txs['synthetic-signature']
        bad=copy.deepcopy(tx);bad['transaction']['message']['accountKeys'][1]=pump.PROGRAM
        with self.assertRaises(Unavailable):transaction_swap(bad,POOL)
        bad=copy.deepcopy(tx);bad['meta']['innerInstructions']=None
        with self.assertRaises(Unavailable):transaction_swap(bad,POOL)
        bad=copy.deepcopy(tx);bad['transaction']['signatures'][0]='wrong'
        with self.assertRaises(Unavailable):reconstruct(p,end,sigs,{'synthetic-signature':bad},102,[100,2**31-1,2**31-1])

    def test_restart_after_real_swap_before_interval_checkpoint(self):
        start,p,end,sigs,txs=interval()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.db';s=Store(path,'captured',100_000_000,'synthetic wire')
            r=Replay(s);r.reserve('lp',start,100);r.deposit('lp',start,100)
            tape=reconstruct(p,end,sigs,txs,102,s.state['liquidity_positions']['lp']['cursor'])
            def lost(stage):
                if stage=='after_commit':raise RuntimeError('lost ack')
            s.hook=lost
            with self.assertRaises(RuntimeError):r.process_tape('lp',tape,102)
            s.close();s=Store(path,'captured',100_000_000,'synthetic wire');r=Replay(s)
            try:
                r.process_tape('lp',tape,102)
                self.assertEqual(s.state['liquidity_positions']['lp']['events'],1)
                self.assertTrue(s.reconcile())
            finally:s.close()
