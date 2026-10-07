"""Gate 1 counterexamples: captured economics and durable overload/restart.

Offline only. No provider topology or provider-cost claim is made by these tests.
"""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory,CandidateDeadlineMissed
from meme_machine.runtime.survivor_history import History
from meme_machine.lanes.pump import runner
from meme_machine.lanes.pump.market_native_runtime import MarketNativeRuntime
from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry
from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
from meme_machine.lanes.meteora import runner as meteora
from meme_machine.lanes.meteora.dlmm_tape import transaction_swaps
from meme_machine.solana_source_intake import select_frame
from meme_machine.solana_program_decoders import pumpswap_trade_events,pump_events
from meme_machine.solana_evidence_queries import PumpEvidenceView
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from tests.test_solana_evidence_plane import record,proof
from tests.lanes.pump import test_pump_acceleration_strategy as current_cases
from tests.lanes.pump.test_pumpswap_survivor import facts
from tests import test_solana_source_intake as intake_cases

ROOT=Path(__file__).parent


class ReconstructionGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'shared.sqlite'
        self.h=CandidateHistory(self.path,clock=lambda:1000.,worker_capacity=1)
        self.addCleanup(lambda:self.h.close())

    def test_captured_pump_downside_and_qualification_do_not_depend_on_available_capital(self):
        snapshot=dict(accounts=json.loads((ROOT/'lanes/pump/fixtures/mainnet_candidate_accounts.json').read_text())['response']['value'])
        signal=current_cases.PumpAccelerationStrategyTests().strong_late();decisions=[];capacities=[]
        for case,available in [('zero',0),('committed',0),('normal',200_000_000)]:
            with self.subTest(case=case),patch.object(runner,'_current_pump_sizing',return_value=dict(
                    realized_equity=200_000_000,target=10_000_000,
                    allocatable_target=min(10_000_000,available),available=available)):
                capacity,_=runner._capacity(snapshot,400_000_000)
                capacities.append(asdict(capacity))
                decisions.append(runner.qualify(replace(signal,immediate_roundtrip_loss_bps=capacity.ordinary_loss_bps)))
        self.assertTrue(decisions[0].qualified)
        self.assertEqual(decisions,[decisions[0]]*3)
        self.assertEqual(capacities,[capacities[0]]*3)

    def test_survivor_qualification_is_durable_before_every_funding_outcome(self):
        rt=object.__new__(Runtime);rt.candidate_history=self.h;rt.now=lambda:1000
        decision=evaluate_entry(facts());self.assertTrue(decision['candidate'])
        for i,(case,available) in enumerate([('zero',0),('committed',0),('normal',1000000)]):
            row=dict(id=case)
            rt._decision(row,decision,1000+i)
            rt._funding(row,'funded' if available else 'denied',
                        None if available else 'survivor_minimum_capital',dict(available=available))
            stored=self.h.db.execute('SELECT qualified,body FROM decisions WHERE id=?',(row['decision_id'],)).fetchone()
            self.assertEqual(stored[0],1)
            self.assertEqual(json.loads(stored[1])['decision']['qualification'],json.loads(json.dumps(decision)))
            self.assertEqual(self.h.funding_outcome(row['decision_id'])['status'],'funded' if available else 'denied')

    def test_meteora_same_required_features_survive_zero_committed_and_normal_capital(self):
        policy=meteora.load_policy()
        features=dict(authenticated_fee_density_24h_pct=4.,competing_liquidity_to_capital_multiple=4.,
                      two_way_balance=.2,drift_ratio=.8,reversal_count=0,
                      stress_inventory_roundtrip=dict(loss_bps=200.),expected_net_lamports=1)
        results=[]
        for i,available in enumerate((0,0,2_000_000_000)):
            decision=meteora.qualify(features,policy);results.append(decision)
            ident=self.h.record_decision('meteora',str(i),mode='dlmm',observed_at=1000,
                qualified=decision['passes'],decision=dict(features=features,qualification=decision))
            self.h.record_funding(ident,'meteora',str(i),status='funded' if available else 'denied',at=1001,
                                 reason=None if available else 'dlmm_accounting_capital_exhausted')
            self.assertEqual(self.h.db.execute('SELECT qualified FROM decisions WHERE id=?',(ident,)).fetchone()[0],1)
        self.assertTrue(results[0]['passes']);self.assertEqual(results,[results[0]]*3)

    def test_recoverable_identity_exceeds_all_historical_count_and_attempt_limits(self):
        count=1024
        survivor=History(str(Path(self.tmp.name)/'survivor.sqlite'),policy='offline',maximum_candidates=64)
        self.addCleanup(survivor.close)
        market=object.__new__(MarketNativeRuntime)
        market.evidence_queue_limit=64;market.evidence_queue={}
        for attr in ('evidence_queue_capacity_pressure','evidence_queue_capacity_skips','capacity_losses','evidence_enqueued'):
            setattr(market,attr,0)
        metric=SimpleNamespace(priority_key=lambda:(0,))
        attempts=runner.RollingAttemptBudget(limit=120)
        warming=meteora.CampaignAttemptBudget(10)
        for i in range(count):
            name=f'mint-{i}'
            self.h.observe('pump',name,surface='pumpswap',observed_at=1000,metadata=dict(recoverable=True))
            self.h.enqueue('pump',name,kind='pumpswap_watch',ready_at=1000,deadline=10000,
                           estimate_seconds=1,identity=name)
            survivor.graduate(name,dict(at=1000,pool=name))
            market._queue_candidate(dict(mint=name,nomination=dict(market_time=1000)),metric,1000)
            attempts.take(1000)
            self.assertTrue(meteora._attempt_budget_state(warming,1000,True)['evaluate'])
        self.assertEqual(len(self.h.candidates()),count)
        self.assertEqual(self.h.pending(),count)
        self.assertEqual(len(survivor.rows()),count)
        self.assertEqual(len(market.evidence_queue),count)
        self.assertEqual(market.capacity_losses,0)
        self.assertEqual(survivor.get_meta('candidate_capacity_pressure'),count-64)
        self.assertEqual(self.h.telemetry()['maximum_queue_depth'],count)

    def test_edf_drains_feasible_overload_without_starvation_and_positions_outrank_it(self):
        for i in reversed(range(64)):
            self.h.enqueue('pump',str(i),kind='qualification',ready_at=1000,deadline=1200+i,
                           estimate_seconds=1,priority=20,identity=str(i))
        for priority,kind in ((2,'continuation'),(1,'position'),(0,'settlement')):
            self.h.enqueue('meteora',kind,kind=kind,ready_at=1000,deadline=10000,
                           estimate_seconds=1,priority=priority,identity=kind)
        identities=[]
        for offset in range(67):
            work=self.h.claim('worker',now=1000+offset)
            self.assertLessEqual(1000+offset+1,work['deadline'])
            identities.append(work['id']);self.h.complete(work['id'],now=1001+offset)
        self.assertEqual(identities,['settlement','position','continuation']+[str(i) for i in range(64)])
        self.assertEqual(self.h.pending(),0)
        self.assertEqual(self.h.telemetry()['deadline_misses'],0)

    def test_actual_meteora_admission_queues_urgent_identity_before_slow_context_io(self):
        import time
        items=[dict(address='slow',signal_observed_at=1000,tvl_usd=1000,
                    fee_5m_usd=1,missing_5m_context=True,decision_deadline=9000),
               dict(address='urgent',signal_observed_at=1000,tvl_usd=1000,
                    fee_5m_usd=1,decision_deadline=5000)]
        class Source:
            deadline_wall=10000;on_discovered=None
            def start(self):pass
            def next_candidate(self):return items.pop(0) if items else None
            def snapshot(self):return dict(first_seen=2,census_cycles=1,pending=len(items))
            def close(self):self.final_snapshot=self.snapshot()
        source=Source();telemetry={}
        with patch.object(meteora,'CANDIDATE_HISTORY',self.h),patch.object(meteora.time,'time',return_value=1000), \
             patch.object(meteora,'_stage'),patch.object(meteora,'_history_acceleration',side_effect=lambda item,_:item) as io:
            stream=meteora._campaign_candidates(meteora.load_policy(),telemetry,time.monotonic()+60,lambda _:None,source)
            self.addCleanup(stream.close)
            first=next(stream)
            self.assertEqual(first['address'],'urgent')
            self.assertEqual(len(self.h.candidates(lane='meteora')),2)
            io.assert_not_called()
            self.h.complete(first['_candidate_work_id'])
            second=next(stream);self.assertEqual(second['address'],'slow')
            io.assert_called_once()
            self.h.complete(second['_candidate_work_id'])
            with self.assertRaises(StopIteration):next(stream)

    def test_current_and_survivor_commit_one_shared_event_with_native_and_relative_order(self):
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpHistory,SWAP_SCOPE
        intake_cases.SourceIntakeTests.setUpClass()
        template=intake_cases.SourceIntakeTests.templates['pumpswap'][0]
        originals=pumpswap_trade_events(dict(template,slot=10))
        self.assertTrue(originals)
        for native in (True,False):
            with self.subTest(native=native):
                candidate='mint-native' if native else 'mint-relative';pool=candidate+'-pool'
                at=originals[0]['market_time'];writer=EvidenceWriter(Path(self.tmp.name)/(candidate+'.sqlite'))
                self.addCleanup(writer.close)
                records=[]
                for i in (0,1):
                    event=dict(originals[0],slot=10,mint=candidate,pool=pool,index=i)
                    records.append(replace(record(slot=10,scope=SWAP_SCOPE,identity=candidate+':'+str(i),observed=at+1),
                        signature='sig'+str(i),event_index=i,transaction_index=107+i if native else None,
                        market_time=at,addresses=(pool,),payload=dict(event=event)))
                writer.ingest(records,proof=proof(10,10,scope=SWAP_SCOPE,at=at+1))
                writer.db.execute('CREATE TABLE stream_order(scope TEXT,slot INTEGER,signature TEXT,rank INTEGER)')
                writer.db.executemany('INSERT INTO stream_order VALUES(?,?,?,?)',[(SWAP_SCOPE,10,'sig'+str(i),7+i) for i in (0,1)])
                reader=EvidenceReader(writer.path);self.addCleanup(reader.close)
                thread=SimpleNamespace()
                def read_events(scope,address,lower,upper,**kwargs):
                    view=PumpEvidenceView(reader,scope)
                    result=view.events(address,lower_slot=10,upper_slot=10,lower_time=lower,upper_time=upper,as_of=at+1)
                    thread.pump_ordered_records=view.ordered_records;return result
                plane=SimpleNamespace(reader=reader,_thread_readers=thread,pump_events=read_events,
                    bounds=lambda *args,**kwargs:(10,10),interest=lambda *args,**kwargs:None,
                    advance_interest=lambda *args,**kwargs:None)
                history=LocalPumpHistory(plane,pool,at-1);history.bind_snapshot(dict(slot=10,market_time=at))
                state=dict(mint=candidate,pool=pool,graduation_time=at-1,history=history)
                with patch.object(runner,'CANDIDATE_HISTORY',self.h):runner._refresh_pool_events(state,None,at,research=True)
                first=self.h.events('pump',candidate)
                survivor=History(str(Path(self.tmp.name)/(candidate+'-survivor.sqlite')),policy='offline')
                self.addCleanup(survivor.close)
                survivor.graduate(candidate,dict(at=at-1,pool=pool))
                rt=object.__new__(Runtime);rt.history=survivor;rt.plane=plane;rt.candidate_history=self.h
                rt.confirmations=SimpleNamespace(cluster=lambda wallet:wallet)
                rt._increment(survivor.get(candidate),at,10)
                self.assertEqual(self.h.events('pump',candidate),first)
                self.assertEqual(len(first),2)
                self.assertEqual([r['transaction_index'] for r in first],[107,108] if native else [None,None])
                self.assertEqual([r['payload']['_economic_order'] for r in first],[107,108] if native else [7,8])
                self.assertTrue(self.h.event_order_status('pump',candidate)['complete'])
                self.assertIsNone(state.get('position'))
                self.assertIsNone(survivor.get(candidate).get('position'))

    def test_deadline_miss_is_durable_after_restart_and_does_not_poison_other_candidates(self):
        self.h.enqueue('pump','miss',kind='qualification',ready_at=1000,deadline=1005,
                       estimate_seconds=10,identity='miss')
        self.h.enqueue('meteora','feasible',kind='warmup',ready_at=1000,deadline=1100,
                       estimate_seconds=1,identity='feasible')
        with self.assertRaises(CandidateDeadlineMissed):self.h.claim('worker',now=1006)
        self.h.close();self.h=CandidateHistory(self.path,clock=lambda:1000.,worker_capacity=1)
        observations=self.h.work_observations(kind='deadline_missed')
        self.assertEqual(len(observations),1)
        self.assertFalse(observations[0]['details']['economic_rejection'])
        self.assertEqual(self.h.claim('worker',now=1000)['id'],'feasible')
        with self.assertRaisesRegex(ValueError,'immutable'):self.h.complete('miss')

    def test_meteora_actual_capture_replay_preserves_original_availability_and_economics(self):
        adapter=SimpleNamespace(snapshot_from_state=lambda *args,**kwargs:{'slot':20})
        signatures=[dict(signature='swap',slot=20,transactionIndex=7)]
        plane=SimpleNamespace(meteora_interval=lambda *args:(signatures,{},{}),count=lambda *args:None)
        from meme_machine.lanes.meteora.dlmm_tape import VerifiedTape
        event=dict(signature='swap',slot=20,cursor=[20,7,0],time=1000,
                   available_time=1001,amount=50,prestate_hash='exact-state')
        def capture():
            tape=VerifiedTape('start','end',(dict(event),),{'time':1000},'proof')
            with patch.object(meteora,'CANDIDATE_HISTORY',self.h),patch.object(meteora,'_stage'), \
                 patch.object(meteora,'_stop_sleep'),patch.object(meteora,'_evidence_plane',return_value=plane), \
                 patch.object(meteora,'reconstruct',return_value=tape):
                meteora._capture_chunk(adapter,{'pool':'pool','slot':19},[19,0,0],1)
        capture();first=self.h.events('meteora','pool')
        self.h.close();self.h=CandidateHistory(self.path,clock=lambda:1010.)
        event['available_time']=1010;capture()
        self.assertEqual(self.h.events('meteora','pool'),first)
        event['amount']=51
        with self.assertRaisesRegex(ValueError,'event_conflict'):capture()

    def test_shared_history_orders_distinct_same_slot_events_across_promotion_replay_and_restart(self):
        expected=[]
        for lane,candidate in [('pump','mint'),('meteora','pool')]:
            self.h.observe(lane,candidate,surface='cheap',observed_at=1000)
            events=[dict(identity=f'{tx}:{event}',slot=20,transaction_index=tx,event_index=event,
                         market_time=1000,kind='economic',payload=dict(wallet=f'w{tx}',amount=tx+event))
                    for tx in (7,9,12) for event in (0,1)]
            random.Random(21).shuffle(events)
            for event in events:self.h.append_event(lane,candidate,**event)
            expected.append(self.h.events(lane,candidate))
            self.h.observe(lane,candidate,surface='promoted',observed_at=1010)
            self.h.observe(lane,candidate,surface='quiet',observed_at=1020)
            self.h.observe(lane,candidate,surface='reactivated',observed_at=1030)
            for event in events:self.h.append_event(lane,candidate,**event)
        self.h.close();self.h=CandidateHistory(self.path,clock=lambda:1040.)
        self.assertEqual(self.h.events('pump','mint'),expected[0])
        self.assertEqual(self.h.events('meteora','pool'),expected[1])
        self.assertEqual([(e['transaction_index'],e['event_index']) for e in expected[0]],
                         [(7,0),(7,1),(9,0),(9,1),(12,0),(12,1)])
        self.h.append_event('pump','unknown',identity='unknown',slot=20,transaction_index=None,
                            event_index=0,market_time=1000,kind='trade',payload={})
        self.assertFalse(self.h.event_order_status('pump','unknown')['complete'])
        self.assertFalse(self.h.event_order_status('pump','missing')['complete'])

    def test_log_only_pump_and_pumpswap_decoders_have_exact_economic_parity(self):
        intake_cases.SourceIntakeTests.setUpClass()
        for family,decoder in [('pump',pump_events),('pumpswap',pumpswap_trade_events)]:
            for tx in intake_cases.SourceIntakeTests.templates[family]:
                full=dict(tx,slot=300)
                cheap=dict(slot=300,meta={k:tx['meta'].get(k) for k in ('err','logMessages')})
                self.assertEqual(decoder(full),decoder(cheap))

    def test_chain_transaction_order_controls_the_same_second_terminal_state(self):
        from meme_machine.lanes.pump.pump_acceleration_evidence import late_curve_trajectory
        events=[dict(market_time=80,slot=8,index=0,real_token_reserves=500,
                     virtual_quote_reserves=100,virtual_token_reserves=100),
                dict(market_time=90,slot=9,index=99,real_token_reserves=300,
                     virtual_quote_reserves=130,virtual_token_reserves=100,_economic_order=7),
                dict(market_time=90,slot=9,index=1,real_token_reserves=400,
                     virtual_quote_reserves=120,virtual_token_reserves=100,_economic_order=9)]
        curve=SimpleNamespace(real_token=200,sol=150,token=100)
        actual=late_curve_trajectory(dict(initial_real_token_reserves=1000),events,curve,100)
        reference=late_curve_trajectory(dict(initial_real_token_reserves=1000),[events[0],events[2]],curve,100)
        self.assertEqual(actual,reference)

    def test_prospect_cutoff_keeps_prior_transaction_with_a_larger_log_index(self):
        from meme_machine.runtime.candidate_history import economic_event_cursor
        earlier=dict(slot=9,_economic_order=7,index=99)
        current=dict(slot=9,_economic_order=9,index=1)
        later=dict(slot=9,_economic_order=12,index=0)
        self.assertEqual([row for row in (earlier,current,later)
                          if economic_event_cursor(row)<=economic_event_cursor(current)],
                         [earlier,current])

    def test_local_pump_view_refuses_ambiguous_multiple_transactions_in_one_slot(self):
        writer=EvidenceWriter(Path(self.tmp.name)/'plane.sqlite');self.addCleanup(writer.close)
        events=[dict(slot=10,market_time=10,wallet='w'+str(i)) for i in (1,2)]
        records=[replace(record(identity=str(i)),signature='sig'+str(i),payload=dict(event=e))
                 for i,e in enumerate(events)]
        writer.ingest(records,proof=proof())
        reader=EvidenceReader(writer.path);self.addCleanup(reader.close)
        view=PumpEvidenceView(reader,'pump')
        with self.assertRaisesRegex(EvidenceUnavailable,'transaction_order_missing'):
            view.events('pool',lower_slot=10,upper_slot=10,lower_time=10,upper_time=10,as_of=100)
        writer.db.execute('CREATE TABLE stream_order(scope TEXT,slot INTEGER,signature TEXT,rank INTEGER)')
        writer.db.executemany('INSERT INTO stream_order VALUES(?,?,?,?)',[('pump',10,'sig0',9),('pump',10,'sig1',7)])
        rows=view.events('pool',lower_slot=10,upper_slot=10,lower_time=10,upper_time=10,as_of=100)
        self.assertEqual([e['wallet'] for e in rows],['w2','w1'])
        self.assertEqual([e['_economic_order'] for e in rows],[7,9])

    def test_pregraduation_strategy_history_survives_hot_archive_and_late_promotion(self):
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape,PUMP_SCOPE,EvidenceUnavailable as LaneUnavailable
        writer=EvidenceWriter(Path(self.tmp.name)/'plane.sqlite');self.addCleanup(writer.close)
        creation=dict(event_type='create',mint='mint',slot=1,market_time=50,initial_real_token_reserves=1000,creator='creator')
        trades=[dict(event_type='trade',mint='mint',slot=i,market_time=t,index=0,wallet='w'+str(i),
                     real_token_reserves=reserves,virtual_quote_reserves=quote,virtual_token_reserves=100)
                for i,t,reserves,quote in [(2,80,500,100),(3,90,300,130)]]
        records=[replace(record(slot=e['slot'],scope=PUMP_SCOPE,observed=100),
                         market_time=e['market_time'],addresses=('mint',),transaction_index=0,payload=dict(event=e))
                 for e in [creation]+trades]
        writer.ingest(records,proof=proof(0,3,scope=PUMP_SCOPE))
        writer.db.execute('CREATE TABLE stream_receipts(scope TEXT,slot INTEGER,market_time INTEGER)')
        writer.db.executemany('INSERT INTO stream_receipts VALUES(?,?,?)',[(PUMP_SCOPE,0,40),(PUMP_SCOPE,3,100)])
        reader=EvidenceReader(writer.path);self.addCleanup(reader.close)
        acknowledgements=[]
        plane=SimpleNamespace(reader=reader,clock=lambda:100,frontier=lambda scope:3,owner='test',
                              command=lambda **args:acknowledgements.append(args))
        tape=LocalPumpTape(plane)
        with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.path)):
            tape.events_since(0)
            self.assertEqual(len(acknowledgements),1)
            self.assertEqual(len(self.h.events('pump','mint')),3)
            self.h.close();self.h=CandidateHistory(self.path,clock=lambda:100.)
            writer.db.execute('UPDATE records SET body=NULL')
            def unavailable(*args,**kwargs):raise LaneUnavailable('evidence_requires_offline_archive_restore')
            plane.pump_events=unavailable
            restored_creation=tape.creation('mint')
            self.assertEqual(restored_creation['initial_real_token_reserves'],1000)
            self.assertEqual(restored_creation['available_time'],100)
            restored=tape.window('mint',100,max_slot=3)
            from meme_machine.lanes.pump.pump_acceleration_evidence import late_curve_trajectory
            curve=SimpleNamespace(real_token=200,sol=150,token=100)
            self.assertEqual(late_curve_trajectory(restored_creation,restored,curve,100),
                             late_curve_trajectory(creation,trades,curve,100))
            with self.assertRaisesRegex(LaneUnavailable,'continuity_missing'):
                tape.window('mint',105,max_slot=4)

    def test_history_commit_failure_cannot_acknowledge_source_consumption(self):
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape,PUMP_SCOPE
        writer=EvidenceWriter(Path(self.tmp.name)/'plane.sqlite');self.addCleanup(writer.close)
        e=dict(event_type='create',mint='mint',slot=1,market_time=50,initial_real_token_reserves=1000)
        writer.ingest([replace(record(slot=1,scope=PUMP_SCOPE),market_time=50,transaction_index=0,payload=dict(event=e))],
                      proof=proof(1,scope=PUMP_SCOPE))
        reader=EvidenceReader(writer.path);self.addCleanup(reader.close);acks=[]
        plane=SimpleNamespace(reader=reader,clock=lambda:100,frontier=lambda scope:1,owner='test',command=lambda **args:acks.append(args))
        with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.path)),patch.object(
                CandidateHistory,'retain_pump_source_history',side_effect=RuntimeError('disk_fault')):
            with self.assertRaisesRegex(RuntimeError,'disk_fault'):LocalPumpTape(plane).events_since(0)
        self.assertEqual(acks,[])

    def test_real_coalesced_meteora_account_counterexample_keeps_the_swap_in_narrow_vector(self):
        fixture=json.loads((ROOT/'fixtures/meteora_account_coalescence.json').read_text())
        counterexample=fixture['counterexample'];tx=fixture['transaction']
        self.assertFalse(counterexample['account_trigger_found'])
        from meme_machine.lanes.meteora.dlmm import PROGRAM
        selected=select_frame(intake_cases.encode(intake_cases.frame([tx],slot=tx['slot'])),'',(PROGRAM,),
                              max_bytes=4*1024*1024,full_transaction_addresses=(PROGRAM,))
        narrow=selected.message['params']['result']['value']['block']['transactions'][0]
        narrow=dict(narrow,slot=tx['slot'],blockTime=tx['blockTime'])
        for pool in counterexample['pools']:
            full_effects=[];narrow_effects=[]
            full=transaction_swaps(tx,pool['pool'],full_effects,trigger_only=True)
            reduced=transaction_swaps(narrow,pool['pool'],narrow_effects,trigger_only=True)
            self.assertEqual(len(full),1)
            self.assertEqual(reduced,full);self.assertEqual(narrow_effects,full_effects)
        self.assertEqual(narrow['transactionIndex'],counterexample['index'])


if __name__=='__main__':unittest.main()
