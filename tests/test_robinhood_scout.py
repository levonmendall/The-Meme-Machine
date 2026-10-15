"""Production scout/cohort/Survivor paths on deterministic offline event tapes."""
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engineering.pons_history.fixtures import Tape, encoded_event
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.pons_historical import FACTORY, LAUNCH, GRADUATION, MANAGER, SWAP, FORWARD_PLAN
from meme_machine.lanes.pons.pons_natural_observation import MarketScout
from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_HASH
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY, evaluate_entry
from meme_machine.lanes.pons import pons_selective_cohort as cohort
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.runtime.robinhood.plane import Plane


class DiscoveryNominationTests(unittest.TestCase):
    """Actual scout/broker/projector paths; no provider or capacity claim."""
    def fixture(self,root,*,count=32):
        from meme_machine.lanes.pons.pipeline import Pipeline
        tape=ObservationTape();tape.top=tape.grad+3
        clock=[float(int(tape.header(tape.top)['timestamp'],16))]
        broker=Broker(root/'plane.sqlite',CURRENT_HASH,clock=lambda:clock[0],source='offline-scout')
        scout=MarketScout(broker.plane)
        tape.logs=[dict(address='0x'+f'{i%4+100:040x}',
            topics=[scout.curve_topics[i%2]],data='0x',blockNumber=hex(tape.grad+i%4),
            blockHash=tape.header(tape.grad+i%4)['hash'],transactionHash='0x'+f'{i+100:064x}',
            transactionIndex=hex(i),logIndex=hex(i)) for i in range(count)]
        pipeline=Pipeline(root/'pipeline.sqlite','pons',CURRENT_HASH)
        return tape,clock,broker,scout,pipeline

    def poll(self,tape,scout,*,after=None):
        def run(*args,nominate=None,**kwargs):
            rows=scout.read_market(tape,tape.grad,tape.top,nominate=nominate)
            if after:after(rows)
            return tape,tape.top,rows
        return run

    @staticmethod
    def durable(broker,pipeline):
        db=broker.plane.db
        return dict(candidates=[tuple(r) for r in db.execute('SELECT * FROM candidates ORDER BY id')],
            watches=[tuple(r) for r in db.execute('SELECT * FROM pons_current_watch ORDER BY candidate')],
            observations=[tuple(r) for r in db.execute('SELECT * FROM observations ORDER BY candidate,observation')],
            transitions=[tuple(r) for r in db.execute('SELECT * FROM transitions ORDER BY seq')],
            progress=[tuple(r) for r in pipeline.db.execute('SELECT candidate,stage,reason,classification,details FROM progress ORDER BY sequence')])

    def test_page_nomination_is_once_and_original_clock_survives_delayed_return(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            tape,clock,broker,scout,pipeline=self.fixture(Path(td))
            self.addCleanup(broker.close);self.addCleanup(pipeline.close)
            original=clock[0]
            def delayed(_rows):clock[0]+=100
            with patch.object(cohort,'_poll',side_effect=self.poll(tape,scout,after=delayed)), \
                    patch.object(broker,'enqueue',wraps=broker.enqueue) as enqueue:
                _,_,rows=cohort._collect_observations(queue=broker,scout=scout)
            self.assertEqual(enqueue.call_count,len(rows))
            self.assertEqual(broker.plane.db.execute("SELECT received FROM observation_counts WHERE lane='pons'").fetchone()[0],len(rows))
            for row in broker.plane.db.execute('SELECT observed,deadline FROM candidates'):
                self.assertEqual(tuple(row),(original,original+5))
            for body, in broker.plane.db.execute('SELECT body FROM pons_current_watch'):
                self.assertEqual(json.loads(body)['last_buy_observed_at'],original)
            self.assertEqual(len(scout.events('curve')),len(rows))

    def test_returned_old_cohort_cannot_overwrite_newer_or_claimed_generation(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            tape,clock,broker,scout,pipeline=self.fixture(Path(td),count=1)
            self.addCleanup(broker.close);self.addCleanup(pipeline.close)
            latest=[];claimed=[]
            def concurrent(rows):
                newer=dict(rows[0],blockNumber=hex(tape.top+1),transactionHash='0x'+'ff'*32)
                clock[0]+=.1;broker.enqueue(newer,now=clock[0],needs_work=True)
                work=broker.plane.claim(lane='pons',interpretation=broker.policy,estimate_seconds=0)
                self.assertIsNotNone(work);claimed.append(work);latest.append(broker.plane.get(work['id']))
            with patch.object(cohort,'_poll',side_effect=self.poll(tape,scout,after=concurrent)):
                _,_,rows=cohort._collect_observations(queue=broker,scout=scout)
            broker.report_to(pipeline,drain=True)
            self.assertEqual(broker.plane.get(claimed[0]['id']),latest[0])
            self.assertTrue(broker.plane.current(claimed[0]))
            self.assertEqual(len(scout.events('curve')),len(rows))
            broker.close();broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:clock[0],source='offline-scout')
            self.addCleanup(broker.close)
            self.assertEqual(broker.plane.get(claimed[0]['id']),latest[0])

    def test_standalone_discovery_still_enqueues_every_event_once(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            tape,clock,broker,scout,pipeline=self.fixture(Path(td),count=4)
            self.addCleanup(broker.close);self.addCleanup(pipeline.close)
            rows=list(tape.logs)
            with patch.object(cohort,'_poll',return_value=(tape,tape.top,rows)), \
                    patch.object(cohort.time,'time',return_value=clock[0]), \
                    patch.object(broker,'enqueue',wraps=broker.enqueue) as enqueue:
                self.assertEqual(cohort._collect_observations(queue=broker),(tape,tape.top,rows))
            self.assertEqual(enqueue.call_count,4)
            self.assertEqual(len(broker.plane.db.execute('SELECT * FROM observations').fetchall()),4)

    def test_failure_after_page_receipt_preserves_pending_nomination_and_original_error(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            tape,clock,broker,scout,pipeline=self.fixture(Path(td),count=1)
            self.addCleanup(broker.close);self.addCleanup(pipeline.close)
            failure=BoundaryError('provider_transport_failure')
            def failed(*args,**kwargs):
                self.poll(tape,scout)(*args,**kwargs)
                raise failure
            with patch.object(cohort,'_poll',side_effect=failed):
                with self.assertRaises(BoundaryError) as raised:
                    cohort._collect_observations(queue=broker,scout=scout)
            self.assertIs(raised.exception,failure)
            before=broker.plane.get(broker.identity(tape.logs[0]))
            self.assertEqual(before['pending'],1)
            self.assertEqual(before['deadline'],clock[0]+5)
            broker.close();broker=Broker(Path(td)/'plane.sqlite',CURRENT_HASH,clock=lambda:clock[0],source='offline-scout')
            self.addCleanup(broker.close)
            self.assertEqual(broker.plane.get(before['id']),before)

    def test_same_durable_outputs_without_repeated_nomination_or_per_event_projection(self):
        # Recreate the exact old callback/return/controller sequence from the
        # reviewed source on the same deterministic raw tape. Only duplicate
        # local receive counters differ; raw records, fences and stages match.
        outputs=[];counts=[]
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True), \
                patch('meme_machine.lanes.pons.pipeline.time.time',return_value=12345.), \
                patch('meme_machine.lanes.pons.pipeline.time.monotonic',return_value=123.):
            for old in (True,False):
                root=Path(td)/str(old);root.mkdir()
                tape,clock,broker,scout,pipeline=self.fixture(root)
                statements=Counter();enqueues=[];maintains=[]
                def trace(sql):statements[sql.split(None,1)[0]]+=1
                broker.plane.db.set_trace_callback(trace)
                enqueue=broker.enqueue;maintain=broker.plane.maintain
                def nominated(*args,**kwargs):enqueues.append(1);return enqueue(*args,**kwargs)
                def maintained():maintains.append(1);return maintain()
                try:
                    started_cpu=time.thread_time();started_wall=time.perf_counter()
                    with patch.object(broker,'enqueue',side_effect=nominated), \
                            patch.object(broker.plane,'maintain',side_effect=maintained), \
                            patch.object(cohort.time,'time',return_value=clock[0]), \
                            patch.object(cohort,'_poll',side_effect=self.poll(tape,scout)):
                        _,_,rows=cohort._collect_observations(queue=broker,scout=scout)
                        if old:
                            for event in rows:broker.enqueue(event,now=clock[0],needs_work=event['topics'][0]==scout.curve_topics[0])
                            for event in rows:
                                broker.enqueue(event,now=clock[0],needs_work=event['topics'][0]==scout.curve_topics[0])
                                broker.report_to(pipeline,drain=True)
                        broker.report_to(pipeline,drain=True)
                    elapsed=dict(cpu_seconds=time.thread_time()-started_cpu,
                        wall_seconds=time.perf_counter()-started_wall)
                    outputs.append(self.durable(broker,pipeline))
                    counts.append(dict(enqueues=len(enqueues),maintenance=len(maintains),statements=dict(statements),**elapsed))
                finally:broker.close();pipeline.close()
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual([r['enqueues'] for r in counts],[96,32])
        self.assertEqual([r['maintenance'] for r in counts],[33,1])
        self.assertLess(counts[1]['statements']['SELECT'],counts[0]['statements']['SELECT'])
        self.assertLess(counts[1]['statements']['BEGIN'],counts[0]['statements']['BEGIN'])
        print('Pons discovery component fixture (32 synthetic raw events; not market capacity): '+
            json.dumps(dict(before=counts[0],after=counts[1]),sort_keys=True))


class ObservationTape(Tape):
    """Same event tape, including topic-OR public and exact canonical filters."""
    def _read(self,method,params):
        if method!='eth_getLogs':return super()._read(method,params)
        self.request_log.append((method,deepcopy(params)))
        if self.error:
            error,self.error=self.error,None;raise BoundaryError(error)
        q=params[0];first,last=int(q['fromBlock'],16),int(q['toBlock'],16)
        if last-first>=10:raise BoundaryError('provider_log_block_range_limit')
        return [deepcopy(e) for e in self.logs if first<=int(e['blockNumber'],16)<=last and
            (not q.get('address') or e['address'].lower()==q['address'].lower()) and
            all(w is None or e['topics'][i] in (w if isinstance(w,list) else [w]) for i,w in enumerate(q.get('topics',[])))]

    def receipt_value(self,tx):
        receipt=super().receipt_value(tx)
        receipt['from']=self.senders.get(tx,'0x'+'01'*20)
        return receipt


class ScoutCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.enterContext(patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(self.root/'sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID='scout-offline'),clear=True))
        self.tape=ObservationTape();self.tape.top=self.tape.grad
        self.clock=lambda:int(self.tape.header(self.tape.top)['timestamp'],16)
        self.broker=Broker(self.root/'plane.sqlite',CURRENT_HASH,clock=self.clock,source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT')
        self.addCleanup(self.broker.close)
        self.scout=MarketScout(self.broker.plane)
        self.runtime=Runtime(self.root/'survivor',10**18,'scout-offline','https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT',
            scout_path=self.broker.plane.path)
        self.runtime.rpc=self.tape;self.runtime.deployments_verified=True;self.runtime.now=self.clock
        self.addCleanup(lambda:self.runtime.close())
        self.enterContext(patch('meme_machine.lanes.pons.pons_survivor_runtime.configured_rpc',
            side_effect=lambda *a,**kw:self.tape.provider()))

    def nominate(self,event,observed):
        self.broker.enqueue(event,now=observed,needs_work=event['topics'][0]==self.scout.curve_topics[0])

    def observe(self,first=None,last=None):
        self.scout.read_market(self.tape,self.tape.grad-12 if first is None else first,
            self.tape.top if last is None else last,nominate=self.nominate)

    def authenticate(self):
        for _ in range(80):
            self.runtime.discover()
            if not self.runtime.history.pending_graduations():return
        self.fail('lineage did not complete')

    def test_one_public_filter_serves_independent_current_and_survivor(self):
        curve=self.tape.records[self.tape.tokens[0]]['curve']
        event=dict(address=curve,topics=[self.scout.curve_topics[0]],data='0x',
            blockNumber=hex(self.tape.grad),blockHash=self.tape.header(self.tape.grad)['hash'],
            transactionHash='0x'+'ae'*32,transactionIndex='0x4',logIndex='0x9')
        self.tape.logs.append(event);self.observe();original=self.broker.plane.get(self.broker.identity(event))
        self.assertEqual(original['deadline'],self.clock()+5)
        public_queries=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs']
        self.assertTrue(all(len(q['topics'][0])==4 for q in public_queries))
        self.assertEqual(len(self.scout.events('graduation')),1)
        # A Current economic rejection has no authority over the graduation.
        self.broker.plane.decision(original['id'],original['generation'],'economic_rejected','Current only')
        before=len(self.tape.request_log);self.authenticate()
        row=self.runtime.history.get(self.tape.tokens[0]);self.assertIsNotNone(row)
        self.assertTrue(self.runtime.candidate_readiness(row['id'])['ready'])
        self.assertEqual(self.runtime.history.get_meta(FORWARD_PLAN)['first'],self.tape.grad-12)
        queries=[p[0] for m,p in self.tape.request_log[before:] if m=='eth_getLogs']
        self.assertTrue(all(len(q['topics'])>1 for q in queries),queries)
        self.observe();self.assertEqual(self.broker.plane.get(original['id'])['deadline'],original['deadline'])
        self.assertEqual(len(self.runtime.history.rows()),1)

    def test_graduation_in_enrollment_block_has_no_seven_day_wait(self):
        self.observe(first=self.tape.grad);self.authenticate()
        self.assertEqual(len(self.runtime.history.rows()),1)
        report=self.runtime.historical_readiness
        self.assertFalse(report['market_wide_coverage_required'])
        self.assertEqual(report['pre_enrollment_coverage'],'UNOBSERVED')
        self.assertIsNone(self.runtime.history.get_meta('discovery_bootstrap'))

    def test_public_loss_never_advances_watermark_and_resume_retains_identities(self):
        self.observe(first=self.tape.grad);before=self.scout.snapshot();self.tape.top+=3
        self.tape.error='provider_http_429'
        with self.assertRaises(BoundaryError):self.observe(first=self.tape.grad+1)
        self.assertEqual(self.scout.snapshot()['market_cursor'],before['market_cursor'])
        self.assertIsNotNone(self.scout.snapshot()['market_gap'])
        self.observe(first=self.tape.grad+1)
        self.assertIsNone(self.scout.snapshot()['market_gap'])
        self.assertEqual(len(self.scout.events('graduation')),2)
        reopened=Plane(self.broker.plane.path,clock=self.clock)
        try:self.assertEqual(MarketScout(reopened).snapshot(),self.scout.snapshot())
        finally:reopened.close()

    def test_reorganization_rewinds_prospective_interval_and_keeps_fork_witnesses(self):
        self.observe(first=self.tape.grad);self.tape.reorg(self.tape.grad);self.tape.top+=1
        with self.assertRaisesRegex(BoundaryError,'scout_public_reorg'):
            self.observe(first=self.tape.grad+1)
        self.assertEqual(self.scout.snapshot()['market_cursor'],self.tape.grad-1)
        self.observe(first=self.tape.grad)
        self.assertEqual(len(self.scout.events('graduation')),3)

    def test_orphan_nomination_does_not_poison_later_canonical_graduation(self):
        self.observe();self.authenticate();self.tape.reorg(self.tape.grad-10);self.tape.top+=1
        with self.assertRaisesRegex(BoundaryError,'scout_public_reorg'):
            self.observe(first=self.tape.grad+1)
        self.observe(first=self.tape.grad-12);self.authenticate()
        row=self.runtime.history.get(self.tape.tokens[0])
        self.assertEqual(row['graduation']['block_hash'],self.tape.header(self.tape.grad)['hash'])
        self.assertEqual(len([r for r in self.runtime.history.rows() if r['id']==row['id']]),1)
        self.assertTrue(self.scout.events('graduation'))

    def test_delayed_authentication_retains_original_identity_and_deadline(self):
        self.observe()
        with patch.object(self.tape,'receipt_value',side_effect=BoundaryError('provider_missing_result')):
            with self.assertRaisesRegex(BoundaryError,'provider_missing_result'):self.runtime.discover()
        self.assertEqual(self.runtime.history.pending_graduations(),1)
        self.authenticate();row=self.runtime.history.get(self.tape.tokens[0])
        self.assertEqual(row['graduation']['at'],int(self.tape.header(self.tape.grad)['timestamp'],16))
        self.assertEqual(self.runtime.history.pending_graduations(),0)

    def test_interrupted_native_hydration_and_restart_never_claims_complete(self):
        self.observe();self.authenticate();self.tape.top+=4
        token=self.tape.tokens[0];before=deepcopy(self.runtime.history.get(token))
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activities',
                side_effect=BoundaryError('provider_transport_failure')):
            with self.assertRaises(BoundaryError):self.runtime._increment_candidates([before],self.tape.top)
        self.assertEqual(self.runtime.history.get(token)['block'],before['block'])
        self.assertFalse(self.runtime.candidate_readiness(token,through_block=self.tape.top)['ready'])
        self.runtime.close()
        self.runtime=Runtime(self.root/'survivor',10**18,'scout-offline','https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT',
            scout_path=self.broker.plane.path)
        self.runtime.rpc=self.tape;self.runtime.deployments_verified=True;self.runtime.now=self.clock
        def collect(endpoint,*,markets,start_block,end_block,**kwargs):
            from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
            return {m['token']:collect_v4_activity(None,**m,start_block=start_block,end_block=end_block,
                _shared=self.tape.shared_activity(start_block,end_block,[m['pool_id']])) for m in markets}
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.collect_v4_activities',side_effect=collect):
            self.runtime._increment_candidates([self.runtime.history.get(token)],self.tape.top)
        self.assertTrue(self.runtime.candidate_readiness(token,through_block=self.tape.top)['ready'])

    def test_multiple_valid_candidates_rotate_without_changing_deadlines(self):
        self.tape.top+=1;self.observe();self.authenticate();h=self.runtime.history
        rows=h.rows();self.assertEqual(len(rows),2)
        originals={r['id']:r['graduation']['at']+7*86400 for r in rows}
        first=h.qualification_turn(rows,self.clock())
        second=h.qualification_turn(h.rows(),self.clock())
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(originals,{r['id']:r['graduation']['at']+7*86400 for r in h.rows()})

    def test_native_fair_tie_breaks_and_urgent_original_deadline_both_survive(self):
        from tests.lanes.pons.test_pons_finalization import address,graduation
        h=self.runtime.history
        h.graduate(address(1),graduation(1,at=200))
        h.graduate(address(2),graduation(2,at=100))
        original={r['id']:r['graduation']['at']+7*86400 for r in h.rows()}
        # The later-born identity wins the original equal-attempt lexical tie.
        self.assertEqual(h.qualification_turn(h.rows(),20000)['id'],address(1))
        old=h.get(address(2));old.update(qualification_attempt=10000,last_checked=20000);h.save(old)
        # A heavily watched candidate still receives its final original chance.
        self.assertEqual(h.qualification_turn(h.rows(),original[address(2)]-1)['id'],address(2))
        self.assertEqual(original,{r['id']:r['graduation']['at']+7*86400 for r in h.rows()})

    def test_pool_scout_is_exact_pons_scope_and_keeps_raw_transaction_evidence(self):
        self.observe();self.authenticate();self.tape.top+=4
        self.scout.read_pools(self.tape,self.tape.top)
        pool=self.runtime.history.get(self.tape.tokens[0])['graduation']['transition']['market']
        retained=self.scout.events('pool',subject=pool)
        self.assertEqual(len(retained),4)
        activity=self.scout.activity(self.runtime.history.get(self.tape.tokens[0]))
        self.assertEqual(activity['buyer_independence'],'UNKNOWN')
        self.assertEqual(activity['swap_samples'],4)
        for _,e,_ in retained:self.assertTrue(e['transactionHash'] and e['data'])
        queries=[p[0] for m,p in self.tape.request_log if m=='eth_getLogs' and p[0].get('address')==MANAGER]
        self.assertTrue(queries)
        self.assertTrue(all(q['topics'][1]==[pool] for q in queries))

    def test_old_public_pool_recovery_cannot_consume_newer_pool_work_credit(self):
        self.tape.top+=1;self.observe();self.authenticate()
        tokens=self.tape.tokens
        self.tape.top=self.tape.grad+100
        # A newer pool was already advanced; the older pool retained an outage.
        with self.broker.plane.transaction():
            self.broker.plane.db.execute('UPDATE pons_scout_pools SET cursor=? WHERE token=?',
                (self.tape.grad+80,tokens[1]))
        self.scout.read_pools(self.tape,self.tape.top)
        newer=self.broker.plane.db.execute('SELECT * FROM pons_scout_pools WHERE token=?',(tokens[1],)).fetchone()
        self.assertEqual(newer['attempt'],0)
        self.scout.read_pools(self.tape,self.tape.top)
        newer=self.broker.plane.db.execute('SELECT * FROM pons_scout_pools WHERE token=?',(tokens[1],)).fetchone()
        older=self.broker.plane.db.execute('SELECT * FROM pons_scout_pools WHERE token=?',(tokens[0],)).fetchone()
        self.assertEqual(newer['cursor'],self.tape.top)
        self.assertLess(older['cursor'],self.tape.top)

    def test_weak_candidate_and_capital_denial_reactivate_on_new_pool_signal(self):
        self.observe();self.authenticate();self.tape.top+=4;now=self.clock()
        row=self.runtime.history.get(self.tape.tokens[0]);row.update(decision=dict(candidate=False),
            scout_next_check=now+60,scout_checked_signal=0)
        self.runtime.history.save(row)
        self.assertFalse(self.runtime._watch_due(row,now))
        self.scout.read_pools(self.tape,self.tape.top)
        self.assertTrue(self.runtime._watch_due(row,now))
        row['state']='capital_unavailable';self.runtime.history.save(row)
        self.assertTrue(self.runtime._watch_due(row,now))
        self.assertEqual(row['graduation']['at']+POLICY['universe']['max_seconds_after_graduation'],
            self.runtime.history.get(row['id'])['graduation']['at']+7*86400)

    def test_burst_retention_is_not_a_work_queue_or_candidate_cap(self):
        prototype=next(e for e in self.tape.logs if e['topics'][0]==GRADUATION)
        extra=[]
        for n in range(300):
            e=deepcopy(prototype);e['transactionHash']='0x'+f'{n+1000:064x}'
            e['transactionIndex']=hex(n);e['topics'][1]='0x'+f'{n+1:064x}';extra.append(e)
        self.tape.logs.extend(extra);self.observe(first=self.tape.grad)
        self.runtime._provider=lambda:None
        with patch('meme_machine.lanes.pons.pons_historical.Preparation.authenticate_step',return_value=False):
            self.runtime.discover();self.runtime.discover()
        self.assertEqual(self.runtime.history.pending_graduations(),301)
        self.assertEqual(self.scout.snapshot()['candidate_count_limit'],None)

    def test_saturation_splits_without_losing_events_or_accepting_pagination(self):
        class Saturated:
            def call(inner,method,params,scope):
                q=params[0]
                if q['fromBlock']!=q['toBlock']:return [dict()] * 1000
                return []
        q=dict(fromBlock='0x1',toBlock='0x4',topics=[[LAUNCH]])
        self.assertEqual(self.scout._logs(Saturated(),q),[])
        with patch.object(Saturated,'call',return_value=dict(logs=[],next='unknown')):
            with self.assertRaisesRegex(BoundaryError,'scout_log_array_required'):self.scout._logs(Saturated(),q)


class EvidenceTests(unittest.TestCase):
    def test_canonical_saturation_subdivides_and_preserves_all_buyers(self):
        from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
        from meme_machine.lanes.pons.protocols import PoolKey
        from meme_machine.lanes.pons.identity import load
        from meme_machine.lanes.pons.abi import decode_event
        tape=ObservationTape(candidates=1);token=tape.tokens[0];record=tape.records[token]
        key=PoolKey(*sorted((record['token'],record['pairToken']),key=lambda x:int(x,16)),
            record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        prototype=next(e for e in tape.logs if e['topics'][0]==SWAP and
            decode_event(load('uniswap_v4_manager')['abi'],e)['args']['amount0']>0)
        extra=[]
        for i in range(1001):
            event=deepcopy(prototype);block=tape.grad+1+i%2
            event.update(blockNumber=hex(block),blockHash=tape.header(block)['hash'],
                transactionHash='0x'+f'{10000+i:064x}',logIndex=hex(i))
            tape.senders[event['transactionHash']]='0x'+f'{10000+i:040x}';extra.append(event)
        tape.logs=extra
        def batched(endpoint,calls,scope,**kwargs):return tape.batch(calls,scope=scope),[]
        with patch('meme_machine.lanes.pons.pons_selective_v4._batched',side_effect=batched):
            result=collect_v4_activity('https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT',
                pool_id=key.pool_id(),key=key,token=token,start_block=tape.grad+1,end_block=tape.grad+2)
        self.assertEqual(len(result['swaps']),1001)
        self.assertEqual(len(result['buyer_groups']),1001)

    def test_current_complete_vectors_match_frozen_reference(self):
        import hashlib
        from engineering.robinhood_scout.replay import reference_module
        from tests.lanes.pons import test_pons_selective_continuation as fixture
        from tests.test_robinhood_usd_valuation import OPPORTUNITY_BASE,OPPORTUNITY_REFERENCE,opportunity_predecessor
        from meme_machine.paper_policy_revision import ACTIVE_REVISION
        reference=reference_module('pons_selective_continuation.py')
        with patch('engineering.robinhood_scout.replay.REFERENCE',OPPORTUNITY_BASE):
            predecessor=reference_module('pons_selective_continuation.py')
        with patch('engineering.robinhood_scout.replay.REFERENCE',OPPORTUNITY_REFERENCE):
            approved=reference_module('pons_selective_continuation.py')
        path='meme_machine/lanes/pons/pons_selective_continuation.py'
        current_source=(Path(__file__).resolve().parents[1]/path).read_bytes()
        self.assertEqual(hashlib.sha256(opportunity_predecessor(self,path,current_source)).hexdigest(),
                         predecessor.source_sha256)
        for override in ({},dict(current_snipe_bps=1),dict(launch_at=111),
                         dict(pair_token='0x'+'99'*20),dict(events=[])):
            actual=fixture.vector(**override)
            with patch.object(fixture,'qualification_vector',approved.qualification_vector):
                revised=fixture.vector(**override)
            self.assertEqual(actual,revised)
            self.assertEqual(actual['policy_revision'],ACTIVE_REVISION)
            with patch.object(fixture,'qualification_vector',predecessor.qualification_vector):
                legacy=fixture.vector(**override)
            with patch.object(fixture,'qualification_vector',reference.qualification_vector):
                expected=fixture.vector(**override)
            self.assertEqual(legacy,expected)

    def test_authenticated_receipt_sender_preserves_exact_v4_buyer_flow(self):
        from meme_machine.lanes.pons.pons_selective_v4 import collect_v4_activity
        from meme_machine.lanes.pons.protocols import PoolKey
        from dataclasses import asdict
        tape=ObservationTape(candidates=1);token=tape.tokens[0];record=tape.records[token]
        key=PoolKey(*sorted((record['token'],record['pairToken']),key=lambda x:int(x,16)),
            record['poolFee'],record['tickSpacing'],__import__('meme_machine.lanes.pons.identity',fromlist=['load']).load('pons_v2_hook')['address'].lower())
        pool=key.pool_id();first=tape.grad+1;last=first+8
        reference=collect_v4_activity(None,pool_id=pool,key=key,token=token,start_block=first,end_block=last,
            _shared=tape.shared_activity(first,last,[pool]))
        def batched(endpoint,calls,scope,**kwargs):return tape.batch(calls,scope=scope),[]
        with patch('meme_machine.lanes.pons.pons_selective_v4._batched',side_effect=batched):
            actual=collect_v4_activity('https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_SCOUT',pool_id=pool,key=key,token=token,start_block=first,end_block=last)
        self.assertEqual(actual,reference)
        self.assertNotIn('eth_getTransactionByHash',tape.methods)
        self.assertEqual(tape.methods['eth_getTransactionReceipt'],9)


if __name__=='__main__':unittest.main()
