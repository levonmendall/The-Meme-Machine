"""Pure paper-contract checks. Never probe resources or run a workload.

Checking a synthetic resource claim is not capacity certification, native
verification, environmental attestation, or a Stage-E acceptance result.
Storage numbers passed here must already be frozen by the source-grounded
contract; this draft cannot choose them on behalf of an absent predecessor.
"""

from fractions import Fraction
from hashlib import sha256
import json


RAM_BYTES = 8 * 1024**3
S = '7a516a6a92be9347661ac0e7f560971c171a0931'
T = '9da7d1e1625ba04c1437c63606c90f5e293bdba7'
HEADROOM_BYTES = 12 * 1024**3


def canonical_sha256(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _two_ids(value):
    return (type(value) is list and len(value) == 2
            and all(_integer(item) for item in value)
            and len(set(value)) == 2)


def resource_claim_errors(claim, storage_bounds):
    """Return static rule violations, never a capacity PASS.

    CPU counts describe the dedicated measured executor allocation, not a
    hypervisor host. Every observed child/thread must share the two-CPU scope.
    Quota entries contain all effective ancestor constraints; null denotes
    unlimited quota. Real admission also needs trusted evidence and repeated
    verification of this claim, which this source-independent checker cannot
    supply.
    """
    errors = []
    if type(claim) is not dict or type(storage_bounds) is not dict:
        return ("malformed claim or storage bounds",)
    if type(claim.get("allocated_vcpu")) is not int or claim["allocated_vcpu"] != 2:
        errors.append("measured executor allocation must be exactly two vCPU")
    if type(claim.get("dedicated_vcpu")) is not int or claim["dedicated_vcpu"] != 2:
        errors.append("exactly two dedicated vCPU must be bound")
    if type(claim.get('executor_visible_vcpu')) is not int or claim['executor_visible_vcpu'] != 2:
        errors.append('measured executor visible CPU inventory must be exactly two vCPU')
    cpu_ids = claim.get("effective_cpuset")
    if not _two_ids(cpu_ids):
        errors.append("effective cpuset must contain exactly two distinct CPUs")
    affinity = claim.get("all_process_thread_affinities")
    if (type(affinity) is not list or not affinity
            or not _two_ids(cpu_ids)
            or any(not _two_ids(ids) or set(ids) != set(cpu_ids) for ids in affinity)):
        errors.append("every measured process/thread must be confined to the same two full CPUs")
    if claim.get("whole_executor_scope_complete") is not True:
        errors.append("whole measured executor scope must be complete")
    quotas = claim.get("all_ancestor_cpu_quotas")
    if type(quotas) is not list or not quotas or claim.get("ancestor_quota_inventory_complete") is not True:
        errors.append("complete ancestor quota inventory required")
    else:
        for quota in quotas:
            if (type(quota) is not dict or "quota_us" not in quota
                    or not _integer(quota.get("period_us"), 1)):
                errors.append("malformed CPU quota")
            elif quota["quota_us"] is not None:
                if (not _integer(quota["quota_us"], 1)
                        or Fraction(quota["quota_us"], quota["period_us"]) < 2):
                    errors.append("CPU quota must supply at least two full CPUs at every ancestor")
    if type(claim.get('allocated_ram_bytes')) is not int or claim['allocated_ram_bytes'] != RAM_BYTES:
        errors.append('allocated_ram_bytes must be exactly eight GiB')
    if 'effective_ram_limit_bytes' not in claim:
        errors.append('complete effective memory limit required')
    elif claim['effective_ram_limit_bytes'] is not None and (
            type(claim['effective_ram_limit_bytes']) is not int or claim['effective_ram_limit_bytes'] != RAM_BYTES):
        errors.append('effective_ram_limit_bytes must be exactly eight GiB or unlimited within attested allocation')
    if claim.get("dedication_and_isolation_evidence_complete") is not True:
        errors.append("dedication and isolation evidence required")
    if claim.get("competing_workload_present") is not False:
        errors.append("no competing workload allowed")
    for field in ("required_storage_bytes", "required_free_headroom_bytes"):
        if not _integer(storage_bounds.get(field), 1):
            errors.append(field + " must be source-bound before admission")
    if storage_bounds.get('required_free_headroom_bytes') != HEADROOM_BYTES:
        errors.append('frozen twelve-GiB member headroom cannot be reduced')
    for field, requirement in (("storage_total_bytes", "required_storage_bytes"),
                               ("storage_free_bytes", "required_free_headroom_bytes")):
        actual, required = claim.get(field), storage_bounds.get(requirement)
        if not _integer(actual) or (_integer(required, 1) and actual < required):
            errors.append(field + " does not meet frozen storage/headroom requirements")
    if (_integer(claim.get("storage_total_bytes")) and _integer(claim.get("storage_free_bytes"))
            and claim["storage_free_bytes"] > claim["storage_total_bytes"]):
        errors.append("free storage cannot exceed total storage")
    manifest = claim.get("environment_manifest")
    if type(manifest) is not dict or not manifest:
        errors.append("environment manifest required")
    else:
        identities = manifest.get("runtime_dependency_identities")
        if type(identities) is not dict or not identities:
            errors.append("frozen runtime/dependency identities required")
        try:
            if claim.get("environment_manifest_sha256") != canonical_sha256(manifest):
                errors.append("environment manifest hash mismatch")
        except (TypeError, ValueError):
            errors.append("environment manifest is not canonical JSON")
    return tuple(errors)


def review_blockers(contract):
    """Source readiness predicates only; execution remains separately prohibited."""
    blockers = list(contract.get("unresolved_source_bindings", []))
    if contract.get('candidate_sha') != S or contract.get('candidate_tree') != T:
        blockers.append('wrong candidate S/T')
    if contract.get('source_audit_complete') is not True:
        blockers.append('source audit incomplete')
    for name in ('gate_map', 'safety_ledger', 'policy_proof', 'history_seal', 'source_identities'):
        if not contract.get(name):
            blockers.append('missing ' + name)
    if contract.get('execution_authorized') is not False:
        blockers.append('paper contract must not authorize execution')
    return tuple(blockers)


def capacity_claim_errors(claim, storage_bounds, evidence, expected_workload_hash):
    """Necessary structural acceptance predicates, never native attestation.

    Future admission must independently verify authentic resource/native receipts,
    origins, archive/lineage/durability and source bytes. This pure checker tests
    that even nominally passing evidence cannot bypass the two-CPU requirement.
    """
    import math
    errors = list(resource_claim_errors(claim, storage_bounds))
    if type(evidence) is not dict:
        return tuple(errors + ['missing native capacity evidence'])
    if evidence.get('candidate_sha') != S or evidence.get('candidate_tree') != T:
        errors.append('capacity exact S/T required')
    if evidence.get('workload_hash') != expected_workload_hash:
        errors.append('capacity workload binding differs')
    if evidence.get('native_verified') is not True or evidence.get('passed') is not True:
        errors.append('native capacity validation did not pass')
    if evidence.get('source_frames') != [2223, 2223, 2223, 4445]:
        errors.append('complete four-member capacity cohort required')
    if evidence.get('provider_attempts') != []:
        errors.append('provider attempted access')
    if evidence.get('environment_hash') != claim.get('environment_manifest_sha256'):
        errors.append('capacity environment binding differs')
    for key, limit in (('source_lag_peak', 45), ('hot_age_peak', 240),
                       ('retained_age_peak', 240), ('hot_db_wal_peak', 2 * 1024**3)):
        value = evidence.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < limit:
            errors.append(key + ' must satisfy unchanged strict bound')
    if evidence.get('integrity') != 'ok' or evidence.get('unresolved_runtime_gaps') != 0:
        errors.append('integrity or gaps invalid')
    if evidence.get('synthetic_floor_seconds') != {'owner': 0, 'archive': 0, 'commit': 0}:
        errors.append('capacity cannot contain synthetic normalization floors')
    return tuple(errors)


def observer_claim_errors(measurement, capacity_errors, expected_workload_hash, expected_environment_hash):
    """v2 integer/order/validity semantics plus v3 bindings; pure fixture checker."""
    import math
    errors = []
    if capacity_errors:
        return ('baseline production capacity blocks observer measurement',)
    if type(measurement) is not dict:
        return ('observer measurement missing',)
    if not str(measurement.get('execution_key', '')).startswith('stage-e-native-v3-observer-'):
        errors.append('fresh v3 campaign identity required; historical slots forbidden')
    if measurement.get('candidate_sha') != S or measurement.get('candidate_tree') != T:
        errors.append('observer exact S/T required')
    if measurement.get('modes') != ['baseline', 'observed', 'observed', 'baseline', 'baseline', 'observed']:
        errors.append('observer arm ordering differs')
    if measurement.get('retries') != 0 or measurement.get('replacements') != 0:
        errors.append('observer retries/replacements forbidden')
    pairs = measurement.get('raw_pairs')
    if type(pairs) is not list or len(pairs) != 3:
        return tuple(errors + ['three complete valid pairs required'])
    numerator = denominator = 0
    seen = set()
    for pair in pairs:
        if type(pair) is not dict:
            errors.append('malformed pair')
            continue
        name = pair.get('pair_id')
        if type(name) is not str or not name or name in seen:
            errors.append('unique pair identity required')
        else:
            seen.add(name)
        baseline, observed = pair.get('baseline_ns'), pair.get('observed_ns')
        if type(baseline) is not int or type(observed) is not int or baseline <= 0 or observed < baseline:
            errors.append('positive baseline and nonnegative v2 increment required')
            continue
        if pair.get('valid') is not True or pair.get('both_arms_capacity_valid') is not True:
            errors.append('all pairs and both arms must be capacity valid')
        if pair.get('workload_hash') != expected_workload_hash or pair.get('environment_hash') != expected_environment_hash:
            errors.append('exact equal-workload/environment pair binding required')
        numerator += observed - baseline
        denominator += baseline
    if (type(measurement.get('numerator_ns')) is not int or type(measurement.get('denominator_ns')) is not int
            or measurement['numerator_ns'] != numerator or measurement['denominator_ns'] != denominator):
        errors.append('inconsistent summed components')
    if denominator <= 0 or not numerator * 100 < denominator:
        errors.append('observer overhead must be strictly less than one percent')
    ratio = measurement.get('ratio')
    if (type(ratio) not in (int, float) or not math.isfinite(ratio)
            or denominator <= 0 or ratio != numerator / denominator):
        errors.append('missing or inconsistent native ratio')
    return tuple(errors)
