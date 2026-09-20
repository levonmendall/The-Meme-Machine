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
    if lane=='pump':
        result['funnel']=dict(discovered=report.get('created_mints_observed'),
            evidence_complete=len(report.get('full_evidence_candidates',[])),qualified=len(report.get('qualifiers',[])),
            settled=len(report.get('settled',[])))
        result['open_positions']=len(report.get('open_positions',[]))+len(report.get('pending_entries',[]))
        result['natural_settled']=len(report.get('settled',[]))
        result['terminal_reasons']=dict(Counter(x.get('limitation') or x.get('stage','unknown') for x in report.get('attempts',[])))
        result['native_accounting']=report.get('accounting')
        result['accounting_replay']=report.get('accounting_replay')
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
        result['funnel']=dict(evaluated=len(report.get('rows',[])),qualified=len(report.get('qualifiers',[])))
        for life in report.get('lifecycles',[]):
            pos=life.get('final_position') or {}
            if pos.get('status')=='settled' and pos.get('entry_tokens',0)>0:
                result['natural_settled']+=1
        result['open_positions']=sum((x.get('reconciliation') or {}).get('open_exposure',0)>0 for x in report.get('lifecycles',[]))
        result['terminal_reasons']=(report.get('summary') or {}).get('rejection_counts',{})
        result['cohort_accounting']=report.get('cohort_accounting')
        if result['cohort_accounting']:
            result['open_positions']=result['cohort_accounting']['unsettled']
        result['limitations'].append('partial_exit_capital_time_and_detailed_cost_decomposition_require_verification')
    else:
        result['funnel']=dict(scans=len(report.get('natural_screens',[])),active_pools=report.get('unique_active_pools'))
        life=report.get('connected_lifecycle') or {};pos=life.get('final_position') or {}
        if report.get('natural_qualifier_found') and pos.get('status')=='settled':result['natural_settled']=1
        forced=report.get('forced_machinery') or {}
        if forced.get('mechanics_complete') and (forced.get('final_position') or {}).get('status')=='settled':result['forced_settled']=1
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
    html+='<details><summary>Funnel, reasons, contention and evidence limits</summary><pre>'+escape(json.dumps(result,indent=2))+'</pre></details></html>'
    Path(path).write_text(html)
