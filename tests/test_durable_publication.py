import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.durable_publication import publish_report,publish_json

class PublicationTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_report_and_returns_error(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'report.json';publish_json(path,{'state':'open'})
            with patch('meme_machine.durable_publication.os.replace',side_effect=OSError('injected')):
                result=publish_report(path,{'state':'new'})
            self.assertEqual(result,{'published':False,'error':'OSError'})
            self.assertEqual(json.loads(path.read_text()),{'state':'open'})
            self.assertEqual(list(Path(root).glob('*.tmp')),[])

    def test_invalid_export_does_not_escape_into_lifecycle(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(publish_report(Path(root)/'report.json',{'invalid':float('nan')})['published'])
