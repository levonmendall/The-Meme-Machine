"""Read-only diagnosis after approved tape rejection; cannot authorize workload."""
import hashlib,importlib.util,json,os,socket,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
REPO=Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE=REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0,str(PACKAGE/'harness'))
import attest,binding,core,tape
from declaration import preview,authorize
from ledger import fresh_campaign
ID='native-v3-a-autonomous-20261003T133500Z'
MOUNT=Path('/mnt/volume_nyc1_1790918115030')
OLD=MOUNT/'meme-machine-observer-v2-7a516a6a'
ADMISSION=MOUNT/'stage-e-native-v3-paper-preflight'/(ID+'-admission')
OUTPUT=MOUNT/'stage-e-native-v3-paper-preflight'/(ID+'-blocker-diagnosis')
OUTPUT.mkdir(exist_ok=False)
RESULT=dict(paper_only=True,diagnostic_only=True,A_trials_started=0,A_slots_consumed=0,source_frames_released=0,stage_e='RED',stage_f='NOT STARTED',preflight_pass=False)
def save(n,v):
 data=core.canonical(v)+b'\n'
 with (OUTPUT/n).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 attest.fsync_dir(OUTPUT)
 return dict(path=str(OUTPUT/n),sha256=core.sha(data),bytes=len(data))
def command(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=60)
 return dict(argv=args,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
try:
 spec=importlib.util.spec_from_file_location('unchanged_admission_collector',HERE/'complete_preflight.py')
 c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
 save('APPROVED_IDENTITY.json',c.approved_identity())
 save('CANDIDATE_VERIFICATION.json',binding.candidate_integrity(OLD/'candidate-checkout'))
 assembly=binding.verify_assembly(OLD/'assembly')
 save('ASSEMBLY_VERIFICATION.json',dict(assembly_digest=assembly['assembly_digest'],assembly_manifest_sha256=core.file_sha(OLD/'assembly/assembly.json'),files_verified=len(assembly['files'])))
 actual=OLD/'tape/full-cohort-v2.tape';inventory=OLD/'tape/FRAMES.json';required=core.workload('A')['tape_binding']
 before=actual.stat();physical=core.file_sha(actual);after=actual.stat()
 binding_ok=(physical==required['physical_sha256'] and before.st_size==required['physical_bytes'] and core.file_sha(inventory)==required['frame_inventory_sha256'] and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns))
 core.require(binding_ok,'stored_tape_or_inventory_identity_changed')
 reader=tape.Reader(actual,required['members'][-1]);raw,row=reader.next();reader.close(strict=False)
 core.require(row==core.read(inventory)[0],'first_stored_frame_inventory_identity')
 b=json.loads(raw)['params']['result']['value']['block'];errors=sum(x['meta']['err'] is not None for x in b['transactions'])
 sys.path.insert(0,str(OLD/'assembly/source'))
 from certification.stage_e_native_v2 import fixtures
 native=fixtures.build_frame('run380',0)
 core.require(raw==native,'stored_first_frame_not_exact_native_fixture')
 spec=fixtures.spec('run380');templates=fixtures.templates('run380');lanes=[]
 for lane,count in spec['transaction_mix'].items():
  name='pumpswap' if lane=='failed' else lane
  n=sum(lane=='failed' or templates[name][i%len(templates[name])]['meta']['err'] is not None for i in range(count))
  lanes.append(dict(lane=lane,declared_count=count,actual_failed_transactions=n,template_count=len(templates[name]),template_failed_count=sum(x['meta']['err'] is not None for x in templates[name])))
 try:
  tape.validate_existing(actual,inventory,kind='A')
 except Exception as exc:
  rejection=dict(verifier_path=str(Path(tape.__file__)),verifier_sha256=core.file_sha(Path(tape.__file__)),exact_rejection_type=type(exc).__name__,exact_rejection=str(exc),passed=False)
 else:raise ValueError('unexpected_tape_validation_state')
 core.require(rejection['exact_rejection']=='failed_transaction_mix','unexpected_tape_rejection')
 save('TAPE_BLOCKER_DIAGNOSIS.json',dict(rejection,physical_tape_path=str(actual),physical_sha256=physical,physical_bytes=before.st_size,frame_inventory_sha256=core.file_sha(inventory),all_physical_bytes_match_approved_binding=True,immutable_file_unchanged=True,first_stored_frame=row,first_stored_frame_equals_exact_candidate_native_fixture=True,actual_total_transactions=len(b['transactions']),actual_failed_transactions=errors,frozen_verifier_required_total_failed_transactions=256,lane_breakdown=lanes,source_frames_released=0,A_slots_consumed=0,repair_requires_frozen_source_or_verifier_semantics_change=True))
 runtime=binding.runtime_identity(OLD/'assembly/source');save('RUNTIME_REVERIFICATION.json',runtime)
 prior=core.read(ADMISSION/'RUNTIME_ENVIRONMENT.json')
 save('RUNTIME_STABILITY_COMPARISON.json',dict(equal=runtime==prior,prior_sha256=core.sha(core.canonical(prior)),current_sha256=core.sha(core.canonical(runtime)),executables_equal=runtime['python_executable_hash']==prior['python_executable_hash'],stdlib_equal=runtime['stdlib_digest']==prior['stdlib_digest'],dependencies_equal=runtime['dependencies']==prior['dependencies'],sqlite_equal=runtime['sqlite']==prior['sqlite']))
 p=command([sys.executable,'-I','-B','-c','import json,sys,site,os;print(json.dumps(dict(version=list(sys.version_info),executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,user_site=site.ENABLE_USER_SITE,affinity=sorted(os.sched_getaffinity(0)))))'])
 save('PYTHON_CAPABILITY.json',p);core.require(p['returncode']==0,'Python_capability')
 values=json.loads(p['stdout']);core.require(values['version'][:3]==[3,12,14] and values['prefix']=='/workspace/stage-e-runtime' and values['base_prefix']=='/workspace/stage-e-python-3.12.14' and values['user_site'] is False and values['affinity']==[0,1],'isolated_runtime_capability')
 ch=command([runtime['os_tools']['unshare']['path'],'--net','--',sys.executable,'-I','-B','-c','import json,os,sys;print(json.dumps(dict(version=list(sys.version_info),network_namespace=os.readlink("/proc/self/ns/net"),affinity=sorted(os.sched_getaffinity(0)),uid=os.getuid(),pid=os.getpid())))'])
 save('CHILD_PROCESS_CAPABILITY.json',ch);core.require(ch['returncode']==0,'network_isolated_child_capability')
 child=json.loads(ch['stdout']);core.require(child['version'][:3]==[3,12,14] and child['network_namespace']!=os.readlink('/proc/self/ns/net') and child['affinity']==[0,1],'child_runtime_namespace')
 resource=attest.inspect([str(MOUNT)],os.getpid());save('POST_STOP_RESOURCE_SNAPSHOT.json',resource);c.host_checks(resource)
 spec=importlib.util.spec_from_file_location('fresh_process_binding',HERE/'fresh_process_binding.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 processes=m.approve(resource,HERE,OUTPUT,save,attest,core)
 bounds=core.read(ADMISSION/'STORAGE_BUDGET_DERIVATION.json')['bounds'];save('POST_STOP_STORAGE_RESERVE_CHECK.json',attest.reserve_storage(resource,bounds))
 oldalloc=attest.signed_document(ADMISSION/'SIGNED_ALLOCATION.json',ADMISSION/'ALLOCATION_PUBLIC_KEY.pem','1c68ec0bffda7d70f93ef31ac6f4418bd5a6b600dfb2d06e106ac1907c9ceadd')
 save('PRESERVED_ALLOCATION_REVERIFICATION.json',dict(signature_verified=True,payload_equals_draft=oldalloc==core.read(ADMISSION/'ALLOCATION_DRAFT.json'),public_key_sha256='1c68ec0bffda7d70f93ef31ac6f4418bd5a6b600dfb2d06e106ac1907c9ceadd',signed_allocation_sha256=core.file_sha(ADMISSION/'SIGNED_ALLOCATION.json'),original_admission_pass=core.read(ADMISSION/'SIGNED_ALLOCATION_ADMISSION.json'),fresh_process_inventory_attested=True,not_reused_as_post_stop_material_admission=True))
 owner=Path('/etc/stage-e-v3/owner-public.pem')
 save('OWNER_SIGNING_TRUST_DISCOVERY.json',dict(public_key_path=str(owner),public_key_present=owner.is_file(),trusted_owner_public_key_sha256=None,exact_owner_permit_present=False,allocation_key_not_substituted=True,textual_owner_execution_authorization_received=True,cryptographic_admission_failed=True,private_keys_examined=False))
 save('WORKLOAD_AND_SLOT_ACCOUNTING.json',dict(workload_sha256=core.sha(core.canonical(core.workload('A'))),trial_budget=1,trial_slots_consumed=0,trials_started=0,source_frames_released=0,material_admission_utc_ns=None,Ledger_create_called=False,run_execute_called=False,trial_source_feeder_started=False,slot_boundary='Approved STARTED ledger event before trial child startup; never reached.',prior_failure_is_preflight_not_a_material_trial=True))
 RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',first_exact_blocker='failed_transaction_mix',escalations=[3,4,12],actual_failed_transactions=errors,required_failed_transactions=256,physical_tape_identity_verified=True,first_frame_exact_native=True,runtime_verified=True,Python_child_capability_verified=True,complete_post_stop_process_attestation=True,post_stop_storage_reserve_check=True,additional_owner_signing_trust_missing=True,remaining_material_declaration_admission=False)
except Exception as exc:RESULT.update(diagnosis_error_type=type(exc).__name__,diagnosis_error=str(exc))
finally:
 save('FINAL_RESULT.json',RESULT)
 rows=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.iterdir()) if p.is_file()]
 save('MANIFEST.json',dict(artifacts=rows,diagnostic_only=True,A_slots_consumed=0,source_frames_released=0))
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUTPUT)+'\n')
 print(json.dumps(RESULT,sort_keys=True))
 if 'diagnosis_error' in RESULT:raise SystemExit(1)
