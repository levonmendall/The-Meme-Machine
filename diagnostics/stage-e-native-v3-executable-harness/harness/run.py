"""Future material controller. Authorization is checked before setup or spawn."""
import os
from pathlib import Path
import signal
import subprocess

from attest import ResourceMonitor, inspect, admission_errors, signed_document, reserve_storage
from binding import candidate_integrity, contract_integrity, runtime_identity, verify_assembly
from core import ASSEMBLY, INFRA, PERF_NS, REAL_NS, canonical, file_sha, read, require, sha, workload
from campaign import verify_capacity_prerequisite
from declaration import authorize
from ledger import Ledger
from preserve import persist, seal, fsync_dir, lock, redundant_copy, abandoned_ipc, failure_copy
from tape import validate_existing
from trial import child_env, runtime_command
from verify import OVERLOAD, verify_trial, verify_observer


def _wait_helpers(root_pid, known_pids, *, timeout=15):
    """Descendant identity is tracked through PID/start_ticks, not process names."""
    from attest import process_inventory
    from core import REAL_NS
    import time
    started = REAL_NS()
    scope = {root_pid}
    while True:
        processes = process_inventory()
        prior = None
        while scope != prior:
            prior = set(scope)
            scope.update(p['pid'] for p in processes if p['ppid'] in scope)
        alive = [p for p in processes if (p['pid'] in scope or known_pids.get(p['pid']) == p['start_ticks']
                                         or p.get('process_group') == root_pid)
                 and p['pid'] not in (root_pid, os.getpid()) and p['state'] != 'Z']
        if not alive:
            return
        require(REAL_NS()-started < timeout*10**9, 'helper_termination_timeout')
        time.sleep(.1)


def _wait_trial(child, monitor, timeout):
    """Resource refusal stops a live trial on the common .25-second boundary."""
    from core import REAL_NS
    deadline = REAL_NS() + int(timeout*10**9)
    while True:
        require(not monitor.errors, 'resource_monitor_refused_live_trial')
        remaining = (deadline-REAL_NS())/10**9
        require(remaining > 0, 'native_trial_deadline')
        try:
            return child.wait(timeout=min(.25, remaining))
        except subprocess.TimeoutExpired:
            continue


def _terminate_trial(child, monitor):
    # The process group also includes decoder children after a member exits.
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=15)
            _wait_helpers(child.pid, monitor.known_pids, timeout=15)
            return dict(trial_pid=child.pid, trial_process_terminated=True,
                        all_native_helpers_terminated=True, real_monotonic_ns=REAL_NS(),
                        tracked_processes=[dict(pid=p,start_ticks=t) for p,t in sorted(monitor.known_pids.items())])
        except (subprocess.TimeoutExpired, ValueError):
            if signum == signal.SIGKILL:
                raise


def _clock_boundary():
    before = REAL_NS()
    perf = PERF_NS()
    after = REAL_NS()
    return dict(real_monotonic_ns=before, perf_ns=perf, clock_read_span_ns=after-before)


def _publish_failure(folder, destination):
    try:
        return redundant_copy(folder, destination)
    except BaseException as exc:
        # The strict inventory may itself be incomplete, or copytree may have
        # left a partial destination. Use a separate exclusive failure copy.
        receipt = failure_copy(folder, destination.with_name(destination.name+'-failure'))
        return dict(receipt, strict_publication_failure=type(exc).__name__+':'+str(exc))


def _finalize_attempt(folder, d, sequence, *, valid, reason, declaration_sha256, allocation):
    """Sealing cannot skip INVALID consumption or failure publication."""
    folder = Path(folder)
    ledger = Ledger(folder.parent/'LEDGER.jsonl')
    destination = Path(d['paths']['durable_publication_root'])/(d['campaign']+f'-t{sequence}')
    digest, result = None, None
    if not valid and (folder/'PROCESS_TERMINATION.json').exists():
        try:
            abandoned_ipc(folder, read(folder/'PROCESS_TERMINATION.json'))
        except BaseException as exc:
            reason = str(reason)+';abandoned_IPC:'+str(exc)
    try:
        digest = seal(folder)
    except BaseException as exc:
        valid = False
        reason = str(reason or '')+';raw_sealing_failure:'+type(exc).__name__+':'+str(exc)
        try:
            persist(folder/'SEAL_FAILURE.json', dict(reason=reason, native_safety_credit=False))
        except BaseException as receipt_error:
            reason += ';seal_failure_receipt:'+str(receipt_error)
    if valid:
        try:
            result = verify_trial(folder,d,declaration_sha256=declaration_sha256,allocation=allocation)
            publication = redundant_copy(folder,destination)
            persist(folder.parent/f'TRIAL-{sequence}-PRESERVATION.json', dict(publication,source=str(folder.resolve())))
        except BaseException as exc:
            valid = False
            reason = 'raw_verification_or_preservation:'+type(exc).__name__+':'+str(exc)
    if valid:
        terminal = result.get('outcome') == OVERLOAD
        ledger.append('DIAGNOSTIC_OVERLOAD' if terminal else 'COMPLETE_VALID',sequence,
                      dict(raw_inventory_sha256=digest,verification=result))
        return result, None, terminal
    # This append precedes every failure-copy attempt, even when digest is null.
    # If recording itself fails, the finally still attempts to publish raw files.
    try:
        ledger.append('INVALID',sequence,dict(reason=reason,raw_inventory_sha256=digest))
    finally:
        try:
            publication = _publish_failure(folder,destination)
            persist(folder.parent/f'TRIAL-{sequence}-FAILURE-PRESERVATION.json',
                    dict(publication,source=str(folder.resolve()),reason=reason))
        except BaseException as exc:
            reason = str(reason)+';failure_publication:'+type(exc).__name__+':'+str(exc)
    return None, reason, True


def _finalize_campaign(campaign, d, ledger, declaration_sha256):
    destination = Path(d['paths']['durable_publication_root'])/(d['campaign']+'-campaign')
    try:
        seal(campaign,name='CAMPAIGN_INVENTORY.json')
        publication = redundant_copy(campaign,destination,name='CAMPAIGN_INVENTORY.json')
        persist(campaign.with_name(d['campaign']+'.PRESERVATION.json'), dict(publication,
            version='v3-complete-campaign-preservation',source=str(campaign.resolve()),campaign=d['campaign'],
            declaration_sha256=declaration_sha256,ledger_sha256=file_sha(ledger.path)))
    except BaseException as exc:
        reason = 'campaign_preservation_failure:'+type(exc).__name__+':'+str(exc)
        try:
            events = ledger.events()
            if not any(r['event'] in ('INVALID','STOPPED','DIAGNOSTIC_OVERLOAD') for r in events):
                ledger.append('STOPPED',None,dict(reason=reason))
        finally:
            try:
                persist(campaign/'CAMPAIGN_PRESERVATION_FAILURE.json',dict(reason=reason,native_safety_credit=False))
            finally:
                failure_copy(campaign,destination.with_name(destination.name+'-failure'))
        raise ValueError(reason) from exc


def execute(declaration_path, permit_path, owner_key, *, kind):
    d = authorize(declaration_path, permit_path, owner_key, kind=kind)
    paths = d['paths']
    candidate_integrity(paths['candidate_checkout'])
    contract_integrity(paths['repository'])
    verify_assembly(paths['assembly'])
    actual_runtime = runtime_identity(Path(paths['assembly'])/'source')
    require(actual_runtime == d['environment']['runtime_dependency_identities'], 'runtime_changed_after_declaration')
    allocation = signed_document(paths['allocation_document'], paths['allocation_public_key'],
                                 d['trust_keys']['allocation_public_key_sha256'])
    require(allocation == d['allocation'], 'allocation_document_changed_after_declaration')
    sample = inspect(paths['storage_paths'], os.getpid())
    require(not admission_errors(sample, allocation, d['storage_bounds'], actual_runtime), 'production_envelope_admission_failed')
    preparation_reserve = reserve_storage(sample,d['storage_bounds'])
    require(sample['boot_id'] == d['executor']['boot_id'] and sample['hostname'] == d['executor']['hostname'], 'actual_executor_identity')
    tape_proof = validate_existing(paths['tape'], paths['frame_inventory'], kind=kind)
    capacity = None
    if kind == 'B':
        capacity = verify_capacity_prerequisite(d,owner_key,paths['allocation_public_key'])
    registry = Path(paths['campaign_registry'])
    ledger = Ledger.create(registry, kind, file_sha(declaration_path), d['campaign'])
    campaign = ledger.path.parent
    try:
        persist(campaign/'DECLARATION.json', d)
        persist(campaign/'TAPE_ADMISSION.json', tape_proof)
        persist(campaign/'PREPARATION_STORAGE_RESERVE.json', preparation_reserve)
        # Public signed documents and original bytes are evidence; no private key,
        # environment credentials or runtime DB is ever a Git publication artifact.
        import shutil
        public = campaign/'public-authority'
        public.mkdir()
        documents = [('owner-permit.json',permit_path),('allocation.json',paths['allocation_document']),
                     ('original-declaration.json',declaration_path)]
        for name, source in documents:
            target=public/name
            with Path(source).open('rb') as reader, target.open('xb') as writer:
                shutil.copyfileobj(reader,writer);writer.flush();os.fsync(writer.fileno())
            require(file_sha(target)==file_sha(source),'authority_document_copy_readback')
        capabilities = []
        for index, proof in enumerate(allocation['allocation_evidence']):
            target = public/f'CAPABILITY-{index}.bin'
            with Path(proof['path']).open('rb') as reader, target.open('xb') as writer:
                shutil.copyfileobj(reader,writer);writer.flush();os.fsync(writer.fileno())
            require(file_sha(target)==proof['sha256'],'capability_copy_readback')
            capabilities.append(dict(original_path=proof['path'],preserved_path=target.relative_to(campaign).as_posix()))
        persist(campaign/'PUBLIC_AUTHORITY_RECEIPTS.json',dict(
            original_declaration_sha256=file_sha(declaration_path),
            owner_permit_path='public-authority/owner-permit.json',allocation_document_path='public-authority/allocation.json',
            original_declaration_path='public-authority/original-declaration.json',capability_files=capabilities))
        params_base = dict(kind=kind, declaration=d, declaration_path=str(Path(declaration_path).resolve()),
            declaration_sha256=file_sha(declaration_path), owner_permit_path=str(Path(permit_path).resolve()),
            owner_key=str(Path(owner_key).resolve()), assembly=paths['assembly'],
            environment=actual_runtime, allocation=allocation, candidate_checkout=paths['candidate_checkout'],
            tape_path=paths['tape'], cache_path=paths['cache_path'], controller_pid=os.getpid())
        require(not Path(paths['cache_path']).exists(), 'existing_bytecode_cache')
        verified_trials = []
        terminal_error = None
        interrupted = []
        def signal_stop(signum, frame):
            interrupted.append(signum)
            raise InterruptedError('workflow_signal:'+str(signum))
        old_handlers = {s: signal.signal(s, signal_stop) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            with lock(campaign/'CAMPAIGN.lock'):
                for trial in d['trials']:
                    sequence = trial['sequence']
                    ledger.append('STARTED', sequence, dict(trial_id=trial['trial_id'], mode=trial['mode']))
                    # No frame or child can precede the consumed-on-start ledger event.
                    start_clock = _clock_boundary()
                    start = start_clock['perf_ns']
                    folder = campaign/f't{sequence}'
                    folder.mkdir(exist_ok=False)
                    resources = folder/'resources'
                    resources.mkdir()
                    monitor = ResourceMonitor(resources, paths['storage_paths'], allocation, d['storage_bounds'], actual_runtime)
                    child = None
                    valid = False
                    failure = None
                    try:
                        monitor.start()
                        persist(folder/'TRIAL_STORAGE_RESERVE.json',reserve_storage(
                            inspect(paths['storage_paths'],os.getpid()),d['storage_bounds']))
                        params = dict(params_base, sequence=sequence, trial_id=trial['trial_id'],
                                      mode=trial['mode'], output=str(folder))
                        param_path = folder/'params.json'
                        persist(param_path, params)
                        unshare = actual_runtime['os_tools']['unshare']['path']
                        command = [unshare, '--net', '--', *runtime_command(params, '--trial')]
                        with (folder/'trial.log').open('xb') as log:
                            startup = REAL_NS()
                            child = subprocess.Popen(command, cwd=paths['candidate_checkout'], env=child_env(param_path),
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                            frames_seconds = 3000.78 + (81.3 if kind == 'A' else 0)
                            code = _wait_trial(child, monitor, frames_seconds+4*240+120)
                            log.flush(); os.fsync(log.fileno())
                        _wait_helpers(child.pid, monitor.known_pids)
                        helpers = REAL_NS()
                        persist(folder/'PROCESS_TERMINATION.json',dict(trial_pid=child.pid,
                            trial_process_terminated=True,all_native_helpers_terminated=True,real_monotonic_ns=helpers,
                            tracked_processes=[dict(pid=p,start_ticks=t) for p,t in sorted(monitor.known_pids.items())]))
                        require(code == 0, 'native_trial_process_failed')
                        cohort = read(folder/'COHORT_RESULT.json')
                        require(cohort['valid'] is True, 'native_cohort_invalid')
                        candidate_integrity(paths['candidate_checkout'])
                        verify_assembly(paths['assembly'])
                        persist(folder/'MEASURED_PERSISTENCE_COMPLETE.json', dict(cohort=cohort,
                            all_native_helpers_terminated=True, resource_errors=monitor.errors,
                            no_subtraction=True, no_double_counting=True))
                        fsync_dir(folder)
                        # Keep monitoring through candidate checks and measured
                        # persistence; teardown then brackets the actual endpoint.
                        monitor.close()
                        end_clock = _clock_boundary()
                        end = end_clock['perf_ns']
                        interval = dict(start_real_monotonic_ns=start_clock['real_monotonic_ns'],start_perf_ns=start,
                            start_clock_read_span_ns=start_clock['clock_read_span_ns'],startup_real_monotonic_ns=startup,
                            helpers_terminated_real_monotonic_ns=helpers,end_perf_ns=end,
                            end_real_monotonic_ns=end_clock['real_monotonic_ns'],end_clock_read_span_ns=end_clock['clock_read_span_ns'])
                        # Endpoint metadata records the instant after all measured
                        # work/persistence/joins. Upload and independent verification
                        # are outside the B interval; no cost is subtracted or added.
                        persist(folder/'TRIAL_RESULT.json', dict(cohort, start_perf_ns=start, end_perf_ns=end,
                                                               elapsed_ns=end-start,execution_interval=interval))
                        valid = True
                    except BaseException as exc:
                        failure = type(exc).__name__+':'+str(exc)
                        terminal_error = failure
                        if child is not None:
                            try:
                                termination = _terminate_trial(child, monitor)
                                if not (folder/'PROCESS_TERMINATION.json').exists():
                                    persist(folder/'PROCESS_TERMINATION.json',termination)
                            except BaseException as closing_error:
                                failure += ';helper_teardown:'+str(closing_error)
                        try:
                            monitor.close()
                        except BaseException as closing_error:
                            failure += ';resource_teardown:'+str(closing_error)
                        terminal_error = failure
                        try:
                            persist(folder/'TERMINAL_FAILURE.json', dict(reason=failure, interrupted=interrupted,
                                incomplete_elapsed_is_not_baseline=True, native_safety_credit=False))
                        except BaseException as receipt_error:
                            terminal_error += ';failure_receipt:'+str(receipt_error)
                    result, terminal_error, terminal = _finalize_attempt(folder,d,sequence,valid=valid,
                        reason=terminal_error,declaration_sha256=file_sha(declaration_path),allocation=allocation)
                    if result is not None:
                        verified_trials.append(result)
                    if terminal:
                        break
                if len(verified_trials) == len(d['trials']) and terminal_error is None:
                    result = verify_observer(verified_trials, d, capacity) if kind == 'B' else verified_trials[0]
                    persist(campaign/'VERIFICATION.json', result)
                else:
                    persist(campaign/'STOP_FOR_ASTRA.json', dict(reason=terminal_error, source_runs_started=True,
                        valid_trials=len(verified_trials), no_retry=True, stage_e='RED', stage_f='NOT STARTED'))
        finally:
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
    except BaseException as exc:
        reason = type(exc).__name__+':'+str(exc)
        try:
            events = ledger.events()
            if not any(r['event'] in ('INVALID','STOPPED','DIAGNOSTIC_OVERLOAD') for r in events):
                active = [r['sequence'] for r in events if r['event'] == 'STARTED']
                done = [r['sequence'] for r in events if r['event'] == 'COMPLETE_VALID']
                ledger.append('INVALID' if len(active) > len(done) else 'STOPPED',
                              active[-1] if len(active) > len(done) else None,dict(reason=reason))
        finally:
            persist(campaign/'CONTROLLER_FAILURE.json', dict(reason=reason,stage_e='RED',stage_f='NOT STARTED'))
        raise
    finally:
        _finalize_campaign(campaign,d,ledger,file_sha(declaration_path))
    require(terminal_error is None, 'campaign_stopped:'+str(terminal_error))
    return campaign
