import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification import run


class HistoricalExposureTests(unittest.TestCase):
    def test_new_output_directory_cannot_hide_known_old_policy_position(self):
        unresolved=run.historical_exposure()
        self.assertEqual(unresolved[0]['lane'],'meteora')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);gate=root/'gate.json';out=root/'new-campaign'
            spec={'lanes':{}}
            gate.write_text(json.dumps(dict(passed=True,source_manifest_hash='hash',
                integration_sha='head',implementation_hash='impl',source_diff_hashes={})))
            with patch.object(run,'integration_integrity'),patch.object(run,'manifest',return_value=spec),\
                 patch.object(run,'digest',return_value='hash'),patch.object(run,'git',return_value='head'),\
                 patch.object(run,'implementation_hash',return_value='impl'),\
                 patch.object(run,'source_integrity',return_value={}),patch.object(run.subprocess,'Popen') as spawn:
                result=run.launch(root,out,600,'smoke',gate)
            spawn.assert_not_called()
            self.assertEqual(result['status'],'BLOCKED')
            self.assertIn('historical_unresolved_exposure:meteora',result['blockers'])
            self.assertEqual(result['historical_exposure'],unresolved)
            self.assertEqual(json.loads((out/'result.json').read_text())['historical_exposure'],unresolved)
            self.assertEqual(run.historical_exposure(),unresolved)
