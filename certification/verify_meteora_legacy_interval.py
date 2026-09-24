"""Replay the retained Meteora legacy one-side interval from immutable run evidence.

No provider access. The caller supplies the digest-verified reconstruction projection ZIP
from workflow 35959153525. PYTHONPATH must point at the prepared Meteora worktree so this
script verifies the exact candidate lane source plus declared overlays.
"""
from __future__ import annotations
import argparse
import base64
import gzip
import json
from pathlib import Path
import struct
import zipfile

from meme_machine import dlmm
from meme_machine.dlmm_tape import reconstruct

RPC_PATH="certification-hourly/meteora/rpc-evidence.jsonl.gz"
POOL="FtwzPjTqoFuy8aF8bMBi7QF7UxpdYN5n9YUH6R7DcHjB"
START_ACCOUNTS_SEQUENCE=154
START_TIME_SEQUENCE=155
END_ACCOUNTS_SEQUENCE=157
END_TIME_SEQUENCE=158
SIGNATURE_SEQUENCE=153


def _result(record):
    response=record["response"]
    if isinstance(response,list):
        if len(response)!=1:
            raise ValueError("legacy_interval_ambiguous_single_response")
        response=response[0]
    return response["result"]


def _records(path):
    with zipfile.ZipFile(path) as archive:
        raw=gzip.decompress(archive.read(RPC_PATH)).decode()
    rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
    by_sequence={int(row["sequence"]):row for row in rows}
    return rows,by_sequence


def _snapshot(by_sequence,accounts_sequence,time_sequence):
    record=by_sequence[accounts_sequence]
    request=record["request"]
    if len(request)!=1 or request[0].get("method")!="getMultipleAccounts":
        raise ValueError("legacy_interval_snapshot_request_shape")
    keys=request[0]["params"][0]
    result=_result(record)
    values=result["value"]
    if len(keys)!=len(values) or keys[0]!=POOL:
        raise ValueError("legacy_interval_snapshot_identity")
    accounts=dict(zip(keys,values))
    indices=[]
    for key,value in accounts.items():
        if not value or value.get("owner")!=dlmm.PROGRAM:
            continue
        raw=base64.b64decode(value["data"][0])
        if len(raw)==10136:
            indices.append(struct.unpack_from("<q",raw,8)[0])
    market_time=int(_result(by_sequence[time_sequence]))
    return dict(
        network="solana-mainnet",commitment="finalized",kind="real",
        pool=POOL,slot=int(result["context"]["slot"]),
        market_time=market_time,available_time=market_time,
        array_indices=sorted(indices),accounts=accounts,
    )


def _transactions(rows,wanted):
    found={}
    for record in rows:
        request=record.get("request")
        if not isinstance(request,list):
            continue
        responses=record.get("response")
        responses=responses if isinstance(responses,list) else [responses]
        requested={item.get("id"):item for item in request}
        for response in responses:
            if not isinstance(response,dict):
                continue
            req=requested.get(response.get("id"))
            if not req or req.get("method")!="getTransaction":
                continue
            signature=(req.get("params") or [None])[0]
            if signature in wanted and response.get("result") is not None:
                found[signature]=response["result"]
    if set(found)!=set(wanted):
        raise ValueError("legacy_interval_transaction_evidence_missing")
    return found


def run(artifact):
    rows,by_sequence=_records(artifact)
    start_snapshot=_snapshot(
        by_sequence,START_ACCOUNTS_SEQUENCE,START_TIME_SEQUENCE)
    end_snapshot=_snapshot(
        by_sequence,END_ACCOUNTS_SEQUENCE,END_TIME_SEQUENCE)
    start=dlmm.validate(
        start_snapshot,start_snapshot["market_time"],"real")
    end=dlmm.validate(
        end_snapshot,end_snapshot["market_time"],"real")
    signatures=_result(by_sequence[SIGNATURE_SEQUENCE])
    selected=[
        row for row in signatures
        if start["slot"]<int(row["slot"])<=end["slot"] and not row.get("err")]
    boundary=max(
        (row for row in signatures if int(row["slot"])<=start["slot"]),
        key=lambda row:(int(row["slot"]),int(row["transactionIndex"])))
    census=sorted(
        selected+[boundary],
        key=lambda row:(int(row["slot"]),int(row["transactionIndex"])),
        reverse=True)
    wanted=[row["signature"] for row in selected]
    transactions=_transactions(rows,wanted)
    tape=reconstruct(
        start,end_snapshot,census,transactions,end_snapshot["market_time"],
        [start["slot"],2**31-1,2**31-1])
    if tape.terminal!=end:
        raise ValueError("legacy_interval_terminal_mismatch")
    kinds=[item.get("kind") for item in tape.terminal_adjustments]
    if kinds.count("add_liquidity_one_side")!=2:
        raise ValueError("legacy_interval_one_side_count")
    if kinds.count("remove_liquidity_by_range2")!=1:
        raise ValueError("legacy_interval_remove_count")
    if len(tape.events)!=1:
        raise ValueError("legacy_interval_swap_count")
    return dict(
        passed=True,pool=POOL,start_slot=start["slot"],end_slot=end["slot"],
        transaction_count=len(selected),swap_count=len(tape.events),
        adjustment_kinds=kinds,array_indices=start_snapshot["array_indices"],
        terminal_match=True,
    )


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--artifact",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    result=run(Path(args.artifact))
    Path(args.output).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
