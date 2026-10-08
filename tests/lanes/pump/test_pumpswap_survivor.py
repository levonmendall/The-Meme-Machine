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
        for age,passes in [(14399,False),(14400,True),(604800,True),(604801,False)]:
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

    def test_compression_exact_sixty_percent_and_one_tick_above(self):
        f=facts();f['price_points'][-2]['price']='186';f['price_points'][-1]['price']='188'
        self.assertNotIn('base_compression',evaluate_entry(f)['all_rejections'])
        f['price_points'][-2]['price']='186.0001'
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

    def test_reset_exact_eighteen_percent_and_one_fraction_below(self):
        f=facts()
        for row in f['price_points']:
            if row['at'] in (17800,20000,20799,20800):row['price']='164'
        self.assertNotIn('meaningful_reset',evaluate_entry(f)['all_rejections'])
        for row in f['price_points']:
            if row['at'] in (17800,20000,20799,20800):row['price']='164.0001'
        self.assertIn('meaningful_reset',evaluate_entry(f)['all_rejections'])

    def test_missing_full_base_and_active_lower_low_sequence(self):
        f=facts();f['price_points']=[r for r in f['price_points'] if r['at']>20800]
        self.assertIn('incomplete_structure_or_demand',evaluate_entry(f)['all_rejections'])
        f=facts()
        replacements={21400:'149',22000:'148',22600:'147',23200:'146',23800:'145'}
        for r in f['price_points']:r['price']=replacements.get(r['at'],r['price'])
        self.assertIn('lower_low_sequence',evaluate_entry(f)['all_rejections'])

    def test_intrasecond_extrema_cannot_hide_base_expansion_or_breakdown(self):
        f=facts();f['price_points'][10]['high']='190'
        self.assertIn('base_compression',evaluate_entry(f)['all_rejections'])
        f=facts();f['price_points'][10]['low']='139'
        self.assertIn('reset_low_breakdown',evaluate_entry(f)['all_rejections'])


if __name__=='__main__':unittest.main()
