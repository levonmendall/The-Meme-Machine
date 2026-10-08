import contextlib
import io
import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from meme_machine.operational import acceptance

class Measurement(unittest.TestCase):
    def test_shared_source_is_required_and_counted_with_only_active_family_processes(self):
        health={'pid':1,'lanes':{'pump':{'pid':2},'pons':{'pid':3},'meteora':{'pid':None},'ramses':{'pid':None}},
                'providers':{'evidence':{'state':'CURRENT','phase':'ACTIVE','startup_released':True,'heartbeat':time.time(),'pid':4}}}
        self.assertEqual(acceptance.running_pids(health),[1,2,3,4])
        for key,value in (('pid',None),('startup_released',False),('phase','DEGRADED'),('heartbeat',0)):
            old=health['providers']['evidence'][key];health['providers']['evidence'][key]=value
            with self.assertRaises(ValueError):acceptance.running_pids(health)
            health['providers']['evidence'][key]=old

    def test_short_capacity_or_autonomy_is_rejected_before_runtime_access(self):
        for phase,seconds in (('CAPACITY','3599'),('AUTONOMY','129599')):
            with self.subTest(phase=phase),patch('sys.argv',['acceptance',phase,'--state-root','/missing','--seconds',seconds]), \
                    patch.object(acceptance,'validate_environment',side_effect=AssertionError('runtime reached')),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:acceptance.main()
                self.assertEqual(raised.exception.code,2)

    def fixture(self,slot):
        return ({'active_evidence':{'pons_canonical_cursor':slot},'providers':{'solana':{'state':'CURRENT','queue_depth':0,'oldest_wait_seconds':0},
                'robinhood':{'state':'CURRENT','queue_depth':0,'oldest_wait_seconds':0},
                'evidence':{'frontiers':[{'scope':s,'slot':slot} for s in ('program:pump','program:pumpswap')]} } },
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

    def test_meteora_progress_cannot_hide_stalled_pump_or_pons_coverage(self):
        samples=[]
        for n in range(40):
            health,portfolio,rss=self.fixture(1)
            health['providers']['evidence']['frontiers'].append({'scope':'program:meteora','slot':n+1})
            samples.append((health,portfolio,rss))
        value=self.measure(samples)
        self.assertFalse(value['passed'])
        self.assertEqual(len(value['errors']),3)

    def test_pump_progress_alone_does_not_pass_concurrent_pons_acceptance(self):
        samples=[]
        for n in range(40):
            health,portfolio,rss=self.fixture(n+1)
            health['active_evidence']['pons_canonical_cursor']=1
            samples.append((health,portfolio,rss))
        value=self.measure(samples)
        self.assertFalse(value['passed'])
        self.assertEqual(value['errors'],['pons:canonical:target_evidence_frontier_did_not_advance'])

    def test_read_only_health_cannot_signal_an_unrelated_process(self):
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);group=root/'system.slice'/'meme-machine-paper.service';group.mkdir(parents=True)
            (group/'cgroup.procs').write_text('100\n')
            with patch.object(acceptance,'CGROUP_ROOT',root),patch('subprocess.check_output',return_value='/system.slice/meme-machine-paper.service\n'):
                acceptance.require_owned_pid(100)
                with self.assertRaisesRegex(ValueError,'not_owned'):acceptance.require_owned_pid(101)

if __name__=='__main__':unittest.main()
