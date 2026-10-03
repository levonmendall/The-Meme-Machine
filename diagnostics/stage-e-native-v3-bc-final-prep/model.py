"""Pure declaration, prerequisite, evidence-path and 47-gate models."""
from copy import deepcopy
from pathlib import Path

from frozen import *
from core import RESOURCE_SAMPLING

A_FIELDS = {
    'declaration': 'existing original A declaration path',
    'declaration_sha256': 'SHA-256 of exact original A declaration bytes',
    'campaign_id': 'fresh capacity-v3 namespace from verified declaration',
    'sealed_campaign': 'complete sealed A campaign path',
    'terminal_ledger': 'path and SHA-256 of complete terminal A ledger',
    'preservation_receipt': 'A final preservation receipt path and SHA-256',
    'raw_trial': 'A t1 path and raw inventory SHA-256',
    'allocation_public_key_evidence': 'signed allocation, capability receipts and independently trusted key bindings',
    'environment_sha256': 'SHA-256 of actual A environment',
    'executor_boot_identity': 'actual executor_id, hostname and boot_id',
}


def a_slot():
    return dict(version='stage-e-native-v3-typed-A-prerequisite', state=UNRESOLVED_A,
                bindings={k: unresolved(UNRESOLVED_A, v) for k, v in A_FIELDS.items()})


def require_a_slot(slot):
    require(type(slot) is dict and slot.get('state') == 'VERIFIED_COMPLETE_A_CAPACITY_PACKAGE',
            UNRESOLVED_A)
    require(set(slot.get('bindings', {})) == set(A_FIELDS), 'missing_A_prerequisite_binding')
    for name, row in slot['bindings'].items():
        require(type(row) is dict and row.get('state') == 'BOUND_FROM_REVERIFIED_RAW_A'
                and row.get('expected_type') == A_FIELDS[name] and row.get('value') is not None,
                'missing_A_prerequisite_binding:' + name)
    return slot


def path_map():
    return dict(version='stage-e-native-v3-evidence-path-map',
        root='/mnt/volume_nyc1_1790918115030/stage-e-native-v3-bc-final',
        component_rule='class + campaign ID + exact declaration SHA-256 + manifest SHA-256; exclusive destinations',
        campaign_registry_rule='separate owner-declared B/C registry; never A registry',
        paths={
            'A_ingestion': 'ingestion/A/{campaign}/{declaration_sha256}/{campaign_inventory_sha256}/',
            'B_trials': 'raw/B/{campaign}/{declaration_sha256}/t{sequence:02d}/{raw_inventory_sha256}/',
            'B_campaign': 'campaign/B/{campaign}/{declaration_sha256}/{campaign_inventory_sha256}/',
            'C_trial': 'raw/C/{campaign}/{declaration_sha256}/t01/{raw_inventory_sha256}/',
            'C_pre_restart': 'raw/C/{campaign}/{declaration_sha256}/t01/m{member}/restart-before/',
            'C_post_restart': 'raw/C/{campaign}/{declaration_sha256}/t01/m{member}/restart-after/',
            'C_terminal_safety_only': 'terminal/C/{campaign}/{declaration_sha256}/{raw_inventory_sha256}/',
            'final': 'qualification/{candidate_sha}/{ABC_binding_sha256}/{manifest_sha256}/',
            'remote': 'diagnostics/stage-e-native-v3-evidence/{class}/{campaign}/{declaration_sha256}/{inventory_sha256}/',
            'redundant': 'redundant/{class}/{campaign}/{declaration_sha256}/{inventory_sha256}/',
        }, all_destinations_exclusive=True, actual_paths_reserved=False)


def declaration_template(kind):
    require(kind in ('B', 'C'), 'unknown_prep_class')
    paths = {k: unresolved('EXECUTION_PATH_NOT_YET_BOUND', k) for k in (
        'repository', 'candidate_checkout', 'assembly', 'tape', 'frame_inventory',
        'allocation_document', 'allocation_public_key', 'storage_paths',
        'campaign_registry', 'cache_path', 'durable_publication_root')}
    d = preview(kind, namespace(kind), executor=unresolved('INHERIT_VERIFIED_A_EXECUTOR', 'executor'),
        environment=unresolved('INHERIT_VERIFIED_A_ENVIRONMENT', 'environment'),
        workflow=unresolved('FUTURE_OWNER_WORKFLOW_BINDING', 'exact workflow/run/attempt'), paths=paths)
    d.update(**{k: v for k, v in FROZEN.items() if k not in d})
    d['envelope'] = contract_file('production_envelope.json')
    d['complete_workload'] = workload(kind)
    d['A_prerequisite_slot'] = a_slot() if kind == 'B' else None
    d['admission_state'] = UNRESOLVED_A if kind == 'B' else 'C_PREVIEW_NOT_AUTHORIZED'
    d['namespace_state'] = 'TEMPLATE_ONLY_NOT_RESERVED_NOT_CONSUMED'
    d['evidence_paths'] = path_map()
    d['acceptance_credit'] = dict(A=False, B=False, C=False)
    if kind == 'B':
        d['pairs'] = [dict(pair_id=namespace(kind) + f'-p{i+1}',
                           trials=[t['trial_id'] for t in d['trials'][2*i:2*i+2]]) for i in range(3)]
        d['observer_acceptance'] = dict(required_complete_valid_pairs=3,
            strict_integer_predicate='100 * sum(observed_ns - baseline_ns) < sum(baseline_ns)',
            equality_at_one_percent='FAIL', observed_below_baseline='FAIL',
            duration_type='positive integer perf_counter_ns delta', subtract_costs=False,
            warmups=0, retries=0, replacements=0, complete_workload_equality=True,
            environment_executor_boot_equality_with_A=True)
    else:
        d['safety_evidence'] = dict(required=[
            'original run381 profile and every failed predicate', 'source pauses at frames 800 and 1400',
            'held-reader interference', 'completed-tail delay', 'native overload/refusal ancestry',
            'restart-before and restart-after raw SQLite states', 'generation health publication while WARMING',
            'refusal-time WARMING generation', 'final OFF readback', 'raw preservation and resource/lifetime coverage'],
            accepted_outcomes=workload('C')['accepted_outcomes'], diagnostic_performance_separate=True,
            capacity_credit=False, observer_credit=False)
    return d


def validate_template(d, kind):
    expected = declaration_template(kind)
    require(d == expected, 'prep_declaration_template_changed')
    require(d['execution_authorized'] is False and d['actual_slots_reserved'] is False
            and d['source_frames_released'] == 0, 'prep_cannot_authorize')
    return True


# Supplemental preserved proof remains mandatory where the approved mapping
# explicitly retains original semantic/assembled/prepared-lane obligations.
PRESERVED = {
    'exact_source_offline-v3': 'canonical/offline/',
    'native_crash_matrix-v3': 'canonical/crash/',
    'restart_safety-v3': 'canonical/restart-safety/',
    'integrated_current_policy-v3': 'canonical/integrated-acceptance/',
    'historical_exposure_resolution-v3': 'canonical/historical-resolution.json',
    'historical_registry_released-v3': 'canonical/historical-registry.json',
    'joined_eight_day_system-v3': 'canonical/joined/',
    'exact_integration_identity-v3': 'canonical/offline/',
    'six_regime_integration-v3': 'canonical/directional-acceptance/',
    'preserved_production_adapter_contracts-v3': 'canonical/integrated-acceptance/',
    'bounded_preserved_validation-v3': 'canonical/preserved-validation/',
    'checkpoint-completion-v3': 'native/held-reader/raw-trial-v2.json',
    'native-archive-v3': 'native/native-transitions/raw-trial-v2.json',
    'native-retirement-v3': 'native/native-transitions/raw-trial-v2.json',
    'prepared-source-v3': 'prepared/prepared-proof.json',
    'prepared-import-collection-v3': 'prepared/prepared-proof.json',
    'protocol-freeze-v3': 'prepared/protocol-proof.json',
    'generation-fencing-v3': 'native/generation-restart/raw-trial-v2.json',
    'restart-accounting-v3': 'native/m1-completion/raw-trial-v2.json',
}


def gate_sources(name):
    if name == 'observer-v3': return ['B']
    if name in ('synthetic-stress-safety-v3', 'burst-schedule-v3', 'fixed-old-cohort-v3', 'debt-tails-v3'): return ['C']
    if name == 'historical-observer-seal-v3': return ['PRESERVED', 'FINAL']
    if name == 'production-envelope-capacity-v3' or name in ('run373-v3', 'run379-v3', 'run380-v3'): return ['A']
    if name in PRESERVED:
        return ['PRESERVED', 'FINAL'] + (['A'] if name in ('native-archive-v3', 'native-retirement-v3') else [])
    if name in ('cohort-complete-v3', 'pressure-profile-v3', 'frame-byte-bounds-v3',
                'joint-lifecycle-v3', 'recovery-v3', 'mature_solana_pressure-v3',
                'combined_mature_solana_pressure-v3'):
        return ['A', 'B', 'C']
    return ['A', 'B', 'C', 'FINAL']


def gate_artifacts(name):
    if name in PRESERVED: return [PRESERVED[name], 'RAW_INVENTORY.json', 'RETAINED_AUTHORITY.json']
    if name == 'historical-observer-seal-v3':
        return ['approved-contract/historical_observer_seal.json', 'approved-contract/source_evidence_manifest.json',
                'approved-contract/evidence/{original_commit}/{original_path}', 'A/B/C/DECLARATION.json']
    if name == 'observer-v3':
        return ['B/t{1..6}/TRIAL_RESULT.json', 'B/t{1..6}/RAW_INVENTORY.json',
                'B/LEDGER.jsonl', 'B/TRIAL-{1..6}-PRESERVATION.json', 'A/CAMPAIGN_INVENTORY.json', 'A/PRESERVATION.json']
    if name in ('run373-v3', 'run379-v3', 'run380-v3'):
        index = {'run373-v3': 1, 'run379-v3': 2, 'run380-v3': 3}[name]
        return [f'A/t1/m{index}/MEMBER_RESULT.json', f'A/t1/m{index}/SOURCE_RECEIPT.json',
                f'A/t1/m{index}/ORIGIN-*.json', f'A/t1/m{index}/ADMISSION-*.json', 'A/t1/RAW_INVENTORY.json']
    suffixes = ['DECLARATION.json', 'PUBLIC_AUTHORITY_RECEIPTS.json', 'IDENTITY.json', 'LEDGER.jsonl',
                'CAMPAIGN_INVENTORY.json', 'TRIAL-{sequence}-PRESERVATION.json', 't{sequence}/TRIAL_RESULT.json',
                't{sequence}/COHORT_RESULT.json', 't{sequence}/PROCESS_TERMINATION.json',
                't{sequence}/MEASURED_PERSISTENCE_COMPLETE.json', 't{sequence}/RAW_INVENTORY.json',
                't{sequence}/resources/RESOURCE-*.json', 't{sequence}/m{member}/MEMBER_RESULT.json',
                't{sequence}/m{member}/SOURCE_RECEIPT.json', 't{sequence}/m{member}/ORIGIN-*.json',
                't{sequence}/m{member}/ADMISSION-*.json', 'PRESERVATION.json']
    return [kind + '/' + path for kind in gate_sources(name) if kind in ('A', 'B', 'C') for path in suffixes]


def skeleton():
    approved = contract_file('contract.json')
    mapping = contract_file('gate-map-v3.json')
    rows = {r['successor_gate']: r for r in mapping['gates'] + mapping['additional_gates']}
    require(len(approved['required_gates']) == 47 and len(set(approved['required_gates'])) == 47
            and set(rows) == set(approved['required_gates']), 'exact_47_approved_gates_required')
    gates = []
    for name in approved['required_gates']:
        r = rows[name]
        sources = gate_sources(name)
        gates.append(dict(name=name, state=UNSATISFIED, required=True,
            authoritative_evidence_class=sources,
            expected_source_artifact=gate_artifacts(name),
            expected_binding=dict(**FROZEN, path='manifest-listed relative path from verified published package',
                sha256=unresolved('RAW_SHA256_NOT_YET_AVAILABLE', 'hash recomputed from read-back bytes')),
            satisfied_by=sources, acceptance_predicate=r['acceptance'],
            machine_predicate='qualification.evaluate_gate:' + name,
            retained_verifier_obligation=r.get('native_verifier_obligation'),
            predecessor_mapping=deepcopy(r.get('predecessor_row')),
            missing_evidence_state=UNSATISFIED, evidence=[]))
    return dict(version='stage-e-native-v3-final-qualification-skeleton', **FROZEN,
        stage_e='RED', stage_f='NOT STARTED', disposition='STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED',
        gates=gates, ingestion_slots={
            'A': ['production-envelope capacity', 'production safety', 'run373', 'run379', 'run380',
                  'cohort/source shape', 'resource', 'recovery/lifecycle', 'artifact/origin'],
            'B': ['six complete trials', 'three pair identities', 'raw durations', 'workload equality',
                  'resource/executor/boot equality', 'summed observer arithmetic', 'strict <1%'],
            'C': ['synthetic diagnostics', 'overload safety', 'native fail closed', 'restart publication/WARMING/OFF',
                  'evidence preservation', 'diagnostic performance outcome'],
            'PRESERVED': list(PRESERVED.values()),
            'FINAL': ['same SHA', 'protocol freeze', 'historical observer seal', 'artifact provenance',
                      'workflow identity', 'assembly origin', 'zero unresolved gates']},
        inputs={k: unresolved('PUBLISHED_EVIDENCE_NOT_YET_AVAILABLE', k + ' evidence package')
                for k in ('A', 'B', 'C', 'PRESERVED')}, unresolved_gate_count=47,
        execution_authorized=False, paper_only=True)


def validate_skeleton(value):
    require(value == skeleton(), 'skeleton_changed_or_manually_asserted_PASS')
    return True
