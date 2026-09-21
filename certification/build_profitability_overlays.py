"""Build current operational overlays rebased onto profitability-v1 source heads.

Credential-free build helper. It never contacts market providers and never changes refs.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OPERATIONAL_REF="d632cbe52220f95844632ac9a5669ee39dfbe082"

LANES={
    "pump": dict(
        base="04c99ca3125747dc8bfc6f655fec7533f8ac8156",
        profit="160985182b043ab41d0418ba5dcfed7dbfbe3cb2",
        patch_path="certification/patches/pump-accounting.patch",
        files=[
            "meme_machine/pump_acceleration_strategy.py",
            "tests/pump_acceleration_natural_prospective.py",
            "tests/test_pump_acceleration_strategy.py",
            "tests/test_pump_acceleration_policy_identity.py",
            ".github/workflows/pump-acceleration-natural-prospective.yml",
            ".github/workflows/ci.yml",
        ],
    ),
    "pons": dict(
        base="c692fe446bdee4ea1179da27a3f0c9f2f281f118",
        profit="a8b560c13f7e1b3696ac7f7aa9f35801f87421e1",
        patch_path="certification/patches/pons-cohort-capital.patch",
        files=[
            "robinhood_research/pons_selective_continuation.py",
            "robinhood_research/pons_selective_cohort.py",
            "robinhood_tests/test_pons_selective_continuation.py",
            ".github/workflows/robinhood-research.yml",
        ],
    ),
}

def run(*args,cwd=ROOT,check=True,text=True):
    return subprocess.run(args,cwd=cwd,check=check,text=text,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT)

def show(ref,path):
    return run("git","show",f"{ref}:{path}").stdout

def conflicts(body):
    return list(re.finditer(r"<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*\n",body,re.S))

def resolve_pump(path,body):
    rows=conflicts(body)
    if len(rows)!=1 or path!="tests/pump_acceleration_natural_prospective.py":
        raise RuntimeError(f"unexpected_pump_conflict:{path}:{len(rows)}")
    m=rows[0]
    left=m.group(1).replace(
        'FROZEN_POLICY_HASH="bb2631d83f5be287a0afc01dfc6d7a4da8b7086ae0afd09dfbf27df6d9d66a6e"',
        'FROZEN_POLICY_HASH="561ce76a334d9cdcd3b4888a9aaee24d11c9eb43f1ca20c5b806940297018bfc"',
    )
    return body[:m.start()]+left+body[m.end():]

def resolve_pons(path,body):
    rows=conflicts(body)
    if path=="robinhood_tests/test_pons_selective_continuation.py" and len(rows)==1:
        m=rows[0]
        return body[:m.start()]+m.group(2)+body[m.end():]
    if path!="robinhood_research/pons_selective_cohort.py" or len(rows)!=3:
        raise RuntimeError(f"unexpected_pons_conflict:{path}:{len(rows)}")
    replacements=[
'''            "distinct Pons V2 buys receive minimal current-state authentication; "
            "trajectory/window investment evaluation is admitted only when current "
            "ungraduated native-quote state satisfies the profitability-v1 progress, "
            "snipe-tax, creator-tax, maturity, ETA and friction prospect screen; "
            "paper entry additionally requires a terminal/flat prior same-curve "
            "lifecycle plus a point-in-time regime reset; at most one screen per "
            "curve per 2 wall-clock seconds; no outcome reranking"
''',
'''                    if len(futures)>=MAX_CONCURRENT_LIFECYCLES:
                        life=dict(index=qindex,status='capacity_censored',
                            boundary='selective_concurrent_position_capacity',economic_rejection=False)
                        result['lifecycles'].append(life)
                        _append_jsonl(ROOT/'completed-lifecycles.jsonl',life)
                        continue
                    future=pool.submit(
                        run_lifecycle,endpoint,evaluation,
                        db_path=ROOT/f"trial-{qindex:03d}.sqlite",
                        capital_path=ROOT/"pons-selective-cohort-capital.sqlite",
                    )
                    futures.append((qindex,future))
                    active_curve_futures[curve]=(qindex,future)
                    last_authorized_vector[curve]=evaluation["vector"]
''',
'',
]
    for m,repl in reversed(list(zip(rows,replacements))):
        body=body[:m.start()]+repl+body[m.end():]
    body=body.replace(
        '            result["lifecycles"].append(life)\n            last_terminal_by_curve[curve]=life',
        '            result["lifecycles"].append(life)\n'
        '            _append_jsonl(ROOT/"completed-lifecycles.jsonl",life)\n'
        '            last_terminal_by_curve[curve]=life')
    body=body.replace(
        '            futures=_collect_completed(result,futures)',
        '            for curve_key in list(active_curve_futures):\n'
        '                collect_curve_future(curve_key)\n'
        '            futures=[item for item in futures if id(item[1]) not in collected_futures]')
    old='''                for qindex,future in futures:
                    try:life=future.result()
                    except Exception as exc:life=dict(status='unexpected_boundary',boundary=type(exc).__name__)
                    life['index']=qindex
                    result['lifecycles'].append(life)
                    _append_jsonl(ROOT/'completed-lifecycles.jsonl',life)
                    _checkpoint(result,cursor=cursor,feed=feed,rpc=rpc,phase='position_drain')
'''
    new='''                for qindex,future in futures:
                    if id(future) in collected_futures:
                        continue
                    try:life=future.result()
                    except Exception as exc:life=dict(status='unexpected_boundary',boundary=type(exc).__name__)
                    life['index']=qindex
                    result['lifecycles'].append(life)
                    _append_jsonl(ROOT/'completed-lifecycles.jsonl',life)
                    collected_futures.add(id(future))
                    _checkpoint(result,cursor=cursor,feed=feed,rpc=rpc,phase='position_drain')
'''
    if old not in body:
        raise RuntimeError("pons_terminal_drain_shape_changed")
    body=body.replace(old,new)
    return body

def merge_file(lane,path,operational,base,profit):
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        a=td/"operational";b=td/"base";c=td/"profit"
        a.write_text(operational);b.write_text(base);c.write_text(profit)
        proc=run("git","merge-file","-p",str(a),str(b),str(c),check=False)
        body=proc.stdout
    if proc.returncode!=0:
        if not any(x in body for x in ("<<<<<<<","=======",">>>>>>>")):
            raise RuntimeError(f"merge_file_failed:{lane}:{path}:{proc.returncode}")
        body=resolve_pump(path,body) if lane=="pump" else resolve_pons(path,body)
    if any(x in body for x in ("<<<<<<<","=======",">>>>>>>")):
        raise RuntimeError(f"conflict_marker_remaining:{lane}:{path}")
    return body

def build_lane(lane,spec,outdir):
    run("git","fetch","origin",spec["base"],spec["profit"])
    root=Path(tempfile.mkdtemp(prefix=f"{lane}-combined-"))
    profitroot=Path(tempfile.mkdtemp(prefix=f"{lane}-profit-"))
    try:
        run("git","worktree","add","--detach",str(root),spec["base"])
        operational_patch=root.parent/f"{lane}-operational.patch"
        operational_patch.write_text(show(OPERATIONAL_REF,spec["patch_path"]))
        run("git","-C",str(root),"apply","--index",str(operational_patch))
        for path in spec["files"]:
            operational=(root/path).read_text()
            base=show(spec["base"],path)
            profit=show(spec["profit"],path)
            (root/path).write_text(merge_file(lane,path,operational,base,profit))

        # Rebase the complete combined tree onto the profitability source head.
        run("git","worktree","add","--detach",str(profitroot),spec["profit"])
        changed=run("git","-C",str(root),"diff","--name-status","HEAD").stdout.splitlines()
        for row in changed:
            status,path=row.split("\t",1)
            target=profitroot/path
            source=root/path
            if status.startswith("D"):
                if target.exists():target.unlink()
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                if source.is_file():shutil.copy2(source,target)
                else:raise RuntimeError(f"unsupported_overlay_path:{lane}:{status}:{path}")
        # Stage the rebased tree so overlay-created files are included in the patch.
        run("git","-C",str(profitroot),"add","-A")
        run("git","-C",str(profitroot),"diff","--cached","--check")
        patch=run("git","-C",str(profitroot),"diff","--cached","--binary","HEAD").stdout
        if not patch.strip():raise RuntimeError(f"empty_rebased_patch:{lane}")
        (outdir/f"{lane}-combined.patch").write_text(patch)
    finally:
        run("git","worktree","remove","--force",str(root),check=False)
        run("git","worktree","remove","--force",str(profitroot),check=False)
        shutil.rmtree(root,ignore_errors=True);shutil.rmtree(profitroot,ignore_errors=True)

def main():
    out=ROOT/"profitability-overlay-build";shutil.rmtree(out,ignore_errors=True);out.mkdir()
    for lane,spec in LANES.items():build_lane(lane,spec,out)
    print({p.name:p.stat().st_size for p in out.iterdir()})

if __name__=="__main__":main()
