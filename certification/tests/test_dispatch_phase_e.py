import copy
import tempfile
from pathlib import Path
import unittest
from certification.dispatch_phase_e import dispatch,run_identity,prerequisites,BRANCH,WORKFLOW,FULL_GATES

SHA='a'*40;RUNTIME=SHA;WRONG='b'*40;PLAN='c'*64

def accepted():
    return dict(passed=True,failures=[],canonical_authority=False,integration_sha=RUNTIME,plan_sha256=PLAN,
        trials=[dict(trial=t,passed=True) for t in ('combined-1','combined-2','combined-3','recovery-1')])

def build():return dict(passed=True,integration_sha=RUNTIME,expected_integration_sha=RUNTIME,
    engineering_certification='CERTIFIED_NON_MARKET_ENGINEERING',validation_scope='preserved_evidence_only',
    paper_only=True,live_money=False,failures=[],gates={name:True for name in FULL_GATES})

def run():return dict(id=99,head_sha=SHA,head_branch=BRANCH,event='workflow_dispatch',
    path='.github/workflows/'+WORKFLOW,run_attempt=1,status='queued',
    referenced_workflows=[dict(sha=SHA)])


class DispatchTests(unittest.TestCase):
    def test_requires_every_fixed_trial_and_complete_build(self):
        prerequisites(accepted(),build(),RUNTIME,PLAN)
        for index in range(4):
            row=accepted();row['trials'][index]['passed']=False
            with self.assertRaisesRegex(ValueError,'fixed_cohort'):prerequisites(row,build(),RUNTIME,PLAN)
        row=accepted();row['trials'][3]=row['trials'][0]
        with self.assertRaises(ValueError):prerequisites(row,build(),RUNTIME,PLAN)
        row=build();row['integration_sha']=WRONG
        with self.assertRaisesRegex(ValueError,'complete_build'):prerequisites(accepted(),row,RUNTIME,PLAN)

    def test_wrong_sha_branch_event_attempt_and_reusable_sha_fail(self):
        for field,value in (('head_sha',WRONG),('head_branch','main'),('event','push'),('run_attempt',2)):
            row=run();row[field]=value
            with self.assertRaises(ValueError):run_identity(row,SHA)
        row=run();row['referenced_workflows']=[dict(sha=WRONG)]
        with self.assertRaisesRegex(ValueError,'reusable'):run_identity(row,SHA)

    def test_ambiguous_post_reconciles_get_only_without_duplicate(self):
        calls=[];posts=[]
        def api(repo,method,path,data=None):
            calls.append((method,path))
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if path.startswith('git/commits'):return dict(tree=dict(sha='tree'))
            if method=='POST':
                posts.append(data);raise TimeoutError('response lost')
            return dict(workflow_runs=[run()] if posts else [])
        with tempfile.TemporaryDirectory() as td:
            result=dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),Path(td)/'receipt.json',api=api,sleep=lambda _:None)
            self.assertEqual(len(posts),1);self.assertEqual(result['run_id'],99)
            self.assertEqual(posts[0]['inputs']['expected_sha'],SHA)

    def test_duplicate_local_intent_blocks_another_post(self):
        posts=[]
        def api(repo,method,path,data=None):
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if path.startswith('git/commits'):return dict(tree=dict(sha='tree'))
            if method=='POST':posts.append(1);return {}
            return dict(workflow_runs=[])
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'receipt.json'
            with self.assertRaisesRegex(RuntimeError,'do_not_retry'):
                dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),target,api=api,sleep=lambda _:None,polls=1)
            with self.assertRaises(FileExistsError):
                dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),target,api=api,sleep=lambda _:None,polls=1)
            self.assertEqual(len(posts),1)

    def test_moved_branch_does_not_dispatch(self):
        def api(repo,method,path,data=None):
            self.assertEqual(method,'GET');return dict(object=dict(sha=WRONG))
        with tempfile.TemporaryDirectory() as td,self.assertRaisesRegex(ValueError,'branch_moved'):
            dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),Path(td)/'receipt.json',api=api)

    def test_current_api_response_id_is_verified(self):
        def api(repo,method,path,data=None):
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if path.startswith('git/commits'):return dict(tree=dict(sha='tree'))
            if method=='POST':return dict(workflow_run_id=99)
            if path=='actions/runs/99':return run()
            return dict(workflow_runs=[])
        with tempfile.TemporaryDirectory() as td:
            row=dispatch('owner/repo',SHA,RUNTIME,PLAN,accepted(),build(),Path(td)/'receipt.json',api=api)
            self.assertEqual(row['run_id'],99)
