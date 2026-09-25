"""Run a pinned lane's existing tests with external Python socket I/O forbidden.

This is component-suite evidence, never a claim of connected strategy E2E proof.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import resource
import sys
import time
import unittest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--barrier',required=True)
    args=parser.parse_args()
    # Match production worker import precedence.
    sys.path.insert(0,os.getcwd())
    # Same root fallback as certification.worker, without shadowing lane modules.
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    forbidden=[]
    def network_guard(event,values):
        if event!='socket.connect':return
        address=values[1]
        if not isinstance(address,tuple):return  # Unix socket.
        host=str(address[0])
        try:local=ipaddress.ip_address(host).is_loopback
        except ValueError:local=host=='localhost'
        if not local:
            forbidden.append({'event':event,'reason':'external_socket_forbidden'})
            raise RuntimeError('non_market_external_socket_forbidden')
    sys.addaudithook(network_guard)
    barrier=Path(args.barrier)
    (barrier/args.lane).touch()
    deadline=time.monotonic()+20
    while not all((barrier/lane).exists() for lane in ('pump','pons','meteora','ramses')):
        if time.monotonic()>deadline:raise TimeoutError('four_lane_test_barrier')
        time.sleep(.02)
    started=time.time()
    class Result(unittest.TextTestResult):
        def __init__(self,*a,**kw):super().__init__(*a,**kw);self.rows=[]
        def addSuccess(self,test):
            super().addSuccess(test);self.rows.append({'id':test.id(),'result':'PROVEN'})
        def addFailure(self,test,err):
            super().addFailure(test,err);self.rows.append({'id':test.id(),'result':'FAILED'})
        def addError(self,test,err):
            super().addError(test,err);self.rows.append({'id':test.id(),'result':'FAILED'})
        def addSkip(self,test,reason):
            super().addSkip(test,reason);self.rows.append({'id':test.id(),'result':'SKIPPED'})
    directory='robinhood_tests' if args.lane in ('pons','ramses') else 'tests'
    suite=unittest.defaultTestLoader.discover(directory)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    usage=resource.getrusage(resource.RUSAGE_SELF)
    output=dict(lane=args.lane,scope='existing_component_suites',started_at=started,
        ended_at=time.time(),tests_run=result.testsRun,tests=result.rows,
        passed=result.wasSuccessful() and not forbidden,external_socket_attempts=forbidden,
        peak_rss_kib=usage.ru_maxrss,cpu_user_seconds=usage.ru_utime,cpu_system_seconds=usage.ru_stime,
        open_file_descriptors=len(list(Path('/proc/self/fd').iterdir())),
        natural_market_proof=False,connected_end_to_end_claim=False)
    Path(args.output).write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    return 0 if output['passed'] else 1


if __name__=='__main__':sys.exit(main())
