#!/usr/bin/env python3
"""One bounded, keyless Pons intake capture; never a financial/strategy verdict.

The existing public RPC recorder and native projection remain unchanged. The
parent owns only its new child process group and retains incomplete evidence.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

SOURCE_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_PARENT = Path('/workspace/experiments/pons-simulator-20261024/capture')
SOURCE_BASE = 'ba6ef30d27c379ef03324cf72356bdcc8b1d73e2'
DURATION_SECONDS = 120
PROCESS_SECONDS = 140
KILL_WAIT_SECONDS = 5
CHUNK_BLOCKS = 10
MAX_SUMMARY = 1024 * 1024
sys.path.insert(0, str(SOURCE_ROOT))
from meme_machine.operational import isolated_native_workload as native
from meme_machine.operational.isolated_native_pons import PonsNativeProjection


def require(value, code):
    if not value:
        raise ValueError(code)


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= MAX_SUMMARY, 'summary_bound')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checked_root(root):
    require(root.parent == CAPTURE_PARENT and re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{16}', root.name),
            'capture_location')
    native.private_directory(root)
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'capture_symlink')
    require(not any((p / name).exists() or (p / name).is_symlink()
        for p in (root, *root.parents)
        for name in ('portfolio.sqlite', 'shared-capital.sqlite', 'native-genesis.json')),
        'financial_ancestor')
    return root


def public_call(rpc, method, params):
    # The reused PublicRPC also enforces its immutable method allowlist, 1 RPS,
    # 150 attempts, response/corpus bounds and immediate HTTP429 cancellation.
    return rpc.call(native.ROBINHOOD, method, params)


def capture(root, *, duration=DURATION_SECONDS):
    require(type(duration) is int and 1 <= duration <= DURATION_SECONDS, 'duration_bound')
    checked_root(root)
    require(not any(root.iterdir()), 'fresh_capture_required')
    storage = native._storage_admission(root)
    stop = threading.Event()
    corpus = native.Corpus(root)
    projection = None
    progress = native.Progress('pons')
    ranges = []
    error = None
    cleanup_errors = []
    snapshot = None
    rpc = None
    started = None
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in old_handlers:
        signal.signal(sig, lambda *_: stop.set())
    try:
        projection = PonsNativeProjection(root / 'pons')
        started = time.monotonic()
        rpc = native.PublicRPC(corpus, stop, started + duration)
        native.require(public_call(rpc, 'eth_chainId', []) == '0x1237', 'native_pons_chain')
        next_block = None
        while not stop.is_set() and time.monotonic() < rpc.deadline:
            native._storage_admission(root)
            raw = public_call(rpc, 'eth_blockNumber', [])
            native.require(type(raw) is str and re.fullmatch('0x[0-9a-fA-F]+', raw), 'native_pons_head')
            head = int(raw, 16)
            progress.sample(head)
            if next_block is None:
                next_block = head
            if next_block > head:
                stop.wait(min(1, max(0, rpc.deadline - time.monotonic())))
                continue
            last = min(head, next_block + CHUNK_BLOCKS - 1)
            observed = time.time()
            event = corpus.event('pons', dict(first=next_block, last=last, acquired_head=head), observed)
            with corpus.recording(event):
                result = projection.consume(next_block, last, rpc, observed_at=observed)
            corpus.complete(event)
            progress.sample(first=next_block, last=last)
            ranges.append(dict(first=next_block, last=last, observed_epoch_seconds=observed,
                completion_epoch_seconds=time.time(), native_consume_seconds=result['seconds'],
                native_curve_observations=result['native_curve_observations'],
                durable_economic_added=result['durable_economic_added']))
            next_block = last + 1
    except Exception as failure:
        error = native._failure(failure)
    finally:
        # Acquisition is synchronous in this child. No projection/corpus close
        # races a background native call. Parent TERM/KILL is the absolute guard.
        stopped_at = time.monotonic()
        if projection is not None:
            try:
                snapshot = projection.snapshot()
            except Exception as failure:
                cleanup_errors.append(native._failure(failure))
            try:
                projection.close()
            except Exception as failure:
                cleanup_errors.append(native._failure(failure))
        counts = corpus.counts().get('pons', dict(attempted_events=0, completed_events=0))
        rpc_metrics = [dict(method=method, completed_requests=count, elapsed_seconds=elapsed,
            mean_elapsed_seconds=mean, maximum_elapsed_seconds=maximum)
            for method, count, elapsed, mean, maximum in corpus.db.execute(
                'SELECT method,count(*),sum(elapsed),avg(elapsed),max(elapsed) FROM rpc GROUP BY method ORDER BY method')]
        corpus_bytes = corpus.bytes
        corpus.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    _, corpus_sha = native._corpus_file(root / 'corpus.sqlite3')
    elapsed = None if started is None else stopped_at - started
    complete = error is None and not cleanup_errors and not stop.is_set() and elapsed is not None and elapsed >= duration
    return dict(schema='pons-simulator-public-intake-v1', result='PARTIAL_NATIVE_PONS_OBSERVATION',
        diagnostic_window_complete=complete, requested_seconds=duration, acquisition_elapsed_seconds=elapsed,
        financial_authority=False, production_state_written=False, strategy_qualification_proven=False,
        strategy_evaluations=None, qualification_count=None, held_protection_proven=False,
        canonical_completeness=False, full_market_speed_proven=False, acceptance_passed=False,
        managed_provider_usage_touched=False, anonymous_public_endpoint=native.ROBINHOOD,
        provider_requests=None if rpc is None else rpc.requests,
        provider_http_429=None if rpc is None else rpc.http_429,
        provider_rpc_rejection=None if rpc is None else rpc.rejection,
        physical_request_start_interval_seconds=1, maximum_requests=native.MAX_REQUESTS,
        maximum_corpus_payload_bytes=native.MAX_CORPUS, maximum_range_blocks=CHUNK_BLOCKS,
        corpus_payload_bytes=corpus_bytes, corpus_sha256=corpus_sha, capture_events=counts,
        processing=progress.summary(), native_projection=snapshot, completed_ranges=ranges,
        rpc_latency=rpc_metrics, failure=error, cleanup_failures=cleanup_errors,
        cleanup_completed=not cleanup_errors, storage_admission=storage,
        limitations=['Public receipt/header consistency only; no managed canonical authority.',
            'Current window hydration/qualification and Survivor canonical history are omitted.',
            'No cohort, portfolio, reservations, fills, exits, or protection lifecycle is constructed.',
            'Unobserved heads and post-window arrivals are outside the sampled backlog population.'])


def source_identity():
    files = ('meme_machine/operational/isolated_native_workload.py',
             'meme_machine/operational/isolated_native_pons.py',
             'meme_machine/operational/isolated_market_observer.py')
    return dict(native_source_base=SOURCE_BASE,
        reused_source_sha256={name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest() for name in files},
        wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        root = checked_root(Path(sys.argv[2]))
        result = capture(root)
        result.update(source_identity())
        write_new(root / 'capture-summary.json', result)
        return 0 if result['diagnostic_window_complete'] else 2
    require(len(sys.argv) == 1, 'fixed_arguments')
    require(CAPTURE_PARENT.parent.is_dir() and not CAPTURE_PARENT.parent.is_symlink(), 'experiment_parent')
    if not CAPTURE_PARENT.exists():
        CAPTURE_PARENT.mkdir(mode=0o700)
    native.private_directory(CAPTURE_PARENT)
    name = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + os.urandom(8).hex()
    root = CAPTURE_PARENT / name
    root.mkdir(mode=0o700)
    checked_root(root)
    child = None
    timeout = False
    interrupted = False
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    def interruption(*_):
        nonlocal interrupted
        interrupted = True
    for sig in old_handlers:
        signal.signal(sig, interruption)
    started = time.monotonic()
    try:
        # Preserve only the existing execution environment's outbound proxy
        # routing. Provider credentials and unrelated runtime configuration
        # remain excluded. This does not change the fixed RPC destination.
        child_env = dict(PATH='/usr/bin:/bin', LANG='C', HOME='/nonexistent')
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                    'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
            if os.environ.get(key):
                child_env[key] = os.environ[key]
        child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child', str(root)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=child_env, start_new_session=True)
        deadline = started + PROCESS_SECONDS
        while child.poll() is None and not interrupted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timeout = True
                break
            try:
                child.wait(timeout=min(1, remaining))
            except subprocess.TimeoutExpired:
                pass
    finally:
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=KILL_WAIT_SECONDS)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    receipt = dict(schema='pons-simulator-public-process-v1', capture_directory=str(root),
        child_exit_code=None if child is None else child.returncode, child_joined=child is not None and child.poll() is not None,
        elapsed_seconds=time.monotonic() - started, timed_out=timeout, interrupted=interrupted,
        financial_authority=False, acceptance_passed=False, summary_available=(root / 'capture-summary.json').is_file(),
        absolute_process_seconds=PROCESS_SECONDS + 2 + KILL_WAIT_SECONDS, **source_identity())
    write_new(root / 'process-receipt.json', receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if child is not None and child.returncode == 0 and not timeout and not interrupted else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as failure:
        print(json.dumps(dict(schema='pons-simulator-public-process-v1', state='REFUSED',
            error_type=type(failure).__name__, financial_authority=False, acceptance_passed=False)))
        raise SystemExit(2)
