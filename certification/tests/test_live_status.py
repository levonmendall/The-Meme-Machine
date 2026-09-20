import json
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from certification.live_status import main
from unittest.mock import patch
from certification.live_status import child_environment, numeric_tree, output, snapshot

class LiveStatusTests(unittest.TestCase):
    def test_unknown_is_not_zero_or_healthy_and_stale_is_explicit(self):
        unknown=snapshot({},now=1000)
        self.assertTrue(unknown['stale'])
        for row in unknown['lanes'].values():
            self.assertEqual(row['health'],'unknown')
            self.assertIsNone(row['natural_settled'])
            self.assertIsNone(row['accounting_reconciled'])
        result={'observed_at':800,'lanes':{'pump':{'health':'responsive','natural_settled':2}}}
        self.assertTrue(snapshot(result,now=1000)['stale'])
        self.assertFalse(snapshot(result,now=850)['stale'])
        self.assertEqual(snapshot(result,now=850)['lanes']['pump']['natural_settled'],2)

    def test_credentials_and_raw_evidence_are_not_published_or_inherited(self):
        secret='https://rpc.example/?api-key=do-not-publish'
        result={'raw_rpc':secret,'lanes':{'pump':{'provider_state':secret,
            'errors':{'HTTPError':3,'https://rpc.example/secret':1},
            'native_accounting':{'cash':100,'url':secret,'private_key':123,'label':secret},
            'policy_hash':'a'*64,'strategy_version':'v1.7'}}}
        body=json.dumps(output(result));self.assertNotIn(secret,body)
        self.assertNotIn('private_key',body);self.assertNotIn('https://rpc.example',body)
        self.assertIn('HTTPError',body);self.assertIn('"cash":100',output(result)['text'])
        with patch.dict(os.environ,{'GH_CHECKS_TOKEN':'secret','GITHUB_TOKEN':'secret','MM_SOLANA_READ_RPC_URL':'read-only'},clear=True):
            child=child_environment();self.assertNotIn('GH_CHECKS_TOKEN',child)
            self.assertNotIn('GITHUB_TOKEN',child);self.assertEqual(child['MM_SOLANA_READ_RPC_URL'],'read-only')

    def test_position_and_provider_counts_are_independent(self):
        result={'observed_at':100,'lanes':{'pons':{'natural_settled':1,'forced_settled':2,
            'open_positions':3,'accounting_reconciled':False,'funnel':{'evaluated':49},
            'process_restarts':0,'errors':{'HTTPError':7}}},'shared_provider':{'solana':{'queues':[{'depth':14}]}}}
        v=snapshot(result,now=101)
        self.assertEqual(v['lanes']['pons']['open_positions'],3)
        self.assertFalse(v['lanes']['pons']['accounting_reconciled'])
        self.assertEqual(v['shared_provider']['solana']['queues'][0]['depth'],14)
        self.assertEqual(v['certification_status'],'INCOMPLETE')
        self.assertIsNone(numeric_tree(float('inf')))

    def test_publisher_starts_before_child_and_does_not_restart_it(self):
        with tempfile.TemporaryDirectory() as temp:
            destination=str(Path(temp)/'smoke')
            process=MagicMock();process.poll.return_value=0
            env={'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,
                 'GITHUB_REPOSITORY':'levonmendall/The-Meme-Machine','GH_CHECKS_TOKEN':'secret'}
            argv=['live_status','--output',destination,'--phase','smoke','--','python','-m','certification.run','run']
            with patch.dict(os.environ,env,clear=True),patch('sys.argv',argv),patch('certification.live_status.request',return_value={'id':123}) as api,patch('certification.live_status.subprocess.Popen',return_value=process) as launch,patch('certification.live_status.signal.signal'):
                with self.assertRaises(SystemExit) as done:main()
                self.assertEqual(done.exception.code,0);launch.assert_called_once()
                self.assertNotIn('GH_CHECKS_TOKEN',launch.call_args.kwargs['env'])
                self.assertEqual(api.call_args_list[0].args[0],'POST')
                self.assertEqual(api.call_args_list[-1].args[2]['conclusion'],'neutral')
                self.assertTrue(Path(temp,'smoke-publisher.jsonl').exists())
            with patch.dict(os.environ,env,clear=True),patch('sys.argv',argv),patch('certification.live_status.request',side_effect=RuntimeError('not_authorized')),patch('certification.live_status.subprocess.Popen') as launch:
                with self.assertRaises(RuntimeError):main()
                launch.assert_not_called()
