"""Real anonymous command transport, native owner and durable receipt tests."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import contextvars
from dataclasses import replace
import json
from functools import partial
from pathlib import Path
import socket
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape, PUMP_SCOPE
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.isolated_native_control import ACTIVE_CONNECTIONS, PENDING_CONNECTIONS
from meme_machine.solana_evidence_plane import canonical
from tests.isolated_native_control_fixture import start_command_source
from tests import test_isolated_native_bootstrap as bootstrap


class AnonymousNativeControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await bootstrap.IsolatedNativeBootstrapTests.asyncSetUp(self)
        self.driver, self.close_source = await start_command_source(self)
        # Actual native consumers have their own threads. Sharing asyncio's
        # default pool with a command waiter can starve the source's checkpoint
        # worker while that worker holds the native owner handoff.
        self.commands = ThreadPoolExecutor(max_workers=24, thread_name_prefix='native-command-test')
        async def close_commands():
            await asyncio.to_thread(self.commands.shutdown, wait=True)
        self.addAsyncCleanup(close_commands)

    def plane(self, owner='pump'):
        value = self.ports.pump_evidence(owner)
        self.addCleanup(value.close)
        return value

    async def query(self, sql, args=()):
        return await self.driver.work(lambda state:state.writer.db.execute(sql, args).fetchall())

    async def command(self, plane=None, **request):
        context = contextvars.copy_context()
        call = partial((plane or self.plane()).command, **request)
        return await asyncio.get_running_loop().run_in_executor(self.commands, context.run, call)

    def envelope(self, **changes):
        return dict(op='counter', key='pump.anonymous', count=1, owner='pump',
            consumer='pump', request_id='actual-offline-command',
            expires_at=time.time()+3, **changes)

    async def test_current_and_survivor_real_commands_without_pathname_connections(self):
        current, survivor = self.plane(), self.plane('pump:survivor')
        began = time.monotonic()
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('pathname connect')):
            replies = await asyncio.gather(*(self.command(
                current if index%2 == 0 else survivor,
                op='counter', key='pump.anonymous', count=1) for index in range(24)),
                return_exceptions=True)
        failures = [row for row in replies if isinstance(row, BaseException)]
        if failures:
            self.fail(canonical(dict(elapsed=time.monotonic()-began,
                errors=[dict(type=type(row).__name__, code=str(row),
                    request=getattr(row, 'request', None)) for row in failures],
                source=await self.query('SELECT consumer,request_id,response FROM command_receipts'),
                ipc=await self.query("SELECT value FROM service_health WHERE key='ipc'"),
                scheduler=await self.query("SELECT value FROM service_health WHERE key='owner_scheduler'"),
                current=current.counts, survivor=survivor.counts,
                connections=self.ports.require_source_commands_ready().snapshot())))
        self.assertTrue(all(row['ok'] and row['state']=='applied' for row in replies))
        self.assertEqual(await self.query("SELECT value FROM counters WHERE key='pump.anonymous'"), [(24,)])
        self.assertEqual(await self.query('SELECT consumer,COUNT(*) FROM command_receipts GROUP BY consumer'),
            [('pump',12), ('pump:survivor',12)])
        self.assertFalse(Path(str(self.resources.root/'solana-evidence.sqlite')+'.sock').exists())
        self.assertFalse(self.physical.calls)

    async def test_lost_reply_retries_exact_envelope_and_rejects_conflict_and_expiry(self):
        plane = self.plane()
        request = self.envelope()
        client = plane._native_commands.connect()
        client.sendall((canonical(request)+'\n').encode())
        client.close()  # A lost waiter cannot undo the actual owner transaction.
        async with asyncio.timeout(2):
            while not await self.query('SELECT 1 FROM command_receipts WHERE request_id=?',
                    (request['request_id'],)):
                await asyncio.sleep(.005)
        reply = await self.command(plane, **request)
        self.assertEqual(reply, dict(ok=True, state='applied', request_id=request['request_id']))
        with self.assertRaisesRegex(ValueError, 'identity_conflict'):
            await self.command(plane, **dict(request, count=2))
        with self.assertRaisesRegex(ValueError, 'command_expired'):
            await self.command(plane, **dict(request,
                request_id='expired-offline-command', expires_at=time.time()-.1))
        self.assertEqual(await self.query("SELECT value FROM counters WHERE key='pump.anonymous'"), [(1,)])

    async def test_pending_retry_and_disconnected_handler_never_cancel_owner_work(self):
        plane = self.plane()
        entered, release = threading.Event(), threading.Event()
        blocker = asyncio.create_task(self.driver.work(
            lambda state:(entered.set(), release.wait(2)), 0))
        self.addCleanup(release.set)
        await asyncio.to_thread(entered.wait, 1)
        task = asyncio.create_task(self.command(plane, op='counter', key='pump.anonymous'))
        try:
            await asyncio.sleep(.6)  # Original .4s pending response and same-ID retry.
        finally:
            release.set()
        await blocker
        self.assertTrue((await task)['ok'])
        self.assertGreaterEqual(plane.counts.get('ipc_retries', 0), 1)
        self.assertEqual(await self.query("SELECT value FROM counters WHERE key='pump.anonymous'"), [(1,)])
        self.assertEqual(await self.query('SELECT COUNT(*) FROM command_receipts'), [(1,)])

    async def test_pair_backlog_is_bounded_and_eof_releases_every_descriptor(self):
        connector = self.ports._source_command_connector('pump')
        generation = self.ports.require_source_commands_ready()
        clients = [connector.connect() for _ in range(ACTIVE_CONNECTIONS)]
        try:
            async with asyncio.timeout(1):
                while generation.snapshot()['active'] != ACTIVE_CONNECTIONS:
                    await asyncio.sleep(.001)
            clients += [connector.connect() for _ in range(PENDING_CONNECTIONS)]
            with self.assertRaisesRegex(OSError, 'overloaded'):
                connector.connect()
            self.assertEqual(generation.snapshot()['pending'], PENDING_CONNECTIONS)
            self.assertEqual(generation.snapshot()['active'], ACTIVE_CONNECTIONS)
            with generation.lock:
                owned = [*generation.active.values(), *generation.pending]
        finally:
            for client in clients:client.close()
        async with asyncio.timeout(2):
            while generation.snapshot()['active'] or generation.snapshot()['pending']:
                await asyncio.sleep(.005)
        self.assertTrue(all(peer.fileno() == -1 for peer in owned))
        self.assertEqual(await self.query('SELECT COUNT(*) FROM command_receipts'), [(0,)])

    async def test_never_started_handler_cancellation_closes_its_original_peer(self):
        connector = self.ports._source_command_connector('pump')
        generation = self.ports.require_source_commands_ready()
        client = connector.connect()
        try:
            generation._pump()
            with generation.lock:
                task, peer = next(iter(generation.active.items()))
            task.cancel()  # Its coroutine finally block has not run yet.
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
            self.assertEqual(peer.fileno(), -1)
            self.assertEqual(generation.snapshot()['active'], 0)
        finally:client.close()

    async def test_cancelled_handler_does_not_cancel_accepted_native_mutation(self):
        from meme_machine.solana_evidence_control import PendingCommands
        entered, release = threading.Event(), threading.Event()
        blocker = asyncio.create_task(self.driver.work(
            lambda state:(entered.set(), release.wait(2)), 0))
        self.addCleanup(release.set)
        await asyncio.to_thread(entered.wait, 1)
        accepted = []
        original = PendingCommands.submit
        def submitted(pending, request):
            future = original(pending, request)
            accepted.append(future)
            return future
        plane = self.plane()
        request = self.envelope()
        client = plane._native_commands.connect()
        generation = self.ports.require_source_commands_ready()
        try:
            with patch.object(PendingCommands, 'submit', submitted):
                client.sendall((canonical(request)+'\n').encode())
                async with asyncio.timeout(1):
                    while not accepted:await asyncio.sleep(.001)
                with generation.lock:
                    handler = next(iter(generation.active))
                handler.cancel()
                await asyncio.gather(handler, return_exceptions=True)
                self.assertFalse(accepted[0].cancelled())
        finally:
            client.close()
            release.set()
        await blocker
        self.assertTrue((await asyncio.wrap_future(accepted[0]))['ok'])
        self.assertTrue((await self.command(plane, **request))['ok'])
        self.assertEqual(await self.query("SELECT value FROM counters WHERE key='pump.anonymous'"), [(1,)])

    async def test_consumer_restart_keeps_source_owner_and_closed_source_refuses_rebind(self):
        original = self.plane()
        generation = self.ports.require_source_commands_ready()
        await self.command(original, op='counter', key='pump.anonymous')
        original.close()
        restarted = self.plane()
        self.assertIs(self.ports.require_source_commands_ready(), generation)
        await self.command(restarted, op='counter', key='pump.anonymous')
        await self.ports._source_commands_close(generation)
        with self.assertRaisesRegex(ValueError, 'source_owned'):
            self.ports._source_commands_start(generation.consumer)
        with self.assertRaisesRegex(ValueError, 'source_owned'):
            self.ports.close()
        with self.assertRaisesRegex(ValueError, 'unacknowledged') as caught:
            await self.command(restarted, op='counter', key='pump.must_not_replay')
        self.assertEqual(caught.exception.request['key'], 'pump.must_not_replay')
        await self.close_source()  # Only actual native owner/executor joins retire it.
        with self.assertRaisesRegex(ValueError, 'not_started'):
            self.ports.require_source_commands_ready()
        self.assertEqual(await asyncio.to_thread(self._read_closed_counter), 2)

    async def test_foreign_generation_and_mutable_connector_cannot_select_source(self):
        from meme_machine.runtime.isolated_native_control import NativeCommandHub
        connector = self.ports._source_command_connector('pump')
        with self.assertRaises(AttributeError):connector.owner = 'another-consumer'
        foreign = NativeCommandHub(self.resources, self.ports)
        with self.assertRaisesRegex(ValueError, 'hub_identity'):
            foreign.connect(connector)
        with self.assertRaisesRegex(ValueError, 'hub_identity'):
            foreign.start(lambda reader, writer:None)
        with self.assertRaisesRegex(ValueError, 'source_generation'):
            await self.ports._source_commands_close(object())
        with self.assertRaisesRegex(ValueError, 'evidence_consumer'):
            self.ports._source_command_connector('unapproved-consumer')
        self.assertFalse(self.physical.calls)

    async def test_native_close_error_retains_generation_and_refuses_port_close(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        generation = self.ports.require_source_commands_ready()
        original = PriorityOwner.close
        joined = []
        def failed(owner):
            original(owner)
            joined.append(not owner.thread.is_alive())
            raise RuntimeError('offline-owner-close-failure')
        with patch.object(PriorityOwner, 'close', failed):
            with self.assertRaisesRegex(RuntimeError, 'offline-owner-close-failure'):
                await self.close_source()
        self.assertEqual(joined, [True])
        self.assertTrue(generation.snapshot()['closed'])
        with self.assertRaisesRegex(ValueError, 'source_owned'):
            self.ports.close()
        # Test-only recovery after independently proving the patched real owner
        # did join. An actual failed/unjoined owner never reaches this cleanup.
        self.ports._source_commands_retire(generation)

    async def test_source_start_and_completed_port_close_cannot_overlap(self):
        consumer = self.ports.require_source_commands_ready().consumer
        await self.close_source()
        hub = self.ports._source_command_hub()
        checked, attempted, completed = threading.Event(), threading.Event(), threading.Event()
        errors = []
        original = hub._database
        def gated_database():
            original()
            checked.set()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(completed.wait(.05))
        def close_ports():
            checked.wait(1)
            attempted.set()
            try:self.ports.close()
            except BaseException as error:errors.append(error)
            finally:completed.set()
        closer = threading.Thread(target=close_ports)
        closer.start()
        try:
            with patch.object(hub, '_database', gated_database):
                generation = self.ports._source_commands_start(consumer)
            await asyncio.to_thread(closer.join, 1)
            self.assertFalse(closer.is_alive())
            self.assertFalse(self.ports.closed)
            self.assertEqual([str(error) for error in errors], ['isolated_native_command_source_owned'])
            # This transport-only generation served no command and owns no new
            # SQLite actor; retire after its empty stream set is joined.
            await self.ports._source_commands_close(generation)
            self.ports._source_commands_retire(generation)
            self.ports.close()
            with self.assertRaisesRegex(ValueError, 'runner_ports'):
                self.ports._source_commands_start(consumer)
            self.assertIsNone(hub.generation)
        finally:
            checked.set()
            closer.join(1)

    def _read_closed_counter(self):
        with sqlite3.connect(self.resources.root/'solana-evidence.sqlite') as db:
            return db.execute("SELECT value FROM counters WHERE key='pump.anonymous'").fetchone()[0]

    async def test_original_tape_full_history_commit_precedes_actual_source_ack(self):
        from tests.test_solana_evidence_plane import record, proof
        now = self.resources.clock()
        event = dict(event_type='create', mint='offline-mint', slot=1,
            market_time=now-1, initial_real_token_reserves=1000)
        material = replace(record(slot=1, scope=PUMP_SCOPE, observed=now),
            market_time=now-1, addresses=('offline-mint',), transaction_index=0,
            payload=dict(event=event))
        def publish(state):
            state.writer.ingest([material], proof=proof(0, 1, scope=PUMP_SCOPE, at=now))
            state.writer.db.executemany('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                [(PUMP_SCOPE, slot, max(0,slot-1), 'fixture-hash', 'fixture-parent',
                  now-2+slot, '[]', 'offline-fixture', now, 1) for slot in (0,1)])
            state.fence.health('phase', 'ACTIVE')
            state.fence.health('heartbeat', now)
            state.fence.health('finalized_frontier:'+PUMP_SCOPE,
                dict(slot=1, time=now-1, seen=now))
        await self.driver.work(publish)
        plane = self.plane()
        history_path = self.resources.root/'candidate-history.sqlite'
        original = CandidateHistory.retain_pump_source_history
        observed = []
        def committed(history, rows, **kwargs):
            self.assertEqual(history.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            result = original(history, rows, **kwargs)
            with sqlite3.connect(self.resources.root/'solana-evidence.sqlite') as source:
                self.assertIsNone(source.execute('SELECT slot FROM consumers WHERE owner=?', ('pump',)).fetchone())
            observed.append(result)
            return result
        def consume():
            local = self.ports.pump_evidence('pump')
            try:
                with patch.dict('os.environ', MM_SOLANA_CANDIDATE_HISTORY_DB=str(history_path)):
                    return LocalPumpTape(local).events_since(0)
            finally:local.close()
        with patch.object(CandidateHistory, 'retain_pump_source_history', committed):
            await asyncio.to_thread(consume)
        self.assertEqual(observed, [1])
        self.assertEqual(await self.query('SELECT scope,slot FROM consumers WHERE owner=?', ('pump',)), [(PUMP_SCOPE,1)])
        with closing(CandidateHistory(history_path, clock=lambda:now)) as history:
            self.assertEqual(len(history.events('pump', 'offline-mint')), 1)
