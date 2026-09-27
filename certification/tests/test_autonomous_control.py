"""Actual Git CAS, workflow dispatch bytes and controller crash boundaries."""
import base64
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from certification import autonomous_control as c
from certification import prospective_program
from certification.journal import digest
from certification.tests.test_single_campaign_control import API as MarketAPI, SHA, market

REF='cert/autonomous-paper-fixture'
CAMPAIGN='autonomous-fixture'
IDENTITY=dict(integration_sha=SHA,implementation_hash='b'*64,source_manifest_hash='c'*64,
    policy_manifest_hash='d'*64,source_diff_hashes={lane:'e'*64 for lane in c.LANES},
    paper_only=True,live_money=False)


class GitAPI(MarketAPI):
    def __init__(self):
        super().__init__();self.refs={REF:SHA};self.commits={SHA:dict(tree={'sha':'base'},parents=[])}
        self.trees={'base':dict(tree=[])};self.blobs={};self.artifacts={};self.active=True
        self.contract=(c.ROOT/c.WORKFLOW_PATH).read_bytes();self.mutations=[];self.fail_ref=False
    def request(self,method,path,body=None):
        self.calls.append((method,path,deepcopy(body)))
        if path=='actions/workflows/'+c.WORKFLOW:
            return dict(id=900,state='active' if self.active else 'disabled_manually',path=c.WORKFLOW_PATH)
        if path.startswith('contents/'):
            return dict(encoding='base64',content=base64.b64encode(self.contract).decode())
        if '/artifacts?per_page=100&page=' in path:
            rows=self.artifacts.get(int(path.split('/')[2]),[])
            page=int(path.rsplit('=',1)[1]);return dict(artifacts=rows[(page-1)*100:page*100],total_count=len(rows))
        if path.startswith('git/'):
            if method!='GET':self.mutations.append((method,path,deepcopy(body)))
            if method=='GET':
                if path.startswith('git/ref/heads/'):
                    ref=path.removeprefix('git/ref/heads/')
                    if ref not in self.refs:raise HTTPError(path,404,'not found',None,None)
                    return dict(object=dict(sha=self.refs[ref]))
                if path.startswith('git/commits/'):return self.commits[path.split('/')[-1]]
                if path.startswith('git/trees/'):return self.trees[path.split('/')[-1].split('?')[0]]
                if path.startswith('git/blobs/'):return self.blobs[path.split('/')[-1]]
            if method=='POST' and path=='git/trees':
                entries={x['path']:deepcopy(x) for x in self.trees[body['base_tree']]['tree']}
                for row in body['tree']:
                    sha=digest(row['content'])[:40]
                    self.blobs[sha]=dict(content=base64.b64encode(row['content'].encode()).decode())
                    entries[row['path']]=dict(path=row['path'],mode=row['mode'],type='blob',sha=sha)
                sha=digest(list(entries.values()))[:40];self.trees[sha]=dict(tree=list(entries.values()))
                return dict(sha=sha)
            if method=='POST' and path=='git/commits':
                sha=digest(body)[:40];self.commits[sha]=dict(tree=dict(sha=body['tree']),parents=body['parents'])
                return dict(sha=sha)
            if method=='POST' and path=='git/refs':
                ref=body['ref'].removeprefix('refs/heads/')
                if ref in self.refs or self.fail_ref:raise ValueError('git_ref_collision')
                self.refs[ref]=body['sha'];return {}
            if method=='PATCH' and path.startswith('git/refs/heads/'):
                ref=path.removeprefix('git/refs/heads/')
                if (body['force'] is not False or self.refs[ref] not in self.commits[body['sha']]['parents']
                        or self.fail_ref):raise ValueError('git_non_fast_forward')
                self.refs[ref]=body['sha'];return {}
            raise AssertionError((method,path))
        self.calls.pop()
        return super().request(method,path,body)
    def run(self,run,nonce='controller'):
        self.detail[run]=dict(id=run,path=c.WORKFLOW_PATH,head_sha=SHA,head_branch=REF,
            event='workflow_dispatch',run_attempt=1,status='in_progress',conclusion=None,
            display_title=f'PAPER {CAMPAIGN} {nonce}')
    def terminal(self,run):self.detail[run].update(status='completed',conclusion='success')


class AutonomousControllerTests(unittest.TestCase):
    def setUp(self):
        self.api=GitAPI();self.api.run(1)
        self.cert=patch.object(prospective_program,'certificate',return_value=dict(IDENTITY,passed=True))
        self.cert.start();self.addCleanup(self.cert.stop)
    def state(self):return c.store_for(self.api,CAMPAIGN).read()
    def posts(self):return [x for x in self.api.calls if x[0]=='POST' and x[1].endswith('/dispatches')]
    def authorize(self):return c.authorize(self.api,IDENTITY,CAMPAIGN,REF,99,1,maximum_windows=2)
    def start(self,actor,run):
        state=c.dispatch_next(self.api,IDENTITY,CAMPAIGN,actor)
        self.api.terminal(actor);self.api.run(run,state['window']['nonce'])
        claim=c.claim(self.api,IDENTITY,CAMPAIGN,state['window']['nonce'],run)
        return claim
    def finish(self,run,positions=None):
        state=self.state();w=state['window'];positions=positions or {lane:[] for lane in c.LANES}
        bound=dict(campaign_id=CAMPAIGN,index=w['index'],workflow_run_id=run,
            native_run_id=w['native_run_id'],authorization_hash=state['authorization_hash'])
        if w['index']:bound['parent_state_hash']=w['parent_state_hash']
        capsule=dict(identity=IDENTITY,window=bound,entry_authority=False,
            discovery_window=state['previous']['discovery_window'] if w['mode']=='position' else bound,
            accounting={lane:dict(verified=True,open_positions=len(positions[lane])) for lane in c.LANES})
        capsule['state_hash']=digest(capsule)
        review=dict(passed=True,identity=IDENTITY,state_hash=capsule['state_hash'],mode=w['mode'],
            entry_authority=w['entry_authority'],gates={key:True for key in c.REVIEW_GATES},open_positions=positions)
        artifact=dict(id=run,name=c.artifact_name(state,run),digest='sha256:'+digest(capsule),workflow_run_id=run)
        self.api.artifacts[run]=[dict(artifact,expired=False)]
        return c.finish(self.api,IDENTITY,CAMPAIGN,run,capsule=capsule,review=review,artifact=artifact)
    def smoke(self,positions=None):
        self.authorize();self.start(1,2);self.finish(2,positions)
        self.api.terminal(2);self.api.run(3)
        c.accept_smoke(self.api,IDENTITY,CAMPAIGN,self.state()['previous']['artifact']['digest'],3)

    def test_smoke_review_then_two_normal_successors_same_sha_manifest_and_capital_identity(self):
        self.authorize();claim=self.start(1,2);native=claim['window']['native_run_id'];self.finish(2)
        with self.assertRaisesRegex(ValueError,'not_ready'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,2)
        self.api.terminal(2);self.api.run(3)
        with self.assertRaisesRegex(ValueError,'review_digest'):c.accept_smoke(self.api,IDENTITY,CAMPAIGN,'sha256:'+'0'*64,3)
        c.accept_smoke(self.api,IDENTITY,CAMPAIGN,self.state()['previous']['artifact']['digest'],3)
        for actor,run in ((3,4),(4,5)):
            claim=self.start(actor,run)
            self.assertEqual(claim['window']['mode'],'hourly')
            self.assertEqual(claim['window']['native_run_id'],native)
            self.assertEqual(claim['identity'],IDENTITY)
            self.finish(run)
        result=c.dispatch_next(self.api,IDENTITY,CAMPAIGN,5)
        self.assertEqual(result['phase'],'STOPPED');self.assertEqual(len(self.posts()),3)
        for _,_,request in self.posts():
            self.assertEqual(request['ref'],REF);self.assertEqual(request['inputs']['expected_sha'],SHA)
        self.assertTrue(all(body.get('force') is False for method,_,body in self.api.mutations if method=='PATCH'))

    def test_intent_survives_ambiguous_post_and_cannot_be_dispatched_twice(self):
        self.authorize();self.api.post_error=TimeoutError('response lost')
        with self.assertRaises(TimeoutError):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,1)
        state=self.state();self.assertEqual(state['phase'],'HANDOFF_PENDING')
        self.assertFalse(state['retry_allowed'])
        with self.assertRaisesRegex(ValueError,'already_consumed'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,1)
        self.assertEqual(len(self.posts()),1)
        self.api.post_error=None;self.api.terminal(1);self.api.run(2,state['window']['nonce'])
        c.claim(self.api,IDENTITY,CAMPAIGN,state['window']['nonce'],2)
        with self.assertRaisesRegex(ValueError,'duplicate'):c.claim(self.api,IDENTITY,CAMPAIGN,state['window']['nonce'],2)

    def test_crash_after_durable_intent_before_post_cannot_create_hidden_retry(self):
        self.authorize();original=c.workflow_contract;calls=[]
        def cut(*args):
            calls.append(1)
            if len(calls)==2:raise SystemExit('process death before dispatch POST')
            return original(*args)
        with patch.object(c,'workflow_contract',side_effect=cut),self.assertRaises(SystemExit):
            c.dispatch_next(self.api,IDENTITY,CAMPAIGN,1)
        self.assertEqual(self.state()['phase'],'HANDOFF_PENDING');self.assertEqual(self.posts(),[])
        with self.assertRaisesRegex(ValueError,'already_consumed'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,1)

    def test_actual_git_ref_cas_rejects_concurrent_dispatch_writers(self):
        self.authorize();a=c.store_for(self.api,CAMPAIGN);b=c.store_for(self.api,CAMPAIGN)
        first=a.read();second=b.read();first['phase']='STOPPED';a.write(first)
        second['phase']='HANDOFF_PENDING'
        with self.assertRaisesRegex(ValueError,'non_fast_forward'):b.write(second)
        self.assertEqual(self.state()['phase'],'STOPPED')

    def test_workflow_registration_ref_bytes_and_authority_are_required(self):
        for kind in ('inactive','wrong_ref','wrong_bytes','live'):
            self.api=GitAPI();self.api.run(1);expected=deepcopy(IDENTITY)
            if kind=='inactive':self.api.active=False
            if kind=='wrong_ref':self.api.refs[REF]='f'*40
            if kind=='wrong_bytes':self.api.contract+=b'changed'
            if kind=='live':expected['live_money']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                c.authorize(self.api,expected,CAMPAIGN,REF,99,1)
            self.assertEqual(self.posts(),[]);self.assertIsNone(self.state())

    def test_queued_competitor_wrong_sha_nonce_and_incomplete_predecessor_fail_closed(self):
        self.smoke();state=c.dispatch_next(self.api,IDENTITY,CAMPAIGN,3);self.api.terminal(3)
        nonce=state['window']['nonce'];self.api.run(4,nonce)
        with self.assertRaisesRegex(ValueError,'authority_identity'):
            c.claim(self.api,dict(IDENTITY,policy_manifest_hash='wrong'),CAMPAIGN,nonce,4)
        with self.assertRaisesRegex(ValueError,'stale'):c.claim(self.api,IDENTITY,CAMPAIGN,'wrong',4)
        self.api.detail[2]['status']='in_progress'
        with self.assertRaisesRegex(ValueError,'not_terminal'):c.claim(self.api,IDENTITY,CAMPAIGN,nonce,4)
        self.api.terminal(2);self.api.runs['queued']=[market(50,path='.github/workflows/position-continuation.yml')]
        with self.assertRaises(ValueError):c.claim(self.api,IDENTITY,CAMPAIGN,nonce,4)
        self.assertEqual(self.state()['phase'],'HANDOFF_PENDING')

    def test_position_window_keeps_campaign_position_and_no_entry_authority(self):
        positions={lane:[] for lane in c.LANES};positions['pump']=['original-current','original-survivor']
        self.smoke(positions);claim=self.start(3,4)
        self.assertEqual(claim['window']['mode'],'position');self.assertFalse(claim['window']['entry_authority'])
        self.assertEqual(claim['window']['positions'],positions)
        changed=deepcopy(positions);changed['pump'].append('unauthorized-new-position')
        with self.assertRaisesRegex(ValueError,'created_position'):self.finish(4,changed)
        self.finish(4)
        claim=self.start(4,5);self.assertEqual(claim['window']['mode'],'hourly')

    def test_artifact_loss_or_cas_failure_prevents_post_and_reruns_are_rejected(self):
        self.smoke();self.api.artifacts[2][0]['expired']=True
        with self.assertRaisesRegex(ValueError,'not_preserved'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,3)
        self.assertEqual(len(self.posts()),1)
        self.api.artifacts[2][0]['expired']=False;self.api.fail_ref=True
        with self.assertRaisesRegex(ValueError,'non_fast_forward'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,3)
        self.assertEqual(len(self.posts()),1)
        with self.assertRaisesRegex(ValueError,'rerun'):c.dispatch_next(self.api,IDENTITY,CAMPAIGN,3,attempt='2')
