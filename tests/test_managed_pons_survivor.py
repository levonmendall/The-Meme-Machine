"""Native read-side reuse, V4 replay and denial of every financial entrypoint."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.managed_pons_survivor import SurvivorMarketReadSide
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.lanes.pons.pons_natural_observation import MarketScout
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,market_sizing_basis
from meme_machine.runtime.journal import digest
from tests.lanes.pons.test_pons_finalization import address,block_header,graduation,ENDPOINT


class ManagedSurvivorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=self.enterContext(tempfile.TemporaryDirectory());self.root=Path(self.tmp)
        self.enterContext(patch.dict(os.environ,{},clear=True))
        self.plane=Plane(self.root/'plane.sqlite');self.addCleanup(self.plane.close)
        self.scout=MarketScout(self.plane)
        # Constructor, book, sleeve, commits and native lifecycle are traps.
        self.enterContext(patch.object(Runtime,'__init__',side_effect=AssertionError('financial runtime constructed')))
        for name in ('open_sleeve','PaperBook','commit','monitor','scale'):
            self.enterContext(patch('meme_machine.lanes.pons.pons_survivor_runtime.'+name,
                                    side_effect=AssertionError('financial API called')))
        self.reader=SurvivorMarketReadSide(self.root/'history.sqlite',ENDPOINT,self.plane,self.scout)
        self.addCleanup(self.reader.close)

    def test_read_side_constructs_no_financial_authority_and_uses_exact_reference_arithmetic(self):
        self.assertFalse(hasattr(self.reader,'sleeve'));self.assertFalse(hasattr(self.reader,'book'))
        for name in ('_enter','_position','exit_quote','step_financial','generation_fence'):
            self.assertFalse(hasattr(self.reader,name))
        basis=market_sizing_basis(self.reader,500,minimum_bps=5)
        self.assertEqual((basis['target'],basis['minimum']),(10**18*500//10000,10**18*5//10000))
        self.assertFalse(basis['allocation_authority'])
        for name in ('_increment','_increment_candidates','reconstruct','qualify','fresh_state'):
            self.assertIs(getattr(SurvivorMarketReadSide,name),getattr(Runtime,name))

    def test_production_sizing_fallback_is_the_unchanged_sleeve_call(self):
        class Native:
            class Sleeve:
                def sizing_basis(inner,target_bps,*,minimum_bps=0):
                    self.assertEqual((target_bps,minimum_bps),(500,5));return {'native':'exact'}
            sleeve=Sleeve()
        self.assertEqual(market_sizing_basis(Native(),500,minimum_bps=5),{'native':'exact'})

    def test_actual_native_survivor_qualification_runs_without_a_financial_runtime(self):
        from tests.lanes.pons.test_pons_postgrad_survivor import facts,NOW
        from meme_machine.lanes.pons.pons_postgrad_survivor import evaluate_entry
        value=facts()
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.time.time',return_value=NOW):
            result=self.reader.qualify(value)
        expected=evaluate_entry(value)
        self.assertTrue(result['candidate'],result['all_rejections'])
        self.assertEqual(result['all_rejections'],expected['all_rejections'])
        self.assertEqual(result['features']['proposed_quote_amount'],expected['features']['proposed_quote_amount'])
        self.assertFalse(hasattr(self.reader,'sleeve'));self.assertFalse(hasattr(self.reader,'book'))

    def test_database_refuses_positions_and_financial_lifecycle_states(self):
        row=self.reader.history.graduate(address(1),graduation(1))
        for change in (dict(position='forbidden'),dict(pending_action='allocate'),dict(state='reserved')):
            with self.subTest(change=change),self.assertRaises(Exception):
                self.reader.history.save(dict(row,**change))
        self.assertIsNone(self.reader.history.get(address(1))['position'])

    def test_three_second_fair_pool_scheduling_keeps_four_hour_age_gate(self):
        row=self.reader.history.graduate(address(1),graduation(1,at=100))
        self.reader.history.append_block(row['id'],block=100,header=block_header(100),events=[],points=[(100,str(10**18))])
        self.reader.now=lambda:200
        self.assertEqual(self.reader.observation_interval_seconds,3)
        with patch.object(self.reader,'_provider'),patch.object(self.reader,'_discover_scout'), \
                patch.object(self.scout,'read_pools') as pools,patch.object(self.reader,'fresh_state') as fresh:
            report=self.reader.step(110)
        pools.assert_called_once_with(self.reader.rpc,110)
        fresh.assert_not_called()
        self.assertEqual(report['age_eligible_candidates'],0)
        self.assertFalse(report['qualification_throughput_verified'])

    def test_native_v4_receipt_decode_is_persisted_and_independently_replayed(self):
        from engineering.pons_history.fixtures import encoded_event
        from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
        from meme_machine.lanes.pons.protocols import PoolKey
        row=self.reader.history.graduate(address(1),graduation(1))
        h=block_header(101);tx='0x'+'a1'*32
        event=encoded_event('uniswap_v4_manager','Swap',dict(
            id=row['graduation']['transition']['market'],sender=address(990),
            amount0=10000,amount1=-10000,sqrtPriceX96=1<<96,liquidity=1000000,tick=0,fee=0),
            block=101,block_hash=h['hash'],tx=tx,tx_index=0,index=0)
        receipt=dict(transactionHash=tx,blockHash=h['hash'],blockNumber=hex(101),
            transactionIndex='0x0',status='0x1',logs=[event],**{'from':address(990)})
        calls=[('eth_getLogs',[{}]),('eth_getBlockByNumber',[hex(101),False]),
               ('eth_getTransactionReceipt',[tx])]
        self.reader._capture(calls,[[event],h,receipt],'pons_selective_v4')
        shared=dict(raw=[event],headers={h['hash']:h},receipts={(tx,h['hash']):receipt},
            txs={(tx,h['hash']):dict(hash=tx,blockHash=h['hash'],**{'from':address(990)})},sessions=[])
        tape=collect_v4_activity(ENDPOINT,pool_id=row['graduation']['transition']['market'],
            key=PoolKey(**row['graduation']['key']),token=row['id'],start_block=101,end_block=101,_shared=shared)
        self.reader._append_tape(row,101,h,tape)
        before=[tuple(r) for r in self.reader.history.db.execute('SELECT * FROM events')]
        replay=self.reader.replay()
        self.assertTrue(replay['verified']);self.assertEqual(replay['events'],1)
        self.assertEqual([tuple(r) for r in self.reader.history.db.execute('SELECT * FROM events')],before)
        self.reader.history.db.execute("UPDATE managed_provider_corpus SET hash='corrupt'")
        with self.assertRaisesRegex(ValueError,'survivor_corpus_digest'):self.reader.replay()

    def test_actual_native_pool_scout_advances_its_fair_bounded_cursor(self):
        self.plane.clock=lambda:100
        row=self.reader.history.graduate(address(1),graduation(1))
        self.scout.register_pool(row);self.reader.now=lambda:200
        from meme_machine.lanes.pons.provider_admission import priority
        calls=[];priorities=[];outer=[]
        class Offline:
            def batch(inner,rows,*,scope):
                priorities.append(priority(scope));calls.extend(rows);return [[] for _ in rows]
        self.reader.rpc=Offline()
        with patch.object(self.reader,'_provider',side_effect=lambda:outer.append(priority('pons_survivor'))), \
                patch.object(self.reader,'_discover_scout'):
            self.reader.step(110)
        self.assertEqual(self.scout.snapshot()['minimum_active_pool_cursor'],110)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][1][0]['topics'][1],[row['graduation']['transition']['market']])
        self.assertEqual(outer,[30]);self.assertEqual(priorities,[20])
