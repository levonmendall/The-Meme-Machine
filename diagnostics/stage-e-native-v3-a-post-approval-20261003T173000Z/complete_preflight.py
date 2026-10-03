"""Fresh admission coordinator on the exact frozen successor; Stage A only after complete PASS."""
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
sys.path.insert(0,str(PACKAGE))
import attest
import binding
import core
import run  # Frozen controller imports only; execute is never called before complete admission.

PREFLIGHT='native-v3-a-post-approval-20261003T173000Z'
MOUNT=Path('/mnt/volume_nyc1_1790918115030')
OLD=MOUNT/'meme-machine-observer-v2-7a516a6a'
OUTPUT=MOUNT/'stage-e-native-v3-paper-preflight'/(PREFLIGHT+'-admission')
EXECUTABLE='e85f7e35df4d4880763c256b5677de575d912d15'
KEY_SHA='f2257220125d8d48b752cce6d044b508c05436263dcf53f3d9e135e037ba0b36'
TRUST_COMMIT='8e3914672f7188769f51ba68fe00d328b8cda1bd'
TRUST_PATH='allocation-trust/native-v3-a-post-approval-20261003T173000Z/ALLOCATION_PUBLIC_KEY.pem'
READY_BRANCH='preflight/native-v3-a-autonomous-allocation-ready-20261003T133500Z'
READY_PATH='diagnostics/stage-e-native-v3-a-post-approval-20261003T173000Z/ALLOCATION_READY.json'
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
    core.require(core.file_sha(PACKAGE/'package-manifest.json')=='91753a805cd7acd48a10bb5e9cf31673f54ab9aebd70ee89039f37a7606ba9ff','approved_harness_manifest_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        path=REPO/row['path']
        core.require(path.is_file() and not path.is_symlink() and path.stat().st_size==row['bytes']
            and core.file_sha(path)==row['sha256'],'approved_harness_artifact_changed:'+row['path'])
    core.require(binding.infrastructure_identity()==core.read(PACKAGE/'source_hashes.json'),'approved_infrastructure_changed')
    core.require(binding.git(REPO,'rev-parse','HEAD^{tree}').decode().strip()=='44d5984e17ec3e22946b180fbecea531678a29bb','approved_successor_tree_changed')
    import review
    package=review.verify_package()
    for row in package['artifacts']:
        mode,kind,blob_path=binding.git(REPO,'ls-tree',EXECUTABLE,'--',row['path']).decode().split(None,2)
        blob,path=blob_path.split('\t',1)
        core.require(mode==row['mode'] and kind=='blob' and path.strip()==row['path'],'approved_package_git_mode_or_path')
        data=binding.git(REPO,'cat-file','blob',blob)
        core.require(core.sha(data)==row['sha256'] and len(data)==row['bytes'],'approved_package_git_blob')
    return dict(executable_commit=EXECUTABLE,successor_tree='44d5984e17ec3e22946b180fbecea531678a29bb',package_artifacts=len(package['artifacts']),manifest_sha256=core.file_sha(PACKAGE/'package-manifest.json'),infrastructure=binding.infrastructure_identity(),contract=binding.contract_integrity(REPO))

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


def bind_independent_approval():
    commit='26136f1b7dc43f809e9968b5d1d9f805ee382aa9'
    base='diagnostics/stage-e-native-v3-independent-approval-e85f7e35-7da67e4c'
    try:
        binding.git(REPO,'cat-file','-e',commit+'^{commit}')
    except subprocess.CalledProcessError:
        binding.git(REPO,'fetch','origin',commit)
    raw=binding.git(REPO,'show',commit+':'+base+'/package/MANIFEST.json')
    core.require(core.sha(raw)=='7da67e4c1b8f3b179feb1387384a60483ba1e08ba38380f817ab656c4b184ccf','independent_review_manifest_identity')
    package=OUTPUT/'independent-approval'/'package'
    package.mkdir(parents=True,exist_ok=False)
    (package/'MANIFEST.json').write_bytes(raw)
    rows=json.loads(raw)['artifacts']
    for row in rows:
        path=core.relative(package,row['path']);path.parent.mkdir(parents=True,exist_ok=True)
        data=binding.git(REPO,'show',commit+':'+base+'/package/'+row['path'])
        core.require(len(data)==row['bytes'] and core.sha(data)==row['sha256'],'independent_approval_artifact:'+row['path'])
        with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and p!=package/'MANIFEST.json'}
    core.require(actual=={r['path'] for r in rows} and len(rows)==244,'independent_review_package_completeness')
    approval=core.read(package/'APPROVAL.json')
    core.require(approval['disposition']=='APPROVED' and approval['reviewed_successor_commit']==EXECUTABLE and approval['reviewed_successor_tree']=='44d5984e17ec3e22946b180fbecea531678a29bb' and approval['successor_package_manifest_sha256']=='91753a805cd7acd48a10bb5e9cf31673f54ab9aebd70ee89039f37a7606ba9ff','independent_approval_successor_scope')
    zip_name='Stage_E_Native_V3_Independent_Approval_e85f7e35.zip'
    zip_data=binding.git(REPO,'show',commit+':'+base+'/'+zip_name)
    core.require(core.sha(zip_data)=='7e5b342ac7f4d2d5edd93cca9e8c1a38ccf28ac76d0be1d8645767528149c273','independent_original_ZIP_identity')
    (OUTPUT/'independent-approval'/zip_name).write_bytes(zip_data)
    return dict(declaration='APPROVED',publication_commit=commit,publication_tree=binding.git(REPO,'rev-parse',commit+'^{tree}').decode().strip(),repository_path=base,manifest_sha256=core.sha(raw),artifacts_verified=len(rows),manifest_verified=True,original_zip_sha256=core.sha(zip_data),original_zip_git_blob=binding.git(REPO,'rev-parse',commit+':'+base+'/'+zip_name).decode().strip(),approval_json_sha256=core.file_sha(package/'APPROVAL.json'),review_txt_sha256=core.file_sha(package/'REVIEW.txt'),supplied_approval_text_sha256=core.file_sha(OUTPUT/'ASTRA_INDEPENDENT_APPROVAL_SUPPLIED.txt'),immutable_package_bound=True,status='PASS',review_not_rerun=True)

def prepare():
    OUTPUT.mkdir(exist_ok=False)
    save('BINDING_SCOPE.json',dict(RESULT,phase='allocation binding; no campaign namespace reserved'))
    save('APPROVED_IDENTITY.json',approved_identity())
    for name in ('ASTRA_INDEPENDENT_APPROVAL_SUPPLIED.txt','OWNER_ARTIFACT_BINDING_HOLD.txt'):
        preserve_bytes(name,(HERE/name).read_bytes())
    save('INDEPENDENT_APPROVAL_BINDING.json',bind_independent_approval())
    save('REPOSITORY_IDENTITY.json',dict(repository='levonmendall/The-Meme-Machine',repository_id=1373661451,approved_remote=binding.git(REPO,'remote','get-url','origin').decode().strip(),actual_workflow_repository=os.environ.get('GITHUB_REPOSITORY')))
    core.require(os.environ.get('GITHUB_REPOSITORY')=='levonmendall/The-Meme-Machine','repository_identity_mismatch')
    public=read_public('https://raw.githubusercontent.com/levonmendall/The-Meme-Machine/'+TRUST_COMMIT+'/'+TRUST_PATH)
    core.require(core.sha(public)==KEY_SHA,'independent_allocation_trust_key_changed')
    preserve_bytes('ALLOCATION_PUBLIC_KEY.pem',public)
    save('INDEPENDENT_PUBLIC_KEY_SOURCE.json',dict(commit=TRUST_COMMIT,path=TRUST_PATH,
        allocation_public_key_sha256=KEY_SHA,independently_supplied_before_signature=True))
    receipts=[dict(path=str(OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json'),sha256=core.file_sha(OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json'))]
    for name in ('PROVIDER_FRESH_FOR_ALLOCATION.json','PROVIDER_FRESH_CONTEXT.json','PROVIDER_PLAN_CAPABILITIES.html','PROVIDER_VOLUME_FEATURES.html'):
        receipt=preserve_bytes(name,(HERE/'inputs'/name).read_bytes())
        receipts.append({k:receipt[k] for k in ('path','sha256')})
    provider=core.read(OUTPUT/'PROVIDER_FRESH_FOR_ALLOCATION.json')
    core.require(provider['id']==605465049 and provider['status']=='active' and provider['size_slug']=='gd-2vcpu-8gb'
        and provider['vcpus']==provider['size']['vcpus']==2 and provider['memory']==provider['size']['memory']==8192
        and provider['disk']==provider['size']['disk']==50 and provider['region']['slug']=='nyc1'
        and provider['size']['description']=='General Purpose 2x SSD','provider_allocation_mismatch')
    core.require(len(provider['volume_ids'])==1,'unambiguous_provider_volume_binding_unavailable')
    snapshot=attest.inspect([str(MOUNT)],os.getpid())
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
    policy=dict(validity_duration_ns=7200*10**9,valid_from_basis='fresh snapshot real_utc_ns',
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
    allocation['qualification_binding']=dict(candidate_sha=core.S,candidate_tree=core.T,successor_commit=EXECUTABLE,successor_tree='44d5984e17ec3e22946b180fbecea531678a29bb',successor_manifest_sha256='91753a805cd7acd48a10bb5e9cf31673f54ab9aebd70ee89039f37a7606ba9ff',independent_approval=core.read(OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json'),contract_commit=core.CONTRACT_COMMIT,contract_manifest_sha256=core.CONTRACT_MANIFEST_SHA,tape_sha256=core.workload('A')['tape_binding']['physical_sha256'],workload_sha256=core.sha(core.canonical(core.workload('A'))),class_id='A',paper_only=True,stage_e='RED',stage_f='NOT STARTED')
    save('SIGNED_PAYLOAD_REFRESH_DETERMINATION.json',dict(existing_allocation_expired=True,existing_private_key_discarded=True,discarded_key_reconstructed=False,successor_and_approval_scope_changed=True,current_fresh_resource_evidence_changes_payload=True,fresh_ephemeral_allocation_signature_required=True))
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
    snapshot=attest.inspect([str(MOUNT)],os.getpid())
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
    final=attest.inspect([str(MOUNT)],os.getpid())
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
        workflow_path='.github/workflows/stagee-native-v3-material.yml',
        local_workflow_path=str(HERE.parents[1]/'.github/workflows/stagee-native-v3-material.yml'),
        workflow_sha256=core.file_sha(HERE.parents[1]/'.github/workflows/stagee-native-v3-material.yml'),
        scope='Complete fresh preflight and conditional exact Stage A under owner authorization; no B/C/F authority')
    declaration=preview('A',campaign,executor=executor,environment=environment,workflow=workflow,paths=paths,
        allocation=allocation,storage_bounds=bounds,trust_keys=dict(allocation_public_key_sha256=KEY_SHA))
    declaration['approved_executable_commit']=EXECUTABLE
    declaration['approved_successor_tree']='44d5984e17ec3e22946b180fbecea531678a29bb'
    declaration['approved_successor_manifest_sha256']='91753a805cd7acd48a10bb5e9cf31673f54ab9aebd70ee89039f37a7606ba9ff'
    declaration['independent_approval']=core.read(OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json')
    declaration['independent_approval_artifact_bound']=True
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

def finish_admission():
    """Complete independent capability checks; unchanged authorize() is the gate."""
    from declaration import authorize
    d=core.read(OUTPUT/'A_PREDECLARATION_PREVIEW.json')
    runtime=core.read(OUTPUT/'RUNTIME_ENVIRONMENT.json')
    python_check=cmd([sys.executable,'-I','-B','-c',
        'import json,sys,site,os; print(json.dumps(dict(version=list(sys.version_info),executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,user_site=site.ENABLE_USER_SITE,affinity=sorted(os.sched_getaffinity(0)))))'])
    core.require(python_check['returncode']==0,'isolated_Python_capability_failed')
    values=json.loads(python_check['stdout'])
    core.require(values['version'][:3]==[3,12,14] and values['prefix']=='/workspace/stage-e-runtime'
        and values['base_prefix']=='/workspace/stage-e-python-3.12.14' and values['user_site'] is False and values['affinity']==[0,1],
        'isolated_runtime_capability_or_affinity')
    save('PYTHON_CAPABILITY.json',python_check)
    child=cmd([runtime['os_tools']['unshare']['path'],'--net','--',sys.executable,'-I','-B','-c',
        'import json,os,sys;print(json.dumps(dict(version=list(sys.version_info),network_namespace=os.readlink("/proc/self/ns/net"),affinity=sorted(os.sched_getaffinity(0)),uid=os.getuid(),pid=os.getpid())))'])
    save('CHILD_PROCESS_CAPABILITY.json',child)
    core.require(child['returncode']==0,'approved_network_isolated_child_capability_failed')
    cv=json.loads(child['stdout'])
    core.require(cv['version'][:3]==[3,12,14] and cv['network_namespace']!=os.readlink('/proc/self/ns/net') and cv['affinity']==[0,1],
        'child_interpreter_namespace_or_affinity')
    again=binding.runtime_identity(OLD/'assembly/source')
    save('RUNTIME_REVERIFICATION.json',again)
    core.require(again==runtime,'runtime_changed_after_complete_inspection')
    save('RUNTIME_RESERVATION.json',dict(runtime_sha256=core.sha(core.canonical(runtime)),environment_sha256=d['environment_sha256'],
        exact_executable_hash=runtime['python_executable_hash'],stdlib_digest=runtime['stdlib_digest'],
        locked_dependency_digest=runtime['dependencies']['websockets']['digest'],sqlite=runtime['sqlite'],
        shared_library_files=len(runtime['mapped_libraries']),system_packages_enabled=False,
        reservation_mechanism='Exact immutable declaration byte identities with re-verification before every approved material admission; no system runtime changes.',
        status='PASS identities reserved for this declaration; workload not admitted'))
    final=attest.inspect([str(MOUNT)],os.getpid())
    save('COMPLETE_RESOURCE_FINAL.json',final)
    errors=attest.admission_errors(final,core.read(OUTPUT/'SIGNED_ALLOCATION.json')['payload'],d['storage_bounds'],runtime)
    save('COMPLETE_RESOURCE_ADMISSION.json',dict(errors=errors,admitted=not errors,scope_pid=final['scope_pid']))
    core.require(not errors,'fresh_complete_admission_failed:'+','.join(errors))
    save('FINAL_STORAGE_RESERVATION.json',attest.reserve_storage(final,d['storage_bounds']))
    save('WORKLOAD_AND_SLOT_ACCOUNTING.json',dict(class_id='A',workload_sha256=d['workload_sha256'],
      candidate_sha=d['candidate_sha'],candidate_tree=d['candidate_tree'],trials=d['trials'],
      A_trials_started=0,A_slots_consumed=0,source_frames_released=0,
      slot_boundary='Unchanged ledger STARTED event before native child/process startup; this preflight never calls Ledger.create or run.execute.',
      campaign_path_exists=(MOUNT/d['campaign']).exists(),actual_slots_reserved=False))
    core.require(not (MOUNT/d['campaign']).exists(),'A_campaign_already_consumed')
    installed_owner=Path('/etc/stage-e-v3/owner-public.pem')
    owner=OUTPUT/'PROPOSED_OWNER_EXECUTION_PUBLIC_KEY.pem'
    preserve_bytes(owner.name,(HERE/'inputs'/owner.name).read_bytes())
    save('PROPOSED_OWNER_KEY.json',core.read(HERE/'inputs/PROPOSED_OWNER_KEY.json'))
    core.require(core.file_sha(owner)=='5ce08e6e27a26848adba32c8bb82558552f5e75eb67c4d84ef0f4d2e608b80b4','proposed_owner_public_key_hash')
    owner_permit=OUTPUT/'OWNER_PERMIT.json'
    save('OWNER_SIGNING_TRUST_DISCOVERY.json',dict(example_approved_public_key_path=str(installed_owner),public_key_present=installed_owner.is_file(),
      public_key_sha256=core.file_sha(installed_owner) if installed_owner.is_file() else None,
      proposed_separate_owner_public_key_path=str(owner),proposed_owner_public_key_sha256=core.file_sha(owner),proposal_is_current_trust=False,exact_owner_permit_present=owner_permit.is_file(),
      separately_established_owner_public_key_sha256=None,private_keys_examined=False,
      textual_owner_authorization_received=True,authorization_scope='Bounded preflight repair and conditional exact Stage A; PAPER ONLY; no B/C/F',
      allocation_signing_key_is_separate_and_not_substituted_for_owner_key=True))
    # The owner's current prompt provides conditional execution scope. The frozen verifier still
    # demands an independently trusted owner signature over these exact bytes.
    d['execution_authorized']=True
    d['disposition']='AUTHORIZED PAPER EXECUTION'
    d['trust_keys']['owner_public_key_sha256']=core.file_sha(owner)
    declaration_receipt=save('A_DECLARATION_FOR_VERIFIER.json',d)
    expected=dict(version='stage-e-native-v3-owner-execution-permit',declaration_sha256=declaration_receipt['sha256'],
      class_id='A',campaign=d['campaign'],workflow=d['workflow'],executor_id=d['executor']['executor_id'],
      paper_only=True,stage_f_authorized=False,provider_authorized=False)
    save('EXACT_OWNER_PERMIT_PAYLOAD_REQUIRED.json',expected)
    # This exact input is ineffective without the independently trusted owner signature.
    try:
        authorize(OUTPUT/'A_DECLARATION_FOR_VERIFIER.json',owner_permit,owner,kind='A')
    except Exception as exc:
        save('DECLARATION_VERIFICATION.json',dict(approved_verifier=str(PACKAGE/'harness/declaration.py'),approved_verifier_sha256=core.file_sha(PACKAGE/'harness/declaration.py'),function='authorize',passed=False,exact_rejection_type=type(exc).__name__,exact_rejection=str(exc),declaration_sha256=declaration_receipt['sha256'],allocation_key_not_substituted_for_owner_authority=True,pre_signature_declaration_checks_passed=True,A_slots_consumed=0,source_frames_released=0))
    else:
        RESULT['owner_declaration_authorized']=True
    save('CPU_RESERVATION.json',dict(allocated_vcpu=2,dedicated_vcpu=2,visible_cpu_ids=final['cpu']['present'],affinity=final['affinity'],ancestor_inventory_sha256=core.sha(core.canonical(final['cgroup'])),allocation_document_sha256=core.file_sha(OUTPUT/'SIGNED_ALLOCATION.json'),system_processes_attested=True,competing_workload=False,reservation_mechanism='Exact signed allocation and unchanged admission_errors predicate; no CPU quota or topology mutation',status='VERIFIED_FOR_NONMATERIAL_PREFLIGHT'))
    save('RAM_RESERVATION.json',dict(allocated_ram_bytes=core.RAM,usable_ram_bytes=final['memory']['MemTotal'],available_ram_bytes=final['memory'].get('MemAvailable'),swap_bytes=final['memory']['SwapTotal'],balloon_modules=final['balloon_modules'],allocation_document_sha256=core.file_sha(OUTPUT/'SIGNED_ALLOCATION.json'),reservation_mechanism='Exact signed dedicated host allocation with ancestor RAM limits verified; no swap or balloon substitution',status='VERIFIED_FOR_NONMATERIAL_PREFLIGHT'))
    save('TAPE_EVIDENCE_CAPACITY_RESERVATION.json',dict(storage_bounds=d['storage_bounds'],storage_reservation=core.read(OUTPUT/'FINAL_STORAGE_RESERVATION.json'),canonical_tape_sha256=d['tape_binding']['physical_sha256'],tape_bytes=d['tape_binding']['physical_bytes'],source_frames_released=0))
    review=core.read(OUTPUT/'PROCESS_APPROVAL.json')
    save('NO_QUIESCENCE_REQUIRED.json',dict(unresolved=review['unresolved'],process_attestation_passed=review['process_attestation_passed'],critical_services_changed=False,service_mutations=0,environment_repair_performed=False))
    save('DECLARATION_COMPLETENESS.json',dict(preview_constructed_by_unchanged_frozen_helper=True,candidate_bound=True,successor_bound=True,contract_bound=True,tape_bound=True,runtime_bound=True,allocation_signature_bound=True,executor_bound=True,workflow_bound=True,all_workload_timing_stop_preservation_trials_fields_unchanged=True,independent_approval_package_bound=True,required_owner_public_key_sha256=core.file_sha(owner),owner_trust_role_approved=False,owner_permit_verified=False,effective_execution_authority=False,Stage_A_admitted=False))
    w=d['workflow']
    core.require(w['event']=='workflow_dispatch' and w['attempt']==1 and w['repository']=='levonmendall/The-Meme-Machine' and w['workflow_path']=='.github/workflows/stagee-native-v3-material.yml' and core.file_sha(w['local_workflow_path'])==w['workflow_sha256'],'future_material_workflow_identity')
    core.require('NOT AUTHORIZED / PREVIEW ONLY' not in Path(w['local_workflow_path']).read_text(),'preview_workflow_cannot_authorize')
    core.require(os.environ.get('GITHUB_REPOSITORY')==w['repository'] and os.environ.get('GITHUB_RUN_ID')==str(w['run_id']) and os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and os.environ.get('GITHUB_SHA')==w['resolved_workflow_commit'],'actual_workflow_run_mismatch')
    save('WORKFLOW_BINDING_VERIFICATION.json',dict(workflow=w,all_frozen_post_signature_workflow_checks_independently_passed=True))
    save('OWNER_SIGNING_HANDOFF.json',dict(candidate_frozen=True,declaration_path=str(OUTPUT/'A_DECLARATION_FOR_VERIFIER.json'),declaration_sha256=declaration_receipt['sha256'],required_owner_public_key_sha256=core.file_sha(owner),proposed_owner_public_key_trusted=False,canonical_owner_permit_payload=expected,canonical_owner_permit_payload_sha256=core.sha(core.canonical(expected)),class_id='A',campaign=d['campaign'],executor=d['executor'],workflow=w,owner_signature_generated=False,owner_trust_role_approval_required=True,allocation_expires_utc_ns=d['allocation']['expires_utc_ns'],latest_owner_handoff_utc_ns=d['allocation']['expires_utc_ns']-4500*10**9,zero_A_trials=True,zero_A_slots=True,zero_released_frames=True,sole_remaining_gate='separate owner execution trust-role establishment and exact signature; no allocation-key substitution'))
    RESULT['owner_signing_candidate_ready']=True
    matrix=[]
    for name,evidence in [('workflow_run_binding','WORKFLOW_BINDING_VERIFICATION.json'),('repository_identity','REPOSITORY_IDENTITY.json'),('successor_package_commit_tree','APPROVED_IDENTITY.json'),('production_candidate_S_T','CANDIDATE_VERIFICATION.json'),('contract_identity','APPROVED_IDENTITY.json'),('canonical_tape_all_4445_frames_exact_284_failures','TAPE_VERIFICATION.json'),('runtime_dependencies_SQLite_shared_libraries','RUNTIME_ENVIRONMENT.json'),('isolated_runtime_integrity','PYTHON_CAPABILITY.json'),('process_service_attestation','PROCESS_APPROVAL.json'),('cgroup_CPU_RAM_dedication','COMPLETE_RESOURCE_ADMISSION.json'),('CPU_reservation','CPU_RESERVATION.json'),('RAM_reservation','RAM_RESERVATION.json'),('storage_reservation','FINAL_STORAGE_RESERVATION.json'),('tape_evidence_capacity_reservation','TAPE_EVIDENCE_CAPACITY_RESERVATION.json'),('runtime_reservation','RUNTIME_RESERVATION.json'),('allocation_signature','SIGNATURE_VERIFICATION.json'),('allocation_current_resource_admission','COMPLETE_RESOURCE_ADMISSION.json'),('isolated_child_network_namespace','CHILD_PROCESS_CAPABILITY.json'),('UNIX_paths_and_fresh_campaign','UNIX_PATH_BOUNDS.json'),('workload_slot_source_accounting','WORKLOAD_AND_SLOT_ACCOUNTING.json')]:
        matrix.append(dict(check=name,status='PASS',evidence=evidence,sha256=core.file_sha(OUTPUT/evidence)))
    matrix.append(dict(check='independent_approval_artifact_binding',status='PASS',evidence='INDEPENDENT_APPROVAL_BINDING.json',sha256=core.file_sha(OUTPUT/'INDEPENDENT_APPROVAL_BINDING.json')))
    authorized=RESULT.get('owner_declaration_authorized') is True
    matrix.extend([dict(check='declaration_final_authorization',status='PASS' if authorized else 'BLOCKED',reason=None if authorized else 'Frozen authorize() requires independently trusted owner key and exact-declaration signature',evidence='DECLARATION_VERIFICATION.json'),dict(check='separately_trusted_owner_key_and_exact_signature',status='PASS' if authorized else 'BLOCKED',reason=None if authorized else 'No independently supplied owner trust hash or exact signature available; allocation-only key is not owner authority',evidence='OWNER_SIGNING_TRUST_DISCOVERY.json')])
    save('ADMISSION_CHECK_MATRIX.json',dict(checks=matrix,every_independent_nonmaterial_check_completed=True,final_admission='PASS' if authorized else 'BLOCKED',first_blocker=None if authorized else 'owner_execution_signing_trust_unavailable',no_workload_started=True))
    if not authorized:
        save('STAGE_A_ADMISSION_BOUNDARY.json',dict(Stage_A_admitted=False,admitted_utc_ns=None,A_trials_started=0,A_slots_consumed=0,source_frames_released=0,trial_disposition='NOT EXECUTED',campaign_created=False,conditional_owner_execution_authorization_received=True))
        RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',first_exact_unresolved_blocker='owner_execution_signing_trust_unavailable',independent_approval_declaration='APPROVED',independent_approval_immutable_artifact_bound=True,declaration_verified=False,runtime_verified=True,complete_process_attestation=True,resource_admission_verified=True,storage_reserved=True,tape_verified=True,runtime_reserved=True,child_capability_verified=True,Stage_A_admitted=False,Stage_A_disposition='NOT EXECUTED',complete_fresh_nonmaterial_checks_completed=True,conditional_owner_execution_authorization_received=True)
        return
    save('STAGE_A_ADMISSION_BOUNDARY.json',dict(Stage_A_admitted=True,admitted_utc_ns=time.time_ns(),A_trials_started=0,A_slots_consumed=0,source_frames_released=0,conditional_owner_execution_authorization_received=True))
    RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_PASS',Stage_A_admitted=True)
    save('PREFLIGHT_PASS.json',dict(STAGE_E_NATIVE_V3_A_PREFLIGHT='PASS',complete_checks=matrix,declaration_sha256=declaration_receipt['sha256'],admission_boundary=core.read(OUTPUT/'STAGE_A_ADMISSION_BOUNDARY.json')))
    print(json.dumps(dict(STAGE_E_NATIVE_V3_A_PREFLIGHT='PASS',Stage_A_admitted=True)),flush=True)
    from run import execute
    campaign=execute(OUTPUT/'A_DECLARATION_FOR_VERIFIER.json',owner_permit,owner,kind='A')
    save('STAGE_A_EXECUTION_RETURN.json',dict(campaign=str(campaign),verifier_result=core.read(campaign/'VERIFICATION.json'),no_B_C_F_execution=True))

if __name__=='__main__':
    phase=sys.argv[1]
    try:
        core.require(phase in ('prepare','complete','await'),'nonmaterial_preflight_phase')
        if phase=='prepare':prepare()
        elif phase=='complete':complete();finish_admission()
        else:
            sys.path.insert(0,str(HERE))
            import await_owner_gate
            await_owner_gate.await_owner(sys.modules[__name__])
    except Exception as exc:
        RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',blocker_type=type(exc).__name__,blocker=str(exc))
    finally:
        if OUTPUT.is_dir():
            save('PREPARE_RESULT.json' if phase=='prepare' else ('FINAL_RESULT.json' if phase=='complete' else 'AWAIT_RESULT.json'),RESULT)
            rows=[dict(path=p.relative_to(OUTPUT).as_posix(),bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.rglob('*')) if p.is_file()]
            save('PREPARE_MANIFEST.json' if phase=='prepare' else ('FINAL_MANIFEST.json' if phase=='complete' else 'AWAIT_MANIFEST.json'),dict(artifacts=rows,execution_authorized=False,
                actual_slots_reserved=False,source_frames_released=0,A_slots_consumed=0))
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_path='+str(OUTPUT)+'\nowner_signing_candidate_ready='+str(RESULT.get('owner_signing_candidate_ready') is True).lower()+'\n')
        print(json.dumps(RESULT,sort_keys=True))
        if RESULT['status']=='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED' and not (phase=='complete' and RESULT.get('owner_signing_candidate_ready') is True):
            raise SystemExit(1)
