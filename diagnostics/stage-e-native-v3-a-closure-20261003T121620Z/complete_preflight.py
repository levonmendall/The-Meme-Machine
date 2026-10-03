"""Preflight-only coordinator. No execution permit, ledger, feeder or native workload."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
REPO=Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE=REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0,str(PACKAGE/'harness'))
import attest
import binding
import core

PREFLIGHT='native-v3-a-closure-20261003T121620Z'
MOUNT=Path('/mnt/volume_nyc1_1790918115030')
OLD=MOUNT/'meme-machine-observer-v2-7a516a6a'
OUTPUT=MOUNT/'stage-e-native-v3-paper-preflight'/(PREFLIGHT+'-signed')
EXECUTABLE='f480c6b4f7a8442fd148c7ed61bcc4447edaefca'
KEY_SHA='5504ae8cfe2f20fcb3245c327e76e6f376f5cd8da895c56ffab3b258ae0079a4'
TRUST_COMMIT='191437b6599d8b48c679a9e0e5af94ca1107a4aa'
TRUST_PATH='allocation-trust/native-v3-a-closure-20261003T121620Z/ALLOCATION_PUBLIC_KEY.pem'
READY_BRANCH='preflight/native-v3-a-signed-closure-20261003T121620Z'
READY_PATH='diagnostics/stage-e-native-v3-a-closure-20261003T121620Z/signed/ALLOCATION_READY.json'
RESULT=dict(preflight_id=PREFLIGHT,paper_only=True,stage_e='RED',stage_f='NOT STARTED',
    execution_authorized=False,actual_slots_reserved=False,source_frames_released=0,
    A_slots_consumed=0,A_trials_started=0,B_started=False,C_started=False,
    owner_execution_permit_created=False,approved_executable_commit=EXECUTABLE)

def save(name,value):
    data=core.canonical(value)+b'\n'
    path=OUTPUT/name
    with path.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    attest.fsync_dir(OUTPUT)
    return dict(path=str(path),sha256=core.sha(data),bytes=len(data))

def preserve_bytes(name,data):
    path=OUTPUT/name
    with path.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    attest.fsync_dir(OUTPUT)
    return dict(path=str(path),sha256=core.sha(data),bytes=len(data))

def read_public(url):
    with urllib.request.urlopen(url,timeout=20) as response:
        return response.read(8*1024**2)

def cmd(argv):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=30)
    return dict(argv=argv,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)

def approved_identity():
    core.require(socket.gethostname()=='ubuntu-gd-2vcpu-8gb-nyc1','executor_hostname_mismatch')
    core.require(os.environ.get('RUNNER_NAME')=='the meme machine' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','runner_or_attempt_mismatch')
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()==EXECUTABLE,'approved_executable_commit_changed')
    core.require(core.file_sha(PACKAGE/'package-manifest.json')=='d0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859','approved_harness_manifest_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        path=REPO/row['path']
        core.require(path.is_file() and not path.is_symlink() and path.stat().st_size==row['bytes']
            and core.file_sha(path)==row['sha256'],'approved_harness_artifact_changed:'+row['path'])
    core.require(binding.infrastructure_identity()==core.read(PACKAGE/'source_hashes.json'),'approved_infrastructure_changed')
    return dict(executable_commit=EXECUTABLE,infrastructure=binding.infrastructure_identity(),contract=binding.contract_integrity(REPO))

def host_checks(snapshot):
    core.require(not snapshot['inspection_errors'],'incomplete_resource_inspection:'+','.join(snapshot['inspection_errors']))
    ids=snapshot['cpu']['present']
    core.require(len(ids)==2 and snapshot['cpu']['possible']==snapshot['cpu']['online']==snapshot['affinity']==ids,
        'executor_allocation_larger_than_two_or_offline_CPUs')
    core.require(0<snapshot['memory']['MemTotal']<=core.RAM,'usable_RAM_allocation_binding')
    core.require(snapshot['memory']['SwapTotal']==0,'swap_is_not_RAM')
    core.require(snapshot['balloon_modules']==[],'ballooning')
    core.require(not attest.cgroup_completeness_errors(snapshot['cgroup']) and snapshot['cgroup']['complete'],
        'corrected_cgroup_inventory_incomplete')
    for row in snapshot['cgroup']['ancestors']:
        q,p=row.get('quota_us'),row.get('period_us')
        core.require(q is None or p and q>=2*p,'restrictive_ancestor_CPU_quota')
        for key in ('cpuset','cpuset_effective'):
            core.require(not row.get(key) or set(ids).issubset(attest.cpus(row[key])),'restrictive_ancestor_cpuset')
        for key in ('memory_max','memory_high','memsw_max'):
            core.require(row.get(key) is None or row[key]>=core.RAM,'restrictive_ancestor_'+key)

def process_approval(snapshot):
    spec=importlib.util.spec_from_file_location('fresh_process_binding',HERE/'fresh_process_binding.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.approve(snapshot,HERE,OUTPUT,save,attest,core)


def prepare():
    OUTPUT.mkdir(exist_ok=False)
    save('BINDING_SCOPE.json',dict(RESULT,phase='allocation binding; no campaign namespace reserved'))
    save('APPROVED_IDENTITY.json',approved_identity())
    public=read_public('https://raw.githubusercontent.com/levonmendall/The-Meme-Machine/'+TRUST_COMMIT+'/'+TRUST_PATH)
    core.require(core.sha(public)==KEY_SHA,'independent_allocation_trust_key_changed')
    preserve_bytes('ALLOCATION_PUBLIC_KEY.pem',public)
    save('INDEPENDENT_PUBLIC_KEY_SOURCE.json',dict(commit=TRUST_COMMIT,path=TRUST_PATH,
        allocation_public_key_sha256=KEY_SHA,independently_supplied_before_signature=True))
    receipts=[]
    for name in ('PROVIDER_FRESH_FOR_ALLOCATION.json','PROVIDER_FRESH_CONTEXT.json','PROVIDER_PLAN_CAPABILITIES.html','PROVIDER_VOLUME_FEATURES.html'):
        receipt=preserve_bytes(name,(HERE/'inputs'/name).read_bytes())
        receipts.append({k:receipt[k] for k in ('path','sha256')})
    provider=core.read(OUTPUT/'PROVIDER_FRESH_FOR_ALLOCATION.json')
    core.require(provider['id']==605465049 and provider['status']=='active' and provider['size_slug']=='gd-2vcpu-8gb'
        and provider['vcpus']==provider['size']['vcpus']==2 and provider['memory']==provider['size']['memory']==8192
        and provider['disk']==provider['size']['disk']==50 and provider['region']['slug']=='nyc1'
        and provider['size']['description']=='General Purpose 2x SSD','provider_allocation_mismatch')
    core.require(len(provider['volume_ids'])==1,'unambiguous_provider_volume_binding_unavailable')
    snapshot=attest.inspect([str(MOUNT)],os.getppid())
    snapshot_receipt=save('ALLOCATION_RESOURCE_SNAPSHOT.json',snapshot)
    host_checks(snapshot)
    observed=core.read(HERE/'inputs/RESOURCE_FINAL_R2.json')
    core.require(snapshot['boot_id']==observed['boot_id'] and snapshot['cpu']==observed['cpu'] and snapshot['memory']['MemTotal']==observed['memory']['MemTotal'],'host_envelope_changed_since_process_attestation')
    processes=process_approval(snapshot)
    spec=importlib.util.spec_from_file_location('nonmaterial_host_collector',HERE/'storage_capability.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    collector.OUTPUT=OUTPUT;collector.PREFLIGHT=PREFLIGHT+'-allocation-binding'
    collector.durability_capability()
    capability=core.read(OUTPUT/'STORAGE_CAPABILITY.json')
    raw=cmd(['lsblk','--json','--bytes','--output','NAME,PATH,SIZE,MODEL,TYPE,FSTYPE,UUID,MOUNTPOINTS'])
    device_receipt=save('DURABLE_BLOCK_DEVICE_RAW.json',raw)
    core.require(raw['returncode']==0,'block_device_inventory_unavailable')
    devices=json.loads(raw['stdout'])['blockdevices']
    volume=[r for r in devices if r['path']==snapshot['storage'][0]['source']]
    core.require(len(volume)==1 and volume[0]['model'].strip()=='Volume' and volume[0]['size']==50*1024**3
        and volume[0]['fstype']=='ext4' and str(MOUNT) in volume[0]['mountpoints'],'physical_durable_volume_identity_mismatch')
    for receipt in (snapshot_receipt,device_receipt):receipts.append({k:receipt[k] for k in ('path','sha256')})
    for name in ('PROCESS_APPROVAL.json','FRESH_PROCESS_DETAILS.json','FRESH_SYSTEMD_OWNERSHIP.json','FRESH_EXECUTABLE_PROVENANCE.json','FRESH_ACTIVITY_INITIAL.json','FRESH_ACTIVITY_FINAL.json','STORAGE_CAPABILITY.json'):
        receipts.append(dict(path=str(OUTPUT/name),sha256=core.file_sha(OUTPUT/name)))
    policy=dict(validity_duration_ns=3600*10**9,valid_from_basis='fresh snapshot real_utc_ns',
        storage_budget_policy='GiB-aligned third of current free bytes after frozen 12-GiB headroom for working evidence; twice that for simultaneous trial and campaign copies')
    save('ALLOCATION_BOUND_POLICY.json',policy)
    allocation=dict(allocation=dict(allocated_vcpu=provider['vcpus'],dedicated_vcpu=provider['size']['vcpus'],
        ram_bytes=provider['memory']*1024**2,visible_cpu_ids=snapshot['cpu']['present'],executor_kind='dedicated-vm',
        swap=snapshot['memory']['SwapTotal']!=0,ballooning=bool(snapshot['balloon_modules']),competing_workload=False),
        boot_id=snapshot['boot_id'],hostname=snapshot['hostname'],valid_from_utc_ns=snapshot['real_utc_ns'],
        expires_utc_ns=snapshot['real_utc_ns']+policy['validity_duration_ns'],usable_ram_bytes=snapshot['memory']['MemTotal'],
        ancestor_inventory_sha256=core.sha(core.canonical(snapshot['cgroup'])),allocation_evidence=receipts,
        durable_mounts=[dict(device=r['device'],mount=r['mount'],file_and_directory_fsync=capability['directory_fsync_returned']
            and all(f['fsync_returned'] for f in capability['files']),sqlite_WAL_locking=capability['journal_mode']=='wal'
            and capability['second_writer_excluded'],physical_durability=True,provider_volume_id=provider['volume_ids'][0])
            for r in snapshot['storage']],system_processes=processes)
    save('ALLOCATION_DRAFT.json',allocation)
    RESULT.update(status='ALLOCATION_DRAFT_REQUIRES_CONTROLLER_SIGNATURE',allocation_public_key_sha256=KEY_SHA,
        actual_hostname=snapshot['hostname'],actual_boot_id=snapshot['boot_id'],provider_evidence_sha256=core.file_sha(OUTPUT/'PROVIDER_FRESH_FOR_ALLOCATION.json'))

def storage_bounds(snapshot):
    gib=1024**3
    working=((min(r['free_bytes'] for r in snapshot['storage'])-core.HEADROOM)//(3*gib))*gib
    core.require(working>0,'insufficient_working_and_publication_budget')
    seen=set();retained=0;files=0
    tape=OLD/'tape/full-cohort-v2.tape'
    for folder,dirs,names in os.walk(MOUNT,followlinks=False):
        for name in names:
            path=Path(folder)/name
            if path==tape or path.is_symlink():continue
            stat=path.stat()
            identity=(stat.st_dev,stat.st_ino)
            if identity not in seen:
                seen.add(identity);retained+=stat.st_size;files+=1
    members=['run373-full-v3','run379-full-v3','run380-full-v3']+[x['id'] for x in core.workload('A')['cohort']]
    member_bytes={name:min(working,2*gib+int(next((r['encoded_prefix_bytes'] for r in core.workload('A')['tape_binding']['members'] if r['id']==name),0))) for name in members}
    bounds=dict(headroom_bytes=core.HEADROOM,immutable_tape_bytes=tape.stat().st_size,working_bytes=working,
        retained_evidence_bytes=retained,publication_copy_bytes=2*working,member_working_bytes=member_bytes,
        requirements=[dict(path=r['path'],minimum_total_bytes=core.HEADROOM+tape.stat().st_size+retained+3*working) for r in snapshot['storage']])
    save('STORAGE_BUDGET_DERIVATION.json',dict(bounds=bounds,free_bytes=[r['free_bytes'] for r in snapshot['storage']],
        actual_retained_regular_file_count=files,retained_hardlinks_counted_once=True,
        simultaneous_publication_copies=2,copy_budget_each=working,policy=core.read(OUTPUT/'ALLOCATION_BOUND_POLICY.json')))
    return bounds

def complete():
    core.require(core.read(OUTPUT/'PREPARE_RESULT.json')['status']=='ALLOCATION_DRAFT_REQUIRES_CONTROLLER_SIGNATURE','allocation_preparation_blocked')
    approved_identity()
    deadline=time.monotonic()+600
    while True:
        try:
            ready=json.loads(read_public('https://raw.githubusercontent.com/levonmendall/The-Meme-Machine/'+READY_BRANCH+'/'+READY_PATH+'?preflight='+str(time.time_ns())))
            break
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
            core.require(time.monotonic()<deadline,'fresh_controller_signed_allocation_unavailable')
            time.sleep(5)
    core.require(ready['allocation_public_key_sha256']==KEY_SHA,'independent_allocation_public_key_hash_changed')
    signed=read_public(ready['signed_allocation_url'])
    core.require(core.sha(signed)==ready['signed_allocation_sha256'],'signed_allocation_download_hash')
    preserve_bytes('SIGNED_ALLOCATION.json',signed)
    allocation=attest.signed_document(OUTPUT/'SIGNED_ALLOCATION.json',OUTPUT/'ALLOCATION_PUBLIC_KEY.pem',KEY_SHA)
    core.require(allocation==core.read(OUTPUT/'ALLOCATION_DRAFT.json'),'signed_allocation_not_exact_fresh_draft')
    save('SIGNATURE_VERIFICATION.json',dict(signed_allocation_sha256=core.sha(signed),allocation_public_key_sha256=KEY_SHA,
        canonical_payload_sha256=core.sha(core.canonical(allocation)),openssl_SHA256_verified=True,
        independent_public_key_source=core.read(OUTPUT/'INDEPENDENT_PUBLIC_KEY_SOURCE.json')))
    RESULT.update(signed_allocation_sha256=core.sha(signed),allocation_public_key_sha256=KEY_SHA,
        provider_evidence_sha256=core.file_sha(OUTPUT/'PROVIDER_FRESH_FOR_ALLOCATION.json'))
    snapshot=attest.inspect([str(MOUNT)],os.getppid())
    save('SIGNED_ADMISSION_RESOURCE_INITIAL.json',snapshot);host_checks(snapshot)
    spec=importlib.util.spec_from_file_location('post_signature_supplement',HERE/'collect_process_attestation_r2.py')
    supplemental=importlib.util.module_from_spec(spec);spec.loader.exec_module(supplemental)
    post_details=supplemental.process_details(snapshot)
    save('POST_SIGNATURE_PROCESS_DETAILS.json',post_details)
    save('POST_SIGNATURE_SYSTEMD_OWNERSHIP.json',supplemental.unit_evidence(post_details))
    save('POST_SIGNATURE_ACTIVITY.json',supplemental.cgroup_activity(post_details))
    # Fresh full runtime inspection uses the unchanged approved binding helper.
    runtime=binding.runtime_identity(OLD/'assembly/source')
    save('RUNTIME_ENVIRONMENT.json',runtime)
    environment=dict(runtime_dependency_identities=runtime,
        observed_constraints={key:snapshot[key] for key in ('boot_id','hostname','cpu','topology','affinity','cgroup')},
        allocated_resources=allocation['allocation'])
    RESULT['runtime_environment_sha256']=core.sha(core.canonical(environment))
    save('ENVIRONMENT_MANIFEST.json',environment)
    save('CANDIDATE_VERIFICATION.json',binding.candidate_integrity(OLD/'candidate-checkout'))
    assembly=binding.verify_assembly(OLD/'assembly')
    save('ASSEMBLY_VERIFICATION.json',dict(assembly_digest=assembly['assembly_digest'],
        assembly_manifest_sha256=core.file_sha(OLD/'assembly/assembly.json'),files_verified=len(assembly['files'])))
    bounds=storage_bounds(snapshot)
    errors=attest.admission_errors(snapshot,allocation,bounds,runtime)
    save('SIGNED_ALLOCATION_ADMISSION.json',dict(errors=errors,admitted=not errors,scope_pid=snapshot['scope_pid']))
    signed_tuples={(r['pid'],r['start_ticks'],r['executable_sha256']) for r in allocation['system_processes']}
    scope={snapshot['scope_pid']}
    while True:
        expanded=scope|{r['pid'] for r in snapshot['processes'] if r['ppid'] in scope}
        if expanded==scope:break
        scope=expanded
    unbound=[r for r in snapshot['processes'] if not r['kernel'] and r['pid'] not in scope and (r['pid'],r['start_ticks'],r['executable_sha256']) not in signed_tuples]
    save('SIGNED_UNBOUND_PROCESS_IDENTITIES.json',dict(unbound=unbound,signed_snapshot=str(OUTPUT/'ALLOCATION_RESOURCE_SNAPSHOT.json')))
    core.require(not errors,('competing_or_unattested_process:'+str(unbound[0]['pid'])+':'+str(unbound[0]['executable'])) if unbound and errors==['competing_or_unattested_process'] else 'production_envelope_admission_failed:'+','.join(errors))
    save('PREPARATION_STORAGE_RESERVE.json',attest.reserve_storage(snapshot,bounds))
    import tape
    tape_receipt=tape.validate_existing(OLD/'tape/full-cohort-v2.tape',OLD/'tape/FRAMES.json',kind='A')
    save('TAPE_VERIFICATION.json',tape_receipt)
    RESULT['tape']=tape_receipt
    final=attest.inspect([str(MOUNT)],os.getppid())
    save('SIGNED_ADMISSION_RESOURCE_FINAL.json',final)
    core.require(attest.constraint_identity(snapshot)==attest.constraint_identity(final),'resource_constraints_changed_during_remaining_preflight')
    errors=attest.admission_errors(final,allocation,bounds,runtime)
    save('FINAL_ADMISSION.json',dict(errors=errors,admitted=not errors))
    core.require(not errors,'final_production_envelope_admission_failed:'+','.join(errors))
    # Preview construction only. Ledger.create(), authorize(), run.execute(), all
    # native workload modules and any source feeder are never called or imported.
    from declaration import preview
    from ledger import fresh_campaign
    campaign=fresh_campaign('A')
    campaign_path=MOUNT/campaign
    core.require(not campaign_path.exists(),'fresh_A_campaign_namespace_already_exists')
    socket_rows=[dict(member_index=i,path=str(campaign_path/'t1'/('m'+str(i))/'d/db.sock'),
        path_bytes=len(os.fsencode(campaign_path/'t1'/('m'+str(i))/'d/db.sock'))) for i in range(1,8)]
    core.require(all(r['path_bytes']<108 for r in socket_rows),'unix_socket_path_length')
    save('UNIX_PATH_BOUNDS.json',dict(paths=socket_rows,maximum_path_bytes=max(r['path_bytes'] for r in socket_rows),limit_exclusive=108))
    cache=MOUNT/('c'+campaign[-12:])
    core.require(not cache.exists(),'existing_bytecode_cache')
    context={key:os.environ.get(key) for key in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME')}
    paths=dict(repository=str(REPO),candidate_checkout=str(OLD/'candidate-checkout'),assembly=str(OLD/'assembly'),
        tape=str(OLD/'tape/full-cohort-v2.tape'),frame_inventory=str(OLD/'tape/FRAMES.json'),
        allocation_document=str(OUTPUT/'SIGNED_ALLOCATION.json'),allocation_public_key=str(OUTPUT/'ALLOCATION_PUBLIC_KEY.pem'),
        storage_paths=[str(MOUNT)],campaign_registry=str(MOUNT),cache_path=str(cache),
        durable_publication_root=str(MOUNT/('p'+campaign[-12:])))
    executor=dict(executor_id='digitalocean-droplet-605465049',droplet_id=605465049,size_slug='gd-2vcpu-8gb',
        hostname=final['hostname'],boot_id=final['boot_id'],network_namespace=os.readlink('/proc/self/ns/net'),scope_pid=final['scope_pid'])
    workflow=dict(repository=context['GITHUB_REPOSITORY'],event=context['GITHUB_EVENT_NAME'],run_id=context['GITHUB_RUN_ID'],
        attempt=int(context['GITHUB_RUN_ATTEMPT']),resolved_workflow_commit=context['GITHUB_SHA'],
        workflow_path='.github/workflows/stagee-native-v3-a-signed-closure.yml',
        local_workflow_path=str(HERE.parents[1]/'.github/workflows/stagee-native-v3-a-signed-closure.yml'),
        workflow_sha256=core.file_sha(HERE.parents[1]/'.github/workflows/stagee-native-v3-a-signed-closure.yml'),
        scope='nonmaterial preflight only; owner execution permit and material workflow not created')
    declaration=preview('A',campaign,executor=executor,environment=environment,workflow=workflow,paths=paths,
        allocation=allocation,storage_bounds=bounds,trust_keys=dict(allocation_public_key_sha256=KEY_SHA))
    declaration['approved_executable_commit']=EXECUTABLE
    declaration['signed_allocation_document_sha256']=core.sha(signed)
    declaration['tape_verification']=tape_receipt
    declaration['member_identities']=[dict(sequence=i,member=name,trial_id=declaration['trials'][0]['trial_id']) for i,name in enumerate(bounds['member_working_bytes'],1)]
    declaration['allocation_public_key_source']=core.read(OUTPUT/'INDEPENDENT_PUBLIC_KEY_SOURCE.json')
    receipt=save('A_PREDECLARATION_PREVIEW.json',declaration)
    save('A_LEDGER_PREVIEW.json',dict(campaign=campaign,actual_slots_reserved=False,source_frames_released=0,
        A_slots_consumed=0,trials=[dict(row,status='UNUSED',started=False) for row in declaration['trials']],execution_authorized=False))
    RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_READY',campaign=campaign,
        declaration_sha256=receipt['sha256'],retained_executor_evidence_path=str(OUTPUT),
        environment_sha256=declaration['environment_sha256'],storage_bounds=bounds,CPU_RAM_admitted=True,
        corrected_cgroup_admitted=True,actual_hostname=final['hostname'],actual_boot_id=final['boot_id'])

if __name__=='__main__':
    phase=sys.argv[1]
    try:
        core.require(phase in ('prepare','complete'),'nonmaterial_preflight_phase')
        prepare() if phase=='prepare' else complete()
    except Exception as exc:
        RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',blocker_type=type(exc).__name__,blocker=str(exc))
    finally:
        if OUTPUT.is_dir():
            save('PREPARE_RESULT.json' if phase=='prepare' else 'FINAL_RESULT.json',RESULT)
            rows=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.iterdir()) if p.is_file()]
            save('PREPARE_MANIFEST.json' if phase=='prepare' else 'FINAL_MANIFEST.json',dict(artifacts=rows,execution_authorized=False,
                actual_slots_reserved=False,source_frames_released=0,A_slots_consumed=0))
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUTPUT)+'\n')
        print(json.dumps(RESULT,sort_keys=True))
        if RESULT['status']=='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED':
            raise SystemExit(1)
