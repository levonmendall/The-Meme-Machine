"""Offline production lifecycle tests: native quotes, finality and journal commits."""
from contextlib import ExitStack
from dataclasses import replace,asdict
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_paper as paper
from meme_machine.lanes.pons.evidence import Store
from meme_machine.lanes.pons.pons import CurveState
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
from tests.lanes.pons.test_pons_execution_acquisition import FakeRPC,candidate,CURVE
from tests.lanes.pons import test_pons_position_provider_recovery as recovery

class EntryOrderingTests(unittest.TestCase):
    def lifecycle(self,*,delay=20,mutate=None,validation_delay=0,persistent=True,folder=None,broker=False,supersede=False):
        clock=[102.0];calls=[];rpc=FakeRPC();rpc.used=0
        rpc.verify_chain=lambda:None
        rpc.telemetry=lambda:dict(logical_calls=rpc.logical,physical_transports=rpc.transports)
        c=candidate();c.update(receipt={'gasUsed':hex(21000)},record={})
        c['state']=CurveState(quote_reserve=2*10**18,token_reserve=800*10**24,
            real_quote=8*10**17,reserved_tokens=100*10**24,fee_bps=100,creator_tax_bps=50,graduated=False,launched_at=0,snipe_start_bps=9900,snipe_seconds=5,timestamp=100)
        vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
            proposed_size={'amount_quote':10**15},evidence_available_at=100,
            trajectory={'graduation_eta_seconds':60},demand={'largest_buyer_flow_bps':1000})
        evaluation=dict(vector=vector,candidate=c,token='t',curve=CURVE,source_transaction='tx',market_events=[])
        if folder is None:
            tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);folder=tmp.name
        db=Path(folder)/'paper.sqlite'
        if broker:
            from certification.robinhood.plane import Plane
            path=Path(folder)/'plane.sqlite'
            plane=Plane(path,clock=lambda:clock[0])
            if plane.get('candidate') is None:
                plane.observe('candidate','pons','obs1',{},ordering=(1,),watermark={'block':12},
                    interpretation={'policy':POLICY_HASH},observed=100,deadline=200,priority=1)
                plane.finish(plane.claim(),result={})
            plane.close()
            evaluation.update(candidate_plane_path=str(path),candidate_broker_identity='candidate',candidate_broker_generation=1)
        original_wait=paper._wait_curve_quote;original_validate=paper._validate_final_entry
        quotes=[]
        def wait(*a,**kw):
            calls.append(('quote',clock[0]));clock[0]+=.5
            q,m,l=original_wait(*a,**kw)
            if quotes and supersede:
                from certification.robinhood.plane import Plane
                plane=Plane(evaluation['candidate_plane_path'],clock=lambda:clock[0])
                plane.observe('candidate','pons','obs2',{},ordering=(2,),watermark={'block':13},
                    interpretation={'policy':POLICY_HASH},observed=clock[0],deadline=200,priority=1)
                plane.close()
            if quotes and mutate:q,m,l=mutate(q,m,l,quotes[0])
            quotes.append((q,m,l));return q,m,l
        def persistence(*a):
            calls.append(('persistence',clock[0]));clock[0]+=delay
            if supersede=='reconstruction':
                from certification.robinhood.plane import Plane
                plane=Plane(evaluation['candidate_plane_path'],clock=lambda:clock[0])
                plane.observe('candidate','pons','reconstruction_supersession',{},ordering=(2,),watermark={'block':13},
                    interpretation={'policy':POLICY_HASH},observed=clock[0],deadline=200,priority=1)
                plane.close()
            t,d,s=recovery.PositionRecoveryTests.persistent_entry_signal()
            if not persistent:d['current_net_quote']=0
            return t,d,s
        def validate(*a):
            original_validate(*a);clock[0]+=validation_delay
        def monitor(*a):raise BoundaryError('offline_monitor_stop')
        patches={'paper_rpc':lambda *a:rpc,'_gas_quote':lambda *a:(21000,1),
            '_wait_curve_quote':wait,'_refresh_entry_persistence_signal':persistence,
            '_validate_final_entry':validate,'_latest_header':monitor,
            'time.time':lambda:clock[0],'time.monotonic':lambda:clock[0],
            'time.sleep':lambda sec:clock.__setitem__(0,clock[0]+sec)}
        with ExitStack() as stack:
            if broker:
                from certification.robinhood.plane import Plane as NativePlane
                stack.enter_context(patch('certification.robinhood.plane.Plane',side_effect=lambda path,**kw:NativePlane(path,clock=lambda:clock[0])))
            for name,value in patches.items():stack.enter_context(patch.object(paper,name,side_effect=value) if '.' not in name else patch('meme_machine.lanes.pons.pons_selective_paper.'+name,side_effect=value))
            result=paper.run_lifecycle('offline',evaluation,db_path=db)
        store=Store(db);events=[json.loads(r[0]) for r in store.db.execute('SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))];store.close()
        return result,events,calls,rpc

    def test_slow_persistence_then_new_native_quote_commits(self):
        r,events,calls,rpc=self.lifecycle()
        self.assertEqual([c[0] for c in calls],['quote','persistence','quote'])
        self.assertEqual(sum(e['action']=='entry' for e in events),1,r)
        metrics=r['entry_persistence']
        self.assertEqual(metrics['persistence_elapsed_seconds'],20)
        self.assertEqual(metrics['final_quote_acquisition_seconds'],.5)
        self.assertLessEqual(metrics['quote_age_at_decision_seconds'],5)
        self.assertEqual(metrics['broad_reconstruction_after_final_quote'],0)
        self.assertEqual((rpc.logical,rpc.transports),(16,4))

    def test_real_time_after_final_quote_still_cancels(self):
        r,events,_,_=self.lifecycle(validation_delay=6)
        self.assertFalse(any(e['action']=='entry' for e in events),r)
        self.assertIn('stale',r.get('entry_failure',r.get('boundary','')))

    def test_decay_prevents_final_quote_acquisition(self):
        r,events,calls,_=self.lifecycle(persistent=False)
        self.assertEqual(r['entry_failure'],'entry_signal_decay')
        self.assertEqual([x[0] for x in calls],['quote','persistence'])
        self.assertFalse(any(e['action']=='entry' for e in events))

    def test_reused_quote_timestamp_forgery_and_missing_finality_rejected(self):
        def reused(q,m,l,old):return old
        def forged(q,m,l,old):return replace(old[0],stamp=replace(old[0].stamp,observed_at=q.stamp.observed_at)),dict(old[1],observed_at=q.stamp.observed_at),old[2]
        def no_finality(q,m,l,old):return q,m,None
        def zero(q,m,l,old):return replace(q,amount_out=0),dict(m,amount_out=0),l
        def missing(q,m,l,old):return replace(q,amount_out=None),dict(m,amount_out=None),l
        def untrusted(q,m,l,old):return replace(q,stamp=replace(q.stamp,block_hash='wrong')),m,l
        for mutate in (reused,forged,no_finality,zero,missing,untrusted):
            with self.subTest(mutation=mutate.__name__):
                r,events,_,_=self.lifecycle(mutate=mutate)
                self.assertFalse(any(e['action']=='entry' for e in events),r)

    def test_final_current_snipe_state_rejects(self):
        def mutate(q,m,l,old):return q,dict(m,current_snipe_bps=100),l
        r,events,_,_=self.lifecycle(mutate=mutate)
        self.assertEqual(r['boundary'],'snipe_tax_nonzero')
        self.assertFalse(any(e['action']=='entry' for e in events))

    def test_same_frontier_conflict_and_missing_delta_proof_reject(self):
        anchor=dict(block=1,block_hash='h1',event_at=100,state={})
        for final,error in ((dict(anchor,block_hash='other'),'conflict'),
                (dict(anchor,block=2,event_at=101),'unprovable'),
                (dict(anchor,block=0),'regression')):
            with self.subTest(error=error),self.assertRaisesRegex(BoundaryError,error):
                paper._confirm_entry_delta('offline',{},anchor,final,{}, {},{})

    def test_exact_delta_does_not_search_or_scan_full_history(self):
        header=dict(number='0x6',hash='h6',timestamp='0x65')
        calls=[]
        def batch(endpoint,rows,scope,**kwargs):calls.extend(rows);return [[]],[]
        with patch.object(paper,'_header_search',side_effect=AssertionError('history search')),patch.object(paper,'_batched',side_effect=batch):
            events,_=paper._curve_logs('https://robinhood-mainnet.g.alchemy.com/v2/offline',CURVE,header,after_block=5)
        self.assertEqual(events,[])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1][0]['fromBlock'],'0x6')
        self.assertEqual(calls[0][1][0]['toBlock'],'0x6')
        with self.assertRaisesRegex(BoundaryError,'capacity'):
            paper._curve_logs('https://robinhood-mainnet.g.alchemy.com/v2/offline',CURVE,dict(header,number=hex(300)),after_block=5)

    def test_generation_superseded_during_final_quote_cannot_enter(self):
        r,events,_,_=self.lifecycle(broker=True,supersede=True)
        self.assertEqual(r['boundary'],'candidate_generation_superseded_before_entry')
        self.assertFalse(any(e['action']=='entry' for e in events))

    def test_generation_superseded_during_reconstruction_cannot_enter(self):
        r,events,_,_=self.lifecycle(broker=True,supersede='reconstruction')
        self.assertFalse(any(e['action']=='entry' for e in events),r)

    def test_committed_entry_survives_restart_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            r,events,_,_=self.lifecycle(broker=True,folder=folder)
            self.assertEqual(sum(e['action']=='entry' for e in events),1,r)
            r,events,_,_=self.lifecycle(broker=True,folder=folder)
            self.assertEqual(sum(e['action']=='entry' for e in events),1,r)
            self.assertEqual(sum(e['action']=='reserve' for e in events),1)

    def test_current_delta_preserves_creator_and_net_demand_gates(self):
        def event(i,at,amount=10,side='buy',group=None):
            group=group or 'g'+str(i)
            return dict(identity=str(i),event_at=at,quote=amount,tokens=100,
                side=side,group=group,actor=group,recipient=group)
        retained=[event(i,80,1) for i in range(6)]+[event(i,99) for i in range(6,12)]
        anchor=dict(block=1,block_hash='h1',event_at=100,state={})
        final=dict(block=2,block_hash='h2',event_at=101,state={})
        headers=[dict(number=hex(x['block']),hash=x['block_hash'],timestamp=hex(x['event_at'])) for x in (anchor,final)]
        trajectory,_,_=recovery.PositionRecoveryTests.persistent_entry_signal()
        demand={'_entry_evidence':dict(complete=True,frontier=anchor,events=retained)}
        for delta,error in (([],None),([event(20,101,1,'sell','creator')],'creator_distribution'),
                ([event(20,101,1000,'sell')],'net_demand_nonpositive')):
            with self.subTest(error=error),patch.object(paper,'_batched',return_value=(headers,[])),patch.object(paper,'_curve_logs',return_value=(delta,[])) as logs:
                if error:
                    with self.assertRaisesRegex(BoundaryError,error):
                        paper._confirm_entry_delta('offline',{'curve':CURVE,'record':{'deployer':'creator'}},anchor,final,trajectory,demand,{})
                else:
                    current,_,metrics=paper._confirm_entry_delta('offline',{'curve':CURVE,'record':{}},anchor,final,trajectory,demand,{})
                    self.assertGreater(current['current_net_quote'],0)
                    self.assertEqual(metrics['events_reused'],12)
                self.assertEqual(logs.call_args.kwargs,{'after_block':1})

    def test_excessive_current_impact_rejected_at_frozen_limit(self):
        from meme_machine.lanes.pons.pons_natural_paper import _ledger_for_quote
        store=Store(':memory:')
        self.addCleanup(store.close)
        with patch('meme_machine.lanes.pons.pons_natural_paper.time.time',return_value=102):
            q,m=paper._curve_quote(FakeRPC(),candidate(),'buy',5*10**16,21000,store,'impact',local_freshness=True)
        m['current_snipe_bps']=0
        with self.assertRaisesRegex(BoundaryError,'selective_entry_impact'):
            paper._validate_final_entry(q,m,None,5*10**16,102)
