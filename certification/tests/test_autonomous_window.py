import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from certification import autonomous_window as adapter
from certification.tests.test_autonomous_control import GitAPI,IDENTITY,CAMPAIGN,REF
from certification import prospective_program
from certification.campaign_state import LANES
from certification.journal import digest


class AutonomousWorkflowAdapterTests(unittest.TestCase):
    def test_hosted_output_paths_allow_real_unix_socket_in_every_window_mode(self):
        import socket
        workflow=(Path(__file__).parents[2]/'.github/workflows/autonomous-paper.yml').read_text()
        self.assertEqual(workflow.count('--output "$RUNNER_TEMP/autonomous-evidence"'),4)
        self.assertIn('path: ${{ runner.temp }}/autonomous-evidence/',workflow)
        hosted=Path('/home/runner/work/_temp/autonomous-evidence')
        for phase in ('smoke','hourly','position'):
            path=hosted/('certification-'+phase)/'solana-evidence-plane.sqlite.sock'
            self.assertLess(len(str(path).encode()),108)
        try:probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        except PermissionError:
            if os.environ.get('GITHUB_ACTIONS')=='true':raise
            self.skipTest('Local executor disables sockets; hosted proof is mandatory')
        old=('/home/runner/work/The-Meme-Machine/The-Meme-Machine/autonomous-evidence/'
             'certification-smoke/solana-evidence-plane.sqlite.sock')
        with probe,self.assertRaisesRegex(OSError,'AF_UNIX path too long'):probe.bind(old)
        with tempfile.TemporaryDirectory(prefix='ipc-',dir=os.environ.get('RUNNER_TEMP','/tmp')) as td:
            for phase in ('smoke','hourly','position'):
                path=Path(td)/('certification-'+phase)/'solana-evidence-plane.sqlite.sock'
                path.parent.mkdir()
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                    server.bind(str(path));server.listen(1)
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                        client.connect(str(path));connection,_=server.accept()
                        with connection:
                            client.sendall(b'paper-only')
                            self.assertEqual(connection.recv(32),b'paper-only')
                path.unlink()

    def test_workflow_command_claims_exact_nonce_then_exports_the_owned_artifact_name(self):
        from certification import autonomous_control as c
        api=GitAPI();api.run(1)
        with patch.object(prospective_program,'certificate',return_value=dict(IDENTITY,passed=True)):
            c.authorize(api,IDENTITY,CAMPAIGN,REF,99,1)
        state=c.dispatch_next(api,IDENTITY,CAMPAIGN,1);nonce=state['window']['nonce']
        api.terminal(1);api.run(2,nonce)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);output=root/'claim.json';envfile=root/'github-env'
            with patch.dict(os.environ,OPERATION='window',AUTONOMOUS_CAMPAIGN=CAMPAIGN,
                    GITHUB_RUN_ID='2',GITHUB_RUN_ATTEMPT='1',DISPATCH_NONCE=nonce,GITHUB_ENV=str(envfile)), \
                    patch.object(adapter,'GitHub',return_value=api),patch.object(adapter,'exact_checkout',return_value=IDENTITY), \
                    patch('sys.argv',['autonomous_window','control','--output',str(output)]):
                adapter.main()
                claim=json.loads(output.read_text());self.assertEqual(claim['window']['workflow_run_id'],2)
                self.assertEqual(envfile.read_text(),f'AUTONOMOUS_ARTIFACT_NAME=autonomous-paper-{CAMPAIGN}-0-2\n')
                with self.assertRaisesRegex(ValueError,'duplicate'):adapter.main()

    def test_actual_verify_operation_never_creates_campaign_or_provider_authority(self):
        api=GitAPI();api.run(1)
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'verify.json'
            with patch.dict(os.environ,OPERATION='verify',AUTONOMOUS_CAMPAIGN=CAMPAIGN,
                    GITHUB_RUN_ID='1',GITHUB_RUN_ATTEMPT='1',GITHUB_REF_NAME=REF), \
                    patch.object(adapter,'GitHub',return_value=api),patch.object(adapter,'exact_checkout',return_value=IDENTITY), \
                    patch('sys.argv',['autonomous_window','control','--output',str(output)]):
                adapter.main()
            value=json.loads(output.read_text())
            self.assertEqual(value['identity'],IDENTITY)
            for field in ('entry_authority','provider_authority','market_dispatch'):self.assertFalse(value[field])
            self.assertEqual(api.mutations,[])
            self.assertFalse(any(method=='POST' for method,path,body in api.calls))

    def test_missing_current_claim_blocks_all_source_provider_and_native_work(self):
        api=GitAPI()
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,AUTONOMOUS_CAMPAIGN=CAMPAIGN,GITHUB_RUN_ID='2'), \
                patch.object(adapter,'exact_checkout',return_value=IDENTITY),patch.object(adapter.subprocess,'run') as provider:
            with self.assertRaisesRegex(ValueError,'authority_identity'):
                adapter.run_window(api,dict(identity=IDENTITY,campaign_id=CAMPAIGN),td,Path(td)/'out')
            provider.assert_not_called();self.assertFalse((Path(td)/'out').exists())

    def test_preserved_sqlite_snapshot_detects_changed_native_evidence(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'lanes';output=root/'output';output.mkdir()
            for lane in LANES:(work/lane).mkdir(parents=True)
            folder=work/'pump/pump-survivor';folder.mkdir()
            with sqlite3.connect(folder/'history.sqlite') as db:
                db.execute('CREATE TABLE authenticated_evidence(id PRIMARY KEY, hash)')
                db.execute("INSERT INTO authenticated_evidence VALUES(1,'original')")
            run=output/'certification-smoke';run.mkdir();(run/'result.json').write_text('{"status":"FINISHED"}')
            artifact=adapter.stage(work,output,'smoke')
            snapshot=adapter.verify_snapshot(artifact)
            self.assertTrue(snapshot['snapshot_complete'])
            copy=artifact/'certification-native/smoke/pump/pump-survivor/history.sqlite'
            with sqlite3.connect(copy) as db:db.execute("UPDATE authenticated_evidence SET hash='changed'")
            with self.assertRaisesRegex(ValueError,'snapshot_hash'):adapter.verify_snapshot(artifact)

    def test_digest_pinned_download_rejects_wrong_artifact_duplicate_and_escaping_members(self):
        reference=dict(workflow_run_id=5,name='native-state',id=7,digest='sha256:'+'a'*64)
        class API:
            def __init__(self,names,wrong=False):self.names=names;self.wrong=wrong
            def artifact(self,run,name):
                assert run==5 and name=='native-state'
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w') as z:
                    for key,value in self.names:z.writestr(key,value)
                stream.seek(0)
                return zipfile.ZipFile(stream),dict(id=8 if self.wrong else 7,digest=reference['digest'])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for index,(names,wrong) in enumerate((([('../outside','bad')],False),([('state','ok')],True),
                                                 ([('/absolute','bad')],False))):
                with self.subTest(index=index),self.assertRaises(ValueError):
                    adapter.extract_artifact(API(names,wrong),reference,root/str(index))
            extracted=adapter.extract_artifact(API([('capsule/state.json','{}')]),reference,root/'valid')
            self.assertEqual((extracted/'capsule/state.json').read_text(),'{}')
