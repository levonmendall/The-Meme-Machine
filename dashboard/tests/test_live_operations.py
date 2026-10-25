"""One dashboard: authenticated telemetry never becomes portfolio accounting."""
import json

from dashboard import simulator
from dashboard.tests.test_simulator import (
    SimulatorFixture, snapshot, original_snapshot, SOURCE, EXPERIMENT, EPOCH,
    INCEPTION, NOW, OWNER_AUTH, ORIGINAL_TOKEN, SIMULATOR_TOKEN, sealed)


class ConsolidatedOperationsTests(SimulatorFixture):
    def test_old_publisher_and_new_internal_alias_preserve_original_snapshot(self):
        from dashboard.snapshots import SnapshotStore
        original = SnapshotStore(self.root/'original.json',
            epoch='synthetic-original-dashboard', candidate='1'*40, clock=lambda: self.now)
        original.accept(original_snapshot(NOW))
        before = original.path.read_bytes()
        base = self.server(original_store=original)
        financial_routes = ('portfolio', 'equity?series=portfolio', 'positions', 'trades')
        observed = {path: self.request(base, '/api/dashboard/'+path,
                    authorization=OWNER_AUTH)[2] for path in financial_routes}
        for sequence, path in enumerate(('/api/pons-simulator/snapshot',
                                        '/api/dashboard/live/snapshot'), 1):
            value = snapshot(sequence=sequence)
            value['metrics']['financial']['cash']['value'] = '987654321.99'
            value = sealed(value)
            for token in (ORIGINAL_TOKEN, None):
                auth = 'Bearer '+token if token else None
                self.assertEqual(self.request(base, path, method='POST',
                    authorization=auth, value=value)[0], 401)
            status, _, raw = self.request(base, path, method='POST',
                authorization='Bearer '+SIMULATOR_TOKEN, value=value)
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(raw), dict(status='accepted', idempotent=False, sequence=sequence))
            status, _, raw = self.request(base, '/api/dashboard/live', authorization=OWNER_AUTH)
            self.assertEqual(status, 200)
            live = json.loads(raw)
            self.assertEqual(live['schema'], 'pons-live-operations-v1')
            self.assertFalse(live['financial_authority'])
            self.assertEqual(live['account_cutover']['state'], 'NOT_ESTABLISHED')
            self.assertNotIn(b'987654321', raw)
            self.assertNotIn('financial', live['metrics'])
            for name in ('lifecycles', 'history'):
                self.assertNotIn(name, live)
            for name in ('entries', 'partial_exits', 'exits', 'open_positions', 'round_trips'):
                self.assertNotIn(name, live['metrics']['activity'])
            self.assertEqual(original.path.read_bytes(), before)
            for route in financial_routes:
                self.assertEqual(self.request(base, '/api/dashboard/'+route,
                    authorization=OWNER_AUTH)[2], observed[route])

    def test_cache_restart_and_old_retry_never_renew_market_freshness(self):
        value = snapshot()
        self.store.accept(value)
        before = self.path.read_bytes()
        self.now = NOW+61
        reopened = simulator.SimulatorStore(self.path,
            experiment_id=EXPERIMENT, epoch_id=EPOCH, source_commit=SOURCE,
            inception_sha256=INCEPTION, clock=lambda: self.now)
        self.assertEqual(reopened.accept(value), dict(idempotent=True, sequence=1))
        self.assertEqual(self.path.read_bytes(), before)
        result = json.loads(simulator.SimulatorChannel(reopened).response(
            'GET', '/api/dashboard/live')[2])
        self.assertEqual(result['state'], 'STALE')
        self.assertEqual(result['captured_at'], value['captured_at'])
        self.assertEqual(result['metrics']['activity']['events_processed']['state'], 'STALE')
        self.assertFalse(result['source_ledger_authoritative'])

    def test_unavailable_intake_cannot_hide_original_dashboard_or_claim_authority(self):
        base = self.server(channel=simulator.SimulatorChannel())
        code, _, raw = self.request(base, '/api/dashboard/live', authorization=OWNER_AUTH)
        self.assertEqual(code, 200)
        live = json.loads(raw)
        self.assertEqual(live['state'], 'UNAVAILABLE')
        self.assertEqual(live['account_cutover']['state'], 'NOT_ESTABLISHED')
        self.assertEqual(self.request(base, '/dashboard', authorization=OWNER_AUTH)[0], 200)
        self.assertEqual(self.request(base, '/api/dashboard/portfolio', authorization=OWNER_AUTH)[0], 200)

    def test_legacy_interface_and_arbitrary_descendants_are_gone_without_ingest_redirect(self):
        base = self.server(public_reads=True)
        for route in ('/dashboard/pons-simulator', '/dashboard/pons-simulator/',
                      '/dashboard/pons-simulator/app.js', '/dashboard/pons-simulator/style.css',
                      '/dashboard/pons-simulator/unlisted', '/api/pons-simulator/state'):
            code, headers, raw = self.request(base, route)
            self.assertEqual(code, 410)
            self.assertNotIn('Location', headers)
            self.assertEqual(json.loads(raw)['dashboard'], '/dashboard')
        code, _, _ = self.request(base, '/api/pons-simulator/snapshot', method='POST',
            authorization='Bearer '+SIMULATOR_TOKEN, value=snapshot())
        self.assertEqual(code, 202)
