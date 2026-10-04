"""Durable observational telemetry: no provider, allocation or epoch authority."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.journal import canonical,digest
from meme_machine.runtime import opportunity_telemetry as telemetry
from meme_machine.lanes.pons.pons_selective_continuation import ENTRY_THRESHOLDS

class OpportunityTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'sleeve.sqlite'
        self.sleeve=self.open()
    def tearDown(self):
        self.sleeve.close();self.temp.cleanup()
    def open(self):
        return SleeveReservations(self.path,lane='pons',capital=100000,
            policies={'current':'c','pons-survivor':'s'},cohort='existing-paper-epoch')
    def decision(self):
        return dict(vector=dict(policy='current',policy_hash='c',thresholds=dict(ENTRY_THRESHOLDS),
            progress_bps=6000,token_age_seconds=200,decision_state_age_seconds=1,
            trajectory=dict(complete=True,progress_15s_bps=199,accelerating=True,graduation_eta_seconds=50),
            demand=dict(independent_groups=5,new_independent_groups_15s=2,buy_sell_ratio_bps=20000,
                current_net_quote=1000,net_flow_accelerating=True,largest_buyer_flow_bps=2000,
                top3_buyer_flow_bps=6000,creator_sell_quote_15s=0),
            roundtrip_loss_bps=100,proposed_size=dict(amount_quote=100,
                execution_capacity=dict(double_loss_bps=200)),current_snipe_bps=0,
            pair_token='0x'+'0'*40,all_rejections=['curve_velocity'],current_threshold_pass=False),
            context=dict(state=dict(graduated=False,creator_tax_bps=0),lineage_verified=True,
                evidence_complete=True,execution_stress_verified=True,
                reference_price='1',source_cursor=dict(block=100,hash='authenticated')),
            executable_quote=dict(observed_at=100,amount=100))
    def reject(self,at=100,decision=None):
        return self.sleeve.opportunity('token',identity='current-decision',regime='current',
            status='rejected',at=at,decision=self.decision() if decision is None else decision)
    def bodies(self,kind):
        return [json.loads(raw) for raw, in self.sleeve.db.execute(
            'SELECT body FROM opportunity_journal_v1 WHERE kind=? ORDER BY seq',(kind,))]
    def financial(self):
        return {name:list(self.sleeve.db.execute('SELECT * FROM '+name)) for name in
            ('sleeve_genesis','sleeve_positions','sleeve_candidates','sleeve_journal')}
    def test_all_gate_distances_categories_and_marginal_alpha(self):
        self.reject();body=self.bodies('receipt')[0]
        self.assertEqual(body['opportunity_id'],'pons:token')
        self.assertEqual(body['asset_id'],'token')
        self.assertTrue(body['marginal_alpha_reject'])
        self.assertEqual(body['ranked_failed_alpha_gates'],['curve_velocity'])
        gate=next(g for g in body['gates'] if g['name']=='curve_velocity')
        self.assertEqual(gate['signed_distance'],'-1')
        self.assertEqual(gate['normalized_signed_distance'],'-1/200')
        self.assertEqual(body['existing_executable_quote'],dict(observed_at=100,amount=100))
        self.assertFalse(body['qualification_authority']);self.assertFalse(body['order_authority'])
        bad=self.decision();bad['vector']['demand']['largest_buyer_flow_bps']=5000
        self.reject(at=101,decision=bad);self.assertFalse(self.bodies('receipt')[-1]['marginal_alpha_reject'])
        unknown=self.decision();unknown['context'].pop('evidence_complete')
        self.reject(at=102,decision=unknown);self.assertFalse(self.bodies('receipt')[-1]['marginal_alpha_reject'])
    def test_replay_conflicting_duplicate_and_immutable_hash_chain(self):
        self.reject();before=telemetry.verify(self.sleeve.db)
        self.reject();self.assertEqual(before,telemetry.verify(self.sleeve.db))
        bad=self.decision();bad['vector']['progress_bps']=6100
        self.assertIsNone(self.reject(decision=bad))
        self.assertIn('ValueError',self.sleeve.opportunity_error)
        self.assertEqual(before,telemetry.verify(self.sleeve.db))
        with self.assertRaises(sqlite3.IntegrityError):
            self.sleeve.db.execute("UPDATE opportunity_journal_v1 SET body='{}' WHERE seq=1")
        self.sleeve.close();self.sleeve=self.open()
        self.assertEqual(before,telemetry.verify(self.sleeve.db))
    def test_outcome_windows_actual_fill_terminal_and_exact_accounting(self):
        self.reject()
        self.sleeve.observe('token',strategy='pons-survivor',at=150,state='qualified',
            evidence={'candidate':True},regime={'at':150})
        self.sleeve.opportunity('token',identity='token',regime='survivor',status='qualified',at=150)
        self.sleeve.reserve('survivor-position',strategy='pons-survivor',amount=100,
            candidate='token',generation=1,regime={'at':150},at=151)
        self.sleeve.acknowledge_native('survivor-position',basis=100,pnl=0,at=152,
            native_hash='fill-hash',native_verified=True)
        self.sleeve.release('survivor-position',pnl=25,at=200,
            terminal_hash='exit-hash',native_verified=True)
        before=self.financial()
        with self.sleeve.transaction():
            telemetry.observe_prices(self.sleeve.db,'pons','pons:token',
                [dict(at=160,price=2*10**18,low=5*10**17,high=3*10**18)],source_hash='persisted')
        for now in (400,1000,3700,21700,86500):
            with self.sleeve.transaction():telemetry.enrich(self.sleeve.db,now=now)
        outcomes=self.bodies('outcome')
        self.assertEqual([o['window_seconds'] for o in outcomes],list(telemetry.WINDOWS))
        self.assertEqual(outcomes[0]['maximum_favorable_excursion_bps'],20000)
        self.assertEqual(outcomes[0]['maximum_adverse_excursion_bps'],-5000)
        self.assertEqual(outcomes[0]['terminal_or_last_observable_return_bps'],10000)
        self.assertTrue(outcomes[0]['survivor_qualified']);self.assertTrue(outcomes[0]['survivor_fill_committed'])
        self.assertEqual(outcomes[0]['survivor_terminal_outcome']['realized_pnl'],25)
        self.assertEqual(before,self.financial())
    def test_old_schema_interrupted_additive_migration_preserves_epoch_and_positions(self):
        self.sleeve.close()
        old=Path(self.temp.name)/'old.sqlite';self.path=old
        with patch.object(telemetry,'install',side_effect=RuntimeError('simulated pre-DDL interruption')):
            self.sleeve=self.open()
        self.assertFalse(self.sleeve.opportunity_ready)
        self.reject()
        self.sleeve.reserve('current-open',strategy='current',amount=100,asset='another',at=1)
        before=self.financial();self.sleeve.close()
        original=telemetry.record
        def interrupted(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError('interrupted legacy backfill')
        with patch.object(telemetry,'record',side_effect=interrupted):
            self.sleeve=self.open()
        self.assertFalse(self.sleeve.opportunity_ready)
        self.assertEqual(before,self.financial())
        self.assertIsNone(self.sleeve.db.execute(
            "SELECT name FROM sqlite_master WHERE name='opportunity_journal_v1'").fetchone())
        self.sleeve.close();self.sleeve=self.open()
        self.assertTrue(self.sleeve.opportunity_ready);self.assertEqual(before,self.financial())
        proof=telemetry.verify(self.sleeve.db)
        self.assertEqual(proof['receipts'],1)
        self.sleeve.close();self.sleeve=self.open()
        self.assertEqual(proof,telemetry.verify(self.sleeve.db))
    def test_enrichment_restart_is_bounded_and_does_not_fetch_or_change_history(self):
        from meme_machine.runtime.survivor_history import History
        history=History(Path(self.temp.name)/'history.sqlite',policy='survivor')
        try:
            history.graduate('token',dict(at=120,identity='authenticated-graduation'))
            history.append('token',through=400,events=[],points=[
                (at,str((at-100)*10**18)) for at in range(121,301)],complete=True)
            self.reject();baseline=history.db.total_changes;before=self.financial()
            service=SimpleNamespace(sleeve=self.sleeve,history=history)
            for index in range(12):
                result=telemetry.enrich_service(service,now=400)
                self.assertLessEqual(result['exported_prices'],256)
                self.assertLessEqual(result['processed_events'],512)
                if self.bodies('outcome'):break
                if index==2:
                    self.sleeve.close();self.sleeve=self.open();service.sleeve=self.sleeve
            self.assertEqual(len(self.bodies('outcome')),1)
            self.assertEqual(self.bodies('outcome')[0]['maximum_favorable_excursion_bps'],1990000)
            self.assertTrue(self.bodies('outcome')[0]['survivor_candidate_created'])
            self.assertEqual(baseline,history.db.total_changes);self.assertEqual(before,self.financial())
        finally:history.close()

    def test_existing_context_capture_never_fetches_market_evidence(self):
        from meme_machine.lanes.pons.evidence import Stamp
        from meme_machine.lanes.pons.pons import CurveState
        signal=SimpleNamespace(mint='mint',point_in_time=True,future_data_used=False)
        snapshot=dict(mint='mint',slot=123,market_time=100,state=dict(quote_reserve=200,base_reserve=100))
        context=telemetry.pump_context(signal,snapshot,'optimistic_preflight')
        self.assertEqual(context['reference_price'],'2')
        self.assertFalse(context['evidence_complete']);self.assertFalse(context['concentration_measured'])
        full=telemetry.pump_context(signal,snapshot,'full_point_in_time')
        self.assertTrue(full['evidence_complete']);self.assertTrue(full['concentration_measured'])
        state=SimpleNamespace(quote_reserve=200,token_reserve=100)
        evaluation=dict(token='token',source_block=123,source_transaction='tx',source_log_index=0,
            candidate=dict(token='token',auth={'verified':True},state=vars(state),
                stamp=Stamp(1,123,'hash',100,101,'confirmed','captured')),
            vector=self.decision()['vector'])
        evaluation['vector']['complete']=True
        context=telemetry.pons_context(evaluation)
        self.assertEqual(context['reference_price'],'2')
        self.assertEqual(context['source_cursor']['stamp']['block_hash'],'hash')
        self.assertTrue(context['lineage_verified']);self.assertTrue(context['execution_stress_verified'])

    def test_disabled_or_failed_enrichment_cannot_change_worker_decisions(self):
        from meme_machine.runtime.survivor_history import Worker
        def factory():
            return SimpleNamespace(step=lambda **kw:dict(last_boundary=None,
                accounting_replay_verified=True,ordinary_admission=kw['admit']),close=lambda:None)
        enabled=Worker(factory);disabled=Worker(factory,enrichment_enabled=False)
        try:
            with patch.object(telemetry,'enrich_service',side_effect=ValueError('diagnostic only')):
                left=enabled.prime();right=disabled.prime()
            for key in ('last_boundary','accounting_replay_verified','ordinary_admission'):
                self.assertEqual(left[key],right[key])
            self.assertEqual(left['opportunity_telemetry']['status'],'FAILED')
            for key in ('completed_steps','successful_steps','admission_enabled_steps','allocation_authority'):
                self.assertEqual(left['machinery'][key],right['machinery'][key])
        finally:enabled.close();disabled.close()
