"""Keep the actual Meteora independence gate enabled in the combined suite."""
import os,subprocess,sys,unittest
from pathlib import Path

class IsolatedMeteoraEvidenceRecoveryTests(unittest.TestCase):
    def test_original_fourteen_recovery_regressions_in_clean_guarded_process(self):
        script="from operational.tests import network_guard; network_guard(); import unittest; unittest.main(module='tests.test_meteora_evidence_recovery')"
        # The disposable test process has no configured PAPER/provider authority.
        environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 14 tests',result.stderr)
