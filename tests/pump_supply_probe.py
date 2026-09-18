"""Read-only exact-mint probe for the active supply_mismatch boundary."""
import json
from pathlib import Path

from meme_machine import pump
from meme_machine.provider import RPC

MINT="BWYKzx8U3YARs8beJWidqmyb5Boc6V3Ei1mfnMkwpump"
REPORT=Path("pump-supply-probe.json")


def main():
    rpc=RPC("https://api.mainnet-beta.solana.com",limit=40)
    if rpc.call("getGenesisHash",priority=True) != pump.MAINNET:
        raise SystemExit("wrong_network")
    pool=pump.pda([b"bonding-curve",pump.un58(MINT)])
    fee=pump.pda([b"fee_config",pump.un58(pump.PROGRAM)],pump.FEE_PROGRAM)
    result=rpc.call(
        "getMultipleAccounts",
        [[pool,MINT,fee],{"encoding":"base64","commitment":"finalized"}],
        priority=True,
    )
    accounts=result["value"]
    if len(accounts)!=3 or any(x is None for x in accounts):
        raise SystemExit("missing_accounts")
    curve=pump.curve(accounts[0])
    mode=pump.curve_mode(accounts[0])
    supply,decimals=pump.mint_info(accounts[1])
    current_validation="accepted"
    try:
        pump.validate_mint_supply(accounts[0],curve,supply,decimals)
    except ValueError as exc:
        current_validation=str(exc)

    max_supply=curve.supply + (
        pump.MAYHEM_EXTRA_WHOLE_TOKENS*(10**decimals) if mode["mayhem"] else 0
    )
    burn_aware_valid=(
        decimals==6 and
        curve.real_token <= supply <= max_supply
    )
    report=dict(
        network="solana-mainnet",
        commitment="finalized",
        slot=int(result["context"]["slot"]),
        mint=MINT,
        bonding_curve=pool,
        bonding_curve_account_bytes=len(__import__("base64").b64decode(accounts[0]["data"][0])),
        mint_account_bytes=len(__import__("base64").b64decode(accounts[1]["data"][0])),
        mint_owner=accounts[1]["owner"],
        decimals=decimals,
        is_mayhem_mode=mode["mayhem"],
        is_cashback_coin=mode["cashback"],
        quote_mint=mode["quote_mint"],
        curve_token_total_supply=curve.supply,
        current_mint_supply=supply,
        supply_minus_curve_total=supply-curve.supply,
        curve_real_token_reserves=curve.real_token,
        curve_complete=curve.complete,
        current_validator_result=current_validation,
        burn_aware_lower_bound=curve.real_token,
        burn_aware_upper_bound=max_supply,
        burn_aware_bound_valid=burn_aware_valid,
        primary_rpc_logical=rpc.calls,
        primary_rpc_transport=rpc.http_requests,
        primary_rpc_failures=rpc.failures,
        primary_rpc_retries=rpc.retries,
        paper_only=True,
        signing_authority=False,
        submission_authority=False,
    )
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True))
    print(json.dumps(report,sort_keys=True))
    if current_validation != "supply_mismatch":
        raise SystemExit("expected_exact_boundary_not_reproduced")
    if not burn_aware_valid:
        raise SystemExit("burn_aware_bound_does_not_explain_mismatch")


if __name__=="__main__":
    main()
