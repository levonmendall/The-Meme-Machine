"""Synthetic RPC wire fixtures exercise the real interval verifier. Not live proof."""
import base64
import copy
import struct
import tempfile
import unittest
from pathlib import Path
from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import (transaction_swap,transaction_swaps,reconstruct,SWAP,SWAP2,EXACT_IN,EVENT_CPI,_un58_data,CLAIM_FEE2_IX,MEMO_PROGRAM,apply_terminal_adjustments)
from meme_machine.dlmm_paper import Replay
from meme_machine.provider import Unavailable
from meme_machine.store import Store,digest
from tests.dlmm_support import snapshot,change_account,POOL


def encode_state(s,p,slot,now):
    s=copy.deepcopy(s);s.update(slot=slot,market_time=now,available_time=now,kind='real')
    s=change_account(s,POOL,40,struct.pack('<IIi',p['volatility_accumulator'],p['volatility_reference'],p['index_reference']))
    s=change_account(s,POOL,56,struct.pack('<q',p['last_update']))
    s=change_account(s,POOL,76,struct.pack('<i',p['active']))
    s=change_account(s,POOL,216,struct.pack('<QQ',p['protocol_fee_x'],p['protocol_fee_y']))
    for key,field in [('vault_x','vault_x_amount'),('vault_y','vault_y_amount')]:
        s=change_account(s,p[key],64,struct.pack('<Q',p[field]))
    for index in s['array_indices']:
        key=dlmm.array_address(POOL,index);raw=bytearray(base64.b64decode(s['accounts'][key]['data'][0]))
        for i in range(70):
            b=p['bins'][str(index*70+i)];off=56+i*144
            struct.pack_into('<QQ',raw,off,b['x'],b['y'])
            for offset,field in [(16,'price'),(32,'supply'),(80,'fee_x'),(96,'fee_y')]:raw[off+offset:off+offset+16]=b[field].to_bytes(16,'little')
        s['accounts'][key]['data'][0]=base64.b64encode(raw).decode()
    return s


def transaction(p,amount,slot,now,signature='synthetic-signature',swap2=False):
    post,q=dlmm.swap(p,amount,True,now)
    event=(SWAP+pump.un58(POOL)+bytes(32)+struct.pack('<iiQQ?QQ',q['start'],q['end'],amount,q['output'],True,q['fee'],q['protocol_fee'])+bytes(24))
    raw=sorted(EXACT_IN)[0]+struct.pack('<QQ',amount,1)
    events=[dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+event))]
    if swap2:
        event2=(SWAP2+pump.un58(POOL)+bytes(32)+struct.pack('<ii?',q['start'],q['end'],True)+
                bytes(16)+struct.pack('<QQQQQQQ??',amount,0,q['output'],q['fee']-q['protocol_fee'],
                q['protocol_fee'],0,0,True,True))
        events.append(dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+event2)))
    tx=dict(slot=slot,blockTime=now,transaction=dict(signatures=[signature],message=dict(accountKeys=[POOL,dlmm.PROGRAM],
        instructions=[dict(programIdIndex=1,accounts=[0],data=pump.b58(raw))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=events)],logMessages=[]))
    return post,tx



def claim_fee2_transaction(p,claimed_x,claimed_y,slot=101,now=101,signature='claim-fee2'):
    position=pump.b58(bytes([31])*32);sender=pump.b58(bytes([32])*32)
    user_x=pump.b58(bytes([33])*32);user_y=pump.b58(bytes([34])*32)
    event_authority=pump.b58(bytes([35])*32)
    keys=[POOL,position,sender,p['vault_x'],p['vault_y'],user_x,user_y,
          p['x'],p['y'],pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,MEMO_PROGRAM,
          event_authority,dlmm.PROGRAM]
    raw=CLAIM_FEE2_IX+struct.pack('<ii',p['active']-2,p['active']+2)
    def row(index,mint,amount):
        return dict(accountIndex=index,mint=mint,
                    uiTokenAmount=dict(amount=str(amount)))
    pre_x=p['vault_x_amount'];pre_y=p['vault_y_amount']
    if not 0<=claimed_x<=pre_x or not 0<=claimed_y<=pre_y:
        raise ValueError('claim fixture')
    meta=dict(
        err=None,innerInstructions=[],logMessages=[],
        preTokenBalances=[
            row(3,p['x'],pre_x),row(4,p['y'],pre_y),
            row(5,p['x'],0),row(6,p['y'],0)],
        postTokenBalances=[
            row(3,p['x'],pre_x-claimed_x),row(4,p['y'],pre_y-claimed_y),
            row(5,p['x'],claimed_x),row(6,p['y'],claimed_y)],
    )
    tx=dict(slot=slot,blockTime=now,
        transaction=dict(signatures=[signature],message=dict(
            accountKeys=keys,instructions=[dict(
                programIdIndex=13,accounts=list(range(14)),data=pump.b58(raw))])),
        meta=meta)
    post=copy.deepcopy(p)
    post['vault_x_amount']-=claimed_x
    post['vault_y_amount']-=claimed_y
    return post,tx


def interval():
    s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
    post,tx=transaction(p,450_000_000,101,101)
    end=encode_state(s,post,102,102)
    sigs=[dict(signature='synthetic-signature',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),
          dict(signature='anchor',slot=99,transactionIndex=2,err=None,confirmationStatus='finalized')]
    return s,p,end,sigs,{'synthetic-signature':tx}


class Tape(unittest.TestCase):
    def test_claim_fee2_exact_vault_transfer_is_terminal_adjustment(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,tx=claim_fee2_transaction(p,1234,5678)
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='claim-fee2',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'claim-fee2':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(tape.events,())
        self.assertEqual(len(tape.terminal_adjustments),1)
        adjustment=tape.terminal_adjustments[0]
        self.assertEqual(adjustment['kind'],'claim_fee2')
        self.assertEqual((adjustment['claimed_x'],adjustment['claimed_y']),(1234,5678))
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])
        self.assertEqual(adjusted['vault_y_amount'],post['vault_y_amount'])
        # Outside reconstruction context, claimFee2 remains explicit rather than
        # silently appearing to be an empty transaction.
        with self.assertRaisesRegex(Unavailable,'claim_fee2_requires'):
            transaction_swaps(tx,POOL)

    def test_claim_fee2_wrong_user_delta_fails_closed(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,tx=claim_fee2_transaction(p,1234,0)
        tx=copy.deepcopy(tx)
        tx['meta']['postTokenBalances'][2]['uiTokenAmount']['amount']='1233'
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='claim-fee2',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        with self.assertRaisesRegex(Unavailable,'claim_fee2_balance_delta'):
            reconstruct(p,end,sigs,{'claim-fee2':tx},102,[100,2**31-1,2**31-1])

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
        more=[sigs[0],dict(signature='another',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),sigs[1]]
        with self.assertRaisesRegex(Unavailable,'order_ambiguous'):reconstruct(p,end,more,txs,102,cursor)
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

    def test_current_swap2_companion_is_cross_checked(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,tx=transaction(p,450_000_000,101,101,swap2=True)
        decoded=transaction_swap(tx,POOL)
        self.assertEqual(decoded['amount'],450_000_000)
        bad=copy.deepcopy(tx)
        raw=bytearray(_un58_data(bad['meta']['innerInstructions'][0]['instructions'][1]['data']))
        # EVENT_CPI (8) + Swap2Evt amount_left offset (105).
        raw[113:121]=(1).to_bytes(8,'little')
        bad['meta']['innerInstructions'][0]['instructions'][1]['data']=pump.b58(bytes(raw))
        with self.assertRaisesRegex(Unavailable,'partial_limit'):
            transaction_swap(bad,POOL)

    def test_same_slot_transactions_use_rpc_transaction_index_order(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        p1,tx1=transaction(p,1_000_000,101,101,'first')
        p2,tx2=transaction(p1,2_000_000,101,101,'second')
        end=encode_state(s,p2,102,102)
        sigs=[dict(signature='second',slot=101,transactionIndex=8,err=None,confirmationStatus='finalized'),
              dict(signature='first',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),
              dict(signature='anchor',slot=99,transactionIndex=2,err=None,confirmationStatus='finalized')]
        tape=reconstruct(p,end,sigs,{'first':tx1,'second':tx2},102,[100,2**31-1,2**31-1])
        self.assertEqual([e['cursor'] for e in tape.events],[[101,7,0],[101,8,0]])
        with self.assertRaisesRegex(Unavailable,'signature_order'):
            reconstruct(p,end,[sigs[1],sigs[0],sigs[2]],{'first':tx1,'second':tx2},102,
                        [100,2**31-1,2**31-1])

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
