"""Owner-selected PAPER rules on disposable native paths, never market research."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump import runner
from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.paper_accounting import PaperBook as CurrentBook
from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
from meme_machine.lanes.pump.pump_acceleration_paper import PumpAccelerationPaperLifecycle
from meme_machine.lanes.pump.pump_attempt_reference import (
    checkpoint_cancelled_attempt,prior_attempt_blocks,
)
from meme_machine.lanes.pump.pump_acceleration_strategy import (
    POLICY as CURRENT_POLICY, MODE_POSTGRAD, SignalVector, qualify,
    entry_signal_persistence,policy_hash as current_hash,STRATEGY_ID as CURRENT_ID,
)
from meme_machine.lanes.pump.pumpswap_survivor import (
    POLICY, POLICY_HASH, STRATEGY_ID, evaluate_entry, reduce_reset_history,
)
from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
from meme_machine.runtime.sleeve_reservations import SleeveReservations
from meme_machine.runtime.survivor_commit import commit
from meme_machine.runtime.survivor_history import History
from meme_machine.runtime.survivor_paper_book import PaperBook
from meme_machine.paper_policy_revision import previous_policies,predecessor_policies
from tests.lanes.pump import test_pump_acceleration_strategy as current_fixtures
from tests.lanes.pump.test_pumpswap_survivor import facts


def shallow_survivor(age=14400):
    """Exact 3% reset followed by equal completed ranges and later breakout."""
    shift=age-14400
    rows=[(0,90),(1000,95),(2000,100),(3000,97),(6500,98),(6600,98),
          (7500,99),(8500,100),(9500,99),(10200,98),(10800,'98.4'),
          (11400,'98.5'),(12000,99),(12600,'99.5'),(13200,'99.6'),
          (13800,100),(14400,101)]
    f=facts();f.update(now=age,graduation_at=0,base_end=age-600,
        migration_price='90',recovery_vwap='99',price_points=[dict(at=0,price='90')]+
        [dict(at=t+shift,price=str(p)) for t,p in rows if t>0])
    if age>21600:
        f['price_points'].insert(1,dict(at=age-21600,price='90'))
    for event in f['demand_events']:event['at']+=age-25000
    return f


class NativeAdapter:
    def __init__(self,f):self.f=f;self.calls=[]
    def now(self):return self.f['now']
    def fresh_state(self,candidate):self.calls.append('state');return dict(at=self.now())
    def fresh_quotes(self,state,budget):self.calls.append('quotes');return self
    def reconstruct(self,state,quotes):self.calls.append('reconstruct');return deepcopy(self.f)
    def turnover_cap(self,facts,decision):return decision['features']['turnover_cap']
    def loss(self,size):return 100 if size<=100 else 900
    def entry(self,size):return dict(cost=size,quantity=4*size)
    def generation_fence(self,candidate,generation):return nullcontext()
    def validate_current(self,state,execution,now):self.calls.append('validate')


class OpportunityAccessPumpTests(unittest.TestCase):
    def late(self,**updates):return current_fixtures.PumpAccelerationStrategyTests().strong_late(**updates)

    def test_broad_new_buyers_reach_prospect_and_fill_without_repeat_purchase(self):
        signal=self.late(repeat_buyer_clusters=0,repeat_buy_share_bps=0)
        decision=qualify(signal)
        self.assertTrue(decision.qualified,decision.reasons)
        self.assertEqual(decision.demoted_conditions,('repeat_buyers','repeat_buy_share'))
        _,reasons=runner._late_stream_prospect(replace(signal,immediate_roundtrip_loss_bps=None))
        self.assertEqual(reasons,())
        fill=entry_signal_persistence(signal,replace(signal,observed_at=1002))
        self.assertTrue(fill['persistent'],fill)
        self.assertEqual(fill['fill_demoted_conditions'],decision.demoted_conditions)
        self.assertEqual(fill['fill_repeat_buy_share_bps'],0)

    def test_missing_optional_repeat_diagnostics_do_not_authorize_or_reject(self):
        signal=self.late(repeat_buyer_clusters=None,repeat_buy_share_bps=None)
        decision=qualify(signal)
        self.assertTrue(decision.qualified,decision)
        self.assertEqual(decision.unavailable_diagnostics,('repeat_buyers','repeat_buy_share'))
        fill=entry_signal_persistence(signal,replace(signal,observed_at=1002))
        self.assertTrue(fill['persistent'],fill)
        self.assertIsNone(fill['fill_repeat_buyer_clusters'])

    def test_retained_late_curve_gates_still_block_without_repeat_purchase(self):
        for update,reason in ((dict(independent_buyer_clusters=13),'independent_buyers'),
                (dict(buyer_growth=2),'buyer_growth'),(dict(net_buy_share_bps=5199),'net_demand'),
                (dict(curve_velocity_bps_per_s=0),'curve_velocity'),
                (dict(concentration_bps=3001),'concentration'),
                (dict(immediate_roundtrip_loss_bps=601),'executable_downside')):
            with self.subTest(reason=reason):
                decision=qualify(self.late(repeat_buyer_clusters=0,repeat_buy_share_bps=0,**update))
                self.assertFalse(decision.qualified);self.assertIn(reason,decision.reasons)

    def test_previous_repeat_rule_remains_available_as_an_explicit_previous_policy(self):
        old=replace(CURRENT_POLICY,**previous_policies()['pump_current']['policy'],
                    revision='pre-opportunity-access-v1')
        decision=qualify(self.late(repeat_buyer_clusters=0,repeat_buy_share_bps=0),old)
        self.assertFalse(decision.qualified)
        self.assertIn('repeat_buyers',decision.reasons);self.assertIn('repeat_buy_share',decision.reasons)

    def test_immediate_predecessor_retains_repeat_diagnostic_economics(self):
        old=replace(CURRENT_POLICY,**predecessor_policies()['pump_current']['policy'])
        decision=qualify(self.late(repeat_buyer_clusters=0,repeat_buy_share_bps=0),old)
        self.assertTrue(decision.qualified,decision.reasons)
        self.assertEqual(decision.demoted_conditions,('repeat_buyers','repeat_buy_share'))

    def test_current_ongoing_requalification_keeps_demand_without_entry_age_deadline(self):
        signal=SignalVector(mint='M',observed_at=10000,surface='pumpswap',phase=MODE_POSTGRAD,
            graduated=True,seconds_since_graduation=10000,independent_buyer_clusters=10,
            buyer_growth=3,net_buy_share_bps=8500,concentration_bps=1600,
            price_vs_graduation_bps=1400,volume_acceleration_bps=3000,
            early_holder_sell_share_bps=1200)
        self.assertIn('postgrad_age',qualify(signal).reasons)
        self.assertTrue(qualify(signal,purpose='ongoing').qualified)
        self.assertIn('net_demand',qualify(replace(signal,net_buy_share_bps=0),purpose='ongoing').reasons)

    def test_optional_creator_launch_history_is_not_postgrad_distribution(self):
        p=SimpleNamespace(basis_quote_units=1000,mint='MINT',surface='pumpswap',
            demand_deterioration_streak=0,exit_reason=None)
        current=SimpleNamespace(creator_quality_bps=None,early_holder_sell_share_bps=1000,
            concentration_bps=1000)
        args=(SimpleNamespace(position=p),current,SimpleNamespace(qualified=True),
            dict(mint='MINT',available_time=1000),1100,1000)
        facts=runner._pump_continuation_facts(*args)
        self.assertTrue(facts['creator_distribution_safe'])
        current.early_holder_sell_share_bps=4501
        self.assertFalse(runner._pump_continuation_facts(*args)['creator_distribution_safe'])
        p.surface='pump.fun'
        facts=runner._pump_continuation_facts(*args)
        self.assertIsNone(facts['creator_distribution_safe'])
        self.assertEqual(facts['distribution_evidence']['source'],'unavailable')

    def test_funded_native_current_reservation_and_delayed_fill_with_zero_repeats(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
            fixture=json.loads((Path(__file__).parent/'fixtures/mainnet_candidate_accounts.json').read_text())
            accounts=deepcopy(fixture['response']['value']);decoded=pump.curve(accounts[0])
            # A synthetic late-curve state using captured account layouts and
            # unchanged native integer quotes, not a claimed market opportunity.
            initial=min(decoded.supply,decoded.token)*3//4
            raw=bytearray(base64.b64decode(accounts[0]['data'][0]))
            struct.pack_into('<Q',raw,24,initial//5)
            accounts[0]['data'][0]=base64.b64encode(raw).decode()
            curve=pump.curve(accounts[0]);initial=5*curve.real_token
            creation=dict(mint='MINT',creator=curve.creator,initial_real_token_reserves=initial)
            events=[]
            for i,(at,reserve) in enumerate(((980,initial*2//5),(990,initial*3//10))):
                events.append(dict(mint='MINT',wallet='old'+str(i),market_time=at,
                    real_token_reserves=reserve,virtual_quote_reserves=curve.sol,
                    virtual_token_reserves=curve.token,slot=i+1,index=0,buy=True,amount=20_000_000))
            for i in range(20):
                events.append(dict(mint='MINT',wallet='new'+str(i),market_time=995,
                    real_token_reserves=curve.real_token,virtual_quote_reserves=curve.sol,
                    virtual_token_reserves=curve.token,slot=10+i,index=0,buy=True,amount=20_000_000))
            confirmations=ConfirmationBook({},0)
            original=dict(mint='MINT',accounts=accounts,slot=100,market_time=1000,available_time=1000)
            final=dict(original,slot=101,market_time=1002,available_time=1002)
            book=CurrentBook(Path(td)/'paper.sqlite',run_id='funded',lane=CURRENT_ID,
                policy_hash=current_hash(),initial=1_000_000_000)
            tape=SimpleNamespace(window=lambda *args,**kwargs:events)
            sessions=SimpleNamespace(ensure=lambda _:None,
                pump=SimpleNamespace(snapshot=lambda *args,**kwargs:final),
                reader=SimpleNamespace(read=lambda *args,**kwargs:(1500,{'source':'offline-holder-fixture'})))
            pending={};active={};report={'qualifiers':[]}
            context=dict(tape=tape,created={'MINT':{'creation':creation}},confirmations=confirmations)
            try:
                with patch.object(runner,'ACCOUNTING',book),patch.object(runner,'FILL_PERSISTENCE_CONTEXT',context),\
                        patch.object(runner,'CANDIDATE_HISTORY',None),patch.object(runner,'PIPELINE',None),\
                        patch.object(runner,'_current_pump_sizing',return_value=dict(target=10_000_000,
                            available=1_000_000_000,realized_equity=1_000_000_000)),\
                        patch.object(runner.time,'time',return_value=1000):
                    signal,_,_=runner._late_signal(creation,events,original,1500,confirmations)
                    decision=qualify(signal)
                    self.assertTrue(decision.qualified,decision)
                    self.assertEqual((signal.repeat_buyer_clusters,signal.repeat_buy_share_bps),(0,0))
                    self.assertTrue(runner._reserve_position(report,pending,active,signal,decision,original,signal.phase))
                    self.assertFalse(runner._reserve_position(report,pending,active,signal,decision,original,signal.phase))
                    with patch.object(runner.time,'time',return_value=1002):
                        runner._fill_pending(report,pending,active,sessions,{},1002)
                self.assertFalse(pending,pending)
                self.assertEqual(book.reconcile()['open_positions'],1)
                self.assertTrue(report['qualifiers'][0]['fill_persistence']['persistent'])
                self.assertEqual(report['qualifiers'][0]['entry_status'],'filled')
                life=next(iter(active.values()))['lifecycle']
                self.assertGreater(life.position.tokens,0)
                self.assertLessEqual(life.position.basis_quote_units,10_000_000+runner.GAS)
                self.assertEqual(book.replay()['verified'],True)
                life.sleeve.close();life.sleeve=None
            finally:book.close()

    def test_verified_cancelled_attempt_requires_release_new_generation_and_no_prior_filled_reference(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
            signal=self.late();snapshot=dict(slot=1,market_time=signal.observed_at)
            book=CurrentBook(Path(td)/'paper.sqlite',run_id='retry',lane=CURRENT_ID,
                policy_hash=current_hash(),initial=100000)
            life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='retry:one',entry_evidence=snapshot)
            try:
                life.reserve(qualify(signal),1000,1000)
                # A terminal native cancel with a delayed sleeve ACK is unresolved.
                book.transition('retry:one','cancelled',1002,evidence={'reason':'offline-cancel'})
                self.assertIsNone(checkpoint_cancelled_attempt(book,'retry:one',signal,snapshot))
                from meme_machine.lanes.pump.pump_attempt_reference import KEY
                self.assertIsNotNone(book.runtime_state('retry:one',KEY))
                rows=[dict(lifecycle_id='retry:one',mint=signal.mint,mode=signal.phase)]
                fresh=replace(signal,observed_at=1005);new_snapshot=dict(slot=2,market_time=1005)
                self.assertTrue(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                p=book._load('retry:one')
                from meme_machine.runtime.journal import digest
                life.sleeve.release('retry:one',pnl=0,at=1002,terminal_hash=digest(p),
                    native_verified=book.replay()['verified'],cancelled=True)
                # The later ACK makes a new candidate reachable without a
                # history rescan, a new timestamp, or a restart/rederivation.
                proof=book.runtime_state('retry:one',KEY)
                self.assertIsNotNone(proof)
                self.assertTrue(prior_attempt_blocks(book,rows,signal,snapshot))
                self.assertFalse(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                self.assertTrue(prior_attempt_blocks(book,rows+[dict(lifecycle_id='earlier-filled',
                    mint=signal.mint,mode=signal.phase)],fresh,new_snapshot))
                book.close();book=CurrentBook(Path(td)/'paper.sqlite',run_id='retry',lane=CURRENT_ID,
                    policy_hash=current_hash(),initial=100000)
                self.assertFalse(prior_attempt_blocks(book,rows,fresh,new_snapshot))
            finally:
                if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                book.close()

    def test_verified_cancellation_can_join_retained_reserved_prefix(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
            signal=self.late();snapshot=dict(slot=1,market_time=signal.observed_at)
            book=CurrentBook(Path(td)/'paper.sqlite',run_id='prefix',lane=CURRENT_ID,
                policy_hash=current_hash(),initial=100000)
            life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='prefix:one',entry_evidence=snapshot)
            try:
                life.reserve(qualify(signal),1000,1000)
                copy=Path(td)/'prefix.sqlite';db=sqlite3.connect(copy)
                book.db.backup(db);db.close()
                checksum=hashlib.sha256(copy.read_bytes()).hexdigest()
                book._compact_preserved(copy,dict(snapshot_sha256=checksum,state_hash=checksum,
                    snapshot_name='offline',epoch_id='offline',window_index=1,artifact=None))
                self.assertEqual(book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
                life.cancel('offline-cancel',1002)
                proof=checkpoint_cancelled_attempt(book,'prefix:one',signal,snapshot)
                self.assertIsNotNone(proof)
                self.assertEqual(proof['native_history_actions'],{'reserved':1,'cancelled':1})
            finally:
                if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                book.close()

    def test_current_completed_trade_count_does_not_block_new_verified_candidate(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
            signal=self.late();snapshot=dict(slot=1,market_time=1000)
            book=CurrentBook(Path(td)/'paper.sqlite',run_id='closed',lane=CURRENT_ID,
                policy_hash=current_hash(),initial=100000)
            life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id='closed:one',entry_evidence=snapshot)
            rows=[dict(lifecycle_id='closed:one',mint=signal.mint,mode=signal.phase)]
            fresh=replace(signal,observed_at=1010);new_snapshot=dict(slot=3,market_time=1010)
            try:
                life.reserve(qualify(signal),1000,1000)
                self.assertTrue(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                life.fill(100,1000,1002,'pump.fun')
                self.assertTrue(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                # Exact settlement is present, but capital release is delayed.
                terminal_snapshot=dict(slot=2,market_time=1005)
                book.transition('closed:one','settled',1005,amount=1100,tokens=100,
                    evidence=dict(snapshot=terminal_snapshot))
                from meme_machine.lanes.pump.pump_attempt_reference import checkpoint_terminal_attempt,KEY
                self.assertIsNone(checkpoint_terminal_attempt(book,'closed:one',signal,snapshot))
                proof=book.runtime_state('closed:one',KEY)
                self.assertEqual(proof['outcome'],'filled_and_closed')
                self.assertEqual((proof['original_entry_quantity'],proof['paid_entry_cost']),(100,1000))
                self.assertTrue(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                from meme_machine.runtime.journal import digest
                p=book._load('closed:one')
                life.sleeve.release('closed:one',pnl=100,at=1005,terminal_hash=digest(p),
                    native_verified=book.replay()['verified'],cancelled=False)
                self.assertFalse(prior_attempt_blocks(book,rows,fresh,new_snapshot))
                self.assertTrue(prior_attempt_blocks(book,rows,replace(signal,observed_at=1005),terminal_snapshot))
                self.assertIn('net_demand',qualify(replace(fresh,net_buy_share_bps=0)).reasons)
                with patch.object(runner,'ACCOUNTING',book),patch.object(runner,'FILL_PERSISTENCE_CONTEXT',None),\
                        patch.object(runner,'CANDIDATE_HISTORY',None),patch.object(runner,'PIPELINE',None),\
                        patch.object(runner,'_current_pump_sizing',return_value=dict(target=1000,available=100000)),\
                        patch.object(runner.time,'time',return_value=1010),patch.object(runner,'GAS',0):
                    report={'qualifiers':rows};pending={}
                    execution=dict(new_snapshot,available_time=1010)
                    self.assertTrue(runner._reserve_position(report,pending,{},fresh,qualify(fresh),execution,fresh.phase))
                    self.assertFalse(runner._reserve_position(report,pending,{},fresh,qualify(fresh),execution,fresh.phase))
                    next(iter(pending.values()))['lifecycle'].sleeve.close()
            finally:
                if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                book.close()

    def test_native_terminal_classification_does_not_depend_on_reporting_split(self):
        from collections import Counter
        from meme_machine.lanes.pump.pump_attempt_reference import fold_terminal_attempt,reference_key
        for outcome in ('cancelled','settled'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                    MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
                signal=self.late();identity='native-terminal:'+outcome
                snapshot=dict(slot=1,market_time=signal.observed_at,
                    _runtime_recovery=dict(signal=signal.__dict__,state={}))
                book=CurrentBook(Path(td)/'paper.sqlite',run_id='native-terminal',lane=CURRENT_ID,
                    policy_hash=current_hash(),initial=100000)
                life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=identity,entry_evidence=snapshot)
                try:
                    life.reserve(qualify(signal),1000,1000)
                    if outcome=='cancelled':life.cancel('offline-cancel',1005)
                    else:
                        life.fill(100,1000,1002,'pump.fun');life.mark(800,1003,80)
                        life.settle(1100,1005,evidence=dict(snapshot=dict(slot=2,market_time=1005)))
                    book.replay()
                    journal=[(json.loads(body),event_hash) for body,event_hash in
                        book.db.execute('SELECT body,hash FROM journal ORDER BY seq')]
                    event,event_hash=journal[-1]
                    summary=dict(events=len(journal),actions=dict(Counter(row['action'] for row,_ in journal)))
                    for unavailable in (None,dict(state='UNAVAILABLE',reason='retired_component_detail')):
                        frontiers={}
                        fold_terminal_attempt(frontiers,event,event_hash,summary,unavailable,book.identity)
                        proof=frontiers[reference_key(signal.mint,signal.phase)]
                        self.assertEqual(proof['outcome'],
                            'verified_never_filled' if outcome=='cancelled' else 'filled_and_closed')
                        self.assertEqual(proof['original_entry_quantity'],0 if outcome=='cancelled' else 100)
                        self.assertEqual(proof['paid_entry_cost'],0 if outcome=='cancelled' else 1000)
                    missing=deepcopy(event);missing['evidence']['attempt'].pop('paid_entry_cost')
                    frontiers={};fold_terminal_attempt(frontiers,missing,event_hash,summary,None,book.identity)
                    self.assertFalse(frontiers)
                finally:
                    if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                    book.close()

    def test_actual_current_retirement_keeps_latest_generation_through_restart(self):
        from meme_machine.runtime.lifecycle_identity import issue
        from meme_machine.runtime.storage import compact_pump
        from meme_machine.lanes.pump.pump_attempt_reference import FRONTIERS,reference_key
        for outcome in ('cancelled','settled'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(
                    MM_PAPER_EPOCH='retirement-fixture',MM_DIRECTIONAL_SLEEVE_DB=td+'/sleeve.sqlite',
                    MM_DIRECTIONAL_COHORT_ID='isolated'),clear=True):
                path=Path(td)/'paper.sqlite';signal=self.late();identity=issue('retirement:'+outcome)
                def snapshot(s,slot):
                    return dict(slot=slot,market_time=s.observed_at,_runtime_recovery=dict(
                        signal=s.__dict__,mode=s.phase,concentration=1500,confirmation_state=None,
                        state=dict(creation=dict(mint=s.mint,creator='creator'),pregrad_wallets=[],graduated=False),
                        execution=dict(scope=runner.PUMP_SCOPE,addresses=['curve'])))
                original=snapshot(signal,1)
                book=CurrentBook(path,run_id='retirement',lane=CURRENT_ID,policy_hash=current_hash(),initial=100000)
                life=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=identity,entry_evidence=original)
                dummy=None
                try:
                    life.reserve(qualify(signal),1000,1000)
                    if outcome=='cancelled':
                        life.cancel('offline-cancel',1005)
                        # A zero-fill cancel has only its original canonical frontier.
                        terminal_slot,terminal_time=1,1000
                    else:
                        life.fill(100,1000,1002,'pump.fun')
                        life.mark(800,1003,80)
                        self.assertEqual(life.position.exit_reason,'risk_stop')
                        life.settle(1100,1005,evidence=dict(snapshot=dict(slot=2,market_time=1005)))
                        terminal_slot,terminal_time=2,1005
                    # No outer checkpoint helper runs: terminal event metadata
                    # must survive folding/retirement directly in the native owner.
                    other=self.late(mint='OTHER',observed_at=1006)
                    other_id=issue('retirement:other')
                    dummy=PumpAccelerationPaperLifecycle(book=book,lifecycle_id=other_id,
                        entry_evidence=snapshot(other,3))
                    dummy.reserve(qualify(other),1000,1006);dummy.fill(100,1000,1006,'pump.fun')
                    remaining=512-book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0]
                    for i in range(remaining):dummy.mark(1000,1007+i,80)
                    with self.assertRaisesRegex(ValueError,'paper_position_missing'):book._load(identity)
                    retained=book._archive()[FRONTIERS][reference_key(signal.mint,signal.phase)]
                    self.assertEqual(retained['lifecycle_id'],identity)
                    self.assertTrue(retained['retirement']['portfolio_release_acknowledged'])
                    self.assertEqual(retained['decision_observed_at'],1000)
                    rows=[dict(lifecycle_id=identity,mint=signal.mint,mode=signal.phase)]
                    same=replace(signal,observed_at=terminal_time)
                    self.assertTrue(prior_attempt_blocks(book,rows,same,
                        dict(slot=terminal_slot,market_time=terminal_time)))
                    fresh=replace(signal,observed_at=1518)
                    self.assertFalse(prior_attempt_blocks(book,rows,fresh,dict(slot=4,market_time=1518)))
                    # A malformed present projection is corruption, not absence
                    # covered by the verified financial retirement receipt.
                    from meme_machine.lanes.pump.pump_attempt_reference import release_acknowledged
                    book.db.execute('INSERT INTO positions VALUES(?,?)',(identity,'not-json'))
                    try:self.assertFalse(release_acknowledged(book,retained))
                    finally:book.db.execute('DELETE FROM positions WHERE id=?',(identity,))
                    dummy.sleeve.close();dummy.sleeve=None;book.close()
                    book=CurrentBook(path,run_id='retirement',lane=CURRENT_ID,
                        policy_hash=current_hash(),initial=100000)
                    plane=SimpleNamespace(interest=lambda *args,**kwargs:None)
                    _,_,_,active,recovered=runner.restore_runtime(book,plane,ConfirmationBook({},0))
                    self.assertIn(('OTHER',other.phase),active)
                    self.assertFalse(any(row['lifecycle_id']==identity for row in recovered))
                    # The report omits retired rows after restart. Native derived
                    # evidence still fences its last consumed canonical generation.
                    self.assertTrue(prior_attempt_blocks(book,recovered,same,
                        dict(slot=terminal_slot,market_time=terminal_time)))
                    self.assertFalse(prior_attempt_blocks(book,recovered,fresh,dict(slot=4,market_time=1518)))
                    for row in active.values():
                        row['lifecycle'].sleeve.close();row['lifecycle'].sleeve=None
                    # A subsequent ordinary prefix fold retains the latest proof.
                    marker=book.replay()
                    with patch('meme_machine.runtime.storage.compact_pump'):
                        book.transition(other_id,'mark',2000,amount=1000,evidence=dict(demand_score=80))
                        copy=Path(td)/'next.sqlite';db=sqlite3.connect(copy);book.db.backup(db);db.close()
                        checksum=hashlib.sha256(copy.read_bytes()).hexdigest()
                        book._compact_preserved(copy,dict(snapshot_sha256=checksum,state_hash=checksum,
                            epoch_id='retirement-fixture',window_index=10**30,snapshot_name='offline',artifact=None),
                            cost_reader=lambda _:None,risk_reader=lambda *_:None)
                    self.assertEqual(book._archive()[FRONTIERS][reference_key(signal.mint,signal.phase)],retained)
                    self.assertEqual(book.replay()['events'],marker['events']+1)
                finally:
                    if life.sleeve is not None:life.sleeve.close();life.sleeve=None
                    if dummy is not None and dummy.sleeve is not None:dummy.sleeve.close();dummy.sleeve=None
                    book.close()

    def test_complete_four_to_six_hour_windows_have_honest_duration_and_boundary(self):
        for age in (14400,18000,21600,21601):
            with self.subTest(age=age):
                decision=evaluate_entry(shallow_survivor(age))
                self.assertTrue(decision['candidate'],decision)
                w=decision['features']['long_structure_window']
                self.assertEqual(w['nominal_seconds'],21600)
                self.assertEqual(w['effective_seconds'],min(age,21600))
                self.assertEqual(w['covered_seconds'],w['effective_seconds'])
                self.assertEqual(w['window_start'],age-min(age,21600))
                self.assertTrue(w['complete'])

    def test_four_hour_boundary_witness_and_continuity_are_required(self):
        f=shallow_survivor();f['price_points']=f['price_points'][1:]
        decision=evaluate_entry(f)
        self.assertIn('six_hour_structure',decision['all_rejections'])
        self.assertFalse(decision['features']['long_structure_window']['complete'])
        self.assertEqual(decision['features']['long_structure_window']['covered_seconds'],13400)
        f=shallow_survivor();f['continuity_complete']=False
        self.assertIn('authoritative_evidence',evaluate_entry(f)['all_rejections'])

    def test_entry_age_bounds_and_held_requalification_are_separate(self):
        for age,valid in ((599,False),(600,True),(14399,True),(14400,True),(604800,True),(604801,False)):
            decision=evaluate_entry(shallow_survivor(age))
            self.assertEqual('age' not in decision['all_rejections'],valid)
        f=shallow_survivor(604801);f['qualification_purpose']='ongoing'
        self.assertTrue(evaluate_entry(f)['candidate'],evaluate_entry(f))
        f['exit_liquidity_available']=False
        self.assertIn('exit_liquidity',evaluate_entry(f)['all_rejections'])

    def test_shallow_nonexpanding_completed_base_retains_order_breakout_and_low_protection(self):
        f=shallow_survivor();decision=evaluate_entry(f)
        self.assertTrue(decision['candidate'],decision)
        self.assertEqual(decision['features']['reset_depth_bps'],300)
        self.assertEqual(decision['features']['base_compression_bps'],10000)
        self.assertLess(decision['features']['peak_at'],decision['features']['reset_at'])
        self.assertLess(decision['features']['reset_at'],f['base_end']-3600)
        for change,reason in ((('reset','97.0001'),'meaningful_reset'),
                              (('low','96.9'),'reset_low_breakdown'),
                              (('base_high','100.0001'),'base_compression'),
                              (('breakout','100'),'no_continuation')):
            changed=deepcopy(f);key,value=change
            target=3000 if key=='reset' else 10800 if key=='low' else 13800 if key=='base_high' else 14400
            for row in changed['price_points']:
                if row['at']==target:row['low' if key=='low' else 'price']=value
            self.assertIn(reason,evaluate_entry(changed)['all_rejections'],key)

    def test_old_threshold_prefix_is_not_relabelled_and_missing_detail_is_explicit(self):
        old=dict(POLICY);old.pop('revision');old.update(minimum_reset_bps=1800,compression_bps=6000)
        original=reduce_reset_history(shallow_survivor()['price_points'][:4],policy=old)
        saved=deepcopy(original)
        self.assertIsNone(original['reset_at'])
        with self.assertRaisesRegex(ValueError,'reset_history_prefix_identity'):
            reduce_reset_history([],original)
        self.assertEqual(original,saved)
        f=shallow_survivor();f['reset_history_revision_detail_unavailable']='retired_predecessor_detail'
        self.assertIn('reset_history_revision_detail_unavailable',evaluate_entry(f)['all_rejections'])

    def test_new_survivor_reaches_funded_smaller_native_commit_and_restart(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            root=Path(td);f=shallow_survivor();decision=evaluate_entry(f);adapter=NativeAdapter(f)
            sleeve=SleeveReservations(root/'sleeve.sqlite',lane='pump',capital=1000,
                policies={'current':'fixture',STRATEGY_ID:POLICY_HASH},cohort='isolated')
            book=PaperBook(root/'paper.sqlite',run_id='fixture',lane=STRATEGY_ID,
                policy_hash=POLICY_HASH,initial=1000)
            self.addCleanup(sleeve.close)
            regime=dict(at=f['now'],base_id='base',high_reset_cycle='peak/reset',buyer_population=['a','b'])
            from meme_machine.runtime.rally_cycle import build_cycle
            features=decision['features']
            regime['rally_cycle']=build_cycle(candidate='mint',venue='pumpswap',
                chain='synthetic-offline',pool='synthetic-pool',policy_hash=POLICY_HASH,
                input_version='synthetic-canonical-history-v1',graduation=dict(at=f['graduation_at']),
                **{key:features[key] for key in ('peak_at','reset_at','base_start','base_end','breakout_at')},
                decision_at=f['now'],evidence_id='synthetic-acquired-history',authoritative=True,
                complete=True,minimum_base_seconds=POLICY['base_seconds'])
            observed=sleeve.observe('mint',strategy=STRATEGY_ID,at=f['now'],state='qualified',
                evidence=decision,regime=regime)
            regime=observed['regime']
            kwargs=dict(sleeve=sleeve,identity='fixture:one',candidate='mint',generation=1,
                strategy=STRATEGY_ID,policy_hash=POLICY_HASH,decision=decision,regime=regime,
                at=f['now'],target=100,minimum=10,retention_bps=5000,ordinary_limit=600,
                stress_limit=600,adapter=adapter,qualify=evaluate_entry)
            try:
                result=commit(book=book,**kwargs)
                self.assertEqual(result['status'],'filled')
                self.assertEqual(result['position']['basis'],50)
                self.assertEqual(adapter.calls,['state','quotes','reconstruct','validate'])
                rt=object.__new__(Runtime);rt.book=book
                self.assertEqual(rt._qualification_purpose({'position':'fixture:one'}),'ongoing')
                book.close();book=PaperBook(root/'paper.sqlite',run_id='fixture',lane=STRATEGY_ID,
                    policy_hash=POLICY_HASH,initial=1000)
                rt.book=book
                before=list(adapter.calls)
                self.assertEqual(commit(book=book,**kwargs)['status'],'already_committed')
                self.assertEqual(adapter.calls,before)
                book.reserve('fixture:pending',20,f['now'],{})
                self.assertEqual(rt._qualification_purpose({'position':'fixture:pending'}),'entry')
                self.assertEqual(rt._qualification_purpose({'position':'missing'}),'entry')
            finally:book.close()

    def test_same_policy_history_restart_preserves_raw_reset_and_bounded_window(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';f=shallow_survivor()
            history=History(path,policy=POLICY_HASH)
            history.graduate('mint',dict(at=0,pool='pool'))
            history.append('mint',through=f['now'],events=f['demand_events'],
                points=[(row['at'],row['price']) for row in f['price_points']],complete=True)
            history.close();history=History(path,policy=POLICY_HASH)
            try:
                points,events,prefix=history.calculation_facts('mint',f['now'],
                    reducer=reduce_reset_history,policy=POLICY_HASH)
                recovered=evaluate_entry(dict(f,price_points=points,demand_events=events,reset_history_prefix=prefix))
                self.assertEqual(recovered,evaluate_entry(f))
            finally:history.close()
