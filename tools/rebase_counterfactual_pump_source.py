from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE_SHA="3c9553afb3caa92ab5f3db769f870df033a9630f"
SOURCE_BRANCH="strategy/pump-counterfactual-replay-v1-20260924"
POLICY_HASH="825084f162efdc10ca4d1faad747902b858bb6e7b4441f7ff48bf089a182f28b"
STRATEGY_VERSION="pump-acceleration-independent-v1/profitability-v1-profit-protection-v2-counterfactual-replay-v1"
OLD_OVERLAY="certification/patches/counterfactual-replay-pump-v1.patch"

def run(*args,cwd=ROOT):
    return subprocess.run(args,cwd=cwd,check=True,capture_output=True)

def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def full_diff_hash(root: Path):
    data=subprocess.check_output([
        "git","diff","--binary","--full-index","--no-ext-diff",
        "--no-textconv","--no-renames","HEAD"
    ],cwd=root)
    return hashlib.sha256(data).hexdigest()

def main():
    sys.path.insert(0,str(ROOT))
    subprocess.run(["git","fetch","origin",SOURCE_SHA],cwd=ROOT,check=True)
    src_root=Path(tempfile.mkdtemp(prefix="mm-pump-source-"))
    source=src_root/"pump"
    fresh_root=None
    try:
        subprocess.run(["git","worktree","add","--detach",str(source),SOURCE_SHA],cwd=ROOT,check=True)
        sources_path=ROOT/"certification/sources.json"
        spec=json.loads(sources_path.read_text())
        row=spec["lanes"]["pump"]
        row["source_branch"]=SOURCE_BRANCH
        row["source_sha"]=SOURCE_SHA
        row.pop("execution_sha",None)
        row["strategy_version"]=STRATEGY_VERSION
        row["policy_hash"]=POLICY_HASH
        row["file_hashes"]={
            name:sha256(source/name)
            for name in row["file_hashes"]
        }
        row["overlay_patches"]=[
            p for p in row.get("overlay_patches",[])
            if p != OLD_OVERLAY
        ]
        row["execution_certification"]["revision"]="profitability-v1-profit-protection-v2-counterfactual-replay-v1"
        row["execution_certification"]["counterfactual_replay_v1"].update({
            "source_promotion":SOURCE_SHA,
            "source_branch":SOURCE_BRANCH,
            "strategy_source_pinned":True,
        })
        sources_path.write_text(json.dumps(spec,indent=2)+"\n")
        old=ROOT/OLD_OVERLAY
        if old.exists():
            old.unlink()

        from certification.run import prepare
        fresh_root=Path(tempfile.mkdtemp(prefix="mm-pump-recompose-"))
        lanes=fresh_root/"lanes"
        prepare(lanes)
        observed=full_diff_hash(lanes/"pump")
        spec=json.loads(sources_path.read_text())
        spec["lanes"]["pump"]["source_diff_sha256"]=observed
        sources_path.write_text(json.dumps(spec,indent=2)+"\n")

        protocol_path=ROOT/"certification/profitability_protocol.json"
        protocol=json.loads(protocol_path.read_text())
        protocol["frozen_parent_integration_sha"]=subprocess.check_output(
            ["git","rev-parse","HEAD"],cwd=ROOT,text=True
        ).strip()
        protocol["frozen_lanes"]["pump"]={
            "strategy_version":STRATEGY_VERSION,
            "source_sha":SOURCE_SHA,
            "execution_sha":SOURCE_SHA,
            "policy_hash":POLICY_HASH,
            "source_diff_sha256":observed,
        }
        protocol_path.write_text(json.dumps(protocol,indent=2)+"\n")

        # Verify the new source plus the full operational composition before commit.
        subprocess.run([
            "python","-m","unittest",
            "tests.test_pump_acceleration_strategy",
            "tests.test_pump_acceleration_policy_identity","-v"
        ],cwd=lanes/"pump",check=True)

        print(json.dumps({
            "source_sha":SOURCE_SHA,
            "policy_hash":POLICY_HASH,
            "source_diff_sha256":observed,
            "removed_strategy_overlay":True,
        },sort_keys=True))
    finally:
        try:
            subprocess.run(["git","worktree","remove","--force",str(source)],cwd=ROOT,check=False)
        finally:
            shutil.rmtree(src_root,ignore_errors=True)
            if fresh_root is not None:
                shutil.rmtree(fresh_root,ignore_errors=True)

if __name__=="__main__":
    main()
