"""Fresh paired observer contract only. This module does not benchmark."""
from .clock import finite
from .contract import HERE, read


def verify(measurement, identity):
    spec = read(HERE / 'observer-contract-v2.json')
    if not isinstance(measurement, dict) or measurement.get('contract') != spec['version']:
        raise ValueError('observer_contract_missing_or_stale')
    if measurement.get('identity') != identity or measurement.get('workload_identity') != spec['workload_identity']:
        raise ValueError('observer_identity')
    if any(measurement.get(k) != spec[k] for k in ('baseline', 'metric', 'estimator', 'repetition_policy')):
        raise ValueError('observer_measurement_definition')
    pairs = measurement.get('raw_pairs')
    if not isinstance(pairs, list) or len(pairs) != spec['repetition_policy']['pairs']:
        raise ValueError('observer_raw_pairs_missing')
    total_numerator = total_denominator = 0
    trial_ids = set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {'pair_id','baseline_ns','observed_ns','valid','same_workload_hash'}:
            raise ValueError('observer_pair_malformed')
        if not isinstance(pair['pair_id'],str) or not pair['pair_id'] or pair['pair_id'] in trial_ids:
            raise ValueError('observer_duplicate_pair')
        trial_ids.add(pair['pair_id'])
        baseline, observed = pair['baseline_ns'], pair['observed_ns']
        if (type(baseline) is not int or type(observed) is not int or baseline <= 0 or observed < baseline
                or pair['valid'] is not True or pair['same_workload_hash'] != spec['workload_identity']):
            raise ValueError('observer_pair_invalid')
        total_numerator += observed - baseline
        total_denominator += baseline
    n, d = measurement.get('numerator_ns'), measurement.get('denominator_ns')
    if type(n) is not int or type(d) is not int or n != total_numerator or d != total_denominator:
        raise ValueError('observer_missing_or_inconsistent_components')
    ratio = measurement.get('ratio')
    if not finite(ratio) or ratio != n / d or not n * 100 < d:
        raise ValueError('observer_ratio_must_be_strictly_less_than_0_01')
    return True
