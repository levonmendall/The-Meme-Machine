"""Regression for the one authenticated pool-neutral Meteora instruction."""
import copy
import struct
import unittest

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import INITIALIZE_POSITION_IX,reconstruct,transaction_swaps
from tests.dlmm_support import snapshot
from tests.test_dlmm_tape import encode_state,transaction


class PoolNeutralPositionInit(unittest.TestCase):
    def _with_initialize_position(self, tx, pool):
        out=copy.deepcopy(tx)
        keys=out['transaction']['message']['accountKeys']
        # Existing fixture keys: [pool, dlmm program]. Add payer, position, owner,
        # system, rent and event-authority stand-ins. Account order follows pinned
        # IDL exactly: payer, position, read-only lb_pair, owner, system, rent,
        # event_authority, program.
        for value in range(70,76):
            keys.append(pump.b58(bytes([value])*32))
        init=dict(
            programIdIndex=1,
            accounts=[2,3,0,4,5,6,7,1],
            data=pump.b58(INITIALIZE_POSITION_IX+struct.pack('<ii',-8,8)),
        )
        out['transaction']['message']['instructions'].append(init)
        return out

    def test_initialize_position_is_pool_neutral_and_terminal_verified(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        post,tx=transaction(start,1_000_000,101,101,'swap-plus-init')
        tx=self._with_initialize_position(tx,start['pool'])
        swaps=transaction_swaps(tx,start['pool'])
        self.assertEqual(len(swaps),1)
        self.assertEqual(swaps[0]['amount'],1_000_000)
        end=encode_state(start_snapshot,post,102,102)
        sigs=[
            dict(signature='swap-plus-init',slot=101,transactionIndex=7,err=None,confirmationStatus='finalized'),
            dict(signature='anchor',slot=100,transactionIndex=1,err=None,confirmationStatus='finalized'),
        ]
        tape=reconstruct(start,end,sigs,{'swap-plus-init':tx},102,[100,2**31-1,2**31-1])
        self.assertEqual(len(tape.events),1)
        self.assertEqual(tape.terminal,dlmm.validate(end,102))

    def test_initialize_position_requires_exact_lb_pair_account_position(self):
        start_snapshot=snapshot();start_snapshot['kind']='real';start=dlmm.validate(start_snapshot,100)
        _,tx=transaction(start,1_000_000,101,101,'bad-init')
        tx=self._with_initialize_position(tx,start['pool'])
        init=tx['transaction']['message']['instructions'][-1]
        init['accounts']=[2,0,3,4,5,6,7,1]
        with self.assertRaisesRegex(ValueError,'dlmm_initialize_position_identity'):
            transaction_swaps(tx,start['pool'])


if __name__=='__main__':unittest.main()
