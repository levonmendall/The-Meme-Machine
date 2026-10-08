"""The revised owner policy permits unknown occupancy, never missing safeguards."""
import copy
import unittest

from engineering.solana_capacity.capability_executor import validate_headroom
from engineering.solana_capacity.capability_limits import CapabilityStop


class AdmissionFirstPreflightTests(unittest.TestCase):
    def receipt(self):
        return dict(authorization_reference='owner-admission-first',
            endpoint_identity='endpoint-fingerprint', app_id='9bin99s96t7ga5e9',
            credential_app_binding_verified=True, headroom_verified=False,
            production_changes_required=False, checked_at=1000, expires_at=1300,
            admission_policy='OWNER_AUTHORIZED_ADMISSION_FIRST',
            external_yellowstone_occupancy='UNKNOWN', unknown_external_occupancy_accepted=True,
            paper_stopped_verified=True, known_competing_workloads_clear=True,
            existing_shared_governor_verified=True, resource_protections_verified=True,
            additional_experiment_topology=dict(native_channels=1, native_subscribe_rpcs=3,
                websocket_connections=1, websocket_subscriptions=2, candidate_filters=5))

    def check(self, receipt, *, authorization='owner-admission-first', now=1100):
        return validate_headroom(receipt, 'endpoint-fingerprint', authorization, now=lambda: now)

    def test_explicit_policy_accepts_unknown_without_relabeling_it_verified(self):
        receipt = self.receipt()
        original = copy.deepcopy(receipt)
        self.check(receipt)
        self.assertEqual(receipt, original)
        self.assertFalse(receipt['headroom_verified'])

    def test_missing_owner_policy_or_any_local_safeguard_blocks(self):
        receipt = self.receipt()
        for key in ('admission_policy', 'external_yellowstone_occupancy',
                    'unknown_external_occupancy_accepted', 'paper_stopped_verified',
                    'known_competing_workloads_clear', 'existing_shared_governor_verified',
                    'resource_protections_verified', 'credential_app_binding_verified'):
            with self.subTest(key=key):
                changed = dict(receipt)
                changed.pop(key)
                with self.assertRaises(CapabilityStop):
                    self.check(changed)

    def test_topology_identity_time_and_production_constraints_still_block(self):
        for changes in ({'app_id': 'other-app'}, {'endpoint_identity': 'wrong'},
                        {'production_changes_required': True}, {'expires_at': 1100},
                        {'checked_at': 1101}, {'expires_at': 1301},
                        {'additional_experiment_topology': dict(self.receipt()['additional_experiment_topology'], native_subscribe_rpcs=4)}):
            with self.subTest(changes=changes), self.assertRaises(CapabilityStop):
                self.check(dict(self.receipt(), **changes))
        with self.assertRaises(CapabilityStop):
            self.check(self.receipt(), authorization='another-owner-reference')

    def test_plain_unverified_receipt_remains_rejected(self):
        receipt = self.receipt()
        receipt.pop('admission_policy')
        with self.assertRaisesRegex(CapabilityStop, 'current_account_headroom_required'):
            self.check(receipt)


if __name__ == '__main__':
    unittest.main()
