"""Start under Python -I -S from the reviewed assembly, including children."""
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
assembly = Path(os.environ['MM_STAGE_E_V2_ASSEMBLY']).resolve()
source = assembly/'source'
manifest = json.loads((assembly/'assembly.json').read_text())
digest = manifest.pop('assembly_digest')
encoded = json.dumps(manifest,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
if digest != os.environ['MM_STAGE_E_V2_DIGEST'] or hashlib.sha256(encoded).hexdigest() != digest:
    raise ValueError('bootstrap_assembly_identity')
if Path(__file__).resolve() != source/'certification/stage_e_native_v2/bootstrap.py':
    raise ValueError('bootstrap_origin')
info = manifest['files']['certification/stage_e_native_v2/bootstrap.py']
if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != info['sha256']:
    raise ValueError('bootstrap_hash')
environment = manifest['identity']['environment_identity']
stdlib = Path(environment['stdlib'])
dependency_files = environment['dependencies']['websockets']['files']
sys.path[:] = [str(source)] + [p for p in sys.path if p and
    (Path(p).resolve().is_relative_to(stdlib) or p.endswith('python312.zip'))] + [environment['dependency_root']]


class AssemblyOriginFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if not spec.origin or spec.origin in ('built-in','frozen'):
            locations = spec.submodule_search_locations or []
            if any(not Path(p).resolve().is_relative_to(source) for p in locations):
                raise ImportError('foreign_namespace_module:' + fullname)
            return spec
        origin = Path(spec.origin).resolve()
        expected = None
        if origin.is_relative_to(source):
            expected = manifest['files'].get(origin.relative_to(source).as_posix(),{}).get('sha256')
        elif str(origin) in dependency_files:
            expected = dependency_files[str(origin)]
        elif str(origin) in environment['stdlib_files']:
            expected = environment['stdlib_files'][str(origin)]
        if expected is None or hashlib.sha256(origin.read_bytes()).hexdigest() != expected:
            raise ImportError('unapproved_module_origin:' + fullname + ':' + str(origin))
        if isinstance(spec.loader,importlib.machinery.SourceFileLoader):
            loader=spec.loader
            # Disabling bytecode writes alone would still permit stale/shadow
            # pyc reads. Compile the approved source bytes, never cached pyc.
            spec.loader.get_code=lambda name,loader=loader:compile(loader.get_source(name),
                loader.get_filename(name),'exec',dont_inherit=True)
        return spec


sys.meta_path.insert(0, AssemblyOriginFinder())


def execution_origin_audit(event,args):
    if event!='exec':
        return
    filename=args[0].co_filename
    if filename.startswith('<frozen '):
        return  # Frozen standard library is pinned by the interpreter hash.
    if filename in ('<string>','<unknown>'):
        # dataclasses/namedtuple compile approved standard-library-generated
        # functions. A qualification/local module cannot use this exception.
        caller=sys._getframe(1).f_code.co_filename
        if caller in environment['stdlib_files']:
            return
        raise PermissionError('undeclared_generated_executable_origin')
    origin=Path(filename).resolve()
    if origin.is_relative_to(source):
        expected=manifest['files'].get(origin.relative_to(source).as_posix(),{}).get('sha256')
    else:
        expected=dependency_files.get(str(origin),environment['stdlib_files'].get(str(origin)))
    if not expected or not origin.is_file() or hashlib.sha256(origin.read_bytes()).hexdigest()!=expected:
        raise PermissionError('unapproved_dynamic_executable_origin:'+str(origin))


sys.addaudithook(execution_origin_audit)
from certification.stage_e_native_v2.runner import main
raise SystemExit(main())
