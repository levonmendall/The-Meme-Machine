"""Read-only evidence supplement to the exact frozen resource inspector.
No process policy exemptions, resource mutations, or Stage-E workload invocation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
ID = 'native-v3-a-closure-20261003T121620Z'
APPROVED = 'f480c6b4f7a8442fd148c7ed61bcc4447edaefca'
MOUNT = Path('/mnt/volume_nyc1_1790918115030')
OLD = MOUNT/'meme-machine-observer-v2-7a516a6a'
OUTPUT = MOUNT/'stage-e-native-v3-paper-preflight'/ID
REPO = Path(os.environ['MM_APPROVED_REPOSITORY']).resolve()
PACKAGE = REPO/'diagnostics/stage-e-native-v3-executable-harness'
sys.path.insert(0, str(PACKAGE/'harness'))
import attest
import binding
import core

RESULT = dict(preflight_id=ID, paper_only=True, execution_authorized=False,
    actual_slots_reserved=False, source_frames_released=0, A_slots_consumed=0,
    A_trials_started=0, owner_execution_permit_created=False,
    resource_configuration_mutations=0, stage_e='RED', stage_f='NOT STARTED')

PROPERTIES = ('Id,Names,LoadState,ActiveState,SubState,MainPID,ControlPID,ControlGroup,'
    'FragmentPath,DropInPaths,Type,BusName,User,Group,DynamicUser,TriggeredBy,Triggers,'
    'Wants,Requires,Requisite,BindsTo,PartOf,After,Before,UnitFileState,UnitFilePreset,'
    'ActiveEnterTimestamp,ActiveEnterTimestampMonotonic,InactiveEnterTimestamp,'
    'InactiveEnterTimestampMonotonic,ExecMainStartTimestamp,ExecMainStartTimestampMonotonic,'
    'ExecMainExitTimestamp,ExecMainExitTimestampMonotonic,ExecMainPID,ExecMainCode,ExecMainStatus,'
    'Result,Restart,NRestarts,RemainAfterExit,TimeoutStartUSec,TimeoutStopUSec,RuntimeMaxUSec,'
    'WatchdogUSec,CPUAccounting,CPUUsageNSec,CPUQuotaPerSecUSec,CPUQuotaPeriodUSec,CPUWeight,'
    'AllowedCPUs,EffectiveCPUs,MemoryAccounting,MemoryCurrent,MemoryPeak,MemoryMax,MemoryHigh,'
    'MemorySwapMax,TasksCurrent,TasksMax,IOAccounting,IOReadBytes,IOWriteBytes,IOWeight,'
    'Nice,IOSchedulingClass,IOSchedulingPriority,OOMPolicy,OOMScoreAdjust,Slice,'
    'NextElapseUSecRealtime,NextElapseUSecMonotonic,LastTriggerUSec,TimersMonotonic,'
    'TimersCalendar,AccuracyUSec,RandomizedDelayUSec,Persistent,OnClockChange,OnTimezoneChange')
SAFE_DIRECTIVES = set(('Description Documentation Type BusName User Group DynamicUser PIDFile '
    'WantedBy RequiredBy Also Alias Wants Requires Requisite BindsTo PartOf After Before '
    'Restart RestartSec RemainAfterExit TimeoutStartSec TimeoutStopSec RuntimeMaxSec '
    'WatchdogSec CPUAccounting CPUQuota CPUQuotaPeriodSec CPUWeight AllowedCPUs '
    'MemoryAccounting MemoryMax MemoryHigh MemorySwapMax TasksMax IOAccounting IOWeight '
    'Nice IOSchedulingClass IOSchedulingPriority OOMPolicy OOMScoreAdjust Slice '
    'OnCalendar OnBootSec OnStartupSec OnUnitActiveSec OnUnitInactiveSec Unit Persistent '
    'AccuracySec RandomizedDelaySec ConditionPathExists ConditionVirtualization '
    'ConditionACPower RefuseManualStart RefuseManualStop StopWhenUnneeded '
    'ProtectSystem ProtectHome PrivateTmp NoNewPrivileges CapabilityBoundingSet '
    'RestrictAddressFamilies ReadWritePaths ReadOnlyPaths').split())
EXEC_DIRECTIVES = {'ExecStart','ExecStartPre','ExecStartPost','ExecStop','ExecStopPost','ExecReload','ExecCondition'}
CONFIG_KEYS = set(('IdleTimeout UpdateMotd EnumerateAllDevices IgnorePower IgnoreBattery '
    'DisabledPlugins DisabledDevices EnableTestDevices AllowEmulation HostBkc '
    'P2pPolicyOnlyTrusted P2pPolicy OnlyTrusted AllowUnsigned TestDevices '
    'Name SystemdService User').split())


def save(name, value):
    data = core.canonical(value)+b'\n'
    path = OUTPUT/name
    with path.open('xb') as target:
        target.write(data); target.flush(); os.fsync(target.fileno())
    attest.fsync_dir(OUTPUT)
    return dict(path=str(path), bytes=len(data), sha256=core.sha(data))


def command(argv, timeout=45):
    start = time.time_ns()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        stdout = p.stdout.decode('utf-8','replace')
        stderr = p.stderr.decode('utf-8','replace')
        # No command accepts secret-bearing inputs or requests environments/cmdlines.
        return dict(argv=argv, started_utc_ns=start, finished_utc_ns=time.time_ns(),
            returncode=p.returncode, stdout=stdout, stderr=stderr)
    except subprocess.TimeoutExpired:
        return dict(argv=argv, started_utc_ns=start, finished_utc_ns=time.time_ns(), error='TIMEOUT')


def read_state(path):
    try:
        raw = Path(path).read_bytes()
        return dict(state='PRESENT', raw=raw.decode('utf-8','replace'), bytes=len(raw), sha256=core.sha(raw))
    except FileNotFoundError:
        return dict(state='ABSENT')
    except OSError as exc:
        return dict(state='UNREADABLE', error=type(exc).__name__+':'+str(exc))


def file_configuration(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
        selected=[]; omitted=[]; section=''
        for line in raw.decode('utf-8','replace').splitlines():
            text=line.strip()
            if text.startswith('[') and text.endswith(']'):
                section=text; continue
            if not text or text.startswith(('#',';')) or '=' not in text:
                continue
            key,value=text.split('=',1)
            if key in SAFE_DIRECTIVES or key in CONFIG_KEYS:
                selected.append(dict(section=section,key=key,value=value))
            elif key in EXEC_DIRECTIVES or key == 'Exec':
                executable=value.lstrip('-+!:@').split()[0] if value.strip() else ''
                selected.append(dict(section=section,key=key,executable=executable,
                    full_directive_sha256=core.sha(text.encode())))
            else:
                omitted.append(dict(section=section,key=key,full_directive_sha256=core.sha(text.encode())))
        return dict(path=str(path), resolved_path=str(path.resolve()), bytes=len(raw),
            sha256=core.sha(raw), relevant_configuration=selected,
            other_directives_hashes=omitted, raw_private_configuration_published=False)
    except OSError as exc:
        return dict(path=str(path),error=type(exc).__name__+':'+str(exc))


def process_details(snapshot):
    results=[]
    for row in snapshot['processes']:
        folder=Path('/proc')/str(row['pid'])
        item=dict(pid=row['pid'],start_ticks=row['start_ticks'],kernel=row['kernel'],
            discovery_row=row, observed_utc_ns=time.time_ns())
        item['raw']={name:read_state(folder/name) for name in ('stat','status','comm','cgroup','io','limits','schedstat')}
        item['threads']={str(t['tid']):dict(cgroup=read_state(folder/'task'/str(t['tid'])/'cgroup'),
            status=read_state(folder/'task'/str(t['tid'])/'status')) for t in row['threads']}
        try:
            item['executable_link']=os.readlink(folder/'exe')
        except OSError as exc:
            item['executable_link_error']=type(exc).__name__
        item['namespaces']={}
        for name in ('cgroup','pid','mnt','user','net'):
            try: item['namespaces'][name]=os.readlink(folder/'ns'/name)
            except OSError as exc: item['namespaces'][name]=type(exc).__name__
        raw=item['raw']['cgroup'].get('raw','')
        units=[]
        for line in raw.splitlines():
            group=line.split(':',2)[-1]
            units.extend(part for part in group.split('/') if part.endswith(('.service','.scope')))
        item['membership_units']=units
        stat=item['raw']['stat'].get('raw','')
        if stat:
            fields=stat[stat.rindex(')')+2:].split()
            item['generation_matches_discovery']=int(fields[19])==row['start_ticks']
        results.append(item)
    return results


def cgroup_activity(details):
    groups={}
    for item in details:
        if item['kernel']: continue
        for thread in item['threads'].values():
            for line in thread['cgroup'].get('raw','').splitlines():
                hierarchy,controllers,group=line.split(':',2)
                if hierarchy != '0' or controllers: continue
                for ancestor in [Path(group),*Path(group).parents]:
                    groups[str(ancestor)]=None
    output={}
    for group in sorted(groups):
        folder=Path('/sys/fs/cgroup')/group.lstrip('/')
        output[group]={name:read_state(folder/name) for name in (
            'cgroup.procs','cgroup.threads','cgroup.events','cgroup.type','cpu.stat','cpu.max',
            'cpu.weight','cpuset.cpus','cpuset.cpus.effective','cpu.pressure','memory.current',
            'memory.peak','memory.max','memory.high','memory.swap.current','memory.swap.max',
            'memory.events','memory.pressure','io.stat','io.max','io.pressure','pids.current','pids.max')}
    return dict(observed_utc_ns=time.time_ns(), observed_monotonic_ns=time.monotonic_ns(),groups=output)


def packages(executables):
    results={}; package_names=set()
    for executable in sorted(executables):
        path=Path(executable)
        candidates=[str(path)]
        if str(path).startswith('/usr/lib/') or str(path).startswith('/usr/bin/') or str(path).startswith('/usr/sbin/'):
            candidates.append(str(path)[4:])
        queries=[command(['dpkg-query','--search',name]) for name in candidates]
        found=[]
        for query in queries:
            for line in query.get('stdout','').splitlines():
                if ': ' in line:
                    name,installed=line.rsplit(': ',1)
                    if installed in candidates:
                        for pkg in name.split(', '):
                            found.append(dict(package=pkg,installed_path=installed));package_names.add(pkg)
        result=dict(path=executable, sha256=core.file_sha(path), size_bytes=path.stat().st_size,
            mode=oct(path.stat().st_mode), uid=path.stat().st_uid,gid=path.stat().st_gid,
            package_search=queries, package_bindings=found)
        result['installed_manifest_verification']=[]
        for item in found:
            pkg=item['package']
            manifests=[Path('/var/lib/dpkg/info')/(pkg+'.md5sums')]
            if ':' in pkg: manifests.append(Path('/var/lib/dpkg/info')/(pkg.split(':')[0]+'.md5sums'))
            for manifest in manifests:
                if not manifest.is_file(): continue
                rows=[]
                for line in manifest.read_text().splitlines():
                    parts=line.split(None,1)
                    if len(parts)==2 and '/'+parts[1].lstrip('./') in candidates:
                        actual=hashlib.md5(path.read_bytes(),usedforsecurity=False).hexdigest()
                        rows.append(dict(installed_path=parts[1],expected_md5=parts[0],actual_md5=actual,
                            matches=parts[0]==actual))
                result['installed_manifest_verification'].append(dict(manifest_path=str(manifest),
                    manifest_sha256=core.file_sha(manifest),executable_entries=rows))
        results[executable]=result
    info=command(['dpkg-query','--show','--showformat=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\t${source:Package}\t${source:Version}\n',*sorted(package_names)])
    return dict(executables=results, installed_package_versions=info)


def unit_evidence(details):
    units=sorted({u for item in details for u in item['membership_units']} |
        {'fwupd.service','fwupd-refresh.service','fwupd-refresh.timer','dbus-org.freedesktop.fwupd.service'})
    raw=command(['systemctl','show','--no-pager','--property='+PROPERTIES,'--',*units])
    parsed={}
    for section in raw.get('stdout','').split('\n\n'):
        fields=dict(line.split('=',1) for line in section.splitlines() if '=' in line)
        if fields.get('Id'):parsed[fields['Id']]=fields
    configs={}
    for unit,fields in parsed.items():
        paths=[fields.get('FragmentPath','')]+fields.get('DropInPaths','').split()
        configs[unit]=[file_configuration(p) for p in paths if p]
    trigger_units=sorted({x for fields in parsed.values() for x in fields.get('TriggeredBy','').split()})
    trigger_raw=command(['systemctl','show','--no-pager','--property='+PROPERTIES,'--',*trigger_units]) if trigger_units else None
    journals={}
    # Unit journals are bounded and deliberately omit arbitrary MESSAGE text.
    for unit in units:
        cmd=command(['journalctl','--no-pager','--output=json','--lines=16','--since=-24 hours','--unit='+unit])
        entries=[]
        for line in cmd.get('stdout','').splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            keep={key:row[key] for key in ('__REALTIME_TIMESTAMP','__MONOTONIC_TIMESTAMP','_BOOT_ID','_PID',
                '_UID','_GID','_COMM','_EXE','_SYSTEMD_UNIT','_SYSTEMD_CGROUP','UNIT','JOB_TYPE',
                'JOB_RESULT','RESULT','MESSAGE_ID','SYSLOG_IDENTIFIER','PRIORITY') if key in row}
            message=row.get('MESSAGE','')
            if isinstance(message,str):
                keep['message_sha256']=core.sha(message.encode())
                # fwupd firmware activity messages are relevant; credentials are never retained.
                if 'fwupd' in unit and not re.search(r'(token|password|secret|credential|authorization|https?://\S+@)',message,re.I):
                    keep['activity_message']=message[:2048]
            entries.append(keep)
        journals[unit]=dict(argv=cmd['argv'],returncode=cmd.get('returncode'),stderr=cmd.get('stderr'),
            started_utc_ns=cmd['started_utc_ns'],finished_utc_ns=cmd['finished_utc_ns'],entries=entries)
    dbus=[]
    for folder in ('/usr/share/dbus-1/system-services','/etc/dbus-1/system-services'):
        if not Path(folder).is_dir():continue
        for p in sorted(Path(folder).glob('*fwupd*')):dbus.append(file_configuration(p))
    fwupd_config=[]
    for folder in ('/etc/fwupd','/usr/share/fwupd'):
        if not Path(folder).is_dir():continue
        for p in sorted(Path(folder).glob('*.conf')):fwupd_config.append(file_configuration(p))
    return dict(unit_show_raw=raw,units=parsed,unit_file_identities=configs,
        triggered_unit_show_raw=trigger_raw,journal_history=journals,
        dbus_activation_files=dbus,fwupd_configuration_files=fwupd_config,
        all_service_units=command(['systemctl','list-units','--all','--type=service','--no-legend','--no-pager']),
        timer_schedule=command(['systemctl','list-timers','--all','--no-pager']),
        dbus_activation_configuration_discovered_read_only=True)


def host_checks(snapshot):
    errors=list(snapshot['inspection_errors'])
    ids=snapshot['cpu']['present']
    if len(ids)!=2 or not snapshot['cpu']['possible']==snapshot['cpu']['online']==snapshot['affinity']==ids:
        errors.append('executor_allocation_larger_than_two_or_offline_CPUs')
    if not 0<snapshot['memory']['MemTotal']<=core.RAM:errors.append('usable_RAM_allocation_binding')
    if snapshot['memory']['SwapTotal']!=0:errors.append('swap_is_not_RAM')
    if snapshot['balloon_modules']:errors.append('ballooning')
    errors.extend(attest.cgroup_completeness_errors(snapshot['cgroup']))
    for row in snapshot['cgroup']['ancestors']:
        q,p=row.get('quota_us'),row.get('period_us')
        if q is not None and not (p and q>=2*p):errors.append('restrictive_ancestor_CPU_quota:'+row['path'])
        for name in ('cpuset','cpuset_effective'):
            if row.get(name) and not set(ids).issubset(attest.cpus(row[name])):errors.append('restrictive_ancestor_cpuset:'+row['path'])
        for name in ('memory_max','memory_high','memsw_max'):
            if row.get(name) is not None and row[name]<core.RAM:errors.append('restrictive_ancestor_'+name+':'+row['path'])
    return dict(errors=errors,passed=not errors,CPU_ids=ids,allocated_RAM_bytes=core.RAM,
        usable_RAM_bytes=snapshot['memory']['MemTotal'],corrected_cgroup_verified=attest.verified_cgroup_inventory(snapshot['cgroup']),
        ancestor_inventory_sha256=core.sha(core.canonical(snapshot['cgroup'])))


def main():
    OUTPUT.mkdir(exist_ok=False)
    save('SCOPE.json',RESULT)
    core.require(socket.gethostname()=='ubuntu-gd-2vcpu-8gb-nyc1','executor_hostname_mismatch')
    core.require(os.environ.get('RUNNER_NAME')=='the meme machine' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','runner_or_attempt_mismatch')
    core.require(binding.git(REPO,'rev-parse','HEAD').decode().strip()==APPROVED,'approved_executable_commit_changed')
    core.require(core.file_sha(PACKAGE/'package-manifest.json')=='d0047922f45cc85599c25705616152005ab598d65343cb4482e983f34ebd6859','approved_harness_manifest_changed')
    for row in core.read(PACKAGE/'package-manifest.json')['artifacts']:
        path=REPO/row['path']
        core.require(path.is_file() and not path.is_symlink() and path.stat().st_size==row['bytes'] and core.file_sha(path)==row['sha256'],'approved_artifact_changed:'+row['path'])
    identity=dict(executable_commit=APPROVED,repository_tree=binding.git(REPO,'rev-parse','HEAD^{tree}').decode().strip(),
        contract=binding.contract_integrity(REPO), infrastructure=binding.infrastructure_identity(),
        collector_sha256=core.file_sha(__file__),python=sys.executable,python_version=sys.version,
        workflow={k:os.environ.get(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_WORKFLOW_REF','RUNNER_NAME')})
    save('APPROVED_IDENTITY.json',identity)
    save('CANDIDATE_IDENTITY.json',binding.candidate_integrity(OLD/'candidate-checkout'))
    assembly=binding.verify_assembly(OLD/'assembly')
    save('ASSEMBLY_IDENTITY.json',dict(assembly_digest=assembly['assembly_digest'],manifest_sha256=core.file_sha(OLD/'assembly/assembly.json'),files_verified=len(assembly['files'])))
    registration=json.loads(Path('/opt/actions-runner/.runner').read_text(encoding='utf-8-sig'))
    save('RUNNER_REGISTRATION.json',{k:registration.get(k) for k in ('agentId','agentName','poolId','poolName','gitHubUrl','workFolder')})
    core.require(registration['agentId']==21,'actual_runner_registration_mismatch')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    metadata={}
    for name in ('id','hostname'):
        with opener.open('http://169.254.169.254/metadata/v1/'+name,timeout=5) as response:metadata[name]=response.read(4096).decode().strip()
    save('GUEST_PROVIDER_IDENTITY.json',metadata)
    core.require(metadata==dict(id='605465049',hostname=socket.gethostname()),'actual_droplet_mismatch')
    initial=attest.inspect([str(MOUNT)],os.getppid())
    save('RESOURCE_INITIAL.json',initial)
    save('RESOURCE_INITIAL_CHECKS.json',host_checks(initial))
    details=process_details(initial)
    save('PROCESS_INITIAL_DETAILS.json',details)
    save('ACTIVITY_INITIAL.json',cgroup_activity(details))
    units=unit_evidence(details)
    save('SYSTEMD_OWNERSHIP_ACTIVATION.json',units)
    save('EXECUTABLE_PACKAGE_PROVENANCE.json',packages({r['executable'] for r in initial['processes'] if not r['kernel']}))
    save('FWUPD_APT_PROVENANCE.json',command(['apt-cache','policy','fwupd']))
    source_files=[]
    for name in ('runsvc.sh','bin/RunnerService.js','bin/Runner.Listener.deps.json','bin/Runner.Worker.deps.json','bin/Runner.Listener.dll','bin/Runner.Worker.dll'):
        p=Path('/opt/actions-runner')/name
        if p.is_file():source_files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=core.file_sha(p),uid=p.stat().st_uid,gid=p.stat().st_gid))
    save('RUNNER_SOURCE_IDENTITIES.json',dict(files=source_files,registered_repository=registration.get('gitHubUrl'),agent_id=registration.get('agentId')))
    raw={p:read_state(p) for p in ('/proc/meminfo','/proc/cpuinfo','/proc/swaps','/proc/modules','/proc/stat','/proc/diskstats','/proc/loadavg','/etc/os-release')}
    save('RAW_HOST_SYSTEM.json',dict(files=raw,ps=command(['ps','-eo','pid,ppid,uid,nlwp,pcpu,pmem,stat,comm']),
        mounts=command(['findmnt','--json','--list','--output','SOURCE,TARGET,FSTYPE,OPTIONS']),
        block_devices=command(['lsblk','--json','--bytes','--output','NAME,PATH,SIZE,MODEL,TYPE,FSTYPE,UUID,MOUNTPOINTS']),
        clock_ticks_per_second=os.sysconf('SC_CLK_TCK')))
    # Bounded passive sample; hashing/discovery overhead is disclosed, no capacity benchmark.
    time.sleep(15)
    final=attest.inspect([str(MOUNT)],os.getppid())
    save('RESOURCE_FINAL.json',final)
    final_details=process_details(final)
    save('PROCESS_FINAL_DETAILS.json',final_details)
    save('ACTIVITY_FINAL.json',cgroup_activity(final_details))
    save('RESOURCE_FINAL_CHECKS.json',host_checks(final))
    initial_units={u for item in details for u in item['membership_units']}
    if any(u not in initial_units for item in final_details for u in item['membership_units']):
        save('SYSTEMD_NEW_PROCESS_UNITS.json',unit_evidence(final_details))
    final_exes={r['executable'] for r in final['processes'] if not r['kernel']}
    if not final_exes.issubset({r['executable'] for r in initial['processes'] if not r['kernel']}):
        save('NEW_EXECUTABLE_PACKAGE_PROVENANCE.json',packages(final_exes))
    checks=host_checks(final)
    stable=attest.constraint_identity(initial)==attest.constraint_identity(final)
    RESULT.update(status='FRESH_PROCESS_FACTS_PRESERVED_REQUIRES_ATTESTATION_REVIEW',
        host_resource_checks=checks,resource_constraints_stable=stable,
        actual_boot_id=final['boot_id'],actual_hostname=final['hostname'],
        complete_discovery_method='approved attest.inspect/process_inventory; supplementary read-only ownership/provenance/activity evidence')
    core.require(checks['passed'] and stable,'fresh_host_resource_checks_failed')


if __name__=='__main__':
    try:main()
    except Exception as exc:RESULT.update(status='STAGE_E_NATIVE_V3_A_PREFLIGHT_BLOCKED',blocker=type(exc).__name__+':'+str(exc))
    finally:
        if OUTPUT.is_dir():
            RESULT['retained_executor_evidence_path']=str(OUTPUT)
            save('DISCOVERY_RESULT.json',RESULT)
            save('EVIDENCE_MANIFEST.json',dict(artifacts=[dict(path=p.name,bytes=p.stat().st_size,sha256=core.file_sha(p)) for p in sorted(OUTPUT.iterdir()) if p.is_file()],
                execution_authorized=False,actual_slots_reserved=False,A_slots_consumed=0,source_frames_released=0))
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as target:target.write('evidence_path='+str(OUTPUT)+'\n')
        print(json.dumps({k:v for k,v in RESULT.items() if k!='host_resource_checks'},sort_keys=True))
