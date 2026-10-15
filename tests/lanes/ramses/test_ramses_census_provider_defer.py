import unittest

from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_extended_test import _scan_with_capacity_recovery


class RamsesCensusProviderDeferTests(unittest.TestCase):
    def test_exhausted_transient_transport_defers_without_replaying_full_scan(self):
        calls=[]
        failures=[]
        def scan():
            calls.append('scan')
            raise BoundaryError('provider_http_429')
        result=_scan_with_capacity_recovery(
            scan,deadline=100,record_failure=failures.append,
            clock=lambda:10,sleeper=lambda _seconds:None,
        )
        self.assertEqual(result,{'_scan_deferred':True,'reason':'provider_http_429'})
        self.assertEqual(calls,['scan'])
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]['failure_domain'],'provider_transport')
        self.assertTrue(failures[0]['failed_admission_reached_transport'])
        self.assertFalse(failures[0]['market_screen_complete'])
        self.assertFalse(failures[0]['qualification_inferred'])
        self.assertTrue(failures[0]['infrastructure_censored'])

    def test_nontransient_scan_boundary_still_fails_closed(self):
        with self.assertRaisesRegex(BoundaryError,'ramses_universe_log_identity'):
            _scan_with_capacity_recovery(
                lambda: (_ for _ in ()).throw(BoundaryError('ramses_universe_log_identity')),
                deadline=100,record_failure=lambda _row:None,
                clock=lambda:10,sleeper=lambda _seconds:None,
            )


if __name__=='__main__':
    unittest.main()
