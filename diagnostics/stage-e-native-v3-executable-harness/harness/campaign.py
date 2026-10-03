"""Read-only sealed campaign and prerequisite verification; no runner imports."""
from pathlib import Path

from attest import signed_document
from binding import infrastructure_identity
from core import (ASSEMBLY, CONTRACT_COMMIT, CONTRACT_MANIFEST_SHA, S, T, canonical,
                  contract_file, file_sha, read, relative, require, sha, workload, RESOURCE_SAMPLING)
from declaration import TIMING, STOP_RULES, PRESERVATION
from ledger import Ledger, trial_matrix
from preserve import verify_inventory
from verify import OVERLOAD, verify_trial, verify_observer


def verify_publication(folder, receipt, *, name, expected_source):
    """A flag alone is insufficient: recheck the retained and published bytes."""
    source, destination = Path(receipt['source']).resolve(), Path(receipt['destination']).resolve()
    require(source == Path(expected_source).resolve() and source != destination
            and receipt['local_copy_retained'] is True and receipt['independently_read_back'] is True,
            'successful_preservation_binding_required')
    expected = verify_inventory(folder, name=name)
    require(verify_inventory(source,name=name) == expected and verify_inventory(destination,name=name) == expected
            and file_sha(Path(folder)/name) == file_sha(source/name) == file_sha(destination/name)
            == receipt['inventory_sha256'], 'successful_preservation_readback_required')
    return receipt


def verify_capacity_prerequisite(declaration, owner_key, allocation_key):
    a = declaration['prerequisites']['capacity']
    require(file_sha(a['declaration']) == a['declaration_sha256'], 'A_prerequisite_declaration_changed')
    original = read(a['declaration'])
    require(original['class_id'] == 'A' and original['campaign'] != declaration['campaign'],
            'A_is_separate_fresh_campaign')
    folder = Path(a['sealed_campaign']).resolve()
    require(read(folder/'DECLARATION.json') == original, 'A_prerequisite_actual_declaration_mismatch')
    capacity = verify_campaign(folder, owner_key, allocation_key,
                               preservation_receipt=a['preservation_receipt'], expected_class='A')
    require(capacity['declaration_sha256'] == a['declaration_sha256']
            and capacity['candidate_sha'] == declaration['candidate_sha'] == S
            and capacity['candidate_tree'] == declaration['candidate_tree'] == T
            and capacity['environment_sha256'] == declaration['environment_sha256']
            and capacity['production_workload_sha256'] == declaration['production_workload_sha256']
            and original['assembly_digest'] == declaration['assembly_digest'] == ASSEMBLY
            and original['tape_binding'] == declaration['tape_binding']
            and all(original['executor'][k] == declaration['executor'][k]
                    for k in ('executor_id','hostname','boot_id')), 'A_B_required_bindings_changed')
    return capacity


def verify_campaign(folder, owner_key, allocation_key, *, preservation_receipt=None, expected_class=None):
    folder = Path(folder).resolve()
    verify_inventory(folder,name='CAMPAIGN_INVENTORY.json')
    require(not any((folder/name).exists() for name in
                    ('STOP_FOR_ASTRA.json','CONTROLLER_FAILURE.json','CAMPAIGN_PRESERVATION_FAILURE.json')),
            'campaign_failure_precludes_acceptance')
    d = read(folder/'DECLARATION.json')
    require(d['execution_authorized'] is True and d['disposition'] == 'AUTHORIZED PAPER EXECUTION'
            and d['paper_only'] is True and d['stage_e'] == 'RED' and d['stage_f'] == 'NOT STARTED',
            'preview_has_no_native_acceptance')
    require(expected_class is None or d['class_id'] == expected_class, 'prerequisite_campaign_class')
    require(d['candidate_sha'] == S and d['candidate_tree'] == T and d['assembly_digest'] == ASSEMBLY
            and d['contract_commit'] == CONTRACT_COMMIT and d['contract_manifest_sha256'] == CONTRACT_MANIFEST_SHA,
            'verifier_exact_candidate_identity')
    require(d['trials'] == trial_matrix(d['campaign'],d['class_id']) and d['infrastructure'] == infrastructure_identity()
            and d['verifier']['infrastructure_digest'] == d['infrastructure']['digest']
            and d['verifier']['sha256'] == d['infrastructure']['files']['verify.py']['sha256'],
            'verifier_trial_or_executable_identity')
    require(d['workload_sha256'] == sha(canonical(workload(d['class_id'])))
            and d['production_workload_sha256'] == sha(canonical(workload('A')))
            and d['tape_binding'] == workload(d['class_id'])['tape_binding']
            and d['environment_sha256'] == sha(canonical(d['environment']))
            and d['historical_seal_sha256'] == sha(canonical(contract_file('historical_observer_seal.json')))
            and d['timing'] == TIMING and d['stop_rules'] == STOP_RULES and d['preservation_rules'] == PRESERVATION
            and d.get('resource_sampling') == RESOURCE_SAMPLING
            and d['retries'] == d['replacements'] == d['warmups'] == 0,
            'verifier_contract_semantic_binding')
    signature = read(folder/'PUBLIC_AUTHORITY_RECEIPTS.json')
    permit = signed_document(relative(folder,signature['owner_permit_path']),owner_key,d['trust_keys']['owner_public_key_sha256'])
    require(permit == dict(version='stage-e-native-v3-owner-execution-permit',
        declaration_sha256=signature['original_declaration_sha256'], class_id=d['class_id'], campaign=d['campaign'],
        workflow=d['workflow'], executor_id=d['executor']['executor_id'], paper_only=True,
        stage_f_authorized=False, provider_authorized=False), 'raw_owner_permit_binding')
    require(read(relative(folder,signature['original_declaration_path'])) == d
            and file_sha(relative(folder,signature['original_declaration_path'])) == signature['original_declaration_sha256'],
            'original_executable_declaration_bytes')
    allocation = signed_document(relative(folder,signature['allocation_document_path']),allocation_key,
                               d['trust_keys']['allocation_public_key_sha256'])
    require(allocation == d['allocation'], 'raw_authenticated_allocation_changed')
    capabilities = {r['original_path']:str(relative(folder,r['preserved_path'])) for r in signature['capability_files']}
    require(len(capabilities) == len(signature['capability_files'])
            and set(capabilities) == {r['path'] for r in allocation['allocation_evidence']}
            and all(file_sha(capabilities[r['path']]) == r['sha256'] for r in allocation['allocation_evidence']),
            'preserved_allocation_capability_inventory_changed')
    identity = read(folder/'IDENTITY.json')
    require(identity == dict(campaign=d['campaign'], kind=d['class_id'],
            declaration_sha256=signature['original_declaration_sha256'], trials=d['trials'],
            history='OBSERVER_V2: INVALID_PAIR', retries=0, replacements=0), 'campaign_ledger_authority_binding')
    events = Ledger(folder/'LEDGER.jsonl').events()
    starts = [r for r in events if r['event'] == 'STARTED']
    completed = [r for r in events if r['event'] == 'COMPLETE_VALID']
    overload = [r for r in events if r['event'] == 'DIAGNOSTIC_OVERLOAD']
    require([r['sequence'] for r in starts] == list(range(1,len(d['trials'])+1))
            and not any(r['event'] in ('INVALID','STOPPED') for r in events)
            and ((d['class_id'] == 'C' and not completed and len(overload) == 1)
                 or not overload and [r['sequence'] for r in completed] == list(range(1,len(d['trials'])+1))),
            'incomplete_or_consumed_invalid_campaign')
    require(all(r['details'] == dict(trial_id=t['trial_id'],mode=t['mode']) for r,t in zip(starts,d['trials'])),
            'campaign_started_trial_binding')
    trials = [verify_trial(folder/f't{r["sequence"]}',d,
              declaration_sha256=signature['original_declaration_sha256'], allocation=allocation, evidence_files=capabilities)
              for r in d['trials']]
    require(not overload or trials[0]['outcome'] == OVERLOAD and trials[0]['safety_only'] is True,
            'terminal_overload_requires_raw_native_proof')
    terminals = completed + overload
    original_root = Path(d['paths']['campaign_registry'])/d['campaign']
    for terminal, trial in zip(terminals,trials):
        require(terminal['details']['verification'] == trial
                and terminal['details']['raw_inventory_sha256'] == trial['raw_inventory_sha256'],
                'campaign_ledger_raw_verification_binding')
        receipt = read(folder/f'TRIAL-{terminal["sequence"]}-PRESERVATION.json')
        verify_publication(folder/f't{terminal["sequence"]}',receipt,name='RAW_INVENTORY.json',
                           expected_source=original_root/f't{terminal["sequence"]}')
    result = verify_observer(trials,d,verify_capacity_prerequisite(d,owner_key,allocation_key)) if d['class_id'] == 'B' else trials[0]
    require(read(folder/'VERIFICATION.json') == result, 'campaign_success_result_changed')
    preservation_receipt = preservation_receipt or original_root.with_name(d['campaign']+'.PRESERVATION.json')
    final = read(preservation_receipt)
    require(final['campaign'] == d['campaign'] and final['declaration_sha256'] == signature['original_declaration_sha256']
            and final['ledger_sha256'] == file_sha(folder/'LEDGER.jsonl'), 'campaign_preservation_authority_binding')
    verify_publication(folder,final,name='CAMPAIGN_INVENTORY.json',expected_source=original_root)
    return dict(result, class_id=d['class_id'], passed=True, campaign=d['campaign'],
                campaign_verified=True, preservation_verified=True,
                declaration_sha256=signature['original_declaration_sha256'],
                campaign_inventory_sha256=file_sha(folder/'CAMPAIGN_INVENTORY.json'))
