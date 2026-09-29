"""Do not spend a fixed cohort on a shallow or differently configured runtime."""
from pathlib import Path
import unittest
from unittest.mock import patch
from certification import qualification_environment as env
from certification.maintenance_qualification import qualification,frozen_inputs


class QualificationEnvironmentTests(unittest.TestCase):
    def test_version_mismatch_is_an_explicit_failed_precondition(self):
        with patch.object(env.platform,'python_version',return_value='3.13.5'),patch.object(
            env.importlib.metadata,'version',return_value='16.0'):
            result=env.inspect()
        self.assertFalse(result['passed'])
        self.assertIn('frozen_python_mismatch',result['failures'])
        self.assertIn('frozen_dependencies_mismatch',result['failures'])
        self.assertFalse(result['canonical_authority'])

    def test_generic_ci_retains_policy_predecessor_history(self):
        workflow=(env.ROOT/'.github/workflows/ci.yml').read_text()
        self.assertIn('fetch-depth: 0',workflow)
        self.assertNotIn('fetch-depth: 2',workflow)
        self.assertTrue(env.inspect()['policy_predecessor_available'])

    def test_new_observation_identity_and_original_workload_are_both_bound(self):
        with qualification():self.assertTrue(frozen_inputs())


if __name__=='__main__':unittest.main()
