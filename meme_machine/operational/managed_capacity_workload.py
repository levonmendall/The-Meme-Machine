"""Concurrent production-native, nonfinancial managed-provider diagnostic.

The owner-installed EC2 worker supplies an exact source, dedicated UID, cgroup,
private credential subset, profile and original-state fences. This program is
not an alternative host authorization path. It never starts normal PAPER.
Raw data stays inside the private generation; stdout is not a data transport.
"""
import argparse
import asyncio
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

if __package__ in (None, ''):
    # The fixed root-owned worker authenticates the complete source before
    # executing this exact file with -I. Never import from the working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from meme_machine.operational.managed_capacity_evidence import (
    Evidence, atomic_json, failure_site, host_sample, private_directory, read_json, verify)

SCHEMA = 'managed-native-capacity-workload-v1'
ALLOWED_ENV = frozenset(('MM_SOLANA_READ_RPC_URL', 'MM_SOLANA_YELLOWSTONE_TOKEN',
    'MM_ROBINHOOD_READ_RPC_URL', 'MM_CAPACITY_PROVIDER_PROFILE',
    'MM_CAPACITY_SOURCE_COMMIT'))
MAX_GENERATION_BYTES = 4 * 1024**3
READINESS_SECONDS = 300
SHUTDOWN_SECONDS = 65
REPLAY_SECONDS = 60


def _require(condition, code):
    if not condition:
        raise ValueError('capacity_' + code)


def parameters(root, duration_seconds, generation, request_id):
    root = private_directory(root, empty=True)
    _require(type(duration_seconds) is int and duration_seconds in (120, 600, 3600), 'duration')
    _require(type(generation) is str and re.fullmatch('[0-9a-f]{32}', generation), 'generation')
    _require(type(request_id) is str and re.fullmatch(
        'ec2-[1-9][0-9]{0,19}-[1-9][0-9]{0,3}', request_id), 'request_id')
    _require(not any(k.startswith('MM_') and k not in ALLOWED_ENV for k in os.environ),
             'inherited_environment')
    revision = os.environ.get('MM_CAPACITY_SOURCE_COMMIT', '')
    _require(re.fullmatch('[0-9a-f]{40}', revision), 'source_commit')
    for name in ('MM_SOLANA_READ_RPC_URL', 'MM_ROBINHOOD_READ_RPC_URL'):
        _require(bool(os.environ.get(name)), 'managed_credential_missing')
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.runtime.robinhood.provider_authority import endpoint
    AlchemyEndpoint.parse(os.environ['MM_SOLANA_READ_RPC_URL'])
    endpoint(os.environ['MM_ROBINHOOD_READ_RPC_URL'])
    from meme_machine.operational.position_continuation import load_continuous
    profile = load_continuous(os.environ.get('MM_CAPACITY_PROVIDER_PROFILE'))
    _require({r.split('_')[0] for r in profile['funding_regimes']} == {'pump', 'pons'},
             'concurrent_provider_profile_required')
    return root, revision, profile


def _environment(lane, root, revision):
    # Never pass the parent's full environment or the other provider's key.
    result = dict(PATH='/usr/bin:/bin', LANG='C', PYTHONDONTWRITEBYTECODE='1')
    names = ('MM_SOLANA_READ_RPC_URL', 'MM_SOLANA_YELLOWSTONE_TOKEN') if lane == 'pump' else (
        'MM_ROBINHOOD_READ_RPC_URL',)
    result.update({k: os.environ[k] for k in names if k in os.environ})
    result.update(MM_CAPACITY_SOURCE_COMMIT=revision,
                  MM_CAPACITY_PROVIDER_PROFILE=str(root / 'provider-profile.json'),
                  MM_CAPACITY_USAGE_DB=str(root / 'provider-usage.sqlite'))
    return result


def _signal_children(children, sig):
    for child in children.values():
        try:
            if sig == signal.SIGTERM and child.poll() is None:
                # The lane owns its accepted native decode/commit work. Wake
                # that coordinator's stop handler without terminating its
                # ProcessPool workers before the existing drain lease ends.
                child.send_signal(sig)
            else:
                # A dead leader can leave workers alive. Forced cleanup still
                # covers the whole group created by this process, including
                # after the bounded source/replay wait has expired.
                os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass


def _telemetry(root, lane):
    path = root / lane / 'telemetry.json'
    try:
        return read_json(path)
    except FileNotFoundError:
        return None


def _active(lane, row):
    if type(row) is not dict:
        return False
    if lane == 'pump':
        canonical = row.get('canonical') or {}
        return canonical.get('sealed_finalized_blocks', 0) > 0
    # The Pons native worker publishes durable block count, not number of RPCs.
    return row.get('durable_blocks', 0) > 0


def sample_projection(lane, row):
    """Bounded counters; full evidence remains in the native generation stores.

    Avoid copying growing per-candidate arrays into each host sample. Hash the
    observed full native snapshot, keeping explicit pipeline units separate.
    """
    if row is None:
        return None
    from meme_machine.operational.managed_capacity_evidence import canonical
    result = dict(snapshot_sha256=hashlib.sha256(canonical(row)).hexdigest(),
                  observed_at=row.get('observed_at'), generation=row.get('generation'))
    if lane == 'pons':
        for key in ('unit', 'baseline', 'incoming_frontier', 'durable_frontier',
                    'incoming_blocks', 'durable_blocks', 'backlog', 'economic_events',
                    'pending_candidates', 'candidate_worker_active', 'storage_bytes'):
            result[key] = row.get(key)
        result['counts'] = row.get('counts')
        result['failures'] = row.get('failures')
        survivor = row.get('survivor') or {}
        result['survivor'] = {k: survivor.get(k) for k in ('available', 'counts',
            'candidates', 'economic_events', 'price_points', 'raw_provider_batches',
            'age_eligible_candidates', 'maximum_history_lag_blocks', 'observed_at', 'monotonic')}
    else:
        native = row.get('canonical') or {}
        result['canonical'] = {k: native.get(k) for k in ('finalized_blocks',
            'sealed_finalized_blocks', 'latest_finalized_slot', 'latest_sealed_slot', 'canonical_events')}
        result['history'] = row.get('history')
        result['pipeline'] = row.get('pipeline')
        frames = row.get('source_frames') or {}
        result['source_frames'] = {k: v for k, v in frames.items()
            if type(v) in (int, float, bool) or v is None}
        result['source_queues'] = {name: {k: row.get(k) for k in ('accepted', 'committed', 'pending')}
            for name, row in (frames.get('queues') or {}).items()
            if name in ('control', 'scout', 'rolling', 'candidate')}
        result['coverage_scopes'] = len(native.get('coverage') or ())
        result['unresolved_gap_scopes'] = len(native.get('unresolved_gaps') or ())
        result['outbox'] = native.get('outbox')
        result['observation_unavailable'] = row.get('observation_unavailable')
        result['authenticated_finalized_head'] = row.get('authenticated_finalized_head')
        qualifier = row.get('qualification_worker') or {}
        result['qualification_worker'] = {k: qualifier.get(k) for k in (
            'initialization_pending', 'observation_unavailable', 'incoming_native_events',
            'durably_observed_native_events', 'native_event_backlog', 'stages',
            'latest_source_sequence', 'durable_sequence',
            'full_qualifications', 'decision_target_available', 'full_qualification_proven')}
    return result


def _wait_children(children, root, generation, *, clock=time.monotonic, sleeper=time.sleep):
    """Separate the original source-drain lease from provider-free replay."""
    drain_until = clock() + SHUTDOWN_SECONDS
    while clock() < drain_until:
        pending = [lane for lane, child in children.items() if child.poll() is None]
        if not pending:
            return None
        drained = True
        for lane in pending:
            try:
                row = read_json(root / lane / 'drained.json')
                drained &= row == dict(generation=generation, native_provider_work_drained=True)
            except FileNotFoundError:
                drained = False
        if drained:
            break
        sleeper(.1)
    else:
        return 'native_shutdown_deadline'
    replay_until = clock() + REPLAY_SECONDS
    for child in children.values():
        try:
            child.wait(timeout=max(.01, replay_until - clock()))
        except subprocess.TimeoutExpired:
            return 'native_replay_deadline'
    return None


def run(root, duration_seconds, generation, request_id):
    """Execute real independent lanes; preserve every failure as partial.

    Even a completed one-hour observation must undergo protected raw-evidence
    evaluation. This runner cannot promote itself into a financial release.
    """
    root, revision, profile = parameters(root, duration_seconds, generation, request_id)
    from meme_machine.operational.artifact_storage import headroom, tree_bytes
    from meme_machine.operational.bounded_provider import Budget
    headroom(root, MAX_GENERATION_BYTES)
    identity = dict(schema=SCHEMA, generation=generation, request_id=request_id,
        source_revision=revision, requested_seconds=duration_seconds,
        criteria_sha256=hashlib.sha256((Path(__file__).resolve().parents[2] /
            'operational/managed-capacity/ACCEPTANCE.md').read_bytes()).hexdigest(),
        profile=profile, financial_authority=False, original_state_inherited=False)
    atomic_json(root / 'generation.json', identity)
    atomic_json(root / 'provider-profile.json', profile)
    budget = Budget.create(root / 'provider-usage.sqlite', continuous=profile)
    for lane in ('pump', 'pons'):
        (root / lane).mkdir(mode=0o700)
    ledger_root = root / 'evidence'
    ledger_root.mkdir(mode=0o700)
    evidence = Evidence(ledger_root, generation)
    children = {}
    stop = threading.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    started = time.monotonic()
    window_started = None
    window_finished = None
    cause = None
    try:
        evidence.append('identity', identity)
        for lane in ('pump', 'pons'):
            children[lane] = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                '--lane', lane, '--root', str(root), '--duration-seconds', str(duration_seconds),
                '--generation', generation, '--request-id', request_id],
                env=_environment(lane, root, revision), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        next_storage_check = 0
        while not stop.is_set():
            now = time.monotonic()
            samples = {lane: _telemetry(root, lane) for lane in children}
            evidence.append('sample', dict(host=host_sample([c.pid for c in children.values()]),
                lanes={lane: sample_projection(lane, row) for lane, row in samples.items()},
                elapsed_seconds=now - started))
            if any(child.poll() is not None for child in children.values()):
                cause = 'native_lane_exited'
                break
            if window_started is None:
                if all(_active(lane, samples[lane]) for lane in children):
                    window_started = now
                    evidence.append('concurrent_window_started', dict(monotonic=now))
                elif now - started >= READINESS_SECONDS:
                    cause = 'native_readiness_deadline'
                    break
            elif now - window_started >= duration_seconds:
                window_finished = now
                break
            if now >= next_storage_check:
                tree_bytes(root, limit=MAX_GENERATION_BYTES, reject_links=True, tolerate_missing=True)
                headroom(root, 0, warn=False)
                next_storage_check = now + 5
            stop.wait(5)
        if stop.is_set() and cause is None:
            cause = 'bounded_cancelled'
    except BaseException as error:
        # Neither exception messages nor URLs can cross the protected boundary.
        cause = 'workload_' + type(error).__name__
    finally:
        _signal_children(children, signal.SIGTERM)
        cleanup_cause = _wait_children(children, root, generation)
        cause = cause or cleanup_cause
        _signal_children(children, signal.SIGKILL)
        for child in children.values():
            child.wait(timeout=5)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        try:
            evidence.append('stopped', dict(cause=cause,
                returncodes={lane: child.returncode for lane, child in children.items()},
                concurrent_seconds=0 if window_started is None else
                    (window_finished or time.monotonic()) - window_started))
        finally:
            evidence.close()
    integrity = verify(ledger_root, generation)
    budget.reap_orphans()
    # Read original ledgers from this fresh generation only. Never rewrite an
    # old usage ledger, refund uncertain bytes or refill allowances on restart.
    results = {}
    for lane in ('pump', 'pons'):
        try:
            results[lane] = read_json(root / lane / 'result.json')
        except FileNotFoundError:
            results[lane] = dict(state='NO_NATIVE_RESULT', financial_authority=False)
    report = dict(schema=SCHEMA, status='MANAGED_NATIVE_NONFINANCIAL_OBSERVATION',
        generation=generation, request_id=request_id, source_revision=revision,
        requested_seconds=duration_seconds,
        concurrent_seconds=0 if window_started is None or window_finished is None else
            window_finished - window_started,
        interval_basis='process_liveness_after_initial_native_progress_requires_raw_coverage_review',
        cause=cause, lanes=results, evidence=integrity, provider_usage=budget.usage(),
        workload_completed=bool(cause is None and window_finished is not None and
            all(child.returncode == 0 for child in children.values()) and
            all(row.get('state') == 'NATIVE_RESULT' for row in results.values())),
        financial_authority=False, normal_operation_enabled=False,
        original_state_inherited=False, production_state_written=False,
        original_terminal_authenticated=False, historical_unknown_handlers_preserved=2,
        acceptance_pass=False, raw_host_review_required=True)
    atomic_json(root / 'result.json', report)
    return report


def _child(args):
    root = private_directory(Path(args.root) / args.lane, empty=True)
    cancel = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: cancel.set())
    def sample(value):
        atomic_json(root / 'telemetry.json', value)
    def drained():
        atomic_json(root / 'drained.json', dict(generation=args.generation,
                                              native_provider_work_drained=True))
    try:
        if args.lane == 'pump':
            from meme_machine.operational.managed_native_pump import PumpManagedConfig, run_pump
            config = PumpManagedConfig(root=root, generation=args.generation,
                request_id=args.request_id, source_revision=os.environ['MM_CAPACITY_SOURCE_COMMIT'],
                endpoint=os.environ['MM_SOLANA_READ_RPC_URL'],
                token=os.environ.get('MM_SOLANA_YELLOWSTONE_TOKEN'),
                provider_usage_db=Path(os.environ['MM_CAPACITY_USAGE_DB']),
                continuous_provider_envelope=Path(os.environ['MM_CAPACITY_PROVIDER_PROFILE']))
            for key in tuple(os.environ):
                if key.startswith('MM_'):
                    os.environ.pop(key)
            async def pump():
                bounded_stop = asyncio.Event()
                async def cancellation():
                    await asyncio.to_thread(cancel.wait)
                    bounded_stop.set()
                monitor = asyncio.create_task(cancellation())
                try:
                    return await run_pump(config, bounded_stop, sample_callback=sample,
                                          drain_callback=drained)
                finally:
                    cancel.set()
                    await monitor
            result = asyncio.run(pump())
        else:
            from meme_machine.operational.managed_native_pons import run_pons
            profile = os.environ.pop('MM_CAPACITY_PROVIDER_PROFILE')
            usage = os.environ.pop('MM_CAPACITY_USAGE_DB')
            os.environ.pop('MM_CAPACITY_SOURCE_COMMIT')
            os.environ.update(MM_PROVIDER_OPERATION_MODE='CONTINUOUS',
                MM_CONTINUOUS_PROVIDER_ENVELOPE=profile, MM_PROVIDER_USAGE_DB=usage,
                MM_ROBINHOOD_STATE_DIR=str(root), MM_PROVIDER_DB=str(root / 'provider.sqlite'),
                MM_RPC_CACHE_DB=str(root / 'evidence.sqlite'), MM_RUNTIME_LANE='pons',
                MM_PONS_OBSERVATION_ROUTE='canonical_primary')
            result = run_pons(root, args.duration_seconds + READINESS_SECONDS + SHUTDOWN_SECONDS,
                             args.generation, cancel=cancel.is_set, drain_callback=drained)
            if result.get('error') is not None or result.get('verdict') != 'OBSERVED':
                atomic_json(root / 'result.json', dict(state='NATIVE_FAILED', result=result,
                                                     financial_authority=False))
                return 2
        atomic_json(root / 'result.json', dict(state='NATIVE_RESULT', result=result,
                                             financial_authority=False))
        return 0
    except BaseException as error:
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        atomic_json(root / 'result.json', dict(state='NATIVE_FAILED',
            error_type=type(error).__name__, native_failure=failure_diagnostic(error),
            origin=failure_site(error),
            financial_authority=False))
        return 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--duration-seconds', type=int, required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--lane', choices=('pump', 'pons'))
    args = parser.parse_args()
    if args.lane:
        return _child(args)
    run(args.root, args.duration_seconds, args.generation, args.request_id)
    return 2  # Raw review, never a self-issued financial/capacity approval.


if __name__ == '__main__':
    raise SystemExit(main())
