"""Real SIGKILL before/after native transactions, with no market or epoch writes."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

class NativeCrashRecoveryTests(unittest.TestCase):
    def check_lane(self,lane):
        with tempfile.TemporaryDirectory() as folder:
            command=[sys.executable,'-m','tests.native_crash_child','--lane',lane,'--db',str(Path(folder)/'native.sqlite')]
            environment={k:v for k,v in os.environ.items() if not k.startswith('MM_')}
            def call(*args):
                return subprocess.run(command+list(args),cwd=Path(__file__).resolve().parents[1],
                    env=environment,capture_output=True,text=True,timeout=20)
            def read():
                result=call('--inspect');self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            result=call('--step','0');self.assertEqual(result.returncode,-9,result.stderr)
            initial=read()
            result=call('--step','1','--before-commit');self.assertEqual(result.returncode,-9,result.stderr)
            self.assertEqual(read(),initial,'uncommitted reservation survived')
            for step in range(1,5):
                result=call('--step',str(step));self.assertEqual(result.returncode,-9,result.stderr)
                state=read();self.assertEqual(read(),state)
                if step in (1,2,4):
                    call('--step',str(step));self.assertEqual(read(),state,'duplicate changed native state')
            final=read()
            if lane=='pump':
                self.assertEqual(final['cash'],1030);self.assertEqual(final['reserved'],0);self.assertEqual(final['open_positions'],0)
            elif lane=='pons':
                self.assertEqual(final['cash'],1026);self.assertEqual(final['remaining_cost_basis'],0)
            elif lane=='ramses':
                self.assertEqual(final['available'],1030);self.assertEqual(final['committed'],0);self.assertEqual(final['open_positions'],0)
            else:
                self.assertEqual(final['cash'],1_000_000_000+final['realized_pnl_lamports'])
                self.assertEqual(final['settled'],1);self.assertEqual(final['open_positions'],0);self.assertEqual(final['reserved'],0)
    def test_pump_native_transaction_crash_recovery(self):self.check_lane('pump')
    def test_pons_native_transaction_crash_recovery(self):self.check_lane('pons')
    def test_meteora_native_transaction_crash_recovery(self):self.check_lane('meteora')
    def test_ramses_native_transaction_crash_recovery(self):self.check_lane('ramses')
