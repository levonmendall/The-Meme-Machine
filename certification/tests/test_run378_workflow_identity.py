import base64
import hashlib
import unittest
from unittest.mock import patch

from certification import guard, single_campaign_control as control, workflow_identity as identity
from certification.tests.test_single_campaign_control import API, market


class Run378WorkflowIdentityTests(unittest.TestCase):
    def setUp(self):
        self.path = '.github/workflows/moderate-thresholds-preflight.yml'
        self.sha = '9a99c8ae5e57b4ead6671d2eb81d4d0e06802175'
        self.body = b'name: Reviewed offline fixture\njobs: {preflight: {run: deterministic}}\n'
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.pin = patch.dict(identity.REVIEWED_OFFLINE, {self.path: self.digest})
        self.pin.start(); self.addCleanup(self.pin.stop)
        self.run = dict(market(36273029605, 'in_progress', self.path), head_sha=self.sha)

    def blob(self, body=None):
        return dict(type='file', encoding='base64', content=base64.b64encode(
            self.body if body is None else body).decode())

    def api(self, status='in_progress', body=None):
        api=API(); api.runs[status]=[dict(self.run,status=status)]
        api.jobs[36273029605]=[dict(id=10,name='preflight',status=status)]
        original=api.request
        def request(method,path,body_arg=None):
            if path.startswith('contents/'):
                self.assertEqual(path,'contents/'+self.path+'?ref='+self.sha)
                return self.blob(body)
            return original(method,path,body_arg)
        api.request=request
        return api

    def test_run378_verified_preflight_is_not_market_for_every_active_status(self):
        # Original run shape was rejected solely because "preflight" was unknown.
        self.assertTrue(control.market_run(self.run,[dict(name='preflight',status='in_progress')]))
        for status in control.ACTIVE_STATUSES:
            with self.subTest(status=status):
                result=control.contention(self.api(status),5)
                self.assertTrue(result['passed'])
                self.assertEqual(result['inspected'][0]['reviewed_offline_workflow_sha256'],self.digest)

    def test_changed_or_unavailable_workflow_keeps_authority_block(self):
        with self.assertRaisesRegex(ValueError,'other_market_workflow'):
            control.contention(self.api(body=self.body+b'provider-work'),5)
        for response in ({},self.blob(b'other'),dict(type='file',encoding='base64',content='???')):
            self.assertIsNone(identity.reviewed_offline_digest(self.run,lambda p:response))
        def unavailable(path):raise OSError('unavailable')
        self.assertIsNone(identity.reviewed_offline_digest(self.run,unavailable))

    def test_job_name_alone_does_not_grant_exception(self):
        run=dict(self.run,path='.github/workflows/unknown.yml')
        def forbidden(path):self.fail('unknown workflow must not be fetched')
        self.assertIsNone(identity.reviewed_offline_digest(run,forbidden))
        self.assertTrue(control.market_run(run,[dict(name='preflight',status='in_progress')]))
        self.assertTrue(guard.active_market_job('unknown',dict(name='preflight',status='in_progress')))

    def test_changed_pinned_wrapper_is_blocked_even_with_offline_job_name(self):
        api=self.api(body=b'changed workflow')
        api.jobs[36273029605]=[dict(id=10,name='full / offline-prerequisites',status='in_progress')]
        with self.assertRaisesRegex(ValueError,'other_market_workflow'):
            control.contention(api,5)

    def test_legacy_guard_uses_same_verified_identity_and_keeps_unknown_block(self):
        job=dict(name='preflight',status='in_progress')
        verified=identity.reviewed_offline_digest(self.run,lambda p:self.blob())
        self.assertFalse(guard.active_market_job('Moderate admission threshold preflight',job,
            self.run,reviewed_offline=bool(verified)))
        self.assertTrue(guard.active_market_job('Moderate admission threshold preflight',job,
            self.run,reviewed_offline=False))

    def test_unpinned_head_never_uses_branch_tip(self):
        def forbidden(path):self.fail('no immutable source identity')
        for sha in ('','main','a'*39):
            self.assertIsNone(identity.reviewed_offline_digest(dict(self.run,head_sha=sha),forbidden))


if __name__=='__main__':unittest.main()
