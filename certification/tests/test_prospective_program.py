import copy
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

from certification import prospective_program as program
from certification.tests import test_prospective_acceptance as fixtures


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.proto,_=program.protocol()
        self.state=program.initial_state('same',1,self.proto,'p',1000)
        self.state.update(phase='RUNNING',current_workflow_run_id=22)
        self.row=fixtures.ProspectiveAcceptanceTests()._record(self.proto,'native',1000,
            {lane:-.01 for lane in program.LANES})
        self.row['workflow_run_id']=22

    def reduce(self,row=None,state=None,event='base',reviewed=True):
        return program.reduce_record(state or self.state,row or self.row,event,self.proto,'p',5000,reviewed)

    def test_losing_completed_block_is_kept_and_schedules_same_frozen_strategy(self):
        state=self.reduce()
        self.assertEqual(state['phase'],'READY')
        self.assertEqual(state['evaluation']['lanes']['pump']['block_returns'],[-.01])
        self.assertFalse(state['evaluation']['promotion_eligible'])
        self.assertEqual(self.reduce(state=state),state)
        changed=copy.deepcopy(self.row);changed['lanes']['pump']['natural_settled']=2
        with self.assertRaisesRegex(ValueError,'conflicting_event'):self.reduce(changed,state)

    def test_identity_failure_cannot_advance_state(self):
        for field,value in [('integration_sha','foreign'),('workflow_run_id',23),('protocol_sha256','wrong')]:
            row=copy.deepcopy(self.row);row[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.reduce(row)
        self.assertEqual(self.state['records'],[])

    def test_excess_infrastructure_censoring_halts_without_discarding_block(self):
        row=copy.deepcopy(self.row);row['lanes']['ramses']['infrastructure_censoring_fraction']=1.0
        state=self.reduce(row)
        self.assertEqual(state['phase'],'HALTED');self.assertEqual(state['records'],[row])

    def test_lane_sample_completion_cannot_hide_incomplete_portfolio_sample(self):
        evaluation={'lanes':{lane:{'quality_checks':{'complete':True}} for lane in program.LANES},
                    'portfolio':{'complete_blocks':24,'calendar_span_hours':168,
                                 'correlations':{'pump__pons':{'joint_nonzero_blocks':8}}}}
        with patch.object(program,'evaluate',return_value=evaluation):
            self.assertEqual(self.reduce()['phase'],'READY')
            evaluation['portfolio']['correlations']['pump__pons']['joint_nonzero_blocks']=12
            self.assertEqual(self.reduce()['phase'],'EVALUATED')

    def test_retirement_never_cancels_an_active_market_block(self):
        run={'status':'in_progress'};jobs=[{'name':'concurrent-smoke','conclusion':'success'}]
        self.assertEqual(program.retirement_action(run,jobs),'cancel_before_new_admission')
        jobs.append({'name':'hourly-campaign','steps':[{'name':'One-hour continuous paper campaign, no process restart',
                                                     'status':'in_progress'}]})
        self.assertEqual(program.retirement_action(run,jobs),'wait_existing_campaign')
        run['status']='completed'
        self.assertEqual(program.retirement_action(run,jobs),'verify_terminal')

    def test_engineering_failure_halts_and_preserves_even_later_terminal_amendment(self):
        row=copy.deepcopy(self.row);row['lanes']['pump']['accounting_reconciled']=False
        state=self.reduce(row)
        self.assertEqual(state['phase'],'HALTED')
        fixed=copy.deepcopy(row);fixed['lanes']['pump']['accounting_reconciled']=True
        state=self.reduce(fixed,state,'later')
        self.assertEqual(state['phase'],'HALTED');self.assertEqual(len(state['records']),2)

    def test_amendment_before_original_review_never_dispatches(self):
        amended=copy.deepcopy(self.row)
        amended['continuation_updates']={'meteora':{'finalized_at':4000,'terminal_replay_verified':True}}
        state=self.reduce(amended,event='terminal',reviewed=False)
        self.assertEqual(state['phase'],'AWAITING_BASE_REVIEW')
        state=self.reduce(state=state)
        self.assertEqual(state['phase'],'READY');self.assertEqual(len(program.merge_records(state['records'])),1)

    def test_open_position_waits_for_verified_native_terminal(self):
        row=copy.deepcopy(self.row)
        row['lanes']['meteora'].update(durable_replay=False,durable_handoff=True,native_accounting_replay=True)
        row['lanes']['meteora']['economics']['flat']=False
        state=self.reduce(row);self.assertEqual(state['phase'],'CONTINUING')
        self.assertEqual(state['pending_lanes'],['meteora'])
        row['lanes']['meteora']['native_accounting_replay']=False
        self.assertEqual(self.reduce(row)['phase'],'HALTED')

    def test_directional_survivor_requires_verified_handoff_before_continuation(self):
        for lane in ('pump','pons'):
            row=copy.deepcopy(self.row)
            row['lanes'][lane].update(durable_replay=False,durable_handoff=True,
                native_accounting_replay=True,position_handoff_verified=True)
            row['lanes'][lane]['economics']['flat']=False
            state=self.reduce(row)
            self.assertEqual(state['phase'],'CONTINUING');self.assertEqual(state['pending_lanes'],[lane])
            row['lanes'][lane]['position_handoff_verified']=False
            self.assertEqual(self.reduce(row)['phase'],'HALTED')

    def test_racing_state_commit_reloads_without_losing_other_event(self):
        memory={'head':'a','state':self.state,'race':True}
        class Store:
            def __init__(s,*args):s.head=None
            def read(s):s.head=memory['head'];return copy.deepcopy(memory['state'])
            def write(s,state):
                if memory['race']:
                    memory['race']=False;memory['head']='b'
                    memory['state']['history'].append({'action':'concurrent-event'})
                    raise HTTPError('fixture',422,'non-fast-forward',{},None)
                memory['head']='c';memory['state']=copy.deepcopy(state);s.head='c'
        with patch.object(program,'StateStore',Store),patch.object(program.time,'sleep'):
            state,changed=program.commit_transition(None,self.proto,'same','p',
                lambda s:self.reduce(state=s))
        self.assertTrue(changed);self.assertEqual(state['history'][0]['action'],'concurrent-event')

    def test_ambiguous_dispatch_is_durable_and_not_retried(self):
        state=self.reduce();memory={'state':state}
        class Store:
            def __init__(s,*args):s.head='a'
            def read(s):return copy.deepcopy(memory['state'])
            def write(s,state):memory['state']=copy.deepcopy(state)
        class API:
            posts=0
            def request(s,method,path,body=None):
                if method=='GET':return {'object':{'sha':'same'}}
                s.posts+=1;raise TimeoutError('ambiguous dispatch response')
        api=API()
        with patch.object(program,'StateStore',Store), \
             patch('certification.single_campaign_control.prohibit_if_enabled'):
            with self.assertRaises(TimeoutError):program.dispatch(api,self.proto,'same','p')
            self.assertEqual(memory['state']['phase'],'DISPATCH_PENDING')
            program.dispatch(api,self.proto,'same','p')
        self.assertEqual(api.posts,1)

    def test_full_certificate_requires_successful_job_and_exact_artifact_identities(self):
        manifest={'lanes':{lane:{'source_diff_sha256':lane} for lane in program.LANES}}
        sha='same';offline=dict(passed=True,integration_sha=sha,source_manifest_hash=program.digest(manifest),
                              source_diff_hashes={lane:lane for lane in program.LANES})
        final=dict(passed=True,integration_sha=sha,gates={'all_required':True})
        class API:
            job='success'
            def request(s,*args):return {'head_sha':sha,'run_attempt':1}
            def pages(s,*args):return [{'name':'certify / offline-prerequisites','conclusion':s.job}]
            def artifact(s,*args):
                data=io.BytesIO()
                with zipfile.ZipFile(data,'w') as z:
                    z.writestr('final-acceptance.json',json.dumps(final));z.writestr('offline/result.json',json.dumps(offline))
                return zipfile.ZipFile(data),{'id':33,'digest':'sha256:fixture'}
        api=API()
        with patch.object(program,'manifest',return_value=manifest),patch.object(program,'implementation_hash',return_value='impl'):
            self.assertTrue(program.certificate(api,1,sha)['passed'])
            api.job='skipped'
            with self.assertRaisesRegex(ValueError,'full_nonmarket'):program.certificate(api,1,sha)
            api.job='success';final['gates']['all_required']=False
            with self.assertRaisesRegex(ValueError,'identity_or_gate'):program.certificate(api,1,sha)


if __name__=='__main__':unittest.main()
