"""Owner pauses are operational state, not deletion of historical implementations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.operational.supervisor import ACTIVE_LANES,PAUSED_LANES,Supervisor
from meme_machine.operational.pause import PauseExposure
from meme_machine.operational.offline import open_native,open_position,close
from meme_machine.runtime.operating_families import PausedFamily


class RamsesOperationalPause(unittest.TestCase):
    def service(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        service=Supervisor(td.name,offline=True);service.initialize()
        self.addCleanup(lambda:service.lock.close() if service.lock else None)
        return service

    def test_live_and_offline_supervisors_have_exactly_two_active_families(self):
        self.assertEqual(ACTIVE_LANES,('pump','pons'))
        self.assertEqual(set(PAUSED_LANES),{'ramses','meteora'})
        self.assertEqual(PAUSED_LANES['ramses'],'market_opportunity_insufficient')
        for offline in (False,True):
            self.assertEqual(Supervisor('/unused',offline=offline).runtime_lanes(),ACTIVE_LANES)

    def test_pause_refuses_to_strand_native_exposure_without_shared_delivery(self):
        for lane in PAUSED_LANES:
            with self.subTest(lane=lane):
                service=self.service();(service.root/lane).mkdir()
                with patch.dict(os.environ,{},clear=True):
                    book,_,_=open_native(service.root,lane,service.epoch)
                    # Remove only the fixture's bridge to model a lost/unbound
                    # native delivery; the true native journal still has risk.
                    book.portfolio=None
                    native=open_position(book,lane,service.epoch,200)
                    close(book,lane)
                with service.account() as account:
                    self.assertFalse(account.snapshot()['positions'])
                    with self.assertRaises(PauseExposure) as caught:
                        service._assert_paused_lanes_clear(account)
                    self.assertTrue(any(r['identity']==native for r in caught.exception.obligations))

    def test_pending_delivery_is_reported_with_its_exact_identity(self):
        service=self.service()
        with service.account() as account:
            for lane in PAUSED_LANES:
                account.db.execute('INSERT INTO portfolio_native_pending VALUES(?,?,?)',
                    (lane,'unsettled-'+lane,json.dumps(dict(kind='enter',native_event_id='lost-ack'))))
            with self.assertRaises(PauseExposure) as caught:service._assert_paused_lanes_clear(account)
            self.assertEqual({r['identity'] for r in caught.exception.obligations},
                             {'unsettled-ramses','unsettled-meteora'})
            self.assertTrue(all(r['event_id']=='lost-ack' for r in caught.exception.obligations))

    def test_direct_start_and_inherited_overrides_cannot_reactivate_a_lane(self):
        service=self.service()
        with patch.dict(os.environ,{'MM_ACTIVE_LANES':'ramses,meteora','MM_RUNTIME_LANE':'ramses'}):
            for lane in PAUSED_LANES:
                with self.assertRaises(PausedFamily):service.start_lane(lane)
                with self.assertRaises(PausedFamily):service.environment(lane)
                self.assertFalse((service.root/lane).exists())
            self.assertEqual(service.runtime_lanes(),ACTIVE_LANES)

    def test_pause_does_not_delete_strategy(self):
        from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH,STRATEGY_VERSION
        from meme_machine.lanes.meteora.runner import load_policy
        self.assertTrue(POLICY_HASH);self.assertIn('ramses',STRATEGY_VERSION)
        self.assertTrue(load_policy())


if __name__=='__main__':unittest.main()
