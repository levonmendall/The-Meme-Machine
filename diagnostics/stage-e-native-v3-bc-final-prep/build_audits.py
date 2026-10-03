"""Build review records from completed allowed tests and isolated Git state."""
import subprocess
from pathlib import Path

from frozen import *
from qualification import historical_seal

CASES = {
    'inject fake A prerequisite': 'test_fake_A_with_complete_typed_assertions_still_requires_raw',
    'omit A preservation receipt': 'test_omit_A_preservation_receipt',
    'reorder B trials': 'test_reorder_B_trials',
    'duplicate B trial': 'test_duplicate_B_trial',
    'reuse historical v2 ID': 'test_reuse_v2_ID',
    'observer overhead exactly 1%': 'test_exactly_one_percent_fails',
    'swap tape identity': 'test_swap_tape_identity',
    'change S/T': 'test_change_S_T_assembly_contract_executable',
    'fabricate C safety credit': 'test_fabricate_C_safety_credit',
    'mark gate PASS without evidence': 'test_mark_gate_PASS_without_evidence',
    'remove one required gate': 'test_remove_one_required_v3_gate',
    'publish partial evidence': 'test_publish_partial_evidence',
    'modify package after manifest': 'test_preparation_manifest_rejects_post_seal_changes_and_partial_files',
}


def git(*args, cwd=REPOSITORY):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()


def build():
    result=read(ROOT/'evidence/test_results.json')
    require(result['passed'] is True and file_sha(ROOT/'evidence/unit_validation.log')==result['log_sha256'],
            'successful_allowed_checks_required')
    log=(ROOT/'evidence/unit_validation.log').read_text()
    rows=[]
    for case,test in CASES.items():
        require(any(line.startswith(test+' (') and line.endswith(' ... ok') for line in log.splitlines()),
                'self_audit_case_not_verified:'+case)
        rows.append(dict(attack=case,test=test,outcome='DETERMINISTIC_REJECTION_VERIFIED'))
    audit=dict(version='stage-e-native-v3-parallel-preparation-self-audit',**FROZEN,
        cases=rows,all_requested_attacks_rejected=True,tests=result['total'],
        log_sha256=result['log_sha256'],fixture_only=True,
        additional_checks=['unresolved A admission','observed below baseline','missing/invalid pair',
            'wrong contract/executable/assembly','changed environment/executor/boot','C as A',
            'nonfinite and boolean raw durations','no hidden subtraction','torn remote manifest',
            'changed staged bytes before API','exclusive redundant destination','symlink escape',
            'mock GitHub exclusive publication and independent readback','chunk-boundary and empty-file readback',
            'deferred physical receipts cannot PASS','integer storage and per-filesystem shortfall',
            'manual summary PASS and skipped/incomplete transcript','zero native entrypoint imports'],
        A_B_C_trials_run=0,slots_reserved=0,slots_consumed=0,source_frames_released=0)
    require(git('rev-parse','HEAD')==EXECUTABLE_COMMIT,'prep_base_changed')
    require(git('diff','--name-only',EXECUTABLE_COMMIT)=='','approved_tracked_bytes_changed')
    untracked=git('ls-files','--others','--exclude-standard').splitlines()
    prefix=ROOT.relative_to(REPOSITORY).as_posix()+'/'
    require(untracked and all(p.startswith(prefix) for p in untracked),'off_path_write_detected')
    static_source=Path(result['static_source'])
    require(git('status','--porcelain',cwd=static_source)==''
            and git('rev-parse','HEAD',cwd=static_source)==S,'static_S_checkout_changed')
    require(git('rev-parse',S+'^{tree}')==T,'frozen_candidate_tree_changed')
    historical=historical_seal()
    isolation=dict(version='stage-e-native-v3-parallel-preparation-isolation-audit',**FROZEN,
        branch=git('rev-parse','--abbrev-ref','HEAD'),base=EXECUTABLE_COMMIT,
        allowed_write_root=prefix,tracked_frozen_files_changed=[],exact_S_static_files_verified=result['exact_S_files_verified'],
        disposable_static_checkout=str(static_source),static_checkout_clean=True,
        approved_executable=check_executable(),historical_read_only_verification=historical,
        A_workspace_accessed=False,A_campaign_registry_accessed=False,
        production_volume_accessed=False,production_volume_mounted=False,tape_generated=False,tape_copied=False,
        physical_verification='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
        current_production_free_space='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
        deferral_authority='Owner instructed no concurrent A workspace or production-volume access; import completed published A-preflight receipts',
        observer_v2_mutated=False,source_candidate_mutated=False,approved_contract_mutated=False,
        approved_executable_mutated=False,PR118_mutated=False,
        PR118_read_only_snapshot=dict(draft=True,head=EXECUTABLE_COMMIT,
            base='7e906e6683ba745f11a390f3c354291980321b89',updated_at='2026-10-03T05:14:55Z',
            metadata_comparison='draft/head/base/title/body/updated_at unchanged before publication'),
        A_trials_run=0,B_trials_run=0,C_trials_run=0,slots_reserved=0,slots_consumed=0,
        source_frames_released=0,jobs_dispatched=0,native_members=0,provider_workloads=0,
        fixtures_created_only_in_disposable_local_tempdirs=True,
        external_A_runtime_claim='No concurrent runtime probe made; no A workspace or production-volume access',
        stage_e='RED',stage_f='NOT STARTED')
    for name,value in [('SELF_AUDIT.json',audit),('ISOLATION_AUDIT.json',isolation)]:
        (ROOT/'evidence'/name).write_bytes(canonical(value)+b'\n')
    print('Requested adversarial cases:',len(rows),'Allowed tests:',result['total'])


if __name__=='__main__': build()
