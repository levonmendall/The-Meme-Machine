"""Run reviewed integration source and its children under Python -I -S."""
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys


def install():
    sys.dont_write_bytecode = True
    declaration = json.loads(Path(os.environ['MM_INTEGRATION_DECLARATION']).read_text())
    assembly = Path(declaration['assembly']).resolve()
    source = assembly / 'source'
    manifest = json.loads((assembly / 'assembly.json').read_text())
    digest = manifest.pop('assembly_digest')
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != digest or digest != declaration['assembly_digest']:
        raise ValueError('integration_assembly_identity')
    if manifest['identity']['candidate_sha'] != declaration['candidate_sha']:
        raise ValueError('integration_candidate_identity')
    own = source / 'certification/stage_e_integration/bootstrap.py'
    if Path(__file__).resolve() != own:
        raise ValueError('integration_bootstrap_origin')
    environment = manifest['identity']['environment_identity']
    external = dict(environment['stdlib_files'])
    external.update(environment['dependencies']['websockets']['files'])
    external.update(declaration['tooling_files'])
    stdlib = Path(environment['stdlib'])
    sys.path[:] = [str(source)] + [p for p in sys.path if p and
        (Path(p).resolve().is_relative_to(stdlib) or p.endswith('python312.zip'))] + [environment['dependency_root']]

    def expected(origin):
        if origin.is_relative_to(source):
            return manifest['files'].get(origin.relative_to(source).as_posix(), {}).get('sha256')
        return external.get(str(origin))

    def checked(origin):
        digest = expected(origin)
        if not digest or not origin.is_file() or hashlib.sha256(origin.read_bytes()).hexdigest() != digest:
            raise PermissionError('unapproved_integration_executable_origin:' + str(origin))

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None:
                return None
            if not spec.origin or spec.origin in ('built-in', 'frozen'):
                for location in spec.submodule_search_locations or []:
                    if not Path(location).resolve().is_relative_to(source):
                        raise ImportError('foreign_integration_namespace:' + fullname)
                return spec
            checked(Path(spec.origin).resolve())
            if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
                loader = spec.loader
                loader.get_code = lambda name, loader=loader: compile(loader.get_source(name),
                    loader.get_filename(name), 'exec', dont_inherit=True)
            return spec

    sys.meta_path.insert(0, Finder())
    from certification.stage_e_integration.generated import code_identity

    def audit(event, args):
        if event != 'exec':
            return
        filename = args[0].co_filename
        if filename.startswith('<frozen '):
            return
        if filename.startswith('<'):
            if sys._getframe(1).f_code.co_filename in external:
                return
            raise PermissionError('undeclared_integration_generated_code')
        if filename == 'native_batch_limit':
            caller = sys._getframe(1).f_code.co_filename
            if (caller != str(source / 'tests/test_owner_admission_phase2.py') or
                    code_identity(args[0]) != declaration['native_batch_limit_code_sha256']):
                raise PermissionError('unreviewed_native_batch_limit_derivative')
            return
        origin = Path(filename).resolve()
        checked(origin)
        if os.environ.get('MM_INTEGRATION_CHILD'):
            record = json.dumps(dict(origin=str(origin), sha256=expected(origin)), sort_keys=True) + '\n'
            path = Path(declaration['output']) / 'children' / (str(os.getpid()) + '.exec.jsonl')
            with path.open('a') as handle:
                handle.write(record)

    sys.addaudithook(audit)
    # Also check modules loaded before the finder, including this bootstrap.
    for module in tuple(sys.modules.values()):
        if getattr(module, '__file__', None):
            checked(Path(module.__file__).resolve())
    manifest['assembly_digest'] = digest
    from certification.stage_e_integration.guard import Guard
    return Guard(declaration, manifest, source, external)


def main():
    guard = install()
    with guard.controls():
        if len(sys.argv) > 1 and sys.argv[1] == '--worker':
            from multiprocessing.spawn import spawn_main
            parameters = json.loads(sys.argv[2])
            sys.argv[:] = [sys.argv[0], '--multiprocessing-fork']
            guard.child_begin('spawn_worker')
            try:
                spawn_main(**parameters)
            finally:
                guard.child_finish()
        elif len(sys.argv) > 1 and sys.argv[1] == '--resource-tracker':
            from multiprocessing.resource_tracker import main as track
            guard.child_begin('resource_tracker')
            try:
                track(int(sys.argv[2]))
            finally:
                guard.child_finish()
        elif len(sys.argv) > 1 and sys.argv[1] == '--crash':
            from certification.stage_e_integration.crash_child import main as crash
            guard.child_begin('crash_before_after_commit')
            sys.argv[:] = [sys.argv[0], *sys.argv[2:]]
            crash()
        else:
            from certification.stage_e_integration.driver import main as run
            return run(guard)


if __name__ == '__main__':
    raise SystemExit(main())
