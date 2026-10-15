"""Bounded, read-only retained-state facts; never a recovery/drain PASS.

Uses named prior receipts and primary-key/index-prefix reads. It does not open
application constructors, acquire ownership, inspect archives, count large whole
tables, run integrity checks, checkpoint, or mark any pending work complete.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time


PRIOR = 'CONSOLIDATED_OBSERVATION_POST_NATIVE_20261014T225954896402Z.json'
OLD = 'INTEGRATED_OBSERVATION_POST_PENDING_SAMPLE_20261014.json'
PREFIX = 257
BODY_LIMIT = 256 * 1024
# solana_rolling_history.program_scope: coverage_scope(family, PROGRAMS[family]).
PROGRAM_SCOPES = (
    'candidate:pump:6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',
    'candidate:pumpswap:pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA',
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class Reader:
    def __init__(self, path, stack, deadline):
        self.path = path
        self.deadline = deadline
        self.db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                                  timeout=.1, isolation_level=None)
        stack.callback(self.db.close)
        self.db.execute('PRAGMA query_only=ON')
        self.queries = []

    def rows(self, sql, args=(), limit=PREFIX + 1):
        started = time.monotonic()
        until = min(self.deadline, started + .5)
        self.db.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
        try:
            if started >= self.deadline:
                raise TimeoutError('whole_probe_budget')
            result = self.db.execute(sql, args).fetchmany(limit + 1)
            if len(result) > limit:
                raise ValueError('row_bound')
            self.queries.append(dict(sql=sql, rows=len(result), status='VERIFIED',
                                     elapsed_seconds=round(time.monotonic()-started, 6)))
            return result
        except (sqlite3.Error, TimeoutError, ValueError) as exc:
            self.queries.append(dict(sql=sql, status='UNAVAILABLE', reason=str(exc),
                                     elapsed_seconds=round(time.monotonic()-started, 6)))
            raise
        finally:
            self.db.set_progress_handler(None, 0)

    def one(self, sql, args=()):
        rows = self.rows(sql, args, limit=1)
        return rows[0] if rows else None


def limited_body(reader, table, identity):
    # Callers use fixed schema names. Length prevents materializing large bodies.
    return reader.one('SELECT CASE WHEN length(CAST(body AS BLOB))<=? THEN body END,'
                      'hash,length(CAST(body AS BLOB)) FROM ' + table + ' WHERE id=?',
                      (BODY_LIMIT, identity))


def history_identity(source, consumer, identity, expected=None):
    row = source.one('SELECT family,address,kind,consumed,CASE WHEN '
                     'length(CAST(body AS BLOB))<=? THEN body END,hash,'
                     'length(CAST(body AS BLOB)) FROM candidate_history_outbox WHERE id=?',
                     (BODY_LIMIT, identity))
    result = dict(identity=identity, status='VERIFIED', present=row is not None)
    if row is None:
        return dict(result, status='FAILED', reason='retained_identity_missing')
    family, address, kind, consumed, raw, checksum, size = row
    result.update(kind=kind, consumed=consumed, bytes=size)
    if raw is None:
        return dict(result, status='UNAVAILABLE', reason='body_byte_bound')
    if sha(raw) != checksum:
        return dict(result, status='FAILED', reason='outbox_checksum')
    body = json.loads(raw)
    record = body.get('record') or {}
    if expected and record.get('identity') != expected['canonical_identity']:
        return dict(result, status='FAILED', reason='retained_canonical_identity_changed')
    if expected and record.get('slot') != expected['slot']:
        return dict(result, status='FAILED', reason='retained_slot_changed')
    receipt = limited_body(consumer, 'source_receipts', identity)
    result['consumer_receipt_present'] = receipt is not None
    if receipt is not None:
        receipt_raw, receipt_hash, receipt_bytes = receipt
        if receipt_raw is None:
            return dict(result, status='UNAVAILABLE', reason='receipt_byte_bound')
        source_hash = body['source_hash'] if consumed is not None and kind == 'canonical' else checksum
        expected_receipt = dict(source_hash=source_hash,
                                scope='candidate:' + family + ':' + address,
                                canonical_identity=record.get('identity'))
        if sha(receipt_raw) != receipt_hash or json.loads(receipt_raw) != expected_receipt:
            return dict(result, status='FAILED', reason='receipt_exact_match')
        result['receipt_exact_match'] = True
    if consumed is not None:
        if receipt is None:
            return dict(result, status='FAILED', reason='consumed_without_receipt')
        if kind == 'canonical':
            compact = canonical(dict(source_hash=body['source_hash'],
                                     record=dict(identity=record['identity'], slot=record['slot']),
                                     available=body['available']))
            if compact != raw or sha(compact) != checksum:
                return dict(result, status='FAILED', reason='compact_ack_exact_bytes')
            result['compact_ack_exact_bytes'] = True
        result['disposition'] = 'ACKED_WITH_AUTHENTIC_RECEIPT'
    else:
        result['disposition'] = 'PENDING_PRESERVED'
    return result


def lock_observation(path):
    stat = path.stat()
    key = f'{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}'
    lines = Path('/proc/locks').read_text().splitlines()
    matches = [line for line in lines if key in line.split()]
    return dict(status='VERIFIED', method='/proc/locks device/inode observation; no lock acquired',
                key=key, matching_locks=matches,
                held_at_observation=bool(matches), race_free_future_acquisition=False)


def probe(args):
    started = time.monotonic()
    deadline = started + args.seconds
    prior_path = args.evidence_root / PRIOR
    old_path = args.evidence_root / OLD
    prior_raw = prior_path.read_text()
    old_raw = old_path.read_text()
    prior = json.loads(prior_raw)
    old = json.loads(old_raw)['sample']
    result = dict(schema='bounded-native-retained-state-v1',
                  at=datetime.now(timezone.utc).isoformat(),
                  authoritative_writes=0, provider_requests=0, tests_run=0,
                  prior_receipts={PRIOR: sha(prior_raw), OLD: sha(old_raw)},
                  checks={}, errors=[],
                  limits=['Independent short read snapshots; no atomic cross-database snapshot.',
                          'Named 32-current/24-old identity cohorts are samples, not a store census.',
                          'Index prefixes are lower bounds unless explicitly exhausted.',
                          'No large-table population scan, integrity check, constructor or ownership acquisition.',
                          'Past graceful drainage and actual future runtime recovery are not proven.'])
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('whole_probe_alarm')))
    signal.alarm(args.seconds)
    readers = []
    try:
        with ExitStack() as stack:
            base = args.state_root / 'shared'
            source = Reader(base / 'solana-evidence.sqlite', stack, deadline)
            consumer = Reader(base / 'solana-candidate-history.sqlite', stack, deadline)
            readers = [source, consumer]
            def check(name, callback):
                try:
                    result['checks'][name] = callback()
                except (OSError, sqlite3.Error, TimeoutError, ValueError, KeyError, TypeError) as exc:
                    result['checks'][name] = dict(status='UNAVAILABLE', reason=str(exc))

            def startup():
                row = source.one('SELECT session,phase,released,body,hash FROM prewarm_startup WHERE id=1')
                if row is None:
                    return dict(status='FAILED', reason='startup_missing')
                session, phase, released, raw, checksum = row
                valid = sha(raw) == checksum
                matches = session == prior['source_startup']['session'] and checksum == prior['source_startup']['body_hash']
                return dict(status='VERIFIED' if valid and matches and not released else 'FAILED',
                            session=session, phase=phase, released=bool(released),
                            body_checksum_valid=valid, matches_retained_receipt=matches,
                            classification='UNRELEASED_PENDING_ALLOWED_FAIL_CLOSED')
            check('source_session_startup', startup)
            def frontiers():
                rows = source.rows("SELECT scope,slot,updated FROM cursors WHERE scope IN ('control:solana','program:pump','program:pumpswap')")
                actual = {scope: [slot, at] for scope, slot, at in rows}
                return dict(status='VERIFIED' if actual == prior['durable_frontiers'] else 'FAILED',
                            durable_frontiers=actual)
            check('durable_frontiers', frontiers)
            def checkpoints():
                rows = source.rows('SELECT scope,slot,receipt,updated FROM candidate_checkpoints WHERE scope IN (?,?)', PROGRAM_SCOPES)
                verified = []
                for scope, slot, identity, updated in rows:
                    receipt = limited_body(consumer, 'source_receipts', 'coverage:' + identity)
                    record = dict(scope=scope, slot=slot, receipt=identity, updated=updated)
                    if receipt is None or receipt[0] is None:
                        verified.append(dict(record, status='UNAVAILABLE', reason='historical_coverage_receipt_missing_or_bounded'))
                        continue
                    raw, checksum, _ = receipt
                    body = json.loads(raw)
                    valid = (sha(raw) == checksum and body['scope'] == scope and body['hi'] == slot
                             and body['identity'] == identity and
                             sha(canonical([scope, body['lo'], body['hi'], body['witness']])) == identity)
                    verified.append(dict(record, status='VERIFIED' if valid else 'FAILED',
                                         consumer_coverage_receipt_checksum_and_identity=valid))
                status = ('FAILED' if any(r['status'] == 'FAILED' for r in verified) else
                          'UNAVAILABLE' if any(r['status'] == 'UNAVAILABLE' for r in verified) else 'VERIFIED')
                return dict(status=status, exact_program_scopes=PROGRAM_SCOPES, checkpoints=verified,
                            absent_is_allowed=True,
                            source_contract='Checkpoint follows committed coverage and no unconsumed rows; missing coverage never becomes a checkpoint.',
                            prior_wrong_scope_absence_claim_reused=False)
            check('program_candidate_checkpoints', checkpoints)
            check('writer_lock', lambda: lock_observation(base / 'solana-evidence.sqlite.writer.lock'))
            for name, reader, sql in (
                ('canonical_outbox_prefix', source, 'SELECT sequence FROM candidate_outbox ORDER BY sequence LIMIT 258'),
                ('history_pending_prefix', source, 'SELECT rowid,created FROM candidate_history_outbox INDEXED BY candidate_history_pending WHERE consumed IS NULL ORDER BY consumed,created LIMIT 258'),
                ('pending_proof_prefix', source, 'SELECT lo,hi FROM candidate_pending_proofs INDEXED BY candidate_proof_publication ORDER BY lo,hi LIMIT 258')):
                def prefix(reader=reader, sql=sql):
                    rows = reader.rows(sql)
                    return dict(status='VERIFIED', records_at_least=min(len(rows), PREFIX),
                                complete_population_count=len(rows) if len(rows) <= PREFIX else None,
                                pending_is_not_failure=True)
                check(name, prefix)
            for name, reader, table, index in (
                ('consumer_work_leases', consumer, 'work', 'work_edf'),
                ('historian_work_leases', source, 'rolling_preparation_jobs', 'rolling_preparation_dispatch')):
                def leases(reader=reader, table=table, index=index):
                    rows = reader.rows('SELECT status FROM ' + table + ' INDEXED BY ' + index + ' ORDER BY status LIMIT 258')
                    active = reader.rows('SELECT lease_until FROM ' + table + ' INDEXED BY ' + index + " WHERE status='active' LIMIT 258")
                    statuses = {value: sum(row[0] == value for row in rows) for value, in rows}
                    now = time.time()
                    return dict(status='VERIFIED', status_counts=statuses,
                                counts_complete=len(rows) <= PREFIX,
                                active_count=len(active), active_count_complete=len(active) <= PREFIX,
                                expired=sum(lease is not None and lease <= now for lease, in active),
                                current=sum(lease is not None and lease > now for lease, in active),
                                missing_expiry=sum(lease is None for lease, in active))
                check(name, leases)
            cohort = []
            for item in prior['current_cohort']['identities']:
                try:
                    cohort.append(history_identity(source, consumer, item['outbox_identity'], item))
                except (sqlite3.Error, TimeoutError, ValueError, KeyError, TypeError) as exc:
                    cohort.append(dict(identity=item['outbox_identity'], status='UNAVAILABLE', reason=str(exc)))
            result['checks']['current_receipt_ack_cohort'] = dict(
                status='FAILED' if any(r['status'] == 'FAILED' for r in cohort) else
                       'UNAVAILABLE' if any(r['status'] == 'UNAVAILABLE' for r in cohort) else 'VERIFIED',
                scope='EXACT_NAMED_32_IDENTITY_SAMPLE', identities=cohort)
            for kind, table, column in (('outbox_sample', 'candidate_outbox', 'identity'),
                                        ('proof_sample', 'candidate_pending_proofs', 'id')):
                ids = [item['identity'] for item in old[kind]]
                present = [identity for identity in ids if source.one('SELECT 1 FROM ' + table + ' WHERE ' + column + '=?', (identity,))]
                result['checks']['old_' + kind] = dict(status='VERIFIED' if len(present) == len(ids) else 'FAILED',
                                                        named=len(ids), present=len(present))
            old_history = [history_identity(source, consumer, item['identity']) for item in old['history_sample']]
            result['checks']['old_history_sample'] = dict(
                status='FAILED' if any(r['status'] == 'FAILED' for r in old_history) else
                       'UNAVAILABLE' if any(r['status'] == 'UNAVAILABLE' for r in old_history) else 'VERIFIED',
                scope='EXACT_NAMED_8_IDENTITY_SAMPLE', identities=old_history)
    except (OSError, sqlite3.Error, TimeoutError, ValueError, KeyError, TypeError) as exc:
        result['errors'].append(dict(status='UNAVAILABLE', reason=str(exc)))
    finally:
        signal.alarm(0)
        result['queries'] = {reader.path.name: reader.queries for reader in readers}
        result['elapsed_seconds'] = round(time.monotonic() - started, 6)
    result['whole_store_recovery_verdict'] = 'UNAVAILABLE'
    result['actual_runtime_recovery_execution'] = 'UNAVAILABLE'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=45, choices=range(1, 61))
    args = parser.parse_args()
    print(json.dumps(probe(args), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
