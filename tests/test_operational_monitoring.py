import copy
import json
from pathlib import Path
import tempfile
import unittest
from meme_machine.operational import monitoring

class Conditions(unittest.TestCase):
    def sample(self,now=1000):
        return dict(timestamp=now,portfolio=dict(state='CURRENT',epoch_id='paper-existing',checks={'conservation':True},positions_by_lane={}),
            host={'service':{'ActiveState':'active','NRestarts':'0'},'disks':{}},
            lanes={l:dict(reconciled=True,restarts=0) for l in ('pump','pons','meteora','ramses')},
            solana={'state':'CURRENT'},solana_provider={'state':'CURRENT','oldest_wait_seconds':0},
            robinhood_provider={'state':'CURRENT','oldest_wait_seconds':0})

    def test_no_trades_retries_rejections_or_pnl_are_not_alerts(self):
        x=self.sample();x['portfolio'].update(realized_pnl='-90',open_positions=0)
        x['solana_provider']['pressure']=[{'rate_errors':40,'cooldown_seconds':1}]
        x['lanes']['pump']['strategy_rejections']=100000
        self.assertEqual(monitoring.evaluate(x,{},'paper-existing',1000)['state'],'CURRENT')

    def test_temporary_provider_outage_is_self_healing(self):
        x=self.sample();x['robinhood_provider']['state']='UNAVAILABLE'
        first=monitoring.evaluate(x,{},'paper-existing',1000)
        self.assertFalse(first['actionable']);self.assertEqual(first['state'],'DEGRADED')
        x=self.sample(1020)
        healed=monitoring.evaluate(x,first,'paper-existing',1020)
        self.assertEqual(healed['state'],'SELF_HEALING_EVENT');self.assertFalse(healed['actionable'])

    def test_persistent_provider_failure_survives_monitor_restart(self):
        x=self.sample();x['robinhood_provider']['state']='UNAVAILABLE'
        previous=json.loads(json.dumps(monitoring.evaluate(x,{},'paper-existing',1000)))
        x['timestamp']=1301
        result=monitoring.evaluate(x,previous,'paper-existing',1301)
        self.assertIn('robinhood_provider_unavailable',result['actionable'])
        self.assertEqual(result['state'],'OWNER_ACTION_REQUIRED')

    def test_epoch_mismatch_and_reconciliation_are_fail_closed_then_actionable(self):
        x=self.sample();x['portfolio']['epoch_id']='paper-wrong';x['portfolio']['checks']['conservation']=False
        first=monitoring.evaluate(x,{},'paper-existing',1000)
        self.assertEqual(first['state'],'FAIL_CLOSED')
        x['timestamp']=1061
        result=monitoring.evaluate(x,first,'paper-existing',1061)
        self.assertIn('epoch_mismatch',result['actionable']);self.assertIn('reconciliation_failure',result['actionable'])

    def test_repeated_component_death_and_isolated_recoveries_are_distinguished(self):
        prior={}
        for n in range(6):
            x=self.sample(1000+n*15);x['lanes']['pump']['restarts']=n
            prior=monitoring.evaluate(x,prior,'paper-existing',1000+n*15)
        self.assertIn('pump_repeated_failure',prior['conditions'])
        self.assertFalse(prior['actionable'])
        x=self.sample(1400);x['lanes']['pump']['restarts']=5
        result=monitoring.evaluate(x,prior,'paper-existing',1400)
        self.assertIn('pump_repeated_failure',result['actionable'])

    def test_planned_stopped_disabled_service_does_not_alert(self):
        x=self.sample();x['host']['service']['ActiveState']='inactive'
        self.assertFalse(monitoring.evaluate(x,{},'paper-existing',1000,expect_running=False)['conditions'])

    def test_current_progress_does_not_hide_persistent_survivor_position_management_failure(self):
        x=self.sample();x['lanes']['pump']['progress_at']=1000
        x['six_regimes']={'Pump Survivor':dict(machinery=dict(accounting={'open_positions':1},
            machinery={'last_step_completed_at':600}))}
        first=monitoring.evaluate(x,{},'paper-existing',1000)
        self.assertFalse(first['actionable'])
        x['timestamp']=1301;x['lanes']['pump']['progress_at']=1301
        result=monitoring.evaluate(x,first,'paper-existing',1301)
        self.assertIn('pump_survivor_position_management_stalled',result['actionable'])
        x['six_regimes']['Pump Survivor']['machinery']['machinery']['last_step_completed_at']=1302
        x['timestamp']=1302
        self.assertFalse(monitoring.evaluate(x,result,'paper-existing',1302)['actionable'])
        x['six_regimes']['Pump Survivor']['machinery']['accounting']['open_positions']=0
        x['timestamp']=1800
        self.assertFalse(monitoring.evaluate(x,{},'paper-existing',1800)['conditions'])

    def test_published_metrics_have_no_economic_control_or_provider_payload(self):
        with tempfile.TemporaryDirectory() as td:
            x=self.sample();x['provider_url']='https://secret.invalid';row=monitoring.evaluate(x,{},'paper-existing',1000)
            monitoring.write_metrics(td,row)
            body=(Path(td)/'meme_machine.prom').read_text()
            self.assertIn('meme_machine_owner_action_required 0',body)
            self.assertNotIn('secret',body)

if __name__=='__main__':unittest.main()
