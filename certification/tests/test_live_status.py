import json
import copy
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from certification.live_status import main
from unittest.mock import patch
from certification.live_status import (LIVE_STATUS_TARGET_BYTES, child_environment, numeric_tree, output, snapshot, terminal_output)

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
        failed=snapshot(dict(result,supervisor_exit_code=1,supervisor_failed=True),now=101)
        self.assertTrue(failed['supervisor_failed']);self.assertEqual(failed['supervisor_exit_code'],1)

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

    def test_many_sessions_keep_publication_bounded_and_all_totals_exact(self):
        session=dict(logical_requests=162,transport_requests=6,requests=162,retries=1,
            methods={'eth_call':8,'eth_chainId':1,'eth_getBlockByNumber':150},
            logical_methods={'eth_call':8,'eth_chainId':1,'eth_getBlockByNumber':150},
            failures={'provider_rpc_429':1},immutable_reuse={'eth_call:hit':3},
            pacing={'throttle_sleep_seconds':1})
        result={'observed_at':100,'lanes':{lane:{'health':'responsive',
            'evidence_state':{'completed_sessions':[copy.deepcopy(session) for _ in range(1000)]},
            'open_positions':1,'accounting_reconciled':True,'natural_settled':2,
            'policy_hash':'a'*64} for lane in ('pump','meteora','pons','ramses')}}
        original=copy.deepcopy(result)
        body=output(result);self.assertLess(len(body['text'].encode()),60000)
        view=snapshot(result,now=101)
        for lane in view['lanes'].values():
            state=lane['evidence_state'];summary=state['completed_session_summary']
            self.assertEqual(summary['session_count'],1000)
            self.assertEqual(summary['totals']['transport_requests'],6000)
            self.assertEqual(summary['totals']['logical_requests'],162000)
            self.assertEqual(summary['logical_methods']['eth_getBlockByNumber'],150000)
            self.assertEqual(summary['failures']['provider_rpc_429'],1000)
            self.assertEqual(summary['immutable_reuse']['eth_call:hit'],3000)
            self.assertEqual(len(state['completed_sessions']),2)
            self.assertEqual(lane['open_positions'],1)
            self.assertTrue(lane['accounting_reconciled'])
        self.assertEqual(result,original) # no raw history removal or mutation

    def test_missing_session_counters_remain_unknown(self):
        v=snapshot({'lanes':{'pons':{'evidence_state':{'completed_sessions':[{}]}}}})
        totals=v['lanes']['pons']['evidence_state']['completed_session_summary']['totals']
        self.assertIsNone(totals['logical_requests'])
        self.assertIsNone(totals['transport_requests'])

    def test_terminal_frontier_history_keeps_all_counts_and_only_recent_samples(self):
        observations=[dict(finalized_block=i,finalized_hash='0x'+'a'*64,
            finalized_timestamp=100+i,elapsed_seconds=i,expensive_scan=i%10==0,
            gate_reason='frontier_advanced' if i%10==0 else 'frontier_unchanged',
            progress='advanced' if i%10==0 else 'unchanged') for i in range(1000)]
        result={'lanes':{lane:{'finality_state':dict(observations=copy.deepcopy(observations),
            advances=99,expensive_scans=100,finalized_block=999)}
            for lane in ('pump','meteora','pons','ramses')}}
        original=copy.deepcopy(result)
        view=snapshot(result,now=1001)
        self.assertLess(len(output(result)['text'].encode()),60000)
        for row in view['lanes'].values():
            state=row['finality_state'];summary=state['observation_summary']
            self.assertEqual(summary['count'],1000)
            self.assertEqual(summary['expensive_scans'],100)
            self.assertEqual(summary['gate_reasons'],{'frontier_advanced':100,'frontier_unchanged':900})
            self.assertEqual([x['finalized_block'] for x in state['observations']],[998,999])
            self.assertEqual(state['advances'],99)
            self.assertTrue(summary['full_history_retained_in_raw_artifacts'])
        self.assertEqual(result,original)

    def test_smoke_scope_does_not_inherit_four_hour_certification_label(self):
        v=snapshot({'phase':'smoke','certification':{'scope':'four_hour_certification','required_observation_seconds':14400}})
        self.assertEqual(v['certification_scope'],'ten_minute_engineering_smoke')
        self.assertEqual(v['required_observation_seconds'],600)
        self.assertEqual(v['certification_status'],'INCOMPLETE')

    def test_immutable_cache_labels_survive_without_allowing_arbitrary_strings(self):
        value={'method':'getGenesisHash','kind':'cross_lane_hit','count':3}
        self.assertEqual(numeric_tree(value),value)
        self.assertIsNone(numeric_tree({'method':'secretvalue'})['method'])
        self.assertIsNone(numeric_tree({'kind':'secretvalue'})['kind'])
        self.assertEqual(numeric_tree({'denominator_status':'zero_or_unmeasured_no_efficiency_claim'})['denominator_status'],'zero_or_unmeasured_no_efficiency_claim')

    def test_run374_shaped_telemetry_compacts_before_github_check_limit(self):
        noisy=[]
        for i in range(100):
            noisy.append(dict(slot=450000000+i,at=i,count=i,depth=i%64,bytes=10_000_000+i,
                              scope='program:pump',state='progressing',stage='evidence'))
        result={'phase':'smoke','observed_at':100,'certification':{'status':'INCOMPLETE'},
            'shared_provider':{'solana':{'queues':noisy},'robinhood':{'queues':noisy}},
            'lanes':{lane:{'health':'responsive','continuous_uptime_seconds':600,
                'provider_requests':1000,'natural_settled':0,'forced_settled':0,'open_positions':0,
                'stream_state':{'cursors':copy.deepcopy(noisy),'active_pins':copy.deepcopy(noisy)},
                'opportunity_coverage':{'history':copy.deepcopy(noisy)},
                'funnel':{'unique_discovered':1000,'unique_admitted':10,'unique_evidence_requested':10},
                'gates':{'responsive':True,'telemetry_complete':True,'paper_only':True}}
                for lane in ('pump','meteora','pons','ramses')}}
        body=output(result)
        self.assertLessEqual(len(body['text'].encode()),LIVE_STATUS_TARGET_BYTES)
        self.assertIn('"payload_mode":"compact"',body['text'])

    def test_terminal_publication_failure_does_not_override_successful_supervisor(self):
        with tempfile.TemporaryDirectory() as temp:
            destination=str(Path(temp)/'smoke')
            process=MagicMock();process.poll.return_value=0
            env={'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,
                 'GITHUB_REPOSITORY':'levonmendall/The-Meme-Machine','GH_CHECKS_TOKEN':'secret'}
            argv=['live_status','--output',destination,'--phase','smoke','--','python','-m','certification.run','run']
            patches=[]
            def api(method,endpoint,body):
                if method=='POST':return {'id':123}
                patches.append(body)
                if len(patches)==1:raise RuntimeError('check_payload_rejected')
                return {}
            with patch.dict(os.environ,env,clear=True),patch('sys.argv',argv),\
                    patch('certification.live_status.request',side_effect=api),\
                    patch('certification.live_status.subprocess.Popen',return_value=process),\
                    patch('certification.live_status.signal.signal'):
                with self.assertRaises(SystemExit) as done:main()
            self.assertEqual(done.exception.code,0)
            self.assertEqual(patches[-1]['status'],'completed')
            self.assertIn('"payload_mode":"terminal_fallback"',patches[-1]['output']['text'])
            journal=Path(temp,'smoke-publisher.jsonl').read_text()
            self.assertIn('publish_failed',journal)
            self.assertIn('terminal_fallback_published',journal)
            self.assertIn('"terminal_check_closed": true',journal)

    def test_supervisor_failure_still_propagates_through_publisher(self):
        with tempfile.TemporaryDirectory() as temp:
            destination=str(Path(temp)/'smoke')
            process=MagicMock();process.poll.return_value=7
            env={'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,
                 'GITHUB_REPOSITORY':'levonmendall/The-Meme-Machine','GH_CHECKS_TOKEN':'secret'}
            argv=['live_status','--output',destination,'--phase','smoke','--','python','-m','certification.run','run']
            with patch.dict(os.environ,env,clear=True),patch('sys.argv',argv),\
                    patch('certification.live_status.request',return_value={'id':123}),\
                    patch('certification.live_status.subprocess.Popen',return_value=process),\
                    patch('certification.live_status.signal.signal'):
                with self.assertRaises(SystemExit) as done:main()
            self.assertEqual(done.exception.code,7)

    def test_terminal_fallback_contains_exact_runtime_identity_and_gate(self):
        body=terminal_output({'phase':'smoke','status':'FINISHED',
            'smoke_engineering':{'status':'PASS'},'certification':{'status':'INCOMPLETE'},
            'supervisor_exit_code':0,'supervisor_failed':False,
            'lanes':{'pump':{'health':'exited','exit_code':0,'unexpected_exit':False,'open_positions':0}}},
            integration_sha='b'*40)
        self.assertLess(len(body['text'].encode()),LIVE_STATUS_TARGET_BYTES)
        self.assertIn('"integration_sha":"'+('b'*40)+'"',body['text'])
        self.assertIn('"engineering_status":"PASS"',body['text'])

