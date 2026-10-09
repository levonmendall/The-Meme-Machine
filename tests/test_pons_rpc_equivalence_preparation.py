"""No endpoint calls; exact state comparisons and bounded future-test envelope."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError,CHAIN_ID
from meme_machine.lanes.pons.evidence import Store
from engineering.proven_efficiency.cross_positions import scenario,native_quote,quote_request
from operational.pons_rpc_equivalence import ENVELOPE,OfflineEnvelope,compare_observations,validate_inactive_configuration
from tests.lanes.pons.test_pons_finalization import ExactQuoteRPC


def observation(method='eth_call',params=None,result='0x1'):
    return dict(chain_id=CHAIN_ID,canonical_header=dict(number='0x64',hash='h100',parentHash='h99',timestamp='0x64'),
        canonical_after='h100',observed_at=100,available_at=101,method=method,
        params=params or [{'to':'quoter','data':'0x12'},{'blockHash':'h100','requireCanonical':True}],result=result)


class ProviderEquivalencePreparationTests(unittest.TestCase):
    def test_default_disabled_and_unverified_monetary_ceiling_stop_before_dispatch(self):
        with self.assertRaisesRegex(BoundaryError,'disabled'):validate_inactive_configuration(ENVELOPE)
        with self.assertRaisesRegex(BoundaryError,'monetary'):validate_inactive_configuration(dict(ENVELOPE,enabled=True))

    def test_standard_methods_archive_and_exact_block_references_are_preserved(self):
        methods=('eth_chainId','eth_getBlockByNumber','eth_getBlockByHash','eth_call','eth_gasPrice',
            'eth_getLogs','eth_getTransactionReceipt','eth_getBlockReceipts','eth_getTransactionByHash','eth_getCode')
        for method in methods:
            a=observation(method);b=deepcopy(a)
            self.assertTrue(compare_observations(a,b,decision_deadline=103)['equivalent'])
        a=observation(params=[{'to':'quoter','data':'0x12'},'0x1'])
        b=deepcopy(a);b['params'][1]='0x64'
        with self.assertRaisesRegex(BoundaryError,'reference'):compare_observations(a,b,decision_deadline=103)

    def test_same_response_at_other_chain_state_and_stale_or_reorganized_state_refuse(self):
        a=observation()
        for changed,reason in ((dict(chain_id=1),'wrong_chain'),(dict(available_at=104),'deadline'),
                (dict(observed_at=95),'stale'),(dict(canonical_after='fork'),'reorganized')):
            with self.assertRaisesRegex(BoundaryError,reason):compare_observations(a,dict(a,**changed),decision_deadline=103)
        b=deepcopy(a);b['canonical_header']['hash']='fork';b['canonical_after']='fork'
        with self.assertRaisesRegex(BoundaryError,'different_canonical'):compare_observations(a,b,decision_deadline=103)
        self.assertEqual(compare_observations(a,dict(a,result=None),decision_deadline=103)['status'],'MISSING_EVIDENCE')
        self.assertEqual(compare_observations(a,dict(a,boundary='provider_http_429'),decision_deadline=103)['status'],'UNAVAILABLE_OR_ENDPOINT_FAILURE')

    def test_native_buy_and_sell_simulations_gas_and_exact_quantities_are_independent(self):
        with patch('time.monotonic',return_value=100),patch('time.time',return_value=100):
            for side in ('buy','sell'):
                request=dict(quote_request(0),side=side)
                def rpc():
                    r=ExactQuoteRPC();base=r.value
                    r.value=lambda m,p:dict(base(m,p),parentHash='0x'+f'{99:064x}') if m=='eth_getBlockByNumber' else base(m,p)
                    return r
                a=native_quote(rpc(),request)
                b=native_quote(rpc(),request)
                self.assertEqual(a,b)
                self.assertEqual(a['native_economic']['quantity'],request['amount'])
                self.assertGreater(a['native_economic']['gas_quote'],0)

    def test_native_current_curve_prices_and_execution_capacity_match_identical_state(self):
        from tests.lanes.pons.test_pons_selective_continuation import state
        from meme_machine.lanes.pons.pons_selective_paper import _entry_capacity
        from dataclasses import asdict
        a=state();b=state();amount=10**15
        self.assertEqual(a.buy_with_snipe(amount,0),b.buy_with_snipe(amount,0))
        self.assertEqual(_entry_capacity({'state':asdict(a)},amount,21000),
            _entry_capacity({'state':asdict(b)},amount,21000))

    def test_actual_native_quotes_and_governor_waits_for_two_and_twenty_positions(self):
        with tempfile.TemporaryDirectory() as td:
            for n in (1,2,20):
                for cadence in (3,5):
                    rows=[]
                    for mode in ('native','prepared_union'):
                        root=Path(td)/f'{n}-{cadence}-{mode}';root.mkdir()
                        rows.append(scenario(root,n,cadence=cadence,mode=mode))
                    before,union=rows
                    self.assertEqual([d['native_economic'] for d in before['decisions']],
                        [d['native_economic'] for d in union['decisions']])
                    self.assertEqual(before['simulations'],n);self.assertEqual(union['simulations'],n)
                    self.assertEqual(before['physical_requests'],1+2*n)
                    self.assertEqual(union['physical_requests'],3 if n==1 else 4)
                    self.assertEqual(union['original_deadline_misses'],0)
                    if n==20:self.assertGreater(before['original_deadline_misses'],0)

    def test_bounded_envelope_counts_failures_without_retries_or_hypothetical_multipliers(self):
        cfg=dict(ENVELOPE,enabled=True,maximum_marginal_usd='0.001',verified_tariff=dict(
            independently_verified=True,source='SYNTHETIC_OFFLINE_PRICE',endpoint_fingerprint='fixture',
            charged_failure_ceiling='full maximum',batch_member_treatment='per element',archive_rules='maximum included',
            method_max_usd={'eth_call':'0.00001'}))
        budget=OfflineEnvelope(cfg,100)
        for i in range(64):
            budget.reserve(['eth_call'],now=101+i*.5);budget.delivered(10)
        with self.assertRaisesRegex(BoundaryError,'purchase'):budget.reserve(['eth_call'],now=133)
        self.assertEqual(budget.starts,64)
        with self.assertRaisesRegex(BoundaryError,'payload'):budget.delivered(16*1024*1024+1)
        with self.assertRaisesRegex(BoundaryError,'wall'):OfflineEnvelope(cfg,100).reserve(['eth_call'],now=160)
