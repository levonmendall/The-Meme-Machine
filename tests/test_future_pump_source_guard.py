"""Exact future isolation layer before the unchanged Pump restoration guards.

This is test-only source authentication, not runtime source approval or native
readiness. Final identities are populated only after the corpus source freeze.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
BASE='780f4015efd9fba528e97223f8e8e3b1a7322e12'
IMPLEMENTATION='3465199505c5d56f0bb4de2e67fdf73d2563f366'
IMPLEMENTATION_TREE='bd2fde2607e485ee35a3092a48069ac379d17b52'
MANIFEST=ROOT/'tests/fixtures/future_pump_source_delta.json'
MANIFEST_SHA256='ad6e14adc8c6ad0c4a86f6f3ab2425d3ae94a79d4625a273d12e8f0e0cfce3be'
PATHS=('meme_machine/lanes/pons/immutable_rpc.py',
 'meme_machine/lanes/pons/pons_selective_acquisition.py',
 'meme_machine/lanes/pons/pons_selective_capital.py',
 'meme_machine/lanes/pons/pons_selective_cohort.py',
 'meme_machine/lanes/pons/pons_selective_ledger.py',
 'meme_machine/lanes/pons/pons_selective_v4.py',
 'meme_machine/lanes/pons/pons_survivor_runtime.py',
 'meme_machine/lanes/pons/provider.py',
 'meme_machine/lanes/pons/provider_admission.py',
 'meme_machine/lanes/pons/provider_topology.py',
 'meme_machine/lanes/pons/sequencer_feed.py',
 'meme_machine/lanes/pump/concentration.py',
 'meme_machine/lanes/pump/paper_accounting.py',
 'meme_machine/lanes/pump/postgrad.py',
 'meme_machine/lanes/pump/provider.py',
 'meme_machine/lanes/pump/pumpswap_survivor_runtime.py',
 'meme_machine/lanes/pump/runner.py',
 'meme_machine/lanes/pump/solana_evidence_runtime.py',
 'meme_machine/lanes/pump/solana_immutable_rpc.py',
 'meme_machine/lanes/pump/solana_read_rpc.py',
 'meme_machine/operational/bounded_provider.py',
 'meme_machine/operational/lane.py',
 'meme_machine/portfolio_accounting.py',
 'meme_machine/runtime/candidate_history.py',
 'meme_machine/runtime/directional_sleeve.py',
 'meme_machine/runtime/evidence_worker.py',
 'meme_machine/runtime/governor.py',
 'meme_machine/runtime/native_boundary.py',
 'meme_machine/runtime/portfolio.py',
 'meme_machine/runtime/request_scheduling.py',
 'meme_machine/runtime/robinhood/plane.py',
 'meme_machine/runtime/robinhood/pons.py',
 'meme_machine/runtime/sleeve_reservations.py',
 'meme_machine/runtime/survivor_history.py',
 'meme_machine/runtime/survivor_paper_book.py',
 'meme_machine/shared_capital/authority.py',
 'meme_machine/shared_capital/native_sleeve.py',
 'meme_machine/shared_capital/runtime.py',
 'meme_machine/solana_checkpoint.py',
 'meme_machine/solana_evidence_service.py',
 'meme_machine/solana_history_work.py',
 'meme_machine/solana_selective_source.py')
UNCHANGED=('meme_machine/solana_evidence_storage.py',
    'meme_machine/runtime/candidate_restore_reads.py','requirements.txt')
DEPENDENCY_PATHS=('meme_machine/lanes/pons/rpc_profile.py',
 'meme_machine/operational/child_transport.py',
 'meme_machine/operational/isolated_native_entry.py',
 'meme_machine/operational/isolated_native_image.py',
 'meme_machine/operational/isolated_native_image_probe.py',
 'meme_machine/operational/isolated_native_kernel_corpus.py',
 'meme_machine/operational/isolated_native_kernel_parent.py',
 'meme_machine/operational/isolated_native_kernel_solana.json',
 'meme_machine/operational/isolated_native_kernel_validation.py',
 'meme_machine/operational/isolated_native_landlock_image.py',
 'meme_machine/operational/isolated_native_landlock_launcher.py',
 'meme_machine/operational/isolated_native_launcher.py',
 'meme_machine/operational/isolated_native_layout.py',
 'meme_machine/operational/isolated_native_lifetime.py',
 'meme_machine/operational/isolated_native_pons_kernel_corpus.py',
 'meme_machine/operational/isolated_native_source.py',
 'meme_machine/operational/native_landlock_policy.py',
 'meme_machine/operational/parent_channel.py',
 'meme_machine/operational/parent_head_lifecycle.py',
 'meme_machine/operational/parent_sizing.py',
 'meme_machine/operational/parent_transport.py',
 'meme_machine/operational/pons_native_profile.py',
 'meme_machine/operational/source_ports.py',
 'meme_machine/operational/transport_bridge.py',
 'meme_machine/runtime/isolated_native_admission.py',
 'meme_machine/runtime/isolated_native_bootstrap.py',
 'meme_machine/runtime/isolated_native_control.py',
 'meme_machine/runtime/isolated_native_execution.py',
 'meme_machine/runtime/isolated_native_executor.py',
 'meme_machine/runtime/isolated_native_liveness.py',
 'meme_machine/runtime/isolated_native_resources.py',
 'meme_machine/runtime/isolated_native_spawn.py',
 'meme_machine/runtime/isolated_pons_current.py',
 'meme_machine/runtime/market_heads.py',
 'meme_machine/runtime/native_commit_measurement.py')
DELETED_PATHS=()
LEGACY_GUARDS=('tests/test_pump_restore_source_guard.py','tests/test_robinhood_usd_valuation.py')
CALLER_MANIFEST=ROOT/'tests/fixtures/future_source_callers.json'
CALLER_MANIFEST_SHA256='74bcfbcba5d917a2bb9c2c9a187544f5164d52845337d6a364b7693186f16967'
EXTERNAL_CALLERS=('tests/test_extended_survivor_hold_research.py','tests/test_forward_survivor.py',
    'tests/test_long_duration_positions.py','tests/test_pons_owner_admission.py',
    'tests/test_robinhood_scout.py','tests/test_shared_capital_strategy.py',
    'tests/test_solana_history_separation.py')
LEGACY_MODULES=tuple(path[:-3].replace('/','.') for path in LEGACY_GUARDS)
CALLER_IMPORT=b'from tests.test_future_pump_source_guard import future_pump_predecessor\n'
IMPORTS={name:'from tests.test_future_pump_source_guard import future_pump_predecessor\n'
    for name in LEGACY_GUARDS}
# These are active file reads only. No original predecessor implementation,
# intermediate source, mutation, expected node, constant or assertion changes.
WRAPPERS={'tests/test_pump_restore_source_guard.py': (('(ROOT/HELPER).read_bytes()',
                                              'future_pump_predecessor(self,HELPER,(ROOT/HELPER).read_bytes())',
                                              1),
                                             ('(ROOT/PATHS[0]).read_bytes()',
                                              'future_pump_predecessor(self,PATHS[0],(ROOT/PATHS[0]).read_bytes())',
                                              2),
                                             ('(ROOT/PATHS[2]).read_bytes()',
                                              'future_pump_predecessor(self,PATHS[2],(ROOT/PATHS[2]).read_bytes())',
                                              1),
                                             ('(ROOT/relative).read_bytes()',
                                              'future_pump_predecessor(self,relative,(ROOT/relative).read_bytes())',
                                              3),
                                             ("(ROOT/row['path']).read_bytes()",
                                              "future_pump_predecessor(self,row['path'],(ROOT/row['path']).read_bytes())",
                                              1)),
 'tests/test_robinhood_usd_valuation.py': (("(ROOT/'tests/test_operational_nine.py').read_bytes()",
                                            "future_pump_predecessor(self,'tests/test_operational_nine.py',(ROOT/'tests/test_operational_nine.py').read_bytes())",
                                            1),
                                           ('(ROOT/RESTORED_HISTORY_HELPER).read_bytes()',
                                            'future_pump_predecessor(self,RESTORED_HISTORY_HELPER,(ROOT/RESTORED_HISTORY_HELPER).read_bytes())',
                                            1),
                                           ('(ROOT/path).read_bytes()',
                                            'future_pump_predecessor(self,path,(ROOT/path).read_bytes())',
                                            1),
                                           ('(ROOT/relative).read_bytes()',
                                            'future_pump_predecessor(self,relative,(ROOT/relative).read_bytes())',
                                            32),
                                           ('(ROOT/relative).read_bytes()',
                                            'future_pump_predecessor(test,relative,(ROOT/relative).read_bytes())',
                                            1))}
ACTIVE_READS={'tests/test_pump_restore_source_guard.py': [(35,
                                              'authenticated_helper',
                                              '(ROOT/HELPER).read_bytes()',
                                              'HELPER',
                                              'test',
                                              False),
                                             (75,
                                              'PumpRestoreSourceGuardTests.test_all_three_complete_sources_and_added_helper_are_exactly_authenticated',
                                              '(ROOT/relative).read_bytes()',
                                              'relative',
                                              'self',
                                              True),
                                             (83,
                                              'PumpRestoreSourceGuardTests.test_legacy_guard_file_reverses_only_ten_active_reads_and_one_import',
                                              "(ROOT/row['path']).read_bytes()",
                                              "row['path']",
                                              'self',
                                              True),
                                             (110,
                                              'PumpRestoreSourceGuardTests.test_only_declared_restoration_and_codec_nodes_change',
                                              '(ROOT/PATHS[2]).read_bytes()',
                                              'PATHS[2]',
                                              'self',
                                              True),
                                             (117,
                                              'PumpRestoreSourceGuardTests.test_partial_reversal_added_source_and_unreviewed_bytes_never_pass',
                                              '(ROOT/relative).read_bytes()',
                                              'relative',
                                              'self',
                                              True),
                                             (145,
                                              'PumpRestoreSourceGuardTests.test_integrity_cancellation_default_economics_and_codec_mutations_are_refused',
                                              '(ROOT/relative).read_bytes()',
                                              'relative',
                                              'self',
                                              True),
                                             (152,
                                              'PumpRestoreSourceGuardTests.test_complete_helper_pin_refuses_any_budget_path_hash_or_owner_mutation',
                                              '(ROOT/HELPER).read_bytes()',
                                              'HELPER',
                                              'self',
                                              True),
                                             (164,
                                              'PumpRestoreSourceGuardTests.test_complete_helper_pin_refuses_any_budget_path_hash_or_owner_mutation',
                                              '(ROOT/PATHS[0]).read_bytes()',
                                              'PATHS[0]',
                                              'self',
                                              True),
                                             (172,
                                              'PumpRestoreSourceGuardTests.test_manifest_mutations_and_unknown_source_are_not_new_exemptions',
                                              '(ROOT/PATHS[0]).read_bytes()',
                                              'PATHS[0]',
                                              'self',
                                              True)],
 'tests/test_robinhood_usd_valuation.py': [(1919,
                                            'guarded_source',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'test',
                                            True),
                                           (2124,
                                            'restored_provider_history_predecessor',
                                            '(ROOT/RESTORED_HISTORY_HELPER).read_bytes()',
                                            'RESTORED_HISTORY_HELPER',
                                            'test',
                                            False),
                                           (2914,
                                            'RobinhoodUSDTests.test_cross_candidate_archive_review_keeps_all_previous_source_guards',
                                            '(ROOT/path).read_bytes()',
                                            'path',
                                            'self',
                                            True),
                                           (2990,
                                            'RobinhoodUSDTests.test_source_recorder_publication_reverses_only_exact_diagnostic_transport_and_test_read',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3010,
                                            'RobinhoodUSDTests.test_source_recorder_publication_reverses_only_exact_diagnostic_transport_and_test_read',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3027,
                                            'RobinhoodUSDTests.test_sleeve_empty_prefix_reverses_only_exact_optional_compaction_scheduling',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3068,
                                            'RobinhoodUSDTests.test_archive_log_order_reverses_only_exact_distinct_post_prefix_sequence_match',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3111,
                                            'RobinhoodUSDTests.test_provider_budget_namespace_read_reverses_only_exact_phase_sql_pushdown',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3141,
                                            'RobinhoodUSDTests.test_pump_cost_environment_reverses_only_exact_opt_in_lane_tuple',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3235,
                                            'RobinhoodUSDTests.test_publication_accounting_turn_preserves_durable_delta_cancellation_and_passive_pump_costs',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3278,
                                            'RobinhoodUSDTests.test_buffered_origin_geometry_preserves_unique_full_obligation_and_original_authority',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3300,
                                            'RobinhoodUSDTests.test_buffered_prejoin_replay_preserves_original_partition_and_full_ack_authority',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3410,
                                            'RobinhoodUSDTests.test_retained_path_factoring_preserves_original_source_guards',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3435,
                                            'RobinhoodUSDTests.test_pump_restore_archive_reuse_preserves_fresh_authority_and_cancellation',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3500,
                                            'RobinhoodUSDTests.test_preparation_replay_preserves_terminal_incident_and_original_full_ack_authority',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3580,
                                            'RobinhoodUSDTests.test_source_parent_drain_preserves_exact_timeouts_identity_and_financial_guards',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3692,
                                            'RobinhoodUSDTests.test_canonical_cold_reader_preserves_exact_locator_and_authenticated_archive_authority',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3721,
                                            'RobinhoodUSDTests.test_pump_restore_selection_reverses_only_three_fixed_index_declarations',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3763,
                                            'RobinhoodUSDTests.test_prejoin_observation_preserves_exact_incident_gaps_and_full_ack_authority',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3867,
                                            'RobinhoodUSDTests.test_maintenance_entry_clock_preserves_exact_original_leases_and_native_guards',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3891,
                                            'RobinhoodUSDTests.test_survivor_increment_continuity_reverses_only_exact_required_window_precheck',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3941,
                                            'RobinhoodUSDTests.test_archive_log_consistency_reverses_only_exact_zero_match_rejection',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (3985,
                                            'RobinhoodUSDTests.test_retained_archive_log_shape_reverses_only_exact_join_and_receipt_metadata',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4035,
                                            'RobinhoodUSDTests.test_session_economic_recovery_preserves_original_incidents_and_exact_full_proofs',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4107,
                                            'RobinhoodUSDTests.test_frozen_paused_reader_preserves_original_financial_and_native_proof',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4153,
                                            'RobinhoodUSDTests.test_retained_canonical_reference_reverses_only_exact_reader_compatibility',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4193,
                                            'RobinhoodUSDTests.test_recovered_economic_boundary_preserves_failed_census_and_all_previous_guards',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4253,
                                            'RobinhoodUSDTests.test_archive_complete_logs_reverse_exactly_and_reject_unverified_source',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4288,
                                            'RobinhoodUSDTests.test_native_startup_failure_delta_preserves_all_prior_authority_and_source_guards',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4307,
                                            'RobinhoodUSDTests.test_survivor_monitor_replay_delta_preserves_fresh_proof_and_exact_prior_economics',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4332,
                                            'RobinhoodUSDTests.test_program_gap_boundary_reverses_exactly_without_weakening_recovery_or_funding',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4375,
                                            'RobinhoodUSDTests.test_startup_history_cancellation_reverses_only_exact_reviewed_sources',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4394,
                                            'RobinhoodUSDTests.test_exact_restored_history_delta_preserves_original_supervisor_and_helper',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4405,
                                            'RobinhoodUSDTests.test_exact_restored_history_delta_preserves_original_supervisor_and_helper',
                                            '(ROOT/RESTORED_HISTORY_HELPER).read_bytes()',
                                            'RESTORED_HISTORY_HELPER',
                                            'self',
                                            True),
                                           (4417,
                                            'RobinhoodUSDTests.test_rally_source_layer_reverses_exactly_and_rejects_unreviewed_bytes',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (4430,
                                            'RobinhoodUSDTests.test_rally_added_policy_and_cycle_sources_have_exact_identities',
                                            '(ROOT/relative).read_bytes()',
                                            'relative',
                                            'self',
                                            True),
                                           (5160,
                                            'RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged',
                                            "(ROOT/'tests/test_operational_nine.py').read_bytes()",
                                            "'tests/test_operational_nine.py'",
                                            'self',
                                            True)]}


def _sha(body):return hashlib.sha256(body).hexdigest()


def manifest(test):
    for value in (IMPLEMENTATION,IMPLEMENTATION_TREE):
        test.assertIsInstance(value,str,'future corpus must be explicitly frozen')
        test.assertRegex(value,'^[0-9a-f]{40}$')
    raw=MANIFEST.read_bytes()
    test.assertEqual(_sha(raw),MANIFEST_SHA256,'complete reviewed future manifest')
    value=json.loads(raw)
    test.assertEqual(set(value),{'schema','base','implementation','implementation_tree',
        'files','dependencies','unchanged','deleted','legacy_guards'})
    test.assertEqual(value['schema'],'authenticated-future-pump-source-delta-v1')
    test.assertEqual((value['base'],value['implementation'],value['implementation_tree']),
        (BASE,IMPLEMENTATION,IMPLEMENTATION_TREE))
    test.assertEqual(set(value['files']),set(PATHS))
    test.assertEqual(set(value['dependencies']),set(DEPENDENCY_PATHS))
    test.assertEqual(set(value['unchanged']),set(UNCHANGED))
    test.assertEqual(tuple(value['deleted']),DELETED_PATHS)
    test.assertEqual(set(value['legacy_guards']),set(LEGACY_GUARDS))
    return value


def _authenticated_file(test,relative,record):
    body=(ROOT/relative).read_bytes()
    test.assertEqual(len(body),record['bytes'],relative+':complete source length')
    test.assertEqual(_sha(body),record['sha256'],relative+':complete dependency source')
    return body


def authenticated_dependencies(test,value,*,include_unchanged=True):
    for group in ('dependencies','unchanged') if include_unchanged else ('dependencies',):
        for relative,record in value[group].items():_authenticated_file(test,relative,record)
    for relative in value['deleted']:
        test.assertFalse(os.path.lexists(ROOT/relative),relative+':deleted source stays absent')


def future_pump_predecessor(test,relative,current):
    """Normalize only authenticated active reads, never old mutation inputs."""
    if relative in LEGACY_GUARDS:return future_legacy_guard(test,relative,current)
    if relative not in PATHS:return current
    # Unchanged codec/restoration-helper pins are verified by the complete
    # closure test and original guards. Do not intercept their original fault
    # injection before the unchanged historical guard can exercise it.
    value=manifest(test);authenticated_dependencies(test,value,include_unchanged=False)
    test.assertIsInstance(current,bytes)
    record=value['files'][relative]
    checksum=_sha(current)
    if checksum==record['before_sha256']:return current
    test.assertEqual(checksum,record['after_sha256'],relative+':exact frozen future source')
    restored=current
    for change in record['changes']:
        before,after=(change[key].encode() for key in ('before','after'))
        test.assertTrue(after,relative+':nonempty exact reversible future hunk')
        test.assertEqual(restored.count(after),1,relative+':one complete future hunk')
        restored=restored.replace(after,before,1)
    test.assertEqual(_sha(restored),record['before_sha256'],relative+':every780source byte restored')
    from tests.test_robinhood_usd_valuation import rally_delta
    test.assertEqual(rally_delta(restored,current),
        {key:record[key] for key in ('nodes','layouts')},relative+':exact future nodes and order')
    return restored


def future_legacy_guard(test,relative,current):
    """Remove only the new active-read wrappers from each complete legacy test."""
    value=manifest(test)
    test.assertIn(relative,LEGACY_GUARDS)
    record=value['legacy_guards'][relative]
    test.assertEqual(_sha(current),record['after_sha256'],relative+':complete wrapped legacy guard')
    imported=IMPORTS[relative].encode()
    test.assertEqual(current.count(imported),1)
    restored=current.replace(imported,b'',1)
    for original,wrapped,expected in WRAPPERS[relative]:
        wrapped=wrapped.encode()
        test.assertEqual(restored.count(wrapped),expected)
        restored=restored.replace(wrapped,original.encode())
    test.assertEqual(_sha(restored),record['before_sha256'],
        relative+':all original assertions, pins, predecessors and mutations preserved')
    return restored


def _git(*args):
    return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)


def _image_source(relative):
    path=Path(relative)
    return ((relative.startswith('meme_machine/') and path.suffix in ('.py','.json','.proto'))
        or (relative.startswith('engineering/solana_capacity/') and path.suffix=='.py')
        or relative in ('engineering/__init__.py','operational/forward-survivor/NEXT_PROOF.json'))


def _active_read_inventory(content):
    """Inventory actual ROOT reads; original predecessor helper reads stay raw."""
    text=content.decode();result=[]
    def visit(node,scope=(),functions=()):
        if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            scope=scope+(node.name,)
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):functions=functions+(node,)
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and node.func.attr=='read_bytes' and isinstance(node.func.value,ast.BinOp)
                and isinstance(node.func.value.op,ast.Div)
                and isinstance(node.func.value.left,ast.Name) and node.func.value.left.id=='ROOT'):
            active=any(item.name.startswith('test_') or item.name=='guarded_source' for item in functions)
            owners=[arg.arg for item in functions for arg in item.args.args if arg.arg in ('test','self')]
            owner=owners[-1] if owners else None
            result.append((node.lineno,'.'.join(scope),ast.get_source_segment(text,node),
                ast.get_source_segment(text,node.func.value.right),owner,active))
        for child in ast.iter_child_nodes(node):visit(child,scope,functions)
    visit(ast.parse(text))
    return sorted(result)


def _active_image_changes():
    changed=_git('diff','--name-only','--no-renames','-z',IMPLEMENTATION,'--').split(b'\0')
    untracked=_git('ls-files','--others','--exclude-standard','-z').split(b'\0')
    ignored=_git('ls-files','--others','--ignored','--exclude-standard','-z').split(b'\0')
    return sorted({raw.decode() for raw in changed+untracked+ignored if raw and _image_source(raw.decode())})


def caller_manifest(test):
    raw=CALLER_MANIFEST.read_bytes()
    test.assertEqual(_sha(raw),CALLER_MANIFEST_SHA256,'complete reviewed exported-helper caller manifest')
    value=json.loads(raw)
    test.assertEqual(set(value),{'schema','base','failed_ci_commit','implementation',
        'implementation_tree','core_manifest_sha256','callers','api_census'})
    test.assertEqual(value['schema'],'authenticated-future-source-callers-v1')
    test.assertEqual((value['base'],value['failed_ci_commit'],value['implementation'],
        value['implementation_tree'],value['core_manifest_sha256']),
        (BASE,'5bd959f4e3e39f030d3f87368e833cc63beccf55',IMPLEMENTATION,
            IMPLEMENTATION_TREE,MANIFEST_SHA256))
    test.assertEqual(set(value['callers']),set(EXTERNAL_CALLERS))
    return value


def external_caller_predecessor(test,relative,current):
    """Restore the entire caller; no legacy helper/mutation input is rewritten."""
    test.assertIn(relative,EXTERNAL_CALLERS)
    row=caller_manifest(test)['callers'][relative]
    test.assertEqual(_sha(current),row['after_sha256'],relative+':complete active caller')
    test.assertEqual(current.count(CALLER_IMPORT),1)
    restored=current.replace(CALLER_IMPORT,b'',1)
    for original,wrapped,count in row['wrappers']:
        before,after=original.encode(),wrapped.encode()
        test.assertEqual(restored.count(after),count,relative+':one inventoried active read')
        restored=restored.replace(after,before)
    test.assertEqual(_sha(restored),row['before_sha256'],relative+':every780caller byte restored')
    return restored


def _literal_string(node,bindings):
    if isinstance(node,ast.Constant) and isinstance(node.value,str):return node.value
    if isinstance(node,ast.Name):return bindings.get(node.id)
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
        before,after=(_literal_string(item,bindings) for item in (node.left,node.right))
        if before is not None and after is not None:return before+after
    return None


def _legacy_api_census(sources,source_names):
    """Static references across repository Python, not a runtime import/exec.

    Imports, qualified accesses, escaping aliases and resolved dynamic loads are
    retained. A new reference cannot inherit admission merely from an old import.
    ABI/RPC fixtures and constants are recorded without rewriting their callers.
    """
    result={}
    basenames={module.rsplit('.',1)[-1]:module for module in LEGACY_MODULES}
    owners={name:module for module,names in source_names.items() for name in names
        if name not in ('baseline','manifest','authenticated_helper')
        and sum(name in other for other in source_names.values())==1}
    for relative,raw in sources:
        if relative in LEGACY_GUARDS:continue
        text=raw.decode();tree=ast.parse(text);parents={};scopes={}
        def visit(node,scope=()):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):scope=scope+(node.name,)
            scopes[node]='.'.join(scope)
            for child in ast.iter_child_nodes(node):parents[child]=node;visit(child,scope)
        visit(tree)
        symbols={};modules={};bindings={};imports=[];loads=[];references=[];markers=[]
        factories={'__import__','import_module','spec_from_file_location'}
        api_names=set().union(*source_names.values())
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                value=_literal_string(node.value,bindings)
                if value is not None:bindings[node.targets[0].id]=value
            if isinstance(node,ast.ImportFrom):
                if node.module in ('importlib','importlib.util'):
                    factories.update(item.asname or item.name for item in node.names
                        if item.name in ('import_module','spec_from_file_location'))
                if node.module in LEGACY_MODULES:
                    for item in node.names:
                        alias=item.asname or item.name;symbols[alias]=(node.module,item.name)
                        imports.append((scopes[node],'symbol',node.module,item.name,alias))
                elif node.module=='tests':
                    for item in node.names:
                        if item.name in basenames:
                            alias=item.asname or item.name;module=basenames[item.name];modules[alias]=module
                            imports.append((scopes[node],'module',module,None,alias))
                else:
                    # A fixed legacy helper can also be re-exported by an
                    # already inventoried engineering/audit module. A newly
                    # introduced same-name route requires explicit review.
                    for item in node.names:
                        if item.name in owners:
                            alias=item.asname or item.name;symbols[alias]=(owners[item.name],item.name)
                            imports.append((scopes[node],'possible_reexport',node.module,item.name,alias))
            elif isinstance(node,ast.Import):
                for item in node.names:
                    if item.name in LEGACY_MODULES:
                        alias=item.asname or item.name;modules[alias]=item.name
                        imports.append((scopes[node],'module',item.name,None,alias))
            elif isinstance(node,ast.Constant) and isinstance(node.value,(str,bytes)):
                value=node.value.decode(errors='replace') if isinstance(node.value,bytes) else node.value
                if any(name in value for name in basenames) or value in api_names:
                    markers.append((scopes[node],_sha(value.encode())))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            factory=ast.unparse(node.func)
            if not (factory.endswith(('.import_module','.spec_from_file_location'))
                    or factory in factories):continue
            for argument in node.args:
                target=_literal_string(argument,bindings)
                if target is None or not any(name in target for name in basenames):continue
                loads.append((scopes[node],factory,target,ast.dump(node,include_attributes=False)))
                parent=parents.get(node)
                if target in LEGACY_MODULES and isinstance(parent,ast.Assign):
                    for binding in parent.targets:
                        if isinstance(binding,ast.Name):modules[binding.id]=target
        for node in ast.walk(tree):
            target=None
            if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id in symbols:
                target=symbols[node.id]
            elif isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load) and node.id in modules:
                parent=parents.get(node)
                if not isinstance(parent,ast.Attribute) or parent.value is not node:
                    references.append((scopes[node],modules[node.id],None,'escaped_module',
                        ast.dump(parent,include_attributes=False)))
            elif isinstance(node,ast.Attribute) and isinstance(node.ctx,ast.Load):
                module=modules.get(ast.unparse(node.value))
                if module is not None:target=(module,node.attr)
                elif node.attr in owners:target=(owners[node.attr],node.attr)
            if target is None or target[1] not in source_names[target[0]]:continue
            parent=parents.get(node)
            kind='call' if isinstance(parent,ast.Call) and parent.func is node else 'escaped_symbol'
            references.append((scopes[node],*target,kind,ast.dump(parent,include_attributes=False)))
        if imports or loads or references or markers:
            result[relative]=dict(imports=sorted(imports,key=repr),dynamic_loads=sorted(loads,key=repr),
                source_references=sorted(references,key=repr),text_markers=sorted(markers,key=repr))
    return result


def _legacy_source_names():
    result={}
    for path,module in zip(LEGACY_GUARDS,LEGACY_MODULES):
        tree=ast.parse(_git('show',BASE+':'+path))
        result[module]={node.name for node in tree.body if isinstance(node,ast.FunctionDef)
            and node.name not in ('abi','text_abi')}
    return result


def _repository_api_census():
    names=set(_git('ls-files','-z','--','*.py').split(b'\0'))
    names.update(_git('ls-files','--others','--exclude-standard','-z','--','*.py').split(b'\0'))
    def sources():
        for name in sorted(names):
            if not name:continue
            relative=name.decode();path=ROOT/relative
            if path.is_symlink():raise AssertionError('caller census requires actual repository source')
            yield relative,path.read_bytes()
    return _legacy_api_census(sources(),_legacy_source_names())


def _caller_read_inventory(raw,source_names):
    text=raw.decode();tree=ast.parse(text);scopes={};relevant=set()
    def visit(node,scope=()):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):scope=scope+(node.name,)
        scopes[node]=scope
        for child in ast.iter_child_nodes(node):visit(child,scope)
    visit(tree)
    for node in ast.walk(tree):
        if (isinstance(node,ast.ImportFrom) and node.module in source_names
                and any(item.name in source_names[node.module] for item in node.names)):
            relevant.add(scopes[node])
    rows=[]
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and node.func.attr in ('read_bytes','read_text')
                and any(scopes[node][:len(scope)]==scope for scope in relevant)):
            rows.append(('.'.join(scopes[node]),node.func.attr,ast.get_source_segment(text,node)))
    return sorted(rows)


def _fresh_normalization_read(node):
    if not isinstance(node,ast.Call) or len(node.args)!=3 or node.keywords:return None
    raw=node.args[2];mode='read_bytes'
    if (isinstance(raw,ast.Call) and isinstance(raw.func,ast.Attribute) and raw.func.attr=='encode'
            and not raw.args and not raw.keywords):
        raw=raw.func.value;mode='read_text'
    if (not isinstance(raw,ast.Call) or not isinstance(raw.func,ast.Attribute)
            or raw.func.attr!=mode):return None
    return mode


class FuturePumpSourceGuardTests(unittest.TestCase):
    def test_complete_frozen_image_source_delta_and_dependency_closure_are_pinned(self):
        value=manifest(self);authenticated_dependencies(self,value)
        self.assertEqual(_git('rev-parse',IMPLEMENTATION+'^{tree}').decode().strip(),IMPLEMENTATION_TREE)
        rows=_git('diff','--name-status','--no-renames',BASE,IMPLEMENTATION).decode().splitlines()
        active=set();deleted=set()
        for row in rows:
            status,relative=row.split('\t')
            if not _image_source(relative):continue
            self.assertIn(status,('A','M','D'))
            (deleted if status=='D' else active).add(relative)
        self.assertEqual(active,set(PATHS)|set(DEPENDENCY_PATHS))
        self.assertEqual(deleted,set(DELETED_PATHS))
        self.assertEqual(_active_image_changes(),[],
            'active image inputs must match the frozen implementation, including previously unchanged files')
        for relative in PATHS:
            current=(ROOT/relative).read_bytes();record=value['files'][relative]
            self.assertEqual(_sha(current),record['after_sha256'])
            restored=future_pump_predecessor(self,relative,current)
            self.assertEqual(restored,_git('show',BASE+':'+relative))
            self.assertEqual(future_pump_predecessor(self,relative,restored),restored)
        for relative in UNCHANGED:
            self.assertEqual((ROOT/relative).read_bytes(),_git('show',BASE+':'+relative))

    def test_complete_legacy_guards_reverse_only_exact_active_reads_and_imports(self):
        for relative in LEGACY_GUARDS:
            restored=future_legacy_guard(self,relative,(ROOT/relative).read_bytes())
            self.assertEqual(restored,_git('show',BASE+':'+relative))
            self.assertEqual(_active_read_inventory(restored),ACTIVE_READS[relative])

    def test_active_image_added_changed_and_deleted_inputs_are_not_invisible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            originals={'meme_machine/runtime/previously_unchanged.py':b'pass\n',
                'engineering/solana_capacity/retained.py':b'pass\n',
                'operational/forward-survivor/NEXT_PROOF.json':b'{}\n',
                '.gitignore':b'meme_machine/ignored_local.json\n'}
            for relative,body in originals.items():
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            environment=dict(PATH='/usr/bin:/bin',LANG='C',GIT_OPTIONAL_LOCKS='0',
                GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null')
            with patch.dict(os.environ,environment,clear=True),patch(__name__+'.ROOT',root):
                _git('init','-q');_git('add','.')
                _git('-c','user.name=Offline Guard','-c','user.email=offline@example.invalid',
                    '-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null','commit','-qm','fixed fixture')
                commit=_git('rev-parse','HEAD').decode().strip()
                with patch(__name__+'.IMPLEMENTATION',commit):
                    for relative in originals:
                        if relative=='.gitignore':continue
                        target=root/relative;target.write_bytes(originals[relative]+b'\n')
                        self.assertEqual(_active_image_changes(),[relative])
                        target.unlink();self.assertEqual(_active_image_changes(),[relative])
                        target.write_bytes(originals[relative])
                    for relative in ('meme_machine/new_unlisted.json','meme_machine/ignored_local.json',
                            'engineering/solana_capacity/new_input.py'):
                        target=root/relative;target.write_bytes(b'{}\n')
                        self.assertEqual(_active_image_changes(),[relative]);target.unlink()
                    target=root/'tests/new_guard.py';target.parent.mkdir();target.write_bytes(b'pass\n')
                    target=root/'engineering/diagnostics/note.md';target.parent.mkdir();target.write_bytes(b'note\n')
                    self.assertEqual(_active_image_changes(),[])

    def test_unknown_partial_reversed_and_mutated_future_sources_are_refused(self):
        for relative,record in manifest(self)['files'].items():
            current=(ROOT/relative).read_bytes()
            changes=[b'',current+b'\n# unreviewed future source\n']
            for change in record['changes']:
                after=change['after'].encode();self.assertEqual(current.count(after),1)
                changed=current.replace(after,change['before'].encode(),1)
                if _sha(changed)!=record['before_sha256']:changes.append(changed)
            for changed in changes:
                with self.subTest(relative=relative,sha256=_sha(changed)),self.assertRaises(AssertionError):
                    future_pump_predecessor(self,relative,changed)

    def test_each_complete_dependency_and_unchanged_source_refuses_mutation(self):
        value=manifest(self);read=Path.read_bytes
        for relative,record in {**value['dependencies'],**value['unchanged']}.items():
            current=(ROOT/relative).read_bytes()
            for changed in (b'' if current else b'\0',current+b'\n'):
                self.assertNotEqual(changed,current)
                with self.subTest(relative=relative,sha256=_sha(changed)),\
                        patch.object(Path,'read_bytes',new=lambda path:changed if path==ROOT/relative else read(path)),\
                        self.assertRaises(AssertionError):
                    _authenticated_file(self,relative,record)

    def test_legacy_assertion_or_wrapper_edits_are_not_new_exemptions(self):
        for relative in LEGACY_GUARDS:
            current=(ROOT/relative).read_bytes()
            for changed in (b'',current+b'\n# unreviewed assertion\n',
                    current.replace(b'assertEqual',b'assertNotEqual',1)):
                self.assertNotEqual(changed,current)
                with self.subTest(relative=relative,sha256=_sha(changed)),self.assertRaises(AssertionError):
                    future_legacy_guard(self,relative,changed)

    def test_manifest_mutations_and_unrelated_sources_do_not_gain_authority(self):
        current=MANIFEST.read_bytes();read=Path.read_bytes
        for changed in (b'{}',current+b'\n',current.replace(BASE.encode(),b'f'*40,1)):
            with self.subTest(sha256=_sha(changed)),\
                    patch.object(Path,'read_bytes',new=lambda path:changed if path==MANIFEST else read(path)),\
                    self.assertRaises(AssertionError):
                future_pump_predecessor(self,PATHS[0],(ROOT/PATHS[0]).read_bytes())
        self.assertEqual(future_pump_predecessor(self,'unrelated/source.py',b'unchanged'),b'unchanged')

    def test_external_callers_reverse_whole_files_and_only_fresh_read_boundaries(self):
        value=caller_manifest(self);source_names=_legacy_source_names()
        for relative,row in value['callers'].items():
            current=(ROOT/relative).read_bytes()
            restored=external_caller_predecessor(self,relative,current)
            self.assertEqual(restored,_git('show',BASE+':'+relative))
            self.assertEqual(_caller_read_inventory(restored,source_names),
                [tuple(item) for item in row['read_inventory']])
            tree=ast.parse(current);parents={child:node for node in ast.walk(tree)
                for child in ast.iter_child_nodes(node)}
            normalized=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
                and isinstance(node.func,ast.Name) and node.func.id=='future_pump_predecessor']
            self.assertEqual(len(normalized),len(row['read_inventory']))
            for node in normalized:
                mode=_fresh_normalization_read(node)
                self.assertIn(mode,('read_bytes','read_text'),relative+':mutations/intermediates stay unnormalized')
                if mode=='read_text':
                    decoded=parents[node]
                    self.assertIsInstance(decoded,ast.Attribute);self.assertEqual(decoded.attr,'decode')
                    self.assertIsInstance(parents[decoded],ast.Call)
                    self.assertEqual(parents[decoded].args,[]);self.assertEqual(parents[decoded].keywords,[])
            for changed in (b'',current+b'\n# unreviewed caller\n'):
                with self.subTest(relative=relative),self.assertRaises(AssertionError):
                    external_caller_predecessor(self,relative,changed)

    def test_repository_exported_source_api_census_matches_fixed_reviewed_contract(self):
        expected=caller_manifest(self)['api_census']
        actual=json.loads(json.dumps(_repository_api_census(),sort_keys=True,allow_nan=False))
        self.assertEqual(actual,expected,
            'new imports/calls/aliases/qualified/dynamic references require explicit boundary review')

    def test_new_aliased_qualified_dynamic_and_escaped_source_api_references_are_visible(self):
        module=LEGACY_MODULES[1];source_names=_legacy_source_names()
        cases=[
            f'from {module} import opportunity_predecessor as guard\nguard(test,path,raw)\n',
            f'import {module} as guard\nguard.opportunity_predecessor(test,path,raw)\n',
            'from tests import test_robinhood_usd_valuation as guard\nguard.opportunity_predecessor(test,path,raw)\n',
            f'import {module}\n{module}.opportunity_predecessor(test,path,raw)\n',
            f'from importlib import import_module as load\nguard=load({module!r})\n'
                'guard.opportunity_predecessor(test,path,raw)\n',
            f'guard=__import__({module!r},fromlist=["*"])\nguard.opportunity_predecessor(test,path,raw)\n',
            'import importlib.util\nspec=importlib.util.spec_from_file_location("guard",'
                '"tests/test_robinhood_usd_valuation.py")\n',
            f'from {module} import opportunity_predecessor as original\nalias=original\nalias(test,path,raw)\n',
            f'import {module} as guard\ngetattr(guard,"opportunity_predecessor")(test,path,raw)\n',
            'from engineering.issue138.generate_source_manifest import rally_delta as delta\ndelta(old,new)\n',
            'import engineering.issue138.generate_source_manifest as generator\ngenerator.rally_delta(old,new)\n',
            'from importlib import import_module as load\n'
                'load("engineering.issue138.generate_source_manifest").rally_delta(old,new)\n',
        ]
        for code in cases:
            with self.subTest(code=code):
                census=_legacy_api_census([('tests/new_caller.py',code.encode())],source_names)
                self.assertIn('tests/new_caller.py',census)
                row=census['tests/new_caller.py']
                self.assertTrue(row['source_references'] or row['dynamic_loads'])
        before=f'from {module} import opportunity_predecessor as original\noriginal(test,path,raw)\n'
        after=before+'alias=original\nalias(test,path,changed)\n'
        self.assertNotEqual(_legacy_api_census([('known.py',before.encode())],source_names),
            _legacy_api_census([('known.py',after.encode())],source_names))
        for value in ('changed','current','raw.replace(b"old",b"new")'):
            node=ast.parse('future_pump_predecessor(test,path,'+value+')',mode='eval').body
            self.assertIsNone(_fresh_normalization_read(node))


if __name__=='__main__':unittest.main()
