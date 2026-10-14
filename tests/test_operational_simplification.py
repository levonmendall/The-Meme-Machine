"""Resource lifetime and same-cycle reuse; no providers or production state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational import artifact_storage as storage, backup
from meme_machine.shared_capital import runtime
from meme_machine.shared_capital.model import CapitalError, digest


class SelectionReaders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portfolio = self.root / 'portfolio.sqlite'
        self.shared = self.root / 'shared-capital.sqlite'
        self.state = dict(epoch_id='offline-epoch', inception_sha256='a'*64,
                          policy={'sizing_basis': 'shared_realized_equity'})
        with closing(sqlite3.connect(self.portfolio)) as db, db:
            db.execute('CREATE TABLE portfolio_funding_authority(id,body)')
            marker = dict(state='SHARED', epoch_id=self.state['epoch_id'],
                          inception_sha256=self.state['inception_sha256'],
                          policy_sha256=digest(self.state['policy']))
            db.execute('INSERT INTO portfolio_funding_authority VALUES(1,?)', (json.dumps(marker),))
        with closing(sqlite3.connect(self.shared)) as db, db:
            db.execute('CREATE TABLE shared_capital_projection(id,body,hash)')
            db.execute('INSERT INTO shared_capital_projection VALUES(1,?,?)',
                       (json.dumps(self.state), digest(self.state)))
        self.opened = []
        self.original_connect = sqlite3.connect

    def track(self, *args, **kwargs):
        connection = self.original_connect(*args, **kwargs)
        # Strong references deliberately prevent GC from hiding leaked readers.
        self.opened.append(connection)
        return connection

    def assert_closed(self):
        for connection in self.opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_repeated_success_closes_both_readers_without_gc_or_writes(self):
        before = {p: p.read_bytes() for p in (self.portfolio, self.shared)}
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            for _ in range(20):
                self.assertEqual(runtime.selected(self.portfolio), self.shared)
                self.assert_closed()
        self.assertEqual(len(self.opened), 40)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_identity_mismatch_closes_all_readers_and_preserves_error(self):
        with closing(sqlite3.connect(self.shared)) as db, db:
            changed = dict(self.state, epoch_id='different-epoch')
            db.execute('UPDATE shared_capital_projection SET body=?,hash=?',
                       (json.dumps(changed), digest(changed)))
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(CapitalError, 'selected_shared_authority_identity_mismatch'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 2)
        self.assert_closed()

    def test_missing_authority_closes_selection_reader_and_fails_closed(self):
        self.shared.unlink()
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(CapitalError, 'selected_shared_authority_missing'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 1)
        self.assert_closed()

    def test_second_open_failure_closes_first_and_preserves_exception(self):
        error = sqlite3.OperationalError('original selection failure')
        def connect(*args, **kwargs):
            if self.opened:
                raise error
            return self.track(*args, **kwargs)
        with patch.object(runtime.sqlite3, 'connect', side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                runtime.selected(self.portfolio)
        self.assertIs(caught.exception, error)
        self.assert_closed()

    def test_projection_query_failure_closes_both_readers(self):
        with closing(sqlite3.connect(self.shared)) as db, db:
            db.execute('DROP TABLE shared_capital_projection')
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'no such table'):
                runtime.selected(self.portfolio)
        self.assertEqual(len(self.opened), 2)
        self.assert_closed()

    def test_unselected_and_missing_portfolios_preserve_original_result(self):
        with closing(sqlite3.connect(self.portfolio)) as db, db:
            db.execute('DROP TABLE portfolio_funding_authority')
        with patch.object(runtime.sqlite3, 'connect', side_effect=self.track):
            self.assertIsNone(runtime.selected(self.portfolio))
            self.assertIsNone(runtime.selected(self.root / 'absent.sqlite'))
        self.assertEqual(len(self.opened), 1)
        self.assert_closed()


class RecoveryVerification(unittest.TestCase):
    def test_two_independent_constructor_replays_and_closures_preserve_shared_fence(self):
        from meme_machine.portfolio_accounting import inception_receipt
        from meme_machine.shared_capital import RiskPolicy
        from meme_machine.shared_capital.cutover import install
        from meme_machine.shared_capital.operational_candidate import initialize_new_epoch
        from tests.shared_capital_support import CONTRACTS, legacy_identities, utc
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            plan = initialize_new_epoch(root, inception_receipt('offline-restored-1000', utc(0),
                'fixture', starting_capital='1000.00', shared=True),
                portfolio_identities=legacy_identities(),
                lane_identities={family: legacy_identities(family) for family in ('pump','pons','meteora','ramses')},
                contracts=CONTRACTS, policy=RiskPolicy(sizing_basis='shared_realized_equity'))
            install(root, plan, approved_policy=plan['policy'], prerequisites={key: True for key in
                ('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')})
            target = Path(directory) / 'restored'
            # This unit proves replay/closure counts, not host-wide syncfs
            # latency. Real copying, state checks and the separate backup suite
            # remain intact; preserve the exact production flush contract here.
            with patch.object(backup.subprocess, 'run') as flush:
                backup.copy_state(root, target)
            flush.assert_called_once_with(['sync','-f',str(target)],check=True,timeout=5)
            original_verify = runtime.RuntimeCapital.verify_replay
            original_close = runtime.RuntimeCapital.close
            openings, closures = [], []
            def verify(authority):
                openings.append(authority)
                return original_verify(authority)
            def close(authority):
                closures.append(authority)
                return original_close(authority)
            with patch.object(runtime.RuntimeCapital, 'verify_replay', verify), \
                    patch.object(runtime.RuntimeCapital, 'close', close):
                result = backup.prove_replay(target)
            self.assertTrue(result['replay_idempotent'])
            self.assertTrue(result['legacy_funding_fenced'])
            self.assertEqual(len(openings), 2)
            self.assertEqual(openings, closures)
            self.assertIsNot(openings[0], openings[1])
            self.assertEqual(backup.state_identity(root), backup.state_identity(target))


class ScratchMeasurement(unittest.TestCase):
    def test_active_scope_measured_once_per_cycle_and_concurrent_scopes_remain_counted(self):
        with tempfile.TemporaryDirectory() as parent:
            other = Path(parent) / 'mm-engineering-other'
            other.mkdir(); (other / 'retained-failure').write_text('keep')
            with storage.Scratch(parent) as scope:
                original = storage.tree_bytes
                for _ in range(2):
                    with patch.object(storage, 'tree_bytes', wraps=original) as measure:
                        scope.check()
                    measured = [call.args[0] for call in measure.call_args_list]
                    self.assertEqual(measured.count(scope.path), 1)
                    self.assertEqual(measured.count(other), 1)
                self.assertEqual((other / 'retained-failure').read_text(), 'keep')
                scope.success = True

    def test_disappearing_file_during_active_walk_is_tolerated_without_double_walk(self):
        with tempfile.TemporaryDirectory() as parent:
            with storage.Scratch(parent) as scope:
                gone = scope.path / 'gone'
                gone.write_text('disposable')
                original = Path.lstat
                def lstat(path, *args, **kwargs):
                    if path == gone:
                        gone.unlink(missing_ok=True)
                        raise FileNotFoundError(str(gone))
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', lstat):
                    scope.check()
                scope.success = True


class SuiteCoverage(unittest.TestCase):
    def test_only_duplicate_meteora_executions_disappear_with_identical_unique_ids(self):
        from operational.tests import FAST, OPERATIONAL
        module = 'tests.test_meteora_discovery_scheduler'
        self.assertEqual(FAST.count(module), 1)
        self.assertEqual(OPERATIONAL.count(module), 1)
        def ids(suite):
            for item in suite:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()
        duplicate = list(ids(unittest.defaultTestLoader.loadTestsFromName(module)))
        current = list(ids(unittest.defaultTestLoader.loadTestsFromNames(OPERATIONAL)))
        self.assertEqual(set(current), set(current + duplicate))
        self.assertEqual(len(current + duplicate) - len(current), len(duplicate))


class ReportingReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # CI already fetches full history for the existing source-integrity
        # guards. Compare complete outputs with the exact reviewed implementation.
        source = subprocess.check_output(['git','show',
            '84463cf78ee53b8117473f4a04b90832a8942a92:meme_machine/shared_capital/reporting.py'],
            cwd=Path(__file__).resolve().parents[1], text=True)
        cls.baseline = ModuleType('meme_machine.shared_capital._reporting_84463_baseline')
        cls.baseline.__package__ = 'meme_machine.shared_capital'
        exec(compile(source, 'reviewed-reporting-84463.py', 'exec'), cls.baseline.__dict__)

    def setUp(self):
        from tests.test_shared_portfolio_epoch import SharedEpochTests
        builder = SharedEpochTests()
        self.addCleanup(builder.doCleanups)
        self.h = builder.harness()

    def compare(self, at):
        from meme_machine.shared_capital import reporting
        authority = self.h.authority
        expected_export = self.baseline.export(authority, at=at)
        expected_summary = self.baseline.summary(authority, at)
        view = reporting.reporting_snapshot(authority, at=at)
        self.assertFalse(authority.db.in_transaction)
        self.assertEqual(reporting.export_from_snapshot(view), expected_export)
        self.assertEqual(reporting.summary_from_snapshot(view), expected_summary)
        self.assertEqual(view.snapshot['ledger']['inception'], authority.snapshot()['ledger']['inception'])

    def test_complete_outputs_equal_empty_missing_marks_partial_add_settlement_and_expiry(self):
        from meme_machine.runtime.directional_continuation import BRIDGE_GATES
        h = self.h
        self.compare(0)
        requests, _ = h.allocate([('pump_current',dict(requested='50')),('pons_survivor',dict(requested='50'))])
        pump, _ = h.fill(requests[0]); pons, _ = h.fill(requests[1])
        self.compare(0)  # Position marks are genuinely unavailable.
        h.at = 1
        h.mark('pump_current', pump, '100'); h.mark('pons_survivor', pons, '100')
        self.compare(1)
        h.realize('pons_survivor', pons, '20', released='12.5', terminal=False)
        h.mark('pons_survivor', pons, '100')
        self.compare(1)
        h.at = 900
        control = dict(opened_at=0,high_water_bps=10000,first_tail_crossed_at=0,
                       realization_taken=True,original_basis=1)
        facts = dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,
                     fresh_execution_requalified=True,after_cost_return_bps=7000)
        key = h.check()['ledger']['positions'][pons]['economic_keys'][0]
        requests, result = h.allocate([('pons_survivor',dict(requested='25',asset=key,
            kind='scale',lifecycle_id=pons,scale_state=control,scale_facts=facts))])
        self.assertEqual(result['decisions'][requests[0].request_id]['basis'], '25')
        h.fill(requests[0]); self.compare(900)
        h.at = 901; h.realize('pump_current', pump, '35')
        self.compare(901)
        self.compare(200000)  # Expiry cannot be renewed by reporting reuse.

    def test_grouped_decisions_preserve_order_last_eight_override_null_and_absence(self):
        from copy import deepcopy
        from meme_machine.shared_capital import reporting
        h = self.h
        requests, _ = h.allocate([('pump_current',dict(requested='50'))])
        life, _ = h.fill(requests[0])
        view = reporting.reporting_snapshot(h.authority, at=0)
        state = view.snapshot['ledger']
        template = deepcopy(next(iter(state['requests'].values())))
        state['requests'] = {}
        for index in range(12):
            row = deepcopy(template)
            row['value']['lifecycle_id'] = life
            row.pop('bound_lifecycle_id', None)
            row['value']['requested_basis'] = str(index + 1)
            state['requests'][f'valid-{index:02}'] = row
        null = deepcopy(template); null['value']['lifecycle_id'] = life
        null['bound_lifecycle_id'] = None
        state['requests']['zz-explicit-null'] = null
        override = deepcopy(template); override['value']['lifecycle_id'] = 'other'
        override['bound_lifecycle_id'] = life
        state['requests']['zz-override'] = override
        missing = deepcopy(template); missing.pop('bound_lifecycle_id', None)
        missing['value'].pop('lifecycle_id', None)
        state['requests']['zz-missing'] = missing
        undecided = deepcopy(template); undecided['decision'] = None
        state['requests']['zz-no-decision'] = undecided
        with patch.object(self.baseline.ReportingReader,'snapshot',return_value=view.snapshot):
            expected = self.baseline.export(h.authority,at=0)
        actual = reporting.export_from_snapshot(view)
        self.assertEqual(actual,expected)
        decisions = actual['positions'][0]['funding_decisions']
        self.assertEqual(len(decisions),8)
        self.assertEqual([row['requested_basis'] for row in decisions[:-1]],
                         [str(index) for index in range(6,13)])

    def test_concurrent_commit_cannot_mix_ledger_sequence_head_and_inception(self):
        from meme_machine.shared_capital import reporting
        h = self.h
        prior = self.baseline.summary(h.authority,0)
        other = runtime.RuntimeCapital(h.path)
        self.addCleanup(other.close)
        original = reporting.ReportingReader._read
        def read(reader):
            state = original(reader)
            other.command('concurrent-reporting-fixture','runtime_publish',{},1)
            return state
        with patch.object(reporting.ReportingReader,'_read',read):
            view = reporting.reporting_snapshot(h.authority,at=0)
        result = reporting.summary_from_snapshot(view)
        self.assertEqual(result,prior)
        self.assertFalse(h.authority.db.in_transaction)
        self.assertEqual(reporting.summary(h.authority,1)['sequence'],prior['sequence']+1)
        self.assertEqual(reporting.export_from_snapshot(view)['sequence'],prior['sequence'])

    def test_reporting_snapshot_never_supplies_spending_authority(self):
        from meme_machine.shared_capital import reporting
        h = self.h; view = reporting.reporting_snapshot(h.authority,at=0)
        h.allocate([('pump_current',dict(requested='50'))])
        self.assertEqual(reporting.summary_from_snapshot(view)['capital']['free_cash'],'1000.00')
        self.assertEqual(reporting.summary(h.authority,0)['capital']['free_cash'],'950.00')

    def test_supervisor_uses_one_validated_reporting_read_and_writes_after_read_commit(self):
        from meme_machine.operational import supervisor
        from meme_machine.shared_capital import reporting
        h = self.h; h.authority.close(); h.authority = runtime.RuntimeCapital(h.path)
        service = supervisor.Supervisor(h.root,offline=True)
        service.shared_capital = h.authority
        reads = []
        original = reporting.ReportingReader._read
        def read(reader):
            reads.append(True)
            return original(reader)
        original_write = supervisor._atomic_json
        def write(path,value):
            self.assertFalse(h.authority.db.in_transaction)
            return original_write(path,value)
        with patch.object(reporting.ReportingReader,'_read',read), \
                patch.object(supervisor,'_atomic_json',write):
            service.publish_shared_capital({},0)
        self.assertEqual(len(reads),1)
        self.assertEqual(service.portfolio_observation['sequence'],
            json.loads((h.root/'portfolio.json').read_text())['sequence'])

    def test_reporting_read_and_request_traversal_counts_drop_without_output_changes(self):
        from meme_machine.shared_capital import reporting
        h = self.h
        requests,_ = h.allocate([('pump_current',dict(requested='50')),('pons_survivor',dict(requested='50'))])
        for request in requests:h.fill(request)
        statements = []
        h.authority.db.set_trace_callback(statements.append)
        expected = (self.baseline.export(h.authority,at=0),self.baseline.summary(h.authority,0),
                    h.authority.snapshot()['ledger']['inception'])
        before = sum(sql.startswith('SELECT ') for sql in statements)
        statements.clear()
        view = reporting.reporting_snapshot(h.authority,at=0)
        actual = (reporting.export_from_snapshot(view),reporting.summary_from_snapshot(view),
                  view.snapshot['ledger']['inception'])
        after = sum(sql.startswith('SELECT ') for sql in statements)
        h.authority.db.set_trace_callback(None)
        self.assertEqual(expected,actual)
        self.assertEqual((before,after),(9,4))
        class Requests(dict):
            reads = 0
            def items(self):
                self.reads += 1
                return super().items()
        requests = Requests(view.snapshot['ledger']['requests'])
        view.snapshot['ledger']['requests'] = requests
        with patch.object(self.baseline.ReportingReader,'snapshot',return_value=view.snapshot):
            old = self.baseline.export(h.authority,at=0)
        old_reads = requests.reads
        requests.reads = 0
        new = reporting.export_from_snapshot(view)
        self.assertEqual(old,new)
        self.assertEqual((old_reads,requests.reads),(2,1))
        print('REPORTING_OPERATION_COUNTS',json.dumps(dict(
            scope='one export/summary/inception publication; two positions',
            selects_before=before,selects_after=after,request_traversals_before=old_reads,
            request_traversals_after=requests.reads)),flush=True)


class ProviderHealthReuse(unittest.TestCase):
    def service(self, root):
        from meme_machine.operational.supervisor import Supervisor
        service = Supervisor(root,offline=False,admission='NORMAL')
        service.epoch = 'offline-fixture-health'
        service.evidence = None
        service.shared_capital = SimpleNamespace(ledger=lambda: {'positions':{},'runtime_pending':{}})
        service.provider_budget = SimpleNamespace(continuous=False,envelope=dict(
            maximum_queue_depth=64,maximum_queue_wait_seconds=5,maximum_rss_bytes=6*1024**3))
        service.last_native_health = {lane:dict(progress_at=100,reconciled=True) for lane in ('pump','pons')}
        return service

    def healthy(self):
        return dict(solana=dict(state='CURRENT',queue_depth=0,oldest_wait_seconds=0),
            robinhood=dict(state='CURRENT',queue_depth=0,oldest_wait_seconds=0),
            evidence=dict(state='CURRENT',phase='ACTIVE',heartbeat=100))

    def test_real_supervisor_cycle_collects_once_and_shutdown_collects_fresh(self):
        from meme_machine.operational import supervisor
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            calls = []
            def provider_health():
                calls.append(True)
                if len(calls)==1:service.stop_requested=True
                return self.healthy()
            with patch.object(service,'initialize'), patch.object(service,'start_services'), \
                    patch.object(service,'start_lane'), patch.object(service,'normal_tick'), \
                    patch.object(service,'publish_shared_capital'), \
                    patch.object(service,'provider_health',side_effect=provider_health), \
                    patch.object(supervisor.time,'time',return_value=100), \
                    patch.object(supervisor.time,'monotonic',return_value=100), \
                    patch.object(supervisor.time,'sleep'), \
                    patch.object(service,'continuation_health',wraps=service.continuation_health) as health, \
                    patch.object(service,'publish',wraps=service.publish) as publish:
                service.run()
            self.assertEqual(len(calls),2)  # One ordinary cycle plus fresh shutdown.
            health.assert_called_once()
            self.assertIs(health.call_args.kwargs['provider_sample'],
                          publish.call_args_list[0].kwargs['provider_sample'])
            self.assertEqual(publish.call_count,2)
            output = json.loads((Path(root)/'health.json').read_text())
            self.assertEqual(output['provider_health_sample']['collected_at'],100)

    def test_stale_failed_and_future_samples_remain_unavailable_without_timestamp_refresh(self):
        from meme_machine.operational import supervisor
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            for sample in (supervisor.ProviderHealthSample(100,100,self.healthy()),
                           supervisor.ProviderHealthSample(119,119,{},'OperationalError'),
                           supervisor.ProviderHealthSample(130,130,self.healthy())):
                with patch.object(supervisor.time,'time',return_value=120):
                    result = service.providers_for_sample(sample)
                self.assertTrue(all(row['state']=='UNAVAILABLE' for row in result.values()))
                self.assertEqual(sample.collected_at,100 if sample.completed_at==100 else sample.completed_at)

    def test_queue_wait_ages_at_consumption_and_empty_queue_does_not_invent_wait(self):
        from meme_machine.operational import supervisor
        providers = self.healthy()
        providers['robinhood'].update(queue_depth=1,oldest_wait_seconds=4,sampled_at=100)
        sample = supervisor.ProviderHealthSample(100,100,providers)
        with patch.object(supervisor.time,'time',return_value=102):
            result = supervisor.Supervisor.providers_for_sample(sample)
        self.assertEqual(result['robinhood']['oldest_wait_seconds'],6)
        self.assertEqual(result['solana']['oldest_wait_seconds'],0)
        self.assertEqual(sample.providers['robinhood']['oldest_wait_seconds'],4)

    def test_failed_standalone_collection_is_not_replaced_with_previous_success(self):
        from meme_machine.operational import supervisor
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            with patch.object(service,'provider_health',side_effect=[self.healthy(),sqlite3.OperationalError('failure')]), \
                    patch.object(supervisor.time,'time',return_value=100):
                first = service.collect_provider_health()
                failed = service.collect_provider_health()
                result = service.providers_for_sample(failed)
            self.assertIsNone(first.error)
            self.assertEqual(failed.error,'OperationalError')
            self.assertTrue(all(row['state']=='UNAVAILABLE' for row in result.values()))

    def test_slow_descriptive_query_cannot_refresh_prior_queue_measurement(self):
        from meme_machine.operational import supervisor, observation
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'shared').mkdir()
            with closing(sqlite3.connect(root/'shared/solana-provider.sqlite')) as db, db:
                db.execute('CREATE TABLE pressure(provider,unused,cooldown,grants,errors)')
            service=self.service(root);clock=[100]
            connect=sqlite3.connect
            def connection(*args,**kwargs):
                db=connect(*args,**kwargs)
                db.set_trace_callback(lambda sql:clock.__setitem__(0,102) if sql=='SELECT * FROM pressure' else None)
                return db
            with patch.object(supervisor.sqlite3,'connect',side_effect=connection), \
                    patch.object(observation,'provider_queue',return_value=(1,95)), \
                    patch.object(supervisor.time,'time',side_effect=lambda:clock[0]), \
                    patch.object(supervisor.time,'monotonic',side_effect=lambda:clock[0]):
                sample=service.collect_provider_health()
                result=service.providers_for_sample(sample)
            self.assertEqual(sample.completed_at,102)
            self.assertEqual(sample.providers['solana']['sampled_at'],100)
            self.assertEqual(result['solana']['oldest_wait_seconds'],7)


if __name__ == '__main__':
    unittest.main()
