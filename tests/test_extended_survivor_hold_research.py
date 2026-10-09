"""Counterfactual mechanical tests; all market inputs are synthetic, not returns.

The real policies, provider allowances and supervisor deadlines are immutable.
No HTTP client, historical download, trading service or real PAPER epoch is used.
"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import resource
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engineering.extended_survivor_hold.research import (
    ROOT, PRIMARY_COMMIT, POLICY_PATHS, HORIZONS, MULTIPLES, build, policies, tail_floor)
from meme_machine.runtime.survivor_risk import mark


def state(multiple=5):
    return dict(opened_at=10, original_quantity=400, remaining_quantity=300,
        realization_taken=True, high_water_bps=(multiple-1)*10000, high_at=10,
        tightened=True, deterioration_streak=0)


def observation(at, gain, **kw):
    return dict(id=str(at), at=at, after_cost_return_bps=gain, exit_liquidity_valid=True, **kw)


class ResearchModelTests(unittest.TestCase):
    def test_no_production_policy_service_or_allowance_changes(self):
        for relative in POLICY_PATHS:
            original = subprocess.check_output(['git', 'show', PRIMARY_COMMIT+':'+relative], cwd=ROOT)
            self.assertEqual((ROOT/relative).read_bytes(), original, relative)
        model = build()
        self.assertEqual(model['baseline']['current_bridge_seconds'], 129600)
        self.assertEqual(model['baseline']['operational_maximum_seconds'], 264065)
        self.assertEqual({p['maximum_hold_seconds'] for p in policies().values()}, {259200})
        self.assertFalse(model['production_extension_recommended'])
        self.assertEqual(model['market_provider_calls'], 0)

    def test_all_horizons_and_winner_strata_report_missing_outcomes_not_zero_returns(self):
        model = build()
        cells = model['economic_comparison']
        self.assertEqual(len(cells), 60)
        self.assertEqual({c['hours'] for c in cells}, set(HORIZONS))
        self.assertEqual({c['boundary_appreciation_multiple'] for c in cells}, set(MULTIPLES))
        for cell in cells:
            self.assertEqual(cell['independently_qualified_market_lifecycles'], 0)
            self.assertIsNone(cell['realized_net_pnl'])
            self.assertIsNone(cell['portfolio_return'])
            self.assertEqual(cell['status'], 'INSUFFICIENT_EVIDENCE')
        evidence = model['evidence']
        self.assertEqual(evidence['prior_audit']['sources_with_reusable_complete_ranges'], 0)
        self.assertLess(evidence['pump_capture']['active_delivery_seconds'], 14)
        self.assertFalse(evidence['seven_day_startup_census_required'])

    def test_resource_projection_no_cache_discount_or_enlarged_authority(self):
        model = build()
        rows = model['resource_horizons']
        prior = None
        for row in rows:
            h = row['hours']
            self.assertEqual(row['pump']['turns'], h*720)
            self.assertEqual(row['pons']['quiet']['turns'], h*1200)
            self.assertEqual(row['pons']['quiet']['assumptions']['cross_turn_quote_hits'], 0)
            self.assertFalse(row['pons']['quiet']['ceiling_checks']['rpc_elements']['fits'])
            self.assertFalse(row['pons']['high_volatility']['local_two_rps_cadence_fits'])
            self.assertFalse(row['safe_duration_proven'])
            self.assertEqual(row['pons']['quiet']['ceiling_checks']['rpc_elements']['unchanged_limit'], 500000)
            self.assertEqual(row['pons']['quiet']['ceiling_checks']['rpc_cu']['unchanged_limit'], 24000000)
            if prior:
                self.assertGreater(row['pump']['rpc_elements'], prior['pump']['rpc_elements'])
                self.assertGreater(Decimal(row['pons']['quiet']['rpc_only_modeled_usd']),
                    Decimal(prior['pons']['quiet']['rpc_only_modeled_usd']))
                self.assertLess(row['native_32_gib_average_allowance_bytes_per_second'],
                    prior['native_32_gib_average_allowance_bytes_per_second'])
            prior = row
        self.assertEqual(rows[-1]['pons']['quiet']['rpc_only_modeled_usd'], '78.744960000')
        self.assertEqual(rows[0]['pump']['rpc_only_modeled_usd'], '2.732073750')
        self.assertGreater(model['simultaneous_positions']['pons_independent_quiet_two_position_minimum_rps'], 2)
        self.assertIsNone(model['conditional_research_parameters']['selected_absolute_hours'])


class RiskHorizonTests(unittest.TestCase):
    def test_unchanged_72_hour_exit_wins_for_every_horizon_and_appreciation_stratum(self):
        for family, policy in policies().items():
            for hours in HORIZONS:
                for multiple in MULTIPLES:
                    with self.subTest(family=family, hours=hours, multiple=multiple):
                        s = state(multiple)
                        before, action = mark(s, observation(259209, s['high_water_bps']), policy)
                        self.assertEqual(action['action'], 'hold')
                        due, action = mark(before, observation(259210, s['high_water_bps']), policy)
                        self.assertEqual(action, dict(action='full_exit', reason='maximum_hold'))
                        later, action = mark(due, observation(10+hours*3600, s['high_water_bps']+10000), policy)
                        self.assertEqual(action['reason'], 'maximum_hold')
                        self.assertEqual(later['opened_at'], 10)

    def test_accelerated_native_risk_cadence_through_each_hypothetical_horizon(self):
        counters = []
        for family, original in policies().items():
            cadence = 3 if family == 'pons' else 5
            for hours in HORIZONS:
                hypothetical = dict(original, maximum_hold_seconds=hours*3600)
                baseline, extended = state(), state()
                started = time.process_time()
                count = hours*3600//cadence
                for turn in range(1, count+1):
                    at = 10+turn*cadence
                    obs = observation(at, 40000, soft_deterioration=False)
                    extended, action = mark(extended, obs, hypothetical)
                    if at-10 < 259200:
                        baseline, reference = mark(baseline, obs, original)
                        if (extended, action) != (baseline, reference):
                            self.fail('changed pre-72h native risk transition')
                    if turn < count and action['action'] != 'hold':
                        self.fail('unexpected synthetic safety fixture exit')
                self.assertEqual(action, dict(action='full_exit', reason='maximum_hold'))
                self.assertEqual(extended['opened_at'], 10)
                self.assertEqual((extended['remaining_quantity'], extended['high_water_bps']), (300, 40000))
                counters.append(dict(family=family, hours=hours, cadence_seconds=cadence,
                    evaluated_turns=count, cpu_seconds=time.process_time()-started,
                    classification='synthetic native pure-risk transitions; no market or execution outcome'))
        print('RESEARCH_RISK_TRACE', json.dumps(counters, sort_keys=True), flush=True)

    def test_original_right_tail_hard_and_structural_exits_preempt_hypothetical_extension(self):
        for family, original in policies().items():
            for hours in HORIZONS[1:]:
                policy = dict(original, maximum_hold_seconds=hours*3600)
                for multiple in MULTIPLES:
                    floor = tail_floor(multiple)
                    boundary = floor['existing_full_exit_at_or_below_return_bps']
                    s = state(multiple)
                    at = 259213
                    self.assertEqual(mark(s, observation(at, boundary+1), policy)[1]['action'], 'hold')
                    stopped, action = mark(s, observation(at, boundary), policy)
                    self.assertEqual(action['reason'], 'tail_gain_giveback')
                    self.assertEqual(mark(stopped, observation(at+3, s['high_water_bps']*2), policy)[1], action)
                    for kw, reason in (
                        (dict(creator_distribution=True), 'creator_distribution'),
                        (dict(severe_persistent_deterioration=True), 'severe_persistent_deterioration'),
                        (dict(exit_liquidity_valid=False), 'invalid_exit_liquidity')):
                        obs = observation(at, s['high_water_bps']);obs.update(kw)
                        self.assertEqual(mark(s, obs, policy)[1]['reason'], reason)
                    stopped, action = mark(s, observation(at, original['hard_stop_bps']), policy)
                    self.assertEqual(action['reason'], 'hard_stop')
                    # A missing quote cannot reverse an already durable stop.
                    self.assertEqual(mark(stopped, observation(at+3, None), policy)[1], action)


class NativeRestartTests(unittest.TestCase):
    from tests.test_survivor_commit import SurvivorCommitTests as Native
    setUp=Native.setUp;tearDown=Native.tearDown;new_book=Native.new_book;fill=Native.fill;reopen=Native.reopen

    def test_shared_native_book_partial_restart_pending_exit_and_reconciliation_all_horizons(self):
        from meme_machine.runtime.survivor_commit import monitor, restore_risk
        first = True
        rows = []
        for family, original in policies().items():
            for hours in HORIZONS:
                if not first:
                    self.tearDown();self.setUp()
                first = False
                policy = dict(original, maximum_hold_seconds=hours*3600)
                self.fill()
                self.adapter.at=11;self.adapter.proceeds=32
                action=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                    observation=observation(11,40000,net_exit_proceeds=500),policy=policy,adapter=self.adapter)
                self.assertEqual(action['quantity'],100)
                self.reopen()
                for at in (1800, 259199, 10+hours*3600-1):
                    self.adapter.at=at
                    monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                        observation=observation(at,40000,net_exit_proceeds=500),policy=policy,adapter=self.adapter)
                    self.reopen()
                    risk=restore_risk(self.book,'run:one')
                    self.assertEqual((risk['opened_at'],risk['high_water_bps'],risk['remaining_quantity']), (10,40000,300))
                self.adapter.at=10+hours*3600;self.adapter.quote_available=False
                action=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                    observation=observation(self.adapter.at,None),policy=policy,adapter=self.adapter)
                self.assertEqual(action,dict(action='exit_pending',reason='maximum_hold'))
                self.reopen();self.assertEqual(self.book._load('run:one')['status'],'open')
                self.assertEqual(restore_risk(self.book,'run:one')['last_action']['reason'],'maximum_hold')
                self.adapter.at+=3;self.adapter.quote_available=True;self.adapter.proceeds=90
                obs=observation(self.adapter.at,50000)
                with patch.object(self.sleeve,'release',side_effect=RuntimeError('offline-interrupted-reconciliation')):
                    with self.assertRaisesRegex(RuntimeError,'offline-interrupted-reconciliation'):
                        monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                            observation=obs,policy=policy,adapter=self.adapter)
                self.reopen()
                self.assertEqual(self.book._load('run:one')['status'],'settled')
                self.assertGreater(self.sleeve.reconcile()['reserved'],0)
                # The existing native manager repairs release/publication at restart.
                if family=='pump':
                    from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
                    manager=object.__new__(Runtime);method=manager._position
                else:
                    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
                    manager=object.__new__(Runtime);method=manager._manage_position
                manager.book=self.book;manager.sleeve=self.sleeve;manager.now=lambda:self.adapter.at
                saved=[];manager.history=SimpleNamespace(save=lambda row:saved.append(deepcopy(row)))
                row=dict(id='mint',position='run:one')
                method(row,admit=False)
                self.assertEqual((row['position'],row['state']),(None,'settled'))
                self.assertEqual(self.sleeve.reconcile()['available'],1022)
                self.assertEqual(self.sleeve.reconcile()['reserved'],0)
                before=deepcopy(self.book.reconcile())
                self.assertEqual(monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                    observation=obs,policy=policy,adapter=self.adapter)['action'],'settled')
                self.assertEqual(self.book.reconcile(),before)
                self.assertTrue(self.book.replay()['verified'])
                rows.append(dict(family=family,hours=hours,opened_at=10,high_water_bps=50000,
                    realized_native_units=self.book._load('run:one')['realized'],duplicate_exit_suppressed=True,
                    interrupted_reconciliation_repaired=True,synthetic_execution_not_market_returns=True))
        print('RESEARCH_RESTART_TRACE',json.dumps(rows,sort_keys=True),flush=True)


class RetentionTests(unittest.TestCase):
    def test_actual_sqlite_dense_hot_window_boundaries_through_14_days_keep_gaps_incomplete(self):
        from meme_machine.lanes.pons.pons_history import PonsHistory
        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
        started=time.process_time();rows=[]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';history=PonsHistory(path,policy=POLICY_HASH)
            try:
                row=history.graduate('offline-fixture',dict(at=0,block=1,block_hash='offline-anchor'))
                # Numeric storage fixtures carry NO canonical economic coverage.
                row.update(complete=False,recovery='offline_missing_intervals',position='offline-held',state='runner')
                history.save(row)
                history.append(row['id'],through=86400,events=[],points=[(s,1) for s in range(86401)],complete=True)
                original=history.db.execute('SELECT price,hash FROM points WHERE at=0').fetchone()
                for hours in HORIZONS:
                    end=hours*3600
                    history.append(row['id'],through=end,events=[],
                        points=[(s,1) for s in range(end-86400,end+1)],complete=True)
                    count=history.db.execute('SELECT COUNT(*) FROM points').fetchone()[0]
                    self.assertLessEqual(count,86405)
                    self.assertLess(count,history.maximum_points)
                    self.assertEqual(history.db.execute('SELECT price,hash FROM points WHERE at=0').fetchone(),original)
                    self.assertFalse(history.get(row['id'])['complete'])
                    prefix=history.get_meta('pons_price_window:'+row['id'])
                    self.assertEqual(prefix['original_anchor']['at'],0)
                    with self.assertRaisesRegex(ValueError,'pons_price_window_past_query'):
                        history.facts(row['id'],1)
                    history.append(row['id'],through=end,events=[],points=[(end,1)],complete=True)
                    self.assertEqual(history.db.execute('SELECT COUNT(*) FROM points').fetchone()[0],count)
                    saved=deepcopy(history.get(row['id']));history.close()
                    history=PonsHistory(path,policy=POLICY_HASH)
                    self.assertEqual(history.get(row['id']),saved)
                    self.assertEqual(history.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    pages=history.db.execute('PRAGMA page_count').fetchone()[0]
                    page_size=history.db.execute('PRAGMA page_size').fetchone()[0]
                    rows.append(dict(hours=hours,retained_numeric_points=count,sqlite_pages=pages,
                        page_size=page_size,sqlite_page_stock_bytes=pages*page_size,
                        physical_main_bytes=path.stat().st_size,
                        wal_bytes=Path(str(path)+'-wal').stat().st_size,
                        repeated_observation_new_point_rows=0,complete_authenticated_history=False))
                with self.assertRaisesRegex(ValueError,'survivor_open_position_retirement'):
                    history.retire(history.get(row['id']))
                row=history.get(row['id']);row.update(position=None,state='settled');history.save(row);history.retire(row)
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM points').fetchone()[0],0)
                self.assertEqual(history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            finally:history.close()
        print('RESEARCH_STORAGE_TRACE',json.dumps(dict(boundaries=rows,cpu_seconds=time.process_time()-started,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            terminal_cleanup=True,classification='actual SQLite capacity/restart test; deliberately incomplete synthetic history'),
            sort_keys=True),flush=True)


class OperationalDeadlineTests(unittest.TestCase):
    from tests.test_position_continuation import LifecycleTests as Native
    fixture=Native.fixture;native_position=Native.native_position;service=Native.service

    def test_unchanged_supervisor_deadline_faults_instead_of_granting_14_day_speculation(self):
        from meme_machine.operational.position_continuation import tick,TOTAL_SECONDS
        root,a,now,s=self.service();book,_,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False
        with patch('time.time',return_value=now+TOTAL_SECONDS-65):tick(s)
        self.assertTrue(s.stop_requested)
        self.assertEqual(s.provider_budget.phase(),'FAULT')
        self.assertFalse(s.provider_budget.fault()['protected'])
        self.assertEqual(book._load(identity)['status'],'open')
        self.assertEqual(a.ledger()['runtime_admission']['mode'],'CONTINUATION')
        from meme_machine.operational.admission import available
        self.assertEqual(available(a.ledger(),now+336*3600),'observation_only_funding_closed')
        original=s.provider_budget.usage()
        with patch('time.time',return_value=now+336*3600):tick(s)
        after=s.provider_budget.usage()
        for phase in ('bootstrap','continuation','recovery'):
            for counter in ('rpc_cu','rpc_elements','http_attempts','native_bytes'):
                self.assertEqual(after['phases'][phase][counter],original['phases'][phase][counter])
        self.assertEqual(after['phase'],'FAULT');self.assertFalse(after['fault']['protected'])
        self.assertEqual(book._load(identity)['status'],'open')

    def test_resource_usage_restart_does_not_reset_or_expand_for_a_research_horizon(self):
        from meme_machine.operational.bounded_provider import Budget,PhaseBudget
        from tests.test_position_continuation import envelope
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'usage.sqlite';Budget.create(path,continuation=envelope())
            usage=PhaseBudget(path);usage.set_phase('CONTINUATION','offline')
            usage.reserve_http('https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE',[dict(method='eth_call')])
            before=usage.usage();resumed=PhaseBudget(path)
            self.assertEqual(resumed.usage(),before)
            self.assertEqual(before['phases']['continuation']['rpc_cu'],'26')
            self.assertEqual(resumed.limits['rpc_elements'],500000)


class QuoteBoundaryTests(unittest.TestCase):
    from tests.test_continuation_resource_efficiency import PonsQuoteTests as Native
    setUp=Native.setUp;runtime=Native.runtime;counts=Native.counts

    def test_fresh_quote_canonical_fork_and_provider_fault_at_each_hypothetical_boundary(self):
        from meme_machine.lanes.pons import BoundaryError
        original=self.rpc.value;fork=[0]
        def value(method,params):
            result=original(method,params)
            if method=='eth_getBlockByNumber':
                result=dict(result,timestamp=hex(int(self.clock[0])))
                if fork[0]:
                    height=int(result['number'],16)
                    result=dict(result,hash='0x'+f'{height+10**12:064x}',
                        parentHash='0x'+f'{height-1+10**12:064x}')
            return result
        self.rpc.value=value
        r=self.runtime();qty=10**18
        rows=[]
        for hours in HORIZONS:
            fork[0]=0;self.failed=False;self.clock[0]=float(hours*3600);self.head=hours*3600
            r.position_exit_quotes={}
            first=r.exit_quote(qty);self.assertIsNotNone(first)
            r.validate_exit(first,qty,int(self.clock[0]))
            fork[0]=1;before=self.counts()['elements']
            changed=r.exit_quote(qty);self.assertIsNotNone(changed)
            self.assertNotEqual(changed['block_hash'],first['block_hash'])
            self.assertGreaterEqual(self.counts()['elements']-before,6)
            # A canonical fork gets a fresh isolated quote, never fabricated history.
            self.failed=True;before=self.counts()['transports']
            self.assertIsNone(r.exit_quote(qty));self.assertEqual(r.position_exit_quotes,{})
            self.assertLessEqual(self.counts()['transports']-before,1)
            self.failed=False;self.clock[0]+=3;self.head+=30
            fresh=r.exit_quote(qty);self.assertIsNotNone(fresh)
            self.assertEqual(fresh['block'],self.head)
            self.clock[0]+=6
            with self.assertRaises(BoundaryError):r.validate_exit(fresh,qty,int(self.clock[0]))
            rows.append(dict(hours=hours,canonical_fork_reacquired=True,
                provider_fault_returned_no_quote=True,recovery_internal_retries=0,
                quote_older_than_five_seconds_rejected=True,economic_history_coverage_claimed=False))
        print('RESEARCH_QUOTE_TRACE',json.dumps(rows,sort_keys=True),flush=True)

    def test_partial_exit_quantity_and_pending_fault_never_use_an_old_full_size_quote(self):
        self.clock[0]=336*3600.;self.head=336*3600
        r=self.runtime();full=r.exit_quote(10**18)
        part=r.exit_quote(10**18//4)
        self.assertEqual(part['quantity'],10**18//4)
        self.assertNotEqual(full['quantity'],part['quantity'])
        self.failed=True
        self.assertIsNone(r.exit_quote(10**18//4))
        self.assertEqual(r.position_exit_quotes,{})
