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
OUT=MOUNT/'stage-e-native-v3-paper-preflight'/(ID+'-runtime-closure')
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
import re

LIBRARY_PACKAGES={'libtk8.6.so':'libtk8.6','libtcl8.6.so':'libtcl8.6','libgdbm.so.6':'libgdbm6t64','libgdbm_compat.so.4':'libgdbm-compat4t64',
 'libX11.so.6':'libx11-6','libXext.so.6':'libxext6','libXft.so.2':'libxft2','libXss.so.1':'libxss1','libfontconfig.so.1':'libfontconfig1',
 'libfreetype.so.6':'libfreetype6','libXrender.so.1':'libxrender1','libxcb.so.1':'libxcb1','libXau.so.6':'libxau6','libXdmcp.so.6':'libxdmcp6',
 'libpng16.so.16':'libpng16-16t64','libbrotlidec.so.1':'libbrotli1','libbrotlicommon.so.1':'libbrotli1','libbsd.so.0':'libbsd0','libmd.so.0':'libmd0'}

def closure():
    rows=[]
    for p in [ROOT/'bin/python3.12']+sorted((ROOT/'lib/python3.12/lib-dynload').glob('*.so')):
        raw=command(['ldd',str(p)])
        rows.append(dict(path=str(p),sha256=core.file_sha(p),raw=raw,missing=re.findall(r'(\S+)\s+=>\s+not found',raw['stdout'])))
    return rows

def relocate_extension(p):
    raw=p.read_bytes();offset,end,old=runpath_location(raw);replacement=b'$ORIGIN/../..'
    core.require(old==b'/opt/hostedtoolcache/Python/3.12.14/x64/lib','unexpected_extension_RUNPATH')
    patched=bytearray(raw[:offset]+replacement+b'\0'*(end-offset-len(replacement))+raw[end:])
    h=struct.unpack_from('<16sHHIQQQIHHHHHH',raw)
    sections=[struct.unpack_from('<IIQQQQIIQQ',raw,h[6]+i*h[11]) for i in range(h[12])]
    dynamic=[s for s in sections if s[1]==6][0]
    tag_offsets=[o for o in range(dynamic[4],dynamic[4]+dynamic[5],16) if struct.unpack_from('<qQ',raw,o)[0]==29]
    core.require(len(tag_offsets)==1,'extension_search_tag_ambiguous')
    struct.pack_into('<q',patched,tag_offsets[0],15)
    with p.open('wb') as f:f.write(patched);f.flush();os.fsync(f.fileno())
    return dict(path=str(p),before_sha256=core.sha(raw),after_sha256=core.file_sha(p),old_RUNPATH=old.decode(),new_RPATH=replacement.decode(),
      string_region_offset=offset,string_region_bytes=end-offset,dynamic_tag_offset=tag_offsets[0],
      change_scope='Existing ELF search path storage and RUNPATH-to-RPATH tag only, to make Stage-E-local shared-library closure inheritable; no code changes.')

result=dict(paper_only=True,A_slots_consumed=0,A_trials_started=0,source_frames_released=0,stage_e='RED',stage_f='NOT STARTED',quiescence_performed=False)
try:
    core.require(socket.gethostname()=='ubuntu-gd-2vcpu-8gb-nyc1' and os.environ.get('RUNNER_NAME')=='the meme machine' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','executor_identity_mismatch')
    OUT.mkdir(exist_ok=False)
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()=='f480c6b4f7a8442fd148c7ed61bcc4447edaefca','approved_harness_commit_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        p=REPO/row['path'];core.require(p.is_file() and p.stat().st_size==row['bytes'] and core.file_sha(p)==row['sha256'],'approved_harness_artifact_changed:'+row['path'])
    save('APPROVED_IDENTITIES.json',dict(candidate=binding.candidate_integrity(OLD/'candidate-checkout'),contract=binding.contract_integrity(REPO),infrastructure=binding.infrastructure_identity()))
    owner=Path('/etc/stage-e-v3/owner-public.pem')
    save('EXISTING_OWNER_TRUST_DISCOVERY.json',dict(approved_public_key_path=str(owner),exists=owner.is_file(),sha256=core.file_sha(owner) if owner.is_file() else None,private_keys_examined=False))
    system={p:core.file_sha(p) for p in ('/usr/bin/python3.12','/usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0','/usr/lib/x86_64-linux-gnu/libsqlite3.so.0.8.6')};save('SYSTEM_BYTES_BEFORE.json',system)
    original=closure();save('SHARED_LIBRARY_CLOSURE_BEFORE.json',original)
    changed=[relocate_extension(Path(row['path'])) for row in original if row['missing']]
    save('EXTENSION_SEARCH_PATH_REPAIRS.json',changed)
    debs=OUT/'debs';debs.mkdir()
    provenance=[];installed=set()
    for attempt in range(12):
        measured=closure();save('SHARED_LIBRARY_CLOSURE_ROUND_'+str(attempt)+'.json',measured)
        missing=sorted({n for row in measured for n in row['missing']})
        if not missing:break
        packages=sorted({LIBRARY_PACKAGES.get(n,'UNKNOWN:'+n) for n in missing})
        core.require(not any(p.startswith('UNKNOWN:') for p in packages),'unresolved_Stage_E_local_library_source:'+','.join(packages))
        core.require(not all(p in installed for p in packages),'local_library_search_still_unresolved')
        for pkg in packages:
            if pkg in installed:continue
            policy=command(['apt-cache','policy',pkg]);candidate=re.search(r'Candidate:\s*(\S+)',policy['stdout'])
            core.require(candidate and candidate[1]!='(none)','approved_Ubuntu_package_candidate_unavailable:'+pkg)
            spec=pkg+'='+candidate[1];metadata=command(['apt-cache','show',spec]);paragraph=metadata['stdout'].split('\n\n')[0]
            fields=dict(line.split(': ',1) for line in paragraph.splitlines() if ': ' in line and not line.startswith(' '))
            core.require(fields.get('SHA256') and fields.get('Filename'),'package_archive_hash_provenance_missing:'+pkg)
            download=subprocess.run(['apt-get','download',spec],cwd=debs,capture_output=True,text=True,timeout=120)
            core.require(download.returncode==0,'isolated_package_download_failed:'+pkg+':'+download.stderr[-400:])
            matches=[p for p in debs.glob('*.deb') if core.file_sha(p)==fields['SHA256']]
            core.require(len(matches)==1,'downloaded_package_digest_mismatch:'+pkg)
            unpack=OUT/'extracted'/pkg;unpack.mkdir(parents=True)
            extraction=command(['dpkg-deb','--extract',str(matches[0]),str(unpack)])
            copies=[]
            for lib in sorted(unpack.rglob('*')):
                if '.so' not in lib.name or not lib.is_file():continue
                dest=ROOT/'lib'/lib.name;data=lib.read_bytes()
                if dest.exists():core.require(core.file_sha(dest)==core.sha(data),'local_library_name_collision:'+lib.name)
                else:
                    with dest.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                    dest.chmod(0o644)
                copies.append(dict(source=str(lib),destination=str(dest),sha256=core.sha(data),bytes=len(data)))
            provenance.append(dict(package=pkg,version=candidate[1],policy=policy,metadata=metadata,archive_sha256=fields['SHA256'],
              archive_filename=fields['Filename'],download_stdout=download.stdout,download_stderr=download.stderr,extraction=extraction,local_copies=copies))
            installed.add(pkg)
            save('LIBRARY_PACKAGE_PROVENANCE_'+str(len(provenance))+'.json',provenance[-1])
    else:raise ValueError('shared_library_closure_not_completed')
    save('LIBRARY_PACKAGE_PROVENANCE.json',provenance)
    target=str(VENV/'bin/python')
    clean=dict(os.environ)
    for k in ('LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH'):clean.pop(k,None)
    verify=command([target,'-I','-B','-c',VERIFY_CODE,str(PACKAGE/'harness'),str(OLD/'assembly/source')],env=clean)
    runtime=json.loads(verify['stdout']);save('RUNTIME_ENVIRONMENT.json',runtime)
    iso=json.loads(command([target,'-I','-B','-c',ISOLATION_CODE],env=clean)['stdout']);save('ISOLATION_AND_DISTRIBUTION_VERIFICATION.json',iso)
    core.require(iso['sys_version_info'][:3]==[3,12,14] and iso['sys_prefix']==str(VENV) and iso['sys_base_prefix']==str(ROOT) and not iso['user_site_enabled'],'venv_isolation_failed')
    core.require(not iso['RECORD_mismatches'],'installed_distribution_RECORD_mismatch')
    core.require(all(Path(d['root']).is_relative_to(VENV) for d in iso['distributions'].values()),'system_distribution_fallback')
    save('RUNTIME_FILES_AFTER.json',dict(venv=inventory(VENV),base=inventory(ROOT),pyvenv_cfg=(VENV/'pyvenv.cfg').read_text()))
    after={p:core.file_sha(p) for p in system};save('SYSTEM_BYTES_AFTER.json',after);core.require(after==system,'system_runtime_bytes_changed')
    save('RESOURCE_AFTER_REPAIR.json',attest.inspect([str(MOUNT)],os.getppid()))
    result.update(status='ISOLATED_RUNTIME_REPAIRED_AND_APPROVED_VERIFIER_PASSED',python=runtime['python'],python_executable=runtime['python_executable'],python_executable_hash=runtime['python_executable_hash'],
      sqlite=runtime['sqlite'],websockets_locked_file_verification='PASS',PyYAML='6.0.2',jsonschema='4.23.0',system_python_unchanged=True,
      original_environment_preserved_at=str(BACKUP),complete_preflight=False,added_local_packages=sorted(installed))
except Exception as exc:
    result.update(status='RUNTIME_CLOSURE_BLOCKED',blocker=type(exc).__name__+':'+str(exc))
finally:
    if OUT.is_dir():
        save('RESULT.json',result)
        save('MANIFEST.json',dict(artifacts=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUT.iterdir()) if p.is_file()],A_slots_consumed=0,source_frames_released=0))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUT)+'\n')
    print(json.dumps(result,sort_keys=True))
    if result['status']=='RUNTIME_CLOSURE_BLOCKED':raise SystemExit(1)
