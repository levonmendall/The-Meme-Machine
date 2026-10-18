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
import sys
import threading
import time
from .isolated_native_lifetime import NativeOwnerDrainFailure

EXECUTION_SECONDS = 900
SOURCE_START_SECONDS = 300
SHUTDOWN_SECONDS = 65
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_WORKERS = ('pump', 'pons', 'sizing')
_ORIGIN_MODULES = frozenset((
    'meme_machine.operational.isolated_native_source',
    'meme_machine.operational.source_ports', 'meme_machine.operational.child_transport',
    'meme_machine.operational.pons_native_profile',
    'meme_machine.runtime.isolated_native_bootstrap',
    'meme_machine.runtime.isolated_native_resources',
    'meme_machine.runtime.isolated_native_execution',
    'meme_machine.runtime.isolated_native_executor',
    'meme_machine.runtime.isolated_native_spawn',
    'meme_machine.runtime.isolated_pons_current',
    'meme_machine.runtime.candidate_history', 'meme_machine.runtime.survivor_history',
    'meme_machine.runtime.evidence_worker', 'meme_machine.runtime.provider_clock',
    'meme_machine.runtime.usd_valuation', 'meme_machine.runtime.robinhood.plane',
    'meme_machine.runtime.robinhood.pons',
    'meme_machine.lanes.pons.pons_selective_cohort',
    'meme_machine.lanes.pons.pons_selective_acquisition',
    'meme_machine.lanes.pons.pons_selective_ledger',
    'meme_machine.lanes.pons.pons_selective_v4',
    'meme_machine.lanes.pons.pons_survivor_runtime',
    'meme_machine.lanes.pons.provider', 'meme_machine.lanes.pons.provider_admission',
    'meme_machine.lanes.pons.immutable_rpc', 'meme_machine.lanes.pons.sequencer_feed',
    'meme_machine.lanes.pump.runner', 'meme_machine.lanes.pump.pumpswap_survivor_runtime',
    'meme_machine.lanes.pump.solana_evidence_runtime',
    'meme_machine.lanes.pump.solana_evidence_plane',
    'meme_machine.solana_evidence_service', 'meme_machine.solana_selective_source'))
_BUILTIN_ERRORS = (BaseException, Exception, AssertionError, ValueError, TypeError,
    RuntimeError, OSError, PermissionError, FileNotFoundError, TimeoutError,
    ConnectionError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
    EOFError, MemoryError, KeyError, IndexError, AttributeError, NotImplementedError)
_NATIVE_ERRORS = (
    ('meme_machine.lanes.pons', 'BoundaryError'),
    ('meme_machine.lanes.pons.sequencer_feed', 'SequencerTransportError'),
    ('meme_machine.lanes.pump.solana_evidence_plane', 'EvidenceUnavailable'),
    ('meme_machine.operational.child_transport', 'ChildTransportFailure'),
    ('meme_machine.operational.pons_native_profile', 'ProfileFailure'),
    ('meme_machine.runtime.isolated_native_execution', 'IsolatedFinancialWriteDenied'),
    ('meme_machine.runtime.isolated_native_executor', 'NativeExecutorCapacityError'),
    ('meme_machine.runtime.isolated_native_spawn', 'NativeSpawnRefused'),
    ('meme_machine.runtime.candidate_history', 'CandidateDeadlineMissed'),
    ('meme_machine.runtime.evidence_worker', 'DeliveredRPCError'),
    ('meme_machine.runtime.provider_clock', 'ProviderClockError'),
    ('meme_machine.runtime.usd_valuation', 'ValuationUnavailable'),
    ('sqlite3', 'OperationalError'), ('sqlite3', 'IntegrityError'),
    ('sqlite3', 'DatabaseError'), ('sqlite3', 'ProgrammingError'))
_ORIGIN_BOUNDARIES = frozenset((
    'selective_tape_warmup_incomplete', 'selective_shutdown_drain_timeout',
    'selective_discovery_range_identity', 'selective_discovery_log_shape',
    'selective_discovery_log_range_identity', 'selective_discovery_recovery_watermark',
    'selective_sequencer_start_timeout', 'selective_sequencer_timestamp_missing',
    'pons_startup_range_incomplete', 'pons_startup_reorg', 'pons_startup_header_identity',
    'pons_startup_boundary_incomplete', 'pons_startup_log_identity', 'pons_startup_log_conflict',
    'native_USD_value_missing_or_stale', 'isolated_native_observation_closed',
    'isolated_native_pons_current_already_owned', 'isolated_native_pons_current_paths',
    'isolated_native_pons_current_configuration', 'isolated_native_pons_current_source',
    'isolated_native_pons_current_owner', 'isolated_native_pons_current_foreign_state',
    'isolated_native_unexpected_financial_continuation'))


class ContainedNativeFailure(ValueError):
    """Only fixed local classifications cross the entrypoint boundary."""


def _worker_failure_origin(worker, error):
    """Bounded original worker classification, never exception or packet text."""
    kind = type(error)
    name = next((item.__name__ for item in _BUILTIN_ERRORS if kind is item), 'UNKNOWN')
    for module_name, class_name in _NATIVE_ERRORS:
        module = sys.modules.get(module_name)
        if module is not None and kind is getattr(module, class_name, None):
            name = class_name
            break
    result = dict(worker=worker, error_type=name, source_module=None, source_line=None,
        trace_complete=True)
    trace = BaseException.__traceback__.__get__(error, kind)
    frames = 0
    while trace is not None and frames < 64:
        module = trace.tb_frame.f_globals.get('__name__')
        if (type(module) is str and module in _ORIGIN_MODULES
                and trace.tb_frame.f_code.co_name != '_require'
                and 0 < trace.tb_lineno < 10000):
            result.update(source_module=module, source_line=trace.tb_lineno)
        trace = trace.tb_next
        frames += 1
    result['trace_complete'] = trace is None
    # A hostile/custom property is not permitted to replace the original error.
    try:number = getattr(error, 'errno', None)
    except BaseException:number = None
    if type(number) is int and 0 < number < 4096:result['error_number'] = number
    args = BaseException.args.__get__(error, kind)
    if (len(args) == 1 and type(args[0]) is str and len(args[0]) <= 100
            and args[0] in _ORIGIN_BOUNDARIES):
        result['boundary_code'] = args[0]
    return result


def worker_failure_details(error):
    """Project only this lifecycle's fixed bounded origin carrier at entry."""
    if type(error) is not ContainedNativeFailure:return []
    rows = getattr(error, '_worker_failures', ())
    if type(rows) is not tuple or len(rows) > len(_WORKERS):return []
    result = [];seen = set()
    types = {item.__name__ for item in _BUILTIN_ERRORS} | {name for _, name in _NATIVE_ERRORS} | {'UNKNOWN'}
    required = {'worker', 'error_type', 'source_module', 'source_line', 'trace_complete'}
    for row in rows:
        if type(row) is not dict or not required <= row.keys() <= required | {'error_number', 'boundary_code'}:return []
        worker = row['worker'];module = row['source_module'];line = row['source_line']
        if type(worker) is not str or worker not in _WORKERS or worker in seen:return []
        if type(row['error_type']) is not str or row['error_type'] not in types:return []
        if not ((module is None and line is None) or (type(module) is str and module in _ORIGIN_MODULES
                and type(line) is int and 0 < line < 10000)):return []
        if type(row['trace_complete']) is not bool:return []
        if 'error_number' in row and not (type(row['error_number']) is int and 0 < row['error_number'] < 4096):return []
        if 'boundary_code' in row and not (type(row['boundary_code']) is str and row['boundary_code'] in _ORIGIN_BOUNDARIES):return []
        seen.add(worker);result.append(dict(row))
    return result


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
    terminal=False
    try:
        os.environ.update(expected)
        yield
    except NativeOwnerDrainFailure:
        terminal=True
        raise
    finally:
        if not terminal:
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
    if len(raw)>65536:
        # The optional observations must never turn an otherwise admissible
        # native receipt into a runtime failure. Missing observations mean
        # UNKNOWN; preserve every original field and the original byte guard.
        projected=dict(value)
        projected.pop('native_commit_observations',None)
        for key in ('first_progress','last_progress'):
            if type(projected.get(key)) is dict:
                projected[key]=dict(projected[key])
                projected[key].pop('native_commit_observations',None)
        original=json.dumps(projected,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if len(original)<=65536 and original!=raw:
            collector=getattr(resources,'_native_commit_measurement',None)
            if collector is not None:collector.lost.set()
            value.clear();value.update(projected)
            raw=original
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
        workers, source_path, source_ready, seconds=EXECUTION_SECONDS,
        startup_seconds=SOURCE_START_SECONDS, shutdown_seconds=SHUTDOWN_SECONDS, progress=None,lifecycle=None):
    """Own all threads until joined, including failure and cancellation paths.

    The shortened arguments are private offline fixture controls. The public
    entrypoint supplies the fixed reviewed limits and actual native functions.
    """
    from meme_machine.runtime import stop
    from meme_machine.runtime.isolated_native_execution import isolated_native_execution
    from .isolated_native_lifetime import NativeLifecycleObservation,observe_lifecycle
    _require(lifecycle is None or type(lifecycle) is NativeLifecycleObservation,
        'isolated_native_lifecycle_observation')
    def observe(event,origin,**fields):
        observe_lifecycle(lifecycle,event,origin,**fields)
    _require(0 < seconds <= EXECUTION_SECONDS and 0 < startup_seconds <= SOURCE_START_SECONDS
        and 0 < shutdown_seconds <= SHUTDOWN_SECONDS, 'isolated_native_lifecycle_bound')
    _require(not stopped.is_set() and not stop.requested.is_set(),
        'isolated_native_already_stopped')
    began = time.monotonic()
    deadline = began + seconds
    source_stop = asyncio.Event()
    errors = []
    worker_failures = {}
    statuses = {}
    threads = []
    counts = dict(sizing_refreshes=0)
    lock = threading.Lock()

    def run_worker(name, call):
        observe('WORKER_STARTED','SOURCE_WORKER',worker=name)
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
        except BaseException as error:
            # Do not carry arbitrary provider content through exception text.
            origin = _worker_failure_origin(name, error)
            observe('WORKER_FAILED','SOURCE_WORKER',worker=name)
            with lock:
                errors.append('isolated_native_'+name+'_failed')
                worker_failures[name] = origin
        finally:
            observe('WORKER_ENDED','SOURCE_WORKER',worker=name)
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
            try:await source(source_stop)
            finally:observe('SOURCE_ENDED','SOURCE_LIFECYCLE')

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
        # The exact owner-issued anonymous command generation must be live.
        # This does not prove financial readiness or economic completeness.
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
                'isolated_native_source_commands_deadline')
            try:
                generation=source_ready()
            except ValueError:
                generation=None
            if generation is not None:
                _require(source_path.is_file() and not source_path.is_symlink(),
                    'isolated_native_source_commands_owner')
                observed_at = time.monotonic()
                observe('SOURCE_READY','SOURCE_LIFECYCLE')
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
        observe('STOP_REQUESTED','SOURCE_LIFECYCLE',
            reason=('LIFECYCLE_FAILURE' if failure is not None else
                'LIFECYCLE_WINDOW' if completed_window else 'LIFECYCLE_EXTERNAL_STOP'),
            prior_local=stopped.is_set(),prior_global=stop.requested.is_set())
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
            if failure is not None:
                receipt['primary_failure_code']=(str(failure) if type(failure) is ContainedNativeFailure
                    else 'isolated_native_runtime_failed')
            failure = ContainedNativeFailure('isolated_native_shutdown_incomplete')
        with lock:
            final_statuses = {key: dict(value) for key, value in statuses.items()}
            final_counts = dict(counts)
            origins = tuple(dict(worker_failures[name]) for name in _WORKERS if name in worker_failures)
            if errors and failure is None:
                failure = ContainedNativeFailure(errors[0])
        receipt.update(full_window_completed=completed_window,
            execution_window_seconds=seconds, startup_seconds=(None if observed_at is None
                else observed_at-began), observed_after_socket_seconds=(None if observed_at is None
                else shutdown_at-observed_at), elapsed_seconds=time.monotonic()-began,
            shutdown_seconds=time.monotonic()-shutdown_at, all_workers_joined=joined,
            source_joined=source_task.done(),graceful_shutdown=joined,
            workers=final_statuses, counters=final_counts,
            progress_samples=progress_samples,first_progress=first_progress,last_progress=last_progress,
            status='FAILED' if failure is not None else 'COMPLETED')
        if origins:
            receipt['worker_failures'] = list(origins)
            if type(failure) is ContainedNativeFailure:failure._worker_failures = origins
        if failure is not None:
            receipt['failure_code'] = (str(failure) if type(failure) is ContainedNativeFailure
                else 'isolated_native_runtime_failed')
        if not joined:
            receipt['cleanup_disposition']='OWNED_PROCESS_TERMINATION_REQUIRED'
            try:_persist(resources,receipt)
            except BaseException:receipt['failure_receipt_persisted']=False
            else:receipt['failure_receipt_persisted']=True
            # This is a typed terminal handoff, not a normal library error that
            # allows an entrypoint to close another live owner's connection.
            raise NativeOwnerDrainFailure(receipt)
        _persist(resources, receipt)
    if failure is not None:
        raise failure
    return receipt


def _run_owned_loop(awaitable):
    """Keep pending source/default-executor owners intact on terminal handoff."""
    runner=asyncio.Runner()
    terminal=None
    try:
        return runner.run(awaitable)
    except NativeOwnerDrainFailure as error:
        terminal=error
        error.retain(runner)
        raise
    finally:
        if terminal is None:
            runner.close()


def run_contained(*, resources, ports, sizing_reader, stopped):
    """Fixed entry integration: no URL, account, budget or runner alternatives."""
    from meme_machine.runtime.isolated_native_resources import require_resources
    from meme_machine.runtime.isolated_native_bootstrap import require_runner_ports
    from meme_machine.runtime.isolated_native_execution import isolated_native_execution
    resources = require_resources(resources)
    require_runner_ports(resources, ports)
    profiles=ports.require_pons_profiles()
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
        ports.require_pons_feed_source()
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
            # Keep the original 256 KiB progress writer/budget unchanged. Only
            # its existing first/last returned samples retain this bounded
            # in-memory diagnostic; no new per-sample disk rows are written.
            value['native_commit_observations']=resources.native_commit_snapshot()
            return value
        result=None
        def finish_metrics(value):
            value['private_output_bytes']=output.bytes
            value['private_progress_bytes']=progress_bytes
            value['native_provider_optimization_profiles']=[profile.value() for profile in profiles]
            value['native_commit_observations']=resources.native_commit_snapshot()
            value['unexercised']=[name for name in value.get('unexercised',[])
                if name!='authenticated_provider_optimization_profiles']
            # Never inspect a dictionary still owned by a live source task.
            if value.get('all_workers_joined'):
                value['source_rpc_counters']=_numeric(rpc.telemetry().get('counters', {}))
                value['source_pipeline_counters']=_numeric(driver.pipeline_metrics)
                value['source_drain_counters']=_numeric(driver.drain_snapshot())
            _persist(resources,value)
        terminal=None
        redirect=redirect_stdout(output)
        redirect.__enter__()
        try:
            result = _run_owned_loop(_run_lifecycle(resources=resources, stopped=stopped,
                sizing_reader=sizing_reader, source=source,
                workers=[('pump', pump_current), ('pons', pons_current)], source_path=source_path,
                source_ready=ports.require_source_commands_ready,progress=progress,
                lifecycle=ports.channel._lifecycle))
        except NativeOwnerDrainFailure as error:
            terminal=error
            # Leave global stdout and private paths on their original contained
            # owners until fixed PID1 exit; a live worker can still print/read.
            error.retain(output,progress_file,redirect,resources,ports)
            raise
        except BaseException:
            path=resources.root/'native-execution.json'
            if path.is_file() and not path.is_symlink() and path.stat().st_size<=65536:
                finish_metrics(json.loads(path.read_bytes()))
            raise
        finally:
            if terminal is None:
                redirect.__exit__(None,None,None)
                progress_file.close()
                output.close()
        finish_metrics(result)
        return result
