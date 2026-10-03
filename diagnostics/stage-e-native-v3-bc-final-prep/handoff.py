"""Bounded future readback/ingestion. No authorization, dispatch or execution."""
import argparse
from copy import deepcopy
from pathlib import Path
import re

from frozen import *
from ingestion import ingest_campaign, bind_preview, verify_bound_B_preview
from model import skeleton
from preservation import GitHub, readback_github
from preserve import persist, seal
from qualification import generate
from shared_inputs import validate_receipts


def plan_template():
    # Commit/hash/path/key fields must be replaced with genuine published inputs.
    return dict(version='stage-e-native-v3-handoff-plan', **FROZEN,
        owner_key=unresolved('INDEPENDENT_TRUST_REQUIRED', 'owner public key file'),
        allocation_key=unresolved('INDEPENDENT_TRUST_REQUIRED', 'allocation public key file'),
        packages={k: dict(commit=None, transport_manifest_sha256=None, campaign_relative_path=None,
                          preservation_receipt_relative_path=None, declaration_sha256=None,
                          campaign_inventory_sha256=None) for k in ('A', 'B', 'C')},
        A_preflight=dict(commit=None, transport_manifest_sha256=None, bindings=None, budget_values=None),
        preview_config={k: dict(paths=None, workflow=None, storage_bounds=None) for k in ('B', 'C')},
        retained=dict(commit=None, transport_manifest_sha256=None, folder_relative_path=None, assembly=None),
        authorization_created=False, actual_slots_reserved=False, source_frames_released=0)


def read_phase(label, spec, output, api):
    require(type(spec.get('commit')) is str and re.fullmatch('[0-9a-f]{40}', spec['commit'])
            and type(spec.get('transport_manifest_sha256')) is str
            and re.fullmatch('[0-9a-f]{64}', spec['transport_manifest_sha256']),
            'genuine_published_' + label + '_reference_required')
    target = Path(output) / ('readback-' + label)
    return readback_github(spec['commit'], target, expected_manifest_sha256=spec['transport_manifest_sha256'], api=api)


def phase_ref(spec, remote):
    root = Path(remote['output'])
    folder = relative(root, spec['campaign_relative_path'])
    receipt = relative(root, spec['preservation_receipt_relative_path'])
    d = read(folder/'DECLARATION.json')
    require(d['class_id'] == remote['class_id'] and d['campaign'] == remote['campaign'], 'transport_campaign_class_changed')
    require(spec['declaration_sha256'] == remote['declaration_sha256'], 'transport_declaration_binding_changed')
    r = dict(remote, output=str(folder.resolve()), inventory_sha256=spec['campaign_inventory_sha256'])
    return dict(sealed_campaign=str(folder), preservation_receipt=str(receipt),
                declaration_sha256=spec['declaration_sha256'],
                campaign_inventory_sha256=spec['campaign_inventory_sha256'], remote_readback=r)


def run(phase, plan, output, *, api=None):
    require(phase in ('after-a', 'after-b', 'after-c'), 'handoff_phase')
    exact_frozen(plan)
    require(type(plan['owner_key']) is str and type(plan['allocation_key']) is str
            and Path(plan['owner_key']).is_file() and Path(plan['allocation_key']).is_file(),
            'independently_trusted_public_keys_required')
    output = Path(output)
    require(not output.resolve().is_relative_to(ROOT), 'handoff_output_must_be_outside_frozen_prep_package')
    output.mkdir(parents=True, exist_ok=False)
    api = api or GitHub()
    keys = dict(owner_key=plan['owner_key'], allocation_key=plan['allocation_key'])
    refs = {}
    phases = ('A',) if phase == 'after-a' else ('A', 'B') if phase == 'after-b' else ('A', 'B', 'C')
    verified, seen = {}, []
    for kind in phases:
        remote = read_phase(kind, plan['packages'][kind], output, api)
        refs[kind] = phase_ref(plan['packages'][kind], remote)
        verified[kind] = ingest_campaign(refs[kind], kind=kind, seen_namespaces=seen,
                                        prerequisite_A=refs.get('A'), **keys)
        seen.append(verified[kind]['declaration']['campaign'])
    # Shared inputs are independently read back on every handoff. Historical
    # free-space snapshots cannot authorize execution or waive fresh continuity.
    pre = plan['A_preflight']; pre_remote = read_phase('PREFLIGHT', pre, output, api)
    require(pre_remote['class_id'] == 'PREFLIGHT', 'shared_inputs_must_be_A_preflight')
    shared = validate_receipts(pre_remote['output'], pre['bindings'],
        expected_executor=verified['A']['declaration']['executor'],
        expected_environment_sha256=verified['A']['declaration']['environment_sha256'],
        budget_values=pre['budget_values'], allocation_key=plan['allocation_key'])
    require(shared['budget']['fits_all_declared_filesystems'] is True, 'final_ABC_evidence_storage_shortfall')
    persist(output/'SHARED_INPUT_RECEIPT.json', shared)
    retained_ref = None
    if phase == 'after-c':
        rr = read_phase('PRESERVED', plan['retained'], output, api)
        require(rr['class_id'] == 'PRESERVED', 'preserved_transport_class')
        retained_ref = dict(folder=str(relative(rr['output'], plan['retained']['folder_relative_path'])),
                            assembly=plan['retained']['assembly'])
    review = generate(refs, retained_ref=retained_ref, **keys)
    persist(output/'QUALIFICATION_REVIEW.json', review)
    if phase != 'after-c':
        kind = 'B' if phase == 'after-a' else 'C'
        previous = verified['A' if kind == 'B' else 'B']
        d = bind_preview(kind, previous, plan['preview_config'][kind])
        if kind == 'B': verify_bound_B_preview(d, **keys)
        persist(output/(kind + '_PREVIEW.json'), d)
        disposition = 'STOP FOR OWNER ' + kind + ' AUTHORIZATION'
    else: disposition = 'STOP FOR ASTRA/OWNER FINAL DISPOSITION'
    persist(output/'HANDOFF_RESULT.json', dict(phase=phase, disposition=disposition,
        stage_e=review['stage_e'], stage_f='NOT STARTED', qualification_disposition=review['disposition'],
        execution_authorized=False, owner_permit_created=False, jobs_dispatched=0,
        A_B_C_trials_started=0, actual_slots_reserved=False, source_frames_released=0))
    seal(output, name='HANDOFF_INVENTORY.json')
    return disposition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('after-a', 'after-b', 'after-c', 'empty-review'))
    parser.add_argument('--plan'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.phase == 'empty-review':
        out = Path(args.output); require(not out.resolve().is_relative_to(ROOT), 'output_inside_frozen_prep')
        out.mkdir(parents=True, exist_ok=False)
        persist(out/'QUALIFICATION_REVIEW.json', generate({}, owner_key=None, allocation_key=None))
        print('STAGE_E_NATIVE_V3_QUALIFICATION_BLOCKED; Stage E RED; Stage F NOT STARTED')
    else:
        require(args.plan is not None, 'published_input_plan_required')
        print(run(args.phase, read(args.plan), args.output))


if __name__ == '__main__': main()
