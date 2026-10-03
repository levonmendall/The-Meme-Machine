"""Generate disposable paper templates only, under this preparation root."""
from pathlib import Path

from frozen import *
from model import declaration_template, path_map, a_slot, skeleton, A_FIELDS
from shared_inputs import template as shared_template, RECEIPTS
from storage import budget_template, harness_reservation_template
from handoff import plan_template
from qualification import generate
from retained import CANONICAL, NATIVE_CASES, LANES


def build(*, refresh=False):
    outputs = {
        'B_TEMPLATE.json': declaration_template('B'),
        'B_A_PREREQUISITE_SCHEMA.json': dict(version='stage-e-native-v3-A-binding-schema',
            fields=A_FIELDS, required_fields=list(A_FIELDS), unresolved=a_slot(),
            admission_rejection='A_PREREQUISITE_NOT_YET_AVAILABLE',
            binding_command='python handoff.py after-a --plan actual-plan.json --output NEW_DIRECTORY',
            authorizes_execution=False),
        'C_TEMPLATE.json': declaration_template('C'),
        'EVIDENCE_PATH_MAP.json': path_map(),
        'IMMUTABLE_INPUT_RECEIPT.json': shared_template(),
        'STORAGE_BUDGET.json': budget_template(),
        'B_STORAGE_RESERVATION_TEMPLATE.json': harness_reservation_template('B'),
        'C_STORAGE_RESERVATION_TEMPLATE.json': harness_reservation_template('C'),
        'QUALIFICATION_SKELETON.json': skeleton(),
        'HANDOFF_PLAN_TEMPLATE.json': plan_template(),
        'EMPTY_QUALIFICATION_REVIEW.json': generate({}, owner_key=None, allocation_key=None),
        'SHARED_INPUT_BINDING_TEMPLATE.json': dict(state='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
            bindings={k: dict(path=None, sha256=None) for k in RECEIPTS},
            import_only_from_completed_published_A_preflight=True, authorizes_execution=False),
        'SHARED_INPUT_SCHEMA.json': dict(state='AWAITING_A_PREFLIGHT_PHYSICAL_INPUT',
            exact_tape_stat_keys=['device','inode','size','mtime_ns','ctime_ns','mode'],
            continuity_keys=['path','physical_bytes','physical_sha256','inventory_path','inventory_sha256',
                             'before','after','inventory_before','inventory_after'],
            receipt_bindings={k: dict(path=None,sha256=None) for k in RECEIPTS},
            receipt_sources=dict(declaration='A_PREDECLARATION_PREVIEW.json',
                tape_verification='TAPE_VERIFICATION.json',frame_inventory='FRAMES.json',
                tape_continuity='genuine published tape/inventory stat before and after hashing',
                storage_initial='SIGNED_ADMISSION_RESOURCE_INITIAL.json',
                storage_final='SIGNED_ADMISSION_RESOURCE_FINAL.json',
                storage_budget='STORAGE_BUDGET_DERIVATION.json',
                storage_reserve='PREPARATION_STORAGE_RESERVE.json or FINAL_STORAGE_RESERVATION.json',
                filesystem_durability='STORAGE_CAPABILITY.json',signed_allocation='SIGNED_ALLOCATION.json',
                runtime='exact declared runtime.json'),
            missing_stat_or_receipt_remains_deferred=True, opens_production_paths=False,
            authorizes_execution=False),
        'RETAINED_INPUT_SCHEMA.json': dict(version='stage-e-native-v3-retained-raw-schema-template', **FROZEN,
            state='PRESERVED_PRIMARY_RAW_EVIDENCE_NOT_YET_INGESTED',
            input_version='stage-e-native-v3-retained-raw-inputs',
            canonical={k: dict(path=None,sha256=None) for k in CANONICAL},
            native={k: dict(path=None,sha256=None) for k in NATIVE_CASES},
            prepared=dict(lanes={k:dict(source=None,before=None,after=None,policy_hashes_before=None,
                policy_hashes_after=None,origin_modules=None,collected_test_modules=None) for k in LANES},
                candidate_sha=S,candidate_tree=T,assembly_digest=ASSEMBLY,protocol_inputs=None),
            primary_test_receipts={k:[dict(lane=lane,source=None,modules=None,
                log=dict(path=None,sha256=None),exit_code=None) for lane in LANES]
                for k in ('offline','crash','restart','integrated','directional','bounded',
                          'joined_crash','joined_provider','joined_long_horizon')},
            origin=dict(candidate_sha=S,candidate_tree=T,assembly_before=None,assembly_after=None,
                        runtime_origins=None,provider_attempts=None),
            raw_inventory='RAW_INVENTORY.json',raw_descriptor='RETAINED_INPUTS.json',
            authority='RETAINED_AUTHORITY.json: signed_document payload commits to exact primary-byte inventory SHA-256',
            historical_summaries_do_not_satisfy_missing_primary_proof=True, authorizes_execution=False),
        'FROZEN_INPUTS.json': dict(**FROZEN, executable=check_executable(),
            production_workload_sha256=sha(canonical(workload('A'))),
            observer_workload_sha256=sha(canonical(workload('B'))),
            stress_workload_sha256=sha(canonical(workload('C'))),
            infrastructure=infrastructure_identity(), stages=dict(E='RED', F='NOT STARTED')),
    }
    for name, value in outputs.items():
        path = ROOT / name
        data = canonical(value) + b'\n'
        if path.exists() and not refresh: require(path.read_bytes() == data, 'template_regeneration_changed:' + name)
        else: path.write_bytes(data)
    return len(outputs)


if __name__ == '__main__': print('Paper templates generated:', build())
