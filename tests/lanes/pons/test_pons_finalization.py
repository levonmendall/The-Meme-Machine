"""Pons-only machinery regressions with offline providers and temporary state.

Synthetic population/market paths prove mechanics, never historical recall or
provider throughput. Native policy authority remains in the existing modules.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import os
import json
import time
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.abi import topic
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons.protocols import PoolKey
from meme_machine.lanes.pons.pons_attempts import Attempts, decision_category, failure_category
from meme_machine.lanes.pons.pons_current_window import canonical_window
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_HASH
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH as SURVIVOR_HASH
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime, ZERO, _event_topic
from meme_machine.lanes.pons.provider_admission import Admission, position_work
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.robinhood.pons import Broker
from tests.lanes.pons.test_pons_selective_continuation import vector
from tests.lanes.pons.test_pons_postgrad_survivor import NOW, winner_points

MODULE='meme_machine.lanes.pons.pons_survivor_runtime'
ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_PONS_FINALIZATION'
POPULATION=1025


def address(n):return '0x'+f'{n:040x}'
def block_header(n):return dict(number=hex(n),timestamp=hex(n),hash='0x'+f'{n:064x}')
def observation(n,block=100):
    return dict(address=address(n),blockNumber=hex(block),blockHash=block_header(block)['hash'],
        transactionHash='0x'+f'{n:064x}',transactionIndex=hex(n),logIndex='0x0')
def graduation(n,at=100,block=100):
    return dict(at=at,block=block,block_hash=block_header(block)['hash'],
        record=dict(pairToken=ZERO,deployer=address(90000),creatorFeeRecipient=address(90000)),
        transition=dict(market='0x'+f'{n:064x}',initialization_sqrt_price_x96=1<<96,graduation_gas_used=200000),
        key=asdict(PoolKey(ZERO,address(n),0,0,address(80000))))


class OfflineRPC:
    used=0
    def call(self,method,params,scope):
        if method=='eth_getBlockByNumber':return block_header(int(params[0],16))
        raise AssertionError(method)
    def batch(self,calls,scope):return [self.call(m,p,scope) for m,p in calls]


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.enterContext(patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(self.root/'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID='pons-finalization'),clear=True))
        self.runtime=Runtime(self.root/'survivor',10**18,'pons-finalization',ENDPOINT)
        self.addCleanup(self.runtime.close)
        self.runtime.rpc=OfflineRPC();self.runtime.deployments_verified=True


class RetentionTests(unittest.TestCase):
    def test_4096_cheap_identities_reopen_without_candidate_or_capital_gate(self):
        with tempfile.TemporaryDirectory() as td:
            broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            history=PonsHistory(Path(td)/'history.sqlite',policy=SURVIVOR_HASH)
            for n in range(1,4097):
                broker.enqueue(observation(n));history.graduate(address(n),graduation(n))
            broker.close();history.close()
            broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            history=PonsHistory(Path(td)/'history.sqlite',policy=SURVIVOR_HASH)
            try:
                self.assertEqual(len(broker.rows),4096);self.assertEqual(len(history.rows()),4096)
                self.assertIsNotNone(broker.plane.get(broker.identity(observation(4096))))
                self.assertEqual(history.get(address(4096))['graduation'],graduation(4096))
            finally:broker.close();history.close()

    def test_1025_current_identities_survive_restart_without_count_eviction(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'plane.sqlite'
            broker=Broker(path,CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            for n in range(1,POPULATION+1):self.assertTrue(broker.enqueue(observation(n)))
            self.assertEqual(len(broker.rows),POPULATION);broker.close()
            broker=Broker(path,CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            try:
                broker.plane.maintain()
                self.assertEqual(len(broker.rows),POPULATION)
                expected=vector()
                for n in (1,65,257,1024,1025):
                    retained=broker.rows[broker.identity(observation(n))]
                    self.assertEqual(retained['event'],observation(n))
                    self.assertEqual(retained['queued_at'],100.)
                    self.assertEqual(vector(),expected)
            finally:broker.close()

    def test_1025_survivors_and_pending_graduations_survive_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';history=PonsHistory(path,policy=SURVIVOR_HASH)
            for n in range(1,POPULATION+1):history.graduate(address(n),graduation(n))
            nominees=[observation(n) for n in range(1,POPULATION+1)]
            history.retain_graduations(nominees,100);history.close()
            history=PonsHistory(path,policy=SURVIVOR_HASH)
            try:
                self.assertEqual(len(history.rows()),POPULATION)
                self.assertEqual(history.pending_graduations(),POPULATION)
                self.assertEqual(history.get_meta('discovery_block'),100)
                for n in (1,65,257,1024,1025):self.assertEqual(history.get(address(n))['graduation'],graduation(n))
            finally:history.close()

    def test_current_failure_reactivates_on_new_market_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            try:
                for n,failure in enumerate(('provider_http_429','provider_transport_failure','selective_window_event_capacity'),1):
                    old=observation(n)
                    broker.enqueue(old);scheduled=broker.pop()
                    self.assertIsNotNone(scheduled);broker.failure(scheduled,failure)
                    self.assertIsNotNone(broker.plane.get(broker.identity(old)))
                    fresh=dict(old,blockNumber=hex(int(old['blockNumber'],16)+100),transactionHash=failure)
                    broker.enqueue(fresh);self.assertIsNotNone(broker.pop())
                    # Complete the claim before the next independent case.
                    claim=broker.plane.get(broker.identity(old))
                    broker.plane.finish(claim,state='authoritative_evidence_failure',reason=failure)
            finally:broker.close()

    def test_public_raw_conflict_cannot_tombstone_every_future_current_generation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'plane.sqlite';broker=Broker(path,CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            raw=observation(1);self.assertTrue(broker.enqueue(raw))
            self.assertFalse(broker.enqueue(dict(raw,data='public-conflicting-variant')))
            self.assertIsNone(broker.plane.get(broker.identity(raw))['reason'])
            broker.close();broker=Broker(path,CURRENT_HASH,clock=lambda:101.,source=ENDPOINT)
            try:
                self.assertTrue(broker.enqueue(observation(1,101)))
                job=broker.pop();self.assertEqual(job['event']['blockNumber'],hex(101))
                self.assertEqual(job['deadline'],106.)
            finally:broker.close()

    def test_legacy_public_conflict_reactivates_only_as_unqualified_canonical_work(self):
        with tempfile.TemporaryDirectory() as td:
            broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:100.,source=ENDPOINT)
            raw=observation(1);key=broker.identity(raw)
            args=dict(ordering=(100,1,0),watermark={},interpretation=broker.policy,observed=100.,deadline=105.,priority=4)
            broker.plane.observe(key,'pons','legacy',raw,**args)
            broker.plane.observe(key,'pons','legacy',dict(raw,data='conflict'),**args)
            self.assertEqual(broker.plane.get(key)['reason'],'conflicting_observation')
            self.assertTrue(broker.enqueue(observation(1,101),now=101.))
            work=broker.pop();self.assertEqual(work['deadline'],106.)
            self.assertIsNone(work['work']['result']);self.assertNotEqual(work['work']['state'],'qualified')
            self.assertEqual(broker.plane.db.execute("SELECT COUNT(*) FROM transitions WHERE reason='pons_public_conflict_requires_fresh_canonical_evidence'").fetchone()[0],1)
            broker.close()


class QuietCurrentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'plane.sqlite';self.now=100.
        self.broker=Broker(self.path,CURRENT_HASH,clock=lambda:self.now,source=ENDPOINT)
        self.addCleanup(lambda:self.broker.close())

    def reopen(self):
        self.broker.close();self.broker=Broker(self.path,CURRENT_HASH,clock=lambda:self.now,source=ENDPOINT)

    def test_provider_failure_restarts_and_rechecks_without_a_new_buy_or_renewed_source_clock(self):
        raw=observation(1);self.broker.enqueue(raw);work=self.broker.pop()
        self.broker.failure(work,'provider_http_429');self.reopen();self.now=106.
        self.assertFalse(self.broker.enqueue(raw))
        self.assertEqual(self.broker.plane.get(work['key'])['deadline'],105.)
        # A failed service estimate cannot become permanent eligibility authority.
        self.broker.plane.db.execute('INSERT INTO service VALUES(?,?,?,?,?)',('pons',10.,0,0,self.now))
        fresh=self.broker.pop();self.assertTrue(fresh['canonical_refresh'])
        self.assertEqual((fresh['queued_at'],fresh['deadline']),(106.,111.))
        self.assertEqual(fresh['event'],raw)
        self.assertEqual(json.loads(fresh['work']['desired'])['first_observed_at'],100.)
        self.assertEqual(fresh['work']['ordering'],work['work']['ordering'])
        self.assertEqual(fresh['work']['latest_id'],work['work']['latest_id'])
        self.assertEqual(fresh['work']['generation'],work['work']['generation']+1)
        self.assertIsNone(fresh['work']['result'])

    def test_every_quiet_identity_gets_a_turn_under_continuous_new_buy_pressure(self):
        for n in range(1,POPULATION+1):self.broker.enqueue(observation(n))
        self.now=106.;self.assertIsNone(self.broker.plane.claim(lane='pons',estimate_seconds=10.))
        seen=set();turns=0
        while len(seen)<POPULATION and turns<2*POPULATION+1:
            self.broker.enqueue(dict(observation(20000+turns,block=int(self.now)),address=address(20000)))
            work=self.broker.pop();self.assertIsNotNone(work)
            if work['canonical_refresh'] and int(work['event']['address'],16)<=POPULATION:
                seen.add(int(work['event']['address'],16))
            self.broker.failure(work,'provider_http_429');self.now+=.5;turns+=1
        self.assertEqual(seen,set(range(1,POPULATION+1)))
        self.assertLessEqual(turns,2*POPULATION)
        self.assertEqual(self.broker.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch WHERE candidate LIKE ?',
            ('%'+address(1024),)).fetchone()[0],1)

    def test_restart_repairs_observation_watch_gap_and_retirement_keeps_the_nominee(self):
        raw=observation(1);self.broker.enqueue(raw)
        # Representative death between durable observe and watch projection.
        self.broker.plane.db.execute('DELETE FROM pons_current_watch');self.reopen()
        work=self.broker.pop();self.broker.failure(work,'provider_transport_failure')
        self.broker.enqueue(observation(1,101),needs_work=False)
        last=self.broker.plane.get(work['key'])
        self.now=100.+86401;self.broker.plane.maintain()
        self.assertIsNone(self.broker.plane.get(work['key']))
        self.reopen();fresh=self.broker.pop()
        self.assertTrue(fresh['canonical_refresh']);self.assertEqual(fresh['event'],raw)
        self.assertEqual(json.loads(fresh['work']['desired'])['first_observed_at'],100.)
        self.assertGreater(fresh['work']['generation'],work['work']['generation'])
        self.assertGreater(fresh['work']['generation'],last['generation'])
        self.assertEqual(fresh['work']['ordering'],last['ordering'])
        self.assertEqual(fresh['work']['latest_id'],last['latest_id'])

    def test_unconsumed_decision_and_pending_native_confirmation_are_not_superseded_by_timer(self):
        self.broker.enqueue(observation(1));work=self.broker.pop()
        self.assertTrue(self.broker.finish(work,dict(candidate={},vector=vector()),.1))
        self.now=106.;self.assertIsNone(self.broker.pop())
        self.assertEqual(self.broker.plane.get(work['key'])['generation'],work['work']['generation'])
        self.now=100.;self.assertTrue(self.broker.plane.decision(work['key'],work['work']['generation'],'entry_confirmation'))
        self.broker.acknowledge(work);self.now=106.;self.assertIsNone(self.broker.pop())
        self.broker.release_entry_guard(address(1));fresh=self.broker.pop()
        self.assertTrue(fresh['canonical_refresh']);self.assertGreaterEqual(fresh['work']['priority'],2)

    def test_real_new_buy_supersedes_timer_and_old_timer_completion_has_no_authority(self):
        self.broker.enqueue(observation(1));work=self.broker.pop();self.broker.failure(work,'provider_http_429')
        self.now=106.;timer=self.broker.pop()
        self.assertTrue(self.broker.enqueue(observation(1,107)))
        self.assertFalse(self.broker.plane.current(timer['work']))
        self.assertFalse(self.broker.finish(timer,dict(candidate={},vector=vector()),.1))
        fresh=self.broker.pop();self.assertFalse(fresh['canonical_refresh'])
        self.assertEqual(fresh['event'],observation(1,107))

    def test_restart_orphan_confirmation_releases_only_without_native_ownership(self):
        for n in (1,2,3):
            self.broker.enqueue(observation(n));work=self.broker.pop()
            self.assertTrue(self.broker.finish(work,dict(candidate={},vector=vector()),.1))
            self.assertTrue(self.broker.plane.decision(work['key'],work['work']['generation'],'entry_confirmation'))
            self.broker.acknowledge(work)
        key=self.broker.identity(observation(3))
        self.broker.plane.checkpoint('native_position:pons:owned',dict(candidate=key,position=dict(status='reserved')))
        self.reopen();self.now=106.;self.broker.release_orphan_entry_guards([address(2)])
        self.assertEqual(self.broker.plane.get(self.broker.identity(observation(2)))['state'],'entry_confirmation')
        self.assertEqual(self.broker.plane.get(key)['state'],'entry_confirmation')
        fresh=self.broker.pop();self.assertTrue(fresh['canonical_refresh'])
        self.assertEqual(fresh['event']['address'],address(1))


class SurvivorSchedulingTests(RuntimeCase):
    def seed(self):
        for n in range(1,POPULATION+1):
            row=self.runtime.history.graduate(address(n),graduation(n))
            row['block']=100;self.runtime.history.save(row)

    def test_failed_64_member_batch_rotates_and_all_1025_advance_after_restart(self):
        self.seed();attempts=[];failed=[False]
        def collect(endpoint,*,markets,start_block,end_block):
            self.assertLessEqual(len(markets),64);self.assertEqual((start_block,end_block),(101,140))
            attempts.append([m['token'] for m in markets])
            if not failed[0]:failed[0]=True;raise BoundaryError('provider_http_429')
            return {m['token']:dict(swaps=[]) for m in markets}
        with patch(MODULE+'.collect_v4_activities',side_effect=collect):
            with self.assertRaisesRegex(BoundaryError,'429'):
                self.runtime._increment_candidates(self.runtime.history.rows(),140)
            self.runtime.history.close()
            self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
            for _ in range(17):self.runtime._increment_candidates(self.runtime.history.rows(),140)
        self.assertTrue(set(attempts[0]).isdisjoint(attempts[1]))
        self.assertEqual({r['block'] for r in self.runtime.history.rows()},{140})
        self.assertEqual(len(self.runtime.history.rows()),POPULATION)
        for n in (1,65,257,1024,1025):self.assertEqual(self.runtime.history.get(address(n))['through'],140)

    def test_qualification_turn_is_fair_and_durable(self):
        self.seed();seen=[]
        for _ in range(513):seen.append(self.runtime.history.qualification_turn(self.runtime.history.rows(),200)['id'])
        self.runtime.history.close()
        self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
        for _ in range(512):seen.append(self.runtime.history.qualification_turn(self.runtime.history.rows(),201)['id'])
        self.assertEqual(len(set(seen)),POPULATION)

    def test_graduation_burst_is_retained_before_one_authentication(self):
        factory=load('pons_v2_factory')['address'].lower();signature=_event_topic('pons_v2_factory','PoolGraduated')
        events=[dict(observation(n),address=factory,topics=[signature,'0x'+'0'*24+address(n)[2:]]) for n in range(1,POPULATION+1)]
        self.runtime.history.set_meta('discovery_block',99)
        self.runtime.now=lambda:100
        def transition(rpc,candidate,start,end,report):
            evidence=graduation(int(candidate['token'],16))
            return dict(evidence['transition'],graduation_at=100),PoolKey(**evidence['key']),block_header(100),evidence['record']
        with patch(MODULE+'._latest_header',return_value=block_header(100)), \
             patch.object(self.runtime.rpc,'batch',return_value=[list(reversed(events))]), \
             patch(MODULE+'._factory_record_at',side_effect=lambda rpc,t,b,r:dict(curve=address(70000))), \
             patch(MODULE+'._graduation_transition',side_effect=transition) as authenticate:
            self.runtime.discover()
        self.assertEqual(authenticate.call_count,1)
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),100)
        self.assertEqual(self.runtime.history.pending_graduations(),1024)
        self.assertEqual(len(self.runtime.history.rows()),1)
        self.runtime.history.close()
        self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
        self.assertEqual(self.runtime.history.pending_graduations(),1024)

    def test_cold_start_seven_day_boundary_is_inclusive_and_resumes_search(self):
        self.runtime.rpc.call=lambda m,p,scope:dict(number=p[0],timestamp=hex(int(p[0],16)*10000),hash=p[0])
        head=dict(number=hex(100),timestamp=hex(1000000),hash='head')
        self.assertIsNone(self.runtime._bootstrap_cursor(head))
        self.runtime.history.close()
        self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
        cursor=None
        for _ in range(10):
            cursor=self.runtime._bootstrap_cursor(head)
            if cursor is not None:break
        # 1,000,000 - 604,800 = 395,200. Block 40 is the first eligible block.
        self.assertEqual(cursor,39)
        self.assertEqual(self.runtime.history.get_meta('discovery_block'),39)

    def test_first_position_failure_does_not_starve_second_or_resume_discovery(self):
        for n in (1,2):
            row=self.runtime.history.graduate(address(n),graduation(n));row['position']=f'position{n}';self.runtime.history.save(row)
        order=[]
        def monitor(row,**kwargs):
            order.append(row['position'])
            if row['position']=='position1':raise BoundaryError('provider_http_429')
        with patch.object(self.runtime,'_position',side_effect=monitor), \
             patch.object(self.runtime,'discover',side_effect=lambda:order.append('discovery')):
            result=self.runtime.step(admit=True)
        self.assertEqual(order,['position1','position2','discovery'])
        self.assertEqual(result['deferred_boundaries'],['provider_http_429'])
        self.assertEqual(self.runtime.history.get(address(1))['position'],'position1')

    def test_block_checkpoint_and_observations_commit_atomically(self):
        row=self.runtime.history.graduate(address(1),graduation(1));row['block']=100;self.runtime.history.save(row)
        self.runtime.history.append_block(address(1),block=140,header=block_header(140),
            events=[dict(id='trade',at=140,group=address(2),buy=True,quote=10,tokens=10,authenticated=True)],points=[(140,'100')])
        self.runtime.history.close();self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
        restored=self.runtime.history.get(address(1));self.assertEqual((restored['block'],restored['through']),(140,140))
        self.assertEqual(restored['block_hash'],block_header(140)['hash'])
        before=deepcopy(restored)
        with self.assertRaisesRegex(ValueError,'future_price'):
            self.runtime.history.append_block(address(1),block=141,header=block_header(141),events=[],points=[(142,'101')])
        self.assertEqual(self.runtime.history.get(address(1)),before)

    def test_reorg_rebuild_is_bounded_and_keeps_other_candidates_and_native_controller(self):
        for n in (1,2):
            row=self.runtime.history.graduate(address(n),graduation(n));row['block']=100
            if n==1:row['position']='native-controller'
            self.runtime.history.save(row)
            self.runtime.history.append_block(address(n),block=140,header=block_header(140),
                events=[dict(id='old',at=140,group=address(3),buy=True,quote=10,tokens=10,authenticated=True)],
                points=[(140,'999')])
        bad=self.runtime.history.get(address(1));bad['block_hash']='orphan'
        bad['evidence_checkpoint']['block_hash']='orphan';self.runtime.history.save(bad)
        with patch(MODULE+'.collect_v4_activities',return_value={address(n):dict(swaps=[]) for n in (1,2)}):
            self.runtime._increment_candidates(self.runtime.history.rows(),180)
        first=self.runtime.history.get(address(1));second=self.runtime.history.get(address(2))
        self.assertEqual((first['block'],first['position'],first['complete']),(100,'native-controller',False))
        self.assertEqual(second['block'],180)
        self.assertEqual(self.runtime.history.facts(address(1),140)[1],[])
        self.runtime.history.close();self.runtime.history=PonsHistory(self.root/'survivor/history.sqlite',policy=SURVIVOR_HASH)
        with patch(MODULE+'.collect_v4_activity',return_value=dict(swaps=[])):
            for end in (140,180):
                self.runtime._increment(self.runtime.history.get(address(1)),end)
                self.assertFalse(self.runtime.history.get(address(1))['complete'])
        self.assertTrue(self.runtime.history.finish_recovery(address(1),block=180,block_hash=block_header(180)['hash']))
        self.assertTrue(self.runtime.history.get(address(1))['complete'])
        self.assertEqual(self.runtime.history.get(address(1))['position'],'native-controller')

    def test_orphaned_graduation_never_reauthorizes_history(self):
        row=self.runtime.history.graduate(address(1),graduation(1));row.update(block=140,position='native-controller')
        self.runtime.history.save(row)
        self.assertFalse(self.runtime.history.reset_after_reorg(address(1),canonical_graduation_hash='fork',anchor_price=1))
        row=self.runtime.history.get(address(1))
        self.assertEqual(row['position'],'native-controller');self.assertFalse(row['complete'])
        self.assertFalse(self.runtime.history.finish_recovery(address(1),block=140,block_hash='fork'))

    def test_graduation_discovery_fork_restarts_bounded_scan_without_losing_nominees(self):
        self.runtime.history.retain_graduations([observation(1)],99,block_hash='orphan')
        def batch(calls,scope):
            return [([] if m=='eth_getLogs' else block_header(int(p[0],16))) for m,p in calls]
        with patch(MODULE+'._latest_header',return_value=block_header(100)),patch.object(self.runtime.rpc,'batch',side_effect=batch):
            with self.assertRaisesRegex(BoundaryError,'survivor_discovery_reorg'):self.runtime.discover()
        self.assertIsNone(self.runtime.history.get_meta('discovery_block'))
        self.assertEqual(self.runtime.history.pending_graduations(),1)
        self.assertEqual(self.runtime.history.get_meta('discovery_reorgs'),1)

    def test_later_canonical_graduation_reactivates_orphan_without_native_reentry(self):
        identity=address(1);row=self.runtime.history.graduate(identity,graduation(1));row.update(block=140,position='native-controller')
        self.runtime.history.save(row);before=self.runtime.book.replay()
        self.runtime.history.reset_after_reorg(identity,canonical_graduation_hash='orphan',anchor_price=1)
        fresh=graduation(1,at=150,block=150)
        row=self.runtime.history.replace_orphaned_graduation(identity,fresh,anchor_price=100)
        self.assertEqual(row['graduation'],fresh);self.assertEqual(row['position'],'native-controller')
        self.assertEqual(row['block'],150);self.assertFalse(row['complete'])
        self.assertEqual(self.runtime.history.facts(identity,150)[0][0]['price'],'100')
        self.assertEqual(self.runtime.book.replay(),before)
        with self.assertRaisesRegex(ValueError,'replacement_authority'):
            self.runtime.history.replace_orphaned_graduation(identity,fresh,anchor_price=101)

    def test_dense_prices_preserve_frozen_vector_without_the_old_100000_point_veto(self):
        from meme_machine.runtime.journal import canonical,digest
        from meme_machine.lanes.pons.pons_postgrad_survivor import evaluate_entry
        identity=address(1);row=self.runtime.history.graduate(identity,graduation(1,at=0,block=0))
        row['block']=0;self.runtime.history.save(row)
        rows=[]
        for at in range(100001):
            p=str(10**18+at*10**13);bar=canonical(dict(price=p,low=p,high=p))
            rows.append((identity,at,bar,digest([identity,at,bar])))
        with self.runtime.history.transaction():self.runtime.history.db.executemany('INSERT INTO points VALUES(?,?,?,?)',rows)
        facts=dict(now=100000,graduation_at=0,lineage_proven=True,native_quote=True,
            price_points=[dict(at=r[1],price_index=int(json.loads(r[2])['price'])) for r in rows],
            flow_30m={},flow_previous_30m={},capital_quote=10**18,execution={})
        before=evaluate_entry(facts)
        self.runtime.history.append_block(identity,block=100000,header=block_header(100000),events=[],points=[])
        points,_=self.runtime.history.facts(identity,100000)
        after=evaluate_entry(dict(facts,price_points=[dict(at=p['at'],price_index=int(p['price'])) for p in points]))
        self.assertEqual(after,before)
        self.assertLessEqual(len(points),86403);self.assertEqual(points[0]['at'],0)
        self.assertIsNotNone(self.runtime.history.get_meta('pons_price_window:'+identity))

    def test_unfunded_position_controller_keeps_advancing_history_after_capital_denial(self):
        row=self.runtime.history.graduate(address(1),graduation(1))
        row.update(block=100,position='qualified-unfunded',decision=dict(candidate=True));self.runtime.history.save(row)
        with patch(MODULE+'._latest_header',return_value=block_header(220)), \
             patch(MODULE+'.collect_v4_activity',return_value=dict(swaps=[])), \
             patch.object(self.runtime,'_enter',side_effect=ValueError('survivor_minimum_capital')):
            for expected in (140,180,220):
                with self.assertRaisesRegex(ValueError,'minimum_capital'):
                    self.runtime._position(self.runtime.history.get(address(1)))
                self.assertEqual(self.runtime.history.get(address(1))['block'],expected)
        self.assertTrue(self.runtime.history.get(address(1))['decision']['candidate'])

    def test_current_outcomes_and_retirement_do_not_remove_later_survivor_eligibility(self):
        from tests.lanes.pons.test_pons_postgrad_survivor import facts
        candidate=address(1);self.runtime.history.graduate(candidate,graduation(1,at=NOW-30*3600))
        path=self.root/'current-plane.sqlite';clock=[NOW]
        broker=Broker(path,CURRENT_HASH,clock=lambda:clock[0],source=ENDPOINT)
        try:
            for block,reason in enumerate(('strategy_rejected','current_exited','sleeve_capital_exhausted','provider_http_429'),100):
                event=observation(1,block)
                event['transactionHash']='0x'+f'{block:064x}'
                broker.enqueue(event)
                scheduled=broker.pop();self.assertIsNotNone(scheduled);broker.failure(scheduled,reason)
                # Survivor sees only its own canonical history and market facts.
                decision=self.runtime.qualify(facts(continuity_complete=True))
                self.assertTrue(decision['candidate'],decision['all_rejections'])
                self.assertEqual(self.runtime.history.get(candidate)['graduation'],graduation(1,at=NOW-30*3600))
            broker.close();broker=Broker(path,CURRENT_HASH,clock=lambda:clock[0],source=ENDPOINT)
            clock[0]+=86401;broker.plane.maintain()
            self.assertIsNone(broker.plane.get(broker.identity(observation(1))))
            self.assertIsNotNone(self.runtime.history.get(candidate))
            self.assertTrue(self.runtime.qualify(facts(now=NOW+86401,continuity_complete=True,
                graduation_at=NOW-30*3600,price_points=[(at+86401,p) for at,p in winner_points()]))['candidate'])
        finally:broker.close()


class CapitalIndependenceTests(RuntimeCase):
    def seed_market(self):
        row=self.runtime.history.graduate(address(1),graduation(1,at=NOW-30*3600))
        row['block']=100;self.runtime.history.save(row)
        trades=[]
        for n in range(1,8):
            trades.append(dict(id=f'buy{n}',at=NOW-100,group=address(n+100),buy=True,quote=10**17//7,tokens=1,authenticated=True))
            if n<=4:trades.append(dict(id=f'old{n}',at=NOW-2000,group=address(n+100),buy=True,quote=6*10**16//4,tokens=1,authenticated=True))
        trades.append(dict(id='sell',at=NOW-90,group=address(200),buy=False,quote=5*10**16,tokens=1,authenticated=True))
        self.runtime.history.append(address(1),through=NOW,events=trades,points=winner_points(),complete=True)
        return dict(block=100,block_hash=block_header(100)['hash'],at=NOW,price_index=12900,acquired=time.monotonic())

    def test_current_and_survivor_vectors_are_identical_across_four_cash_states(self):
        from meme_machine.lanes.pons.pons_selective_cohort import _current_pons_realized_equity
        state=self.seed_market()
        quotes=SimpleNamespace(budget=5*10**16,loss=lambda n:200)
        results=[]
        # Cash is altered through the real sleeve reservation machinery. The
        # realized-equity base remains 1e18; no mark profit increases it.
        for label,amount in (('available',0),('zero_allocatable',10**18),('committed_elsewhere',10**18),('sleeve_exhausted',10**18)):
            if amount:self.runtime.sleeve.reserve(label,strategy='pons-selective-continuation-v1',amount=amount,at=NOW,asset=label)
            self.runtime.current=self.runtime.history.get(address(1))
            current=vector(strategy_capital_quote=_current_pons_realized_equity())
            survivor=self.runtime.qualify(self.runtime.reconstruct(state,quotes))
            results.append((current,survivor))
            if amount:self.runtime.sleeve.release(label,pnl=0,at=NOW,terminal_hash=label,native_verified=True,cancelled=True)
        self.assertTrue(results[0][0]['current_threshold_pass'])
        self.assertTrue(results[0][1]['candidate'],results[0][1]['all_rejections'])
        self.assertTrue(all(result==results[0] for result in results[1:]))

    def test_exact_native_quotes_qualify_turnover_capped_size_independent_of_funding_budget(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Quotes
        state=self.seed_market();self.runtime.current=self.runtime.history.get(address(1))
        rpc=ExactQuoteRPC();self.runtime.rpc=rpc;decisions=[]
        for budget in (5*10**16,0,10**15):
            context=Quotes(self.runtime,state,budget)
            before=len(rpc.transports)
            decision=self.runtime.qualify(self.runtime.reconstruct(state,context));decisions.append(decision)
            cap=self.runtime.facts['organic_flow']['turnover']//30
            self.assertTrue(decision['candidate'],decision['all_rejections'])
            self.assertEqual(self.runtime.facts['execution']['capacity']['final_size'],cap)
            self.assertLess(cap,5*10**16)
            self.assertEqual(len(rpc.transports)-before,3)
            count=len(rpc.transports);self.assertIsNotNone(context.loss(2*cap))
            self.assertEqual(len(rpc.transports),count)
            partial=10**15-17;self.assertIsNotNone(context.loss(partial))
            self.assertLessEqual(context.entry(partial)['cost'],partial)
            self.assertEqual(len(rpc.transports)-count,2)
        self.assertTrue(all(d==decisions[0] for d in decisions[1:]))


class ExactQuoteRPC(OfflineRPC):
    hash_state_supported={'eth_call','eth_getCode'}
    def __init__(self):self.transports=[];self.fork=False;self.evidence_pins={hex(100):'old_alias'}
    def value(self,method,params):
        from meme_machine.lanes.pons.abi import calldata
        if method=='eth_gasPrice':return '0x1'
        if method=='eth_getCode':return '0x6000'
        if method=='eth_getBlockByNumber':
            header=block_header(100 if params[0]=='latest' else int(params[0],16))
            return dict(header,hash='fork') if self.fork and params[0]!='latest' else header
        if method=='eth_call':
            if params[0]['data']==calldata('poolManager()'):
                return '0x'+load('uniswap_v4_manager')['address'][2:].zfill(64)
            raw=params[0]['data'][10:];words=[int(raw[n:n+64],16) for n in range(0,len(raw),64)]
            buy=bool(words[6]);amount=words[7]
            output=amount*100 if buy else amount//100*99//100
            return '0x'+f'{output:064x}'+f'{100000:064x}'
        raise AssertionError(method)
    def call(self,method,params,*,scope):
        self.transports.append(('call',[(method,params)]));return self.value(method,params)
    def batch(self,calls,*,scope):
        self.transports.append(('batch',calls));return [self.value(m,p) for m,p in calls]


class PinnedQuoteTests(unittest.TestCase):
    def test_v4_reads_share_two_transports_and_canonical_numeric_boundary_is_fresh(self):
        from meme_machine.lanes.pons.pons_quotes import PinnedV4Reads
        from meme_machine.lanes.pons.pons_natural_paper import V4_QUOTER,_v4_quoter_calldata
        from meme_machine.lanes.pons.abi import calldata
        key=PoolKey(ZERO,address(1),0,0,address(2));rpc=ExactQuoteRPC()
        reads=PinnedV4Reads(rpc,key,'sell',10**18);header=reads.call('eth_getBlockByNumber',['latest',False],scope='pons_natural')
        self.assertEqual(reads.call('eth_getCode',[V4_QUOTER,header['number']],scope='pons_paper'),'0x6000')
        manager=reads.call('eth_call',[dict(to=V4_QUOTER,data=calldata('poolManager()')),header['number']],scope='pons_paper')
        self.assertEqual(manager,'0x'+load('uniswap_v4_manager')['address'][2:].zfill(64))
        reads.call('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(key,False,10**18)),header['number']],scope='pons_paper')
        self.assertEqual(reads.call('eth_gasPrice',[],scope='pons_paper'),'0x1')
        self.assertEqual(len(rpc.transports),2)
        batch=rpc.transports[-1][1]
        self.assertTrue(all(p[-1]==dict(blockHash=header['hash'],requireCanonical=True) for m,p in batch if m in ('eth_call','eth_getCode')))
        self.assertEqual(batch[-1],('eth_getBlockByNumber',[hex(100),False]))
        self.assertEqual(rpc.evidence_pins,{hex(100):'old_alias'})

    def test_v4_reorg_during_quote_cannot_authorize_cached_exit_state(self):
        from meme_machine.lanes.pons.pons_quotes import PinnedV4Reads
        from meme_machine.lanes.pons.pons_natural_paper import V4_QUOTER
        rpc=ExactQuoteRPC();reads=PinnedV4Reads(rpc,PoolKey(ZERO,address(1),0,0,address(2)),'sell',10**18)
        h=reads.call('eth_getBlockByNumber',['latest',False],scope='pons_natural');rpc.fork=True
        with self.assertRaisesRegex(BoundaryError,'canonical_membership_disagreement'):
            reads.call('eth_getCode',[V4_QUOTER,h['number']],scope='pons_paper')
        self.assertIsNone(reads.cache)

    def test_stale_cached_loss_remains_an_operational_failure(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Quotes
        q=object.__new__(Quotes);q.state=dict(acquired=0.);q.cache={100:dict(loss_bps=1)};q.prepared={100};q.prepared_ladder=True
        with self.assertRaisesRegex(BoundaryError,'stale_quote'):q.loss(100)
        self.assertEqual(failure_category('survivor_exit_quote_stale'),'DEADLINE_MISSED')


class CurrentRecheckEvidenceTests(unittest.TestCase):
    def setUp(self):
        from meme_machine.lanes.pons import CHAIN_ID
        from meme_machine.lanes.pons.abi import calldata
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        from tests.lanes.pons.test_pons_selective_continuation import events,CREATOR
        self.acquisition=acquisition;self.head=197;self.records=[];self.fork=False
        self.raw=[]
        trades=events()+[dict(side='buy',group=address(25),quote=10**15,tokens=10**20,event_at=197)]
        for index,event in enumerate(trades):
            self.raw.append(dict(observation(index+1,event['event_at']),address=address(1),
                topics=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
                    '0x'+event['group'][2:].zfill(64),'0x'+event['group'][2:].zfill(64)],
                data='0x'+''.join(f'{n:064x}' for n in [event['quote'],event['tokens'],0,0])))
        test=self
        class RPC:
            used=0;counts=Counter();per_scope=200
            def telemetry(self):return dict(used=self.used)
            def batch(self,calls,scope):
                self.used+=len(calls);self.counts[scope]+=len(calls)
                return [self.call(m,p,scope) for m,p in calls]
            def call(self,m,p,scope):
                test.records.append((m,p,scope))
                if m=='eth_chainId':return hex(CHAIN_ID)
                if m=='eth_gasPrice':return '0x1'
                if m=='eth_getBlockByNumber':
                    n=test.head if p[0]=='latest' else int(p[0],16)
                    return dict(block_header(n),hash='fork') if test.fork and p[0]!='latest' and n==test.head else block_header(n)
                if m=='eth_getBlockByHash':return block_header(int(p[0],16))
                if m=='eth_getLogs':
                    q=p[0];return [r for r in reversed(test.raw) if int(q['fromBlock'],16)<=int(r['blockNumber'],16)<=int(q['toBlock'],16)]
                if m=='eth_getTransactionReceipt':
                    r=next(r for r in test.raw if r['transactionHash']==p[0])
                    return dict(transactionHash=r['transactionHash'],blockHash=r['blockHash'],
                        transactionIndex=r['transactionIndex'],gasUsed=hex(100000),status='0x1',logs=[r])
                if m in ('eth_call','eth_getCode'):
                    test.assertEqual(p[-1],hex(test.head),'every mutable fact must be at the actual current head')
                    if m=='eth_getCode':return '0x6000'
                    data=p[0]['data'];values={calldata('token()'):int(address(2),16),
                        calldata('realQuoteReserve()'):8*10**17,calldata('reservedTokens()'):100*10**24,
                        calldata('graduated()'):0,calldata('launchedAt()'):110}
                    if data==calldata('getReserves()'):return '0x'+f'{2*10**18:064x}'+f'{800*10**24:064x}'
                    if data.startswith(calldata('getLaunchedToken(address)',address(2))[:10]):return '0xdead'
                    if data.startswith(calldata('currentSnipeTaxBps(address)',address(2))[:10]):return '0x'+64*'0'
                    return '0x'+f'{values[data]:064x}'
                raise AssertionError(m)
        self.context=acquisition.SelectiveEvidenceContext(ENDPOINT);self.context.rpc=RPC()
        self.context.cache.remember_launch(address(1),110)
        module='meme_machine.lanes.pons.pons_natural_observation.'
        self.enterContext(patch(module+'authenticate_curve',return_value=dict(runtime_sha256='proved_runtime',
            immutables=dict(feeBps=100,creatorTaxBps=50))))
        self.enterContext(patch(module+'factory_record',return_value=dict(token=address(2),curve=address(1),
            pairToken=ZERO,deployer=CREATOR,creatorFeeRecipient=CREATOR,graduationThreshold=10**18,exists=True)))
        self.enterContext(patch.object(acquisition.time,'time',return_value=202.))
        self.enterContext(patch.object(acquisition.time,'monotonic',return_value=100.))

    def evaluate(self,event=None,refresh=True):
        from tests.lanes.pons.test_pons_selective_continuation import snapshots
        with patch.object(self.acquisition,'_trajectory',return_value=(snapshots(),110,{})):
            return self.acquisition.evaluate_candidate(ENDPOINT,event or self.raw[-1],[],
                strategy_capital_quote=10**18,evidence_context=self.context,canonical_refresh=refresh,
                evidence_observed_at=202.,evidence_observed_monotonic=100.)

    def test_age_gate_reopens_without_new_trade_using_real_receipt_decoder_and_current_state(self):
        with tempfile.TemporaryDirectory() as td:
            now=[197.];broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:now[0],source=ENDPOINT)
            try:
                broker.enqueue(self.raw[-1]);work=broker.pop();early=self.evaluate(refresh=False)
                self.assertEqual(early['vector']['all_rejections'],['token_age'])
                self.assertEqual(early['vector']['token_age_seconds'],87)
                self.assertTrue(broker.finish(work,early,.1));broker.acknowledge(work)
                now[0]=202.;self.head=200;self.records.clear()
                fresh=broker.pop();self.assertTrue(fresh['canonical_refresh'])
                row=self.evaluate(fresh['event'],fresh['canonical_refresh'])
                self.assertTrue(row['vector']['complete']);self.assertTrue(row['vector']['current_threshold_pass'],row['vector']['all_rejections'])
                self.assertEqual(row['vector']['token_age_seconds'],90)
                self.assertEqual(row['candidate']['nomination_block'],197)
                self.assertEqual(row['candidate']['receipt']['blockHash'],block_header(197)['hash'])
                self.assertEqual(row['candidate']['stamp'].block,200)
                self.assertEqual(row['candidate']['stamp'].event_at,200)
                self.assertEqual(row['candidate']['state'].timestamp,200)
                self.assertEqual(row['candidate']['original_nomination'],self.raw[-1])
                self.assertEqual(len(row['market_events']),len(self.raw))
                self.assertTrue(all(e['event_at']<=200 for e in row['market_events']))
                ranges=[p[0] for m,p,s in self.records if m=='eth_getLogs']
                self.assertEqual({n for q in ranges for n in range(int(q['fromBlock'],16),int(q['toBlock'],16)+1)},set(range(140,201)))
                self.assertEqual(sum(int(q['toBlock'],16)-int(q['fromBlock'],16)+1 for q in ranges),61,
                    'the complete range is acquired once and reused for authentication')
                public=self.acquisition.public_evaluation(row)
                self.assertTrue(public['canonical_refresh']);self.assertEqual(public['nomination_block'],197)
            finally:broker.close()

    def test_orphan_or_false_old_nominee_cannot_override_new_canonical_membership(self):
        self.head=200
        raw=dict(self.raw[-1],blockNumber=hex(3000),blockHash='orphan')
        self.context.cache.remember_receipt(raw['transactionHash'],'orphan',
            dict(transactionHash=raw['transactionHash'],blockHash='orphan'))
        row=self.evaluate(raw)
        self.assertTrue(row['vector']['current_threshold_pass'],row['vector']['all_rejections'])
        self.assertEqual(row['candidate']['original_nomination'],raw)
        self.assertEqual(row['source_transaction'],self.raw[-1]['transactionHash'])
        self.assertEqual(row['candidate']['receipt']['blockHash'],block_header(197)['hash'])

    def test_fork_and_missing_buy_fail_closed_without_economic_rejection(self):
        self.head=203
        with self.assertRaisesRegex(BoundaryError,'future_current_head'):self.evaluate()
        self.head=200;self.fork=True
        with self.assertRaisesRegex(BoundaryError,'canonical_membership_disagreement'):self.evaluate()
        self.fork=False;event=self.raw[-1];self.raw=[]
        with self.assertRaisesRegex(BoundaryError,'no_recent_canonical_buy'):self.evaluate(event)
        self.assertEqual(failure_category('pons_current_recheck_no_recent_canonical_buy'),'INCOMPLETE_EVIDENCE')

    def test_only_authenticated_chain_age_expires_watch_without_affecting_survivor(self):
        from meme_machine.runtime.robinhood.pons import durable_cache
        with tempfile.TemporaryDirectory() as td:
            now=[197.];path=Path(td)/'plane.sqlite';broker=Broker(path,CURRENT_HASH,clock=lambda:now[0],source=ENDPOINT)
            history=PonsHistory(Path(td)/'history.sqlite',policy=SURVIVOR_HASH)
            try:
                history.graduate(address(1),graduation(1));broker.enqueue(self.raw[-1]);work=broker.pop()
                broker.failure(work,'provider_http_429');now[0]=202.;timer=broker.pop()
                cache=durable_cache(broker.plane,'recheck_authority');self.context.cache=cache
                cache.remember_compiled(address(1),address(2),'0x6000',197,block_header(197),dict(runtime_sha256='proved_runtime'))
                cache.remember_launch(address(1),110);self.head=1011
                with patch.object(self.acquisition.time,'time',return_value=1013.),self.assertRaisesRegex(BoundaryError,'strategy_horizon_expired'):
                    self.evaluate(timer['event'])
                proof=self.context.boundary_evidence
                self.assertEqual((proof['launch_at'],proof['asof']),(110,1011))
                broker.failure(timer,'strategy_horizon_expired',evidence=proof)
                self.assertEqual(broker.plane.db.execute('SELECT COUNT(*) FROM pons_current_watch').fetchone()[0],0)
                broker.close();broker=Broker(path,CURRENT_HASH,clock=lambda:now[0],source=ENDPOINT)
                self.assertIsNone(broker.pop());self.assertIsNotNone(history.get(address(1)))
            finally:broker.close();history.close()


class WindowContext:
    def __init__(self,events):self.cache=ImmutableEvidenceCache();self.events=events;self.calls=[];self.windows=[]
    def header(self,n):return block_header(n)
    def call(self,m,p,scope):self.calls.append((m,p));return self.header(int(p[0],16))
    def batch(self,calls,scope):
        self.windows.extend(calls)
        return [[e for e in reversed(self.events) if int(p[0]['fromBlock'],16)<=int(e['blockNumber'],16)<=int(p[0]['toBlock'],16)] for _,p in calls]


class CanonicalWindowTests(unittest.TestCase):
    def candidate(self):return dict(curve=address(1),block=200,stamp=SimpleNamespace(event_at=200),header=block_header(200))
    def event(self,n,at):return dict(observation(n,at),address=address(1),topics=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')])
    def test_every_canonical_trade_is_returned_even_when_public_tape_omits_it(self):
        events=[self.event(1,150),self.event(2,160),self.event(3,200)]
        context=WindowContext(events);returned=canonical_window(context,self.candidate())
        self.assertEqual(returned,events)
        self.assertTrue(context.window_coverage['complete'])
        self.assertEqual(context.window_coverage['authority'],'canonical_alchemy_getLogs')
        ranges=[p[0] for m,p in context.windows]
        self.assertEqual((int(ranges[0]['fromBlock'],16),int(ranges[-1]['toBlock'],16)),(140,200))
        self.assertTrue(all(int(r['toBlock'],16)-int(r['fromBlock'],16)<10 for r in ranges))
        self.assertEqual(set(range(140,201)),{n for r in ranges for n in range(int(r['fromBlock'],16),int(r['toBlock'],16)+1)})

    def test_same_second_lower_boundary_and_header_reuse(self):
        context=WindowContext([self.event(1,140),self.event(2,141),self.event(3,142)])
        context.header=lambda n:dict(block_header(n),timestamp=hex(140 if 140<=n<=142 else n-2 if n>142 else n))
        candidate=self.candidate();candidate['stamp']=SimpleNamespace(event_at=198);candidate['header']=context.header(200)
        candidate['stamp']=SimpleNamespace(event_at=200);candidate['header']=block_header(200)
        # Target 140 contains three consecutive blocks; the first is included.
        first=canonical_window(context,candidate);calls=len(context.calls)
        self.assertEqual(len(first),3)
        canonical_window(context,candidate);self.assertEqual(len(context.calls),calls)

    def test_missing_page_and_conflicting_member_fail_closed(self):
        for kind in ('missing','conflict','removed','future'):
            with self.subTest(kind=kind):
                event=self.event(1,160);ctx=WindowContext([event]);real=ctx.batch
                def batch(calls,scope):
                    rows=real(calls,scope)
                    if kind=='missing':return rows[:-1]
                    index=next(i for i,r in enumerate(rows) if r)
                    if kind=='conflict':rows[index].append(dict(event,data='conflict'))
                    if kind=='removed':rows[index][0]=dict(event,removed=True)
                    if kind=='future':rows[index][0]=dict(event,blockNumber='0xc9')
                    return rows
                ctx.batch=batch
                with self.assertRaises(BoundaryError):canonical_window(ctx,self.candidate())
                self.assertFalse(getattr(ctx,'window_coverage',{}).get('complete',False))

    def test_real_receipt_decoder_sees_creator_sale_omitted_from_public_nomination(self):
        from collections import defaultdict
        from meme_machine.lanes.pons import pons_selective_acquisition as acquisition
        from tests.lanes.pons.test_pons_selective_continuation import events,state,snapshots,CREATOR
        raw=[]
        for index,event in enumerate(events()+[dict(side='buy',group=address(25),quote=10**15,tokens=10**20,event_at=200),
                dict(side='sell',group=CREATOR,quote=1,tokens=1,event_at=200)]):
            signature=topic('Curve'+('Buy' if event['side']=='buy' else 'Sell')+'(address,address,uint256,uint256,uint256,uint256)')
            amounts=([event['quote'],event['tokens']] if event['side']=='buy' else [event['tokens'],event['quote']])+[0,0]
            raw.append(dict(address=address(1),blockNumber=hex(event['event_at']),blockHash=block_header(event['event_at'])['hash'],
                transactionHash='0x'+f'{index+1:064x}',transactionIndex=hex(index),logIndex='0x0',
                topics=[signature,'0x'+event['group'][2:].zfill(64),'0x'+event['group'][2:].zfill(64)],
                data='0x'+''.join(f'{n:064x}' for n in amounts)))
        receipts={r['transactionHash']:dict(transactionHash=r['transactionHash'],blockHash=r['blockHash'],
            transactionIndex=r['transactionIndex'],status='0x1',logs=[r]) for r in raw}
        class RPC(OfflineRPC):
            counts=defaultdict(int);per_scope=200
            def telemetry(self):return {}
            def call(self,method,params,scope):
                if method=='eth_getLogs':
                    q=params[0];return [r for r in raw if int(q['fromBlock'],16)<=int(r['blockNumber'],16)<=int(q['toBlock'],16)]
                if method=='eth_getTransactionReceipt':return receipts[params[0]]
                if method=='eth_getBlockByHash':return block_header(int(params[0],16))
                return super().call(method,params,scope)
        context=acquisition.SelectiveEvidenceContext(ENDPOINT);context.rpc=RPC()
        candidate=dict(token=address(2),curve=address(1),block=200,stamp=SimpleNamespace(event_at=200),
            header=block_header(200),receipt=receipts[raw[-2]['transactionHash']],state=state(),
            record=dict(pairToken=ZERO,graduationThreshold=10**18,deployer=CREATOR,creatorFeeRecipient=CREATOR),
            current_snipe_bps=0,roundtrip_gas_wei=10**10,decoded_event={'decoded':{'name':'CurveBuy'}})
        with patch.object(acquisition,'_authenticate_candidate',return_value=candidate), \
             patch.object(acquisition,'_trajectory',return_value=(snapshots(),50,{})), \
             patch.object(acquisition.time,'time',return_value=202):
            result=acquisition.evaluate_candidate(ENDPOINT,raw[-2],raw[:-1],strategy_capital_quote=10**18,evidence_context=context)
        self.assertTrue(result['vector']['complete'])
        self.assertIn('creator_distribution',result['vector']['all_rejections'])
        self.assertEqual(len(result['market_events']),len(raw))
        self.assertTrue(result['window_coverage']['complete'])


class DispositionTests(unittest.TestCase):
    def test_current_active_position_blocks_execution_after_durable_qualification_with_explicit_reason(self):
        from tests.lanes.pons.test_pons_continuous_campaign import ContinuousCampaignTests
        ContinuousCampaignTests()._campaign_probe(blocked=True)

    def test_operational_failures_are_explicit_and_do_not_become_strategy_rejections(self):
        examples={'provider_http_429':'PROVIDER_UNAVAILABLE','provider_shared_queue_capacity':'PROVIDER_UNAVAILABLE',
            'selective_window_event_capacity':'INCOMPLETE_EVIDENCE','survivor_history_reorg':'INCOMPLETE_EVIDENCE',
            'trajectory_history':'INCOMPLETE_EVIDENCE','survivor_monitoring_not_caught_up':'INCOMPLETE_EVIDENCE',
            'provider_evidence_deadline_before_transport':'DEADLINE_MISSED',
            'candidate_generation_superseded':'SUPERSEDED_STATE','survivor_executable_size_missing':'EXECUTION_CAPACITY_UNAVAILABLE',
            'survivor_graduation_expired':'EXPIRED_BY_STRATEGY_HORIZON','non_native_quote':'STRUCTURAL_INELIGIBLE'}
        for reason,category in examples.items():self.assertEqual(failure_category(reason),category)
        self.assertEqual(failure_category('sleeve_capital_exhausted',qualified=True),'QUALIFIED_BUT_CAPITAL_UNAVAILABLE')
        self.assertEqual(decision_category(dict(vector=dict(complete=False,trajectory_screen_only=True,all_rejections=['trajectory_history']))),'INCOMPLETE_EVIDENCE')
        self.assertEqual(decision_category(dict(vector=dict(complete=False,token_age_seconds=901,all_rejections=['token_age']))),'EXPIRED_BY_STRATEGY_HORIZON')
        self.assertEqual(decision_category(dict(vector=dict(complete=False,token_age_seconds=89,prospect_screen_only=True,all_rejections=['token_age']))),'STRATEGY_REJECT')
        self.assertEqual(decision_category(dict(vector=dict(complete=True,candidate=False,all_rejections=['buyer_concentration']))),'STRATEGY_REJECT')
        self.assertEqual(decision_category(dict(complete=False,current_threshold_pass=False,
            all_rejections=['position_size_zero','roundtrip_cost_unavailable'],
            proposed_size=dict(execution_capacity=dict(final_size=0,binding_reason='ordinary_execution',evaluated_sizes=[100,50,1])))),
            'EXECUTION_CAPACITY_UNAVAILABLE')

    def test_durable_qualification_precedes_funding_and_duplicate_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'plane.sqlite';plane=Plane(path);attempts=Attempts(plane)
            attempts.record('candidate',1,'qualification','QUALIFIED',at=100,decision=vector())
            plane.close();plane=Plane(path);attempts=Attempts(plane)
            denial=dict(at=101,reason='sleeve_capital_exhausted')
            for _ in range(2):attempts.record('candidate',1,'funding','QUALIFIED_BUT_CAPITAL_UNAVAILABLE',**denial)
            rows=attempts.rows('candidate');self.assertEqual(len(rows),2)
            self.assertEqual([r['phase'] for r in rows],['qualification','funding'])
            self.assertTrue(rows[0]['decision']['current_threshold_pass']);plane.close()


class PositionAdmissionTests(unittest.TestCase):
    def test_full_candidate_queue_cannot_refuse_an_imminent_position(self):
        with tempfile.TemporaryDirectory() as td:
            admission=Admission(str(Path(td)/'provider.sqlite'),ENDPOINT,lane='pons',clock=lambda:100.,sleeper=lambda s:None)
            db=admission.connect()
            for n in range(256):
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(str(n),admission.endpoint,30,99.,130.))
                db.execute('INSERT INTO queue_meta VALUES(?,?)',(str(n),'pons'))
            db.close()
            with self.assertRaisesRegex(BoundaryError,'provider_shared_queue_capacity'):admission.acquire('pons_candidate',deadline=101.)
            @position_work
            def acquire():return admission.acquire('pons_candidate',deadline=100.4)
            result=acquire();self.assertEqual(result['queue_depth'],257);self.assertEqual(result['wait_seconds'],0.)
            db=admission.connect()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0],256)
            self.assertEqual(db.execute('SELECT interval,next_at FROM limits').fetchone(),(.5,100.5));db.close()


class CurrentHistoryTests(unittest.TestCase):
    def event(self,n,at):return dict(identity=f'trade{n}',event_at=at,side='buy',quote=10,tokens=10,group=address(n),actor=address(n),recipient=address(n))

    def test_normal_windows_accumulate_exact_900_second_history_and_restart(self):
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'plane.sqlite';plane=Plane(path);history=CurrentHistory(plane,ENDPOINT)
            history.remember(address(1),block_header(100),[self.event(1,100)],from_time=40)
            for at in range(130,971,30):
                old=history.get(address(1))
                history.remember(address(1),block_header(at),[self.event(at,at)],from_time=old['through'],delta_from=old['block'])
            self.assertEqual(len(history.facts(address(1),block_header(970),900)),30)
            plane.close();plane=Plane(path);history=CurrentHistory(plane,ENDPOINT)
            self.assertEqual(len(history.facts(address(1),block_header(970),900)),30)
            with self.assertRaisesRegex(BoundaryError,'not_caught_up'):history.facts(address(1),block_header(971),900)
            # Future events cannot contaminate this historical point in time.
            with self.assertRaisesRegex(BoundaryError,'future_event'):
                history.remember(address(1),block_header(980),[self.event(980,981)],from_time=970,delta_from=970)
            self.assertEqual(history.get(address(1))['block'],970);plane.close()

    def test_promotion_consumes_only_delta_and_gap_restarts_short_safety_window(self):
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory,_active
        from meme_machine.lanes.pons import pons_selective_paper as paper
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');history=CurrentHistory(plane,ENDPOINT)
            history.remember(address(1),block_header(1000),[self.event(1,900)],from_time=100)
            token=_active.set(history)
            try:
                with patch.object(paper,'_read_curve_logs',return_value=([self.event(2,1010)],[])) as read:
                    events,_=paper._curve_logs(ENDPOINT,address(1),block_header(1010),900)
                    self.assertEqual(read.call_args.kwargs,{'after_block':1000,'expected_previous_hash':block_header(1000)['hash']})
                    self.assertEqual(len(events),2)
                with patch.object(paper,'_read_curve_logs',return_value=([self.event(3,1400)],[])) as read:
                    with self.assertRaisesRegex(BoundaryError,'not_caught_up'):
                        paper._curve_logs(ENDPOINT,address(1),block_header(1400),900)
                    self.assertEqual(read.call_args.args[-1],60)
                    read.assert_called_once()
                with patch.object(paper,'_read_curve_logs',side_effect=AssertionError('same block needs no old history RPC')):
                    self.assertEqual(len(paper._curve_logs(ENDPOINT,address(1),block_header(1400),60)[0]),1)
            finally:_active.reset(token);plane.close()

    def test_out_of_order_candidate_does_not_rewind_position_or_leak_future_window(self):
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');history=CurrentHistory(plane,ENDPOINT)
            history.remember(address(1),block_header(200),[self.event(1,195)],from_time=140)
            history.remember(address(1),block_header(190),[self.event(2,180)],from_time=130)
            self.assertEqual(history.get(address(1))['block'],200)
            with self.assertRaisesRegex(BoundaryError,'not_caught_up'):history.facts(address(1),block_header(190),60)
            with self.assertRaisesRegex(BoundaryError,'reorg'):
                history.remember(address(1),dict(block_header(200),hash='fork'),[],from_time=140)
            plane.close()

    def test_busy_authenticated_window_is_not_a_population_veto(self):
        from meme_machine.lanes.pons.pons_selective_continuation import demand_metrics
        rows=[dict(self.event(n,195),quote=10**15) for n in range(1,POPULATION+1)]
        demand=demand_metrics(rows,asof=200)
        self.assertEqual(demand['independent_groups'],POPULATION)
        self.assertEqual(demand['current_buy_quote'],10**15*POPULATION)
        self.assertTrue(vector(events=rows)['current_threshold_pass'])

    def test_later_fork_discards_old_prefix_and_defers_add_until_history_accumulates(self):
        from meme_machine.lanes.pons.pons_current_history import CurrentHistory,_active
        from meme_machine.lanes.pons import pons_selective_paper as paper
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');history=CurrentHistory(plane,ENDPOINT)
            history.remember(address(1),block_header(1000),[self.event(1,900)],from_time=100)
            token=_active.set(history)
            try:
                with patch.object(paper,'_read_curve_logs',side_effect=[BoundaryError('pons_current_history_reorg'),([self.event(2,1010)],[])]) as read:
                    with self.assertRaisesRegex(BoundaryError,'not_caught_up'):
                        paper._curve_logs(ENDPOINT,address(1),block_header(1010),900)
                self.assertEqual(read.call_count,2)
                self.assertEqual(history.facts(address(1),block_header(1010),60),[self.event(2,1010)])
                self.assertEqual(history.get(address(1))['from_time'],950)
                plane.close();plane=Plane(Path(td)/'plane.sqlite');history=CurrentHistory(plane,ENDPOINT)
                self.assertEqual(history.get(address(1))['from_time'],950)
                with self.assertRaisesRegex(BoundaryError,'not_caught_up'):history.facts(address(1),block_header(1010),900)
            finally:_active.reset(token);plane.close()

    def test_delta_checks_numeric_canonical_boundary_before_using_immutable_old_hash(self):
        from meme_machine.lanes.pons import pons_selective_paper as paper
        calls=[]
        def batch(endpoint,requests,scope,**kwargs):
            calls.extend(requests)
            return [dict(block_header(1000),hash='fork')]+[[]]*(len(requests)-1),[]
        with patch.object(paper,'_batched',side_effect=batch):
            with self.assertRaisesRegex(BoundaryError,'reorg'):
                paper._read_curve_logs(ENDPOINT,address(1),block_header(1010),900,
                    after_block=1000,expected_previous_hash=block_header(1000)['hash'])
        self.assertEqual(calls[0],('eth_getBlockByNumber',['0x3e8',False]))


class CanonicalCacheTests(unittest.TestCase):
    def test_cache_hit_does_not_replace_current_canonical_membership(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        context=SelectiveEvidenceContext(ENDPOINT);context.cache.remember_header(block_header(100))
        context.pin=(100,block_header(100)['hash']);context.live_membership=True
        class RPC(OfflineRPC):
            counts=Counter();per_scope=200
            def batch(self,calls,scope):
                self.calls=calls
                return [dict(block_header(100),hash='fork') for _ in calls]
        rpc=RPC();context.rpc=rpc
        with self.assertRaisesRegex(BoundaryError,'canonical_membership_disagreement'):
            context.batch([('eth_getBlockByNumber',[hex(100),False])],'pons_natural')
        self.assertEqual(len(rpc.calls),1);self.assertIsNone(context.cache.header_by_number(100))

    def test_durable_fork_aliases_are_invalidated_but_hash_bodies_are_reusable(self):
        from meme_machine.runtime.robinhood.pons import durable_cache
        from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
        from meme_machine.lanes.pons.abi import calldata
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');cache=durable_cache(plane,'offline-domain')
            old=block_header(100);cache.remember_header(old);cache.remember_launch(address(1),50)
            cache.remember_compiled(address(1),address(2),'0xOLD',100,old,dict(runtime_sha256='compiled'))
            plane.close();plane=Plane(Path(td)/'plane.sqlite');cache=durable_cache(plane,'offline-domain')
            context=SelectiveEvidenceContext(ENDPOINT,cache=cache);context.pin=(200,block_header(200)['hash'])
            context.live_membership=True;context.deadline=12345.;calls=[]
            class RPC(OfflineRPC):
                counts=Counter();per_scope=200
                def call(self,method,params,scope):
                    if method=='eth_getCode':return '0xNEW'
                    h=super().call(method,params,scope)
                    return dict(h,hash='fork') if params[0]==hex(100) else h
                def batch(self,requests,scope):
                    calls.append(requests);return super().batch(requests,scope)
            context.rpc=RPC()
            values=context.batch([('eth_getBlockByNumber',[hex(200),False]),('eth_getCode',[address(1),hex(200)])],'pons_natural')
            self.assertEqual(values,[block_header(200),'0xNEW']);self.assertEqual(len(calls),2)
            self.assertEqual(context.deadline,12345.);self.assertIsNone(cache.launch(address(1)))
            self.assertIsNone(cache.immutable_curve(address(1),200));self.assertEqual(cache.header_by_hash(old['hash']),old)
            self.assertEqual(cache.header_by_number(100)['hash'],'fork');plane.close()
class AdditionalRecoveryTests(unittest.TestCase):
    def test_observation_failure_services_existing_positions_and_keeps_restart_cursor(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        order=[];rpc=SimpleNamespace()
        feed=SimpleNamespace(connect=lambda:order.append('sequencer'),
            wait_for_after=lambda *a,**k:200,state=SimpleNamespace(latest_header_timestamp=200),
            close=lambda:order.append('observation_close'))
        def discovery(endpoint):
            order.append('public_discovery')
            if order.count('public_discovery')==1:raise BoundaryError('provider_http_429')
            return rpc
        def maintenance(reason):
            self.assertEqual(reason,'provider_http_429');order.append('existing_position');return True
        with patch.object(cohort,'_discovery',side_effect=discovery),patch.object(cohort,'_stop_sleep'):
            result=cohort._start_observation(ENDPOINT,feed,saved=dict(cursor=100),maintenance=maintenance)
        self.assertEqual(result,(rpc,100,200))
        self.assertEqual(order,['public_discovery','existing_position','observation_close','public_discovery','sequencer'])

    def test_invalid_discovery_recovery_cursor_never_starts_at_new_head(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        feed=SimpleNamespace(connect=lambda:None,wait_for_after=lambda *a,**k:200,
            state=SimpleNamespace(latest_header_timestamp=200))
        with patch.object(cohort,'_discovery',return_value=SimpleNamespace()):
            for saved in (dict(cursor=201),dict(cursor=None)):
                with self.assertRaisesRegex(BoundaryError,'recovery_watermark'):
                    cohort._start_observation(ENDPOINT,feed,saved=saved)

    def test_process_death_after_atomic_history_commit_retains_exact_watermark(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite'
            program='''import os,sys
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
h=PonsHistory(sys.argv[1],policy=POLICY_HASH)
r=h.graduate('candidate',dict(at=100));r['block']=100;h.save(r)
h.append_block('candidate',block=140,header=dict(number='0x8c',hash='h140',timestamp='0x8c'),events=[dict(id='swap',at=139,authenticated=True)],points=[(139,'123')])
os._exit(23)
'''
            child=subprocess.run([sys.executable,'-c',program,str(path)],capture_output=True,timeout=10)
            self.assertEqual(child.returncode,23,child.stderr.decode())
            history=PonsHistory(path,policy=SURVIVOR_HASH)
            self.assertEqual((history.get('candidate')['block'],history.get('candidate')['through']),(140,140))
            points,events=history.facts('candidate',140)
            self.assertEqual(points[0]['price'],'123');self.assertEqual(events[0]['id'],'swap');history.close()

    def test_attempt_retirement_uses_horizon_and_preserves_pending_and_qualified_unfunded(self):
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite',clock=lambda:0.);attempts=Attempts(plane)
            for candidate in ('expired','pending','qualified','open'):
                attempts.record(candidate,1,'qualification','QUALIFIED',at=100,decision=vector())
            plane.observe('pending','pons','tx',{},ordering=(1,),watermark={},interpretation={},observed=100,deadline=None,priority=4)
            now=100+7*86400+1
            self.assertEqual(attempts.maintain(now,protected=('qualified','open')),1)
            self.assertEqual({r['candidate'] for r in attempts.rows()},{'pending','qualified','open'})
            self.assertEqual(plane.checkpoint_read('pons_attempts_expired')['count'],1)
            with self.assertRaises(Exception):plane.db.execute('DELETE FROM pons_attempts')
            plane.close()

    def test_native_right_tail_bridge_and_one_add_survive_restart_without_rebasing(self):
        from tests.test_pons_ongoing_scale import ScaleIntegrationTests
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.evidence import Store
        fixture=ScaleIntegrationTests();fixture.setUp()
        try:
            fixture.state.bridged=True;fixture.state.bridged_at=1000;fixture.state.bridge_deadline=101+36*3600
            added=fixture.attempt();self.assertIsNotNone(added)
            original=dict(opened_at=101,high_water=10000,first_tail_crossed_at=102,
                partial_taken=True,bridged=True,bridged_at=1000,bridge_deadline=101+36*3600,scale_committed=True)
            path=Path(fixture.temp.name)/'native.sqlite';fixture.store.close()
            fixture.store=Store(path);fixture.addCleanup(fixture.store.close)
            fixture.paper=SelectivePaper(fixture.store,STRATEGY_NAMESPACE,100000,delay=1,natural_policy_hash=CURRENT_HASH)
            restored=LifecycleState.restore(fixture.paper,fixture.identity)
            for key,value in original.items():self.assertEqual(getattr(restored,key),value)
            position=fixture.paper._get(fixture.identity)
            self.assertEqual(position['id'],fixture.identity)
            self.assertEqual(position['original_basis'],fixture.before['original_basis'])
            self.assertEqual(position['original_quantity'],fixture.before['original_quantity'])
            fixture.state=restored;fixture.paper.controller_context=restored.checkpoint
            self.assertIsNone(fixture.attempt());self.assertEqual(fixture.paper._get(fixture.identity)['version'],position['version'])
            self.assertTrue(fixture.paper.accounting(fixture.identity)['replay_verified'])
        finally:
            fixture.sleeve.close();fixture.doCleanups()


class TailMechanicsTests(unittest.TestCase):
    def test_peak_profit_floor_preserves_controlled_2x_to_50x_winner_conversion(self):
        from decimal import Decimal
        from meme_machine.lanes.pons.pons_selective_continuation import runner_action
        outputs={}
        for multiple in (2,5,10,25,50):
            high=(multiple-1)*10000;floor=high*6000//10000
            common=dict(tokens=7500,partial_taken=True,high_water_return_bps=high,
                seconds_since_high=0,new_buyer_growth=True,buy_quote=2,sell_quote=1)
            self.assertEqual(runner_action(after_cost_return_bps=floor+1,**common)['action'],'hold')
            self.assertEqual(runner_action(after_cost_return_bps=floor,**common)['action'],'full_exit')
            # Controlled frictionless paths, explicitly not historical performance.
            proceeds=Decimal('.25')*Decimal('1.18')+Decimal('.75')*(1+Decimal(floor)/10000)
            outputs[multiple]=(proceeds-1)*Decimal('.05')
        self.assertEqual(outputs,{2:Decimal('.02475'),5:Decimal('.09225'),10:Decimal('.20475'),25:Decimal('.54225'),50:Decimal('1.10475')})

    def test_pre_2x_trail_can_end_exposure_before_later_underlying_winner(self):
        from meme_machine.lanes.pons.pons_selective_continuation import runner_action
        action=runner_action(tokens=7500,partial_taken=True,after_cost_return_bps=4000,
            high_water_return_bps=6000,seconds_since_high=0,new_buyer_growth=True,buy_quote=2,sell_quote=1)
        self.assertEqual(action['action'],'full_exit');self.assertEqual(action['reason'],'runner_trailing_stop')
