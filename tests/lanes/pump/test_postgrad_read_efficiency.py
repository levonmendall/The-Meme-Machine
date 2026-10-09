"""Deterministic Pump provider-element and executable-quote parity tests.

No network, funded positions, provider secrets, subscriptions or timeouts.
"""
import base64
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.postgrad import (
    GraduationHandoff, PostGraduationAdapter, PUMPSWAP_PROGRAM,
    buy_quote, sell_quote,
)
from meme_machine.lanes.pump.provider import PumpAdapter, Unavailable
from tests.lanes.pump.test_postgrad import (
    MINT, CREATOR, WSOL, account, complete_pump_snapshot, fee_config,
    token_account, pumpswap_pool_account,
)


class MeteredRPC:
    def __init__(self):
        self.time = 101
        self.requests = []
        self.curve = complete_pump_snapshot()['accounts'][0]
        self.mint = complete_pump_snapshot()['accounts'][1]
        self.curve_key = pump.pda([b'bonding-curve',pump.un58(MINT)])
        self.pool, self.pool_acc, self.base_key, self.quote_key = pumpswap_pool_account()
        self.base_acc = token_account(MINT,self.pool,500_000_000_000_000)
        self.quote_acc = token_account(WSOL,self.pool,50_000_000_000)
        self.fee_acc = fee_config()
        self.fee_key = pump.pda(
            [b'fee_config',pump.un58(PUMPSWAP_PROGRAM)],pump.FEE_PROGRAM)
        self.url = 'https://offline.invalid'
        self.transport = object()
        self._http = object()

    def clock(self):return self.time
    def count(self,method):return sum(kind==method for kind,_ in self.requests)

    def call(self,method,params=None,priority=False):
        self.requests.append((method,params))
        if method=='getGenesisHash':return pump.MAINNET
        if method=='getBlockTime':return 100
        if method!='getMultipleAccounts':raise AssertionError('unexpected '+method)
        keys=params[0]
        if keys==[self.pool]:
            return dict(context=dict(slot=1000),value=[self.pool_acc])
        if keys==[self.curve_key,MINT]:
            return dict(context=dict(slot=1000),value=[self.curve,self.mint])
        core=[self.pool,MINT,self.base_key,self.quote_key,self.fee_key]
        if keys==core:
            return dict(context=dict(slot=1001),value=[
                self.pool_acc,self.mint,self.base_acc,self.quote_acc,self.fee_acc])
        if keys==core+[self.curve_key]:
            return dict(context=dict(slot=1001),value=[
                self.pool_acc,self.mint,self.base_acc,self.quote_acc,
                self.fee_acc,self.curve])
        raise AssertionError('unexpected account scope '+repr(keys))


class PumpRequestParity(unittest.TestCase):
    def setUp(self):
        self.rpc=MeteredRPC()
        self.adapter=PostGraduationAdapter(self.rpc,scan_rpc=object())

    def test_first_held_quote_removes_separate_graduation_read(self):
        before=self.rpc.count('getMultipleAccounts')
        quote=self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(self.rpc.count('getMultipleAccounts')-before,2)
        self.assertEqual(self.rpc.count('getBlockTime'),1)
        self.assertEqual(quote['creator'],CREATOR)
        self.assertEqual(quote['state']['raw_quote_reserve'],50_000_000_000)
        self.assertEqual(quote['source']['account_slot'],1001)
        self.assertEqual(quote['source']['graduation_slot'],1001)

    def test_warm_quote_reads_fresh_all_mutable_accounts_one_call(self):
        self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.rpc.quote_acc=token_account(WSOL,self.rpc.pool,80_000_000_000)
        self.rpc.fee_acc=fee_config(lp=30,protocol=10,creator=20)
        before=self.rpc.count('getMultipleAccounts')
        state=self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(self.rpc.count('getMultipleAccounts')-before,1)
        self.assertEqual(state['state']['quote_reserve'],80_000_000_000)
        self.assertEqual(state['state']['fee_parts_bps'],[30,10,20])
        self.assertEqual(self.adapter.held_pumpswap_probe_reuses,1)
        # Prospective entry/requalification never uses a held hint.
        handoff=GraduationHandoff(MINT,CREATOR,'source',900,90,False)
        before=self.rpc.count('getMultipleAccounts')
        ordinary=self.adapter.pumpswap_snapshot(handoff,101)
        self.assertEqual(self.rpc.count('getMultipleAccounts')-before,2)
        self.assertEqual(state['state'],ordinary['state'])

    def test_live_creator_change_and_completed_curve_required_each_turn(self):
        self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        other=pump.b58(bytes([76])*32)
        self.rpc.curve=complete_pump_snapshot(creator=other)['accounts'][0]
        next_quote=self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(next_quote['creator'],other)
        # An admin-changed source is not silenced by a sixty-second TTL.
        raw=bytearray(base64.b64decode(self.rpc.curve['data'][0]))
        raw[48]=0
        self.rpc.curve=account(bytes(raw),pump.PROGRAM)
        with self.assertRaisesRegex(ValueError,'bonding_curve_not_complete'):
            self.adapter.pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)

    def test_invalid_or_missing_mutable_account_stops_quote(self):
        self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.rpc.fee_acc=None
        with self.assertRaisesRegex(Unavailable,'pumpswap_accounts_missing'):
            self.adapter.pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.rpc.fee_acc=fee_config()
        self.rpc.curve=None
        with self.assertRaisesRegex(Unavailable,'pumpswap_accounts_missing'):
            self.adapter.pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)

    def test_warm_vault_drift_blocks_and_cold_retry_reprobes(self):
        self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        original=self.rpc.pool_acc
        raw=bytearray(base64.b64decode(original['data'][0]))
        raw[139:171]=bytes([79])*32
        self.rpc.pool_acc=account(bytes(raw),PUMPSWAP_PROGRAM)
        with self.assertRaisesRegex(ValueError,'pumpswap_verified_vault_drift'):
            self.adapter.pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertNotIn(MINT,self.adapter._held_pumpswap_vaults)
        self.rpc.pool_acc=original
        prior=self.rpc.count('getMultipleAccounts')
        self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(self.rpc.count('getMultipleAccounts')-prior,2)
        restarted=PostGraduationAdapter(self.rpc,scan_rpc=object())
        prior=self.rpc.count('getMultipleAccounts')
        restarted.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(self.rpc.count('getMultipleAccounts')-prior,2)

    def test_cold_probe_vs_second_batch_vault_drift_fails(self):
        oldcall=self.rpc.call
        raw=bytearray(base64.b64decode(self.rpc.pool_acc['data'][0]))
        raw[139:171]=bytes([79])*32
        replacement=account(bytes(raw),PUMPSWAP_PROGRAM)
        def swap_between_reads(method,params=None,priority=False):
            if method=='getMultipleAccounts' and len(params[0])==6:
                self.rpc.pool_acc=replacement
            return oldcall(method,params,priority)
        self.rpc.call=swap_between_reads
        with self.assertRaisesRegex(ValueError,'pumpswap_verified_vault_drift'):
            self.adapter.pumpswap_snapshot(
                MINT,101,reuse_verified_pool=True,held_curve_inline=True)

    def test_quote_economics_same_as_original_without_caching(self):
        handoff=GraduationHandoff(MINT,CREATOR,'source',900,90,False)
        original=self.adapter.pumpswap_snapshot(handoff,101)
        held=self.adapter.pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(original['state'],held['state'])
        for qty in (10**6,10**9,10**11):
            self.assertEqual(sell_quote(original,qty),sell_quote(held,qty))
        self.assertEqual(buy_quote(original,100_000_000),
                         buy_quote(held,100_000_000))

    def test_exact_finalized_local_time_or_original_rpc(self):
        self.rpc.time=120
        observed=[]
        self.adapter.finalized_market_time=lambda slot:observed.append(slot) or 100
        before=self.rpc.count('getBlockTime')
        state=self.adapter.pumpswap_snapshot(
            MINT,120,reuse_verified_pool=True,held_curve_inline=True)
        self.assertEqual(self.rpc.count('getBlockTime'),before)
        self.assertEqual(state['market_time'],100)
        self.assertEqual(observed,[1001])
        for invalid in (None,True,-1,121,'100'):
            self.adapter.finalized_market_time=lambda slot,v=invalid:v
            before=self.rpc.count('getBlockTime')
            self.adapter.pumpswap_snapshot(
                MINT,120,reuse_verified_pool=True,held_curve_inline=True)
            self.assertEqual(self.rpc.count('getBlockTime'),before+1)

    def test_pump_bonding_curve_timestamp_requires_exact_proof(self):
        rpc=MeteredRPC()
        adapter=PumpAdapter(rpc)
        original=rpc.call
        def active_curve(method,params=None,priority=False):
            if method=='getMultipleAccounts' and len(params[0])==3:
                rpc.requests.append((method,params))
                return dict(context=dict(slot=1001),value=[object(),object(),object()])
            return original(method,params,priority)
        rpc.call=active_curve
        with (
            patch.object(pump,'curve',return_value=object()),
            patch.object(pump,'mint_info',return_value=(10**12,6)),
            patch.object(pump,'validate_mint_supply',return_value={'mayhem':False}),
            patch.object(pump,'fees',return_value=[20,5,50]),
        ):
            adapter.finalized_market_time=lambda slot:100 if slot==1001 else None
            before=rpc.count('getBlockTime')
            a=adapter.snapshot(MINT,101,priority=True)
            self.assertEqual(rpc.count('getBlockTime'),before)
            self.assertEqual(a['market_time'],100)
            adapter.finalized_market_time=lambda slot:None
            b=adapter.snapshot(MINT,101,priority=True)
            self.assertEqual(rpc.count('getBlockTime'),before+1)
            self.assertEqual(a['market_time'],b['market_time'])


if __name__=='__main__':
    unittest.main()
