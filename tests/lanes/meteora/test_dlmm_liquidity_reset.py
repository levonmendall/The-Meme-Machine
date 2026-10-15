"""Safe segmentation around authenticated add_liquidity_by_strategy2."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine.lanes.meteora import dlmm,pump
from meme_machine.lanes.meteora.dlmm_tape import (
    ADD_LIQUIDITY_BY_STRATEGY2_IX,_add_liquidity_by_strategy2_record,
    _materialize_removal_effects,_resolve_effect_event,apply_external_adjustment,
    decode_add_liquidity,transaction_swaps
)
from meme_machine.lanes.meteora.provider import Unavailable
from meme_machine.lanes.meteora.store import digest
from tests.meteora_tape_fixtures import snapshot
from tests.meteora_tape_fixtures import transaction


class LiquidityMutationIdentity(unittest.TestCase):
    def _with_mutation(self,tx,pool):
        out=copy.deepcopy(tx);keys=out['transaction']['message']['accountKeys']
        # Derive fresh stand-in indices from the actual fixture key count so only
        # pinned account position 1 references the target lb_pair.
        base=len(keys)
        for value in range(180,193):
            keys.append(pump.b58(bytes([value])*32))
        accounts=[base,0]+[base+i for i in range(1,12)]+[1,base+12]
        out['transaction']['message']['instructions'].append(dict(
            programIdIndex=1,accounts=accounts,
            data=pump.b58(ADD_LIQUIDITY_BY_STRATEGY2_IX+b'payload')))
        return out

    def test_real_strategy2_shape_authenticates_instruction_and_event(self):
        # Exact instruction and AddLiquidity event bytes retained from the natural
        # slot-449436239 failure.  The repair authenticates the instruction/event
        # identity and amounts instead of converting it into a snapshot-reset error.
        pool='AsSyvUnbfaZJPRrNh3kUuvZTeHKoMVWEoHz86f4Q5D9x'
        position='Ma8ZKfjwNR68RdfVT3GqQHXCypdcb2aD31RbFzH9nkH'
        sender='8r9iJh7dEbGrVtMKKsETUQXW5KRxsfb3yX8KH13rq9FY'
        token='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
        keys=[
            position,pool,pump.b58(bytes([3])*32),pump.b58(bytes([4])*32),
            pump.b58(bytes([5])*32),pump.b58(bytes([6])*32),
            pump.b58(bytes([7])*32),pump.b58(bytes([8])*32),
            pump.b58(bytes([9])*32),sender,token,token,
            pump.b58(bytes([12])*32),dlmm.PROGRAM,
        ]
        raw=bytes.fromhex(
            '03dd95da6f8d76d5d7d709000000000070b92d0000000000'
            'd40100000a00000097010000da01000006'
            + '00'*64 +
            '00000000000000000200000000000100')
        effect=_add_liquidity_by_strategy2_record(
            raw,dict(accounts=list(range(14))),keys,pool,[3,1])
        event=decode_add_liquidity(bytes.fromhex(
            '1f5e7d5ae3343dba92a5999e33292a1da65d118d47b774214d1a809653dda67d'
            'c49e0a72b619a8a774991e7673f2cdba5bab2e92d878e598e286a3419d12013771'
            '3d06f83a0d073b054513a47d79427d6864831921664e8c6d6e675988d9795fc174'
            '6f6c97199882d3d709000000000068b92d0000000000d4010000'),pool)
        effect['events']=[event];effect['event_order']=[3,5]
        resolved=_resolve_effect_event(effect,pool)
        self.assertEqual(resolved['kind'],'add_liquidity_by_strategy2')
        self.assertEqual((resolved['amount_x'],resolved['amount_y']),(645075,2996584))
        self.assertEqual(resolved['active'],468)
        self.assertEqual((resolved['min_bin'],resolved['max_bin']),(407,474))

    def test_wrong_pool_position_is_not_classified_as_safe_reset(self):
        s=snapshot();s['kind']='real';state=dlmm.validate(s,100)
        _,tx=transaction(state,1_000_000,101,101,'mutation')
        tx=self._with_mutation(tx,state['pool'])
        ix=tx['transaction']['message']['instructions'][-1]
        ix['accounts'][0],ix['accounts'][1]=ix['accounts'][1],ix['accounts'][0]
        with self.assertRaisesRegex(ValueError,'add_liquidity_by_strategy2_identity'):
            transaction_swaps(tx,state['pool'])



class Strategy2TerminalMaterialization(unittest.TestCase):
    def test_finalized_bin_deltas_become_replayable_external_adjustment(self):
        raw=snapshot();raw['kind']='real';start=dlmm.validate(raw,100)
        active=int(start['active'])
        below=max(int(k) for k in start['bins'] if int(k)<active)
        above=min(int(k) for k in start['bins'] if int(k)>active)
        end=copy.deepcopy(start)
        deposits=[(below,0,1_000_000),(above,1_000_000,0)]
        total_x=total_y=0
        for bid,x,y in deposits:
            b=end['bins'][str(bid)]
            share=dlmm.deposit_share(b,x,y)
            self.assertGreater(share,0)
            b['x']+=x;b['y']+=y;b['supply']+=share
            end['vault_x_amount']+=x;end['vault_y_amount']+=y
            total_x+=x;total_y+=y
        effect=dict(
            kind='add_liquidity_by_strategy2',active=active,
            min_bin=below,max_bin=above,amount_x=total_x,amount_y=total_y)
        _materialize_removal_effects(start,end,[effect])
        self.assertEqual(
            [(r['bin_id'],r['x'],r['y']) for r in effect['bin_deposits']],
            deposits)
        self.assertEqual(
            apply_external_adjustment(start,effect,counterfactual=False),end)
        # The same fixed external token deposit is then applied to the hypothetical
        # pool independently; observed real-world share deltas are not imposed on it.
        virtual=copy.deepcopy(start)
        self.assertEqual(
            apply_external_adjustment(virtual,effect,counterfactual=True)
                ['vault_x_amount'],
            virtual['vault_x_amount']+total_x)


