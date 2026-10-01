"""All successor operations explicitly select v2; historical entrypoints intact."""
import argparse
from pathlib import Path

from .binding import assemble, launch, verify_assembly
from .contract import canonical, read, sha256
from .verify import aggregate


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='operation',required=True)
    a=sub.add_parser('assemble');a.add_argument('--root',required=True);a.add_argument('--output',required=True)
    a.add_argument('--candidate',required=True);a.add_argument('--tree',required=True)
    a.add_argument('--plan-hash',required=True);a.add_argument('--input-hash',required=True);a.add_argument('--workflow',required=True)
    t=sub.add_parser('trial');t.add_argument('--assembly',required=True);t.add_argument('--digest',required=True)
    t.add_argument('--candidate',required=True);t.add_argument('--case',required=True);t.add_argument('--output',required=True)
    g=sub.add_parser('aggregate');g.add_argument('--assembly',required=True);g.add_argument('--digest',required=True)
    g.add_argument('--inventory',required=True);g.add_argument('--output',required=True);g.add_argument('raw_trials',nargs='+')
    w=sub.add_parser('workflow-check');w.add_argument('--output',required=True)
    args=p.parse_args()
    if args.operation=='assemble':
        result=assemble(args.root,args.output,candidate=args.candidate,tree=args.tree,workflow=read(args.workflow),
            expected_plan_hash=args.plan_hash,expected_input_hash=args.input_hash)
        print(result['assembly_digest']);return 0
    if args.operation=='trial':
        expected_entrypoint=Path(args.assembly).resolve()/'source/certification/stage_e_native_v2/__main__.py'
        if Path(__file__).resolve()!=expected_entrypoint:
            raise ValueError('qualification_launcher_must_load_from_assembly')
        manifest=verify_assembly(args.assembly,args.digest)
        if manifest['identity']['candidate_sha']!=args.candidate:raise ValueError('foreign_candidate_execution')
        result=launch(args.assembly,args.digest,args.case,args.output)
        print(result.stdout+result.stderr,end='');return result.returncode
    if args.operation=='aggregate':
        row=aggregate(args.assembly,args.digest,args.raw_trials,read(args.inventory),args.output)
        return 0 if row['passed'] else 1
    if args.operation=='workflow-check':
        from .workflow import validate
        row=validate();Path(args.output).write_bytes(canonical(row));return 0


if __name__=='__main__':raise SystemExit(main())
