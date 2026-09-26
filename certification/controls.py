"""Evidence-backed engineering readiness, separate from natural certification."""
import gzip
import json
from pathlib import Path
import sqlite3

from certification.journal import Journal, digest
from certification.report import LANES,permanently_unfunded


def audit_telemetry(folder,lane,policy,*,require_returned=True):
    """Verify every raw transport against its append-only journal reference."""
    folder=Path(folder);journal=Journal(folder/'telemetry.sqlite')
    try:
        references={};terminals=[]
        for event in journal.records():
            if event['lane']!=lane:raise ValueError('cross_lane_telemetry')
            if event['kind']=='rpc_transport':
                body=event['body'];seq=body['sequence']
                if seq in references:raise ValueError('duplicate_transport_sequence')
                references[seq]=body['raw_hash']
            elif event['kind']=='process_terminal':terminals.append(event['body'])
    finally:journal.close()
    seen=set();methods=set()
    with gzip.open(folder/'rpc-evidence.jsonl.gz','rt') as raw:
        for line in raw:
            row=json.loads(line);seq=row['sequence']
            if row['lane']!=lane or seq in seen or references.get(seq)!=digest(row):
                raise ValueError('raw_transport_journal_mismatch')
            seen.add(seq)
            for request in row['request']:
                methods.add(request['method'] if isinstance(request,dict) else request[0])
    if set(references)!=seen:raise ValueError('missing_raw_transport_record')
    if (len(terminals)!=1 or terminals[0].get('policy_hash')!=policy
            or terminals[0].get('status') not in ('returned','failed')
            or (require_returned and terminals[0].get('status')!='returned')):
        raise ValueError('native_terminal_or_policy_mismatch')
    read_only=all(method.startswith('get') if lane in ('pump','meteora') else method in {
        'eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_getBlockByHash',
        'eth_getLogs','eth_getTransactionReceipt','eth_getTransactionByHash',
        'eth_getCode','eth_getStorageAt','eth_getBalance','eth_call','eth_gasPrice',
        'eth_getBlockReceipts','eth_callMany',
        'eth_feeHistory','net_version','web3_clientVersion','eth_estimateGas',
        'alchemy_getAssetTransfers',
    } for method in methods)
    return dict(verified=True,raw_transport_records=len(seen),methods=sorted(methods),read_only=read_only,
                process_terminal=terminals[0]['status'],successful_process=terminals[0]['status']=='returned')


def broker_snapshot(path):
    path=Path(path)
    if not path.exists():return None
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        rows=db.execute('SELECT priority,status,count(*) FROM jobs GROUP BY priority,status').fetchall()
        return dict(active=sum(n for _,s,n in rows if s in ('pending','inflight')),
            priority_status=[dict(priority=p,status=s,count=n) for p,s,n in rows])
    finally:db.close()


def record_unfinished_broker_jobs(path,journal,now):
    """Retain and explicitly censor every unfinished shared job at shutdown.

    Never mutates broker state or reclassifies missing evidence as economic
    rejection. Called only after all four processes have exited.
    """
    path=Path(path)
    if not path.exists():return dict(count=0,reasons={})
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    counts={};consumer_counts={}
    try:
        for key,kind,priority,deadline,status in db.execute("SELECT job_key,kind,priority,deadline,status FROM jobs WHERE status IN ('pending','inflight')"):
            reason='evidence_deadline_expired_at_shutdown' if deadline<now else 'uncompleted_evidence_at_campaign_shutdown'
            journal.append('supervisor','broker-terminal:'+key,'evidence_terminal',dict(
                job_key=key,kind=kind,priority=priority,deadline=deadline,native_status=status,
                terminal_reason=reason,qualification_inferred=False))
            counts[reason]=counts.get(reason,0)+1
        # Logical evidence interests are distinct from the bounded transport queue.
        # Every unserved consumer also receives a durable shutdown terminal; reducing
        # admission must never hide missing evidence behind a smaller job count.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_consumers'").fetchone():
            for owner,signature,kind,deadline in db.execute(
                    "SELECT owner,signature,kind,deadline FROM evidence_consumers WHERE state='waiting'"):
                reason=('consumer_deadline_expired_at_shutdown' if deadline<now
                        else 'consumer_censored_at_campaign_shutdown')
                journal.append('supervisor','consumer-terminal:'+owner+':'+signature,
                    'evidence_consumer_terminal',dict(owner=owner,signature=signature,
                    kind=kind,deadline=deadline,terminal_reason=reason,qualification_inferred=False))
                consumer_counts[reason]=consumer_counts.get(reason,0)+1
    finally:db.close()
    return dict(count=sum(counts.values()),reasons=counts,
                consumer_count=sum(consumer_counts.values()),consumer_reasons=consumer_counts)


def smoke_engineering(result):
    """A machinery preflight, never a four-hour or natural execution PASS."""
    failures=[]
    if result.get('phase')!='smoke' or result.get('status')!='FINISHED':failures.append('smoke_not_finished')
    from certification.solana_lifecycle import pump_flat_completion,authoritative_activity
    lanes=result.get('lanes',{})
    # Pump's native 600-second discovery can finish before the last-launched lane.
    # Record actual overlap unchanged; require the exact native completion receipt
    # and a full observed interval for every other lane.
    completed=(pump_flat_completion(lanes.get('pump',{})) and all(
        lanes.get(lane,{}).get('continuous_uptime_seconds',0)>=600 for lane in LANES if lane!='pump'))
    if result.get('continuous_overlap_seconds',0)<600 and not completed:failures.append('ten_minute_overlap_missing')
    for lane in LANES:
        row=result.get('lanes',{}).get(lane,{})
        if permanently_unfunded(row):failures.append(lane+':permanently_unfunded_paper_book')
        if row.get('exit_code')!=0 or row.get('unexpected_exit') or row.get('process_restarts')!=0:
            failures.append(lane+':process_continuity')
        handoff=(lane in ('meteora','ramses') and row.get('open_positions')==1
                 and row.get('durable_handoff') is True
                 and (row.get('terminal_reconciliation') or {}).get('verified') is True)
        if (row.get('open_positions')!=0 and not handoff) or row.get('accounting_reconciled') is not True:
            failures.append(lane+':accounting_or_exposure')
        if lane=='pump' and not authoritative_activity(row):
            failures.append('pump:local_authoritative_evidence_activity')
        elif lane!='pump' and not row.get('provider_requests'):
            failures.append(lane+':no_provider_activity')
        if lane in ('pump','meteora') and row.get('infrastructure_failure'):
            failures.append(lane+':evidence_unusable')
        if lane=='ramses' and (row.get('funnel') or {}).get('completed_scans',0)<1:
            failures.append(lane+':no_completed_market_census')
        for gate in ('telemetry_complete','policy_unchanged','paper_only','responsive','state_isolated'):
            if row.get('gates',{}).get(gate) is not True:failures.append(lane+':'+gate)
    shared=result.get('shared_provider',{})
    for network in ('solana','robinhood'):
        if network not in shared or shared[network].get('queues')!=[]:failures.append(network+':provider_queue_not_drained')
    if 'robinhood_reuse' in shared and shared['robinhood_reuse'].get('inflight_jobs')!=0:
        failures.append('robinhood:immutable_provider_jobs_not_drained')
    return dict(status='PASS' if not failures else 'FAIL',failures=failures,
        scope='ten_minute_engineering_preflight_only; not natural or sustained certification')


def hourly_engineering(result):
    """Execution integrity for one hour, separate from natural certification.

    A scarcity-driven INCOMPLETE result is a valid completed observation, not a
    supervisor crash. False controls, accounting failures, restarts and short
    windows still fail this surface.
    """
    failures=[]
    if result.get('phase')!='hourly' or result.get('status')!='FINISHED':
        failures.append('hourly_not_finished')
    if result.get('continuous_overlap_seconds',0)<3600:
        failures.append('one_hour_overlap_missing')
    if (result.get('certification') or {}).get('failures'):
        failures.extend('certification:'+x for x in result['certification']['failures'])
    for lane in LANES:
        row=result.get('lanes',{}).get(lane,{})
        if row.get('exit_code')!=0 or row.get('unexpected_exit') or row.get('process_restarts')!=0:
            failures.append(lane+':process_continuity')
        open_positions=row.get('open_positions')
        durable_handoff=(
            lane in ('meteora','ramses')
            and open_positions==1
            and row.get('durable_handoff') is True
        )
        if row.get('accounting_reconciled') is not True:
            failures.append(lane+':accounting_or_exposure')
        elif open_positions is None:
            failures.append(lane+':open_exposure_unknown')
        elif open_positions and not durable_handoff:
            failures.append(lane+':unsettled_position_without_durable_handoff')
        from certification.solana_lifecycle import authoritative_activity
        if lane=='pump' and not authoritative_activity(row):
            failures.append('pump:local_authoritative_evidence_activity')
        elif lane!='pump' and not row.get('provider_requests'):
            failures.append(lane+':no_provider_activity')
        if lane in ('pump','meteora') and row.get('infrastructure_failure'):
            failures.append(lane+':evidence_unusable')
        if lane=='ramses' and (row.get('funnel') or {}).get('completed_scans',0)<1:
            failures.append(lane+':no_completed_market_census')
        for gate in ('telemetry_complete','policy_unchanged','paper_only','responsive','state_isolated'):
            if row.get('gates',{}).get(gate) is not True:failures.append(lane+':'+gate)
    shared=result.get('shared_provider',{})
    for network in ('solana','robinhood'):
        if network not in shared or shared[network].get('queues')!=[]:
            failures.append(network+':provider_queue_not_drained')
    if 'robinhood_reuse' in shared and shared['robinhood_reuse'].get('inflight_jobs')!=0:
        failures.append('robinhood:immutable_provider_jobs_not_drained')
    return dict(status='PASS' if not failures else 'FAIL',failures=failures,
        scope='one_hour_execution_integrity_only; natural certification remains separate')


def sustained_readiness(smoke_path,*,manifest_hash,implementation_hash,integration_sha):
    if not smoke_path:return ['exact_revision_clean_smoke_required']
    try:smoke=json.loads(Path(smoke_path).read_text())
    except (OSError,ValueError):return ['smoke_result_unreadable']
    blockers=[]
    for key,value in (('source_manifest_hash',manifest_hash),('implementation_hash',implementation_hash),('integration_sha',integration_sha)):
        if smoke.get(key)!=value:blockers.append('smoke_revision_mismatch:'+key)
    blockers.extend(smoke_engineering(smoke)['failures'])
    if any(row.get('open_positions') for row in smoke.get('lanes',{}).values()):
        blockers.append('smoke_positions_require_verified_continuation_before_fresh_campaign')
    return blockers


def export_readiness(path,output):
    """Small workflow handoff; full evidence stays in the smoke artifact."""
    import hashlib
    raw=Path(path).read_bytes();result=json.loads(raw)
    if smoke_engineering(result)['status']!='PASS':raise ValueError('clean_smoke_required')
    keys=('phase','status','run_id','continuous_overlap_seconds','source_manifest_hash','implementation_hash','integration_sha')
    attestation={key:result[key] for key in keys}
    attestation['full_smoke_result_sha256']=hashlib.sha256(raw).hexdigest()
    attestation['shared_provider']={network:dict(queues=result['shared_provider'][network]['queues']) for network in ('solana','robinhood')}
    if 'robinhood_reuse' in result['shared_provider']:
        attestation['shared_provider']['robinhood_reuse']={k:result['shared_provider']['robinhood_reuse'].get(k) for k in ('state','inflight_jobs')}
    lane_keys=('exit_code','unexpected_exit','process_restarts','open_positions','accounting_reconciled','provider_requests','gates','native_accounting','funnel','durable_handoff','terminal_reconciliation',
               'continuous_uptime_seconds','pump_discovery_terminal','evidence_liveness','infrastructure_failure','stream_state','method_counts','process_terminal','pipeline_health','scan_progress')
    attestation['lanes']={lane:{key:result['lanes'][lane].get(key) for key in lane_keys} for lane in LANES}
    with Path(output).open('a') as handle:
        handle.write('readiness='+json.dumps(attestation,separators=(',',':'))+'\n')
        handle.write('pending_positions='+str(any(r.get('open_positions') for r in result['lanes'].values())).lower()+'\n')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--smoke-result',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();export_readiness(args.smoke_result,args.output)
