"""Anonymous, child-local transport for the unchanged native command protocol.

This owns connected descriptors and source generations, not commands or SQLite.
The actual service consumer, PendingCommands and PriorityOwner remain the only
command interpreters. No descriptor is sent to another process or to the parent.
"""
import asyncio
from collections import deque
import socket
import stat
import threading


PENDING_CONNECTIONS = 32  # Original listener backlog.
ACTIVE_CONNECTIONS = 32  # Original service consumer admission bound.


class _CommandConnector:
    __slots__ = ('_hub', '_generation', 'owner')

    def __init__(self, hub, generation, owner):
        object.__setattr__(self, '_hub', hub)
        object.__setattr__(self, '_generation', generation)
        object.__setattr__(self, 'owner', owner)

    def __setattr__(self, name, value):
        raise AttributeError('immutable_native_command_connector')

    def connect(self):
        # The caller retains its original attempt/overall deadlines and wire
        # envelope. A stale facade never silently adopts a new source owner.
        return self._hub.connect(self)


class _SourceGeneration:
    def __init__(self, hub, consumer):
        self.hub = hub
        self.loop = asyncio.get_running_loop()
        self.consumer = consumer
        self.lock = threading.Lock()
        self.pending = deque()
        self.active = {}
        self.wake_scheduled = False
        self.closing = False
        self.closed = False

    def connect(self):
        # Reserve the bounded pending slot before allocating either descriptor.
        # Only one coalesced wakeup is queued, never an unbounded callback/FD
        # list. The lock is released before all stream or provider I/O.
        with self.lock:
            if self.closing or self.closed or self.loop.is_closed():
                raise OSError('isolated_native_command_source_unavailable')
            if len(self.pending) >= PENDING_CONNECTIONS:
                raise OSError('evidence_control_overloaded')
            client, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            self.pending.append(peer)
            if not self.wake_scheduled:
                self.wake_scheduled = True
                try:
                    self.loop.call_soon_threadsafe(self._pump)
                except RuntimeError:
                    self.pending.pop()
                    self.wake_scheduled = False
                    client.close()
                    peer.close()
                    raise OSError('isolated_native_command_source_unavailable') from None
            return client

    def _pump(self):
        while True:
            with self.lock:
                self.wake_scheduled = False
                if self.closing or not self.pending or len(self.active) >= ACTIVE_CONNECTIONS:
                    return
                peer = self.pending.popleft()
                task = self.loop.create_task(self._serve(peer))
                self.active[task] = peer
                task.add_done_callback(self._done)

    async def _serve(self, peer):
        from meme_machine.solana_evidence_control import MAX_COMMAND_BYTES
        writer = None
        try:
            # Supplying an already-connected socket does not call connect(),
            # bind(), listen(), accept(), sendmsg() or recvmsg(). Keep the real
            # line limit and invoke the exact existing one-command handler.
            reader, writer = await asyncio.open_unix_connection(
                sock=peer, limit=MAX_COMMAND_BYTES + 1)
            await self.consumer(reader, writer)
        finally:
            if writer is None:
                peer.close()
            else:
                writer.close()

    def _done(self, task):
        # Match the existing service's connection ownership: disconnect may
        # fail its waiter but cannot cancel an accepted PriorityOwner future.
        if not task.cancelled():
            task.exception()
        with self.lock:
            peer = self.active.pop(task)
        # A task cancelled before its coroutine's first turn still owns this
        # descriptor; its coroutine finally block has not run in that case.
        peer.close()
        self._pump()

    async def close(self):
        if asyncio.get_running_loop() is not self.loop:
            raise ValueError('isolated_native_command_source_loop')
        with self.lock:
            self.closing = True
            peers = list(self.pending)
            self.pending.clear()
            tasks = list(self.active)
        for peer in peers:
            peer.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        with self.lock:
            self.closed = True

    def snapshot(self):
        with self.lock:
            return dict(pending=len(self.pending), active=len(self.active),
                closing=self.closing, closed=self.closed)


class NativeCommandHub:
    """One exact resource/port capability and one unreplaced source owner."""
    def __init__(self, resources, ports):
        from .isolated_native_bootstrap import require_runner_ports
        require_runner_ports(resources, ports)
        self.resources = resources
        self.ports = ports
        self.generation = None
        self.lock = threading.Lock()

    def _owned(self):
        from .isolated_native_bootstrap import require_runner_ports
        require_runner_ports(self.resources, self.ports)
        if self.ports._stores.get('source_commands') is not self:
            raise ValueError('isolated_native_command_hub_identity')

    def _database(self):
        path = self.resources.root/'solana-evidence.sqlite'
        try:
            info = path.lstat()
        except OSError:
            raise ValueError('isolated_native_source_owner_not_started') from None
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ValueError('isolated_native_source_database_owner')

    def start(self, consumer):
        # Port close checks retirement and closes caches under this same
        # lifecycle lock. A separate hub-only recheck leaves a race between
        # require_retired() returning and the port's closed flag publication.
        with self.ports._lock:
            self._owned()
            self._database()
            with self.lock:
                if self.generation is not None:
                    raise ValueError('isolated_native_command_source_owned')
                generation = _SourceGeneration(self, consumer)
                self.generation = generation
                return generation

    def ready(self):
        self._owned()
        self._database()
        with self.lock:
            generation = self.generation
            if generation is None:
                raise ValueError('isolated_native_command_source_not_started')
            with generation.lock:
                if generation.closing or generation.closed:
                    raise ValueError('isolated_native_command_source_unavailable')
            return generation

    def connector(self, owner):
        if owner not in ('pump', 'pump:survivor'):
            raise ValueError('isolated_native_evidence_consumer')
        return _CommandConnector(self, self.ready(), owner)

    def connect(self, connector):
        self._owned()
        with self.lock:
            if (type(connector) is not _CommandConnector or connector._hub is not self
                    or connector._generation is not self.generation):
                raise OSError('isolated_native_command_source_generation')
            return connector._generation.connect()

    async def close(self, generation):
        self._owned()
        with self.lock:
            if type(generation) is not _SourceGeneration or generation is not self.generation:
                raise ValueError('isolated_native_command_source_generation')
        await generation.close()

    def retire(self, generation):
        # Called only after serve has joined the original SQLite owner and all
        # executors. Closing sockets alone never permits a replacement owner.
        self._owned()
        with self.lock:
            if type(generation) is not _SourceGeneration or generation is not self.generation:
                raise ValueError('isolated_native_command_source_generation')
            state = generation.snapshot()
            if not state['closed'] or state['active'] or state['pending']:
                raise ValueError('isolated_native_command_source_not_drained')
            self.generation = None

    def require_retired(self):
        with self.lock:
            if self.generation is not None:
                raise ValueError('isolated_native_command_source_owned')
