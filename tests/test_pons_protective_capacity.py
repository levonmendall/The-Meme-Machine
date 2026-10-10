"""Native decisions under the actual two-RPS admission, with injected HTTP RTT.

No provider is contacted. These traces prove software envelopes, not endpoint
latency or capability. Every replay uses real native books, risk and capital.
"""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission
from tests import test_pons_shared_native_acquisition as shared
from tests.lanes.pons import test_pons_finalization as native


class ActiveRPC(shared.TraceRPC):
    def __init__(self,*,proved=False,count=1,latency=.1,price_factor=1.,paced=True,admission_path=None):
        super().__init__(proved=proved)
        from engineering.pons_history.fixtures import encoded_event
        self.transaction='0x'+'a9'*32;self.latency=latency;self.price_factor=price_factor
        if self.shared_quote_resources is not None:self.shared_quote_resources['max_latency_seconds']=latency
        self.events=[encoded_event('uniswap_v4_manager','Swap',dict(
            id=native.graduation(i)['transition']['market'],sender=native.address(990),
            amount0=10000,amount1=-10000,sqrtPriceX96=1<<96,liquidity=1000000,tick=0,fee=0),
            block=101,block_hash=native.block_header(101)['hash'],tx=self.transaction,
            tx_index=0,index=i-1) for i in range(1,count+1)]
        self.tmp=tempfile.TemporaryDirectory();self.starts=[];self.waits=[];self.responses=[]
        self.bytes=0;self.request_bytes=0
        self.governor=Admission(admission_path or self.tmp.name+'/provider.sqlite',native.ENDPOINT,lane='pons',
            clock=lambda:self.clock,sleeper=self.sleep) if paced else None

    def sleep(self,seconds):self.clock+=seconds
    def close(self):self.tmp.cleanup()

    def value(self,method,params):
        if method=='eth_getLogs':
            q=params[0];topics=q['topics'][1]
            if isinstance(topics,str):topics=[topics]
            return deepcopy([e for e in self.events if e['topics'][1] in topics
                and int(q['fromBlock'],16)<=101<=int(q['toBlock'],16)])
        if method=='eth_getTransactionReceipt':
            return dict(transactionHash=self.transaction,blockHash=native.block_header(101)['hash'],
                blockNumber='0x65',transactionIndex='0x0',status='0x1',logs=deepcopy(self.events),
                **{'from':native.address(990)})
        if method=='eth_getTransactionByHash':
            return dict(hash=self.transaction,blockHash=native.block_header(101)['hash'],
                blockNumber='0x65',transactionIndex='0x0',**{'from':native.address(990)})
        result=super().value(method,params)
        if method=='eth_call' and params[0]['data']!=shared.runtime.calldata('poolManager()'):
            amount=int(result[2:66],16)
            result='0x'+f'{int(amount*self.price_factor):064x}'+result[66:]
        return result

    def purchase(self,rows,scope,invoke):
        deadline=getattr(self,'evidence_deadline',None)
        admitted=(self.governor.acquire(scope,deadline,methods=[m for m,p in rows]) if self.governor
            else dict(wait_seconds=0,admitted_at=self.clock))
        self.starts.append(admitted['admitted_at']);self.waits.append(admitted['wait_seconds'])
        self.request_bytes+=len(json.dumps(rows,separators=(',',':')).encode())
        result=invoke();self.clock+=self.latency
        self.bytes+=len(json.dumps(result,separators=(',',':')).encode());self.responses.append(self.clock)
        if deadline is not None and self.clock>=deadline:
            raise BoundaryError('evidence_deadline_during_transport')
        return result

    def call(self,method,params,*,scope):
        return self.purchase([(method,params)],scope,lambda:super(ActiveRPC,self).call(method,params,scope=scope))
    def batch(self,calls,*,scope):
        return self.purchase(calls,scope,lambda:super(ActiveRPC,self).batch(calls,scope=scope))


def replay(test,count,*,predecessor=False,proved=True,latency=.1,price_factor=1.,paced=True,before_step=None):
    def rpc(**kw):
        obj=ActiveRPC(**kw,count=count,latency=latency,price_factor=price_factor,paced=paced)
        test.addCleanup(obj.close);return obj
    with patch.object(shared,'TraceRPC',side_effect=rpc):
        return test.run_positions(count,proved=proved,predecessor=predecessor,moving_clock=True,before_step=before_step)


class ProtectiveCapacityTests(shared.SharedNativeAcquisitionTests):
    def economic(self,positions,risks):
        # RTT changes genuine observation/settlement time and capital-time
        # integrals. Never alter those clocks to manufacture byte parity.
        return ([{k:v for k,v in p.items() if k not in ('last_at','risk_at','capital_unit_seconds')}
                    for p in positions],
                [{k:v for k,v in r.items() if k not in ('last_at','high_at','first_tail_crossed_at')}
                    for r in risks])

    def test_one_active_native_survivor_finishes_hold_and_full_stop_inside_original_window(self):
        for factor,action,starts in ((1.,'hold',4),(.6,'full_exit',6),(2.2,'partial_exit',6)):
            with self.subTest(action=action):
                a,ra,old,_=replay(self,1,predecessor=True,price_factor=factor,paced=False,latency=0)
                exact,re,_,_=replay(self,1,price_factor=factor,paced=False,latency=0)
                self.assertEqual(a,exact);self.assertEqual(ra,re)
                b,rb,new,_=replay(self,1,price_factor=factor)
                self.assertEqual(self.economic(a,ra),self.economic(b,rb))
                self.assertEqual(rb[0]['last_action']['action'],action)
                self.assertEqual(len(new.starts),starts)
                self.assertLess(new.clock-100+new.local_wall_seconds,3)
                self.assertTrue(all(b-a>=.5-1e-8 for a,b in zip(new.starts,new.starts[1:])))
                # State+logs precede enrichment; the following numeric batch is
                # genuinely ordered after receipt completion, not batch order.
                self.assertIn('eth_getLogs',[m for m,p in new.transports[1][1]])
                self.assertEqual(new.transports[2][1][0][0],'eth_getTransactionReceipt')
                self.assertTrue(all(m=='eth_getBlockByNumber' for m,p in new.transports[3][1]))
                print('NATIVE_PROTECTIVE_ENVELOPE',json.dumps(dict(action=action,starts=new.starts,
                    responses=new.responses,queue_wait=sum(new.waits),decision_completed=new.clock,
                    native_local_wall_seconds=new.local_wall_seconds,native_cpu_seconds=new.local_cpu_seconds,
                    complete_modeled_envelope_seconds=new.clock-100+new.local_wall_seconds,
                    response_bytes=new.bytes,request_bytes=new.request_bytes,
                    original_transports=len(old.transports),optimized_transports=len(new.transports))),flush=True)

    def test_one_through_twenty_active_positions_keep_native_risk_and_accounting(self):
        for count in range(1,21):
            with self.subTest(positions=count):
                a,ra,old,_=replay(self,count,predecessor=True,paced=False,latency=0)
                exact,re,_,_=replay(self,count,paced=False,latency=0)
                self.assertEqual(a,exact);self.assertEqual(ra,re)
                b,rb,new,result=replay(self,count)
                self.assertEqual(self.economic(a,ra),self.economic(b,rb))
                self.assertEqual(len(new.starts),4)
                self.assertEqual(new.methods['eth_getTransactionReceipt'],1)
                self.assertLess(new.clock-100,3)
                self.assertEqual(result['accounting']['open_positions'],count)

    def test_partial_realization_retains_original_quote_clock_and_fresh_quantity_and_gas(self):
        a,ra,old,_=replay(self,1,predecessor=True,price_factor=2.2,paced=False,latency=0)
        exact,re,_,_=replay(self,1,price_factor=2.2,paced=False,latency=0)
        self.assertEqual(a,exact);self.assertEqual(ra,re)
        b,rb,new,_=replay(self,1,price_factor=2.2)
        self.assertEqual(self.economic(a,ra),self.economic(b,rb))
        self.assertTrue(rb[0]['realization_taken'])
        self.assertEqual(len(new.starts),6)
        self.assertLess(new.clock-100+new.local_wall_seconds,3)
        self.assertEqual([m for m,p in new.transports[-2][1]],['eth_call','eth_gasPrice'])
        self.assertEqual(self.native_runtime.book.replay()['verified'],True)
        print('NATIVE_PARTIAL_EXECUTION_ENVELOPE',json.dumps(dict(starts=new.starts,
            responses=new.responses,decision_completed=new.clock,original_deadline=103,
            quantity_remaining=b[0]['tokens'],native_accounting_verified=True)),flush=True)

    def test_noncanonical_receipts_are_never_published(self):
        self.run_positions(1,proved=False)
        r=self.native_runtime;row=r.history.rows()[0];before=deepcopy(row)
        rpc=ActiveRPC();self.addCleanup(rpc.close);rpc.fork=True;rpc.top=102;r.rpc=rpc
        with patch('time.time',side_effect=lambda:rpc.clock),patch('time.monotonic',side_effect=lambda:rpc.clock):
            with self.assertRaisesRegex(BoundaryError,'canonical.*membership'):
                r._prepare_held_acquisition([row])
        self.assertEqual(r.history.get(row['id']),before)
        self.assertFalse(getattr(r,'shared_held_quotes',{}))

    def test_pending_full_exit_uses_its_own_joint_frame_before_other_owners(self):
        from meme_machine.runtime.survivor_commit import restore_risk
        from meme_machine.runtime.survivor_risk import mark
        def pending(r,rpc):
            p=r.book._load('pons-finalization:position:1')
            state=restore_risk(r.book,p['id'])
            observation=dict(id='prior-stop',at=99,after_cost_return_bps=-4000,
                net_exit_proceeds=p['basis']*6//10,exit_liquidity_valid=True)
            risk,action=mark(state,observation,shared.runtime.risk_policy())
            self.assertEqual(action['action'],'full_exit')
            r.book.transition(p['id'],'mark',99,amount=observation['net_exit_proceeds'],
                evidence=dict(risk_state=risk,observation=observation))
            row=r.history.rows()[0];row['position_safety']=dict(pending_exit=True);r.history.save(row)
        a,ra,old,_=replay(self,1,predecessor=True,latency=0,paced=False,before_step=pending)
        b,rb,new,_=replay(self,1,latency=0,paced=False,before_step=pending)
        self.assertEqual(a,b);self.assertEqual(ra,rb)
        _,risk,rpc,_=replay(self,1,before_step=pending)
        self.assertEqual(risk[0]['last_action']['action'],'full_exit')
        self.assertEqual(len(rpc.starts),6)
        self.assertLess(rpc.clock-100+rpc.local_wall_seconds,3)

    def test_two_simultaneous_full_exits_share_only_valid_common_execution_facts(self):
        a,ra,_,_=replay(self,2,price_factor=.6,predecessor=True,latency=0,paced=False)
        b,rb,_,_=replay(self,2,price_factor=.6,latency=0,paced=False)
        self.assertEqual(a,b);self.assertEqual(ra,rb)
        positions,risk,rpc,_=replay(self,2,price_factor=.6)
        self.assertTrue(all(p['status']=='settled' for p in positions))
        self.assertTrue(all(r['last_action']['action']=='full_exit' for r in risk))
        self.assertEqual(len(rpc.starts),6)
        self.assertLess(rpc.clock-100+rpc.local_wall_seconds,3)

    def test_shared_execution_gas_uses_each_native_gas_proxy_and_invalidates_after_new_provider_work(self):
        def changed(r,rpc):
            for i,row in enumerate(r.history.rows(),1):
                row['graduation']['transition']['graduation_gas_used']=200000+i*10001;r.history.save(row)
            position=r._position
            def turn(row,**kwargs):
                result=position(row,**kwargs)
                if row['id']==native.address(1):
                    rpc.gas=7;rpc.call('eth_gasPrice',[],scope='pons_survivor')
                return result
            r._position=turn
        a,ra,_,_=replay(self,2,price_factor=.6,predecessor=True,latency=0,paced=False,before_step=changed)
        b,rb,rpc,_=replay(self,2,price_factor=.6,latency=0,paced=False,before_step=changed)
        self.assertEqual(a,b);self.assertEqual(ra,rb)
        self.assertEqual(rpc.methods['eth_gasPrice'],4)

    def test_missing_receipt_sender_preserves_body_fallback_and_exposes_its_extra_start(self):
        def missing_sender(r,rpc):
            original=rpc.value
            def value(m,p):
                result=original(m,p)
                if m=='eth_getTransactionReceipt':result.pop('from')
                return result
            rpc.value=value
        p,risk,rpc,_=replay(self,1,price_factor=2.2,before_step=missing_sender)
        self.assertTrue(risk[0]['realization_taken'])
        self.assertEqual(rpc.methods['eth_getTransactionByHash'],1)
        self.assertEqual(len(rpc.starts),7)
        self.assertGreater(rpc.clock-100,3)

    def test_two_simultaneous_partial_realizations_expose_remaining_capacity_deficit(self):
        positions,risk,rpc,_=replay(self,2,price_factor=2.2)
        self.assertTrue(all(r['realization_taken'] for r in risk))
        self.assertEqual(len(rpc.starts),8)
        self.assertGreater(rpc.clock-100,3)
        print('NATIVE_CONCURRENT_EXIT_CAPACITY_BLOCKER',json.dumps(dict(
            action='partial_exit',held_positions=2,physical_starts=len(rpc.starts),starts=rpc.starts,responses=rpc.responses,
            modeled_decision_seconds=rpc.clock-100,native_local_wall_seconds=rpc.local_wall_seconds,
            native_cpu_seconds=rpc.local_cpu_seconds,original_deadline_seconds=3,
            native_accounting_verified=self.native_runtime.book.replay()['verified'])),flush=True)

    def test_missing_history_receipt_keeps_a_fresh_native_hard_stop_and_outstanding_history(self):
        def missing(r,rpc):
            original=rpc.value
            rpc.value=lambda m,p:None if m=='eth_getTransactionReceipt' else original(m,p)
        positions,risk,rpc,_=replay(self,1,price_factor=.6,before_step=missing)
        self.assertEqual(positions[0]['status'],'settled')
        self.assertEqual(risk[0]['last_action']['reason'],'hard_stop')
        self.assertEqual(self.native_runtime.history.rows()[0]['block'],100)
        self.assertLess(rpc.clock-100+rpc.local_wall_seconds,3)

    def test_ordered_settlement_read_is_not_reused_across_provider_or_economic_changes(self):
        from meme_machine.lanes.pons.pons_quotes import canonical_boundary,unchanged_canonical_read
        rpc=ActiveRPC(latency=0,paced=False);self.addCleanup(rpc.close)
        header=rpc.value('eth_getBlockByNumber',['0x65',False])
        with patch('time.monotonic',side_effect=lambda:rpc.clock):
            canonical_boundary(rpc,header,'pons_survivor');proof=rpc.last_canonical_read
            self.assertTrue(unchanged_canonical_read(rpc,proof,header))
            self.assertFalse(unchanged_canonical_read(rpc,dict(proof),header))
            rpc.call('eth_gasPrice',[],scope='pons_survivor')
            self.assertFalse(unchanged_canonical_read(rpc,proof,header))
            canonical_boundary(rpc,header,'pons_survivor');proof=rpc.last_canonical_read
            rpc.clock+=5.001
            self.assertFalse(unchanged_canonical_read(rpc,proof,header))
            rpc.clock=100;canonical_boundary(rpc,header,'pons_survivor');proof=rpc.last_canonical_read
            rpc.provider_fingerprint='rotated'
            self.assertFalse(unchanged_canonical_read(rpc,proof,header))
        self.run_positions(1,proved=False)
        r=self.native_runtime;r.current=r.history.rows()[0];r.rpc=rpc
        execution=dict(quantity=1,acquired=100,block=101,block_hash=header['hash'])
        with patch('time.monotonic',return_value=100):
            count=len(rpc.transports)
            with self.assertRaisesRegex(BoundaryError,'quote_stale'):r.validate_exit(execution,2,100)
            self.assertEqual(len(rpc.transports),count)
            r.final_exit_quote_check=None;r.validate_exit(execution,1,100)
            self.assertEqual(len(rpc.transports),count+1)

    def test_slow_provider_remains_an_explicit_protective_deadline_blocker(self):
        positions,risk,rpc,_=replay(self,1,price_factor=.6,latency=.6)
        self.assertEqual(positions[0]['status'],'settled')
        self.assertEqual(risk[0]['last_action']['action'],'full_exit')
        self.assertGreater(rpc.clock-100,3)
        self.assertTrue(self.native_runtime.sleeve.reconcile()['reconciled'])

    def test_turn_head_expires_and_is_not_restored_or_reused_after_session_rotation(self):
        self.run_positions(1,proved=False)
        r=self.native_runtime;r.current=r.history.rows()[0]
        rpc=ActiveRPC(latency=0,paced=False);self.addCleanup(rpc.close);r.rpc=rpc;r.now=lambda:int(rpc.clock)
        header=rpc.value('eth_getBlockByNumber',['latest',False]);qty=r.book._load(r.current['position'])['tokens']//4
        for cause in ('age','session','restart'):
            rpc.clock=103.1 if cause=='age' else 100.
            r.position_exit_quotes={}
            r.position_exit_head=(header,100,id(rpc),rpc.provider_fingerprint)
            if cause=='session':r.position_exit_head=(*r.position_exit_head[:2],0,rpc.provider_fingerprint)
            if cause=='restart':r.position_exit_head=None
            before=len(rpc.transports)
            with patch('time.time',side_effect=lambda:rpc.clock),patch('time.monotonic',side_effect=lambda:rpc.clock):
                quote=r.exit_quote(qty)
            self.assertIsNotNone(quote)
            self.assertEqual(rpc.transports[before][1],[('eth_getBlockByNumber',['latest',False])])
            self.assertGreaterEqual(quote['acquired'],103.1 if cause=='age' else 100)
