from pathlib import Path
import base64,collections,datetime,hashlib,json,shutil
ROOT=Path(__file__).resolve().parent
PACKAGE=ROOT/'bundle/published'
PACKAGE.mkdir(parents=True,exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(name,value):
 p=PACKAGE/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def copy(src,dst):
 target=PACKAGE/dst;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
def read(path):return json.loads((ROOT/path).read_text())
prior=Path('/workspace/stage-e-source/diagnostics/stage-e-native-v3-a-closure-20261003T121620Z/published')
for p in prior.rglob('*'):
 if p.is_file():copy(p,'original-blocked-package/'+str(p.relative_to(prior)))
external=[]
for folder in ['diagnosis','runtime-repair-original','runtime-closure','fresh-allocation','admission-attempt','blocker-diagnosis']:
 for p in (ROOT/folder).rglob('*'):
  if not p.is_file():continue
  if p.suffix=='.gz':
   external.append(dict(original_package=folder,path=p.name,bytes=p.stat().st_size,sha256=sha(p),preserved_local_path=str(p),official_source_url='https://github.com/actions/python-versions/releases/download/3.12.14-31661455385/python-3.12.14-linux-24.04-x64.tar.gz',remote_evidence_root='/mnt/volume_nyc1_1790918115030/stage-e-native-v3-paper-preflight/native-v3-a-autonomous-20261003T133500Z-runtime-repair'))
  else:copy(p,folder+'/'+str(p.relative_to(ROOT/folder)))
for p in (ROOT/'allocation-controller').iterdir():
 if p.name=='ALLOCATION_SIGNATURE.bin':
  put('signing/ALLOCATION_SIGNATURE_BYTES.json',dict(encoding='base64',bytes=p.stat().st_size,sha256=sha(p),base64=base64.b64encode(p.read_bytes()).decode(),exact_original_preserved=True))
 else:copy(p,'signing/'+p.name)
for n in ['INITIAL_IDENTITY_VERIFICATION.json','ALLOCATION_INDEPENDENT_REVIEW.json','ALLOCATION_SIGNATURE_INDEPENDENT_VERIFICATION.json','ALL_SOURCE_MANIFESTS_INDEPENDENT_VERIFICATION.json','RUNTIME_MANIFEST_COMPARISON_RESOLUTION.json','NATIVE_FIXTURE_MIX_DIAGNOSIS.json','PYTHON_RELEASE_PROVENANCE.json','INDEPENDENT_TRUST_READBACK.pem','PRIOR_TRUSTED_PUBLIC_KEY.pem']:
 copy(ROOT/n,'independent-review/'+n)
for n in ['diagnose_runtime.py','diagnose_runtime.yml','repair_runtime.py','repair_runtime.yml','repair_runtime_closure.py','repair_runtime_closure.yml','complete_preflight.py','material_binding.yml','collect_process_attestation_r2.py','fresh_process_binding.py','storage_capability.py','sign_allocation_once.py','diagnose_admission_blocker.py','blocker_diagnosis.yml','build_evidence_package.py']:
 copy(ROOT/n,'collection-source/'+n)
for p in (ROOT/'inputs').iterdir():
 if p.is_file():copy(p,'collection-source/inputs/'+p.name)
archives=[('diagnosis.zip',37126924643,11275313122),('runtime-repair-original.zip',37127763008,11275935112),('runtime-closure.zip',37128222746,11275634808),('fresh-allocation.zip',37129843201,11276342821),('admission-attempt.zip',37129843201,11276671279),('blocker-diagnosis.zip',37130492923,11276726645)]
put('EXTERNAL_BINARY_AND_ARTIFACT_PROVENANCE.json',dict(large_original_artifacts=external,workflow_archives=[dict(name=n,bytes=(ROOT/n).stat().st_size,sha256=sha(ROOT/n),run_id=run,artifact_id=artifact,run_url=f'https://github.com/levonmendall/The-Meme-Machine/actions/runs/{run}',preserved_local_path=str(ROOT/n),extracted_artifacts_preserved_under_manifest=True) for n,run,artifact in archives],original_python_archive=dict(bytes=95088884,sha256='5a03168292516f6dd6dcf630f4bf5369b108abd7c699a7e1db37f1e622257fff',release='3.12.14-31661455385',asset_id=512394035)))
process=read('blocker-diagnosis/PROCESS_APPROVAL.json');runtime=read('runtime-closure/RUNTIME_ENVIRONMENT.json');snapshot=read('admission-attempt/SIGNED_ADMISSION_RESOURCE_INITIAL.json');alloc=read('allocation-controller/SIGNED_ALLOCATION.json');blocker=read('blocker-diagnosis/TAPE_BLOCKER_DIAGNOSIS.json')
checks={
 'candidate':'PASS unchanged S/T, 1241 files',
 'harness':'PASS unchanged approved f480 commit, 62 manifest artifacts',
 'production_contract':'PASS unchanged approved 5ed5 commit, 192 manifest artifacts',
 'executor':'PASS existing DigitalOcean droplet 605465049, hostname and boot unchanged',
 'CPU_RAM_envelope':'PASS at signed resource admission; exactly two dedicated vCPU and 8 GiB allocated RAM',
 'CPU_RAM_reservation':'PASS signed fresh provider allocation plus complete ancestor/process checks at 14:35 admission; not a Stage-A permit',
 'cgroup_completeness':'PASS complete inventory, no restrictive ancestor CPU/cpuset/RAM limit',
 'process_attestation':'PASS 114 processes at allocation; 116 at post-stop diagnostic; zero unexplained or competing processes',
 'storage_capacity':'PASS approved durable volume, ext4, file/directory fsync and SQLite WAL locking',
 'storage_reservation':'PASS unchanged reserve_storage check; 10 GiB working, 20 GiB simultaneous publication, 12 GiB headroom',
 'tape_capacity_reservation':'PASS tape is 2442975789 bytes and included in signed storage bounds',
 'tape_physical_and_inventory_bytes':'PASS exact approved tape and frame-inventory digests',
 'tape_semantic_validation':'FAIL unchanged validate_existing at first frame: failed_transaction_mix; 284 actual failed transactions, 256 required',
 'full_tape_semantic_prefix_checks':'NOT REACHED: approved verifier stops at the first-frame semantic failure; no PASS claimed',
 'Python_identity':'PASS actual executing 3.12.14 with verified Stage-E-local executable and libpython',
 'Python_capability':'PASS selected isolated executable, prefixes, disabled user/system package fallback, affinity [0,1]',
 'child_process_capability':'PASS approved unshare binary launches verified 3.12.14 in a distinct network namespace',
 'locked_dependencies':'PASS 62 exact locked websockets files; required PyYAML/jsonschema versions and distribution identities',
 'SQLite_and_shared_libraries':'PASS 3.45.1 and unchanged SQLite bytes; 1881 stdlib files; complete library closure inspected',
 'runtime_reservation':'BYTE IDENTITIES VERIFIED; final authorized declaration/runtime binding NOT ADMITTED after tape failure',
 'allocation_signature':'PASS independently verified new exact fresh payload against pre-established separate public key',
 'declaration_authorization':'BLOCKED/NOT ADMITTED; tape gate failed first; separate trusted owner key and exact-declaration signed permit are also unavailable',
 'required_workflow_identity':'PASS actual workflow_dispatch run 37129843201 attempt 1 at exact installed material workflow path',
 'workload_identity':'PASS unchanged class A workload digest; no feeder or trial process started',
 'slot_and_source_accounting':'PASS zero A slots consumed, zero trial namespaces created, zero source frames released',
 'final_material_admission':'BLOCKED; no complete preflight PASS record and no Stage A'
}
put('ADMISSION_CHECK_MATRIX.json',dict(checks=checks,first_exact_blocker='failed_transaction_mix',true_escalation_numbers=[3,4,12],no_partial_completion_promoted_to_PASS=True))
facts=dict(version='stage-e-native-v3-a-autonomous-consolidated-result',paper_only=True,stage_e='RED',stage_f='NOT STARTED',
 repository='levonmendall/The-Meme-Machine',approved_repository_commit='f480c6b4f7a8442fd148c7ed61bcc4447edaefca',approved_repository_tree='6805846ed6d5c2acb31d843d749b80b923df87a1',candidate_S='7a516a6a92be9347661ac0e7f560971c171a0931',candidate_T='9da7d1e1625ba04c1437c63606c90f5e293bdba7',
 harness_manifest_sha256='d0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859',executor_id='digitalocean-droplet-605465049',hostname='ubuntu-gd-2vcpu-8gb-nyc1',boot_id='f0453f41-fe5e-4e10-bda7-657de65713d8',
 preflight_result='BLOCKED',first_exact_blocker='failed_transaction_mix',first_blocker_utc='2026-10-03T14:35:08Z',actual_failed_transactions=284,required_failed_transactions=256,repair_exceeds_authorization='Changing the frozen tape/source bytes changes approved workload hashes; changing the verifier alters frozen admission semantics. Escalations 3, 4, 12.',additional_blocker='Separately trusted owner public key and exact-declaration signed permit unavailable; allocation key cannot supply owner authority.',
 runtime_version_before='3.12.3',runtime_version_after='3.12.14',runtime_root_cause='Relocated official shared launcher retained absent /opt/hostedtoolcache RUNPATH and loaded system 3.12.3 libpython through ld.so cache.',runtime_changed_paths=['/workspace/stage-e-runtime','/workspace/stage-e-python-3.12.14'],original_venv_preserved_path='/workspace/stage-e-runtime-before-native-v3-a-autonomous-20261003T133500Z',system_python_unchanged=True,host_services_quiesced=[],runtime_executable_sha256=runtime['python_executable_hash'],stdlib_digest=runtime['stdlib_digest'],SQLite_version=runtime['sqlite'],dependency_versions={'PyYAML':'6.0.2','jsonschema':'4.23.0','websockets':'17.1'},
 allocation_public_key_sha256='1c68ec0bffda7d70f93ef31ac6f4418bd5a6b600dfb2d06e106ac1907c9ceadd',allocation_signed_document_sha256=sha(ROOT/'allocation-controller/SIGNED_ALLOCATION.json'),allocation_payload_sha256=hashlib.sha256(json.dumps(alloc['payload'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),allocation_verified=True,allocation_private_key_discarded=True,
 final_process_count=len(process['complete_mapping']),process_classifications=dict(collections.Counter(x['disposition'] for x in process['complete_mapping'])),unexplained_processes=[],competing_processes=[],storage_bounds=read('admission-attempt/STORAGE_BUDGET_DERIVATION.json')['bounds'],
 Stage_A_admitted=False,Stage_A_admission_utc=None,Stage_A_disposition='NOT EXECUTED: complete preflight PASS was not obtained',Stage_A_trial_budget=1,Stage_A_trials_started=0,Stage_A_slots_consumed=0,Stage_A_slots_remaining=1,Stage_A_source_frames_released=0,Stage_A_early_stop=None,preworkload_stop='Frozen tape admission semantics conflict with exact approved bytes',Stage_B_started=False,Stage_F_started=False,production_live_trading_activated=False,
 remote_evidence_root='/mnt/volume_nyc1_1790918115030/stage-e-native-v3-paper-preflight',local_evidence_root=str(ROOT),material_workflow_commit='a568bb7704131c0aad3147968ed74ceabdce9466',material_workflow_run=37129843201,material_workflow_attempt=1,material_workflow_event='workflow_dispatch')
put('RESULT.json',facts)
(PACKAGE/'README.md').write_text('''This is the audit payload for the owner-authorized Stage-E Native V3-A preflight repair. The frozen tape verifier rejected the exact native fixture before material admission. The consolidated report is the sibling REPORT.md. RESULT.json and ADMISSION_CHECK_MATRIX.json separate measured passes from blocked and unreached gates. No material Stage-A slot or source frame was consumed.

The outer MANIFEST.json covers every regular file in this published directory except itself. Nested manifests preserve each original evidence package as collected. The 95,088,884-byte official Python archive is preserved locally and on the executor and identified by immutable release URL and SHA-256 in EXTERNAL_BINARY_AND_ARTIFACT_PROVENANCE.json. That binary is omitted from Git; its original nested-manifest entry is intentionally retained. Allocation private keys were held only in memory and discarded. No private key is an evidence artifact.
''')
rows=[dict(path=str(p.relative_to(PACKAGE)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(PACKAGE.rglob('*')) if p.is_file()]
manifest=dict(version='stage-e-native-v3-a-autonomous-evidence-manifest',paper_only=True,preflight_result='BLOCKED',A_slots_consumed=0,source_frames_released=0,artifacts=rows)
(PACKAGE/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
for row in rows:
 p=PACKAGE/row['path'];assert p.stat().st_size==row['bytes'] and sha(p)==row['sha256']
print(json.dumps(dict(published_artifacts=len(rows),bytes=sum(r['bytes'] for r in rows),manifest_sha256=sha(PACKAGE/'MANIFEST.json'),manifest_bytes=(PACKAGE/'MANIFEST.json').stat().st_size,first_exact_blocker='failed_transaction_mix',A_slots_consumed=0,source_frames_released=0)))
request=dict(base_tree='6805846ed6d5c2acb31d843d749b80b923df87a1',tree=[dict(path='diagnostics/stage-e-native-v3-a-autonomous-20261003T133500Z/published/'+str(p.relative_to(PACKAGE)),mode='100644',type='blob',content=p.read_text()) for p in sorted(PACKAGE.rglob('*')) if p.is_file()])
(ROOT/'EVIDENCE_PUBLICATION_TREE_REQUEST.json').write_text(json.dumps(request))
