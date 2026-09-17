"""Single writer, atomic state + journal, bounded hot state.

Hash-chained journal is auditable offline; startup validates only current checkpoint
and current accounting invariants. This detects accidental corruption, not a hostile
operator who can rewrite the database and hashes together.

The hot journal is intentionally bounded. Older event bodies are retired once the
retained tail reaches a fixed row ceiling, while the last retired sequence/hash is
kept as the chain anchor. That preserves restart-time chain continuity without making
persistent storage scale with runtime. Retired event bodies are not performance or
research history; economically relevant current state remains in the checkpoint.
"""
import fcntl
import hashlib
import json
import os
import sqlite3
import shutil
from contextlib import contextmanager

JOURNAL_MAX_ROWS = 4096
JOURNAL_KEEP_ROWS = 2048


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def _funnel_defaults():
    return dict(scout_batches=0,observed_events=0,seed_events=0,nominations=0,
                qualification_attempts=0,qualified=0,entries=0,settled_exits=0)


def _journal_defaults():
    return dict(journal_anchor_seq=0,journal_anchor_hash='0'*64,journal_rotations=0)


class IntegrityError(RuntimeError):
    pass


class Store:
    def __init__(self, path, mode, sol_usd_micros, valuation_source, hook=None):
        if mode not in ('synthetic','captured','prospective') or sol_usd_micros <= 0 or not valuation_source:
            raise ValueError('explicit experiment and initial valuation required')
        self.path, self.hook = str(path), hook or (lambda stage: None)
        self.lock = open(self.path+'.lock','a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError('writer_already_running') from None
        try:
            self.db = sqlite3.connect(path, isolation_level=None)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA cache_size=-2048')
            self.db.execute('PRAGMA wal_autocheckpoint=128')
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY,event TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL);
            ''')
            row = self.db.execute('SELECT body,hash FROM state WHERE id=1').fetchone()
            if row is None:
                initial = 500_000_000*1_000_000_000//sol_usd_micros
                self.state = dict(mode=mode,policy='continuation-v1',model='pump-sol-cp-v1',initial_usd_micros=500_000_000,
                    initial=initial,sol_usd_micros=sol_usd_micros,valuation_source=valuation_source,
                    cash=initial,reserved=0,rent=0,fees=0,realized=0,positions={},orders={},seen={},
                    decisions=[],counts={},wallets={},progress=0,gaps=[],journal_seq=0,journal_hash='0'*64,
                    entry_count=0,provider={},last_time=0,entry_quarantine_until=0,funnel=_funnel_defaults(),
                    **_journal_defaults())
                with self.transaction('genesis'):
                    pass
            else:
                self.state = json.loads(row[0])
                if digest(self.state) != row[1]:
                    raise IntegrityError('checkpoint_hash_mismatch')
                if (self.state['mode'], self.state['sol_usd_micros'], self.state['valuation_source']) != (mode,sol_usd_micros,valuation_source):
                    raise IntegrityError('experiment_or_genesis_mismatch')
                if self.state['policy'] != 'continuation-v1' or self.state['model'] != 'pump-sol-cp-v1':
                    raise IntegrityError('policy_or_model_mismatch')
                tail = self.db.execute('SELECT seq,hash FROM journal ORDER BY seq DESC LIMIT 1').fetchone()
                if tail != (self.state['journal_seq'],self.state['journal_hash']):
                    raise IntegrityError('journal_checkpoint_mismatch')
                anchor_seq=int(self.state.get('journal_anchor_seq',0))
                anchor_hash=self.state.get('journal_anchor_hash','0'*64)
                first=self.db.execute('SELECT seq,previous FROM journal ORDER BY seq LIMIT 1').fetchone()
                if first is not None and first != (anchor_seq+1,anchor_hash):
                    raise IntegrityError('journal_anchor_mismatch')
                self.reconcile()
                # Additive runtime-state migration only. Existing gaps conservatively
                # quarantine new exposure for one complete 60-second signal window.
                missing_journal=any(key not in self.state for key in _journal_defaults())
                if 'entry_quarantine_until' not in self.state or 'funnel' not in self.state or missing_journal:
                    with self.transaction('prospective_validation_state_v3'):
                        if 'entry_quarantine_until' not in self.state:
                            self.state['entry_quarantine_until']=(self.state.get('last_time',0)+60 if self.state.get('gaps') else 0)
                        self.state.setdefault('funnel',_funnel_defaults())
                        for key,value in _funnel_defaults().items():
                            self.state['funnel'].setdefault(key,value)
                        for key,value in _journal_defaults().items():
                            self.state.setdefault(key,value)
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            self.lock.close()
            raise

    def reconcile(self):
        s = self.state
        positions = s['positions'].values()
        basis = sum(p['basis'] for p in positions)
        if s['cash']+s['reserved']+s['rent']+basis != s['initial']+s['realized']:
            raise IntegrityError('capital_conservation')
        pending = sum(o['reservation'] for o in s['orders'].values() if o['status']=='reserved')
        if pending != s['reserved'] or min(s['cash'],s['reserved'],s['rent']) < 0:
            raise IntegrityError('reservation_invariant')
        if s['rent'] != sum(p['rent'] for p in s['positions'].values()):
            raise IntegrityError('rent_invariant')
        if any(p['tokens'] <= 0 or p['kind'] != 'spot' for p in s['positions'].values()):
            raise IntegrityError('position_invariant')
        return True

    def _rotate_journal_if_needed(self):
        """Bound retained event bodies while preserving the journal hash-chain anchor.

        Rotation occurs inside the same SQLite transaction as the next durable action,
        so a crash cannot commit a new anchor without also retiring the matching rows.
        The database file may keep reusable SQLite pages, but allocated size plateaus
        instead of growing with total runtime.
        """
        s=self.state
        anchor_seq=int(s.get('journal_anchor_seq',0))
        retained=int(s.get('journal_seq',0))-anchor_seq
        if retained < JOURNAL_MAX_ROWS:
            return False
        remove=retained-(JOURNAL_KEEP_ROWS-1)
        cutoff=anchor_seq+remove
        row=self.db.execute('SELECT seq,hash FROM journal WHERE seq=?',(cutoff,)).fetchone()
        if row is None:
            raise IntegrityError('journal_rotation_boundary_missing')
        self.db.execute('DELETE FROM journal WHERE seq<=?',(cutoff,))
        s['journal_anchor_seq'],s['journal_anchor_hash']=int(row[0]),row[1]
        s['journal_rotations']=int(s.get('journal_rotations',0))+1
        return True

    @contextmanager
    def transaction(self, action):
        before = encode(self.state)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self.state
            self.reconcile()
            self._rotate_journal_if_needed()
            s = self.state
            seq, previous = s['journal_seq']+1,s['journal_hash']
            event = encode(dict(action=action,state_hash=digest(s)))
            h = hashlib.sha256((previous+event).encode()).hexdigest()
            self.db.execute('INSERT INTO journal VALUES(?,?,?,?)',(seq,event,previous,h))
            s['journal_seq'],s['journal_hash'] = seq,h
            self.db.execute('INSERT OR REPLACE INTO state VALUES(1,?,?)',(encode(s),digest(s)))
            self.hook('before_commit')
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
                self.state = json.loads(before)
            raise
        self.hook('after_commit')

    def verify_archive(self):
        previous = self.state.get('journal_anchor_hash','0'*64)
        seq = int(self.state.get('journal_anchor_seq',0))
        for n,event,parent,h in self.db.execute('SELECT seq,event,previous,hash FROM journal ORDER BY seq'):
            if n != seq+1 or parent != previous or hashlib.sha256((parent+event).encode()).hexdigest()!=h:
                raise IntegrityError('journal_corruption')
            seq,previous = n,h
        if (seq,previous)!=(self.state['journal_seq'],self.state['journal_hash']):
            raise IntegrityError('journal_tail')
        return True

    def journal_stats(self):
        rows=int(self.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0])
        db_bytes=os.path.getsize(self.path) if os.path.exists(self.path) else 0
        wal_path=self.path+'-wal'
        wal_bytes=os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        return dict(rows=rows,anchor_seq=int(self.state.get('journal_anchor_seq',0)),
                    tail_seq=int(self.state['journal_seq']),
                    rotations=int(self.state.get('journal_rotations',0)),
                    db_bytes=db_bytes,wal_bytes=wal_bytes)

    def pressure(self):
        size = sum(os.path.getsize(self.path+x) for x in ('','-wal') if os.path.exists(self.path+x))
        free = shutil.disk_usage(os.path.dirname(os.path.abspath(self.path))).free
        return free < 16*1024*1024 or size > 32*1024*1024 or self.state['entry_count'] >= 100

    def close(self):
        self.db.close()
        self.lock.close()