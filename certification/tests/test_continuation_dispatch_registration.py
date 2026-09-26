"""Offline regressions for run 36043064083's unregistered workflow and authority."""
from copy import deepcopy
import os
import unittest
from unittest.mock import patch

from certification import single_campaign_control as control
from certification.tests.test_single_campaign_control import API, SHA, REF


class ContinuationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ, {'SINGLE_AUTHORIZATION_ID': 'unit-continuation-authority-v2'}, clear=False)
        self.env_patch.start(); self.addCleanup(self.env_patch.stop)
        self.config = control.configuration()
        self.identity = {'integration_sha': SHA, 'implementation_hash': 'frozen'}
        self.parent = dict(identity=self.identity, workflow_run_id=22,
            runtime_ref=REF, phase='POSITION_CONTINUATION', continuation_allowed=True,
            phase_records={'hourly': {'native_positions': {'meteora': dict(
                open_positions=1, accounting_reconciled=True, durable_handoff=True)}}})
        self.chain = None
        self.api = API()
        self.api.detail[23] = dict(head_sha=SHA, head_branch=REF, run_attempt=1,
            event='workflow_dispatch', path='.github/workflows/position-continuation.yml')
        test = self
        class ParentStore:
            def __init__(self, *args, **kwargs): pass
            def read(self): return deepcopy(test.parent)
        class ChainStore:
            def read(self): return deepcopy(test.chain)
            def write(self, value): test.chain = deepcopy(value)
        self.chain_store = ChainStore()
        for context in (patch.object(control, 'StateStore', ParentStore),
                        patch.object(control, 'continuation_store', return_value=self.chain_store)):
            context.start(); self.addCleanup(context.stop)

    def claim(self, **overrides):
        args = dict(api=self.api, config=self.config, identity=self.identity, lane='meteora',
                    campaign_run_id=22, state_run_id=22, run_id=23, attempt=1)
        args.update(overrides)
        return control.continuation_claim(**args)

    def test_duplicate_claim_is_rejected_before_any_position_work(self):
        self.claim()
        with self.assertRaisesRegex(ValueError, 'chain_identity'): self.claim()
        self.assertEqual(len(self.chain['history']), 1)

    def test_source_campaign_lane_and_attempt_cannot_be_replayed(self):
        for change in ({'campaign_run_id': 21}, {'state_run_id': 21}, {'lane': 'ramses'},
                       {'lane': 'pump'}, {'attempt': 2},
                       {'identity': dict(self.identity, integration_sha='b'*40)}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.claim(**change)
        self.assertIsNone(self.chain)

    def test_continuation_must_match_exact_workflow_sha_ref_and_event(self):
        original = deepcopy(self.api.detail[23])
        for key, value in [('head_sha','b'*40), ('head_branch','main'), ('run_attempt',2),
                           ('event','push'), ('path',control.MARKET_WORKFLOW)]:
            self.api.detail[23] = dict(original, **{key:value})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'run_identity'): self.claim()
        self.assertIsNone(self.chain)

    def test_stale_artifact_after_successful_slice_is_rejected(self):
        self.claim()
        control.continuation_record(self.api,self.config,self.identity,'meteora',22,23,
            dict(lane='meteora', assurance_passed=True, handoff_required=True),'success')
        with self.assertRaisesRegex(ValueError,'chain_identity'): self.claim(state_run_id=22)
        self.assertEqual(self.chain['last_state_run_id'],23)

    def test_authorization_and_terminal_chain_cannot_be_reused(self):
        self.claim()
        for key,value in [('authorization_sha256','other'),('campaign_run_id',21),
                          ('lane','ramses'),('status','SETTLED'),('status','HALTED_UNRESOLVED')]:
            self.chain.update(status='OPEN',authorization_sha256=control.digest(self.config),
                              campaign_run_id=22,lane='meteora')
            self.chain[key]=value
            with self.subTest(key=key,value=value), self.assertRaisesRegex(ValueError,'chain_identity'): self.claim()

    def test_native_position_must_be_durable_reconciled_and_known(self):
        row=self.parent['phase_records']['hourly']['native_positions']['meteora']
        for key,value in [('open_positions',0),('open_positions',2),('open_positions_unknown',True),
                          ('accounting_reconciled',False),('durable_handoff',False)]:
            original=deepcopy(row); row[key]=value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'position_not_authorized'): self.claim()
            row.clear();row.update(original)

    def test_no_claim_from_new_discovery_or_terminal_campaign_state(self):
        for phase in ('CLAIMED','DISPATCH_COMMITTED','HALTED','HALTED_UNRESOLVED'):
            self.parent['phase']=phase
            with self.subTest(phase=phase),self.assertRaisesRegex(ValueError,'parent_state'): self.claim()

    def test_no_authority_for_successor_replacement_entry_or_live_money(self):
        for action in ('discovery','qualification','entry','retry','replacement','successor','live_money'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'prohibits_'):
                control.prohibit_if_enabled(action)
        self.assertFalse(self.config['live_money'])
        self.assertFalse(self.config['workflow_reruns'])
        self.assertFalse(self.config['automatic_successors'])
        self.assertFalse(self.config['dispatch_retries'])


class RegistrationTests(unittest.TestCase):
    def test_original_404_has_registration_without_position_execution(self):
        # GitHub registers the same workflow path on its first push execution.
        # No runtime code/default-branch promotion or actual dispatch is needed.
        workflow=(control.ROOT/'.github/workflows/position-continuation.yml').read_text()
        triggers=workflow.split('jobs:',1)[0]
        self.assertIn('push:',triggers)
        self.assertIn('branches: [repair/v9-position-continuation-dispatch-20260924]',triggers)
        registration=workflow.split('  registration:',1)[1].split('  resume:',1)[0]
        self.assertIn("if: github.event_name == 'push'",registration)
        self.assertIn('contents: read',registration)
        for forbidden in ('checkout@','GH_TOKEN','secrets.','workflow run','python','uses:'):
            self.assertNotIn(forbidden,registration)
        resume=workflow.split('  resume:',1)[1]
        self.assertTrue(resume.lstrip().startswith("if: github.event_name != 'push'"))
        self.assertIn("always() && github.event_name != 'push' && inputs.program == true",workflow)

    def test_nonmarket_wrapper_cannot_dispatch_a_position(self):
        workflow=(control.ROOT/'.github/workflows/continuation-dispatch-nonmarket-certification.yml').read_text()
        self.assertIn('uses: ./.github/workflows/non-market-certification.yml',workflow)
        self.assertNotIn('actions: write',workflow)
        self.assertNotIn('workflow run',workflow)
        self.assertNotIn('dispatches',workflow)
