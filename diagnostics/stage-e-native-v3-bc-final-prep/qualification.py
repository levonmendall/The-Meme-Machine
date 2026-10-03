"""Recompute all 47 gates from read-back raw packages, never asserted PASS."""
from pathlib import Path

from frozen import *
from model import skeleton, validate_skeleton, PRESERVED
from ingestion import ingest_campaign, equal_runtime
from retained import ingest_retained, canonical_gate
from verify import production_member_errors, observer_sample_errors, stress_member_result, OVERLOAD


def historical_seal():
    seal = contract_file('historical_observer_seal.json')
    m = contract_file('source_evidence_manifest.json')
    require(len(m['evidence_files']) == 159, 'historical_full_inventory_missing')
    for row in m['evidence_files']:
        p = relative(CONTRACT, 'evidence/' + row['commit'] + '/' + row['path'])
        require(p.is_file() and p.stat().st_size == row['bytes'] and file_sha(p) == row['sha256'],
                'historical_v2_evidence_changed')
    before = contract_file('candidate_integrity_before.json')
    require(before['S'] == S and before['T'] == T, 'historical_candidate_identity_changed')
    require(seal['outcome'] == 'OBSERVER_V2: INVALID_PAIR' and seal['started_trials'] == seal['started_members'] == 1
            and seal['unused_slots'] == 5 and seal['complete_valid_pairs'] == 0
            and seal['observer_overhead_earned'] is False and seal['reuse_allowed'] is False
            and seal['retries'] == seal['replacement_trials'] == 0
            and seal['numerator_ns'] is seal['denominator_ns'] is seal['ratio'] is None,
            'historical_observer_seal_changed')
    return dict(verified_files=159, seal_sha256=sha(canonical(seal)), outcome=seal['outcome'])


def members(package):
    d = package['declaration']; root = Path(package['reference']['sealed_campaign'])
    rows = []
    for trial in d['trials']:
        t = root / f't{trial["sequence"]}'
        result = read(t/'TRIAL_RESULT.json')
        for n, member in enumerate(result['members'], 1):
            rows.append((t / f'm{n}', read(t / f'm{n}/MEMBER_RESULT.json')))
    return rows


def evaluate_gate(name, packages, retained, seal):
    required = {r['name']: r for r in skeleton()['gates']}[name]['satisfied_by']
    if any(s in ('A', 'B', 'C') and s not in packages for s in required): return False
    if 'PRESERVED' in required and name != 'historical-observer-seal-v3' and retained is None: return False
    if name == 'historical-observer-seal-v3': return seal is not None and all(
        not set(t['trial_id'] for t in p['declaration']['trials']).intersection(
            contract_file('historical_observer_seal.json')['all_old_trial_ids_forbidden']) for p in packages.values())
    if name in PRESERVED:
        return canonical_gate(name, retained)
    if name == 'observer-v3':
        return packages['B']['result']['outcome'] == 'OBSERVER_V3: VALID_THREE_PAIRS'
    if name == 'production-envelope-capacity-v3':
        return packages['A']['result']['complete_cohort'] is True and packages['A']['result']['capacity_credit'] is True
    if name in ('run373-v3', 'run379-v3', 'run380-v3'):
        shape = name[:-3]
        selected = [row for _, row in members(packages['A']) if row.get('shape') == shape]
        return len(selected) == 1 and not production_member_errors(selected[0])
    if name == 'synthetic-stress-safety-v3':
        return all(stress_member_result(row)['mandatory_native_safety_pass']
                   and row.get('capacity_credit') is False for _, row in members(packages['C']))
    if name in ('burst-schedule-v3', 'fixed-old-cohort-v3', 'debt-tails-v3'):
        c = packages['C']['result']
        # Failed or incomplete diagnostics never become full profile coverage.
        return c['complete_cohort'] is True and c['diagnostic_outcome'] == 'PASS' and all(
            stress_member_result(row)['diagnostic_performance_pass'] for _, row in members(packages['C']))
    if name == 'cohort-complete-v3':
        return packages['A']['result']['complete_cohort'] is True and len(packages['B']['declaration']['trials']) == 6
    if name == 'pressure-profile-v3':
        return all(row['artificial_contention'] == workload('A')['artificial_contention']
                   for kind in ('A', 'B') for _, row in members(packages[kind])) and all(
            row['measured_contention']['owner_seconds_per_frame'] >= .165
            and row['measured_contention']['archive_seconds_per_thousand'] >= .36
            and row['measured_contention']['additional_commit_latency_seconds'] >= .006
            for _, row in members(packages['C']))
    if name in ('same-sha-v3', 'artifact-provenance-v3', 'workflow-identity-v3', 'assembly-origin-v3',
                'resource_bounds-v3', 'integrity-resources-v3', 'provider-isolation-v3',
                'source-shape-v3', 'frame-byte-bounds-v3', 'candidate-progress-v3',
                'urgent-source-fairness-v3', 'residence-v3', 'recovery-v3',
                'mature_solana_pressure-v3', 'combined_mature_solana_pressure-v3', 'joint-lifecycle-v3'):
        # These exact obligations are recomputed per member, raw DB, source
        # receipt, timeline, origin, signed allocation and ledger by the approved
        # verify_campaign -> verify_trial -> verify_member path, not a supplied
        # verification summary. Preserve C diagnostic status separately.
        return all(p['verified_from_raw'] is True for p in packages.values()) and all(
            not production_member_errors(row) and (row['mode'] != 'observed' or not observer_sample_errors(row))
            for kind in ('A', 'B') if kind in packages for _, row in members(packages[kind]))
    raise ValueError('required_gate_has_no_machine_predicate:' + name)


def generate(input_refs, *, owner_key, allocation_key, initial_skeleton=None, retained_ref=None):
    validate_skeleton(initial_skeleton if initial_skeleton is not None else skeleton())
    require(type(input_refs) is dict and set(input_refs).issubset({'A', 'B', 'C'}), 'qualification_input_schema')
    packages, failures, seen = {}, [], []
    for kind in ('A', 'B', 'C'):
        if kind not in input_refs: continue
        try:
            p = ingest_campaign(input_refs[kind], kind=kind, owner_key=owner_key, allocation_key=allocation_key,
                                seen_namespaces=seen, prerequisite_A=input_refs.get('A'))
            if kind != 'A' and 'A' in packages: equal_runtime(packages['A']['declaration'], p['declaration'])
            seen.append(p['declaration']['campaign']); packages[kind] = p
        except (ValueError, KeyError, TypeError, OSError) as e:
            failures.append(dict(class_id=kind, reason=str(e)))
    retained = None
    if retained_ref is not None:
        try:
            require(set(retained_ref) == {'folder', 'assembly'}, 'retained_reference_schema')
            require('A' in packages, 'A_trusted_key_required_for_preserved_raw_attestation')
            retained = ingest_retained(**retained_ref, owner_key=owner_key,
                owner_public_key_sha256=packages['A']['declaration']['trust_keys']['owner_public_key_sha256'])
        except (ValueError, KeyError, TypeError, OSError) as e:
            failures.append(dict(class_id='PRESERVED', reason=str(e)))
    seal = None
    # Historical evidence is never automatically credited on an empty package.
    if all(kind in packages for kind in ('A', 'B', 'C')):
        try: seal = historical_seal()
        except (ValueError, KeyError, TypeError, OSError) as e: failures.append(dict(class_id='HISTORY', reason=str(e)))
    review = skeleton()
    for kind, p in packages.items():
        review['inputs'][kind] = dict(state='VERIFIED_FROM_PUBLISHED_RAW_CAMPAIGN', value=p['reference'])
    if retained is not None:
        review['inputs']['PRESERVED'] = dict(state='VERIFIED_FROM_PRESERVED_PRIMARY_RAW_EVIDENCE',
            value=dict(reference=retained_ref, raw_inventory_sha256=retained['raw_inventory_sha256']))
    for gate in review['gates']:
        try: satisfied = evaluate_gate(gate['name'], packages, retained, seal)
        except (ValueError, KeyError, TypeError, OSError) as e:
            satisfied = False; failures.append(dict(gate=gate['name'], reason=str(e)))
        gate['state'] = 'SATISFIED_BY_VERIFIED_RAW_EVIDENCE' if satisfied else UNSATISFIED
        if satisfied:
            gate['evidence'] = [dict(class_id=k, campaign=p['declaration']['campaign'],
                declaration_sha256=p['reference']['declaration_sha256'],
                inventory_sha256=p['reference']['campaign_inventory_sha256'],
                remote_commit=p['reference']['remote_readback']['commit']) for k, p in packages.items()
                if k in gate['satisfied_by']]
            if 'PRESERVED' in gate['satisfied_by']:
                gate['evidence'].append(seal if gate['name'] == 'historical-observer-seal-v3' else
                                      dict(raw_inventory_sha256=retained['raw_inventory_sha256']))
            bound = [dict(path=p['reference']['sealed_campaign'] + '/CAMPAIGN_INVENTORY.json',
                          sha256=p['reference']['campaign_inventory_sha256'])
                     for kind, p in packages.items() if kind in gate['satisfied_by']]
            if 'PRESERVED' in gate['satisfied_by']:
                preserved_path = (str(CONTRACT/'source_evidence_manifest.json')
                    if gate['name'] == 'historical-observer-seal-v3' else retained_ref['folder'] + '/RAW_INVENTORY.json')
                bound.append(dict(path=preserved_path, sha256=file_sha(preserved_path)))
            gate['expected_binding']['path'] = [r['path'] for r in bound]
            gate['expected_binding']['sha256'] = dict(state='BOUND_FROM_REVERIFIED_RAW_ARTIFACT_INVENTORIES',
                expected_type='exact inventory paths and SHA-256 recomputed from read-back bytes', value=bound)
    unresolved = [g['name'] for g in review['gates'] if g['state'] != 'SATISFIED_BY_VERIFIED_RAW_EVIDENCE']
    qualified = not unresolved and not failures and all(k in packages for k in ('A', 'B', 'C'))
    review.update(disposition='STAGE_E_NATIVE_V3_QUALIFIED' if qualified else 'STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED',
        stage_e='GREEN' if qualified else 'RED', stage_f='NOT STARTED', unresolved_gate_count=len(unresolved),
        unresolved_gates=unresolved, validation_failures=failures,
        C_diagnostic_outcome=packages.get('C', {}).get('result', {}).get('diagnostic_outcome', 'NOT_RUN'),
        decision_is_review_only=True, next_authority='ASTRA/OWNER', execution_authorized=False)
    return review
