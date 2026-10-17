"""Bounded, semaphore-free spawn workers for the owned isolated native source.

The native preparation functions are unchanged. Each fresh interpreter has one
task reader and one result writer, so there is no shared multiprocess queue,
named semaphore, lock file, descriptor transfer or resource-sharer server.
"""
from collections import deque
from concurrent.futures import Executor, Future, InvalidStateError
from concurrent.futures.process import BrokenProcessPool, _ExceptionWithTraceback
from dataclasses import dataclass
import io
import mmap
import multiprocessing
from multiprocessing.connection import _ConnectionBase
from multiprocessing.reduction import ForkingPickler
import signal
import socket
import threading


MAX_FRAME_BYTES = 64 * 1024 * 1024


class NativeExecutorCapacityError(RuntimeError):
    pass


class _LimitedBuffer(io.BytesIO):
    def write(self, value):
        if self.tell() + len(value) > MAX_FRAME_BYTES:
            raise NativeExecutorCapacityError('isolated_native_worker_frame_bound')
        return super().write(value)


class _DataPickler(ForkingPickler):
    def reducer_override(self, value):
        # Ordinary ForkingPickler would start a pathname resource-sharer and
        # transfer these with SCM_RIGHTS. Native jobs contain immutable data,
        # never capabilities; reject before the registered reducer can run.
        if (isinstance(value, (socket.socket, io.IOBase, mmap.mmap, _ConnectionBase))
                or type(value).__module__ in ('multiprocessing.resource_sharer',
                    'multiprocessing.synchronize', '_multiprocessing')):
            raise NativeExecutorCapacityError('isolated_native_worker_capability_forbidden')
        return NotImplemented


def _pack(value):
    buffer = _LimitedBuffer()
    _DataPickler(buffer, 5).dump(value)
    return buffer.getvalue()


def _worker(task_reader, result_writer, initializer):
    """Fixed spawn target; the original native initializer runs before work."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        if initializer is not None:
            initializer()
        while True:
            try:
                request = task_reader.recv_bytes(MAX_FRAME_BYTES)
            except EOFError:
                # Only the owner has this pipe's writer. Its disappearance
                # ends the worker without inventing a result for any task.
                return
            item = ForkingPickler.loads(request)
            del request
            if item is None:
                return
            identity, function, args, kwargs = item
            del item
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                result = None
                error = _ExceptionWithTraceback(exc, exc.__traceback__)
            else:
                error = None
            try:
                response = _pack((identity, result, error))
            except BaseException as exc:
                response = _pack((identity, None,
                    _ExceptionWithTraceback(exc, exc.__traceback__)))
            del result, error, args, kwargs, function
            result_writer.send_bytes(response)
            del response
    finally:
        task_reader.close()
        result_writer.close()


@dataclass
class _Work:
    identity: int
    future: Future
    function: object
    args: tuple
    kwargs: dict


class IsolatedSpawnExecutor(Executor):
    """Actual spawn processes, original Futures, explicit owned shutdown.

    At most W running and W+1 waiting tasks are retained. The configured source
    already bounds native input/results; the additional serialized frame bound
    refuses oversize work explicitly. Accepted work is never silently retried.
    A worker death breaks its whole pool, as ProcessPoolExecutor does; the
    original HistoryExecutor alone decides when to construct a replacement.
    """
    def __init__(self, *, max_workers, initializer, role):
        if (type(max_workers) is not int or (role, max_workers) not in
                (('decoder', 2), ('history', 1)) or not callable(initializer)):
            raise ValueError('isolated_native_worker_configuration')
        self._max_workers = max_workers
        self._initializer = initializer
        self._role = role
        self._max_tasks = 2 * max_workers + 1
        self._condition = threading.Condition()
        self._queue = deque()
        self._items = {}
        self._next_identity = 0
        self._shutdown_thread = False
        self._broken = False
        self._termination_failed = False
        self._processes = {}
        self._threads = []
        self._channels = []
        self._started = False
        from .isolated_native_spawn import current_spawn_scope
        self._kernel_counts=(dict(returned=0,successful=0,probe_successful=0)
            if current_spawn_scope() is not None else None)

    def _start_owned(self):
        """Lazy startup: the caller owns this executor before any child exists.

        Called under the condition before accepting the first Future. Partial
        startup remains on this already-registered owner; no inline join can
        freeze the source loop or bypass its existing outer shutdown fence.
        """
        self._started = True
        context = multiprocessing.get_context('spawn')
        try:
            for index in range(self._max_workers):
                task_reader, task_writer = context.Pipe(duplex=False)
                result_reader, result_writer = context.Pipe(duplex=False)
                try:
                    process = context.Process(target=_worker,
                        args=(task_reader, result_writer, self._initializer),
                        name=f'isolated-native-{self._role}-{index}')
                    from .isolated_native_spawn import pool_start
                    with pool_start(self._role):process.start()
                except BaseException:
                    task_writer.close()
                    result_reader.close()
                    raise
                finally:
                    task_reader.close()
                    result_writer.close()
                self._processes[process.pid] = process
                self._channels.append((process, task_writer, result_reader))
            for process, writer, reader in self._channels:
                thread = threading.Thread(target=self._own_worker,
                    args=(process, writer, reader),
                    name=f'isolated-native-result-{process.pid}', daemon=True)
                self._threads.append(thread)
                thread.start()
        except BaseException as error:
            self._break_pool()
            for process, writer, reader in self._channels:
                writer.close()
                reader.close()
            raise BrokenProcessPool('isolated_native_worker_start_failed') from error

    def submit(self, function, /, *args, **kwargs):
        with self._condition:
            if self._broken:
                raise BrokenProcessPool(self._broken)
            if self._shutdown_thread:
                raise RuntimeError('cannot schedule new futures after shutdown')
            if len(self._items) >= self._max_tasks:
                raise NativeExecutorCapacityError('isolated_native_worker_task_bound')
            if not self._started:
                self._start_owned()
            future = Future()
            work = _Work(self._next_identity, future, function, args, kwargs)
            self._next_identity += 1
            self._items[work.identity] = work
            self._queue.append(work)
            self._condition.notify()
            return future

    def _take(self, process):
        with self._condition:
            while True:
                if self._broken:
                    return None
                if self._queue:
                    return self._queue.popleft()
                if self._shutdown_thread:
                    return None
                if not process.is_alive():
                    raise BrokenProcessPool('isolated_native_worker_died')
                self._condition.wait(.05)

    def _finished(self, work, *, value=None, error=None):
        with self._condition:
            present = self._items.pop(work.identity, None)
            self._condition.notify_all()
        if present is None or work.future.done():
            return
        if error is None:
            work.future.set_result(value)
        else:
            work.future.set_exception(error)

    def _own_worker(self, process, writer, reader):
        try:
            while True:
                work = self._take(process)
                if work is None:
                    break
                if not work.future.set_running_or_notify_cancel():
                    with self._condition:
                        self._items.pop(work.identity, None)
                    continue
                try:
                    request = _pack((work.identity, work.function, work.args, work.kwargs))
                except BaseException as exc:
                    self._finished(work, error=exc)
                    continue
                probe=(getattr(work.function,'__module__',None)=='meme_machine.solana_evidence_service'
                    and getattr(work.function,'__name__',None)=='source_decoder_probe')
                work.function = None
                work.args = ()
                work.kwargs = {}
                writer.send_bytes(request)
                del request
                identity, value, error = ForkingPickler.loads(reader.recv_bytes(MAX_FRAME_BYTES))
                if identity != work.identity or (error is not None and not isinstance(error, BaseException)):
                    raise RuntimeError('isolated_native_worker_result_identity')
                if self._kernel_counts is not None:
                    with self._condition:
                        self._kernel_counts['returned']+=1
                        if error is None:
                            self._kernel_counts['successful']+=1
                            if probe:self._kernel_counts['probe_successful']+=1
                self._finished(work, value=value, error=error)
                del value, error, work
            if not self._broken:
                writer.send_bytes(_pack(None))
        except BaseException:
            self._break_pool()
        finally:
            writer.close()
            reader.close()
            process.join()

    def _break_pool(self):
        with self._condition:
            if self._broken:
                return
            self._broken = 'isolated_native_worker_died_or_transport_failed'
            self._shutdown_thread = True
            unfinished = list(self._items.values())
            self._items.clear()
            self._queue.clear()
            self._condition.notify_all()
        for process in self._processes.values():
            try:
                if process.is_alive():
                    process.terminate()
            except OSError:
                # The original outer owner fence still requires actual join.
                # A denied signal cannot strand Future completion or turn an
                # unjoined process into an asserted graceful shutdown.
                self._termination_failed = True
        for work in unfinished:
            try:
                work.future.set_exception(BrokenProcessPool(self._broken))
            except InvalidStateError:
                # Queued callers can cancel concurrently with a worker crash.
                # Keep completing every other accepted Future and joining all
                # owners, even when that cancellation wins this exact race.
                pass

    def shutdown(self, wait=True, *, cancel_futures=False):
        if wait and threading.current_thread() in self._threads:
            raise RuntimeError('isolated_native_worker_shutdown_from_owner')
        cancelled = []
        with self._condition:
            self._shutdown_thread = True
            if cancel_futures:
                while self._queue:
                    work = self._queue.popleft()
                    self._items.pop(work.identity, None)
                    cancelled.append(work.future)
            self._condition.notify_all()
        for future in cancelled:
            future.cancel()
        if wait:
            for thread in self._threads:
                if thread.ident is not None:
                    thread.join()
            # A partial first-submit startup may have no started owner thread
            # for one child. It is still owned, and must join before return.
            for process in self._processes.values():
                process.join()

    def kernel_lifecycle_snapshot(self):
        """Only the explicit copied profile records actual post-join counts."""
        with self._condition:
            if self._kernel_counts is None:return dict(state='UNAVAILABLE')
            if not self._shutdown_thread or any(thread.is_alive() for thread in self._threads):
                return dict(state='UNJOINED')
            joined=sum(process.exitcode is not None for process in self._processes.values())
            return dict(state='JOINED' if joined==len(self._processes) else 'UNJOINED',
                role=self._role,spawned=len(self._processes),joined=joined,
                zero_exit=sum(process.exitcode==0 for process in self._processes.values()),
                broken=bool(self._broken),termination_failed=self._termination_failed,
                submitted=self._next_identity,**self._kernel_counts)

