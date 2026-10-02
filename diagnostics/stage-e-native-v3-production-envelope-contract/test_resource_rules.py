"""Deterministic synthetic-claim tests only; no candidate or workload imports."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from resource_rules import (RAM_BYTES, S, T, HEADROOM_BYTES, canonical_sha256,
                            resource_claim_errors, review_blockers, capacity_claim_errors, observer_claim_errors)


def synthetic_fixture():
    # Invented unit-test values and identities; never submitted as execution evidence.
    manifest = {"fixture": "SYNTHETIC_NOT_EXECUTION_EVIDENCE",
                "runtime_dependency_identities": {"runtime": "fixture-only", "dependencies": "fixture-only"}}
    claim = {
        "allocated_vcpu": 2,
        "dedicated_vcpu": 2,
        "executor_visible_vcpu": 2,
        "effective_cpuset": [0, 1],
        "all_process_thread_affinities": [[0, 1], [0, 1]],
        "whole_executor_scope_complete": True,
        "all_ancestor_cpu_quotas": [{"quota_us": None, "period_us": 100000},
                                    {"quota_us": 200000, "period_us": 100000}],
        "ancestor_quota_inventory_complete": True,
        "allocated_ram_bytes": RAM_BYTES,
        "effective_ram_limit_bytes": RAM_BYTES,
        "dedication_and_isolation_evidence_complete": True,
        "competing_workload_present": False,
        "storage_total_bytes": 40 * 1024**3,
        "storage_free_bytes": 20 * 1024**3,
        "environment_manifest": manifest,
        "environment_manifest_sha256": canonical_sha256(manifest)
    }
    bounds = {"required_storage_bytes": 20 * 1024**3,
              "required_free_headroom_bytes": HEADROOM_BYTES}
    return claim, bounds


class ResourceRulesTests(unittest.TestCase):
    def setUp(self):
        self.claim, self.bounds = synthetic_fixture()

    def check(self, claim=None, bounds=None):
        return resource_claim_errors(self.claim if claim is None else claim,
                                     self.bounds if bounds is None else bounds)

    def test_exact_two_cpu_claim_is_structurally_eligible_only(self):
        self.assertEqual(self.check(), ())

    def test_four_cpu_executor_rejected(self):
        self.claim.update(allocated_vcpu=4, dedicated_vcpu=4, effective_cpuset=[0, 1, 2, 3],
                          all_process_thread_affinities=[[0, 1, 2, 3]])
        self.assertIn("measured executor allocation must be exactly two vCPU", self.check())

    def test_four_cpu_executor_with_two_cpu_affinity_and_quota_still_rejected(self):
        self.claim.update(allocated_vcpu=4, dedicated_vcpu=4)
        self.assertIn("measured executor allocation must be exactly two vCPU", self.check())

    def test_four_cpu_allocation_cannot_claim_only_two_dedicated(self):
        self.claim["allocated_vcpu"] = 4
        self.assertIn("measured executor allocation must be exactly two vCPU", self.check())

    def test_claim_with_escape_thread_rejected(self):
        self.claim["all_process_thread_affinities"].append([0, 1, 2, 3])
        self.assertTrue(self.check())

    def test_incomplete_process_scope_rejected(self):
        self.claim["whole_executor_scope_complete"] = False
        self.assertTrue(self.check())

    def test_one_cpu_ancestor_quota_rejected(self):
        self.claim["all_ancestor_cpu_quotas"][0]["quota_us"] = 100000
        self.assertIn("CPU quota must supply at least two full CPUs at every ancestor", self.check())

    def test_incomplete_ancestor_inventory_rejected(self):
        self.claim["ancestor_quota_inventory_complete"] = False
        self.assertTrue(self.check())

    def test_affinity_alias_duplicate_cannot_count_as_two_cpus(self):
        self.claim["effective_cpuset"] = [0, 0]
        self.assertTrue(self.check())

    def test_less_or_more_ram_cannot_substitute(self):
        for memory in (4 * 1024**3, 16 * 1024**3):
            with self.subTest(memory=memory):
                claim = deepcopy(self.claim)
                claim["allocated_ram_bytes"] = memory
                self.assertTrue(self.check(claim))

    def test_lower_cgroup_ram_limit_rejected(self):
        self.claim["effective_ram_limit_bytes"] = 4 * 1024**3
        self.assertTrue(self.check())

    def test_shared_or_competing_executor_rejected(self):
        for field, value in (("dedication_and_isolation_evidence_complete", False),
                             ("competing_workload_present", True)):
            with self.subTest(field=field):
                claim = deepcopy(self.claim)
                claim[field] = value
                self.assertTrue(self.check(claim))

    def test_missing_storage_binding_fails_closed(self):
        self.assertTrue(self.check(bounds={}))

    def test_insufficient_storage_or_headroom_rejected(self):
        for field in ("storage_total_bytes", "storage_free_bytes"):
            with self.subTest(field=field):
                claim = deepcopy(self.claim)
                claim[field] = 0
                self.assertTrue(self.check(claim))

    def test_environment_tampering_rejected(self):
        self.claim["environment_manifest"]["fixture"] = "changed"
        self.assertIn("environment manifest hash mismatch", self.check())

    def test_missing_frozen_identities_rejected(self):
        self.claim["environment_manifest"]["runtime_dependency_identities"] = {}
        self.claim["environment_manifest_sha256"] = canonical_sha256(self.claim["environment_manifest"])
        self.assertTrue(self.check())

    def test_absent_and_malformed_claims_fail_closed(self):
        for claim in (None, {}, [], {"allocated_vcpu": True}):
            with self.subTest(claim=claim):
                self.assertTrue(resource_claim_errors(claim, self.bounds))


class PaperGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent
        cls.contract = json.loads((cls.root / "contract.json").read_text())

    def test_authoritative_sources_bound_and_readiness_is_separate_from_execution(self):
        self.assertEqual(review_blockers(self.contract), ())
        self.assertTrue(self.contract['source_audit_complete'])
        unbound = deepcopy(self.contract)
        unbound['source_audit_complete'] = False
        self.assertTrue(review_blockers(unbound))

    def test_paper_validation_cannot_grant_execution_or_change_stage(self):
        self.assertFalse(self.contract["execution_authorized"])
        self.assertEqual(self.contract["stage_e"], "RED")
        self.assertEqual(self.contract["stage_f"], "NOT STARTED")
        self.assertFalse(self.contract["governance"]["static_tests_can_turn_stage_e_green"])

    def test_historical_slots_and_failure_are_preserved_by_proposal(self):
        historical = json.loads((self.root/'historical_observer_seal.json').read_text())
        self.assertEqual(historical["outcome"], "OBSERVER_V2: INVALID_PAIR")
        self.assertEqual(historical["unused_slots"], 5)
        self.assertFalse(historical["reuse_allowed"])
        self.assertEqual(historical['new_v3_slots'], [])
        self.assertFalse(self.contract['governance']['mutate_candidate'])

    def test_observer_capacity_prerequisite_and_strict_bounds(self):
        observer = json.loads((self.root/'observer_workload.json').read_text())
        self.assertIn('production-capacity-v3 PASS', observer['prerequisite'])
        self.assertEqual(observer["pair_count"], 3)
        self.assertTrue(observer['repetition_policy']['no_retry'])
        self.assertTrue(observer['no_replacements'])
        self.assertIn('numerator*100 < denominator', observer['acceptance'])

    def test_capacity_removes_only_proposed_synthetic_floors_stress_retains_values(self):
        capacity = json.loads((self.root/'production_capacity_workload.json').read_text())
        self.assertEqual(capacity['artificial_contention']['owner_seconds_per_frame'], 0)
        self.assertEqual(capacity['artificial_contention']['archive_seconds_per_thousand'], 0)
        self.assertEqual(capacity['artificial_contention']['additional_commit_latency_seconds'], 0)
        specification = json.loads((self.root/'adversarial_stress_workload.json').read_text())
        stress = specification['artificial_contention']
        self.assertEqual(stress["owner_seconds_per_frame"], 0.165)
        self.assertEqual(stress["archive_seconds_per_thousand"], 0.36)
        self.assertEqual(stress["additional_commit_latency_seconds"], 0.006)
        self.assertFalse(specification['production_minimum_cpu_inference_from_artificial_delays'])

    def test_source_bound_workloads_remain_explicitly_not_authorized(self):
        for name in ("production_capacity_workload.json", "observer_workload.json"):
            with self.subTest(name=name):
                workload = json.loads((self.root / name).read_text())
                self.assertEqual(workload['candidate_sha'], S)
                self.assertEqual(workload['candidate_tree'], T)
                self.assertFalse(workload["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
