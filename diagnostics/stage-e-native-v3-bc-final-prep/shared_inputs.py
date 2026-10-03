"""Ingest published A-preflight receipts. Never opens the production tape/mount.

Imported receipts establish preparation bindings only. Fresh execution-time
physical hashing/continuity/admission stays in the approved executable.
"""
from copy import deepcopy
import re

from frozen import *
from storage import feasibility, PARAMETERS

AWAITING = 'AWAITING_A_PREFLIGHT_PHYSICAL_INPUT'
RECEIPTS = ('declaration', 'tape_verification', 'frame_inventory', 'tape_continuity',
            'storage_initial', 'storage_final', 'storage_budget', 'storage_reserve',
            'filesystem_durability', 'signed_allocation', 'runtime')


def template():
    tape = workload('A')['tape_binding']
    return dict(version='stage-e-native-v3-deferred-shared-input-receipt', **FROZEN,
        state=AWAITING, verified=False,
        expected=dict(physical_bytes=tape['physical_bytes'], physical_sha256=tape['physical_sha256'],
            frame_inventory_sha256=tape['frame_inventory_sha256'],
            prefix_2223={k: tape['members'][0][k] for k in (
                'frames', 'encoded_prefix_bytes', 'encoded_prefix_sha256', 'decoded_canonical_sha256')},
            decoded_4445=tape['members'][-1]['decoded_canonical_sha256']),
        tape_path=unresolved(AWAITING, 'exact published A tape path'),
        tape_stat=unresolved(AWAITING, 'device/inode/size/mtime_ns/ctime_ns/mode before and after hashing'),
        inventory_identity=unresolved(AWAITING, 'path/device/inode/size/mtime_ns/SHA-256'),
        production_storage=unresolved(AWAITING, 'statvfs/mount/device/durability and reserve inputs'),
        bindings={k: unresolved(AWAITING, 'manifest-listed path and exact raw SHA-256: ' + k) for k in RECEIPTS},
        requires_completed_published_A_preflight=True,
        physical_bytes_rehashed_by_this_prep=False, substitutes_execution_time_checks=False,
        production_volume_accessed=False, tape_generated=False, tape_copied=False,
        source_frames_released=0, capacity_credit=False, observer_credit=False)


def artifact(root, ref):
    require(type(ref) is dict and set(ref) == {'path', 'sha256'}
            and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']), 'raw_receipt_path_hash_required')
    p = relative(root, ref['path'])
    require(p.is_file() and file_sha(p) == ref['sha256'], 'raw_receipt_bytes_changed:' + ref['path'])
    return p


def check_stat(row):
    require(type(row) is dict and set(row) == {'device', 'inode', 'size', 'mtime_ns', 'ctime_ns', 'mode'},
            'complete_physical_stat_required')
    require(all(type(v) is int and v >= 0 for v in row.values()) and row['inode'] > 0,
            'invalid_physical_stat')


def published_capabilities(root, allocation):
    """Resolve signed original paths by exact SHA/name in preserved bytes.

    No production path is opened. This accepts the unchanged A-preflight
    STORAGE_BUDGET_DERIVATION schema, which has no invented capability map.
    Multiple exact copies may exist; their bytes must all agree with the signed
    receipt and the selected file must be inside the verified published root.
    """
    root = Path(root).resolve()
    files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
    result = {}
    for receipt in allocation['allocation_evidence']:
        require(set(receipt) == {'path', 'sha256'} and receipt['path'] not in result,
                'preflight_duplicate_or_malformed_capability')
        candidates = [p for p in files if p.name == Path(receipt['path']).name
                      and file_sha(p) == receipt['sha256']]
        require(candidates, 'preflight_published_signed_capability_missing')
        result[receipt['path']] = str(sorted(candidates)[0])
    require(result, 'preflight_capability_inventory_incomplete')
    return result


def validate_receipts(root, bindings, *, expected_executor, expected_environment_sha256, budget_values,
                      allocation_key):
    require(type(bindings) is dict and set(bindings) == set(RECEIPTS), AWAITING)
    paths = {name: artifact(root, ref) for name, ref in bindings.items()}
    d = read(paths['declaration'])
    require(d.get('class_id') == 'A' and d.get('approved_executable_commit', d.get('executable_commit')) == EXECUTABLE_COMMIT
            and all(d.get(k) == v for k, v in FROZEN.items() if k in (
                'candidate_sha', 'candidate_tree', 'assembly_digest', 'contract_commit', 'contract_manifest_sha256')),
            'preflight_source_identity_changed')
    require(d['infrastructure'] == infrastructure_identity()
            and all(d['executor'][k] == expected_executor[k] for k in ('executor_id', 'hostname', 'boot_id'))
            and d['environment_sha256'] == expected_environment_sha256 == sha(canonical(d['environment'])),
            'preflight_executor_environment_changed')
    b = workload('A')['tape_binding']; require(d['tape_binding'] == b, 'preflight_tape_binding_changed')
    v = read(paths['tape_verification'])
    require(v.get('version') == 'v3-existing-tape-validation' and v.get('valid') is True
            and v.get('path') == d['paths']['tape'] and v.get('frames_validated') == 4445
            and v.get('physical_sha256') == b['physical_sha256']
            and v.get('frame_inventory_sha256') == b['frame_inventory_sha256']
            and v.get('binding_sha256') == sha(canonical(b))
            and v.get('no_regeneration') is True and v.get('source_frames_released') == 0,
            'preflight_tape_receipt_incomplete_or_wrong')
    for count in (2223, 4445):
        member = next(m for m in b['members'] if m['frames'] == count)
        expected = {k: member[k] for k in ('frames', 'encoded_prefix_bytes', 'encoded_prefix_sha256', 'decoded_canonical_sha256')}
        require(v['checkpoints'][str(count)] == expected, 'prefix_or_decoded_canonical_identity_changed')
    require(file_sha(paths['frame_inventory']) == b['frame_inventory_sha256'], 'published_frame_inventory_changed')
    frames = read(paths['frame_inventory'])
    require(type(frames) is list and len(frames) == 4445 and [r['number'] for r in frames] == list(range(4445))
            and [r['slot'] for r in frames] == list(range(1000, 5445)), 'published_frame_inventory_incomplete')
    continuity = read(paths['tape_continuity'])
    require(continuity['path'] == d['paths']['tape'] and continuity['physical_bytes'] == b['physical_bytes']
            and continuity['physical_sha256'] == b['physical_sha256']
            and continuity['inventory_path'] == d['paths']['frame_inventory']
            and continuity['inventory_sha256'] == b['frame_inventory_sha256'], 'physical_continuity_binding_changed')
    for name in ('before', 'after', 'inventory_before', 'inventory_after'): check_stat(continuity[name])
    require(continuity['before'] == continuity['after'] and continuity['inventory_before'] == continuity['inventory_after']
            and continuity['before']['size'] == b['physical_bytes']
            and not continuity['before']['mode'] & 0o222
            and continuity['inventory_before']['size'] == paths['frame_inventory'].stat().st_size,
            'physical_path_inode_or_time_changed')
    from attest import signed_document, admission_errors, constraint_identity, reserve_storage
    allocation = signed_document(paths['signed_allocation'], allocation_key, d['trust_keys']['allocation_public_key_sha256'])
    require(allocation == d['allocation'], 'preflight_allocation_changed')
    # Resolve signed capability paths only to exact manifest-bound published bytes.
    capabilities = published_capabilities(root, allocation)
    require(set(capabilities) == {r['path'] for r in allocation['allocation_evidence']},
            'preflight_capability_inventory_incomplete')
    runtime = read(paths['runtime'])
    initial, final = read(paths['storage_initial']), read(paths['storage_final'])
    require(constraint_identity(initial) == constraint_identity(final), 'preflight_resource_constraints_changed')
    for sample in (initial, final):
        require(not admission_errors(sample, allocation, d['storage_bounds'], runtime, evidence_files=capabilities),
                'preflight_raw_resource_admission_failed')
    derivation = read(paths['storage_budget'])
    require(derivation['bounds'] == d['storage_bounds']
            and derivation['free_bytes'] == [r['free_bytes'] for r in initial['storage']]
            and derivation['retained_hardlinks_counted_once'] is True
            and derivation['simultaneous_publication_copies'] == 2
            and derivation['copy_budget_each'] == d['storage_bounds']['working_bytes'],
            'preflight_storage_derivation_changed')
    reserve = read(paths['storage_reserve'])
    require(any(reserve == reserve_storage(sample, d['storage_bounds']) for sample in (initial, final)),
            'preflight_raw_reserve_changed')
    durability = read(paths['filesystem_durability'])
    require(durability['journal_mode'] == 'wal' and durability['synchronous'] == 2
            and durability['separate_connection_readback'] == [[1]]
            and durability['second_writer_excluded'] is True and durability['directory_fsync_returned'] is True
            and bool(durability['files']) and all(r['fsync_returned'] is True for r in durability['files'])
            and durability['source_frames_released'] == durability['A_trials_started'] == 0,
            'filesystem_WAL_fsync_durability_missing')
    budget = feasibility(budget_values, final['storage'])
    return dict(version='stage-e-native-v3-imported-shared-input-receipt', **FROZEN,
        state='VERIFIED_PUBLISHED_A_PREFLIGHT_RECEIPTS_ONLY', verified=True,
        tape_path=continuity['path'], tape_stat=continuity['after'],
        inventory_identity=dict(path=continuity['inventory_path'], stat=continuity['inventory_after'],
                                sha256=b['frame_inventory_sha256']),
        bindings=deepcopy(bindings), production_storage=deepcopy(final['storage']), budget=budget,
        physical_bytes_rehashed_by_this_prep=False, substitutes_execution_time_checks=False,
        fresh_execution_time_continuity_required=True, historical_free_space_is_current_admission=False,
        capacity_credit=False, observer_credit=False, source_frames_released=0)
