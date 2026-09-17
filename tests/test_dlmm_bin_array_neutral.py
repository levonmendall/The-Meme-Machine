"""Authenticated structural no-op coverage for Meteora initialize_bin_array."""
import copy
import struct
import unittest

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import INITIALIZE_BIN_ARRAY_IX,SYSTEM_PROGRAM,reconstruct,transaction_swaps
from tests.dlmm_support import snapshot
from tests.test_dlmm_tape import encode_state,transaction


class BinArrayInitialization(unittest.TestCase):
    def _with_init(self,tx,pool,index=-44):
        out=copy.deepcopy(tx)
        keys=out['transaction']['message']['accountKeys']
        bin_array=pump.pda([b'bin_array',pump.un58(pool),struct.pack('<q',index)],dlmm.PROGRAM)
        keys.extend([bin_array,pump.b58(bytes([91])*32),SYSTEM_PROGRAM])
        out['transaction']['message']['instructions'].append(dict(
            programIdIndex=1,accounts=[0,2,3,4],
            data=pump.b58(INITIALIZE_BIN_ARRAY_IX+struct.pack('<q',index))))
        return out,bin_array

    def test_initialize_bin_array_is_structural_and_terminal_verified(self):
        s=snapshot();s['kind']='real';start=dlmm.validate(s,100)
        post,tx=transaction(start,1_000_000,101,101,'swap-plus-bin-init')
        tx,_=self._with_init(tx,start['pool'])
        swaps=transaction_swaps(tx,start['pool'])
        self.assertEqual(len(swaps),1);self.assertEqual(swaps[0]['amount'],1_000_000)
        end=encode_state(s,post,102,102)
        sigs=[dict(signature='swap-plus-bin-init',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),
              dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized')]
        tape=reconstruct(start,end,sigs,{'swap-plus-bin-init':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.events),1);self.assertEqual(tape.terminal,dlmm.validate(end,102))

    def test_initialize_bin_array_requires_exact_pool_position_pda_and_system(self):
        s=snapshot();s['kind']='real';start=dlmm.validate(s,100)
        _,tx=transaction(start,1_000_000,101,101,'bad-bin-init')
        tx,_=self._with_init(tx,start['pool'])
        init=tx['transaction']['message']['instructions'][-1]
        bad=copy.deepcopy(tx);bad['transaction']['message']['instructions'][-1]['accounts']=[2,0,3,4]
        with self.assertRaisesRegex(ValueError,'dlmm_initialize_bin_array_identity'):
            transaction_swaps(bad,start['pool'])
        bad=copy.deepcopy(tx);bad['transaction']['message']['accountKeys'][init['accounts'][1]]=pump.b58(bytes([92])*32)
        with self.assertRaisesRegex(ValueError,'dlmm_initialize_bin_array_pda_or_system'):
            transaction_swaps(bad,start['pool'])
        bad=copy.deepcopy(tx);bad['transaction']['message']['accountKeys'][init['accounts'][3]]=pump.b58(bytes([93])*32)
        with self.assertRaisesRegex(ValueError,'dlmm_initialize_bin_array_pda_or_system'):
            transaction_swaps(bad,start['pool'])

    def test_other_non_swap_pool_mutation_still_fails_closed(self):
        s=snapshot();s['kind']='real';start=dlmm.validate(s,100)
        _,tx=transaction(start,1_000_000,101,101,'unknown-mutation')
        tx,_=self._with_init(tx,start['pool'])
        tx['transaction']['message']['instructions'][-1]['data']=pump.b58(bytes.fromhex('0102030405060708'))
        with self.assertRaisesRegex(Exception,'dlmm_non_swap_mutation_in_interval'):
            transaction_swaps(tx,start['pool'])


if __name__=='__main__':unittest.main()
