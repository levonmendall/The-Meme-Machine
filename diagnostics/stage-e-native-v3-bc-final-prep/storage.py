"""Integer storage budgets, with no allocation/reservation/mount operation."""
from frozen import *

GIB = 1024**3
HEADROOM = 12 * GIB
TAPE = 2442975789
PARAMETERS = ('retained_A_bytes', 'retained_predecessor_bytes', 'B_raw_per_trial_bytes',
              'B_metadata_bytes', 'C_raw_bytes', 'C_pre_restart_bytes', 'C_post_restart_bytes',
              'C_failure_bytes', 'C_metadata_bytes', 'final_metadata_bytes', 'working_peak_bytes',
              'transport_chunk_metadata_bytes')


def budget_template():
    return dict(version='stage-e-native-v3-nonreserving-storage-budget',
        state='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT', immutable_tape_bytes=TAPE,
        required_headroom_bytes=HEADROOM, trials_B=6, redundant_trial_copies=1,
        final_campaign_publication_copies=1, final_bundle_copies=2,
        parameters={k: unresolved('AWAITING_A_PREFLIGHT_PHYSICAL_INPUT', 'nonnegative integer bytes: ' + k)
                    for k in PARAMETERS},
        formulas={
            'B_raw': '6 * B_raw_per_trial_bytes',
            'B_redundant': '6 * B_raw_per_trial_bytes',
            'B_campaign_publication': '6 * B_raw_per_trial_bytes + B_metadata_bytes',
            'C_raw_with_restart_failure': 'C_raw_bytes + C_pre_restart_bytes + C_post_restart_bytes + C_failure_bytes',
            'C_raw_redundant_and_campaign': '3 * C_raw_with_restart_failure + C_metadata_bytes',
            'final_bundle_one': 'retained_A_bytes + B_raw + C_raw_with_restart_failure + retained_predecessor_bytes + final_metadata_bytes',
            'total_capacity': 'tape + retained_A + retained_predecessor + 3*B_raw + B_metadata + 3*C_raw_with_restart_failure + C_metadata + 2*final_bundle_one + working_peak + transport_chunk_metadata + headroom',
            'required_new_free': 'total_capacity - tape_already_present - retained_A_already_present - retained_predecessor_already_present',
        }, free_space_rule='Compare required_new_free with current execution-time statvfs f_bavail*f_frsize, per filesystem; never sum free space across mounts',
        lower_bound_bytes=TAPE + HEADROOM,
        feasibility='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT', actual_disk_reserved=False,
        no_evidence_deleted=True, conservative_full_bundle_copies=True,
        execution_time_revalidation_required=True)


def calculate(values):
    require(type(values) is dict and set(values) == set(PARAMETERS), 'storage_parameters_incomplete')
    require(all(type(v) is int and v >= 0 for v in values.values()), 'storage_bytes_must_be_integer')
    require(all(values[k] > 0 for k in ('B_raw_per_trial_bytes', 'C_raw_bytes', 'working_peak_bytes',
                                      'B_metadata_bytes', 'C_metadata_bytes', 'final_metadata_bytes')),
            'missing_positive_working_or_publication_budget')
    b = 6 * values['B_raw_per_trial_bytes']
    c = sum(values[k] for k in ('C_raw_bytes', 'C_pre_restart_bytes', 'C_post_restart_bytes', 'C_failure_bytes'))
    final = values['retained_A_bytes'] + b + c + values['retained_predecessor_bytes'] + values['final_metadata_bytes']
    total = (TAPE + HEADROOM + values['retained_A_bytes'] + values['retained_predecessor_bytes']
             + 3*b + values['B_metadata_bytes'] + 3*c + values['C_metadata_bytes']
             + 2*final + values['working_peak_bytes'] + values['transport_chunk_metadata_bytes'])
    already = TAPE + values['retained_A_bytes'] + values['retained_predecessor_bytes']
    return dict(B_raw_bytes=b, B_redundant_bytes=b,
        B_campaign_publication_bytes=b + values['B_metadata_bytes'],
        C_one_raw_restart_failure_bytes=c, C_three_copies_bytes=3*c + values['C_metadata_bytes'],
        final_bundle_one_bytes=final, final_bundle_two_bytes=2*final,
        minimum_total_capacity_bytes=total, required_new_free_bytes=total-already,
        headroom_bytes=HEADROOM, immutable_tape_bytes=TAPE, actual_disk_reserved=False)


def feasibility(values, filesystems):
    result = calculate(values)
    require(type(filesystems) is list and filesystems, 'missing_storage_filesystems')
    for fs in filesystems:
        require(type(fs.get('free_bytes')) is int and type(fs.get('total_bytes')) is int
                and 0 <= fs['free_bytes'] <= fs['total_bytes'], 'invalid_filesystem_capacity')
    result['fits_all_declared_filesystems'] = all(
        fs['free_bytes'] >= result['required_new_free_bytes']
        and fs['total_bytes'] >= result['minimum_total_capacity_bytes'] for fs in filesystems)
    result['shortfall_by_path'] = {fs['path']: max(0, result['required_new_free_bytes']-fs['free_bytes']) for fs in filesystems}
    result['execution_time_revalidation_required'] = True
    return result


def harness_reservation_template(kind):
    require(kind in ('B', 'C'), 'storage_class')
    return dict(class_id=kind, state='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
        headroom_bytes=HEADROOM, immutable_tape_bytes=TAPE,
        working_bytes=None, publication_copy_bytes=None, retained_evidence_bytes=None,
        member_working_bytes={m['id']: None for m in workload(kind)['cohort']},
        requirements=None, actual_disk_reserved=False,
        future_predicate='approved attest.reserve_storage(snapshot, bounds); purely checks bytes, no fallocate',
        completeness_required='All nulls replaced by genuine measured inventory plus reviewed positive upper bounds before execution; samples and copies may not exceed declared bounds')
