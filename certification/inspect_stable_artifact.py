"""Read-only verification of frozen archive bytes and native ledgers."""
import collections,hashlib,json,pathlib,runpy,sqlite3
state=runpy.run_path('certification/frozen_artifact_review.py')
root=state['root'];review=state['review'];result=state['result'];out=state['OUT']
manifest=json.loads((root/'evidence-snapshot.json').read_text())
failures=[];counts=collections.Counter();verified=[]
for row in manifest['files']:
    counts[row['kind'] if 'kind' in row else 'snapshot_error']+=1
    if row.get('error_type'):failures.append({'snapshot_error':row})
    if not row.get('sha256'):continue
    parts=pathlib.Path(row['target']).parts
    try:relative=pathlib.Path(*parts[parts.index('certification-artifact')+1:])
    except ValueError:raise RuntimeError('unexpected_staged_target')
    path=root/relative
    if not path.resolve().is_relative_to(root.resolve()):raise RuntimeError('snapshot_path')
    with path.open('rb') as file:actual=hashlib.file_digest(file,'sha256').hexdigest()
    if actual!=row['sha256'] or path.stat().st_size!=row['bytes']:
        failures.append({'checksum':str(relative)})
    record={'path':str(relative),'bytes':path.stat().st_size,'sha256':actual}
    if row.get('kind')=='sqlite_online_backup':
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        integrity=db.execute('PRAGMA quick_check').fetchall()
        mode=db.execute('PRAGMA journal_mode').fetchone()[0]
        db.close()
        record.update(integrity=integrity,journal_mode=mode)
        if integrity!=[('ok',)] or mode!='delete':failures.append({'sqlite':str(relative)})
    verified.append(record)
if not manifest.get('snapshot_complete'):failures.append({'snapshot_complete':False})
if manifest.get('native_exposure_relabelled') is not False:failures.append({'exposure_manifest':False})
metrics={lane:{k:value.get(k) for k in (
 'policy_hash','strategy_version','process_restarts','continuous_uptime_seconds','runtime_resources',
 'stream_state','funnel','opportunity_coverage','evidence_state','finality_state','scan_progress',
 'provider_method_errors','provider_http_status_errors','provider_rpc_error_codes','method_counts',
 'accounting_reconciled','cohort_accounting','native_accounting','open_positions','natural_settled',
 'forced_settled','unexpected_exit','exit_code')} for lane,value in result['lanes'].items()}
source={k:v for k,v in result.items() if any(x in k for x in ('source','integrity','drain','manifest','diff','engineering','seconds','status','sha'))}
receipt={'sha':state['SHA'],'run':state['RUN'],'phase':state['PHASE'],
 'snapshot_complete':manifest.get('snapshot_complete'),'snapshot_cancelled':manifest.get('cancelled'),
 'verified_file_count':len(verified),'file_kinds':dict(counts),'failures':failures,'source':source,
 'lanes':metrics,'shared_provider':result.get('shared_provider'),
 'pons_native_final_complete':review.get('pons_native_final_complete'),
 'pons_native_boundary':review.get('pons_native_boundary'),
 'pons_lifecycles':review['native_lifecycles'],
 'pons_journals':review['pons_journals'],
 'pump_complete':review['pump_complete']}
(out/'stable-archive-audit.json').write_text(json.dumps(receipt,indent=2,sort_keys=True))
(out/'verified-file-checksums.json').write_text(json.dumps(verified,indent=2,sort_keys=True))
# Attribute null immutable-body responses without treating absent data as successful reuse.
nulls=collections.defaultdict(list)
with state['gzip'].open(state['base']/'pump/rpc-evidence.jsonl.gz','rt') as file:
    try:
        for line in file:
            row=json.loads(line);requests=row.get('request') or []
            requests=requests if isinstance(requests,list) else [requests]
            response=row.get('response');responses=response if isinstance(response,list) else [response]
            by_id={r.get('id'):r for r in responses if isinstance(r,dict) and 'id' in r}
            for request in requests:
                if not isinstance(request,dict) or request.get('method')!='getTransaction':continue
                answer=by_id.get(request.get('id'))
                if answer is not None and 'result' in answer and answer['result'] is None:
                    signature=request['params'][0]
                    nulls[signature].append({k:row.get(k) for k in (
                        'physical_request_id','observed_at_ns','http_status','json_rpc_error_codes',
                        'retry_count','original_deadline','evidence_kind','evidence_priority')})
    except EOFError:
        if not state['cancelled']:raise
null_failure_records=[r for r in review['raw']['pump']['provider_failures'] if 'null' in str(r.get('error','')).lower()]
null_summary={'attribution_scope':'explicit per-member JSON-RPC result:null; exception-only failures retained separately',
 'exception_null_records':null_failure_records,'unique_signatures':len(nulls),'null_members':sum(map(len,nulls.values())),
 'repeated_null_signatures':{k:v for k,v in nulls.items() if len(v)>1},
 'all_null_signatures':dict(nulls)}
(out/'null-transaction-attribution.json').write_text(json.dumps(null_summary,indent=2,sort_keys=True))
print('NULL_TRANSACTION_AUDIT_BEGIN',flush=True)
print(json.dumps(null_summary,sort_keys=True),flush=True)
print('NULL_TRANSACTION_AUDIT_END',flush=True)

# Read-only attribution of foreground work to retained finalized stream hints.
import zlib
PUMPSWAP_PROGRAM='pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
broker_paths=list(root.rglob('shared-solana-evidence.sqlite'))
if len(broker_paths)!=1:raise RuntimeError('shared_broker_identity_ambiguous')
db=sqlite3.connect(broker_paths[0].resolve().as_uri()+'?mode=ro',uri=True)
def log_shape(logs):
    if not isinstance(logs,list) or not logs:return 'missing_or_empty_logs'
    if any('truncat' in str(x).lower() for x in logs):return 'truncated_logs'
    if any(PUMPSWAP_PROGRAM in str(x) for x in logs):return 'possible_pumpswap'
    return 'complete_logs_exclude_pumpswap'
hints=collections.Counter();body_shapes=collections.Counter();seen_bodies=set()
for stream,signature,payload,body in db.execute("""
    SELECT a.stream,a.signature,a.payload,t.payload
    FROM stream_signature_archive a LEFT JOIN immutable_transactions t ON t.signature=a.signature
    WHERE a.stream LIKE 'pumpswap_pool:%'"""):
    hints['archived_notifications']+=1
    if signature=='1'*64:hints['default_signature_notifications']+=1
    if payload is None:hints['without_retained_payload']+=1
    else:
        value=json.loads(zlib.decompress(payload))
        hints['retained_payload:'+log_shape(value.get('logs'))]+=1
    if body is None:
        hints['without_acquired_body']+=1
    elif signature not in seen_bodies:
        seen_bodies.add(signature)
        tx=json.loads(zlib.decompress(body))
        body_shapes[log_shape((tx.get('meta') or {}).get('logMessages'))]+=1
consumers=[dict(kind=k,state=s,logical_consumers=n,unique_signatures=u,unique_candidates=c)
    for k,s,n,u,c in db.execute("""
        SELECT kind,state,count(*),count(DISTINCT signature),count(DISTINCT candidate_id)
        FROM evidence_consumers WHERE lane='pump' GROUP BY kind,state""")]
deadlines=[dict(kind=k,stage=stage,logical_consumers=n,unique_signatures=u)
    for k,stage,n,u in db.execute("""
        SELECT kind,CASE WHEN created_at>=deadline THEN 'already_expired_before_enqueue'
          WHEN first_transport_at IS NULL THEN 'expired_before_transport'
          ELSE 'expired_after_transport_started' END,count(*),count(DISTINCT signature)
        FROM evidence_consumers WHERE lane='pump' AND state='consumer_deadline_expired' GROUP BY 1,2""")]
stream_audit={'run':state['RUN'],'sha':state['SHA'],'phase':state['PHASE'],
 'scope':'All archived pool notifications; acquired-body classification is evidence only for bodies actually obtained, not an inference about missing bodies.',
 'archived_hints':dict(hints),'unique_acquired_body_log_shapes':dict(body_shapes),
 'consumer_states':consumers,'deadline_decomposition':deadlines}
db.close()

# Actual per-pool negative-screen counters, including retired histories.
screened={}
def history_count(mint,history):
    if isinstance(history,dict) and 'stream_prefiltered_signatures' in history:
        screened[str(mint)]=max(screened.get(str(mint),0),int(history['stream_prefiltered_signatures']))
pump_report=review['pump_complete']
for mint,history in (pump_report.get('postgrad_history_status') or {}).items():history_count(mint,history)
for key in ('postgrad','attempts','full_evidence_attempts'):
    values=pump_report.get(key)
    if isinstance(values,list):
        for value in values:
            if isinstance(value,dict):history_count(value.get('mint'),value.get('history_status'))
terminal_sources=[]
for path in (state['native']/'pump').rglob('*terminal*.jsonl'):
    terminal_sources.append(str(path.relative_to(root)))
    with path.open() as file:
        for line in file:
            if not line.strip():continue
            value=json.loads(line);history_count(value.get('mint'),value.get('history_status'))
stream_audit['actual_prefiltered_unique_by_mint']=screened
stream_audit['actual_prefiltered_pool_signature_pairs']=sum(screened.values())
stream_audit['terminal_counter_sources']=terminal_sources
# Method error counters can describe affected batches; retain actual RPC error members separately.
rpc_members=[]
with state['gzip'].open(state['base']/'pons/rpc-evidence.jsonl.gz','rt') as file:
    try:
        for line in file:
            row=json.loads(line);requests=row.get('request') or []
            requests=requests if isinstance(requests,list) else [requests]
            request_by_id={r.get('id'):r for r in requests if isinstance(r,dict)}
            responses=row.get('response');responses=responses if isinstance(responses,list) else [responses]
            for response in responses:
                if not isinstance(response,dict) or not isinstance(response.get('error'),dict):continue
                request=request_by_id.get(response.get('id')) or {}
                error=response['error']
                rpc_members.append(dict(physical_request_id=row.get('physical_request_id'),
                    observed_at_ns=row.get('observed_at_ns'),method=request.get('method'),
                    code=error.get('code'),message=str(error.get('message',''))[:180],http_status=row.get('http_status')))
    except EOFError:
        if not state['cancelled']:raise
rpc_attribution={'scope':'Actual response error members when present; exception-only failures retain affected batch methods without inventing per-member attribution.',
 'response_error_members':rpc_members,
 'exception_only_failures':[dict(physical_request_id=r.get('physical_request_id'),observed_at_ns=r.get('observed_at_ns'),
     error=r.get('error'),http_status=r.get('http_status'),json_rpc_error_codes=r.get('json_rpc_error_codes'),
     affected_batch_methods=sorted(set(x.get('method') if isinstance(x,dict) else x[0] for x in (r.get('request') or []))))
     for r in review['raw']['pons']['provider_failures']]}
(out/'pons-rpc-member-errors.json').write_text(json.dumps(rpc_attribution,indent=2,sort_keys=True))
print('PONS_RPC_MEMBER_ERRORS_BEGIN',flush=True);print(json.dumps(rpc_attribution,sort_keys=True),flush=True);print('PONS_RPC_MEMBER_ERRORS_END',flush=True)

(out/'stream-admission-attribution.json').write_text(json.dumps(stream_audit,indent=2,sort_keys=True))
print('STREAM_ADMISSION_AUDIT_BEGIN',flush=True);print(json.dumps(stream_audit,sort_keys=True),flush=True);print('STREAM_ADMISSION_AUDIT_END',flush=True)

print('STABLE_ARCHIVE_AUDIT_BEGIN',flush=True)
printed={k:v for k,v in receipt.items() if k not in ('pons_journals','pump_complete')}
printed['pons_journal_categories']={p['file']:dict(collections.Counter(r['category'] for r in p['records'])) for p in review['pons_journals']}
printed['pump_replay']=review['pump_complete'].get('accounting_replay')
print(json.dumps(printed,sort_keys=True),flush=True)
print('STABLE_ARCHIVE_AUDIT_END',flush=True)
if failures:raise RuntimeError('stable_archive_integrity_failed')
