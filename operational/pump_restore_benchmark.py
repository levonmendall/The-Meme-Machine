"""Offline exact-source Pump restoration comparison; never a live capacity proof.

Both revisions consume the same hashed native-frame JSON, construct their own
disposable FULL-delivered/ACK'd/retired histories through production APIs, and
call the actual runner restoration function. No production implementation is
replaced or switched by a monkeypatch. Python audit hooks count archive opens
and refuse network, financial databases, and writes outside the worker folder.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sqlite3
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

SCHEMA = 'pump-restore-native-fixture-v1'
SCOPE = 'SYNTHETIC_NATIVE_FIXTURE_ONLY_NOT_LIVE_CAPACITY'
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 4096
NOW = 1791400000
SCRIPT = Path(__file__).resolve()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    def blob(value):
        if isinstance(value, bytes): return dict(sqlite_blob_hex=value.hex())
        raise TypeError('benchmark_json_type')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=blob)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def git(source, *args):
    return subprocess.check_output(
        ['git', '--no-optional-locks', '-C', str(source), *args],
        stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'HOME': '/nonexistent',
             'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
             'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}).decode().strip()


def source_identity(path, expected=None):
    path = Path(path).resolve(strict=True)
    head = git(path, 'rev-parse', 'HEAD')
    require(len(head) == 40 and (expected is None or head == expected),
            'benchmark_source_revision_mismatch')
    require(not git(path, 'status', '--porcelain', '--untracked-files=normal'),
            'benchmark_source_dirty')
    return dict(commit=head, tree=git(path, 'rev-parse', 'HEAD^{tree}'),
                requirements_sha256=hashlib.sha256((path/'requirements.txt').read_bytes()).hexdigest())


def capture_fixture(source, candidates, references, archive_records, graduation_every):
    """Native log fixture with explicitly synthetic identities/times, never live data.

    The captured Create/Trade layout remains decoded by production functions.
    Mint/curve identities, timestamps, signatures and block coordinates vary to
    obtain separate candidate scopes rather than mismatched index aliases.
    """
    require(1 <= candidates <= 256 and 1 <= references <= 128
            and candidates * references <= MAX_FRAMES, 'benchmark_corpus_bound')
    require(1 <= archive_records <= 64 and 0 <= graduation_every <= candidates,
            'benchmark_archive_or_graduation_bound')
    sys.path.insert(0, str(source))
    from meme_machine import pump
    from meme_machine.solana_program_decoders import pump_events
    template_path = source/'tests/fixtures/solana_selective_cohort.json'
    templates = json.loads(template_path.read_text())['pump']
    creation = next(tx for tx in templates if any(
        event['event_type'] == 'create' for event in pump_events(tx)))
    trade = next(tx for tx in templates if any(
        event['event_type'] == 'trade' for event in pump_events(tx)))
    frames = []
    for candidate in range(candidates):
        mint = pump.b58(hashlib.sha256(('offline-restore-mint:'+str(candidate)).encode()).digest())
        curve = pump.pda([b'bonding-curve', pump.un58(mint)])
        for reference in range(references):
            transaction = deepcopy(creation if reference == 0 else trade)
            event = next(event for event in pump_events(transaction)
                         if event['event_type'] == ('create' if reference == 0 else 'trade'))
            old_mint = event['mint']
            old_curve = event.get('bonding_curve') or pump.pda([b'bonding-curve', pump.un58(old_mint)])
            at = NOW + len(frames)
            logs = []
            for line in transaction['meta']['logMessages']:
                if line.startswith('Program data: '):
                    raw = base64.b64decode(line[14:], validate=True)
                    raw = raw.replace(pump.un58(old_mint), pump.un58(mint))
                    raw = raw.replace(pump.un58(old_curve), pump.un58(curve))
                    if raw[:8] == bytes([27, 114, 169, 77, 222, 235, 99, 118]):
                        offset = 8
                        for _ in range(3):
                            offset += 4 + struct.unpack_from('<I', raw, offset)[0]
                        raw = bytearray(raw)
                        struct.pack_into('<q', raw, offset+128, at)
                    elif raw[:8] == bytes([189, 219, 127, 211, 78, 230, 97, 238]):
                        raw = bytearray(raw)
                        struct.pack_into('<q', raw, 89, at)
                        if (graduation_every and (candidate+1) % graduation_every == 0
                                and reference == references-1):
                            struct.pack_into('<Q', raw, 121, 0)
                    line = 'Program data: '+base64.b64encode(raw).decode()
                logs.append(line)
            transaction['meta']['logMessages'] = logs
            # Preserve remaining captured fields, with public identity strings
            # changed consistently. This is not a signed mainnet transaction.
            transaction = json.loads(canonical(transaction).replace(old_mint, mint).replace(old_curve, curve))
            slot = 100 + len(frames)
            signature = pump.b58(hashlib.sha512(('offline-frame:'+str(slot)).encode()).digest())
            transaction.update(slot=slot, transactionIndex=0, blockTime=at)
            transaction['transaction']['signatures'] = [signature]
            require(any(row['mint'] == mint for row in pump_events(transaction)),
                    'benchmark_fixture_decode_identity')
            frames.append(dict(slot=slot, parent=slot-1, blockhash=str(slot),
                parent_blockhash=str(slot-1), market_time=at, seen=NOW+MAX_FRAMES+1,
                transaction=transaction))
    result = dict(schema=SCHEMA, scope=SCOPE, template_sha256=hashlib.sha256(
        template_path.read_bytes()).hexdigest(), candidates=candidates,
        references_per_candidate=references, archive_records=archive_records,
        graduation_every=graduation_every, clock=NOW+MAX_FRAMES+1,
        restore_at=NOW+len(frames)+60, endpoint_identity='a'*64, frames=frames)
    require(len(canonical(result).encode()) <= MAX_CAPTURE_BYTES, 'benchmark_capture_byte_bound')
    return result


def validate_capture(value):
    require(type(value) is dict and value.get('schema') == SCHEMA
            and value.get('scope') == SCOPE, 'benchmark_fixture_scope')
    frames = value.get('frames')
    require(type(frames) is list and 1 <= len(frames) <= MAX_FRAMES,
            'benchmark_frame_bound')
    require(type(value.get('archive_records')) is int
            and 1 <= value['archive_records'] <= 64, 'benchmark_archive_bound')
    require(type(value.get('candidates')) is int and 1 <= value['candidates'] <= 256,
            'benchmark_candidate_bound')
    require(type(value.get('clock')) is int and type(value.get('restore_at')) is int,
            'benchmark_clock_shape')
    require(type(value.get('endpoint_identity')) is str
            and value['endpoint_identity'] == 'a'*64, 'benchmark_fixture_endpoint')
    for index, row in enumerate(frames):
        require(type(row) is dict and row.get('slot') == 100+index
                and row.get('parent') == 99+index and type(row.get('transaction')) is dict,
                'benchmark_frame_shape')
    return value


def guard(root):
    """Audit actual operations, without replacing a production implementation."""
    allowed = {root/'solana-evidence.sqlite', root/'solana-candidate-history.sqlite'}
    counts = dict(archive_opens=0, archive_bytes_offered=0, database_opens=0,
                  network_calls=0, database_paths=set(), archive_paths=set())
    def local(path):
        path = Path(os.fsdecode(path)).resolve()
        require(path.is_relative_to(root), 'benchmark_write_outside_disposable_root')
        return path
    def audit(event, args):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'):
            counts['network_calls'] += 1
            raise RuntimeError('benchmark_network_forbidden')
        if event == 'sqlite3.connect':
            value = os.fsdecode(args[0])
            path = Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).resolve()
            require(path in allowed, 'benchmark_financial_or_foreign_database_forbidden')
            counts['database_opens'] += 1
            counts['database_paths'].add(path.name)
        elif event == 'open' and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).resolve()
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                local(path)
            elif path.suffix == '.zlib' and path.is_relative_to(root):
                counts['archive_opens'] += 1
                counts['archive_bytes_offered'] += path.stat().st_size
                counts['archive_paths'].add(path.name)
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod'):
            local(args[0])
        elif event in ('os.rename', 'os.replace'):
            local(args[0]); local(args[1])
    sys.addaudithook(audit)
    return counts


def rows_digest(path):
    """Logical state proof; opening a read connection can affect WAL metadata."""
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return digest({table: sorted(db.execute('SELECT * FROM "'+table+'"').fetchall(), key=repr)
                       for table in tables})


def build_history(corpus, root):
    from meme_machine.runtime.candidate_history import CandidateHistory
    from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_history_archive import prepare, apply
    from meme_machine.solana_history_delivery import capture, deliver, acknowledge, generation
    from meme_machine.solana_program_decoders import pump_events
    from meme_machine.solana_rolling_history import program_scope
    from meme_machine.solana_scoped_retirement import ScopedRetirement
    from meme_machine.solana_selective_history import PROGRAMS
    from meme_machine.solana_selective_source import install, commit_candidate_batch, commit_control
    from meme_machine.yellowstone import geyser_pb2 as pb
    source, consumer = root/'solana-evidence.sqlite', root/'solana-candidate-history.sqlite'
    writer = EvidenceWriter(source, clock=lambda: corpus['clock'])
    state = SimpleNamespace(writer=writer, fence=FinalizedFence(
        writer, endpoint_identity=corpus['endpoint_identity']))
    try:
        history = install(state)
        history.clock = history.lifecycle.clock = lambda: corpus['clock']
        life = history.lifecycle
        life.delivery_separated = True; life.path = consumer
        frames = []
        for row in corpus['frames']:
            update = pb.SubscribeUpdate(); block = update.block
            block.slot = row['slot']; block.parent_slot = row['parent']
            block.blockhash = row['blockhash']; block.parent_blockhash = row['parent_blockhash']
            block.block_time.timestamp = row['market_time']
            tx = row['transaction']; sig = tx['transaction']['signatures'][0]
            frames.append(YellowstoneTransactionFrame(update, len(canonical(row).encode()), row['seen'],
                replay_from_slot=100, log_transactions=(tx,),
                candidate_statuses=((sig, 0, (program_scope('pump'),), None, row['seen']),)))
            for event in pump_events(tx):
                if event['event_type'] == 'create': history.bind('pump', event['mint'])
        # Real linked control frames close the same candidate interval boundaries.
        for frame in frames:
            update = pb.SubscribeUpdate(); update.CopyFrom(frame.update)
            commit_control(state, YellowstoneTransactionFrame(update, update.ByteSize(), frame.seen,
                replay_from_slot=100))
        tail = pb.SubscribeUpdate(); tail.block.slot = frames[-1].update.block.slot+1
        tail.block.parent_slot = tail.block.slot-1; tail.block.blockhash = str(tail.block.slot)
        tail.block.parent_blockhash = str(tail.block.parent_slot)
        tail.block.block_time.timestamp = corpus['clock']
        tail = YellowstoneTransactionFrame(tail, tail.ByteSize(), corpus['clock'], replay_from_slot=100)
        commit_control(state, tail)
        addresses = {PROGRAMS[family]: program_scope(family) for family in ('pump', 'pumpswap')}
        for start in range(0, len(frames), 8):
            commit_candidate_batch(state, frames[start:start+8], addresses,
                                   'offline-startup-ab', publish=False)
        commit_candidate_batch(state, [tail], addresses, 'offline-startup-ab', publish=False)
        batches = 0
        for _ in range(MAX_FRAMES*2):
            batch = capture(life)
            if batch is None: break
            require(acknowledge(life, batch, deliver(batch)), 'benchmark_full_delivery_ack_failed')
            life.publish(); batches += 1
        else: raise ValueError('benchmark_delivery_bound')
        life.publish()
        require(life.unconsumed(program_scope('pump')) is None, 'benchmark_unacknowledged_pump')
        with closing(CandidateHistory(consumer)) as shared:
            refs = shared.db.execute('SELECT body FROM canonical_event_refs '
                'WHERE lane=? ORDER BY slot,transaction_index,event_index,identity', ('pump',)).fetchall()
            records = [json.loads(row[0])['canonical_identity'] for row in refs]
            expected_candidates = shared.candidates(lane='pump', event_prefix='pump_')
        require(len(expected_candidates) == corpus['candidates'], 'benchmark_candidate_corpus_mismatch')
        ScopedRetirement(history)
        archives = []
        for start in range(0, len(records), corpus['archive_records']):
            selected = {identity: history.db.execute('SELECT * FROM canonical_evidence WHERE identity=?',
                (identity,)).fetchone() for identity in records[start:start+corpus['archive_records']]}
            require(all(row is not None and row[9] is not None for row in selected.values()),
                    'benchmark_missing_original_canonical_content')
            plan = dict(selected=selected, pinned={}, oldest=None, before=None, bindings=[],
                started=time.monotonic(), canonical_path=str(source), generation=generation(life), limit=64,
                selection=dict(mode='disposable_actual_full_ack', metadata_rows=len(selected),
                    metadata_row_bound=len(selected), candidate_scopes=corpus['candidates']))
            prepared = prepare(plan); result = apply(history, plan, prepared)
            require(type(result) is dict and result['canonical_generation_revalidated']
                    and result['retired_records'] == len(selected), 'benchmark_retirement_failed')
            archive = Path(prepared['receipt']['path'])
            archives.append(dict(sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                 records=len(selected), bytes=archive.stat().st_size))
        canonical_rows = history.db.execute(
            'SELECT identity,hash,archive FROM canonical_evidence ORDER BY identity').fetchall()
        require(all(row[2] is not None for row in canonical_rows), 'benchmark_cold_retirement_incomplete')
        return dict(source=source, consumer=consumer, archives=archives,
            candidate_hash=digest(expected_candidates), canonical_hash=digest(canonical_rows),
            candidates=len(expected_candidates), references=len(refs), full_ack_batches=batches)
    finally:
        writer.close()


def restore_pass(fixture, counts, *, cancel_after=None):
    from meme_machine.lanes.pump import runner
    from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
    from meme_machine.runtime.candidate_history import CandidateHistory
    from meme_machine.runtime import stop
    class Confirmations(ConfirmationBook):
        def __init__(self): super().__init__({}, NOW); self.calls = 0
        def observe_creation(self, creation):
            super().observe_creation(creation); self.calls += 1
            if self.calls == cancel_after: stop.requested.set()
    confirmations = Confirmations(); created, postgrad, pools = {}, {}, []
    stream = SimpleNamespace(add_address=pools.append)
    stop.requested.clear()
    if cancel_after == 0: stop.requested.set()
    io_before = {key: counts[key] for key in ('archive_opens', 'archive_bytes_offered')}
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    with closing(CandidateHistory(fixture['consumer'])) as shared:
        runner.CANDIDATE_HISTORY = shared
        wall, cpu = time.perf_counter(), time.process_time()
        cancelled = False
        try:
            restored = runner._startup_work('pump.observed_candidates_restore',
                runner._restore_observed_pump_candidates, created, postgrad, stream,
                object(), confirmations, fixture['restore_at'])
        except stop.Shutdown:
            require(cancel_after is not None, 'benchmark_unexpected_cancellation')
            cancelled = True; restored = len(created)
        finally:
            wall, cpu = time.perf_counter()-wall, time.process_time()-cpu
            runner.CANDIDATE_HISTORY = None; stop.requested.clear()
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    for row in created.values(): row['pregrad_wallets'] = sorted(row['pregrad_wallets'])
    for row in postgrad.values():
        row['pregrad_wallets'] = sorted(row['pregrad_wallets'])
        history = row['history']
        row['history'] = dict(pool=history.pool, graduation_time=history.graduation_time,
                              snapshot=history.snapshot, rows=history.rows,
                              candidate_history_rows=history.candidate_history_rows)
    output = dict(created=created, postgrad=postgrad, pools=pools,
                  creator_launches=confirmations.creator_launches, mint_creator=confirmations.mint_creator)
    return dict(restored=restored, cancelled=cancelled, output_sha256=digest(output),
        wall_seconds=wall, cpu_seconds=cpu,
        archive_opens=counts['archive_opens']-io_before['archive_opens'],
        archive_bytes_offered=counts['archive_bytes_offered']-io_before['archive_bytes_offered'],
        block_inputs=usage_after.ru_inblock-usage_before.ru_inblock,
        block_outputs=usage_after.ru_oublock-usage_before.ru_oublock,
        process_peak_rss_kib=usage_after.ru_maxrss)


def worker(args):
    source = Path(args.source).resolve(strict=True)
    identity = source_identity(source, args.revision)
    root = Path(args.root).resolve(strict=True)
    require(root.is_dir() and not any(root.iterdir()), 'benchmark_disposable_root_not_empty')
    raw = Path(args.corpus).read_bytes()
    require(len(raw) <= MAX_CAPTURE_BYTES, 'benchmark_capture_byte_bound')
    corpus = validate_capture(json.loads(raw))
    sys.path.insert(0, str(source))
    counts = guard(root)
    from meme_machine.operational.offline import install_network_guard
    install_network_guard()
    fixture = build_history(corpus, root); fixture['restore_at'] = corpus['restore_at']
    before = [rows_digest(fixture[key]) for key in ('source', 'consumer')]
    complete = restore_pass(fixture, counts)
    require(complete['restored'] == fixture['candidates'], 'benchmark_incomplete_restore')
    cancel_at = max(1, fixture['candidates']//2) if fixture['candidates'] > 1 else 0
    cancelled = restore_pass(fixture, counts, cancel_after=cancel_at)
    require(cancelled['cancelled'], 'benchmark_cancel_not_observed')
    resumed = restore_pass(fixture, counts)
    require(resumed['output_sha256'] == complete['output_sha256'], 'benchmark_resume_output_changed')
    after = [rows_digest(fixture[key]) for key in ('source', 'consumer')]
    require(before == after, 'benchmark_persistent_history_changed')
    require(counts['network_calls'] == 0, 'benchmark_network_attempted')
    return dict(schema='pump-restore-benchmark-worker-v1', scope=SCOPE, source=identity,
        corpus_sha256=hashlib.sha256(raw).hexdigest(), canonical_sha256=fixture['canonical_hash'],
        candidate_sha256=fixture['candidate_hash'], archives=fixture['archives'],
        candidates=fixture['candidates'], references=fixture['references'],
        full_ack_batches=fixture['full_ack_batches'], restore=complete,
        cancellation=cancelled, resume=resumed, persistent_history_unchanged=True,
        network_calls=0, financial_database_opens=0,
        only_database_paths=sorted(counts['database_paths']), financial_authority=False,
        production_state_written=False, full_market_speed_proven=False)


def compare(args):
    require(sys.version_info[:3] == (3, 12, 14), 'benchmark_requires_cpython_3_12_14')
    own_source = SCRIPT.parents[1]
    sys.path.insert(0, str(own_source))
    from meme_machine.operational.artifact_storage import Scratch
    sources = [Path(args.before).resolve(strict=True), Path(args.after).resolve(strict=True)]
    identities = [source_identity(path) for path in sources]
    require(identities[0]['requirements_sha256'] == identities[1]['requirements_sha256'],
            'benchmark_runtime_requirements_differ')
    require(12 <= args.worker_seconds <= 600, 'benchmark_worker_time_bound')
    with Scratch() as scratch:
        if args.corpus:
            corpus_path = Path(args.corpus).resolve(strict=True)
            require(corpus_path.stat().st_size <= MAX_CAPTURE_BYTES, 'benchmark_capture_byte_bound')
            corpus = validate_capture(json.loads(corpus_path.read_text()))
        else:
            corpus = capture_fixture(sources[1], args.candidates, args.references,
                                     args.archive_records, args.graduation_every)
        capture_path = scratch.path/'native-frames.json'
        capture_path.write_text(canonical(corpus)+'\n')
        outputs = []
        for index, (source, identity) in enumerate(zip(sources, identities)):
            root = scratch.path/('source-'+str(index)); root.mkdir(mode=0o700)
            command = [sys.executable, '-I', '-B', str(SCRIPT), '_worker',
                '--source', str(source), '--revision', identity['commit'],
                '--root', str(root), '--corpus', str(capture_path)]
            env = dict(PATH='/usr/bin:/bin', LANG='C', HOME=str(root), TMPDIR=str(scratch.path),
                MM_MODE='PAPER', MM_SOLANA_HISTORY_SEPARATED='1',
                MM_OPERATION_COST_DIAGNOSTICS='1', PYTHONDONTWRITEBYTECODE='1')
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            deadline = time.monotonic()+args.worker_seconds
            try:
                while True:
                    try:
                        stdout, stderr = process.communicate(timeout=.25)
                        break
                    except subprocess.TimeoutExpired:
                        scratch.check()
                        require(time.monotonic() < deadline, 'benchmark_worker_deadline')
                (scratch.path/('worker-'+str(index)+'.stderr')).write_bytes(stderr)
                (scratch.path/('worker-'+str(index)+'.json')).write_bytes(stdout)
                require(process.returncode == 0, 'benchmark_worker_failed_'+str(index))
                outputs.append(json.loads(stdout))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=3)
        before, after = outputs
        for key in ('corpus_sha256', 'canonical_sha256', 'candidate_sha256', 'archives',
                    'candidates', 'references', 'full_ack_batches'):
            require(before[key] == after[key], 'benchmark_workload_differs_'+key)
        for phase in ('restore', 'cancellation', 'resume'):
            for key in ('restored', 'cancelled', 'output_sha256'):
                require(before[phase][key] == after[phase][key], 'benchmark_behavior_differs_'+phase+'_'+key)
        result = dict(schema='pump-restore-ab-comparison-v1', scope=SCOPE, result='EQUIVALENT',
            before=before, after=after, identical_workload=True,
            benchmark_script_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            python_version=sys.version.split()[0],
            identical_restore_cancel_resume_outputs=True,
            wall_speedup=before['restore']['wall_seconds']/max(after['restore']['wall_seconds'], 1e-9),
            cpu_speedup=before['restore']['cpu_seconds']/max(after['restore']['cpu_seconds'], 1e-9),
            financial_authority=False, production_state_written=False, full_market_speed_proven=False)
        # Only a reviewable small JSON receipt leaves the admitted scratch scope.
        output = Path(args.output).resolve()
        require(not output.exists() and not output.is_relative_to(scratch.path),
                'benchmark_output_must_be_new_outside_scratch')
        with output.open('x') as handle: handle.write(canonical(result)+'\n')
        if args.capture_output:
            with Path(args.capture_output).open('x') as handle: handle.write(canonical(corpus)+'\n')
        scratch.check(); scratch.success = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    pair = sub.add_parser('compare')
    pair.add_argument('--before', required=True, help='clean exact-source checkout')
    pair.add_argument('--after', required=True, help='clean exact-source checkout')
    pair.add_argument('--output', required=True)
    pair.add_argument('--capture-output', help='optional new JSON corpus for independent replay')
    pair.add_argument('--corpus', help='reuse an existing bounded native-frame JSON capture')
    pair.add_argument('--candidates', type=int, default=16)
    pair.add_argument('--references', type=int, default=4)
    pair.add_argument('--archive-records', type=int, default=64)
    pair.add_argument('--graduation-every', type=int, default=4)
    pair.add_argument('--worker-seconds', type=int, default=120)
    child = sub.add_parser('_worker')
    for name in ('source', 'revision', 'root', 'corpus'): child.add_argument('--'+name, required=True)
    args = parser.parse_args()
    result = worker(args) if args.action == '_worker' else compare(args)
    print(canonical(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
