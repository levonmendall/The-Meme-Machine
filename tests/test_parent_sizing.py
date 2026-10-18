"""Original replay/formulas and USD decoders; no providers or real financial DB."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal,localcontext,Inexact,Rounded
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational.parent_sizing import (
    ParentSizingProducer,ParentSizingUnavailable,build_sizing_receipt,
)
from meme_machine.operational.parent_transport import ParentHTTP
from meme_machine.operational.child_transport import ChildRPCPort
from meme_machine.runtime.journal import digest
from meme_machine.runtime.usd_valuation import NativeValueReader,sol_usd
from meme_machine.shared_capital import RiskPolicy
from meme_machine.shared_capital.authority import _size_equity,capital_view
from meme_machine.shared_capital.reporting import read_authority
from tests.shared_capital_support import Harness
from tests import test_shared_portfolio_epoch as epoch_fixtures
from tests.test_robinhood_usd_valuation import ReadRPC,NOW
from tests.lanes.pump import test_pumpswap_survivor_evidence as pump_fixtures
from tests import test_parent_native_transport as fixtures
from tests import test_child_transport as client_fixtures
from tests import test_isolated_rpc_ports as rpc_fixtures


def actual_snapshot(harness):
    reader=read_authority(harness.authority.db)
    reader.path=harness.path
    proof=reader.verify_replay();state=reader._read()
    head=reader.db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
    assert proof['conservation'] is True and (proof['events'],proof['journal_hash'],proof['state_sha256'])==tuple(head)
    names=('reservations','commitments','obligations','pending_deliveries','pending_backing','runtime_pending','runtime_inbox')
    counts={k:len(state.get(k,{})) for k in names}
    counts.update(positions_open=sum(p['status']=='OPEN' for p in state['positions'].values()),legacy_native_pending=0)
    financial=dict(state='VERIFIED_FULL_REPLAY',full_replay_verified=True,
        financial_obligations_verified=True,no_financial_exposure=all(v==0 for v in counts.values()),
        obligations=counts,epoch_id=state['epoch_id'],inception_sha256=state['inception_sha256'],
        raw_journal_sequence=head[0],journal_hash=head[1],projection_hash=head[2],
        source_sequence=state['migration_source']['sequence'],
        combined_sequence=state['migration_source']['sequence']+head[0],
        cash_usd=capital_view(state)['free_cash'],initial_capital_usd=state['initial_capital'])
    return financial,state


def decoded_values():
    oracle=pump_fixtures.EvidenceTests().oracle(published=NOW-118,previous=NOW-120)
    response=dict(context=dict(slot=90),value=[oracle])
    pump=sol_usd(oracle,now=NOW,slot=90,evidence_hash=digest(response))
    with patch('meme_machine.runtime.usd_valuation.time.time',return_value=NOW):
        pons=NativeValueReader('pons',rpc=ReadRPC())(NOW)
    return pump,pons


class ParentSizingTests(unittest.TestCase):
    harness=epoch_fixtures.SharedEpochTests.harness

    def arguments(self,h=None):
        financial,state=actual_snapshot(h or self.harness())
        pump,pons=decoded_values()
        return dict(financial=financial,state=state,scope='offline-fenced-caller-fixture',
            source_commit='a'*40,source_tree='b'*40,pump_value=pump,pons_value=pons,now=NOW)

    def test_real_replay_and_original_shared_1000_formula_exact_native_floor(self):
        args=self.arguments()
        before=deepcopy(args)
        with patch('sqlite3.connect',side_effect=AssertionError('producer opened financial DB')):
            produced=build_sizing_receipt(**args)
        value=produced.value()
        self.assertEqual(value['portfolio_sequence'],args['financial']['combined_sequence'])
        self.assertEqual(value['epoch_reference'],args['state']['epoch_id'])
        self.assertEqual(args['state']['initial_capital'],'1000.00')
        for lane in ('pump','pons'):
            unit=args[lane+'_value'].amount(1,NOW)
            expected=int(Fraction(_size_equity(args['state'],lane+'_current'))/Fraction(unit))
            self.assertEqual(value['lanes'][lane]['realized_equity'],expected)
            self.assertEqual(value['lanes'][lane]['reserved'],0)
            self.assertLessEqual(Fraction(expected)*Fraction(unit),1000)
            self.assertGreater(Fraction(expected+1)*Fraction(unit),1000)
        self.assertEqual(value['valid_until'],NOW+2)  # Actual old SOL publication, not a new TTL.
        self.assertEqual(value['lanes']['pons']['valuation_valid_until'],NOW+5)
        proof=produced.proof()
        self.assertEqual(proof['policy_sha256'],digest(args['state']['policy']))
        self.assertEqual(proof['contracts_sha256'],digest(args['state']['contracts']))
        self.assertFalse(proof['fence_verified_here']);self.assertFalse(proof['authentication_performed_here'])
        self.assertEqual(args,before)
        value['lanes']['pump']['available']=0
        self.assertGreater(produced.value()['lanes']['pump']['available'],0)

    def test_effective_family_equivalence_uses_same_authenticated_production_inputs(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        harness=Harness(Path(temp.name),RiskPolicy(sizing_basis='effective_family_equivalence'))
        self.addCleanup(harness.close)
        args=self.arguments(harness)
        value=build_sizing_receipt(**args).value()
        for lane in ('pump','pons'):
            equity=_size_equity(args['state'],lane+'_current')
            self.assertEqual(value['lanes'][lane]['realized_equity'],int(
                Fraction(equity)/Fraction(args[lane+'_value'].amount(1,NOW))))
        self.assertEqual(args['state']['initial_capital'],'500.00')
        self.assertEqual(build_sizing_receipt(**args).proof()['sizing_basis'],'effective_family_equivalence')
        with localcontext() as context:
            context.prec=1;context.traps[Inexact]=context.traps[Rounded]=True
            self.assertEqual(build_sizing_receipt(**args).value(),value)

    def test_exact_conversion_ignores_ambient_decimal_precision(self):
        args=self.arguments();expected=build_sizing_receipt(**args).value()
        with localcontext() as context:
            context.prec=1;context.traps[Inexact]=context.traps[Rounded]=True
            self.assertEqual(build_sizing_receipt(**args).value(),expected)

    def test_unresolved_obligations_binding_or_valuation_never_become_zero_fallback(self):
        original=self.arguments()
        for key in original['financial']['obligations']:
            args=deepcopy(original);args['financial']['obligations'][key]=1
            with self.subTest(bucket=key),self.assertRaises(ParentSizingUnavailable):build_sizing_receipt(**args)
        mutations=[('projection_hash','c'*64),('combined_sequence',-1),('cash_usd','999'),('epoch_id','foreign')]
        for field,bad in mutations:
            args=deepcopy(original);args['financial'][field]=bad
            with self.subTest(field=field),self.assertRaises(ParentSizingUnavailable):build_sizing_receipt(**args)
        for lane in ('pump','pons'):
            args=deepcopy(original);args[lane+'_value']=replace(args[lane+'_value'],evidence_hash='invented')
            with self.subTest(lane=lane),self.assertRaises(ParentSizingUnavailable):build_sizing_receipt(**args)
        args=deepcopy(original);args['now']=NOW+3
        with self.assertRaises(ValueError):build_sizing_receipt(**args)


class ParentSizingPortTests(unittest.IsolatedAsyncioTestCase):
    harness=epoch_fixtures.SharedEpochTests.harness
    connected=client_fixtures.ChildTransportTests.connected
    pump=rpc_fixtures.IsolatedRpcPortTests.pump
    store=rpc_fixtures.IsolatedRpcPortTests.store

    async def asyncSetUp(self):
        await fixtures.ParentNativeTransportTests.asyncSetUp(self)
        self.now=[NOW];self.market=ReadRPC();self.market.chain_verified=True
        self.sol=replace(self.sol,operation='pump_current_qualification',alias=replace(self.sol.alias,
            methods=frozenset(('getGenesisHash','getMultipleAccounts'))))
        self.pons=replace(self.pons,alias=replace(self.pons.alias,
            methods=frozenset(('eth_chainId','eth_getBlockByNumber','eth_getCode','eth_call'))))
        self.oracle=pump_fixtures.EvidenceTests().oracle(published=NOW,previous=NOW-1)
        from meme_machine.solana_provider_config import GENESIS
        self.genesis=GENESIS
        physical=self.physical
        def provider(request,timeout):
            packet=json.loads(request.data);calls=packet if type(packet) is list else [packet]
            def result(call):
                if call['method']=='getGenesisHash':
                    return self.genesis
                if call['method']=='getMultipleAccounts':return dict(context=dict(slot=90),value=[self.oracle])
                return self.market.call(call['method'],call['params'])
            response=[dict(jsonrpc='2.0',id=call['id'],result=result(call)) for call in calls]
            physical.body=json.dumps(response if type(packet) is list else response[0]).encode()
            return physical(request,timeout)
        self.http=ParentHTTP(self.budget,[self.sol,self.pons],opener=provider)
        self.addAsyncCleanup(self.http.aclose)
        self.enterContext(patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:self.now[0]))

    async def producer(self):
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        channel,_=await self.connected()
        pump=self.pump(ChildRPCPort(channel,'pump'))
        # Original pacer, explicit deterministic clock; actual parent admission,
        # Budget and physical purchase ledgers remain in use unchanged.
        tick=[0.0]
        def sleep(seconds):tick[0]+=seconds
        pons=configured_rpc(parent_port=ChildRPCPort(channel,'pons'),immutable_store=self.store(),
            limit=200,per_scope=200,retries=0)
        pons.pacer.clock=lambda:tick[0];pons.pacer.sleep=sleep
        return ParentSizingProducer(pump,pons,clock=lambda:self.now[0])

    async def test_original_native_market_decoders_are_really_parent_metered_without_money_open(self):
        producer=await self.producer()
        financial,state=actual_snapshot(self.harness())
        before=digest(state)
        args=dict(scope='offline-parent-ports',source_commit='a'*40,source_tree='b'*40)
        with patch('meme_machine.lanes.pump.solana_read_rpc.primary_rpc_url',side_effect=AssertionError('URL fallback')), \
                patch('meme_machine.lanes.pons.provider_topology.primary_endpoint',side_effect=AssertionError('URL fallback')):
            value=(await asyncio.to_thread(producer.produce,financial,state,**args)).value()
        self.assertGreater(len(self.physical.calls),1)
        self.assertTrue(any(type(call) is list for call in self.physical.calls))
        self.assertEqual(int(self.budget.snapshot()['http_attempts']),len(self.physical.calls))
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertEqual(value['valid_until'],NOW+5)
        self.assertGreater(value['lanes']['pump']['realized_equity'],0)
        self.assertGreater(value['lanes']['pons']['realized_equity'],0)
        self.assertEqual(value['lanes']['pons']['usd_evidence_hash'],producer._pons.cached.evidence_hash)
        self.assertEqual(digest(state),before)
        purchases=len(self.physical.calls)
        # A compatible original quote is reused, never given a later expiry.
        self.now[0]+=1
        reused=(await asyncio.to_thread(producer.produce,financial,state,**args)).value()
        self.assertEqual(len(self.physical.calls),purchases)
        self.assertEqual(reused['valid_until'],value['valid_until'])

    async def test_bad_flatness_rejects_before_any_provider_purchase_and_absent_ports_do_not_fallback(self):
        producer=await self.producer();financial,state=actual_snapshot(self.harness())
        financial['obligations']['legacy_native_pending']=1
        with self.assertRaises(ParentSizingUnavailable):
            await asyncio.to_thread(producer.produce,financial,state,scope='fixture',source_commit='a'*40,source_tree='b'*40)
        self.assertFalse(self.physical.calls)
        with self.assertRaises(ParentSizingUnavailable):ParentSizingProducer(object(),object())

    async def test_actual_native_route_failure_preserves_failure_and_no_sizing_fallback(self):
        from meme_machine.runtime.usd_valuation import ValuationUnavailable
        producer=await self.producer();financial,state=actual_snapshot(self.harness())
        self.market.no_pairs=True
        with self.assertRaisesRegex(ValuationUnavailable,'native_USDG_executable_route_unavailable'):
            await asyncio.to_thread(producer.produce,financial,state,scope='fixture',
                source_commit='a'*40,source_tree='b'*40)
        self.assertGreater(int(self.budget.snapshot()['http_attempts']),0)
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertIsNone(producer._pons.cached)

    async def test_authenticated_url_does_not_substitute_for_actual_solana_chain_validation(self):
        producer=await self.producer();financial,state=actual_snapshot(self.harness())
        self.genesis='wrong-chain'
        with self.assertRaisesRegex(ParentSizingUnavailable,'^parent_sizing_solana_chain$'):
            await asyncio.to_thread(producer.produce,financial,state,scope='fixture',
                source_commit='a'*40,source_tree='b'*40)
        self.assertEqual(len(self.physical.calls),1)
        self.assertEqual(self.physical.calls[0]['method'],'getGenesisHash')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertIsNone(producer._pump);self.assertIsNone(producer._pons.cached)


if __name__=='__main__':unittest.main()
