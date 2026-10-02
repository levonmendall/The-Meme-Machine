"""Build paper artifacts by reading frozen bytes. Never import/run the candidate."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/workspace/The-Meme-Machine-S')
S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
REVIEW = 'dd75942dcc7498156f80808397c594a6767871e9'
TERMINAL = 'a4fb375b6661637eda74acf17a5ebbc09f8ae06c'
DURABILITY = '5e6faa3033334a664cbdcc490f860735fd8148f9'
DECLARATION = '309e6f9dc11b4bb5e584937baecf4747f18d6047'
HISTORY = ROOT / 'evidence' / REVIEW / 'diagnostics/stage-e-observer-v2-self-hosted'


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def ref(path, symbol=None):
    record = read(ROOT / 'candidate_integrity_before.json')['tracked_files'][path]
    result = dict(commit=S, path=path, **record)
    if symbol:
        nodes = [n for n in ast.walk(ast.parse((SOURCE/path).read_bytes()))
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol]
        if len(nodes) != 1:
            raise ValueError('ambiguous source symbol ' + symbol)
        result.update(symbol=symbol, first_line=nodes[0].lineno, last_line=nodes[0].end_lineno)
    return result


def main():
    v2 = read(SOURCE/'certification/stage_e_native_v2/plan-v2.json')
    oldmap = read(SOURCE/'certification/stage_e_native_v2/gate-map-v2.json')
    observer = read(SOURCE/'certification/stage_e_native_v2/observer-contract-v2.json')
    tape = read(HISTORY/'TAPE.json')
    predecl = read(HISTORY/'PREDECLARATION.json')
    ledger = read(HISTORY/'LEDGER.json')
    terminal = read(ROOT/'evidence'/TERMINAL/'diagnostics/stage-e-observer-v2-self-hosted-execution/RESULTS.json')
    assert terminal == read(HISTORY/'RESULTS.json')
    assert ledger == terminal['ledger'] and terminal['outcome'] == 'INVALID_PAIR'
    assert ledger['started_trials'] == ledger['started_members'] == 1
    assert [x['status'] for x in ledger['slots']] == ['INVALID'] + ['UNUSED']*5
    assert ledger['retries'] == 0 and terminal['no_replacements'] and terminal['no_retries']
    declared_bytes = (HISTORY/'PREDECLARATION.json').read_bytes()
    for commit in (DECLARATION, DURABILITY, TERMINAL):
        assert (ROOT/'evidence'/commit/'diagnostics/stage-e-observer-v2-self-hosted-execution/PREDECLARATION.json').read_bytes() == declared_bytes
    assert digest(HISTORY/'PREDECLARATION.json') == ledger['declaration_sha256']
    assert set(v2['required_gates']) == {g['new_gate'] for g in oldmap['gates'] if g['required']}

    source_paths = [
        'certification/stage_e_native_v2/plan-v2.json', 'certification/stage_e_native_v2/gate-map-v2.json',
        'certification/stage_e_native_v2/GATE_MAP.md', 'certification/stage_e_native_v2/observer-contract-v2.json',
        'certification/stage_e_native_v2/observer.py', 'certification/stage_e_native_v2/contract.py',
        'certification/stage_e_native_v2/verify.py', '.github/workflows/stagee-native-qualification-v2.yml',
        '.github/workflows/stagee-native-qualification-v2-reusable.yml', 'certification/qualification_environment.py',
        'certification/maintenance_qualification.py', 'certification/run381_pressure.py',
        'certification/notes/run381-runtime-repair.md', 'certification/combined_pressure.py',
        'certification/combined_observer.py', 'certification/pressure_diagnostics.py',
        'certification/cleanup_recovery.py', 'certification/lifecycle_capacity.py',
        'certification/cleanup_recovery_plan.json', 'certification/stagee24_qualification_plan.json',
        'certification/stage_e_native_v2/fixtures.py', 'certification/stage_e_native_v2/material.py',
        'certification/stage_e_native_v2/fixtures/run373-v2.json',
        'certification/stage_e_native_v2/fixtures/run379-v2.json',
        'certification/stage_e_native_v2/fixtures/run380-v2.json',
        'certification/stage_e_native_v2/fixtures/run379-templates-v2.json.gz',
        'certification/stage_e_native_v2/fixtures/run380-templates-v2.json.gz',
        'certification/stage_e_native_v2/input-manifest-v2.json',
        'certification/stage_e_native_v2/dependency-lock-v2.json',
        'certification/stage_e_native_v2/trial-definition-v2.json',
        'certification/sources.json', 'certification/profitability_protocol.json',
        'meme_machine/solana_evidence_service.py', 'meme_machine/solana_evidence_plane.py',
        'meme_machine/solana_evidence_storage.py', 'meme_machine/solana_evidence_control.py',
        'meme_machine/solana_maintenance_runtime.py', 'meme_machine/solana_maintenance_state.py',
        'meme_machine/solana_archive_snapshot.py'
    ]
    write('consumed_sources.json', {'candidate_sha': S, 'candidate_tree': T,
        'sources': [ref(path) for path in source_paths], 'evidence_manifest': 'source_evidence_manifest.json',
        'all_candidate_files': 'candidate_integrity_before.json',
        'raw_artifact_downloaded': False,
        'raw_artifact_not_required_reason': 'Only published terminal classification, preservation receipts and workload definition are used; no member-level/root-cause inference.'})

    profile = v2['retained_material_contract']
    envelope = {
        'version': 'vendor-neutral-production-envelope-v3', 'allocated_vcpu': 2, 'dedicated_vcpu': 2,
        'executor_visible_vcpu': 2, 'effective_affinity_cpu_count': 2,
        'cpu_quota': 'Every effective ancestor unlimited or quota_us/period_us >= 2; complete ancestor inventory required',
        'cpu_allocation_rule': 'The measured executor allocation itself has exactly two dedicated vCPU. A >2-vCPU executor with taskset/quota=2 fails. A physical hypervisor host is not the measured VM allocation.',
        'ram_bytes': 8*1024**3,
        'ram_rule': 'Exactly 8 GiB allocated to the complete executor; OS/kernel memory included in that budget. Record usable RAM and all cgroup limits. An unlimited cgroup is permitted only within the attested 8-GiB executor. No >8-GiB allocation or restrictive ancestor may earn credit.',
        'no_competing_workload': True,
        'whole_scope': ['candidate owner', 'two shared spawn decode/archive workers', 'source feeder',
            'qualification observer when enabled', 'resource tracker', 'required verifier/receipt helpers'],
        'storage': {'required_free_headroom_bytes': 12*1024**3,
            'check_boundaries': ['before preparation', 'before each member', 'during member', 'before durable archive/advance'],
            'total_capacity_requirement': '>= 12 GiB remaining usable headroom + immutable tape 2442975789 bytes + retained prior evidence + working DB/WAL/archive + simultaneously required publication copies; record all actual byte counts and reserve before advancing',
            'filesystem_requirements': 'Native SQLite locking/transaction/WAL behavior, file and parent-directory fsync, durable content-addressed archive publication; no tmpfs durability substitute',
            'insufficient_storage': 'Stop, preserve failure, no next member/slot; never delete sole evidence or loosen candidate storage limits'},
        'runtime': {'python': '3.12.14', 'websockets': '17.1',
            'dependency_lock': ref('certification/stage_e_native_v2/dependency-lock-v2.json'),
            'tooling_dependencies': v2['tooling_dependencies'],
            'platform': 'CPython 3.12 Linux x86_64; reviewed v2 dependency file lock unchanged',
            'freeze_before_execution': ['Python executable/shared library', 'stdlib and extensions',
                'websockets installed files', 'SQLite version/library', 'OS/kernel/libc',
                'required OS tools', 'external harness/verifier source and bindings']},
        'evidence': {'boundaries': ['admission', 'every spawn/thread admission', 'continuous monitored scope', 'teardown'],
            'required': ['dedicated allocation capability attestation', 'visible CPU inventory and topology',
                'complete effective cpusets and per-thread affinity', 'all ancestor quotas/cgroup paths',
                'memory allocation, usable RAM and ancestor limits', 'swap/ballooning status; no substitute RAM',
                'no competing workload evidence', 'storage mount/device/free/total/physical durability',
                'runtime/dependency/tool manifests', 'generation and monotonic timestamps'],
            'hashing': 'Canonical SHA-256 of complete environment manifest and resource timeline; every raw result binds the same frozen manifest',
            'missing_changed_or_ambiguous': 'BLOCK_OR_INVALIDATE; no inferred resource credit from CPU labels or cpu_count alone'}
    }
    write('production_envelope.json', envelope)

    clock = dict(v2['clock_domains'])
    clock.update(execution='After frozen setup, anchor once at first source-data release; wall=1800000000+real_elapsed_ns/1e9; monotonic=100+real_elapsed_ns/1e9; no pause/time compensation',
        scheduler='OS/event-loop waits use real clocks. Immutable source/economic timestamps never change on receive.',
        audit_origin={'commit': REVIEW, 'path': 'diagnostics/stage-e-observer-v2-self-hosted/SEMANTIC_CLOCK_AUDIT.json',
            'sha256': digest(HISTORY/'SEMANTIC_CLOCK_AUDIT.json')})
    tape_binding = {k: tape[k] for k in ('cadence_us', 'wall_epoch', 'monotonic_epoch', 'transaction_mix',
        'physical_sha256', 'physical_bytes', 'frame_inventory_sha256', 'members', 'decoded_format', 'format')}
    tape_binding.update(generator_source={'commit': REVIEW, 'path': 'diagnostics/stage-e-observer-v2-self-hosted/infra/tape.py',
        'sha256': digest(HISTORY/'infra/tape.py'), 'symbol': 'extended_frame', 'frame_index_bounds': [0, 4444]},
        fixture_source=ref('certification/stage_e_native_v2/fixtures.py'),
        template=ref('certification/stage_e_native_v2/fixtures/run380-templates-v2.json.gz'),
        spec=ref('certification/stage_e_native_v2/fixtures/run380-v2.json'),
        native_prefix_equivalence_frames=240,
        expected_bytes_status='Exact hashes from frozen published tape/proof metadata; tape payload not downloaded or generated in this static task. Authorized admission must verify actual bytes against these identities.',
        frame_formula='slot=1000+n; parent=slot-1; blockhash=h{slot}; previous=h{slot-1}; event/blockTime=int(1800000000+n*270000/1000000-1); native timed_transaction helpers; 512 transactions per frame; no receive-time retiming')
    cohort = [{'id': m['id'], 'frames': m['frames'], 'source_duration_us': m['frames']*270000,
        'ordered_frame_indices': [0, m['frames']-1], 'transactions': m['frames']*512,
        'initial_state': 'Fresh isolated empty native DB/WAL/archive directory; no pre-existing candidate/lifecycle pins; independently frozen setup; no extra seed frames',
        'input_binding': m} for m in tape['members']]
    source_deltas = {'owner_seconds_per_frame': 0, 'archive_seconds_per_thousand': 0,
        'additional_commit_latency_seconds': 0, 'source_pause_frames': [],
        'held_reader_injected_sleeps_seconds': [], 'completed_tail_injected_delay_seconds': 0}
    common = {'candidate_sha': S, 'candidate_tree': T, 'execution_authorized': False,
        'resource_envelope': 'production_envelope.json', 'clock': clock, 'tape_binding': tape_binding,
        'cohort': cohort, 'worker_limits': {'shared_spawn_pool': 2, 'archive_futures': 1,
            'extra_archive_pools': 0, 'owner_queue_entries': 64, 'urgent_reserved_entries': 8},
        'native_work': 'Use unmodified ServiceState.source_batch, EvidenceWriter.prepare_and_write_archive and native SQLite commits/fsync. No measured-contention class/pool/commit injector in production capacity or either observer arm.',
        'candidate_local_read_schedule': 'One in-flight real RuntimeEvidence check after >10 accepted frames, at most every 10 real seconds; ack then native windows across all three scopes, as original run381 candidate()',
        'urgent_ack_schedule': 'Existing real local-IPC acknowledgement coroutine, one-second real intervals once source >10 frames; >=10 successes and no errors for each mature member',
        'source_release_schedule': 'Exactly n*270000 microseconds after first release; catch up to original due times after real scheduler stalls without rebasing deadlines',
        'common_safety_monitoring': 'Original .25-second poll of native counters, source frontier, unresolved gaps, global hot/retained minimum age and DB+WAL; common to both observer arms, never disable native health checks',
        'member_deadline': 'Original native loop deadline frames*.27+120 real seconds; outer child timeout frames*.27+240 plus bounded termination cleanup as frozen v2 external trial. No grant from either deadline overriding <45/<240 safety.',
        'verification': 'Native current-S archive/body/hash/lineage verification, SQLite integrity, exact input receipts and admitted drain, committed source/maintenance progress and all unchanged safety predicates. External v3 only changes classified harness/performance predicates.',
        'post_failure': 'No continuation/retry/replacement; stop and join helpers, preserve DB/WAL/archive and receipts with fsynced inventory before terminal stop.'}
    capacity = dict(deepcopy(common), version='production-capacity-workload-v3',
        workload_identity='production-equivalent-full-cohort-v3', class_id='A',
        qualification_observer='disabled; minimum common safety checks and durable native evidence remain',
        artificial_contention=source_deltas,
        source_frames_total=sum(m['frames'] for m in cohort),
        source_duration_total_us=sum(m['source_duration_us'] for m in cohort),
        sequential_members=True, required_all_members=True,
        predecessor_full_shape_cases=[{'id': run+'-full-v3', 'spec': ref('certification/stage_e_native_v2/fixtures/'+run+'-v2.json'),
            'unchanged_spec': read(SOURCE/'certification/stage_e_native_v2/fixtures'/ (run+'-v2.json')),
            'purpose': 'Retain full predecessor shape/economic clock requirements, separately admitted on the same exact two-vCPU envelope; no throughput inferred from modeled clock execution'}
            for run in ('run373','run379','run380')],
        current_source_seeding='run379 alone retains all 100x160 historical seed transactions, fixed epoch-185 schedule, linked empty block1100 at epoch, then all 120x160 execution frames. Other cases start empty. Historical seeds are not current source authority.',
        full_shape_schedule='The four mature members use the common270000-us cadence. Each additional run373/run379/run380 case uses its own unchanged spec.cadence_us (750000/50000/270000), exact full native generator inputs and frozen historical seed schedule, with real-speed post-release clocks; no source-shape reduction or modeled-time capacity credit.',
        acceptance='All four mature members and all three retained full-shape cases valid on exact declared envelope; source lag strictly <45, both residence ages strictly <240, all production safety/integrity/storage/worker/durability/native identity requirements satisfied. A larger machine or synthetic-stress result cannot earn this gate.',
        measured_capacity_result='NOT_RUN', source_reference_profile=profile)
    write('production_capacity_workload.json', capacity)
    observer_workload = dict(deepcopy(common), version='observer-overhead-workload-v3',
        workload_identity='production-equivalent-full-cohort-v3', class_id='B',
        prerequisite='Fresh native production-capacity-v3 PASS including this exact four-member baseline workload, S/T/resource/runtime identities; no historical or larger-executor credit. Standalone capacity qualification is a separate gate, not an observer warmup.',
        artificial_contention=source_deltas, pair_count=3,
        modes=['baseline','observed','observed','baseline','baseline','observed'],
        repetition_policy=observer['repetition_policy'], no_replacements=True, no_warmups=True,
        baseline='Same production-equivalent workload; qualification observation disabled; common safety checks/receipts/native durability enabled',
        observed='Only read-only qualification observation enabled: eligibility/current committed counters and LifecycleObserver recovery-1 at five-second wall intervals; no synthetic readers/tail delays added. Required native lifecycle evidence, origins, joins and persistence included.',
        observation_validity='Zero observer errors; >=30 advancing recovery-1 samples; each scope strict<240 age, no active pins or unresolved gaps in the no-pin fixture, finite nonnegative debt samples, monotonic native ingested/archived/retired/continuity counters and committed archive/retirement progress. Preserve separate lifecycle short-reader wall fraction<=.01. Compute original pure assessment within measured time, but its burst/old-cohort stress-performance subresults are C diagnostics: A/B must not demand manufactured burst/reader/cohort eligibility to call a capacity-valid baseline valid.',
        qualification_snapshot_schedule='At the fixed216/378 source-second landmarks record read-only native eligibility/current counters, without holding manufactured readers. LifecycleObserver samples only recovery-1 every5 real seconds. All qualification reads and pure assessments are observed-arm costs; common safety polling stays identical.',
        timing=predecl['timing'], metric=observer['metric'], estimator=observer['estimator'],
        acceptance='Every baseline and observed member passes common native capacity/safety validation. Three complete valid equal-workload pairs in fixed order. positive baseline_ns; observed_ns>=baseline_ns retained from v2; exact sum differences and positive denominator; numerator*100 < denominator. Equality, incomplete pair, stale/cross-generation/resource/input binding or invalid baseline blocks the measurement.',
        native_verification='New v3 verifier identity, frozen externally before execution, rechecks all raw receipts and exact binding then retains the arithmetic/type/validity predicates of S observer.py; never submit new results as v2 historical evidence.',
        future_campaign_namespace='stage-e-native-v3-observer-{fresh-declaration-sha256}',
        existing_slots_reusable=False, measured=False)
    write('observer_workload.json', observer_workload)
    stress = dict(deepcopy(common), version='run381-adversarial-stress-workload-v3',
        workload_identity='run381-fullcert-36293751021-adversarial-v3', class_id='C',
        resource_policy='Default same two-vCPU envelope; separately declared larger-machine diagnostics are permitted only after authorization and earn zero production-capacity/observer credit',
        artificial_contention={'owner_seconds_per_frame': .165, 'archive_seconds_per_thousand': .36,
            'additional_commit_latency_seconds': .006, 'source_pause_frames': [800,1400],
            'source_pause_seconds': 8, 'burst_source_seconds': [216,378],
            'held_reader_injected_sleeps_seconds': [1.25,.1], 'completed_tail_injected_delay_seconds': .75},
        source_profile_refs=[ref('certification/run381_pressure.py'), ref('certification/pressure_diagnostics.py'),
            ref('certification/combined_pressure.py'), ref('certification/combined_observer.py')],
        qualification_observer='Original durable-window-v4 and joint-eligible-hot-archive-retirement-v2; no start-phase-only overlap credit',
        recovery_plan=read(SOURCE/'certification/stagee24_qualification_plan.json'),
        exact_recovery_predicates={'assessment': ref('certification/lifecycle_capacity.py','assessment'),
            'debt_series': ref('certification/lifecycle_capacity.py','_recovery_series'),
            'fixed_cohort': ref('certification/cleanup_recovery.py','recovery_assessment')},
        accepted_outcomes=['FULL_PROFILE_SAFETY_PASS', 'DIAGNOSTIC_OVERLOAD_WITH_NATIVE_FAIL_CLOSED_PROOF'],
        full_profile='All original profile/interaction coverage, source-lag/residence/debt recovery/progress predicates remain as separately reported strict stress results. Never convert a failed original stress predicate into a passed historical result.',
        overload='Record every original failed predicate and raw incomplete member. Synthetic performance failure remains FAILED_DIAGNOSTIC, with no capacity credit. Mandatory stress safety can pass only with exact native proof of threshold-triggered refusal/stop, bounded workers/queues/storage, no corruption/hidden gaps/lost or duplicate committed work, durable restart/receipt/ledger continuity, no policy/trade authorization from stale data. Wrapper-only stop is not native fail-closed proof. Missing proof or any native safety violation is safety failure and keeps Stage E RED.',
        retirement_on_overload='Preserve existing lifecycle/account/gap pins and recovery deadlines; do not force retirement, re-enroll episodes, change origin timestamps or remove protected evidence to satisfy age.',
        required_stress_safety=True, production_minimum_cpu_inference_from_artificial_delays=False,
        executed=False)
    write('adversarial_stress_workload.json', stress)

    classification = {'version':'run381-component-classification-v3', 'source_sha': S,
        'components':[
            {'id':'owner-floor', 'value_seconds':.165, 'unit':'source frame', 'classification':'EXECUTOR_NORMALIZATION_TEST_ONLY',
             'production_semantic':False, 'production_safety_limit':False,
             'mechanism':'MeasuredServiceState.source_batch calls native super().source_batch(items), then time.sleep(max(0,.165*len(items)-elapsed)). Batch occupancy floor, not added CPU instruction cost.',
             'source':ref('certification/run381_pressure.py','MeasuredServiceState'),
             'rationale':'Rounded up from ~.163 s/frame measured in full certificate 36293751021 to prevent fast hosted hardware hiding contention; notes explicitly state production has no artificial delays.',
             'A_B':'native source_batch, floor zero', 'C':'exact floor retained'},
            {'id':'archive-floor', 'value_seconds':.36, 'unit':'1000 actually prepared archived records', 'classification':'EXECUTOR_NORMALIZATION_TEST_ONLY',
             'production_semantic':False, 'production_safety_limit':False,
             'mechanism':'measured_archive performs native prepare_and_write_archive first, then sleeps max(0,.36*len(result[0])/1000-elapsed). MeasuredProcessPool substitutes only that callable in the existing pool.',
             'source':ref('certification/run381_pressure.py','measured_archive'),
             'rationale':'Rounded up from ~.358 s/1000 prepare/publication wall time in certificate 36293751021; production snapshot/hash/compression/fsync work itself remains mandatory.',
             'A_B':'native archive job on the same two spawn workers; floor zero', 'C':'exact floor retained'},
            {'id':'commit-pad', 'value_seconds':.006, 'unit':'COMMIT for a transaction whose total_changes changed after BEGIN', 'classification':'EXECUTOR_NORMALIZATION_TEST_ONLY',
             'production_semantic':False, 'production_safety_limit':False,
             'mechanism':'SQLTimings TimedConnection records total_changes on BEGIN; for SQL exactly COMMIT with changed total_changes it measures injected_commit_wait around sleep(.006), BEFORE executing the real COMMIT. Additive sleep, not a floor or fsync replacement.',
             'source':ref('certification/pressure_diagnostics.py','SQLTimings'),
             'activation':ref('certification/run381_pressure.py','run'),
             'rationale':'run381 comments compare 37.84 ms for six commits in 36297528197 with 2.82 ms in 36302144874 and round the per-commit difference upward; no source establishes a required production dwell time.',
             'A_B':'no injected_commit_wait; real COMMIT/fsync and all SQLite durability remain', 'C':'exact additive pad retained'},
            {'id':'real-owner-archive-commit-work', 'classification':'PRODUCTION_SEMANTIC',
             'mechanism':'Native decode/source commit, pin recheck, bounded archive prepare/hash/fsynced publication, native SQLite transaction, retirement/floor publication, lifecycle/priority/durability/recovery behavior',
             'A_B_C':'unchanged; no candidate edits'},
            {'id':'source-lag-and-residence-bounds', 'classification':'PRODUCTION_SAFETY_LIMIT',
             'values':{'source_lag':'<45 s','hot_residence':'<240 s','retained_residence':'<240 s','retention':'180 s'},
             'A_B_C':'identical limits; synthetic overload must refuse/stop safely, never grant stale acceptance'},
            {'id':'SQLTimings-and-process-profile', 'classification':'DIAGNOSTIC_INSTRUMENTATION',
             'mechanism':'bounded wall/thread CPU SQL/stage summaries, process/CPU/environment samples; the .1-second maximum injector input is a diagnostic configuration guard, not a production limit',
             'source':ref('certification/pressure_diagnostics.py'), 'A_B':'extra SQL timing wrappers disabled in both arms unless identical bound common evidence is separately declared; no subtraction', 'C':'historical instrumentation retained'},
            {'id':'source-pause-and-catchup', 'classification':'ADVERSARIAL_TEST_ONLY',
             'mechanism':'Pause before frames800/1400 for 8 real seconds; preserve original timestamps and release schedule; cancellation cannot erase pause',
             'source':ref('certification/combined_pressure.py','run'), 'A_B':'no deliberate pauses', 'C':'retained; source outages are separately tested safety obligations'},
            {'id':'held-reader-waits', 'classification':'ADVERSARIAL_TEST_ONLY',
             'mechanism':'Native SQLite read snapshot held across sleep1.25, actual native checkpoint, sleep.1; observe durable counters before rollback',
             'source':ref('certification/combined_observer.py','Interaction'), 'A_B':'no manufactured reader occupancy', 'C':'retained; checkpoint safety also retained in native held-reader bounded gate'},
            {'id':'completed-tail-delay', 'classification':'ADVERSARIAL_TEST_ONLY',
             'mechanism':'sleep.75 only after a genuinely complete PASSIVE checkpoint receipt; never falsify receipt or add owner-side work',
             'source':ref('certification/combined_pressure.py','Interaction'), 'A_B':'zero', 'C':'retained'},
            {'id':'fixed-source-cadence-and-input-retiming', 'classification':'PRODUCTION_REPRESENTATIVE_INPUT_MODEL',
             'mechanism':'.27-second fixed input cadence and pure preconstruction of fixture event times; external immutable tape bypasses recv retimer; clocks advance at real speed after first release',
             'source':ref('certification/run381_pressure.py','Wire'), 'A_B_C':'cadence/bytes preserved; no runtime retiming'},
            {'id':'poll-query-ack-and-log-cadence', 'classification':'DIAGNOSTIC_INSTRUMENTATION_AND_DECLARED_CONTROL_LOAD',
             'mechanism':'.25 s common safety poll; 10 s candidate queries; 1 s urgent local ACK loop; 30 s driver reports; optional bounded diagnostics; qualification observer5 s. These are measurement/control schedules, not CPU-normalization floors.',
             'A_B':'same common monitoring/control load; only qualification reads differ by arm', 'C':'original schedules retained'}],
        'rationale_source':ref('certification/notes/run381-runtime-repair.md'),
        'production_import_audit':'No run381/MeasuredServiceState/MeasuredProcessPool/SQLTimings or floor-constant reference in candidate meme_machine/*.py; deterministic AST/text tests recheck this.',
        'completeness':'All three run381 measured-contention injections and all combined reader/tail/pause injections are explicitly classified; real production delays/cadences are never globally zeroed.'}
    write('contention_classification.json', classification)

    safety = {'version':'unchanged-production-safety-ledger-v3','changes':[],
        'limits':{
            'source_lag_seconds':{'operator':'<','value':45,'domain':'projected wall minus immutable finalized block time'},
            'hot_age_seconds':{'operator':'<','value':240,'domain':'wall minus original market_time; first_seen only when no market_time'},
            'retained_age_seconds':{'operator':'<','value':240,'domain':'same original age over ALL retained rows, including archived index rows'},
            'retention_seconds':180,'hot_db_wal_bytes':{'operator':'<','value':2*1024**3},
            'dispatch_frames_max':64,'dispatch_bytes_max':96*1024**2,
            'commit_messages_max':8,'commit_bytes_max':16*1024**2,'source_message_bytes_max':16*1024**2,
            'prepared_decode_bytes_max':16*1024**2,'protocol_queue_frames':32,
            'shared_decode_archive_workers':2,'archive_futures_max':1,'extra_archive_pools':0,
            'owner_queue_capacity':64,'urgent_reserved':8,'archive_snapshot_records_max':1000,
            'archive_snapshot_target_bytes':4*1024**2,'archive_snapshot_hard_encoded_bytes':20*1024**2,
            'archive_commit_slice_records':512,'retention_slice_records_max':256,
            'gap_repair_pages_max':16,'gap_repair_attempts_max':48,
            'storage_warning_bytes':512*1024**2,'storage_critical_bytes':128*1024**2,
            'source_idle_seconds':20,'commit_stall_seconds':15,
            'command_attempt_seconds':.5,'command_seconds':3,'max_command_bytes':32768,'max_command_receipts':8192,
            'declared_member_storage_headroom_bytes':12*1024**3,
            'recovery_deadline_source_seconds':120,'pipeline_slack_records':1000,
            'minimum_decline_records':256,'trend_slack_records':256,
            'advancing_recovery_samples_min':30,'burst_window_samples_min':3,'tail_half_samples_min':10,
            'qualified_observer_pair_overhead':{'operator':'<','value':.01},
            'legacy_lifecycle_observer_wall_fraction':{'operator':'<=','value':.01,'scope':'separate short read-only sample cost, not substitute paired measurement'}},
        'nonnumeric_invariants':['zero corruption; verify native archive/body hashes and lineage',
            'zero unresolved gaps/capacity disconnects during valid production execution; explicit shutdown boundaries never represent live coverage',
            'exact received==committed==source_frames+1 admitted drain',
            'linked source order/finality; no receive-time freshness substitution',
            'active candidate/open/reserved/account/gap pins survive; no forced premature deletion',
            'only committed native archive/retirement/receipt/floor/service credit; no attempted credit',
            'generation fencing, restart ledger and latched origin/deadline survive without reenrollment',
            'complete held-reader snapshot identity and actual checkpoint blocking/release/completion proof',
            'urgent priority0/1 precedence, zero urgent errors, all three scopes progress',
            'count provider/DNS/network attempts before access; zero attempts for qualification',
            'all previously required resource/RSS, integrated/current-policy, four-lane/six-regime, prepared-source, crash and eight-day gates remain required via full gate map',
            'stale/missing/contradictory evidence or threshold equality fail closed'],
        'before_and_after_thresholds_identical':True,
        'authority':[ref('certification/stage_e_native_v2/plan-v2.json'),ref('certification/stage_e_native_v2/gate-map-v2.json'),
            ref('certification/combined_pressure.py'),ref('certification/combined_observer.py'),
            ref('certification/lifecycle_capacity.py'),ref('meme_machine/solana_evidence_service.py'),
            ref('meme_machine/solana_evidence_plane.py'),ref('meme_machine/solana_evidence_storage.py'),ref('meme_machine/solana_evidence_control.py'),ref('meme_machine/solana_archive_snapshot.py')],
        'comparators':'Strict v2 successor residence <240 takes precedence over legacy <=240 helpers. Paired <1% unchanged. Separate legacy lifecycle read-wall <=1% retained explicitly.',
        'stress_witness_lower_bounds':'dispatch_peak>=16, commit_peak>=2 and synthetic backpressure/tail counters are adversarial coverage witnesses, not production resource maxima. Retained exactly in C; A/B allow valid native single-message progress with identical safety maxima.'}
    write('safety_ledger.json', safety)

    changed = {
        'mature_solana_pressure-v2':('SPLIT_CAPACITY_AND_STRESS','All mature capacity members on exact two-vCPU/eight-GiB envelope without synthetic floors; original run381 profile separately retained in C.'),
        'combined_mature_solana_pressure-v2':('SPLIT_CAPACITY_AND_STRESS','Native production work in A/B; two pauses/readers/tail interference and original coverage predicates retained in C.'),
        'resource_bounds-v2':('STRENGTHENED_BINDING','Retain predecessor native resource/RSS bounds plus exact declared allocation, ancestor quota/affinity/RAM/isolation/headroom/runtime bindings. >2 executor fails A/B.'),
        'cohort-complete-v2':('SEPARATED_COHORTS','All four capacity members required; all six observer trials/three valid pairs required; all stress members/failed attempts preserved, with overload safely terminal rather than capacity credit.'),
        'pressure-profile-v2':('SPLIT_NATIVE_AND_SYNTHETIC','A/B floors zero; unmodified native work. C exact owner/archive/changed-COMMIT sleep profile. No new hardware-minimum inference.'),
        'burst-schedule-v2':('MOVED_ADVERSARIAL_INJECTION','Exact pause frames800/1400,8 seconds,216/378 source seconds retained in C. A/B original fixed clocks/cadence without deliberately injected outages.'),
        'recovery-v2':('SPLIT_PERFORMANCE_AND_SAFETY','Exact120-second/1000/256/256 recovery and latched native origin retained. Original burst recovery predicates reported in C. A/B no-pin age/progress cannot be waived. Overload safety requires unchanged native refusal/restart/pins.'),
        'fixed-old-cohort-v2':('RETAINED_IN_STRESS','Exact frozen old-slot cutoff/cohort and clearance during advancing source retained in C full-profile diagnostic and native bounded recovery obligations; never relabel failed cleanup as passed.'),
        'debt-tails-v2':('RETAINED_IN_STRESS','Exact5-second/30 advancing/>=3 windows/>=10 tail halves and debt inequalities retained in C; A/B preserve residence and committed maintenance progress on real production-equivalent input.'),
        'frame-byte-bounds-v2':('SPLIT_SAFETY_AND_COVERAGE','A/B dispatch1..64 and commits1..8 with original byte maxima; C retains dispatch16..64, commit2..8 and backpressure coverage. Lower bounds only exercise synthetic queue/batching, never tighten production minimum CPU.'),
        'urgent-source-fairness-v2':('SPLIT_NATIVE_AND_INTERFERENCE','>=10 real urgent ACKs, zero errors, source order and all-scope native progress retained in A/B/C; durable reader-overlap stress witnesses retained in C.'),
        'joint-lifecycle-v2':('SPLIT_CAPACITY_OBSERVATION_AND_STRESS','Retain native committed archive/retirement/generation/floor/pin bounds, strict ages and all-scope progress. Original burst/debt sampling/assessment in C and read-only qualification costs in B. No stage credit from missing baseline observation.'),
        'observer-v2':('RESOURCE_BOUND_SUCCESSOR','Three fixed-order pairs; no retries/replacements/warmups; exact equal work/resource/clock boundaries; native verification; original integer estimator and strict<1%; prerequisite A PASS; new namespace, old INVALID_PAIR sealed.'),
        'workflow-identity-v2':('SEPARATE_CANDIDATE_AND_EXTERNAL_CONTRACT','Candidate source origins remain exact S/T. Existing deterministic v2 workflow hashes unchanged. Future v3 external harness/control workflow has separate exact immutable identity and reviewed binding; no workflow from different source can masquerade as candidate S.'),
        'assembly-origin-v2':('EXTERNAL_V3_ORIGIN_BINDING','All candidate/child/dynamic origins and before/after assembly integrity retained. External v3 contract/harness/verifier has separate frozen hashes; no overlay or patch to candidate source files.'),
        'artifact-provenance-v2':('APPEND_ONLY_SUCCESSOR_PROVENANCE','Retain first-attempt raw IDs/hashes/run/attempt, reread receipt and immutable failures. New v3 namespace rejects all historical slot IDs and measurements; v2 evidence read-only.'),
    }
    gates=[]
    for g in oldmap['gates']:
        key=g['new_gate']; treatment,criteria=changed.get(key,('RETAINED_UNCHANGED',g['equivalence_or_strength']))
        gates.append({'predecessor_gate':key,'successor_gate':key[:-3]+'-v3','required':g['required'],
            'treatment':treatment,'acceptance':criteria,'predecessor_row':g,
            'source_gate_map':ref('certification/stage_e_native_v2/gate-map-v2.json'),
            'safety_delta':'NONE; exact native predicates/thresholds in safety_ledger.json retained',
            'execution_now':'NOT_AUTHORIZED','acceptance_evidence_now':'NOT_RUN',
            'phase':'C' if key in ('burst-schedule-v2','fixed-old-cohort-v2','debt-tails-v2') else 'B' if key=='observer-v2' else 'A/B/C or retained predecessor proof',
            'native_verifier_obligation':'Fresh exact-S native witness/receipts/origins and same-semantic verifier; all generic predecessor acceptance expressions stay required, including historical inputs and full prepared lane tests. No fixture-only throughput/economic credit.'})
    extras=[{'successor_gate':'production-envelope-capacity-v3','required':True,'acceptance':capacity['acceptance']},
        {'successor_gate':'synthetic-stress-safety-v3','required':True,'acceptance':stress['overload']+' Full-profile predicate success remains separate diagnostics.'},
        {'successor_gate':'historical-observer-seal-v3','required':True,'acceptance':'All 159 consumed evidence files and exact v2 candidate files unchanged; original INVALID_PAIR, one started trial/member, five UNUSED, zero retries/replacements, zero earned overhead retained; no slot IDs reused.'}]
    write('gate-map-v3.json',{'version':'stage-e-predecessor-v2-successor-v3-gate-map','predecessor_sha':S,
        'predecessor_required_count':len(v2['required_gates']),'gates':gates,'additional_gates':extras,
        'required_gates':[r['successor_gate'] for r in gates if r['required']]+[r['successor_gate'] for r in extras],
        'dropped_gates':[],'unmapped_required_gates':[],'execution_authorized':False})
    rows=['# Stage-E native v2 → v3 gate map','',f'Authority: exact candidate `{S}` / tree `{T}`. Every one of the 44 required v2 gates is mapped. PAPER ONLY; no execution acceptance earned.','',
        '| v2 gate | v3 gate | Treatment | Exact acceptance delta / preservation |','|---|---|---|---|']
    rows += ['| '+r['predecessor_gate']+' | '+r['successor_gate']+' | '+r['treatment']+' | '+r['acceptance']+' |' for r in gates]
    rows += ['', 'All native thresholds/definitions are preserved in safety_ledger.json. Synthetic coverage predicates remain in the stress class and cannot substitute for production acceptance. gate-map-v3.json includes complete original rows and source hashes.','']
    (ROOT/'GATE_MAP.md').write_text('\n'.join(rows))

    deltas=[{'id':'S1','change':'Exact 2 dedicated vCPU / 8 GiB capacity and observer allocation; >2 executor rejected even quota/affinity-limited'},
        {'id':'S2','change':'Separate production-capacity prerequisite before observer campaign; every baseline/observed member must remain capacity-valid'},
        {'id':'S3','change':'Test-only owner/archive floors and additive changed-transaction COMMIT pad excluded from A/B; real operations untouched; retained exactly in C'},
        {'id':'S4','change':'Manufactured source pauses, held-reader sleeps and completed-tail delay moved to C; A/B identical fixed production-equivalent release schedule without injected interference'},
        {'id':'S5','change':'Synthetic queue/batch minimum-peak and backpressure/tail coverage retained in C; A/B enforce the same upper safety bounds without requiring manufactured queue occupancy'},
        {'id':'S6','change':'Original stress recovery/debt predicates retained as strict diagnostics; mandatory stress acceptance requires native fail-closed/integrity/durability/pin/restart proof if synthetic overload occurs; no production CPU inference from that overload'},
        {'id':'S7','change':'Complete hashed resource/environment/external v3 harness/verifier/workflow identity binding beside unchanged candidate S/T and native origins'},
        {'id':'S8','change':'Fresh v3 namespace and slots; preserve all historical v2 failure/evidence and forbid reuse of its five UNUSED slots'}]
    write('acceptance_semantic_changes.json',{'version':'v2-v3-acceptance-semantic-delta','changes':deltas,
        'changed_predecessor_gates':sorted(changed),'production_safety_limit_changes':[],
        'strategy_economic_policy_changes':[], 'observer_arithmetic_order_threshold_changes':[],
        'justification':'Measured floors are expressly diagnostic normalization and absent from production. Pause/read/tail injections and minimum-peak counters are synthetic interference coverage. All such coverage is preserved explicitly, all native safety bounds stay identical, and production capacity must pass independently on the actual deployment envelope.'})
    policy = read(SOURCE/'certification/profitability_protocol.json')
    write('policy_conservation.json',{'version':'strategy-economic-conservation-proof-v3',
        'candidate_sha':S,'candidate_tree':T,'proof':'Every one of 1241 tracked candidate files is hashed against the exact git tree before/after; no candidate diff, source overlay, configuration or economic policy edit. v3 files and history snapshots are outside candidate checkout.',
        'entire_candidate_manifest':'candidate_integrity_before.json','after_verification':'preservation_verification.json',
        'source_manifest':ref('certification/sources.json'),'economic_protocol':ref('certification/profitability_protocol.json'),
        'frozen_lanes':policy['frozen_lanes'],'frozen_strategies':policy['frozen_strategies'],
        'directional_sleeves':policy['directional_sleeves'],
        'economic_acceptance_authority':'Entire unchanged profitability_protocol.json, including every lane/portfolio/autonomy requirement; synthetic throughput gives no market/economic/promotion credit.',
        'changes':[],'basis_not_stale_BUILD_STATUS_policy':'Exact S protocol and full candidate tree are authority; old BUILD_STATUS milestone prose does not replace current six-regime hashes.'})
    slots=[row['id'] for row in predecl['trials']]
    history={'version':'immutable-observer-v2-seal-v3','outcome':'OBSERVER_V2: INVALID_PAIR',
        'review_commit':REVIEW,'terminal_commit':TERMINAL,'durability_commit':DURABILITY,'predeclaration_commit':DECLARATION,
        'workflow_run':37021065563,'attempt':1,'started_trials':1,'started_members':1,'unused_slots':5,
        'retries':0,'replacement_trials':0,'complete_valid_pairs':0,'observer_overhead_earned':False,
        'numerator_ns':None,'denominator_ns':None,'ratio':None,
        'declaration_sha256':digest(HISTORY/'PREDECLARATION.json'),
        'terminal_result_sha256':digest(ROOT/'evidence'/TERMINAL/'diagnostics/stage-e-observer-v2-self-hosted-execution/RESULTS.json'),
        'durability_receipt_sha256':digest(ROOT/'evidence'/DURABILITY/'diagnostics/stage-e-observer-v2-self-hosted-execution/TRIAL-1-DURABILITY.json'),
        'raw_artifact':{'id':11233586036,'sha256':'8cb1e6e7294feb2075918bd344e0f46f161e54b8afe5f088af81308c4455c6dc','downloaded':False},
        'raw_tar_sha256':'6dfb54fb59b94fb6542d53a1227f36f18a3410bf95c8e67686cef57cc187cd0a',
        'all_old_trial_ids_forbidden':slots,'unused_slot_sequences_forbidden':[2,3,4,5,6],
        'new_v3_slots':[],'new_trials_started':0,'reuse_allowed':False,
        'proof':'Published terminal/result/ledger/stop and immutable predeclaration/durability commit bytes agree. Independent SHA-256/git-blob verification for all consumed snapshots; no writes to historical commit objects or candidate files; successor declaration must use disjoint namespace/IDs.',
        'root_cause':'NOT_ESTABLISHED; incomplete origins_valid/tape_valid do not independently identify bad import, changed tape, synthetic cost failure or insufficient real production capacity.',
        'full_snapshot_manifest':'source_evidence_manifest.json'}
    write('historical_observer_seal.json',history)
    plan={'plan_version':'stage-e-native-production-envelope-plan-v3','contract_version':'stage-e-native-production-envelope-contract-v3',
        'candidate_sha':S,'candidate_tree':T,'required_gates':[r['successor_gate'] for r in gates]+[r['successor_gate'] for r in extras],
        'phase_order':['static/source review','ASTRA/OWNER stop','separately authorized A capacity','separately authorized B observer after A','separately authorized C diagnostic/safety and retained predecessor gates','ASTRA/OWNER qualification decision'],
        'current_authorization':{'paper_only':True,'stage_e':'RED','stage_f':'NOT STARTED','material_capacity':False,'observer_campaign':False,'stress_campaign':False,'provider_access':False,'runtime_or_market':False},
        'rollback':'No current candidate change exists to roll back. If the proposed contract is rejected, leave S/T and historical v2 results intact and supersede only external v3 paper files. Never revert to v2 unused slots as a fallback. Future interruption/failure halts qualification, preserves evidence and native state/pins/ledger; restart never credits incomplete service or rebases clocks/deadlines.',
        'execution_readiness_prerequisites':['ASTRA/owner approval of contract semantics',
            'separate explicit material execution authorization', 'reviewed exact external v3 harness/verifier implementation; production source remains S/T',
            'actual dedicated resource attestation and frozen runtime/environment manifest',
            'actual tape bytes verified against frozen hashes before any source release',
            'fresh successor predeclaration/slots and before/after origin/resource/evidence bindings'],
        'static_review_can_earn_capacity_or_stage_e':False}
    write('plan-v3.json',plan)
    contract={'contract_id':'stage-e-native-production-envelope-contract-v3','version':3,'predecessor':'stage-e-native-transition-contract-v2',
        'document_state':'SOURCE_GROUNDED_PENDING_STATIC_VALIDATION','stage_e':'RED','stage_f':'NOT STARTED',
        'execution_authorized':False,'review_ready':False,'candidate_sha':S,'candidate_tree':T,
        'production_envelope':'production_envelope.json', 'production_capacity':'production_capacity_workload.json',
        'observer_overhead':'observer_workload.json','synthetic_stress':'adversarial_stress_workload.json',
        'required_gates':plan['required_gates'],'gate_map':'gate-map-v3.json','safety_ledger':'safety_ledger.json',
        'classification':'contention_classification.json','semantic_delta':'acceptance_semantic_changes.json',
        'policy_proof':'policy_conservation.json','history_seal':'historical_observer_seal.json',
        'source_identities':'consumed_sources.json','source_audit_complete':True,'unresolved_source_bindings':[],
        'governance':{'append_only_successor':True,'mutate_candidate':False,'historical_slots_reusable':False,
            'static_tests_can_turn_stage_e_green':False,'review_ready_authorizes_execution':False,'next_authority':'ASTRA/OWNER'},
        'scope_note':'Paper native-v3 contract design and pure static predicates only. No v3 workload runner or material workflow is installed or launched. Execution readiness is a distinct future authorization/implementation stage.'}
    write('contract.json',contract)


if __name__ == '__main__':
    main()
