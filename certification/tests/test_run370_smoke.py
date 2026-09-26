import copy
import unittest
from certification.controls import smoke_engineering
from certification.tests import test_controls


class Run370SmokeTests(unittest.TestCase):
    def test_direct_requests_do_not_replace_authenticated_current_local_reads(self):
        good=test_controls.ControlsTests().smoke();good['lanes']['pump']['provider_requests']=0
        self.assertEqual(smoke_engineering(good)['status'],'PASS')
        for mutation in ('missing_provider','no_stream','no_local_reads','bypass','stale','no_discovery'):
            row=copy.deepcopy(good);p=row['lanes']['pump'];p['provider_requests']=100
            if mutation=='missing_provider':p['stream_state']['service_health']['provider']={}
            if mutation=='no_stream':p['stream_state']['counters']['stream_accepted_messages']=0
            if mutation=='no_local_reads':p['stream_state']['counters']['pump.complete_local_reads']=0
            if mutation=='bypass':p['method_counts']={'getTransaction':1}
            if mutation=='stale':p['evidence_liveness']['last']['usable']=False
            if mutation=='no_discovery':p['funnel']['discovered']=0
            with self.subTest(mutation=mutation):
                self.assertIn('pump:local_authoritative_evidence_activity',smoke_engineering(row)['failures'])
                self.assertNotIn('pump:no_provider_activity',smoke_engineering(row)['failures'])
