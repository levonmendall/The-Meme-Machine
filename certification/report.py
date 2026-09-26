"""Conservative result evaluation: absence of evidence can never become PASS."""
from collections import Counter
from html import escape
import json
from pathlib import Path

LANES=('pump','meteora','pons','ramses')
REQUIRED=('responsive','bounded_queue','provider_limits','no_starvation','telemetry_complete',
          'accounting_reconciled','policy_unchanged','freshness_finality_unchanged',
          'paper_only','state_isolated','durable_replay')


def evaluate(result):
    failures=[];incomplete=[]
    hourly=result.get('phase')=='hourly'
    required_seconds=3600 if hourly else 14400
    if result.get('status')=='FAILED':failures.append('supervisor_failed')
    if result.get('continuous_overlap_seconds',0)<required_seconds:
        incomplete.append('continuous_one_hour_window_not_completed' if hourly else 'continuous_four_hour_window_not_completed')
    for lane in LANES:
        row=result.get('lanes',{}).get(lane,{})
        if row.get('process_restarts',0):failures.append(lane+':process_restart')
        if row.get('unexpected_exit'):failures.append(lane+':unexpected_exit')
        if permanently_unfunded(row):failures.append(lane+':permanently_unfunded_paper_book')
        if row.get('continuous_uptime_seconds',0)<required_seconds:incomplete.append(lane+':continuous_uptime_short')
        for gate in REQUIRED:
            value=row.get('gates',{}).get(gate)
            if value is False:failures.append(lane+':'+gate)
            elif value is not True:incomplete.append(lane+':unproven:'+gate)
        if row.get('natural_settled',0)<1:incomplete.append(lane+':natural_lifecycle_missing')
        if row.get('open_positions') is None:incomplete.append(lane+':open_exposure_unknown')
        elif row['open_positions']:
            if row.get('durable_handoff') is True:
                incomplete.append(lane+':position_continuation_pending')
            else:
                failures.append(lane+':unsettled_position')
    return dict(status='FAIL' if failures else 'INCOMPLETE' if incomplete else 'PASS',
                scope='one_hour_paper_campaign' if hourly else 'four_hour_certification',
                required_observation_seconds=required_seconds,
                failures=failures,incomplete=incomplete,
                target_three_per_lane_met=all(result.get('lanes',{}).get(k,{}).get('natural_settled',0)>=3 for k in LANES))


def permanently_unfunded(row):
    book=row.get('native_accounting') or {}
    manifest=book.get('manifest') or {}
    return ('genesis_by_quote_asset' in manifest and not manifest['genesis_by_quote_asset']
        and manifest.get('later_assets')=='unfunded_capacity_censoring')


def summarize(lane, report):
    """Map actual runner fields. Never count cancelled reservations as trades."""
    result=dict(natural_settled=0,forced_settled=0,open_positions=None,
                accounting_reconciled=None,terminal_reasons={},funnel={},limitations=[])
    if not isinstance(report,dict):return result
    terminal=report.get('process_terminal')
    if isinstance(terminal,dict):
        compact={}
        for key in ('status','exception_type','boundary','policy_hash'):
            value=terminal.get(key)
            if isinstance(value,str) and len(value)<=160:
                compact[key]=value
        if compact:result['process_terminal']=compact
    result['stream_state']=report.get('stream') or report.get('wake_stream') or report.get('sequencer_discovery')
    result['evidence_state']=report.get('evidence_broker') or report.get('evidence_acquisition')
    result['provider_state']=report.get('active_provider') or report.get('active_discovery_provider') or report.get('provider')
    result['finality_state']=report.get('frontier_discovery') or report.get('canonical_discovery_cursor')
    result['opportunity_coverage']=report.get('opportunity_coverage')
    result['scan_progress']=report.get('scan_progress')
    result['last_completed_scan']=report.get('last_completed_scan')
    if lane in ('pump','meteora'):
        result['evidence_liveness']=report.get('evidence_liveness')
        result['infrastructure_failure']=report.get('infrastructure_failure')
    if lane=='pump':
        result['pump_discovery_terminal']=dict(reason=report.get('smoke_tail_exit'),
            configured_seconds=report.get('discovery_seconds'),deadline=report.get('discovery_deadline'),
            completed_at=report.get('discovery_completed_at'))
        qualifiers=report.get('qualifiers',[])
        entry_status=Counter(x.get('entry_status','unknown') for x in qualifiers)
        entry_terminals=Counter('entry_cancelled:'+(x.get('entry_limitation') or 'unknown')
            for x in qualifiers if x.get('entry_status')=='cancelled')
        result['funnel']=dict(discovered=report.get('created_mints_observed'),
            evidence_complete=len(report.get('full_evidence_candidates',[])),qualified=len(qualifiers),
            entry_filled=entry_status['filled'],entry_cancelled=entry_status['cancelled'],
            entry_reserved=entry_status['reserved'],settled=len(report.get('settled',[])))
        result['open_positions']=len(report.get('open_positions',[]))+len(report.get('pending_entries',[]))
        result['natural_settled']=len(report.get('settled',[]))
        terminals=Counter(x.get('limitation') or x.get('stage','unknown') for x in report.get('attempts',[]))
        terminals.update(entry_terminals)
        result['terminal_reasons']=dict(terminals)
        result['native_accounting']=report.get('accounting')
        result['accounting_replay']=report.get('accounting_replay')
        if (report.get('accounting') or {}).get('reconciled') is True and (report.get('accounting_replay') or {}).get('verified') is True:
            result['accounting_reconciled']=True
        result['limitations'].append('detailed_cost_decomposition_and_complete_economic_replay_require_verification')
    elif lane=='meteora':
        checkpoint=report.get('checkpoint') or {}
        economic=sum('pre_entry_features' in x and 'qualification' in x for x in report.get('attempts',[]))
        result['funnel']=dict(discovered=report.get('discovery_unique_pool_count'),
            screened=report.get('compatibility_screened_count',checkpoint.get('compatibility_screened_count')),
            complete_observations=economic,complete_economic_vectors=economic,
            complete_lifecycles=report.get('complete_lifecycle_count',checkpoint.get('complete_lifecycle_count')))
        result['terminal_reasons']=report.get('qualification_failure_counts',{})
        book=report.get('accounting') or {};replay=report.get('accounting_replay') or {}
        result['native_accounting']=book;result['accounting_replay']=replay
        handoffs=[x for x in report.get('qualified_lifecycles',[]) if x.get('handoff_required')]
        if book.get('unsettled') and handoffs:
            result['durable_handoff']=True
            result['continuation_state']=handoffs
        if book:
            result['open_positions']=book.get('unsettled')
            settled=list(report.get('qualified_lifecycles',[]))+list(report.get('continuation_lifecycles',[]))
            identities={x.get('lifecycle_id') for x in settled if x.get('complete') and x.get('lifecycle_id')}
            if book.get('reconciled') is True and book.get('settled')==len(identities):
                result['natural_settled']=len(identities)
                result['accounting_reconciled']=True
        result['limitations'].append('economic_replay_uses_authenticated_lane_tapes_raw_chain_reauthentication_is_separate')
    elif lane=='pons':
        summary=report.get('summary') or {}
        result['funnel']=dict(evaluated=summary.get('enrolled',len(report.get('rows',[]))),
                             qualified=summary.get('qualified',len(report.get('qualifiers',[]))))
        writeoffs=0
        for life in report.get('lifecycles',[]):
            pos=life.get('final_position') or {}
            if (life.get('settlement_kind')=='liquidity_writeoff' or
                    pos.get('reason')=='liquidity_writeoff:impossible_full_position_exit'):
                writeoffs+=1
                continue
            if pos.get('status')=='settled' and pos.get('entry_tokens',0)>0:
                result['natural_settled']+=1
        result['funnel']['liquidity_writeoffs']=writeoffs
        result['open_positions']=sum((x.get('reconciliation') or {}).get('open_exposure',0)>0 for x in report.get('lifecycles',[]))
        result['terminal_reasons']=(report.get('summary') or {}).get('rejection_counts',{})
        result['cohort_accounting']=report.get('cohort_accounting')
        if result['cohort_accounting']:
            result['open_positions']=result['cohort_accounting']['unsettled']
            result['accounting_reconciled']=all(result['cohort_accounting'].get(key) is True
                for key in ('conservation','cash_basis_conservation','native_observation_complete'))
        result['limitations'].append('capital_time_uses_durable_event_times; open_marks_are_asof_observations_not_current_prices')
    else:
        result['funnel']=dict(scans=len(report.get('natural_screens',[])),active_pools=report.get('unique_active_pools'))
        failures=report.get('scan_recovery_attempts') or []
        failed_scans={r.get('logical_scan_id') for r in failures if r.get('infrastructure_censored') is True}
        result['funnel'].update(completed_scans=len(report.get('natural_screens',[])),
            infrastructure_censored_scans=len(failed_scans))
        life=report.get('connected_lifecycle') or {};pos=life.get('ledger_final') or {}
        reconciliation=life.get('ledger_reconciliation') or {}
        lives=report.get('natural_lifecycles') if report.get('continuous_campaign') else [life]
        seen=set()
        for natural in lives or []:
            position=natural.get('ledger_final') or {};book=natural.get('ledger_reconciliation') or {}
            segments=natural.get('segments') or [];identity=natural.get('lifecycle_id') or position.get('id')
            if not report.get('continuous_campaign'):identity=identity or 'single-native-lifecycle'
            if (report.get('natural_qualifier_found') and position.get('status')=='settled'
                    and not position.get('forced_machinery_test') and position.get('strategy_evidence_eligible') is not False
                    and position.get('policy_hash')==report.get('policy_hash') and report.get('policy_hash')
                    and book.get('open_positions')==0 and segments and identity
                    and all(x.get('terminal_equality') is True for x in segments)):
                seen.add(identity)
        result['natural_settled']=len(seen)
        campaign=report.get('campaign_accounting')
        continuation=report.get('continuation_accounting')
        if continuation:
            result['native_accounting']=continuation
            result['open_positions']=continuation.get('open_positions')
            result['accounting_reconciled']=True
            if continuation.get('open_positions'):
                result['durable_handoff']=True
                result['continuation_state']=report.get('position_continuation')
        elif campaign:
            result['native_accounting']=campaign
            result['open_positions']=campaign.get('open_positions')
            result['accounting_reconciled']=campaign.get('conservation') is True
        forced=report.get('forced_machinery') or {}
        if forced.get('mechanics_complete') and (forced.get('final_position') or {}).get('status')=='settled':result['forced_settled']=1
        result['accounting_by_scope']=dict(natural=reconciliation or None,forced=forced.get('reconciliation'))
        if campaign:pass
        elif reconciliation and 'open_positions' in reconciliation:
            result['open_positions']=reconciliation['open_positions']
        elif report.get('natural_qualifier_found') is False and forced.get('reconciliation'):
            result['open_positions']=forced['reconciliation'].get('open_positions')
        result['pnl_decomposition']=life.get('pnl') or (forced.get('segment') or {}).get('pnl')
        reasons=Counter()
        for screen in report.get('natural_screens',[]):
            for row in screen.get('rows',[]):reasons.update(row.get('reasons') or [])
        result['terminal_reasons']=dict(reasons)
        result['limitations'].append('quote_assets_require_separate_balances_and_authenticated_valuation_before_consolidation')
    coverage=result.get('opportunity_coverage') or {}
    if lane=='pons' and coverage:
        result['funnel']['complete_evidence_vectors']=coverage.get('stages',{}).get('evidence_complete',0)
    if coverage:
        result['funnel'].update({'unique_'+k:v for k,v in coverage.get('stages',{}).items()})
        result['funnel'].update({'unique_'+k:v for k,v in coverage.get('unique_classes',{}).items()})
    if lane in ('pump','pons'):
        from certification.directional_accounting import summarize_survivor
        result=summarize_survivor(lane,report,result)
    return result


def pipeline_health(row,now):
    """Stage liveness never replaces transport health or authorizes a restart."""
    scan=row.get('scan_progress') or {}
    frontier=row.get('finality_state') or {}
    if scan.get('state')=='in_progress':
        age=max(0,now-scan.get('updated_at',scan.get('started_at',now)))
        transport_age=row.get('transport_activity_age_seconds')
        transport_fresh=(
            isinstance(transport_age,(int,float))
            and not isinstance(transport_age,bool)
            and 0<=transport_age<=30
        )
        # Provider activity (including repeated errors) is not strategy progress.
        # The census now emits a checkpoint when authenticated pages complete.
        stalled=age>300
        return dict(
            state='stalled' if stalled else 'progressing',
            stage=scan.get('stage'),
            stage_age_seconds=age,
            scan_age_seconds=max(0,now-scan.get('started_at',now)),
            stall_bound_seconds=300,
            progress_source=(
                'transport_without_stage_progress' if age>300 and transport_fresh
                else 'stage_checkpoint'
            ),
            transport_activity_age_seconds=transport_age,
        )
    if scan.get('state')=='deferred':
        return dict(state='infrastructure_censored',stage=scan.get('stage'),
                    boundary=scan.get('boundary'),qualification_inferred=False)
    if isinstance(frontier,dict) and frontier.get('last_gate_reason') in ('frontier_unchanged','cadence_floor'):
        return dict(state='waiting_finalized_frontier',stage=frontier['last_gate_reason'])
    last=(row.get('opportunity_coverage') or {}).get('last_transition') or {}
    if not last:return dict(state='unknown',stage=None)
    age=max(0,now-last.get('at',now))
    active=last.get('stage') in ('evidence_requested','warmup_started','reconstruction_started','entry_reserved')
    return dict(state='stalled' if active and age>300 else 'progressing' if active else 'awaiting_market_or_policy',
                stage=last.get('stage'),stage_age_seconds=age,stall_bound_seconds=300)


def dashboard(result,path):
    """Compact view of measured fields, with the complete result retained below."""
    def value(x):
        if x is None:return 'unmeasured'
        if isinstance(x,bool):return 'yes' if x else 'no'
        if isinstance(x,float):return f'{x:.3f}'
        if isinstance(x,(dict,list)):return json.dumps(x,separators=(',',':'))
        return str(x)
    def cell(x):return '<td>'+escape(value(x))+'</td>'
    def table(headers,rows):
        return ('<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(x)+'</th>' for x in headers)
            +'</tr></thead><tbody>'+''.join('<tr>'+''.join(cell(x) for x in row)+'</tr>' for row in rows)+'</tbody></table></div>')
    def mapping(data):
        return table(('Measure','Observed value'),(data or {'status':None}).items())
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Four-lane paper certification</title><style>
body{font:14px system-ui;background:#101820;color:#e7eef4;padding:24px;max-width:1600px;margin:auto}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:8px;border-bottom:1px solid #34434f;vertical-align:top}td{overflow-wrap:anywhere}th{color:#a7bdca}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1{font-size:24px}h2{font-size:20px}.scroll{overflow-x:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px}section{background:#17232d;padding:16px;border-radius:8px}summary{cursor:pointer;padding:10px 0}.note{color:#b6c5d0}code{overflow-wrap:anywhere}
</style><h1>Four-lane paper certification</h1>'''
    verdict=result.get('certification') or {}
    html+='<p>Result: <strong>'+escape(verdict.get('status','RUNNING'))+'</strong> · '+escape(result.get('status','unknown'))+' · run '+escape(str(result.get('run_id','unknown')))+'</p>'
    html+='<p class="note">Paper only. Unknown fields remain unproven. Forced settlements are separate from natural execution. All balances are native units; unlike assets are never summed.</p>'
    rows=[]
    for lane in LANES:
        r=result.get('lanes',{}).get(lane,{})
        rows.append([lane,r.get('health'),r.get('continuous_uptime_seconds'),r.get('process_restarts'),
            r.get('open_positions'),r.get('natural_settled'),r.get('forced_settled'),r.get('accounting_reconciled')])
    html+=table(('Lane','Health','Uptime seconds','Restarts','Open','Natural settled','Forced settled','Reconciled'),rows)
    html+='<h2>Shared resources</h2>'
    shared=result.get('shared_provider') or {};pressure=[]
    for network,body in shared.items():
        for endpoint in body.get('endpoints',body.get('providers',[])):
            pressure.append([network,endpoint.get('identity',endpoint.get('provider')),endpoint.get('requests',endpoint.get('grants')),
                endpoint.get('interval_seconds'),endpoint.get('rate_errors'),endpoint.get('cooldown_remaining_seconds')])
    html+=table(('Network','Provider identity','Requests / grants','Interval seconds','Rate errors','Cooldown remaining seconds'),pressure)
    html+=mapping({network+' queue':body.get('queues') for network,body in shared.items()})
    html+='<div class="cards">'
    for lane in LANES:
        r=result.get('lanes',{}).get(lane,{})
        html+='<section><h2>'+escape(lane)+'</h2><p>'+escape(r.get('strategy_version','unknown'))+'</p><code>'+escape(r.get('policy_hash','unknown'))+'</code>'
        html+=mapping({'phase':r.get('phase'),'physical requests':r.get('provider_requests'),
            'provider sessions (not reconnect count)':r.get('provider_session_count'),
            'RPC latency p50 / p95 / p99 seconds':r.get('rpc_latency_seconds'),
            'last strategy progress age seconds':r.get('progress_age_seconds'),
            'last transport activity age seconds':r.get('transport_activity_age_seconds')})
        html+='<h3>Opportunity funnel</h3>'+mapping(r.get('funnel'))
        html+='<h3>Pipeline health</h3>'+mapping(r.get('pipeline_health'))
        if r.get('scan_progress'):html+='<h3>Pinned scan progress</h3>'+mapping(r['scan_progress'])
        evidence=r.get('evidence_state') or {};stream=r.get('stream_state') or {}
        native_finality=r.get('finality_state')
        finality=native_finality if isinstance(native_finality,dict) else {}
        html+='<h3>Evidence and continuity</h3>'+mapping({
            'pending jobs':evidence.get('pending_jobs'),'inflight jobs':evidence.get('inflight_jobs'),
            'expired jobs retained':evidence.get('expired_jobs'),'connected':stream.get('connected'),
            'covered':stream.get('covered'),'stream gaps':stream.get('gaps'),
            'last slot':stream.get('last_slot'),
            'canonical cursor':native_finality if isinstance(native_finality,int) and not isinstance(native_finality,bool) else None,
            'frontier polls':finality.get('polls'),
            'frontier advances':finality.get('advances')})
        reasons=sorted((r.get('terminal_reasons') or {}).items(),key=lambda x:(-x[1],x[0]))
        html+='<h3>Latest terminal reasons</h3>'+table(('Reason','Count'),reasons[:6])
        book=r.get('native_accounting') or r.get('cohort_accounting') or {}
        fields=('initial','genesis','cash','basis','reserved','available','realized','unrealized','marked_equity',
            'starting_capital','ending_cash','realized_pnl','capital_unit_nanoseconds','capital_unit_seconds','funding_state','paper_entry_ready')
        balance={k:book[k] for k in fields if k in book}
        if permanently_unfunded(r):balance['capacity defect']='permanently unfunded paper book'
        if book.get('by_quote_asset') is not None:balance['separate quote-asset balances']=book['by_quote_asset']
        html+='<h3>Accounting and PnL</h3>'+mapping(balance)
        if r.get('pnl_decomposition'):html+=mapping(r['pnl_decomposition'])
        html+='<h3>Errors</h3>'+mapping(r.get('errors') or {'observed errors':0})
        html+='<details><summary>Runtime, provider detail and all controls</summary><pre>'+escape(json.dumps({k:r.get(k) for k in (
            'runtime_resources','telemetry_cost','provider_state','finality_state','evidence_state','gates','limitations','terminal_reasons')},indent=2))+'</pre></details></section>'
    html+='</div><details><summary>Complete machine-readable result</summary><pre>'+escape(json.dumps(result,indent=2))+'</pre></details>'
    html+='<p class="note">Raw RPC archives and append-only journals remain available per lane. This view does not replace durable evidence.</p></html>'
    Path(path).write_text(html)


def provider_efficiency(result):
    """Attach estimates to measured denominators; never convert missing evidence to zero."""
    provider=result.get('shared_provider',{}).get('robinhood',{})
    for lane in ('pons','ramses'):
        row=result.get('lanes',{}).get(lane,{})
        stats=provider.get('lanes',{}).get(lane,{})
        cu=stats.get('estimated_cu');funnel=row.get('funnel',{})
        evaluated=funnel.get('evaluated');complete=funnel.get('complete_evidence_vectors');scans=funnel.get('scans')
        ratio=lambda n:cu/n if cu is not None and isinstance(n,(int,float)) and n>0 else None
        row['rpc_efficiency']=dict(estimated_cu=cu,physical_http_requests=stats.get('requests'),
            logical_wire_calls=stats.get('logical_calls'),cu_per_evaluated=ratio(evaluated),
            cu_per_complete_vector=ratio(complete),cu_per_scan=ratio(scans),
            evaluated=evaluated,complete_vectors=complete,scans=scans,
            cache=(result.get('shared_provider',{}).get('robinhood_reuse',{}).get('lanes',{}).get(lane)))
    for lane in ('pump','meteora'):
        row=result.get('lanes',{}).get(lane,{})
        methods=row.get('method_counts',{});physical=row.get('provider_requests')
        logical=sum(methods.values()) if methods else None
        f=row.get('funnel',{});complete=f.get('evidence_complete') if lane=='pump' else f.get('complete_economic_vectors')
        ratio=lambda value:value/complete if value is not None and isinstance(complete,(int,float)) and complete>0 else None
        row['rpc_efficiency']=dict(physical_http_transports=physical,logical_rpc_members=logical,methods=methods,
            estimated_cu=row.get('estimated_alchemy'),complete_evidence_vectors=complete,
            physical_per_complete=ratio(physical),logical_per_complete=ratio(logical),
            cache=result.get('shared_provider',{}).get('solana_reuse',{}).get('lanes',{}).get(lane),
            denominator_status='measured' if complete else 'zero_or_unmeasured_no_efficiency_claim')
    return result
