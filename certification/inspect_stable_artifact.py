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
print('STABLE_ARCHIVE_AUDIT_BEGIN',flush=True)
printed={k:v for k,v in receipt.items() if k not in ('pons_journals','pump_complete')}
printed['pons_journal_categories']={p['file']:dict(collections.Counter(r['category'] for r in p['records'])) for p in review['pons_journals']}
printed['pump_replay']=review['pump_complete'].get('accounting_replay')
print(json.dumps(printed,sort_keys=True),flush=True)
print('STABLE_ARCHIVE_AUDIT_END',flush=True)
if failures:raise RuntimeError('stable_archive_integrity_failed')
