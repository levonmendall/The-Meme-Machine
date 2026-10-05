"""Keep the actual Meteora independence gate enabled in the combined suite."""
import os,subprocess,sys,unittest
from pathlib import Path

class IsolatedMeteoraEvidenceRecoveryTests(unittest.TestCase):
    def test_historical_protocol_and_native_evidence_regressions_in_clean_guarded_process(self):
        modules=('tests.lanes.meteora.test_dlmm',
            'tests.lanes.meteora.test_dlmm_broker_census',
            'tests.lanes.meteora.test_dlmm_reference',
            'tests.lanes.meteora.test_dlmm_tape_extensions',
            'tests.lanes.meteora.test_evidence_plane_publication',
            'tests.lanes.meteora.test_evidence_runtime_cutover',
            'tests.lanes.meteora.test_run369_admission')
        script=("from operational.tests import network_guard; network_guard(); "
            "import unittest; result=unittest.TextTestRunner().run("
            "unittest.defaultTestLoader.loadTestsFromNames("+repr(modules)+")); "
            "raise SystemExit(not result.wasSuccessful())")
        environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 29 tests',result.stderr)

    def test_historical_lifecycle_and_retention_regressions_in_clean_guarded_process(self):
        modules=('tests.lanes.meteora.test_dlmm_independent_accounting',
            'tests.lanes.meteora.test_dlmm_liquidity_reset',
            'tests.lanes.meteora.test_run380_candidate_retention',
            'tests.lanes.meteora.test_meteora_continuous_campaign')
        script=("from operational.tests import network_guard; network_guard(); "
            "import unittest; result=unittest.TextTestRunner().run("
            "unittest.defaultTestLoader.loadTestsFromNames("+repr(modules)+")); "
            "raise SystemExit(not result.wasSuccessful())")
        environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 15 tests',result.stderr)

    def test_original_fourteen_recovery_regressions_in_clean_guarded_process(self):
        script="from operational.tests import network_guard; network_guard(); import unittest; unittest.main(module='tests.test_meteora_evidence_recovery')"
        # The disposable test process has no configured PAPER/provider authority.
        environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 14 tests',result.stderr)
