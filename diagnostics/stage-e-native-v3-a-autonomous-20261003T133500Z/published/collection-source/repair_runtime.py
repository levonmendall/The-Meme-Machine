"""Owner-authorized isolated runtime reconstruction; frozen harness untouched."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request

sys.dont_write_bytecode=True
ID='native-v3-a-autonomous-20261003T133500Z'
REPO=Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE=REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0,str(PACKAGE/'harness'))
import binding,core,attest
MOUNT=Path('/mnt/volume_nyc1_1790918115030')
OLD=MOUNT/'meme-machine-observer-v2-7a516a6a'
OUT=MOUNT/'stage-e-native-v3-paper-preflight'/(ID+'-runtime-repair')
DIAG=MOUNT/'stage-e-native-v3-paper-preflight'/(ID+'-diagnosis')
ROOT=Path('/workspace/stage-e-python-3.12.14')
VENV=Path('/workspace/stage-e-runtime')
BACKUP=Path('/workspace/stage-e-runtime-before-'+ID)
SOURCE='https://github.com/actions/python-versions/releases/download/3.12.14-31661455385/python-3.12.14-linux-24.04-x64.tar.gz'
ARCHIVE_SHA='5a03168292516f6dd6dcf630f4bf5369b108abd7c699a7e1db37f1e622257fff'
LAUNCHER_SHA='bef88f140b625959f8af25c7b75cce2cd5d4b29cc2f2b079befd7f68eda4dba0'
LIBRARY_SHA='1fa3c52ba5aa8f6b2852836a4bf6cbb23161f7cf379f6f19248d87124b28b38a'

def save(name,value):
    data=core.canonical(value)+b'\n'
    with (OUT/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    attest.fsync_dir(OUT)

def command(argv,*,env=None,timeout=300):
    p=subprocess.run(argv,capture_output=True,text=True,env=env,timeout=timeout)
    receipt=dict(argv=argv,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,utc_ns=time.time_ns())
    core.require(p.returncode==0,'runtime_repair_command_failed:'+str(argv[0])+':'+p.stderr[-1000:])
    return receipt

def inventory(folder):
    return [dict(path=str(p.relative_to(folder)),bytes=p.lstat().st_size,
                 sha256=core.file_sha(p) if p.is_file() else None,
                 symlink=os.readlink(p) if p.is_symlink() else None,mode=oct(p.lstat().st_mode))
            for p in sorted(folder.rglob('*')) if p.is_file() or p.is_symlink()]

def runpath_location(data):
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
    core.require(h[0][:6]==b'\x7fELF\x02\x01' and h[2]==62,'unexpected_interpreter_ELF')
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,h[6]+i*h[11]) for i in range(h[12])]
    dyn=[s for s in sections if s[1]==6]
    core.require(len(dyn)==1 and dyn[0][9]==16,'ELF_dynamic_table_ambiguous')
    tags=[struct.unpack_from('<qQ',data,o) for o in range(dyn[0][4],dyn[0][4]+dyn[0][5],16)]
    paths=[value for tag,value in tags if tag==29]
    strings=[s for s in sections if s[1]==3 and s[3]==dict(tags)[5]]
    core.require(len(paths)==len(strings)==1,'ELF_RUNPATH_ambiguous')
    offset=strings[0][4]+paths[0];end=data.index(0,offset)
    return offset,end,data[offset:end]

VERIFY_CODE=r'''
import sys,json,argparse
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import run,binding
r=binding.runtime_identity(Path(sys.argv[2]))
print(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False))
'''
ISOLATION_CODE=r'''
import sys,json,site,importlib,importlib.metadata,hashlib,base64,csv,io,sqlite3,_sqlite3
from pathlib import Path
deps={};fail=[]
for d in importlib.metadata.distributions():
 files={}
 for n in d.files or []:
  p=Path(d.locate_file(n))
  if p.is_file() and p.suffix!='.pyc':files[str(p.resolve())]=hashlib.sha256(p.read_bytes()).hexdigest()
 record=d.read_text('RECORD')
 if record:
  for n,hashspec,size in csv.reader(io.StringIO(record)):
   if hashspec:
    alg,expected=hashspec.split('=',1);p=Path(d.locate_file(n));actual=base64.urlsafe_b64encode(hashlib.new(alg,p.read_bytes()).digest()).rstrip(b'=').decode()
    if actual!=expected:fail.append(str(p))
 deps[d.metadata['Name']]={'version':d.version,'root':str(Path(d.locate_file('')).resolve()),'files':files}
mods={}
for name in ('yaml','jsonschema','websockets'):
 m=importlib.import_module(name);mods[name]={'path':m.__file__,'importable':True}
print(json.dumps(dict(sys_executable=sys.executable,sys_version=sys.version,sys_version_info=list(sys.version_info),sys_prefix=sys.prefix,
 sys_base_prefix=sys.base_prefix,sys_path=sys.path,user_site_enabled=site.ENABLE_USER_SITE,distributions=deps,imports=mods,RECORD_mismatches=fail,
 sqlite_runtime=sqlite3.sqlite_version,sqlite_extension=_sqlite3.__file__),sort_keys=True))
'''
result=dict(paper_only=True,A_slots_consumed=0,A_trials_started=0,source_frames_released=0,stage_e='RED',stage_f='NOT STARTED',runtime_files_changed=False)
try:
    core.require(socket.gethostname()=='ubuntu-gd-2vcpu-8gb-nyc1' and os.environ.get('RUNNER_NAME')=='the meme machine' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','executor_identity_mismatch')
    OUT.mkdir(exist_ok=False)
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()=='f480c6b4f7a8442fd148c7ed61bcc4447edaefca','approved_harness_commit_changed')
    core.require(core.file_sha(PACKAGE/'package-manifest.json')=='d0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859','approved_harness_manifest_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        p=REPO/row['path'];core.require(p.is_file() and not p.is_symlink() and p.stat().st_size==row['bytes'] and core.file_sha(p)==row['sha256'],'approved_harness_artifact_changed:'+row['path'])
    save('APPROVED_IDENTITIES.json',dict(candidate=binding.candidate_integrity(OLD/'candidate-checkout'),contract=binding.contract_integrity(REPO),infrastructure=binding.infrastructure_identity(),assembly=binding.verify_assembly(OLD/'assembly')['assembly_digest']))
    for row in core.read(DIAG/'MANIFEST.json')['artifacts']:
        core.require(core.file_sha(DIAG/row['path'])==row['sha256'],'original_diagnosis_changed')
    original=core.read(DIAG/'SELECTED_RUNTIME.json');launcher=Path(original['sys_base_prefix'])/'bin/python3.12';library=Path(original['sys_base_prefix'])/'lib/libpython3.12.so.1.0'
    core.require(core.file_sha(launcher)==LAUNCHER_SHA and core.file_sha(library)==LIBRARY_SHA,'existing_Python_artifact_provenance_mismatch')
    env=dict(os.environ);env['LD_LIBRARY_PATH']=str(library.parent)
    proof=command([str(VENV/'bin/python'),'-I','-B','-c','import sys,json;print(json.dumps(dict(version=sys.version,version_info=list(sys.version_info))))'],env=env)
    core.require(json.loads(proof['stdout'])['version_info'][:3]==[3,12,14],'intended_libpython_not_approved_version')
    offset,end,old=runpath_location(launcher.read_bytes())
    core.require(old==b'/opt/hostedtoolcache/Python/3.12.14/x64/lib','unexpected_original_RUNPATH')
    save('ROOT_CAUSE_PROOF.json',dict(original_version=original['sys_version'],original_launcher_sha256=LAUNCHER_SHA,original_RUNPATH=old.decode(),RUNPATH_file_offset=offset,
      actual_installation=str(launcher.parent.parent),loader_selected_system_library_sha256=original['loaded_maps']['/usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0']['sha256'],
      correct_official_library_sha256=LIBRARY_SHA,correct_library_measurement=proof,explanation='Relocated official shared build retained hostedtoolcache RUNPATH; absent destination caused ld.so cache fallback to Ubuntu 3.12.3 libpython. Older observer launcher explicitly supplied LD_LIBRARY_PATH; frozen v3 child_env omits it.'))
    system={p:core.file_sha(p) for p in ('/usr/bin/python3.12','/usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0','/usr/lib/x86_64-linux-gnu/libsqlite3.so.0.8.6')}
    save('SYSTEM_BYTES_BEFORE.json',system)
    archive=OUT/'python-3.12.14-linux-24.04-x64.tar.gz'
    with urllib.request.urlopen(SOURCE,timeout=60) as response,archive.open('xb') as target:shutil.copyfileobj(response,target)
    core.require(core.file_sha(archive)==ARCHIVE_SHA,'official_Python_release_digest_mismatch')
    save('ARTIFACT_PROVENANCE.json',dict(source_url=SOURCE,release_repository='actions/python-versions',release_tag='3.12.14-31661455385',release_asset_id=512394035,
      release_asset_sha256=ARCHIVE_SHA,archive_bytes=archive.stat().st_size,expected_original_launcher_sha256=LAUNCHER_SHA,expected_original_libpython_sha256=LIBRARY_SHA))
    core.require(not ROOT.exists() and not BACKUP.exists() and VENV.is_dir() and not VENV.is_symlink(),'isolated_reconstruction_paths_ambiguous')
    ROOT.mkdir()
    with tarfile.open(archive) as t:t.extractall(ROOT,filter='data')
    new=ROOT/'bin/python3.12';core.require(core.file_sha(new)==LAUNCHER_SHA and core.file_sha(ROOT/'lib/libpython3.12.so.1.0')==LIBRARY_SHA,'extracted_Python_bytes_changed')
    raw=new.read_bytes();offset,end,old=runpath_location(raw);replacement=b'$ORIGIN/../lib'
    patched=raw[:offset]+replacement+b'\0'*(end-offset-len(replacement))+raw[end:]
    core.require(len(patched)==len(raw),'unexpected_executable_length_change')
    with new.open('wb') as f:f.write(patched);f.flush();os.fsync(f.fileno())
    result['runtime_files_changed']=True
    save('ELF_RELOCATION_CHANGE.json',dict(path=str(new),before_sha256=core.sha(raw),after_sha256=core.file_sha(new),old_RUNPATH=old.decode(),new_RUNPATH=replacement.decode(),
      changed_region_offset=offset,changed_region_bytes=end-offset,code_and_all_other_bytes_unchanged=True,procedure='Parse ELF64 SHT_DYNAMIC/DT_STRTAB/DT_RUNPATH; replace only existing RUNPATH string storage, NUL-pad without resizing; resolve libpython relative to the Stage-E-local launcher.'))
    clean=dict(os.environ)
    for k in ('LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH'):clean.pop(k,None)
    save('RECONSTRUCTED_BASE_VERSION.json',command([str(new),'-I','-B','-c','import sys;assert sys.version_info[:3]==(3,12,14);print(sys.version)'],env=clean))
    VENV.rename(BACKUP)
    save('VENV_RECONSTRUCTION.json',dict(old_path=str(VENV),preserved_before_path=str(BACKUP),new_base=str(ROOT),old_file_inventory_sha256=core.file_sha(DIAG/'RUNTIME_FILES_BEFORE.json'),system_packages_enabled=False))
    save('VENV_CREATE_COMMAND.json',command([str(new),'-I','-B','-m','venv',str(VENV)],env=clean))
    target=str(VENV/'bin/python')
    save('DEPENDENCY_INSTALL_COMMAND.json',command([target,'-I','-B','-m','pip','install','--disable-pip-version-check','--no-cache-dir','--only-binary=:all:',
      '--report',str(OUT/'PIP_INSTALL_REPORT.json'),'PyYAML==6.0.2','jsonschema==4.23.0','websockets==17.1'],env=clean))
    verify=command([target,'-I','-B','-c',VERIFY_CODE,str(PACKAGE/'harness'),str(OLD/'assembly/source')],env=clean)
    runtime=json.loads(verify['stdout']);save('RUNTIME_ENVIRONMENT.json',runtime)
    iso=json.loads(command([target,'-I','-B','-c',ISOLATION_CODE],env=clean)['stdout']);save('ISOLATION_AND_DISTRIBUTION_VERIFICATION.json',iso)
    core.require(iso['sys_version_info'][:3]==[3,12,14] and iso['sys_prefix']==str(VENV) and iso['sys_base_prefix']==str(ROOT) and not iso['user_site_enabled'],'venv_isolation_failed')
    core.require(not iso['RECORD_mismatches'],'installed_distribution_RECORD_mismatch')
    core.require(all(Path(d['root']).is_relative_to(VENV) for d in iso['distributions'].values()),'system_distribution_fallback')
    save('RUNTIME_FILES_AFTER.json',dict(venv=inventory(VENV),base=inventory(ROOT),pyvenv_cfg=(VENV/'pyvenv.cfg').read_text()))
    after={p:core.file_sha(p) for p in system};save('SYSTEM_BYTES_AFTER.json',after);core.require(after==system,'system_runtime_bytes_changed')
    save('CORRECTED_LOADER_SEARCH.json',command(['env','LD_DEBUG=libs',target,'-I','-B','-c','import sys;print(sys.version)'],env=clean))
    owner=Path('/etc/stage-e-v3/owner-public.pem')
    save('EXISTING_OWNER_TRUST_DISCOVERY.json',dict(approved_public_key_path=str(owner),exists=owner.is_file(),sha256=core.file_sha(owner) if owner.is_file() else None,
      private_keys_examined=False,original_material_workflow_preview_only=True))
    save('RESOURCE_AFTER_REPAIR.json',attest.inspect([str(MOUNT)],os.getppid()))
    result.update(status='ISOLATED_RUNTIME_REPAIRED_AND_APPROVED_VERIFIER_PASSED',python=runtime['python'],python_executable=runtime['python_executable'],
      python_executable_hash=runtime['python_executable_hash'],sqlite=runtime['sqlite'],websockets_locked_file_verification='PASS',PyYAML='6.0.2',jsonschema='4.23.0',
      system_python_unchanged=True,original_environment_preserved_at=str(BACKUP),complete_preflight=False)
except Exception as exc:
    result.update(status='RUNTIME_REPAIR_BLOCKED',blocker=type(exc).__name__+':'+str(exc))
finally:
    if OUT.is_dir():
        save('RESULT.json',result)
        save('MANIFEST.json',dict(artifacts=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUT.iterdir()) if p.is_file()],A_slots_consumed=0,source_frames_released=0))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUT)+'\n')
    print(json.dumps(result,sort_keys=True))
    if result['status']=='RUNTIME_REPAIR_BLOCKED':raise SystemExit(1)
