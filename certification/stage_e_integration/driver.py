"""Run the predeclared test IDs only, from the exact read-only assembly."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from certification.stage_e_native_v2.contract import canonical, read, sha256


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        self.outcomes[test.id()] = 'PASS'
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.outcomes[test.id()] = 'FAIL'
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcomes[test.id()] = 'ERROR'
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.outcomes[test.id()] = 'SKIP'
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.outcomes[test.id()] = 'EXPECTED_FAILURE'
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcomes[test.id()] = 'UNEXPECTED_SUCCESS'
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.outcomes[test.id()] = 'FAIL_SUBTEST'
        super().addSubTest(test, subtest, err)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def children(guard):
    rows = []
    for pid, launched in sorted(guard.children.items()):
        before = read(guard.child_directory / (str(pid) + '.before.json'))
        if before['candidate_sha'] != guard.declaration['candidate_sha'] or before['assembly_before'] != guard.declaration['assembly_digest']:
            raise ValueError('child_foreign_assembly')
        if not before['foreign_dynamic_origin_rejected'] or not before['origins_before']:
            raise ValueError('child_missing_origin_guard')
        after_path = guard.child_directory / (str(pid) + '.after.json')
        if after_path.exists():
            after = read(after_path)
            if after['assembly_after'] != guard.declaration['assembly_digest'] or after['provider_attempts'] or not after['origins_after']:
                raise ValueError('child_origin_or_provider_failure')
            if after['exit_code'] != launched.get('expected_exit', 0):
                raise ValueError('unexpected_bound_child_exit')
            status = 'COMPLETE'
        elif launched.get('expected_signal') == 9:
            # SIGKILL cannot emit an after receipt. Keep the startup receipt and
            # durable execution/attempt records; do not fabricate final origins.
            status = 'EXPECTED_SIGKILL_NO_FINAL_RECEIPT'
        else:
            raise ValueError('missing_bound_child_final_receipt:' + str(pid))
        attempt_path = guard.child_directory / (str(pid) + '.providers.jsonl')
        if attempt_path.exists() and attempt_path.read_bytes():
            raise ValueError('child_provider_attempts')
        exec_path = guard.child_directory / (str(pid) + '.exec.jsonl')
        for event in exec_path.read_text().splitlines() if exec_path.exists() else []:
            event = json.loads(event)
            path = Path(event['origin'])
            expected = (guard.manifest['files'].get(path.relative_to(guard.source).as_posix(), {}).get('sha256')
                        if path.is_relative_to(guard.source) else guard.external.get(str(path)))
            if event['sha256'] != expected:
                raise ValueError('foreign_child_execution_event')
        rows.append(dict(launch=launched, status=status, before=before,
            after=read(after_path) if after_path.exists() else None))
    receipts = {int(p.name.split('.')[0]) for p in guard.child_directory.glob('*.before.json')}
    if receipts != set(guard.children):
        raise ValueError('undeclared_or_missing_child_process')
    return rows


def main(guard):
    declaration = guard.declaration
    output = Path(declaration['output'])
    allow_path = guard.source / 'diagnostics/stage-e-native-v2-successor/deterministic-allowlist.json'
    if sha256(allow_path.read_bytes()) != declaration['allowlist_sha256']:
        raise ValueError('allowlist_predeclaration_changed')
    allow = read(allow_path)
    spec = importlib.util.spec_from_file_location('stage_e_m1_prerequisite',
        guard.source / 'diagnostics/stage-e-owner-admission-phase2/native_completion_prerequisite.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    identities = list(allow['tests'])
    loaded = [test for identity in identities for test in flatten(unittest.defaultTestLoader.loadTestsFromName(identity))]
    if [test.id() for test in loaded] != identities or len(loaded) != allow['expected_tests']:
        raise ValueError('explicit_test_identity_or_denominator_changed')
    if set(identities) & set(allow['excluded_tests']):
        raise PermissionError('pressure_test_in_allowlist')
    q2 = read(guard.source / 'certification/stage_e_native_v2/test-classifications-v2.json')['tests']
    if {test for test in identities if allow['tests'][test]['group'] == 'Q2_original_71'} != set(q2):
        raise ValueError('original_q2_denominator_changed')
    (output / 'classification-before-execution.json').write_bytes(canonical(allow))
    row = dict(candidate_sha=declaration['candidate_sha'], candidate_tree=declaration['candidate_tree'],
        assembly_digest=declaration['assembly_digest'], predeclaration_sha256=sha256(canonical(declaration)),
        assembly_before=declaration['assembly_digest'], assembly_after=None,
        expected_tests=len(identities), q2_original_denominator=71, material_executions=0,
        observer_measurements=0, qualification_credit=False, certification_credit=False,
        stage_e='RED', stage_f='NOT_STARTED', errors=[], provider_attempts=[], children=[], passed=False)
    try:
        with (output / 'tests.log').open('w') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Results).run(unittest.TestSuite(loaded))
        # All production pools have shut down before stopping their tracker.
        from multiprocessing.resource_tracker import _resource_tracker
        _resource_tracker._stop()
        row.update(tests_run=result.testsRun, outcomes=result.outcomes,
            failures=[dict(test=t.id(), traceback=trace) for t, trace in result.failures],
            test_errors=[dict(test=t.id(), traceback=trace) for t, trace in result.errors],
            skipped=[dict(test=t.id(), reason=reason) for t, reason in result.skipped],
            groups={group: dict(expected=sum(r['group'] == group for r in allow['tests'].values()),
                outcomes=dict(Counter(result.outcomes.get(test, 'MISSING') for test, info in allow['tests'].items() if info['group'] == group)))
                for group in sorted({r['group'] for r in allow['tests'].values()})})
        row['children'] = children(guard)
        row['runtime_origins'] = guard.origins()
        guard.verify()
        row['assembly_after'] = declaration['assembly_digest']
        row['provider_attempts'] = list(guard.attempts)
        row['passed'] = (result.wasSuccessful() and not result.skipped and not guard.attempts and
            result.testsRun == len(identities) and set(result.outcomes) == set(identities) and
            all(value == 'PASS' for value in result.outcomes.values()))
    except BaseException as exc:
        row['errors'].append(dict(type=type(exc).__name__, message=str(exc)))
    (output / 'test-results.json').write_bytes(canonical(row))
    print(json.dumps({k: row.get(k) for k in ('candidate_sha', 'candidate_tree', 'assembly_digest', 'tests_run', 'groups', 'passed', 'errors')}, sort_keys=True), flush=True)
    return 0 if row['passed'] else 1
