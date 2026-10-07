import unittest

from meme_machine.operational.supervisor import ACTIVE_LANES,PAUSED_LANES,Supervisor


class _Db:
    def __init__(self,pending=False):self.pending=pending
    def execute(self,*_args,**_kwargs):
        pending=self.pending
        class _Row:
            def fetchone(self):return (1,) if pending else None
        return _Row()


class _Account:
    def __init__(self,*,position=False,reservation=False,pending=False):
        self.db=_Db(pending)
        self.position=position;self.reservation=reservation
    def snapshot(self):
        return dict(
            positions=({'ramses-position':dict(lane='ramses')} if self.position else {}),
            reservations=({'ramses-reservation':dict(lane='ramses')} if self.reservation else {}),
        )


class RamsesOperationalPause(unittest.TestCase):
    def test_live_runtime_excludes_ramses_but_offline_archive_retains_it(self):
        self.assertEqual(ACTIVE_LANES,('pump','pons','meteora'))
        self.assertEqual(PAUSED_LANES,{'ramses':'market_opportunity_insufficient'})
        self.assertEqual(Supervisor('/unused',offline=False).runtime_lanes(),ACTIVE_LANES)
        self.assertEqual(set(Supervisor('/unused',offline=True).runtime_lanes()),
                         {'pump','pons','meteora','ramses'})

    def test_pause_refuses_to_strand_ramses_economic_state(self):
        service=Supervisor('/unused',offline=False)
        service._assert_paused_lanes_clear(_Account())
        for kwargs in (dict(position=True),dict(reservation=True),dict(pending=True)):
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(
                    RuntimeError,'paused_lane_has_active_or_pending_exposure:ramses'):
                service._assert_paused_lanes_clear(_Account(**kwargs))

    def test_pause_does_not_delete_strategy(self):
        from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH,STRATEGY_VERSION
        self.assertTrue(POLICY_HASH)
        self.assertIn('ramses',STRATEGY_VERSION)


if __name__=='__main__':unittest.main()
