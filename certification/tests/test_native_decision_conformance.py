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

if __name__=='__main__':unittest.main()
