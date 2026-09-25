import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from certification import preserved_position_recovery as recovery


class RecoveryCheckpointTests(unittest.TestCase):
    def exercise(self, *, stopped=True, digest_matches=True, authority_matches=True):
        source=json.loads(recovery.AUTHORITY.read_text())
        checkpoint=source['reviewed_recovery_checkpoint']
        previous=dict(source,recovery_sha=checkpoint['integration_sha'],
            certificate_run_id=checkpoint['certificate_run_id'])
        if not authority_matches:previous['integration_sha']='foreign'
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            archive.writestr('engineering-recovery-authorization.json',json.dumps(previous))
            archive.writestr('original-native-book.sqlite',b'preserved-native-bytes')
            archive.writestr('recovery-artifact-chain.jsonl','{"original":true}\n')
        class API:
            def pages(self,path,key):return []
            def request(self,method,path):
                return dict(head_sha=checkpoint['integration_sha'],
                    status='completed' if stopped else 'in_progress',conclusion=checkpoint['conclusion'])
            def artifact(self,run_id,name):
                assert run_id==checkpoint['run_id'] and name==checkpoint['artifact_name']
                return zipfile.ZipFile(io.BytesIO(raw.getvalue())),dict(id=checkpoint['artifact_id'],
                    digest=checkpoint['artifact_digest'] if digest_matches else 'wrong')
        with tempfile.TemporaryDirectory() as td,patch('certification.run.git',return_value='successor'),\
                patch('certification.prospective_program.certificate',return_value={'passed':True}):
            root=Path(td)/'copy'
            result=recovery.prepare(API(),root,'worktrees',999,checkpoint['run_id'])
            self.assertEqual(result['recovery_sha'],'successor')
            self.assertEqual(result['certificate_run_id'],999)
            self.assertEqual((root/'original-native-book.sqlite').read_bytes(),b'preserved-native-bytes')
            prior=root/'engineering-recovery-history'/(str(checkpoint['run_id'])+'-authorization.json')
            self.assertEqual(json.loads(prior.read_text()),previous)
            self.assertTrue((root/'recovery-artifact-chain.jsonl').read_text().startswith('{"original":true}\n'))

    def test_certified_successor_preserves_checkpoint_book_and_prior_authority(self):
        self.exercise()

    def test_active_checkpoint_cannot_be_forked(self):
        with self.assertRaisesRegex(RuntimeError,'checkpoint_not_stopped'):
            self.exercise(stopped=False)

    def test_foreign_artifact_or_authority_cannot_be_bridged(self):
        with self.assertRaisesRegex(RuntimeError,'artifact_identity'):
            self.exercise(digest_matches=False)
        with self.assertRaisesRegex(RuntimeError,'authority_mismatch'):
            self.exercise(authority_matches=False)


if __name__=='__main__':unittest.main()
