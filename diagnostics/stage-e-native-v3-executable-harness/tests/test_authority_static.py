"""Execution denial and static bindings. No authorized document is created."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'harness'))
from core import contract_file,workload,read,canonical
from declaration import authorize,preview
from ledger import fresh_campaign


class AuthorityStaticTests(unittest.TestCase):
    def test_preview_rejected_before_ANY_process_or_tape_access(self):
        from run import execute
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preview.json';path.write_text('{"execution_authorized":false}')
            with patch('subprocess.Popen') as spawn,patch('run.validate_existing') as tape:
                with self.assertRaisesRegex(ValueError,'NOT_AUTHORIZED_PREVIEW_ONLY'):
                    execute(path,'nonexistent-permit','nonexistent-key',kind='A')
                spawn.assert_not_called();tape.assert_not_called()

    def test_preview_always_marks_no_execution_or_reserved_slots(self):
        for kind in ('A','B','C'):
            declaration=preview(kind,fresh_campaign(kind),executor={},environment={},workflow={},paths={})
            self.assertFalse(declaration['execution_authorized']);self.assertFalse(declaration['actual_slots_reserved'])
            self.assertEqual(declaration['disposition'],'NOT AUTHORIZED / PREVIEW ONLY')
            self.assertEqual(declaration['source_frames_released'],0)

    def test_exact_A_B_cohorts_and_no_synthetic_fields(self):
        A,B,C=workload('A'),workload('B'),workload('C')
        self.assertEqual([r['frames'] for r in A['cohort']],[2223,2223,2223,4445])
        for key in ('cohort','clock','worker_limits','tape_binding','artificial_contention'):
            self.assertEqual(A[key],B[key])
        self.assertEqual(A['source_frames_total'],11114)
        self.assertEqual(A['source_duration_total_us'],3000780000)
        self.assertEqual(C['artificial_contention']['owner_seconds_per_frame'],.165)
        self.assertEqual(C['artificial_contention']['archive_seconds_per_thousand'],.36)
        self.assertEqual(C['artificial_contention']['additional_commit_latency_seconds'],.006)

    def test_all_predecessor_gate_rows_and_policies_retained(self):
        mapping=contract_file('gate-map-v3.json')
        self.assertEqual(len(mapping['gates']),44);self.assertEqual(mapping['dropped_gates'],[])
        self.assertEqual(mapping['unmapped_required_gates'],[])
        self.assertEqual(contract_file('policy_conservation.json')['changes'],[])
        self.assertEqual(contract_file('safety_ledger.json')['changes'],[])

    def test_executable_source_static_and_C_AST_equivalence(self):
        sys.path.insert(0,str(ROOT))
        import review
        result=review.static_checks()
        self.assertTrue(result['C_exact_checkpoint_AST']);self.assertTrue(result['production_injection_exclusion'])
        self.assertEqual(result['candidate']['candidate_files'],1241)

    def test_no_installed_material_workflow(self):
        self.assertFalse((ROOT.parents[1]/'.github/workflows/stagee-native-v3-material.yml').exists())
        text=(ROOT/'workflows/stagee-native-v3-material.yml.preview').read_text()
        self.assertIn('NOT AUTHORIZED / PREVIEW ONLY',text);self.assertIn('if: ${{ false }}',text)

    def test_pure_verifier_does_not_import_workload_entrypoints(self):
        tree=ast.parse((ROOT/'harness/verify.py').read_bytes())
        imported={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertFalse(imported.intersection({'run','production','stress','trial'}))
