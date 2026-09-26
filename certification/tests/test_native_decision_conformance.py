"""Run real frozen decision tests through capture, then replay in a clean process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SUITES={
    'pump':['tests.test_pump_acceleration_strategy','tests.test_pump_acceleration_paper'],
    'pons':['robinhood_tests.test_pons_selective_continuation.PonsSelectivePolicyTests'],
    'meteora':['tests.test_solana_dlmm_independent_v1'],
    'ramses':['robinhood_tests.test_ramses_strategy'],
}
SCRIPT=r'''
import json,os,sys,unittest
from certification.decision_conformance import install
lane,output,policy,*names=sys.argv[1:]
rec=install(output,lane,policy)
try:
 result=unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromNames(names))
 if lane=='meteora':
  from copy import deepcopy
  from meme_machine import dlmm
  from meme_machine.dlmm_tape import VerifiedTape
  from meme_machine.store import digest
  from tests.dlmm_support import snapshot
  from tests import solana_dlmm_independent_v1 as m
  start=dlmm.validate(snapshot(),100);end=deepcopy(start);end.update(time=400,slot=101)
  p=m.load_policy();features=dict(half_width_bins=4,lower=-4,upper=4)
  position=m._build_position(start,features,p)
  tape=VerifiedTape(digest(start),digest(end),(),end,digest(dict(synthetic=True)))
  m._segment_exit(position,start,tape,end,dict(volume_rate_sol_lamports_per_second=1,fee_density=1),p)
finally:rec.close()
if not result.wasSuccessful():raise SystemExit(1)
'''

class NativeConformanceTests(unittest.TestCase):
    def test_native_decisions_serialize_and_replay_without_provider_or_book(self):
        repo=Path(__file__).resolve().parents[2]
        roots=Path(os.environ.get('MM_TEST_LANE_WORKTREES',str(repo.parent/'fresh-lanes')))
        authority=json.loads((repo/'certification/sources.json').read_text())['lanes']
        if not all((roots/lane).exists() for lane in SUITES):self.skipTest('prepared lanes unavailable')
        for lane,names in SUITES.items():
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                env=dict(os.environ,PYTHONPATH=str(roots/lane)+os.pathsep+str(repo),
                    MM_CERT_INTEGRATION_SHA='offline-conformance-regression',
                    MM_CERT_SOURCE_SHA=authority[lane]['source_sha'])
                capture=subprocess.run([sys.executable,'-c',SCRIPT,lane,td,authority[lane]['policy_hash'],*names],
                    cwd=roots/lane,env=env,text=True,capture_output=True,timeout=120)
                self.assertEqual(capture.returncode,0,capture.stdout+capture.stderr)
                replay=subprocess.run([sys.executable,'-m','certification.decision_conformance',
                    '--lane',lane,'--source-root',str(roots/lane),'--trace',td+'/decision-trace.jsonl',
                    '--policy-hash',authority[lane]['policy_hash'],'--runtime-sha','offline-conformance-regression',
                    '--output',td+'/replay.json'],cwd=repo,text=True,capture_output=True,timeout=120)
                result=json.loads(Path(td+'/replay.json').read_text())
                self.assertEqual(replay.returncode,0,json.dumps(result))
                self.assertGreater(result['checked'],0)

class SurvivorConformanceTests(unittest.TestCase):
    def test_active_survivor_entry_and_runner_capture_replay(self):
        repo=Path(__file__).resolve().parents[2]
        roots=Path(os.environ.get('MM_TEST_LANE_WORKTREES',str(repo.parent/'fresh-lanes')))
        spec=json.loads((repo/'certification/sources.json').read_text())['lanes']
        if not all((roots/lane).exists() for lane in ('pump','pons')):self.skipTest('prepared lanes unavailable')
        for lane,entry in (('pump','tests.test_pumpswap_survivor'),('pons','robinhood_tests.test_pons_postgrad_survivor')):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                env=dict(os.environ,PYTHONPATH=str(roots/lane)+os.pathsep+str(repo),
                    MM_DIRECTIONAL_COMPOSITE_REQUIRED='1',MM_CERT_INTEGRATION_SHA='offline-survivor',
                    MM_CERT_SOURCE_SHA=spec[lane]['source_sha'])
                captured=subprocess.run([sys.executable,'-c',SCRIPT,lane,td,spec[lane]['policy_hash'],
                    entry,'certification.tests.test_survivor_risk_boundaries'],cwd=roots/lane,env=env,
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(captured.returncode,0,captured.stdout+captured.stderr)
                replay=subprocess.run([sys.executable,'-m','certification.decision_conformance','--lane',lane,
                    '--source-root',str(roots/lane),'--trace',td+'/decision-trace.jsonl',
                    '--policy-hash',spec[lane]['policy_hash'],'--runtime-sha','offline-survivor',
                    '--output',td+'/result.json'],cwd=repo,capture_output=True,text=True,timeout=60)
                result=json.loads(Path(td+'/result.json').read_text())
                self.assertEqual(replay.returncode,0,str(result))
                self.assertGreater(result['function_counts'].get('certification.survivor_risk:mark',0),0)
                self.assertTrue(any('survivor:evaluate_entry' in k for k in result['function_counts']))

if __name__=='__main__':unittest.main()
