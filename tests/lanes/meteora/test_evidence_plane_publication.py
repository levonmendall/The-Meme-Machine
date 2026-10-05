import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from meme_machine.lanes.meteora import durable_publication
from meme_machine.lanes.meteora import runner as runtime

class PublicationIsolationTests(unittest.TestCase):
    def test_export_failure_does_not_escape_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            report={"open_positions":[{"status":"open"}]}
            with patch.object(runtime,'OUT',Path(temp)/'report.json'), patch.object(durable_publication,'publish_json',side_effect=OSError('injected')):
                runtime._atomic_checkpoint(report,'monitoring',[],SimpleNamespace(telemetry=lambda:{}))
            self.assertEqual(report['open_positions'][0]['status'],'open')
            self.assertFalse(report['publication']['published'])
