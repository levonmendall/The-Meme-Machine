"""Independent simulator snapshots; no execution, funding or historical feed writes."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard.__main__ import make_server
from dashboard.api import Dashboard
from dashboard.model import Reader
from dashboard import simulator as simulator
from dashboard.snapshots import SnapshotStore, SCHEMA as ORIGINAL_SCHEMA, PHASES


NOW = 1791490000.0
EXPERIMENT = 'pons-simulator-independent-fixture'
EPOCH = 'paper-pons-simulator-1000-20261024'
SOURCE = 'a'*40
INCEPTION = 'b'*64
OWNER = ('owner', 'synthetic-simulator-owner-password')
OWNER_AUTH = 'Basic '+base64.b64encode(':'.join(OWNER).encode()).decode()
ORIGINAL_TOKEN = 'synthetic-original-ingest-token'
SIMULATOR_TOKEN = 'synthetic-independent-simulator-ingest-token'
BASELINE_STRATEGY = dict(version='baseline-909738760e6f722b',
    policy_revision='paper-postgrad-rally-v1',
    policy_sha256='909738760e6f722b8668a99493f698c3a415867f77f08199a61b0fb047381be7',
    adaptation_state='BASELINE_UNCHANGED')


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def metric(value, unit, *, at=NOW, quality='MEASURED'):
    return dict(value=value, quality=quality, unit=unit,
        as_of=None if quality == 'UNAVAILABLE' else utc(at))


def sealed(value):
    value = deepcopy(value)
    unsigned = {name: item for name, item in value.items() if name != 'snapshot_sha256'}
    raw = json.dumps(unsigned, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')
    value['snapshot_sha256'] = hashlib.sha256(raw).hexdigest()
    return value


def snapshot(*, sequence=1, captured=NOW, execution='RUNNING'):
    return sealed(dict(schema='pons-simulator-snapshot-v1',
        label='EXPERIMENTAL PONS CURRENT — SIMULATED TRADING — NO REAL MONEY',
        identity=dict(experiment_id=EXPERIMENT, epoch_id=EPOCH,
            source_commit=SOURCE, inception_sha256=INCEPTION),
        sequence=sequence, captured_at=utc(captured), execution_state=execution,
        metrics=dict(
            financial=dict(starting_capital=metric('1000.00', 'USD', at=captured),
                cash=metric('950.00', 'USD', at=captured),
                reserved=metric('0', 'USD', at=captured),
                deployed=metric('50.00', 'USD', at=captured),
                realized_pnl=metric('0.00', 'USD', at=captured),
                equity=metric(None, 'USD', quality='UNAVAILABLE')),
            activity=dict(events_seen=metric('7', 'COUNT', at=captured),
                events_processed=metric('7', 'COUNT', at=captured),
                entries=metric('1', 'COUNT', at=captured),
                open_positions=metric('1', 'COUNT', at=captured)),
            strategy=dict(evaluated=metric('2', 'COUNT', at=captured)),
            operational=dict(connected=metric('1', 'COUNT', at=captured),
                provider_requests=metric('4', 'COUNT', at=captured),
                memory_bytes=metric('123456', 'BYTES', at=captured))),
        lifecycles=[dict(lifecycle_id='c'*64, asset_id='d'*64, state='OPEN',
            entered_at=utc(captured-5), updated_at=utc(captured), settled_at=None,
            metrics=dict(quantity=metric('2.00', 'TOKENS', at=captured),
                remaining_quantity=metric('2.00', 'TOKENS', at=captured),
                realized_pnl=metric('0', 'USD', at=captured),
                mark_price=metric(None, 'USD', quality='UNAVAILABLE')),
            reason_codes=['QUOTE_UNAVAILABLE'])],
        history=dict(
            equity=dict(rows=[dict(at=utc(captured),
                equity=metric('1000.00', 'USD', at=captured, quality='ESTIMATED'))],
                total=1, complete=True),
            events=dict(rows=[dict(at=utc(captured-5), event_id='e'*64,
                kind='ENTRY', lifecycle_id='c'*64, reason_code='NONE')], total=1, complete=True)),
        reason_codes=['QUOTE_UNAVAILABLE']))


def original_snapshot(now):
    return dict(schema=ORIGINAL_SCHEMA, captured_at=utc(now),
        source=dict(epoch_id='synthetic-original-dashboard', candidate_commit='1'*40,
            deployed_commit='2'*40, publisher_commit='3'*40),
        observer=dict(at=utc(now), epoch_id='synthetic-original-dashboard', lanes={}),
        monitor=dict(at=utc(now), conditions=[]),
        service=dict(ActiveState='inactive', SubState='dead', MainPID='0'),
        acceptance={phase: dict(status='NOT_STARTED', elapsed_seconds=0, verified_result=False)
            for phase in PHASES},
        portfolio=dict(bundle=None, observation=dict(state='UNAVAILABLE')))


class SimulatorFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = NOW
        self.path = self.root/'independent-simulator.json'
        self.store = simulator.SimulatorStore(self.path,
            experiment_id=EXPERIMENT, epoch_id=EPOCH, source_commit=SOURCE,
            inception_sha256=INCEPTION, clock=lambda: self.now)

    def server(self, *, channel=None, original_store=None, public_reads=False,
               simulator_token=SIMULATOR_TOKEN):
        server = make_server(Dashboard(Reader()), '127.0.0.1', 0,
            max_concurrency=4, rate_limit_per_minute=100,
            owner=OWNER, ingest_token=ORIGINAL_TOKEN,
            snapshot_store=original_store, public_reads=public_reads,
            simulator_channel=channel or simulator.SimulatorChannel(self.store),
            simulator_ingest_token=simulator_token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def request(self, base, target, *, method='GET', authorization=None, value=None, raw=None):
        headers = {}
        if authorization is not None:
            headers['Authorization'] = authorization
        if value is not None:
            raw = json.dumps(value, allow_nan=False).encode()
        if raw is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(base+target, data=raw, method=method, headers=headers)
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read()


class ReadOnlyObserverTests(SimulatorFixture):
    def observed(self):
        value = snapshot()
        value['observer'] = dict(schema='pons-readonly-observer-v1', read_only=True,
            source_commit=SOURCE, status='RUNNING', heartbeat_at=utc(NOW),
            market_as_of=utc(NOW-2), restart_count=1,
            current=dict(completed=2, eligible=1, wait=1, rejected=0, incomplete=1),
            survivor=dict(completed=None, eligible=None, wait=1, rejected=0, incomplete=1),
            decisions=[dict(id='f'*64, at=utc(NOW-1), strategy='CURRENT', action='ENTER',
                reason='native_current_threshold_pass', evidence_sha256='1'*64,
                qualification='COMPLETE')], history_coverage='INCOMPLETE')
        return sealed(value)

    def test_observer_preserves_independent_counts_shadow_evidence_and_financial_clock(self):
        value = self.observed()
        value['metrics']['financial']['cash'] = metric('1000', 'USD', at=NOW-120)
        self.store.accept(sealed(value))
        view = simulator.SimulatorReader(self.store).view()
        self.assertEqual(view['observer'], value['observer'])
        self.assertFalse(view['source_ledger_authoritative'])
        self.assertIsNone(view['observer']['survivor']['completed'])
        self.assertEqual(view['observer']['decisions'][0]['action'], 'ENTER')
        self.assertEqual(view['metrics']['financial']['cash']['state'], 'STALE')
        self.assertEqual(view['metrics']['activity']['entries']['value'], '1')
        self.now += 61
        self.assertEqual(simulator.SimulatorReader(self.store).view()['state'], 'STALE')

    def test_observer_refuses_authority_missing_entry_evidence_and_false_completion(self):
        for mutate in (
                lambda o: o.update(read_only=False),
                lambda o: o.update(source_commit='0'*40),
                lambda o: o.update(heartbeat_at=utc(NOW+1)),
                lambda o: o.update(market_as_of=utc(NOW+1)),
                lambda o: o.update(provider_url='https://private.invalid/secret'),
                lambda o: o['current'].update(completed=0, eligible=1),
                lambda o: o['current'].update(completed=True),
                lambda o: o['decisions'][0].update(qualification='INCOMPLETE'),
                lambda o: o['decisions'][0].update(evidence_sha256=None),
                lambda o: o['decisions'][0].update(reason='https://private.invalid/secret'),
                lambda o: o['decisions'].append(deepcopy(o['decisions'][0]))):
            value = self.observed()
            mutate(value['observer'])
            with self.assertRaises(ValueError):
                self.store.accept(sealed(value))
        self.assertIsNone(self.store.get())

    def test_observer_schema_is_optional_for_existing_publisher(self):
        value = snapshot()
        self.store.accept(value)
        self.assertIsNone(simulator.SimulatorReader(self.store).view()['observer'])
        self.assertTrue(simulator.SimulatorReader(self.store).view()['source_ledger_authoritative'])
        code, _, raw = simulator.SimulatorChannel(self.store).response('GET', '/dashboard/pons-simulator')
        self.assertEqual(code, 200)
        self.assertIn(b'Pons Current and Survivor', raw)
        self.assertIn(b'read-only shadow observer', raw)


class SimulatorStoreTests(SimulatorFixture):
    def test_content_hash_idempotence_strict_sequence_and_reopen(self):
        first = snapshot()
        expected = first['snapshot_sha256']
        self.assertEqual(simulator.snapshot_digest(first), expected)
        self.assertEqual(self.store.accept(first), dict(idempotent=False, sequence=1))
        persisted = self.path.read_bytes()
        before_stat = self.path.stat()
        self.assertEqual(self.store.accept(deepcopy(first)), dict(idempotent=True, sequence=1))
        self.assertEqual(self.path.read_bytes(), persisted)
        self.assertEqual(self.path.stat().st_mtime_ns, before_stat.st_mtime_ns)
        changed = deepcopy(first)
        changed['metrics']['activity']['events_seen']['value'] = '8'
        with self.assertRaisesRegex(ValueError, 'simulator_sequence_equivocation'):
            self.store.accept(sealed(changed))
        second = snapshot(sequence=2, captured=NOW+1)
        self.now = NOW+1
        self.store.accept(second)
        with self.assertRaisesRegex(ValueError, 'simulator_sequence_regression'):
            self.store.accept(first)
        reopened = simulator.SimulatorStore(self.path, experiment_id=EXPERIMENT,
            epoch_id=EPOCH, source_commit=SOURCE, inception_sha256=INCEPTION,
            clock=lambda: self.now)
        self.assertEqual(reopened.get(), second)
        with self.assertRaisesRegex(ValueError, 'simulator_sequence_equivocation'):
            reopened.accept(sealed(dict(second, execution_state='FAILED')))
        self.assertEqual(reopened.get(), second)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_returned_and_submitted_objects_cannot_mutate_retained_snapshot(self):
        value = snapshot()
        self.store.accept(value)
        value['metrics']['financial']['cash']['value'] = '999999'
        returned = self.store.get()
        returned['identity']['experiment_id'] = 'pons-simulator-unrelated'
        returned['lifecycles'].clear()
        self.assertEqual(self.store.get(), snapshot())

    def test_rejects_wrong_identity_historical_pilot_and_bad_digest_without_replacing_file(self):
        self.store.accept(snapshot())
        before = self.path.read_bytes()
        for field, value in (('experiment_id', 'pons-simulator-another'),
                             ('experiment_id', 'paper-pons-pilot-1000-20261023'),
                             ('epoch_id', 'paper-pons-simulator-1000-20261025'),
                             ('epoch_id', 'paper-pons-pilot-1000-20261023'),
                             ('source_commit', 'f'*40), ('inception_sha256', 'f'*64)):
            bad = snapshot(sequence=2)
            bad['identity'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.store.accept(sealed(bad))
            self.assertEqual(self.path.read_bytes(), before)
        bad = snapshot(sequence=2)
        bad['metrics']['financial']['cash']['value'] = '1'
        with self.assertRaisesRegex(ValueError, 'simulator_digest'):
            self.store.accept(bad)
        self.assertEqual(self.path.read_bytes(), before)

    def test_timestamp_regression_future_time_and_old_arrival_cannot_renew_snapshot(self):
        self.store.accept(snapshot())
        before = self.path.read_bytes()
        for value in (snapshot(sequence=2, captured=NOW-1),
                      snapshot(sequence=2, captured=NOW+6)):
            with self.assertRaises(ValueError):
                self.store.accept(value)
        self.now = NOW+121
        with self.assertRaises(ValueError):
            self.store.accept(snapshot(sequence=2))
        # The exact old retry remains idempotent without renewing its timestamp.
        self.assertEqual(self.store.accept(snapshot()), dict(idempotent=True, sequence=1))
        self.assertEqual(self.path.read_bytes(), before)
        view = simulator.SimulatorReader(self.store).view()
        self.assertEqual(view['state'], 'STALE')
        self.assertEqual(view['captured_at'], utc(NOW))

    def test_explicit_zero_unavailable_and_estimate_keep_distinct_quality_and_time(self):
        self.store.accept(snapshot())
        reader = simulator.SimulatorReader(self.store)
        current = reader.view()
        self.assertEqual(current['state'], 'CURRENT')
        self.assertEqual(current['metrics']['financial']['realized_pnl'],
            dict(metric('0.00', 'USD'), state='CURRENT'))
        self.assertEqual(current['metrics']['financial']['equity'],
            dict(metric(None, 'USD', quality='UNAVAILABLE'), state='UNAVAILABLE'))
        self.assertEqual(current['metrics']['financial']['unrealized_pnl']['value'], None)
        self.assertEqual(current['metrics']['financial']['unrealized_pnl']['quality'], 'UNAVAILABLE')
        self.assertEqual(current['history']['equity']['rows'][0]['equity']['quality'], 'ESTIMATED')
        self.now = NOW+61
        stale = reader.view()
        self.assertEqual(stale['state'], 'STALE')
        self.assertIn('STALE_SNAPSHOT', stale['reason_codes'])
        self.assertEqual(stale['metrics']['financial']['realized_pnl']['state'], 'STALE')
        self.assertEqual(stale['metrics']['financial']['realized_pnl']['value'], '0.00')
        self.assertEqual(stale['metrics']['financial']['realized_pnl']['as_of'], utc(NOW))
        self.assertEqual(stale['metrics']['financial']['equity']['value'], None)
        reopened = simulator.SimulatorStore(self.path, experiment_id=EXPERIMENT,
            epoch_id=EPOCH, source_commit=SOURCE, inception_sha256=INCEPTION,
            clock=lambda: self.now)
        self.assertEqual(simulator.SimulatorReader(reopened).view()['state'], 'STALE')

    def test_fresh_transport_does_not_make_old_metric_current_or_stopped_source_running(self):
        value = snapshot(execution='STOPPED')
        value['metrics']['financial']['cash']['as_of'] = utc(NOW-61)
        self.store.accept(sealed(value))
        view = simulator.SimulatorReader(self.store).view()
        self.assertEqual(view['state'], 'CURRENT')
        self.assertEqual(view['execution_state'], 'STOPPED')
        self.assertEqual(view['metrics']['financial']['cash']['state'], 'STALE')
        self.assertEqual(view['metrics']['financial']['cash']['as_of'], utc(NOW-61))
        self.assertEqual(view['persistence'], 'EPHEMERAL_UNVERIFIED')

    def test_closed_schema_rejects_unknown_fields_types_units_and_hostile_text(self):
        mutations = (
            lambda value: value.update(provider_url='https://private.invalid/SECRET'),
            lambda value: value['identity'].update(epoch_id='paper-pons-pilot-1000-20261023'),
            lambda value: value.update(sequence=True),
            lambda value: value.update(sequence=0),
            lambda value: value.update(captured_at='2026-10-08T12:00:00+00:00'),
            lambda value: value.update(execution_state='LIVE_MONEY'),
            lambda value: value.update(label='<script>SECRET</script>'),
            lambda value: value['metrics'].update(capital={'secret': 'SECRET'}),
            lambda value: value['metrics']['activity'].update(unknown=metric('1', 'COUNT')),
            lambda value: value['metrics']['activity']['entries'].update(value=True),
            lambda value: value['metrics']['activity']['entries'].update(value='-1'),
            lambda value: value['metrics']['activity']['entries'].update(value='1.5'),
            lambda value: value['metrics']['financial']['cash'].update(value='NaN'),
            lambda value: value['metrics']['financial']['cash'].update(value=0),
            lambda value: value['metrics']['financial']['cash'].update(value='1e3'),
            lambda value: value['metrics']['financial']['cash'].update(unit='TOKENS'),
            lambda value: value['metrics']['financial']['cash'].update(quality='EXACT'),
            lambda value: value['metrics']['financial']['cash'].update(quality='UNAVAILABLE'),
            lambda value: value['metrics']['financial']['cash'].update(state='CURRENT'),
            lambda value: value['metrics']['financial']['cash'].update(as_of=utc(NOW+1)),
            lambda value: value['metrics']['operational']['connected'].update(value='2'),
            lambda value: value['lifecycles'][0].update(asset_id='<script>SECRET</script>'),
            lambda value: value['lifecycles'][0].update(updated_at=utc(NOW+1)),
            lambda value: value['lifecycles'][0].update(entered_at=utc(NOW+1)),
            lambda value: value['lifecycles'][0]['metrics'].update(raw_quote='SECRET'),
            lambda value: value.update(reason_codes=['SECRET']),
            lambda value: value.update(reason_codes=['NONE', 'NONE']),
        )
        for index, mutation in enumerate(mutations):
            value = snapshot()
            mutation(value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.store.accept(sealed(value))
            self.assertFalse(self.path.exists())
            self.assertIsNone(self.store.get())

    def test_history_and_lifecycle_bounds_preserve_explicit_incomplete_population(self):
        value = snapshot()
        value['history']['equity'].update(total=900, complete=False)
        value['history']['events'].update(total=None, complete=False)
        self.store.accept(sealed(value))
        view = simulator.SimulatorReader(self.store).view()
        self.assertEqual(view['history']['equity']['total'], 900)
        self.assertFalse(view['history']['equity']['complete'])
        self.assertIsNone(view['history']['events']['total'])
        self.assertFalse(view['history']['events']['complete'])
        for section, maximum in (('equity', simulator.MAX_EQUITY), ('events', simulator.MAX_EVENTS)):
            bad = snapshot(sequence=2)
            row = bad['history'][section]['rows'][0]
            bad['history'][section] = dict(rows=[deepcopy(row) for _ in range(maximum+1)],
                total=maximum+1, complete=True)
            with self.subTest(section=section), self.assertRaises(ValueError):
                self.store.accept(sealed(bad))
        bad = snapshot(sequence=2)
        bad['lifecycles'] *= simulator.MAX_LIFECYCLES+1
        with self.assertRaises(ValueError):
            self.store.accept(sealed(bad))
        for section in ('equity', 'events'):
            for total, complete in ((0, False), (2, True), (None, True), (True, False)):
                bad = snapshot(sequence=2)
                bad['history'][section].update(total=total, complete=complete)
                with self.subTest(section=section, total=total, complete=complete), self.assertRaises(ValueError):
                    self.store.accept(sealed(bad))
        self.assertEqual(self.store.get(), sealed(value))

    def test_duplicate_lifecycle_event_and_reversed_history_are_rejected(self):
        cases = []
        duplicate_life = snapshot()
        duplicate_life['lifecycles'] *= 2
        cases.append(duplicate_life)
        duplicate_event = snapshot()
        duplicate_event['history']['events']['rows'] *= 2
        duplicate_event['history']['events']['total'] = 2
        cases.append(duplicate_event)
        reversed_equity = snapshot()
        reversed_equity['history']['equity'] = dict(rows=[
            dict(at=utc(NOW), equity=metric('1000', 'USD')),
            dict(at=utc(NOW-1), equity=metric('999', 'USD', at=NOW-1))], total=2, complete=True)
        cases.append(reversed_equity)
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.store.accept(sealed(value))

    def test_bounded_decoder_rejects_duplicate_keys_nan_and_oversize_before_acceptance(self):
        raw = json.dumps(snapshot(), ensure_ascii=True).encode('ascii')
        decoded = simulator.decode_snapshot(raw)
        self.assertEqual(decoded, snapshot())
        for invalid in (b'{"sequence":1,"sequence":2}', b'{"nested":{"x":1,"x":2}}',
                        b'{"value":NaN}', b'{"value":Infinity}',
                        b' '*(simulator.MAX_BYTES+1), b'', b'\xff'):
            with self.subTest(prefix=invalid[:32]), self.assertRaises((ValueError, UnicodeError)):
                simulator.decode_snapshot(invalid)

    def test_corrupt_or_foreign_persisted_file_cannot_reopen_as_current_data(self):
        self.store.accept(snapshot())
        for raw in (b'{', json.dumps(sealed(dict(snapshot(), identity=dict(
                experiment_id='pons-simulator-foreign', epoch_id=EPOCH, source_commit=SOURCE,
                inception_sha256=INCEPTION)))).encode()):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                simulator.SimulatorStore(self.path, experiment_id=EXPERIMENT,
                    epoch_id=EPOCH, source_commit=SOURCE, inception_sha256=INCEPTION,
                    clock=lambda: self.now)


class SimulatorStrategyVersionTests(SimulatorFixture):
    def test_omitted_metadata_remains_unknown_and_explicit_null_cannot_replace_it(self):
        value = snapshot()
        self.store.accept(value)
        before = self.path.read_bytes()
        self.assertIsNone(simulator.SimulatorReader(self.store).view()['strategy_version'])
        self.assertNotIn('strategy_version', self.store.get())
        self.assertEqual(value, snapshot())
        bad = snapshot(sequence=2)
        bad['strategy_version'] = None
        with self.assertRaises(ValueError):
            self.store.accept(sealed(bad))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(simulator.SimulatorReader(self.store).view()['strategy_version'])

    def test_baseline_experimental_and_reverted_metadata_echo_without_changing_original_feed(self):
        original = SnapshotStore(self.root/'original-latest.json',
            epoch='synthetic-original-dashboard', candidate='1'*40, clock=lambda: self.now)
        original.accept(original_snapshot(NOW))
        original_bytes = original.path.read_bytes()
        versions = (BASELINE_STRATEGY,
            dict(version='experiment-2.1', policy_revision='paper-experiment_r2',
                policy_sha256='f'*64, adaptation_state='EXPERIMENTAL'),
            dict(version='a'*64, policy_revision='r'*96,
                policy_sha256='f'*64, adaptation_state='EXPERIMENTAL'),
            dict(BASELINE_STRATEGY, adaptation_state='REVERTED'))
        for sequence, metadata in enumerate(versions, 1):
            value = snapshot(sequence=sequence)
            value['strategy_version'] = deepcopy(metadata)
            value = sealed(value)
            submitted = deepcopy(value)
            self.store.accept(value)
            view = simulator.SimulatorReader(self.store).view()
            self.assertEqual(view['strategy_version'], metadata)
            self.assertEqual(value, submitted)
            view['strategy_version']['version'] = 'unrelated'
            self.assertEqual(self.store.get()['strategy_version'], metadata)
            self.assertEqual(original.path.read_bytes(), original_bytes)
        reopened = simulator.SimulatorStore(self.path, experiment_id=EXPERIMENT,
            epoch_id=EPOCH, source_commit=SOURCE, inception_sha256=INCEPTION,
            clock=lambda: self.now)
        self.assertEqual(simulator.SimulatorReader(reopened).view()['strategy_version'], versions[-1])

    def test_metadata_refuses_private_text_unknown_keys_malformed_types_and_false_baselines(self):
        self.store.accept(snapshot())
        before = self.path.read_bytes()
        mutations = (
            lambda metadata: metadata.update(provider_url='https://private.invalid/SECRET'),
            lambda metadata: metadata.update(version='https://private.invalid/SECRET'),
            lambda metadata: metadata.update(version='/srv/private/SECRET'),
            lambda metadata: metadata.update(version='<script>SECRET</script>'),
            lambda metadata: metadata.update(version='Uppercase'),
            lambda metadata: metadata.update(version='-leading-separator'),
            lambda metadata: metadata.update(version=''),
            lambda metadata: metadata.update(version=True),
            lambda metadata: metadata.update(version='a'*65),
            lambda metadata: metadata.update(policy_revision='https://private.invalid/SECRET'),
            lambda metadata: metadata.update(policy_revision='/srv/private/SECRET'),
            lambda metadata: metadata.update(policy_revision='<script>SECRET</script>'),
            lambda metadata: metadata.update(policy_revision=1),
            lambda metadata: metadata.update(policy_revision='a'*97),
            lambda metadata: metadata.update(policy_sha256='F'*64),
            lambda metadata: metadata.update(policy_sha256='f'*63),
            lambda metadata: metadata.update(policy_sha256=None),
            lambda metadata: metadata.update(adaptation_state='ADAPTED'),
            lambda metadata: metadata.update(adaptation_state=False),
            lambda metadata: metadata.update(adaptation_state='BASELINE_UNCHANGED',
                version='another-baseline'),
            lambda metadata: metadata.update(adaptation_state='BASELINE_UNCHANGED',
                policy_revision='another-policy'),
            lambda metadata: metadata.update(adaptation_state='BASELINE_UNCHANGED',
                policy_sha256='f'*64),
            lambda metadata: metadata.pop('policy_revision'),
        )
        base = self.server()
        for index, mutation in enumerate(mutations):
            metadata = dict(BASELINE_STRATEGY, adaptation_state='EXPERIMENTAL')
            mutation(metadata)
            value = snapshot(sequence=2)
            value['strategy_version'] = metadata
            value = sealed(value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.store.accept(value)
            code, _, raw = self.request(base, '/api/pons-simulator/snapshot', method='POST',
                authorization='Bearer '+SIMULATOR_TOKEN, value=value)
            self.assertEqual(code, 400)
            self.assertEqual(json.loads(raw), dict(error='invalid_simulator_snapshot'))
            for private in (b'SECRET', b'private.invalid', b'/srv/private', b'<script>'):
                self.assertNotIn(private, raw)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertNotIn('strategy_version', self.store.get())

    def test_manager_counters_are_independent_typed_measurements_and_preserve_observed_zero(self):
        value = snapshot()
        value['metrics']['strategy'] = dict(
            manager_decisions=metric('0', 'COUNT'), manager_rejections=metric('3', 'COUNT'))
        self.store.accept(sealed(value))
        strategy = simulator.SimulatorReader(self.store).view()['metrics']['strategy']
        self.assertEqual(strategy['manager_decisions'], dict(metric('0', 'COUNT'), state='CURRENT'))
        self.assertEqual(strategy['manager_rejections'], dict(metric('3', 'COUNT'), state='CURRENT'))
        self.assertEqual(strategy['evaluated'],
            dict(metric(None, 'COUNT', quality='UNAVAILABLE'), state='UNAVAILABLE'))
        before = self.path.read_bytes()
        for field in ('manager_decisions', 'manager_rejections'):
            for amount in (True, '-1', '1.5'):
                bad = deepcopy(value)
                bad['sequence'] = 2
                bad['metrics']['strategy'][field]['value'] = amount
                with self.subTest(field=field, amount=amount), self.assertRaises(ValueError):
                    self.store.accept(sealed(bad))
                self.assertEqual(self.path.read_bytes(), before)


class SimulatorChannelTests(SimulatorFixture):
    def test_missing_configuration_is_explicit_and_original_routes_are_not_claimed(self):
        channel = simulator.SimulatorChannel()
        status, headers, raw = channel.response('GET', '/api/pons-simulator/state')
        view = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(view['schema'], 'pons-simulator-view-v1')
        self.assertEqual(view['state'], 'UNAVAILABLE')
        self.assertIsNone(view['identity'])
        self.assertEqual(view['reason_codes'], ['CONFIGURATION_UNAVAILABLE'])
        self.assertIsNone(view['sequence'])
        self.assertIsNone(view['metrics']['financial']['cash']['value'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIsNone(channel.response('GET', '/api/dashboard/portfolio'))
        self.assertEqual(channel.response('POST', '/api/pons-simulator/state')[0], 405)
        self.assertEqual(channel.response('GET', '/api/pons-simulator/state?epoch=old')[0], 400)

    def test_configuration_cannot_alias_original_snapshot_by_path_hardlink_or_symlink(self):
        original = self.root/'original-snapshot.json'
        original.write_bytes(b'ORIGINAL_RETAINED_BYTES')
        config = dict(MM_PONS_SIMULATOR_EXPERIMENT_ID=EXPERIMENT,
            MM_PONS_SIMULATOR_EPOCH_ID=EPOCH,
            MM_PONS_SIMULATOR_SOURCE_COMMIT=SOURCE,
            MM_PONS_SIMULATOR_INCEPTION_SHA256=INCEPTION,
            MM_DASHBOARD_SNAPSHOT_PATH=str(original))
        alias = self.root/'hardlink.json'
        alias.hardlink_to(original)
        symlink = self.root/'symlink.json'
        symlink.symlink_to(original)
        for path in (original, alias, symlink):
            with self.subTest(path=path.name):
                channel = simulator.configured_channel(dict(config,
                    MM_PONS_SIMULATOR_SNAPSHOT_PATH=str(path)))
                view = json.loads(channel.response('GET', '/api/pons-simulator/state')[2])
                self.assertEqual(view['state'], 'UNAVAILABLE')
                self.assertEqual(view['reason_codes'], ['CONFIGURATION_UNAVAILABLE'])
                self.assertIsNone(channel.store)
        self.assertEqual(original.read_bytes(), b'ORIGINAL_RETAINED_BYTES')

    def test_bad_and_partial_configuration_never_select_historical_pilot_or_implicit_source(self):
        configurations = ({}, dict(MM_PONS_SIMULATOR_SNAPSHOT_PATH=str(self.path)),
            dict(MM_PONS_SIMULATOR_SNAPSHOT_PATH=str(self.path),
                MM_PONS_SIMULATOR_EXPERIMENT_ID='paper-pons-pilot-1000-20261023',
                MM_PONS_SIMULATOR_EPOCH_ID=EPOCH,
                MM_PONS_SIMULATOR_SOURCE_COMMIT=SOURCE,
                MM_PONS_SIMULATOR_INCEPTION_SHA256=INCEPTION))
        for config in configurations:
            with self.subTest(config=config):
                channel = simulator.configured_channel(config)
                self.assertIsNone(channel.store)
                self.assertEqual(json.loads(channel.response('GET', '/api/pons-simulator/state')[2])
                    ['reason_codes'], ['CONFIGURATION_UNAVAILABLE'])
        self.assertFalse(self.path.exists())

    def test_complete_configuration_binds_the_independent_epoch_without_creating_data(self):
        config = dict(MM_PONS_SIMULATOR_SNAPSHOT_PATH=str(self.path),
            MM_PONS_SIMULATOR_EXPERIMENT_ID=EXPERIMENT,
            MM_PONS_SIMULATOR_EPOCH_ID=EPOCH,
            MM_PONS_SIMULATOR_SOURCE_COMMIT=SOURCE,
            MM_PONS_SIMULATOR_INCEPTION_SHA256=INCEPTION)
        channel = simulator.configured_channel(config)
        self.assertIsNotNone(channel.store)
        self.assertEqual(channel.store.identity, dict(experiment_id=EXPERIMENT,
            epoch_id=EPOCH, source_commit=SOURCE, inception_sha256=INCEPTION))
        self.assertIsNone(channel.store.get())
        self.assertFalse(self.path.exists())
        del config['MM_PONS_SIMULATOR_EPOCH_ID']
        self.assertIsNone(simulator.configured_channel(config).store)


class SimulatorHTTPTests(SimulatorFixture):
    def original_store(self):
        return SnapshotStore(self.root/'original-latest.json',
            epoch='synthetic-original-dashboard', candidate='1'*40, clock=lambda: self.now)

    def test_bearer_tokens_are_isolated_and_owner_credentials_cannot_ingest(self):
        original = self.original_store()
        original.accept(original_snapshot(NOW))
        original_before = original.path.read_bytes()
        base = self.server(original_store=original)
        target = '/api/pons-simulator/snapshot'
        for auth in (None, OWNER_AUTH, 'Bearer '+ORIGINAL_TOKEN, 'Bearer incorrect'):
            code, _, raw = self.request(base, target, method='POST', authorization=auth, value=snapshot())
            self.assertEqual(code, 401)
            self.assertNotIn(b'synthetic-independent', raw)
        code, _, _ = self.request(base, target, method='POST',
            authorization='Bearer '+SIMULATOR_TOKEN, value=snapshot())
        self.assertEqual(code, 202)
        self.assertEqual(self.store.get(), snapshot())
        self.assertEqual(original.path.read_bytes(), original_before)
        code, _, _ = self.request(base, '/api/dashboard/snapshot', method='POST',
            authorization='Bearer '+SIMULATOR_TOKEN, value=original_snapshot(NOW+1))
        self.assertEqual(code, 401)
        self.assertEqual(original.path.read_bytes(), original_before)
        simulator_before = self.path.read_bytes()
        code, _, _ = self.request(base, '/api/dashboard/snapshot', method='POST',
            authorization='Bearer '+ORIGINAL_TOKEN, value=original_snapshot(NOW+1))
        self.assertEqual(code, 202)
        self.assertEqual(self.path.read_bytes(), simulator_before)

    def test_equal_tokens_disable_only_new_ingest_and_preserve_original_authority(self):
        original = self.original_store()
        original.accept(original_snapshot(NOW))
        base = self.server(original_store=original, simulator_token=ORIGINAL_TOKEN)
        code, _, raw = self.request(base, '/api/pons-simulator/snapshot', method='POST',
            authorization='Bearer '+ORIGINAL_TOKEN, value=snapshot())
        self.assertEqual(code, 503)
        self.assertEqual(json.loads(raw), dict(error='simulator_ingestion_unavailable'))
        self.assertFalse(self.path.exists())
        code, _, _ = self.request(base, '/api/dashboard/snapshot', method='POST',
            authorization='Bearer '+ORIGINAL_TOKEN, value=original_snapshot(NOW+1))
        self.assertEqual(code, 202)
        self.assertEqual(original.get()['captured_at'], utc(NOW+1))
        code, _, raw = self.request(base, '/api/pons-simulator/state', authorization=OWNER_AUTH)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['state'], 'UNAVAILABLE')

    def test_new_read_routes_share_existing_basic_policy_without_bearer_read_authority(self):
        self.store.accept(snapshot())
        base = self.server()
        for target in ('/api/pons-simulator/state', '/dashboard/pons-simulator',
                       '/dashboard/pons-simulator/app.js', '/dashboard/pons-simulator/style.css'):
            for auth in (None, 'Bearer '+SIMULATOR_TOKEN):
                with self.subTest(target=target, authorization=auth):
                    self.assertEqual(self.request(base, target, authorization=auth)[0], 401)
            code, headers, _ = self.request(base, target, authorization=OWNER_AUTH)
            self.assertEqual(code, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
        code, _, raw = self.request(base, '/api/pons-simulator/state', authorization=OWNER_AUTH)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['identity']['experiment_id'], EXPERIMENT)
        code, _, raw = self.request(base, '/api/dashboard/portfolio', authorization=OWNER_AUTH)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['data']['state'], 'NOT_INITIALIZED')
        self.assertNotIn(EXPERIMENT.encode(), raw)
        self.assertNotIn(b'EXPERIMENTAL PONS CURRENT', raw)

    def test_public_reads_do_not_open_either_ingest_route_or_mutating_methods(self):
        original = self.original_store()
        base = self.server(original_store=original, public_reads=True)
        for target in ('/dashboard/pons-simulator', '/api/pons-simulator/state',
                       '/dashboard', '/api/dashboard/portfolio'):
            code, headers, _ = self.request(base, target)
            self.assertEqual(code, 200)
            self.assertNotIn('WWW-Authenticate', headers)
        self.assertEqual(self.request(base, '/api/pons-simulator/snapshot',
            method='POST', value=snapshot())[0], 401)
        self.assertEqual(self.request(base, '/api/dashboard/snapshot',
            method='POST', value=original_snapshot(NOW))[0], 401)
        self.assertEqual(self.request(base, '/api/pons-simulator/state',
            method='POST', raw=b'{}')[0], 405)
        self.assertEqual(self.request(base, '/api/dashboard/portfolio',
            method='POST', raw=b'{}')[0], 405)

    def test_ingest_refuses_malformed_hostile_and_equivocating_content_without_leaks(self):
        base = self.server()
        auth = 'Bearer '+SIMULATOR_TOKEN
        code, _, _ = self.request(base, '/api/pons-simulator/snapshot', method='POST',
            authorization=auth, value=snapshot())
        self.assertEqual(code, 202)
        before = self.path.read_bytes()
        hostile = snapshot(sequence=2)
        hostile['provider_url'] = 'https://private.invalid/SYNTHETIC_SECRET'
        wrong_identity = snapshot(sequence=2)
        wrong_identity['identity']['experiment_id'] = 'paper-pons-pilot-1000-20261023'
        equivocation = snapshot()
        equivocation['execution_state'] = 'FAILED'
        for value in (sealed(hostile), sealed(wrong_identity), sealed(equivocation)):
            code, _, raw = self.request(base, '/api/pons-simulator/snapshot', method='POST',
                authorization=auth, value=value)
            self.assertEqual(code, 400)
            self.assertNotIn(b'SYNTHETIC_SECRET', raw)
            self.assertNotIn(b'private.invalid', raw)
            self.assertEqual(self.path.read_bytes(), before)
        for raw in (b'{"sequence":1,"sequence":2}', b'{"value":NaN}'):
            code, _, body = self.request(base, '/api/pons-simulator/snapshot', method='POST',
                authorization=auth, raw=raw)
            self.assertEqual(code, 400)
            self.assertNotIn(raw, body)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
