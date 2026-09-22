"""Safe segmentation around authenticated add_liquidity_by_strategy2."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import (
    ADD_LIQUIDITY_BY_STRATEGY2_IX,_add_liquidity_by_strategy2_record,
    _materialize_removal_effects,_resolve_effect_event,apply_external_adjustment,
    decode_add_liquidity,transaction_swaps
)
from meme_machine.provider import Unavailable
from meme_machine.store import digest
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_strategy_high_activity_batched as base
from tests.dlmm_support import snapshot
from tests.test_dlmm_tape import transaction


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
            'c49e0a72b619a8a7054513a47d79427d6864831921664e8c6d6e675988d9795fc'
            '1746f6c9719988274991e7673f2cdba5bab2e92d878e598e286a3419d120137713'
            'd06f83a0d073b054513a47d79427d6864831921664e8c6d6e675988d9795fc174'
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


class WarmupSnapshotReset(unittest.TestCase):
    def _state(self,slot):
        return dict(pool='pool',slot=slot,time=slot,last_update=slot,
                    parameters=dict(filter_period=30,decay_period=600))

    def _boundary(self,*_args,**_kwargs):
        return dict(trigger='time',polls=1,waited_seconds=0.5,
                    counts={'pool':1},peak_transactions={'pool':1},
                    overflow=(),soft_limit=10,hard_limit=16)

    def test_warmup_discards_pre_mutation_chunks_and_restarts_full_window(self):
        initial=self._state(100);fresh=self._state(103);end1=self._state(101)
        end2=self._state(104);end3=self._state(105)
        states={'pool':initial}
        adapter=SimpleNamespace(rpc=object())
        adapter.snapshot=lambda *_a,**_k: {'available_time':103,'pool':'pool','slot':103}
        tape1=SimpleNamespace(terminal=end1,events=(),terminal_adjustments=())
        tape2=SimpleNamespace(terminal=end2,events=(),terminal_adjustments=())
        tape3=SimpleNamespace(terminal=end3,events=(),terminal_adjustments=())
        calls=[(tape1,[101,0,0],1),
               Unavailable('dlmm_snapshot_reset_required:add_liquidity_by_strategy2:102'),
               (tape2,[104,0,0],1),(tape3,[105,0,0],1)]
        def capture(*_a,**_k):
            item=calls.pop(0)
            if isinstance(item,Exception): raise item
            return item
        chained=[]
        def chain(origin,chunks):
            chained.append((origin['slot'],[x.terminal['slot'] for x in chunks]))
            return chunks[-1]
        with patch.object(dense,'_await_pressure_boundary',self._boundary), \
             patch.object(base,'_capture_chunk',side_effect=capture), \
             patch.object(dense.dlmm,'validate',return_value=fresh), \
             patch.object(dense,'chain_verified_tapes',side_effect=chain):
            advanced,tapes,errors=dense.pressure_advance(
                adapter,states,1.0,allow_snapshot_reset=True)
        self.assertFalse(errors)
        self.assertEqual(states['pool']['slot'],103)
        self.assertEqual(chained,[(103,[104,105])])
        self.assertEqual(advanced['pool']['slot'],105)
        self.assertEqual(tapes['pool'].terminal['slot'],105)

    def test_outcome_never_segments_post_entry_liquidity_mutation(self):
        initial=self._state(100);states={'pool':initial}
        adapter=SimpleNamespace(rpc=object())
        adapter.snapshot=lambda *_a,**_k: (_ for _ in ()).throw(
            AssertionError('outcome must not reset snapshot'))
        with patch.object(dense,'_await_pressure_boundary',self._boundary), \
             patch.object(base,'_capture_chunk',side_effect=Unavailable(
                 'dlmm_snapshot_reset_required:add_liquidity_by_strategy2:101')):
            advanced,tapes,errors=dense.pressure_advance(
                adapter,states,1.0,allow_snapshot_reset=False)
        self.assertFalse(advanced);self.assertFalse(tapes)
        self.assertEqual(len(errors),1)
        self.assertIn('snapshot_reset_required',errors[0]['reason'])
        self.assertEqual(states['pool']['slot'],100)


if __name__=='__main__':
    unittest.main()
