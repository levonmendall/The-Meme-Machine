"""Promotion must certify the tested commit, not an equivalent untested tree."""
from pathlib import Path
import tempfile
import unittest
from certification.dispatch_phase_e import dispatch, run_inventory, BRANCH, WORKFLOW

SHA='a'*40
OTHER='b'*40
PLAN='c'*64
TRIALS=('combined-1','combined-2','combined-3','recovery-1')

def evidence(sha=SHA):
    return (dict(passed=True,failures=[],integration_sha=sha,plan_sha256=PLAN,
                 trials=[dict(trial=t,passed=True) for t in TRIALS]),
            dict(passed=True,failures=[],integration_sha=sha,paper_only=True))

def run(sha=SHA,id=99):
    return dict(id=id,head_sha=sha,head_branch=BRANCH,event='workflow_dispatch',
                path='.github/workflows/'+WORKFLOW,run_attempt=1,status='queued',
                referenced_workflows=[dict(sha=sha)])

class ExactCommitFencingTests(unittest.TestCase):
    def test_identical_tree_is_not_an_exact_sha_certificate(self):
        calls=[]
        def api(repo,method,path,data=None):
            calls.append((method,path))
            if path=='git/refs' and method=='POST':return dict(ref=data['ref'],object=dict(sha=data['sha']))
            if path.startswith('git/ref'): return dict(object=dict(sha=SHA))
            if path.startswith('git/commits'): return dict(tree=dict(sha='same-tree'))
            if method=='POST': return dict(workflow_run_id=99)
            if path=='actions/runs/99': return run()
            return dict(workflow_runs=[])
        cohort,build=evidence(OTHER)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'exact_verified_sha_required'):
                dispatch('owner/repo',SHA,OTHER,PLAN,cohort,build,Path(td)/'receipt.json',api=api)
        self.assertFalse(calls, 'SHA drift must fail before external mutation')

    def test_ref_changed_after_inventory_is_not_dispatched(self):
        refs=[];posts=[]
        def api(repo,method,path,data=None):
            if path=='git/refs' and method=='POST':return dict(ref=data['ref'],object=dict(sha=data['sha']))
            if path.startswith('git/ref'):
                refs.append(1);return dict(object=dict(sha=SHA if len(refs)==1 else OTHER))
            if path.startswith('git/commits'):return dict(tree=dict(sha='tree'))
            if method=='POST':posts.append(data);return dict(workflow_run_id=99)
            if path=='actions/runs/99':return run()
            return dict(workflow_runs=[])
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'canonical_branch_moved'):
                dispatch('owner/repo',SHA,SHA,PLAN,*evidence(),Path(td)/'receipt.json',api=api)
        self.assertEqual(posts,[])

    def test_new_wrong_sha_run_is_failure_not_invisible(self):
        posts=[]
        def api(repo,method,path,data=None):
            if path=='git/refs' and method=='POST':return dict(ref=data['ref'],object=dict(sha=data['sha']))
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if path.startswith('git/commits'):return dict(tree=dict(sha='tree'))
            if method=='POST':posts.append(data);return {}
            return dict(workflow_runs=[run(OTHER)] if posts else [])
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'canonical_run_identity_mismatch'):
                dispatch('owner/repo',SHA,SHA,PLAN,*evidence(),Path(td)/'receipt.json',api=api,sleep=lambda _:None,polls=1)
        self.assertEqual(len(posts),1)

class InventoryTests(unittest.TestCase):
    def test_second_page_cannot_hide_competing_work(self):
        calls=[]
        def api(repo,method,path):
            calls.append(path)
            return dict(workflow_runs=[run(id=n) for n in range(100)] if path.endswith('page=1') else [run(id=101)])
        rows=run_inventory('owner/repo','inventory?per_page=100',api)
        self.assertEqual(len(rows),101)
        self.assertEqual(len(calls),2)

    def test_repeated_or_truncated_inventory_fails_closed(self):
        repeated=lambda *args:dict(workflow_runs=[run(id=n) for n in range(100)])
        with self.assertRaisesRegex(ValueError,'inventory_changed'):
            run_inventory('owner/repo','inventory?per_page=100',repeated)
        with self.assertRaisesRegex(ValueError,'inventory_incomplete'):
            run_inventory('owner/repo','inventory?per_page=100',repeated,max_pages=1)


class RemoteIntentTests(unittest.TestCase):
    def test_lost_runner_cannot_reacquire_same_sha_dispatch_authority(self):
        refs=set();dispatches=[]
        def api(repo,method,path,data=None):
            if path=='git/refs' and method=='POST':
                if data['ref'] in refs:raise ValueError('remote_intent_exists')
                refs.add(data['ref']);return dict(ref=data['ref'],object=dict(sha=data['sha']))
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if method=='POST':dispatches.append(data);raise TimeoutError('ambiguous')
            return dict(workflow_runs=[])
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as replacement:
            with self.assertRaisesRegex(RuntimeError,'do_not_retry'):
                dispatch('owner/repo',SHA,SHA,PLAN,*evidence(),Path(first)/'out.json',api=api,sleep=lambda _:None,polls=1)
            with self.assertRaisesRegex(ValueError,'remote_intent_exists'):
                dispatch('owner/repo',SHA,SHA,PLAN,*evidence(),Path(replacement)/'out.json',api=api,sleep=lambda _:None,polls=1)
        self.assertEqual(len(dispatches),1)

    def test_ambiguous_remote_intent_blocks_workflow_post(self):
        workflow_posts=[]
        def api(repo,method,path,data=None):
            if path=='git/refs' and method=='POST':raise TimeoutError('reservation reply lost')
            if path.startswith('git/ref'):return dict(object=dict(sha=SHA))
            if method=='POST':workflow_posts.append(data)
            return dict(workflow_runs=[])
        with tempfile.TemporaryDirectory() as td,self.assertRaises(TimeoutError):
            dispatch('owner/repo',SHA,SHA,PLAN,*evidence(),Path(td)/'out.json',api=api,polls=1)
        self.assertFalse(workflow_posts)
