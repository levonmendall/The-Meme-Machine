"""Pinned Meteora host-fee exact-input accounting regressions."""
import base64
import copy
import struct
import unittest

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import (
    EVENT_CPI,SWAP,SWAP2,SWAP_IX,SWAP2_IX,transaction_swap,reconstruct
)
from meme_machine.provider import Unavailable
from tests.dlmm_support import snapshot,POOL,VAULT_X,VAULT_Y
from tests.test_dlmm_tape import encode_state

HOST_ACCOUNT=pump.b58(bytes([71])*32)
USER_IN=pump.b58(bytes([72])*32)
USER_OUT=pump.b58(bytes([73])*32)
ORACLE=pump.b58(bytes([74])*32)
USER=pump.b58(bytes([75])*32)
BITMAP=pump.b58(bytes([76])*32)


def expected_host(quote):
    return sum(row['protocol_fee']*dlmm.HOST_FEE_BPS//10000 for row in quote['traversed'])


def host_transaction(p,amount,slot,now,signature='hosted',instruction=SWAP_IX,companion=True,
                     host_delta_adjustment=0,host_mint=None):
    _,plain=dlmm.swap(p,amount,True,now)
    host=expected_host(plain)
    if host<=0: raise AssertionError('host fixture needs nonzero host')
    post,q=dlmm.swap(p,amount,True,now,host_fee=host)
    legacy=(SWAP+pump.un58(POOL)+bytes(32)+
        struct.pack('<iiQQ?QQ',q['start'],q['end'],amount,q['output'],True,
                    q['fee'],q['protocol_fee'])+bytes(16)+host.to_bytes(8,'little'))
    raw=instruction+struct.pack('<QQ',amount,1)
    events=[dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+legacy))]
    if companion:
        lp_fee=q['fee']-q['protocol_fee']-host
        current=(SWAP2+pump.un58(POOL)+bytes(32)+struct.pack('<ii?',q['start'],q['end'],True)+
                 bytes(16)+struct.pack('<QQQQQQQ??',amount,0,q['output'],lp_fee,
                 q['protocol_fee'],0,host,True,True))
        events.append(dict(programIdIndex=1,accounts=[],data=pump.b58(EVENT_CPI+current)))
    keys=[POOL,dlmm.PROGRAM,VAULT_X,VAULT_Y,USER_IN,USER_OUT,p['x'],p['y'],
          ORACLE,HOST_ACCOUNT,USER,BITMAP]
    accounts=[0,11,2,3,4,5,6,7,8,9,10]
    mint=host_mint or p['x'];before=1_000_000
    balances=lambda amount:[dict(accountIndex=9,mint=mint,owner=USER,
        uiTokenAmount=dict(amount=str(amount),decimals=6,uiAmount=None,uiAmountString=str(amount)))]
    tx=dict(slot=slot,blockTime=now,
        transaction=dict(signatures=[signature],message=dict(accountKeys=keys,
            instructions=[dict(programIdIndex=1,accounts=accounts,data=pump.b58(raw))])),
        meta=dict(err=None,innerInstructions=[dict(index=0,instructions=events)],logMessages=[],
                  preTokenBalances=balances(before),
                  postTokenBalances=balances(before+host+host_delta_adjustment)))
    return post,q,host,tx


class HostFeeAccounting(unittest.TestCase):
    def test_host_is_protocol_carveout_not_extra_fee_or_lp_revenue(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        normal,q0=dlmm.swap(p,450_000_000,True,101)
        host=expected_host(q0)
        hosted,qh=dlmm.swap(p,450_000_000,True,101,host_fee=host)
        self.assertGreater(host,0)
        self.assertEqual((q0['output'],q0['fee']),(qh['output'],qh['fee']))
        self.assertEqual(qh['host_fee'],host)
        self.assertEqual(qh['protocol_fee'],q0['protocol_fee']-host)
        self.assertEqual(qh['protocol_fee_pre_host'],q0['protocol_fee'])
        self.assertEqual(hosted['bins'],normal['bins'])
        self.assertEqual(normal['vault_x_amount']-hosted['vault_x_amount'],host)
        self.assertEqual(normal['protocol_fee_x']-hosted['protocol_fee_x'],host)
        self.assertEqual(hosted['vault_y_amount'],normal['vault_y_amount'])
        with self.assertRaisesRegex(Unavailable,'host_fee_cannot_be_reconstructed'):
            dlmm.swap(p,450_000_000,True,101,host_fee=host+1)

    def test_legacy_event_host_account_and_companion_event_are_authenticated(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        for ix in (SWAP_IX,SWAP2_IX):
            with self.subTest(ix=ix.hex()):
                _,q,host,tx=host_transaction(p,450_000_000,101,101,instruction=ix)
                event=transaction_swap(tx,POOL)
                self.assertEqual(event['observed']['host_fee'],host)
                self.assertEqual(event['observed']['protocol_fee'],q['protocol_fee'])
                self.assertEqual(event['observed']['fee'],q['fee'])

    def test_wrong_host_delta_and_wrong_input_mint_fail_closed(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        _,_,_,bad=host_transaction(p,450_000_000,101,101,host_delta_adjustment=1)
        with self.assertRaisesRegex(Unavailable,'balance_delta'):
            transaction_swap(bad,POOL)
        wrong=pump.b58(bytes([88])*32)
        _,_,_,bad=host_transaction(p,450_000_000,101,101,host_mint=wrong)
        with self.assertRaisesRegex(Unavailable,'wrong_token'):
            transaction_swap(bad,POOL)

    def test_shared_host_account_authenticates_transaction_aggregate(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        p1,q1,h1,tx1=host_transaction(
            p,220_000_000,101,101,signature='multi')
        p2,q2,h2,tx2=host_transaction(
            p1,230_000_000,101,101,signature='multi')
        combined=copy.deepcopy(tx1)
        combined['transaction']['message']['instructions']=[
            tx1['transaction']['message']['instructions'][0],
            tx2['transaction']['message']['instructions'][0],
        ]
        combined['meta']['innerInstructions']=[
            dict(index=0,instructions=tx1['meta']['innerInstructions'][0]['instructions']),
            dict(index=1,instructions=tx2['meta']['innerInstructions'][0]['instructions']),
        ]
        # One transaction-level pre/post delta covers both hosted swaps.
        before=int(combined['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'])
        combined['meta']['postTokenBalances'][0]['uiTokenAmount']['amount']=str(
            before+h1+h2)
        events=transaction_swaps(combined,POOL)
        self.assertEqual(len(events),2)
        self.assertEqual(
            [e['observed']['host_fee'] for e in events],[h1,h2])
        end=encode_state(s,p2,102,102)
        sigs=[
            dict(signature='multi',slot=101,transactionIndex=7,err=None,
                 confirmationStatus='finalized'),
            dict(signature='anchor',slot=100,transactionIndex=1,err=None,
                 confirmationStatus='finalized')]
        tape=reconstruct(
            p,end,sigs,{'multi':combined},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.events),2)
        bad=copy.deepcopy(combined)
        bad['meta']['postTokenBalances'][0]['uiTokenAmount']['amount']=str(
            before+h1+h2+1)
        with self.assertRaisesRegex(Unavailable,'host_fee_balance_delta'):
            transaction_swaps(bad,POOL)

    def test_hosted_swap_reconstructs_exact_terminal_state(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        post,q,host,tx=host_transaction(p,450_000_000,101,101)
        end=encode_state(s,post,102,102)
        sigs=[dict(signature='hosted',slot=101,transactionIndex=7,err=None,
                   confirmationStatus='finalized'),
              dict(signature='anchor',slot=100,transactionIndex=1,err=None,
                   confirmationStatus='finalized')]
        tape=reconstruct(p,end,sigs,{'hosted':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.events),1)
        self.assertEqual(tape.events[0]['observed']['host_fee'],host)
        self.assertEqual(tape.events[0]['observed']['protocol_fee'],q['protocol_fee'])

    def test_swap2_partial_limit_and_output_fee_modes_remain_rejected(self):
        s=snapshot();s['kind']='real';p=dlmm.validate(s,100)
        _,_,_,tx=host_transaction(p,450_000_000,101,101)
        bad=copy.deepcopy(tx)
        raw=bytearray()
        # companion is second event CPI; set amount_left nonzero at Swap2Evt offset.
        from meme_machine.dlmm_tape import _un58_data
        encoded=_un58_data(bad['meta']['innerInstructions'][0]['instructions'][1]['data'])
        raw=bytearray(encoded);raw[8+105:8+113]=(1).to_bytes(8,'little')
        bad['meta']['innerInstructions'][0]['instructions'][1]['data']=pump.b58(bytes(raw))
        with self.assertRaisesRegex(Unavailable,'partial_limit'):
            transaction_swap(bad,POOL)


if __name__=='__main__':
    unittest.main()
