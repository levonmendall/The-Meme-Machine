import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons import pons_selective_cohort as cohort
from meme_machine.lanes.pons.provider_admission import priority


class DiscoveryCapacityTests(unittest.TestCase):
    def rpc(self,boundary='provider_shared_admission_deadline'):
        return SimpleNamespace(used=151,_last_boundary=boundary,
            telemetry=lambda:{'requests':151},
            pacer=SimpleNamespace(requests_per_second=2.0,slow_to=Mock()))

    def test_local_capacity_recovery_is_not_provider_throttling(self):
        old=self.rpc();new=object();sessions=[];recoveries=[]
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'PROVIDER_LOG',Path(td)/'providers'),patch.object(cohort,'RECOVERY_LOG',Path(td)/'recoveries'),patch.object(cohort,'_discovery',return_value=new),patch.object(cohort.time,'sleep'):
            self.assertIs(cohort._recover_discovery('unused',old,123,sessions,recoveries),new)
        old.pacer.slow_to.assert_not_called()
        self.assertEqual(len(sessions),1);self.assertEqual(len(recoveries),1)
        row=recoveries[0]
        self.assertEqual(row['kind'],'local_admission_recovery')
        self.assertTrue(row['local_capacity_limited']);self.assertFalse(row['rate_limited'])
        self.assertEqual(row['canonical_cursor_before'],123)
        self.assertFalse(row['canonical_cursor_advanced'])
        self.assertEqual(row['catchup_from'],124)

    def test_actual_provider_429_keeps_existing_backpressure(self):
        old=self.rpc('provider_rpc_429');recoveries=[]
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'PROVIDER_LOG',Path(td)/'providers'),patch.object(cohort,'RECOVERY_LOG',Path(td)/'recoveries'),patch.object(cohort,'_discovery',return_value=object()),patch.object(cohort.time,'sleep'):
            cohort._recover_discovery('unused',old,123,[],recoveries)
        old.pacer.slow_to.assert_called_once_with(1.0)
        self.assertTrue(recoveries[0]['rate_limited'])

    def test_persistent_local_pressure_remains_bounded(self):
        old=self.rpc()
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'PROVIDER_LOG',Path(td)/'providers'),patch.object(cohort,'_discovery',side_effect=BoundaryError('provider_shared_admission_deadline')) as connect,patch.object(cohort.time,'sleep'):
            with self.assertRaisesRegex(BoundaryError,'provider_recovery_exhausted'):
                cohort._recover_discovery('unused',old,123,[],[])
        self.assertEqual(connect.call_count,cohort.PROVIDER_RATE_LIMIT_ATTEMPTS)
        old.pacer.slow_to.assert_not_called()

    def test_session_rotation_recovers_without_duplicate_archive_or_cursor_advance(self):
        old=self.rpc();new=self.rpc();new.used=0;sessions=[];recoveries=[]
        def discovery(endpoint):
            self.assertEqual(priority('connectivity'),10)
            if not getattr(discovery,'called',False):
                discovery.called=True;raise BoundaryError('provider_shared_admission_deadline')
            return new
        with tempfile.TemporaryDirectory() as td,patch.object(cohort,'PROVIDER_LOG',Path(td)/'providers'),patch.object(cohort,'RECOVERY_LOG',Path(td)/'recoveries'),patch.object(cohort,'_discovery',side_effect=discovery),patch.object(cohort,'_next_discovery_end',return_value=None),patch.object(cohort.time,'sleep'):
            actual,cursor,fresh=cohort._poll('unused',old,123,[],object(),sessions,recoveries)
        self.assertIs(actual,new);self.assertEqual(cursor,123);self.assertEqual(fresh,[])
        self.assertEqual(len(sessions),1);self.assertEqual(len(recoveries),1)
        self.assertEqual(priority('connectivity'),50)

    def test_discovery_authentication_failure_stays_fail_closed(self):
        old=self.rpc()
        with patch.object(cohort,'_discovery',side_effect=BoundaryError('provider_http_401')) as connect:
            with self.assertRaisesRegex(BoundaryError,'401'):
                cohort._poll('unused',old,123,[],object(),[],[])
        self.assertEqual(connect.call_count,1)
        self.assertEqual(priority('connectivity'),50)
