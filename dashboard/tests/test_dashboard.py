import builtins
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.api import Dashboard
from dashboard.fixtures import example, FIXTURE_NOW, iso, write
from dashboard.model import Reader, inception_receipt, canonical, decimal, MAX_POSITIONS


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.epoch, self.accounting, self.telemetry = example()
        self.now = FIXTURE_NOW
        self.save()
        self.reader = self.new_reader()
        self.api = Dashboard(self.reader)

    def new_reader(self, mode='fixture'):
        return Reader(self.root/'inception.json', self.root/'accounting.json',
                      self.root/'telemetry.json', mode=mode, clock=lambda: self.now)

    def save(self):
        for name, obj in (('inception', self.epoch), ('accounting', self.accounting), ('telemetry', self.telemetry)):
            (self.root/(name+'.json')).write_text(json.dumps(obj))

    def view(self):
        self.save()
        return self.reader.view()

    def get(self, path, method='GET'):
        code, headers, body = self.api.response(method, '/api/dashboard/'+path)
        return code, json.loads(body)

    def metric(self, name, lane=None):
        v = self.view()
        return (v['lanes'][lane] if lane else v['portfolio'])['metrics'][name]

    def flat(self):
        self.accounting['positions'] = []
        self.accounting['balances'] = dict(equity='500.00', available_cash='500.00', reserved_cash='0.00',
            deployed_capital='0.00', realized_pnl='0.00', fees='0.00', shared_costs='0.00')
        self.accounting['history'] = []

    def test_live_default_not_initialized_never_fixture_fallback(self):
        view = Reader().view()
        self.assertEqual(view['state'], 'NOT_INITIALIZED')
        self.assertIsNone(view['portfolio']['metrics']['equity']['value'])
        self.assertIsNone(view['portfolio']['metrics']['open_positions']['value'])
        self.assertEqual(view['positions'], [])

    def test_fixture_cannot_be_read_as_canonical(self):
        self.assertEqual(self.new_reader('canonical').view()['state'], 'FAIL_CLOSED')

    def test_exact_500_no_trades_has_real_zero_and_undefined_win_rate(self):
        self.flat()
        p = self.view()['portfolio']
        self.assertEqual(p['metrics']['equity']['value'], '500.00')
        self.assertEqual(p['metrics']['open_positions']['value'], 0)
        self.assertEqual(p['metrics']['net_pnl']['value'], '0.00')
        self.assertIsNone(p['metrics']['win_rate']['value'])
        self.assertIsNone(p['metrics']['max_drawdown_pct']['value'])
        self.assertEqual(p['reconciliation']['state'], 'CURRENT')

    def test_initialized_portfolio_reconciles_exactly(self):
        p = self.view()['portfolio']
        self.assertEqual(p['metrics']['equity']['value'], '512.34')
        self.assertEqual(p['metrics']['net_pnl']['value'], '12.34')
        self.assertEqual(p['metrics']['return_pct']['value'], '2.468')
        self.assertEqual(set(p['reconciliation']['value'].values()), {True})

    def test_wins_losses_breakevens_use_completed_net_result(self):
        p = self.view()['portfolio']['metrics']
        self.assertEqual([p[k]['value'] for k in ('wins','losses','breakevens','completed_trades')], [4,3,1,8])
        self.assertEqual(Decimal(p['win_rate']['value']).quantize(Decimal('.0001')), Decimal('57.1429'))

    def test_partial_realization_runner_is_one_open_lifecycle(self):
        m = self.view()['lanes']['pons']['metrics']
        self.assertEqual(m['trades_taken']['value'], 3)
        self.assertEqual(m['open_positions']['value'], 1)
        self.assertEqual(m['completed_trades']['value'], 2)
        self.assertEqual(m['realized_pnl']['value'], '3.80')
        self.assertEqual(m['unrealized_pnl']['value'], '0.60')
        self.assertEqual(m['net_pnl']['value'], '4.40')

    def test_multiple_fills_and_rebalances_do_not_increment_trades(self):
        self.accounting['positions'][-1]['fills'] = [{'id':str(i)} for i in range(8)]
        m = self.view()['lanes']['meteora']['metrics']
        self.assertEqual(m['trades_taken']['value'], 3)
        p = self.reader.view()['positions'][-1]
        self.assertEqual(p['rebalance_count'], 2)
        self.assertEqual(p['lp_state'], 'MAKER_ACTIVE')

    def test_duplicate_terminal_lifecycle_fails_instead_of_double_counting(self):
        self.accounting['positions'].append(deepcopy(self.accounting['positions'][0]))
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_no_exposure_failed_entries_not_trades(self):
        self.accounting['positions'][0]['exposure_entered'] = False
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_contribution_uses_500_and_no_invented_lane_return(self):
        m = self.view()['lanes']['pons']['metrics']
        self.assertEqual(m['contribution_pct']['value'], '0.88')
        self.assertIsNone(m['lane_return_pct']['value'])

    def test_fees_and_shared_costs_not_subtracted_twice(self):
        v = self.view()
        lane_sum = sum(Decimal(x['metrics']['net_pnl']['value']) for x in v['lanes'].values())
        self.assertEqual(lane_sum-Decimal('.12'), Decimal('12.34'))
        self.assertEqual(v['portfolio']['metrics']['fees']['value'], '1.12')

    def test_mismatch_visible_with_failed_check(self):
        self.accounting['balances']['equity'] = '999.00'
        v = self.view()
        self.assertEqual(v['state'], 'FAIL_CLOSED')
        self.assertIs(v['portfolio']['reconciliation']['value']['equity_equals_inception_plus_net'], False)
        self.assertEqual(v['lanes']['pons']['metrics']['net_pnl']['state'], 'FAIL_CLOSED')

    def test_no_external_adjustment_balancing_item(self):
        self.accounting['external_adjustments'] = ['500']
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_cost_attribution_mismatch(self):
        self.accounting['balances']['fees'] = '99'
        self.assertEqual(self.view()['portfolio']['reconciliation']['state'], 'FAIL_CLOSED')

    def test_gross_net_mismatch(self):
        self.accounting['positions'][0]['gross_result'] = '4.99'
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_stale_mark_is_not_zero_or_usable_equity(self):
        self.accounting['positions'][-1]['mark']['valid_until'] = iso(self.now-0.5)
        m = self.view()['portfolio']['metrics']
        self.assertEqual(m['unrealized_pnl']['state'], 'STALE')
        self.assertIsNone(m['unrealized_pnl']['value'])
        self.assertIsNone(m['net_pnl']['value'])
        self.assertIsNone(m['equity']['value'])
        self.assertEqual(m['realized_pnl']['value'], '8.34')

    def test_missing_mark_is_unavailable(self):
        self.accounting['positions'][-1].pop('mark')
        self.assertEqual(self.metric('unrealized_pnl')['state'], 'UNAVAILABLE')

    def test_fail_closed_mark_cannot_be_overridden_by_another_stale_mark(self):
        self.accounting['positions'][-2]['mark'] = dict(state='FAIL_CLOSED')
        self.accounting['positions'][-1]['mark'] = dict(state='STALE')
        self.assertEqual(self.metric('unrealized_pnl')['state'], 'FAIL_CLOSED')

    def test_stale_export_has_stale_cash_and_no_current_net(self):
        self.now += 5
        p = self.view()['portfolio']
        self.assertEqual(p['state'], 'STALE')
        self.assertEqual(p['metrics']['available_cash']['state'], 'STALE')
        self.assertIsNone(p['metrics']['net_pnl']['value'])

    def test_exact_expiry_invalidates_cache(self):
        self.view()
        self.now += 4.01
        self.assertEqual(self.reader.view()['portfolio']['metrics']['unrealized_pnl']['state'], 'STALE')

    def test_missing_balance_not_zero(self):
        self.accounting['balances'].pop('available_cash')
        p = self.view()['portfolio']
        self.assertIsNone(p['metrics']['available_cash']['value'])
        self.assertEqual(p['reconciliation']['state'], 'UNAVAILABLE')

    def test_known_position_with_unavailable_usd_result_keeps_counts(self):
        self.accounting['positions'][0]['realized_pnl'] = None
        self.accounting['positions'][-1]['remaining_basis'] = None
        v = self.view()
        self.assertEqual(v['portfolio']['metrics']['trades_taken']['value'],12)
        self.assertEqual(v['lanes']['pump']['metrics']['completed_trades']['value'],2)
        self.assertIsNone(v['lanes']['pump']['metrics']['win_rate']['value'])
        self.assertIsNone(v['lanes']['pump']['metrics']['realized_pnl']['value'])
        self.assertIsNone(v['lanes']['meteora']['metrics']['deployed_capital']['value'])
        self.assertIsNone(v['portfolio']['metrics']['unrealized_pnl']['value'])

    def test_missing_settlement_financial_field_can_be_enriched(self):
        actual = self.accounting['positions'][0]['realized_pnl']
        self.accounting['positions'][0]['realized_pnl'] = None
        self.view()
        self.accounting['sequence'] += 1
        self.accounting['positions'][0]['realized_pnl'] = actual
        self.assertEqual(self.view()['state'],'CURRENT')

    def test_old_epoch_history_excluded_even_with_current_timestamps(self):
        old = deepcopy(self.accounting['positions'][0]);old['epoch_id'] = 'old-campaign';old['id'] = 'old'
        old['realized_pnl'] = '900000'
        self.accounting['positions'].append(old)
        self.accounting['history'].append(dict(epoch_id='old-campaign',series='portfolio',at=iso(self.now),value='900000'))
        p = self.view()['portfolio']
        self.assertEqual(p['excluded_historical_positions'], 1)
        self.assertEqual(p['metrics']['equity']['value'], '512.34')

    def test_pre_inception_same_epoch_fails(self):
        self.accounting['positions'][0]['entered_at'] = iso(self.now-90000)
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_inception_is_explicit_immutable_500(self):
        self.assertEqual(inception_receipt('new', iso(self.now), 'event')['starting_capital'], '500.00')
        self.view()
        self.epoch['inception_at'] = iso(self.now-90000)
        self.accounting['inception_sha256'] = hashlib.sha256(canonical(self.epoch).encode()).hexdigest()
        self.accounting['sequence'] += 1
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_no_guessing_missing_inception_time(self):
        self.epoch.pop('inception_at')
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_no_float_currency_or_nan(self):
        for v in (1.23, float('nan'), True, 'NaN', 'Infinity', '1e3'):
            with self.subTest(v=v), self.assertRaises(ValueError):
                decimal(v)
        self.accounting['balances']['equity'] = 512.34
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_restart_same_records_same_metrics(self):
        before = self.view()
        self.assertEqual(before, self.new_reader().view())

    def test_sequence_regression_and_equivocation_fail(self):
        self.view()
        self.accounting['sequence'] = 0
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')
        self.accounting['sequence'] = 1
        self.accounting['balances']['equity'] = '513'
        self.assertEqual(self.view()['state'], 'FAIL_CLOSED')

    def test_insufficient_history_drawdown_unavailable(self):
        self.accounting['history'] = self.accounting['history'][:1]
        self.assertIsNone(self.metric('max_drawdown_pct')['value'])

    def test_drawdown_uses_equity_history_not_start_and_end(self):
        points = self.accounting['history'][:3]
        for row, value in zip(points, ('500', '600', '450')):
            row['value'] = value
        self.accounting['history'] = points
        self.assertEqual(Decimal(self.metric('max_drawdown_pct')['value']), Decimal('25'))

    def test_history_gap_prevents_drawdown_claim(self):
        self.accounting['history'][1]['value'] = None
        self.assertIsNone(self.metric('max_drawdown_pct')['value'])

    def test_mixed_lane_health_and_unknown_evidence(self):
        v = self.view()['system']
        self.assertEqual(v['lanes']['pump']['operational']['state'], 'CURRENT')
        self.assertEqual(v['lanes']['meteora']['operational']['state'], 'FAIL_CLOSED')
        self.assertEqual(v['lanes']['pump']['evidence']['state'], 'UNKNOWN')

    def test_stale_telemetry_never_green(self):
        self.telemetry['observed_at'] -= 121
        s = self.view()['system']
        self.assertEqual(s['lanes']['pump']['operational']['state'], 'STALE')
        self.assertEqual(s['lanes']['meteora']['operational']['state'], 'FAIL_CLOSED')

    def test_unknown_lane_health(self):
        self.telemetry['lanes'].pop('pons')
        self.assertEqual(self.view()['system']['lanes']['pons']['operational']['state'], 'UNKNOWN')

    def test_native_units_preserved_without_usd_conversion(self):
        self.telemetry['lanes']['pons']['cohort_accounting'] = dict(genesis=10**24,
            booked_realized=-123, secret='do-not-publish')
        v = self.view()
        book = v['system']['lanes']['pons']['native_accounting']
        self.assertEqual(book, dict(genesis=str(10**24), booked_realized='-123'))
        self.assertEqual(v['portfolio']['metrics']['equity']['value'], '512.34')

    def test_daily_metrics_count_lifecycles_and_completed_net_only(self):
        _, body = self.get('analytics')
        self.assertEqual(sum(x['entries'] for x in body['data']),12)
        self.assertEqual(sum(x['settlements'] for x in body['data']),8)
        self.assertEqual(sum(Decimal(x['completed_net_pnl']) for x in body['data']),Decimal('7.46'))

    def test_paginated_filtered_history(self):
        code, body = self.get('trades?lane=pump&outcome=winner&limit=1')
        self.assertEqual(code, 200)
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['data'][0]['id'], 'fixture-pump-0')
        code, body = self.get('trades?limit=2')
        self.assertEqual(len(body['data']), 2)
        self.assertEqual(body['next_offset'], 2)
        _, body = self.get('trades?strategy=pons-fixture&q=PONS-ETH')
        self.assertEqual(body['total'], 1)

    def test_date_filter_and_position_detail(self):
        _, body = self.get('trades?from=2026-09-24T00%3A00%3A00Z')
        self.assertTrue(all(p['settled_at'].startswith('2026-09-24') for p in body['data']))
        _, body = self.get('positions/fixture-open-pons')
        self.assertEqual(body['data']['runner_state'], 'ACTIVE')
        self.assertEqual(self.get('positions/no-such-id')[0], 404)

    def test_encoded_canonical_position_identity(self):
        self.accounting['positions'][-1]['id'] = 'epoch:pool:position'
        self.accounting['positions'][-1]['strategy_id'] = 'profitability-v1/protection-v2'
        self.save()
        self.assertEqual(self.get('positions/epoch%3Apool%3Aposition')[0],200)

    def test_export_cannot_erase_previously_seen_settlement(self):
        self.view()
        self.accounting['sequence'] += 1
        self.accounting['positions'].pop(0)
        self.assertEqual(self.view()['state'],'FAIL_CLOSED')

    def test_query_bounds_and_route_allowlist(self):
        for query in ('trades?limit=101','trades?offset=-1','trades?lane=evil','trades?limit=1&limit=2',
                      'trades?sort=secret','equity?limit=1','equity?series=evil','trades?from=oops'):
            with self.subTest(query=query):
                self.assertEqual(self.get(query)[0], 400)
        self.assertEqual(self.get('start-run')[0], 404)

    def test_chart_bounded_actual_samples(self):
        _, body = self.get('equity?limit=3')
        self.assertEqual(len(body['data']), 3)
        self.assertTrue(body['truncated'])
        self.assertEqual(body['reference'], '500.00')
        self.assertEqual(body['data'], self.reader.view()['history']['portfolio'][-3:])

    def test_unknown_positions_total_not_zero(self):
        app = Dashboard()
        body = json.loads(app.response('GET','/api/dashboard/positions')[2])
        self.assertIsNone(body['total'])

    def test_all_mutating_methods_rejected(self):
        for method in ('POST','PUT','PATCH','DELETE','OPTIONS'):
            for route in ('portfolio','positions','trades','system','start-run'):
                self.assertEqual(self.get(route,method)[0], 405)

    def test_reads_cannot_network_execute_or_write(self):
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        original_open = builtins.open
        original_path_open = Path.open
        def readonly(file, mode='r', *args, **kwargs):
            if any(c in mode for c in 'wax+'):
                raise AssertionError('write attempted')
            return original_open(file,mode,*args,**kwargs)
        def path_readonly(path, mode='r', *args, **kwargs):
            if any(c in mode for c in 'wax+'):
                raise AssertionError('write attempted')
            return original_path_open(path,mode,*args,**kwargs)
        with patch('socket.socket', side_effect=AssertionError('network')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('provider')), \
             patch('subprocess.Popen', side_effect=AssertionError('workflow/child')), \
             patch('builtins.open', side_effect=readonly), patch.object(Path,'open',path_readonly):
            for route in ('portfolio','lanes','lanes/pons','positions','trades','equity','system','analytics'):
                self.assertEqual(self.get(route)[0], 200)
            self.assertEqual(self.api.response('GET','/dashboard')[0],200)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_export_failure_does_not_invoke_canonical_runtime(self):
        (self.root/'accounting.json').write_text('{broken')
        with patch('meme_machine.store.Store', side_effect=AssertionError('canonical store')), \
             patch('meme_machine.engine.Engine', side_effect=AssertionError('canonical engine')):
            self.assertEqual(self.reader.view()['state'], 'FAIL_CLOSED')

    def test_secrets_not_projected_or_served(self):
        secret='TOP_SECRET_NOT_FOR_DASHBOARD'
        self.accounting['api_key']=secret
        self.accounting['private_rpc_url']='https://private.invalid/'+secret
        self.telemetry['lanes']['pons']['environment']={'secret':secret}
        self.telemetry['lanes']['pons']['source_sha']=secret
        self.save()
        for route in ('portfolio','positions','trades','system','lanes'):
            self.assertNotIn(secret,self.api.response('GET','/api/dashboard/'+route)[2].decode())
        self.assertIsNone(self.api.response('GET','/.env'))
        self.assertEqual(self.api.response('GET','/dashboard/../../.env')[0],404)

    def test_unreadable_state_does_not_silently_reuse_good_balance(self):
        self.view()
        (self.root/'accounting.json').unlink()
        self.assertEqual(self.reader.view()['state'],'UNAVAILABLE')

    def test_snapshot_capacity_is_fail_closed(self):
        self.accounting['positions'] *= MAX_POSITIONS//len(self.accounting['positions'])+1
        self.assertEqual(self.view()['state'],'FAIL_CLOSED')

    def test_fixture_writer_never_overwrites_existing_files(self):
        with self.assertRaises(FileExistsError):
            write(self.root)

    def test_response_security_and_no_external_assets(self):
        code, headers, body = self.api.response('GET','/dashboard')
        self.assertEqual(code,200)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
        self.assertNotIn(b'https://',body)

    def test_shared_cache_avoids_repeat_full_aggregation(self):
        self.reader.view()
        with patch.object(self.reader,'_view',side_effect=AssertionError('rescan')):
            for _ in range(8):
                self.reader.view()


if __name__ == '__main__':
    unittest.main()
