"""Recovery overlays cannot change the frozen strategy or target universe."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import unittest
from certification.directional_acceptance import strategy_contract,meteora_threshold_revision_is_bounded
from certification.run import manifest

def baseline(lane):
    path=Path(__file__).parent/'fixtures/autonomous-policy-baselines.json'
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='e88254d5d9caedea414f1bc6759e1f98b896603cb7b318f78b45b6fa8aef9b77':
        raise ValueError('historical_policy_baseline_identity')
    return json.loads(raw)[lane]['row']

class AutonomousPolicyPreservation(unittest.TestCase):
    def test_ramses_recovery_is_implementation_only(self):
        original=baseline('ramses')
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
        prior=baseline('meteora')
        current=manifest()['lanes']['meteora']
        self.assertTrue(meteora_threshold_revision_is_bounded(current,prior))
        for key,value in [('policy_hash','changed'),('execution_sha','changed'),('prospect_admission',{})]:
            changed=deepcopy(current);changed[key]=value
            self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
        changed=deepcopy(current);changed['composed_file_hashes']['SOLANA_DLMM_INDEPENDENT_V1.json']='changed'
        self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
        changed=deepcopy(current);changed['overlay_patches'].append('unreviewed.patch')
        self.assertFalse(meteora_threshold_revision_is_bounded(changed,prior))
