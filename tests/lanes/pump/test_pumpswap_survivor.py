"""Synthetic exact-boundary fixtures; these are not market profitability evidence."""
from copy import deepcopy
import unittest
from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry, POLICY


def facts():
    now=25000
    points=[(0,100),(3400,100),(12000,150),(17200,190),(17700,200),
            (17800,140),(20000,145),(20799,160),(20800,150),
            (21400,153),(22000,155),(22600,154),(23200,157),(23800,158),
            (24400,160),(25000,162)]
    events=[]
    for i,g in enumerate(['a','b','c']):
        events.append(dict(id='prior'+g,at=now-2000+i,group=g,quote=1000,buy=True,authenticated=True))
    for i,g in enumerate(['a','b','d','e','f','g']):
        events.append(dict(id='new'+g,at=now-1000+i,group=g,quote=1000,buy=True,authenticated=True))
    return dict(now=now,graduation_at=0,migration_price='100',
                origin='pump.fun',venue='pumpswap',canonical_migration_pool=True,
                lineage_proven=True,quote_asset='SOL',authoritative=True,
                continuity_complete=True,creator_distribution_safe=True,
                hard_concentration_pass=True,exit_liquidity_available=True,
                mayhem=dict(status='never'),liquidity_usd_micros=30_000_000_000,
                base_end=24400,price_points=[dict(at=t,price=str(p)) for t,p in points],
                recovery_vwap='155',demand_events=events,demand_complete=True)


def bridge_facts(age=600,quote_scale=1):
    """Complete, synthetic canonical graduation-to-breakout tape at each tier."""
    tier=next(t for t in POLICY['bridge_tiers'] if t['minimum_age_seconds']<=age<t['maximum_age_seconds'])
    duration=tier['base_seconds'];end=age-60;start=end-duration;previous=start-duration
    points=[(0,100),(previous-40,200),(previous-20,140),(previous,145),
            (previous+duration//2,160),(start,150),(start+duration//3,153),
            (start+2*duration//3,156),(end,160),(age,162)]
    window=tier['demand_window_seconds']
    f=facts();f.update(now=age,base_end=end,price_points=[dict(at=t,price=str(p)) for t,p in points],
                      recovery_vwap='155',demand_events=[])
    for i,g in enumerate(('a','b','c')):
        f['demand_events'].append(dict(id='prior'+g,at=age-window-window//2+i,
            group=g,quote=1000*quote_scale,buy=True,authenticated=True))
    for i,g in enumerate(('a','b','d','e','f','g')):
        f['demand_events'].append(dict(id='current'+g,at=age-window//2+i,
            group=g,quote=1000*quote_scale,buy=True,authenticated=True))
    return f


class SurvivorTests(unittest.TestCase):
    def test_exact_covariance_matches_pairwise_identity_without_quadratic_evaluation(self):
        from fractions import Fraction
        from unittest.mock import patch
        from meme_machine.lanes.pump.pumpswap_survivor import price_time_covariance
        for size in (1,2,7,31):
            for direction in (-1,0,1):
                rows=[(i*7,Fraction(100*size+direction*i,3+i%3)) for i in range(size)]
                reference=sum((a[0]-b[0])*(a[1]-b[1]) for n,a in enumerate(rows) for b in rows[n+1:])/size
                self.assertEqual(price_time_covariance(rows),reference)
        f=facts();original=f['price_points'];points={p['at']:p for p in original}
        for i in range(256):
            at=3400+i*21600//255
            points[at]=dict(at=at,price=next(p['price'] for p in reversed(original) if p['at']<=at))
        f['price_points']=[points[t] for t in sorted(points)]
        addition=Fraction.__add__;calls=[]
        def counted(left,right):calls.append(1);return addition(left,right)
        with patch.object(Fraction,'__add__',counted):decision=evaluate_entry(f)
        self.assertTrue(decision['candidate'],decision)
        self.assertLess(len(calls),10*len(points))

    def test_archived_reset_prefix_matches_independent_original_scan_and_full_decisions(self):
        from fractions import Fraction
        import random
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
        rng=random.Random(714)
        for _ in range(24):
            rows=[dict(at=i,price=str(rng.randrange(90,230)),low=str(rng.randrange(60,89))) for i in range(500)]
            peak=reset=peak_at=reset_at=running_high=high_at=previous_price=None
            new_cycle=False
            for r in rows:
                at=r['at'];p=Fraction(r['price'])
                if reset_at is not None and previous_price is not None and p>previous_price and not new_cycle:
                    running_high,high_at=p,at;new_cycle=True
                if running_high is None or p>running_high:running_high,high_at=p,at
                if (running_high-p)*10000>=running_high*POLICY['minimum_reset_bps']:
                    if reset_at is None or high_at!=peak_at or p<=reset:
                        peak,reset,peak_at,reset_at=running_high,p,high_at,at;new_cycle=False
                previous_price=p
            prefix=None
            for i in range(0,len(rows),37):prefix=reduce_reset_history(rows[i:i+37],prefix)
            self.assertEqual(prefix,reduce_reset_history(rows))
            self.assertEqual((prefix['peak'],prefix['reset'],prefix['peak_at'],prefix['reset_at']),
                (str(peak),str(reset),peak_at,reset_at))
            self.assertEqual(Fraction(prefix['minimum_low']),min(Fraction(r['low']) for r in rows if r['at']>=reset_at))
        for old_low in ('100','10'):
            f=facts();shift=2*86400
            f['now']+=shift;f['base_end']+=shift
            for event in f['demand_events']:event['at']+=shift
            for row in f['price_points']:row['at']+=shift
            f['price_points']=[dict(at=0,price='100'),dict(at=50,price='210'),dict(at=100,price='150',low=old_low)]+f['price_points']
            full=evaluate_entry(f)
            prefix=reduce_reset_history(f['price_points'][:3])
            compact=deepcopy(f);compact['price_points']=f['price_points'][:1]+f['price_points'][2:]
            compact['reset_history_prefix']=prefix
            self.assertEqual(evaluate_entry(compact),full)
            for change in (dict(policy_hash='wrong'),dict(through=f['now']),dict(first_at=-1)):
                corrupt=deepcopy(compact);corrupt['reset_history_prefix'].update(change)
                self.assertIn('incomplete_structure_or_demand',evaluate_entry(corrupt)['all_rejections'])

    def test_valid_survival_reset_base_continuation(self):
        d=evaluate_entry(facts())
        self.assertTrue(d['candidate'],d)
        self.assertEqual(d['features']['turnover_cap'],150)
        self.assertEqual(d['features']['repeat_buyers'],2)

    def test_fail_closed_universe_liquidity_and_safety(self):
        for key,value,reason in [
            ('lineage_proven',False,'graduation_lineage'),('canonical_migration_pool',False,'graduation_lineage'),
            ('quote_asset','USDC','non_sol_quote'),('liquidity_usd_micros',19_999_999_999,'liquidity_floor'),
            ('liquidity_usd_micros',None,'liquidity_floor'),('migration_price','163','migration_price_survival'),
            ('creator_distribution_safe',None,'creator_distribution'),('hard_concentration_pass',False,'hard_concentration'),
            ('exit_liquidity_available',False,'exit_liquidity'),('continuity_complete',False,'authoritative_evidence')]:
            with self.subTest(key=key,value=value):
                f=facts();f[key]=value
                self.assertIn(reason,evaluate_entry(f)['all_rejections'])

    def test_age_inclusive_exact_bounds(self):
        for age,passes in [(599,False),(600,True),(14399,True),(14400,True),(604800,True),(604801,False)]:
            f=facts();f['graduation_at']=f['now']-age
            self.assertEqual('age' not in evaluate_entry(f)['all_rejections'],passes)

    def test_mayhem_unknown_active_clean_and_excluded_flow(self):
        for m,reason in [({},'unknown_mayhem'),(dict(status='active'),'active_mayhem'),
                         (dict(status='ended',ended_at=21401,clean_since=21401),'mayhem_clean_window')]:
            f=facts();f['mayhem']=m;self.assertIn(reason,evaluate_entry(f)['all_rejections'])
        f=facts();f['mayhem']=dict(status='ended',ended_at=21400,clean_since=21400)
        self.assertTrue(evaluate_entry(f)['candidate'])
        f['mayhem']=dict(status='ended',ended_at=21400,clean_since=21400,agent_identity_proven=True,agent_groups=['bot'])
        f['demand_events'].append(dict(id='bot',at=24999,group='bot',quote=10**12,buy=True,authenticated=True))
        d=evaluate_entry(f);self.assertTrue(d['candidate'],d)
        self.assertEqual(d['features']['independent_buyers'],6)
        self.assertEqual(d['features']['buy_flow'],6000)
        f['mayhem']['status']='active'
        self.assertIn('active_mayhem',evaluate_entry(f)['all_rejections'])

    def test_breakout_and_both_extension_bounds(self):
        for price,reason in [('160','no_continuation'),('184.0001','price_extension'),('175.0001','base_range_extension')]:
            f=facts();f['price_points'][-1]['price']=price
            self.assertIn(reason,evaluate_entry(f)['all_rejections'])
        f=facts();f['price_points'][-1]['price']='175'
        self.assertNotIn('base_range_extension',evaluate_entry(f)['all_rejections'])

    def test_no_repeat_threshold_and_positive_organic_flow(self):
        f=facts()
        for e in f['demand_events']:
            if e['at']>=23200:e['group']='new'+e['group']
        d=evaluate_entry(f);self.assertTrue(d['candidate'],d)
        self.assertEqual(d['features']['repeat_buyers'],0)
        f['demand_events'].append(dict(id='sell',at=24990,group='seller',quote=6000,buy=False,authenticated=True))
        self.assertIn('net_buy_flow',evaluate_entry(f)['all_rejections'])

    def test_nonpositive_base_future_and_missing_demand(self):
        f=facts()
        for r in f['price_points']:
            if 20800<=r['at']<=24400:r['price']='155'
        self.assertIn('base_range',evaluate_entry(f)['all_rejections'])
        f=facts();f['price_points'][-1]['at']=25001
        self.assertIn('incomplete_structure_or_demand',evaluate_entry(f)['all_rejections'])
        f=facts();f['demand_complete']=False
        self.assertIn('incomplete_structure_or_demand',evaluate_entry(f)['all_rejections'])

    def test_recovery_vwap_and_negative_two_hour_structure(self):
        f=facts();f['recovery_vwap']='162'
        self.assertIn('recovery_vwap',evaluate_entry(f)['all_rejections'])
        f=facts();f['price_points'][5]['price']='163'
        self.assertIn('two_hour_structure',evaluate_entry(f)['all_rejections'])

    def test_compression_exact_nonexpansion_and_one_tick_above(self):
        f=facts();f['price_points'][-2]['price']='210';f['price_points'][-1]['price']='212'
        self.assertNotIn('base_compression',evaluate_entry(f)['all_rejections'])
        f['price_points'][-2]['price']='210.0001'
        self.assertIn('base_compression',evaluate_entry(f)['all_rejections'])

    def test_both_extension_limits_exactly_equal(self):
        f=facts();f['price_points'][8]['price']='144';f['price_points'][-1]['price']='184'
        d=evaluate_entry(f);self.assertTrue(d['candidate'],d)
        f['price_points'][-1]['price']='184.0001'
        reasons=evaluate_entry(f)['all_rejections']
        self.assertIn('price_extension',reasons);self.assertIn('base_range_extension',reasons)

    def test_six_hour_slope_zero_is_valid_negative_is_not(self):
        from fractions import Fraction
        f=facts();rows=[r for r in f['price_points'] if r['at']>=3400]
        center=Fraction(sum(r['at'] for r in rows),len(rows))
        target=next(r for r in rows if r['at']==3400)
        rest=sum((r['at']-center)*Fraction(r['price']) for r in rows if r is not target)
        target['price']=str(-rest/(target['at']-center))
        self.assertNotIn('six_hour_structure',evaluate_entry(f)['all_rejections'])
        target['price']=str(Fraction(target['price'])+Fraction(1,10000))
        self.assertIn('six_hour_structure',evaluate_entry(f)['all_rejections'])

    def test_migration_price_equal_passes_below_fails(self):
        f=facts();f['migration_price']='162'
        self.assertNotIn('migration_price_survival',evaluate_entry(f)['all_rejections'])
        f['migration_price']='162.0001'
        self.assertIn('migration_price_survival',evaluate_entry(f)['all_rejections'])

    def test_reset_exact_three_percent_and_one_fraction_below(self):
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
        rows=[dict(at=0,price='100'),dict(at=1,price='97')]
        self.assertEqual(reduce_reset_history(rows)['reset_at'],1)
        rows[-1]['price']='97.0001'
        self.assertIsNone(reduce_reset_history(rows)['reset_at'])

    def test_missing_full_base_and_active_lower_low_sequence(self):
        f=facts();f['price_points']=[r for r in f['price_points'] if r['at']>20800]
        self.assertIn('incomplete_structure_or_demand',evaluate_entry(f)['all_rejections'])
        f=facts()
        replacements={21400:'149',22000:'148',22600:'147',23200:'146',23800:'145'}
        for r in f['price_points']:r['price']=replacements.get(r['at'],r['price'])
        self.assertIn('lower_low_sequence',evaluate_entry(f)['all_rejections'])

    def test_intrasecond_extrema_cannot_hide_base_expansion_or_breakdown(self):
        f=facts();f['price_points'][10]['high']='211'
        self.assertIn('base_compression',evaluate_entry(f)['all_rejections'])
        f=facts();f['price_points'][10]['low']='139'
        self.assertIn('reset_low_breakdown',evaluate_entry(f)['all_rejections'])


class PumpPostgradBridgeTests(unittest.TestCase):
    def test_exact_maturity_tiers_have_complete_canonical_funded_decisions(self):
        for age,tier in ((600,'10m-30m'),(1799,'10m-30m'),(1800,'30m-2h'),
                         (7199,'30m-2h'),(7200,'2h-4h'),(14399,'2h-4h')):
            with self.subTest(age=age):
                d=evaluate_entry(bridge_facts(age))
                self.assertTrue(d['candidate'],d)
                self.assertEqual(d['features']['execution_profile'],'pump_postgrad_bridge')
                self.assertEqual(d['features']['maturity_tier'],tier)
                window=d['features']['long_structure_window']
                self.assertEqual((window['effective_seconds'],window['window_start'],window['complete']),
                                 (age,0,True))
                self.assertEqual(d['features']['base_end']-d['features']['base_start'],d['features']['base_seconds'])
        f=bridge_facts();f['now']=599;f['price_points'][-1]['at']=599
        self.assertIn('age',evaluate_entry(f)['all_rejections'])

    def test_bridge_comparison_uses_exact_predecessor_age_and_existing_predicates(self):
        from meme_machine.paper_policy_revision import predecessor_hash
        admitted=evaluate_entry(bridge_facts())
        comparison=admitted['policy_comparison']
        self.assertEqual(comparison['predecessor_policy_hash'],predecessor_hash('pump_survivor'))
        self.assertEqual(comparison['predecessor_minimum_age_seconds'],14400)
        self.assertEqual(comparison['predecessor_decisive_rejection'],'age')
        self.assertFalse(comparison['predecessor_minimum_age_pass'])
        self.assertTrue(comparison['newly_admitted_bridge'])
        rejected=bridge_facts();rejected['hard_concentration_pass']=False
        comparison=evaluate_entry(rejected)['policy_comparison']
        self.assertFalse(comparison['newly_admitted_bridge'])
        self.assertFalse(comparison['evaluated_shared_predicates']['hard_concentration'])
        mature=evaluate_entry(facts())['policy_comparison']
        self.assertTrue(mature['predecessor_minimum_age_pass'])
        self.assertEqual(mature['scope'],'evaluated_shared_entry_predicates')
        self.assertEqual(mature['complete_predecessor_decision'],'not_replayed')

    def test_denied_bridge_uses_existing_funding_event_for_missed_eligibility(self):
        from types import SimpleNamespace
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
        runtime=object.__new__(Runtime);runtime.now=lambda:600;events=[]
        runtime.candidate_history=SimpleNamespace(record_funding=lambda *args,**kwargs:events.append((args,kwargs)))
        row=dict(id='mint',decision_id='qualified-decision',decision=evaluate_entry(bridge_facts()))
        runtime._funding(row,'denied','fresh_quote_unavailable')
        self.assertEqual(len(events),1)
        self.assertTrue(events[0][1]['details']['missed_eligible_bridge'])
        self.assertEqual(events[0][1]['reason'],'fresh_quote_unavailable')
        self.assertTrue(events[0][1]['details']['policy_comparison']['newly_admitted_bridge'])

    def test_bridge_unknown_history_structure_demand_and_safety_are_closed(self):
        mutations=[
            (lambda f:f.update(authoritative=False),'authoritative_evidence'),
            (lambda f:f.update(continuity_complete=False),'authoritative_evidence'),
            (lambda f:f.update(demand_complete=False),'incomplete_structure_or_demand'),
            (lambda f:f['price_points'].pop(0),'complete_graduation_history'),
            (lambda f:f.update(hard_concentration_pass=False),'hard_concentration'),
            (lambda f:f.update(creator_distribution_safe=False),'creator_distribution'),
            (lambda f:f.update(exit_liquidity_available=False),'exit_liquidity'),
            (lambda f:f.update(mayhem={'status':'active'}),'active_mayhem'),
            (lambda f:f['price_points'][-1].update(price='160'),'no_continuation'),
            (lambda f:f['demand_events'].pop(),'bridge_buyer_breadth'),
            (lambda f:f['demand_events'][-1].update(quote=100000),'bridge_demand_concentration'),
            (lambda f:f['demand_events'][-1].update(authenticated=False),'incomplete_structure_or_demand'),
        ]
        for mutate,reason in mutations:
            with self.subTest(reason=reason):
                f=bridge_facts();mutate(f)
                d=evaluate_entry(f)
                self.assertFalse(d['candidate'],d)
                self.assertIn(reason,d['all_rejections'])

    def test_bridge_pre_two_x_trail_and_right_tail_match_current_boundaries(self):
        from meme_machine.runtime.survivor_risk import mark
        from tests.test_survivor_risk_boundaries import state,observation
        policy=POLICY['bridge_exits']
        # A positive peak below +15% still arms Current's 14% price drawdown.
        peak,_=mark(state(),observation(1,1000),policy)
        self.assertEqual(mark(peak,observation(2,-539),policy)[1]['action'],'hold')
        self.assertEqual(mark(peak,observation(2,-540),policy)[1]['reason'],'runner_trail')
        tail,_=mark(state(),observation(1,10000),policy)
        tail.update(realization_taken=True,remaining_quantity=301)
        self.assertEqual(mark(tail,observation(2,6001),policy)[1]['action'],'hold')
        self.assertEqual(mark(tail,observation(2,6000),policy)[1]['reason'],'tail_gain_giveback')

    def test_original_bridge_exit_profile_survives_fill_across_four_hour_boundary(self):
        from meme_machine.runtime.survivor_commit import risk_record
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
        decision=evaluate_entry(bridge_facts(14399))
        fresh=evaluate_entry(facts())
        self.assertTrue(decision['candidate']);self.assertTrue(fresh['candidate'])
        risk=risk_record(None,dict(action='filled',at=14400,
            position=dict(tokens=400,basis=100),evidence=dict(decision=decision,fill=fresh)))
        self.assertEqual(risk['execution_profile'],'pump_postgrad_bridge')
        runtime=object.__new__(Runtime)
        self.assertEqual(runtime.position_policy(risk,POLICY['exits']),POLICY['bridge_exits'])

    def test_bridge_keeps_native_quote_capacity_and_full_financial_lifecycle(self):
        from fractions import Fraction
        import os,tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH,STRATEGY_ID
        from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime,Quotes
        from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,buy_quote,sell_quote
        from meme_machine.runtime.directional_sleeve import open_sleeve
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.survivor_commit import monitor,restore_risk
        from tests.lanes.pump.test_postgrad_read_efficiency import MeteredRPC
        from tests.lanes.pump.test_postgrad import MINT
        # Real native integer quotes on decoded account layouts; no provider IO.
        rpc=MeteredRPC();state=PostGraduationAdapter(rpc,scan_rpc=object()).pumpswap_snapshot(
            MINT,101,reuse_verified_pool=True,held_curve_inline=True)
        state.update(market_time=600,available_time=600)
        f=bridge_facts(quote_scale=100000)
        ratio=Fraction(state['state']['quote_reserve'],state['state']['base_reserve'])/162
        for point in f['price_points']:point['price']=str(Fraction(point['price'])*ratio)
        f['migration_price']=str(100*ratio);f['recovery_vwap']=str(155*ratio)
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='bridge-offline'),clear=True):
            rt=object.__new__(Runtime);rt.root=Path(td);rt.run_id='bridge';rt.last_error=None
            rt.candidate_history=None;rt.adapter=None;rt.rpc=None;rt.clock=600;rt.now=lambda:rt.clock
            rt.sleeve=open_sleeve('pump',10_000_000_000)
            rt.book=PaperBook(td+'/paper',run_id=rt.run_id,lane=STRATEGY_ID,
                              policy_hash=POLICY_HASH,initial=10_000_000_000)
            rt.history=History(td+'/history',policy=POLICY_HASH)
            rt.history.graduate(MINT,dict(at=0,pool=state['pool'],identity='canonical-migration',
                signature='finalized-migration',quote_amount=100,mint_amount=1))
            rt.plane=SimpleNamespace(frontier=lambda scope:state['slot'],block_time=lambda slot:600,
                                     require_usable=lambda scope:None)
            rt.discover=lambda:None;rt._increment=lambda *args:None
            rt.fresh_state=lambda candidate,**kw:state
            rt.reconstruct=lambda *args,**kw:deepcopy(f)
            try:
                with patch('meme_machine.runtime.storage.compact_survivor'):
                    status=rt.step(admit=True)
                self.assertIsNone(status['last_boundary'],status)
                self.assertEqual(status['accounting']['open_positions'],1)
                work=status['execution_work_model']
                self.assertEqual((work['additional_workers'],work['additional_broad_market_scans'],
                                  work['counterfactual_full_history_evaluations']),(0,0,0))
                row=rt.history.get(MINT);identity=row['position'];position=rt.book._load(identity)
                self.assertGreater(position['basis'],0)
                self.assertEqual(position['status'],'open')
                self.assertLessEqual(position['basis'],evaluate_entry(f)['features']['turnover_cap'])
                risk=restore_risk(rt.book,identity)
                self.assertEqual(risk['execution_profile'],'pump_postgrad_bridge')
                self.assertEqual(rt.position_policy(risk,POLICY['exits']),POLICY['bridge_exits'])
                # Policy follows the original fill even after age four hours.
                f['now']=20000
                self.assertEqual(rt.position_policy(risk,POLICY['exits'])['hard_stop_bps'],-800)
                original_tokens=position['tokens'];original_basis=position['basis']
                rt.clock=601;rt.exit_quote=lambda qty:dict(quantity=qty,net_proceeds=original_basis*115//400,
                    acquired=rt.clock,market_time=rt.clock,slot=state['slot'])
                action=monitor(book=rt.book,sleeve=rt.sleeve,identity=identity,adapter=rt,
                    policy=POLICY['exits'],observation=dict(id='harvest',at=601,
                    after_cost_return_bps=1500,net_exit_proceeds=original_basis*115//100,exit_liquidity_valid=True))
                self.assertEqual(action['action'],'partial_exit')
                self.assertEqual(action['quantity'],original_tokens//4)
                rt.book.close();rt.book=PaperBook(td+'/paper',run_id=rt.run_id,lane=STRATEGY_ID,
                    policy_hash=POLICY_HASH,initial=10_000_000_000)
                self.assertTrue(restore_risk(rt.book,identity)['realization_taken'])
                rt.clock=602;remaining=rt.book._load(identity)
                rt.exit_quote=lambda qty:dict(quantity=qty,net_proceeds=remaining['basis']*92//100,
                    acquired=rt.clock,market_time=rt.clock,slot=state['slot'])
                action=monitor(book=rt.book,sleeve=rt.sleeve,identity=identity,adapter=rt,
                    policy=POLICY['exits'],observation=dict(id='stop',at=602,
                    after_cost_return_bps=-800,net_exit_proceeds=remaining['basis']*92//100,exit_liquidity_valid=True))
                self.assertEqual((action['action'],action['reason']),('full_exit','hard_stop'))
                terminal=rt.book._load(identity);native=rt.book.reconcile();capital=rt.sleeve.reconcile()
                self.assertEqual(terminal['status'],'settled')
                self.assertEqual((native['basis'],native['reserved'],native['open_positions']),(0,0,0))
                self.assertEqual(capital['reserved'],0)
                self.assertEqual(capital['available'],10_000_000_000+terminal['realized'])
                self.assertTrue(rt.book.replay()['verified'])
            finally:rt.book.close();rt.history.close();rt.sleeve.close()


if __name__=='__main__':unittest.main()
