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
from meme_machine.runtime.robinhood.provider_usage import evidence_work
from . import BoundaryError
from .abi import calldata,words,scalar
from .identity import metadata as load,authenticate
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

    @decision_work(1)
    @evidence_work('final_qualification')
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
    # Forty blocks every five seconds cannot follow the measured ~9.9 blocks/s
    # chain. Reuse the same serialized worker more frequently; shared provider
    # admission, range limits and position-first ordering stay authoritative.
    observation_interval_seconds=3

    def __init__(self,root,capital,run_id,endpoint,*,scout_path=None):
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
        self.plane=Plane(scout_path if scout_path is not None else plane_path(self.root/'candidate-evidence.sqlite'))
        self.scout=None
        if scout_path is not None:
            from .pons_natural_observation import MarketScout
            self.scout=MarketScout(self.plane)
        self.attempts=Attempts(self.plane)
        self.rpc=None;self.current=None;self.last_error=None
        # Experimental PAPER shadow only; the native monitor always decides
        # exits using its original fresh quote before this optional observer.
        from .held_paper_shadow import PaperHeldShadow
        self.held_paper_shadow=PaperHeldShadow(endpoint,asynchronous=True)

    def now(self):return int(time.time())

    def historical_preparation_step(self):
        """Explicit preparation turn on this runtime's existing history authority.

        Explicit research/recovery only: ordinary startup and scheduling never
        call this method. It creates no economic decision or admission prerequisite.
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
        # Session rotation preserves deployment pins, but each new transport
        # still has to establish canonical chain identity before reuse.
        if not getattr(self.rpc,'chain_verified',False):self.rpc.verify_chain()
        if not getattr(self,'deployments_verified',False):
            roles=('pons_v2_factory','pons_v2_hook','uniswap_v4_manager')
            results=self.rpc.batch([('eth_getCode',[load(role)['address'],'latest']) for role in roles],scope='pons_survivor')
            for role,code in zip(roles,results):authenticate(role,load(role)['address'],code)
            self.deployments_verified=True

    @decision_work(4)
    def discover(self):
        """Independent prospective factory census, never a cold market scan.

        The original history database owns enrollment, launch/graduation witnesses
        and bounded gap recovery. Its aggregate coverage is reporting only.
        """
        from .pons_historical import Preparation, FORWARD_PLAN, number
        if getattr(self,'scout',None) is not None:
            return self._discover_scout()
        worker=getattr(self,'forward_preparation',None)
        if worker is None:
            def provider():
                self._provider()
                return self.rpc
            worker=Preparation(self.history,provider,forward_only=True,clock=self.now)
            self.forward_preparation=worker
        plan=self.history.get_meta(FORWARD_PLAN)
        if plan is None:
            worker.begin()
        elif not worker.restored:
            worker.resume()
        # A moving frontier never waits for unrelated history or census maturity.
        header=_latest_header(self.rpc)
        plan=self.history.get_meta(FORWARD_PLAN)
        if number(header)==number(plan['target']) and header['hash']!=plan['target']['hash']:
            worker.resume()
        if number(header)>number(plan['target']):worker.extend(header)
        worker.discover_step()
        worker.authenticate_step()
        self.historical_readiness=worker.readiness()
        last=self.history.get_meta('pons_forward_maintenance_at')
        if last is None or self.now()-last>=60:
            plan=self.history.get_meta(FORWARD_PLAN)
            worker.maintain(recovery_before=plan['cutoff']-86400)
            self.history.set_meta('pons_forward_maintenance_at',self.now())

    def _discover_scout(self):
        """Consume the shared journal; zero independent broad Alchemy scans."""
        from .pons_historical import Preparation, FORWARD_PLAN
        after=self.history.get_meta('pons_scout_graduation_seq') or 0
        nominations=self.scout.events('graduation',after=after)
        if nominations:
            with self.history.transaction():
                for seq,event,_ in nominations:
                    self.history.retain_graduations([event],int(event['blockNumber'],16))
                    self.history.set_meta('pons_scout_graduation_seq',seq)
        enrollment=self.plane.checkpoint_read('pons_scout_enrollment')
        if enrollment is None:
            self.historical_readiness=dict(ready=False,category='PENDING_EVIDENCE',
                qualification_authority=False,pre_enrollment_coverage='UNOBSERVED')
            return
        worker=getattr(self,'forward_preparation',None)
        if worker is None:
            def provider():self._provider();return self.rpc
            worker=Preparation(self.history,provider,forward_only=True,clock=self.now,observations=self.scout)
            self.forward_preparation=worker
        if self.history.get_meta(FORWARD_PLAN) is None:
            worker.begin(enrollment_block=enrollment['first'])
        elif not worker.restored:worker.resume()
        reorgs=self.plane.checkpoint_read('pons_scout_reorganizations') or 0
        if reorgs != self.history.get_meta('pons_scout_checked_reorganizations'):
            worker.resume()
            self.history.set_meta('pons_scout_checked_reorganizations',reorgs)
        if self.history.pending_graduations():
            with evidence_work('canonical_verification'):worker.authenticate_step()
        if not getattr(self,'scout_registered',False):
            for row in self.history.rows():self.scout.register_pool(row)
            self.scout_registered=True
        token=getattr(worker,'last_authenticated_candidate',None)
        if token is not None:
            row=self.history.get(token)
            if row:self.scout.register_pool(row)
            worker.last_authenticated_candidate=None
        self.historical_readiness=dict(ready=True,mode='shared_public_scout',
            qualification_authority=False,market_wide_coverage_required=False,
            pre_enrollment_coverage='UNOBSERVED',scout=self.scout.snapshot(),
            pending_canonical_graduations=self.history.pending_graduations())

    def _watch_due(self,row,now):
        """Cheap scheduling, without deleting an economic or unknown candidate.

        Every new pool observation can reactivate a weak candidate. Timed window
        changes and the original four-hour boundary also get fresh evidence.
        Unknown or interrupted work remains due until canonical hydration finishes.
        """
        age=now-row['graduation']['at']
        if age<POLICY['universe']['min_seconds_after_graduation']:return False
        if row.get('recovery') or row.get('complete') is not True:return True
        if not row.get('decision'):return True
        if self.scout.signal(row['graduation']['transition']['market']) != row.get('scout_checked_signal',-1):return True
        return now >= row.get('scout_next_check',now)

    def _deep_watch_due(self,row,now):
        if self._watch_due(row,now):return True
        signal=self.scout.signal(row['graduation']['transition']['market'])
        if row.get('scout_level')=='deep_watch':
            return signal != row.get('scout_hydrated_signal',-1)
        activity=self.scout.activity(row)
        if row.get('recovery') or activity['improving']:
            row['scout_level']='deep_watch';self.history.save(row)
            return True
        # A newly registered pool may still be catching up in the public scout.
        # Before the original entry age, this is pending observation, not an
        # economic rejection or a reason to hydrate every new identity. Mature
        # candidates and canonical recovery already remain due above.
        return False

    def _schedule_watch(self,row,now,signal):
        # These are mathematical feature boundaries in the frozen policy, not
        # new strategy thresholds. No future event is inspected.
        points,events=self.history.facts(row['id'],now)
        windows=tuple(POLICY['trend'][k] for k in ('short_window_seconds','medium_window_seconds',
            'long_window_seconds','base_seconds','breakout_exclusion_seconds'))
        boundaries=[p['at']+window+1 for p in points for window in windows if p['at']+window+1>now]
        boundaries += [e['at']+window+1 for e in events for window in (1800,3600) if e['at']+window+1>now]
        # A missed public notification cannot tombstone an identity. A bounded
        # recovery probe checks the candidate even in a quiet public journal.
        boundaries.append(now+60)
        row.update(scout_next_check=min(boundaries),
            scout_checked_signal=signal)
        return row

    def candidate_readiness(self,candidate,*,through_block=None,through_hash=None):
        """Native contiguous history and lineage, independent of market recall.

        Fresh canonical state, quotes and the frozen strategy remain mandatory.
        A persisted readiness result has no funding or fresh-state authority.
        """
        row=self.history.get(candidate)
        reasons=[]
        if row is None:
            reasons.append('candidate_missing')
        else:
            graduation=row['graduation']
            if not all(graduation.get(k) for k in ('transition','key','record','block_hash')):
                reasons.append('candidate_lineage_incomplete')
            if row.get('complete') is not True or row.get('recovery'):
                reasons.append('candidate_continuity_incomplete')
            if row.get('block') is None or not row.get('block_hash',graduation.get('block_hash')):
                reasons.append('candidate_checkpoint_missing')
            if row.get('block')!=graduation.get('block') and not row.get('block_hash'):
                reasons.append('candidate_checkpoint_missing')
            if through_block is not None and row.get('block')!=through_block:
                reasons.append('candidate_history_not_caught_up')
            if through_hash is not None and row.get('block_hash',graduation.get('block_hash'))!=through_hash:
                reasons.append('candidate_checkpoint_noncanonical')
        return dict(ready=not reasons,category='COMPLETE' if not reasons else 'INCOMPLETE_EVIDENCE',
                    reasons=reasons,market_wide_coverage_required=False)

    @evidence_work('deep_watch')
    def _increment(self,row,end):
        start=row['block']+1
        if end<start:return
        if end-start>=40:raise BoundaryError('survivor_incremental_slice_required')
        key=PoolKey(**row['graduation']['key']);pool=row['graduation']['transition']['market']
        tape=collect_v4_activity(self.endpoint,pool_id=pool,key=key,token=row['id'],
            start_block=start,end_block=end,max_events=256,acquisition_state=self.history,evidence_context=self._position_context)
        # The preceding boundary must still have the authenticated hash recorded
        # at the last watermark. A fork never becomes clean historical evidence.
        h,previous=self.rpc.batch([('eth_getBlockByNumber',[hex(b),False])
            for b in (end,row['block'])],scope='pons_survivor')
        if int(h['number'],16)!=end or int(previous['number'],16)!=row['block']:
            raise BoundaryError('survivor_header_number')
        expected=row.get('block_hash',row['graduation']['block_hash'])
        if previous['hash']!=expected:
            self._recover_reorg(row)
            raise BoundaryError('survivor_history_reorg')
        self._append_tape(row,end,h,tape)

    def _position_context(self):
        context=getattr(self,'position_evidence_context',None)
        if context is None:
            from .pons_selective_acquisition import SelectiveEvidenceContext
            context=SelectiveEvidenceContext(self.endpoint);self.position_evidence_context=context
        return context

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

    @evidence_work('deep_watch')
    def _increment_candidates(self,rows,top):
        if not rows:return
        population=len(rows)
        pending=[r for r in rows if r.get('block') is not None and r['block']<top]
        if not pending:return
        first=min(pending,key=lambda r:(r.get('history_attempt',0),r['block'],r['id']))['block']
        from .pons_selective_v4 import acquisition_windows
        proposed=[r for r in pending if first<=r['block']<first+160][:64]
        window=acquisition_windows(self.endpoint,
            [r['graduation']['transition']['market'] for r in proposed],self.history).turn_blocks()
        # Separate acquisition credit for overlapping checkpoints: an older
        # recovery cannot claim a newer pool without advancing that pool.
        rows=self.history.history_batch([r for r in pending if first<=r['block']<first+window],top)
        if not rows:return
        start=min(row['block'] for row in rows)+1;end=min(top,start+window-1)
        if end<start:return
        active=[row for row in rows if row['block']<end]
        markets=[dict(pool_id=r['graduation']['transition']['market'],
            key=PoolKey(**r['graduation']['key']),token=r['id']) for r in active]
        tapes=collect_v4_activities(self.endpoint,markets=markets,start_block=start,end_block=end,
            acquisition_state=self.history)
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

    @decision_work(1)
    @evidence_work('final_qualification')
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
        self.facts=dict(now=now,graduation_at=row['graduation']['at'],lineage_proven=True,native_quote=True,
            evidence_acquired_monotonic=state['acquired'],
            price_points=[dict(at=p['at'],price_index=int(p['price'])) for p in points],
            flow_30m=window(now-1800,now+1),flow_previous_30m=window(now-3600,now-1800),
            capital_quote=sizing['realized_equity'],continuity_complete=self.candidate_readiness(row['id'],
                through_block=state['block'],through_hash=state['block_hash'])['ready'],
            execution={},
            organic_flow=flow)
        preview=evaluate_entry(self.facts)
        missing_execution={'missing_roundtrip_loss_bps','missing_double_size_roundtrip_loss_bps'}
        market_ready=(self.facts['continuity_complete'] and
            not (set(preview['all_rejections'])-missing_execution))
        if market_ready:
            capacity=resize(cap,sizing["minimum"],quotes.loss,ordinary_limit=450,stress_limit=650,max_steps=4)
            self.facts['execution']=dict(roundtrip_loss_bps=capacity.ordinary_loss_bps,
                double_size_roundtrip_loss_bps=capacity.double_loss_bps,capacity=capacity.telemetry())
        self.facts['execution_evidence_status']='COMPLETE' if market_ready else 'PENDING_EVIDENCE'
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
        from .pons_quotes import v4_quote as _v4_quote,quote_deadline
        from .evidence import Store
        grad=self.current['graduation'];key=PoolKey(**grad['key'])
        cache=getattr(self,'position_exit_quotes',None)
        cached=cache.get(qty) if cache is not None else None
        if cached and 0<=time.monotonic()-cached['acquired']<=5:
            # Reuse only within this one evaluation at an unchanged current
            # canonical head. Gas is mutable even then and is reacquired. No
            # observed/acquisition clock is renewed, and no full-size quote is
            # substituted for a partial exit. validate_exit() still fences fill.
            try:
                with quote_deadline(self.rpc,cached['acquired']):
                    header,gas=self.rpc.batch([('eth_getBlockByNumber',['latest',False]),
                        ('eth_gasPrice',[])],scope='pons_survivor')
                if (header['hash']==cached['block_hash'] and int(header['number'],16)==cached['block']
                        and 0<=time.monotonic()-cached['acquired']<=5):
                    gas=cached['gas_units']*int(gas,16)
                    return dict(net_proceeds=max(0,cached['amount_out']-gas),quantity=qty,
                        acquired=cached['acquired'],block=cached['block'],block_hash=cached['block_hash'],gas=gas)
            except BoundaryError:
                cache.clear();return None
        if cache is not None:cache.pop(qty,None)
        # A quote is a single fresh, canonical snapshot, not a consecutive
        # block stream. Reusing one Finality scope across three-second turns
        # rejects normal skipped blocks and eventually fills its evidence store.
        # Validate with the existing native snapshot ledger; the economic book
        # durably records the execution, and validate_exit reacquires membership.
        # The old quote-evidence file is retained, with no journal deletion.
        store=Store(':memory:')
        acquired=time.monotonic()
        try:
            q,meta,ledger=_v4_quote(self.rpc,key,grad['transition']['market'],qty,
                grad['transition']['graduation_gas_used'],store,'survivor_exit',local_freshness=True)
            q.check(self.now(),q.market,'sell',qty,q.stamp.kind,finality_ledger=ledger)
            result=dict(net_proceeds=max(0,q.amount_out-q.gas_quote),quantity=qty,
                acquired=acquired,block=meta['block'],block_hash=meta['block_hash'],gas=q.gas_quote)
            if cache is not None:cache[qty]=dict(result,amount_out=q.amount_out,gas_units=meta['gas_units_proxy'])
            return result
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
        # Transient exact-quantity quote reuse has no restart or next-turn
        # authority. The existing native monitor remains the sole exit owner.
        self.position_exit_quotes={}
        try:return self._manage_position(row,admit=admit)
        finally:self.position_exit_quotes=None

    def _position_head(self, row, quote):
        """Reuse the fresh authenticated quote head for this history turn.

        The native sell quote has already purchased a numeric canonical
        membership fence. An immediately repeated `latest` read costs another
        provider element, can move the history past the price snapshot, and
        is unnecessary when the quote is still fresh and ahead of the durable
        history watermark. Invalid/missing/stale quotes keep the original read.
        This is a history target, NEVER a cross-turn or settlement quote reuse.
        """
        if isinstance(quote, dict):
            number=quote.get('block')
            block_hash=quote.get('block_hash')
            acquired=quote.get('acquired')
            prior=row.get('block')
            try:
                age=time.monotonic()-acquired
                fresh=(isinstance(number,int) and type(number) is int
                    and isinstance(block_hash,str) and block_hash.startswith('0x')
                    and isinstance(prior,int) and number>=prior
                    and 0<=age<=5)
            except (TypeError,ValueError):fresh=False
            if fresh and (number!=prior or block_hash==row.get('block_hash',
                    row.get('graduation',{}).get('block_hash'))):
                return dict(number=hex(number),hash=block_hash)
        return _latest_header(self.rpc)

    def _manage_position(self,row,*,admit=True):
        from meme_machine.operational.position_continuation import cancel_unfilled
        if cancel_unfilled(self.book,self.sleeve,self.history,row,self.now()):return
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
            header=self._position_head(row,q);end=int(header['number'],16)
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
        extension=None;factory=getattr(self,'exceptional_context',None)
        if factory is not None:
            try:extension=factory(self,p,row,q,flow,observation)
            except (ValueError,TypeError,KeyError,BoundaryError):extension={}
        action=monitor(book=self.book,sleeve=self.sleeve,identity=row['position'],observation=observation,
                       policy=risk_policy(),adapter=self,exceptional_context=extension)
        row['position_safety']=dict(at=self.now(),evidence_current=header is not None and flow is not None and q is not None,
            exit_quote_available=q is not None,pending_exit=action['action']=='exit_pending',
            blocker='pons_survivor_authenticated_flow_or_exit_quote_unavailable')
        self.history.save(row)
        if action['action']=='hold':
            scale(book=self.book,sleeve=self.sleeve,identity=row['position'],candidate=row['id'],
                generation=row['generation'],adapter=self,qualify=self.qualify,ordinary_limit=450,
                stress_limit=650,minimum=self.sleeve.sizing_basis(500,minimum_bps=5)["minimum"])
        if action['action']=='partial_exit':
            row=self.history.get(row['id']);row['state']='runner';self.history.save(row)
        # No optional provider work occurs until original native risk, exit,
        # accounting and potential scale work have already completed.
        shadow=getattr(self,'held_paper_shadow',None)
        if shadow is not None and shadow.enabled:
            try:
                if action['action']=='hold' and q is not None and p['status']=='open':
                    from .held_paper_shadow import protective_margin_bps
                    from meme_machine.runtime.survivor_commit import restore_risk
                    risk=restore_risk(self.book,row['position'])
                    policy=risk_policy()
                    margin=protective_margin_bps(
                        current=observation['after_cost_return_bps'],
                        high=risk.get('high_water_bps'),
                        stop=policy['hard_stop_bps'],
                        first_profit=policy['first_profit_bps'],
                        trail_bps=policy['trail_bps'],
                        tight_arm=policy['tight_arm_bps'],
                        tight_trail_bps=policy['tight_trail_bps'],
                        partial_taken=risk.get('realization_taken',False))
                    if (risk.get('deterioration_streak',0)>0 or
                            risk.get('last_action',{}).get('action')!='hold' or
                            not row.get('position_safety',{}).get('evidence_current')):
                        margin=0
                    shadow.observe_after_hold(
                        rpc=self.rpc,pool_id=row['graduation']['transition']['market'],
                        quantity=p['tokens'],quote_block=q['block'],
                        quote_hash=q['block_hash'],net_proceeds=q['net_proceeds'],
                        gross_amount_out=q['net_proceeds']+q['gas'],
                        gas_quote=q['gas'],
                        position_open=True,no_pending_exit=True,
                        no_pending_partial=True,owner_protected=True,
                        risk_distance_bps=margin)
                else:
                    shadow.last.pop(row['graduation']['transition']['market'].lower(),None)
            except Exception:
                # A shadow measurement can never block, authorize or delay
                # settlement. The original position decision is already final.
                shadow.counts['isolated_unexpected_probe_error']+=1

    @decision_work(4)
    def step(self,*,admit):
        errors=[]
        try:
            from meme_machine.runtime.storage import compact_survivor
            compact_survivor(self,'pons')
            self._provider()
            def position_priority(row):
                if not row.get('position'):return 2
                try:position=self.book._load(row['position'])
                except ValueError:return 1
                return 0 if position['status']=='open' and position['tokens']>0 else 1
            for row in sorted(self.history.rows(),key=position_priority):
                if row.get('position'):
                    try:self._position(row,admit=admit)
                    except (ValueError,BoundaryError) as exc:
                        errors.append(str(exc));self._failure(row,str(exc),phase='position')
                        from meme_machine.runtime.survivor_commit import exceptional_evidence_failure
                        exceptional_evidence_failure(self,family='pons_survivor',blocker=str(exc),rows=[row])
            if admit:
                # Discovery never depends on population or allocatable capital.
                try:self.discover()
                except (ValueError,BoundaryError) as exc:
                    errors.append(str(exc))
                    self.historical_readiness=dict(ready=False,category='INCOMPLETE_EVIDENCE',
                        reason=str(exc),qualification_authority=False,pre_enrollment_coverage='UNOBSERVED')
            rows=[r for r in self.history.rows() if not r.get('position') and r['state']!='retired']
            if admit and rows:
                for expired in list(rows):
                    if self.now()-expired['graduation']['at']>POLICY['universe']['max_seconds_after_graduation']:
                        self.history.retire(expired,expired_before=self.now()-POLICY['universe']['max_seconds_after_graduation']);rows.remove(expired)
                if getattr(self,'scout',None) is not None:
                    rows=[r for r in rows if self._deep_watch_due(r,self.now())]
                if rows:
                    top=int(_latest_header(self.rpc)['number'],16)
                    signals={r['id']:self.scout.signal(r['graduation']['transition']['market'])
                        for r in rows} if getattr(self,'scout',None) is not None else {}
                    try:self._increment_candidates(rows,top)
                    except (ValueError,BoundaryError) as exc:errors.append(str(exc))
                    rows=[self.history.get(r['id']) for r in rows]
                    if getattr(self,'scout',None) is not None:
                        for r in rows:
                            if r['block']==top:
                                r['scout_hydrated_signal']=signals[r['id']]
                                self.history.save(r)
            if admit and rows:
                row=self.history.qualification_turn(rows,self.now())
                age=self.now()-row['graduation']['at']
                if age>POLICY['universe']['max_seconds_after_graduation']:self.history.retire(row,expired_before=self.now()-POLICY['universe']['max_seconds_after_graduation'])
                else:
                    end=top
                    self._increment(row,min(end,row['block']+40));row=self.history.get(row['id'])
                    if age<POLICY['universe']['min_seconds_after_graduation']:row['state']='aging';self.history.save(row)
                    elif end-row['block']<=40:
                        signal=self.scout.signal(row['graduation']['transition']['market']) if getattr(self,'scout',None) else None
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
                        if getattr(self,'scout',None) is not None:self._schedule_watch(row,state['at'],signal)
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
            from meme_machine.runtime.survivor_commit import exceptional_evidence_failure
            exceptional_evidence_failure(self,family='pons_survivor',blocker=str(exc))
            if 'row' in locals() and row and row.get('id'):
                self._failure(row,str(exc))
        from meme_machine.runtime.directional_accounting import execution_cost
        self.attempts.maintain(self.now(),protected=(r['id'] for r in self.history.rows()))
        return dict(strategy=STRATEGY_VERSION,policy_hash=POLICY_HASH,active=True,paper_only=True,
                    position_safety=[r.get('position_safety',dict(at=0,evidence_current=False,
                        blocker='pons_survivor_position_not_observed')) for r in self.history.rows() if r.get('position')],
                    native_execution_cost=execution_cost(self.book),
                    candidate_count=len(self.history.rows()),last_boundary=self.last_error,
                    discovery_capacity_deferred=False,
                    pending_graduations=self.history.pending_graduations(),
                    deferred_boundaries=errors,
                    acquisition=getattr(self,'acquisition',None),
                    historical_readiness=getattr(self,'historical_readiness',None),
                    qualification_authority='candidate_specific_authenticated_evidence',
                    accounting=self.book.reconcile(),accounting_replay=self.book.replay(),
                    policies=self.sleeve.identity['policies'],sleeve=self.sleeve.reconcile(),
                    durable_handoff=handoff_ready(self.book,self.history.rows()),
                    held_paper_shadow=(getattr(self,'held_paper_shadow',None).status()
                        if getattr(self,'held_paper_shadow',None) is not None else
                        dict(enabled=False,mode='PAPER_SHADOW_ONLY')))

    def close(self):
        shadow=getattr(self,'held_paper_shadow',None)
        if shadow is not None:shadow.close()
        self.book.close();self.history.close();self.sleeve.close();self.plane.close()
