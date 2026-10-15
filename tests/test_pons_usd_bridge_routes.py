"""Offline quantity/canonical proof for the disabled Pons USD bridge reader."""
from decimal import Decimal
import os
import re
import unittest
from unittest.mock import patch

from meme_machine.lanes.ramses.abi import calldata
from meme_machine.lanes.ramses.identity import load,verify_compilation,compiler_input
from meme_machine.runtime.usd_valuation import (
    NativeValueReader,PONS_USD_BRIDGES,USDG_ASSET,ValuationUnavailable,
)
from tests.test_robinhood_usd_valuation import ReadRPC,WNATIVE,NOW,abi


class BridgeRPC(ReadRPC):
    def __init__(self):
        super().__init__();self.no_pairs=True
        self.bridge_calls=[];self.bridge_code_bad=False;self.bridge_hooks=0
        self.ignored=False;self.unspent=False;self.fee_bad=False
        self.second_quantities=[];self.batches=[];self.reorganized=False
        self.bridge_rows=[]
        impl=load('ramses_pool_implementation')['address'][2:]
        for role,first,second in PONS_USD_BRIDGES:
            asset=load(role)['address'].lower()
            for pool,source,target,hop in ((first,WNATIVE,asset,1),(second,asset,USDG_ASSET,2)):
                code=('0x363d3d373d3d3d3d61002c806035363936013d73'+impl
                    +'5af43d3d93803e603357fd5bf3'+source[2:]+target[2:]+'000a002c')
                self.bridge_rows.append(dict(pool=pool,asset=asset,source=source,target=target,
                    code=code,role=role,hop=hop))

    def batch(self,calls,*,scope):
        self.batches.append(calls)
        return super().batch(calls,scope=scope)

    def call(self,method,params,*,scope=None):
        if method=='eth_getCode':
            for role,_,_ in PONS_USD_BRIDGES:
                pin=load(role)
                if params[0].lower()==pin['address'].lower():
                    self.bridge_calls.append((method,params))
                    return '0x6000' if self.bridge_code_bad else pin['runtimeBytecode']['onchainBytecode']
            for row in self.bridge_rows:
                if params[0].lower()==row['pool']:return row['code']
        if method=='eth_call':
            address=params[0]['to'].lower();data=params[0]['data']
            for row in self.bridge_rows:
                if address==self.factory['address'].lower() and data==calldata(
                        'getAllLBPairs(address,address)',row['asset'],row['source'] if row['hop']==1 else row['target']):
                    self.bridge_calls.append((method,params))
                    return abi(32,1,10,row['pool'],1,int(self.ignored))
                if address!=row['pool']:continue
                if data==calldata('getLBHooksParameters()'):return abi(self.bridge_hooks)
                quantity=10**15 if row['hop']==1 else 10**18
                if data==calldata('getSwapOut(uint128,bool)',quantity,1):
                    if row['hop']==1:return abi(int(self.unspent),quantity*1000,10**12)
                    self.second_quantities.append(quantity)
                    output=2000000 if row['role']=='pons_usd_r33' else 500000
                    return abi(int(self.unspent),output,quantity+1 if self.fee_bad else 10**12)
        value=super().call(method,params,scope=scope)
        if method=='eth_getBlockByNumber' and params[0]!='latest' and self.reorganized:
            value=dict(value,hash='0x'+'34'*32)
        return value


class PonsUSDBridgeTests(unittest.TestCase):
    def setUp(self):
        self.rpc=BridgeRPC()
        for item in (patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:self.rpc.now),
                patch.dict(os.environ,MM_PONS_USD_BRIDGE_ROUTES='verified_two_hop_v1')):
            item.start();self.addCleanup(item.stop)

    def test_disabled_extension_makes_no_bridge_requests(self):
        with patch.dict(os.environ,MM_PONS_USD_BRIDGE_ROUTES=''):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual(self.rpc.bridge_calls,[])

    def test_direct_route_still_precedes_extension(self):
        self.rpc.no_pairs=False
        value=NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual(value.usd_per_unit,Decimal('2500.349025'))
        self.assertEqual(self.rpc.bridge_calls,[])

    def test_both_quantity_specific_hops_and_depeg_compose_exactly(self):
        reader=NativeValueReader('pons',rpc=self.rpc);value=reader(NOW)
        self.assertEqual(value.usd_per_unit,Decimal('2000.27922'))
        self.assertEqual((value.asset,value.decimals,value.valid_until),('ETH',18,NOW+5))
        self.assertEqual(self.rpc.second_quantities,[10**18,10**18])
        self.assertTrue(all(params[-1]=='0x4bdc170' for method,params in self.rpc.bridge_calls))
        self.assertEqual(len(value.evidence_hash),64)
        count=len(self.rpc.bridge_calls)
        self.rpc.now=NOW+5;self.assertIs(reader(NOW+5),value)
        self.assertEqual(len(self.rpc.bridge_calls),count)
        self.rpc.now=NOW+6;new=reader(NOW+6)
        self.assertEqual(new.valid_until,NOW+11)
        self.assertGreater(len(self.rpc.bridge_calls),count)

    def test_hooks_unfilled_membership_and_fee_fail_closed(self):
        for field in ('bridge_hooks','unspent','ignored','fee_bad','bridge_code_bad'):
            with self.subTest(field=field):
                rpc=BridgeRPC();setattr(rpc,field,True)
                with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=rpc)(NOW)

    def test_reorganization_clears_cached_route_and_oracle(self):
        reader=NativeValueReader('pons',rpc=self.rpc);reader(NOW)
        self.rpc.now=NOW+6;self.rpc.reorganized=True
        with self.assertRaises(ValuationUnavailable):reader(NOW+6)
        self.assertIsNone(reader.cached);self.assertIsNone(reader.oracle)
        self.assertEqual(reader.route_state,{})

    def test_bridge_delay_does_not_extend_original_five_second_validity(self):
        original=self.rpc.call
        def delayed(method,params,**kwargs):
            value=original(method,params,**kwargs)
            if self.rpc.second_quantities:self.rpc.now=NOW+6
            return value
        with patch.object(self.rpc,'call',side_effect=delayed):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_compiler_matched_bridges_have_no_local_transfer_overrides(self):
        permitted={
            'transfer':'dependencies/@openzeppelin-contracts-5.1.0/token/ERC20/ERC20.sol',
            'transferFrom':'dependencies/@openzeppelin-contracts-5.1.0/token/ERC20/ERC20.sol',
            '_transfer':'dependencies/@openzeppelin-contracts-5.1.0/token/ERC20/ERC20.sol',
            '_update':'dependencies/@openzeppelin-contracts-5.1.0/token/ERC20/ERC20.sol',
            '_msgSender':'dependencies/@openzeppelin-contracts-5.1.0/utils/Context.sol',
        }
        for role,_,_ in PONS_USD_BRIDGES:
            pin=verify_compilation(load(role));sources=compiler_input(pin)['sources']
            for function,expected in permitted.items():
                owners=[]
                for name,row in sources.items():
                    source=re.sub(r'/\*.*?\*/|//[^\n]*','',row['content'],flags=re.S)
                    if re.search(r'function\s+'+function+r'\s*\([^;{}]*\)[^;{}]*\{',source):owners.append(name)
                self.assertEqual(owners,[expected])


if __name__=='__main__':unittest.main()
