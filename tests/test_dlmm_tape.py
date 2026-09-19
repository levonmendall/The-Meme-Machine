"""Synthetic RPC wire fixtures exercise the real interval verifier. Not live proof."""
import base64
import copy
import struct
import tempfile
import unittest
from pathlib import Path
from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import (transaction_swap,transaction_swaps,reconstruct,SWAP,SWAP2,EXACT_IN,EVENT_CPI,_un58_data,CLAIM_FEE2_IX,CLAIM_FEE2_EVT,SWAP_EXACT_OUT2_IX,REMOVE_LIQUIDITY_BY_RANGE2_IX,REMOVE_LIQUIDITY_EVT,ADD_LIQUIDITY2_IX,ADD_LIQUIDITY_EVT,INITIALIZE_POSITION_IX,MEMO_PROGRAM,apply_terminal_adjustments)
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



def _balance_row(index,mint,amount):
    return dict(accountIndex=index,mint=mint,
                uiTokenAmount=dict(amount=str(amount)))


def claim_fee2_transaction(p,claimed_x,claimed_y,slot=101,now=101,signature='claim-fee2'):
    position=pump.b58(bytes([31])*32);sender=pump.b58(bytes([32])*32)
    user_x=pump.b58(bytes([33])*32);user_y=pump.b58(bytes([34])*32)
    event_authority=pump.b58(bytes([35])*32)
    keys=[POOL,position,sender,p['vault_x'],p['vault_y'],user_x,user_y,
          p['x'],p['y'],pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,MEMO_PROGRAM,
          event_authority,dlmm.PROGRAM]
    raw=CLAIM_FEE2_IX+struct.pack('<ii',p['active']-2,p['active']+2)
    event=(CLAIM_FEE2_EVT+pump.un58(POOL)+pump.un58(position)+
           pump.un58(sender)+struct.pack('<QQi',claimed_x,claimed_y,p['active']))
    pre_x=p['vault_x_amount'];pre_y=p['vault_y_amount']
    if not 0<=claimed_x<=pre_x or not 0<=claimed_y<=pre_y:
        raise ValueError('claim fixture')
    meta=dict(
        err=None,
        innerInstructions=[dict(index=0,instructions=[
            dict(programIdIndex=13,accounts=[],
                 data=pump.b58(EVENT_CPI+event))])],
        logMessages=[],
        preTokenBalances=[
            _balance_row(3,p['x'],pre_x),_balance_row(4,p['y'],pre_y),
            _balance_row(5,p['x'],0),_balance_row(6,p['y'],0)],
        postTokenBalances=[
            _balance_row(3,p['x'],pre_x-claimed_x),
            _balance_row(4,p['y'],pre_y-claimed_y),
            _balance_row(5,p['x'],claimed_x),
            _balance_row(6,p['y'],claimed_y)],
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


def exact_out_transaction(p,out_amount,slot=101,now=101,signature='exact-out'):
    post,q=dlmm.swap_exact_out(p,out_amount,True,now)
    bitmap=pump.b58(bytes([44])*32);user_in=pump.b58(bytes([45])*32)
    user_out=pump.b58(bytes([46])*32);oracle=pump.b58(bytes([47])*32)
    user=pump.b58(bytes([48])*32);event_authority=pump.b58(bytes([49])*32)
    keys=[POOL,bitmap,p['vault_x'],p['vault_y'],user_in,user_out,p['x'],p['y'],
          oracle,dlmm.PROGRAM,user,pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,
          MEMO_PROGRAM,event_authority,dlmm.PROGRAM]
    raw=SWAP_EXACT_OUT2_IX+struct.pack('<QQ',q['input']+1,out_amount)
    event=(SWAP2+pump.un58(POOL)+bytes(32)+
           struct.pack('<ii?',q['start'],q['end'],True)+bytes(16)+
           struct.pack('<QQQQQQQ??',q['input'],0,q['output'],
                       q['fee']-q['protocol_fee'],q['protocol_fee'],0,0,True,True))
    tx=dict(
        slot=slot,blockTime=now,
        transaction=dict(signatures=[signature],message=dict(
            accountKeys=keys,instructions=[dict(
                programIdIndex=15,accounts=list(range(16)),
                data=pump.b58(raw))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=[
            dict(programIdIndex=15,accounts=[],
                 data=pump.b58(EVENT_CPI+event))])],
                  logMessages=[],preTokenBalances=[],postTokenBalances=[]))
    return post,q,tx


def remove_liquidity_transaction(p,bid=0,share=None,claim_x=0,claim_y=0,
                                 slot=101,now=101,signature='remove'):
    position=pump.b58(bytes([50])*32);sender=pump.b58(bytes([51])*32)
    bitmap=dlmm.PROGRAM;user_x=pump.b58(bytes([52])*32)
    user_y=pump.b58(bytes([53])*32);event_authority=pump.b58(bytes([54])*32)
    b=p['bins'][str(bid)]
    share=share or max(1,b['supply']//10)
    if share>b['supply']:
        raise ValueError('remove fixture share')
    x=dlmm.withdraw_amount(share,b['x'],b['supply'])
    y=dlmm.withdraw_amount(share,b['y'],b['supply'])
    post=copy.deepcopy(p);pb=post['bins'][str(bid)]
    pb['x']-=x;pb['y']-=y;pb['supply']-=share
    post['vault_x_amount']-=x;post['vault_y_amount']-=y
    main=[position,POOL,bitmap,user_x,user_y,p['vault_x'],p['vault_y'],
          p['x'],p['y'],sender,pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,
          MEMO_PROGRAM,event_authority,dlmm.PROGRAM]
    remove_raw=REMOVE_LIQUIDITY_BY_RANGE2_IX+struct.pack('<iiH',bid,bid,10000)
    remove_event=(REMOVE_LIQUIDITY_EVT+pump.un58(POOL)+pump.un58(sender)+
                  pump.un58(position)+struct.pack('<QQi',x,y,p['active']))
    instructions=[dict(programIdIndex=14,accounts=list(range(15)),
                       data=pump.b58(remove_raw))]
    inners=[dict(programIdIndex=14,accounts=[],
                 data=pump.b58(EVENT_CPI+remove_event))]
    expected_x=x;expected_y=y
    if claim_x or claim_y:
        claim_accounts=[1,0,9,5,6,3,4,7,8,10,11,12,13,14]
        claim_raw=CLAIM_FEE2_IX+struct.pack('<ii',bid,bid)
        claim_event=(CLAIM_FEE2_EVT+pump.un58(POOL)+pump.un58(position)+
                     pump.un58(sender)+
                     struct.pack('<QQi',claim_x,claim_y,p['active']))
        instructions.append(dict(programIdIndex=14,accounts=claim_accounts,
                                 data=pump.b58(claim_raw)))
        # Event belongs to the second top-level instruction.
        expected_x+=claim_x;expected_y+=claim_y
        post['vault_x_amount']-=claim_x;post['vault_y_amount']-=claim_y
        inner_groups=[
            dict(index=0,instructions=inners),
            dict(index=1,instructions=[dict(
                programIdIndex=14,accounts=[],
                data=pump.b58(EVENT_CPI+claim_event))])]
    else:
        inner_groups=[dict(index=0,instructions=inners)]
    pre_x=p['vault_x_amount'];pre_y=p['vault_y_amount']
    balances_pre=[
        _balance_row(5,p['x'],pre_x),_balance_row(6,p['y'],pre_y),
        _balance_row(3,p['x'],0),_balance_row(4,p['y'],0)]
    balances_post=[
        _balance_row(5,p['x'],pre_x-expected_x),
        _balance_row(6,p['y'],pre_y-expected_y),
        _balance_row(3,p['x'],expected_x),
        _balance_row(4,p['y'],expected_y)]
    tx=dict(
        slot=slot,blockTime=now,
        transaction=dict(signatures=[signature],message=dict(
            accountKeys=main,instructions=instructions)),
        meta=dict(err=None,innerInstructions=inner_groups,logMessages=[],
                  preTokenBalances=balances_pre,
                  postTokenBalances=balances_post))
    return post,dict(share=share,x=x,y=y),tx


def add_liquidity2_transaction(p,amount_x=1_000_001,amount_y=0,
                               slot=101,now=101,signature='add2'):
    if bool(amount_x)==bool(amount_y):
        raise ValueError('add2 fixture is single-sided')
    position=pump.b58(bytes([60])*32);sender=pump.b58(bytes([61])*32)
    bitmap=dlmm.PROGRAM;user_x=pump.b58(bytes([62])*32)
    user_y=pump.b58(bytes([63])*32);event_authority=pump.b58(bytes([64])*32)
    if amount_x:
        bids=[p['active']+1,p['active']+2]
    else:
        bids=[p['active']-2,p['active']-1]
    rows=[(bids[0],5000,5000),(bids[1],5000,5000)]
    actual_x=sum(amount_x*dx//10000 for _bid,dx,_dy in rows)
    actual_y=sum(amount_y*dy//10000 for _bid,_dx,dy in rows)
    post=copy.deepcopy(p)
    for bid,dx,dy in rows:
        x=amount_x*dx//10000;y=amount_y*dy//10000
        b=post['bins'][str(bid)]
        share=dlmm.deposit_share(b,x,y)
        b['x']+=x;b['y']+=y;b['supply']+=share
        post['vault_x_amount']+=x;post['vault_y_amount']+=y
    keys=[position,POOL,bitmap,user_x,user_y,p['vault_x'],p['vault_y'],
          p['x'],p['y'],sender,pump.TOKEN_PROGRAM,pump.TOKEN_PROGRAM,
          event_authority,dlmm.PROGRAM]
    raw=bytearray(ADD_LIQUIDITY2_IX+struct.pack('<QQI',amount_x,amount_y,len(rows)))
    for bid,dx,dy in rows:
        raw.extend(struct.pack('<iHH',bid,dx,dy))
    # RemainingAccountsInfo: TransferHookX len 0, TransferHookY len 0.
    raw.extend(struct.pack('<I',2)+bytes([0,0,1,0]))
    event=(ADD_LIQUIDITY_EVT+pump.un58(POOL)+pump.un58(sender)+
           pump.un58(position)+struct.pack('<QQi',actual_x,actual_y,p['active']))
    def transfer(source,mint,destination,amount,decimals):
        return dict(programIdIndex=10,accounts=[source,mint,destination,9],
                    data=pump.b58(bytes([12])+int(amount).to_bytes(8,'little')+
                                  bytes([decimals])))
    inner=[
        transfer(3,7,5,actual_x,6),
        transfer(4,8,6,actual_y,9),
        dict(programIdIndex=13,accounts=[12],data=pump.b58(EVENT_CPI+event)),
    ]
    pre_x=p['vault_x_amount'];pre_y=p['vault_y_amount']
    tx=dict(
        slot=slot,blockTime=now,
        transaction=dict(signatures=[signature],message=dict(
            accountKeys=keys,instructions=[dict(
                programIdIndex=13,accounts=list(range(14)),
                data=pump.b58(bytes(raw)))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=inner)],
                  logMessages=[],
                  preTokenBalances=[
                      _balance_row(3,p['x'],10_000_000),
                      _balance_row(4,p['y'],10_000_000),
                      _balance_row(5,p['x'],pre_x),
                      _balance_row(6,p['y'],pre_y)],
                  postTokenBalances=[
                      _balance_row(3,p['x'],10_000_000-actual_x),
                      _balance_row(4,p['y'],10_000_000-actual_y),
                      _balance_row(5,p['x'],pre_x+actual_x),
                      _balance_row(6,p['y'],pre_y+actual_y)]))
    return post,dict(actual_x=actual_x,actual_y=actual_y,bids=bids),tx


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
        self.assertEqual((adjustment['amount_x'],adjustment['amount_y']),(1234,5678))
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])
        self.assertEqual(adjusted['vault_y_amount'],post['vault_y_amount'])
        # Outside reconstruction context, claimFee2 remains explicit rather than
        # silently appearing to be an empty transaction.
        with self.assertRaisesRegex(Unavailable,'external_effect_requires'):
            transaction_swaps(tx,POOL)
        self.assertEqual(transaction_swaps(tx,POOL,trigger_only=True),[])

    def test_claim_fee2_event_binds_across_intervening_dlmm_inner_instruction(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,tx=claim_fee2_transaction(p,321,654)
        tx=copy.deepcopy(tx)
        tx['meta']['innerInstructions'][0]['instructions'].insert(
            0,dict(
                programIdIndex=13,
                accounts=[1,1,1,1,1,1,1,1],
                data=pump.b58(INITIALIZE_POSITION_IX),
            ))
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='claim-fee2',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'claim-fee2':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.terminal_adjustments),1)
        self.assertEqual(tape.terminal_adjustments[0]['kind'],'claim_fee2')

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
        with self.assertRaisesRegex(Unavailable,'external_effect_balance_delta'):
            reconstruct(p,end,sigs,{'claim-fee2':tx},102,[100,2**31-1,2**31-1])

    def test_add_liquidity2_replays_floor_distribution_exactly(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,added,tx=add_liquidity2_transaction(p,amount_x=1_000_001)
        self.assertEqual(added['actual_x'],1_000_000)
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='add2',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'add2':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(tape.events,())
        self.assertEqual(len(tape.terminal_adjustments),1)
        item=tape.terminal_adjustments[0]
        self.assertEqual(item['kind'],'add_liquidity2')
        self.assertEqual(item['amount_x'],1_000_000)
        self.assertEqual(item['recipient_auth'],'ordered_spl_transfer')
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['bins'][str(added['bids'][0])],
                         post['bins'][str(added['bids'][0])])
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])

    def test_add_liquidity2_wrong_transfer_fails_closed(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,_added,tx=add_liquidity2_transaction(p,amount_y=1_000_001,amount_x=0)
        bad=copy.deepcopy(tx)
        ix=bad['meta']['innerInstructions'][0]['instructions'][1]
        raw=bytearray(_un58_data(ix['data']))
        raw[1:9]=(int.from_bytes(raw[1:9],'little')+1).to_bytes(8,'little')
        ix['data']=pump.b58(bytes(raw))
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='add2',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        with self.assertRaisesRegex(
                Unavailable,'add_liquidity2_transfer_amount_mismatch'):
            reconstruct(
                p,end,sigs,{'add2':bad},102,[100,2**31-1,2**31-1])

    def test_exact_out2_reconstructs_actual_input_output_and_terminal_state(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,q,tx=exact_out_transaction(p,20_000_000)
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='exact-out',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'exact-out':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.events),1)
        event=tape.events[0]
        self.assertEqual(event['swap_mode'],'exact_out')
        self.assertEqual(event['amount'],q['input'])
        self.assertEqual(event['observed']['output'],20_000_000)
        bad=copy.deepcopy(tx)
        raw=bytearray(_un58_data(
            bad['transaction']['message']['instructions'][0]['data']))
        raw[16:24]=(20_000_001).to_bytes(8,'little')
        bad['transaction']['message']['instructions'][0]['data']=pump.b58(bytes(raw))
        with self.assertRaisesRegex(ValueError,'exact_out_instruction_event'):
            reconstruct(
                p,end,sigs,{'exact-out':bad},102,[100,2**31-1,2**31-1])

    def test_remove_liquidity_by_range2_reconstructs_exact_bin_share_delta(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,removed,tx=remove_liquidity_transaction(p,bid=0)
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='remove',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tx=copy.deepcopy(tx)
        tx['meta']['innerInstructions'][0]['instructions'].insert(
            0,dict(
                programIdIndex=14,
                accounts=[0,0,0,0,0,0,0,0],
                data=pump.b58(INITIALIZE_POSITION_IX),
            ))
        tape=reconstruct(
            p,end,sigs,{'remove':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(tape.events,())
        self.assertEqual(len(tape.terminal_adjustments),1)
        item=tape.terminal_adjustments[0]
        self.assertEqual(item['kind'],'remove_liquidity_by_range2')
        self.assertEqual(item['removed_shares'],{'0':removed['share']})
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['bins']['0'],post['bins']['0'])
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])
        self.assertEqual(adjusted['vault_y_amount'],post['vault_y_amount'])

    def test_remove_plus_claim_uses_aggregate_transaction_balance_delta(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,removed,tx=remove_liquidity_transaction(
            p,bid=0,claim_x=123,claim_y=456)
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='remove',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'remove':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(
            [x['kind'] for x in tape.terminal_adjustments],
            ['remove_liquidity_by_range2','claim_fee2'])
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])
        self.assertEqual(adjusted['vault_y_amount'],post['vault_y_amount'])
        bad=copy.deepcopy(tx)
        # Break only the transaction-level aggregate user X receipt.
        bad['meta']['postTokenBalances'][2]['uiTokenAmount']['amount']=str(
            removed['x']+123-1)
        with self.assertRaisesRegex(Unavailable,'external_effect_balance_delta'):
            reconstruct(
                p,end,sigs,{'remove':bad},102,[100,2**31-1,2**31-1])

    def test_external_effect_new_ata_uses_ordered_transfer_proof(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        claim_x,claim_y=123,456
        post,removed,tx=remove_liquidity_transaction(
            p,bid=0,claim_x=claim_x,claim_y=claim_y,
            signature='new-ata-effects')
        tx=copy.deepcopy(tx)

        def transfer_checked(source,mint,destination,amount):
            return dict(
                programIdIndex=10,
                accounts=[source,mint,destination,1],
                data=pump.b58(
                    bytes([12])+int(amount).to_bytes(8,'little')+bytes([0])),
            )

        remove_transfers=[]
        if removed['x']:
            remove_transfers.append(
                transfer_checked(5,7,3,removed['x']))
        if removed['y']:
            remove_transfers.append(
                transfer_checked(6,8,4,removed['y']))
        claim_transfers=[]
        if claim_x:
            claim_transfers.append(transfer_checked(5,7,3,claim_x))
        if claim_y:
            claim_transfers.append(transfer_checked(6,8,4,claim_y))
        tx['meta']['innerInstructions'][0]['instructions'][
            0:0]=remove_transfers
        tx['meta']['innerInstructions'][1]['instructions'][
            0:0]=claim_transfers

        # Match the natural PERPSPAD shape: destination ATA is created in the
        # transaction, so there is no preTokenBalances row for user Y.
        tx['meta']['preTokenBalances']=[
            row for row in tx['meta']['preTokenBalances']
            if row.get('accountIndex')!=4
        ]

        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='new-ata-effects',slot=101,transactionIndex=7,
                 err=None,confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'new-ata-effects':tx},102,
            [100,2**31-1,2**31-1])
        self.assertEqual(
            [item['recipient_auth'] for item in tape.terminal_adjustments],
            ['ordered_spl_transfer','ordered_spl_transfer'])
        adjusted=apply_terminal_adjustments(p,tape.terminal_adjustments)
        self.assertEqual(adjusted['vault_x_amount'],post['vault_x_amount'])
        self.assertEqual(adjusted['vault_y_amount'],post['vault_y_amount'])

        bad=copy.deepcopy(tx)
        # Corrupt one authenticated reserve->user transfer by one unit.
        ix=bad['meta']['innerInstructions'][0]['instructions'][0]
        raw=bytearray(_un58_data(ix['data']))
        raw[1:9]=(int.from_bytes(raw[1:9],'little')+1).to_bytes(8,'little')
        ix['data']=pump.b58(bytes(raw))
        with self.assertRaisesRegex(
                Unavailable,'external_effect_transfer_amount_mismatch'):
            reconstruct(
                p,end,sigs,{'new-ata-effects':bad},102,
                [100,2**31-1,2**31-1])

    def test_external_effect_missing_balance_has_external_reason(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,_removed,tx=remove_liquidity_transaction(
            p,bid=0,claim_x=123,claim_y=456,
            signature='missing-effect-balance')
        tx=copy.deepcopy(tx)
        tx['meta']['preTokenBalances']=[
            row for row in tx['meta']['preTokenBalances']
            if row.get('accountIndex')!=4
        ]
        end=encode_state(s,post,102,102)
        sigs=[
            dict(signature='missing-effect-balance',slot=101,
                 transactionIndex=7,err=None,confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,err=None,
                 confirmationStatus='finalized')]
        with self.assertRaisesRegex(
                Unavailable,'dlmm_external_effect_token_balance_missing'):
            reconstruct(
                p,end,sigs,{'missing-effect-balance':tx},102,
                [100,2**31-1,2**31-1])

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

    def test_remove_claim_tape_resumes_after_lost_adjustment_ack(self):
        start=snapshot();start['kind']='real';p=dlmm.validate(start,100)
        post,_removed,tx=remove_liquidity_transaction(
            p,bid=0,claim_x=123,claim_y=456,signature='remove-restart')
        end=encode_state(start,post,102,102)
        sigs=[
            dict(signature='remove-restart',slot=101,transactionIndex=7,
                 err=None,confirmationStatus='finalized'),
            dict(signature='anchor',slot=99,transactionIndex=2,
                 err=None,confirmationStatus='finalized')]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'adjustment-restart.db'
            store=Store(path,'captured',100_000_000,'adjustment restart')
            replay=Replay(store)
            replay.reserve('lp',start,100);replay.deposit('lp',start,100)
            tape=reconstruct(
                p,end,sigs,{'remove-restart':tx},102,
                store.state['liquidity_positions']['lp']['cursor'])
            fired={'value':False}
            def lost(stage):
                if stage=='after_commit' and not fired['value']:
                    fired['value']=True
                    raise RuntimeError('lost adjustment ack')
            store.hook=lost
            with self.assertRaisesRegex(RuntimeError,'lost adjustment ack'):
                replay.process_tape('lp',tape,102)
            store.close()
            store=Store(path,'captured',100_000_000,'adjustment restart')
            replay=Replay(store)
            try:
                replay.process_tape('lp',tape,102)
                position=store.state['liquidity_positions']['lp']
                self.assertEqual(position['real'],tape.terminal)
                self.assertEqual(position['events'],2)
                self.assertTrue(store.reconcile())
            finally:
                store.close()

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
