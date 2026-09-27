import base64
from copy import deepcopy
import unittest
from unittest.mock import patch

from certification import autonomous_launch as launch
from certification.tests.test_autonomous_control import GitAPI,IDENTITY,SHA,REF,CAMPAIGN


class LaunchAPI(GitAPI):
    def request(self,method,path,body=None):
        if path.startswith('contents/'+launch.WORKFLOW+'?ref='):
            self.calls.append((method,path,body))
            return dict(content=base64.b64encode((launch.ROOT/launch.WORKFLOW).read_bytes()).decode())
        return super().request(method,path,body)


class AutonomousLaunchTests(unittest.TestCase):
    def setUp(self):
        self.api=LaunchAPI()
        self.api.detail[1]=dict(path=launch.WORKFLOW,head_branch=launch.BRANCH,event='push',run_attempt=1,
            head_sha='b'*40,head_commit=dict(message='Explicit request [autonomous-paper-request]'))
        self.value=dict(operation='authorize',runtime_sha=SHA,runtime_ref=REF,campaign_id=CAMPAIGN,
            certification_run_id=99,reviewed_artifact_digest='',maximum_normal_windows=2)
        for target,return_value in (('checkout_files',None),('campaign_state.identity',IDENTITY)):
            patcher=patch('certification.autonomous_launch.'+target,return_value=return_value)
            patcher.start();self.addCleanup(patcher.stop)
    def posts(self):return [r for r in self.api.calls if r[0]=='POST' and r[1].endswith('/dispatches')]

    def test_existing_launch_pattern_dispatches_authorization_not_a_market_window(self):
        result=launch.launch(self.api,self.value,1,'1')
        self.assertFalse(result['entry_authority']);self.assertFalse(result['retry_allowed'])
        self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.posts()[0][2]['inputs']['operation'],'authorize')
        self.assertEqual(self.posts()[0][2]['inputs']['expected_sha'],SHA)
        with self.assertRaisesRegex(ValueError,'already_consumed'):launch.launch(self.api,self.value,1,'1')
        self.assertEqual(len(self.posts()),1)

    def test_read_only_real_workflow_availability_check_never_consumes_or_dispatches(self):
        value=dict(self.value,operation='check',certification_run_id=0)
        result=launch.launch(self.api,value,1,'1')
        self.assertFalse(result['dispatch']);self.assertEqual(result['provider_calls'],0)
        self.assertEqual(result['workflow_contract']['sha'],SHA)
        self.assertEqual(self.posts(),[]);self.assertEqual(self.api.mutations,[])

    def test_verification_dispatch_uses_no_certificate_or_campaign_authority(self):
        value=dict(self.value,operation='verify',certification_run_id=0)
        result=launch.launch(self.api,value,1,'1')
        self.assertFalse(result['entry_authority']);self.assertFalse(result['retry_allowed'])
        self.assertEqual(self.posts()[0][2]['inputs']['operation'],'verify')
        self.assertEqual(len(self.posts()),1)
        from certification.autonomous_control import store_for
        self.assertIsNone(store_for(self.api,CAMPAIGN).read())
        with self.assertRaisesRegex(ValueError,'already_consumed'):launch.launch(self.api,value,1,'1')
        self.assertEqual(len(self.posts()),1)

    def test_response_loss_is_a_consumed_intent_and_stale_smoke_acceptance_is_rejected(self):
        self.api.post_error=TimeoutError('ambiguous POST')
        with self.assertRaises(TimeoutError):launch.launch(self.api,self.value,1,'1')
        with self.assertRaisesRegex(ValueError,'already_consumed'):launch.launch(self.api,self.value,1,'1')
        self.assertEqual(len(self.posts()),1)
        self.api.post_error=None
        with self.assertRaisesRegex(ValueError,'authority_identity'):
            launch.launch(self.api,dict(self.value,operation='accept',reviewed_artifact_digest='sha256:'+'a'*64),1,'1')
        self.assertEqual(len(self.posts()),1)

    def test_request_injection_rerun_and_wrong_certificate_fail_before_dispatch(self):
        for field,value in (('runtime_sha','a'*40+'\nextra=1'),('runtime_ref',REF+'\n'),
                            ('campaign_id',CAMPAIGN+'\n'),('maximum_normal_windows',169),
                            ('reviewed_artifact_digest','anything')):
            with self.subTest(field=field),self.assertRaises(ValueError):launch.request(dict(self.value,**{field:value}))
        with self.assertRaisesRegex(ValueError,'rerun'):launch.launch(self.api,self.value,1,'2')
        self.api.detail[99]=dict(head_sha='f'*40,status='completed',conclusion='success')
        with self.assertRaisesRegex(ValueError,'exact_terminal_success'):launch.launch(self.api,self.value,1,'1')
        self.assertEqual(self.posts(),[])
