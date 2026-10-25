"""Synthetic receiver/reporting boundaries; no trading or financial authority."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from dashboard import simulator
from dashboard.tests.test_simulator import NOW, sealed, snapshot, utc


def reported(**changes):
    value = snapshot()
    identity = value['identity']
    value['paper'] = dict(schema='pons-current-paper-report-v1',
        source_commit=identity['source_commit'], epoch_id=identity['epoch_id'],
        inception_sha256=identity['inception_sha256'],
        policy_sha256=simulator.BASELINE_STRATEGY['policy_sha256'],
        authority_sha256='e'*64, permission_enabled=True, new_risk_enabled=False,
        state='READY', heartbeat_at=utc(NOW), ledger_sequence=33, ledger_sha256='f'*64,
        lifecycle_total=len(value['lifecycles']), lifecycle_truncated=False,
        event_total=len(value['history']['events']['rows']), events_truncated=False)
    value['paper'].update(changes)
    return sealed(value)


class PaperReportTests(unittest.TestCase):
    def validate(self, value):
        return simulator.validate_snapshot(value, value['identity'])

    def test_permission_and_readiness_are_distinct_from_a_fill(self):
        value = reported()
        before = deepcopy(value)
        self.validate(value)
        self.assertEqual(value, before)
        self.assertTrue(value['paper']['permission_enabled'])
        self.assertFalse(value['paper']['new_risk_enabled'])
        self.assertEqual(value['metrics']['activity']['entries']['value'], '1')
        # Only the supplied ledger fixture creates that count; a READY report
        # cannot add an entry or change the financial data itself.
        flat = reported()
        flat['metrics']['activity'].pop('entries')
        self.validate(sealed(flat))
        self.assertNotIn('entries', flat['metrics']['activity'])

    def test_disabled_permission_does_not_erase_a_managed_lifecycle(self):
        value = reported(state='MANAGING', permission_enabled=False,
                         new_risk_enabled=False, authority_sha256=None)
        self.validate(value)
        store = type('Store', (), {'get': lambda _: deepcopy(value),
                                  'clock': staticmethod(lambda: NOW), 'identity': value['identity']})()
        view = simulator.SimulatorReader(store).view()
        self.assertEqual(view['paper']['state'], 'MANAGING')
        self.assertFalse(view['paper']['permission_enabled'])
        self.assertEqual(view['lifecycles'][0]['state'], 'OPEN')
        self.assertEqual(view['metrics']['financial']['cash']['value'], '950.00')

    def test_identity_policy_and_permission_contradictions_are_rejected(self):
        cases = [dict(source_commit='b'*40), dict(epoch_id='paper-pons-simulator-1000-20261023'),
            dict(inception_sha256='a'*64), dict(policy_sha256='a'*64),
            dict(authority_sha256=None), dict(authority_sha256='PRIVATE_PROVIDER_TOKEN'),
            dict(permission_enabled=1), dict(new_risk_enabled=1),
            dict(state='READY', permission_enabled=False),
            dict(state='DISABLED', permission_enabled=True),
            dict(state='MANAGING', permission_enabled=False, new_risk_enabled=True),
            dict(state='WARMING', new_risk_enabled=True),
            dict(state='UNAVAILABLE', permission_enabled=True),
            dict(heartbeat_at=utc(NOW+1)), dict(heartbeat_at=None),
            dict(ledger_sequence=None), dict(ledger_sha256=None),
            dict(ledger_sequence=True), dict(ledger_sequence=0)]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(reported(**change))

    def test_unknowns_remain_unknown_and_do_not_require_a_live_authority(self):
        value = reported(state='UNAVAILABLE', heartbeat_at=None,
            permission_enabled=None, new_risk_enabled=None, authority_sha256=None,
            ledger_sequence=None, ledger_sha256=None)
        self.validate(value)
        value = reported(state='WARMING', new_risk_enabled=None)
        self.validate(value)
        self.assertIsNone(value['paper']['new_risk_enabled'])

    def test_stale_or_future_view_never_renews_the_resident_heartbeat(self):
        value = reported(new_risk_enabled=True)
        original = deepcopy(value)
        for now in (NOW+61, NOW-1):
            store = type('Store', (), {'get': lambda _: deepcopy(value),
                'clock': staticmethod(lambda: now), 'identity': value['identity']})()
            view = simulator.SimulatorReader(store).view()
            self.assertEqual(view['paper']['state'], 'STALE')
            self.assertEqual(view['paper']['heartbeat_at'], original['paper']['heartbeat_at'])
            self.assertEqual(view['paper']['authority_sha256'], original['paper']['authority_sha256'])
        self.assertEqual(value, original)

    def test_resident_staleness_is_independent_of_fresh_observer_snapshot(self):
        value = reported(heartbeat_at=utc(NOW-61))
        self.validate(value)
        store = type('Store', (), {'get': lambda _: deepcopy(value),
            'clock': staticmethod(lambda: NOW), 'identity': value['identity']})()
        view = simulator.SimulatorReader(store).view()
        self.assertEqual(view['state'], 'CURRENT')
        self.assertEqual(view['paper']['state'], 'STALE')

    def test_populations_are_bounded_and_reported_truncation_must_match(self):
        value = reported(lifecycle_total=17, lifecycle_truncated=True,
                         event_total=99, events_truncated=True)
        self.validate(value)
        for changes in (dict(lifecycle_total=0), dict(lifecycle_total=True),
                        dict(lifecycle_total=17, lifecycle_truncated=False),
                        dict(events_truncated=True), dict(event_total=99)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(reported(**changes))

    def test_private_fields_are_rejected_without_reflecting_their_values(self):
        value = reported()
        value['paper']['authority_path'] = '/PRIVATE_PROVIDER_TOKEN_AND_ACCOUNT_PATH'
        with self.assertRaises(ValueError) as raised:
            self.validate(sealed(value))
        self.assertNotIn('PRIVATE', str(raised.exception))

    def test_legacy_feed_and_original_financial_values_remain_unchanged(self):
        value = snapshot()
        self.validate(value)
        store = type('Store', (), {'get': lambda _: deepcopy(value),
            'clock': staticmethod(lambda: NOW), 'identity': value['identity']})()
        self.assertNotIn('paper', simulator.SimulatorReader(store).view())
        value['metrics']['activity']['partial_exits'] = dict(
            value='2', quality='MEASURED', unit='COUNT', as_of=utc(NOW))
        self.validate(sealed(value))
        if value['history']['events']['rows']:
            value['history']['events']['rows'][0]['kind'] = 'ADD'
            self.validate(sealed(value))

    def test_original_operations_status_exposes_permission_but_no_experimental_finances(self):
        value = reported()
        store = type('Store', (), {'get': lambda _: deepcopy(value),
            'clock': staticmethod(lambda: NOW), 'identity': value['identity']})()
        code, _, raw = simulator.SimulatorChannel(store).response('GET', '/api/dashboard/live')
        self.assertEqual(code, 200)
        view = json.loads(raw)
        self.assertEqual(view['paper']['state'], 'READY')
        self.assertTrue(view['paper']['permission_enabled'])
        self.assertFalse(view['source_ledger_authoritative'])
        self.assertFalse(view['financial_authority'])
        self.assertEqual(view['account_cutover']['state'], 'NOT_ESTABLISHED')
        for key in ('ledger_sequence', 'ledger_sha256', 'lifecycle_total', 'event_total'):
            self.assertNotIn(key, view['paper'])
        self.assertNotIn('financial', view['metrics'])
        self.assertNotIn('history', view)
        self.assertNotIn('lifecycles', view)


if __name__ == '__main__':
    unittest.main()
