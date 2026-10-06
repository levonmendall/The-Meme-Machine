"""Active Pump Survivor inside the Pump sleeve, on the Solana Evidence Plane.

One incremental monitoring task, at most one candidate hydration per turn. It
never scans RPC history and never qualifies from public websocket discoveries.
"""
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
from meme_machine.runtime.survivor_paper_book import PaperBook
from .engine import GAS,MAYHEM_AGENT_WALLET
from .postgrad import PostGraduationAdapter,graduation_handoff,buy_quote,sell_quote
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
    def __init__(self,root,capital,run_id,confirmations):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.capital=capital;self.run_id=run_id;self.confirmations=confirmations
        self.sleeve=open_sleeve('pump',capital)
        if self.sleeve is None:raise ValueError('survivor_shared_sleeve_required')
        self.history=History(str(self.root/'history.sqlite'),policy=POLICY_HASH)
        from meme_machine.runtime.survivor_history import compact_restored_history
        from .pumpswap_survivor import reduce_reset_history
        compact_restored_history(self.history,lane='pump',reducer=reduce_reset_history)
        self.book=PaperBook(str(self.root/'paper.sqlite'),run_id=run_id,lane=STRATEGY_ID,
                            policy_hash=POLICY_HASH,initial=capital)
        from meme_machine.runtime.survivor_terminal_archive import compact
        compact(self.book,self.sleeve,self.history)
        self.plane=RuntimeEvidence(owner='pump:survivor')
        self.rpc=None;self.current=None;self.last_error=None

    def now(self):return int(time.time())

    def _provider(self,priority=30):
        if self.rpc is None or self.rpc.calls>160:
            pacer=None if self.rpc is None else self.rpc.read_pacer
            self.rpc=new_rpc(limit=240,pacer=pacer)
            self.rpc.evidence_priority=priority
            self.adapter=PostGraduationAdapter(self.rpc)
        self.rpc.evidence_priority=priority
        self.rpc.evidence_kind='survivor_monitor' if priority==30 else 'survivor_commit_or_exit'

    def discover(self):
        top=self.plane.frontier(PUMP_SCOPE)
        cursor=self.history.get_meta('discovery_slot')
        if cursor is None:
            self.history.set_meta('discovery_slot',max(0,top-1));return
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
        self.history.set_meta('discovery_slot',end)

    def _increment(self,row,at,slot):
        row=self.history.get(row['id'])
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
        events=[];points={}
        for record in records:
            e=record['payload']['event'];t=e['market_time']
            if not row['through']<=t<=at:continue
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

    def fresh_state(self,candidate,priority=1):
        self._provider(priority);self.current=self.history.get(candidate)
        raw=self.adapter.graduation_snapshot(candidate,self.now(),priority=True)
        handoff=graduation_handoff(raw,self.now())
        state=self.adapter.pumpswap_snapshot(handoff,self.now(),priority=True,additional_accounts=(SOL_USD_ACCOUNT,))
        if state['pool']!=self.current['graduation']['pool']:raise ValueError('survivor_pool_drift')
        return state

    def fresh_quotes(self,state,budget):return Quotes(state,self.now())

    def reconstruct(self,state,quote_context):
        row=self.current;at=state['market_time'];self._increment(row,at,state['slot'])
        price=Fraction(state['state']['quote_reserve'],state['state']['base_reserve'])
        self.history.append(row['id'],through=at,events=[],points=[(at,str(price))],complete=True)
        points,events=self.history.facts(row['id'],at)
        grad=row['graduation'];creator=self.confirmations.cluster(state['creator'])
        mayhem=state['state']['mayhem_mode']
        agents={self.confirmations.cluster(MAYHEM_AGENT_WALLET)} if mayhem else set()
        organic=[e for e in events if e['group'] not in agents and e['group']!=creator]
        recent=[e for e in organic if at-1800<=e['at']<=at]
        tokens=sum(e['tokens'] for e in recent)
        vwap=None if tokens<=0 else str(Fraction(sum(e['quote'] for e in recent),tokens))
        from meme_machine.lanes.pump.runner import _postgrad_concentration
        concentration=_postgrad_concentration(self.rpc,state)
        usd=sol_usd_lower_micros(state['additional_accounts'][SOL_USD_ACCOUNT],now=self.now(),slot=state['slot'])
        base_end=max((p['at'] for p in points if p['at']<=at-60),default=None)
        facts=dict(now=at,graduation_at=grad['at'],lineage_proven=True,origin='pump.fun',venue='pumpswap',
            canonical_migration_pool=True,quote_asset='SOL',authoritative=True,
            continuity_complete=self.history.get(row['id'])['complete'],demand_complete=True,
            creator_distribution_safe=not any(not e['buy'] and e['group']==creator for e in events),
            hard_concentration_pass=concentration<=POLICY['maximum_holder_concentration_bps'],
            exit_liquidity_available=state['state']['raw_quote_reserve']>0,
            migration_price=str(Fraction(grad['quote_amount'],grad['mint_amount'])),
            liquidity_usd_micros=2*state['state']['raw_quote_reserve']*usd//10**9,
            # The immutable coin flag proves whether it is a Mayhem coin. It
            # does not prove the agent's completion time. Never infer completion
            # from absent trades or elapsed age; without that evidence entry is
            # blocked, even though the disclosed agent flow can be excluded.
            mayhem=dict(status='unknown' if mayhem else 'never',agent_identity_proven=mayhem,
                        agent_groups=sorted(agents)),price_points=points,base_end=base_end,
            reset_history_prefix=self.history.prefix(row['id']),
            recovery_vwap=vwap,demand_events=organic,holder_concentration_bps=concentration)
        self.facts=facts;return facts

    def turnover_cap(self,facts,decision):return decision['features']['turnover_cap']
    def generation_fence(self,candidate,generation):return nullcontext() # sleeve is the Pump generation authority
    def validate_current(self,state,execution,now):
        self.plane.require_usable(SWAP_SCOPE)
        if not 0<=now-state['market_time']<=10 or not 0<=now-execution['acquired']<=5:
            raise ValueError('survivor_stale_commit')
        if execution['slot']!=state['slot']:raise ValueError('survivor_quote_state')

    def exit_quote(self,qty):
        try:
            self._provider(0)
            state=self.fresh_state(self.current['id'],priority=0)
            q=sell_quote(state,qty)
            return dict(net_proceeds=max(0,q.output_amount-GAS),quantity=qty,
                acquired=self.now(),market_time=state['market_time'],slot=state['slot'])
        except (ValueError,Unavailable):return None

    def validate_exit(self,quote,qty,now):
        if quote['quantity']!=qty or not 0<=now-quote['market_time']<=10 or not 0<=now-quote['acquired']<=5:
            raise ValueError('survivor_exit_quote_stale')

    def _position(self,row,*,admit=True):
        self.current=row
        try:position=self.book._load(row['position'])
        except ValueError:
            if not admit:raise ValueError('survivor_continuation_unfilled_controller')
            return self._enter(row,row['decision'],row['generation'],row['regime'],row['position'])
        if position['status'] in ('settled','cancelled'):
            self.sleeve.release(row['position'],pnl=position['realized'],at=max(self.now(),position['last_at']),
                terminal_hash=digest(position),native_verified=self.book.replay()['verified'],cancelled=position['status']=='cancelled')
            row.update(position=None,state='settled');self.history.save(row);return
        if position['status']=='reserved':
            if not admit:raise ValueError('survivor_continuation_reservation')
            # Reconstruct the exact qualified decision, then reacquire every fresh
            # input; a persisted successful validation has no restart authority.
            return self._enter(row,row['decision'],row['generation'],row['regime'],row['position'])
        state=None;facts=None
        try:
            state=self.fresh_state(row['id'],priority=0)
            facts=self.reconstruct(state,Quotes(state,self.now()))
        except (ValueError,Unavailable):pass
        q=self.exit_quote(position['tokens'])
        net=None if q is None else q['net_proceeds']
        flow={} if facts is None else buyer_persistence(facts['demand_events'],now=facts['now'],window_seconds=1800)
        observation=dict(id=str(state['slot']) if state else 'unavailable:'+str(self.now()),at=self.now(),
            after_cost_return_bps=None if net is None else (net-position['basis'])*10000//position['basis'],
            net_exit_proceeds=position['mark'] if net is None else net,
            exit_liquidity_valid=True if q is not None else None,creator_distribution=facts is not None and not facts['creator_distribution_safe'],
            soft_deterioration=None if not flow else flow['buy_flow']<=flow['sell_flow'] and flow['new_buyers']==0)
        action=monitor(book=self.book,sleeve=self.sleeve,identity=row['position'],observation=observation,
                       policy=POLICY['exits'],adapter=self)
        if action['action']=='hold':
            scale(book=self.book,sleeve=self.sleeve,identity=row['position'],candidate=row['id'],
                generation=row['generation'],adapter=self,qualify=evaluate_entry,ordinary_limit=600,
                stress_limit=600,minimum=GAS*2+1)
        if action['action']=='partial_exit':
            row=self.history.get(row['id']);row['state']='runner';self.history.save(row)

    def _enter(self,row,decision,generation,regime,identity):
        sizing=self.sleeve.sizing_basis(POLICY["target_sleeve_bps"])
        return commit(book=self.book,sleeve=self.sleeve,identity=identity,candidate=row['id'],generation=generation,
            strategy=STRATEGY_ID,policy_hash=POLICY_HASH,decision=decision,regime=regime,at=self.now(),
            target=sizing["target"],minimum=GAS*2+1,retention_bps=5000,
            ordinary_limit=600,stress_limit=600,adapter=self,qualify=evaluate_entry)

    def step(self,*,admit):
        discovery_deferred=False
        try:
            from meme_machine.runtime.storage import compact_survivor
            compact_survivor(self,'pump')
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
                                           int(r['graduation']['at']),r['id']))
                row['last_checked']=self.now();self.history.save(row)
                age=self.now()-row['graduation']['at']
                if age>POLICY['maximum_age_seconds']:
                    self.history.retire(row,expired_before=self.now()-POLICY['maximum_age_seconds'])
                    self.plane.command(op='release',owner='pump:survivor:'+row['id'],scope=SWAP_SCOPE,resolved=False)
                else:
                    # Incremental local monitoring starts at graduation, without
                    # RPC hydration or entry authority before the frozen age floor.
                    top=self.plane.frontier(SWAP_SCOPE);at=self.plane.block_time(top)
                    self._increment(row,at,top)
                    if age<POLICY['minimum_age_seconds']:row=self.history.get(row['id']);row['state']='aging';self.history.save(row)
                    else:
                        state=self.fresh_state(row['id'],priority=30)
                        decision=evaluate_entry(self.reconstruct(state,Quotes(state,self.now())))
                        row=self.history.get(row['id'])
                        f=decision['features'];regime=dict(at=state['market_time'],
                            high_reset_cycle=[f.get('peak_at'),f.get('reset_at')],base_id=[f.get('base_low'),f.get('base_high')],
                            buyer_population=f.get('buyer_groups'),independent_demand=f.get('independent_buyers'),
                            flow_regime='buy' if f.get('buy_flow',0)>f.get('sell_flow',0) else 'sell')
                        blocked=row.get('extension_blocked_regime')
                        if blocked:
                            from meme_machine.runtime.survivor_risk import new_regime
                            if not (new_regime(blocked,regime) and blocked['base_id']!=regime['base_id']
                                    and blocked['high_reset_cycle']!=regime['high_reset_cycle']):
                                decision['candidate']=False;decision['all_rejections'].append('extension_requires_new_reset_base')
                        if any(reason in decision['all_rejections'] for reason in ('price_extension','base_range_extension')):
                            row['extension_blocked_regime']=regime;self.history.save(row)
                        observed=self.sleeve.observe(row['id'],strategy=STRATEGY_ID,at=state['market_time'],
                            state='qualified' if decision['candidate'] else decision['stage'],evidence=decision,regime=regime)
                        self.sleeve.opportunity(row['id'],identity=row['id'],regime='survivor',
                            status=observed['state'],at=state.get('market_time',state.get('at')),decision=decision)
                        row=self.history.get(row['id']);row.update(state=observed['state'],decision=decision,
                            generation=observed['generation'],regime=regime)
                        if decision['candidate']:
                            sizing=self.sleeve.sizing_basis(POLICY["target_sleeve_bps"])
                            if int(sizing.get('allocatable_target',0)) < GAS*2+1:
                                # Qualification remains durable even when funding is
                                # unavailable. Do not mint a fake reserved position.
                                row['position']=None
                                row['state']='qualified_but_capital_unavailable'
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
                                    if str(exc)!='survivor_minimum_capital':
                                        raise
                                    row=self.history.get(row['id'])
                                    row['position']=None
                                    row['state']='qualified_but_capital_unavailable'
                                    self.sleeve.opportunity(
                                        row['id'],identity=row['id'],regime='survivor',
                                        status=row['state'],at=state.get('market_time',state.get('at')),
                                        decision=dict(decision,funding_reason='survivor_minimum_capital'))
                                else:
                                    row=self.history.get(row['id']);row['state']='filled'
                        self.history.save(row)
            self.last_error=None
        except (ValueError,Unavailable) as exc:
            self.last_error=str(exc)
        return dict(strategy=STRATEGY_ID,policy_hash=POLICY_HASH,active=True,paper_only=True,
                    candidate_count=len(self.history.rows()),last_boundary=self.last_error,
                    discovery_capacity_deferred=discovery_deferred,
                    candidate_capacity_pressure=(
                        self.history.get_meta('candidate_capacity_pressure') or 0),
                    accounting=self.book.reconcile(),accounting_replay=self.book.replay(),
                    policies=self.sleeve.identity['policies'],sleeve=self.sleeve.reconcile(),
                    durable_handoff=handoff_ready(self.book,self.history.rows()))

    def close(self):
        self.book.close();self.history.close();self.sleeve.close();self.plane.close()
