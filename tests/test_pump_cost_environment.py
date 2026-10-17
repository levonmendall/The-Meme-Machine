"""Opt-in Pump startup costs reach existing health without runtime authority.

The real Supervisor environment filter and actual nested Pump restoration run
on disposable CandidateHistory rows. No provider or live capacity is exercised.
"""
from collections import deque
from contextlib import ExitStack,closing
from contextvars import ContextVar
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.operational.supervisor import Supervisor
from meme_machine.runtime import operation_costs as costs,status,stop
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.operating_families import PausedFamily


class PumpCostEnvironmentTests(unittest.TestCase):
    def setUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ,{},clear=True))
        self.root=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        for key,value in (('_rows',costs._new_rows()),('_active',{}),('_sequence',0),
                ('_recorder_valid',True),('_recording_lost_calls',0),('_active_overflow_calls',0),
                ('_current',ContextVar('pump_cost_environment',default=None))):
            stack.enter_context(patch.object(costs,key,value))
        for key,value in (('state',dict(phase='RECONCILING',reconciled=False)),
                ('_operations',[]),('_completed',deque(maxlen=8)),('_signal',None)):
            stack.enter_context(patch.object(status,key,value))
        stack.enter_context(patch.object(stop,'requested',threading.Event()))

    def supervisor(self,*,offline=False):
        service=Supervisor(self.root,offline=offline,admission='OBSERVATION')
        service.epoch='paper-cost-environment-fixture'
        return service

    def test_only_exact_opt_in_is_forwarded_to_all_three_existing_workers(self):
        service=self.supervisor()
        for value in (None,'0','1','','true','01','1 ','2'):
            with self.subTest(parent=value):
                os.environ.pop('MM_OPERATION_COST_DIAGNOSTICS',None)
                if value is not None:os.environ['MM_OPERATION_COST_DIAGNOSTICS']=value
                children={lane:service.environment(lane) for lane in ('pump','pons','solana')}
                for lane,child in children.items():
                    self.assertEqual(child['MM_OPERATION_COST_DIAGNOSTICS'],'1' if value=='1' else '0')
                    self.assertEqual(child['MM_MODE'],'PAPER')
                    self.assertEqual(child['MM_PAPER_EPOCH'],service.epoch)
                    self.assertEqual(child['MM_RUNTIME_LANE'],lane)
                    self.assertEqual(child['MM_OPERATIONAL_PHASE'],'OBSERVATION' if lane=='solana' else 'continuous')
        self.assertFalse(self.root.joinpath('portfolio.sqlite').exists())

    def test_opt_in_preserves_provider_path_credential_and_sqlite_diagnostic_boundaries(self):
        parent=dict(MM_OPERATION_COST_DIAGNOSTICS='1',PATH='/offline/interpreter-path',
            MM_SOLANA_READ_RPC_URL='https://solana-mainnet.g.alchemy.com/v2/offline-cost',
            MM_ROBINHOOD_READ_RPC_URL='https://rpc.testnet.chain.robinhood.com',
            MM_STATE_ROOT='/never-publish-parent-state',MM_PAPER_EPOCH='never-publish-parent-epoch',
            MM_PROVIDER_USAGE_DB='/never-publish-parent-budget.sqlite',
            AWS_SECRET_ACCESS_KEY='never-publish-aws',MM_PRIVATE_KEY='never-publish-signing',
            MM_REAL_TRADING='1',MM_SQLITE_DIAGNOSTIC_REQUIRED='1',
            MM_SQLITE_TERMINAL_RECORD_PATH=str(self.root/'terminal.json'))
        with patch.dict(os.environ,parent,clear=True):
            for offline in (False,True):
                service=self.supervisor(offline=offline)
                children={lane:service.environment(lane) for lane in ('pump','pons','solana')}
                for lane,child in children.items():
                    self.assertEqual(child['MM_OPERATION_COST_DIAGNOSTICS'],'1')
                    self.assertEqual(child['PATH'],parent['PATH'])
                    self.assertEqual(child['MM_STATE_ROOT'],str(service.root))
                    self.assertEqual(child['MM_PAPER_EPOCH'],service.epoch)
                    for key in ('AWS_SECRET_ACCESS_KEY','MM_PRIVATE_KEY','MM_REAL_TRADING','MM_PROVIDER_USAGE_DB'):
                        self.assertNotIn(key,child)
                    if offline:
                        self.assertNotIn('MM_SOLANA_READ_RPC_URL',child)
                        self.assertNotIn('MM_ROBINHOOD_READ_RPC_URL',child)
                        self.assertNotIn('MM_PORTFOLIO_ACCOUNTING_DB',child)
                    else:
                        provider='MM_ROBINHOOD_READ_RPC_URL' if lane=='pons' else 'MM_SOLANA_READ_RPC_URL'
                        other='MM_SOLANA_READ_RPC_URL' if lane=='pons' else 'MM_ROBINHOOD_READ_RPC_URL'
                        self.assertEqual(child[provider],parent[provider]);self.assertNotIn(other,child)
                        self.assertEqual(child['MM_PORTFOLIO_ACCOUNTING_DB'],str(service.root/'portfolio.sqlite'))
                    if lane!='solana' or offline:
                        self.assertNotIn('MM_SQLITE_DIAGNOSTIC_REQUIRED',child)
                        self.assertNotIn('MM_SQLITE_TERMINAL_RECORD_PATH',child)
                if not offline:
                    self.assertEqual(children['solana']['MM_SQLITE_DIAGNOSTIC_REQUIRED'],'1')
                    self.assertEqual(children['solana']['MM_SQLITE_TERMINAL_RECORD_PATH'],parent['MM_SQLITE_TERMINAL_RECORD_PATH'])

    def test_diagnostic_flag_does_not_make_paused_or_unknown_lanes_runnable(self):
        os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
        for offline in (False,True):
            service=self.supervisor(offline=offline)
            for lane in ('ramses','meteora'):
                with self.subTest(offline=offline,lane=lane),self.assertRaises(PausedFamily):service.environment(lane)
            with self.assertRaisesRegex(ValueError,'unknown_runtime_lane'):service.environment('other')

    def restore(self,child):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        with patch.dict(os.environ,child,clear=True),closing(CandidateHistory(self.root/'disposable-history.sqlite')) as history:
            history.observe('pump','mint',surface='pump.fun',observed_at=1000)
            for identity,slot,kind,payload in (
                    ('create',10,'pump_create',dict(event_type='create',mint='mint',creator='never-publish-creator',market_time=1000)),
                    ('trade',11,'pump_trade',dict(event_type='trade',mint='mint',wallet='never-publish-buyer',market_time=1001,real_token_reserves=4))):
                history.append_event('pump','mint',identity=identity,slot=slot,transaction_index=0,
                    event_index=0,market_time=payload['market_time'],kind=kind,payload=payload)
            before=history.db.total_changes
            created={};postgrad={};confirmation=ConfirmationBook({'cohort':[]},1)
            with patch.object(runner,'CANDIDATE_HISTORY',history):
                restored=runner._startup_work('pump.observed_candidates_restore',runner._restore_observed_pump_candidates,
                    created,postgrad,object(),object(),confirmation,1020)
            self.assertEqual(restored,1)
            self.assertEqual(created['mint']['pregrad_wallets'],{'never-publish-buyer'})
            self.assertFalse(created['mint']['graduated']);self.assertEqual(postgrad,{})
            self.assertEqual(history.db.total_changes,before)
            return status.snapshot()

    def test_actual_pump_nested_restore_publishes_completed_cost_rows_when_child_opted_in(self):
        os.environ['MM_OPERATION_COST_DIAGNOSTICS']='1'
        snapshot=self.restore(self.supervisor().environment('pump'))
        sample=snapshot['operation_costs']
        self.assertTrue(sample['enabled']);self.assertTrue(sample['recorder_valid'])
        self.assertEqual(sample['active'],[])
        self.assertEqual(set(sample['rows']),{'pump.observed_candidates_restore','pump.observed_candidate_events'})
        outer=sample['rows']['pump.observed_candidates_restore'];inner=sample['rows']['pump.observed_candidate_events']
        self.assertEqual((outer['calls'],inner['calls'],outer['child_calls']),(1,1,1))
        self.assertEqual((outer['failed_calls'],inner['failed_calls']),(0,0))
        self.assertEqual(outer['child_unmeasured_calls'],0)
        self.assertGreater(outer['wall_seconds_total_microseconds'],0)
        self.assertGreater(inner['sql']['statement']['calls'],0)
        self.assertGreater(inner['sql']['fetch']['calls'],0)
        completed={row['operation']:row for row in snapshot['native_recent_operations']}
        self.assertTrue(all(completed[name]['state']=='COMPLETE' for name in sample['rows']))
        self.assertNotIn('native_operation',snapshot)
        self.assertEqual(snapshot['phase'],'RECONCILING');self.assertFalse(snapshot['reconciled'])
        self.assertNotIn('never-publish',json.dumps(snapshot))

    def test_default_pump_child_restores_identically_without_exposing_cost_aggregate(self):
        child=self.supervisor().environment('pump')
        self.assertEqual(child['MM_OPERATION_COST_DIAGNOSTICS'],'0')
        snapshot=self.restore(child)
        self.assertNotIn('operation_costs',snapshot)
        self.assertEqual(costs.snapshot()['rows'],{})
        self.assertEqual(snapshot['phase'],'RECONCILING');self.assertFalse(snapshot['reconciled'])
