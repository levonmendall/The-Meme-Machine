import unittest
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_extended_test import _scan_with_capacity_recovery


class ScanRecoveryTests(unittest.TestCase):
    def test_transient_retry_keeps_closure_frontier_and_original_deadline(self):
        now=[0.];rows=[];calls=[];frontier={'number':'0x12','hash':'pinned'}
        def scan():
            calls.append(frontier.copy())
            if len(calls)==1:raise BoundaryError('provider_shared_admission_deadline')
            return {'frontier':frontier.copy()}
        result=_scan_with_capacity_recovery(scan,deadline=10,record_failure=rows.append,
            clock=lambda:now[0],sleeper=lambda t:now.__setitem__(0,now[0]+t))
        self.assertEqual(calls,[frontier,frontier]);self.assertEqual(result['frontier'],frontier)
        self.assertEqual(rows[0]['original_deadline'],10)
        self.assertFalse(rows[0]['failed_admission_reached_transport'])

    def test_observation_end_preserves_incomplete_scan_without_retry(self):
        now=[0.];rows=[];calls=[]
        def scan():
            calls.append(1);now[0]=10
            raise BoundaryError('provider_shared_queue_capacity')
        self.assertIsNone(_scan_with_capacity_recovery(scan,deadline=10,record_failure=rows.append,
            clock=lambda:now[0],sleeper=lambda _:self.fail('late retry')))
        self.assertEqual(calls,[1]);self.assertEqual(len(rows),1)

    def test_persistent_local_loss_is_bounded_deferred_and_auth_failure_is_not_recovered(self):
        rows=[];calls=[]
        def admission_scan():
            calls.append(1)
            raise BoundaryError('provider_shared_admission_deadline')
        result=_scan_with_capacity_recovery(
            admission_scan,deadline=100,record_failure=rows.append,
            clock=lambda:0,sleeper=lambda _:None)
        self.assertEqual(
            result,
            {'_scan_deferred':True,'reason':'provider_shared_admission_deadline'})
        self.assertEqual(len(calls),3)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row['infrastructure_censored'] for row in rows))
        self.assertTrue(all(row['market_screen_complete'] is False for row in rows))
        self.assertTrue(all(row['qualification_inferred'] is False for row in rows))

        calls=[]
        def auth_scan():
            calls.append(1)
            raise BoundaryError('header_hash_mismatch')
        with self.assertRaisesRegex(BoundaryError,'header_hash_mismatch'):
            _scan_with_capacity_recovery(
                auth_scan,deadline=100,record_failure=lambda _row:None,
                clock=lambda:0,sleeper=lambda _:None)
        self.assertEqual(len(calls),1)

    def test_missing_result_is_fail_closed_not_completed(self):
        with self.assertRaisesRegex(BoundaryError,'missing_result'):
            _scan_with_capacity_recovery(lambda:None,deadline=100,record_failure=lambda _:None,
                clock=lambda:0,sleeper=lambda _:None)
