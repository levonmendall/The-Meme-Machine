import unittest
from certification.report import summarize,pipeline_health
from certification.live_status import numeric_tree

class PipelineReportingTests(unittest.TestCase):
    def test_meteora_economics_are_not_settled_lifecycles(self):
        report={'attempts':[{'pre_entry_features':{},'qualification':{'passes':False}}, {'reason':'timeout'}],
                'checkpoint':{'compatibility_screened_count':3,'complete_lifecycle_count':0},
                'discovery_unique_pool_count':9}
        row=summarize('meteora',report)
        self.assertEqual(row['funnel']['complete_economic_vectors'],1)
        self.assertEqual(row['funnel']['complete_lifecycles'],0)
        self.assertEqual(row['funnel']['screened'],3)
    def test_idle_frontier_is_not_a_stall_but_blocked_scan_is(self):
        row={'scan_progress':{'state':'in_progress','stage':'economic_logs','started_at':10,'updated_at':20}}
        self.assertEqual(pipeline_health(row,321)['state'],'stalled')
        row={'finality_state':{'last_gate_reason':'frontier_unchanged'}}
        self.assertEqual(pipeline_health(row,100000)['state'],'waiting_finalized_frontier')
    def test_live_stage_and_gate_reason_are_retained(self):
        row=numeric_tree({'scan_progress':{'state':'in_progress','stage':'economic_logs'},
            'frontier':{'last_gate_reason':'frontier_unchanged'}})
        self.assertEqual(row['scan_progress']['state'],'in_progress')
        self.assertEqual(row['frontier']['last_gate_reason'],'frontier_unchanged')
