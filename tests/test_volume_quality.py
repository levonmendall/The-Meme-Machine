"""Attention changes actual queues, without adding economic/funding authority."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime import volume_quality as vq
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.survivor_history import History
from meme_machine.lanes.pons.pons_history import PonsHistory
from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH as SURVIVOR_POLICY
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_POLICY
from meme_machine.runtime.robinhood.pons import Broker
from tests.lanes.pons.test_pons_candidate_plane import event as nomination


def event(identity,at,group,quote,buy=True):
    return dict(id=identity,at=at,group=group,quote=quote,buy=buy,authenticated=True)


def accelerating():
    return [event('p'+str(i),85,'g'+str(i),10) for i in range(2)]+[
        event('c'+str(i),95,'g'+str(i),20) for i in range(4)]


class VolumeQualityTests(unittest.TestCase):
    def setUp(self):
        self.switch=patch.dict('os.environ',MM_VOLUME_QUALITY_ENABLED='1')
        self.switch.start();self.addCleanup(self.switch.stop)

    def signal(self,events,**kwargs):
        return vq.from_events(events,lower=40,through=100,now=100,observed_at=100,
            asset='SOL',authoritative=True,**kwargs)

    def test_independent_acceleration_exact_components(self):
        value=self.signal(accelerating());row=value['windows']['10']
        self.assertEqual(value['classification'],'QUALITY_ACCELERATING')
        self.assertEqual((row['volume_change'],row['net_buy_change'],row['buyer_growth']),(60,60,2))
        self.assertEqual((row['new_buying_groups'],row['repeat_buying_groups'],row['repeat_buy_share_bps']),(2,2,5000))
        self.assertEqual(row['net_per_trade'],[80,4])
        self.assertEqual(row['net_per_buyer'],[80,4])
        self.assertEqual(row['net_rate'],[80,10])
        self.assertFalse(value['windows']['60']['complete'])

    def test_related_wallets_do_not_become_independent_buyers(self):
        rows=[dict(id=str(i),market_time=95,wallet='wallet'+str(i),amount=50,buy=True) for i in range(8)]
        value=self.signal(rows,cluster_map={'wallet'+str(i):'one-funded-group' for i in range(8)})
        self.assertEqual(value['windows']['10']['current']['independent_groups'],1)
        self.assertEqual(value['classification'],'VOLUME_ONLY_ACCELERATION')
        self.assertEqual(value['rank'],0)

    def test_market_context_does_not_create_another_demand_score(self):
        baseline=self.signal(accelerating())
        context=dict(stage='bonding_curve',curve_progress_bps=6500)
        value=self.signal(accelerating(),progress=context)
        self.assertEqual(value['progress_context'],context)
        self.assertEqual(value['rank'],baseline['rank'])
        self.assertEqual(value['windows'],baseline['windows'])
        # Native quote units remain explicit through each market transition.
        survivor=self.signal(accelerating(),progress=dict(stage='postgraduation'))
        self.assertEqual(survivor['quote_asset'],'SOL')
        self.assertEqual(survivor['progress_context']['stage'],'postgraduation')

    def test_creator_flow_is_counted_gross_but_not_independent(self):
        rows=accelerating()+[event('creator',95,'creator',1000)]
        value=self.signal(rows,excluded=('creator',))
        row=value['windows']['10']
        self.assertEqual(row['current']['raw_buy'],1080)
        self.assertEqual(row['current']['buy'],80)
        self.assertIn('related_flow_dominant',row['warnings'])
        self.assertNotEqual(value['classification'],'QUALITY_ACCELERATING')

    def test_more_volume_with_declining_net_is_deterioration(self):
        rows=accelerating()+[event('selling',95,'seller',120,False)]
        value=self.signal(rows)
        self.assertEqual(value['classification'],'DEMAND_DETERIORATING')
        self.assertGreater(value['windows']['10']['volume_change'],0)
        self.assertLess(value['windows']['10']['net_buy_change'],0)

    def test_strong_repeat_participation_need_not_add_new_groups(self):
        rows=[event('p'+str(i),85,'g'+str(i),10) for i in range(2)]+[
            event('c'+str(i),95,'g'+str(i),50) for i in range(2)]
        value=self.signal(rows)
        self.assertEqual(value['classification'],'QUALITY_ACCELERATING')
        self.assertEqual(value['windows']['10']['repeat_buy_share_bps'],10000)

    def test_renewed_demand_from_authentic_quiet_window_has_no_infinity(self):
        quiet=self.signal([]);quiet['asof']=99
        growing=self.signal([event('a',95,'a',30),event('b',95,'b',30)])
        self.assertEqual(quiet['classification'],'STABLE_OR_QUIET')
        self.assertIsNone(growing['windows']['10']['acceleration_bps'])
        self.assertTrue(vq.recovered(quiet,growing,100))
        self.assertFalse(vq.recovered(growing,dict(growing,asof=101),101))

    def test_unknown_windows_are_never_zero(self):
        state=vq.advance(None,[],lower=95,through=100,complete=True,asset='SOL',authoritative=True)
        self.assertEqual(vq.signal(state,now=100,observed_at=100)['classification'],'INSUFFICIENT_EVIDENCE')
        state=vq.advance(None,[],lower=0,through=100,complete=False,asset='SOL',authoritative=True)
        self.assertFalse(vq.signal(state,now=100,observed_at=100)['complete'])

    def test_duplicate_delivery_and_same_timestamp_order(self):
        rows=accelerating()
        self.assertEqual(self.signal(rows),self.signal(rows[::-1]+rows))
        conflict=dict(rows[0],quote=999)
        with self.assertRaisesRegex(ValueError,'event_conflict'):self.signal(rows+[conflict])

    def test_no_future_or_boundary_trade_leaks_into_completed_window(self):
        before=self.signal(accelerating())
        self.assertEqual(before,self.signal(accelerating()+[event('future',101,'new',999),event('boundary',100,'now',999)]))

    def test_stale_clock_and_liquidity_warning_are_neutral_or_deteriorating(self):
        state=vq.advance(None,accelerating(),lower=40,through=100,complete=True,asset='SOL',authoritative=True)
        self.assertEqual(vq.signal(state,now=106,observed_at=100)['classification'],'INSUFFICIENT_EVIDENCE')
        value=vq.signal(state,now=100,observed_at=100,windows=(10,),market_warnings=('liquidity_deteriorating',))
        self.assertEqual(value['classification'],'DEMAND_DETERIORATING')

    def test_native_units_are_separate_and_feature_switch_is_reversible(self):
        value=self.signal(accelerating())
        other=vq.from_events(accelerating(),lower=40,through=100,now=100,observed_at=100,
            asset='ROBINHOOD_NATIVE',authoritative=True)
        self.assertNotEqual(value['quote_asset'],other['quote_asset'])
        with patch.dict('os.environ',MM_VOLUME_QUALITY_ENABLED='0'):
            self.assertEqual(vq.attention(value,100),0)
            self.assertFalse(vq.recovered(dict(value,classification='STABLE_OR_QUIET'),value,100))

    def history(self,path,kind=History):
        history=kind(path,policy=SURVIVOR_POLICY);history.volume_quote_asset='SOL' if kind is History else 'ROBINHOOD_NATIVE'
        row=history.graduate('candidate',dict(at=0));row['volume_quality_excluded']=[];history.save(row)
        return history

    def test_restart_replay_and_gap_invalidation_in_real_history(self):
        with tempfile.TemporaryDirectory() as td,patch('time.time',return_value=120):
            path=Path(td)/'history';history=self.history(path)
            first=[event('p'+str(i),5,'g'+str(i),10) for i in range(2)]
            second=[event('c'+str(i),65,'g'+str(i),20) for i in range(4)]
            history.append('candidate',through=60,events=first,points=[],complete=True)
            history.append('candidate',through=120,events=second,points=[],complete=True)
            row=history.get('candidate');self.assertTrue(row['volume_quality_requalification_due'])
            self.assertEqual(row['volume_quality']['classification'],'QUALITY_ACCELERATING')
            before=row['volume_quality_state'];history.close()
            history=History(path,policy=SURVIVOR_POLICY);history.volume_quote_asset='SOL'
            history.append('candidate',through=120,events=first+second,points=[],complete=True)
            self.assertEqual(history.get('candidate')['volume_quality_state'],before)
            history.append('candidate',through=121,events=[],points=[],complete=False)
            self.assertEqual(history.volume_signal(history.get('candidate'),121)['classification'],'INSUFFICIENT_EVIDENCE')
            self.assertEqual(history.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],6)
            history.close()

    def test_long_held_position_never_enters_optional_tracker(self):
        with tempfile.TemporaryDirectory() as td:
            history=self.history(Path(td)/'history');row=history.get('candidate')
            row['position']='original-owner';history.save(row)
            with patch.object(vq,'advance',side_effect=AssertionError('protection must not pay tracker work')):
                history.append('candidate',through=2592000,events=[],points=[],complete=True)
            self.assertEqual(history.get('candidate')['position'],'original-owner');history.close()

    def test_queue_quality_changes_only_exact_edf_peers(self):
        with tempfile.TemporaryDirectory() as td,patch('meme_machine.solana_prewarm_startup.candidate_release',return_value=True):
            clock=[100.];history=CandidateHistory(Path(td)/'work',clock=lambda:clock[0])
            for name in ('quiet','strong'):
                history.observe('pump',name,surface='pumpswap',observed_at=100)
                history.enqueue('pump',name,kind='qualification',ready_at=100,deadline=120,estimate_seconds=1,identity=name)
            history.volume_quality('pump','strong',self.signal(accelerating()))
            chosen=history.claim('worker',now=100);self.assertEqual(chosen['candidate'],'strong')
            history.complete(chosen['id'],now=101)
            self.assertEqual(history.claim('worker2',now=106)['candidate'],'quiet')
            history.close()

    def test_protection_and_earlier_deadline_precede_quality(self):
        with tempfile.TemporaryDirectory() as td,patch('meme_machine.solana_prewarm_startup.candidate_release',return_value=True):
            history=CandidateHistory(Path(td)/'work',clock=lambda:100)
            history.observe('pump','strong',surface='pumpswap',observed_at=100)
            history.volume_quality('pump','strong',self.signal(accelerating()))
            history.enqueue('pump','strong',kind='qualification',ready_at=100,deadline=120,estimate_seconds=1)
            urgent=history.enqueue('pump','urgent',kind='qualification',ready_at=100,deadline=110,estimate_seconds=1)
            protection=history.enqueue('pump','held',kind='protect',ready_at=100,deadline=125,estimate_seconds=1,priority=0)
            self.assertEqual(history.claim('protect',now=100)['id'],protection);history.complete(protection,now=101)
            self.assertEqual(history.claim('qual',now=101)['id'],urgent);history.close()

    def test_tracker_cannot_grant_capital_or_rewrite_rejected_decision(self):
        with tempfile.TemporaryDirectory() as td:
            history=CandidateHistory(Path(td)/'work',clock=lambda:100)
            history.observe('pump','mint',surface='pumpswap',observed_at=100)
            rejected=history.record_decision('pump','mint',mode='current',observed_at=99,qualified=False,decision={'reason':'creator_risk'})
            before=history.db.execute('SELECT * FROM decisions').fetchall()
            history.volume_quality('pump','mint',self.signal(accelerating()))
            with self.assertRaisesRegex(ValueError,'funding_without_qualification'):
                history.record_funding(rejected,'pump','mint',status='funded',at=100)
            self.assertEqual(history.db.execute('SELECT * FROM decisions').fetchall(),before);history.close()

    def test_pons_survivor_fair_rotation_then_attention_and_exact_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            history=PonsHistory(Path(td)/'history',policy=SURVIVOR_POLICY)
            for name in ('a-quiet','z-strong'):
                row=history.graduate(name,dict(at=0));row['volume_quality_excluded']=[]
                row['volume_quality_state']=vq.advance(None,[],lower=0,through=120,complete=True,asset='ROBINHOOD_NATIVE',authoritative=True)
                if name=='z-strong':
                    row['volume_quality_state']=vq.advance(None,[event('p'+str(i),5,'g'+str(i),10) for i in range(2)]+[event('c'+str(i),65,'g'+str(i),20) for i in range(4)],lower=0,through=120,complete=True,asset='ROBINHOOD_NATIVE',authoritative=True)
                row['through']=120;history.save(row)
                row['volume_quality']=history.volume_signal(row,120);history.save(row)
            rows=history.rows();self.assertEqual(history.qualification_turn(rows,120)['id'],'z-strong')
            self.assertEqual(history.qualification_turn(history.rows(),120)['id'],'a-quiet')
            history.close()

    def test_pons_current_material_native_recovery_uses_existing_requalification(self):
        with tempfile.TemporaryDirectory() as td:
            clock=[100.];b=Broker(Path(td)/'plane',CURRENT_POLICY,clock=lambda:clock[0])
            event1=nomination();b.enqueue(event1);work=b.pop()
            quiet=self.signal([])
            self.assertTrue(b.finish(work,dict(vector=dict(volume_quality=quiet)),.01));b.acknowledge(work)
            clock[0]=101.;b.enqueue(nomination(2));work=b.pop()
            value=self.signal(accelerating());value.update(asof=101,observed_at=101,expires_at=106)
            self.assertTrue(b.finish(work,dict(vector=dict(volume_quality=value)),.01));b.acknowledge(work)
            watch=b.plane.db.execute('SELECT next_at FROM pons_current_watch WHERE candidate=?',(work['key'],)).fetchone()
            self.assertEqual(watch[0],101)
            self.assertEqual(b.reactivate_one(),work['key'])
            next_work=b.pop();self.assertTrue(next_work['canonical_refresh'])
            self.assertGreater(next_work['work']['generation'],work['work']['generation'])
            self.assertFalse(b.plane.decision(work['key'],next_work['work']['generation'],'entry_confirmation'))
            b.close()

    def test_physical_optional_capacity_is_neutral_not_a_market_rejection(self):
        with patch.object(vq,'MAX_GROUP_CELLS',1):
            with self.assertRaisesRegex(ValueError,'aggregate_capacity'):
                self.signal(accelerating())
        neutral=vq.neutral_failure(ValueError('capacity'),at=100,asset='SOL')
        self.assertEqual(vq.attention(neutral,100),0)

    def test_actual_supervisor_forwards_only_the_two_trading_families(self):
        from meme_machine.operational.supervisor import Supervisor
        with tempfile.TemporaryDirectory() as td:
            supervisor=Supervisor.__new__(Supervisor)
            supervisor.root=Path(td);supervisor.epoch='isolated-test-epoch';supervisor.offline=True
            with patch('meme_machine.operational.supervisor.require_active'):
                for family in ('pump','pons'):
                    self.assertEqual(supervisor.environment(family)['MM_VOLUME_QUALITY_ENABLED'],'1')
                for lane in ('solana','meteora','ramses'):
                    self.assertNotIn('MM_VOLUME_QUALITY_ENABLED',supervisor.environment(lane))

    def test_known_canonical_gap_clears_current_attention_without_changing_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            history=CandidateHistory(Path(td)/'work',clock=lambda:100)
            history.observe('pump','mint',surface='pump.fun',observed_at=100)
            history.volume_quality('pump','mint',self.signal(accelerating()))
            work=history.enqueue('pump','mint',kind='qualify',ready_at=100,deadline=120,estimate_seconds=1)
            history.wait_for_history(work,'pump',10,20,retry_at=110)
            value=history.candidate('pump','mint')['metadata']['volume_quality']
            self.assertEqual(vq.attention(value,100),0)
            self.assertEqual(history.db.execute('SELECT deadline FROM work WHERE id=?',(work,)).fetchone()[0],120)
            history.close()

    def test_recovery_candidate_cannot_reuse_cached_favorable_attention(self):
        with tempfile.TemporaryDirectory() as td:
            history=PonsHistory(Path(td)/'history',policy=SURVIVOR_POLICY)
            row=history.graduate('mint',dict(at=0))
            row.update(complete=False,recovery='canonical_reorg',volume_quality=self.signal(accelerating()))
            self.assertEqual(history._quality_rank(row,100),0)
            history.close()


if __name__=='__main__':unittest.main()
