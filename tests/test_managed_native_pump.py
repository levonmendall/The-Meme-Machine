"""Contained production-source contracts; no providers or original epoch files."""
import asyncio
from contextlib import closing, ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meme_machine.operational import managed_native_pump as managed


class ManagedPumpTests(unittest.TestCase):
    def test_market_head_does_not_confuse_sql_progress_or_invent_missing_arrivals(self):
        observer = managed.FinalizedHeadObserver()
        rpc = SimpleNamespace(call_delivered=Mock(side_effect=[
            (100, {}), TimeoutError('private-provider'), (102, {}), (99, {})]))
        first = observer.sample(rpc)
        self.assertEqual(first['slot'], 100)
        self.assertTrue(first['fresh'])
        failed = observer.sample(rpc)
        self.assertFalse(failed['fresh'])
        self.assertEqual(failed['observed_monotonic'], first['observed_monotonic'])
        self.assertNotIn('private-provider', json.dumps(failed))
        self.assertEqual(observer.sample(rpc)['slot'], 102)
        with self.assertRaisesRegex(ValueError, 'authenticated_head_regressed'):
            observer.sample(rpc)
        self.assertTrue(all(call.args == ('getSlot', [{'commitment':'finalized'}])
                            and call.kwargs == dict(priority=2)
                            for call in rpc.call_delivered.call_args_list))

    def pressured_head(self, *, background=False, cooldown=False):
        """Real admission/transport path, with a deterministic offline clock.

        A source producer always has a foreground ticket waiting. On each
        available physical turn it consumes that ticket through the real
        governor, retaining its absolute deadline, then queues its next turn.
        This models the sustained native repair pressure in the retained run;
        no request to a market provider or financial position is made.
        """
        from meme_machine.runtime.evidence_worker import RepairRPC, DeliveredRPCError
        from meme_machine.runtime.governor import Governor
        from meme_machine.runtime.provider_purchases import ledger
        now = [100.]
        starts = []
        path = self.parent / 'pressured-governor.sqlite'
        tickets = dict(position_zero=0, held_position=1, foreground=2)
        governor = None

        def sleep(seconds):
            now[0] += seconds
            with closing(sqlite3.connect(path)) as db:
                head = Governor._head(db, 'solana', now[0])
                ready = db.execute("SELECT max(next_at,cooldown) FROM pressure "
                                   "WHERE provider='solana'").fetchone()[0]
                if not head or head[0] not in tickets or now[0] < ready:
                    return
                name = head[0]
                deadline = db.execute('SELECT deadline FROM queue WHERE id=?',
                                      (name,)).fetchone()[0]
                db.execute('DELETE FROM queue WHERE id=?', (name,))
                db.commit()
            # Consume the producer's already queued turn through production
            # admission. Preserve its deadline when exchanging the fixture's
            # pending ticket for the actual governor-owned request ticket.
            priority = tickets[name]
            governor.acquire('solana', 'evidence', priority,
                deadline_seconds=deadline-now[0], methods=('getTransaction',))
            starts.append((priority, now[0]))
            if name == 'foreground':
                with closing(sqlite3.connect(path)) as db:
                    db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',
                        (name, 'solana', 'evidence', priority, now[0], now[0]+8))
                    db.commit()

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, maximum):
                return b'{"jsonrpc":"2.0","id":1,"result":777}'

        def transport(request, *, timeout):
            self.assertEqual(timeout, 8)
            self.assertEqual(json.loads(request.data)['method'], 'getSlot')
            starts.append((2, now[0]))
            return Response()

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,
                MM_SOLANA_EVIDENCE_PLANE_DB='isolated-pressure-fixture'))
            stack.enter_context(patch('meme_machine.operational.position_continuation.provider_interval',
                                      return_value=.5))
            stack.enter_context(patch('meme_machine.runtime.governor.time.monotonic',
                                      side_effect=lambda: now[0]))
            stack.enter_context(patch('meme_machine.runtime.governor._stop_sleep',
                                      side_effect=sleep))
            opened = stack.enter_context(patch(
                'meme_machine.runtime.evidence_worker.urllib.request.urlopen',
                side_effect=transport))
            governor = Governor(path)
            self.assertEqual(governor.solana_interval, .5)
            with closing(sqlite3.connect(path)) as db:
                db.execute('INSERT INTO pressure VALUES(?,?,?,?,?)',
                           ('solana', now[0], 0, 0, 0))
                for name, priority in tickets.items():
                    db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',
                        (name, 'solana', 'evidence', priority, 99.9, 107.9))
                db.commit()
            rpc = RepairRPC(self.config.endpoint, governor)
            if cooldown:
                # The second genuine rate event retains the existing sixteen-
                # second method/provider cooldown, beyond admission's8s bound.
                governor.rate_limited('solana', ('getSlot',))
                governor.rate_limited('solana', ('getSlot',))
            if background:
                with self.assertRaises(DeliveredRPCError) as failed:
                    rpc.call('getSlot', [dict(commitment='finalized')])
                self.assertEqual(failed.exception.cause_kind, 'TimeoutError')
                result = None
            else:
                result = managed.FinalizedHeadObserver().sample(rpc)
            purchases = ledger(rpc).snapshot()['totals']
            with closing(sqlite3.connect(path)) as db:
                audit = db.execute('SELECT priority,granted FROM grants ORDER BY id').fetchall()
                pending = db.execute('SELECT id FROM queue ORDER BY id').fetchall()
            return dict(result=result, starts=starts, elapsed=now[0]-100.,
                opened=opened.call_count, counters=dict(rpc.counts),
                purchases=purchases, audit=audit, pending=pending)

    def test_background_head_starves_under_real_foreground_governor_pressure(self):
        result = self.pressured_head(background=True)
        self.assertEqual(result['opened'], 0)
        self.assertGreaterEqual(result['elapsed'], 8)
        self.assertLess(result['elapsed'], 8.1)
        self.assertEqual(result['audit'][-1], (4, 0))
        self.assertEqual(result['counters']['physical_requests'], 0)

    def test_required_head_uses_foreground_turn_behind_held_protection(self):
        result = self.pressured_head()
        self.assertEqual([priority for priority, _ in result['starts']], [0, 1, 2, 2])
        starts = [at for _, at in result['starts']]
        self.assertTrue(all(b-a >= .5-1e-9 for a, b in zip(starts, starts[1:])))
        self.assertLess(result['elapsed'], 2)
        self.assertEqual(result['result']['slot'], 777)
        self.assertTrue(result['result']['fresh'])
        self.assertEqual(result['audit'][-1], (2, 1))
        self.assertEqual(result['pending'], [('foreground',)])
        self.assertEqual(result['opened'], 1)
        for counter in ('physical_requests', 'logical_calls', 'method:getSlot'):
            self.assertEqual(result['counters'][counter], 1)
        # call_delivered performs both consumer and physical accounting once.
        for counter in ('logical_consumers', 'physical_requests', 'completed_requests'):
            self.assertEqual(result['purchases'][counter], 1)

    def test_foreground_head_still_respects_shared_rate_limit_cooldown(self):
        result = self.pressured_head(cooldown=True)
        self.assertEqual(result['opened'], 0)
        self.assertFalse(result['result']['fresh'])
        self.assertEqual(result['result']['failures'], 1)
        self.assertNotIn('slot', result['result'])
        self.assertEqual(result['audit'][-1], (2, 0))
        self.assertGreaterEqual(result['elapsed'], 8)
        self.assertLess(result['elapsed'], 8.1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.root = self.parent / 'pump'
        self.root.mkdir(mode=0o700)
        self.usage = self.parent / 'provider-usage.sqlite'
        self.profile = self.parent / 'continuous.json'
        self.usage.write_bytes(b'')
        self.profile.write_text('{}')
        self.usage.chmod(0o600)
        self.profile.chmod(0o600)
        self.config = managed.PumpManagedConfig(self.root, 'a' * 32, 'request_1',
            'b' * 40, 'https://solana-mainnet.g.alchemy.com/v2/not-a-real-key',
            self.usage, self.profile, token='not-a-real-native-token')
        clean = {k: v for k, v in os.environ.items() if not k.startswith('MM_')}
        self.env = patch.dict(os.environ, clean, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.started = patch.object(managed, '_started', False)
        self.started.start()
        self.addCleanup(self.started.stop)

    def test_fresh_marker_contains_only_public_identity_and_pins_source(self):
        identity = managed.prepare_generation(self.config)
        self.assertFalse(identity['financial_authority'])
        self.assertTrue(identity['canonical_history_delivery'])
        self.assertFalse(identity['economic_strategy_evaluation'])
        raw = (self.root / managed.MARKER).read_text()
        self.assertNotIn('not-a-real-key', raw)
        self.assertNotIn(self.config.token, raw)
        self.assertNotIn('not-a-real-key', repr(self.config))
        self.assertEqual(managed.prepare_generation(self.config, restart=True), identity)
        with self.assertRaisesRegex(ValueError, 'generation_identity_changed'):
            managed.prepare_generation(replace(self.config, source_revision='c' * 40), restart=True)
        with self.assertRaisesRegex(ValueError, 'generation_identity_changed'):
            managed.prepare_generation(replace(self.config, token='different-native-token'), restart=True)
        self.profile.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'generation_identity_changed'):
            managed.prepare_generation(self.config, restart=True)

    def test_nonempty_financial_and_linked_roots_fail_before_any_work(self):
        sentinel = self.root / 'old-state'
        sentinel.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'fresh_root_required'):
            managed.prepare_generation(self.config)
        sentinel.unlink()
        (self.parent / 'portfolio.sqlite').write_bytes(b'original financial evidence')
        original = hashlib.sha256((self.parent / 'portfolio.sqlite').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'financial_ancestor_refused'):
            managed.prepare_generation(self.config)
        self.assertEqual(hashlib.sha256((self.parent / 'portfolio.sqlite').read_bytes()).hexdigest(), original)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_restart_rejects_foreign_hardlink_and_generation_is_not_a_reset(self):
        managed.prepare_generation(self.config)
        linked = self.root / 'foreign.sqlite'
        os.link(self.usage, linked)
        with self.assertRaisesRegex(ValueError, 'private_owned_path_required'):
            managed.prepare_generation(self.config, restart=True)
        linked.unlink()
        linked.symlink_to(self.usage)
        with self.assertRaisesRegex(ValueError, 'real_absolute_path_required'):
            managed.prepare_generation(self.config, restart=True)
        with self.assertRaisesRegex(ValueError, 'fresh_root_required'):
            managed.prepare_generation(self.config)

    def test_explicit_environment_has_no_original_state_or_financial_authority(self):
        with managed.production_environment(self.config):
            self.assertEqual(os.environ['MM_OPERATIONAL_PHASE'], 'OBSERVATION')
            self.assertEqual(os.environ['MM_SOLANA_HISTORY_SEPARATED'], '1')
            self.assertEqual(os.environ['MM_PROVIDER_OPERATION_MODE'], 'CONTINUOUS')
            self.assertEqual(os.environ['MM_PROVIDER_USAGE_DB'], str(self.usage))
            self.assertNotIn('MM_STATE_ROOT', os.environ)
            self.assertNotIn('MM_PAPER_EPOCH', os.environ)
            self.assertNotIn('MM_BOUNDED_PROVIDER_DB', os.environ)
            self.assertEqual(Path(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB']).parent, self.root / 'shared')
        self.assertFalse(any(k.startswith('MM_') for k in os.environ))
        os.environ['MM_STATE_ROOT'] = '/original/financial/state'
        with self.assertRaisesRegex(ValueError, 'inherited_production_environment_refused'):
            asyncio.run(managed.run_pump(self.config, asyncio.Event()))
        self.assertEqual(list(self.root.iterdir()), [])

    def stores(self):
        managed.prepare_generation(self.config)
        with managed.production_environment(self.config):
            managed.install_nonfinancial_history(self.config)
            from meme_machine.solana_evidence_service import ServiceState
            from meme_machine.solana_selective_source import install
            state = ServiceState(self.config.evidence,
                managed.AlchemyEndpoint.parse(self.config.endpoint))
            install(state)
            state.writer.close()

    def test_sql_admission_denies_financial_entries_before_provider_dispatch(self):
        managed.prepare_generation(self.config)
        with managed.production_environment(self.config):
            managed.install_nonfinancial_history(self.config)
        with sqlite3.connect(self.config.history) as db:
            for table in ('funding', 'decisions'):
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'managed_pump_nonfinancial_history'):
                    db.execute('INSERT INTO ' + table + ' DEFAULT VALUES')
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_snapshots_do_not_call_empty_files_complete(self):
        managed.prepare_generation(self.config)
        self.config.evidence.touch(mode=0o600)
        result = managed.pump_snapshot(self.config)
        self.assertTrue(result['initialization_pending'])
        self.assertIsNone(result['canonical'])
        self.assertIsNone(result['history'])

    def test_real_history_reader_replays_hashes_without_mutation(self):
        self.stores()
        from meme_machine.runtime.candidate_history import CandidateHistory
        with managed.production_environment(self.config):
            history = CandidateHistory(self.config.history)
            try:
                history.observe('pump', 'mint', surface='pump.fun', observed_at=100)
                history.append_event('pump', 'mint', identity='native-event', slot=10,
                    transaction_index=2, event_index=0, market_time=100,
                    kind='pump_buy', payload=dict(mint='mint', event_type='buy'))
            finally:
                history.close()
        result = managed.replay_pump(self.config)
        self.assertEqual(result['events'], 1)
        self.assertTrue(result['read_only'])
        self.assertEqual(managed.pump_snapshot(self.config)['history']['funding'], 0)
        with sqlite3.connect(self.config.history) as db:
            db.execute("UPDATE events SET hash='tampered'")
        with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
            managed.replay_pump(self.config)

    def test_replay_refuses_external_canonical_reference_before_opening_it(self):
        self.stores()
        raw = json.dumps(dict(path='/original/economic/source.sqlite'))
        with sqlite3.connect(self.config.history) as db:
            db.execute('INSERT INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('pump', 'mint', 'event', 10, 2, 0, 100, 'pump_buy', raw,
                 hashlib.sha256(raw.encode()).hexdigest()))
        with self.assertRaisesRegex(ValueError, 'foreign_canonical_reference_refused'):
            managed.replay_pump(self.config)

    def test_recursive_cold_locators_and_payload_hashes_are_isolated(self):
        self.stores()
        def manifest(path, checksum):
            with sqlite3.connect(self.config.evidence) as db:
                db.execute('CREATE TABLE IF NOT EXISTS scoped_cold_manifests('
                    'id TEXT PRIMARY KEY,path TEXT,hash TEXT,records INTEGER,'
                    'hot_bytes INTEGER,cold_bytes INTEGER,created REAL)')
                db.execute('INSERT OR REPLACE INTO scoped_cold_manifests VALUES(?,?,?,?,?,?,?)',
                    ('cold', str(path), checksum, 0, 0, 4, 100.))
        manifest('/original/economic/archive.zlib', 'f' * 64)
        with self.assertRaisesRegex(ValueError, 'foreign_cold_reference_refused'):
            managed.replay_pump(self.config)
        directory = self.config.evidence.with_suffix('.scoped-cold')
        directory.mkdir(mode=0o700)
        path = directory / ('a' * 64 + '.zlib')
        path.write_bytes(b'cold')
        path.chmod(0o600)
        manifest(path, hashlib.sha256(b'cold').hexdigest())
        self.assertTrue(managed.replay_pump(self.config)['verified'])
        path.write_bytes(b'fail')
        with self.assertRaisesRegex(ValueError, 'cold_payload_corruption'):
            managed.replay_pump(self.config)

    def test_replay_rejects_orphan_population_and_same_count_mutation(self):
        self.stores()
        from meme_machine.runtime.candidate_history import CandidateHistory
        with managed.production_environment(self.config):
            history = CandidateHistory(self.config.history)
            history.append_event('pump', 'mint', identity='orphan-event', slot=10,
                transaction_index=2, event_index=0, market_time=100,
                kind='pump_buy', payload=dict(mint='mint', event_type='buy'))
            history.close()
        with self.assertRaisesRegex(ValueError, 'replay_population_mismatch'):
            managed.replay_pump(self.config)
        with managed.production_environment(self.config):
            history = CandidateHistory(self.config.history)
            history.observe('pump', 'mint', surface='pump.fun', observed_at=100)
            history.close()
        original = CandidateHistory.events
        def mutate_after_read(history, *args, **kwargs):
            result = original(history, *args, **kwargs)
            with sqlite3.connect(self.config.history) as db:
                db.execute("UPDATE events SET hash='same-row-count-different-bytes'")
            return result
        with patch.object(CandidateHistory, 'events', mutate_after_read):
            with self.assertRaisesRegex(ValueError, 'replay_mutated_native_history'):
                managed.replay_pump(self.config)

    def test_components_are_the_production_driver_rpc_and_sql_service(self):
        managed.prepare_generation(self.config)
        profile = dict(funding_regimes=['pump_current'],
            physical_http_start_interval_seconds='0.5',
            robinhood_http_start_interval_seconds='0.5')
        with managed.production_environment(self.config), \
                patch('meme_machine.operational.bounded_provider.install') as install, \
                patch('meme_machine.operational.position_continuation.load_continuous', return_value=profile):
            rpc, driver, serve = managed.production_components(self.config)
            from meme_machine.solana_selective_source import SelectiveSource
            from meme_machine.runtime.evidence_worker import RepairRPC
            from meme_machine.solana_evidence_service import serve as production_serve
            self.assertIs(type(driver), SelectiveSource)
            self.assertIs(type(rpc), RepairRPC)
            self.assertIs(serve, production_serve)
            self.assertEqual(rpc.governor.path, str(self.root / 'provider-governor.sqlite'))
            install.assert_called_once()

    def test_actual_source_boundary_is_joined_on_parent_cancellation(self):
        drained = []
        initialized = []
        async def scenario():
            stop = asyncio.Event()
            rpc = SimpleNamespace(validate_network=Mock())
            driver = SimpleNamespace(pipeline_metrics={}, drain_snapshot=lambda: {})
            async def serve(path, endpoint, **kwargs):
                from meme_machine.solana_evidence_service import ServiceState
                from meme_machine.solana_selective_source import install
                state = ServiceState(path, managed.AlchemyEndpoint.parse(endpoint))
                install(state)
                try:
                    await kwargs['stop'].wait()
                    self.assertEqual(os.environ['MM_SOLANA_EVIDENCE_PLANE_DB'], str(self.config.evidence))
                    drained.append(True)
                finally:
                    state.writer.close()
            def components(_):
                initialized.append('provider-guards')
                return rpc, driver, serve
            def sizing():
                from meme_machine.operational.managed_pump_qualification import FreshReferenceSizing
                self.assertEqual(initialized, ['provider-guards'])
                self.assertEqual(os.environ['MM_PROVIDER_OPERATION_MODE'], 'CONTINUOUS')
                initialized.append('native-valuation-reader')
                return FreshReferenceSizing(self.config.generation, value_reader=Mock(
                    side_effect=AssertionError('no_admitted_native_inputs_no_valuation_rpc')))
            with patch.object(managed, 'production_components', side_effect=components):
                task = asyncio.create_task(managed.run_pump(self.config, stop,
                    decision_target_reader_factory=sizing))
                await asyncio.sleep(.05)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(drained)
            self.assertEqual(initialized, ['provider-guards', 'native-valuation-reader'])
            self.assertFalse(any(k.startswith('MM_') for k in os.environ))
            self.assertEqual(managed.replay_pump(self.config)['events'], 0)
        asyncio.run(scenario())

    def test_normal_stop_uses_one_shutdown_deadline_and_cancels_stuck_source(self):
        async def scenario():
            stop = asyncio.Event()
            cancelled = []
            rpc = SimpleNamespace(validate_network=Mock())
            driver = SimpleNamespace(pipeline_metrics={}, drain_snapshot=lambda: {})
            async def serve(*args, **kwargs):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)
            with patch.object(managed, 'production_components', return_value=(rpc, driver, serve)), \
                    patch.object(managed, 'SHUTDOWN_SECONDS', .03):
                asyncio.get_running_loop().call_later(.01, stop.set)
                with self.assertRaisesRegex(ValueError, 'source_shutdown_deadline'):
                    await managed.run_pump(self.config, stop)
                await asyncio.sleep(0)
            self.assertTrue(cancelled)
            self.assertFalse(any(k.startswith('MM_') for k in os.environ))
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
