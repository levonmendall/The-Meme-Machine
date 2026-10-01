"""Explicit v2 execution inside one reviewed assembly; no canonical dispatch."""
import argparse
import os
from pathlib import Path
import traceback
import uuid

from .binding import verify_assembly, origin_proof, environment_identity, launch
from .contract import canonical, read
from .firewall import classification
from .isolation import provider_firewall, child_firewall


def execute(case, output):
    if case=='preflight':
        from .contract import validate_inputs
        return dict(input_binding=validate_inputs(),preflight_only=True)
    if case=='clock-contract':
        from .tests.test_clocks import bounded_clock_proof
        return bounded_clock_proof()
    if case in ('native-transitions','held-reader'):
        from .native import transitions
        return transitions(output,held=case=='held-reader')
    if case=='generation-restart':
        from .restart import check_generations, check_restart
        return dict(generation_fencing=check_generations(output),restart=check_restart(output))
    if case=='run379-setup':
        from .run379 import bounded_setup_witness
        return bounded_setup_witness(output)
    if case=='m1-completion':
        from .m1 import qualify
        return qualify(output)
    if case=='origin-child':
        # A child has its own actual entrypoint/helper origins and verifies the
        # same assembly. Arbitrary Python subprocesses are prohibited in trials.
        from . import fixtures
        import importlib.util
        import sys
        shadow=Path(output)/'foreign_shadow.py'
        shadow.write_text("raise AssertionError('foreign module executed')\n")
        rejected=False
        try:
            module_spec=importlib.util.spec_from_file_location('v2_foreign_shadow',shadow)
            foreign=importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(foreign)
        except PermissionError as exc:
            rejected='unapproved_dynamic_executable_origin' in str(exc)
        if not rejected:raise AssertionError('foreign_dynamic_local_module_not_rejected')
        return dict(child_origin_probe=True,foreign_dynamic_import_rejected=True,
            fixture_origin=str(Path(fixtures.__file__).resolve()))
    raise PermissionError('unimplemented_or_material_case:'+case)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();case=classification(args.case)
    assembly=Path(os.environ['MM_STAGE_E_V2_ASSEMBLY']);digest=os.environ['MM_STAGE_E_V2_DIGEST']
    manifest=verify_assembly(assembly,digest);output=Path(args.output).resolve()
    if output.is_relative_to(assembly.resolve()):raise ValueError('output_inside_assembly')
    raw=dict(identity=dict(manifest['identity'],assembly_digest=digest),case_id=args.case,
        trial_id=f'{args.case}:{uuid.uuid4().hex}',classification=case['classification'],
        paper_only=True,canonical_authority=False,market_authority=False,passed=False,
        generation=None,payload={},errors=[],provider_attempts=[],runtime_origins=[],
        assembly_before=digest,assembly_after=None,children=[])
    if environment_identity()!=manifest['identity']['environment_identity']:
        raise ValueError('actual_execution_environment_drifted')
    if args.case!='origin-child':
        child=launch(assembly,digest,'origin-child',output/'child-origin')
        if child.returncode!=0:raise ValueError('assembled_child_origin_proof_failed')
        raw['children']=[read(output/'child-origin/raw-trial-v2.json')]
    with provider_firewall() as attempts, child_firewall():
        try:
            raw['payload']=execute(args.case,output)
            raw['generation']=raw['payload'].get('generation')
            raw['passed']=raw['payload'].get('passed',True) is True
        except BaseException as exc:
            raw['errors'].append(dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
        raw['provider_attempts']=list(attempts)
        if attempts:raw['passed']=False
    try:
        raw['runtime_origins']=origin_proof(manifest,assembly/'source')
        verify_assembly(assembly,digest);raw['assembly_after']=digest
    except BaseException as exc:
        raw['passed']=False;raw['errors'].append(dict(type=type(exc).__name__,message=str(exc)))
    (output/'raw-trial-v2.json').write_bytes(canonical(raw))
    return 0 if raw['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
