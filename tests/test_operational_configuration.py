import json
from pathlib import Path
import tempfile
import unittest
from meme_machine.operational.configuration import environment


class Configuration(unittest.TestCase):
    def test_manifest_contains_names_and_public_endpoint_identity_without_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'paper.env'
            path.write_text('MM_MODE=PAPER\nMM_STATE_ROOT=/mnt/volume/state\nMM_ROBINHOOD_READ_RPC_URL=https://example.com/v2/never-publish-this-key\nPROVIDER_TOKEN=another-secret\n')
            value=environment(path);raw=json.dumps(value)
            self.assertNotIn('never-publish-this-key',raw);self.assertNotIn('another-secret',raw)
            self.assertIn('PROVIDER_TOKEN',value['variable_names'])
            self.assertEqual(value['provider_endpoints']['MM_ROBINHOOD_READ_RPC_URL']['hostname'],'example.com')
            self.assertNotIn('environment_sha256',value)
