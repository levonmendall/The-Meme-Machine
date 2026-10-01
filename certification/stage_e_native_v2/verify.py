"""Independently recheck original raw trials, never select a passing retry."""
from pathlib import Path
import re

from .binding import verify_assembly, workflow_identity
from .contract import HERE, canonical, read, sha256


def native_witness(payload, generation, held):
    if not isinstance(generation,str) or not generation or payload.get('generation')!=generation:
        raise ValueError('cross_generation_witness')
    from .clock import validate_clock_samples
    from .fixtures import spec
    validate_clock_samples(payload['clock_samples'],spec('run380')['clock'])
    ids=payload['input_record_identities']
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('record_identity_missing_or_duplicate')
    before={r['identity']:r for r in payload['hot_before']['records']}
    archived={r['identity']:r for r in payload['archived_after']['records']}
    after={r['identity']:r for r in payload['retired_after']['records']}
    retired_ids=payload['retired_record_identities']
    if not retired_ids or len(retired_ids)!=len(set(retired_ids)) or not set(retired_ids)<=set(ids):
        raise ValueError('retired_record_identity_missing')
    receipt=payload['archive_receipt']
    if not receipt or not re.fullmatch('[0-9a-f]{64}',receipt.get('hash','')) or payload.get('durable_archive_hash')!=receipt['hash']:
        raise ValueError('archive_receipt_missing')
    for identity in ids:
        if (identity not in before or identity not in archived or not before[identity]['body_present']
                or archived[identity]['body_present'] or archived[identity]['archive']!=receipt['name']
                or before[identity]['hash']!=archived[identity]['hash']):
            raise ValueError('native_transition_not_committed')
    for identity in retired_ids:
        if identity in after:raise ValueError('native_retirement_not_committed')
        floor=payload['retired_after']['floors'].get('retention_floor:'+archived[identity]['scope'])
        if floor is None or int(floor)<=archived[identity]['slot']:
            raise ValueError('retirement_floor_not_published')
    transactions=payload['archive_transactions']+payload['retirement_transactions']
    if not payload['archive_transactions'] or not payload['retirement_transactions']:
        raise ValueError('committed_transaction_proof_missing')
    transaction_ids=[]
    for row in transactions:
        row=dict(row);identity=row.pop('transaction_id')
        if row['committed'] is not True or row['generation']!=generation or sha256(canonical(row))!=identity:
            raise ValueError('attempt_or_cross_generation_transaction')
        transaction_ids.append(identity)
    if len(set(transaction_ids))!=len(transaction_ids):raise ValueError('duplicated_transaction')
    outcome=payload['retention_outcome']
    if outcome['retired_records']<len(retired_ids) or outcome['committed_slices']<=0:
        raise ValueError('attempted_retirement_cannot_count')
    for side,key in [('archive','archived_after'),('retirement','retired_after')]:
        if not any(r[1]==side and r[3]>0 and r[5]>0 for r in payload[key]['progress']):
            raise ValueError('native_maintenance_progress_missing')
    if payload['source_after']['counters']['stream_accepted_messages']<=payload['source_before']['counters']['stream_accepted_messages']:
        raise ValueError('source_not_advanced')
    if payload['source_after']['gaps'] or payload['integrity']!='ok':raise ValueError('continuity_or_integrity')
    for lane in ('pump','meteora'):
        row=payload['selection'][lane]
        if row['generation']!=generation or not row['candidate'] or not row['exclusion']:
            raise ValueError('native_lane_selection_identity')
        if not row['selected_events' if lane=='pump' else 'selected_transactions']:
            raise ValueError('native_lane_selection_missing')
    if held:
        row=payload['held_reader']
        if (row['generation']!=generation or not row['snapshot_read_id'] or not row['snapshot_query']
                or row['established_before_transaction']!=payload['archive_transactions'][0]['transaction_id']
                or set(row['held_across_transactions'])!=set(transaction_ids)
                or row['snapshot_preserved'] is not True or row['reader_released'] is not True
                or row['passive_while_held'][1]<=row['passive_while_held'][2]
                or row['truncate_while_held'][0]!=1
                or row['passive_after_release'][0]!=0 or row['passive_after_release'][1]!=row['passive_after_release'][2]
                or row['truncate_after_release']!=[0,0,0] or row['integrity']!='ok'):
            raise ValueError('held_reader_or_checkpoint_incomplete')
    return True


def validate_raw(raw, manifest, case, *, allow_failed=False):
    expected=dict(manifest['identity'],assembly_digest=manifest['assembly_digest'])
    schema=read(HERE/'evidence-schema-v2.json')
    if set(raw)!=set(schema['required']):raise ValueError('raw_schema_missing_or_extra_fields')
    if raw['identity']!=expected:raise ValueError('foreign_or_contradictory_raw_identity')
    workflow_identity(raw['identity']['workflow_identity'],expected['candidate_sha'])
    if raw['case_id']!=case or not isinstance(raw['trial_id'],str) or not raw['trial_id'].startswith(case+':'):
        raise ValueError('wrong_or_missing_trial_id')
    if raw['classification'] not in ('STATIC','DETERMINISTIC_BOUNDED'):
        raise ValueError('material_trial_not_authorized')
    if raw['paper_only'] is not True or raw['canonical_authority'] is not False or raw['market_authority'] is not False:
        raise ValueError('authority_not_paper_only')
    if raw['assembly_before']!=expected['assembly_digest'] or raw['assembly_after']!=expected['assembly_digest']:
        raise ValueError('assembly_not_verified_before_and_after')
    if raw['provider_attempts']!=[]:raise ValueError('provider_attempted_calls')
    origins=raw['runtime_origins']
    if not isinstance(origins,list) or not origins:raise ValueError('runtime_origins_missing')
    modules=set()
    for row in origins:
        if not isinstance(row,dict) or set(row)!={'module','origin','sha256','category'} or row['module'] in modules:
            raise ValueError('invalid_or_duplicated_origin')
        modules.add(row['module'])
        if row['category']=='assembled':
            # Physical path is recorded. Its suffix AND actual file hash must
            # belong to this exact manifest, not the root checkout.
            choices=[name for name in manifest['files'] if row['origin'].endswith('/source/'+name)]
            if len(choices)!=1 or manifest['files'][choices[0]]['sha256']!=row['sha256']:
                raise ValueError('foreign_assembly_origin')
        elif row['category']=='approved_dependency':
            if expected['environment_identity']['dependencies']['websockets']['files'].get(row['origin'])!=row['sha256']:
                raise ValueError('wrong_dependency_origin')
        elif row['category']=='standard_library':
            if expected['environment_identity'].get('stdlib_files',{}).get(row['origin'])!=row['sha256']:
                raise ValueError('foreign_standard_library_origin')
        else:raise ValueError('unknown_module_origin_category')
    if 'certification.stage_e_native_v2.runner' not in modules or 'certification.stage_e_native_v2.binding' not in modules:
        raise ValueError('actual_runtime_origin_binding_missing')
    if case!='origin-child':
        if len(raw['children'])!=1:raise ValueError('bound_child_origin_proof_missing')
        validate_raw(raw['children'][0],manifest,'origin-child')
    elif raw['children']:
        raise ValueError('unexpected_nested_origin_probe')
    if type(raw['passed']) is not bool or not isinstance(raw['errors'],list):raise ValueError('malformed_outcome')
    if raw['passed'] is not True:
        if allow_failed:return False
        raise ValueError('failed_trial_preserved_not_qualified')
    if raw['errors']:raise ValueError('contradictory_success')
    payload=raw['payload']
    if case=='origin-child' and (payload.get('child_origin_probe') is not True or payload.get('foreign_dynamic_import_rejected') is not True):
        raise ValueError('child_origin_rejection_proof_missing')
    if case in ('native-transitions','held-reader'):native_witness(payload,raw['generation'],case=='held-reader')
    if case=='generation-restart':
        g,r=payload['generation_fencing'],payload['restart']
        if g['old_generation']==g['new_generation'] or len(g['rejected'])!=3 or g['stale_records_committed']!=0:
            raise ValueError('generation_rejection_missing')
        for k in ('incomplete_service_not_credited','no_duplicate_completion','no_lost_completion',
                  'archive_receipt_continued','retirement_continued','restart_gap_preserved'):
            if r.get(k) is not True:raise ValueError('restart_requirement_missing:'+k)
        if r['episode_before']!=r['episode_after'] or r['committed_service_before']!=r['reconstructed_ledger']:
            raise ValueError('restart_episode_or_ledger_rebased')
    if case=='m1-completion' and (payload.get('passed') is not True or not payload.get('gates') or not all(payload['gates'].values())):
        raise ValueError('m1_native_completion_unearned')
    if case=='run379-setup':
        if (payload.get('setup_elapsed_us')!=0 or payload.get('native_hot_debt')!=200
                or payload.get('bounded_execution_transactions')!=6 or payload.get('source_continuity') is not True
                or payload.get('original_availability_preserved') is not True or payload.get('timestamps_refreshed') is not False
                or payload.get('episodes_reenrolled') is not False or payload.get('integrity')!='ok'):
            raise ValueError('run379_setup_semantics_unearned')
    return True


def aggregate(assembly, digest, paths, inventory, output):
    manifest=verify_assembly(assembly,digest);matrix=manifest['identity']['expected_trial_matrix']
    if type(paths) is not list or len(paths)!=len(matrix) or len({str(Path(p).resolve()) for p in paths})!=len(paths):
        raise ValueError('missing_or_duplicate_trial')
    if not isinstance(inventory,dict) or set(inventory)!=set(matrix):raise ValueError('exact_cohort_inventory_missing')
    seen=set();results={};failed=[];generations={}
    for path in paths:
        raw_bytes=Path(path).read_bytes();raw=read(path);case=raw['case_id']
        if case not in matrix or case in seen:raise ValueError('foreign_or_duplicate_trial')
        receipt=inventory[case]
        if set(receipt)!={'trial_id','sha256','candidate_sha','assembly_digest','run_id','attempt','generation'}:
            raise ValueError('artifact_receipt_missing')
        expected=manifest['identity']
        if (receipt['trial_id']!=raw['trial_id'] or receipt['sha256']!=sha256(raw_bytes)
                or receipt['candidate_sha']!=expected['candidate_sha'] or receipt['assembly_digest']!=digest
                or receipt['run_id']!=expected['workflow_identity']['run_id'] or receipt['attempt']!=1
                or receipt['generation']!=raw['generation']):raise ValueError('stale_or_replaced_artifact')
        seen.add(case);passing=validate_raw(raw,manifest,case,allow_failed=True)
        if not passing:failed.append(case)
        results[case]=dict(passed=passing,raw_hash=receipt['sha256'],trial_id=raw['trial_id'])
    if seen!=set(matrix):raise ValueError('missing_trial')
    verify_assembly(assembly,digest)
    result=dict(contract='stage-e-native-transition-evidence-v2',passed=not failed,
        identity=dict(manifest['identity'],assembly_digest=digest),results=results,failed_trials=failed,
        attempts_policy='first attempt; failed raw trials preserved; no retry selection',
        paper_only=True,canonical_authority=False,market_authority=False,
        stage_e='RED',stage_f='NOT STARTED')
    Path(output).write_bytes(canonical(result))
    return result
