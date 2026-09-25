import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from certification.controls import audit_telemetry
from certification.journal import Journal,digest
from certification.worker import provider_identity


class FailureEvidenceTests(unittest.TestCase):
    def test_failed_process_can_have_complete_evidence_but_cannot_pass_success_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);journal=Journal(root/'telemetry.sqlite')
            row=dict(sequence=1,lane='ramses',request=[['eth_getLogs',[]]],response=None,error='provider_http_429')
            journal.append('ramses','rpc','rpc_transport',dict(sequence=1,raw_hash=digest(row)))
            journal.append('ramses','terminal','process_terminal',dict(status='failed',policy_hash='policy'))
            journal.close()
            with gzip.open(root/'rpc-evidence.jsonl.gz','wt') as file:file.write(json.dumps(row)+'\n')
            audit=audit_telemetry(root,'ramses','policy',require_returned=False)
            self.assertTrue(audit['verified']);self.assertFalse(audit['successful_process'])
            with self.assertRaisesRegex(ValueError,'native_terminal_or_policy_mismatch'):
                audit_telemetry(root,'ramses','policy')

    def test_endpoint_identity_never_exposes_credentials_or_mislabels_public_as_alchemy(self):
        for endpoint,kind in [('https://rpc.mainnet.chain.robinhood.com','robinhood_public'),
                              ('https://solana-mainnet.g.alchemy.com/v2/private-test-key','alchemy')]:
            row=provider_identity(SimpleNamespace(_endpoint=endpoint),'robinhood')
            self.assertEqual(row['provider_kind'],kind)
            self.assertNotIn('private-test-key',json.dumps(row))
            self.assertNotIn(endpoint,json.dumps(row))
            self.assertEqual(len(row['endpoint_identity']),64)
