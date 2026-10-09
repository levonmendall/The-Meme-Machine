"""Native V4 parity and purchase counts; captured lineage, synthetic density."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import ModuleType
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape,encoded_event,checksum
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons.protocols import PoolKey
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
from meme_machine.lanes.pons import pons_selective_v4 as optimized
from meme_machine.runtime.cu import estimate

ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_DENSE_RECEIPTS'
BEFORE='50732ef1c8ae0b8ea1de63d3e337872a1ff00000'


def original_v4():
    path='meme_machine/lanes/pons/pons_selective_v4.py'
    module=ModuleType('frozen_v4');module.__package__='meme_machine.lanes.pons'
    source=subprocess.check_output(['git','show',BEFORE+':'+path],text=True)
    exec(compile(source,path,'exec'),module.__dict__);return module


def fixture(relevant=100,total=100,*,dense=True,failure=None,receipt_sender=True,missing=False,fork=False,seed=0):
    tape=Tape(candidates=1);tape.counts=Counter();tape.per_scope=190
    tape.max_response=2_000_000;tape.timeout=10
    token=tape.tokens[0];record=tape.records[token]
    key=PoolKey('0x'+'00'*20,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
    block=tape.grad+1+seed;header=tape.header(block);txs=[checksum(('dense',seed,i)) for i in range(total)]
    tape.logs=[];receipts={}
    for i,tx in enumerate(txs):
        sender=f'0x{i+1:040x}';tape.senders[tx]=sender
        logs=[]
        if i<relevant:
            logs=[encoded_event('uniswap_v4_manager','Swap',dict(id=key.pool_id(),sender=sender,
                amount0=10000,amount1=-10000,sqrtPriceX96=1<<96,liquidity=1000000,tick=0,fee=record['poolFee']),
                block=block,block_hash=header['hash'],tx=tx,tx_index=i,index=i)]
            tape.logs.extend(logs)
        row=dict(transactionHash=tx,blockHash=header['hash'],blockNumber=hex(block),
            transactionIndex=hex(i),status='0x1',logs=logs)
        if receipt_sender:row['from']=sender
        receipts[tx]=row
    old_header=tape.header
    tape.header=lambda n:dict(old_header(n),transactions=txs if n==block else [])
    tape.receipt_value=lambda tx:deepcopy(receipts[tx])
    original=tape._read
    def read(method,params):
        if method=='eth_getBlockReceipts':
            tape.request_log.append((method,deepcopy(params)))
            if failure=='transport':raise BoundaryError('provider_transport_failure')
            if failure=='unsupported':raise BoundaryError('provider_rpc_-32601')
            rows=[deepcopy(receipts[tx]) for tx in txs]
            if failure=='partial':return rows[:-1]
            if failure=='identity':rows[0]['blockHash']='other'
            if failure=='sender':rows[0]['from']='invalid'
            return rows
        if missing and method=='eth_getTransactionReceipt':raise BoundaryError('provider_missing_result')
        return original(method,params)
    tape._read=read
    if fork:tape.forks[block]=1
    context=SelectiveEvidenceContext(ENDPOINT);context.deadline=110
    context.block_receipts_supported=dense
    context.block_receipts_resources=dict(validated=True,max_response_bytes=2_000_000,
        max_latency_seconds=.2,max_throughput_cu=500,max_transactions=128) if dense else None
    options=dict(pool_id=key.pool_id(),key=key,token=token,start_block=block,end_block=block,evidence_context=context)
    return tape,context,options


def run(module,**kwargs):
    tape,context,options=fixture(**kwargs)
    with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
        result=module.collect_v4_activity(ENDPOINT,**options)
    schedule=json.loads(Path('meme_machine/runtime/alchemy-cu-schedule.json').read_text())
    weights=dict(schedule['methods'],**schedule['throughput_overrides'])
    counts=dict(physical=tape.batches,methods=dict(tape.methods),billed_cu_estimate=estimate(tape.methods)['estimated_cu'],
        throughput_cu=sum(weights[m]*n for m,n in tape.methods.items()),response_bytes=tape.response_bytes,
        request_bytes=tape.request_bytes,selector=dict(context.receipt_acquisition_counts))
    return {k:v for k,v in result.items() if k!='provider_sessions'},counts,tape,context


class DenseV4Tests(unittest.TestCase):
    def compare(self,**kwargs):
        old,a,_,_=run(original_v4(),**kwargs);new,b,tape,context=run(optimized,**kwargs)
        self.assertEqual(old,new);self.assertEqual(len(new['swaps']),kwargs.get('relevant',100))
        return a,b,tape,context

    def test_dense_100_unique_receipts_in_one_authenticated_block_preserve_all_economics(self):
        old,new,tape,ctx=self.compare()
        self.assertEqual((old['methods']['eth_getTransactionReceipt'],new['methods'].get('eth_getTransactionReceipt',0)),(100,0))
        self.assertEqual(new['methods']['eth_getBlockReceipts'],1)
        self.assertEqual(old['physical']-new['physical'],1)
        self.assertEqual(old['billed_cu_estimate']-new['billed_cu_estimate'],1980)
        self.assertEqual(old['throughput_cu']-new['throughput_cu'],1500)
        self.assertEqual((tape.timeout,tape.max_response),(10,2_000_000))

    def test_sparse_unknown_large_and_urgent_demand_keep_individual_receipts(self):
        for options in (dict(relevant=1,total=100),dict(relevant=24,total=24),
                dict(relevant=25,total=100),dict(relevant=100,total=129),dict(dense=False)):
            with self.subTest(options=options):
                old,new,_,_=self.compare(**options)
                self.assertEqual(old['methods'],new['methods']);self.assertEqual(old['physical'],new['physical'])
        tape,ctx,options=fixture();ctx.deadline=100.9
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
            optimized.collect_v4_activity(ENDPOINT,**options)
        self.assertNotIn('eth_getBlockReceipts',tape.methods)

    def test_partial_failure_identity_and_sender_results_fall_back_without_partial_cache(self):
        for failure in ('partial','transport','unsupported','identity','sender'):
            with self.subTest(failure=failure):
                old,new,_,ctx=self.compare(failure=failure)
                self.assertEqual(new['methods']['eth_getTransactionReceipt'],100)
                self.assertEqual(new['methods']['eth_getBlockReceipts'],1)
                self.assertEqual(new['billed_cu_estimate']-old['billed_cu_estimate'],20)
                self.assertEqual(ctx.receipt_acquisition_counts.get('selected_block_receipts',0),0)

    def test_receipts_without_sender_preserve_original_transaction_body_fallback(self):
        old,new,_,_=self.compare(receipt_sender=False)
        self.assertEqual(old['methods']['eth_getTransactionByHash'],100)
        self.assertEqual(new['methods']['eth_getTransactionByHash'],100)

    def test_reorganization_never_purchases_receipts_and_missing_evidence_never_qualifies(self):
        for module in (original_v4(),optimized):
            tape,ctx,options=fixture(fork=True)
            with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
                with self.assertRaisesRegex(BoundaryError,'canonical_header_membership'):
                    module.collect_v4_activity(ENDPOINT,**options)
            self.assertNotIn('eth_getTransactionReceipt',tape.methods);self.assertNotIn('eth_getBlockReceipts',tape.methods)
            tape,ctx,options=fixture(missing=True,failure='partial')
            with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
                with self.assertRaisesRegex(BoundaryError,'missing_result'):module.collect_v4_activity(ENDPOINT,**options)

    def test_missing_resource_proof_and_inadequate_throughput_never_purchase_dense(self):
        for resources in (None,{},dict(validated=True,max_response_bytes=2_000_001,
                max_latency_seconds=.2,max_throughput_cu=499,max_transactions=128)):
            tape,ctx,options=fixture();ctx.block_receipts_resources=resources
            with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape),patch('time.monotonic',return_value=100):
                optimized.collect_v4_activity(ENDPOINT,**options)
            self.assertNotIn('eth_getBlockReceipts',tape.methods)
