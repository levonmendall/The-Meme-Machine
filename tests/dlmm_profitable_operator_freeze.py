"""Freeze the exact completed pre-PnL profitable-operator census artifact."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

SOURCE_RUN_ID=35422204122
SOURCE_COMMIT="4c9e5e07e7e1917011f8577fd8340636f18ec6f0"
SOURCE_ARTIFACT_ID=10578350403
SOURCE_ARTIFACT_DIGEST="sha256:f5f259673aaa5c4817ae79db3a966ca0af69251fc5aeba186e4d55cedecdd656"
SOURCE_REPORT_SHA256="6b7c520a2573dc1303f2bf58eadd49761935bcf2fe617aff72da1e881b9d090c"
EXPECTED_POOLS=112
EXPECTED_EVENTS=747
EXPECTED_WALLETS=200

OUT=Path("DLMM_PROFITABLE_OPERATOR_COHORT_V1.json")


def freeze(source):
    source=Path(source)
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_REPORT_SHA256:
        raise RuntimeError("dlmm_operator_source_report_hash_mismatch")
    report=json.loads(raw)
    required={
        "kind":"dlmm_profitable_operator_census_v1",
        "status":"candidate_cohort_ready",
        "pnl_data_read":False,
        "allocation_authority":False,
        "strategy_freeze_permitted":False,
        "pool_count":EXPECTED_POOLS,
        "completed_pools":EXPECTED_POOLS,
        "wallet_count":EXPECTED_WALLETS,
        "total_lp_actor_events":EXPECTED_EVENTS,
    }
    for key,value in required.items():
        if report.get(key)!=value:
            raise RuntimeError(f"dlmm_operator_source_boundary:{key}")
    source_wallets=report.get("wallets")
    if not isinstance(source_wallets,list) or len(source_wallets)!=EXPECTED_WALLETS:
        raise RuntimeError("dlmm_operator_source_wallet_shape")
    wallets=[]
    seen=set()
    for row in source_wallets:
        wallet=row.get("wallet") if isinstance(row,dict) else None
        if not isinstance(wallet,str) or not wallet or wallet in seen:
            raise RuntimeError("dlmm_operator_source_wallet_identity")
        seen.add(wallet);wallets.append({"wallet":wallet})
    canonical=json.dumps(wallets,sort_keys=True,separators=(",",":")).encode()
    body=dict(
        kind="dlmm_profitable_operator_cohort_v1",
        status="frozen_pre_pnl",
        scope="meme_machine_solana_dlmm_only",
        pnl_data_read_before_freeze=False,
        allocation_authority=False,
        strategy_freeze_permitted=False,
        cohort_hash=hashlib.sha256(canonical).hexdigest(),
        frozen_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
        source_census_run_id=SOURCE_RUN_ID,
        source_census_commit=SOURCE_COMMIT,
        source_artifact_id=SOURCE_ARTIFACT_ID,
        source_artifact_digest=SOURCE_ARTIFACT_DIGEST,
        source_report_sha256=SOURCE_REPORT_SHA256,
        source_protocol_sha256=report.get("protocol_sha256"),
        source_status=report.get("status"),
        source_pool_count=report.get("pool_count"),
        source_completed_pools=report.get("completed_pools"),
        source_total_lp_actor_events=report.get("total_lp_actor_events"),
        source_wallet_count=report.get("wallet_count"),
        freeze_rule=(
            "exactly every distinct wallet from the completed pre-PnL "
            "all-eligible-pool census; no additions, removals, reranking, or outcome filtering"
        ),
        wallets=wallets,
    )
    OUT.write_text(json.dumps(body,indent=2)+"\n")
    print(json.dumps(dict(
        cohort_hash=body["cohort_hash"],wallets=len(wallets),
        pools=body["source_pool_count"],events=body["source_total_lp_actor_events"],
        pnl_data_read_before_freeze=False,
    ),sort_keys=True))
    return body


def main():
    if len(sys.argv)!=2:
        raise SystemExit("usage: python -m tests.dlmm_profitable_operator_freeze <census.json>")
    freeze(sys.argv[1])


if __name__=="__main__":
    main()
