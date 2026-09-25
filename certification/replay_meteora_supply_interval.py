"""Read-only, narrow historical comparison against the final prepared Meteora lane.

No provider objects, strategy evaluation, entry or accounting mutation is invoked.
The retained signature prefix is not promoted to an independently complete census.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys


POOL = 'EjTLLhayt7s5F9iA143PsCbb9UzvzqG7Q3Q1KJTiLmWh'
MINT = '98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump'
START_SLOT, END_SLOT = 449870963, 449870974
SUPPLIES = (956208555432374, 956207960807047)
TRANSPORTS = {
    START_SLOT: 'd67b348d-26e0-4fed-9c4c-fc7d8f744d46:669',
    END_SLOT: 'd67b348d-26e0-4fed-9c4c-fc7d8f744d46:672',
}
PREFIX_CUTOFF_NS = 1790211061000000000


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def replay(raw_path, lane_root, expected_tape_hash=None):
    lane_root = Path(lane_root).resolve()
    raw_path = Path(raw_path).resolve()
    tape_path = lane_root / 'meme_machine/dlmm_tape.py'
    hashes = {name: sha256(lane_root / name) for name in (
        'meme_machine/dlmm.py', 'meme_machine/dlmm_tape.py')}
    if expected_tape_hash:
        require(hashes['meme_machine/dlmm_tape.py'] == expected_tape_hash,
                'final_lane_tape_hash_mismatch')
    sys.path.insert(0, str(lane_root))
    from meme_machine import dlmm, dlmm_tape
    from meme_machine.store import digest
    require(Path(dlmm.__file__).resolve() == lane_root / 'meme_machine/dlmm.py',
            'wrong_lane_dlmm_import')
    require(Path(dlmm_tape.__file__).resolve() == tape_path, 'wrong_lane_tape_import')

    endpoints, block_times, signatures, signature_reads = {}, {}, {}, []
    with gzip.open(raw_path, 'rt', encoding='utf-8') as handle:
        for line in handle:
            record = json.loads(line)
            observed_ns = record['observed_at_ns']
            if observed_ns > PREFIX_CUTOFF_NS:
                continue
            responses = record.get('response')
            responses = responses if isinstance(responses, list) else [responses]
            by_id = {row.get('id'): row for row in responses if isinstance(row, dict)}
            for request in record['request']:
                method, params = request['method'], request.get('params', [])
                response = by_id.get(request['id'], {})
                result = response.get('result')
                if method == 'getMultipleAccounts' and params and len(params[0]) > 1 \
                        and params[0][0] == POOL and isinstance(result, dict):
                    slot = result.get('context', {}).get('slot')
                    if slot not in TRANSPORTS:
                        continue
                    require(record['physical_request_id'] == TRANSPORTS[slot],
                            'unexpected_endpoint_transport')
                    require(slot not in endpoints, 'ambiguous_endpoint_snapshot')
                    require(not response.get('error') and not record.get('error')
                            and record.get('http_status') == 200, 'failed_endpoint_transport')
                    require(params[1].get('commitment') == 'finalized', 'endpoint_not_finalized')
                    require(len(params[0]) == len(result['value']), 'endpoint_account_count')
                    endpoints[slot] = dict(keys=params[0], values=result['value'],
                                           observed_ns=observed_ns,
                                           transport_id=record['physical_request_id'])
                elif method == 'getBlockTime' and params and params[0] in TRANSPORTS:
                    require(type(result) is int and not response.get('error'), 'block_time_missing')
                    prior = block_times.get(params[0])
                    require(prior is None or prior['time'] == result, 'conflicting_block_time')
                    block_times[params[0]] = dict(time=result, observed_ns=observed_ns)
                elif method == 'getSignaturesForAddress' and params and params[0] == POOL:
                    require(params[1].get('commitment') == 'finalized', 'signature_query_not_finalized')
                    require(isinstance(result, list) and not response.get('error')
                            and not record.get('error'), 'failed_signature_response')
                    signature_reads.append(dict(transport_id=record['physical_request_id'],
                                                observed_at_ns=observed_ns, rows=len(result)))
                    for row in result:
                        require(row.get('confirmationStatus') == 'finalized'
                                and type(row.get('slot')) is int, 'invalid_signature_evidence')
                        prior = signatures.get(row['signature'])
                        require(prior is None or prior['slot'] == row['slot'],
                                'conflicting_signature_slot')
                        signatures[row['signature']] = row

    require(set(endpoints) == set(TRANSPORTS) and set(block_times) == set(TRANSPORTS),
            'required_endpoint_evidence_missing')
    snapshots = {}
    for slot, endpoint in endpoints.items():
        accounts = dict(zip(endpoint['keys'], endpoint['values']))
        decoded = dlmm.pool(accounts[POOL])
        center = decoded['active'] // 70
        indices = [index for index in (center - 1, center, center + 1)
                   if accounts.get(dlmm.array_address(POOL, index)) is not None]
        snapshots[slot] = dict(pool=POOL, accounts=accounts, array_indices=indices, slot=slot,
            market_time=block_times[slot]['time'],
            available_time=max(endpoint['observed_ns'], block_times[slot]['observed_ns']) // 10**9,
            network='solana-mainnet', commitment='finalized', kind='real')
    start = dlmm.validate(snapshots[START_SLOT], snapshots[START_SLOT]['available_time'], 'real')
    end = dlmm.validate(snapshots[END_SLOT], snapshots[END_SLOT]['available_time'], 'real')
    start_copy = deepcopy(start)
    differences = sorted(key for key in start if key not in ('slot', 'time') and start[key] != end[key])
    require(differences == ['token_x_mint_info'], 'endpoint_difference_is_not_mint_metadata_only')
    mint_differences = sorted(key for key in start['token_x_mint_info']
                             if start['token_x_mint_info'][key] != end['token_x_mint_info'][key])
    require(mint_differences == ['supply'], 'mint_controls_changed')
    require(tuple(state['token_x_mint_info']['supply'] for state in (start, end)) == SUPPLIES,
            'captured_supply_values_changed')
    raw_mints = [base64.b64decode(snapshots[slot]['accounts'][MINT]['data'][0], validate=True)
                 for slot in (START_SLOT, END_SLOT)]
    require(len(raw_mints[0]) == len(raw_mints[1]) == 390, 'mint_account_size_changed')
    changed_offsets = [index for index, values in enumerate(zip(*raw_mints)) if values[0] != values[1]]
    require(changed_offsets == [36, 37, 38, 39], 'raw_mint_change_outside_expected_supply_bytes')
    selected = [row for row in signatures.values()
                if START_SLOT < row['slot'] <= END_SLOT and not row.get('err')]
    require(not selected, 'retained_prefix_contains_successful_pool_transaction')
    witnesses = [row for row in signatures.values() if row['slot'] <= START_SLOT]
    require(witnesses, 'retained_lower_boundary_missing')
    witness = dict(max(witnesses, key=lambda row: (row['slot'], row['signature'])))
    require(witness['slot'] == 449870908, 'unexpected_lower_boundary')
    # Same lower-witness convention as the native census; the witness is not replayed.
    witness_index_defaulted = type(witness.get('transactionIndex')) is not int
    if witness_index_defaulted:
        witness['transactionIndex'] = 0
    tape = dlmm_tape.reconstruct(start, snapshots[END_SLOT], [witness], {},
        snapshots[END_SLOT]['available_time'], [START_SLOT, 2**31 - 1, 2**31 - 1])
    require(start == start_copy, 'reconstruction_mutated_start_state')
    require(tape.terminal == end and tape.start_hash == digest(start)
            and tape.end_hash == digest(end), 'authenticated_terminal_not_preserved')
    require(not tape.events and not tape.terminal_adjustments, 'unexpected_pool_action')
    require(signature_reads, 'retained_signature_prefix_missing')
    last_signature_read = max(signature_reads, key=lambda row: row['observed_at_ns'])
    return dict(schema='meteora-supply-historical-replay-v1', status='pass',
        predecessor_run_id=35935431384,
        predecessor_runtime_sha='c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66',
        raw_evidence_sha256=sha256(raw_path), final_lane_file_sha256=hashes,
        slots=[START_SLOT, END_SLOT], endpoint_transport_ids=TRANSPORTS,
        supply_values=list(SUPPLIES), supply_delta=SUPPLIES[1]-SUPPLIES[0],
        raw_mint_changed_byte_offsets=changed_offsets, supply_only_endpoint_difference_proved=True,
        all_other_mint_and_pool_fields_unchanged=True,
        reconstructed_from_retained_inputs=True, current_reconstruction='pass',
        terminal_hash=tape.end_hash, lineage_hash=tape.lineage,
        selected_successful_pool_transactions_in_retained_prefix=0,
        lower_boundary_slot=witness['slot'], lower_witness_index_defaulted=witness_index_defaulted,
        last_retained_signature_read=last_signature_read,
        signature_read_after_end_account_observation=any(
            row['observed_at_ns'] >= endpoints[END_SLOT]['observed_ns'] for row in signature_reads),
        independent_complete_signature_census_claimed=False,
        limitation='Retained native signature prefix only; no independent post-endpoint complete census or new chain reauthentication.',
        strategy_evaluations=0, entries_created=0, provider_calls=0, accounting_mutations=0,
        historical_block_admission_changed=False, predecessor_hour_remains_censored=True,
        complete_historical_warmup_recovered=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-evidence', required=True)
    parser.add_argument('--lane-root', required=True)
    parser.add_argument('--expected-dlmm-tape-sha256')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        result = replay(args.raw_evidence, args.lane_root, args.expected_dlmm_tape_sha256)
        code = 0
    except Exception as exc:
        result = dict(schema='meteora-supply-historical-replay-v1', status='fail',
                      error_type=type(exc).__name__, reason=str(exc)[:200],
                      historical_block_admission_changed=False, provider_calls=0, entries_created=0)
        code = 1
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n'
    if args.output:
        Path(args.output).write_text(encoded)
    sys.stdout.write(encoded)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
