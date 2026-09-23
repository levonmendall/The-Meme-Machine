import json
import unittest
from collections import Counter
from certification.worker import Observer


class MeteoraCheckpointTests(unittest.TestCase):
    def observer(self):
        observer=Observer.__new__(Observer)
        observer.policy='policy';observer.meteora_archived={}
        observer.meteora_rejection_counts=Counter()
        observer.public_http_requests=0;observer.public_http_errors=Counter()
        self.events=[];self.snapshots=[]
        observer.event=lambda k,v:self.events.append((k,v))
        observer.checkpoint=lambda body,phase:self.snapshots.append(body)
        return observer

    def test_growing_rejections_are_lossless_without_quadratic_archive_growth(self):
        observer=self.observer()
        result=dict(discovery_api_rejections=[],frozen_policy={'rules':'frozen'},
                    accounting={'unsettled':1,'reserved':100},qualified_lifecycles=[])
        for index in range(100):
            result['discovery_api_rejections'].append(dict(pool=str(index),
                failed=['public_fee_context_zero'],raw='x'*2000))
            snapshot=observer.meteora_progress(result,'discovery_rejection')
        rows=[body['observation'] for kind,body in self.events if kind=='meteora_observation']
        self.assertEqual(rows,result['discovery_api_rejections'])
        self.assertEqual(len([k for k,_ in self.events if k=='meteora_frozen_policy']),1)
        self.assertEqual(snapshot['accounting'],result['accounting'])
        self.assertEqual(snapshot['discovery_api_rejection_counts'],{'public_fee_context_zero':100})
        self.assertLess(sum(len(json.dumps(x)) for x in self.snapshots),80000)
        self.assertIn('frozen_policy',result)
        observer.meteora_progress(result,'final')
        self.assertEqual(len([k for k,_ in self.events if k=='meteora_observation']),100)

    def test_observation_loss_and_policy_mutation_fail_closed(self):
        observer=self.observer()
        observer.meteora_progress(dict(discovery_errors=[{'reason':'timeout'}],frozen_policy={}), 'census')
        with self.assertRaisesRegex(ValueError,'history_regressed'):
            observer.meteora_progress(dict(discovery_errors=[]),'census')
        with self.assertRaisesRegex(ValueError,'frozen_policy_changed'):
            observer.meteora_progress(dict(frozen_policy={'threshold':1}),'census')
