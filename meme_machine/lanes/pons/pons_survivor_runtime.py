"""Independent Pons V2 graduation discovery and active PAPER Survivor controller.

All transport uses the existing canonical Robinhood provider and governor. The
Candidate/Evidence Plane owns generation fencing. History is incremental and
bounded; it is never reconstructed by an unbounded seven-day RPC scan.
"""
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import time

from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.execution_capacity import resize,buyer_persistence
from meme_machine.runtime.journal import digest
from meme_machine.runtime.survivor_commit import commit,monitor,handoff_ready,scale
from .pons_history import PonsHistory
from .pons_attempts import Attempts, decision_category, failure_category
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.runtime.robinhood.pons import plane_path
from . import BoundaryError
from .abi import calldata,words,scalar
from .identity import load,authenticate
from .keccak import keccak256
from .protocols import PoolKey
from .provider_topology import configured_rpc
from .provider_admission import decision_work,position_work
from .pons_natural_observation import _latest_header,_one_word,ZERO
from .pons_natural_paper import (_graduation_transition,_factory_record_at,_event_topic,
    _v4_quoter_calldata,V4_QUOTER)
from .pons_selective_v4 import collect_v4_activity,collect_v4_activities
from .pons_postgrad_survivor import POLICY,POLICY_HASH,STRATEGY_VERSION,evaluate_entry,risk_policy


def price_index(sqrt,token,key):
    if sqrt<=0:raise BoundaryError('survivor_v4_price')
    return sqrt*sqrt*10**18//(1<<192) if token==key.currency0 else (1<<192)*10**18//(sqrt*sqrt)


class Quotes:
    """Exact bounded probes, quoted at one authenticated block.

Each ladder point has its exact 2x probe. No interpolation invents executable
capacity. Searching cached quotes issues zero additional provider calls.
"""
    def __init__(self,runtime,state,budget):
        self.runtime=runtime;self.state=state;self.cache={};self.budget=budget;self.acquired=time.monotonic()
        self.prepared=set();self.prepared_ladder=False;self.gas_price=None

    def _fetch(self,sizes):
        from .pons_quotes import quote_deadline
        with quote_deadline(self.runtime.rpc,self.state['acquired']):
            return self._acquire(sizes)

    def _acquire(self,sizes):
        runtime=self.runtime;state=self.state
        rpc=runtime.rpc;key=PoolKey(**runtime.current['graduation']['key'])
        from .pons_quotes import pinned_block
        header=dict(number=hex(state['block']),hash=state['block_hash'])
        block=pinned_block(rpc,'eth_call',header);minimum=runtime.sleeve.sizing_basis(500,minimum_bps=5)["minimum"]
        sizes={n for n in sizes if n>=minimum and n not in self.prepared}
        if not sizes:return
        # A requested probe is execution evidence, not a reservation. The
        # strategy's nominal target and the funding amount remain independent.
        if len(self.prepared|sizes)>256:raise BoundaryError('provider_survivor_quote_probe_work_bound')
        if not 0<=time.monotonic()-state['acquired']<=5:raise BoundaryError('survivor_stale_quote')
        # Gas is an explicit conservative reservation, checked against each
        # quoter simulation. If it is inadequate the quote fails closed.
        units=max(500000,2*runtime.current['graduation']['transition']['graduation_gas_used'])
        if self.gas_price is None:
            values=rpc.batch([
                ('eth_getCode',[V4_QUOTER,pinned_block(rpc,'eth_getCode',header)]),
                ('eth_call',[dict(to=V4_QUOTER,data=calldata('poolManager()')),block]),
                ('eth_gasPrice',[])],scope='pons_survivor')
            if len(values)!=3:raise BoundaryError('survivor_quote_cost_identity_incomplete')
            code,manager,gas=values;self.gas_price=int(gas,16)
            if not code or code=='0x' or _one_word(manager,'address')!=load('uniswap_v4_manager')['address'].lower():
                raise BoundaryError('survivor_quoter_authority')
        gas_price=self.gas_price
        buffer=units*gas_price
        self.prepared.update(sizes)
        ordered=sorted(n for n in sizes if n>buffer)
        if not ordered:return
        buys=rpc.batch([('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(key,key.currency0==ZERO,n-buffer)),block])
                        for n in ordered],scope='pons_survivor')
        if len(buys)!=len(ordered):raise BoundaryError('survivor_buy_quote_incomplete')
        decoded=[tuple(scalar('uint256',w) for w in words(raw)) for raw in buys]
        if any(len(v)!=2 or v[0]<=0 for v in decoded):raise BoundaryError('survivor_buy_quote_shape')
        calls=[('eth_call',[dict(to=V4_QUOTER,data=_v4_quoter_calldata(key,key.currency0!=ZERO,v[0])),block]) for v in decoded]
        calls.append(('eth_getBlockByNumber',[header['number'],False]))
        previous=getattr(rpc,'evidence_pins',{});rpc.evidence_pins={}
        try:values=rpc.batch(calls,scope='pons_survivor')
        finally:rpc.evidence_pins=previous
        if len(values)!=len(calls):raise BoundaryError('survivor_sell_quote_incomplete')
        if values[-1]['number']!=header['number'] or values[-1]['hash']!=header['hash']:
            raise BoundaryError('pons_quote_canonical_membership_disagreement')
        sells=values[:-1]
        for n,b,raw in zip(ordered,decoded,sells):
            s=tuple(scalar('uint256',w) for w in words(raw))
            if len(s)!=2 or s[0]<=0:continue
            entry_gas=max(units,b[1]*2)*gas_price;exit_gas=max(units,s[1]*2)*gas_price
            cost=n-buffer+entry_gas
            if cost>n:continue
            self.cache[n]=dict(cost=cost,quantity=b[0],net_proceeds=max(0,s[0]-exit_gas),
                gas=entry_gas,roundtrip_gas=entry_gas+exit_gas,
                block=state['block'],block_hash=state['block_hash'],acquired=time.monotonic(),
                loss_bps=max(0,(cost-max(0,s[0]-exit_gas))*10000//cost))

    def loss(self,n):
        if not 0<=time.monotonic()-self.state['acquired']<=5:raise BoundaryError('survivor_stale_quote')
        if not self.prepared_ladder:
            minimum=self.runtime.sleeve.sizing_basis(500,minimum_bps=5)['minimum']
            sizes={n,minimum}|{max(minimum,n//2**i) for i in range(1,4)}
            self._fetch(sizes|{2*x for x in sizes});self.prepared_ladder=True
        elif n not in self.prepared:self._fetch({n,2*n})
        return self.cache.get(n,{}).get('loss_bps')
    def entry(self,n):
        if n not in self.cache:raise BoundaryError('survivor_executable_size_missing')
        return dict(self.cache[n])


class Runtime:
    def __init__(self,root,capital,run_id,endpoint):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.capital=capital;self.run_id=run_id;self.endpoint=endpoint
        self.sleeve=open_sleeve('pons',capital)
        if self.sleeve is None:raise BoundaryError('survivor_shared_sleeve_required')
        self.history=PonsHistory(str(self.root/'history.sqlite'),policy=POLICY_HASH)
        from meme_machine.runtime.survivor_history import compact_restored_history
        compact_restored_history(self.history,lane='pons')
        self.book=PaperBook(str(self.root/'paper.sqlite'),run_id=run_id,lane=STRATEGY_VERSION,
                            policy_hash=POLICY_HASH,initial=capital)
        from meme_machine.runtime.survivor_terminal_archive import compact
        compact(self.book,self.sleeve,self.history)
        self.plane=Plane(plane_path(self.root/'candidate-evidence.sqlite'))
        self.attempts=Attempts(self.plane)
        self.rpc=None;self.current=None;self.last_error=None

    def now(self):return int(time.time())

    def historical_preparation_step(self):
        """Explicit preparation turn on this runtime's existing history authority.

        The ordinary Current/Survivor scheduling and startup guard are unchanged.
        An authorized historical executor or existing Survivor worker can drive
        this after native position maintenance. It creates no economic decision.
        """
        from .pons_historical import Preparation
        def provider():
            self._provider()
            return self.rpc
        preparation=getattr(self,'historical_preparation',None)
        if preparation is None:
            preparation=Preparation(self.history,provider)
            self.historical_preparation=preparation
        status=preparation.step(self)
        if status.get('ready'):
            # Keep the seven-day domain plus one full day of acquisition overlap.
            # Retire at most 256 expired range records per minute, after native
            # position work; existing economic archives remain independently owned.
            last=self.history.get_meta('pons_historical_maintenance_at')
            if last is None or self.now()-last>=60:
                plan=self.history.get_meta('pons_historical_plan')
                preparation.maintain(recovery_before=plan['cutoff']-86400)
                self.history.set_meta('pons_historical_maintenance_at',self.now())
        return status

    def _provider(self):
        if self.rpc is None or self.rpc.used>150:
            self.rpc=configured_rpc(self.endpoint,limit=200,per_scope=200,retries=0)
        if not getattr(self,'deployments_verified',False):
            roles=('pons_v2_factory','pons_v2_hook','uniswap_v4_manager')
            results=self.rpc.batch([('eth_getCode',[load(role)['address'],'latest']) for role in roles],scope='pons_survivor')
            for role,code in zip(roles,results):authenticate(role,load(role)['address'],code)
            self.deployments_verified=True

    @decision_work(4)
    def discover(self):
        # A prepared history stays on its durable acquisition path after restart.
        # Unseeded ordinary discovery keeps its original ten/forty-block limits.
        # The runtime adapter also uses ten/forty: larger historical requests are
        # confined to a separately driven preparation with a capability receipt.
        from .pons_historical import PLAN,number
        prepared=self.history.get_meta(PLAN)
        if prepared is not None:
            worker=getattr(self,'historical_preparation',None)
            if worker is not None and worker.restored and prepared.get('ready'):
                header=_latest_header(self.rpc)
                if number(header)>number(prepared['target']):worker.extend(header)
            self.historical_readiness=self.historical_preparation_step()
            return
        header=_latest_header(self.rpc);top=int(header['number'],16)
        cursor=self.history.get_meta('discovery_block')
        if cursor is None:
            cursor=self._bootstrap_cursor(header)
            if cursor is None:return
        expected=self.history.get_meta('discovery_block_hash')
        if top==cursor and expected and header['hash']!=expected:
            self.history.invalidate_discovery()
            raise BoundaryError('survivor_discovery_reorg')
        if top>cursor:
            end=min(top,cursor+40);factory=load('pons_v2_factory')['address'].lower()
            calls=[('eth_getLogs',[dict(address=factory,fromBlock=hex(first),toBlock=hex(min(end,first+9)),
                topics=[_event_topic('pons_v2_factory','PoolGraduated')])]) for first in range(cursor+1,end+1,10)]
            count=len(calls)
            if end!=top:calls.append(('eth_getBlockByNumber',[hex(end),False]))
            if expected:calls.append(('eth_getBlockByNumber',[hex(cursor),False]))
            values=self.rpc.batch(calls,scope='pons_survivor')
            if len(values)!=len(calls):raise BoundaryError('survivor_graduation_range_incomplete')
            boundary=header if end==top else values[count]
            if int(boundary['number'],16)!=end or not boundary.get('hash'):
                raise BoundaryError('survivor_discovery_boundary_identity')
            if expected and (int(values[-1]['number'],16)!=cursor or values[-1]['hash']!=expected):
                self.history.invalidate_discovery()
                raise BoundaryError('survivor_discovery_reorg')
            batches=values[:count]
            if len(batches)!=count or any(not isinstance(b,list) for b in batches):
                raise BoundaryError('survivor_graduation_range_incomplete')
            events=[]
            for (_,params),batch in zip(calls,batches):
                q=params[0]
                for event in batch:
                    if (event.get('removed') or event.get('address','').lower()!=factory
                            or not int(q['fromBlock'],16)<=int(event['blockNumber'],16)<=int(q['toBlock'],16)
                            or not event.get('topics') or event['topics'][0]!=q['topics'][0]):
                        raise BoundaryError('survivor_graduation_log_identity')
                    events.append(event)
            events.sort(key=lambda e:(int(e['blockNumber'],16),int(e.get('transactionIndex','0x0'),16),int(e.get('logIndex','0x0'),16)))
            self.history.retain_graduations(events,end,block_hash=boundary['hash'])
        # Authentication is scheduling work. Even a burst larger than 32 remains
        # durable; a failed member rotates rather than blocking every later one.
        for nomination,event in self.history.graduation_batch():
            if len(event['topics'])<2:raise BoundaryError('survivor_graduation_token')
            token='0x'+event['topics'][1][-40:].lower();block=int(event['blockNumber'],16)
            report={'reads':[]};record=_factory_record_at(self.rpc,token,block,report)
            result=_graduation_transition(self.rpc,dict(token=token,curve=record['curve']),block,block,report)
            if result is None:raise BoundaryError('survivor_graduation_missing')
            transition,key,h,record=result
            canonical=self.rpc.call('eth_getBlockByNumber',[hex(block),False],scope='pons_survivor')
            if int(canonical['number'],16)!=block or canonical['hash']!=h['hash']:
                raise BoundaryError('survivor_graduation_canonical_membership_disagreement')
            if record['pairToken']!=ZERO:
                self.attempts.record(token,0,'graduation','STRUCTURAL_INELIGIBLE',at=transition['graduation_at'],reason='non_native_quote')
                self.history.graduation_complete(nomination);continue
            evidence=dict(at=transition['graduation_at'],block=block,block_hash=h['hash'],
                transition=transition,key=asdict(key),record=record,
                source='robinhood_authenticated_candidate_evidence_plane')
            if (self.history.get(token) is None and (self.history.expired(evidence)
                    or self.now()-evidence['at']>POLICY['universe']['max_seconds_after_graduation'])):
                self.attempts.record(token,0,'graduation','EXPIRED_BY_STRATEGY_HORIZON',at=evidence['at'],reason='strategy_horizon_expired')
                self.history.graduation_complete(nomination);continue
            old=self.history.get(token)
            if old and old['graduation']!=evidence and old.get('recovery')!='graduation_membership_unavailable':
                anchor=self.rpc.call('eth_getBlockByNumber',[hex(old['graduation']['block']),False],scope='pons_survivor')
                if anchor['hash']!=old['graduation']['block_hash']:
                    old['complete']=False;old['recovery']='graduation_membership_unavailable';self.history.save(old)
            if old and old.get('recovery')=='graduation_membership_unavailable':
                p=price_index(transition['initialization_sqrt_price_x96'],token,key)
                row=self.history.replace_orphaned_graduation(token,evidence,anchor_price=p)
            else:row=self.history.graduate(token,evidence)
            if row['state']=='retired':self.history.graduation_complete(nomination);continue
            if row.get('block') is None:
                row['block']=block;self.history.save(row)
                p=price_index(transition['initialization_sqrt_price_x96'],token,key)
                self.history.append(token,through=evidence['at'],events=[],points=[(evidence['at'],str(p))],complete=True)
            self.history.graduation_complete(nomination)

    def _bootstrap_cursor(self,header):
        """One header per step finds the full seven-day domain on a cold start."""
        top=int(header['number'],16);at=int(header['timestamp'],16)
        search=self.history.get_meta('discovery_bootstrap')
        if search is None:
            search=dict(low=-1,high=top,cutoff=max(0,at-POLICY['universe']['max_seconds_after_graduation']))
        if search['low']+1<search['high']:
            mid=(search['low']+search['high'])//2
            witness=self.rpc.call('eth_getBlockByNumber',[hex(mid),False],scope='pons_survivor')
            if int(witness['number'],16)!=mid:raise BoundaryError('survivor_bootstrap_header_identity')
            search['low' if int(witness['timestamp'],16)<search['cutoff'] else 'high']=mid
            self.history.set_meta('discovery_bootstrap',search)
        if search['low']+1==search['high']:
            self.history.set_meta('discovery_block',search['low'])
            return search['low']
        return None

    def _increment(self,row,end):
        start=row['block']+1
        if end<start:return
        if end-start>=40:raise BoundaryError('survivor_incremental_slice_required')
        key=PoolKey(**row['graduation']['key']);pool=row['graduation']['transition']['market']
        tape=collect_v4_activity(self.endpoint,pool_id=pool,key=key,token=row['id'],
            start_block=start,end_block=end,max_events=256)
        h=self.rpc.call('eth_getBlockByNumber',[hex(end),False],scope='pons_survivor')
        # The preceding boundary must still have the authenticated hash recorded
        # at the last watermark. A fork never becomes clean historical evidence.
        previous=self.rpc.call('eth_getBlockByNumber',[hex(row['block']),False],scope='pons_survivor')
        expected=row.get('block_hash',row['graduation']['block_hash'])
        if previous['hash']!=expected:
            self._recover_reorg(row)
            raise BoundaryError('survivor_history_reorg')
        self._append_tape(row,end,h,tape)

    def _recover_reorg(self,row):
        graduation=row['graduation'];block=graduation['block']
        header=self.rpc.call('eth_getBlockByNumber',[hex(block),False],scope='pons_survivor')
        if int(header['number'],16)!=block:raise BoundaryError('survivor_recovery_anchor_identity')
        key=PoolKey(**graduation['key'])
        price=price_index(graduation['transition']['initialization_sqrt_price_x96'],row['id'],key)
        self.history.reset_after_reorg(row['id'],canonical_graduation_hash=header['hash'],anchor_price=price)

    def _append_tape(self,row,end,h,tape):
        at=int(h['timestamp'],16);events=[];points={}
        for e in tape['swaps']:
            events.append(dict(id=e['identity'],at=e['event_at'],group=e['group'],buy=e['side']=='buy',
                quote=e['quote'],tokens=e['tokens'],authenticated=True,
                block=e['block'],transaction_index=e.get('transaction_index'),log_index=e.get('log_index')))
            p=str(e['price_index']);old=points.get(e['event_at'])
            points[e['event_at']]=dict(price=p,low=str(min(int(p),int(old['low']))) if old else p,
                high=str(max(int(p),int(old['high']))) if old else p)
        self.history.append_block(row['id'],block=end,header=h,events=events,points=sorted(points.items()))

    def _increment_candidates(self,rows,top):
        if not rows:return
        population=len(rows)
        rows=self.history.history_batch(rows,top)
        if not rows:return
        start=min(row['block'] for row in rows)+1;end=min(top,start+39)
        if end<start:return
        active=[row for row in rows if row['block']<end]
        markets=[dict(pool_id=r['graduation']['transition']['market'],
            key=PoolKey(**r['graduation']['key']),token=r['id']) for r in active]
        tapes=collect_v4_activities(self.endpoint,markets=markets,start_block=start,end_block=end)
        blocks=sorted({end}|{r['block'] for r in active})
        values=[]
        for offset in range(0,len(blocks),50):
            self._provider()
            values.extend(self.rpc.batch([('eth_getBlockByNumber',[hex(b),False]) for b in blocks[offset:offset+50]],scope='pons_survivor'))
        headers=dict(zip(blocks,values))
        if any(int(headers[b]['number'],16)!=b for b in blocks):raise BoundaryError('survivor_header_number')
        valid=[];reorgs=[]
        for row in active:
            if headers[row['block']]['hash']!=row.get('block_hash',row['graduation']['block_hash']):
                self._recover_reorg(row);reorgs.append(row['id'])
            else:valid.append(row)
        for row in valid:
            tape=dict(tapes[row['id']]);tape['swaps']=[e for e in tape['swaps'] if e['block']>row['block']]
            self._append_tape(row,end,headers[end],tape)
        self.acquisition=dict(observed_at=self.now(),head_block=top,through_block=end,
            retained_candidates=population,scheduled_candidates=len(rows),advanced_candidates=len(valid),
            reorg_recoveries=reorgs,
            maximum_lag_blocks=max(top-self.history.get(r['id'])['block'] for r in rows))

    def fresh_state(self,candidate):
        self._provider();self.current=self.history.get(candidate)
        from .pons_quotes import pinned_block,quote_deadline
        acquired=time.monotonic()
        with quote_deadline(self.rpc,acquired):header=_latest_header(self.rpc)
        block=int(header['number'],16)
        if block-self.current['block']>40:raise BoundaryError('survivor_monitoring_not_caught_up')
        pool=self.current['graduation']['transition']['market'];manager=load('uniswap_v4_manager')['address'].lower()
        slot=keccak256(bytes.fromhex(pool[2:])+(6).to_bytes(32,'big'))
        data='0x'+keccak256(b'extsload(bytes32)').hex()[:8]+slot.hex()
        with quote_deadline(self.rpc,acquired):
            raw=self.rpc.call('eth_call',[dict(to=manager,data=data),pinned_block(self.rpc,'eth_call',header)],scope='pons_survivor')
        if time.monotonic()-acquired>5:raise BoundaryError('survivor_stale_state')
        value=words(raw)
        if len(value)!=1:raise BoundaryError('survivor_v4_state_shape')
        sqrt=scalar('uint256',value[0])&((1<<160)-1)
        key=PoolKey(**self.current['graduation']['key'])
        return dict(block=block,block_hash=header['hash'],at=int(header['timestamp'],16),
                    price_index=price_index(sqrt,candidate,key),acquired=acquired)

    def fresh_quotes(self,state,budget):return Quotes(self,state,budget)

    def reconstruct(self,state,quotes):
        row=self.current;self._increment(row,state['block'])
        self.history.finish_recovery(row['id'],block=state['block'],block_hash=state['block_hash'])
        self.history.append(row['id'],through=state['at'],events=[],points=[(state['at'],str(state['price_index']))],complete=True)
        points,events=self.history.facts(row['id'],state['at']);now=state['at']
        record=row['graduation']['record'];creators={str(record[k]).lower() for k in ('deployer','creatorFeeRecipient') if record.get(k)}
        flow=buyer_persistence([e for e in events if e['group'] not in creators],now=now,window_seconds=1800)
        def window(lower,upper):
            rows=[e for e in events if lower<=e['at']<upper and e['group'] not in creators]
            groups=defaultdict(int)
            for e in rows:
                if e['buy']:groups[e['group']]+=e['quote']
            total=sum(groups.values())
            return dict(buy_quote=total,sell_quote=sum(e['quote'] for e in rows if not e['buy']),
                buyer_groups=sorted(groups),new_buyer_groups=sorted(set(groups)-set(flow['previous_buyer_groups'])),
                buy_quote_by_group=dict(groups),largest_buyer_flow_bps=0 if not total else max(groups.values())*10000//total,
                creator_sell_quote=sum(e['quote'] for e in events if lower<=e['at']<upper and not e['buy'] and e['group'] in creators))
        sizing=self.sleeve.sizing_basis(500,minimum_bps=5)
        # Available cash is tested only after the durable decision. Identical
        # market evidence is qualified against the same realized-equity target.
        cap=min(sizing['target'],flow['turnover']//POLICY['execution']['min_turnover_multiple'])
        capacity=resize(cap,sizing["minimum"],quotes.loss,ordinary_limit=450,stress_limit=650,max_steps=4)
        self.facts=dict(now=now,graduation_at=row['graduation']['at'],lineage_proven=True,native_quote=True,
            evidence_acquired_monotonic=state['acquired'],
            price_points=[dict(at=p['at'],price_index=int(p['price'])) for p in points],
            flow_30m=window(now-1800,now+1),flow_previous_30m=window(now-3600,now-1800),
            capital_quote=sizing['realized_equity'],continuity_complete=self.history.get(row['id'])['complete'],
            execution=dict(roundtrip_loss_bps=capacity.ordinary_loss_bps,
                double_size_roundtrip_loss_bps=capacity.double_loss_bps,capacity=capacity.telemetry()),
            organic_flow=flow)
        return self.facts

    def qualify(self,facts):
        acquired=facts.get('evidence_acquired_monotonic')
        if acquired is not None and not 0<=time.monotonic()-acquired<=5:
            raise BoundaryError('survivor_stale_qualification')
        result=evaluate_entry(facts)
        result['features'].update(independent_buyers=result['features']['independent_buyers_30m'])
        if facts.get('continuity_complete') is not True:
            result['candidate']=False;result['all_rejections'].append('incomplete_continuity')
        if acquired is not None and time.monotonic()-acquired>5:raise BoundaryError('survivor_stale_qualification')
        return result

    def turnover_cap(self,facts,decision):return decision['features']['turnover_quote_30m']//POLICY['execution']['min_turnover_multiple']

    @contextmanager
    def generation_fence(self,candidate,generation):
        with self.plane.transaction():
            row=self.plane.get('pons:survivor:'+candidate)
            if row is None or row['generation']!=self.current['plane_generation']:
                raise BoundaryError('survivor_generation_superseded')
            yield

    def commit_context_expired(self,state):
        return not 0<=time.monotonic()-state['acquired']<=5

    def validate_current(self,state,execution,now):
        from .pons_quotes import canonical_boundary
        canonical_boundary(self.rpc,dict(number=hex(state['block']),hash=state['block_hash']),'pons_survivor')
        if execution['block_hash']!=state['block_hash'] or not 0<=time.monotonic()-state['acquired']<=5:
            raise BoundaryError('survivor_stale_commit')

    @position_work
    def exit_quote(self,qty):
        from .pons_quotes import v4_quote as _v4_quote
        from .evidence import Store
        grad=self.current['graduation'];key=PoolKey(**grad['key'])
        store=Store(str(self.root/'quote-evidence.sqlite'))
        acquired=time.monotonic()
        try:
            q,meta,ledger=_v4_quote(self.rpc,key,grad['transition']['market'],qty,
                grad['transition']['graduation_gas_used'],store,'survivor_exit',local_freshness=True)
            q.check(self.now(),q.market,'sell',qty,q.stamp.kind,finality_ledger=ledger)
            return dict(net_proceeds=max(0,q.amount_out-q.gas_quote),quantity=qty,
                acquired=acquired,block=meta['block'],block_hash=meta['block_hash'],gas=q.gas_quote)
        except BoundaryError:return None
        finally:store.close()

    def validate_exit(self,execution,qty,now):
        from .pons_quotes import canonical_boundary
        canonical_boundary(self.rpc,dict(number=hex(execution['block']),hash=execution['block_hash']),'pons_survivor')
        if execution['quantity']!=qty or not 0<=time.monotonic()-execution['acquired']<=5:
            raise BoundaryError('survivor_exit_quote_stale')

    @decision_work(1)
    def _enter(self,row):
        sizing=self.sleeve.sizing_basis(500,minimum_bps=5)
        try:
            result=commit(book=self.book,sleeve=self.sleeve,identity=row['position'],candidate=row['id'],generation=row['generation'],
                strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,decision=row['decision'],regime=row['regime'],at=self.now(),
                target=sizing["target"],minimum=sizing["minimum"],retention_bps=5000,
                ordinary_limit=450,stress_limit=650,adapter=self,qualify=self.qualify)
        except (ValueError,BoundaryError) as exc:
            self._failure(row,str(exc),phase='funding');raise
        self.attempts.record(row['id'],row['generation'],'funding','OTHER_EXPLICIT_REASON',at=row['regime']['at'],
            reason=result['status'],execution=dict(position=row['position']))
        return result

    def _failure(self,row,reason,*,phase='evidence'):
        category=failure_category(reason,qualified=bool((row.get('decision') or {}).get('candidate')))
        self.attempts.record(row['id'],row.get('generation',0),phase,category,
            at=row.get('regime',{}).get('at',row.get('through',self.now())),reason=reason,
            execution=dict(position=row.get('position')))
        current=self.history.get(row['id'])
        if current is not None:
            current['last_failure']=dict(category=category,reason=reason,at=self.now())
            self.history.save(current)

    @position_work
    def _position(self,row,*,admit=True):
        self.current=row
        try:p=self.book._load(row['position'])
        except ValueError:
            if not admit:raise BoundaryError('survivor_continuation_unfilled_controller')
            # Qualified-unfunded candidates remain history work. A capital
            # denial must not strand their block pin while they wait for cash.
            header=_latest_header(self.rpc)
            self._increment(row,min(int(header['number'],16),row['block']+40))
            row=self.history.get(row['id'])
            return self._enter(row)
        if p['status'] in ('settled','cancelled'):
            self.sleeve.release(row['position'],pnl=p['realized'],at=max(self.now(),p['last_at']),
                terminal_hash=digest(p),native_verified=self.book.replay()['verified'],cancelled=p['status']=='cancelled')
            row.update(position=None,state='settled');self.history.save(row);return
        if p['status']=='reserved':
            if not admit:raise BoundaryError('survivor_continuation_reservation')
            header=_latest_header(self.rpc)
            self._increment(row,min(int(header['number'],16),row['block']+40))
            row=self.history.get(row['id'])
            return self._enter(row)
        q=self.exit_quote(p['tokens']);net=None if q is None else q['net_proceeds']
        events=[];flow=None;header=None
        try:
            header=_latest_header(self.rpc);end=int(header['number'],16)
            self._increment(row,min(end,row['block']+40))
            if end-self.history.get(row['id'])['block']<=1:
                _,events=self.history.facts(row['id'],self.now())
                flow=buyer_persistence(events,now=self.now(),window_seconds=1800)
        except (ValueError,BoundaryError):pass
        record=row['graduation']['record'];creators={record.get('deployer'),record.get('creatorFeeRecipient')}
        observation=dict(id=header['hash'] if header else 'unavailable:'+str(self.now()),at=self.now(),
            after_cost_return_bps=None if net is None else (net-p['basis'])*10000//p['basis'],
            net_exit_proceeds=p['mark'] if net is None else net,exit_liquidity_valid=True if q is not None else None,
            creator_distribution=any(not e['buy'] and e['group'] in creators for e in events),
            soft_deterioration=None if flow is None else flow['buy_flow']*10000<flow['sell_flow']*8000 and flow['new_buyers']==0)
        action=monitor(book=self.book,sleeve=self.sleeve,identity=row['position'],observation=observation,
                       policy=risk_policy(),adapter=self)
        if action['action']=='hold':
            scale(book=self.book,sleeve=self.sleeve,identity=row['position'],candidate=row['id'],
                generation=row['generation'],adapter=self,qualify=self.qualify,ordinary_limit=450,
                stress_limit=650,minimum=self.sleeve.sizing_basis(500,minimum_bps=5)["minimum"])
        if action['action']=='partial_exit':
            row=self.history.get(row['id']);row['state']='runner';self.history.save(row)

    @decision_work(4)
    def step(self,*,admit):
        errors=[]
        try:
            from meme_machine.runtime.storage import compact_survivor
            compact_survivor(self,'pons')
            self._provider()
            from .pons_historical import PLAN
            historical_mode=self.history.get_meta(PLAN) is not None
            history_verified=(not historical_mode or
                bool(getattr(self,'historical_readiness',{}).get('ready')) and
                bool(getattr(getattr(self,'historical_preparation',None),'restored',False)))
            def position_priority(row):
                if not row.get('position'):return 2
                try:position=self.book._load(row['position'])
                except ValueError:return 1
                return 0 if position['status']=='open' and position['tokens']>0 else 1
            for row in sorted(self.history.rows(),key=position_priority):
                if row.get('position'):
                    try:self._position(row,admit=admit and history_verified)
                    except (ValueError,BoundaryError) as exc:
                        errors.append(str(exc));self._failure(row,str(exc),phase='position')
            if admit:
                # Discovery never depends on population or allocatable capital.
                try:self.discover()
                except (ValueError,BoundaryError) as exc:
                    errors.append(str(exc))
                    if historical_mode:self.historical_readiness=dict(ready=False,category='INCOMPLETE_EVIDENCE',reason=str(exc))
            if historical_mode:
                # Existing positions were maintained above. Incomplete census or
                # histories cannot authorize new Survivor decisions or funding.
                admit=(admit and bool(getattr(self,'historical_readiness',{}).get('ready')) and
                    bool(getattr(getattr(self,'historical_preparation',None),'restored',False)))
            rows=[r for r in self.history.rows() if not r.get('position') and r['state']!='retired']
            if admit and rows:
                for expired in list(rows):
                    if self.now()-expired['graduation']['at']>POLICY['universe']['max_seconds_after_graduation']:
                        self.history.retire(expired,expired_before=self.now()-POLICY['universe']['max_seconds_after_graduation']);rows.remove(expired)
                if rows:
                    top=int(_latest_header(self.rpc)['number'],16)
                    if not historical_mode:
                        try:self._increment_candidates(rows,top)
                        except (ValueError,BoundaryError) as exc:errors.append(str(exc))
                    rows=[self.history.get(r['id']) for r in rows]
            if admit and rows:
                row=self.history.qualification_turn(rows,self.now())
                age=self.now()-row['graduation']['at']
                if age>POLICY['universe']['max_seconds_after_graduation']:self.history.retire(row,expired_before=self.now()-POLICY['universe']['max_seconds_after_graduation'])
                else:
                    end=top
                    self._increment(row,min(end,row['block']+40));row=self.history.get(row['id'])
                    if age<POLICY['universe']['min_seconds_after_graduation']:row['state']='aging';self.history.save(row)
                    elif end-row['block']<=40:
                        state=self.fresh_state(row['id']);quotes=self.fresh_quotes(state,self.sleeve.sizing_basis(500)["target"])
                        decision=self.qualify(self.reconstruct(state,quotes));f=decision['features']
                        regime=dict(at=state['at'],high_reset_cycle=f['reset_pullback_bps'],
                            base_id=[f.get('base_low'),f.get('base_high')],buyer_population=self.facts['organic_flow']['buyer_groups'],
                            independent_demand=f['independent_buyers_30m'],flow_regime=f['buy_sell_ratio_bps']//10000)
                        key='pons:survivor:'+row['id']
                        self.plane.observe(key,'pons',state['block_hash'],decision,ordering=(state['block'],),
                            watermark=dict(block=state['block'],hash=state['block_hash']),interpretation=dict(policy=POLICY_HASH),
                            observed=time.time(),deadline=None,priority=4,needs_work=False)
                        self.attempts.record(row['id'],row.get('qualification_attempt',0),'qualification',
                            decision_category(decision),at=state['at'],decision=decision)
                        observed=self.sleeve.observe(row['id'],strategy=STRATEGY_VERSION,at=state['at'],
                            state='qualified' if decision['candidate'] else decision['stage'],evidence=decision,regime=regime)
                        self.sleeve.opportunity(row['id'],identity=row['id'],regime='survivor',
                            status=observed['state'],at=state.get('market_time',state.get('at')),decision=decision)
                        row=self.history.get(row['id']);row.update(state=observed['state'],decision=decision,
                            generation=observed['generation'],regime=regime,plane_generation=self.plane.get(key)['generation'])
                        # Qualification is durable before any funding attempt,
                        # including before the position-limit execution block.
                        self.history.save(row)
                        if decision['candidate'] and sum(bool(r.get('position')) for r in self.history.rows())<POLICY['execution']['max_open_positions']:
                            from meme_machine.runtime.lifecycle_identity import issue
                            row['position']=issue(self.run_id+':'+digest([STRATEGY_VERSION,row['id'],regime]))
                            row['state']='reserved';self.history.save(row);self._enter(row)
                            row=self.history.get(row['id']);row['state']='filled'
                        elif decision['candidate']:
                            self.attempts.record(row['id'],row['generation'],'funding','OTHER_EXPLICIT_REASON',
                                at=state['at'],reason='survivor_open_position_limit')
                        self.history.save(row)
            self.last_error=errors[0] if errors else None
        except (ValueError,BoundaryError) as exc:
            self.last_error=str(exc)
            if 'row' in locals() and row and row.get('id'):
                self._failure(row,str(exc))
        from meme_machine.runtime.directional_accounting import execution_cost
        self.attempts.maintain(self.now(),protected=(r['id'] for r in self.history.rows()))
        return dict(strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,active=True,paper_only=True,
                    native_execution_cost=execution_cost(self.book),
                    candidate_count=len(self.history.rows()),last_boundary=self.last_error,
                    discovery_capacity_deferred=False,
                    pending_graduations=self.history.pending_graduations(),
                    deferred_boundaries=errors,
                    acquisition=getattr(self,'acquisition',None),
                    historical_readiness=getattr(self,'historical_readiness',None),
                    accounting=self.book.reconcile(),accounting_replay=self.book.replay(),
                    policies=self.sleeve.identity['policies'],sleeve=self.sleeve.reconcile(),
                    durable_handoff=handoff_ready(self.book,self.history.rows()))

    def close(self):
        self.book.close();self.history.close();self.sleeve.close();self.plane.close()
