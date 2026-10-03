"""Fresh evidence-derived process bindings; no harness changes or name exemptions."""
import importlib.util
import os
from pathlib import Path


def approve(snapshot, here, output, save, attest, core):
    spec=importlib.util.spec_from_file_location('process_evidence_supplement',here/'collect_process_attestation_r2.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    collector.OUTPUT=output
    review=core.read(here/'inputs/PROCESS_ATTESTATION_REVIEW.json')
    core.require(review['process_attestation_passed'] and not review['unresolved'],'previous_complete_process_review_not_passed')
    roles={(r['unit'],r['executable'],r['executable_sha256']):r for r in review['reviewed_service_roles']}
    details=collector.process_details(snapshot)
    save('FRESH_PROCESS_DETAILS.json',details)
    activity_initial=collector.cgroup_activity(details);save('FRESH_ACTIVITY_INITIAL.json',activity_initial)
    units=collector.unit_evidence(details);save('FRESH_SYSTEMD_OWNERSHIP.json',units)
    sources={r['executable'] for r in snapshot['processes'] if not r['kernel']}
    for files in units['unit_file_identities'].values():
        for file in files:
            for directive in file.get('relevant_configuration',[]):
                path=directive.get('executable')
                if path and Path(path).is_file():sources.add(str(Path(path).resolve()))
    sources.add('/usr/libexec/fwupd/fwupd')
    provenance=collector.packages(sources);save('FRESH_EXECUTABLE_PROVENANCE.json',provenance)
    save('FRESH_ACTIVITY_FINAL.json',collector.cgroup_activity(details))
    by_pid={r['pid']:r for r in snapshot['processes']};supplement={r['pid']:r for r in details}
    scope={snapshot['scope_pid']}
    while True:
        more=scope|{r['pid'] for r in by_pid.values() if r['ppid'] in scope}
        if more==scope:break
        scope=more
    approved=[];mapping=[];unresolved=[]
    for row in snapshot['processes']:
        d=supplement[row['pid']];issues=[]
        raw=d['raw']['cgroup'].get('raw','');group=raw.split(':',2)[-1].strip() if raw else None
        unit=d['membership_units'][-1] if d['membership_units'] else None
        if not d.get('generation_matches_discovery'):issues.append('process_generation_changed_or_unavailable')
        for thread in row['threads']:
            state=d['threads'][str(thread['tid'])]['cgroup']
            if state.get('sha256')!=thread['cgroup_sha256']:issues.append('thread_cgroup_changed')
        if row['kernel']:
            if row['ppid'] not in (0,2) or 'Kthread:\t1' not in d['raw']['status'].get('raw',''):
                issues.append('unproved_kernel_process')
            disposition='ATTESTED_KERNEL_SYSTEM_PROCESS'
        elif row['pid'] in scope:
            disposition='NONMATERIAL_PREFLIGHT_SCOPE'
        else:
            role=roles.get((unit,row['executable'],row['executable_sha256']))
            if not role:issues.append('no_evidence_reviewed_service_binding')
            properties=units['units'].get(unit,{})
            cg=properties.get('ControlGroup')
            if properties.get('LoadState')!='loaded' or properties.get('ActiveState')!='active':issues.append('unit_not_active_loaded')
            if not cg or not (group==cg or group.startswith(cg.rstrip('/')+'/')):issues.append('unit_cgroup_mismatch')
            if row['pid']==1 and row['ppid']==0 and group=='/init.scope' and role:
                pass # Evidence-proved OS init.scope has no service MainPID property.
            else:
                main=int(properties.get('MainPID','0'));chain=[];pid=row['pid']
                while pid in by_pid and pid not in chain:
                    chain.append(pid);pid=by_pid[pid]['ppid']
                if main<=0 or main not in chain:issues.append('unit_parent_ownership_mismatch')
            if role:
                old={x['path']:x['sha256'] for x in role['unit_files']}
                current={x['path']:x.get('sha256') for x in units['unit_file_identities'].get(unit,[])}
                if old!=current:issues.append('reviewed_unit_configuration_changed')
            source=provenance['executables'].get(row['executable'],{})
            if source.get('sha256')!=row['executable_sha256']:issues.append('source_executable_changed')
            if source.get('package_bindings'):
                entries=[r for manifest in source['installed_manifest_verification'] for r in manifest['executable_entries']]
                if not entries or not all(r['matches'] for r in entries):issues.append('installed_package_file_mismatch')
            elif not role or not unit.startswith('actions.runner.') or not row['executable'].startswith('/opt/actions-runner/'):
                issues.append('unpackaged_source_unresolved')
            if row['executable']=='/usr/bin/python3.12':
                script='/usr/share/unattended-upgrades/unattended-upgrade-shutdown'
                if script not in provenance['executables']:issues.append('system_Python_source_script_unbound')
            disposition='ATTESTED_SYSTEM_SERVICE'
            if not issues:approved.append({k:row[k] for k in ('pid','start_ticks','executable_sha256')})
        if issues:
            disposition='OWNER_APPROVED_QUIESCENCE_REQUIRED'
            unresolved.append(dict(pid=row['pid'],executable=row['executable'],issues=issues))
        mapping.append(dict(discovery=row,unit=unit,cgroup=group,ppid=row['ppid'],
            process_status=d['raw']['status'],process_io=d['raw']['io'],provenance_path='FRESH_EXECUTABLE_PROVENANCE.json',
            owner_evidence='FRESH_SYSTEMD_OWNERSHIP.json',activity_evidence=['FRESH_ACTIVITY_INITIAL.json','FRESH_ACTIVITY_FINAL.json'],
            disposition=disposition,issues=issues))
    save('PROCESS_APPROVAL.json',dict(approved_system_processes=approved,complete_mapping=mapping,
        scope_pids=sorted(scope),unresolved=unresolved,process_attestation_passed=not unresolved,
        competing_workload=False if not unresolved else None,scope='actual PID/start-time/executable tuples only; no future PID or executable-name exemptions'))
    core.require(not unresolved,'competing_or_unattested_process:'+str(unresolved[0]['pid'])+':'+str(unresolved[0]['executable']) if unresolved else 'process_attestation_failed')
    return approved
