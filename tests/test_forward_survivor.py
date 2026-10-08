"""Prospective operation on synthetic canonical tapes; no market acceptance."""
from copy import deepcopy
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_historical import Preparation, FORWARD_PLAN, PLAN, FACTORY, GRADUATION
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY, evaluate_entry
from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity


class ForwardSurvivorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=self.temp.name+'/sleeve.sqlite',
            MM_DIRECTIONAL_COHORT_ID='forward-offline'),clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.tape=Tape();self.tape.top=self.tape.grad-12
        self.runtime=Runtime(Path(self.temp.name)/'pons',10**18,'forward','https://offline.invalid')
        self.runtime.rpc=self.tape;self.runtime.deployments_verified=True
        self.runtime.now=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)
        self.addCleanup(lambda:self.runtime.close())
        provider=patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',
                       side_effect=lambda *a,**kw:self.tape.provider())
        provider.start();self.addCleanup(provider.stop)

    def enroll(self):
        self.runtime.discover()
        return self.runtime.history.get_meta(FORWARD_PLAN)

    def observe(self,top=None):
        if top is not None:self.tape.top=top
        for _ in range(160):
            self.runtime.discover()
            if not self.runtime.history.pending_graduations():return
        self.fail('targeted lineage acquisition did not finish')

    def activities(self,endpoint,*,markets,start_block,end_block,**kwargs):
        return {m['token']:collect_v4_activity(None,**m,start_block=start_block,end_block=end_block,
                    _shared=self.tape.shared_activity(start_block,end_block,[m['pool_id']])) for m in markets}

    def seed_complete_winner(self):
        self.enroll();self.observe(self.tape.grad+4)
        token=self.tape.tokens[0];history=self.runtime.history;row=history.get(token)
        anchor=int(history.facts(token,row['through'])[0][0]['price']);at=row['graduation']['at']
        # Complete available four-hour path: trend, reset, completed base, breakout.
        prices=[(0,10000),(1800,11000),(3600,12500),(7200,11200),(9000,11500),
                (12600,11800),(13440,12000),(14100,13000),(14400,13500)]
        points=[(at+t,str(anchor*p//10000)) for t,p in prices]
        now=at+14400;events=[]
        for group in range(3):
            events.append(dict(id='prior:'+str(group),at=now-2000+group,group='buyer:'+str(group),
                               buy=True,quote=10**18,tokens=100,authenticated=True))
        for group in range(6):
            events.append(dict(id='recent:'+str(group),at=now-1000+group,group='buyer:'+str(group),
                               buy=True,quote=10**18,tokens=100,authenticated=True))
        history.append_block(token,block=self.tape.top,header=self.tape.header(self.tape.top),
                             events=events,points=points)
        return token,dict(block=self.tape.top,block_hash=self.tape.header(self.tape.top)['hash'],
                          at=now,price_index=anchor*13500//10000,acquired=time.monotonic())

    def run_winner(self,token,state,*,discovery_failure=False):
        def fresh(candidate):
            self.assertEqual(candidate,token);self.runtime.current=self.runtime.history.get(candidate)
            return dict(state,acquired=time.monotonic())
        with ExitStack() as stack:
            stack.enter_context(patch('meme_machine.runtime.storage.compact_survivor'))
            stack.enter_context(patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activities',side_effect=self.activities))
            stack.enter_context(patch.object(self.runtime,'fresh_state',side_effect=fresh))
            stack.enter_context(patch.object(self.runtime,'fresh_quotes',return_value=SimpleNamespace(loss=lambda n:100)))
            if discovery_failure:
                stack.enter_context(patch.object(self.runtime,'discover',side_effect=BoundaryError('provider_transport_failure')))
            return self.runtime.step(admit=True)

    def test_cold_start_enrolls_inclusively_without_seed_or_backdated_coverage(self):
        self.tape.top=self.tape.grad
        plan=self.enroll()
        self.assertEqual(plan['first'],self.tape.grad)
        self.assertEqual(plan['enrollment_header'],plan['target'])
        self.assertIsNone(self.runtime.history.get_meta(PLAN))
        self.assertIsNone(self.runtime.history.get_meta('discovery_bootstrap'))
        self.observe()
        self.assertIsNotNone(self.runtime.history.get(self.tape.tokens[0]))
        for method,params in self.tape.request_log:
            if method=='eth_getLogs':
                q=params[0]
                self.assertLessEqual(int(q['toBlock'],16)-int(q['fromBlock'],16)+1,10)
                if int(q['fromBlock'],16)<plan['first']:
                    self.assertEqual(q['address'],FACTORY)
                    self.assertEqual(len(q['topics']),2) # candidate-specific pre-enrollment launch
        report=self.runtime.historical_readiness
        self.assertEqual(report['pre_enrollment_coverage'],'UNOBSERVED')
        self.assertFalse(report['historical_opportunity_recall_complete'])
        self.assertFalse(report['seven_day_domain_mature'])

    def test_four_hour_winner_qualifies_despite_unrelated_incomplete_census_and_capital(self):
        token,state=self.seed_complete_winner()
        self.runtime.sleeve.opportunity(token,identity='current-reject',regime='current',
            status='rejected',at=state['at']-1,decision=dict(reason='Current only'))
        self.runtime.sleeve.reserve('all-cash-committed',strategy='pons-selective-continuation-v1',
            amount=10**18,at=state['at']-1,asset='another-asset')
        other=self.runtime.history.get(self.tape.tokens[1]);other['complete']=False
        self.runtime.history.save(other)
        result=self.run_winner(token,state,discovery_failure=True)
        row=self.runtime.history.get(token)
        self.assertTrue(row['decision']['candidate'],row['decision'])
        self.assertEqual(row['decision']['features']['age_seconds'],14400)
        self.assertFalse(result['historical_readiness']['ready'])
        self.assertEqual(row['last_failure']['category'],'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        self.assertEqual(self.runtime.book.reconcile()['open_positions'],0)
        self.assertEqual(self.runtime.sleeve.reconcile()['available'],0)
        phases=[r['phase'] for r in self.runtime.attempts.rows(token)]
        self.assertLess(phases.index('qualification'),phases.index('funding'))

    def test_incomplete_individual_continuity_cannot_qualify(self):
        token,state=self.seed_complete_winner()
        row=self.runtime.history.get(token);row['complete']=False;self.runtime.history.save(row)
        self.run_winner(token,state)
        decision=self.runtime.history.get(token)['decision']
        self.assertFalse(decision['candidate'])
        self.assertIn('incomplete_continuity',decision['all_rejections'])
        self.assertEqual(self.runtime.book.reconcile()['open_positions'],0)

    def test_obsolete_historical_plan_never_starts_or_gates_normal_operation(self):
        token,state=self.seed_complete_winner();h=self.runtime.history
        obsolete=dict(ready=False,search=dict(low=-1,high=100),marker='preserved research plan')
        h.set_meta(PLAN,obsolete)
        self.runtime.sleeve.reserve('committed',strategy='pons-selective-continuation-v1',
                                  amount=10**18,at=state['at']-1,asset='other')
        with patch.object(Preparation,'step',side_effect=AssertionError('whole-market preparation forbidden')):
            self.run_winner(token,state)
        self.assertTrue(h.get(token)['decision']['candidate'])
        self.assertEqual(h.get_meta(PLAN),obsolete)

    def test_required_individual_interval_crossing_outage_stays_incomplete(self):
        token,state=self.seed_complete_winner();h=self.runtime.history
        before=h.get(token)['block'];self.tape.top+=1
        with patch('meme_machine.runtime.storage.compact_survivor'), \
             patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activities',
                   side_effect=BoundaryError('provider_transport_failure')), \
             patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activity',
                   side_effect=BoundaryError('provider_transport_failure')):
            result=self.runtime.step(admit=True)
        self.assertEqual(h.get(token)['block'],before)
        self.assertFalse(self.runtime.candidate_readiness(token,through_block=self.tape.top)['ready'])
        self.assertEqual(result['last_boundary'],'provider_transport_failure')
        self.assertIsNone(h.get(token).get('decision'))
        self.assertEqual(self.runtime.book.reconcile()['open_positions'],0)

    def test_warm_restart_retains_frontier_candidate_times_and_complete_history(self):
        token,state=self.seed_complete_winner();h=self.runtime.history
        row=h.get(token);row.update(original_deadline=123,generation=7);h.save(row)
        before=deepcopy(h.get(token));plan=deepcopy(h.get_meta(FORWARD_PLAN))
        self.runtime.close()
        self.runtime=Runtime(Path(self.temp.name)/'pons',10**18,'forward','https://offline.invalid')
        self.runtime.rpc=self.tape;self.runtime.deployments_verified=True
        self.runtime.now=lambda:state['at'];self.tape.request_log=[]
        self.runtime.discover()
        self.assertEqual(self.runtime.history.get(token),before)
        self.assertEqual(self.runtime.history.get_meta(FORWARD_PLAN)['enrollment_header'],plan['enrollment_header'])
        self.assertTrue(self.runtime.candidate_readiness(token,through_block=state['block'])['ready'])
        self.assertFalse(any(m=='eth_getLogs' for m,p in self.tape.request_log))

    def test_short_outage_keeps_gap_and_recovers_only_uncovered_tail(self):
        self.enroll();self.observe(self.tape.grad+2)
        old=self.runtime.history.get_meta('pons_historical_frontier:forward_population')['block']
        self.tape.top+=3;read=self.tape._read
        def fail_logs(method,params):
            if method=='eth_getLogs':raise BoundaryError('provider_transport_failure')
            return read(method,params)
        with patch.object(self.tape,'_read',side_effect=fail_logs):
            with self.assertRaisesRegex(BoundaryError,'transport_failure'):self.runtime.discover()
        self.assertEqual(self.runtime.history.get_meta('pons_historical_frontier:forward_population')['block'],old)
        self.assertGreater(self.runtime.history.db.execute('SELECT COUNT(*) FROM pons_historical_gaps').fetchone()[0],0)
        self.tape.request_log=[];self.runtime.discover()
        queries=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs']
        self.assertTrue(queries);self.assertTrue(all(int(q['fromBlock'],16)>old for q in queries))
        self.assertEqual(self.runtime.history.db.execute('SELECT COUNT(*) FROM pons_historical_gaps').fetchone()[0],0)

    def test_first_forward_start_migrates_native_checkpoint_but_not_partial_research(self):
        h=self.runtime.history;cursor=self.tape.grad-2
        h.set_meta('discovery_block',cursor)
        h.set_meta('discovery_block_hash',self.tape.header(cursor)['hash'])
        self.tape.top=self.tape.grad+2
        plan=self.enroll();self.observe()
        self.assertEqual(plan['first'],cursor)
        self.assertEqual(plan['restored_from'],'preserved_native_discovery_checkpoint')
        self.assertIsNotNone(h.get(self.tape.tokens[0]))
        self.assertFalse(h.get_meta(FORWARD_PLAN)['readiness']['historical_opportunity_recall_complete'])
        # A retained partial research bootstrap must never silently resume its
        # old market scan. Complete preserved candidate histories remain native.
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
        research=PonsHistory(Path(self.temp.name)/'research.sqlite',policy=POLICY_HASH)
        self.addCleanup(research.close)
        research.set_meta(PLAN,dict(ready=False,marker='obsolete research'))
        research.set_meta('discovery_block',cursor)
        research.set_meta('discovery_block_hash',self.tape.header(cursor)['hash'])
        worker=Preparation(research,self.tape.provider,forward_only=True)
        fresh=worker.begin()
        self.assertEqual(fresh['first'],self.tape.top)
        self.assertNotIn('restored_from',fresh)

    def test_retained_pre_frontier_nomination_recovers_only_its_authenticated_lineage(self):
        h=self.runtime.history;self.tape.top=self.tape.grad+4
        event=next(e for e in self.tape.logs if e['address']==FACTORY and e['topics'][0]==GRADUATION)
        h.retain_graduations([event],self.tape.top,block_hash=self.tape.header(self.tape.top)['hash'])
        plan=self.enroll();self.observe()
        self.assertEqual(plan['first'],self.tape.top)
        self.assertIsNotNone(h.get(self.tape.tokens[0]))
        self.assertEqual(h.pending_graduations(),0)
        for method,params in self.tape.request_log:
            if method=='eth_getLogs' and int(params[0]['fromBlock'],16)<plan['first']:
                self.assertEqual(len(params[0]['topics']),2)
        self.assertEqual(self.runtime.historical_readiness['pre_enrollment_coverage'],'UNOBSERVED')

    def test_old_recovery_never_claims_or_delays_newer_candidate_acquisition(self):
        self.enroll();self.observe(self.tape.grad+2)
        h=self.runtime.history;old=h.get(self.tape.tokens[0]);new=h.get(self.tape.tokens[1])
        old['history_attempt']=100;h.save(old)
        h.set_meta('history_attempt_sequence',100)
        self.tape.top+=80;before=self.tape.top-1
        h.append_block(new['id'],block=before,header=self.tape.header(before),events=[],points=[])
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activities',side_effect=self.activities):
            self.runtime._increment_candidates(h.rows(),self.tape.top)
            self.assertEqual(h.get(new['id'])['block'],self.tape.top)
            self.assertEqual(h.get(old['id'])['block'],old['block'])
            self.assertEqual(h.get(old['id'])['history_attempt'],100)
            self.runtime._increment_candidates(h.rows(),self.tape.top)
        self.assertEqual(h.get(old['id'])['block'],old['block']+40)
        self.assertGreater(h.get(old['id'])['history_attempt'],100)

    def test_reorg_affects_only_forked_checkpoints_and_preserves_controllers(self):
        token,state=self.seed_complete_winner();h=self.runtime.history
        other=deepcopy(h.get(self.tape.tokens[1]));row=h.get(token)
        row.update(position='existing-controller',original_deadline=123,generation=9);h.save(row)
        self.tape.reorg(self.tape.grad+3)
        self.runtime.discover()
        affected=h.get(token)
        self.assertFalse(affected['complete']);self.assertIsNotNone(affected.get('recovery'))
        self.assertEqual(affected['position'],'existing-controller')
        self.assertEqual(affected['original_deadline'],123);self.assertEqual(affected['generation'],9)
        self.assertEqual(h.get(other['id']),other)
        self.assertFalse(self.runtime.candidate_readiness(token)['ready'])

    def test_fork_at_enrollment_parent_rewinds_same_prospective_domain(self):
        self.tape.top=self.tape.grad-2
        original=self.enroll();self.observe(self.tape.grad+2)
        self.tape.reorg(self.tape.grad-11) # includes the targeted pre-enrollment launch
        self.runtime.discover();self.observe()
        plan=self.runtime.history.get_meta(FORWARD_PLAN)
        self.assertEqual(plan['first'],original['first'])
        self.assertEqual(plan['enrollment_header'],original['enrollment_header'])
        self.assertEqual(plan['anchor']['hash'],self.tape.header(plan['first']-1)['hash'])
        self.assertIsNone(self.runtime.history.get_meta(PLAN))
        self.assertEqual(self.runtime.history.get_meta('pons_forward_boundary_reorganizations')['count'],1)
        self.assertTrue(self.runtime.history.db.execute('SELECT COUNT(*) FROM pons_historical_ranges WHERE valid=0').fetchone()[0])
        identity=self.runtime.history.get_meta('pons_historical_identity:'+self.tape.tokens[0])
        self.assertEqual(identity['launch']['blockHash'],self.tape.header(self.tape.grad-10)['hash'])
        self.assertEqual(self.runtime.historical_readiness['pre_enrollment_coverage'],'UNOBSERVED')

    def test_positions_keep_original_admission_during_missing_market_census(self):
        token,state=self.seed_complete_winner();h=self.runtime.history
        row=h.get(token);row.update(position='owned',state='filled');h.save(row)
        calls=[]
        with patch('meme_machine.runtime.storage.compact_survivor'), \
             patch.object(self.runtime,'_position',side_effect=lambda r,**kw:calls.append(('position',kw['admit']))), \
             patch.object(self.runtime,'discover',side_effect=BoundaryError('provider_transport_failure')), \
             patch.object(self.runtime,'_increment_candidates'),patch.object(h,'rows',return_value=[row]):
            result=self.runtime.step(admit=True)
        self.assertEqual(calls,[('position',True)])
        self.assertFalse(result['historical_readiness']['ready'])

    def test_prospective_factory_discovery_retains_more_than_transport_cohort_bound(self):
        self.tape=Tape(candidates=70);self.tape.top=self.tape.grad-12;self.runtime.rpc=self.tape
        self.enroll();self.tape.top=self.tape.grad+70
        worker=self.runtime.forward_preparation
        while worker._frontier(worker.population_kind,self.tape.grad-12,None)['block']<self.tape.top:
            self.runtime.discover()
        for _ in range(150):
            if not self.runtime.history.pending_graduations():break
            self.runtime.discover()
        self.assertEqual(len(self.runtime.history.rows()),70)
        self.assertEqual(len([e for e in worker.population() if e['topics'][0]==GRADUATION]),70)
        self.assertEqual(self.runtime.history.pending_graduations(),0)

    def test_original_inclusive_maximum_age_and_frozen_policies(self):
        from tests.lanes.pons.test_pons_postgrad_survivor import facts
        for age,valid in ((14399,False),(14400,True),(604800,True),(604801,False)):
            out=evaluate_entry(facts(graduation_at=1000000-age))
            self.assertEqual(not {'too_early','too_old'} & set(out['all_rejections']),valid)
        for path in ('meme_machine/lanes/pons/pons_postgrad_survivor.py',
                     'meme_machine/lanes/pump/pumpswap_survivor.py','operational/nine-change-implementation.json'):
            original=subprocess.check_output(['git','show','b1f215ed:'+path])
            self.assertEqual(Path(path).read_bytes(),original)

    def test_pump_uses_its_own_four_hour_age_and_six_hour_price_requirement(self):
        from tests.lanes.pump.test_pumpswap_survivor import facts
        from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry as pump_entry, POLICY as pump_policy
        self.assertEqual(pump_policy['minimum_age_seconds'],14400)
        for age,passes in ((14400,False),(21600,True)):
            f=facts();offset=f['now']-age
            f['now']=age;f['base_end']-=offset
            f['price_points']=[dict(at=0,price='100')]+[
                dict(row,at=row['at']-offset) for row in f['price_points'] if row['at']>offset]
            for e in f['demand_events']:e['at']-=offset
            decision=pump_entry(f)
            self.assertNotIn('age',decision['all_rejections'])
            self.assertEqual(decision['candidate'],passes,decision)
            if not passes:self.assertIn('six_hour_structure',decision['all_rejections'])
        f['continuity_complete']=False
        self.assertIn('authoritative_evidence',pump_entry(f)['all_rejections'])

    def test_pump_discovers_independently_from_canonical_interval_on_cold_and_warm_start(self):
        from dataclasses import replace
        from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime as PumpRuntime, PUMP_SCOPE
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH as PUMP_POLICY
        from tests.test_solana_evidence_plane import record,proof
        path=Path(self.temp.name)/'pump-plane.sqlite'
        writer=EvidenceWriter(path);self.addCleanup(writer.close)
        reader=EvidenceReader(path);self.addCleanup(reader.close)
        history=History(Path(self.temp.name)/'pump-history.sqlite',policy=PUMP_POLICY)
        self.addCleanup(lambda:history.close())
        rt=object.__new__(PumpRuntime);rt.history=history
        interests=[];rt.plane=SimpleNamespace(frontier=lambda s:101,reader=reader,
            interest=lambda scope,**kw:interests.append((scope,kw)))
        rt.discover();self.assertEqual(history.get_meta('discovery_slot'),100)
        event=dict(event_type='migration',quote_asset='SOL',market_time=101,slot=101,
                   mint='new-independent-mint',pool='canonical-migration-pool',quote_amount=100,mint_amount=10)
        row=replace(record(101,scope=PUMP_SCOPE,observed=200),payload=dict(event=event),kind='event')
        # An observed migration without an interval proof cannot create history.
        writer.ingest([row])
        with self.assertRaises(EvidenceUnavailable):rt.discover()
        self.assertIsNone(history.get(event['mint']))
        writer.ingest([],proof=proof(101,101,scope=PUMP_SCOPE,at=200));rt.discover()
        self.assertEqual(history.get(event['mint'])['graduation']['at'],101)
        self.assertEqual(interests[0][1]['lower_slot'],101)
        history.close();history=History(Path(self.temp.name)/'pump-history.sqlite',policy=PUMP_POLICY)
        rt.history=history;before=history.get(event['mint']);rt.discover()
        self.assertEqual(history.get(event['mint']),before)
        self.assertIsNone(history.get_meta('seven_day_ready'))

    def test_shared_worker_cadence_follows_pons_without_changing_pump_or_provider_rate(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime as PumpRuntime
        from meme_machine.runtime.robinhood.provider_authority import INTERVAL_SECONDS
        self.assertGreater(40/Runtime.observation_interval_seconds,9.897436221985844)
        self.assertFalse(hasattr(PumpRuntime,'observation_interval_seconds'))
        self.assertEqual(INTERVAL_SECONDS,.5)
        for interval in (3,5):
            calls=[]
            service=SimpleNamespace(step=lambda **kw:(calls.append(kw) or {}),close=lambda:None)
            if interval==3:service.observation_interval_seconds=Runtime.observation_interval_seconds
            worker=Worker(lambda:service,enrichment_enabled=False)
            try:
                worker.prime();worker.tick(100,admit=True);worker.future.result(timeout=1)
                worker.tick(100+interval-1,admit=True)
                self.assertEqual(len(calls),2)
                worker.tick(100+interval,admit=True);worker.future.result(timeout=1)
                self.assertEqual(len(calls),3)
            finally:worker.close()
