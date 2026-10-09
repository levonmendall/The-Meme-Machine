"""Native read-path comparisons against 20f8398a; synthetic markets, no provider I/O."""
import base64
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
import time
from unittest.mock import patch

from meme_machine.lanes.pump import pumpswap_survivor_runtime as pump_runtime
from meme_machine.lanes.pons import pons_survivor_runtime as pons_runtime,BoundaryError
from meme_machine.lanes.pons import pons_selective_v4 as v4,pons_selective_paper as current
from meme_machine.lanes.pons.pons_current_history import CurrentHistory
from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext
from meme_machine.runtime.robinhood.plane import Plane
from tests.lanes.pons.test_pons_finalization import ExactQuoteRPC,address,graduation
from tests.lanes.pump.test_postgrad import pumpswap_snapshot,mint_account

BASE='20f8398abb738c85160aa36c9a8c36c1feedb287'
ROOT=Path(__file__).resolve().parents[1]
ENDPOINT='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_RESOURCE_PROOF'


def original(path):
    source=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,text=True)
    module=ModuleType(path.replace('/','.').removesuffix('.py')+'_resource_baseline')
    module.__package__=path.rsplit('/',1)[0].replace('/','.')
    module.__file__=str(ROOT/path)
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    return module


class PumpReadTests(unittest.TestCase):
    def runtime(self):
        r=object.__new__(pump_runtime.Runtime);r.now=lambda:100;r.current=dict(id='mint')
        r._provider=lambda *a:None;r.plane=SimpleNamespace(require_usable=lambda scope:None)
        return r

    def test_one_snapshot_is_shared_for_mark_but_settlement_reacquires(self):
        r=self.runtime();state=pumpswap_snapshot(now=100);seen=[]
        r.fresh_state=lambda *a,**kw:(seen.append(kw) or deepcopy(state))
        first=r.exit_quote(10**12,state=state);self.assertEqual(seen,[]);self.assertIsNotNone(first)
        final=r.exit_quote(10**12)
        self.assertEqual(first,final);self.assertEqual(len(seen),1)
        self.assertTrue(seen[0]['maintenance'])

    def test_snapshot_freshness_clock_is_not_renewed_and_stale_input_refreshes(self):
        r=self.runtime();state=pumpswap_snapshot(now=98);seen=[]
        r.fresh_state=lambda *a,**kw:(seen.append(True) or pumpswap_snapshot(now=100))
        self.assertEqual(r.exit_quote(10**12,state=state)['acquired'],98)
        r.now=lambda:104
        self.assertEqual(r.exit_quote(10**12,state=state)['acquired'],100)
        self.assertEqual(len(seen),1)
        with self.assertRaisesRegex(ValueError,'quote_stale'):
            r.validate_exit(dict(quantity=1,market_time=100,acquired=98),1,104)

    def test_failed_evidence_keeps_quote_unavailable(self):
        r=self.runtime();r.plane.require_usable=lambda scope:(_ for _ in ()).throw(ValueError('evidence_missing'))
        self.assertIsNone(r.exit_quote(1000,state=pumpswap_snapshot(now=100)))

    def history_runtime(self,module):
        r=object.__new__(module.Runtime);r.now=lambda:100
        state=pumpswap_snapshot(now=100);state['additional_accounts']={pump_runtime.SOL_USD_ACCOUNT:{}}
        row=dict(id=state['mint'],graduation=dict(at=1,quote_amount=10,mint_amount=100))
        r.current=row;r.confirmations=SimpleNamespace(cluster=lambda wallet:wallet)
        r.rpc=SimpleNamespace()
        r._increment=lambda *a:None
        events=[dict(id='buy',at=99,group='buyer',buy=True,quote=300,tokens=100,authenticated=True)]
        r.history=SimpleNamespace(get=lambda identity:dict(row,complete=True),
            append=lambda *a,**kw:None,facts=lambda *a:([dict(at=30,price='1')],events),prefix=lambda identity:None)
        return r,state

    def test_maintenance_omits_only_qualification_reads_and_preserves_risk_inputs(self):
        base=original('meme_machine/lanes/pump/pumpswap_survivor_runtime.py')
        before,s=self.history_runtime(base);after,_=self.history_runtime(pump_runtime)
        with patch('meme_machine.lanes.pump.runner._postgrad_concentration',return_value=100) as concentration,\
             patch.object(base,'sol_usd_lower_micros',return_value=100000000):
            old=before.reconstruct(s,base.Quotes(s,100))
            self.assertEqual(concentration.call_count,1)
        with patch('meme_machine.lanes.pump.runner._postgrad_concentration',side_effect=AssertionError('qualification read')),\
             patch.object(pump_runtime,'sol_usd_lower_micros',side_effect=AssertionError('qualification oracle')):
            new=after.reconstruct(s,pump_runtime.Quotes(s,100),maintenance=True)
        for key in ('now','demand_events','creator_distribution_safe','exit_liquidity_available','price_points'):
            self.assertEqual(new[key],old[key])
        self.assertIs(new['qualification_evidence_complete'],False)
        self.assertIsNone(new['holder_concentration_bps'])
        with patch('meme_machine.lanes.pump.runner._postgrad_concentration',return_value=100) as concentration,\
             patch.object(pump_runtime,'sol_usd_lower_micros',return_value=100000000):
            full=after.reconstruct(s,pump_runtime.Quotes(s,100))
            self.assertEqual(concentration.call_count,1)
            self.assertTrue(full['qualification_evidence_complete'])
            for key in old:self.assertEqual(full[key],old[key])

    def test_compact_postgrad_concentration_matches_largest_with_custody_excluded(self):
        from meme_machine.lanes.pump.concentration import ConcentrationReader
        state=pumpswap_snapshot();state['accounts']={'mint':mint_account()}
        custody=state['state']['base_vault'];values=[100000000000000*(i+1) for i in range(7)]
        largest=dict(context=dict(slot=100),value=[dict(address=str(i),amount=str(n)) for i,n in enumerate(values)]+[
            dict(address=custody,amount=str(900000000000000))])
        compact=dict(context=dict(slot=100),value=[dict(pubkey=row['address'],account=dict(data=[
            base64.b64encode(int(row['amount']).to_bytes(8,'little')).decode(),'base64'])) for row in largest['value']])
        self.assertEqual(ConcentrationReader._decode_largest(largest,state['mint'],state),
            ConcentrationReader._decode_program_scan(compact,state['mint'],state))
        compact['context']['slot']=1
        with self.assertRaisesRegex(Exception,'stale_concentration'):
            ConcentrationReader._decode_program_scan(compact,state['mint'],state)


class PonsQuoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.rpc=ExactQuoteRPC();base_value=self.rpc.value
        self.head=100;self.gas=1;self.failed=False
        def value(method,params):
            if self.failed:raise BoundaryError('provider_transport_failure')
            if method=='eth_getBlockByNumber':
                n=self.head if params[0]=='latest' else int(params[0],16)
                return dict(number=hex(n),hash='0x'+f'{n:064x}',parentHash='0x'+f'{n-1:064x}',timestamp=hex(n))
            if method=='eth_gasPrice':return hex(self.gas)
            return base_value(method,params)
        self.rpc.value=value
        self.clock=[100.]
        self.enterContext(patch('time.time',side_effect=lambda:self.clock[0]))
        self.enterContext(patch('time.monotonic',side_effect=lambda:self.clock[0]))

    def runtime(self,cls=pons_runtime.Runtime):
        r=object.__new__(cls);r.rpc=self.rpc;r.root=Path(self.tmp.name)
        r.current=dict(graduation=graduation(1));r.now=lambda:int(self.clock[0])
        r.position_exit_quotes={}
        return r

    def counts(self):
        methods=Counter(m for _,calls in self.rpc.transports for m,_ in calls)
        return dict(elements=sum(methods.values()),transports=len(self.rpc.transports),methods=methods)

    def test_immediate_full_exit_reuses_exact_state_and_reacquires_mutable_gas(self):
        base=original('meme_machine/lanes/pons/pons_survivor_runtime.py')
        before=self.runtime(base.Runtime);qty=10**18
        old=[before.exit_quote(qty),before.exit_quote(qty)];count=self.counts()
        self.rpc.transports=[];after=self.runtime();new=[after.exit_quote(qty),after.exit_quote(qty)]
        self.assertEqual(new,old);self.assertEqual(count['elements'],12)
        self.assertEqual(self.counts()['elements'],8);self.assertEqual(self.counts()['transports'],3)
        self.gas=2;self.clock[0]+=1
        updated=after.exit_quote(qty);self.assertEqual(updated['acquired'],100)
        self.assertEqual(updated['gas'],2*new[0]['gas'])
        self.assertEqual(updated['net_proceeds'],new[0]['net_proceeds']-new[0]['gas'])

    def test_material_state_or_canonical_head_change_requires_full_reconstruction(self):
        r=self.runtime();qty=10**18;r.exit_quote(qty);before=self.counts()
        self.head=101;self.clock[0]=101
        q=r.exit_quote(qty)
        self.assertEqual(q['block'],101);self.assertEqual(self.counts()['elements']-before['elements'],8)
        self.assertEqual(self.counts()['methods']['eth_getCode'],2)

    def test_partial_quantity_and_expired_evidence_never_use_full_quote(self):
        r=self.runtime();qty=10**18;r.exit_quote(qty);before=self.counts()
        q=r.exit_quote(qty//4);self.assertEqual(q['quantity'],qty//4)
        self.assertEqual(self.counts()['elements']-before['elements'],6)
        self.clock[0]=106;self.head=106;before=self.counts()
        self.assertIsNotNone(r.exit_quote(qty));self.assertEqual(self.counts()['elements']-before['elements'],6)

    def test_provider_failure_during_reuse_cannot_return_old_execution(self):
        r=self.runtime();r.exit_quote(10**18);self.failed=True
        self.assertIsNone(r.exit_quote(10**18));self.assertEqual(r.position_exit_quotes,{})

    def test_original_single_stream_quote_scope_rejects_normal_block_gaps(self):
        base=original('meme_machine/lanes/pons/pons_survivor_runtime.py')
        native=original('meme_machine/lanes/pons/pons_natural_paper.py')
        old=self.runtime(base.Runtime)
        with patch('meme_machine.lanes.pons.pons_natural_paper._ledger_for_quote',native._ledger_for_quote):
            self.assertIsNotNone(old.exit_quote(10**18))
        self.clock[0]=103;self.head=130
        value=self.rpc.value
        def market(method,params):
            row=value(method,params)
            if method=='eth_getBlockByNumber':row=dict(row,timestamp=hex(int(self.clock[0])))
            return row
        self.rpc.value=market
        with patch('meme_machine.lanes.pons.pons_natural_paper._ledger_for_quote',native._ledger_for_quote):
            self.assertIsNone(old.exit_quote(10**18))
        fixed=self.runtime();self.assertIsNotNone(fixed.exit_quote(10**18))
        self.clock[0]=106;self.head=160
        self.assertIsNotNone(fixed.exit_quote(10**18))

    def test_full_72_hours_native_quotes_keep_freshness_cadence_and_bounded_evidence(self):
        # Native decoder, pinning and ledger; transport is deterministic and
        # never calls a provider. The final turn also quotes the hold deadline.
        counts=Counter();value=self.rpc.value
        def market(method,params):
            counts[method]+=1;row=value(method,params)
            if method=='eth_getBlockByNumber':row=dict(row,timestamp=hex(int(self.clock[0])))
            return row
        self.rpc.value=market
        self.rpc.call=lambda m,p,**kw:market(m,p)
        self.rpc.batch=lambda calls,**kw:[market(m,p) for m,p in calls]
        r=self.runtime()
        for turn in range(86401):
            self.clock[0]=100+3*turn;self.head=100+30*turn
            r.position_exit_quotes={}
            q=r.exit_quote(10**18)
            self.assertIsNotNone(q,turn);self.assertEqual(q['acquired'],self.clock[0])
            self.assertEqual(q['block'],self.head)
            if turn%10000==0:r=self.runtime()
        self.assertEqual(counts['eth_call'],172802)
        self.assertEqual(sum(counts.values()),518406)
        self.assertFalse((Path(self.tmp.name)/'quote-evidence.sqlite').exists())

    def test_quote_cache_has_no_next_turn_or_restart_authority(self):
        r=self.runtime()
        def manage(row,**kwargs):
            self.assertEqual(r.position_exit_quotes,{});r.position_exit_quotes[1]={};raise BoundaryError('test_exit_pending')
        r._manage_position=manage
        for _ in range(2):
            with self.assertRaisesRegex(BoundaryError,'test_exit_pending'):r._position({})
            self.assertIsNone(r.position_exit_quotes)

    def test_session_rotation_preserves_original_freshness_and_membership_fence(self):
        from meme_machine.lanes.pons.position_sessions import PositionSessions
        from tests.lanes.pons.test_position_sessions import Rpc
        from meme_machine.lanes.pons.pons_quotes import quote_deadline
        old=Rpc(200);new=Rpc();r=PositionSessions(old,lambda:new,lambda *a:None)
        r.evidence_pins={'0x1':'known_hash'}
        with quote_deadline(r,99):
            self.assertEqual(old.evidence_deadline,104)
            r.call('quote',[])
            self.assertEqual(new.evidence_deadline,104);self.assertEqual(new.evidence_pins,old.evidence_pins)
        self.assertIsNone(new.evidence_deadline)


class RollingV4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.plane=Plane(Path(self.tmp.name)/'plane.sqlite');self.addCleanup(self.plane.close)
        self.history=CurrentHistory(self.plane,ENDPOINT);self.requests=[];self.fork=False
        self.key=pons_runtime.PoolKey(pons_runtime.ZERO,address(1),0,60,address(2));self.pool=self.key.pool_id()
        def call(method,params,scope):
            self.requests.append((method,params));n=int(params[0],16)
            return dict(number=hex(n),hash=('fork' if self.fork else str(n)),timestamp=hex(n//10))
        self.rpc=SimpleNamespace(call=call,batch=lambda calls,scope:[call(m,p,scope) for m,p in calls])

    def tape(self,endpoint,**kw):
        self.requests.append(('range',(kw['start_block'],kw['end_block'])))
        rows=[dict(identity=str(n),block=n,event_at=n//10,group=address(n%7+1),side='buy' if n%4 else 'sell',
            quote=n+100,tokens=10,price_index=n+1,transaction_index=0,log_index=0)
            for n in range(kw['start_block'],kw['end_block']+1)]
        return v4.activity_summary(rows,provider_sessions=[])

    def turn(self,n):
        header=dict(number=hex(n),hash=str(n),timestamp=hex(n//10))
        return v4.rolling_position_activity(ENDPOINT,rpc=self.rpc,history=self.history,pool_id=self.pool,
            key=self.key,token=address(1),header=header)

    def test_only_uncovered_tail_preserves_exact_busy_and_quiet_window(self):
        with patch.object(v4,'collect_v4_activity',side_effect=self.tape),\
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.rpc):
            for n in (200,250,300,350):
                result=self.turn(n)
                from meme_machine.lanes.pons.pons_selective_acquisition import _header_search
                first=int(_header_search(self.rpc,n,n//10,n//10-15,{} )['number'],16)
                original=self.tape(ENDPOINT,start_block=first,end_block=n)
                for key in original:self.assertEqual(result[key],original[key])
            queries=[p for m,p in self.requests if m=='range']
            self.assertIn((201,250),queries);self.assertIn((251,300),queries)
            self.assertEqual(self.history.get(self.pool)['block'],350)
            before=len([1 for m,p in self.requests if m=='range'])
            same=self.turn(350);self.assertEqual(same,result)
            self.assertEqual(len([1 for m,p in self.requests if m=='range']),before+1)
            self.assertEqual([p for m,p in self.requests if m=='range'][-1],(351,350))

    def test_restart_retains_window_and_duplicate_events_are_suppressed(self):
        with patch.object(v4,'collect_v4_activity',side_effect=self.tape),\
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.rpc):
            self.turn(200)
            self.history=CurrentHistory(self.plane,ENDPOINT)
            new=self.turn(250);again=self.turn(250)
            self.assertEqual(new,again)
            self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0],192)

    def test_reorg_invalidates_observation_history_and_cannot_publish_success(self):
        with patch.object(v4,'collect_v4_activity',side_effect=self.tape),\
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.rpc):
            self.turn(200);self.fork=True
            with self.assertRaisesRegex(BoundaryError,'canonical_membership'):self.turn(250)
            self.assertIsNone(self.history.get(self.pool))
            self.assertEqual(self.plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0],0)

    def test_interrupted_acquisition_retains_original_complete_watermark(self):
        with patch.object(v4,'collect_v4_activity',side_effect=self.tape),\
             patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=self.rpc):
            self.turn(200);before=self.history.get(self.pool)
        with patch.object(v4,'collect_v4_activity',side_effect=BoundaryError('provider_transport_failure')):
            with self.assertRaisesRegex(BoundaryError,'transport_failure'):self.turn(250)
        self.assertEqual(self.history.get(self.pool),before)

    def sparse(self,timestamp,n):
        def header(method,params,scope):
            height=int(params[0],16)
            return dict(number=hex(height),hash=str(height),timestamp=hex(timestamp(height)))
        rpc=SimpleNamespace(call=header,batch=lambda calls,scope:[header(m,p,scope) for m,p in calls])
        def tape(endpoint,**kw):
            result=self.tape(endpoint,**kw)
            for row in result['swaps']:row['event_at']=timestamp(row['block'])
            return v4.activity_summary(result['swaps'])
        with patch.object(v4,'collect_v4_activity',side_effect=tape):
            h=header('',[hex(n)],'')
            result=v4.rolling_position_activity(ENDPOINT,rpc=rpc,history=self.history,pool_id=self.pool,
                key=self.key,token=address(1),header=h)
            from meme_machine.lanes.pons.pons_selective_acquisition import _header_search
            first=_header_search(rpc,n,timestamp(n),timestamp(n)-15,{n:h})
            expected=tape(ENDPOINT,start_block=int(first['number'],16),end_block=n)
        for key in expected:self.assertEqual(result[key],expected[key])
        return result

    def test_exact_original_boundary_includes_last_block_before_a_timestamp_gap(self):
        for n in (200,250,300,350):self.sparse(lambda block:(block//10)*10,n)

    def test_gap_beyond_retention_keeps_required_boundary_events_through_restart(self):
        timestamp=lambda block:block//10 if block<=200 else 1000+block//10
        self.sparse(timestamp,200);result=self.sparse(timestamp,250)
        self.assertIn('200',[e['identity'] for e in result['swaps']])
        self.history=CurrentHistory(self.plane,ENDPOINT)
        result=self.sparse(timestamp,300)
        self.assertIn('200',[e['identity'] for e in result['swaps']])
        result=self.sparse(timestamp,350)
        self.assertNotIn('200',[e['identity'] for e in result['swaps']])

    def test_provider_gap_recovers_only_original_required_window(self):
        with patch.object(v4,'collect_v4_activity',side_effect=self.tape):
            self.turn(200);self.requests=[]
            result=self.turn(2000)
        ranges=[p for m,p in self.requests if m=='range']
        self.assertEqual(ranges,[(1859,2000)])
        self.assertEqual(result['swaps'][0]['block'],1859)
        self.assertGreater(self.history.get(self.pool)['from_time'],20)


class CurveTrajectoryTests(unittest.TestCase):
    def test_current_trajectory_shares_only_canonically_proved_history(self):
        from meme_machine.lanes.pons.pons_current_history import _active
        from meme_machine.lanes.pons.pons_selective_acquisition import _trajectory
        from meme_machine.lanes.pons.abi import calldata
        counts=Counter();fork=[False]
        class Rpc:
            def __init__(self):self.used=0;self.counts=Counter();self.per_scope=190;self.evidence_pins={}
            def call(self,m,p,scope):return self.batch([(m,p)],scope=scope)[0]
            def batch(self,calls,scope):
                counts['transports']+=1;self.used+=len(calls);self.counts[scope]+=len(calls);out=[]
                for m,p in calls:
                    counts[m]+=1
                    if m=='eth_getBlockByNumber':
                        n=int(p[0],16);out.append(dict(number=hex(n),hash='fork' if fork[0] else str(n),timestamp=hex(n//10)))
                    elif m=='eth_call':
                        value=0 if p[0]['data']==calldata('launchedAt()') else int(p[-1],16)*100
                        out.append('0x'+f'{value:064x}')
                    else:raise AssertionError(m)
                return out
            def telemetry(self):return dict(used=self.used)
        def factory(*a,**kw):
            counts['eth_chainId']+=1;counts['transports']+=1;return Rpc()
        history=SimpleNamespace();token=_active.set(history)
        self.addCleanup(lambda:_active.reset(token))
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=factory):
            old_counts=Counter();new_counts=Counter()
            for n in range(200,1201,50):
                candidate=dict(curve=address(1),block=n,header=dict(number=hex(n),hash=str(n),timestamp=hex(n//10)),
                    state=SimpleNamespace(real_quote=n*100),record=dict(graduationThreshold=1000000))
                counts.clear();old=_trajectory(ENDPOINT,candidate);old_counts.update(counts)
                counts.clear();new=current._position_trajectory(ENDPOINT,candidate);new_counts.update(counts)
                self.assertEqual(new[:2],old[:2])
            self.assertLess(new_counts['eth_getBlockByNumber'],old_counts['eth_getBlockByNumber'])
            self.assertLess(new_counts['eth_chainId'],old_counts['eth_chainId'])
            print('RESOURCE_TRACE '+json.dumps(dict(case='curve_trajectory_21_turns_10_blocks_per_second',
                before=old_counts,after=new_counts),sort_keys=True))
            fork[0]=True
            with self.assertRaisesRegex(BoundaryError,'canonical_membership'):
                current._position_trajectory(ENDPOINT,candidate)
            self.assertEqual(len(history.curve_evidence_context.cache.headers_by_number),0)

    def test_fifty_block_normal_delta_does_not_rebuild_sixty_seconds(self):
        from meme_machine.lanes.pons.pons_current_history import _active
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');self.addCleanup(plane.close)
            history=CurrentHistory(plane,ENDPOINT);token=_active.set(history);self.addCleanup(lambda:_active.reset(token))
            history.remember(address(1),dict(number=hex(1000),hash='1000',timestamp=hex(100)),[],from_time=40)
            h=dict(number=hex(1050),hash='1050',timestamp=hex(105))
            with patch.object(current,'_read_curve_logs',return_value=([],[])) as read:
                current._curve_logs(ENDPOINT,address(1),h)
            self.assertEqual(read.call_args.kwargs,dict(after_block=1000,expected_previous_hash='1000'))


class V4WitnessTests(unittest.TestCase):
    def test_native_authentication_preserves_canonical_before_receipt_ordering_and_swaps(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.identity import load
        before=original('meme_machine/lanes/pons/pons_selective_v4.py')
        tape=Tape();tape.counts=Counter();tape.per_scope=190
        token=tape.tokens[0];record=tape.records[token]
        key=pons_runtime.PoolKey(pons_runtime.ZERO,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        opts=dict(pool_id=key.pool_id(),key=key,token=token,start_block=tape.grad,end_block=tape.grad+9)
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape):
            old=before.collect_v4_activity(ENDPOINT,**opts)
            old_counts=dict(methods=dict(tape.methods),transports=tape.batches)
            tape.methods.clear();tape.batches=0;tape.used=0
            new=v4.collect_v4_activity(ENDPOINT,**opts)
            new_counts=dict(methods=dict(tape.methods),transports=tape.batches)
        self.assertGreater(len(old['swaps']),0)
        self.assertEqual({k:v for k,v in new.items() if k!='provider_sessions'},
            {k:v for k,v in old.items() if k!='provider_sessions'})
        self.assertEqual(new_counts['methods'],old_counts['methods'])
        self.assertEqual(new_counts['transports'],old_counts['transports'])
        print('RESOURCE_TRACE '+json.dumps(dict(case='canonical_before_receipts_unchanged_cold_demand',before=old_counts,after=new_counts),sort_keys=True))

    def test_canonical_failure_does_not_buy_receipts_or_authorize_evidence(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.identity import load
        tape=Tape();tape.counts=Counter();tape.per_scope=190
        token=tape.tokens[0];record=tape.records[token]
        key=pons_runtime.PoolKey(pons_runtime.ZERO,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        tape.forks[tape.grad]=1 # retained log hashes now disagree with numeric canonical headers
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',return_value=tape):
            with self.assertRaisesRegex(BoundaryError,'canonical_header_membership'):
                v4.collect_v4_activity(ENDPOINT,pool_id=key.pool_id(),key=key,token=token,
                    start_block=tape.grad,end_block=tape.grad+9)
        self.assertNotIn('eth_getTransactionReceipt',tape.methods)

    def test_equivalent_consumers_reuse_authenticated_receipts_and_senders_but_not_membership(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.identity import load
        tape=Tape();tape.counts=Counter();tape.per_scope=190
        token=tape.tokens[0];record=tape.records[token]
        key=pons_runtime.PoolKey(pons_runtime.ZERO,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        ctx=SelectiveEvidenceContext(ENDPOINT)
        opts=dict(pool_id=key.pool_id(),key=key,token=token,start_block=tape.grad,end_block=tape.grad+9,evidence_context=ctx)
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=lambda *a,**kw:tape.provider()):
            first=v4.collect_v4_activity(ENDPOINT,**opts)
            before=dict(methods=dict(tape.methods),physical=tape.batches,elements=tape.logical,response_bytes=tape.response_bytes)
            tape.methods.clear();tape.batches=0;tape.logical=0;tape.response_bytes=0
            second=v4.collect_v4_activity(ENDPOINT,**opts)
            after=dict(methods=dict(tape.methods),physical=tape.batches,elements=tape.logical,response_bytes=tape.response_bytes)
            self.assertEqual(first['swaps'],second['swaps'])
            self.assertEqual(after['methods']['eth_getBlockByNumber'],9)
            self.assertNotIn('eth_getTransactionReceipt',after['methods'])
            self.assertNotIn('eth_getTransactionByHash',after['methods'])
            self.assertLess(after['physical'],before['physical']);self.assertLess(after['elements'],before['elements'])
            self.assertEqual(ctx.cache.telemetry()['receipt_hit'],9)
            # Retained orphan bodies must not answer current numeric membership.
            tape.forks[tape.grad]=1
            with self.assertRaisesRegex(BoundaryError,'canonical_header_membership'):
                v4.collect_v4_activity(ENDPOINT,**opts)
        print('RESOURCE_TRACE',json.dumps(dict(case='equivalent_v4_readers',before=before,after=after,
            cache=ctx.cache.telemetry(),cross_block_quote_reuse=False),sort_keys=True),flush=True)

    def test_real_cached_receipt_payloads_obey_byte_and_count_bounds(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import ImmutableEvidenceCache,CACHE_MAP_BYTES
        cache=ImmutableEvidenceCache()
        for i in range(700):
            tx='0x'+f'{i:064x}';cache.remember_receipt(tx,'block',dict(transactionHash=tx,blockHash='block',logs=[],payload='x'*32768))
        actual=sum(len(json.dumps([key,value],sort_keys=True,separators=(',',':')).encode()) for key,value in cache.receipts.items())
        self.assertLessEqual(actual,CACHE_MAP_BYTES);self.assertLess(len(cache.receipts),700)
        self.assertEqual(cache.telemetry()['accounted_cache_bytes'],actual)
        self.assertIsNone(cache.receipt('0x'+f'{0:064x}','block'))


class EnvelopeModelTests(unittest.TestCase):
    def test_quote_only_demand_cannot_fit_old_element_envelope_and_never_enlarges_it(self):
        from engineering.continuation_resources.model import build
        result=build();limits=result['proposal_verification']
        self.assertEqual(limits['rpc_elements']['quote_only'],518400)
        self.assertGreater(limits['rpc_elements']['quote_only'],limits['rpc_elements']['proposed'])
        self.assertIsNone(result['recommended_funded_envelope'])
        self.assertFalse(limits['rpc_cu']['adequate'])
        self.assertEqual(result['live_provider_calls'],0)

    def test_compact_failure_cost_is_charged_and_never_presented_as_guaranteed_savings(self):
        from engineering.continuation_resources.model import build
        result=build()['pump_72_hours']
        self.assertGreater(result['compact_failure_every_turn']['rpc_cu'],result['current_before']['rpc_cu'])
        self.assertEqual(result['compact_failure_every_turn']['methods']['getTokenLargestAccounts'],51840)

    def test_stress_exceeds_shared_provider_ceiling_even_after_witness_batching(self):
        from engineering.continuation_resources.model import build
        result=build()['scenarios']['high_activity']['after']
        self.assertGreater(result['minimum_physical_rps_under_scenario'],2)
        self.assertGreater(result['rpc_elements'],500000)
        self.assertGreater(result['rpc_cu'],24000000)

    def test_old_contract_bootstrap_limits_are_retained_exactly(self):
        from engineering.continuation_resources.model import build
        from meme_machine.operational.bounded_provider import LIMITS
        b=build()['bootstrap']
        self.assertEqual((b['rpc_cu'],b['rpc_elements'],b['physical_attempts'],b['native_bytes']),
            (LIMITS['rpc_cu'],LIMITS['rpc_elements'],LIMITS['http_attempts'],LIMITS['native_bytes']))
        self.assertEqual((b['seconds'],b['funding_seconds'],b['maximum_gross_usd'],b['modeled_spend_usd']),
            (1800,1200,'25','3'))


class LongHoldStorageTests(unittest.TestCase):
    def setUp(self):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'current.sqlite';self.clock=[100]
        self.store=Store(self.path,max_records=8192);self.addCleanup(lambda:self.store.close())
        self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,
            clock_ns=lambda:int(self.clock[0]*10**9))

    def quote(self,at,side,quantity,proceeds,*,label='selective-v4-mark-test',block=None):
        from meme_machine.lanes.pons.evidence import Stamp
        from meme_machine.lanes.pons.pons_natural_paper import LocalFreshQuote,_ledger_for_quote
        block=at*10 if block is None else block
        stamp=Stamp(4663,block,'0x'+f'{block:064x}',at,at,'confirmed','natural')
        ledger=_ledger_for_quote(self.store,stamp,'0x'+f'{block-1:064x}',label,local_freshness_seconds=.01)
        return LocalFreshQuote('m',side,quantity,proceeds,2,0,stamp,acquisition_latency_seconds=.01),ledger

    def fill(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        self.paper.reserve('x',market='m',amount=100,gas_budget=2,now=100,
            features=PartialAccountingTests().features(100))
        self.clock[0]=102;q,ledger=self.quote(102,'buy',100,1000,label='selective-entry')
        return self.paper.advance('x',now=102,action='entry',quote=q,finality_ledger=ledger)

    def test_original_current_record_capacity_is_exhausted_before_tail_deadline(self):
        from meme_machine.lanes.pons.evidence import Stamp
        legacy=original('meme_machine/lanes/pons/pons_natural_paper.py')
        count=0
        with self.assertRaisesRegex(BoundaryError,'storage_capacity_stop_admission'):
            while count<25920:
                at=100+5*count;stamp=Stamp(4663,count*50+1,'h'+str(count),at,at,'confirmed','natural')
                legacy._ledger_for_quote(self.store,stamp,'parent','selective-v4-mark-'+str(count),local_freshness_seconds=.01)
                count+=1
        self.assertEqual(count,8191)  # one real genesis record shares the bound
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],8192)
        print('STORAGE_TRACE',json.dumps(dict(original_current_stop_turn=count,
            stop_hours=count*5/3600,body_bytes=self.store.db.execute('SELECT SUM(length(CAST(body AS BLOB))) FROM records').fetchone()[0],
            sqlite_bytes=self.path.stat().st_size)),flush=True)

    def test_original_survivor_scope_stops_before_its_sqlite_record_limit(self):
        from meme_machine.lanes.pons.evidence import Store,Stamp
        legacy=original('meme_machine/lanes/pons/pons_natural_paper.py')
        path=Path(self.tmp.name)/'original-survivor-quote-evidence.sqlite'
        store=Store(path);self.addCleanup(store.close)
        for turn in range(4):
            at=100+3*turn
            stamp=Stamp(4663,turn+1,'h'+str(turn+1),at,at,'confirmed','natural')
            ledger=legacy._ledger_for_quote(store,stamp,'h'+str(turn),'survivor_exit',local_freshness_seconds=.01)
            ledger.check_identity(stamp)
        with self.assertRaisesRegex(BoundaryError,'finality_capacity'):
            stamp=Stamp(4663,5,'h5',112,112,'confirmed','natural')
            legacy._ledger_for_quote(store,stamp,'h4','survivor_exit',local_freshness_seconds=.01)
        self.assertEqual(store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],4)
        print('STORAGE_TRACE',json.dumps(dict(original_survivor_quote_scope_stop_turn=4,
            sqlite_record_capacity=10000,sqlite_bytes=path.stat().st_size,
            classification='actual original four-block Finality scope fails before record limit; fast-chain gaps fail earlier')),flush=True)

    def test_same_scope_and_exact_identity_are_idempotent_but_new_availability_is_distinct(self):
        from dataclasses import replace
        from meme_machine.lanes.pons.evidence import Stamp
        from meme_machine.lanes.pons.finality import Finality
        from meme_machine.lanes.pons.pons_natural_paper import _ledger_for_quote
        stamp=Stamp(4663,1,'h1',100,100,'confirmed','natural')
        ledger=Finality(self.store,'history-authority')
        self.assertTrue(ledger.observe(stamp,'p',local_freshness_seconds=.01))
        self.assertFalse(ledger.observe(replace(stamp,observed_at=103),'p',local_freshness_seconds=.01))
        ledger.check_identity(stamp)
        with self.assertRaisesRegex(BoundaryError,'observation_identity_disagreement'):
            ledger.check_identity(replace(stamp,observed_at=103))
        for at in (100,100,103):
            q=_ledger_for_quote(self.store,replace(stamp,observed_at=at),'p','selective-v4-mark-test',local_freshness_seconds=.01)
            q.check_identity(replace(stamp,observed_at=at))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM records WHERE category='confirmed_block'").fetchone()[0],3)

    def test_quote_expiration_does_not_grant_history_or_delete_history_dependencies(self):
        from meme_machine.runtime.storage import compact_pons_observations
        q,ledger=self.quote(100,'sell',1000,130)
        ledger.bind('history-consumer',[q.stamp],asof=100)
        before=self.store.get('confirmed_block',ledger._id(q.stamp.block_hash))
        compact_pons_observations(self.paper,300)
        self.assertEqual(self.store.get('confirmed_block',ledger._id(q.stamp.block_hash)),before)
        with self.assertRaisesRegex(BoundaryError,'stale_state'):
            q.check(106,'m','sell',1000,'natural',finality_ledger=ledger)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM pons_journal_checkpoint').fetchone()[0],0)

    def test_retention_rollback_keeps_exact_evidence_and_accounting(self):
        from meme_machine.runtime.storage import compact_pons_observations
        self.fill();q,ledger=self.quote(105,'sell',1000,130)
        self.clock[0]=105;self.paper.advance('x',now=105,action='mark',quote=q,finality_ledger=ledger)
        before=self.paper.reconcile();rows=list(self.store.db.execute('SELECT * FROM records ORDER BY category,id'))
        self.store.db.execute("CREATE TRIGGER injected_retention_cut BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'injected retention cut'); END")
        with self.assertRaisesRegex(Exception,'injected retention cut'):compact_pons_observations(self.paper,300)
        self.assertEqual(rows,list(self.store.db.execute('SELECT * FROM records ORDER BY category,id')))
        self.assertEqual(self.paper.reconcile(),before)
        self.store.db.execute('DROP TRIGGER injected_retention_cut')
        compact_pons_observations(self.paper,300)
        self.assertEqual(self.paper.reconcile(),before)
        self.assertGreater(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_actual_64_mib_page_pressure_preserves_pending_exit_and_reports_capacity(self):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        self.fill();self.clock[0]=103
        pending=self.paper.advance('x',now=103,action='exit_intent',exit_tokens=1000)
        before=self.paper.reconcile();count=0
        with self.assertRaisesRegex(BoundaryError,'evidence_store_page_capacity'):
            while count<8192:
                self.store.put('large_captured_evidence',str(count),dict(payload='x'*32700));count+=1
        self.assertGreater(count,1000);self.assertLess(count,8192)
        pages=self.store.db.execute('PRAGMA page_count').fetchone()[0]
        cap=self.store.db.execute('PRAGMA max_page_count').fetchone()[0]
        self.assertEqual(cap,16384);self.assertLessEqual(pages,cap)
        self.assertEqual(self.paper._get('x'),pending);self.assertEqual(self.paper.reconcile(),before)
        self.store.close();self.store=Store(self.path,max_records=8192)
        self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH)
        self.assertEqual(self.paper._get('x'),pending);self.assertEqual(self.paper.reconcile(),before)
        print('STORAGE_TRACE',json.dumps(dict(page_pressure_records=count,sqlite_pages=pages,
            page_size=self.store.db.execute('PRAGMA page_size').fetchone()[0],pending_exit_preserved=True)),flush=True)

    def test_full_36_hour_current_bridge_actual_journals_quotes_and_restart(self):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE,JOURNAL_CATEGORY
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH,runner_action
        from meme_machine.lanes.pons.pons_selective_recovery import LifecycleState
        from meme_machine.runtime.storage import compact_pons_observations
        opened=self.fill()
        evaluation=dict(token='token',curve='m',source_transaction='fixture',market_events=[],
            candidate=dict(curve='m',token='token',auth={'fixture':True},record={}),
            vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
                trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}))
        state=LifecycleState.create(self.store,'x',evaluation,10000,21000,opened_at=102,last_block=1020)
        self.paper.controller_context=state.checkpoint
        # Native partial accounting precedes the extended tail bridge.
        state.high_water=12000;state.high_at=104;state.first_tail_crossed_at=104
        self.clock[0]=104;self.paper.advance('x',now=104,action='exit_intent',exit_tokens=250)
        self.clock[0]=106;q,ledger=self.quote(106,'sell',250,60,label='selective-v4-exit')
        p=self.paper.advance('x',now=106,action='exit',quote=q,finality_ledger=ledger)
        state.acknowledge(p);self.assertTrue(state.partial_taken);self.assertEqual(p['tokens'],750)
        original_risk=original('meme_machine/lanes/pons/pons_selective_continuation.py')
        maximum=0;started=time.process_time();checkpoint=None
        facts=dict(current_after_cost_return_positive=True,after_cost_return_bps=12000,
            fresh_generation_state=True,fresh_executable_exit_quote=True,canonical_lineage_and_venue=True,
            creator_distribution_safe=True,hard_concentration_safe=True,executable_exit_liquidity=True,
            no_persistent_confirmed_demand_failure=True,no_irreversible_exit_intent=True)
        for turn in range(1,25921):
            at=102+turn*5;self.clock[0]=at
            rbps=12000+turn;state.high_water=rbps;state.high_at=at
            args=dict(tokens=750,partial_taken=True,after_cost_return_bps=rbps,
                high_water_return_bps=rbps,seconds_since_high=0,new_buyer_growth=1,
                buy_quote=300,sell_quote=100,soft_deterioration_streak=0)
            action=runner_action(**args);self.assertEqual(action,original_risk.runner_action(**args))
            action=current._bridge_action(state,dict(facts,observed_at=at),action,p,now=at)
            if turn<25920:self.assertEqual(action['action'],'hold')
            else:self.assertEqual((action['action'],action['reason']),('full_exit','max_total_hold'))
            q,ledger=self.quote(at,'sell',750,2+77*(10000+rbps)//10000,
                label='selective-v4-mark-'+str(p['version']),block=1020+50*turn)
            state.remember_action(action,p)
            p=self.paper.advance('x',now=at,action='mark',quote=q,finality_ledger=ledger)
            if turn%500==0:
                maximum=max(maximum,self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0])
                self.assertLess(maximum,8192)
            if turn in (5000,15000,25919):
                before=self.paper.reconcile();checkpoint=deepcopy(vars(state))
                self.store.close();self.store=Store(self.path,max_records=8192)
                self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,
                    clock_ns=lambda:int(self.clock[0]*10**9))
                state=LifecycleState.restore(self.paper,'x');self.paper.controller_context=state.checkpoint
                self.assertEqual(vars(state),checkpoint);self.assertEqual(self.paper.reconcile(),before)
                self.assertEqual(state.opened_at,102);self.assertTrue(state.partial_taken)
        self.clock[0]=129702;pending=self.paper.advance('x',now=129702,action='exit_intent',exit_tokens=750)
        # A missing provider quote cannot settle. The native intent survives restart.
        self.assertEqual(pending['status'],'exit_pending');before=self.paper.reconcile()
        self.store.close();self.store=Store(self.path,max_records=8192)
        self.paper=SelectivePaper(self.store,STRATEGY_NAMESPACE,10000,natural_policy_hash=POLICY_HASH,
            clock_ns=lambda:int(self.clock[0]*10**9))
        self.assertEqual(self.paper.reconcile(),before)
        state=LifecycleState.restore(self.paper,'x');self.paper.controller_context=state.checkpoint
        self.clock[0]=129710;q,ledger=self.quote(129710,'sell',750,360,label='selective-v4-exit')
        closed=self.paper.advance('x',now=129710,action='exit',quote=q,finality_ledger=ledger)
        self.assertEqual(closed['status'],'settled');self.assertEqual(closed['realized_proceeds'],416)
        reconciliation=self.paper.reconcile();self.assertTrue(reconciliation['cash_basis_conservation'])
        self.assertTrue(reconciliation['accounting']['x']['integral_complete'])
        compact_pons_observations(self.paper,130000)
        self.assertEqual(self.paper.reconcile(),reconciliation)
        self.assertEqual(self.store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        print('STORAGE_TRACE',json.dumps(dict(current_monitor_turns=25920,maximum_records=maximum,
            final_records=self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],
            journal_rows=self.store.db.execute('SELECT COUNT(*) FROM records WHERE category=?',(JOURNAL_CATEGORY,)).fetchone()[0],
            maximum_sqlite_bytes=self.path.stat().st_size,cpu_seconds=time.process_time()-started,
            restarts=4,original_opened_at=state.opened_at,high_water=state.high_water,partial_quantity=750,
            final_booked_realized=closed['realized_pnl'])),flush=True)


class LongHoldHistoryTests(unittest.TestCase):
    def test_full_36_hour_current_v4_rolling_history_preserves_original_windows(self):
        from meme_machine.lanes.pons.pons_selective_acquisition import _header_search
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'current-history.sqlite';plane=Plane(path)
            history=CurrentHistory(plane,ENDPOINT);pool='0x'+'ab'*32
            counts=Counter();now=[200.];started=time.process_time();maximum=0
            def header(method,params,scope):
                n=int(params[0],16);counts[method]+=1
                return dict(number=hex(n),hash='h'+str(n),timestamp=hex(n//10))
            rpc=SimpleNamespace(call=header,batch=lambda calls,scope:[header(m,p,scope) for m,p in calls])
            def rows(first,last):
                # Quiet stretches, distinct buyers and fast reversals use the
                # same reference block interval as the published acquisition.
                return [dict(identity='h'+str(n)+':tx'+str(n)+':0',block=n,event_at=n//10,
                    group=address(n%13+1),side='sell' if n%70<30 else 'buy',quote=n%101+100,
                    tokens=10,price_index=(10**18 if n%300<200 else 10**17)+n,
                    transaction_index=0,log_index=0) for n in range(first,last+1)
                    if n%10==0 and n%1000<800]
            def collect(endpoint,**kw):
                counts['intervals']+=1
                return v4.activity_summary(rows(kw['start_block'],kw['end_block']))
            n=2000
            try:
                with patch.object(v4,'collect_v4_activity',side_effect=collect),patch('time.time',side_effect=lambda:now[0]):
                    for turn in range(25920):
                        now[0]=200+5*turn
                        if turn and turn%100:n+=50
                        h=header('',[hex(n)],'');at=int(h['timestamp'],16)
                        first=int(_header_search(rpc,n,at,at-15,{n:h})['number'],16)
                        expected=rows(first,n)
                        result=v4.rolling_position_activity(ENDPOINT,rpc=rpc,history=history,pool_id=pool,
                            key=SimpleNamespace(),token=address(1),header=h)
                        self.assertEqual(result['swaps'],expected)
                        # Compare complete price, volume, buyer and ordering
                        # evidence with the original independent block search.
                        for key,value in v4.activity_summary(expected).items():self.assertEqual(result[key],value)
                        if turn%1000==0:
                            retained=plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0]
                            maximum=max(maximum,retained);self.assertLessEqual(retained,902)
                        if turn in (5000,15000,25919):
                            previous=history.get(pool);plane.close();plane=Plane(path)
                            history=CurrentHistory(plane,ENDPOINT)
                            self.assertEqual(history.get(pool),previous)
                self.assertEqual(plane.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                print('STORAGE_TRACE',json.dumps(dict(current_v4_monitor_turns=25920,
                    original_boundary_parity_every_turn=True,maximum_retained_events=maximum,
                    sqlite_bytes=path.stat().st_size,wal_bytes=Path(str(path)+'-wal').stat().st_size,
                    cpu_seconds=time.process_time()-started,restarts=3)),flush=True)
            finally:plane.close()

    def test_full_72_hour_survivor_actual_history_is_bounded_and_keeps_original_risk_age(self):
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH,risk_policy
        from meme_machine.runtime.survivor_risk import mark
        legacy=original('meme_machine/runtime/survivor_risk.py')
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';history=PonsHistory(path,policy=POLICY_HASH)
            service=object.__new__(pons_runtime.Runtime);service.history=history
            row=history.graduate(address(1),graduation(1));row.update(state='runner',position='native-held')
            history.save(row)
            state=dict(opened_at=100,original_quantity=1000,remaining_quantity=750,realization_taken=True,
                high_water_bps=12000,high_at=100)
            old=deepcopy(state);started=time.process_time();maximum_points=maximum_events=0
            try:
                for turn in range(86401):
                    at=100+turn*3;block=100+turn*30
                    tape=dict(swaps=[dict(identity=f'{block}:{i}',block=block,event_at=at,
                        group=address(i+1),side='buy' if i==0 else 'sell',quote=300 if i==0 else 100,
                        tokens=10,price_index=10**18+turn,transaction_index=i,log_index=i) for i in range(2)])
                    header=dict(number=hex(block),hash='h'+str(block),timestamp=hex(at))
                    service._append_tape(row,block,header,tape)
                    observation=dict(id=header['hash'],at=at,after_cost_return_bps=12000+turn,
                        creator_distribution=False,exit_liquidity_valid=True,soft_deterioration=False)
                    state,action=mark(state,observation,risk_policy());old,prior=legacy.mark(old,observation,risk_policy())
                    self.assertEqual((state,action),(old,prior));self.assertEqual(state['opened_at'],100)
                    if turn<86400:self.assertEqual(action['action'],'hold')
                    else:self.assertEqual((action['action'],action['reason']),('full_exit','maximum_hold'))
                    if turn%1200==0:
                        points,events=history.facts(row['id'],at)
                        maximum_points=max(maximum_points,len(points));maximum_events=max(maximum_events,len(events))
                        self.assertLessEqual(len(points),28805);self.assertLessEqual(len(events),2402)
                        self.assertEqual(history.get(row['id'])['block'],block)
                    if turn in (21600,43200,86399):
                        checkpoint=history.get(row['id']);history.close();history=PonsHistory(path,policy=POLICY_HASH)
                        service.history=history;self.assertEqual(history.get(row['id']),checkpoint)
                        self.assertEqual(state['opened_at'],100);self.assertEqual(state['remaining_quantity'],750)
                prefix=history.get_meta('pons_price_window:'+row['id'])
                self.assertGreater(prefix['count'],50000)
                self.assertEqual(prefix['original_anchor']['at'],100)
                self.assertEqual(history.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                # Only native/shared completion can retire a held history.
                with self.assertRaisesRegex(ValueError,'survivor_open_position_retirement'):history.retire(history.get(row['id']))
                row=history.get(row['id']);row.update(position=None,state='settled');history.save(row)
                history.retire(row)
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM points').fetchone()[0],0)
                print('STORAGE_TRACE',json.dumps(dict(survivor_monitor_turns=86401,
                    maximum_retained_points=maximum_points,maximum_retained_events=maximum_events,
                    sqlite_bytes=path.stat().st_size,wal_bytes=Path(str(path)+'-wal').stat().st_size,
                    cpu_seconds=time.process_time()-started,original_opened_at=state['opened_at'],
                    risk_high_water=state['high_water_bps'],automatic_terminal_history_cleanup=True)),flush=True)
            finally:history.close()

    def test_native_overlapping_v4_acquisition_preserves_all_economics_and_measures_savings(self):
        from engineering.pons_history.fixtures import Tape
        from meme_machine.lanes.pons.identity import load
        from meme_machine.lanes.pons.pons_selective_acquisition import _header_search
        class Market(Tape):
            def __init__(self):
                super().__init__(candidates=1);self.counts=Counter();self.per_scope=190
            def header(self,n):
                h=super().header(n)
                return dict(h,timestamp=hex(1000+(n-self.grad)//10))
            def receipt_value(self,tx):
                r=super().receipt_value(tx)
                return dict(r,**{'from':self.senders.get(tx,address(999))})
        old_v4=original('meme_machine/lanes/pons/pons_selective_v4.py')
        tape=Market();token=tape.tokens[0];record=tape.records[token]
        key=pons_runtime.PoolKey(pons_runtime.ZERO,token,record['poolFee'],record['tickSpacing'],load('pons_v2_hook')['address'].lower())
        pool=key.pool_id();turns=list(range(tape.grad+10,tape.grad+501,50));expected=[]
        with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=lambda *a,**kw:tape.provider()):
            for n in turns:
                h=tape.header(n);at=int(h['timestamp'],16)
                first=_header_search(tape,n,at,at-15,{n:h})
                expected.append(old_v4.collect_v4_activity(ENDPOINT,pool_id=pool,key=key,token=token,
                    start_block=int(first['number'],16),end_block=n))
        before=dict(physical=tape.batches,elements=tape.logical,methods=dict(tape.methods),
            response_bytes=tape.response_bytes,request_bytes=tape.request_bytes)
        tape=Market()
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'plane.sqlite');history=CurrentHistory(plane,ENDPOINT)
            try:
                with patch('meme_machine.lanes.pons.pons_selective_acquisition._rpc',side_effect=lambda *a,**kw:tape.provider()):
                    for i,n in enumerate(turns):
                        if i==7:history=CurrentHistory(plane,ENDPOINT)
                        result=v4.rolling_position_activity(ENDPOINT,rpc=tape,history=history,pool_id=pool,
                            key=key,token=token,header=tape.header(n))
                        self.assertEqual({k:v for k,v in result.items() if k!='provider_sessions'},
                            {k:v for k,v in expected[i].items() if k!='provider_sessions'})
                        row=history.get(pool);self.assertEqual(row['last_interval']['last_block'],n)
                    after=dict(physical=tape.batches,elements=tape.logical,methods=dict(tape.methods),
                        response_bytes=tape.response_bytes,request_bytes=tape.request_bytes)
                    # Duplicate delivery, quiet same-head acquisition and restart
                    # cannot manufacture a new event or a new economic window.
                    prior=history.get(pool);count=plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0]
                    tape.duplicates=True
                    again=v4.rolling_position_activity(ENDPOINT,rpc=tape,history=history,pool_id=pool,
                        key=key,token=token,header=tape.header(turns[-1]))
                    self.assertEqual(again['swaps'],expected[-1]['swaps'])
                    self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM pons_current_events').fetchone()[0],count)
                    self.assertEqual(history.get(pool)['last_interval']['kind'],'already_complete_no_delta')
                self.assertLess(after['physical'],before['physical']);self.assertLess(after['elements'],before['elements'])
                from engineering.solana_capacity.proof_limits import PUBLISHED
                for value in (before,after):value['rpc_cu']=sum(PUBLISHED['robinhood'][m]*n for m,n in value['methods'].items())
                self.assertLess(after['rpc_cu'],before['rpc_cu']);self.assertLess(after['response_bytes'],before['response_bytes'])
                print('RESOURCE_TRACE',json.dumps(dict(case='native_current_v4_overlap_with_restart',
                    turns=len(turns),extra_same_head_physical=tape.batches-after['physical'],before=before,after=after,
                    cache=history.v4_evidence_context.cache.telemetry(),fixture='captured lineage with synthetic headers/receipts/swaps'),sort_keys=True),flush=True)
            finally:plane.close()

    def test_fresh_quote_does_not_publish_missing_or_incomplete_history(self):
        # Quote and history authority are independent even at the same frontier.
        case=RollingV4Tests();case.setUp()
        try:
            with patch.object(v4,'collect_v4_activity',side_effect=case.tape):case.turn(200)
            old=case.history.get(case.pool)
            with patch.object(v4,'collect_v4_activity',side_effect=BoundaryError('pons_log_batch_shape')):
                with self.assertRaisesRegex(BoundaryError,'pons_log_batch_shape'):case.turn(300)
            self.assertEqual(case.history.get(case.pool),old)
            with self.assertRaisesRegex(BoundaryError,'not_caught_up'):
                case.history.facts(case.pool,dict(number=hex(300),hash='300',timestamp=hex(30)),15)
        finally:case.doCleanups()
