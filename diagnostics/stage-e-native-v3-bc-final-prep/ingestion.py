"""Read-only A/B/C ingestion using the exact approved raw campaign verifier."""
from copy import deepcopy
from pathlib import Path
import re

from frozen import *
from model import a_slot, A_FIELDS, require_a_slot, declaration_template
from shared_inputs import artifact
from campaign import verify_campaign, verify_capacity_prerequisite
from verify import OVERLOAD, observer_arithmetic


def reject_asserted_state(value):
    """Input API accepts evidence references, never verdicts or gate overrides."""
    require(type(value) is dict, 'evidence_reference_object_required')
    require(not {'passed', 'PASS', 'gates', 'gate_states', 'stage_e', 'qualification'}.intersection(value),
            'manually_asserted_PASS_is_not_evidence')


def check_declaration(d, kind):
    require(d['class_id'] == kind and all(d.get(k) == v for k, v in FROZEN.items() if k in (
                'candidate_sha', 'candidate_tree', 'assembly_digest', 'contract_commit', 'contract_manifest_sha256')),
            'wrong_candidate_tree_assembly_contract')
    require(d.get('approved_executable_commit', d.get('executable_commit')) == EXECUTABLE_COMMIT
            and d['infrastructure'] == infrastructure_identity(), 'wrong_executable')
    require(d['trials'] == trial_matrix(d['campaign'], kind), 'wrong_order_duplicate_trial_or_v2_reuse')
    require(d['tape_binding'] == workload(kind)['tape_binding']
            and d['workload_sha256'] == sha(canonical(workload(kind)))
            and d['environment_sha256'] == sha(canonical(d['environment'])), 'changed_tape_workload_environment')
    require(d['execution_authorized'] is True and d['disposition'] == 'AUTHORIZED PAPER EXECUTION',
            'PREVIEW_cannot_receive_campaign_credit')
    require(d['warmups'] == d['retries'] == d['replacements'] == 0, 'warmup_retry_replacement_forbidden')


def equal_runtime(left, right):
    require(left['environment_sha256'] == right['environment_sha256']
            and left['environment'] == right['environment']
            and all(left['executor'][k] == right['executor'][k] for k in ('executor_id', 'hostname', 'boot_id'))
            and left['production_workload_sha256'] == right['production_workload_sha256']
            and left['tape_binding'] == right['tape_binding'], 'changed_environment_executor_boot_or_tape')


def ingest_campaign(ref, *, kind, owner_key, allocation_key, seen_namespaces=(), prerequisite_A=None):
    reject_asserted_state(ref)
    require(set(ref) == {'sealed_campaign', 'preservation_receipt', 'declaration_sha256',
                         'campaign_inventory_sha256', 'remote_readback'}, 'campaign_ingestion_reference_schema')
    folder = Path(ref['sealed_campaign'])
    require(folder.is_dir() and ref['preservation_receipt'], 'campaign_or_preservation_missing')
    for k in ('declaration_sha256', 'campaign_inventory_sha256'):
        require(type(ref[k]) is str and re.fullmatch('[0-9a-f]{64}', ref[k]), 'missing_campaign_digest')
    require(file_sha(folder/'DECLARATION.json') == ref['declaration_sha256']
            and file_sha(folder/'CAMPAIGN_INVENTORY.json') == ref['campaign_inventory_sha256'], 'campaign_manifest_changed')
    d = read(folder/'DECLARATION.json'); check_declaration(d, kind)
    require(d['campaign'] not in set(seen_namespaces), 'reused_campaign_namespace')
    r = ref['remote_readback']
    require(type(r) is dict and r.get('complete') is True and r.get('independently_recomputed_sha256') is True
            and r.get('class_id') == kind and r.get('campaign') == d['campaign']
            and r.get('declaration_sha256') == ref['declaration_sha256']
            and r.get('inventory_sha256') == ref['campaign_inventory_sha256']
            and Path(r.get('output', '')).resolve() == folder.resolve()
            and re.fullmatch(r'[0-9a-f]{40}', r.get('commit', '')), 'complete_remote_readback_required')
    if kind == 'B':
        require(prerequisite_A is not None, 'A_PREREQUISITE_NOT_YET_AVAILABLE')
        # A is recomputed from its raw package on every B admission/ingestion.
        a = ingest_campaign(prerequisite_A, kind='A', owner_key=owner_key, allocation_key=allocation_key)
        equal_runtime(a['declaration'], d)
        require(d['prerequisites']['capacity']['declaration_sha256'] == prerequisite_A['declaration_sha256'],
                'B_bound_to_different_A')
    result = verify_campaign(folder, owner_key, allocation_key,
                             preservation_receipt=ref['preservation_receipt'], expected_class=kind)
    require(result['passed'] is True and result['campaign_verified'] is True
            and result['preservation_verified'] is True, 'raw_campaign_verification_failed')
    if kind in ('A', 'B'):
        require(result.get('diagnostic_outcome', 'PASS') == 'PASS' and not result.get('safety_only', False),
                'synthetic_or_incomplete_result_has_no_A_B_credit')
    if kind == 'B':
        require(len(result['raw_pairs']) == 3, 'three_complete_valid_pairs_required')
        arithmetic = observer_arithmetic(result['raw_pairs'])
        require(all(result[k] == v for k, v in arithmetic.items()), 'observer_arithmetic_not_derived')
    if kind == 'C':
        require(result.get('capacity_credit') is False and result.get('observer_credit') is False,
                'C_receiving_A_B_credit')
        require(result['outcome'] in ('FULL_PROFILE_SAFETY_PASS', OVERLOAD), 'C_native_safety_disposition_required')
    return dict(class_id=kind, declaration=d, result=result, reference=deepcopy(ref),
                verification_origin='exact approved campaign.verify_campaign from ' + EXECUTABLE_COMMIT,
                verified_from_raw=True)


def bind_A_prerequisite(a):
    require(a.get('verified_from_raw') is True and a['class_id'] == 'A', 'verified_raw_A_required')
    d, ref = a['declaration'], a['reference']; root = Path(ref['sealed_campaign'])
    authority = read(root/'PUBLIC_AUTHORITY_RECEIPTS.json')
    values = dict(declaration=str(root/'DECLARATION.json'), declaration_sha256=ref['declaration_sha256'],
        campaign_id=d['campaign'], sealed_campaign=str(root),
        terminal_ledger=dict(path=str(root/'LEDGER.jsonl'), sha256=file_sha(root/'LEDGER.jsonl')),
        preservation_receipt=dict(path=ref['preservation_receipt'], sha256=file_sha(ref['preservation_receipt'])),
        raw_trial=dict(path=str(root/'t1'), raw_inventory_sha256=file_sha(root/'t1/RAW_INVENTORY.json')),
        allocation_public_key_evidence=dict(authority_receipts=authority,
            authority_receipts_sha256=file_sha(root/'PUBLIC_AUTHORITY_RECEIPTS.json'),
            trust_keys=d['trust_keys']), environment_sha256=d['environment_sha256'],
        executor_boot_identity={k: d['executor'][k] for k in ('executor_id', 'hostname', 'boot_id')})
    slot = dict(version=a_slot()['version'], state='VERIFIED_COMPLETE_A_CAPACITY_PACKAGE',
                bindings={k: dict(state='BOUND_FROM_REVERIFIED_RAW_A', expected_type=A_FIELDS[k], value=values[k])
                          for k in A_FIELDS})
    require_a_slot(slot); return slot


def bind_preview(kind, verified, config):
    require(kind in ('B', 'C'), 'preview_class')
    require(verified['class_id'] == ('A' if kind == 'B' else 'B') and verified['verified_from_raw'] is True,
            'verified_preceding_phase_required')
    require(set(config) == {'paths', 'workflow', 'storage_bounds'}, 'preview_handoff_config_schema')
    prior = verified['declaration']
    d = preview(kind, declaration_template(kind)['campaign'], executor=deepcopy(prior['executor']),
        environment=deepcopy(prior['environment']), workflow=deepcopy(config['workflow']),
        paths=deepcopy(config['paths']), allocation=deepcopy(prior['allocation']),
        storage_bounds=deepcopy(config['storage_bounds']), trust_keys=deepcopy(prior['trust_keys']))
    d['approved_executable_commit'] = EXECUTABLE_COMMIT
    if kind == 'B':
        slot = bind_A_prerequisite(verified); values = {k: r['value'] for k, r in slot['bindings'].items()}
        d['A_prerequisite_slot'] = slot
        d['prerequisites']['capacity'] = dict(declaration=values['declaration'],
            declaration_sha256=values['declaration_sha256'], sealed_campaign=values['sealed_campaign'],
            preservation_receipt=values['preservation_receipt']['path'])
    require(d['paths']['tape'] == prior['paths']['tape'] and d['paths']['frame_inventory'] == prior['paths']['frame_inventory']
            and d['paths']['assembly'] == prior['paths']['assembly'], 'preview_changed_physical_input_paths')
    require(Path(d['paths']['campaign_registry']).resolve() != Path(prior['paths']['campaign_registry']).resolve(),
            'B_C_registry_must_be_separate_from_preceding_registry')
    # Path length is checked without mkdir/stat/reserving any production path.
    campaign_root = Path(d['paths']['campaign_registry']) / d['campaign']
    require(max(len(str(campaign_root / f't{n}' / f'm{m}' / 'd/db.sock').encode())
                for n in range(1, 7 if kind == 'B' else 2) for m in range(1, 5)) < 108,
            'native_UNIX_socket_path_too_long')
    if kind == 'C': d['acceptance_credit'] = dict(A=False, B=False)
    return d


def verify_bound_B_preview(d, *, owner_key, allocation_key):
    require(d['execution_authorized'] is False and d['disposition'] == 'NOT AUTHORIZED / PREVIEW ONLY',
            'handoff_cannot_authorize_B')
    require_a_slot(d.get('A_prerequisite_slot'))
    return verify_capacity_prerequisite(d, owner_key, allocation_key)
