"""Resume durable Meteora/Ramses paper positions in bounded restart-safe slices.

This module is intentionally separate from market discovery.  It consumes only
append-only paper state created by the original lane and re-authenticates fresh
market evidence before advancing the same position.  It never creates a new
strategy decision, changes thresholds, signs, or submits transactions.
"""
from __future__ import annotations

import argparse
from contextlib import chdir
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


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


def _activate_lane_root():
    root=str(os.environ.get('MM_CONTINUATION_LANE_ROOT','') or '').strip()
    if not root:
        return None
    path=str(Path(root).resolve())
    if not Path(path).is_dir():
        raise RuntimeError('continuation_lane_root_missing')
    if path not in sys.path:
        sys.path.insert(0,path)
    return path


def _runtime_identity(state_dir,lane):
    """Bind continuation to the exact certified implementation and lane authority."""
    from certification.run import implementation_hash
    current=json.loads((Path(__file__).parent/'sources.json').read_text())
    expected=(current.get('lanes') or {}).get(lane)
    if not isinstance(expected,dict):
        raise RuntimeError('continuation_current_lane_missing')

    manifests=[]
    for path in Path(state_dir).rglob('manifest.json'):
        try:value=json.loads(path.read_text())
        except (OSError,ValueError):continue
        if isinstance(value,dict) and isinstance(value.get('lanes'),dict) and value.get('integration_sha'):
            manifests.append((path,value))
    if len(manifests)!=1:
        raise RuntimeError('continuation_runtime_manifest_ambiguous')
    manifest_path,manifest=manifests[0]
    observed=(manifest.get('lanes') or {}).get(lane) or {}
    for key in ('source_sha','policy_hash','strategy_version'):
        if observed.get(key)!=expected.get(key):
            raise RuntimeError('continuation_lane_identity_mismatch:'+key)

    bridge_path=Path(state_dir)/'engineering-recovery-authorization.json'
    bridge=json.loads(bridge_path.read_text()) if bridge_path.exists() else None
    if bridge:
        authority=json.loads((Path(__file__).parent/'recovery_predecessor.json').read_text())
        from certification.run import git
        certificate=bridge.get('full_exact_sha_certificate') or {}
        if (any(bridge.get(k)!=authority.get(k) for k in ('run_id','integration_sha','implementation_hash','artifact_id','artifact_digest'))
                or bridge.get('recovery_sha')!=git('rev-parse','HEAD')
                or certificate.get('integration_sha')!=bridge.get('recovery_sha')
                or certificate.get('passed') is not True
                or certificate.get('implementation_hash')!=implementation_hash()):
            raise RuntimeError('continuation_recovery_authority_mismatch')
    results=[]
    for path in Path(state_dir).rglob('result.json'):
        try:value=json.loads(path.read_text())
        except (OSError,ValueError):continue
        if isinstance(value,dict) and value.get('phase') in ('hourly','smoke') and value.get('implementation_hash'):
            results.append((path,value))
    if len(results)!=1:
        raise RuntimeError('continuation_hourly_result_ambiguous')
    result_path,result=results[0]
    if result.get('integration_sha')!=manifest.get('integration_sha'):
        raise RuntimeError('continuation_integration_identity_mismatch')
    current_hash=implementation_hash()
    if bridge:
        if (result.get('integration_sha')!=bridge['integration_sha'] or
                result.get('implementation_hash')!=bridge['implementation_hash']):
            raise RuntimeError('continuation_recovery_predecessor_mismatch')
    elif result.get('implementation_hash')!=current_hash:
        raise RuntimeError('continuation_implementation_hash_mismatch')
    return dict(
        lane=lane,phase=result.get('phase'),source_sha=observed.get('source_sha'),
        policy_hash=observed.get('policy_hash'),
        strategy_version=observed.get('strategy_version'),
        integration_sha=manifest.get('integration_sha'),
        implementation_hash=current_hash,
        manifest_path=str(manifest_path),result_path=str(result_path),
        engineering_recovery=bool(bridge),economic_sample_eligible=not bool(bridge),
    )


def _meteora_events(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        return [json.loads(raw) for raw, in db.execute(
            'SELECT body FROM events ORDER BY seq')]


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
    from meme_machine.dlmm_tape import VerifiedTape
    from certification.decision_conformance import restoring_recorded_state
    with closing(book.connect()) as db:
        db.execute('BEGIN')
        book._replay(db)
        events=[json.loads(raw) for raw, in db.execute('SELECT body FROM events ORDER BY seq')]
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


def resume_meteora(state_dir,*,slice_seconds):
    runtime_identity=_runtime_identity(state_dir,'meteora')
    lane_root=_activate_lane_root()
    runtime_identity['lane_root']=lane_root
    from tests import solana_dlmm_independent_v1 as module
    from meme_machine.dlmm_independent_accounting import PaperBook
    from meme_machine.dlmm_tape import VerifiedTape
    from certification.decision_conformance import restoring_recorded_state

    db_path=_find(state_dir,'solana-dlmm-independent-v1-live.accounting.sqlite3')
    events=_meteora_events(db_path)
    genesis=events[0]['data']
    identity,entry_event=_meteora_open_identity(events)
    entry_data=entry_event['data']
    policy=entry_data['policy'];features=entry_data['features'];entry=entry_data['entry_state']
    book=PaperBook(db_path,run_id=genesis['run_id'],policy_hash=genesis['policy_hash'],
                   capital=int(genesis['capital']))

    recovered=restore_meteora_strategy(book,module)
    position=recovered['position'];current=recovered['current'];elapsed=recovered['elapsed']
    entry_flow=recovered['entry_flow'];collapse_streaks=recovered['collapse_streaks']
    last_lineage=recovered['last_lineage'];restored_exit=recovered['restored_exit']

    max_hold=int(policy['range']['max_holding_seconds'])
    segment_seconds=int(policy['exit']['observation_segment_seconds'])
    entry_flow=dict(
        volume_rate_sol_lamports_per_second=features['volume_rate_sol_lamports_per_second'],
        fee_density=features['fee_density'],
    )
    lower=list(range(features['lower'],entry['active']))
    upper=list(range(entry['active']+1,features['upper']+1))
    # Retain the exact strategy-derived range construction as a restart invariant.
    if not lower or not upper:raise RuntimeError('meteora_continuation_range_invalid')

    pacer=module.provider.AlchemyPacer();rpcs=[]
    module._prove_network_identity(pacer,rpcs)
    adapter=module._new_adapter(pacer,rpcs)
    broker_path=Path(state_dir)/'continuation-solana-evidence.sqlite3'
    os.environ['MM_SOLANA_EVIDENCE_BROKER_DB']=str(broker_path)
    broker=module.EvidenceBroker(str(broker_path))
    slice_deadline=time.monotonic()+int(slice_seconds)
    segments=[];exit_reason=restored_exit;handoff_reason='continuation_slice_complete'
    try:
        while elapsed<max_hold and exit_reason is None:
            available=int(slice_deadline-time.monotonic()-10)
            if available<=0:break
            duration=min(segment_seconds,max_hold-elapsed)
            # A block cut cannot create an extra short confirmation segment.
            if duration>available:break
            if duration<=0:break
            adapter=module._rotate(adapter,pacer,rpcs)
            phase,tape,terminal,effective_start,adapter,recoveries=(
                module._recover_position_observation(
                    adapter,entry['pool'],current,duration,pacer,rpcs,
                    slice_deadline,broker))
            if not phase.get('verified'):
                reason=str(phase.get('reason') or 'position_evidence_incomplete')
                if reason=='experiment_runtime_deadline':
                    handoff_reason=reason;break
                terminal_writeoff=(
                    reason in ('dlmm_multiple_liquidity_removals_in_interval',
                               'dlmm_add_liquidity_by_strategy2_mixed_with_swap_interval')
                    or reason.startswith('dlmm_rebalance_liquidity_requires_position_state:')
                )
                if terminal_writeoff:
                    book.append(identity,'writeoff',dict(reason=reason,recovery_attempts=recoveries))
                    accounting=book.reconcile()
                    replay=book.replay_economics(
                        module._build_position,module._advance_position,module._mark)
                    return dict(
                        lane='meteora',status='written_off',handoff_required=False,
                        reason=reason,accounting=accounting,
                        accounting_replay=replay,
                        terminal_replay_verified=replay.get('verified') is True,
                        runtime_identity=runtime_identity)
                book.fail(identity,reason)
                handoff_reason=reason;break
            position=module._advance_position(position,tape)
            raw_reasons,recent,mark,uplift=module._segment_exit(
                position,effective_start,tape,terminal,entry_flow,policy)
            observed=max(duration,max(0,int(terminal.get('time',0))-int(current.get('time',0))))
            elapsed,collapse_streaks,reasons=_meteora_exit_progress(module,raw_reasons,
                elapsed=elapsed,observed=observed,streaks=collapse_streaks,policy=policy)
            book.append(identity,'mark',dict(
                tape=module.asdict(tape),position_hash=module.digest(position),mark=mark,
                strategy_progress=dict(observed_seconds=observed,elapsed_seconds=elapsed,
                    collapse_streaks=collapse_streaks,raw_exit_reasons=raw_reasons,
                    eligible_exit_reasons=reasons,effective_start_hash=module.digest(effective_start),
                    effective_start=(effective_start if effective_start!=current else None))))
            current=deepcopy(terminal);last_lineage=tape.lineage
            segments.append(dict(
                elapsed_seconds=elapsed,lineage=tape.lineage,swaps=len(tape.events),
                recent=recent,mark=mark,dynamic_fee_uplift=uplift,
                raw_exit_reasons=raw_reasons,collapse_streaks=dict(collapse_streaks),
                exit_reasons=reasons,evidence_recovery_attempts=recoveries))
            if reasons:
                exit_reason=reasons[0];break
        if elapsed>=max_hold and exit_reason is None:
            exit_reason='maximum_holding_time'
        if exit_reason is not None:
            final=module._mark(position)
            book.append(identity,'settle',dict(
                mark=final,exit_reason=exit_reason,lineage=last_lineage or module.digest(entry)))
            accounting=book.reconcile()
            replay=book.replay_economics(
                module._build_position,module._advance_position,module._mark)
            return dict(
                lane='meteora',status='settled',handoff_required=False,
                lifecycle_id=identity,exit_reason=exit_reason,
                realized_hold_seconds=elapsed,segments=segments,final=final,
                accounting=accounting,accounting_replay=replay,
                terminal_replay_verified=replay.get('verified') is True,
                runtime_identity=runtime_identity,
            )
        row=dict(
            schema='meteora-position-continuation-v1',lane='meteora',
            status='handoff_required',handoff_required=True,lifecycle_id=identity,
            reason=handoff_reason,verified_hold_seconds=elapsed,
            accounting_path=str(db_path),accounting=book.reconcile(),
            updated_at=time.time(),
        )
        from meme_machine.durable_publication import publish_report
        row['publication']=publish_report(Path(state_dir)/'solana-dlmm-independent-v1-live.continuation.json',row)
        return row
    finally:
        broker.close()


def _json_env(name):
    raw=str(os.environ.get(name,'') or '').strip()
    if not raw:return {}
    value=json.loads(raw)
    if not isinstance(value,dict):raise RuntimeError('invalid_'+name.lower())
    return {str(k).lower():v for k,v in value.items()}


def resume_ramses(state_dir,*,slice_seconds):
    runtime_identity=_runtime_identity(state_dir,'ramses')
    lane_root=_activate_lane_root()
    runtime_identity['lane_root']=lane_root
    from robinhood_research import BoundaryError
    from robinhood_research import ramses_all_pool_lifecycle as module
    from robinhood_research.ramses_strategy_ledger import RamsesStrategyLedger

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
        from certification.continuity_state import recover as recover_checkpoint,checkpoint as durable_checkpoint,fields
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
            time.sleep(min(module.MONITOR_POLL_SECONDS,max(0,slice_deadline-time.monotonic()-5)))
            if time.monotonic()>=slice_deadline-5:break
            try:
                rpc=module._new_position_reader(endpoint,rpc)
                frontier=rpc.call('eth_getBlockByNumber',['finalized',False],scope='lifecycle_monitor')
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                module._record_provider_hold(state,book,identity,stage='frontier',
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
                    module._record_provider_hold(state,book,identity,stage='rescan',
                        boundary=exc,at=terminal_at)
                finally:last_scan_wall=time.monotonic()
            row=next((r for r in latest_screen.get('rows',[])
                      if str(r.get('pool','')).lower()==pool),None)
            opportunity_qualified=bool(row and (row.get('decision') or {}).get('qualified'))
            try:
                state_now=module._position_state(rpc,pool,decision,block)
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                module._record_provider_hold(state,book,identity,stage='position_state',
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
                    module._record_provider_hold(state,book,identity,stage='fee_reserve',
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
                    book.checkpoint(identity,action='monitor',detail=hold,at=at);continue
            except BoundaryError as exc:
                if not module._is_transient_provider_boundary(exc):raise
                module._record_provider_hold(state,book,identity,stage='exit_replay_or_unwind',
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
            return settle_flat('flat_quote_without_committed_replacement')
        state.update(active=True,handoff_required=True,ledger_path=str(ledger_path),
                     paper_capital=int(state['paper_capital']),quote_asset=state['quote_asset'])
        _atomic(state_path,state)
        return dict(lane='ramses',status='handoff_required',handoff_required=True,
                    accounting=book.reconcile(),state=state,runtime_identity=runtime_identity)
    finally:
        book.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--lane',choices=('meteora','ramses'),required=True)
    p.add_argument('--state-dir',required=True)
    p.add_argument('--slice-seconds',type=int,default=3000)
    p.add_argument('--output',default='position-continuation-result.json')
    p.add_argument('--audit-output')
    a=p.parse_args()
    if not 60<=a.slice_seconds<=3300:raise SystemExit('continuation_slice_bound')
    state_dir=Path(a.state_dir).resolve();output=Path(a.output).resolve()
    audit=Path(a.audit_output).resolve() if a.audit_output else state_dir/'continuation-audits'/str(time.time_ns())
    audit.mkdir(parents=True,exist_ok=True)
    _activate_lane_root()
    from certification.market_assurance import native_positions,continuity
    from certification.decision_conformance import install
    source=json.loads((Path(__file__).parent/'sources.json').read_text())['lanes'][a.lane]
    os.environ['MM_CERT_SOURCE_SHA']=source['source_sha']
    from certification.run import git
    os.environ['MM_CERT_INTEGRATION_SHA']=git('rev-parse','HEAD')
    # Snapshot the lane book once; subsequent changes must extend its prefix.
    before=native_positions(state_dir,a.lane);_atomic(audit/'position-before.json',before)
    conformance=install(audit,a.lane,source['policy_hash'])
    try:
        native_paths=sorted(state_dir.glob('certification-native/*/'+a.lane))
        cwd=native_paths[0] if len(native_paths)==1 else state_dir
        with chdir(cwd):
            result=(resume_meteora(state_dir,slice_seconds=a.slice_seconds)
                    if a.lane=='meteora' else resume_ramses(state_dir,slice_seconds=a.slice_seconds))
    finally:
        conformance.close()
        after=native_positions(state_dir,a.lane);_atomic(audit/'position-after.json',after)
        transfer=continuity(before,after);_atomic(audit/'continuity.json',transfer)
    import subprocess
    replay=subprocess.run([sys.executable,'-m','certification.decision_conformance',
        '--lane',a.lane,'--trace',str(audit/'decision-trace.jsonl'),
        '--source-root',os.environ['MM_CONTINUATION_LANE_ROOT'],
        '--policy-hash',source['policy_hash'],'--runtime-sha',os.environ['MM_CERT_INTEGRATION_SHA'],
        '--output',str(audit/'conformance.json')],capture_output=True,text=True,timeout=180)
    result['conformance']=json.loads((audit/'conformance.json').read_text())
    result['continuity']=transfer
    if replay.returncode or transfer['status']!='pass' or after['violations']:
        result['assurance_passed']=False;_atomic(output,result)
        raise RuntimeError('continuation_assurance_failed_state_preserved')
    result['assurance_passed']=True
    result['economic_sample_eligible']=(not (state_dir/'engineering-recovery-authorization.json').exists()
        and (result.get('runtime_identity') or {}).get('phase')=='hourly')
    _atomic(output,result)
    print(json.dumps({k:result.get(k) for k in ('lane','status','handoff_required','terminal_replay_verified','assurance_passed','economic_sample_eligible')},sort_keys=True))


if __name__=='__main__':main()
