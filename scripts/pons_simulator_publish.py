#!/usr/bin/env python3
"""Independent read-only simulator export and separate authenticated publication.

No ledger mutation, market request, runtime start or protection dependency.
Invoke once, or --repeat for a bounded 30-second publication interval.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from meme_machine.operational import pons_simulator as simulator
from dashboard import simulator as contract

PUBLICATION = simulator.EXPERIMENT / 'publication'
CAPTURES = simulator.EXPERIMENT / 'capture'
ENDPOINT = 'https://meme-machine-dashboard-staging.onrender.com/api/pons-simulator/snapshot'
EXPERIMENT_ID = 'pons-simulator-20261024'


def need(value):
    if not value:
        raise ValueError('publisher_boundary')


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def private(path, maximum=contract.MAX_BYTES):
    simulator.physical(path)
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
         and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1 and before.st_size <= maximum)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid,
        s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        need(identity(os.fstat(fd)) == identity(before))
        raw = os.read(fd, maximum + 1)
        need(len(raw) == before.st_size and identity(os.fstat(fd)) == identity(before)
             and identity(path.lstat()) == identity(before))
        return raw, before.st_mtime
    finally:
        os.close(fd)


def read_json(path, maximum=contract.MAX_BYTES):
    raw, at = private(path, maximum)
    return contract.decode_snapshot(raw), at


def atomic(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    need(len(raw) <= contract.MAX_BYTES)
    temporary = path.parent / ('.publish-' + os.urandom(8).hex())
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def sequence():
    simulator.physical(PUBLICATION)
    if not PUBLICATION.exists():
        PUBLICATION.mkdir(mode=0o700)
    info = PUBLICATION.lstat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700)
    fd = os.open(PUBLICATION / 'publisher.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = PUBLICATION / 'sequence.json'
        previous = read_json(path, 128)[0] if path.exists() or path.is_symlink() else {'sequence': 0}
        need(type(previous) is dict and set(previous) == {'sequence'}
             and type(previous['sequence']) is int and 0 <= previous['sequence'] < 2**63 - 1)
        current = previous['sequence'] + 1
        atomic(path, dict(sequence=current))
        yield current
    finally:
        os.close(fd)


def metric(value, unit, at):
    return dict(value=None if value is None else format(Decimal(str(value)), 'f'),
        quality='UNAVAILABLE' if value is None else 'MEASURED', unit=unit,
        as_of=None if value is None else at)


def observation():
    if not CAPTURES.exists():
        return None, None, 'UNKNOWN'
    simulator.physical(CAPTURES)
    attempts = list(CAPTURES.iterdir())
    need(len(attempts) <= 256)
    attempts = sorted(p for p in attempts if re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{16}', p.name))
    if not attempts:
        return None, None, 'UNKNOWN'
    latest = attempts[-1]
    simulator.physical(latest)
    # An unfinished newer attempt never makes an older failed sample current.
    if not (latest / 'capture-summary.json').exists() or not (latest / 'process-receipt.json').exists():
        return None, None, 'UNKNOWN'
    capture, stamp = read_json(latest / 'capture-summary.json', 1024 * 1024)
    receipt, _ = read_json(latest / 'process-receipt.json')
    need(capture.get('schema') == 'pons-simulator-public-intake-v1'
         and receipt.get('schema') == 'pons-simulator-public-process-v1'
         and receipt.get('capture_directory') == str(latest) and receipt.get('child_joined') is True
         and capture.get('financial_authority') is False and receipt.get('financial_authority') is False)
    failed = capture.get('failure') is not None or receipt.get('child_exit_code') != 0
    return capture, utc(stamp), 'FAILED' if failed else 'STOPPED'


def build(current, source_commit):
    book = simulator.export_state()
    portfolio = book['portfolio']
    at = portfolio['as_of']
    balances = portfolio['balances']
    groups = {group: {} for group in contract.METRICS}
    def put(group, name, value, stamp=at):
        groups[group][name] = metric(value, contract.METRICS[group][name], stamp)
    for name, key in (('cash', 'available_cash'), ('reserved', 'reserved_cash'),
            ('deployed', 'deployed_capital'), ('realized_pnl', 'realized_pnl'),
            ('unrealized_pnl', 'unrealized_pnl'), ('equity', 'equity'), ('fees', 'fees')):
        put('financial', name, balances.get(key))
    put('financial', 'starting_capital', portfolio['shared_capital']['inception_equity'])
    positions = portfolio['positions']
    retired = portfolio['retired_regime_totals'].get('pons_current', {}).get('count', 0)
    empty = not positions and retired == 0
    put('activity', 'open_positions', book['obligations']['positions_open'])
    if empty:
        for name in ('entries', 'exits', 'round_trips', 'winners', 'losers'):
            put('activity', name, 0)
    capture, observed_at, execution = observation()
    reasons = ['PROTECTION_UNAVAILABLE', 'MEASUREMENT_UNAVAILABLE']
    if capture is None:
        reasons.append('INPUT_UNAVAILABLE')
    else:
        put('operational', 'provider_requests', capture.get('provider_requests'), observed_at)
        failure = (capture.get('failure') or {}).get('code')
        provider_failure = failure in {'native_provider_429', 'native_provider_http_error',
            'native_provider_response_unavailable', 'native_rpc_rejected'}
        if provider_failure:
            put('operational', 'provider_failures', 1, observed_at)
            put('operational', 'connected', 0, observed_at)
            reasons.append('PROVIDER_UNAVAILABLE')
        ranges = capture.get('completed_ranges') or []
        progress = capture.get('processing', {}).get('samples') or []
        projection = capture.get('native_projection') or {}
        if ranges:
            range_at = utc(ranges[-1]['completion_epoch_seconds'])
            put('operational', 'range_processing_ms', ranges[-1]['native_consume_seconds'] * 1000, range_at)
        if progress:
            sampled_at = utc(progress[-1]['wall_epoch_seconds'])
            if 'sampled_block_debt' in contract.METRICS['activity']:
                put('activity', 'sampled_block_debt', progress[-1]['sampled_backlog_chain_units'], sampled_at)
        put('activity', 'queue_depth', projection.get('pending_native_candidates'), observed_at)
        put('activity', 'events_processed', projection.get('durable_economic_events'), observed_at)
        seen = projection.get('scout', {}).get('events', {}).get('curve')
        put('activity', 'events_seen', seen, observed_at)
        put('activity', 'launch_events', projection.get('scout', {}).get('events', {}).get('launch'), observed_at)
        if not provider_failure and sum(row['completed_requests'] for row in capture.get('rpc_latency', [])):
            put('operational', 'connected', 1, observed_at)
    if execution in ('STOPPED', 'FAILED'):
        reasons.append('SOURCE_STOPPED' if execution == 'STOPPED' else 'SOURCE_FAILED')
    equity_rows = [dict(at=row['at'], equity=metric(row['value'], 'USD', row['at']))
        for row in portfolio.get('history', []) if row.get('series') == 'portfolio']
    history = dict(equity=dict(rows=equity_rows[-contract.MAX_EQUITY:], total=None, complete=False),
        events=dict(rows=[], total=0 if empty else None, complete=empty))
    lifecycles = []
    for position in positions[-contract.MAX_LIFECYCLES:]:
        life = position['id']
        asset = position.get('asset')
        need(type(life) is str and type(asset) is str)
        life = life if re.fullmatch('[0-9a-f]{64}', life) else hashlib.sha256(life.encode()).hexdigest()
        asset = asset if re.fullmatch('[0-9a-f]{64}', asset) else hashlib.sha256(asset.encode()).hexdigest()
        lifecycles.append(dict(lifecycle_id=life, asset_id=asset,
            state='PARTIAL' if position['state'] == 'OPEN' and position.get('partial_exits', 0) else position['state'],
            entered_at=position.get('entered_at'),
            updated_at=position.get('settled_at') or position.get('entered_at'), settled_at=position.get('settled_at'),
            metrics={name: metric(position.get(key), 'USD', at) for name, key in
                (('realized_pnl', 'realized_pnl'), ('fees', 'fees'))}, reason_codes=['QUOTE_UNAVAILABLE']))
    if positions or len(equity_rows) > contract.MAX_EQUITY or not portfolio.get('history_complete'):
        reasons.append('HISTORY_TRUNCATED')
    value = dict(schema=contract.SCHEMA, label=contract.LABEL,
        identity=dict(experiment_id=EXPERIMENT_ID, epoch_id=book['epoch_id'], source_commit=source_commit,
            inception_sha256=book['inception_sha256']), sequence=current, captured_at=utc(time.time()),
        execution_state=execution, metrics=groups, lifecycles=lifecycles, history=history,
        reason_codes=list(dict.fromkeys(reasons)))
    value['snapshot_sha256'] = contract.snapshot_digest(value)
    return contract.validate_snapshot(value, value['identity'])


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def publish_once():
    config, _ = read_json(PUBLICATION / 'config.json', 4096)
    need(set(config) == {'source_commit'} and type(config['source_commit']) is str
         and re.fullmatch('[0-9a-f]{40}', config['source_commit']))
    source = Path(__file__).resolve().parents[1]
    git = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.hooksPath=/dev/null',
           '-c', 'core.fsmonitor=false', '-C', str(source)]
    env = dict(PATH='/usr/bin:/bin', LANG='C', HOME='/nonexistent', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL='/dev/null', GIT_OPTIONAL_LOCKS='0')
    for args, expected in ((['rev-parse', 'HEAD'], config['source_commit'].encode()),
                           (['status', '--porcelain', '--untracked-files=all'], b'')):
        result = subprocess.run(git + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, timeout=3, check=True)
        need(len(result.stdout) <= 65536 and result.stdout.strip() == expected)
    raw_token, _ = private(PUBLICATION / 'token.txt', 8192)
    token = raw_token.decode('ascii').strip()
    need(16 <= len(token) <= 4096 and all(33 <= ord(c) <= 126 for c in token))
    with sequence() as current:
        value = build(current, config['source_commit'])
        atomic(PUBLICATION / 'latest.json', value)
        raw = json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
        request = Request(ENDPOINT, data=raw, method='POST', headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            need(response.status == 202)
            received = response.read(4097)
        need(len(received) <= 4096)
        result = json.loads(received)
        need(type(result) is dict and set(result) == {'status', 'idempotent', 'sequence'}
             and result['status'] == 'accepted' and type(result['idempotent']) is bool
             and type(result['sequence']) is int and result['sequence'] == current)
        return dict(status='PUBLISHED', sequence=current, snapshot_sha256=value['snapshot_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=1, choices=range(1, 121))
    args = parser.parse_args()
    failed = False
    for turn in range(args.repeat):
        try:
            print(json.dumps(publish_once(), sort_keys=True), flush=True)
        except Exception as error:
            failed = True
            print(json.dumps(dict(status='UNAVAILABLE', error_type=type(error).__name__)), flush=True)
        if turn + 1 < args.repeat:
            time.sleep(30)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
