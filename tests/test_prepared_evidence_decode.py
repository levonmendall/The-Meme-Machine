"""Prepared outer decoding preserves the existing lossless codec contract."""
import copy
import asyncio
from concurrent.futures import Future
import hashlib
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import zlib

from meme_machine import solana_evidence_storage as storage


LIMIT = 16 * 1024 * 1024


def compressed(value):
    return b'SEP1' + zlib.compress(json.dumps(value, separators=(',', ':')).encode(), 1)


def fixture():
    body = dict(identity='native-economic-record', payload=dict(
        event=dict(mint='retained-mint', nested=[dict(value=7)]),
        raw_lineage=dict(logs=['first-' + 'a' * 600 for _ in range(4)]),
        meta=dict(logMessages=['second-' + 'b' * 600 for _ in range(4)])))
    encoded, chunks = storage.prepare(body)
    return body, encoded, chunks


class NoDB:
    def execute(self, *args, **kwargs):
        raise AssertionError('unexpected database read')


class PreparedEvidenceDecodeTests(unittest.TestCase):
    def test_text_scalars_lists_and_literal_markers_keep_original_json_meaning(self):
        marker = {'_hot_log_chunk': 'a' * 64}
        values = [None, False, 17, 'scalar', ['list', marker],
            dict(payload=dict(raw_lineage=dict(logs=marker), meta=dict(logMessages=marker))),
            dict(payload=None)]
        for expected in values:
            with self.subTest(expected=expected):
                raw = json.dumps(expected)
                prepared = storage.prepare_decode(raw)
                self.assertFalse(prepared.compressed)
                self.assertEqual(prepared.references, ())
                self.assertEqual(prepared.inflated_outer_bytes, len(raw.encode()))
                self.assertEqual(storage.finish_decode(prepared, NoDB(), chunks=object(),
                    decoded_chunks=object()), expected)
                self.assertEqual(storage.decode(raw, NoDB()), expected)

    def test_text_utf8_width_does_not_add_surrogate_rejection(self):
        for value in ('é', '\ud800'):
            raw = '"' + value + '"'
            prepared = storage.prepare_decode(raw)
            self.assertEqual(prepared.inflated_outer_bytes,
                len(raw.encode('utf-8', 'surrogatepass')))
            self.assertEqual(storage.finish_decode(prepared), value)
            self.assertEqual(storage.decode(raw), value)

    def test_actual_encoder_two_chunks_prepare_without_io_and_finish_real_sqlite(self):
        body, encoded, chunks = fixture()
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(len(chunks), 2)
        prepared = storage.prepare_decode(encoded)
        self.assertTrue(prepared.compressed)
        self.assertEqual(prepared.inflated_outer_bytes, len(zlib.decompress(encoded[4:])))
        self.assertEqual(prepared.references, (
            ('raw_lineage', 'logs', chunks[0][0]), ('meta', 'logMessages', chunks[1][0])))
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL)')
            db.executemany('INSERT INTO hot_chunks VALUES(?,?)', chunks)
            reads = []
            db.set_trace_callback(reads.append)
            self.assertEqual(storage.finish_decode(prepared, db), body)
            self.assertEqual(len(reads), 2)
            self.assertIn(chunks[0][0], reads[0])
            self.assertIn(chunks[1][0], reads[1])
            self.assertEqual(storage.decode(encoded, db), body)
        self.assertEqual(storage.decode(encoded, chunks=dict(chunks)), body)

    def test_only_actual_two_sep1_marker_paths_are_references(self):
        marker = {'_hot_log_chunk': 'a' * 64}
        value = dict(payload=dict(
            event=dict(logs=marker), raw_lineage=dict(logs=dict(marker, literal=True)),
            meta=['not a metadata mapping']))
        prepared = storage.prepare_decode(compressed(value))
        self.assertEqual(prepared.references, ())
        self.assertEqual(storage.finish_decode(prepared, NoDB()), value)

    def test_missing_first_chunk_precedes_malformed_second_checksum(self):
        raw = json.dumps(['first']).encode()
        first = hashlib.sha256(raw).hexdigest()
        value = dict(payload=dict(raw_lineage=dict(logs={'_hot_log_chunk': first}),
            meta=dict(logMessages={'_hot_log_chunk': []})))
        prepared = storage.prepare_decode(compressed(value))
        self.assertEqual(prepared.references[1][2], [])
        # Extracting references must not hash/coerce a later malformed value.
        with self.assertRaisesRegex(ValueError, '^hot_chunk_missing$'):
            storage.finish_decode(prepared, chunks={})
        with self.assertRaisesRegex(ValueError, '^hot_chunk_missing$'):
            storage.decode(compressed(value), chunks={})
        with self.assertRaises(TypeError):
            storage.decode(compressed(value), chunks={first: zlib.compress(raw)})

    def test_corrupt_or_wrong_hash_first_chunk_does_not_read_second(self):
        body, encoded, chunks = fixture()
        for broken, reason in ((b'not-zlib', 'hot_chunk_corrupt'),
                (zlib.compress(b'["different"]'), 'hot_chunk_hash_mismatch')):
            with self.subTest(reason=reason), sqlite3.connect(':memory:') as db:
                db.execute('CREATE TABLE hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL)')
                db.execute('INSERT INTO hot_chunks VALUES(?,?)', (chunks[0][0], broken))
                reads = []
                db.set_trace_callback(reads.append)
                with self.assertRaisesRegex(ValueError, '^' + reason + '$'):
                    storage.finish_decode(storage.prepare_decode(encoded), db)
                self.assertEqual(len(reads), 1)
                self.assertIn(chunks[0][0], reads[0])

    def test_original_encoding_json_and_payload_failure_classes_remain(self):
        for raw in (None, bytearray(b'SEP1'), b'', b'SEP2invalid'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, '^hot_body_encoding$'):
                storage.decode(raw)
        with self.assertRaisesRegex(ValueError, '^hot_body_corrupt$'):
            storage.prepare_decode(b'SEP1not-zlib')
        for raw in ('{', b'SEP1' + zlib.compress(b'{')):
            with self.assertRaises(json.JSONDecodeError):
                storage.decode(raw)
        for value, error in (({}, KeyError), ([], TypeError), (dict(payload=None), AttributeError)):
            with self.subTest(value=value), self.assertRaises(error):
                storage.decode(compressed(value))

    def test_prepared_outer_remains_owned_and_default_calls_do_not_share_payloads(self):
        body, encoded, chunks = fixture()
        prepared = storage.prepare_decode(encoded)
        result = storage.finish_decode(prepared, chunks=dict(chunks))
        self.assertIs(result, prepared.value)
        result['payload']['event']['nested'][0]['value'] = 99
        self.assertEqual(storage.finish_decode(prepared, NoDB()), result)
        fresh = storage.decode(encoded, chunks=dict(chunks))
        self.assertEqual(fresh, body)
        self.assertIsNot(fresh['payload']['raw_lineage']['logs'],
            result['payload']['raw_lineage']['logs'])

    def test_original_verified_decoded_cache_precedence_and_alias_semantics(self):
        body, encoded, chunks = fixture()
        cache = {}
        first = storage.decode(encoded, chunks=dict(chunks), decoded_chunks=cache)
        self.assertEqual(set(cache), {checksum for checksum, _ in chunks})
        second = storage.finish_decode(storage.prepare_decode(encoded), NoDB(),
            chunks={}, decoded_chunks=cache)
        self.assertEqual(second, body)
        for parent, key, checksum in storage.prepare_decode(encoded).references:
            self.assertIs(first['payload'][parent][key], cache[checksum][1])
            self.assertIs(second['payload'][parent][key], cache[checksum][1])

    def test_original_four_megabyte_decoded_cache_bound_is_preserved(self):
        body, encoded, chunks = fixture()
        cache = {'previous': (4 * 1024 * 1024, ['already cached'])}
        before = copy.deepcopy(cache)
        self.assertEqual(storage.decode(encoded, chunks=dict(chunks), decoded_chunks=cache), body)
        self.assertEqual(cache, before)

    def test_outer_inflation_exact_original_limit_and_one_byte_overflow(self):
        prefix, suffix = b'{"payload":{"value":"', b'"}}'
        for extra in (0, 1):
            raw = prefix + b'x' * (LIMIT - len(prefix) - len(suffix) + extra) + suffix
            encoded = b'SEP1' + zlib.compress(raw, 1)
            if extra:
                with self.assertRaisesRegex(ValueError, '^hot_chunk_bound_or_corruption$'):
                    storage.prepare_decode(encoded)
            else:
                prepared = storage.prepare_decode(encoded)
                self.assertEqual(prepared.inflated_outer_bytes, LIMIT)
                self.assertEqual(len(storage.finish_decode(prepared)['payload']['value']),
                    LIMIT - len(prefix) - len(suffix))

    def test_plain_text_has_no_new_sixteen_megabyte_history_limit(self):
        raw = '"' + 'x' * LIMIT + '"'
        prepared = storage.prepare_decode(raw)
        self.assertEqual(prepared.inflated_outer_bytes, LIMIT + 2)
        self.assertEqual(len(storage.finish_decode(prepared)), LIMIT)

    def test_chunk_keeps_original_inflation_bound(self):
        value = dict(payload=dict(raw_lineage=dict(logs={'_hot_log_chunk': 'a' * 64})))
        raw = compressed(value)
        with self.assertRaisesRegex(ValueError, '^hot_chunk_bound_or_corruption$'):
            storage.finish_decode(storage.prepare_decode(raw),
                chunks={'a' * 64: zlib.compress(b'x' * (LIMIT + 1), 1)})


class ControlledPreparationExecutor:
    def __init__(self):self.jobs=[];self.closed=None
    def submit(self,fn,*args,**kwargs):
        future=Future();future.set_running_or_notify_cancel()
        self.jobs.append((future,fn,args,kwargs));return future
    def finish(self,index,*,error=None):
        future,fn,args,kwargs=self.jobs[index]
        if error is not None:future.set_exception(error)
        else:future.set_result(fn(*args,**kwargs))
    def shutdown(self,**kwargs):self.closed=kwargs


class PreparationPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_native_slot_and_native_continuation_before_maintenance(self):
        from meme_machine.solana_preparation_pool import PreparationPool
        executor=ControlledPreparationExecutor();pool=PreparationPool(executor)
        native=pool.native.submit(str,'native-1')
        optional=pool.try_submit_optional(str,'optional')
        waiting_native=pool.native.submit(str,'native-2')
        maintenance=pool.submit(str,'maintenance')
        self.assertEqual(len(executor.jobs),2)
        self.assertIsNone(pool.try_submit_optional(str,'must-not-queue'))
        executor.finish(0)
        self.assertEqual(executor.jobs[2][2],('native-2',))
        self.assertEqual(native.result(),'native-1')
        self.assertFalse(maintenance.done())
        executor.finish(1)
        self.assertEqual(executor.jobs[3][2],('maintenance',))
        executor.finish(2);executor.finish(3)
        self.assertEqual((optional.result(),waiting_native.result(),maintenance.result()),
            ('optional','native-2','maintenance'))
        self.assertTrue(all(value is None for value in pool.active.values()))

    async def test_cancelled_optional_waiter_keeps_physical_slot_and_queued_cancel_enqueues_nothing(self):
        from meme_machine.solana_preparation_pool import PreparationPool
        executor=ControlledPreparationExecutor();pool=PreparationPool(executor)
        optional=pool.try_submit_optional(str,'accepted')
        waiter=asyncio.ensure_future(asyncio.wrap_future(optional));await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):await waiter
        self.assertFalse(optional.cancel())
        self.assertIsNone(pool.try_submit_optional(str,'overlap'))
        maintenance=pool.submit(str,'cancel-before-admission')
        self.assertTrue(maintenance.cancel())
        native=pool.native.submit(str,'native')
        self.assertEqual(len(executor.jobs),2)
        executor.finish(0);executor.finish(1)
        self.assertEqual(optional.result(),'accepted');self.assertEqual(native.result(),'native')
        self.assertEqual(len(executor.jobs),2)
        successor=pool.try_submit_optional(str,'successor');self.assertIsNotNone(successor)
        executor.finish(2);self.assertEqual(successor.result(),'successor')

    async def test_submit_failure_and_native_queue_cancellation_release_only_their_reservations(self):
        from meme_machine.solana_preparation_pool import PreparationPool
        class Refusing(ControlledPreparationExecutor):
            def submit(self,*args,**kwargs):raise RuntimeError('offline-submit-failure')
        pool=PreparationPool(Refusing());failed=pool.try_submit_optional(str,'failure')
        with self.assertRaisesRegex(RuntimeError,'offline-submit-failure'):failed.result()
        self.assertTrue(all(value is None for value in pool.active.values()))
        executor=ControlledPreparationExecutor();pool=PreparationPool(executor)
        native=pool.native.submit(str,'native');queued=pool.native.submit(str,'cancelled')
        self.assertTrue(queued.cancel());successor=pool.native.submit(str,'successor')
        error=RuntimeError('offline-native-failure');executor.finish(0,error=error)
        with self.assertRaises(RuntimeError) as caught:native.result()
        self.assertIs(caught.exception,error)
        self.assertEqual(len(executor.jobs),2);executor.finish(1)
        self.assertEqual(successor.result(),'successor')

    async def test_shutdown_without_cancel_drains_accepted_maintenance_but_serve_close_cancels_pending(self):
        from meme_machine.solana_preparation_pool import PreparationPool
        for cancel in (False,True):
            with self.subTest(cancel=cancel):
                executor=ControlledPreparationExecutor();pool=PreparationPool(executor)
                active=pool.try_submit_optional(str,'active');queued=pool.submit(str,'mandatory')
                entered=threading.Event();finished=threading.Event()
                def close():
                    entered.set();pool.shutdown(wait=True,cancel_futures=cancel);finished.set()
                closer=threading.Thread(target=close,daemon=True);closer.start()
                await asyncio.to_thread(entered.wait,1)
                # The lock proves shutdown selected its policy before the test
                # completes the still-running physical operation.
                while not pool.closed:await asyncio.sleep(0)
                self.assertFalse(finished.is_set())
                executor.finish(0)
                if cancel:self.assertTrue(queued.cancelled())
                else:
                    self.assertEqual(len(executor.jobs),2);executor.finish(1)
                    self.assertEqual(queued.result(),'mandatory')
                await asyncio.to_thread(closer.join,1)
                self.assertTrue(finished.is_set());self.assertEqual(active.result(),'active')
                self.assertEqual(executor.closed,dict(wait=True,cancel_futures=cancel))


class ArchivePreparationHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_preparation_pool import PreparationPool
        self.source=SelectiveSource(SimpleNamespace(identity='a'*64),None,token='offline')
        self.source.stop=asyncio.Event();self.executor=ControlledPreparationExecutor()
        loop=asyncio.get_running_loop()
        self.pool=PreparationPool(self.executor,notify=lambda:loop.call_soon_threadsafe(
            self.source.archive_preparation_wakeup.notify))
        self.patch=patch('meme_machine.solana_economic_preparation.prepare_archive_transaction',
            lambda context,family,raw:raw)
        self.patch.start();self.tasks=[]
    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        for index,job in enumerate(self.executor.jobs):
            if not job[0].done():self.executor.finish(index)
        self.patch.stop()
    async def settle(self,predicate):
        for _ in range(100):
            if predicate():return
            await asyncio.sleep(0)
        self.fail('bounded handoff did not reach expected state')
    def task(self,coroutine):
        task=asyncio.create_task(coroutine);self.tasks.append(task);return task
    def job(self,*,priority=3,seconds=30):
        return dict(priority=priority,deadline=time.time()+seconds,family='pump')
    async def turn(self,raw,**kw):
        return await self.source._archive_preparation_turn(self.job(**kw),self.pool,'context',raw)

    async def test_eight_carriers_handoff_each_transaction_with_reserved_native_and_maintenance_first(self):
        native=self.pool.native.submit(str,'native')
        async def carrier(index):
            return [await self.turn(str(index)+'-'+str(part)) for part in range(2)]
        carriers=[self.task(carrier(index)) for index in range(8)]
        await self.settle(lambda:len(self.executor.jobs)==2)
        maintenance=self.pool.submit(str,'mandatory')
        self.executor.finish(1)
        self.assertEqual(self.executor.jobs[2][2],('mandatory',))
        self.assertFalse(carriers[1].done());self.executor.finish(2)
        for offset in range(15):
            expected=offset+3
            await self.settle(lambda:len(self.executor.jobs)>expected)
            # Each physical turn returns to the back of the eight-carrier FIFO.
            value=str((offset+1)%8)+'-'+str((offset+1)//8)
            self.assertEqual(self.executor.jobs[expected][2][-1],value)
            self.assertIsNone(self.pool.try_submit_optional(str,'must-not-overlap'))
            self.executor.finish(expected)
        results=await asyncio.gather(*carriers)
        self.assertEqual(results,[[str(i)+'-0',str(i)+'-1'] for i in range(8)])
        self.assertEqual(maintenance.result(),'mandatory');self.assertFalse(native.done())
        self.executor.finish(0);self.assertEqual(native.result(),'native')

    async def test_urgent_job_never_waits_for_busy_carrier_or_physical_slot(self):
        await self.source.archive_preparation_lock.acquire()
        try:self.assertIsNone(await asyncio.wait_for(self.turn('urgent-lock',priority=2),.2))
        finally:self.source.archive_preparation_lock.release()
        active=self.pool.try_submit_optional(str,'physical')
        self.assertIsNone(await asyncio.wait_for(self.turn('urgent-slot',priority=0),.2))
        self.assertEqual(len(self.executor.jobs),1);self.executor.finish(0)
        self.assertEqual(active.result(),'physical')

    async def test_urgent_release_woken_waiter_race_never_awaits_carrier_lock(self):
        lock=self.source.archive_preparation_lock
        await lock.acquire();waiter=self.task(lock.acquire());await asyncio.sleep(0)
        lock.release()
        self.assertFalse(lock.locked());self.assertFalse(waiter.done())
        original=self.pool.try_submit_optional
        def completed(*args,**kwargs):
            future=original(*args,**kwargs)
            if future is not None:self.executor.finish(0)
            return future
        with patch.object(self.pool,'try_submit_optional',completed):
            self.assertEqual(await self.turn('urgent-race',priority=1),'urgent-race')
        self.assertFalse(waiter.done()) # Urgent admission had no async lock wait.
        await waiter;lock.release()
        self.assertEqual(len(self.executor.jobs),1)

    async def test_canceled_carrier_releases_turn_but_not_accepted_physical_slot(self):
        first=self.task(self.turn('first'));await self.settle(lambda:len(self.executor.jobs)==1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        self.assertFalse(self.source.archive_preparation_lock.locked())
        second=self.task(self.turn('second'));await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertEqual(len(self.executor.jobs),1)
        self.executor.finish(0);await self.settle(lambda:len(self.executor.jobs)==2)
        self.executor.finish(1);self.assertEqual(await second,'second')

    async def test_stop_and_original_deadline_bound_wait_without_new_admission(self):
        active=self.pool.try_submit_optional(str,'physical')
        timed=self.task(self.turn('expired',seconds=.02))
        self.assertIsNone(await asyncio.wait_for(timed,.5))
        stopped=self.task(self.turn('stopped'));await asyncio.sleep(0);self.source.stop.set()
        self.assertIsNone(await asyncio.wait_for(stopped,.5))
        self.assertEqual(len(self.executor.jobs),1);self.executor.finish(0)
        self.assertEqual(active.result(),'physical')
        self.assertFalse(self.source.archive_preparation_lock.locked())

    async def test_epoch_before_admission_closes_inline_release_lost_wakeup(self):
        original=self.pool.try_submit_optional;calls=[]
        def racing(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:
                self.source.archive_preparation_wakeup.notify();return None
            future=original(*args,**kwargs)
            self.executor.finish(0)
            return future
        with patch.object(self.pool,'try_submit_optional',racing):
            self.assertEqual(await asyncio.wait_for(self.turn('race'),.5),'race')
        self.assertEqual(len(calls),2)

    async def test_accepted_result_does_not_depend_on_advisory_notification(self):
        self.pool.notify=lambda:(_ for _ in ()).throw(RuntimeError('offline-notifier'))
        task=self.task(self.turn('actual-future'))
        await self.settle(lambda:len(self.executor.jobs)==1)
        self.executor.finish(0)
        self.assertEqual(await asyncio.wait_for(task,.5),'actual-future')

    async def test_accepted_stop_and_deadline_release_carrier_without_freeing_physical_slot(self):
        for stop in (False,True):
            with self.subTest(stop=stop):
                self.source.stop.clear();index=len(self.executor.jobs)
                task=self.task(self.turn('accepted',seconds=30 if stop else .02))
                await self.settle(lambda:len(self.executor.jobs)>index)
                if stop:self.source.stop.set()
                self.assertIsNone(await asyncio.wait_for(task,.5))
                self.assertIsNone(self.pool.try_submit_optional(str,'overlap'))
                self.assertFalse(self.source.archive_preparation_lock.locked())
                self.executor.finish(index)
        self.source.stop.clear()

    async def test_notifier_failure_never_hides_terminal_result_or_slot_release(self):
        self.pool.notify=lambda:(_ for _ in ()).throw(RuntimeError('offline-notifier'))
        future=self.pool.try_submit_optional(str,'retained')
        self.executor.finish(0)
        self.assertEqual(future.result(),'retained')
        self.assertTrue(all(value is None for value in self.pool.active.values()))


if __name__ == '__main__':
    unittest.main()
