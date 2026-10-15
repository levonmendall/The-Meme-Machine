import unittest
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_universe import _batched_logs
from meme_machine.lanes.ramses.ramses_extended_test import _scan_with_capacity_recovery


class CensusBudgetRegressionTests(unittest.TestCase):
    def test_observed_thirty_minute_window_covers_every_block_within_frozen_budget(self):
        queries=[]; progress=[]
        class Rpc:
            def batch(self,calls,scope):
                queries.extend(call[1][0] for call in calls)
                return [[] for _ in calls]
        # Exact window from run 35905479952, which exhausted seven 200-call sessions.
        _batched_logs(Rpc(),70719011,70736895,['pool'],lambda **x:progress.append(x))
        covered=[]
        for q in queries:
            covered.extend(range(int(q['fromBlock'],16),int(q['toBlock'],16)+1))
            self.assertEqual(q['address'],['pool'])
        self.assertEqual(covered,list(range(70719011,70736896)))
        self.assertEqual(len(queries),18)
        self.assertLess(len(queries)+22+1,7*200)
        self.assertEqual(progress[-1]['log_pages_completed'],18)
        self.assertEqual(progress[-1]['log_pages_total'],18)

    def test_budget_exhaustion_is_censored_without_restarting_census_or_inventing_screen(self):
        failures=[]; calls=[]
        def scan():
            calls.append(1)
            raise BoundaryError('ramses_provider_program_budget_exhausted')
        result=_scan_with_capacity_recovery(scan,deadline=100,record_failure=failures.append,
            clock=lambda:10,sleeper=lambda _:None)
        self.assertTrue(result['_scan_deferred'])
        self.assertEqual(calls,[1])
        self.assertEqual(failures[0]['failure_domain'],'local_budget')
        self.assertFalse(failures[0]['failed_admission_reached_transport'])
        self.assertFalse(failures[0]['market_screen_complete'])
        self.assertTrue(failures[0]['infrastructure_censored'])
