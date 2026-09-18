"""Targeted read-only probe for natural DLMM hosted-swap transaction shapes.

This exists only to diagnose the two live host-fee attribution failures observed in
run 35367056432. It uses the same Alchemy route and bounded finalized census as the
normal verifier, and writes public-chain transaction structure only.
"""
from __future__ import annotations

import json
from pathlib import Path

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import (
    EVENT_CPI, SWAP, SWAP2, EXACT_SWAP, EXACT_SWAP_NAME,
    _event_pool, _keys, _ordered_instructions, _un58_data,
    decode_swap, decode_swap2,
)
from tests import dlmm_alchemy_provider as alchemy_provider
from tests.dlmm_boundary_acquisition import _fetch_transaction_bodies


class HistoricalAlchemyRPC(alchemy_provider.AlchemyPoolScanRPC):
    ALLOWED = alchemy_provider.AlchemyPoolScanRPC.ALLOWED | {"getBlock"}

OUT = Path("dlmm-host-fee-shape-probe.json")
INTERVALS = (
    dict(
        name="STONK-SOL",
        pool="zxTpi4BtaWX3mgdAPoezkMD1hxx8CdeCfrqXMWvSCLX",
        start_slot=448133924,
        end_slot=448133940,
    ),
    dict(
        name="USELESS-SOL",
        pool="8ztFxjFPfVUtEf4SLSapcFj8GW2dxyUA9no2bLPq7H7V",
        start_slot=448133985,
        end_slot=448134018,
    ),
)


def _balance_rows(meta):
    rows = {}
    for side in ("preTokenBalances", "postTokenBalances"):
        by_index = {}
        for row in meta.get(side) or []:
            idx = row.get("accountIndex")
            token = row.get("uiTokenAmount") or {}
            amount = token.get("amount")
            if type(idx) is int and isinstance(row.get("mint"), str) and isinstance(amount, str):
                by_index[idx] = dict(
                    mint=row["mint"],
                    owner=row.get("owner"),
                    amount=amount,
                )
        rows[side] = by_index
    return rows


def _instruction_summary(order, ix, keys, pool):
    program_index = ix.get("programIdIndex")
    if type(program_index) is not int or not 0 <= program_index < len(keys):
        return dict(order=order, error="bad_program_index")
    program = keys[program_index]
    accounts = ix.get("accounts") or []
    resolved = [
        keys[i] if type(i) is int and 0 <= i < len(keys) else None
        for i in accounts
    ]
    raw = _un58_data(ix.get("data") or "")
    item = dict(
        order=list(order),
        program=program,
        accounts=resolved,
        account_indexes=accounts,
        data_hex=raw.hex(),
    )
    if program == dlmm.PROGRAM:
        item["dlmm_discriminator"] = raw[:8].hex() if len(raw) >= 8 else raw.hex()
        if raw[:8] in EXACT_SWAP and accounts:
            item["dlmm_instruction"] = EXACT_SWAP_NAME[raw[:8]]
            item["target_pool_call"] = resolved[0] == pool
            if len(resolved) > 9:
                item["host_fee_account"] = resolved[9]
                item["user_token_in"] = resolved[4]
                item["reserve_x"] = resolved[2]
                item["reserve_y"] = resolved[3]
                item["token_x_mint"] = resolved[6]
                item["token_y_mint"] = resolved[7]
        elif raw[:8] == EVENT_CPI and raw[8:16] in (SWAP, SWAP2):
            event_pool = _event_pool(raw)
            item["event_pool"] = event_pool
            if event_pool == pool:
                try:
                    ev = decode_swap(raw[8:], pool) if raw[8:16] == SWAP else decode_swap2(raw[8:], pool)
                    item["event"] = ev
                except Exception as exc:
                    item["event_error"] = str(exc)
    elif program == pump.TOKEN_PROGRAM and raw:
        tag = raw[0]
        item["token_instruction_tag"] = tag
        if tag == 3 and len(raw) == 9 and len(resolved) >= 2:
            item["token_transfer"] = dict(
                kind="transfer",
                source=resolved[0],
                destination=resolved[1],
                amount=int.from_bytes(raw[1:9], "little"),
            )
        elif tag == 12 and len(raw) == 10 and len(resolved) >= 3:
            item["token_transfer"] = dict(
                kind="transfer_checked",
                source=resolved[0],
                mint=resolved[1],
                destination=resolved[2],
                amount=int.from_bytes(raw[1:9], "little"),
                decimals=raw[9],
            )
    return item


def run():
    pacer = alchemy_provider.AlchemyPacer()
    rpc = HistoricalAlchemyRPC(
        alchemy_provider.rpc_url(), limit=240, pacer=pacer
    )
    if rpc.call("getGenesisHash", priority=True) != pump.MAINNET:
        raise RuntimeError("host_shape_probe_wrong_network")
    report = dict(
        kind="dlmm_host_fee_shape_probe_v1",
        allocation_authority=False,
        intervals=[],
    )
    for interval in INTERVALS:
        telemetry = dict(
            method="finalized_getBlock_accounts_exact_slots",
            blocks=[],
        )
        relevant = []
        for slot in range(interval["start_slot"] + 1, interval["end_slot"] + 1):
            block = rpc.call("getBlock", [slot, dict(
                commitment="finalized",
                encoding="json",
                transactionDetails="accounts",
                maxSupportedTransactionVersion=0,
                rewards=False,
            )], True)
            if block is None:
                telemetry["blocks"].append(dict(slot=slot,missing=True))
                continue
            matches = 0
            for transaction_index, row in enumerate(block.get("transactions") or []):
                tx = row.get("transaction") or {}
                keys = []
                for item in tx.get("accountKeys") or []:
                    key = item.get("pubkey") if isinstance(item, dict) else item
                    if isinstance(key, str):
                        keys.append(key)
                if interval["pool"] not in keys or (row.get("meta") or {}).get("err"):
                    continue
                signatures = tx.get("signatures") or []
                if not signatures or not isinstance(signatures[0], str):
                    raise RuntimeError("host_shape_probe_block_signature_shape")
                relevant.append(dict(
                    signature=signatures[0],
                    slot=slot,
                    transactionIndex=transaction_index,
                    err=None,
                    confirmationStatus="finalized",
                ))
                matches += 1
            telemetry["blocks"].append(dict(
                slot=slot,
                matching_successful_transactions=matches,
                transaction_rows=len(block.get("transactions") or []),
            ))
        telemetry["transaction_count"] = len(relevant)
        if not relevant:
            raise RuntimeError("host_shape_probe_no_matching_transactions")
        txs = _fetch_transaction_bodies(rpc, relevant, telemetry)
        rows = []
        for sig, tx in zip(relevant, txs):
            meta = tx["meta"]
            message = tx["transaction"]["message"]
            keys = _keys(meta, message)
            instructions = [
                _instruction_summary((outer, inner), ix, keys, interval["pool"])
                for outer, inner, ix in _ordered_instructions(meta, message)
            ]
            rows.append(dict(
                signature=sig["signature"],
                slot=sig["slot"],
                transaction_index=sig["transactionIndex"],
                block_time=tx.get("blockTime"),
                account_keys=keys,
                token_balances=_balance_rows(meta),
                instructions=instructions,
            ))
        report["intervals"].append(dict(
            **interval,
            census=telemetry,
            transactions=rows,
        ))
    report.update(
        rpc_calls=rpc.calls,
        rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,
        pacer=pacer.telemetry(),
    )
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(
        intervals=len(report["intervals"]),
        transactions=sum(len(x["transactions"]) for x in report["intervals"]),
        rpc_calls=rpc.calls,
        rpc_failures=rpc.failures,
    ), sort_keys=True))
    return report


if __name__ == "__main__":
    run()
