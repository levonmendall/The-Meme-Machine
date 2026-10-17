"""Actual native pipelines in an explicitly bookless, disposable child.

This module has no provider/financial construction fallback. The protected
parent owns source authentication, purchases and sizing observations. A finished
900-second observation is neither production recovery nor PAPER acceptance.
"""
import asyncio
from contextlib import contextmanager, redirect_stdout
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time

EXECUTION_SECONDS = 900
SOURCE_START_SECONDS = 300
SHUTDOWN_SECONDS = 65
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class ContainedNativeFailure(ValueError):
    """Only fixed local classifications cross the entrypoint boundary."""


def _require(value, code):
    if not value:
        raise ContainedNativeFailure(code)


def _environment(resources):
    root = resources.root
    return {
        'MM_MODE': 'PAPER',
        'MM_OPERATIONAL_PHASE': 'ISOLATED_NATIVE',
        'MM_DIRECTIONAL_COMPOSITE_REQUIRED': '1',
        'MM_SOLANA_HISTORY_SEPARATED': '1',
        'MM_SOLANA_CANDIDATE_HISTORY_DB': str(root/'candidate-history.sqlite'),
        'MM_SOLANA_EVIDENCE_PLANE_DB': str(root/'solana-evidence.sqlite'),
        'MM_SOLANA_EVIDENCE_BROKER_DB': str(root/'solana-broker.sqlite'),
        'MM_PUMP_ACCELERATION_REPORT': str(root/'pump-current'/'report.json'),
        'MM_PONS_SELECTIVE_COHORT_DIR': str(root/'pons-current'),
        'MM_PONS_SELECTIVE_COHORT_REPORT': str(root/'pons-current'/'report.json'),
    }


@contextmanager
def _fixed_environment(resources):
    # Refuse credential/financial/state inheritance instead of hiding or copying
    # it. These are fixed private paths, never caller-selected endpoint strings.
    forbidden = ('MM_PAPER_EPOCH', 'MM_PORTFOLIO_ACCOUNTING_DB',
        'MM_PORTFOLIO_EPOCH_FILE', 'MM_DIRECTIONAL_SLEEVE_DB',
        'MM_NATIVE_GENESIS_CAPITAL', 'MM_STATE_ROOT', 'MM_RPC_CAPABILITIES',
        'MM_SOLANA_READ_RPC_URL', 'MM_SOLANA_STREAM_URL', 'MM_PONS_RPC_URL',
        'ALCHEMY_API_KEY', 'ROBINHOOD_API_KEY')
    _require(not any(os.environ.get(key) for key in forbidden),
        'isolated_native_inherited_authority_or_transport')
    expected = _environment(resources)
    _require(all(key not in os.environ or os.environ[key] == value
        for key, value in expected.items()), 'isolated_native_configuration_conflict')
    # Module-level paths are evaluated at import. Never silently reuse a module
    # already bound to ordinary files, even if its apparent report path matches.
    names = ('meme_machine.lanes.pump.runner',
        'meme_machine.lanes.pons.pons_selective_cohort')
    _require(not any(name in sys.modules for name in names),
        'isolated_native_consumers_preimported')
    prior = {key: os.environ.get(key) for key in expected}
    try:
        os.environ.update(expected)
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _PrivateOutput:
    def __init__(self, path):
        self.file = path.open('x', encoding='utf-8')
        self.bytes = 0
        self.lock = threading.Lock()

    def write(self, value):
        encoded = value.encode('utf-8')
        with self.lock:
            _require(self.bytes + len(encoded) <= MAX_OUTPUT_BYTES,
                'isolated_native_output_bound')
            self.bytes += len(encoded)
            return self.file.write(value)

    def flush(self):
        with self.lock:
            self.file.flush()

    def close(self):
        self.file.close()


def _numeric(value, *, depth=0):
    """Bound the fixed source metric projection; omit provider/error text."""
    if type(value) in (int, float, bool):
        return value if type(value) is not float or abs(value) < 1e100 else None
    if type(value) is dict and depth < 5:
        result = {}
        for key, item in list(value.items())[:128]:
            if (type(key) is str and len(key) <= 100 and
                    all(char.islower() or char.isdigit() or char in '_.:' for char in key)):
                projected = _numeric(item, depth=depth+1)
                if projected is not None:
                    result[key] = projected
        return result
    return None


def _persist(resources, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    _require(len(raw) <= 65536, 'isolated_native_receipt_bound')
    path = resources.root/'native-execution.json'
    temporary = resources.root/'native-execution.json.tmp'
    _require(not path.is_symlink() and not temporary.exists(),
        'isolated_native_receipt_owner')
    with temporary.open('xb') as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


async def _run_lifecycle(*, resources, stopped, sizing_reader, source,
        workers, source_path, seconds=EXECUTION_SECONDS,
        startup_seconds=SOURCE_START_SECONDS, shutdown_seconds=SHUTDOWN_SECONDS, progress=None):
    """Own all threads until joined, including failure and cancellation paths.

    The shortened arguments are private offline fixture controls. The public
    entrypoint supplies the fixed reviewed limits and actual native functions.
    """
    from meme_machine.runtime import stop
    from meme_machine.runtime.isolated_native_execution import isolated_native_execution
    _require(0 < seconds <= EXECUTION_SECONDS and 0 < startup_seconds <= SOURCE_START_SECONDS
        and 0 < shutdown_seconds <= SHUTDOWN_SECONDS, 'isolated_native_lifecycle_bound')
    _require(not stopped.is_set() and not stop.requested.is_set(),
        'isolated_native_already_stopped')
    began = time.monotonic()
    deadline = began + seconds
    source_stop = asyncio.Event()
    errors = []
    statuses = {}
    threads = []
    counts = dict(sizing_refreshes=0)
    lock = threading.Lock()

    def run_worker(name, call):
        with lock:
            statuses[name] = dict(started=True, completed=False, cancelled=False)
        try:
            with isolated_native_execution(resources):
                call()
        except stop.Shutdown:
            if not stop.requested.is_set():
                with lock:
                    errors.append('isolated_native_unrequested_shutdown')
            else:
                with lock:
                    statuses[name]['cancelled'] = True
        except BaseException:
            # Do not carry arbitrary provider content through exception text.
            with lock:
                errors.append('isolated_native_'+name+'_failed')
        finally:
            with lock:
                statuses[name]['completed'] = True

    def sizing():
        while not stopped.is_set():
            try:
                sizing_reader.apply_next(resources, seconds=4)
            except BaseException:
                if stopped.is_set():
                    return
                raise
            with lock:
                counts['sizing_refreshes'] += 1

    async def source_main():
        with isolated_native_execution(resources):
            for lane in ('pump', 'pons'):
                resources.facts.require_fresh(lane, int(resources.clock()))
            await source(source_stop)

    sizing_thread = threading.Thread(target=run_worker, args=('sizing', sizing),
        name='isolated-native-sizing', daemon=False)
    threads.append(sizing_thread)
    sizing_thread.start()
    source_task = asyncio.create_task(source_main())
    observed_at = None
    first_progress = None
    last_progress = None
    progress_samples = 0
    next_progress = began
    def sample_progress():
        nonlocal first_progress,last_progress,progress_samples,next_progress
        if progress is None or time.monotonic()<next_progress:return
        value=progress()
        _require(type(value) is dict,'isolated_native_progress_shape')
        last_progress=value
        if first_progress is None:first_progress=value
        progress_samples+=1
        next_progress=time.monotonic()+5
    failure = None
    completed_window = False
    receipt = dict(schema='isolated-native-execution-v1', financial_authority=False,
        normal_readiness=False, authoritative_historical_recovery=False,
        held_protection='UNEXERCISED', fills='UNEXERCISED', settlement='UNEXERCISED',
        source_accounting_scope='PARENT_PUBLIC_HANDOFF_ONLY',
        physical_provider_accounting='PROTECTED_PARENT_ONLY',
        complete_production_parity=False,
        unexercised=['production_state_restoration', 'held_position_priority_zero',
            'financial_settlement', 'authenticated_provider_optimization_profiles'])
    try:
        # This only proves a private owner socket exists, not native financial
        # readiness, complete history, or complete economic coverage.
        while True:
            sample_progress()
            if source_task.done():
                source_task.result()
                raise ContainedNativeFailure('isolated_native_source_ended')
            _require(not stopped.is_set(), 'isolated_native_start_cancelled')
            with lock:
                _require(not errors, errors[0] if errors else 'isolated_native_worker_failed')
            for lane in ('pump', 'pons'):
                resources.facts.require_fresh(lane, int(resources.clock()))
            _require(time.monotonic() < min(deadline, began+startup_seconds),
                'isolated_native_source_socket_deadline')
            socket_path = Path(str(source_path)+'.sock')
            if source_path.is_file() and socket_path.exists():
                _require(not source_path.is_symlink() and not socket_path.is_symlink()
                    and stat.S_ISSOCK(socket_path.stat().st_mode),
                    'isolated_native_source_socket_owner')
                observed_at = time.monotonic()
                break
            await asyncio.sleep(.05)
        for name, call in workers:
            thread = threading.Thread(target=run_worker, args=(name, call),
                name='isolated-native-'+name, daemon=False)
            threads.append(thread)
            thread.start()
        while time.monotonic() < deadline and not stopped.is_set():
            sample_progress()
            if source_task.done():
                source_task.result()
                raise ContainedNativeFailure('isolated_native_source_ended')
            with lock:
                _require(not errors, errors[0] if errors else 'isolated_native_worker_failed')
                _require(not any(item['completed'] for name, item in statuses.items()
                    if name != 'sizing'), 'isolated_native_consumer_ended')
            # Fresh parent facts are mandatory even when consumers are waiting
            # on source warmup and have not requested a new sizing basis yet.
            for lane in ('pump', 'pons'):
                resources.facts.require_fresh(lane, int(resources.clock()))
            await asyncio.sleep(.05)
        completed_window = time.monotonic() >= deadline and not stopped.is_set()
        # Last execution sample remains before stop/drain, so terminal cleanup
        # is never silently counted as steady processing throughput.
        next_progress=0
        sample_progress()
    except BaseException as error:
        failure = error
    finally:
        stopped.set()
        stop.requested.set()
        source_stop.set()
        shutdown_at = time.monotonic()
        shutdown_deadline = shutdown_at + shutdown_seconds
        # Preserve the original source drain and consumer cancellation first;
        # cancelling the source task early would interrupt accepted FULL/ACK.
        while time.monotonic() < shutdown_deadline:
            if source_task.done() and not any(thread.is_alive() for thread in threads):
                break
            await asyncio.sleep(.05)
        joined = source_task.done() and not any(thread.is_alive() for thread in threads)
        if source_task.done():
            try:
                source_task.result()
            except BaseException as error:
                if failure is None:
                    failure = error
        if joined:
            for thread in threads:
                if thread.ident is not None:thread.join()
        else:
            # The outer fixed process boundary must stop an uncooperative
            # thread/worker. Never represent a live thread as graceful cleanup.
            failure = ContainedNativeFailure('isolated_native_shutdown_incomplete')
        with lock:
            final_statuses = {key: dict(value) for key, value in statuses.items()}
            final_counts = dict(counts)
            if errors and failure is None:
                failure = ContainedNativeFailure(errors[0])
        receipt.update(full_window_completed=completed_window,
            execution_window_seconds=seconds, startup_seconds=(None if observed_at is None
                else observed_at-began), observed_after_socket_seconds=(None if observed_at is None
                else shutdown_at-observed_at), elapsed_seconds=time.monotonic()-began,
            shutdown_seconds=time.monotonic()-shutdown_at, all_workers_joined=joined,
            workers=final_statuses, counters=final_counts,
            progress_samples=progress_samples,first_progress=first_progress,last_progress=last_progress,
            status='FAILED' if failure is not None else 'COMPLETED')
        if failure is not None:
            receipt['failure_code'] = (str(failure) if type(failure) is ContainedNativeFailure
                else 'isolated_native_runtime_failed')
        _persist(resources, receipt)
    if failure is not None:
        raise failure
    return receipt


def run_contained(*, resources, ports, sizing_reader, stopped):
    """Fixed entry integration: no URL, account, budget or runner alternatives."""
    from meme_machine.runtime.isolated_native_resources import require_resources
    from meme_machine.runtime.isolated_native_bootstrap import require_runner_ports
    from meme_machine.runtime.isolated_native_execution import isolated_native_execution
    resources = require_resources(resources)
    require_runner_ports(resources, ports)
    _require(type(stopped) is threading.Event and callable(getattr(sizing_reader, 'apply_next', None)),
        'isolated_native_lifecycle_capabilities')
    for lane in ('pump', 'pons'):
        resources.facts.require_fresh(lane, int(resources.clock()))
    # Exclusive disposable ownership is established before importing any native
    # module whose module globals bind paths. No production epoch is adopted.
    with _fixed_environment(resources), isolated_native_execution(resources):
        resources.candidate_history().close()
        from meme_machine.runtime.evidence_worker import RepairRPC
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_evidence_service import serve
        rpc = RepairRPC(None, None, native_resources=resources, native_ports=ports)
        driver = SelectiveSource(rpc.config, rpc, native_resources=resources, native_ports=ports)
        pump = importlib.import_module('meme_machine.lanes.pump.runner')
        pons = importlib.import_module('meme_machine.lanes.pons.pons_selective_cohort')
        # Validate every mandatory source before the first provider acquisition.
        for priority in (1, 2, 3, 4, 5, 6):
            for operation in ('history_receipt', 'recovery_restart', 'unattributed'):
                ports.source_rpc(priority, operation=operation)
        for lane in ('pump', 'pons'):
            for regime in ('current', 'survivor', 'discovery'):
                ports.rpc_port(lane, regime)
        ports.pons_feed()
        source_path = resources.root/'solana-evidence.sqlite'
        async def source(stop_event):
            await serve(source_path, None, repair_rpc=rpc, stop=stop_event,
                source_driver=driver, native_resources=resources, native_ports=ports)
        def pump_current():
            pump.main(campaign=True, native_resources=resources, native_ports=ports)
        def pons_current():
            value = pons.run(ports.rpc_port('pons', 'current').source, campaign=True,
                native_resources=resources, native_ports=ports)
            pons.persist_terminal(value)
        output = _PrivateOutput(resources.root/'native-output.txt')
        progress_file=(resources.root/'native-progress.jsonl').open('xb')
        progress_bytes=0
        def progress():
            nonlocal progress_bytes
            native=driver.pipeline_metrics.get('native_frame:shared:slot',{})
            head=native.get('latest_slot')
            processed=driver.control_committed_slot
            # Finalized control slots are one population. Economic queues are
            # separate counters; no slot/frame or slot/transaction conversion.
            queues={name:{key:row[key] for key in ('accepted','committed')}
                for name,row in driver.source_drain['queues'].items()}
            for row in queues.values():row['pending']=row['accepted']-row['committed']
            value=dict(wall_time=resources.clock(),monotonic=time.monotonic(),
                finalized_control_native_slot=head,finalized_control_durable_slot=processed,
                finalized_control_gap_slots=(head-processed if type(head) is int and
                    type(processed) is int and head>=processed else None),
                joined_frame_queues=queues)
            raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
            _require(progress_bytes+len(raw)<=256*1024,'isolated_native_progress_bound')
            progress_file.write(raw);progress_file.flush()
            progress_bytes+=len(raw)
            return value
        result=None
        def finish_metrics(value):
            value['private_output_bytes']=output.bytes
            value['private_progress_bytes']=progress_bytes
            # Never inspect a dictionary still owned by a live source task.
            if value.get('all_workers_joined'):
                value['source_rpc_counters']=_numeric(rpc.telemetry().get('counters', {}))
                value['source_pipeline_counters']=_numeric(driver.pipeline_metrics)
                value['source_drain_counters']=_numeric(driver.drain_snapshot())
            _persist(resources,value)
        try:
            with redirect_stdout(output):
                result = asyncio.run(_run_lifecycle(resources=resources, stopped=stopped,
                    sizing_reader=sizing_reader, source=source,
                    workers=[('pump', pump_current), ('pons', pons_current)], source_path=source_path,
                    progress=progress))
        except BaseException:
            path=resources.root/'native-execution.json'
            if path.is_file() and not path.is_symlink() and path.stat().st_size<=65536:
                finish_metrics(json.loads(path.read_bytes()))
            raise
        finally:
            progress_file.close()
            output.close()
        finish_metrics(result)
        return result
