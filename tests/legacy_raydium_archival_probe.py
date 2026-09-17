"""One bounded archival attempt to recover an old Pump -> Raydium migration.

This is research-only. It uses public read-only endpoints, writes only a local JSON
report/capture for CI artifact retention, and has no Store/order/allocation/signing or
transaction-submission authority.

Method:
1. Ask DexScreener for the exact creation timestamp of the already-known Fartcoin
   Raydium-v4 pair.
2. Page *only* the old Pump withdraw/migrator address history until that timestamp.
3. Fetch only successful signatures in a narrow +/- 1 hour window around pair creation.
4. Require the same finalized transaction to link the target mint, target pool, old
   migrator, Pump program, Raydium AMM-v4, and Raydium initialize2 log. A Pump
   `Instruction: Withdraw` log is recorded separately and required for the strongest
   direct-lineage classification.

No threshold, strategy, registry, or allocation state is changed by this diagnostic.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

from meme_machine import pump
from meme_machine.postgrad import RAYDIUM_AMM_V4
from meme_machine.provider import RPC, Unavailable

MINT = '9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump'
POOL = 'Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw'
OLD_MIGRATOR = '39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg'
DEXSCREENER = f'https://api.dexscreener.com/latest/dex/pairs/solana/{POOL}'
REPORT = Path('legacy-raydium-archival-report.json')
CAPTURE = Path('legacy-raydium-archival-capture.json')
WINDOW_SECONDS = 3600
MAX_SIGNATURE_PAGES = 180
MAX_TRANSACTION_CANDIDATES = 96


def _pair_created_at():
    req = urllib.request.Request(DEXSCREENER, headers={'User-Agent':'The-Meme-Machine/archival-proof'})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise RuntimeError('dexscreener_response_size_limit')
    doc = json.loads(raw)
    pairs = doc.get('pairs') or []
    exact = [row for row in pairs if row.get('pairAddress') == POOL]
    if len(exact) != 1:
        raise RuntimeError('dexscreener_pair_identity')
    created = exact[0].get('pairCreatedAt')
    if not isinstance(created, (int, float)) or created <= 0:
        raise RuntimeError('dexscreener_pair_created_at_missing')
    return int(created)//1000


def _pubkey(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('pubkey') or value.get('address')
    return None


def _keys(tx):
    message = ((tx or {}).get('transaction') or {}).get('message') or {}
    keys = {_pubkey(value) for value in message.get('accountKeys') or []}
    loaded = ((tx or {}).get('meta') or {}).get('loadedAddresses') or {}
    keys.update(loaded.get('writable') or [])
    keys.update(loaded.get('readonly') or [])
    keys.discard(None)
    return keys


def _analyze(signature_row, tx, target):
    meta = (tx or {}).get('meta') or {}
    logs = meta.get('logMessages') or []
    keys = _keys(tx)
    lower = '\n'.join(logs).lower()
    success = bool(tx) and meta.get('err') is None
    flags = {
        'success': success,
        'mint_present': MINT in keys,
        'pool_present': POOL in keys,
        'old_migrator_present': OLD_MIGRATOR in keys or OLD_MIGRATOR in '\n'.join(logs),
        'pump_program_present': pump.PROGRAM in keys or pump.PROGRAM in '\n'.join(logs),
        'raydium_v4_present': RAYDIUM_AMM_V4 in keys or RAYDIUM_AMM_V4 in '\n'.join(logs),
        'raydium_initialize2_log': 'initialize2' in lower and 'initializeinstruction2' in lower,
        'pump_withdraw_log': 'instruction: withdraw' in lower,
    }
    same_tx_link = all(flags[name] for name in (
        'success', 'mint_present', 'pool_present', 'old_migrator_present',
        'pump_program_present', 'raydium_v4_present', 'raydium_initialize2_log'))
    direct = same_tx_link and flags['pump_withdraw_log']
    return {
        'signature': signature_row['signature'],
        'slot': int((tx or {}).get('slot') or signature_row.get('slot') or 0),
        'block_time': (tx or {}).get('blockTime', signature_row.get('blockTime')),
        'seconds_from_pair_created_at': (
            None if signature_row.get('blockTime') is None
            else int(signature_row['blockTime']) - target),
        'flags': flags,
        'same_transaction_migration_link': same_tx_link,
        'direct_pump_withdraw_lineage_verified': direct,
    }


def main():
    started = int(time.time())
    url = os.environ.get('MM_SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
    rpc = RPC(url, limit=240)
    report = {
        'kind': 'targeted_legacy_pump_raydium_archival_attempt',
        'network': 'solana-mainnet',
        'mint': MINT,
        'pool': POOL,
        'old_migrator': OLD_MIGRATOR,
        'authority': 'read_only_research_only',
        'allocation_enabled': False,
        'order_authority': False,
        'signing_authority': False,
        'transaction_submission_authority': False,
        'live_money_authority': False,
        'profitability_evidence': False,
        'provider_spend_usd': 0 if url == 'https://api.mainnet-beta.solana.com' else None,
        'infrastructure_spend_usd': 0,
        'started': started,
    }
    capture = {}
    try:
        if rpc.call('getGenesisHash', priority=True) != pump.MAINNET:
            raise Unavailable('unsupported_network')
        target = _pair_created_at()
        report['pair_created_at'] = target
        report['window_start'] = target - WINDOW_SECONDS
        report['window_end'] = target + WINDOW_SECONDS

        before = None
        pages = 0
        signatures_seen = 0
        candidate_rows = []
        oldest_seen = newest_seen = None
        reached_window = False
        passed_window = False

        while pages < MAX_SIGNATURE_PAGES:
            options = {'limit':1000, 'commitment':'finalized'}
            if before:
                options['before'] = before
            rows = rpc.call('getSignaturesForAddress', [OLD_MIGRATOR, options], priority=True)
            pages += 1
            if not rows:
                break
            signatures_seen += len(rows)
            times = [int(r['blockTime']) for r in rows if r.get('blockTime') is not None]
            if times:
                page_newest, page_oldest = max(times), min(times)
                newest_seen = page_newest if newest_seen is None else max(newest_seen, page_newest)
                oldest_seen = page_oldest if oldest_seen is None else min(oldest_seen, page_oldest)
                if page_oldest <= target + WINDOW_SECONDS and page_newest >= target - WINDOW_SECONDS:
                    reached_window = True
                    candidate_rows.extend(
                        r for r in rows
                        if r.get('blockTime') is not None
                        and target-WINDOW_SECONDS <= int(r['blockTime']) <= target+WINDOW_SECONDS
                        and not r.get('err'))
                if page_newest < target - WINDOW_SECONDS:
                    passed_window = True
                    break
                if page_oldest < target - WINDOW_SECONDS:
                    passed_window = True
                    break
            before = rows[-1]['signature']
            if len(rows) < 1000:
                break

        # De-duplicate and examine closest signatures first. Bound transaction bodies
        # so this cannot turn into an unbounded historical scrape.
        unique = {row['signature']:row for row in candidate_rows}
        ordered = sorted(
            unique.values(),
            key=lambda row: abs(int(row.get('blockTime') or 0)-target),
        )[:MAX_TRANSACTION_CANDIDATES]
        available = max(0, rpc.limit-rpc.calls)
        ordered = ordered[:available]
        params = [[row['signature'], {
            'encoding':'json', 'commitment':'finalized',
            'maxSupportedTransactionVersion':0,
        }] for row in ordered]
        txs = rpc.call_many('getTransaction', params, True, batch_size=8) if params else []
        analyses = [_analyze(row, tx, target) for row, tx in zip(ordered, txs)]
        strongest = [row for row in analyses if row['direct_pump_withdraw_lineage_verified']]
        linked = [row for row in analyses if row['same_transaction_migration_link']]

        report.update(
            success=bool(strongest),
            direct_pump_withdraw_lineage_verified=bool(strongest),
            same_transaction_migration_link_found=bool(linked),
            signatures_pages=pages,
            signatures_seen=signatures_seen,
            reached_target_window=reached_window,
            passed_target_window=passed_window,
            candidate_signatures_in_window=len(unique),
            transaction_candidates_examined=len(analyses),
            newest_migrator_time_seen=newest_seen,
            oldest_migrator_time_seen=oldest_seen,
            matches=strongest,
            partial_same_transaction_links=linked,
        )
        if strongest:
            match_sig = strongest[0]['signature']
            match_index = next(i for i,row in enumerate(ordered) if row['signature'] == match_sig)
            capture = {
                'kind':'captured_legacy_pump_raydium_migration_transaction',
                'classification':'direct_lineage_candidate',
                'analysis':strongest[0],
                'transaction':txs[match_index],
            }
        elif linked:
            match_sig = linked[0]['signature']
            match_index = next(i for i,row in enumerate(ordered) if row['signature'] == match_sig)
            capture = {
                'kind':'captured_legacy_pump_raydium_same_transaction_link',
                'classification':'missing_explicit_pump_withdraw_log',
                'analysis':linked[0],
                'transaction':txs[match_index],
            }
        else:
            report['limitation'] = (
                'No transaction satisfying the strict lineage predicate was recovered within the '
                'single bounded public-RPC attempt. This does not disprove historical lineage.'
            )
    except Exception as exc:
        report.update(
            success=False,
            direct_pump_withdraw_lineage_verified=False,
            error=f'{type(exc).__name__}:{str(exc)}',
        )
    finally:
        report.update(
            ended=int(time.time()),
            rpc_logical_requests=rpc.calls,
            rpc_transport_requests=rpc.http_requests,
            rpc_failures=rpc.failures,
            rpc_retries=rpc.retries,
            rpc_failure_kinds=dict(rpc.failure_kinds),
        )
        REPORT.write_text(json.dumps(report, sort_keys=True))
        CAPTURE.write_text(json.dumps(capture, sort_keys=True))
        print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
