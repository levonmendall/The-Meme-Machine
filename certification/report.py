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
    if result.get('continuous_overlap_seconds',0)<14400:incomplete.append('continuous_four_hour_window_not_completed')
    for lane in LANES:
        row=result.get('lanes',{}).get(lane,{})
        if row.get('process_restarts',0):failures.append(lane+':process_restart')
        if row.get('unexpected_exit'):failures.append(lane+':unexpected_exit')
        if row.get('continuous_uptime_seconds',0)<14400:incomplete.append(lane+':continuous_uptime_short')
        for gate in REQUIRED:
            value=row.get('gates',{}).get(gate)
            if value is False:failures.append(lane+':'+gate)
            elif value is not True:incomplete.append(lane+':unproven:'+gate)
        if row.get('natural_settled',0)<1:incomplete.append(lane+':natural_lifecycle_missing')
        if row.get('open_positions') is None:incomplete.append(lane+':open_exposure_unknown')
        elif row['open_positions']:failures.append(lane+':unsettled_position')
    return dict(status='FAIL' if failures else 'INCOMPLETE' if incomplete else 'PASS',
                failures=failures,incomplete=incomplete,
                target_three_per_lane_met=all(result.get('lanes',{}).get(k,{}).get('natural_settled',0)>=3 for k in LANES))


def summarize(lane, report):
    """Map actual runner fields. Never count cancelled reservations as trades."""
    result=dict(natural_settled=0,forced_settled=0,open_positions=None,
                accounting_reconciled=None,terminal_reasons={},funnel={},limitations=[])
    if not isinstance(report,dict):return result
    result['stream_state']=report.get('stream') or report.get('wake_stream') or report.get('sequencer_discovery')
    result['evidence_state']=report.get('evidence_broker') or report.get('evidence_acquisition')
    result['provider_state']=report.get('active_provider') or report.get('active_discovery_provider') or report.get('provider')
    result['finality_state']=report.get('frontier_discovery') or report.get('canonical_discovery_cursor')
    if lane=='pump':
        result['funnel']=dict(discovered=report.get('created_mints_observed'),
            evidence_complete=len(report.get('full_evidence_candidates',[])),qualified=len(report.get('qualifiers',[])),
            settled=len(report.get('settled',[])))
        result['open_positions']=len(report.get('open_positions',[]))+len(report.get('pending_entries',[]))
        result['natural_settled']=len(report.get('settled',[]))
        result['terminal_reasons']=dict(Counter(x.get('limitation') or x.get('stage','unknown') for x in report.get('attempts',[])))
        result['native_accounting']=report.get('accounting')
        result['accounting_replay']=report.get('accounting_replay')
        if (report.get('accounting') or {}).get('reconciled') is True and (report.get('accounting_replay') or {}).get('verified') is True:
            result['accounting_reconciled']=True
        result['limitations'].append('detailed_cost_decomposition_and_complete_economic_replay_require_verification')
    elif lane=='meteora':
        result['funnel']=dict(discovered=report.get('discovery_unique_pool_count'),screened=report.get('compatibility_screened_count'),
                              complete_observations=report.get('complete_lifecycle_count'))
        result['terminal_reasons']=report.get('qualification_failure_counts',{})
        book=report.get('accounting') or {};replay=report.get('accounting_replay') or {}
        result['native_accounting']=book;result['accounting_replay']=replay
        if book:
            result['open_positions']=book.get('unsettled')
            settled=report.get('qualified_lifecycles',[])
            identities={x.get('lifecycle_id') for x in settled if x.get('complete') and x.get('lifecycle_id')}
            if book.get('reconciled') is True and book.get('settled')==len(identities):
                result['natural_settled']=len(identities)
                result['accounting_reconciled']=True
        result['limitations'].append('economic_replay_uses_authenticated_lane_tapes_raw_chain_reauthentication_is_separate')
    elif lane=='pons':
        summary=report.get('summary') or {}
        result['funnel']=dict(evaluated=summary.get('enrolled',len(report.get('rows',[]))),
                             qualified=summary.get('qualified',len(report.get('qualifiers',[]))))
        for life in report.get('lifecycles',[]):
            pos=life.get('final_position') or {}
            if pos.get('status')=='settled' and pos.get('entry_tokens',0)>0:
                result['natural_settled']+=1
        result['open_positions']=sum((x.get('reconciliation') or {}).get('open_exposure',0)>0 for x in report.get('lifecycles',[]))
        result['terminal_reasons']=(report.get('summary') or {}).get('rejection_counts',{})
        result['cohort_accounting']=report.get('cohort_accounting')
        if result['cohort_accounting']:
            result['open_positions']=result['cohort_accounting']['unsettled']
            result['accounting_reconciled']=result['cohort_accounting'].get('conservation') is True
        result['limitations'].append('partial_exit_capital_time_and_detailed_cost_decomposition_require_verification')
    else:
        result['funnel']=dict(scans=len(report.get('natural_screens',[])),active_pools=report.get('unique_active_pools'))
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
        if campaign:
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
    return result


def dashboard(result,path):
    columns=('Lane','Health','Uptime (s)','Policy','Natural / forced settled','Requests','Latest phase','Accounting')
    rows=[]
    for lane in LANES:
        r=result.get('lanes',{}).get(lane,{})
        rows.append([lane,r.get('health','unknown'),round(r.get('continuous_uptime_seconds',0),1),
                     r.get('policy_hash','unknown')[:12],f"{r.get('natural_settled',0)} / {r.get('forced_settled',0)}",
                     r.get('provider_requests','unknown'),r.get('phase','unknown'),
                     'verified' if r.get('gates',{}).get('accounting_reconciled') is True else 'unproven'])
    cell=lambda x:'<td>'+escape(str(x))+'</td>'
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Four-lane paper certification</title><style>body{font:15px system-ui;background:#101820;color:#e7eef4;padding:24px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #34434f}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1{font-size:24px}.scroll{overflow-x:auto}</style><h1>Four-lane paper certification</h1>'''
    html+='<p>Result: '+escape(result.get('certification',{}).get('status','RUNNING'))+'</p><div class="scroll"><table><tr>'+''.join('<th>'+x+'</th>' for x in columns)+'</tr>'
    html+=''.join('<tr>'+''.join(cell(x) for x in row)+'</tr>' for row in rows)+'</table></div>'
    html+='<p>Unknown fields remain unproven. Raw RPC evidence and append-only telemetry are retained per lane. Forced outcomes never count as natural qualification.</p>'
    for lane in LANES:
        r=result.get('lanes',{}).get(lane,{})
        fields=('strategy_version','funnel','terminal_reasons','open_positions','native_accounting','cohort_accounting',
                'accounting_by_scope','pnl_decomposition','stream_state','finality_state','evidence_state',
                'rpc_latency_seconds','provider_state','errors')
        html+='<details open><summary>'+escape(lane)+' — lane status</summary><pre>'+escape(json.dumps({k:r.get(k) for k in fields if k in r},indent=2))+'</pre></details>'
    html+='<details open><summary>Shared provider contention</summary><pre>'+escape(json.dumps(result.get('shared_provider'),indent=2))+'</pre></details>'
    html+='<details><summary>Funnel, reasons, contention and evidence limits</summary><pre>'+escape(json.dumps(result,indent=2))+'</pre></details></html>'
    Path(path).write_text(html)
