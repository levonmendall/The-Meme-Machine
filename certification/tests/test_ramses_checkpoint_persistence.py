import json
import unittest

from certification.worker import Observer, compact_ramses_screen


def screen():
    return {
        'finalized_block': 123,
        'finalized_timestamp': 456,
        'factory_pool_count': 287,
        'pools_with_recent_swaps': 3,
        'state_complete_pools': 3,
        'qualified': [],
        'elapsed_seconds': 30.0,
        'frontier_poll_index': 2,
        'cost_model': {'available': True},
        'pools_with_automatic_cost_evidence': 1,
        'provider': {
            'requests': 999,
            'transport_requests': 111,
            'logical_requests': 222,
            'retries': 3,
            'failures': {'provider_http_429': 1},
            'sessions': 4,
            'max_sessions': 7,
            'rate_limit_events': 1,
            'completed_sessions': [{'huge': 'x' * 200000}],
        },
        'rows': [{
            'pool': '0xpool',
            'swaps': 5,
            'turnover_bps': 100,
            'turnover_percentile_bps': 9000,
            'fee_percentile_bps': 8000,
            'volume_acceleration_milli': 1200,
            'chop_ratio_milli': 500,
            'flow_imbalance_bps': 1000,
            'mode': 'no_trade',
            'qualified': False,
            'reasons': ['cost_evidence_unavailable'],
            'cost_evidence': {
                'available': False,
                'source': 'automatic_onchain',
                'reason': 'no_executable_bounded_wnative_quote_route',
                'conversion': {'huge': 'y' * 200000},
            },
        }],
    }


class RamsesCheckpointCompactionTests(unittest.TestCase):
    def test_compact_projection_preserves_decision_but_drops_heavy_duplicate_detail(self):
        original=screen()
        compact=compact_ramses_screen(original)
        encoded=json.dumps(compact,sort_keys=True)
        self.assertLess(len(encoded),10000)
        self.assertNotIn('completed_sessions',compact['provider'])
        self.assertNotIn('conversion',compact['rows'][0]['cost_evidence'])
        self.assertEqual(
            compact['rows'][0]['cost_evidence']['reason'],
            'no_executable_bounded_wnative_quote_route',
        )
        self.assertEqual(compact['rows'][0]['reasons'],['cost_evidence_unavailable'])
        self.assertEqual(compact['full_detail_archive'],
                         'telemetry.sqlite:ramses_screen_observation')
        self.assertIn('completed_sessions',original['provider'])
        self.assertIn('conversion',original['rows'][0]['cost_evidence'])

    def test_full_screen_is_archived_once_while_repeated_checkpoint_is_compact(self):
        observer=Observer.__new__(Observer)
        observer.policy='policy'
        observer.ramses_screens=0
        observer.ramses_terminals=0
        observer.ramses_lifecycles=0
        events=[];checkpoints=[]
        observer.event=lambda kind,body: events.append((kind,body))
        observer.checkpoint=lambda body,phase: checkpoints.append((phase,body))
        result={
            'natural_screens':[screen()],
            'campaign_terminals':[],
            'natural_lifecycles':[],
            'policy_hash':'policy',
        }
        snapshot=Observer.ramses_progress(observer,result,'campaign_checkpoint')
        Observer.ramses_progress(observer,result,'campaign_checkpoint')
        archived=[row for row in events if row[0]=='ramses_screen_observation']
        self.assertEqual(len(archived),1)
        self.assertIn('conversion',
                      archived[0][1]['observation']['rows'][0]['cost_evidence'])
        self.assertNotIn('conversion',
                         snapshot['natural_screens'][0]['rows'][0]['cost_evidence'])
        self.assertEqual(snapshot['observation_archive']['ramses_screens'],1)
        self.assertEqual(len(checkpoints),2)

    def test_observation_history_regression_fails_closed(self):
        observer=Observer.__new__(Observer)
        observer.policy='policy'
        observer.ramses_screens=2
        observer.ramses_terminals=0
        observer.ramses_lifecycles=0
        observer.event=lambda *_args,**_kwargs: None
        observer.checkpoint=lambda *_args,**_kwargs: None
        with self.assertRaisesRegex(ValueError,'ramses_observation_history_regressed'):
            Observer.ramses_progress(observer,{
                'natural_screens':[screen()],
                'campaign_terminals':[],
                'natural_lifecycles':[],
            },'campaign_checkpoint')


if __name__=='__main__':
    unittest.main()
