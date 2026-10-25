"""Explicit financial-source selection never combines the two account histories."""
from copy import deepcopy
import hashlib
import json
import os
import threading
import unittest

from dashboard.__main__ import make_server
from dashboard.active_portfolio import (ActivePortfolioReader, ActivePortfolioStore,
    EXPERIMENT_EPOCH, EXPERIMENT_INCEPTION, NATIVE_SOURCE, RISK_SHA256,
    SelectedOperationsChannel, select_financial_source)
from dashboard.api import Dashboard
from dashboard.model import canonical, inception_receipt
from dashboard.snapshots import CHECKS, PHASES, SCHEMA, SnapshotReader, SnapshotStore
from dashboard import simulator
from dashboard.tests.test_simulator import (SimulatorFixture, SOURCE, NOW,
    ORIGINAL_TOKEN, SIMULATOR_TOKEN, OWNER, OWNER_AUTH, snapshot as ops_snapshot,
    sealed, utc)
from meme_machine.portfolio_snapshot_transport import build_snapshot


def full_snapshot(now, *, epoch=EXPERIMENT_EPOCH, capital='1000.00', sequence=7):
    shared = capital != '500.00'
    receipt = inception_receipt(epoch, utc(NOW-100), 'isolated-source-selection-fixture',
                                starting_capital=capital, shared=shared)
    inception = hashlib.sha256(canonical(receipt).encode()).hexdigest()
    balances = dict(equity=capital, available_cash=capital, reserved_cash='0.00',
        deployed_capital='0.00', realized_pnl='0.00', fees='0.00', shared_costs='0.00')
    identities = dict(source_sha=NATIVE_SOURCE, policy_hash='c'*64, config_hash='d'*64)
    export = dict(schema='meme-machine-portfolio-export-v1', mode='canonical',
        epoch_id=epoch, inception_sha256=inception, sequence=sequence,
        as_of=utc(now), valid_until=utc(now+45), complete_lifecycle_coverage=True,
        balances=balances, positions=[], history_complete=True,
        history=[dict(epoch_id=epoch, series='portfolio', at=utc(NOW-100), value=capital),
                 dict(epoch_id=epoch, series='portfolio', at=utc(now), value=capital)],
        lane_identities={lane:dict(identities) for lane in ('pump', 'pons', 'ramses', 'meteora')},
        **identities)
    if shared:
        export['shared_capital'] = dict(sizing_basis='shared_realized_equity',
            inception_equity=capital, realized_equity=capital, actual_cash=capital,
            free_cash=capital, deployed_basis='0.00', active_reservations='0.00',
            pending_authoritative_commitments='0.00', required_funding_obligations='0.00',
            directional_sizing={regime:dict(realized_equity=capital,
                new_position_target='50.00', staged_add_equity_ceiling='25.00',
                combined_basis_ceiling='75.00') for regime in (
                    'pump_current', 'pump_survivor', 'pons_current', 'pons_survivor')},
            regimes={regime:dict(realized_pnl='0.00') for regime in (
                'pump_current', 'pump_survivor', 'pons_current', 'pons_survivor')})
    proof = dict(journal_sequence=sequence-1, journal_hash='e'*64,
        projection_sha256='f'*64, epoch_id=epoch, inception_sha256=inception,
        risk_sha256=RISK_SHA256)
    admission = dict(schema='pons-current-paper-report-v1', source_commit=SOURCE,
        epoch_id=epoch, inception_sha256=inception,
        policy_sha256=simulator.BASELINE_STRATEGY['policy_sha256'],
        state='DISABLED', heartbeat_at=utc(now), permission_enabled=False,
        new_risk_enabled=False, authority_sha256=None,
        ledger_sequence=proof['journal_sequence'], ledger_sha256=proof['journal_hash'])
    return dict(schema=SCHEMA, captured_at=utc(now), source=dict(epoch_id=epoch,
        candidate_commit=SOURCE, publisher_commit=SOURCE, deployed_commit=NATIVE_SOURCE),
        observer=dict(at=utc(now), health_at=utc(now), epoch_id=epoch, lanes={},
                      financial_admission=admission),
        monitor=dict(at=utc(now), conditions=[]),
        service=dict(unit='meme-machine-pons-current.service',
                     ActiveState='active', SubState='running', MainPID='123'),
        acceptance={phase:dict(status='NOT_STARTED', elapsed_seconds=0,
                              verified_result=False) for phase in PHASES},
        portfolio=dict(bundle=build_snapshot(receipt, export), observation=dict(
            state='CURRENT', epoch_id=epoch, sequence=sequence, inception_sha256=inception,
            at=utc(now), reconciliation='PASS', checks={key:True for key in CHECKS},
            balances=dict(balances, unrealized_pnl='0.00'), financial_statement=proof)))


class ActivePortfolioTests(SimulatorFixture):
    def setUp(self):
        super().setUp()
        self.active_value = full_snapshot(NOW)
        self.inception = self.active_value['portfolio']['bundle']['inception_sha256']
        self.original_value = full_snapshot(NOW, epoch='original-retained-archive', capital='500.00')
        self.original = SnapshotStore(self.root/'original.json',
            epoch='original-retained-archive', candidate=SOURCE, clock=lambda:self.now)
        self.original.accept(self.original_value)
        self.active = self.new_active()

    def new_active(self):
        return ActivePortfolioStore(self.root/'selected.json', archive_path=self.original.path,
            epoch=EXPERIMENT_EPOCH, candidate=SOURCE, inception_sha256=self.inception,
            clock=lambda:self.now)

    def financial_api(self, reader, route):
        code, _, body = Dashboard(reader).response('GET', '/api/dashboard/'+route)
        self.assertEqual(code, 200)
        return json.loads(body)

    def test_selected_reader_uses_only_experimental_capital_history_and_identity(self):
        self.active.accept(self.active_value)
        reader = ActivePortfolioReader(self.active, clock=lambda:self.now)
        original_before = self.original.path.read_bytes()
        p = self.financial_api(reader, 'portfolio')['data']
        self.assertEqual(p['epoch']['epoch_id'], EXPERIMENT_EPOCH)
        self.assertEqual(p['financial_identity']['inception_sha256'], self.inception)
        self.assertEqual(p['metrics']['available_cash']['value'], '1000.00')
        self.assertEqual(p['financial_source'], 'pons_experiment')
        chart = self.financial_api(reader, 'equity?series=portfolio')
        self.assertEqual(chart['financial_identity'], p['financial_identity'])
        self.assertNotIn('original-retained-archive', json.dumps(chart))
        self.assertNotIn('500.00', json.dumps(chart))
        self.assertEqual(reader.view()['system']['paper_state'], 'DISABLED')
        self.assertNotIn('candidate_not_deployed', reader.view()['system']['operations']['alerts'])
        self.assertEqual(self.original.path.read_bytes(), original_before)
        archived = SnapshotReader(self.original, clock=lambda:self.now).view()
        self.assertEqual(archived['portfolio']['metrics']['available_cash']['value'], '500.00')

    def test_wrong_source_epoch_inception_service_or_proof_cannot_replace_selected_feed(self):
        self.active.accept(self.active_value)
        before = self.active.path.read_bytes()
        for mutate in (
            lambda v:v['source'].update(epoch_id='other'),
            lambda v:v['source'].update(candidate_commit='0'*40),
            lambda v:v['source'].update(publisher_commit='0'*40),
            lambda v:v['source'].update(deployed_commit=SOURCE),
            lambda v:v['service'].update(unit='meme-machine-paper.service'),
            lambda v:v['portfolio']['observation']['financial_statement'].update(inception_sha256='0'*64),
            lambda v:v['portfolio']['observation']['financial_statement'].update(risk_sha256='0'*64),
            lambda v:v['observer']['financial_admission'].update(ledger_sha256='0'*64),
            lambda v:v['observer']['financial_admission'].update(permission_enabled=True),
            lambda v:v['portfolio'].update(bundle=None),
        ):
            value = deepcopy(self.active_value)
            value['captured_at'] = utc(NOW+1)
            mutate(value)
            with self.assertRaises((ValueError, RuntimeError)):
                self.active.accept(value)
            self.assertEqual(self.active.path.read_bytes(), before)

    def test_exact_retry_recovery_and_new_report_do_not_mutate_ledger_history(self):
        result = self.active.accept(self.active_value)
        self.assertEqual(result, dict(sequence=7, idempotent=False))
        before = self.active.path.read_bytes()
        self.now += 121
        reopened = self.new_active()
        self.assertEqual(reopened.accept(self.active_value), dict(sequence=7, idempotent=True))
        self.assertEqual(reopened.path.read_bytes(), before)
        self.assertEqual(ActivePortfolioReader(reopened, clock=lambda:self.now).view()['state'], 'STALE')
        self.now = NOW+2
        # Same journal sequence, truthful newer sampled export timestamps.
        fresh = full_snapshot(self.now)
        reopened.accept(fresh)
        self.assertEqual(reopened.get()['portfolio']['bundle']['sequence'], 7)
        for mutate in (
            lambda v:v['portfolio']['observation']['financial_statement'].update(journal_hash='0'*64),
            lambda v:v['portfolio']['observation']['financial_statement'].update(projection_sha256='0'*64),
        ):
            bad = full_snapshot(self.now+1); mutate(bad)
            with self.assertRaises(ValueError): reopened.accept(bad)
        with self.assertRaises(ValueError): reopened.accept(self.active_value)
        conflict = deepcopy(fresh); conflict['monitor']['conditions'] = ['conflict']
        with self.assertRaises(ValueError): reopened.accept(conflict)

    def test_missing_corrupt_or_removed_selected_data_never_falls_back_to_archive(self):
        original = self.original.path.read_bytes()
        missing = ActivePortfolioReader(self.active, clock=lambda:self.now).view()
        self.assertEqual(missing['state'], 'UNAVAILABLE')
        self.assertIsNone(missing['portfolio']['metrics']['available_cash']['value'])
        self.active.accept(self.active_value)
        self.active.path.unlink()
        view = ActivePortfolioReader(self.active, clock=lambda:self.now).view()
        self.assertEqual(view['state'], 'UNAVAILABLE')
        self.assertIsNone(view['portfolio']['epoch'])
        self.active.path.write_text('{corrupt')
        view = ActivePortfolioReader(self.active, clock=lambda:self.now).view()
        self.assertEqual(view['state'], 'FAIL_CLOSED')
        self.assertIsNone(view['portfolio']['metrics']['equity']['value'])
        self.assertEqual(self.original.path.read_bytes(), original)
        with self.assertRaises(ValueError): self.new_active()

    def test_alias_and_symlink_caches_are_refused_without_touching_original(self):
        original = self.original.path.read_bytes()
        for kind in ('same', 'symlink', 'hardlink', 'parent_symlink'):
            path = self.root/('alias-'+kind)
            if kind == 'same': path = self.original.path
            if kind == 'symlink': path.symlink_to(self.original.path)
            if kind == 'hardlink': os.link(self.original.path, path)
            if kind == 'parent_symlink':
                path.symlink_to(self.root, target_is_directory=True)
                path = path/'another.json'
            with self.assertRaises(ValueError):
                ActivePortfolioStore(path, archive_path=self.original.path,
                    epoch=EXPERIMENT_EPOCH, candidate=SOURCE, inception_sha256=self.inception)
            if kind == 'hardlink': path.unlink()
            self.assertEqual(self.original.path.read_bytes(), original)

    def test_explicit_configuration_pins_existing_account_and_does_not_fallback(self):
        reader = SnapshotReader(self.original, clock=lambda:self.now)
        self.assertIs(select_financial_source({}, reader, self.original).reader, reader)
        config = dict(MM_DASHBOARD_FINANCIAL_SOURCE='pons_experiment',
            MM_DASHBOARD_ACTIVE_SNAPSHOT_PATH=str(self.root/'new-selected.json'),
            MM_DASHBOARD_ACTIVE_EPOCH=EXPERIMENT_EPOCH,
            MM_DASHBOARD_ACTIVE_CANDIDATE=SOURCE,
            MM_DASHBOARD_ACTIVE_INCEPTION_SHA256=EXPERIMENT_INCEPTION)
        selection = select_financial_source(config, reader, self.original, clock=lambda:self.now)
        self.assertTrue(selection.selected)
        self.assertIsNotNone(selection.store)
        self.assertEqual(selection.reader.view()['state'], 'UNAVAILABLE')
        for key in config:
            bad = dict(config)
            bad[key] = str(self.original.path) if key == 'MM_DASHBOARD_ACTIVE_SNAPSHOT_PATH' else 'wrong'
            selected = select_financial_source(bad, reader, self.original, clock=lambda:self.now)
            self.assertTrue(selected.selected)
            self.assertIsNone(selected.store)
            self.assertEqual(selected.reader.view()['state'], 'FAIL_CLOSED')
            self.assertIsNone(selected.reader.view()['portfolio']['epoch'])

    def test_paper_state_reports_authority_and_freshness_instead_of_service_liveness(self):
        self.active.accept(self.active_value)
        reader = ActivePortfolioReader(self.active, clock=lambda:self.now)
        self.assertEqual(reader.view()['system']['paper_state'], 'DISABLED')
        active = full_snapshot(NOW+1)
        active['observer']['financial_admission'].update(state='READY',
            permission_enabled=True, new_risk_enabled=True, authority_sha256='1'*64)
        self.now = NOW+1
        self.active.accept(active)
        self.assertEqual(reader.view()['system']['paper_state'], 'READY')
        self.now += 47
        self.assertEqual(reader.view()['system']['paper_state'], 'STALE')
        self.assertNotEqual(reader.view()['system']['paper_state'], 'RUNNING')

    def active_server(self):
        reader = ActivePortfolioReader(self.active, clock=lambda:self.now)
        channel = SelectedOperationsChannel(simulator.SimulatorChannel(self.store), reader)
        server = make_server(Dashboard(reader), '127.0.0.1', 0, owner=OWNER,
            ingest_token=ORIGINAL_TOKEN, snapshot_store=self.original, public_reads=False,
            simulator_channel=channel, simulator_ingest_token=SIMULATOR_TOKEN,
            active_portfolio_store=self.active)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_receivers_have_distinct_write_authority_and_old_ingest_cannot_select_archive(self):
        base = self.active_server()
        route = '/api/dashboard/active-portfolio/snapshot'
        original = self.original.path.read_bytes()
        for token in (None, ORIGINAL_TOKEN):
            self.assertEqual(self.request(base, route, method='POST', value=self.active_value,
                authorization='Bearer '+token if token else None)[0], 401)
        status, _, raw = self.request(base, route, method='POST', value=self.active_value,
            authorization='Bearer '+SIMULATOR_TOKEN)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(raw), dict(status='accepted', captured_at=utc(NOW),
                                              sequence=7, idempotent=False))
        self.assertEqual(self.original.path.read_bytes(), original)
        self.assertEqual(self.request(base, '/api/dashboard/snapshot', method='POST',
            authorization='Bearer '+SIMULATOR_TOKEN, value=self.original_value)[0], 401)
        self.assertEqual(self.request(base, '/api/dashboard/snapshot', method='POST',
            authorization='Bearer '+ORIGINAL_TOKEN, value=self.original_value)[0], 202)
        self.assertEqual(json.loads(self.request(base, '/api/dashboard/portfolio',
            authorization=OWNER_AUTH)[2])['data']['epoch']['epoch_id'], EXPERIMENT_EPOCH)
        self.assertEqual(self.request(base, route, method='POST',
            authorization='Bearer '+SIMULATOR_TOKEN, value=ops_snapshot())[0], 400)

    def test_operations_binding_requires_fresh_matching_canonical_identity(self):
        reader = ActivePortfolioReader(self.active, clock=lambda:self.now)
        channel = SelectedOperationsChannel(simulator.SimulatorChannel(self.store), reader)
        value = ops_snapshot(); value['identity']['inception_sha256'] = self.inception
        # Reopen the independent operations cache with this fixture's inception.
        self.store = simulator.SimulatorStore(self.path,
            experiment_id=value['identity']['experiment_id'], epoch_id=EXPERIMENT_EPOCH,
            source_commit=SOURCE, inception_sha256=self.inception, clock=lambda:self.now)
        channel = SelectedOperationsChannel(simulator.SimulatorChannel(self.store), reader)
        self.store.accept(sealed(value))
        self.assertEqual(json.loads(channel.response('GET', '/api/dashboard/live')[2])[
            'account_cutover']['state'], 'UNAVAILABLE')
        self.active.accept(self.active_value)
        live = json.loads(channel.response('GET', '/api/dashboard/live')[2])
        self.assertEqual(live['account_cutover']['state'], 'VERIFIED')
        self.assertFalse(live['financial_authority'])
        self.assertNotIn('financial', live['metrics'])
        self.now += 61
        self.assertEqual(json.loads(channel.response('GET', '/api/dashboard/live')[2])[
            'account_cutover']['state'], 'UNAVAILABLE')
