"""Assemble a bounded evidence closure; no machine/runtime mutation or workload."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path('/workspace/native-v3-closure-20261003T121620Z')
DEST=ROOT/'published'
DEST.mkdir(exist_ok=False)
CONTROLLER=Path('/workspace/allocation-controller-closure-20261003T121620Z')
SHA=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
READ=lambda p:json.loads(Path(p).read_bytes())
def save(name,value):
    path=DEST/name;path.parent.mkdir(exist_ok=True,parents=True)
    path.write_text(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
def copy_tree(source,name):
    for path in sorted(source.iterdir()):
        assert path.is_file() and not path.is_symlink()
        target=DEST/name/path.name;target.parent.mkdir(exist_ok=True,parents=True)
        shutil.copyfile(path,target)

for source,name in [('raw','discovery'),('raw-r2','process-provenance'),('final-raw','signed-allocation'),('runtime-raw','runtime-blocker')]:
    copy_tree(ROOT/source,name)
for name in ('PROCESS_ATTESTATION_REVIEW.json','FWUPD_DISPOSITION.json','CONTROLLER_PAYLOAD_REVIEW.json'):
    shutil.copyfile(ROOT/name,DEST/name)
for name in ('KEY_ESTABLISHMENT.json','SIGNING_RECEIPT.json','ALLOCATION_PUBLIC_KEY.pem','CANONICAL_ALLOCATION_PAYLOAD.json'):
    shutil.copyfile(CONTROLLER/name,DEST/name)
for name in ('collect_process_attestation.py','collect_process_attestation_r2.py','complete_preflight.py','fresh_process_binding.py','storage_capability.py','runtime_failure_evidence.py','sign_allocation_once.py','process-attestation.yml','process-attestation-r2.yml','signed-closure.yml','runtime-blocker-workflow.yml'):
    target=DEST/'collection-source'/name;target.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(ROOT/name,target)

review=READ(ROOT/'PROCESS_ATTESTATION_REVIEW.json')
roles={(r['unit'],r['executable'],r['executable_sha256']):r for r in review['reviewed_service_roles']}
roles.update({('fwupd.service','/usr/libexec/fwupd/fwupd',READ(ROOT/'FWUPD_DISPOSITION.json')['executable_sha256']):READ(ROOT/'FWUPD_DISPOSITION.json')})
versions=READ(ROOT/'runtime-raw/RUNTIME_FAILURE_OBSERVATION.json')
allocation=READ(ROOT/'final-raw/SIGNED_ALLOCATION.json')['payload']
signed={(r['pid'],r['start_ticks'],r['executable_sha256']) for r in allocation['system_processes']}

def mapping(snapshot,details,units,provenance,label):
    by_pid={r['pid']:r for r in snapshot['processes']};details={r['pid']:r for r in details}
    scope={snapshot['scope_pid']}
    while True:
        more=scope|{r['pid'] for r in by_pid.values() if r['ppid'] in scope}
        if more==scope:break
        scope=more
    rows=[];unresolved=[]
    for row in snapshot['processes']:
        d=details[row['pid']];unit=d['membership_units'][-1] if d['membership_units'] else None
        raw=d['raw']['cgroup'].get('raw','')
        group=raw.split(':',2)[-1].strip() if raw else None
        status=d['raw']['status'].get('raw','');issue=[]
        chain=[];pid=row['pid']
        while pid in by_pid and pid not in chain:
            chain.append(pid);pid=by_pid[pid]['ppid']
        if row['kernel']:
            disposition='ATTESTED_KERNEL_SYSTEM_PROCESS'
            if row['ppid'] not in (0,2) or 'Kthread:\t1' not in status:issue.append('kernel_owner_unproved')
            source=dict(kind='kernel-thread',kernel_identity=versions['uname'])
        elif row['pid'] in scope:
            disposition='NONMATERIAL_PREFLIGHT_SCOPE'
            source=dict(kind='published-collection-only-controller',executable_sha256=row['executable_sha256'])
        else:
            source=provenance['executables'].get(row['executable'])
            role=roles.get((unit,row['executable'],row['executable_sha256']))
            if role is None:issue.append('no_reviewed_exact_service_executable_binding')
            props=units['units'].get(unit,{})
            cg=props.get('ControlGroup')
            if row['pid']==1:
                if row['ppid']!=0 or group!='/init.scope':issue.append('OS_init_owner_unproved')
            elif not props.get('MainPID','0').isdigit() or int(props.get('MainPID','0')) not in chain:
                issue.append('unit_main_pid_not_in_parent_ancestry')
            if not cg or not group or not (group==cg or group.startswith(cg.rstrip('/')+'/')):issue.append('unit_cgroup_unproved')
            if source is None or source['sha256']!=row['executable_sha256']:issue.append('executable_source_identity_unproved')
            if source and source['package_bindings']:
                installed=[entry for item in source['installed_manifest_verification'] for entry in item['executable_entries']]
                if not installed or any(not item['matches'] for item in installed):issue.append('installed_package_manifest_unproved')
            elif not unit or not unit.startswith('actions.runner.'):
                issue.append('unpackaged_owner_unproved')
            disposition='ATTESTED_SYSTEM_SERVICE'
        if issue:
            disposition='OWNER_APPROVED_QUIESCENCE_REQUIRED';unresolved.append(dict(pid=row['pid'],issues=issue))
        owner=next((line.split()[1:] for line in status.splitlines() if line.startswith('Uid:')),None)
        rows.append(dict(pid=row['pid'],ppid=row['ppid'],start_ticks=row['start_ticks'],executable=row['executable'],
            executable_sha256=row['executable_sha256'],process_name=d['raw']['comm'].get('raw','').strip(),
            UID_owner=owner,owner_unit=unit,owner_main_pid=units['units'].get(unit,{}).get('MainPID'),parent_ancestry=chain,
            cgroup=group,cgroup_sha256=d['raw']['cgroup'].get('sha256'),thread_inventory=row['threads'],provenance=source,
            activity=dict(stat=d['raw']['stat'],io=d['raw']['io'],scheduler=d['raw']['schedstat'],
                systemd_CPU_usage_ns=units['units'].get(unit,{}).get('CPUUsageNSec'),systemd_memory_current=units['units'].get(unit,{}).get('MemoryCurrent')),
            disposition=disposition,issues=issue,in_signed_allocation_system_tuple=(row['pid'],row['start_ticks'],row['executable_sha256']) in signed,
            evidence_scope=label))
    return dict(snapshot_utc_ns=snapshot['real_utc_ns'],snapshot_boot_id=snapshot['boot_id'],complete_mapping=rows,
        unresolved_owner_or_source_bindings=unresolved,all_processes_mapped=not unresolved,
        distinction='Service/source mapping describes observed ownership. Exact signed-tuple admission is a separate unchanged harness requirement. No post-blocker workload admission was attempted.',
        A_trials_started=0,A_slots_consumed=0,source_frames_released=0)

current=READ(ROOT/'runtime-raw/RESOURCE_AFTER_BLOCKER.json')
map_current=mapping(current,READ(ROOT/'runtime-raw/PROCESS_AFTER_BLOCKER_DETAILS.json'),READ(ROOT/'runtime-raw/SYSTEMD_AFTER_BLOCKER.json'),READ(ROOT/'runtime-raw/EXECUTABLES_AFTER_BLOCKER_PROVENANCE.json'),'final read-only stop snapshot; not workload admission')
save('FINAL_PROCESS_MAPPING.json',map_current)
post=READ(ROOT/'final-raw/SIGNED_ADMISSION_RESOURCE_INITIAL.json')
map_post=mapping(post,READ(ROOT/'final-raw/POST_SIGNATURE_PROCESS_DETAILS.json'),READ(ROOT/'final-raw/POST_SIGNATURE_SYSTEMD_OWNERSHIP.json'),READ(ROOT/'final-raw/FRESH_EXECUTABLE_PROVENANCE.json'),'post-signature snapshot before frozen-runtime check')
save('POST_SIGNATURE_PROCESS_MAPPING.json',map_post)

sys.dont_write_bytecode=True
sys.path.insert(0,'/workspace/meme-preflight-repo/diagnostics/stage-e-native-v3-executable-harness/harness')
import attest,core
cap=READ(ROOT/'final-raw/STORAGE_CAPABILITY.json')
provider=READ(ROOT/'final-raw/PROVIDER_FRESH_FOR_ALLOCATION.json')
assert provider['id']==605465049 and provider['size_slug']=='gd-2vcpu-8gb' and provider['vcpus']==2 and provider['memory']==8192 and provider['disk']==50 and provider['region']['slug']=='nyc1'
assert not attest.cgroup_completeness_errors(current['cgroup']);attest.verified_cgroup_inventory(current['cgroup'])
checks=READ(ROOT/'runtime-raw/RESOURCE_AFTER_BLOCKER_CHECKS.json');assert checks['passed']
identity=READ(ROOT/'raw-r2/APPROVED_IDENTITY.json')
candidate=READ(ROOT/'raw-r2/CANDIDATE_IDENTITY.json')
assembly=READ(ROOT/'raw-r2/ASSEMBLY_IDENTITY.json')
save('RESOURCE_AND_REMAINING_CHECKS.json',dict(fresh_CPU='PASS',visible_CPU_ids=current['cpu']['present'],present_possible_online_affinity_exactly_2=True,
    fresh_RAM_allocation='PASS',allocated_RAM_bytes=provider['memory']*1024**2,usable_RAM_bytes=current['memory']['MemTotal'],available_RAM_bytes=current['memory']['MemAvailable'],
    corrected_cgroup='PASS',ancestor_inventory_sha256=core.sha(core.canonical(current['cgroup'])),swap=False,ballooning=False,
    current_storage_mount=current['storage'],durability_capability='PASS',sqlite_WAL_locking=cap['second_writer_excluded'],file_directory_fsync=cap['directory_fsync_returned'],
    storage_budget_and_reservation='NOT REACHED: first frozen-runtime predicate failed before storage_bounds/reserve_storage',
    tape_physical_and_encoded_decoded_hash_verification='NOT REACHED: first frozen-runtime predicate failed before tape.validate_existing',
    tape_evidence_capacity_reservation='NOT REACHED',runtime_reservation='BLOCKED: frozen_runtime_version',
    full_runtime_library_stdlib_extensions_sqlite_OS_tool_manifest='NOT REACHED: approved runtime_identity stops at its first version predicate',
    execution_identity=dict(approved_executable_commit=identity['executable_commit'],repository_tree=identity['repository_tree'],candidate=candidate,assembly=assembly),
    UNIX_socket_path_validation='NOT REACHED',declaration_validation='NOT REACHED; no A campaign, declaration, ledger or owner execution permit created',
    no_inferred_PASS_for_unreached_checks=True))
save('TRUST_ESTABLISHMENT_AND_READBACK.json',dict(allocation_public_key_sha256=SHA(CONTROLLER/'ALLOCATION_PUBLIC_KEY.pem'),
    trust_commit='191437b6599d8b48c679a9e0e5af94ca1107a4aa',trust_path='allocation-trust/native-v3-a-closure-20261003T121620Z/ALLOCATION_PUBLIC_KEY.pem',
    independent_connector_readback_compared_byte_for_byte=True,independent_readback_public_key_sha256=SHA(ROOT/'INDEPENDENT_PUBLIC_KEY.pem'),
    public_key_established_before_signed_allocation_accepted=True,signing_procedure='sign_allocation_once.py',controller_payload_review='CONTROLLER_PAYLOAD_REVIEW.json',
    private_key_never_committed_or_published=True,private_signer_process_exited_after_one_signature=True,private_key_preserved=False,
    separate_from_owner_execution_permit=True,signature_verification_evidence='signed-allocation/SIGNATURE_VERIFICATION.json'))
save('OWNER_STOP_RECORD.json',dict(first_exact_unresolved_blocker='frozen_runtime_version',expected_python='3.12.14',observed_python=versions['observed']['python'],
    no_quiescence_required_to_resolve_fwupd=True,quiescence_performed=[],runtime_mutations_performed=[],
    authorized_scope='read-only preflight closure and evidence publication only',owner_action_needed='Authorize a separate task to establish the approved Python 3.12.14 runtime and required locked tooling on the actual executor, then repeat the complete fresh preflight under a newly established key. This closure task cannot change runtime behavior.',
    stop_for_owner=True,execution_authorized=False,actual_slots_reserved=False,A_trials_started=0,A_slots_consumed=0,source_frames_released=0,
    Stage_E='RED',Stage_F='NOT STARTED'))
result=dict(preflight_id='native-v3-a-closure-20261003T121620Z',disposition='STAGE_E_NATIVE_V3_A_PREFLIGHT: BLOCKED',first_exact_unresolved_blocker='frozen_runtime_version',
    expected_python='3.12.14',observed_python=versions['observed']['python'],observed_websockets_metadata_version=versions['observed']['websockets'],
    approved_contract_commit='5ed5aef4dfe1bb7823037fe1ce440c193411a194',approved_executable_commit=identity['executable_commit'],approved_repository_tree=identity['repository_tree'],
    candidate_S='7a516a6a92be9347661ac0e7f560971c171a0931',candidate_T='9da7d1e1625ba04c1437c63606c90f5e293bdba7',assembly_digest=assembly['assembly_digest'],
    droplet_id=provider['id'],size_slug=provider['size_slug'],hostname=current['hostname'],boot_id=current['boot_id'],
    CPU_admission='PASS resource facts only',RAM_admission='PASS resource facts only',corrected_cgroup_admission='PASS resource facts only',
    fwupd_disposition='ATTESTED_SYSTEM_SERVICE: packaged/proven; naturally inactive, no future PID exemption',
    allocation_signature='VALID under newly established dedicated trusted key; does not imply complete workload admission',
    signed_allocation_sha256=SHA(ROOT/'final-raw/SIGNED_ALLOCATION.json'),allocation_public_key_sha256=SHA(CONTROLLER/'ALLOCATION_PUBLIC_KEY.pem'),
    provider_evidence_sha256=SHA(ROOT/'final-raw/PROVIDER_FRESH_FOR_ALLOCATION.json'),runtime_failure_evidence_sha256=SHA(ROOT/'runtime-raw/RUNTIME_FAILURE_OBSERVATION.json'),
    full_environment_manifest_sha256=None,tape_verification='NOT REACHED',storage_reservation='NOT REACHED',runtime_reservation='BLOCKED',declaration_validation='NOT REACHED',
    campaign_id=None,owner_execution_permit_created=False,execution_authorized=False,actual_slots_reserved=False,A_trials_started=0,A_slots_consumed=0,source_frames_released=0,
    resource_configuration_mutations=0,quiescence_performed=[],stage_e='RED',stage_f='NOT STARTED',PR_118_merged=False,stop_for_owner=True,
    original_executor_evidence_roots=[str(READ(ROOT/'raw/DISCOVERY_RESULT.json')['retained_executor_evidence_path']),str(READ(ROOT/'raw-r2/DISCOVERY_RESULT.json')['retained_executor_evidence_path']),str(READ(ROOT/'allocation-raw/ALLOCATION_RESOURCE_SNAPSHOT.json')['storage'][0]['path'])+'/stage-e-native-v3-paper-preflight/native-v3-a-closure-20261003T121620Z-signed','/mnt/volume_nyc1_1790918115030/stage-e-native-v3-paper-preflight/native-v3-a-closure-20261003T121620Z-runtime-blocker'])
save('RESULT.json',result)
text=f'''# Stage-E Native V3-A preflight closure — PAPER ONLY

STAGE_E_NATIVE_V3_A_PREFLIGHT: BLOCKED

The first exact unresolved blocker is `frozen_runtime_version`: the actual CPython reports **{versions['observed']['python']}**, while the frozen contract requires **3.12.14**. The executable resolves under a directory named `Python/3.12.14`, but its actual version is 3.12.3. The unchanged `binding.runtime_identity()` refused it. Websockets metadata reports 17.1; the full locked-file runtime check was not reached. No runtime change is authorized or performed.

Fresh records resolve the prior fwupd owner/provenance gap. PID 36400 belongs to packaged `fwupd.service`, activated through D-Bus and the refresh timer. Journal evidence records successful natural deactivation at 12:06:52 UTC. fwupd is absent from the fresh snapshots. Its installed executable matches package version 2.0.20-1ubuntu2~24.04.2 and the installed manifest. The installed idle timeout documentation and repeated approximately 300-second deactivation history are preserved. This gives no future-PID exemption and does not reconstruct historical CPU/I/O counters that were not retained.

The complete process inventories, owner/unit/cgroup/provenance/activity mappings, corrected cgroup raw evidence, fresh provider response, CPU/RAM observations and durable-mount capability proof are preserved. The allocation was signed with a newly established dedicated RSA-3072/OpenSSL-SHA256 key and verified independently by the controller and exact approved harness. The public key was separately published before signature acceptance. The private key was held only in the controller process and discarded when that process exited after one signature.

Signed allocation SHA-256: `{result['signed_allocation_sha256']}`. Public-key SHA-256: `{result['allocation_public_key_sha256']}`. Exact provider receipt SHA-256: `{result['provider_evidence_sha256']}`.

The native runtime failure occurred before complete storage-budget/reservation, tape physical/frame/prefix/decoded verification, runtime reservation, UNIX path bounds and declaration validation. Those checks remain **NOT REACHED**. No complete environment manifest, A campaign, execution declaration, ledger reservation or owner execution permit was created. A process-to-service mapping is not a substitute for the frozen signed PID/start-time/executable admission predicate.

Approved contract `{result['approved_contract_commit']}`; executable `{result['approved_executable_commit']}`; tree `{result['approved_repository_tree']}`; S `{result['candidate_S']}`; T `{result['candidate_T']}`; assembly `{result['assembly_digest']}`. Droplet {result['droplet_id']} / {result['size_slug']}, host `{result['hostname']}`, boot `{result['boot_id']}`. PR #118 remains open, draft and unmerged. No harness, contract, candidate, runtime or host-resource configuration changed.

Every published file is listed with exact bytes and SHA-256 in `MANIFEST.json`. Original evidence remains on the executor and in bounded GitHub Actions artifacts. Only evidence and collection-source receipts are included in this publication tree.

Stage E remains RED. Stage F remains NOT STARTED. **A processes started: 0; A slots consumed: 0; source frames released: 0.** No quiescence was performed.

STOP FOR OWNER. A separate owner-authorized runtime correction and a completely fresh preflight are required before any A authorization can be considered.
'''
(DEST/'README.md').write_text(text)
rows=[dict(path=p.relative_to(DEST).as_posix(),bytes=p.stat().st_size,sha256=SHA(p)) for p in sorted(DEST.rglob('*')) if p.is_file()]
save('MANIFEST.json',dict(version='stage-e-native-v3-A-preflight-closure-evidence',artifacts=rows,paper_only=True,execution_authorized=False,actual_slots_reserved=False,A_slots_consumed=0,source_frames_released=0))
print(json.dumps(dict(files=len(rows)+1,bytes=sum(r['bytes'] for r in rows),first_blocker=result['first_exact_unresolved_blocker'],current_process_count=len(map_current['complete_mapping']),current_unresolved_mapping=map_current['unresolved_owner_or_source_bindings'],post_signature_unresolved_mapping=map_post['unresolved_owner_or_source_bindings'],result_sha256=SHA(DEST/'RESULT.json'),manifest_sha256=SHA(DEST/'MANIFEST.json')),indent=2))
