#!/usr/bin/env bash
set -euo pipefail

PUMP_SHA=9932305ebe83dd3ff2dd45ffe9006cf628962bf3
METEORA_SHA=a616366fbe64e816708d035c15141b7e7e800304
PONS_SHA=157e3d3a94510ced93976088b5a3f56a672ad9c4
RAMSES_SHA=b8b62b7528c884d034af6c677a88e7d21e0b2fb1
export PUMP_SHA METEORA_SHA PONS_SHA RAMSES_SHA

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
: > "$RUNNER_TEMP/recomposed-hashes.txt"

recompose() {
  lane="$1"; source_sha="$2"; patch="$3"
  worktree="$RUNNER_TEMP/recompose-$lane"
  git fetch origin "$source_sha"
  git worktree add --detach "$worktree" "$source_sha"
  if [ "$lane" = pump ] || [ "$lane" = meteora ]; then
    git -C "$worktree" apply --3way --index --exclude=meme_machine/solana_read_rpc.py "$GITHUB_WORKSPACE/$patch"
    WORKTREE="$worktree" python - <<'PY'
import os
from pathlib import Path
p=Path(os.environ["WORKTREE"])/"meme_machine/solana_read_rpc.py"
s=p.read_text()
if "from .solana_immutable_rpc import ImmutableRPCMixin" not in s:
    marker="class _ReadOnlyFailoverMixin:"
    if marker not in s:
        raise SystemExit("solana_read_rpc_mixin_shape_changed")
    s=s.replace(marker,"from .solana_immutable_rpc import ImmutableRPCMixin\n\n\nclass _ReadOnlyFailoverMixin(ImmutableRPCMixin):",1)
elif "class _ReadOnlyFailoverMixin(ImmutableRPCMixin):" not in s:
    raise SystemExit("solana_read_rpc_inheritance_shape_changed")
p.write_text(s)
PY
  elif [ "$lane" = ramses ]; then
    git -C "$worktree" apply --3way --index --exclude=robinhood_research/ramses_universe.py "$GITHUB_WORKSPACE/$patch"
    WORKTREE="$worktree" python - <<'PY'
import os
from pathlib import Path
p=Path(os.environ["WORKTREE"])/"robinhood_research/ramses_universe.py"
s=p.read_text()
s=s.replace(
    "    finalized_frontier=None,\n):",
    "    finalized_frontier=None,\n    progress=None,\n):",1)
needle="    started = time.time()\n    rpc.verify_chain()\n    observation_rpc.verify_chain()"
replacement="""    started = time.time()
    scan_progress=dict(state='in_progress',started_at=started,stage='chain_authentication',
        pools_total=0,pools_attempted=0,pools_completed=0,pools_failed=0)
    def checkpoint(stage,**fields):
        scan_progress.update(stage=stage,updated_at=time.time(),**fields)
        if progress is not None:progress(dict(scan_progress))
    checkpoint('chain_authentication')
    rpc.verify_chain()
    observation_rpc.verify_chain()"""
if needle not in s: raise SystemExit("ramses_progress_start_shape_changed")
s=s.replace(needle,replacement,1)
needle='        frontier_source = "pinned_external_finalized_header"\n    end = int(frontier["number"], 16)'
replacement='        frontier_source = "pinned_external_finalized_header"\n    rpc.evidence_pins={frontier["number"]:frontier["hash"]}\n    end = int(frontier["number"], 16)'
if needle not in s: raise SystemExit("ramses_frontier_shape_changed")
s=s.replace(needle,replacement,1)
needle='    start = _window_start_block(\n        observation_rpc,end,int(frontier["timestamp"],16),LOOKBACK_SECONDS,lookback_blocks\n    )\n\n    factory_pin = load("ramses_factory")'
replacement='    start = _window_start_block(\n        observation_rpc,end,int(frontier["timestamp"],16),LOOKBACK_SECONDS,lookback_blocks\n    )\n    checkpoint(\'factory_authentication\',frontier_block=end,frontier_hash=frontier[\'hash\'],\n        frontier_timestamp=int(frontier[\'timestamp\'],16))\n\n    factory_pin = load("ramses_factory")'
if needle not in s: raise SystemExit("ramses_window_shape_changed")
s=s.replace(needle,replacement,1)
needle='    addresses = _enumerate_factory(\n        observation_rpc,factory,end,\n        factory_runtime_sha256=factory_identity["runtime_sha256"],\n    )\n    logs = _batched_logs(observation_rpc, start, end, addresses)'
replacement='    addresses = _enumerate_factory(\n        observation_rpc,factory,end,\n        factory_runtime_sha256=factory_identity["runtime_sha256"],\n    )\n    checkpoint(\'economic_log_census\',pools_total=len(addresses))\n    logs = _batched_logs(observation_rpc, start, end, addresses)'
if needle not in s: raise SystemExit("ramses_inventory_shape_changed")
s=s.replace(needle,replacement,1)
needle='    active_addresses={row["pool"] for row in active_cohort}\n    # Receipt gas is authoritative evidence'
replacement='    active_addresses={row["pool"] for row in active_cohort}\n    checkpoint(\'receipt_cost_authentication\')\n    # Receipt gas is authoritative evidence'
if needle not in s: raise SystemExit("ramses_receipt_shape_changed")
s=s.replace(needle,replacement,1)
needle='    for activity_row in active_cohort:\n        address = activity_row["pool"]\n        try:'
replacement='    for activity_row in active_cohort:\n        address = activity_row["pool"]\n        checkpoint(\'pool_prestate\',current_pool=address,\n            pools_attempted=scan_progress[\'pools_attempted\']+1,\n            active_cohort_size=len(active_cohort),inactive_pools=len(addresses)-len(histories))\n        try:'
if needle not in s: raise SystemExit("ramses_pool_loop_shape_changed")
s=s.replace(needle,replacement,1)
needle='        except BoundaryError as exc:\n            exclusions[str(exc)] += 1\n\n    features ='
replacement='        except BoundaryError as exc:\n            exclusions[str(exc)] += 1\n            checkpoint(\'pool_prestate_failed\',pools_failed=scan_progress[\'pools_failed\']+1,\n                last_reason=str(exc))\n\n    features ='
if needle not in s: raise SystemExit("ramses_pool_failure_shape_changed")
s=s.replace(needle,replacement,1)
needle='    classified = []\n    for row in rows:\n        f = row["features"]'
replacement='    classified = []\n    for row in rows:\n        checkpoint(\'pool_economic_classification\',current_pool=row[\'pool\'])\n        f = row["features"]'
if needle not in s: raise SystemExit("ramses_classification_shape_changed")
s=s.replace(needle,replacement,1)
needle='            "allocation_authority": False,\n        })\n\n    ranked = sorted(classified, key=_selection_key, reverse=True)'
replacement='            "allocation_authority": False,\n        })\n\n        checkpoint(\'pool_complete\',pools_completed=len(classified))\n    checkpoint(\'complete\',state=\'complete\',completed_at=time.time())\n    ranked = sorted(classified, key=_selection_key, reverse=True)'
if needle not in s: raise SystemExit("ramses_complete_shape_changed")
s=s.replace(needle,replacement,1)
p.write_text(s)
PY
  else
    git -C "$worktree" apply --3way --index "$GITHUB_WORKSPACE/$patch"
  fi

  if [ "$lane" = pump ]; then
    WORKTREE="$worktree" python - <<'PY'
import os
from pathlib import Path
p=Path(os.environ["WORKTREE"])/"tests/pump_acceleration_natural_prospective.py"
s=p.read_text()
old1="prefetch=incremental,"
old2="evidence_service=StreamEvidenceService(broker,lambda:new_rpc(limit=240)) if incremental else None"
if old1 not in s or old2 not in s:
    raise SystemExit("pump_runtime_prefetch_shape_changed")
s=s.replace(old1,"prefetch=False,",1)
s=s.replace(old2,"evidence_service=None",1)
p.write_text(s)
PY
  fi

  git -C "$worktree" diff --check HEAD
  git -C "$worktree" diff --binary HEAD > "$GITHUB_WORKSPACE/$patch.tmp"
  test -s "$GITHUB_WORKSPACE/$patch.tmp"
  mv "$GITHUB_WORKSPACE/$patch.tmp" "$GITHUB_WORKSPACE/$patch"
  printf '%s %s\n' "$lane" "$(sha256sum "$GITHUB_WORKSPACE/$patch" | awk '{print $1}')" >> "$RUNNER_TEMP/recomposed-hashes.txt"
  git worktree remove --force "$worktree"
}

recompose pump "$PUMP_SHA" certification/patches/pump-accounting.patch
recompose meteora "$METEORA_SHA" certification/patches/meteora-checkpoint.patch
recompose pons "$PONS_SHA" certification/patches/pons-cohort-capital.patch
recompose ramses "$RAMSES_SHA" certification/patches/ramses-admission.patch

python - <<'PY'
import json,os
from pathlib import Path
m_path=Path("certification/sources.json")
m=json.loads(m_path.read_text())
hashes={}
for line in Path(os.environ["RUNNER_TEMP"]).joinpath("recomposed-hashes.txt").read_text().splitlines():
    lane,value=line.split()
    hashes[lane]=value
heads={
    "pump":os.environ["PUMP_SHA"],
    "meteora":os.environ["METEORA_SHA"],
    "pons":os.environ["PONS_SHA"],
    "ramses":os.environ["RAMSES_SHA"],
}
details={
 "pump":dict(revision="alchemy-scarce-authoritative-evidence-v1",
   discovery_plane="public_solana_finalized_websocket",
   alchemy_role="candidate_and_position_authoritative_http_evidence_only",
   speculative_alchemy_prefetch=False,breadth_changed=False,
   strategy_thresholds_changed=False,paper_only_unchanged=True),
 "meteora":dict(revision="alchemy-scarce-authoritative-evidence-v1",
   discovery_plane="public_solana_program_and_account_wake_streams",
   alchemy_role="candidate_reconstruction_and_position_authoritative_http_evidence_only",
   alternate_authenticated_provider=False,breadth_changed=False,
   strategy_thresholds_changed=False,paper_only_unchanged=True),
 "pons":dict(revision="public-observation-alchemy-gap-evidence-v1",
   discovery_plane="official_robinhood_sequencer_plus_public_rpc",
   alchemy_role="candidate_position_evidence_and_exact_gap_recovery_only",
   routine_discovery_on_alchemy=False,breadth_changed=False,
   strategy_thresholds_changed=False,paper_only_unchanged=True),
 "ramses":dict(revision="public-observation-alchemy-active-cohort-v1",
   discovery_plane="official_robinhood_public_rpc",
   alchemy_role="candidate_state_active_cohort_costs_and_lifecycle_only",
   broad_factory_and_log_observation_on_alchemy=False,
   receipt_cost_scope="active_cohort_only",breadth_changed=False,
   strategy_thresholds_changed=False,paper_only_unchanged=True),
}
for lane,sha in heads.items():
    row=m["lanes"][lane]
    row["source_sha"]=sha
    row.pop("execution_sha",None)
    row["source_diff_sha256"]=hashes[lane]
    repairs=row.setdefault("repair_commits",[])
    if sha not in repairs: repairs.append(sha)
    row.setdefault("execution_certification",{})["provider_optimization"]=dict(
        source_commit=sha,**details[lane])
m["verified_at"]="2026-09-22-alchemy-optimization-composed-awaiting-certification"
m_path.write_text(json.dumps(m,indent=2)+"\n")
PY

while IFS= read -r -d '' path; do
  lower="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"
  if [[ "$lower" == *onfinality* ]]; then
    git rm -f -- "$path"
  fi
done < <(git ls-files -z)

cat > certification/provider_removal_gate.py <<'PY'
"""Fail closed if the retired Solana provider can re-enter active runtime/config."""
from __future__ import annotations
import argparse
from pathlib import Path

ACTIVE_SUFFIXES={".py",".pyw",".yml",".yaml",".json",".toml",".ini",".cfg",".sh"}
SKIP_PARTS={".git","__pycache__",".pytest_cache",".mypy_cache",".ruff_cache"}
NEEDLE="on"+"finality"

def scan(root):
    root=Path(root)
    bad=[]
    if not root.exists():
        return bad
    paths=[root] if root.is_file() else root.rglob("*")
    for path in paths:
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in ACTIVE_SUFFIXES:
            continue
        try:
            text=path.read_text(errors="strict")
        except (UnicodeDecodeError,OSError):
            continue
        if NEEDLE in text.lower():
            bad.append(str(path))
    return bad

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",action="append",required=True)
    args=p.parse_args()
    bad=sorted({x for root in args.root for x in scan(root)})
    if bad:
        raise SystemExit("retired_provider_reference:"+",".join(bad))
    print("no_retired_provider_references")

if __name__=="__main__":
    main()
PY

python - <<'PY'
from pathlib import Path
p=Path(".github/workflows/non-market-certification.yml")
s=p.read_text()
name="      - name: Reject retired provider references in prepared runtime\n"
if name not in s:
    marker='      - name: Preserve prepared runtime sources for repair inspection\n'
    if s.count(marker)!=1:
        raise SystemExit("non_market_workflow_prepare_marker_changed")
    step=(
      '      - name: Reject retired provider references in prepared runtime\n'
      '        run: >-\n'
      '          python -m certification.provider_removal_gate\n'
      '          --root "$RUNNER_TEMP/non-market-lanes/pump"\n'
      '          --root "$RUNNER_TEMP/non-market-lanes/meteora"\n'
      '          --root "$RUNNER_TEMP/non-market-lanes/pons"\n'
      '          --root "$RUNNER_TEMP/non-market-lanes/ramses"\n'
      '          --root "$GITHUB_WORKSPACE/certification"\n'
      '          --root "$GITHUB_WORKSPACE/.github/workflows"\n'
    )
    s=s.replace(marker,step+marker,1)
    p.write_text(s)
PY

python -m certification.run prepare --worktrees "$RUNNER_TEMP/finalize-lanes"
# The one-shot driver and trigger are not part of the canonical state.
git rm -f .github/workflows/finalize-alchemy-optimization.yml certification/finalize_alchemy_optimization.sh
python -m certification.provider_removal_gate   --root "$RUNNER_TEMP/finalize-lanes/pump"   --root "$RUNNER_TEMP/finalize-lanes/meteora"   --root "$RUNNER_TEMP/finalize-lanes/pons"   --root "$RUNNER_TEMP/finalize-lanes/ramses"   --root "$GITHUB_WORKSPACE/certification"   --root "$GITHUB_WORKSPACE/.github/workflows"

grep -q 'prefetch=False' "$RUNNER_TEMP/finalize-lanes/pump/tests/pump_acceleration_natural_prospective.py"
! grep -q 'prefetch=incremental' "$RUNNER_TEMP/finalize-lanes/pump/tests/pump_acceleration_natural_prospective.py"
grep -q 'pons_discovery_public_observation' "$RUNNER_TEMP/finalize-lanes/pons/robinhood_research/provider_topology.py"
grep -q 'configured_discovery_recovery_rpc' "$RUNNER_TEMP/finalize-lanes/pons/robinhood_research/provider_topology.py"
grep -q 'provider_role="public_observation"' "$RUNNER_TEMP/finalize-lanes/ramses/robinhood_research/ramses_universe.py"
grep -q 'receipt_cost_acquisition="active_cohort_only"' "$RUNNER_TEMP/finalize-lanes/ramses/robinhood_research/ramses_universe.py"

mkdir -p "$RUNNER_TEMP/finalize-evidence"
python -m unittest discover -s certification/tests -v 2>&1 | tee "$RUNNER_TEMP/finalize-evidence/supervisor.log"
python -m certification.run verify --worktrees "$RUNNER_TEMP/finalize-lanes" --output "$RUNNER_TEMP/finalize-evidence/deterministic"
python -m certification.non_market --worktrees "$RUNNER_TEMP/finalize-lanes" --output "$RUNNER_TEMP/finalize-evidence/offline"
python -m certification.restart_safety --worktrees "$RUNNER_TEMP/finalize-lanes" --output "$RUNNER_TEMP/finalize-evidence/restart-safety"
python -m certification.integrated_acceptance --worktrees "$RUNNER_TEMP/finalize-lanes" --output "$RUNNER_TEMP/finalize-evidence/integrated-acceptance"

git add certification .github/workflows/non-market-certification.yml .github/workflows/ci.yml
git diff --cached --check
git commit -m "[non-market-cert] [alchemy-optimization-finalized] Compose scarce-Alchemy provider topology"
git push origin HEAD:cert/non-market-e2e-20260922
