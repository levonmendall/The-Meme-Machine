"""Reuse existing authoritative provider and long-lifecycle proofs, offline only."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

PROVIDER = (
    'tests.test_provider_retry', 'tests.test_provider_partial_batch_retry',
    'tests.test_solana_evidence_plane', 'tests.test_solana_evidence_service_runtime',
    'certification.tests.test_survivor_acquisition',
    'certification.tests.test_normal_window_recovery',
    'certification.tests.test_governor_method_pressure',
    'certification.tests.test_solana_efficiency.SolanaEfficiencyTests.test_physical_governor_foreground_fairness_and_position_priority',
)
LONG_HORIZON = (
    'tests.test_dlmm_independent_accounting.DurableIndependentAccounting.test_full_lifecycle_reopens_replays_and_recycles_only_actual_cash',
    'certification.tests.test_ramses_long_horizon',
)


def run(sources,output,kind):
    from certification.campaign_state import identity
    from certification.offline_tests import install_network_guard
    sources=Path(sources).resolve()
    output=Path(output).resolve()
    os.environ['MM_TEST_LANE_WORKTREES']=str(sources)
    # Solana service integration tests live in the integration repository; its
    # runtime bytes are themselves pinned into both prepared Solana lanes.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1] if kind=='provider' else sources/'meteora'))
    if kind=='long_horizon':os.chdir(sources/'meteora')
    forbidden=install_network_guard()
    names=PROVIDER if kind=='provider' else LONG_HORIZON
    class Result(unittest.TextTestResult):
        def startTestRun(self):self.rows=[]
        def addSuccess(self,test):
            super().addSuccess(test);self.rows.append(dict(id=test.id(),passed=True))
        def addSkip(self,test,reason):
            super().addSkip(test,reason);self.rows.append(dict(id=test.id(),passed=False,skipped=reason))
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(
        unittest.defaultTestLoader.loadTestsFromNames(names))
    body=dict(schema='joined-reused-proof-set-v1',kind=kind,identity=identity(),
        passed=result.wasSuccessful() and not result.skipped and not forbidden,
        tests=result.testsRun,results=result.rows,errors=len(result.errors),failures=len(result.failures),
        reused_suites=names,paper_only=True,market_collection=False,external_socket_attempts=forbidden)
    Path(output).write_text(json.dumps(body,sort_keys=True))
    return 0 if body['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sources',required=True);p.add_argument('--output',required=True)
    p.add_argument('--kind',choices=('provider','long_horizon'),required=True)
    a=p.parse_args();raise SystemExit(run(a.sources,a.output,a.kind))
