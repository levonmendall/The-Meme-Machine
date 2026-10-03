import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from meme_machine.lanes.pump import durable_publication
from meme_machine.lanes.pump import runner as runtime

class PublicationIsolationTests(unittest.TestCase):
    def test_export_failure_does_not_escape_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            report={"qualifiers":[{"entry_status":"reserved"}]}
            with patch.object(runtime,'REPORT',Path(temp)/'report.json'), patch.object(runtime,'ACCOUNTING',None), patch.object(runtime,'PIPELINE',None), patch.object(durable_publication,'publish_json',side_effect=OSError('injected')):
                runtime._save(report)
            self.assertEqual(report['qualifiers'][0]['entry_status'],'reserved')
            self.assertFalse(report['publication']['published'])
