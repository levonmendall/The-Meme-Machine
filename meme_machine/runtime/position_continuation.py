"""Resume existing native strategies from their own verified journals."""
from contextlib import closing,nullcontext
from copy import deepcopy
from pathlib import Path
import os,json,sqlite3,time
def _atomic(path,value):
    import uuid
    path=Path(path);tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x') as stream:
            stream.write(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:tmp.unlink(missing_ok=True)


def _find(root,pattern):
    rows=sorted(Path(root).rglob(pattern))
    if not rows:raise FileNotFoundError(pattern)
    if len(rows)>1:
        exact=[p for p in rows if not p.name.endswith(('-wal','-shm'))]
        if len(exact)==1:return exact[0]
        raise RuntimeError('ambiguous_continuation_state:'+pattern)
    return rows[0]


def _meteora_open_identity(events):
    last={};entry={}
    for event in events:
        identity=event.get('identity')
        if not identity:continue
        last[identity]=event['action']
        if event['action']=='entry':entry[identity]=event
    open_ids=[identity for identity,action in last.items()
              if action not in ('cancel','settle','writeoff')]
    if len(open_ids)!=1:
        raise RuntimeError('meteora_continuation_requires_exactly_one_open_position')
    identity=open_ids[0]
    if identity not in entry:raise RuntimeError('meteora_continuation_entry_missing')
    return identity,entry[identity]


def _meteora_exit_progress(module,raw_reasons,*,elapsed,observed,streaks,policy):
    """Apply the native frozen exit filter, carrying counters across process cuts."""
    elapsed+=observed
    streaks={reason:(count+1 if reason in raw_reasons else 0)
             for reason,count in streaks.items()}
    eligible=module._eligible_exit_reasons(raw_reasons,elapsed_seconds=elapsed,
        collapse_streaks=streaks,policy=policy)
    return elapsed,streaks,eligible


def restore_meteora_strategy(book,module):
    """Rebuild the open native strategy from a verified ledger; no provider/report I/O.

    Recovery never appends an entry, mark, settlement, or synthetic exit. The same
    function is used by continuation and deterministic interruption tests.
    """
    from contextlib import closing
    from meme_machine.lanes.meteora.dlmm_tape import VerifiedTape
    from contextlib import nullcontext as restoring_recorded_state
    with closing(book.connect()) as db:
        db.execute('BEGIN')
        book._replay(db)
        events=list(book.events(db))
    identity,entry_event=_meteora_open_identity(events)
    entry_data=entry_event['data']
    policy=entry_data['policy'];features=entry_data['features'];entry=entry_data['entry_state']
    position=module._build_position(entry,features,policy)
    current=deepcopy(entry);elapsed=max(0,int(current['time'])-int(entry['time']))
    entry_flow={key:features[key] for key in
        ('volume_rate_sol_lamports_per_second','fee_density')}
    collapse_streaks={'volume_collapse':0,'fee_density_collapse':0}
    segment_seconds=int(policy['exit']['observation_segment_seconds'])
    last_lineage=None;restored_exit=None;tapes=[]
    for event in events:
        if event.get('identity')!=identity or event.get('action')!='mark':continue
        if restored_exit is not None:
            raise RuntimeError('strategy_conformance_failure:mark_after_eligible_exit')
        t=event['data']['tape']
        tape=VerifiedTape(t['start_hash'],t['end_hash'],tuple(t['events']),
                          t['terminal'],t['lineage'],tuple(t.get('terminal_adjustments',())))
        position=module._advance_position(position,tape);tapes.append(tape)
        saved=event['data'].get('strategy_progress')
        effective_start=(saved or {}).get('effective_start') or current
        if saved and saved.get('effective_start_hash') not in (None,module.digest(effective_start)):
            raise RuntimeError('meteora_restored_effective_start_hash')
        with restoring_recorded_state():
            raw_reasons,_,_,_=module._segment_exit(position,
                effective_start,tape,tape.terminal,entry_flow,policy)
        observed=(int(saved['observed_seconds']) if saved else
            max(segment_seconds,max(0,int(tape.terminal['time'])-int(current['time']))))
        with restoring_recorded_state():
            elapsed,collapse_streaks,eligible=_meteora_exit_progress(module,raw_reasons,
                elapsed=elapsed,observed=observed,streaks=collapse_streaks,policy=policy)
        if saved and (saved['elapsed_seconds']!=elapsed or
                saved['collapse_streaks']!=collapse_streaks or
                saved['eligible_exit_reasons']!=eligible):
            raise RuntimeError('strategy_conformance_failure:meteora_restored_exit_state')
        restored_exit=eligible[0] if eligible else None
        current=deepcopy(tape.terminal);last_lineage=tape.lineage

    if module.digest(module._build_position(entry,features,policy))!=module.digest(entry_data['position']):
        raise RuntimeError('meteora_restored_entry_position_mismatch')
    return dict(identity=identity,entry=entry,policy=policy,features=features,
        position=position,current=current,elapsed=elapsed,entry_flow=entry_flow,
        collapse_streaks=collapse_streaks,last_lineage=last_lineage,restored_exit=restored_exit,tapes=tapes)


def _json_env(name):
    raw=str(os.environ.get(name,'') or '').strip()
    if not raw:return {}
    value=json.loads(raw)
    if not isinstance(value,dict):raise RuntimeError('invalid_'+name.lower())
    return {str(k).lower():v for k,v in value.items()}


def _resume_ramses_native(state_dir,*,slice_seconds,runtime_identity):
    """Existing native lifecycle core; callers must establish continuation authority."""
    from meme_machine.lanes.ramses import BoundaryError
    from meme_machine.lanes.ramses import ramses_all_pool_lifecycle as module
    from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger

    state_path=_find(state_dir,'robinhood-ramses-continuation.json')
    state=json.loads(state_path.read_text())
    if state.get('schema')!='ramses-position-continuation-v1':
        raise RuntimeError('ramses_continuation_schema')
    ledger_name=Path(state['ledger_path']).name
    ledger_path=_find(state_dir,ledger_name)
    identity=state.get('lifecycle_id')
    if not identity:raise RuntimeError('ramses_continuation_identity_missing')
    book=RamsesStrategyLedger(
        str(ledger_path),paper_capital=int(state['paper_capital']),
        quote_asset=state['quote_asset'])
    try:
        from meme_machine.runtime.continuity_state import recover as recover_checkpoint,checkpoint as durable_checkpoint,fields
        recover_checkpoint(book,identity,state,state_path)
        ledger_position=book.position(identity)
        if ledger_position.get('status')=='settled':
            accounting=book.reconcile()
            return dict(
                lane='ramses',status='settled',handoff_required=False,
                accounting=accounting,terminal_replay_verified=True,
                runtime_identity=runtime_identity)
        ledger_proposal=ledger_position.get('proposal_hash')
        current=deepcopy(state.get('decision'))
        pending=deepcopy(state.get('pending_rebalance') or {})
        candidates=[
            ('current',current),
            ('pending_old',pending.get('old_decision')),
            ('pending_new',pending.get('new_decision')),
        ]
        matched=next(
            ((name,value) for name,value in candidates
             if isinstance(value,dict)
             and (value.get('freeze') or {}).get('proposal_hash')==ledger_proposal),
            None,
        )
        if matched is None:
            raise RuntimeError('ramses_continuation_ledger_geometry_mismatch')
        geometry_source,decision=matched
        if ledger_position.get('status')=='reserved':
            # Complete the already-authorized, durable reserve/open operation.
            # The identity, geometry and original strategy time are unchanged.
            book.open(identity,at=ledger_position['at'])
        if geometry_source=='pending_new':
            state['decision']=deepcopy(decision)
            state['position_phase']='deployed'
            state.pop('pending_rebalance',None)
            _atomic(state_path,state)
        elif geometry_source=='pending_old':
            state['decision']=deepcopy(decision)
            _atomic(state_path,state)
        endpoint=os.environ.get('MM_ROBINHOOD_READ_RPC_URL','')
        costs_by_pool=_json_env('MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON')
        signals_by_pool=_json_env('MM_ROBINHOOD_RAMSES_SIGNALS_BY_POOL_JSON')
        cost_state={}
        rpc=module.BoundedMultiRpc(endpoint,max_sessions=16,batch_size=20,
            batch_pause=0.5,rate_retries=1)
        rpc.verify_chain()
        pool=str(state['pool']).lower()
        costs=module._segment_costs(state.get('costs'))
        segments=list(state.get('segments') or [])
        current_capital=int(state.get('current_capital')
                            or decision['freeze']['proposals'][0]['capital_employed'])
        segment_start=int(state['segment_start'])
        entry_at=int(state['entry_at']);rebalances=int(state.get('rebalances') or 0)
        latest_screen=module.scan(endpoint,gas_costs_by_pool=costs_by_pool,
            signals_by_pool=signals_by_pool,cost_state=cost_state)
        last_scan_wall=time.monotonic();last_fee_reserve=None;last_fee_refresh_wall=0.0
        slice_deadline=time.monotonic()+int(slice_seconds)
        terminal_at=max(entry_at,int(book.position(identity).get('at') or entry_at))

        def monitor_checkpoint(detail,at):
            next_state=fields(state);next_state['last_controller']=deepcopy(detail)
            return durable_checkpoint(book,identity,state=state,path=state_path,
                action='monitor',detail=detail,at=at,next_state=next_state)

        def provider_hold(*,stage,boundary,at):
            # Provider holds also advance the native journal version. Commit their
            # matching sidecar through the same write-ahead bridge as decisions.
            from types import SimpleNamespace
            proxy=SimpleNamespace(checkpoint=lambda _id,**kw:monitor_checkpoint(kw['detail'],kw['at']))
            return module._record_provider_hold(state,proxy,identity,stage=stage,boundary=boundary,at=at)

        def settle_flat(reason):
            if not segments:
                raise RuntimeError('ramses_flat_quote_without_closed_segment')
            aggregate=module.aggregate_segments(segments)
            aggregate=dict(aggregate,continuation_terminal_reason=reason)
            final=book.settle(identity,pnl=aggregate,at=terminal_at)
            state.update(active=False,result=dict(status=final['status'],pnl=aggregate),
                         handoff_required=False,position_phase='settled')
            state.pop('pending_rebalance',None)
            _atomic(state_path,state)
            accounting=book.reconcile()
            terminal_verified=(
                final.get('status')=='settled'
                and accounting.get('open_positions')==0
                and accounting.get('committed')==0
            )
            return dict(
                lane='ramses',status=final['status'],handoff_required=False,
                pnl=aggregate,accounting=accounting,
                terminal_replay_verified=terminal_verified,
                runtime_identity=runtime_identity)

        def prepare_replacement(reference_decision):
            nonlocal costs,current_capital,segment_start,rebalances,latest_screen,decision
            started=time.monotonic()
            fresh=module.scan(endpoint,gas_costs_by_pool=costs_by_pool,
                signals_by_pool=signals_by_pool,cost_state=cost_state)
            prior=reference_decision['freeze']['proposals'][0]
            candidate=module._requalify_current_pool(
                fresh,pool,current_capital,costs_by_pool,signals_by_pool,
                rebalance_mode=((state.get('last_controller') or {}).get('action') or {}).get('mode') or 'recenter',
                reference_bins=prior['bins'])
            elapsed=time.monotonic()-started
            if elapsed>210:
                state.setdefault('recenter_deadline_misses',[]).append(dict(
                    at=time.time(),elapsed_seconds=elapsed,
                    action='discard_stale_geometry_and_redecide_from_fresh_scan'))
                _atomic(state_path,state)
                started=time.monotonic()
                fresh=module.scan(endpoint,gas_costs_by_pool=costs_by_pool,
                    signals_by_pool=signals_by_pool,cost_state=cost_state)
                candidate=module._requalify_current_pool(
                    fresh,pool,current_capital,costs_by_pool,signals_by_pool,
                    rebalance_mode=((state.get('last_controller') or {}).get('action') or {}).get('mode') or 'recenter',
                    reference_bins=prior['bins'])
            if time.monotonic()-started>210:
                state['recenter_hard_deadline_exhausted']=True
                _atomic(state_path,state)
                return False
            if not candidate or candidate.get('qualified') is not True:
                return False
            module.verify_proposal_hash(candidate['freeze'])
            fresh_row=next((r for r in fresh.get('rows',[])
                            if str(r.get('pool','')).lower()==pool),None)
            if fresh_row is None:
                raise BoundaryError('connected_lifecycle_rebalance_row_missing')
            next_costs=module._segment_costs(
                fresh_row.get('gas_costs') if fresh_row.get('gas_costs') is not None
                else costs_by_pool.get(pool))
            next_block=int(fresh['finalized_block'])
            next_at=int(fresh['finalized_timestamp'])
            next_index=rebalances+1
            pending=dict(
                old_decision=deepcopy(reference_decision),
                new_decision=deepcopy(candidate),
                new_proposal_hash=candidate['freeze']['proposal_hash'],
                prepared_at=time.time(),
            )
            state['pending_rebalance']=pending
            _atomic(state_path,state)
            next_state=fields(state)
            next_state.update(decision=deepcopy(candidate),costs=deepcopy(next_costs),
                segment_start=next_block,current_capital=current_capital,
                rebalances=next_index,position_phase='deployed')
            next_state.pop('pending_rebalance',None)
            durable_checkpoint(book,identity,state=state,path=state_path,action='rebalance',detail=dict(
                index=next_index,block=next_block,at=next_at,
                capital=current_capital,proposal_hash=candidate['freeze']['proposal_hash']),
                at=next_at,next_state=next_state)
            decision=candidate;costs=next_costs;latest_screen=fresh
            segment_start=next_block;rebalances=next_index
            state.update(decision=deepcopy(candidate),costs=deepcopy(next_costs),
                segment_start=segment_start,current_capital=current_capital,
                rebalances=rebalances,position_phase='deployed')
            state.pop('pending_rebalance',None)
            _atomic(state_path,state)
            return True

        if state.get('position_phase')=='flat_quote':
            last_action=(state.get('last_controller') or {}).get('action') or {}
            burn_at=state.get('recenter_started_at')
            if (last_action.get('action')=='rebalance' and isinstance(burn_at,(int,float))
                    and time.time()-burn_at>210):
                state.setdefault('recenter_deadline_misses',[]).append(dict(
                    at=time.time(),elapsed_seconds=time.time()-burn_at,
                    action='restart_after_burn_discards_stale_geometry'))
                _atomic(state_path,state)
            if (max(0,terminal_at-entry_at)>=int(module.POLICY['controller'].get(
                    'max_holding_seconds',604800))
                    or last_action.get('action')!='rebalance'
                    or current_capital<=0):
                return settle_flat(last_action.get('reason') or 'flat_quote_exit')
            if not prepare_replacement(decision):
                return settle_flat('rebalance_requalification_failed_or_stale')

        while time.monotonic()<slice_deadline-5:
            _stop_sleep(min(module.MONITOR_POLL_SECONDS,max(0,slice_deadline-time.monotonic()-5)))
            if time.monotonic()>=slice_deadline-5:break
            try:
                rpc=module._new_position_reader(endpoint,rpc)
                frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='lifecycle_monitor')
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                provider_hold(stage='frontier',
                    boundary=exc,at=terminal_at);continue
            block=int(frontier['number'],16);at=int(frontier['timestamp'],16)
            terminal_at=max(terminal_at,at)
            if block<=segment_start:continue
            if time.monotonic()-last_scan_wall>=module.RESCAN_SECONDS:
                try:
                    latest_screen=module.scan(endpoint,gas_costs_by_pool=costs_by_pool,
                        signals_by_pool=signals_by_pool,cost_state=cost_state)
                except BoundaryError as exc:
                    if not module._is_transient_provider_boundary(exc):raise
                    provider_hold(stage='rescan',
                        boundary=exc,at=terminal_at)
                finally:last_scan_wall=time.monotonic()
            row=next((r for r in latest_screen.get('rows',[])
                      if str(r.get('pool','')).lower()==pool),None)
            opportunity_qualified=bool(row and (row.get('decision') or {}).get('qualified'))
            try:
                state_now=module._position_state(rpc,pool,decision,block)
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                provider_hold(stage='position_state',
                    boundary=exc,at=terminal_at);continue
            if (last_fee_reserve is None or
                    time.monotonic()-last_fee_refresh_wall>=module.FEE_RESERVE_REFRESH_SECONDS):
                try:
                    _,fee_replay=module._build_segment_replay(
                        rpc,pool,decision,segment_start,block)
                    fees=module.paper_fee_capture(module.paper_position(decision['freeze'],0),fee_replay)
                    last_fee_reserve=max(0,int(fees['quote_value']))
                    last_fee_refresh_wall=time.monotonic()
                except BoundaryError as exc:
                    if not module._is_transient_provider_boundary(exc):raise
                    provider_hold(stage='fee_reserve',
                        boundary=exc,at=terminal_at)
            total_cost=sum(costs.values());rebalance_cost=int(costs.get('rebalance',total_cost))
            unwind_cost=int(costs.get('unwind',costs.get('unwind_gas',0)))
            elapsed=max(0,at-entry_at)
            action=module.controller_action(
                decision,current_active_bin=state_now['active'],elapsed_seconds=elapsed,
                rebalances_used=rebalances,opportunity_still_qualified=opportunity_qualified,
                expected_remaining_fee_quote=last_fee_reserve,
                estimated_inventory_loss_quote=state_now['inventory_loss_quote'],
                rebalance_cost_quote=rebalance_cost,unwind_cost_quote=unwind_cost)
            controller_row=dict(at=at,block=block,active_bin=state_now['active'],
                inventory_value=state_now['inventory_value'],
                inventory_loss_quote=state_now['inventory_loss_quote'],
                opportunity_qualified=opportunity_qualified,action=action)
            next_state=fields(state);next_state['last_controller']=controller_row
            durable_checkpoint(book,identity,state=state,path=state_path,action='monitor',
                detail=controller_row,at=at,next_state=next_state)
            if action['action']=='hold':continue
            try:
                capture,replay_result=module._build_segment_replay(
                    rpc,pool,decision,segment_start,block)
                unwind=module._unwind(rpc,pool,decision,replay_result,block)
                if not module._unwind_has_full_liquidity(unwind):
                    hold=dict(action='hold',reason='unwind_liquidity_unavailable',
                        stage='unwind',block=block,amount_in=unwind['amount_in'],
                        amount_in_left=unwind['amount_in_left'])
                    monitor_checkpoint(hold,at);continue
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                provider_hold(stage='exit_replay_or_unwind',
                    boundary=exc,at=terminal_at);continue
            pnl=module.decompose_pnl(decision,replay_result,unwind=unwind,costs=costs)
            segment=dict(
                index=len(segments),start_block=segment_start,end_block=block,
                start_at=int(capture['headers'][str(segment_start)]['timestamp'],16),
                end_at=int(capture['headers'][str(block)]['timestamp'],16),
                exit_reason=action['reason'],
                initial_cost_basis=int(decision['freeze']['proposals'][0]['capital_employed']),
                proposal_hash=decision['freeze']['proposal_hash'],
                terminal_equality=replay_result['terminal_equality'],
                events=replay_result['events'],transactions=replay_result['transactions'],
                pnl=pnl)
            segments.append(segment)
            next_state=fields(state);next_state['segments']=deepcopy(segments)
            next_state['position_phase']='flat_quote'
            if type(pnl.get('net_result_quote')) is int:
                next_state['current_capital']=int(segment['initial_cost_basis'])+int(pnl['net_result_quote'])
            if action.get('action')=='rebalance':next_state['recenter_started_at']=time.time()
            durable_checkpoint(book,identity,state=state,path=state_path,action='segment_close',detail=dict(
                segment=segment['index'],end_block=block,exit_reason=action['reason'],
                net_result_quote=pnl.get('net_result_quote')),at=at,next_state=next_state)
            if pnl.get('unresolved_inventory') or type(pnl.get('net_result_quote')) is not int:
                break
            current_capital=int(segment['initial_cost_basis'])+int(pnl['net_result_quote'])
            if action['action']!='rebalance' or current_capital<=0:break

            prior_decision=deepcopy(decision)
            if not prepare_replacement(prior_decision):
                return settle_flat('rebalance_requalification_failed_or_stale')
            last_fee_reserve=None
            last_fee_refresh_wall=0.0

        position=book.position(identity)
        if position.get('status')=='open' and state.get('position_phase')=='flat_quote':
            action=(state.get('last_controller') or {}).get('action') or {}
            return settle_flat(action.get('reason') or 'flat_quote_without_committed_replacement')
        state.update(active=True,handoff_required=True,ledger_path=str(ledger_path),
                     paper_capital=int(state['paper_capital']),quote_asset=state['quote_asset'])
        _atomic(state_path,state)
        return dict(lane='ramses',status='handoff_required',handoff_required=True,
                    accounting=book.reconcile(),state=state,runtime_identity=runtime_identity)
    finally:
        book.close()


class PumpCurrentContinuation:
    """The native Pump monitor with discovery and pending-entry execution absent."""
    def __init__(self,root,confirmations):
        from meme_machine.lanes.pump import runner as strategy
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence,LocalPumpTape
        from meme_machine.runtime.terminal_reconciliation import connect
        from contextlib import nullcontext as restoring_recorded_state
        from contextlib import closing
        self.strategy=strategy;self.confirmations=confirmations
        self.book=self.plane=self.sessions=None
        path=Path(root)/'pump-acceleration-natural-prospective.accounting.sqlite3'
        try:
            with closing(connect(path)) as db:
                genesis=json.loads(db.execute('SELECT body FROM genesis WHERE id=1').fetchone()[0])
            if genesis['policy_hash']!=strategy.policy_hash():raise RuntimeError('pump_continuation_policy')
            self.book=PaperBook(path,**genesis)
            self.plane=RuntimeEvidence(owner='pump');self.tape=LocalPumpTape(self.plane)
            with restoring_recorded_state():
                self.created,self.postgrad,pending,self.active,qualifiers=strategy.restore_runtime(
                    self.book,self.plane,confirmations)
            if pending:raise RuntimeError('pump_continuation_pending_entry_forbidden')
            self.sessions=strategy.Sessions();self.sessions.plane=self.plane
            self.report=dict(settled=[],qualifiers=qualifiers,entry_authority=False)
        except BaseException:
            self.close();raise

    def step(self):
        self.strategy._monitor_positions(self.report,self.active,self.sessions,self.created,
            self.postgrad,self.tape,self.confirmations,int(time.time()))
        return dict(open_positions=len(self.active),accounting=self.book.reconcile(),
            settled=list(self.report['settled']),new_entries=0,
            monitor_failures={row['lifecycle'].lifecycle_id:row.get('monitor_failures',[])
                for row in self.active.values()})

    def close(self):
        try:
            if self.sessions is not None:self.sessions.finish()
        finally:
            try:
                for row in getattr(self,'active',{}).values():
                    life=row['lifecycle']
                    if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                if self.plane is not None:self.plane.close()
            finally:
                if self.book is not None:self.book.close()




def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
