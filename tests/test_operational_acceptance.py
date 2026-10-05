import contextlib
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from meme_machine.operational import acceptance

class Measurement(unittest.TestCase):
    def test_short_capacity_or_autonomy_is_rejected_before_runtime_access(self):
        for phase,seconds in (('CAPACITY','3599'),('AUTONOMY','129599')):
            with self.subTest(phase=phase),patch('sys.argv',['acceptance',phase,'--state-root','/missing','--seconds',seconds]), \
                    patch.object(acceptance,'validate_environment',side_effect=AssertionError('runtime reached')),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:acceptance.main()
                self.assertEqual(raised.exception.code,2)

    def fixture(self,slot):
        return ({'providers':{'solana':{'state':'CURRENT','queue_depth':0,'oldest_wait_seconds':0},
                'robinhood':{'state':'CURRENT','queue_depth':0,'oldest_wait_seconds':0},
                'evidence':{'frontiers':[{'scope':'program:pump','slot':slot}]} } },
            {'balances':{'realized_pnl':'-2'}},1000)

    def measure(self,samples):
        now=[0]
        def sleep(s):now[0]+=s
        def observe(_):
            if samples and isinstance(samples[0],Exception):raise samples.pop(0)
            return samples.pop(0) if samples else self.fixture(now[0]+1)
        with patch.object(acceptance,'observe',side_effect=observe):
            return acceptance.measure(None,200,clock=lambda:now[0],sleeper=sleep)

    def test_bounded_self_recovery_does_not_fail_a_complete_window(self):
        value=self.measure([self.fixture(1),ValueError('temporary'),self.fixture(2)])
        self.assertTrue(value['passed']);self.assertEqual(value['elapsed_seconds'],200)
        self.assertEqual(value['self_healing_events'],1)

    def test_persistent_failure_cannot_be_combined_with_later_recovery(self):
        value=self.measure([ValueError('provider_unavailable')]*38+[self.fixture(1),self.fixture(2)])
        self.assertFalse(value['passed']);self.assertTrue(value['errors'])

    def test_accounting_failure_is_not_dismissed_as_a_transient(self):
        value=self.measure([ValueError('portfolio_not_reconciled'),self.fixture(1),self.fixture(2)])
        self.assertFalse(value['passed'])

    def test_read_only_health_cannot_signal_an_unrelated_process(self):
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);group=root/'system.slice'/'meme-machine-paper.service';group.mkdir(parents=True)
            (group/'cgroup.procs').write_text('100\n')
            with patch.object(acceptance,'CGROUP_ROOT',root),patch('subprocess.check_output',return_value='/system.slice/meme-machine-paper.service\n'):
                acceptance.require_owned_pid(100)
                with self.assertRaisesRegex(ValueError,'not_owned'):acceptance.require_owned_pid(101)

if __name__=='__main__':unittest.main()
