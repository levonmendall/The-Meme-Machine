"""Exact candidate, full prerequisite, pagination and durable one-POST recovery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification.dispatch_phase_e import dispatch,reconcile_existing,prerequisites,store
from certification.tests.test_dispatch_phase_e import SHA,RUNTIME,WRONG,PLAN,accepted,build,run


class ExactDispatchTests(unittest.TestCase):
    def test_tree_equivalent_different_commit_is_not_the_verified_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'canonical_sha_not_verified_candidate'):
                dispatch('owner/repo',WRONG,RUNTIME,PLAN,accepted(),build(),Path(folder)/'receipt.json',
                    api=lambda *a: self.fail('mismatched candidate must fail before API access'))

    def test_preflight_or_incomplete_full_certificate_cannot_authorize_promotion(self):
        partial=dict(passed=True,integration_sha=RUNTIME,paper_only=True,failures=[])
        with self.assertRaisesRegex(ValueError,'complete_build'):prerequisites(accepted(),partial,RUNTIME,PLAN)
        for name in build()['gates']:
            certificate=build();certificate['gates'].pop(name)
            with self.assertRaisesRegex(ValueError,'complete_build'):
                prerequisites(accepted(),certificate,RUNTIME,PLAN)

    def test_run_on_wrong_sha_after_branch_race_fails_without_a_second_post(self):
        posts=[]
        def api(repo,method,path,data=None):
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if method=='POST':posts.append(data);return {}
            row=run();row['head_sha']=WRONG
            return dict(workflow_runs=[row] if posts else [])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'identity_mismatch'):
                dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),Path(folder)/'receipt.json',api=api,sleep=lambda _:None)
            self.assertEqual(len(posts),1)

    def test_active_run_on_second_page_cannot_be_hidden(self):
        def api(repo,method,path,data=None):
            self.assertEqual(method,'GET')
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if path.endswith('page=1'):
                return dict(total_count=101,workflow_runs=[dict(id=i,status='completed',head_sha=WRONG) for i in range(100)])
            return dict(total_count=101,workflow_runs=[dict(id=999,status='queued',head_sha=WRONG)])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'competing_canonical_run'):
                dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),Path(folder)/'receipt.json',api=api)

    def test_interrupted_response_can_be_reconciled_after_restart_with_get_only(self):
        posts=[];visible=[False]
        def api(repo,method,path,data=None):
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if method=='POST':posts.append(data);raise TimeoutError('ambiguous response')
            return dict(workflow_runs=[run()] if visible[0] else [])
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'receipt.json'
            with self.assertRaises(RuntimeError):
                dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),output,api=api,sleep=lambda _:None,polls=1)
            visible[0]=True
            def reads_only(repo,method,path,data=None):
                self.assertEqual(method,'GET');return api(repo,method,path,data)
            result=reconcile_existing('owner/repo',output,api=reads_only,sleep=lambda _:None)
            self.assertEqual(result['run_id'],99);self.assertEqual(len(posts),1)
            self.assertFalse(result['canonical_authority']);self.assertFalse(result['artifacts_verified'])

    def test_failed_json_update_preserves_previous_complete_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'receipt.json';store(output,{'previous':True})
            with patch('certification.dispatch_phase_e.os.replace',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):store(output,{'previous':False})
            self.assertEqual(json.loads(output.read_text()),{'previous':True})
            self.assertEqual(list(Path(folder).iterdir()),[output])


if __name__=='__main__':unittest.main()
