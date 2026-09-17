"""Regression coverage for the narrow current-market DLMM tape extension."""
import copy
import unittest

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import chain_verified_tapes,reconstruct,transaction_swaps,_un58_data
from tests.dlmm_support import snapshot,POOL
from tests.test_dlmm_tape import encode_state,transaction


class DlmmTapeExtensions(unittest.TestCase):
    def test_multiple_exact_input_swaps_preserve_transaction_execution_order(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        p1,tx1=transaction(start,1_000_000,101,101,'combo')
        p2,tx2=transaction(p1,2_000_000,101,101,'combo')
        combo=copy.deepcopy(tx1)
        combo['transaction']['message']['instructions']=[tx1['transaction']['message']['instructions'][0],tx2['transaction']['message']['instructions'][0]]
        combo['meta']['innerInstructions']=[dict(index=0,instructions=tx1['meta']['innerInstructions'][0]['instructions']),dict(index=1,instructions=tx2['meta']['innerInstructions'][0]['instructions'])]
        swaps=transaction_swaps(combo,start['pool'])
        self.assertEqual([s['amount'] for s in swaps],[1_000_000,2_000_000])
        self.assertEqual([s['execution_order'] for s in swaps],[[0,0],[1,0]])
        end=encode_state(start_snapshot,p2,102,102)
        sigs=[dict(signature='combo',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]
        tape=reconstruct(start,end,sigs,{'combo':combo},102,[100,2**31-1,2**31-1])
        self.assertEqual([e['cursor'] for e in tape.events],[[101,7,0],[101,7,1]])
        self.assertEqual(tape.terminal_adjustments,())

    def test_routed_transaction_ignores_authenticated_swap_for_other_pool(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        _,tx=transaction(start,1_000_000,101,101,'route')
        other=pump.b58(bytes([99])*32);routed=copy.deepcopy(tx)
        routed['transaction']['message']['accountKeys'].append(other)
        routed['transaction']['message']['instructions'][0]['accounts']=[2]
        inner=routed['meta']['innerInstructions'][0]['instructions'][0]
        raw=bytearray(_un58_data(inner['data']))
        raw[16:48]=pump.un58(other)
        inner['data']=pump.b58(bytes(raw))
        self.assertEqual(transaction_swaps(routed,POOL),[])
        bad=copy.deepcopy(routed)
        bad['transaction']['message']['instructions'][0]['accounts']=[2,0]
        with self.assertRaisesRegex(ValueError,'pool_positions=1'):
            transaction_swaps(bad,POOL)

    def test_swap_preserves_variable_parameter_last_update(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        post,tx=transaction(start,1_000_000,101,110,'clock')
        self.assertEqual(post['last_update'],start['last_update'])
        end=encode_state(start_snapshot,post,102,112)
        sigs=[dict(signature='clock',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]
        tape=reconstruct(start,end,sigs,{'clock':tx},112,[100,2**31-1,2**31-1])
        self.assertEqual(tape.terminal_adjustments,())
        self.assertEqual(tape.terminal['last_update'],start['last_update'])

    def test_unexplained_terminal_last_update_mutation_still_fails_closed(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        post,tx=transaction(start,1_000_000,101,110,'clock-bad')
        post['last_update']=start['last_update']+1
        end=encode_state(start_snapshot,post,102,112)
        sigs=[dict(signature='clock-bad',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]
        with self.assertRaisesRegex(Exception,'last_update'):
            reconstruct(start,end,sigs,{'clock-bad':tx},112,[100,2**31-1,2**31-1])

    def test_verified_chunks_chain_without_raising_transaction_bound(self):
        s0=snapshot();s0['kind']='real';p0=dlmm.validate(s0,100)
        p1,tx1=transaction(p0,1_000_000,101,101,'one');s1=encode_state(s0,p1,102,102)
        sigs1=[dict(signature='one',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),dict(signature='a0',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]
        t1=reconstruct(p0,s1,sigs1,{'one':tx1},102,[100,2**31-1,2**31-1])
        p1_auth=dlmm.validate(s1,102);p2,tx2=transaction(p1_auth,2_000_000,103,103,'two');s2=encode_state(s1,p2,104,104)
        sigs2=[dict(signature='two',slot=103,transactionIndex=9,err=None,confirmationStatus='finalized'),dict(signature='a1',slot=102,transactionIndex=1,err=None,confirmationStatus='finalized')]
        t2=reconstruct(p1_auth,s2,sigs2,{'two':tx2},104,t1.events[-1]['cursor'])
        joined=chain_verified_tapes(p0,[t1,t2])
        self.assertEqual(len(joined.events),2);self.assertEqual(joined.events[-1]['cursor'],[103,9,0])
        self.assertEqual(joined.end_hash,t2.end_hash);self.assertEqual(joined.terminal,t2.terminal)


if __name__=='__main__':unittest.main()
