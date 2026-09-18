"""Safe segmentation around authenticated add_liquidity_by_strategy2."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import dlmm,pump
from meme_machine.dlmm_tape import (
    ADD_LIQUIDITY_BY_STRATEGY2_IX,transaction_swaps
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
        # Existing keys [pool, program]. Add enough stand-ins for the pinned 14
        # main accounts plus one remaining bin array. Pool is lb_pair position 1.
        for value in range(40,54):
            keys.append(pump.b58(bytes([value])*32))
        accounts=[2,0,3,4,5,6,7,8,9,10,11,12,13,1,14]
        out['transaction']['message']['instructions'].append(dict(
            programIdIndex=1,accounts=accounts,
            data=pump.b58(ADD_LIQUIDITY_BY_STRATEGY2_IX+b'payload')))
        return out

    def test_exact_target_pool_strategy2_surfaces_snapshot_reset_boundary(self):
        s=snapshot();s['kind']='real';state=dlmm.validate(s,100)
        _,tx=transaction(state,1_000_000,101,101,'mutation')
        tx=self._with_mutation(tx,state['pool'])
        with self.assertRaisesRegex(
                Unavailable,'snapshot_reset_required:add_liquidity_by_strategy2:101'):
            transaction_swaps(tx,state['pool'])

    def test_wrong_pool_position_is_not_classified_as_safe_reset(self):
        s=snapshot();s['kind']='real';state=dlmm.validate(s,100)
        _,tx=transaction(state,1_000_000,101,101,'mutation')
        tx=self._with_mutation(tx,state['pool'])
        ix=tx['transaction']['message']['instructions'][-1]
        ix['accounts'][0],ix['accounts'][1]=ix['accounts'][1],ix['accounts'][0]
        with self.assertRaisesRegex(ValueError,'add_liquidity_by_strategy2_identity'):
            transaction_swaps(tx,state['pool'])


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
