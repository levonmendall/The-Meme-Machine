"""Recovery overlays cannot change the frozen strategy or target universe."""
from copy import deepcopy
import json
import unittest
from certification.directional_acceptance import strategy_contract,meteora_threshold_revision_is_bounded
from certification.run import git,manifest

class AutonomousPolicyPreservation(unittest.TestCase):
    def test_ramses_recovery_is_implementation_only(self):
        original=json.loads(git('show','af60b355995dfa960555288fa73808bb7aba5d25:certification/sources.json'))['lanes']['ramses']
        current=manifest()['lanes']['ramses']
        self.assertEqual(strategy_contract(current),strategy_contract(original))
        for key,value in [('policy_hash','changed'),('execution_sha','changed'),('prospect_admission',{})]:
            changed=deepcopy(current);changed[key]=value
            self.assertNotEqual(strategy_contract(changed),strategy_contract(original))
        changed=deepcopy(current);changed['composed_file_hashes']['robinhood_research/ramses_strategy.py']='changed'
        self.assertNotEqual(strategy_contract(changed),strategy_contract(original))
        changed=deepcopy(current);changed['overlay_patches'].append('unreviewed.patch')
        self.assertNotEqual(strategy_contract(changed),strategy_contract(original))

    def test_meteora_recovery_preserves_exact_approved_thresholds(self):
        prior=json.loads(git('show','48e46b27086a8058fcbd7752a42420c1f9186af7:certification/sources.json'))['lanes']['meteora']
        current=manifest()['lanes']['meteora']
        self.assertTrue(meteora_threshold_revision_is_bounded(current,prior))
        for key,value in [('policy_hash','changed'),('execution_sha','changed'),('prospect_admission',{})]:
            changed=deepcopy(current);changed[key]=value
            self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
        changed=deepcopy(current);changed['composed_file_hashes']['SOLANA_DLMM_INDEPENDENT_V1.json']='changed'
        self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
        changed=deepcopy(current);changed['overlay_patches'].append('unreviewed.patch')
        self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
