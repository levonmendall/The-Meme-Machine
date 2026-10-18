"""Active Pump Survivor inside the Pump sleeve, on the Solana Evidence Plane.

One incremental monitoring task, at most one candidate hydration per turn. It
never scans RPC history and never qualifies from public websocket discoveries.
"""
from meme_machine.runtime.provider_purchases import attributed_work
from contextlib import nullcontext
from fractions import Fraction
import json
import os
from pathlib import Path
import time

from meme_machine.runtime.directional_sleeve import open_sleeve
from meme_machine.runtime.execution_capacity import buyer_persistence
from meme_machine.runtime.journal import digest
from meme_machine.runtime.survivor_commit import commit,monitor,handoff_ready,scale
from meme_machine.runtime.survivor_history import History
from meme_machine.runtime.isolated_native_bootstrap import survivor_constructor
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.solana_evidence_plane import decode_body
from .engine import GAS,MAYHEM_AGENT_WALLET
from .postgrad import PostGraduationAdapter,graduation_handoff,buy_quote,sell_quote,held_rpc_mode
from .provider import Unavailable
from .solana_read_rpc import new_rpc
from .solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE,SWAP_SCOPE
from .pumpswap_survivor import POLICY,POLICY_HASH,STRATEGY_ID,evaluate_entry
from .pumpswap_survivor_evidence import SOL_USD_ACCOUNT,sol_usd_lower_micros


class Quotes:
    def __init__(self,state,now):self.state=state;self.acquired=now
    def entry(self,budget):
        if budget<=GAS:raise ValueError('survivor_dust')
        q=buy_quote(self.state,budget-GAS)
        return dict(cost=q.input_amount+GAS,quantity=q.output_amount,slot=self.state['slot'],
                    acquired=self.acquired,market_time=self.state['market_time'],gas=GAS,fee=q.fee_amount)
    def loss(self,budget):
        try:
            q=self.entry(budget);out=sell_quote(self.state,q['quantity']).output_amount
            return max(0,(q['cost']-max(0,out-GAS))*10000//q['cost'])
        except (ValueError,Unavailable,ZeroDivisionError):return None


class Runtime:
    @survivor_constructor('pump')
    def __init__(self,root,capital,run_id,confirmations,*,native_resources=None,native_ports=None):
        self.native_resources=None;self.native_ports=None
        if native_resources is not None:
            from meme_machine.runtime.isolated_native_bootstrap import validate_survivor_constructor
            self.native_resources=validate_survivor_constructor(root,capital,run_id,'pump',native_resources,native_ports)
            self.native_ports=native_ports
        elif native_ports is not None:raise ValueError('isolated_native_resources_required')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.capital=capital;self.run_id=run_id;self.confirmations=confirmations
        if self.native_resources is None:
            self.sleeve=open_sleeve('pump',capital)
            if self.sleeve is None:raise ValueError('survivor_shared_sleeve_required')
            self.history=History(str(self.root/'history.sqlite'),policy=POLICY_HASH)
        else:
            self.sleeve=open_sleeve('pump',None,native_resources=self.native_resources)
            self.history=self.native_resources.survivor_history('pump')
        self.history.volume_quote_asset='SOL'
        from meme_machine.runtime.survivor_history import compact_restored_history
        from .pumpswap_survivor import reduce_reset_history
        compact_restored_history(self.history,lane='pump',reducer=reduce_reset_history)
        if self.native_resources is None:
            self.book=PaperBook(str(self.root/'paper.sqlite'),run_id=run_id,lane=STRATEGY_ID,
                                policy_hash=POLICY_HASH,initial=capital)
            from meme_machine.runtime.survivor_terminal_archive import compact
            compact(self.book,self.sleeve,self.history)
            self.plane=RuntimeEvidence(owner='pump:survivor')
            from meme_machine.runtime.candidate_history import open_candidate_history
            self.candidate_history=open_candidate_history()
        else:
            self.book=None
            self.plane=self.native_ports.pump_evidence('pump:survivor')
            self.candidate_history=self.native_resources.candidate_history()
        self.rpc=None;self.current=None;self.last_error=None
        if self.native_resources is not None:
            from meme_machine.runtime.isolated_native_bootstrap import require_bookless_runtime
            require_bookless_runtime(self,'pump')

    def now(self):
        resources=getattr(self,'native_resources',None)
        return int(resources.clock()) if resources is not None else int(time.time())

    def _quality_rank(self,row,now):
        from meme_machine.runtime.volume_quality import attention
        if row.get('complete') is not True or row.get('recovery'):return 0
        return attention(row.get('volume_quality'),now)

    def _provider(self,priority=30):
        if self.rpc is None or self.rpc.calls>160:
            pacer=None if self.rpc is None else self.rpc.read_pacer
            self.rpc=(new_rpc(limit=240,pacer=pacer) if getattr(self,'native_resources',None) is None else
                self.native_ports.pump_rpc('survivor',limit=240,pacer=pacer))
            self.rpc.evidence_priority=priority
            self.adapter=PostGraduationAdapter(self.rpc)
            if held_rpc_mode()=='optimized':
                self.adapter.finalized_market_time=self._local_finalized_time
        self.rpc.evidence_priority=priority
        self.rpc.evidence_kind='survivor_monitor' if priority==30 else 'survivor_commit_or_exit'

    @attributed_work('pump_discovery')
    def discover(self):
        from meme_machine.solana_selective_runtime import selective
        selected=selective(self.plane._selective_reader()) if hasattr(self.plane,'_selective_reader') else False
        top=self.plane.frontier(PUMP_SCOPE)
        cursor=self.history.get_meta('discovery_slot')
        if cursor is None and not selected:
            self.history.set_meta('discovery_slot',max(0,top-1));return
        if selected:
            sequence=self.history.get_meta('discovery_sequence') or 0
            delivery=self.plane.reader.discovery(sequence,as_of=time.time())
            rows=[decode_body(row[1],self.plane.reader.db) for row in delivery]
            end=top
        else:
            if top<=cursor:return
            end=min(top,cursor+64)
            rows=self.plane.reader.window(PUMP_SCOPE,cursor+1,end,as_of=time.time(),kind='event',limit=10000)
        for row in rows:
            event=row['payload']['event']
            if event.get('event_type')!='migration' or event.get('quote_asset')!='SOL':continue
            evidence=dict(event,at=event['market_time'],identity=row['identity'],
                          signature=row['signature'],source='solana_finalized_evidence_plane')
            prior=self.history.get(event['mint'])
            if prior is None and self.history.expired(evidence):continue
            current=self.history.graduate(event['mint'],evidence)
            if current['state']=='retired':continue
            if prior is None:
                self.history.append(event['mint'],through=event['market_time'],events=[],
                    points=[(event['market_time'],str(Fraction(event['quote_amount'],event['mint_amount'])))],complete=True)
            self.plane.interest(SWAP_SCOPE,lower_slot=event['slot'],addresses=[event['pool']],
                lifecycle='candidate',priority=4,owner='pump:survivor:'+event['mint'])
        if selected:
            if delivery:self.history.set_meta('discovery_sequence',delivery[-1][0])
        else:self.history.set_meta('discovery_slot',end)

    def _increment(self,row,at,slot):
        row=self.history.get(row['id'])
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        from meme_machine.solana_selective_history import ConsumerReader
        reader=self.plane._selective_reader()
        db=reader.original.db if isinstance(reader,ConsumerReader) else reader.db
        # A durable incremental checkpoint does not seal its retained prefix
        # against a subsequently observed gap. Recheck the exact required
        # history without hydrating it or changing its historical observations.
        db.execute('BEGIN')
        try:
            graduation=row['graduation'];lower=graduation.get('slot');upper=slot
            if lower is None:
                lower,_=self.plane.bounds(SWAP_SCOPE,graduation['at'],at,upper_slot=slot)
            elif type(lower) is not int or lower<0:
                raise EvidenceUnavailable('survivor_graduation_slot_unverified')
            candidate=reader.candidate('pumpswap',row['graduation']['pool']) if isinstance(reader,ConsumerReader) else reader
            scope=candidate.scope if isinstance(reader,ConsumerReader) else SWAP_SCOPE
            if not candidate.covered(scope,lower,upper,as_of=time.time()):
                raise EvidenceUnavailable('unresolved_evidence_gap')
        finally:db.execute('ROLLBACK')
        checkpoint=row.get('evidence_checkpoint')
        if checkpoint and checkpoint['through']==at and checkpoint['consumed_slot']==slot:
            self._ack_history_checkpoint(row,checkpoint);return
        grad=row['graduation'];lo,hi=self.plane.bounds(SWAP_SCOPE,row['through'],at,upper_slot=slot)
        records=self.plane.reader.window(SWAP_SCOPE,lo,hi,as_of=time.time(),address=grad['pool'],kind='event',limit=10000)
        def order(record):
            index=record['transaction_index']
            if index is None:
                proof=self.plane.reader.db.execute('SELECT rank FROM stream_order WHERE scope=? AND slot=? AND signature=?',
                    (SWAP_SCOPE,record['slot'],record['signature'])).fetchone()
                if proof is None:raise ValueError('survivor_trade_order_unknown')
                index=proof[0]
            return record['slot'],index,record['event_index']
        records.sort(key=order)
        multiple={}
        for record in records:multiple.setdefault(record['slot'],set()).add(record['signature'])
        events=[];points={}
        for record in records:
            e=dict(record['payload']['event']);t=e['market_time']
            if len(multiple[record['slot']])>1:e['_economic_order']=order(record)[1]
            if not row['through']<=t<=at:continue
            shared=getattr(self,'candidate_history',None)
            if shared is not None:
                shared.observe('pump',row['id'],surface='pumpswap',
                    observed_at=grad['at'],metadata=dict(pool=grad['pool']))
                shared.retain_pumpswap_record(row['id'],record,order(record)[1])
            price=Fraction(e['pool_quote_reserve'],e['pool_base_reserve'])
            prior=points.get(t,dict(low=str(price),high=str(price)))
            points[t]=dict(price=str(price),low=str(min(price,Fraction(prior['low']))),
                           high=str(max(price,Fraction(prior['high']))))
            events.append(dict(id=record['identity'],at=t,group=self.confirmations.cluster(e['wallet']),
                wallet=e['wallet'],buy=e['buy'],quote=e['amount'],tokens=e['tokens'],
                price=str(price),authenticated=True))
        lower=max(lo,slot-1)
        checkpoint=dict(scope=SWAP_SCOPE,lower_slot=lower,consumed_slot=hi,through=at,
            evidence_hash=digest([(r['identity'],digest(r)) for r in records]))
        self.history.append(row['id'],through=at,events=events,points=sorted(points.items()),
            complete=True,evidence_checkpoint=checkpoint)
        self._ack_history_checkpoint(row,checkpoint)

    def _ack_history_checkpoint(self,row,checkpoint):
        owner='pump:survivor:'+row['id']
        self.plane.interest(SWAP_SCOPE,lower_slot=checkpoint['lower_slot'],addresses=[row['graduation']['pool']],
            lifecycle='open' if row.get('position') else 'candidate',priority=0 if row.get('position') else 4,
            owner=owner)
        self.plane.advance_interest(SWAP_SCOPE,lower_slot=checkpoint['lower_slot'],consumed_slot=checkpoint['consumed_slot'],
            checkpoint_hash=digest(checkpoint),owner=owner)

    def _local_finalized_time(self, slot):
        # A stream receipt must belong to this *exact* finalized account slot.
        # If coverage is behind, the postgrad adapter uses the original RPC.
        self.plane.require_usable(SWAP_SCOPE)
        if self.plane.frontier(SWAP_SCOPE)<slot:return None
        return self.plane.block_time(slot)

    def fresh_state(self,candidate,priority=1,*,maintenance=False):
        self._provider(priority);self.current=self.history.get(candidate)
        if maintenance and held_rpc_mode()=='optimized':
            # A co-slot fresh curve AND quote; no creator or price reuse.
            state=self.adapter.pumpswap_snapshot(
                candidate,self.now(),priority=True,
                reuse_verified_pool=True,held_curve_inline=True)
        else:
            # Original provider path remains available for a controlled
            # same-source live PAPER baseline. Qualification is never altered.
            raw=self.adapter.graduation_snapshot(candidate,self.now(),priority=True)
            handoff=graduation_handoff(raw,self.now())
            state=self.adapter.pumpswap_snapshot(
                handoff,self.now(),priority=True,
                additional_accounts=() if maintenance else (SOL_USD_ACCOUNT,))
        if state['pool']!=self.current['graduation']['pool']:raise ValueError('survivor_pool_drift')
        return state

    def fresh_quotes(self,state,budget):return Quotes(state,self.now())

    def position_policy(self,risk,policy):
        # The original filled native journal owns this profile. Maturing beyond
        # four hours, scaling and restarting cannot loosen a bridge's protection.
        return POLICY['bridge_exits'] if risk.get('execution_profile')=='pump_postgrad_bridge' else policy

    def necessary_scale_return(self,state,position,risk):
        """Exact native sell arithmetic; no extra acquisition or retained quote."""
        try:
            if not (0<=self.now()-state['available_time']<=5
                    and 0<=self.now()-state['market_time']<=10):return None
            self.plane.require_usable(SWAP_SCOPE)
            q=sell_quote(state,position['tokens'])
            from meme_machine.runtime.directional_continuation import reference_return
            return reference_return(max(0,q.output_amount-GAS),position['tokens'],
                risk['original_basis'],risk['original_quantity'])
        except (ValueError,Unavailable,KeyError,TypeError,ZeroDivisionError):return None

    def reconstruct(self,state,quote_context,*,maintenance=False):
        row=self.current;at=state['market_time'];self._increment(row,at,state['slot'])
        price=Fraction(state['state']['quote_reserve'],state['state']['base_reserve'])
        self.history.append(row['id'],through=at,events=[],points=[(at,str(price))],complete=True)
        row=self.history.get(row['id'])
        recomputation_blocker=row.get('policy_recomputation_blocker')
        if maintenance or recomputation_blocker:
            points,events=self.history.facts(row['id'],at);reset_prefix=self.history.prefix(row['id'])
        else:
            from .pumpswap_survivor import reduce_reset_history
            points,events,reset_prefix=self.history.calculation_facts(row['id'],at,
                reducer=reduce_reset_history,policy=POLICY_HASH)
        grad=row['graduation'];creator=self.confirmations.cluster(state['creator'])
        mayhem=state['state']['mayhem_mode']
        agents={self.confirmations.cluster(MAYHEM_AGENT_WALLET)} if mayhem else set()
        from meme_machine.runtime import volume_quality as vq
        if vq.enabled() and not maintenance and not row.get('position'):
            row=self.history.get(row['id'])
            row['volume_quality_excluded']=sorted(agents|{creator})
            row['volume_quality']=self.history.volume_signal(row,self.now())
            row['volume_quality_requalification_due']=False
            self.history.save(row)
        organic=[e for e in events if e['group'] not in agents and e['group']!=creator]
        age=at-grad['at']
        tier=next((t for t in POLICY['bridge_tiers']
                   if t['minimum_age_seconds']<=age<t['maximum_age_seconds']),None)
        demand_seconds=POLICY['demand_window_seconds'] if tier is None else tier['demand_window_seconds']
        recent=[e for e in organic if at-demand_seconds<=e['at']<=at]
        tokens=sum(e['tokens'] for e in recent)
        vwap=None if tokens<=0 else str(Fraction(sum(e['quote'] for e in recent),tokens))
        from meme_machine.lanes.pump.runner import _postgrad_concentration
        # Held-position risk uses authenticated demand/creator flow and the full
        # executable exit. Holder/USD gates belong to entry and fresh additions;
        # scale() reacquires them independently before any added exposure.
        concentration=None if maintenance else _postgrad_concentration(self.rpc,state)
        usd=None if maintenance else sol_usd_lower_micros(
            state['additional_accounts'][SOL_USD_ACCOUNT],now=self.now(),slot=state['slot'])
        base_end=max((p['at'] for p in points if p['at']<=at-60),default=None)
        facts=dict(now=at,graduation_at=grad['at'],lineage_proven=True,origin='pump.fun',venue='pumpswap',
            canonical_migration_pool=True,quote_asset='SOL',authoritative=True,
            continuity_complete=self.history.get(row['id'])['complete'],demand_complete=True,
            creator_distribution_safe=not any(not e['buy'] and e['group']==creator for e in events),
            hard_concentration_pass=None if maintenance else concentration<=POLICY['maximum_holder_concentration_bps'],
            exit_liquidity_available=state['state']['raw_quote_reserve']>0,
            migration_price=str(Fraction(grad['quote_amount'],grad['mint_amount'])),
            liquidity_usd_micros=None if maintenance else 2*state['state']['raw_quote_reserve']*usd//10**9,
            # The immutable coin flag proves whether it is a Mayhem coin. It
            # does not prove the agent's completion time. Never infer completion
            # from absent trades or elapsed age; without that evidence entry is
            # blocked, even though the disclosed agent flow can be excluded.
            mayhem=dict(status='unknown' if mayhem else 'never',agent_identity_proven=mayhem,
                        agent_groups=sorted(agents)),price_points=points,base_end=base_end,
            reset_history_prefix=reset_prefix,qualification_evidence_complete=not maintenance,
            reset_history_revision_detail_unavailable=recomputation_blocker,
            qualification_purpose=self._qualification_purpose(row),
            evidence_acquired_at=state['available_time'],evidence_available_at=self.now(),
            decision_at=self.now(),canonical_slot=state['slot'],
            canonical_evidence_checkpoint=row.get('evidence_checkpoint'),
            recovery_vwap=vwap,demand_events=organic,holder_concentration_bps=concentration)
        if vq.enabled() and not maintenance:facts['volume_quality']=row.get('volume_quality')
        self.facts=facts;return facts

    def _qualification_purpose(self,row):
        """Only an actually filled, still open position gets ongoing rules.

        A controller row persisted before reservation/fill retains every initial
        entry-age check. Restart never turns pending entry into an addition.
        """
        if row.get('position'):
            try:
                if self.book._load(row['position'])['status']=='open':return 'ongoing'
            except ValueError:pass
        return 'entry'

    def turnover_cap(self,facts,decision):return decision['features']['turnover_cap']
    def generation_fence(self,candidate,generation):return nullcontext() # sleeve is the Pump generation authority
    def validate_current(self,state,execution,now):
        self.plane.require_usable(SWAP_SCOPE)
        if not 0<=now-state['market_time']<=10 or not 0<=now-execution['acquired']<=5:
            raise ValueError('survivor_stale_commit')
        if execution['slot']!=state['slot']:raise ValueError('survivor_quote_state')

    def exit_quote(self,qty,*,state=None):
        try:
            self._provider(0)
            # A caller may share the just-authenticated snapshot within this
            # evaluation, never a cached quote from a preceding turn or restart.
            # Settlement still calls exit_quote() without state and reacquires.
            if state is None or not (0<=self.now()-state['available_time']<=5
                    and 0<=self.now()-state['market_time']<=10):
                state=self.fresh_state(self.current['id'],priority=0,maintenance=True)
            self.plane.require_usable(SWAP_SCOPE)
            q=sell_quote(state,qty)
            return dict(net_proceeds=max(0,q.output_amount-GAS),quantity=qty,
                acquired=state['available_time'],market_time=state['market_time'],slot=state['slot'])
        except (ValueError,Unavailable):return None

    def validate_exit(self,quote,qty,now):
        if quote['quantity']!=qty or not 0<=now-quote['market_time']<=10 or not 0<=now-quote['acquired']<=5:
            raise ValueError('survivor_exit_quote_stale')

    @attributed_work('pump_held_protection',consumer='survivor')
    def _position(self,row,*,admit=True):
        from meme_machine.operational.position_continuation import cancel_unfilled
        if cancel_unfilled(self.book,self.sleeve,self.history,row,self.now()):return
        self.current=row
        try:position=self.book._load(row['position'])
        except ValueError:
            if not admit:raise ValueError('survivor_continuation_unfilled_controller')
            return self._enter(row,row['decision'],row['generation'],row['regime'],row['position'])
        if position['status'] in ('settled','cancelled'):
            self.sleeve.release(row['position'],pnl=position['realized'],at=position['last_at'],
                terminal_hash=digest(position),native_verified=self.book.replay()['verified'],cancelled=position['status']=='cancelled')
            row.update(position=None,state='settled');self.history.save(row);return
        if position['status']=='reserved':
            if not admit:raise ValueError('survivor_continuation_reservation')
            # Reconstruct the exact qualified decision, then reacquire every fresh
            # input; a persisted successful validation has no restart authority.
            return self._enter(row,row['decision'],row['generation'],row['regime'],row['position'])
        state=None;facts=None
        try:
            state=self.fresh_state(row['id'],priority=0,maintenance=True)
            facts=self.reconstruct(state,Quotes(state,self.now()),maintenance=True)
        except (ValueError,Unavailable):pass
        q=self.exit_quote(position['tokens'],state=state)
        net=None if q is None else q['net_proceeds']
        flow={} if facts is None else buyer_persistence(facts['demand_events'],now=facts['now'],window_seconds=1800)
        observation=dict(id=str(state['slot']) if state else 'unavailable:'+str(self.now()),at=self.now(),
            evidence_current=state is not None and facts is not None and q is not None,
            after_cost_return_bps=None if net is None else (net-position['basis'])*10000//position['basis'],
            net_exit_proceeds=position['mark'] if net is None else net,
            exit_liquidity_valid=True if q is not None else None,creator_distribution=facts is not None and not facts['creator_distribution_safe'],
            soft_deterioration=None if not flow else flow['buy_flow']<=flow['sell_flow'] and flow['new_buyers']==0)
        extension=None;factory=getattr(self,'exceptional_context',None)
        if factory is not None:
            try:extension=factory(self,position,row,state,facts,observation)
            except (ValueError,TypeError,KeyError,Unavailable):extension={}
        action=monitor(book=self.book,sleeve=self.sleeve,identity=row['position'],observation=observation,
                       policy=POLICY['exits'],adapter=self,exceptional_context=extension)
        row['position_safety']=dict(at=self.now(),evidence_current=state is not None and facts is not None and q is not None,
            exit_quote_available=q is not None,pending_exit=action['action']=='exit_pending',
            blocker='pump_survivor_authenticated_state_flow_or_exit_quote_unavailable')
        self.history.save(row)
        if action['action']=='hold' and row['position_safety']['evidence_current']:
            scale(book=self.book,sleeve=self.sleeve,identity=row['position'],candidate=row['id'],
                generation=row['generation'],adapter=self,qualify=evaluate_entry,ordinary_limit=600,
                stress_limit=600,minimum=GAS*2+1)
        if action['action']=='partial_exit':
            row=self.history.get(row['id']);row['state']='runner';self.history.save(row)

    @attributed_work('pump_survivor_qualification')
    def _enter(self,row,decision,generation,regime,identity):
        sizing=self.sleeve.sizing_basis(POLICY["target_sleeve_bps"])
        try:
            result=commit(book=self.book,sleeve=self.sleeve,identity=identity,candidate=row['id'],generation=generation,
                strategy=STRATEGY_ID,policy_hash=POLICY_HASH,decision=decision,regime=regime,at=self.now(),
                target=sizing["target"],minimum=GAS*2+1,retention_bps=5000,
                ordinary_limit=600,stress_limit=600,adapter=self,qualify=evaluate_entry)
        except (ValueError,Unavailable) as exc:
            # Use the existing qualification's one durable funding disposition.
            # A fresh safety/quote failure is also a missed eligible opportunity;
            # it is never relabeled as a fill or sent to another strategy worker.
            try:materialized=self.book._load(identity)['status'] in ('open','settled')
            except ValueError:materialized=False
            if not materialized:
                self._funding(row,'denied',str(exc),dict(lifecycle_id=identity,sizing=sizing,
                    phase='native_reservation_or_fresh_execution_validation'))
            from meme_machine.runtime.survivor_commit import unmaterialized_entry_rejection
            if unmaterialized_entry_rejection(self.book,self.sleeve,identity,exc):
                current=self.history.get(row['id'])
                if current.get('position')==identity and current.get('state')=='reserved':
                    current.update(position=None,state='breakout_watch')
                    current['entry_rejection']=dict(identity=identity,reason=str(exc),at=self.now(),
                        native_absence_verified=True)
                    self.history.save(current)
            raise
        self._funding(row,'funded',details=dict(lifecycle_id=identity,sizing=sizing))
        return result

    def _decision(self,row,decision,at):
        shared=getattr(self,'candidate_history',None)
        if shared is None:return
        row['decision_id']=shared.record_decision('pump',row['id'],mode='survivor',
            observed_at=at,qualified=bool(decision['candidate']),
            decision=dict(qualification=decision,policy_hash=POLICY_HASH))

    def _funding(self,row,status,reason=None,details=None):
        shared=getattr(self,'candidate_history',None)
        if shared is not None and row.get('decision_id'):
            decision=row.get('decision') or {}
            bridge=decision.get('features',{}).get('execution_profile')=='pump_postgrad_bridge'
            details=dict(details or {})
            details.update(execution_profile=decision.get('features',{}).get('execution_profile'),
                missed_eligible_bridge=bridge and decision.get('candidate') is True and status=='denied',
                policy_comparison=decision.get('policy_comparison'))
            shared.record_funding(row['decision_id'],'pump',row['id'],
                status=status,at=self.now(),reason=reason,details=details)

    def _allocation_allowed(self,row,decision):
        from meme_machine.runtime.isolated_native_admission import survivor_allocation_allowed
        return survivor_allocation_allowed(self,row,decision,lane='pump',policy=POLICY_HASH)

    def _publish_qualification(self,row,decision,regime,*,state):
        if getattr(self,'native_resources',None) is not None:
            from meme_machine.runtime.isolated_native_admission import require_survivor_resources
            require_survivor_resources(self,'pump')
        observed=self.sleeve.observe(row['id'],strategy=STRATEGY_ID,at=state['market_time'],
            state='qualified' if decision['candidate'] else decision['stage'],evidence=decision,regime=regime)
        # Preserve the first observed cycle instead of moving its breakout.
        regime=observed['regime']
        self.sleeve.opportunity(row['id'],identity=row['id'],regime='survivor',
            status=observed['state'],at=state.get('market_time',state.get('at')),decision=decision)
        row=self.history.get(row['id']);row.update(state=observed['state'],decision=decision,
            generation=observed['generation'],regime=regime)
        self._decision(row,decision,state['market_time'])
        self.history.save(row)
        return row,observed,regime

    def step(self,*,admit):
        from meme_machine.runtime.isolated_native_bootstrap import maintain_bookless_runtime
        bookless=maintain_bookless_runtime(self,'pump')
        discovery_deferred=False
        try:
            from meme_machine.runtime.storage import compact_survivor
            if not bookless:compact_survivor(self,'pump')
            rows=self.history.rows()
            for row in rows:
                if row.get('position'):
                    self._position(row,admit=admit)
            if admit:
                # Candidate count is never observation authority. Discovery always
                # continues; the historical limit is retained only as pressure
                # telemetry. Expensive evaluation remains one candidate per turn.
                rows_now=self.history.rows()
                discovery_deferred=False
                if (self.history.maximum_candidates is not None
                        and len(rows_now)>=self.history.maximum_candidates):
                    self.last_error='survivor_candidate_capacity_pressure'
                self.discover()
            rows=[r for r in self.history.rows() if not r.get('position') and r['state']!='retired']
            if admit and rows:
                # Fair, lossless scheduling: oldest checked candidate first so a
                # quiet older row cannot permanently starve later graduations.
                row=min(rows,key=lambda r:(int(r.get('last_checked') or 0),
                    -self._quality_rank(r,self.now()),int(r['graduation']['at']),r['id']))
                row['last_checked']=self.now();self.history.save(row)
                age=self.now()-row['graduation']['at']
                if age>POLICY['maximum_age_seconds']:
                    self.history.retire(row,expired_before=self.now()-POLICY['maximum_age_seconds'])
                    self.plane.command(op='release',owner='pump:survivor:'+row['id'],scope=SWAP_SCOPE,resolved=False)
                else:
                    # Incremental local monitoring starts at graduation, without
                    # RPC hydration or entry authority before the ten-minute floor.
                    top=self.plane.frontier(SWAP_SCOPE);at=self.plane.block_time(top)
                    self._increment(row,at,top)
                    if age<POLICY['minimum_age_seconds']:row=self.history.get(row['id']);row['state']='aging';self.history.save(row)
                    else:
                        state=self.fresh_state(row['id'],priority=30)
                        qualification_facts=self.reconstruct(state,Quotes(state,self.now()))
                        decision=evaluate_entry(qualification_facts)
                        row=self.history.get(row['id'])
                        f=decision['features'];regime=dict(at=state['market_time'],
                            high_reset_cycle=[f.get('peak_at'),f.get('reset_at')],base_id=[f.get('base_low'),f.get('base_high')],
                            buyer_population=f.get('buyer_groups'),independent_demand=f.get('independent_buyers'),
                            flow_regime='buy' if f.get('buy_flow',0)>f.get('sell_flow',0) else 'sell')
                        if decision['candidate']:
                            from meme_machine.runtime.rally_cycle import build_cycle
                            regime['rally_cycle']=build_cycle(candidate=row['id'],venue='pumpswap',
                                chain='solana-mainnet',pool=row['graduation']['pool'],
                                policy_hash=POLICY_HASH,input_version='pump-postgrad-canonical-history-v1',
                                graduation=row['graduation'],peak_at=f['peak_at'],reset_at=f['reset_at'],
                                base_start=f['base_start'],base_end=f['base_end'],breakout_at=f['breakout_at'],
                                decision_at=self.now(),evidence_id=digest(dict(
                                    slot=state['slot'],checkpoint=row.get('evidence_checkpoint'),
                                    historical_evidence_hash=digest(dict(
                                        graduation=row['graduation'],points=qualification_facts['price_points'],
                                        prefix=qualification_facts.get('reset_history_prefix'))))),
                                authoritative=True,complete=row['complete'],
                                minimum_base_seconds=f['base_seconds'])
                        blocked=row.get('extension_blocked_regime')
                        if blocked:
                            # This is an untraded overextension watch, so it has
                            # no native settlement. Preserve its original hour
                            # spacing plus changed reset AND base; settlement
                            # verification belongs to an actually traded cycle.
                            changed=(regime['at']-blocked['at']>=POLICY['reentry']['minimum_seconds']
                                     and blocked['base_id']!=regime['base_id']
                                     and blocked['high_reset_cycle']!=regime['high_reset_cycle'])
                            if not changed:
                                decision['candidate']=False;decision['all_rejections'].append('extension_requires_new_reset_base')
                        if any(reason in decision['all_rejections'] for reason in ('price_extension','base_range_extension')):
                            row['extension_blocked_regime']=regime;self.history.save(row)
                        row,observed,regime=self._publish_qualification(row,decision,regime,state=state)
                        if decision['candidate'] and self._allocation_allowed(row,decision):
                            sizing=self.sleeve.sizing_basis(POLICY["target_sleeve_bps"])
                            if int(sizing.get('allocatable_target',0)) < GAS*2+1:
                                # Qualification remains durable even when funding is
                                # unavailable. Do not mint a fake reserved position.
                                row['position']=None
                                row['state']='qualified_but_capital_unavailable'
                                self._funding(row,'denied','survivor_minimum_capital',sizing)
                                self.sleeve.opportunity(
                                    row['id'],identity=row['id'],regime='survivor',
                                    status=row['state'],at=state.get('market_time',state.get('at')),
                                    decision=dict(decision,funding_reason='survivor_minimum_capital'))
                            else:
                                from meme_machine.runtime.lifecycle_identity import issue
                                row['position']=issue(self.run_id+':'+digest([STRATEGY_ID,row['id'],regime]))
                                row['state']='reserved';self.history.save(row)
                                try:
                                    self._enter(row,decision,observed['generation'],regime,row['position'])
                                except ValueError as exc:
                                    row=self.history.get(row['id'])
                                    # _enter alone may clear a proved unused
                                    # identity. Real or uncertain native work
                                    # retains its controller and recovery path.
                                    if row.get('position') is not None:raise
                                    from meme_machine.shared_capital.native_sleeve import FundingDenied
                                    if isinstance(exc,FundingDenied) or str(exc) in ('survivor_minimum_capital','sleeve_capital_exhausted'):
                                        row['state']='qualified_but_capital_unavailable'
                                    self._funding(row,'denied',str(exc),sizing)
                                    self.sleeve.opportunity(
                                        row['id'],identity=row['id'],regime='survivor',
                                        status=row['state'],at=state.get('market_time',state.get('at')),
                                        decision=dict(decision,funding_reason=str(exc)))
                                else:
                                    row=self.history.get(row['id']);row['state']='filled'
                        self.history.save(row)
            self.last_error=None
        except (ValueError,Unavailable) as exc:
            self.last_error=str(exc)
            from meme_machine.runtime.survivor_commit import exceptional_evidence_failure
            exceptional_evidence_failure(self,family='pump_survivor',blocker=str(exc))
        result=dict(strategy=STRATEGY_ID,policy_hash=POLICY_HASH,active=True,paper_only=True,
                    rally_lifecycles=None if bookless else self.sleeve.rally_report(),
                    execution_work_model=dict(owner='existing_pump_survivor_worker',
                        intake='canonical_solana_evidence_plane',additional_workers=0,
                        additional_broad_market_scans=0,new_candidates_per_turn_limit=1,
                        commit_state_refresh_limit=2,counterfactual_full_history_evaluations=0,
                        comparison_cost='existing_predicates_and_constant_age_comparison'),
                    pump_held_rpc=dict(
                        mode=held_rpc_mode(),
                        verified_pool_probe_reuses=getattr(getattr(self,'adapter',None),
                            'held_pumpswap_probe_reuses',0),
                        finalized_slot_time_reuses=getattr(getattr(self,'adapter',None),
                            'held_finalized_time_reuses',0),
                        physical_http_requests=getattr(getattr(self,'rpc',None),
                            'http_requests',0)),
                    position_safety=[r.get('position_safety',dict(at=0,evidence_current=False,
                        blocker='pump_survivor_position_not_observed')) for r in self.history.rows() if r.get('position')],
                    candidate_count=len(self.history.rows()),last_boundary=self.last_error,
                    discovery_capacity_deferred=discovery_deferred,
                    candidate_capacity_pressure=(
                        self.history.get_meta('candidate_capacity_pressure') or 0),
                    accounting=None if bookless else self.book.reconcile(),
                    accounting_replay=None if bookless else self.book.replay(),
                    policies=self.sleeve.identity['policies'],sleeve=None if bookless else self.sleeve.reconcile(),
                    durable_handoff=False if bookless else handoff_ready(self.book,self.history.rows()))
        if bookless:
            from meme_machine.runtime.isolated_native_bootstrap import bookless_report
            result.update(bookless_report(self,'pump'))
        return result

    def close(self):
        if getattr(self,'native_resources',None) is None:
            if getattr(self,'candidate_history',None) is not None:self.candidate_history.close()
            self.book.close();self.history.close();self.sleeve.close();self.plane.close()
        else:
            from meme_machine.runtime.isolated_native_bootstrap import close_bookless_runtime
            close_bookless_runtime(self,'pump')
