import unittest

from meme_machine.lanes.pump import runner as runner


class PumpSmokeTailTests(unittest.TestCase):
    def test_smoke_tail_closes_at_discovery_boundary_only_in_smoke(self):
        self.assertFalse(runner._smoke_tail_admission_closed(True,599,600))
        self.assertTrue(runner._smoke_tail_admission_closed(True,600,600))
        self.assertFalse(runner._smoke_tail_admission_closed(False,900,600))

    def test_smoke_tail_exits_only_when_flat(self):
        self.assertTrue(runner._smoke_tail_should_exit(True,600,600,{},{}))
        self.assertFalse(runner._smoke_tail_should_exit(True,600,600,{('mint','mode'):{}},{}))
        self.assertFalse(runner._smoke_tail_should_exit(True,600,600,{}, {('mint','mode'):{}}))
        self.assertFalse(runner._smoke_tail_should_exit(False,1600,600,{},{}))


if __name__=='__main__':
    unittest.main()
