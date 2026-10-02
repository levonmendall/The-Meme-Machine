"""Preview construction and independently signed, future execution admission."""
from pathlib import Path

from attest import admission_errors, signed_document
from binding import infrastructure_identity
from core import (ASSEMBLY, CONTRACT_COMMIT, CONTRACT_MANIFEST_SHA, INFRA, MODES, ROOT,
                  S, T, canonical, contract_file, file_sha, read, require, sha, workload)
from ledger import trial_matrix

TIMING = dict(start='before isolated trial-process startup and complete-cohort setup',
              end='after all four members, observer joins, teardown, persistence and helper termination',
              clock='time.perf_counter_ns', subtraction=False, double_counting=False, uploads_inside=False)
STOP_RULES = ['resource admission or continuity failure', 'strict safety equality or excess',
              'missing/changed origin, tape, generation, raw receipt or prerequisite',
              'provider or DNS attempt', 'invalid baseline/member/pair or interruption',
              'any retry/replacement or insufficient storage', 'missing native overload-safety proof']
PRESERVATION = ['consume slot before process startup', 'stop qualification; join helpers',
                'preserve DB/WAL/archive/pins/gaps/ledger/raw receipts',
                'fsync files and parent directories; hash exact inventory',
                'read back redundant durable copy; retain local copy',
                'no advancement after failure; no sole evidence deletion']


def preview(kind, campaign, *, executor, environment, workflow, paths, allocation=None,
            storage_bounds=None, prerequisites=None, trust_keys=None):
    spec = workload(kind)
    infra = infrastructure_identity()
    trial_rows = trial_matrix(campaign, kind)
    verifier = dict(path=str(INFRA/'verify.py'), sha256=file_sha(INFRA/'verify.py'),
                    infrastructure_digest=infra['digest'])
    return dict(version='stage-e-native-v3-executable-declaration', disposition='NOT AUTHORIZED / PREVIEW ONLY',
        execution_authorized=False, paper_only=True, stage_e='RED', stage_f='NOT STARTED',
        candidate_sha=S, candidate_tree=T, contract_commit=CONTRACT_COMMIT,
        contract_manifest_sha256=CONTRACT_MANIFEST_SHA, assembly_digest=ASSEMBLY,
        class_id=kind, campaign=campaign, trials=trial_rows, modes=list(MODES) if kind == 'B' else [trial_rows[0]['mode']],
        retries=0, replacements=0, warmups=0, timing=TIMING, stop_rules=STOP_RULES,
        preservation_rules=PRESERVATION, executor=executor, environment=environment,
        environment_sha256=sha(canonical(environment)), workflow=workflow,
        paths=paths, allocation=allocation, storage_bounds=storage_bounds,
        prerequisites=prerequisites or {}, trust_keys=trust_keys or {},
        infrastructure=infra, verifier=verifier, tape_binding=spec['tape_binding'],
        workload_sha256=sha(canonical(spec)), production_workload_sha256=sha(canonical(workload('A'))),
        historical_seal_sha256=sha(canonical(contract_file('historical_observer_seal.json'))),
        actual_slots_reserved=False, source_frames_released=0)


def authorize(declaration_path, owner_permit_path, owner_key, *, kind):
    """The review package contains no owner permit or trusted signing identity."""
    d = read(declaration_path)
    require(d.get('execution_authorized') is True and d.get('disposition') == 'AUTHORIZED PAPER EXECUTION',
            'NOT_AUTHORIZED_PREVIEW_ONLY')
    require(d.get('actual_slots_reserved') is False and d.get('source_frames_released') == 0, 'declaration_already_consumed')
    require(d['candidate_sha'] == S and d['candidate_tree'] == T and d['class_id'] == kind
            and d['contract_commit'] == CONTRACT_COMMIT and d['contract_manifest_sha256'] == CONTRACT_MANIFEST_SHA
            and d['assembly_digest'] == ASSEMBLY, 'declaration_source_identity')
    require(d['paper_only'] is True and d['stage_e'] == 'RED' and d['stage_f'] == 'NOT STARTED', 'execution_scope')
    require(d['trials'] == trial_matrix(d['campaign'], kind) and d['retries'] == d['replacements'] == d['warmups'] == 0,
            'declared_trial_identity')
    require(d['timing'] == TIMING and d['stop_rules'] == STOP_RULES and d['preservation_rules'] == PRESERVATION,
            'declaration_rules_changed')
    spec = workload(kind)
    require(d['workload_sha256'] == sha(canonical(spec)) and d['tape_binding'] == spec['tape_binding']
            and d['production_workload_sha256'] == sha(canonical(workload('A'))), 'declaration_workload_changed')
    require(d['historical_seal_sha256'] == sha(canonical(contract_file('historical_observer_seal.json'))), 'history_seal_changed')
    infra = infrastructure_identity()
    require(d['infrastructure'] == infra and d['verifier']['sha256'] == file_sha(INFRA/'verify.py')
            and d['verifier']['infrastructure_digest'] == infra['digest'], 'harness_or_verifier_drift')
    require(d['environment_sha256'] == sha(canonical(d['environment'])), 'environment_manifest_changed')
    permit = signed_document(owner_permit_path, owner_key, d['trust_keys']['owner_public_key_sha256'])
    expected = dict(version='stage-e-native-v3-owner-execution-permit',
        declaration_sha256=file_sha(declaration_path), class_id=kind, campaign=d['campaign'],
        workflow=d['workflow'], executor_id=d['executor']['executor_id'],
        paper_only=True, stage_f_authorized=False, provider_authorized=False)
    require(permit == expected, 'owner_permit_not_exact_declaration')
    w = d['workflow']
    require(w.get('event') == 'workflow_dispatch' and type(w.get('attempt')) is int and w['attempt'] == 1
            and w.get('repository') == 'levonmendall/The-Meme-Machine'
            and bool(w.get('run_id')) and bool(w.get('resolved_workflow_commit'))
            and w.get('workflow_path') == '.github/workflows/stagee-native-v3-material.yml'
            and file_sha(w['local_workflow_path']) == w['workflow_sha256'], 'future_material_workflow_identity')
    require(not Path(w['local_workflow_path']).read_text().find('NOT AUTHORIZED / PREVIEW ONLY') >= 0,
            'preview_workflow_cannot_authorize')
    # Actual workflow environment cannot be replaced by fields supplied in JSON.
    import os
    require(os.environ.get('GITHUB_REPOSITORY') == w['repository']
            and os.environ.get('GITHUB_RUN_ID') == str(w['run_id'])
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
            and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_SHA') == w['resolved_workflow_commit'], 'actual_workflow_run_mismatch')
    return d
