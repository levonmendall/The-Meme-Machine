"""Allowed static/unit/parser checks only; no native member or workload."""
import io
from pathlib import Path
import sys
import unittest

from frozen import *
from preserve import persist


def run(static_source):
    static_source = Path(static_source)
    before = contract_file('candidate_integrity_before.json')
    require(before['S'] == S and before['T'] == T, 'source_fixture_identity')
    for name, row in before['tracked_files'].items():
        path = relative(static_source, name)
        require(path.is_file() and file_sha(path) == row['sha256'], 'static_exact_S_file_changed:' + name)
    loader = unittest.TestLoader()
    prep_suite = loader.discover(str(ROOT), pattern='test_*.py')
    # The approved contract embeds a legacy absolute source path. Override its
    # in-memory read-only source selector to this newly isolated exact-S fixture;
    # the approved test files and contract bytes remain unchanged.
    sys.path.insert(0, str(CONTRACT))
    import static_validation
    static_validation.SOURCE = static_source
    import test_source_grounding
    test_source_grounding.SOURCE = static_source
    contract_suite = loader.discover(str(CONTRACT), pattern='test_*.py')
    tests_root = EXECUTABLE/'tests'
    sys.path.insert(0, str(tests_root))
    resource_suite = unittest.TestSuite()
    for name in ('test_envelope', 'test_cgroup_applicability', 'test_resource_interval'):
        resource_suite.addTests(loader.loadTestsFromName(name))
    verifier_suite = loader.loadTestsFromName('test_verifier')
    suites = [('prep', prep_suite), ('approved_contract', contract_suite),
              ('pure_resources', resource_suite), ('pure_native_evidence_predicates', verifier_suite)]
    results, complete_log = {}, []
    for name, suite in suites:
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        log = stream.getvalue(); complete_log.append('Suite: ' + name + '\n' + log)
        results[name] = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                             skipped=len(result.skipped), passed=result.wasSuccessful() and not result.skipped,
                             log_sha256=sha(log.encode()))
    full_log = '\n'.join(complete_log)
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence/unit_validation.log').write_text(full_log)
    for name, row in before['tracked_files'].items():
        require(file_sha(relative(static_source, name)) == row['sha256'], 'static_source_mutated_by_checks')
    check_executable()
    record = dict(version='stage-e-native-v3-parallel-prep-allowed-test-results', **FROZEN,
        python=sys.version.split()[0], suites=results, total=sum(r['tests'] for r in results.values()),
        passed=all(r['passed'] for r in results.values()),
        log_sha256=file_sha(ROOT/'evidence/unit_validation.log'),
        static_source=str(static_source), exact_S_files_verified=len(before['tracked_files']),
        physical_inputs='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
        A_trials_run=0, B_trials_run=0, C_trials_run=0, slots_consumed=0, slots_reserved=0,
        source_frames_released=0, native_members=0, provider_workloads=0, jobs_dispatched=0,
        stage_e='RED', stage_f='NOT STARTED')
    (ROOT/'evidence/test_results.json').write_bytes(canonical(record)+b'\n')
    print(canonical(record).decode())
    require(record['passed'], 'deterministic_preparation_validation_failed')
    return record


if __name__=='__main__':
    require(len(sys.argv)==2, 'usage: run_checks.py ISOLATED_EXACT_S_STATIC_SOURCE')
    run(sys.argv[1])
