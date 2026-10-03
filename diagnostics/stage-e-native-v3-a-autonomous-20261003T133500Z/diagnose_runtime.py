"""Read-only evidence collector; no Stage-A workload, runtime repair, or slots."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True
RUN = 'native-v3-a-autonomous-20261003T133500Z'
REPO = Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE = REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0, str(PACKAGE/'harness'))
import binding
import core
import attest

MOUNT = Path('/mnt/volume_nyc1_1790918115030')
OLD = MOUNT/'meme-machine-observer-v2-7a516a6a'
OUT = MOUNT/'stage-e-native-v3-paper-preflight'/(RUN+'-diagnosis')
TARGET = Path('/workspace/stage-e-runtime/bin/python')

def save(name, value):
    data = core.canonical(value)+b'\n'
    with (OUT/name).open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    attest.fsync_dir(OUT)

def cmd(argv, timeout=60):
    before = time.time_ns()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return dict(argv=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr,
                    started_utc_ns=before, finished_utc_ns=time.time_ns())
    except Exception as exc:
        return dict(argv=argv, error=type(exc).__name__+':'+str(exc))

def identity(path):
    p = Path(path)
    st = p.lstat()
    return dict(path=str(p), resolved=str(p.resolve()), symlink=os.readlink(p) if p.is_symlink() else None,
                bytes=st.st_size, device=st.st_dev, inode=st.st_ino, uid=st.st_uid, gid=st.st_gid,
                mode=oct(st.st_mode), mtime_ns=st.st_mtime_ns,
                sha256=core.file_sha(p) if p.is_file() else None)

PROBE = r'''
import sys,sysconfig,platform,os,json,hashlib,sqlite3,_sqlite3,importlib,importlib.metadata
from pathlib import Path
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
libs={}
for row in Path('/proc/self/maps').read_text().splitlines():
    fields=row.split()
    if len(fields)>=6 and fields[-1].startswith('/'):
        p=Path(fields[-1]);libs[str(p.resolve())]={'sha256':h(p),'bytes':p.stat().st_size}
dependencies={}
for name in ('PyYAML','jsonschema','websockets'):
    try:
        d=importlib.metadata.distribution(name)
        dependencies[name]={'version':d.version,'root':str(Path(d.locate_file('')).resolve()),
          'metadata':{str(n):{'path':str(d.locate_file(n)), 'sha256':h(d.locate_file(n))}
             for n in d.files or [] if Path(n).name in ('METADATA','RECORD','WHEEL','direct_url.json','INSTALLER') and Path(d.locate_file(n)).is_file()}}
    except importlib.metadata.PackageNotFoundError: dependencies[name]={'state':'NOT INSTALLED'}
modules={}
for name in ('yaml','jsonschema','websockets'):
    try:
        m=importlib.import_module(name);modules[name]={'importable':True,'path':getattr(m,'__file__',None)}
    except Exception as exc: modules[name]={'importable':False,'error':type(exc).__name__+':'+str(exc)}
print(json.dumps(dict(sys_executable=sys.executable,sys_version=sys.version,sys_version_info=list(sys.version_info),
  sys_prefix=sys.prefix,sys_base_prefix=sys.base_prefix,sys_exec_prefix=sys.exec_prefix,
  python_build=platform.python_build(),python_compiler=platform.python_compiler(),implementation=platform.python_implementation(),
  config={k:sysconfig.get_config_var(k) for k in ('CONFIG_ARGS','Py_ENABLE_SHARED','LDLIBRARY','LIBRARY','LIBDIR','LIBPL','MULTIARCH','SOABI','BUILD_GNU_TYPE','HOST_GNU_TYPE')},
  sys_path=sys.path,sys_flags=str(sys.flags),config_paths=sysconfig.get_paths(),sqlite_runtime=sqlite3.sqlite_version,
  sqlite_source_id=sqlite3.connect(':memory:').execute('select sqlite_source_id()').fetchone()[0],
  sqlite_extension={'path':_sqlite3.__file__,'sha256':h(_sqlite3.__file__)},loaded_maps=libs,
  distributions=dependencies,importability=modules),sort_keys=True))
'''

result = dict(paper_only=True, A_slots_consumed=0, A_trials_started=0, source_frames_released=0,
              runtime_changes_performed=0, quiescence_performed=False, stage_e='RED', stage_f='NOT STARTED')
try:
    core.require(socket.gethostname()=='ubuntu-gd-2vcpu-8gb-nyc1', 'executor_hostname_mismatch')
    core.require(os.environ.get('RUNNER_NAME')=='the meme machine' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','runner_or_attempt_mismatch')
    OUT.mkdir(exist_ok=False)
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()=='f480c6b4f7a8442fd148c7ed61bcc4447edaefca','approved_executable_commit_changed')
    core.require(core.file_sha(PACKAGE/'package-manifest.json')=='d0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859','approved_harness_manifest_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        p=REPO/row['path']
        core.require(p.is_file() and not p.is_symlink() and p.stat().st_size==row['bytes'] and core.file_sha(p)==row['sha256'],'approved_harness_artifact_changed:'+row['path'])
    core.require(binding.infrastructure_identity()==core.read(PACKAGE/'source_hashes.json'),'approved_infrastructure_changed')
    assembly=binding.verify_assembly(OLD/'assembly')
    save('APPROVED_IDENTITIES.json',dict(candidate=binding.candidate_integrity(OLD/'candidate-checkout'),contract=binding.contract_integrity(REPO),
      infrastructure=binding.infrastructure_identity(),assembly_digest=assembly['assembly_digest'],executor_hostname=socket.gethostname(),
      executor_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),runner_name=os.environ.get('RUNNER_NAME')))
    chain=[];p=TARGET
    for _ in range(20):
        chain.append(identity(p))
        if not p.is_symlink(): break
        link=Path(os.readlink(p));p=link if link.is_absolute() else p.parent/link
    save('EXECUTABLE_SYMLINK_CHAIN.json',dict(chain=chain,component_links=[identity(q) for q in TARGET.parents if q.is_symlink()],
      target_realpath=str(TARGET.resolve()),target=identity(TARGET),system_python=identity('/usr/bin/python3.12')))
    probe=cmd([str(TARGET),'-I','-B','-c',PROBE])
    save('SELECTED_RUNTIME_RAW.json',probe)
    core.require(probe['returncode']==0,'runtime_diagnostic_probe_failed')
    runtime=json.loads(probe['stdout']);save('SELECTED_RUNTIME.json',runtime)
    commands=[['file',str(TARGET.resolve())],['readelf','-W','-d',str(TARGET.resolve())],['readelf','-W','-n',str(TARGET.resolve())],
      ['readelf','-W','-l',str(TARGET.resolve())],['ldd',str(TARGET.resolve())],['ldd',runtime['sqlite_extension']['path']],
      ['dpkg-query','--search',str(TARGET.resolve())],['dpkg-query','--show','python3.12-minimal','libpython3.12','libpython3.12-stdlib','libsqlite3-0']]
    for path in runtime['loaded_maps']:
        if 'libpython' in path or 'libsqlite' in path:
            commands += [['dpkg-query','--search',path],['readelf','-W','-n',path]]
    save('ELF_LIBRARY_PROVENANCE.json',dict(commands=[cmd(a) for a in commands],
      loader_environment={k:os.environ.get(k) for k in ('LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH')},
      ld_so_conf=Path('/etc/ld.so.conf').read_text() if Path('/etc/ld.so.conf').is_file() else None,
      ld_so_conf_d={str(p):p.read_text() for p in Path('/etc/ld.so.conf.d').glob('*.conf')}))
    save('LOADER_SEARCH_RAW.json',cmd(['env','LD_DEBUG=libs',str(TARGET),'-I','-B','-c','import sys; print(sys.version)']))
    save('SYSTEM_PYTHON_COMPARISON.json',cmd(['/usr/bin/python3.12','-I','-B','-c',PROBE]))
    save('VIRTUAL_ENVIRONMENT_METADATA.json',dict(pyvenv_cfg=Path('/workspace/stage-e-runtime/pyvenv.cfg').read_text(),
      selected_prefix_files=[identity(p) for p in Path('/workspace/stage-e-runtime/bin').iterdir()],
      tool_installation_metadata=[dict(identity=identity(p),text=p.read_text()[:20000])
        for p in TARGET.resolve().parents[1].glob('**/*') if p.is_file() and p.name in ('pyvenv.cfg','INSTALL_RECEIPT.json','install_metadata.json')]))
    rows=[]
    for p in sorted(Path('/workspace/stage-e-runtime').rglob('*')):
        if p.is_file() or p.is_symlink(): rows.append(identity(p))
    save('RUNTIME_FILES_BEFORE.json',dict(root='/workspace/stage-e-runtime',files=rows))
    save('EXISTING_ENVIRONMENT_RECORD.json',core.read(OLD/'fresh-environment.json'))
    save('READ_ONLY_RESOURCE_SNAPSHOT.json',attest.inspect([str(MOUNT)],os.getppid()))
    result.update(status='DIRECT_RUNTIME_DIAGNOSIS_COLLECTED',observed_python=runtime['sys_version'],selected_realpath=str(TARGET.resolve()),
      loaded_python_libraries=[p for p in runtime['loaded_maps'] if 'libpython' in p],sqlite_runtime=runtime['sqlite_runtime'])
except Exception as exc:
    result.update(status='DIAGNOSIS_BLOCKED',blocker=type(exc).__name__+':'+str(exc))
finally:
    if OUT.is_dir():
        save('RESULT.json',result)
        save('MANIFEST.json',dict(artifacts=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUT.iterdir()) if p.is_file()],
                                  A_slots_consumed=0,source_frames_released=0))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f: f.write('evidence_path='+str(OUT)+'\n')
    print(json.dumps(result,sort_keys=True))
    if result['status']=='DIAGNOSIS_BLOCKED': raise SystemExit(1)
