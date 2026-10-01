#!/usr/bin/env node
// Read-only audit of the pinned predecessor. No Python, workload or dispatch.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

function inspectPinnedSource(text, bytes, digest) {
  const checks=[];
  const check=(name,value)=>checks.push({name,passed:Boolean(value)});
  const fixed=text(".github/workflows/stagee-fixed-cohort.yml");
  const wrapper=text(".github/workflows/directional-six-regime-nonmarket.yml");
  const full=text(".github/workflows/non-market-certification.yml");
  const entry=text("certification/maintenance_qualification.py");
  const recovery=text("certification/cleanup_recovery.py");
  const promotion=text("certification/promote_phase_e.py");
  const dispatch=text("certification/dispatch_phase_e.py");
  const build=text("certification/build_consistency.py");
  const run=text("certification/run.py");
  const checkout=text("certification/single_campaign_control.py");
  const final=text("certification/final_acceptance.py");
  const observer=text("certification/lifecycle_capacity.py");
  const plan=JSON.parse(text("certification/stagee24_qualification_plan.json"));
  const request=JSON.parse(text(".github/stagee27/cohort-request.json"));
  const spec=JSON.parse(text("certification/sources.json"));
  const protocol=JSON.parse(text("certification/profitability_protocol.json"));
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const includes=(s,...needles)=>needles.every(x=>s.includes(x));
  check("workflow_text_has_no_tabs_or_conflict_markers",
    [fixed,wrapper,full].every(x=>!/\t|^<<<<<<<|^=======|^>>>>>>>/m.test(x)));
  check("canonical_wrapper_uses_local_reusable_workflow",
    wrapper.includes("uses: ./.github/workflows/non-market-certification.yml"));
  check("canonical_wrapper_forwards_expected_sha_and_preserved_scope",
    includes(wrapper,"expected_sha: ${{ inputs.expected_sha || '' }}","preserved_only: true"));
  check("canonical_branch_and_workflow_are_explicit",
    includes(dispatch,"WORKFLOW='directional-six-regime-nonmarket.yml'",
      "BRANCH='cert/autonomous-paper-machinery-20260927'"));
  const matrix=fixed.match(/^        trial: \[([^\]]+)\]$/m);
  check("fixed_matrix_matches_all_four_plan_trials",
    matrix && same(matrix[1].split(",").map(x=>x.trim()),plan.trials)
      && same(plan.trials,["combined-1","combined-2","combined-3","recovery-1"]));
  check("fixed_plan_preserves_workload_and_no_retry",
    plan.repeat_frames===2223 && plan.extended_frames===4445
      && plan.sample_wall_seconds===5 && same(plan.burst_source_seconds,[216,378])
      && plan.recovery_deadline_source_seconds===120
      && plan.requires_all_trials===true && plan.retry_until_pass===false
      && plan.market_authority===false && plan.observer_wall_fraction_limit===0.01);
  const planHash=digest(bytes("certification/stagee24_qualification_plan.json"));
  check("reviewed_publication_binds_exact_plan_bytes",planHash===request.plan_sha256);
  const frozenInputs=Object.entries({...plan.unchanged_inputs,...plan.observation_sources})
    .map(([path,expected])=>({path,expected,actual:digest(bytes(path))}))
    .map(row=>({...row,passed:row.expected===row.actual}));
  check("every_declared_frozen_input_matches",frozenInputs.length===12 && frozenInputs.every(x=>x.passed));
  check("fixed_trials_depend_on_preflight",fixed.includes("  trial:\n    needs: preflight\n"));
  check("fixed_jobs_checkout_event_sha",fixed.split("ref: ${{ github.sha }}").length-1===3);
  check("fixed_jobs_are_first_attempt_only",fixed.split('test "$GITHUB_RUN_ATTEMPT" = 1').length-1===3);
  check("fixed_workload_cannot_continue_after_error",
    fixed.includes("fail-fast: false") && !fixed.includes("continue-on-error"));
  check("preflight_records_commit_tree_parent_and_reviewed_files",
    includes(fixed,"HEAD^{tree}","request['expected_parent']","request['reviewed_files']",
      'test "$GITHUB_SHA" = "$EXPECTED_SHA"','test -z "$(git status --porcelain)"'));
  check("fixed_preflight_prepares_then_verifies_build",
    includes(fixed,"python -m certification.run prepare",
      "python -m certification.build_consistency verify",'--expected-sha "$GITHUB_SHA"'));
  check("fixed_trial_calls_predecessor_entrypoint",
    fixed.includes('python -m certification.maintenance_qualification --trial "$TRIAL"'));
  check("fixed_aggregate_uses_same_predecessor_context",
    includes(fixed,"from certification.maintenance_qualification import PLAN_PATH,frozen_inputs,qualification",
      "with qualification():result=cleanup_recovery.aggregate(root,sha)"));
  check("fixed_aggregate_retains_every_raw_artifact",
    includes(fixed,"for part in ['preflight',*plan['trials']]","_artifact_metadata(api,run_id,name)",
      "extract_artifact(api,reference,root/part)","os.environ['TRIAL_JOB_RESULT']=='success'"));
  check("predecessor_entrypoint_versions_plan_observer_and_acceptance",
    includes(entry,"stagee24_qualification_plan.json","original_frozen_inputs()",
      "patch.object(recovery,'BacklogObserver',LifecycleObserver)",
      "patch.object(recovery,'recovery_assessment',assessment)",
      "patch.object(legacy,'Interaction',Interaction)","original_extended_verified(row,frames)"));
  check("raw_trial_acceptance_binds_metadata_and_result_to_same_sha",
    includes(recovery,"metadata.get('plan_sha256')==plan_hash()",
      "metadata.get('integration_sha')==expected_sha and raw.get('integration_sha')==expected_sha",
      "missing_or_duplicate:"));
  check("promotion_reverification_uses_same_predecessor_plan_and_context",
    includes(promotion,"from certification.maintenance_qualification import PLAN_PATH, frozen_inputs, qualification",
      "with qualification():","cohort = cleanup_recovery.aggregate(cohort_root, sha)"));
  check("promotion_requires_completed_exact_sha_first_attempt_runs",
    includes(promotion,"row.get('head_sha') != sha","row.get('run_attempt') != 1",
      "row.get('conclusion') != 'success'","item.get('sha') != sha"));
  check("promotion_orders_full_verification_after_cohort",
    promotion.includes("cohort_end > build_start"));
  check("promotion_recomputes_full_acceptance_and_source_manifest",
    includes(promotion,"offline.get('implementation_hash') != implementation_hash()",
      "offline.get('source_manifest_hash') != digest(spec)",
      "final_acceptance.run(build_root, output / 'recomputed-build.json', sha, preserved_only=True)",
      "build != read(build_root / 'final-acceptance.json')"));
  check("promotion_rechecks_artifacts_after_read",
    includes(promotion,"phase_e_artifact_changed_during_verification",
      "successful_run(api, run_id, sha)"));
  check("one_shot_remote_intent_precedes_exact_push_and_dispatch",
    includes(promotion,"claim = reserve_intent(api, row)","push(sha, old_sha)",
      "result = dispatch.dispatch","'POST', 'git/refs'",
      "phase_e_intent_already_consumed_use_get_only"));
  check("promotion_cas_forbids_history_loss",
    includes(promotion,"'merge-base', '--is-ancestor'",
      "--force-with-lease=refs/heads/{dispatch.BRANCH}:{old_sha}"));
  check("dispatch_rejects_different_candidate_and_existing_runs",
    includes(dispatch,"if sha!=runtime:raise ValueError('canonical_sha_not_verified_candidate')",
      "canonical_branch_moved","canonical_sha_already_dispatched","store(intent,row,exclusive=True)"));
  check("canonical_run_binds_event_branch_attempt_and_reusable_shas",
    includes(dispatch,"row.get('head_sha')==sha and row.get('head_branch')==BRANCH",
      "row.get('event')=='workflow_dispatch' and row.get('run_attempt')==1",
      "workflow.get('sha')!=sha"));
  check("canonical_authority_requires_terminal_raw_artifact_review",
    includes(promotion,"def review_canonical(","canonical_workflow_failed",
      "phase_e_review_dispatch_not_unique","phase_e_review_canonical_branch_changed",
      "result.update(passed=True, canonical_authority=True, artifacts_verified=True"));
  check("complete_build_verifies_sha_sources_policy_imports_and_collections",
    includes(build,"build_integration_sha_drift","integration_integrity()",
      "source_integrity(worktrees)","protocol_verify()","build_import_shadow:",
      "native_test_collection(","'pump','meteora','pons','ramses'"));
  check("assembly_copies_and_stages_declared_integration_bytes",
    includes(run,"target.write_bytes((ROOT/rel).read_bytes())",
      "'git','add','--',str(rel)","source_changed_during_verification"));
  check("assembly_rejects_source_shadowing_unstaged_changes_and_diff_drift",
    includes(run,"unreviewed_lane_runtime_file:","worktree_head_drift:",
      "uncommitted_integration_overlay_file:","declared_overlay_diff_identity_mismatch:",
      "unreviewed_lane_mutation:","untracked_integration_source:"));
  check("promotion_checkout_hashes_committed_executable_and_configuration_blobs",
    includes(checkout,"def checkout_files(sha):","single_campaign_checkout_identity",
      "hashlib.sha1(b'blob '","single_campaign_uncommitted_runtime_configuration"));
  check("full_workflow_retains_broader_predecessor_gates",
    includes(full,"certification.run381_pressure --measured-contention",
      "certification.combined_observer","certification.joined_soak",
      "certification.joined_acceptance","certification.non_market",
      "certification.crash_matrix","certification.restart_safety",
      "certification.integrated_acceptance","certification.historical_resolution",
      "certification.directional_acceptance","certification.directional_preserved_validation",
      "certification.final_acceptance"));
  check("full_acceptance_uses_predecessor_combined_reader",
    final.includes("from certification.combined_observer import verified as combined_verified"));
  check("all_four_native_diff_bindings_match_protocol",
    Object.entries(spec.lanes).length===4
      && Object.entries(spec.lanes).every(([lane,row])=>
        row.source_diff_sha256===protocol.frozen_lanes[lane].source_diff_sha256));
  check("frozen_environment_versions_are_exact",
    includes(text("certification/qualification_environment.py"),
      "PYTHON='3.12.14'","DEPENDENCIES={'websockets':'17.1'}",
      "POLICY_PREDECESSOR='af60b355995dfa960555288fa73808bb7aba5d25'"));
  const findings=[
    {code:"REQUIRED_NATIVE_REVISION_NOT_EXPOSED",
      detected:![fixed,entry,promotion,JSON.stringify(plan),full,final].some(x=>
        /stage-e-native-transition-contract-v1|native-transition-cohort-v1|native-contract-held-reader-v1/.test(x)),
      effect:"Native implementation, plan schema, raw witness/reader verifier and deterministic tests are required."},
    {code:"PREDECESSOR_OBSERVER_ACCEPTS_EQUAL_LIMIT",
      detected:observer.includes("passed=ratio<=original.plan().get('observer_wall_fraction_limit',.01)"),
      effect:"The successor needs a newly applicable strict <1% exact-candidate measurement and boundary rejection tests."},
    {code:"TRIAL_EXECUTION_NOT_BOUND_TO_PREPARED_WORKTREES",
      detected:fixed.includes('python -m certification.maintenance_qualification --trial "$TRIAL" --output "$RUNNER_TEMP/cohort/$TRIAL"')
        && !entry.includes("--worktrees"),
      effect:"A different preflight job prepares assemblies; no trial consumed-assembly binding is established by this command."}
  ];
  return {
    schema:"stage-e-native-wiring-static-audit-v1",
    inspected_sha:"dc08f9064cf5e37b63f383f52aa709d0afc1723f",
    scope:"static_source_trace_only",
    static_assertions:checks,
    assertions_passed:checks.filter(x=>x.passed).length,
    assertions_total:checks.length,
    trace_passed:checks.every(x=>x.passed),
    plan_sha256:planHash,
    plan_version:plan.version,
    frozen_inputs:frozenInputs,
    findings,
    native_source_verified:false,
    future_same_sha_execution_guarantee_proved:false,
    qualification_wiring_ready:false,
    canonical_authority:false,
    market_authority:false,
    paper_only:true
  };
}

const sha = "dc08f9064cf5e37b63f383f52aa709d0afc1723f";
const cache = new Map();
const bytes = path => {
  if (!cache.has(path)) {
    cache.set(path, execFileSync("git", ["show", sha + ":" + path], {
      maxBuffer: 16 * 1024 * 1024
    }));
  }
  return cache.get(path);
};
const text = path => bytes(path).toString("utf8");
const digest = value => createHash("sha256").update(value).digest("hex");
const result = inspectPinnedSource(text, bytes, digest);
process.stdout.write(JSON.stringify(result, null, 2) + "\n");
process.exitCode = result.trace_passed ? 0 : 1;
