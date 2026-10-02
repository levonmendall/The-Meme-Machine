"""Independent raw native evidence verification. No workload entrypoint imports.

Every result keeps Stage E RED. Finite dictionary tests exercise predicates;
they cannot produce native capacity or observer acceptance.
"""
from contextlib import closing, contextmanager
import gzip
import json
import math
from pathlib import Path
import sqlite3

from core import (ASSEMBLY, COHORT, MODES, S, T, canonical, contract_file, file_sha,
                  read, relative, require, sha, workload)
from preserve import verify_inventory, inventory

SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def bounded(value, limit, *, strict=False):
    return number(value) and (value < limit if strict else value <= limit)


def production_member_errors(row):
    if type(row) is not dict:
        return ['malformed_native_member']
    failures = []
    def check(condition, name):
        if not condition:
            failures.append(name)
    shape = row.get('shape')
    frames = row.get('frames')
    if type(frames) is not int or frames <= 0:
        return ['full_workload_shape']
    check(row.get('candidate_sha') == S and row.get('kind') in ('A', 'B'), 'native_candidate_class')
    check(row.get('errors') == [] and row.get('provider_attempts') == [], 'native_error_or_provider')
    check(row.get('integrity') == ['ok'], 'integrity')
    check(row.get('artificial_contention') == workload('A')['artificial_contention'], 'synthetic_contention_in_production')
    expected_frames = dict(COHORT).get(row.get('member')) if not shape else {'run373':14, 'run379':120, 'run380':240}.get(shape)
    cadence = {'run373':750000, 'run379':50000, 'run380':270000}.get(shape, 270000)
    check(type(frames) is int and frames == expected_frames and row.get('cadence_us') == cadence
          and row.get('source_seconds') == frames*cadence/1e6, 'full_workload_shape')
    setup = row.get('setup', {})
    check(setup.get('setup_elapsed_ns') == 0 and setup.get('historical_availability_unchanged') is True, 'nonaging_setup')
    check(setup.get('seed_frames') == (100 if shape == 'run379' else 0), 'historical_seeds')
    counters, ipc = row.get('counters', {}), row.get('ipc', {})
    initial = setup.get('counters', {}).get('stream_accepted_messages', 0)
    check(type(initial) is int and counters.get('stream_accepted_messages') == frames+initial, 'complete_committed_source')
    check(ipc.get('stream.received_messages') == ipc.get('stream.commit_messages') == frames+1, 'admitted_drain')
    for key, limit in [('stream.outstanding_frames_peak',64), ('stream.dispatch_bytes_peak',96*1024**2),
                        ('stream.commit_batch_messages_peak',8), ('stream.commit_batch_bytes_peak',16*1024**2)]:
        check(bounded(ipc.get(key), limit), 'native_'+key)
    owner = row.get('final', {}).get('health', {}).get('owner_scheduler', {})
    check(bounded(owner.get('queue_peak'),64), 'native_owner_queue')
    check(ipc.get('stream.decode_process_messages', 0) >= frames, 'native_shared_workers_decode')
    check(not any(v for k, v in counters.items() if k.startswith('disconnect:') or k == 'capacity_stops'), 'capacity_disconnect')
    samples = row.get('safety_samples', [])
    check(bool(samples), 'common_safety_raw_samples_missing')
    for sample in samples:
        for key, limit in [('source_lag',45), ('hot_age',240), ('retained_age',240), ('hot_bytes',2*1024**3)]:
            check(bounded(sample.get(key), limit, strict=True), 'strict_'+key)
        check(sample.get('gaps') == [], 'runtime_gaps')
    check(row.get('source_receipt', {}).get('source_frames_released') == frames
          and row.get('source_receipt', {}).get('tape', {}).get('valid') is True, 'full_consumed_input')
    if not shape:
        check(len(row.get('candidate_checks', [])) > 1, 'original_candidate_schedule')
        check(row.get('common_control', {}).get('urgent_acks', 0) >= 10
              and row.get('common_control', {}).get('urgent_errors') == [], 'original_urgent_ack_schedule')
        check(sum(a['records'] for a in row.get('archives', [])) > 0
              and counters.get('archived_records', 0) > 0 and counters.get('compacted_records', 0) > 0,
              'native_archive_retirement')
    if shape == 'run379':
        check(counters.get('pump.run379_control_probe') == 25 and row.get('archived_before_finish') is True,
              'run379_control_and_durable_progress')
        check(row.get('live_shape_candidate_records') == 160, 'run379_native_fresh_candidate')
        check(len(setup.get('seed_sha256', [])) == 100, 'run379_full_100_seed_frames')
    if shape in ('run373', 'run380'):
        scope = 'program:pumpswap' if shape == 'run373' else 'program:meteora'
        check(row.get('coverage', {}).get(scope) is True, 'native_full_shape_coverage')
    return sorted(set(failures))


def observer_sample_errors(row):
    failures = []
    if row.get('observer_errors') != []:
        failures.append('observer_errors')
    landmarks = row.get('qualification_snapshots', [])
    if [r.get('frame') for r in landmarks] != [800,1400] or any(type(r.get('eligible')) is not bool for r in landmarks):
        failures.append('fixed_qualification_landmarks')
    if row.get('member') != 'recovery-1':
        if row.get('observer_samples') != []:
            failures.append('unapproved_lifecycle_sampling')
        return failures
    samples = row.get('observer_samples', [])
    advancing = []
    prior = -1
    for sample in samples:
        try:
            frames = sample['source_frames']
            require(type(frames) is int and frames >= prior, 'observer_source_regressed')
            require(sample['active_pins'] == sample['unresolved_gaps'] == 0, 'observer_pin_gap')
            observed = sample['lifecycle_observation']
            require(sample['lifecycle_revision'] == 'joint-eligible-hot-archive-retirement-v2'
                    and type(observed['source_frames']) is int and observed['source_frames'] >= frames, 'lifecycle_snapshot_identity')
            require(number(sample['observer_ms']), 'nonfinite_observer_wall_cost')
            for scope in SCOPES:
                for key in ('hot','archived_pending','oldest_age'):
                    require(number(sample['scopes'][scope][key]), 'invalid_debt')
                require(sample['scopes'][scope]['oldest_age'] < 240, 'strict_retained_age')
                require(number(observed['oldest_hot_slot_age'][scope])
                        and observed['oldest_hot_slot_age'][scope] < 240, 'strict_hot_age')
                require(number(observed['archive_eligible_hot'][scope]), 'invalid_eligible_debt')
                for stage in ('ingested','archived','retired','continuity'):
                    value = observed['service'][scope][stage]
                    require(type(value) is int and value >= 0, 'invalid_service_counter')
            if frames > prior:
                advancing.append(sample)
            prior = frames
        except (KeyError, TypeError, ValueError) as exc:
            failures.append('invalid_lifecycle_sample:'+str(exc))
    if len(advancing) < 30:
        failures.append('insufficient_advancing_lifecycle_samples')
    for scope in SCOPES:
        service = [s['lifecycle_observation']['service'][scope] for s in advancing]
        for stage in ('ingested','archived','retired','continuity'):
            if any(b[stage] < a[stage] for a, b in zip(service,service[1:])):
                failures.append('service_counter_regressed:'+scope+':'+stage)
        if service and service[-1]['ingested'] > service[0]['ingested']:
            if any(service[-1][stage] <= service[0][stage] for stage in ('archived','retired')):
                failures.append('committed_lifecycle_starved:'+scope)
    if len(advancing) >= 2:
        elapsed = advancing[-1]['monotonic'] - advancing[0]['monotonic']
        cost = sum(s['observer_ms'] for s in advancing[1:])
        if not number(elapsed) or elapsed <= 0 or cost/(1000*elapsed) > .01:
            failures.append('legacy_short_reader_fraction_above_1_percent')
    else:
        failures.append('legacy_short_reader_fraction_missing')
    # The original pure assessment must be retained; burst/cohort performance
    # subresults are C diagnostics and do not invalidate A/B capacity here.
    if type(row.get('original_stress_assessment')) is not dict:
        failures.append('original_pure_assessment_missing')
    return sorted(set(failures))


def observer_arithmetic(pairs):
    require(type(pairs) is list and len(pairs) == 3, 'three_complete_valid_pairs_required')
    numerator = denominator = 0
    seen = set()
    for pair in pairs:
        require(set(pair) == {'pair_id','baseline_ns','observed_ns','valid','same_workload_hash'}, 'observer_pair_schema')
        require(type(pair['pair_id']) is str and pair['pair_id'] and pair['pair_id'] not in seen, 'duplicate_pair')
        seen.add(pair['pair_id'])
        baseline, observed = pair['baseline_ns'], pair['observed_ns']
        require(type(baseline) is int and type(observed) is int and baseline > 0 and observed >= baseline
                and pair['valid'] is True and pair['same_workload_hash'] == 'production-equivalent-full-cohort-v3',
                'invalid_observer_pair')
        numerator += observed-baseline
        denominator += baseline
    require(numerator*100 < denominator, 'observer_overhead_must_be_strictly_below_1_percent')
    return dict(numerator_ns=numerator, denominator_ns=denominator, ratio=numerator/denominator,
                strict_integer_inequality=True)


def native_overload_errors(row):
    errors = []
    proof = row.get('native_restart', {})
    before, after = proof.get('before', {}), proof.get('after', {})
    reason = proof.get('native_failure') or ''
    frames = proof.get('native_failure_frames', [])
    # Known native refusal classes, with actual native traceback ancestry.
    native_files = ('solana_maintenance_runtime.py','solana_maintenance_arbiter.py',
                    'solana_maintenance_state.py','solana_owner_admission.py','solana_evidence_service.py')
    native_refusal = reason.startswith('EvidenceUnavailable:') and any(r.get('file') in native_files for r in frames)
    if not native_refusal or not any(token in reason for token in ('deadline','capacity','stalled','clock','generation','admission','recovery','lease')):
        errors.append('native_threshold_triggered_refusal_missing')
    if proof.get('external_stop_is_native_proof') is not False:
        errors.append('wrapper_stop_is_not_native_proof')
    if not proof.get('old_generation') or proof.get('new_generation') == proof.get('old_generation'):
        errors.append('native_restart_generation_missing')
    if proof.get('source_frames_released_after_restart') != 0:
        errors.append('source_released_during_restart_witness')
    for key in ('progress', 'episodes', 'records_digest', 'record_count', 'floors'):
        if key not in before or before[key] != after.get(key):
            errors.append('restart_ledger_episode_or_work_changed:'+key)
    if before.get('protected', {}).get('integrity') != ['ok'] or after.get('protected', {}).get('integrity') != ['ok']:
        errors.append('restart_integrity')
    for key in ('interests','service_interests','account_interest_floors','stream_receipts',
                'interest_checkpoints','interest_owners','consumers'):
        if key not in before.get('protected', {}) or before['protected'][key] != after.get('protected', {}).get(key):
            errors.append('protected_evidence_or_receipts_changed:'+key)
    for key in ('archived_records','compacted_records','stream_accepted_messages'):
        if before.get('counters', {}).get(key) != after.get('counters', {}).get(key):
            errors.append('uncommitted_or_duplicate_credit:'+key)
    original_gaps = {tuple(r) for r in before.get('gaps', [])}
    new_gaps = {tuple(r) for r in after.get('gaps', [])}
    if not original_gaps.issubset(new_gaps) or not any(r[-1] == 'service_restart' for r in new_gaps):
        errors.append('native_restart_gap_not_preserved')
    if {r.get('scope') for r in proof.get('stale_refusals', [])} != set(SCOPES):
        errors.append('native_stale_authority_refusal_missing')
    ipc = row.get('ipc', {})
    if ipc.get('stream.received_messages') != ipc.get('stream.commit_messages'):
        errors.append('lost_admitted_source_work')
    if not proof.get('preserved_original_inventory_sha256'):
        errors.append('pre_restart_raw_copy_missing')
    admission = before.get('health', {}).get('owner_scheduler', {}).get('owner_admission', {})
    if before.get('health', {}).get('phase') != 'FAILED' or admission.get('failed') is not True:
        errors.append('native_failed_admission_state_missing')
    if not any(event.get('native_refusal') is True and event.get('maintenance_error_type') == 'EvidenceUnavailable'
               for event in admission.get('events', [])):
        errors.append('native_refusal_event_missing')
    return sorted(set(errors))


def stress_member_result(row):
    errors = []
    # Original strict outcomes are rechecked from raw dictionaries under exact S
    # source by verify_stress_native; these structural results never invent a pass.
    perf = row.get('workload_valid') is True and row.get('observation_valid') is True
    if row.get('member') == 'recovery-1':
        perf = perf and row.get('observer_assessment', {}).get('passed') is True
    for key, limit in [('lag_peak',45), ('oldest_hot_age_peak',240), ('oldest_retained_age_peak',240), ('hot_peak',2*1024**3)]:
        if not bounded(row.get(key), limit, strict=True):
            errors.append('strict_'+key)
    if row.get('integrity') != ['ok'] or row.get('provider_attempts') != []:
        errors.append('native_integrity_or_provider')
    ipc = row.get('ipc', {})
    for key, limit in [('stream.outstanding_frames_peak',64), ('stream.dispatch_bytes_peak',96*1024**2),
                        ('stream.commit_batch_messages_peak',8), ('stream.commit_batch_bytes_peak',16*1024**2)]:
        if not bounded(ipc.get(key), limit):
            errors.append('native_'+key)
    if ipc.get('stream.received_messages') != ipc.get('stream.commit_messages'):
        errors.append('native_admitted_drain')
    if not bounded(row.get('owner', {}).get('queue_peak'),64):
        errors.append('native_owner_queue')
    if not perf:
        errors += native_overload_errors(row)
    return dict(diagnostic_performance_pass=perf, diagnostic_outcome='PASS' if perf else 'FAILED_DIAGNOSTIC',
                mandatory_native_safety_pass=not errors, native_safety_errors=sorted(set(errors)),
                outcome=('FULL_PROFILE_SAFETY_PASS' if perf else 'DIAGNOSTIC_OVERLOAD_WITH_NATIVE_FAIL_CLOSED_PROOF')
                        if not errors else 'NATIVE_SAFETY_FAILURE', capacity_credit=False)


def verify_source(receipt, row, declaration):
    frames = row['frames']
    require(receipt['source_frames_released'] == frames and receipt['retiming_calls'] == 0
            and receipt['immutable_semantic_wall_epoch'] == 1800000000
            and receipt['immutable_semantic_monotonic_epoch'] == 100, 'raw_source_clock_identity')
    require(receipt['declaration_sha256'] == row['declaration_sha256'], 'raw_source_declaration')
    anchor = receipt['first_release_real_monotonic_ns']
    require(type(anchor) is int and anchor > 0, 'source_release_anchor_missing')
    for sample in receipt['clock_samples']:
        elapsed = (sample['real_monotonic_ns']-anchor)/1e9
        require(sample['anchor_real_monotonic_ns'] == anchor and elapsed >= 0
                and abs(sample['wall']-(1800000000+elapsed)) < .01
                and abs(sample['monotonic']-(100+elapsed)) < .01, 'semantic_clock_rebased_or_unprojected')
    if not row.get('shape'):
        expected = next(m for m in declaration['tape_binding']['members'] if m['id'] == row['member'])
        require(all(receipt['tape'].get(k) == v for k,v in expected.items() if k != 'id'), 'consumed_prefix_hash_changed')
    if row.get('kind') != 'C':
        release = receipt['raw_release_hashes']
        require(len(release) == frames, 'raw_source_release_inventory_missing')
        cadence = row['cadence_us']*1000
        for n, event in enumerate(release):
            require(event['number'] == n and event['released_real_monotonic_ns'] >= anchor+n*cadence,
                    'source_cadence_or_order_changed')


def verify_native_db(root, row):
    # Original absolute runtime path is only an identity; map to the sealed
    # member folder's actual DB for independent verification.
    dbpath = relative(root, 'before-restart-native-state/db' if row.get('kind') == 'C' else 'd/db')
    require(dbpath.is_file(), 'preserved_native_DB_missing')
    with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        require([r[0] for r in db.execute('PRAGMA integrity_check')] == ['ok'], 'raw_DB_integrity')
        counters = dict(db.execute('SELECT key,value FROM counters'))
        health = {k: json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
        require(counters == row['counters'] and health.get('ipc', {}) == row['ipc'], 'raw_native_counters_or_drain_mismatch')
        from meme_machine.solana_evidence_plane import decode_body, digest
        for identity, body, expected in db.execute('SELECT identity,body,hash FROM records WHERE body IS NOT NULL'):
            require(digest(decode_body(body, db)) == expected, 'raw_native_record_body_hash')
    actual_archives = sorted((Path(root)/'d').glob('*.archive/*.gz'))
    records = 0
    for path in actual_archives:
        require(file_sha(path) == path.name.split('.')[0], 'raw_archive_encoded_hash')
        with gzip.open(path, 'rt') as source:
            for line in source:
                entry = json.loads(line)
                require(sha(canonical(entry['body'])) == entry['hash'] and entry['lineage'], 'raw_archive_body_or_lineage')
                records += 1
    require(records == sum(a['records'] for a in row['archives']), 'raw_archive_inventory_missing')
    return dict(integrity='ok', archive_records=records)


def verify_restart_raw(folder, row):
    """Recheck preserved native before/after state; no restart is performed here."""
    require(file_sha(Path(folder)/'BEFORE_RESTART_INVENTORY.json') ==
            row['native_restart']['preserved_original_inventory_sha256'], 'restart_preservation_receipt_hash')
    require(read(Path(folder)/'BEFORE_RESTART_INVENTORY.json')['artifacts'] ==
            inventory(Path(folder)/'before-restart-native-state'), 'restart_original_copy_changed')
    for phase, name in [('before','before-restart-native-state/db'),('after','d/db')]:
        proof = row['native_restart'][phase]
        require(set(proof['protected']) == {'interests','service_interests','account_interest_floors',
                'stream_receipts','interest_checkpoints','interest_owners','consumers','integrity'},
                'raw_restart_protected_table_inventory')
        with closing(sqlite3.connect(relative(folder,name).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            for table, expected in proof['protected'].items():
                actual = [r[0] for r in db.execute('PRAGMA integrity_check')] if table == 'integrity' else [
                    list(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1,2')]
                require(actual == expected, 'raw_restart_protected_table_changed:'+table)
            for key, query in [('progress','SELECT * FROM maintenance_progress ORDER BY scope,side'),
                               ('episodes','SELECT * FROM maintenance_episodes ORDER BY scope,side')]:
                require([list(r) for r in db.execute(query)] == proof[key], 'raw_restart_native_ledger_changed')
            h = __import__('hashlib').sha256(); count = 0
            for record in db.execute('SELECT identity,hash,scope,slot,archive,market_time,first_seen FROM records ORDER BY identity'):
                h.update(canonical(list(record))+b'\n');count += 1
            require(h.hexdigest() == proof['records_digest'] and count == proof['record_count'], 'raw_restart_records_changed')
            counters = dict(db.execute('SELECT key,value FROM counters'))
            require(all(counters.get(k) == v for k,v in proof['counters'].items()), 'raw_restart_committed_counters_changed')
            floors = dict(db.execute("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'"))
            require(floors == proof['floors'], 'raw_restart_floors_changed')
    return dict(native_before_after_rechecked=True,source_frames_released=0)


def verify_admissions(admissions, declaration, declaration_sha256, allocation, *, evidence_files=None):
    from attest import admission_errors, constraint_identity
    require(admissions, 'child_thread_admission_missing')
    constraints = None
    phases = {}
    for row in admissions:
        require(row['errors'] == [] and row['declaration_sha256'] == declaration_sha256,
                'child_thread_admission_failure')
        snapshot = row['snapshot']
        require(not admission_errors(snapshot, allocation, declaration['storage_bounds'],
            declaration['environment']['runtime_dependency_identities'], evidence_files=evidence_files),
            'raw_child_thread_envelope_invalid')
        if row.get('storage_reserve') is not None:
            from attest import reserve_storage
            require(row['storage_reserve'] == reserve_storage(snapshot,declaration['storage_bounds'],
                    member=row['storage_reserve']['member']), 'raw_member_storage_reserve_changed')
        require(not row['phase'].startswith('before-member-') or row.get('storage_reserve') is not None,
                'before_member_storage_reserve_missing')
        identity = sha(canonical(constraint_identity(snapshot)))
        require(constraints is None or identity == constraints, 'child_thread_resource_constraints_changed')
        constraints = identity
        process = next((p for p in snapshot['processes'] if p['pid'] == row['pid']), None)
        require(process is not None and any(t['tid'] == row['tid'] for t in process['threads']),
                'child_thread_identity_missing_from_raw_inventory')
        phases.setdefault(row['pid'],set()).add(row['phase'])
    require(all({'initialized','terminated'}.issubset(p) for p in phases.values()), 'child_admission_teardown_missing')
    starts = [(r['pid'], r['tid']) for r in admissions if r['phase'] == 'thread-start']
    ends = [(r['pid'], r['tid']) for r in admissions if r['phase'] == 'thread-stop']
    require(len(starts) == len(set(starts)) and sorted(starts) == sorted(ends), 'thread_lifecycle_continuity_missing')
    return dict(admission_receipts=len(admissions),constraints_sha256=constraints,pids=sorted(phases))


def verify_origins(folder, declaration, declaration_sha256, allocation, *, evidence_files=None, expected_roles=None):
    receipts = [read(p) for p in Path(folder).glob('ORIGIN-*.json')]
    require(receipts, 'native_process_origins_missing')
    runtime = declaration['environment']['runtime_dependency_identities']
    native = contract_file('candidate_integrity_before.json')['tracked_files']
    expected = dict(runtime['stdlib_files'])
    expected.update(runtime['dependencies']['websockets']['files'])
    pids = {}
    for row in receipts:
        require(row['candidate_sha'] == S and row['assembly_digest'] == ASSEMBLY
                and row['declaration_sha256'] == declaration_sha256
                and row['infrastructure_digest'] == declaration['infrastructure']['digest']
                and row['environment_sha256'] == declaration['environment_sha256']
                and row['isolated'] == 1 and row['no_site'] == 1 and row['no_bytecode_writes'] is True
                and row['provider_attempts'] == [], 'origin_identity_or_provider')
        require(row['net_namespace'] != declaration['executor']['admission_net_namespace'], 'native_network_namespace_not_isolated')
        pids.setdefault(row['pid'], set()).add(row['phase'])
        for module, origin in row['modules'].items():
            name = origin['origin']
            checksum = expected.get(name)
            if '/source/' in name:
                checksum = native.get(name.split('/source/',1)[1], {}).get('sha256')
            if name.endswith('/harness/'+Path(name).name):
                checksum = declaration['infrastructure']['files'].get(Path(name).name, {}).get('sha256')
            require(checksum == origin['sha256'], 'foreign_native_or_harness_origin:'+module)
    require(all({'initialized','terminated'}.issubset(phases) for phases in pids.values()), 'missing_child_teardown')
    roles = [r['role'] for r in receipts if r['phase'] == 'initialized']
    expected_roles = expected_roles or {'member':1,'decoder-spawn':2,'resource-tracker':1}
    require({role:roles.count(role) for role in set(roles)} == expected_roles, 'native_worker_count_or_child_coverage')
    admissions = [read(p) for p in Path(folder).glob('ADMISSION-*.json')]
    verified = verify_admissions(admissions,declaration,declaration_sha256,allocation,evidence_files=evidence_files)
    require(set(verified['pids']) == set(pids), 'child_origin_and_resource_identity_mismatch')
    return dict(pids=sorted(pids), roles=roles, **{k:v for k,v in verified.items() if k!='pids'})


def verify_resource_timeline(folder, declaration, allocation, *, evidence_files=None):
    from attest import admission_errors, constraint_identity
    rows = [read(p) for p in sorted(Path(folder).glob('RESOURCE-*.json'))]
    require(rows and rows[0]['boundary'] == 'admission' and rows[-1]['boundary'] == 'teardown', 'resource_timeline_boundaries')
    previous = '0'*64
    constraints = None
    previous_time = None
    for n, row in enumerate(rows,1):
        raw = dict(row); digest = raw.pop('sha256')
        require(row['ordinal'] == n and row['previous'] == previous and sha(canonical(raw)) == digest, 'resource_timeline_hash_chain')
        snapshot = row['snapshot']
        require(row['errors'] == [] and not admission_errors(snapshot, allocation, declaration['storage_bounds'],
                    declaration['environment']['runtime_dependency_identities'],evidence_files=evidence_files), 'raw_resource_admission')
        current = sha(canonical(constraint_identity(snapshot)))
        require(row['constraints_sha256'] == current and (constraints is None or constraints == current), 'resource_continuity_changed')
        now = snapshot['real_monotonic_ns']
        require(previous_time is None or 0 < now-previous_time <= 2*10**9, 'resource_monitor_gap')
        previous_time, previous, constraints = now, digest, current
    return dict(samples=len(rows), constraints_sha256=constraints)


def verify_trial(folder, declaration, *, declaration_sha256, allocation, evidence_files=None):
    folder = Path(folder)
    verify_inventory(folder)
    result = read(folder/'TRIAL_RESULT.json')
    require(result['declaration_sha256'] == declaration_sha256 and result['kind'] == declaration['class_id']
            and result['trial_id'] in {r['trial_id'] for r in declaration['trials']}, 'fresh_exact_trial_binding')
    expected = [('run373-full-v3',14),('run379-full-v3',120),('run380-full-v3',240)] + list(COHORT) if result['kind'] == 'A' else list(COHORT)
    require([(r['member'],r['frames']) for r in result['members']] == expected, 'complete_native_cohort_required')
    require(type(result['start_perf_ns']) is int and type(result['end_perf_ns']) is int
            and result['end_perf_ns'] > result['start_perf_ns']
            and result['elapsed_ns'] == result['end_perf_ns']-result['start_perf_ns'], 'raw_trial_timing')
    require(result['mode'] in ('baseline','observed','stress') and result['valid'] is True, 'invalid_trial_retained')
    cohort = read(folder/'COHORT_RESULT.json')
    require(all(result[k] == v for k,v in cohort.items()), 'native_trial_result_contradicts_raw_cohort')
    with native_verifier_context(declaration):
        for index, member in enumerate(result['members'],1):
            verify_member(folder/f'm{index}', member, result, declaration, declaration_sha256, allocation,
                          evidence_files=evidence_files)
    verify_origins(folder, declaration, declaration_sha256, allocation,
                   evidence_files=evidence_files,expected_roles={'trial':1})
    resources = verify_resource_timeline(folder/'resources', declaration, allocation,evidence_files=evidence_files)
    return dict(version='v3-native-trial-verification', native_verified=True, class_id=result['kind'],
                trial_id=result['trial_id'], mode=result['mode'], elapsed_ns=result['elapsed_ns'],
                declaration_sha256=declaration_sha256, environment_sha256=declaration['environment_sha256'],
                production_workload_sha256=declaration['production_workload_sha256'],
                source_frames=[r['frames'] for r in result['members']], resources=resources,
                raw_inventory_sha256=file_sha(folder/'RAW_INVENTORY.json'), passed=True,
                candidate_sha=S, candidate_tree=T, stage_e='RED', stage_f='NOT STARTED')


def verify_member(member_folder, member, result, declaration, declaration_sha256, allocation, *, evidence_files=None):
        row = read(member_folder/'MEMBER_RESULT.json')
        require(row['declaration_sha256'] == declaration_sha256 and row['mode'] == result['mode']
                and row['member'] == member['member'] and row['frames'] == member['frames']
                and file_sha(member_folder/'MEMBER_RESULT.json') == member['member_result_sha256'], 'member_binding')
        if result['kind'] == 'C':
            require(stress_member_result(row)['mandatory_native_safety_pass'], 'C_native_safety_failure')
            verify_stress_native(row, declaration)
            verify_restart_raw(member_folder,row)
        else:
            require(not production_member_errors(row), 'A_B_raw_native_capacity_invalid')
            if result['mode'] == 'observed':
                require(not observer_sample_errors(row), 'B_raw_observation_invalid')
        verify_source(read(member_folder/'SOURCE_RECEIPT.json'), row, declaration)
        verify_native_db(member_folder, row)
        verify_origins(member_folder, declaration, declaration_sha256, allocation,evidence_files=evidence_files)


@contextmanager
def native_verifier_context(declaration):
    import sys
    source = Path(declaration['paths']['assembly'])/'source'
    from binding import verify_assembly
    manifest = verify_assembly(declaration['paths']['assembly'])
    original = list(sys.path)
    sys.path.insert(0,str(source))
    try:
        yield
        for module in list(sys.modules.values()):
            name = getattr(module,'__name__','')
            if not name.startswith(('meme_machine','certification','tests.')):
                continue
            origin = Path(getattr(module,'__file__','')).resolve()
            require(origin.is_relative_to(source), 'foreign_native_verifier_module')
            rel = origin.relative_to(source).as_posix()
            require(file_sha(origin) == manifest['files'].get(rel,{}).get('sha256'), 'native_verifier_source_hash')
    finally:
        sys.path[:] = original


def verify_stress_native(row, declaration):
    """Only pure exact-S verifier/assessment functions; never their run functions."""
    import sys
    source = Path(declaration['paths']['assembly'])/'source'
    require(str(source) in sys.path, 'isolated_native_stress_verifier_origin_required')
    from certification import combined_observer, lifecycle_capacity
    from certification import cleanup_recovery
    cleanup_recovery.PLAN_PATH = source/'certification/stagee24_qualification_plan.json'
    # combined verified has a fixed 2223 frame domain; the exact recovery member
    # uses the original external full-cohort common_valid predicate at 4445.
    from stress_predicates import common_valid
    diagnostic = common_valid(row, row['frames']) and combined_observer.observation_verified(row)
    if row['member'] != 'recovery-1':
        diagnostic = diagnostic and combined_observer.verified(row, S)
    else:
        diagnostic = diagnostic and lifecycle_capacity.assessment(row['observer_samples'], row['observer_errors'])['passed']
    require(bool(diagnostic) == row['diagnostic_performance_pass'], 'original_stress_diagnostic_outcome_changed')
    return diagnostic


def verify_observer(trials, declaration, capacity):
    require(capacity.get('native_verified') is True and capacity.get('passed') is True
            and capacity.get('class_id') == 'A' and capacity.get('candidate_sha') == S
            and capacity.get('candidate_tree') == T
            and capacity.get('environment_sha256') == declaration['environment_sha256']
            and capacity.get('production_workload_sha256') == declaration['production_workload_sha256'], 'fresh_A_pass_required')
    require(len(trials) == 6 and [r['mode'] for r in trials] == list(MODES), 'three_pair_order_no_replacements')
    require([r['trial_id'] for r in trials] == [r['trial_id'] for r in declaration['trials']], 'fresh_trial_ledger_binding')
    pairs = []
    for i in range(3):
        pair = trials[2*i:2*i+2]
        baseline = next(r for r in pair if r['mode'] == 'baseline')
        observed = next(r for r in pair if r['mode'] == 'observed')
        require(all(r['passed'] is True and r['native_verified'] is True
                    and r['environment_sha256'] == declaration['environment_sha256']
                    and r['production_workload_sha256'] == declaration['production_workload_sha256'] for r in pair),
                'invalid_or_different_raw_pair')
        pairs.append(dict(pair_id=declaration['campaign']+f'-p{i+1}', baseline_ns=baseline['elapsed_ns'],
                          observed_ns=observed['elapsed_ns'], valid=True,
                          same_workload_hash='production-equivalent-full-cohort-v3'))
    return dict(raw_pairs=pairs, **observer_arithmetic(pairs), native_verified=True,
                outcome='OBSERVER_V3: VALID_THREE_PAIRS', historical_v2_acceptance_credit=False,
                candidate_sha=S, candidate_tree=T, stage_e='RED', stage_f='NOT STARTED')


def gate_status():
    return {name:'NOT_RUN' for name in contract_file('contract.json')['required_gates']}
