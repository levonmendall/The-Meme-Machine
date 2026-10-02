"""Finite file/AST/native-pure-verifier checks; no material or candidate runtime."""
import ast
import importlib
import json
from pathlib import Path
import sys
import unittest

from resource_rules import S,T
import static_validation as validation

ROOT=Path(__file__).resolve().parent
SOURCE=validation.SOURCE


def read(name):
    return json.loads((ROOT/name).read_bytes())


def nodes(path):
    return ast.parse((SOURCE/path).read_bytes())


def numeric(node):
    if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
    if isinstance(node,ast.BinOp):
        a,b=numeric(node.left),numeric(node.right)
        if isinstance(node.op,ast.Mult):return a*b
        if isinstance(node.op,ast.Pow):return a**b
        if isinstance(node.op,ast.Add):return a+b
    raise ValueError('not a literal numeric source expression')


class SourceGroundingTests(unittest.TestCase):
    def test_exact_candidate_and_every_preserved_evidence_byte_unchanged(self):
        result=validation.source_integrity()
        self.assertEqual(result['candidate_files'],1241)
        self.assertEqual(result['evidence_files'],159)
        self.assertEqual(result['changed_candidate_files'],[])
        self.assertEqual(result['changed_history_files'],[])

    def test_all_required_gates_and_exact_original_rows_preserved(self):
        self.assertEqual(validation.contract_static()['v2_gates_mapped'],44)

    def test_all_three_full_predecessor_shapes_are_exact(self):
        A=read('production_capacity_workload.json')
        for entry in A['predecessor_full_shape_cases']:
            self.assertEqual(entry['unchanged_spec'],json.loads((SOURCE/entry['spec']['path']).read_bytes()))
        specs={r['id']:r['unchanged_spec'] for r in A['predecessor_full_shape_cases']}
        self.assertEqual(specs['run373-full-v3']['frames'],14)
        self.assertEqual(specs['run379-full-v3']['setup_debt_frames'],100)
        self.assertEqual(specs['run379-full-v3']['transactions_per_frame'],160)
        self.assertEqual(specs['run380-full-v3']['frames'],240)

    def test_native_resource_constants_equal_safety_ledger(self):
        parsed={}
        for n in nodes('meme_machine/solana_evidence_service.py').body:
            if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
                try:parsed[n.targets[0].id]=numeric(n.value)
                except ValueError:pass
        limits=read('safety_ledger.json')['limits']
        for name,key in [('STREAM_DECODE_WORKERS','shared_decode_archive_workers'),
                         ('STREAM_DISPATCH_MAX_MESSAGES','dispatch_frames_max'),
                         ('STREAM_DISPATCH_MAX_BYTES','dispatch_bytes_max'),
                         ('STREAM_COMMIT_BATCH_MAX_MESSAGES','commit_messages_max'),
                         ('STREAM_COMMIT_BATCH_MAX_BYTES','commit_bytes_max'),
                         ('STREAM_MAX_MESSAGE_BYTES','source_message_bytes_max'),
                         ('STREAM_PREPARED_MAX_BYTES','prepared_decode_bytes_max'),
                         ('STREAM_PROTOCOL_QUEUE_FRAMES','protocol_queue_frames'),
                         ('STREAM_SOURCE_IDLE_SECONDS','source_idle_seconds'),
                         ('STREAM_COMMIT_STALL_SECONDS','commit_stall_seconds'),
                         ('ARCHIVE_COMMIT_SLICE_RECORDS','archive_commit_slice_records')]:
            with self.subTest(name=name):self.assertEqual(parsed[name],limits[key])

    def test_snapshot_hard_bound_and_owner_limits_are_unchanged_native_source(self):
        tree=nodes('meme_machine/solana_archive_snapshot.py')
        n=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MAX_SINGLE_SNAPSHOT_BYTES' for t in n.targets))
        self.assertEqual(numeric(n.value),read('safety_ledger.json')['limits']['archive_snapshot_hard_encoded_bytes'])
        source=ast.unparse(nodes('meme_machine/solana_evidence_control.py'))
        self.assertIn('capacity=64',source)
        self.assertIn('reserved=8',source)

    def test_all_normalization_constants_match_actual_run381_source(self):
        values={n.targets[0].id:numeric(n.value) for n in nodes('certification/run381_pressure.py').body
            if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
            and n.targets[0].id in ('OWNER_SECONDS_PER_FRAME','ARCHIVE_SECONDS_PER_THOUSAND','COMMIT_LATENCY_SECONDS')}
        self.assertEqual(values,{'OWNER_SECONDS_PER_FRAME':.165,'ARCHIVE_SECONDS_PER_THOUSAND':.36,'COMMIT_LATENCY_SECONDS':.006})
        classes={r['id']:r for r in read('contention_classification.json')['components']}
        for key in ('owner-floor','archive-floor','commit-pad'):
            self.assertEqual(classes[key]['classification'],'EXECUTOR_NORMALIZATION_TEST_ONLY')
            self.assertFalse(classes[key]['production_semantic'])
            self.assertFalse(classes[key]['production_safety_limit'])

    def test_native_work_precedes_owner_and_archive_sleep(self):
        tree=nodes('certification/run381_pressure.py')
        archive=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='measured_archive')
        owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MeasuredServiceState')
        for source in (ast.unparse(archive),ast.unparse(owner)):
            native='prepare_and_write_archive' if 'prepare_and_write_archive' in source else 'super().source_batch'
            self.assertLess(source.index(native),source.index('time.sleep'))
            self.assertIn('max(0,',source)

    def test_commit_pad_is_additive_before_real_changed_transaction_commit(self):
        source=ast.unparse(nodes('certification/pressure_diagnostics.py'))
        self.assertIn("sql == 'COMMIT'",source)
        self.assertIn('self.total_changes !=',source)
        self.assertLess(source.index("timings.measure('injected_commit_wait'"),source.index('label = statement_class(sql)'))
        self.assertIn('super(TimedConnection, self).execute',source)

    def test_historical_rationale_explicitly_excludes_artificial_delays_from_production(self):
        notes=(SOURCE/'certification/notes/run381-runtime-repair.md').read_text()
        self.assertIn('explicit test-only profile',notes)
        self.assertIn('Production has no artificial delays',notes)
        code=(SOURCE/'certification/run381_pressure.py').read_text()
        for run in ('36293751021','36297528197','36302144874'):self.assertIn(run,code)

    def test_no_production_module_imports_or_names_injectors(self):
        forbidden={'run381_pressure','MeasuredServiceState','MeasuredProcessPool','SQLTimings',
                   'OWNER_SECONDS_PER_FRAME','ARCHIVE_SECONDS_PER_THOUSAND','COMMIT_LATENCY_SECONDS'}
        for path in (SOURCE/'meme_machine').glob('*.py'):
            tree=ast.parse(path.read_bytes())
            names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
            imports={a.name.split('.')[-1] for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names}
            self.assertFalse(forbidden & (names|imports),path.name)

    def test_stress_profile_preserves_all_injected_delays_and_recovery(self):
        C=read('adversarial_stress_workload.json')
        p=C['artificial_contention']
        self.assertEqual(p['source_pause_frames'],[800,1400])
        self.assertEqual(p['source_pause_seconds'],8)
        self.assertEqual(p['held_reader_injected_sleeps_seconds'],[1.25,.1])
        self.assertEqual(p['completed_tail_injected_delay_seconds'],.75)
        self.assertTrue(C['required_stress_safety'])
        self.assertIn('Wrapper-only stop is not native fail-closed proof',C['overload'])
        self.assertEqual(C['recovery_plan'],json.loads((SOURCE/'certification/stagee24_qualification_plan.json').read_bytes()))

    def test_original_synthetic_coverage_lower_bounds_have_explicit_mapping(self):
        mapping=next(r for r in read('gate-map-v3.json')['gates'] if r['predecessor_gate']=='frame-byte-bounds-v2')
        self.assertIn('16..64',mapping['predecessor_row']['new_purpose'])
        self.assertIn('C retains dispatch16..64, commit2..8',mapping['acceptance'])
        self.assertIn('original byte maxima',mapping['acceptance'])

    def test_no_observer_order_metric_estimator_or_threshold_change(self):
        old=json.loads((SOURCE/'certification/stage_e_native_v2/observer-contract-v2.json').read_bytes())
        new=read('observer_workload.json')
        for field in ('metric','estimator','repetition_policy'):self.assertEqual(old[field],new[field])
        self.assertEqual(read('acceptance_semantic_changes.json')['observer_arithmetic_order_threshold_changes'],[])

    def test_exact_native_v2_pure_verifier_still_rejects_one_percent_and_incomplete_pairs(self):
        # These modules contain only contract/clock/pure verification functions.
        # No candidate production runtime, material generator, driver or service is imported.
        sys.path.insert(0,str(SOURCE))
        try:
            native=importlib.import_module('certification.stage_e_native_v2.observer')
            old=json.loads((SOURCE/'certification/stage_e_native_v2/observer-contract-v2.json').read_bytes())
            pairs=[dict(pair_id=str(i),baseline_ns=10000,observed_ns=10099,valid=True,
                        same_workload_hash=old['workload_identity']) for i in range(3)]
            m={k:old[k] for k in ('baseline','metric','estimator','repetition_policy')}
            m.update(contract=old['version'],identity={'fixture':'PURE_SYNTHETIC'},workload_identity=old['workload_identity'],
                     raw_pairs=pairs,numerator_ns=297,denominator_ns=30000,ratio=297/30000)
            self.assertTrue(native.verify(m,m['identity']))
            for p in pairs:p['observed_ns']=10100
            m.update(numerator_ns=300,ratio=.01)
            with self.assertRaisesRegex(ValueError,'strictly_less'):native.verify(m,m['identity'])
            m['raw_pairs']=[]
            with self.assertRaisesRegex(ValueError,'raw_pairs_missing'):native.verify(m,m['identity'])
            self.assertFalse(any(x in sys.modules for x in ('certification.run381_pressure','certification.combined_pressure','meme_machine.solana_evidence_service')))
        finally:sys.path.pop(0)

    def test_original_terminal_predeclaration_and_durability_publication_are_byte_bound(self):
        seal=read('historical_observer_seal.json')
        self.assertEqual(seal['outcome'],'OBSERVER_V2: INVALID_PAIR')
        self.assertEqual(seal['unused_slots'],5)
        self.assertEqual(seal['complete_valid_pairs'],0)
        self.assertFalse(seal['observer_overhead_earned'])
        self.assertFalse(seal['raw_artifact']['downloaded'])
        self.assertEqual(seal['raw_artifact']['sha256'],'8cb1e6e7294feb2075918bd344e0f46f161e54b8afe5f088af81308c4455c6dc')
        self.assertEqual(len(seal['all_old_trial_ids_forbidden']),6)
        self.assertEqual(seal['new_v3_slots'],[])

    def test_exact_six_regime_economic_policy_and_sleeves_preserved(self):
        source=json.loads((SOURCE/'certification/profitability_protocol.json').read_bytes())
        proof=read('policy_conservation.json')
        for field in ('frozen_lanes','frozen_strategies','directional_sleeves'):self.assertEqual(proof[field],source[field])
        self.assertEqual(sum(len(v) for v in proof['frozen_strategies'].values()),6)
        self.assertEqual(proof['changes'],[])


if __name__=='__main__':
    unittest.main()
