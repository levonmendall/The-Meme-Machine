"""Small single-writer store; atomic coverage, immutable research, bounded admission."""
from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3

from . import BoundaryError, CHAIN_ID


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Stamp:
    chain_id: int
    block: int
    block_hash: str
    event_at: int
    observed_at: int
    finality: str
    kind: str

    def check(self, asof, max_age=120, *, finality_ledger=None):
        if self.finality == 'confirmed' and finality_ledger is not None:
            return finality_ledger.check(self, asof, max_age)
        if self.chain_id != CHAIN_ID:
            raise BoundaryError('wrong_chain')
        if self.kind not in ('synthetic', 'captured', 'natural'):
            raise BoundaryError('unknown_evidence_kind')
        if self.finality != 'finalized':
            raise BoundaryError('unfinalized_state')
        if self.event_at > self.observed_at or self.observed_at > asof:
            raise BoundaryError('future_evidence')
        if asof - self.event_at > max_age:
            raise BoundaryError('stale_state')
        if self.block < 0 or not self.block_hash:
            raise BoundaryError('invalid_block_identity')


class Store:
    """No evidence deletion. At capacity, stop admission, export, then start a new study.

    SQLite page cap 64 MiB; memory cache 2 MiB; rollback journal bounded by transaction
    size. A separate DB is mandatory; this module never imports the Solana Store.
    """
    def __init__(self, path, *, max_records=10000):
        if not 1 <= max_records <= 100000:
            raise BoundaryError('invalid_storage_bound')
        self.max_records = max_records
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA max_page_count=16384')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS records(
                category TEXT, id TEXT, body TEXT NOT NULL, hash TEXT NOT NULL,
                PRIMARY KEY(category,id));
            CREATE TABLE IF NOT EXISTS cursors(
                scope TEXT PRIMARY KEY, block INTEGER NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper(
                id TEXT PRIMARY KEY, body TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def put(self, category, identity, body):
        encoded = canonical(body)
        if len(encoded.encode()) > 32768:
            raise BoundaryError('record_payload_capacity')
        old = self.db.execute('SELECT hash FROM records WHERE category=? AND id=?', (category, identity)).fetchone()
        checksum = digest(body)
        if old:
            if old[0] != checksum:
                raise BoundaryError('conflicting_immutable_evidence')
            return False
        if self.db.execute('SELECT count(*) FROM records').fetchone()[0] >= self.max_records:
            raise BoundaryError('storage_capacity_stop_admission')
        self.db.execute('INSERT INTO records VALUES(?,?,?,?)', (category, identity, encoded, checksum))
        return True

    def get(self, category, identity):
        row = self.db.execute('SELECT body,hash FROM records WHERE category=? AND id=?', (category, identity)).fetchone()
        if not row:
            raise BoundaryError('missing_evidence')
        body = json.loads(row[0])
        if digest(body) != row[1]:
            raise BoundaryError('evidence_checksum_mismatch')
        return body

    def cursor(self, scope):
        return self.db.execute('SELECT block,hash FROM cursors WHERE scope=?', (scope,)).fetchone()


def ingest_batch(store, *, scope, headers, receipts, logs, addresses, observed_at, kind):
    """Reconcile eth_getLogs against *all* receipts of each bounded finalized block.

    Receipt source must include all block transactions. Omission fails closed. This
    is an expensive certification route, not an unbounded steady-state scanner.
    """
    if not headers or len(headers) > 32 or len(logs) > 1000 or len(receipts) > 2000:
        raise BoundaryError('ingest_capacity')
    expected = {}
    cursor = store.cursor(scope)
    for i, block in enumerate(headers):
        stamp = Stamp(**block['stamp'])
        stamp.check(observed_at, max_age=86400)
        if stamp.kind != kind:
            raise BoundaryError('mixed_evidence_kind')
        previous = headers[i-1] if i else None
        expected_number = previous['stamp']['block'] + 1 if previous else (cursor[0] + 1 if cursor else stamp.block)
        expected_parent = previous['stamp']['block_hash'] if previous else (cursor[1] if cursor else block['parent_hash'])
        if stamp.block != expected_number:
            raise BoundaryError('missing_block_coverage')
        if block['parent_hash'] != expected_parent:
            raise BoundaryError('reorg_parent_conflict')
        transactions = block['transactions']
        if len(transactions) != len(set(transactions)):
            raise BoundaryError('duplicate_block_transaction')
        found = [r for r in receipts if r['block_hash'] == stamp.block_hash]
        if sorted(r['transaction_hash'] for r in found) != sorted(transactions):
            raise BoundaryError('missing_or_duplicate_receipts')
        for receipt in found:
            for event in receipt['logs']:
                if event['block_hash'] != stamp.block_hash or event['block'] != stamp.block or event['transaction_hash'] != receipt['transaction_hash']:
                    raise BoundaryError('incorrect_log_identity')
                if event['removed']:
                    raise BoundaryError('removed_log_reorg')
                if event['address'].lower() in addresses:
                    identity = (event['block'], event['log_index'])
                    if identity in expected:
                        raise BoundaryError('conflicting_receipt_log')
                    expected[identity] = event
    actual = {}
    for event in logs:
        key = (event['block'], event['log_index'])
        if key in actual and actual[key] != event:
            raise BoundaryError('conflicting_logs')
        actual[key] = event
    if actual != expected:
        raise BoundaryError('missing_or_unexpected_logs')
    store.db.execute('BEGIN IMMEDIATE')
    try:
        for key, event in sorted(actual.items()):
            store.put('event', f'{scope}:{key[0]}:{key[1]}', event)
        last = headers[-1]['stamp']
        store.put('coverage', f'{scope}:{last["block"]}', dict(
            headers=headers, event_hashes=[digest(x) for x in actual.values()],
            observed_at=observed_at, kind=kind))
        store.db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)', (scope, last['block'], last['block_hash']))
        store.db.execute('COMMIT')
    except Exception:
        store.db.execute('ROLLBACK')
        raise
    return list(actual.values())
