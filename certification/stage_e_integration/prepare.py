"""Predeclare and extract one exact integration tree; execution stays assembled."""
import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from certification.stage_e_native_v2.binding import assemble, execution_environment, verify_assembly
from certification.stage_e_native_v2.contract import ROOT, canonical, identities, read, sha256
from certification.stage_e_integration.generated import code_identity


def tooling_files(source):
    lock = read(Path(source) / 'certification/stage_e_integration/tooling-lock.json')
    files = {}
    for name, expected in lock['distributions'].items():
        dist = importlib.metadata.distribution(name)
        current = {str(n): sha256(Path(dist.locate_file(n)).read_bytes()) for n in dist.files or []
            if Path(dist.locate_file(n)).is_file() and Path(n).suffix != '.pyc'
            and Path(n).name not in ('RECORD', 'INSTALLER', 'REQUESTED')}
        if dist.version != expected['version'] or current != expected['files']:
            raise ValueError('supplemental_tooling_bytes_changed:' + name)
        files.update({str(Path(dist.locate_file(n)).resolve()): value for n, value in current.items()})
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    workflow = dict(workflow_path='.github/workflows/stagee-native-qualification-v2.yml',
        reusable_workflow_path='.github/workflows/stagee-native-qualification-v2-reusable.yml',
        resolved_workflow_sha=candidate, reusable_workflow_sha=candidate, candidate_sha=candidate,
        run_id='durable-integration-local-' + candidate, attempt=1, event='local_static_deterministic')
    bound = identities()
    manifest = assemble(ROOT, output / 'assembly', candidate=candidate, tree=tree, workflow=workflow,
        expected_plan_hash=bound['plan_hash'], expected_input_hash=bound['input_manifest_hash'])
    source = output / 'assembly/source'
    method = next(n for c in ast.parse((source / 'tests/test_lifecycle.py').read_text()).body
        if isinstance(c, ast.ClassDef) and c.name == 'Lifecycle' for n in c.body
        if isinstance(n, ast.FunctionDef) and n.name == 'test_process_termination_before_after_commit')
    literal = next(n.value.value for n in ast.walk(method) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'code' for t in n.targets))
    service = ast.parse((source / 'meme_machine/solana_evidence_service.py').read_text())
    serve = next(n for n in service.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'serve')
    limit = next(n for n in serve.body if isinstance(n, ast.FunctionDef) and n.name == 'maintenance_batch_limit')
    derivative = compile(ast.Module(body=[limit], type_ignores=[]), 'native_batch_limit', 'exec')
    declaration = dict(candidate_sha=candidate, candidate_tree=tree,
        assembly=str(output / 'assembly'), assembly_digest=manifest['assembly_digest'],
        output=str(output / 'deterministic'),
        allowlist_sha256=sha256((source / 'diagnostics/stage-e-native-v2-successor/deterministic-allowlist.json').read_bytes()),
        supplemental_allowlist_sha256=sha256((source / 'diagnostics/stage-e-integration-successor/deterministic-supplement.json').read_bytes()),
        crash_literal_sha256=sha256(literal.encode()), tooling_files=tooling_files(source),
        native_batch_limit_code_sha256=code_identity(derivative),
        expected_tests=621, q2_original_denominator=71, expected_supplemental_tests=4, attempt=1,
        qualification_credit=False, certification_credit=False,
        material_executions=0, observer_measurements=0)
    (output / 'deterministic').mkdir()
    declaration_path = output / 'predeclaration.json'
    declaration_path.write_bytes(canonical(declaration))
    print(json.dumps(dict(candidate_sha=candidate, candidate_tree=tree,
        assembly_digest=manifest['assembly_digest'], declaration_sha256=sha256(canonical(declaration)),
        source_files=len(manifest['files']), expected_tests=621, q2_original_denominator=71)), flush=True)
    env = execution_environment(output / 'assembly', manifest['assembly_digest'], manifest)
    env['MM_INTEGRATION_DECLARATION'] = str(declaration_path)
    result = subprocess.run([sys.executable, '-I', '-S', str(source / 'certification/stage_e_integration/bootstrap.py')],
        cwd=source, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / 'controller.log').write_text(result.stdout)
    verify_assembly(output / 'assembly', manifest['assembly_digest'])
    print(result.stdout, flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
