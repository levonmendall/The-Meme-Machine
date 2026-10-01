"""Reverify the authorized semantic port and exact protected component bytes."""
import ast
import hashlib
from pathlib import Path
import subprocess

from certification.stage_e_native_v2.contract import ROOT, read, validate_inputs, canonical


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def method(text, cls, name):
    return next(n for c in ast.parse(text).body if isinstance(c, ast.ClassDef) and c.name == cls
        for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name)


def verify():
    mapping = read(ROOT / 'diagnostics/stage-e-native-v2-successor/component-map.json')['components']
    base = mapping['A2']['sha']
    runtime = 'meme_machine/solana_maintenance_runtime.py'
    before = git('show', base + ':' + runtime).decode()
    after = (ROOT / runtime).read_text()
    for name in ('_cooperative', '_complete_decision'):
        assert ast.dump(method(before, 'MaintenanceRuntime', name)) == ast.dump(method(after, 'MaintenanceRuntime', name)), name
    reference = git('show', mapping['housekeeping']['sha'] + ':diagnostics/housekeeping-ordering/treatment.patch')
    assert reference == (ROOT / 'diagnostics/stage-e-owner-admission-phase2/HOUSEKEEPING_REFERENCE.patch').read_bytes()
    lines = reference.decode().splitlines()
    start = lines.index('+    def _housekeeping_first(self,decision,observation,needs,ready,flight):')
    helper = []
    for line in lines[start:]:
        if not line.startswith('+'):
            break
        helper.append(line[1:])
    assert ast.dump(ast.parse('class MaintenanceRuntime:\n' + '\n'.join(helper)).body[0].body[0]) == ast.dump(method(after, 'MaintenanceRuntime', '_housekeeping_first'))
    plane = 'meme_machine/solana_evidence_plane.py'
    old_retain = method(git('show', base + ':' + plane).decode(), 'EvidenceWriter', 'retain')
    new_retain = method((ROOT / plane).read_text(), 'EvidenceWriter', 'retain')
    new_gc = method((ROOT / plane).read_text(), 'EvidenceWriter', '_retention_housekeeping')
    gc_start = next(i for i, n in enumerate(old_retain.body) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'garbage' for t in n.targets))
    gc_end = next(i for i, n in enumerate(old_retain.body) if isinstance(n, ast.If)
        and isinstance(n.test, ast.Name) and n.test.id == 'checkpoint')
    assert [ast.dump(n) for n in old_retain.body[gc_start:gc_end]] == [ast.dump(n) for n in new_gc.body]
    scope_loops = lambda body: [ast.dump(n) for n in body if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
        and any(isinstance(t, ast.Name) and t.id == 'index' for t in n.target.elts)]
    assert scope_loops(old_retain.body) == scope_loops(new_retain.body)
    protected = ['meme_machine/engine.py', 'meme_machine/solana_evidence_control.py',
        'meme_machine/solana_owner_admission.py', 'meme_machine/solana_maintenance_arbiter.py',
        'meme_machine/solana_maintenance_state.py', 'tests/test_m1_maintenance_completion.py',
        'tests/test_owner_admission_phase2.py', 'tests/test_run373_dispatch_throughput.py',
        'tests/test_run379_production_pressure.py', 'tests/test_run380_production_pressure.py',
        '.github/workflows/stagee-fixed-cohort.yml', 'certification/maintenance_qualification_plan.json']
    for path in protected:
        assert (ROOT / path).read_bytes() == git('show', base + ':' + path), path
    q2_changed = []
    q2 = mapping['Q2']
    for path, expected in q2['source_files'].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected['sha256']:
            q2_changed.append(path)
    assert sorted(q2_changed) == sorted(['certification/stage_e_native_v2/input-manifest-v2.json',
        'certification/stage_e_native_v2/dependency-lock-v2.json']), q2_changed
    allow = read(ROOT / 'diagnostics/stage-e-native-v2-successor/deterministic-allowlist.json')
    q2_tests = read(ROOT / 'certification/stage_e_native_v2/test-classifications-v2.json')['tests']
    assert len(allow['tests']) == 621 and len(q2_tests) == 71
    assert {name for name, row in allow['tests'].items() if row['group'] == 'Q2_original_71'} == set(q2_tests)
    assert not set(allow['tests']) & set(allow['excluded_tests'])
    return dict(passed=True, m1_completion_ast_unchanged=True, exact_housekeeping_selector=True,
        exact_native_housekeeping_batch=True, exact_scope_loop=True, protected_bytes=protected,
        controlled_q2_changes=q2_changed, input_identity=validate_inputs(),
        expected_tests=621, q2_original_denominator=71, certification_credit=False)


if __name__ == '__main__':
    print(canonical(verify()).decode())
