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
                  read, relative, require, sha, workload, RESOURCE_SAMPLING, RESOURCE_TOLERANCE_NS, CLOCK_PAIR_TOLERANCE_NS)
from preserve import verify_inventory, inventory

SCOPES = ('program:meteora', 'program:pump', 'program:pumpswap')
OVERLOAD = 'DIAGNOSTIC_OVERLOAD_WITH_NATIVE_FAIL_CLOSED_PROOF'
# Monitor cadence is .25 s. Two seconds is the maximum permitted collection
# gap and boundary/identity sampling uncertainty; it is never elapsed credit.


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
    if not proof.get('old_generation') or not proof.get('new_generation') or proof.get('new_generation') == proof.get('old_generation'):
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
        count = before.get('counters', {}).get(key)
        if type(count) is not int or count < 0 or count != after.get('counters', {}).get(key):
            errors.append('uncommitted_or_duplicate_credit:'+key)
    original_gaps = {tuple(r) for r in before.get('gaps', [])}
    new_gaps = {tuple(r) for r in after.get('gaps', [])}
    if not original_gaps.issubset(new_gaps) or not any(r[-1] == 'service_restart' for r in new_gaps):
        errors.append('native_restart_gap_not_preserved')
    if {r.get('scope') for r in proof.get('stale_refusals', [])} != set(SCOPES) or any(
            not r.get('reason') for r in proof.get('stale_refusals', [])):
        errors.append('native_stale_authority_refusal_missing')
    ipc = row.get('ipc', {})
    received, committed = ipc.get('stream.received_messages'), ipc.get('stream.commit_messages')
    if type(received) is not int or received <= 0 or type(committed) is not int or received != committed:
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
    if row.get('candidate_sha') != S or row.get('kind') != 'C':
        errors.append('native_candidate_class')
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
    received, committed = ipc.get('stream.received_messages'), ipc.get('stream.commit_messages')
    if type(received) is not int or received <= 0 or type(committed) is not int or received != committed:
        errors.append('native_admitted_drain')
    if not bounded(row.get('owner', {}).get('queue_peak'),64):
        errors.append('native_owner_queue')
    if not perf:
        errors += native_overload_errors(row)
    return dict(diagnostic_performance_pass=perf, diagnostic_outcome='PASS' if perf else 'FAILED_DIAGNOSTIC',
                mandatory_native_safety_pass=not errors, native_safety_errors=sorted(set(errors)),
                outcome=('FULL_PROFILE_SAFETY_PASS' if perf else 'DIAGNOSTIC_OVERLOAD_WITH_NATIVE_FAIL_CLOSED_PROOF')
                        if not errors else 'NATIVE_SAFETY_FAILURE', capacity_credit=False)


def verify_source(receipt, row, declaration, *, allow_incomplete=False):
    frames = row['frames']
    released = receipt['source_frames_released']
    require(type(released) is int and 0 < released <= frames
            and (released == frames or allow_incomplete and row['kind'] == 'C') and receipt['retiming_calls'] == 0
            and receipt['immutable_semantic_wall_epoch'] == 1800000000
            and receipt['immutable_semantic_monotonic_epoch'] == 100, 'raw_source_clock_identity')
    require(receipt['declaration_sha256'] == row['declaration_sha256'], 'raw_source_declaration')
    anchor = receipt['first_release_real_monotonic_ns']
    require(type(anchor) is int and anchor > 0, 'source_release_anchor_missing')
    require(receipt['clock_samples'] and receipt['clock_samples'][0]['frames'] == 1,
            'source_clock_samples_missing')
    prior = 0
    for sample in receipt['clock_samples']:
        elapsed = (sample['real_monotonic_ns']-anchor)/1e9
        require(type(sample['frames']) is int and prior < sample['frames'] <= released
                and sample['anchor_real_monotonic_ns'] == anchor and elapsed >= 0
                and abs(sample['wall']-(1800000000+elapsed)) < .01
                and abs(sample['monotonic']-(100+elapsed)) < .01, 'semantic_clock_rebased_or_unprojected')
        prior = sample['frames']
    if not row.get('shape'):
        expected = next(m for m in declaration['tape_binding']['members'] if m['id'] == row['member'])
        if released == frames:
            require(receipt['tape']['valid'] is True and all(receipt['tape'].get(k) == v for k,v in expected.items() if k != 'id'),
                    'consumed_prefix_hash_changed')
        else:
            verify_incomplete_prefix(receipt, declaration, expected)
    release = receipt['raw_release_hashes']
    require(len(release) == released, 'raw_source_release_inventory_missing')
    cadence = row.get('cadence_us',270000)*1000
    previous = anchor-1
    for n, event in enumerate(release):
        now = event['released_real_monotonic_ns']
        require(event['number'] == n and type(now) is int and now > previous and now >= anchor+n*cadence,
                'source_cadence_or_order_changed')
        previous = now
    require(receipt['last_release_real_monotonic_ns'] == previous, 'last_source_release_boundary_changed')
    return dict(first_release_ns=anchor, last_release_ns=previous, frames=released)


def verify_incomplete_prefix(receipt, declaration, expected):
    """Verify the consumed prefix against the unchanged authorized input bytes.

    A partial prefix is permitted only at a proved C overload terminal. This
    read-only path neither feeds a native source nor credits unread frames.
    """
    from tape import Reader
    binding, paths = declaration['tape_binding'], declaration['paths']
    require(file_sha(paths['frame_inventory']) == binding['frame_inventory_sha256'], 'partial_frame_inventory_changed')
    require(Path(paths['tape']).stat().st_size == binding['physical_bytes']
            and file_sha(paths['tape']) == binding['physical_sha256'], 'partial_original_input_changed')
    frames = read(paths['frame_inventory'])
    reader = Reader(paths['tape'], expected)
    try:
        for n in range(receipt['source_frames_released']):
            raw, actual = reader.next()
            event = receipt['raw_release_hashes'][n]
            require(actual == frames[n] and event['number'] == n
                    and event['sha256'] == sha(raw) and event['bytes'] == len(raw), 'partial_consumed_frame_changed')
        actual_receipt = reader.close(strict=False)
    finally:
        if not reader.file.closed:
            reader.file.close()
    require(actual_receipt == receipt['tape'] and actual_receipt['immutable_file_unchanged'] is True,
            'partial_consumed_prefix_changed')


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
            require(counters == proof['counters'], 'raw_restart_committed_counters_changed')
            health = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
            require(health == proof['health'], 'raw_restart_native_refusal_health_changed')
            generation = health.get('storage_maintenance',{}).get('maintenance_arbiter',{}).get('generation')
            require(generation == row['native_restart']['old_generation' if phase == 'before' else 'new_generation'],
                    'raw_restart_generation_changed')
            gaps = [list(r) for r in db.execute('SELECT scope,lo,hi,reason FROM gaps WHERE repaired IS NULL ORDER BY scope,lo')]
            require(gaps == proof['gaps'], 'raw_restart_native_gaps_changed')
            floors = dict(db.execute("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'"))
            require(floors == proof['floors'], 'raw_restart_floors_changed')
            if phase == 'after':
                # Reuse only the exact immutable native read-only health predicate.
                # No runtime/service is started, and no command is sent.
                from types import SimpleNamespace
                from meme_machine.solana_evidence_health import evidence_health
                require(health.get('phase') == 'OFF' and number(proof['wall']), 'restart_final_native_teardown_missing')
                reader = SimpleNamespace(db=db,path=relative(folder,name))
                for refusal in row['native_restart']['stale_refusals']:
                    result = evidence_health(reader,refusal['scope'],proof['wall'])
                    require(result['usable'] is False and result['reason'] == refusal['reason'],
                            'raw_restart_stale_authority_refusal_changed')
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
    lifetimes = []
    for pid in sorted(pids):
        origins = [r for r in receipts if r['pid'] == pid]
        require(len(origins) == 2 and {r['phase'] for r in origins} == {'initialized','terminated'},
                'duplicate_or_unknown_process_origin_phase')
        first = next(r for r in origins if r['phase'] == 'initialized')
        last = next(r for r in origins if r['phase'] == 'terminated')
        require(type(first['real_monotonic_ns']) is int and type(last['real_monotonic_ns']) is int
                and first['real_monotonic_ns'] < last['real_monotonic_ns']
                and first['role'] == last['role'] and first['process_start_ticks'] == last['process_start_ticks'],
                'process_lifetime_origin_changed')
        own = [r for r in admissions if r['pid'] == pid]
        for row in own:
            process = next(p for p in row['snapshot']['processes'] if p['pid'] == pid)
            require(process['start_ticks'] == first['process_start_ticks'], 'process_start_identity_changed')
            require(type(row['real_monotonic_ns']) is int
                    and 0 <= row['real_monotonic_ns']-row['snapshot']['real_monotonic_ns'] <= RESOURCE_TOLERANCE_NS
                    and row['role'] == first['role'],
                    'admission_snapshot_time_unbound')
        require(sum(r['phase'] == 'initialized' for r in own) == sum(r['phase'] == 'terminated' for r in own) == 1,
                'duplicate_process_admission_lifecycle')
        initialized = next(r for r in own if r['phase'] == 'initialized')
        terminated = next(r for r in own if r['phase'] == 'terminated')
        require(initialized['real_monotonic_ns'] <= first['real_monotonic_ns']
                < terminated['real_monotonic_ns'] <= last['real_monotonic_ns'], 'process_admission_lifetime_order')
        require(initialized['tid'] == terminated['tid'] == pid and all(
                    initialized['snapshot']['real_monotonic_ns'] <= r['snapshot']['real_monotonic_ns']
                    <= r['real_monotonic_ns'] <= last['real_monotonic_ns'] for r in own),
                'admission_outside_required_process_lifetime')
        lifetimes.append(dict(pid=pid, start_ticks=first['process_start_ticks'], role=first['role'],
                              start_ns=initialized['snapshot']['real_monotonic_ns'], end_ns=last['real_monotonic_ns']))
        for row in own:
            if row['phase'] == 'thread-start':
                stop = next(r for r in own if r['tid'] == row['tid'] and r['phase'] == 'thread-stop')
                require(row['real_monotonic_ns'] < stop['real_monotonic_ns'], 'thread_lifetime_order')
                lifetimes.append(dict(pid=pid, tid=row['tid'], start_ticks=first['process_start_ticks'], role='thread',
                                      start_ns=row['snapshot']['real_monotonic_ns'], end_ns=stop['real_monotonic_ns']))
    return dict(pids=sorted(pids), roles=roles, lifetimes=lifetimes,
                **{k:v for k,v in verified.items() if k!='pids'})


def verify_resource_timeline(folder, declaration, allocation, *, execution_interval=None,
                             lifetimes=None, source_intervals=None, evidence_files=None):
    from attest import admission_errors, constraint_identity
    require(type(execution_interval) is dict and lifetimes and source_intervals,
            'resource_execution_interval_and_lifetimes_required')
    require(declaration.get('resource_sampling') == RESOURCE_SAMPLING, 'declared_resource_sampling_tolerance_changed')
    interval = execution_interval
    keys = ('start_real_monotonic_ns','startup_real_monotonic_ns','helpers_terminated_real_monotonic_ns',
            'end_real_monotonic_ns','start_perf_ns','end_perf_ns','start_clock_read_span_ns','end_clock_read_span_ns')
    require(all(type(interval.get(k)) is int and interval[k] >= 0 for k in keys), 'resource_interval_schema')
    start, startup, helpers, end = [interval[k] for k in keys[:4]]
    require(0 < start <= startup < helpers <= end and interval['end_perf_ns'] > interval['start_perf_ns'],
            'resource_execution_boundary_order')
    require(max(interval['start_clock_read_span_ns'],interval['end_clock_read_span_ns']) <= CLOCK_PAIR_TOLERANCE_NS
            and abs((end-start)-(interval['end_perf_ns']-interval['start_perf_ns'])) <= 2*CLOCK_PAIR_TOLERANCE_NS,
            'resource_monotonic_and_measured_clocks_unbound')
    rows = [read(p) for p in sorted(Path(folder).glob('RESOURCE-*.json'))]
    require(rows and rows[0]['boundary'] == 'admission' and rows[-1]['boundary'] == 'teardown', 'resource_timeline_boundaries')
    previous = '0'*64
    constraints = None
    previous_time = None
    for n, row in enumerate(rows,1):
        raw = dict(row); digest = raw.pop('sha256')
        require(type(row['ordinal']) is int and row['ordinal'] == n and row['previous'] == previous
                and sha(canonical(raw)) == digest, 'resource_timeline_hash_chain')
        snapshot = row['snapshot']
        require(row['errors'] == [] and not admission_errors(snapshot, allocation, declaration['storage_bounds'],
                    declaration['environment']['runtime_dependency_identities'],evidence_files=evidence_files), 'raw_resource_admission')
        current = sha(canonical(constraint_identity(snapshot)))
        require(row['constraints_sha256'] == current and (constraints is None or constraints == current), 'resource_continuity_changed')
        now = snapshot['real_monotonic_ns']
        require(type(now) is int and now > 0 and (previous_time is None or 0 < now-previous_time <= RESOURCE_TOLERANCE_NS),
                'resource_monitor_gap')
        require(row['boundary'] == ('admission' if n == 1 else 'teardown' if n == len(rows) else 'continuous'),
                'resource_timeline_phase_order')
        require(snapshot['boot_id'] == declaration['executor']['boot_id']
                and snapshot['hostname'] == declaration['executor']['hostname'], 'resource_executor_time_binding')
        previous_time, previous, constraints = now, digest, current
    admission, teardown = rows[0]['snapshot']['real_monotonic_ns'], rows[-1]['snapshot']['real_monotonic_ns']
    require(start <= admission <= startup and admission-start <= RESOURCE_TOLERANCE_NS
            and helpers <= teardown <= end and end-teardown <= RESOURCE_TOLERANCE_NS,
            'resource_timeline_does_not_cover_execution')
    require(all(startup <= s['first_release_ns'] <= s['last_release_ns'] <= helpers for s in source_intervals),
            'source_release_outside_resource_execution')
    for life in lifetimes:
        require(type(life['start_ns']) is int and type(life['end_ns']) is int
                and startup <= life['start_ns'] < life['end_ns'] <= helpers,
                'required_process_lifetime_outside_execution')
        # Every sample taken away from lifecycle edges must contain that same
        # PID/start_ticks (and TID for a thread). Short-lived helpers are covered
        # by their mandatory admission/termination snapshots and edge brackets.
        interior = [r['snapshot'] for r in rows if life['start_ns']+RESOURCE_TOLERANCE_NS
                    <= r['snapshot']['real_monotonic_ns'] <= life['end_ns']-RESOURCE_TOLERANCE_NS]
        require(life['end_ns']-life['start_ns'] <= 2*RESOURCE_TOLERANCE_NS or interior,
                'required_process_lifetime_not_sampled')
        for snapshot in interior:
            process = next((p for p in snapshot['processes'] if p['pid'] == life['pid']), None)
            require(process is not None and process['start_ticks'] == life['start_ticks']
                    and ('tid' not in life or any(t['tid'] == life['tid'] for t in process['threads'])),
                    'required_process_or_thread_missing_during_lifetime')
    return dict(samples=len(rows), constraints_sha256=constraints, first_sample_ns=admission,
                last_sample_ns=teardown, execution_interval=interval, sampling_tolerance_ns=RESOURCE_TOLERANCE_NS,
                required_lifetimes_verified=len(lifetimes))


def verify_trial(folder, declaration, *, declaration_sha256, allocation, evidence_files=None):
    folder = Path(folder)
    verify_inventory(folder)
    result = read(folder/'TRIAL_RESULT.json')
    trial = next((r for r in declaration['trials'] if r['trial_id'] == result['trial_id']), None)
    require(result['declaration_sha256'] == declaration_sha256 and result['kind'] == declaration['class_id']
            and trial is not None and result['sequence'] == trial['sequence'] and result['mode'] == trial['mode'],
            'fresh_exact_trial_binding')
    expected = [('run373-full-v3',14),('run379-full-v3',120),('run380-full-v3',240)] + list(COHORT) if result['kind'] == 'A' else list(COHORT)
    terminal = result['kind'] == 'C' and result.get('outcome') == OVERLOAD
    actual = [(r['member'],r['frames']) for r in result['members']]
    if terminal:
        require(0 < len(actual) <= len(expected) and actual == expected[:len(actual)]
                and result.get('complete_profile') is False and result.get('no_further_members') is True
                and result.get('terminal_member') == actual[-1][0]
                and result.get('diagnostic_outcome') == 'FAILED_DIAGNOSTIC'
                and result.get('capacity_credit') is False, 'C_terminal_overload_prefix_required')
    else:
        require(actual == expected and result.get('complete_profile') is True, 'complete_native_cohort_required')
    require(sorted(p.name for p in folder.glob('m[0-9]*')) == sorted(f'm{i}' for i in range(1,len(actual)+1)),
            'members_after_terminal_or_unlisted_member')
    require(type(result['start_perf_ns']) is int and type(result['end_perf_ns']) is int
            and result['end_perf_ns'] > result['start_perf_ns']
            and result['elapsed_ns'] == result['end_perf_ns']-result['start_perf_ns'], 'raw_trial_timing')
    require(result['mode'] in ('baseline','observed','stress') and result['valid'] is True, 'invalid_trial_retained')
    cohort = read(folder/'COHORT_RESULT.json')
    require(all(result[k] == v for k,v in cohort.items()), 'native_trial_result_contradicts_raw_cohort')
    persistence = read(folder/'MEASURED_PERSISTENCE_COMPLETE.json')
    require(persistence['cohort'] == cohort and persistence['all_native_helpers_terminated'] is True
            and persistence['resource_errors'] == [] and persistence['no_subtraction'] is True
            and persistence['no_double_counting'] is True, 'measured_persistence_or_helper_termination_missing')
    interval = result['execution_interval']
    require(interval['start_perf_ns'] == result['start_perf_ns'] and interval['end_perf_ns'] == result['end_perf_ns'],
            'resource_interval_measured_endpoint_mismatch')
    termination = read(folder/'PROCESS_TERMINATION.json')
    require(termination['trial_process_terminated'] is True and termination['all_native_helpers_terminated'] is True
            and termination['real_monotonic_ns'] == interval['helpers_terminated_real_monotonic_ns'],
            'resource_helper_termination_boundary_unbound')
    lifetimes, sources, classifications, child_constraints = [], [], [], []
    with native_verifier_context(declaration):
        for index, member in enumerate(result['members'],1):
            verified = verify_member(folder/f'm{index}', member, result, declaration, declaration_sha256, allocation,
                          allow_incomplete=terminal and index == len(actual), evidence_files=evidence_files)
            lifetimes.extend(verified['origins']['lifetimes']); sources.append(verified['source'])
            child_constraints.append(verified['origins']['constraints_sha256'])
            classifications.append(verified['classification'])
    if result['kind'] == 'C':
        require(all(r['outcome'] == 'FULL_PROFILE_SAFETY_PASS' for r in classifications[:-1])
                and classifications[-1]['outcome'] == (OVERLOAD if terminal else 'FULL_PROFILE_SAFETY_PASS'),
                'C_terminal_classification_contradicts_raw_members')
    trial_origins = verify_origins(folder, declaration, declaration_sha256, allocation,
                   evidence_files=evidence_files,expected_roles={'trial':1})
    lifetimes.extend(trial_origins['lifetimes'])
    child_constraints.append(trial_origins['constraints_sha256'])
    resources = verify_resource_timeline(folder/'resources', declaration, allocation,execution_interval=interval,
                                         lifetimes=lifetimes, source_intervals=sources, evidence_files=evidence_files)
    require(all(c == resources['constraints_sha256'] for c in child_constraints),
            'resource_timeline_and_child_constraints_differ')
    return dict(version='v3-native-trial-verification', native_verified=True, class_id=result['kind'],
                trial_id=result['trial_id'], mode=result['mode'], elapsed_ns=result['elapsed_ns'],
                declaration_sha256=declaration_sha256, environment_sha256=declaration['environment_sha256'],
                production_workload_sha256=declaration['production_workload_sha256'],
                source_frames=[r['frames'] for r in sources], resources=resources,
                raw_inventory_sha256=file_sha(folder/'RAW_INVENTORY.json'), passed=True,
                outcome=OVERLOAD if terminal else 'FULL_PROFILE_SAFETY_PASS' if result['kind'] == 'C' else 'COMPLETE_NATIVE_COHORT_PASS',
                diagnostic_outcome='FAILED_DIAGNOSTIC' if terminal else 'PASS', safety_only=terminal,
                complete_cohort=not terminal, capacity_credit=result['kind'] == 'A', observer_credit=False,
                candidate_sha=S, candidate_tree=T, stage_e='RED', stage_f='NOT STARTED')


def verify_member(member_folder, member, result, declaration, declaration_sha256, allocation, *,
                  allow_incomplete=False, evidence_files=None):
        row = read(member_folder/'MEMBER_RESULT.json')
        require(row['declaration_sha256'] == declaration_sha256 and row['mode'] == result['mode']
                and row['kind'] == result['kind'] and member['valid'] is True and member['exit_code'] == 0
                and row['member'] == member['member'] and row['frames'] == member['frames']
                and file_sha(member_folder/'MEMBER_RESULT.json') == member['member_result_sha256'], 'member_binding')
        if result['kind'] == 'C':
            classification = stress_member_result(row)
            require(classification['mandatory_native_safety_pass'] and all(row.get(k) == v for k,v in classification.items()),
                    'C_native_safety_failure_or_forged_classification')
            verify_stress_native(row, declaration)
            original = read(member_folder/'result.json')
            require(original.get('failure') == row.get('failure') == row['native_restart']['native_failure']
                    and original.get('failure_frames',[]) == row.get('failure_frames',[]) == row['native_restart']['native_failure_frames'],
                    'original_native_failure_ancestry_changed')
            verify_restart_raw(member_folder,row)
        else:
            classification = None
            require(not production_member_errors(row), 'A_B_raw_native_capacity_invalid')
            if result['mode'] == 'observed':
                require(not observer_sample_errors(row), 'B_raw_observation_invalid')
        receipt = read(member_folder/'SOURCE_RECEIPT.json')
        require(row['source_receipt'] == receipt, 'member_embedded_source_receipt_changed')
        source = verify_source(receipt, row, declaration, allow_incomplete=allow_incomplete)
        verify_native_db(member_folder, row)
        origins = verify_origins(member_folder, declaration, declaration_sha256, allocation,evidence_files=evidence_files)
        life = next(r for r in origins['lifetimes'] if r['role'] == 'member')
        require(life['start_ns'] <= source['first_release_ns'] <= source['last_release_ns'] <= life['end_ns']
                and all(life['start_ns'] <= r['real_monotonic_ns'] <= life['end_ns'] for r in receipt['clock_samples']),
                'source_release_outside_member_lifetime')
        return dict(source=source, origins=origins, classification=classification)


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
            and capacity.get('campaign_verified') is True and capacity.get('preservation_verified') is True
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
