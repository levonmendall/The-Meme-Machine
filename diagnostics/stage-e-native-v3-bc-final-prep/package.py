"""Seal or verify only the disposable preparation package; no campaign credit."""
import argparse
from pathlib import Path

from frozen import *
from preservation import snapshot_tree, exclusive_bytes

MANIFEST = 'package-manifest.json'


def rows(root):
    root = Path(root)
    result = []
    for row in snapshot_tree(root):
        if row['path'] == MANIFEST: continue
        require(not (root/row['path']).stat().st_mode & 0o111, 'unexpected_executable_prep_artifact')
        result.append(dict(row, mode='100644'))
    return result


def seal_package(root=ROOT):
    artifacts = rows(root)
    record = dict(version='stage-e-native-v3-parallel-preparation-manifest', **FROZEN,
        artifacts=artifacts, manifest_self_excluded=True,
        physical_inputs='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
        stage_e='RED', stage_f='NOT STARTED', paper_only=True,
        execution_authorized=False, A_trials_run=0, B_trials_run=0, C_trials_run=0,
        slots_reserved=0, slots_consumed=0, source_frames_released=0,
        jobs_dispatched=0, production_volume_accessed=False, acceptance_credit=False)
    exclusive_bytes(Path(root)/MANIFEST, canonical(record)+b'\n')
    verify_package(root, expected_manifest_sha256=file_sha(Path(root)/MANIFEST))
    return record


def verify_package(root=ROOT, *, expected_manifest_sha256):
    path = Path(root)/MANIFEST
    require(file_sha(path) == expected_manifest_sha256, 'prep_manifest_hash_changed')
    record = read(path); exact_frozen(record)
    require(record['version'] == 'stage-e-native-v3-parallel-preparation-manifest'
            and record['artifacts'] == rows(root) and record['manifest_self_excluded'] is True,
            'prep_package_modified_partial_or_extra_after_manifest')
    require(record['stage_e'] == 'RED' and record['stage_f'] == 'NOT STARTED'
            and record['execution_authorized'] is False and record['acceptance_credit'] is False
            and all(record[k] == 0 for k in ('A_trials_run','B_trials_run','C_trials_run',
                                          'slots_reserved','slots_consumed','source_frames_released','jobs_dispatched')),
            'prep_manifest_cannot_assert_material_acceptance')
    return dict(files=len(record['artifacts'])+1, manifest_sha256=expected_manifest_sha256, verified=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('seal','verify'))
    parser.add_argument('--manifest-sha256')
    args=parser.parse_args()
    if args.operation=='seal':
        seal_package(); print(file_sha(ROOT/MANIFEST))
    else:
        require(args.manifest_sha256 is not None,'independently_bound_manifest_sha256_required')
        print(canonical(verify_package(expected_manifest_sha256=args.manifest_sha256)).decode())


if __name__=='__main__': main()
