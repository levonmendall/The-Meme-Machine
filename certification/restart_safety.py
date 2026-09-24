"""Deterministic fail-closed restart safety against the exact prepared lane runtimes.

This is intentionally not a claim that every lane can reconstruct volatile controller
context and resume trading automatically. It proves the safety contract that a restart
cannot silently discard durable exposure or start a fresh campaign over it.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

LANES=("pump","pons","meteora","ramses")

PROBES={
"pump": r'''
from pathlib import Path
import tempfile
from tests import pump_acceleration_natural_prospective as m
from meme_machine.paper_accounting import PaperBook
with tempfile.TemporaryDirectory() as td:
    m.REPORT=Path(td)/"pump.json"
    path=m.REPORT.with_suffix(".accounting.sqlite3")
    b=PaperBook(str(path),run_id="restart-contract",lane=m.STRATEGY_ID,
                policy_hash=m.policy_hash(),initial=m.INITIAL_LAMPORTS)
    before=b.reconcile();b.db.close()
    try:
        m.main(campaign=True,discovery_seconds=600)
    except RuntimeError as exc:
        assert str(exc)=="existing_paper_book_requires_explicit_recovery",str(exc)
    else:
        raise AssertionError("pump_restart_guard_missing")
    b=PaperBook(str(path),run_id="restart-contract",lane=m.STRATEGY_ID,
                policy_hash=m.policy_hash(),initial=m.INITIAL_LAMPORTS)
    assert b.reconcile()==before
    b.db.close()
print("PROVEN")
''',
"pons": r'''
from pathlib import Path
import tempfile
from robinhood_research import BoundaryError
from robinhood_research import pons_selective_cohort as m
with tempfile.TemporaryDirectory() as td:
    root=Path(td)
    sentinel=root/"trial-001.sqlite"
    sentinel.write_bytes(b"durable-state")
    m.ROOT=root
    try:
        m.run("",campaign=True)
    except BoundaryError as exc:
        assert str(exc)=="selective_existing_run_requires_explicit_recovery",str(exc)
    else:
        raise AssertionError("pons_restart_guard_missing")
    assert sentinel.read_bytes()==b"durable-state"
print("PROVEN")
''',
"meteora": r'''
from pathlib import Path
import os,tempfile
from unittest.mock import patch
from tests import solana_dlmm_independent_v1 as m
from meme_machine.dlmm_independent_accounting import PaperBook
from meme_machine.provider import Unavailable
class Broker:
    def __init__(self,*a,**k):pass
    def stream_status(self,*a,**k):return {}
    def telemetry(self):return {}
    def close(self):pass
class Wake:
    def __init__(self,*a,**k):pass
    def run(self,stop,ready):ready.set()
with tempfile.TemporaryDirectory() as td:
    m.OUT=Path(td)/"meteora.json"
    policy=m.load_policy();ph=m.digest(policy)
    path=m.OUT.with_suffix(".accounting.sqlite3")
    book=PaperBook(path,run_id="restart-contract",policy_hash=ph,capital=1_000_000_000)
    ident=book.identity();book.append(ident,"reserve",dict(amount=1_000_000))
    before=book.reconcile()
    with patch.dict(os.environ,{"MM_CERTIFICATION_RUN_ID":"restart-contract"}),\
         patch.object(m,"_prove_network_identity",return_value={"verified":True}),\
         patch.object(m,"EvidenceBroker",Broker),\
         patch.object(m,"ProgramAccountWakeStream",Wake),\
         patch.object(m,"_campaign_candidates",return_value=(row for row in [{"address":"candidate"}])):
        try:
            m.run_live(target=1,max_attempted=1,max_runtime_seconds=60,campaign=True)
        except Unavailable as exc:
            assert str(exc)=="solana_dlmm_unresolved_position_blocks_new_admission",str(exc)
        else:
            raise AssertionError("meteora_restart_guard_missing")
    reopened=PaperBook(path,run_id="restart-contract",policy_hash=ph,capital=1_000_000_000)
    assert reopened.reconcile()==before
print("PROVEN")
''',
"ramses": r'''
from pathlib import Path
import tempfile
from robinhood_research import BoundaryError
from robinhood_research.ramses_campaign import CampaignBooks
with tempfile.TemporaryDirectory() as td:
    root=Path(td)/"campaign";root.mkdir()
    sentinel=root/"capital-manifest.json";sentinel.write_text("durable-state")
    try:
        CampaignBooks(root,{})
    except BoundaryError as exc:
        assert str(exc)=="ramses_campaign_existing_capital_requires_recovery",str(exc)
    else:
        raise AssertionError("ramses_restart_guard_missing")
    assert sentinel.read_text()=="durable-state"
print("PROVEN")
''',
}

def run(worktrees,output):
    roots=Path(worktrees).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    rows={}
    for lane in LANES:
        proc=subprocess.run([sys.executable,"-c",PROBES[lane]],cwd=roots/lane,
                            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        log=out/(lane+".log");log.write_text(proc.stdout)
        rows[lane]=dict(exit_code=proc.returncode,proven=(proc.returncode==0 and "PROVEN" in proc.stdout),
                        log=log.name)
    result=dict(
        scope="production_runner_restart_safety",
        passed=all(r["proven"] for r in rows.values()),
        lanes=rows,
        contract=(
            "durable pre-existing lane state is preserved and fresh campaign admission "
            "fails closed; automatic volatile-controller reconstruction is not inferred"
        ),
        natural_market_required=False,
    )
    (out/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0 if result["passed"] else 1

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--worktrees",required=True);p.add_argument("--output",required=True)
    a=p.parse_args();raise SystemExit(run(a.worktrees,a.output))
