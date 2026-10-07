"""Explicit durable Pons decision/execution dispositions, without strategy authority."""
import json

from meme_machine.runtime.journal import canonical, digest


CATEGORIES = frozenset((
    'STRATEGY_REJECT', 'STRUCTURAL_INELIGIBLE', 'INCOMPLETE_EVIDENCE',
    'PROVIDER_UNAVAILABLE', 'DEADLINE_MISSED', 'QUALIFIED_BUT_CAPITAL_UNAVAILABLE',
    'EXECUTION_CAPACITY_UNAVAILABLE', 'SUPERSEDED_STATE',
    'EXPIRED_BY_STRATEGY_HORIZON', 'OTHER_EXPLICIT_REASON',
))


def failure_category(reason, *, qualified=False):
    value = str(reason)
    if any(x in value for x in ('superseded', 'generation_changed')):
        return 'SUPERSEDED_STATE'
    if any(x in value for x in ('capital_exhausted', 'minimum_capital', 'capital_unavailable', 'sleeve_exhausted')):
        return 'QUALIFIED_BUT_CAPITAL_UNAVAILABLE' if qualified else 'OTHER_EXPLICIT_REASON'
    if any(x in value for x in ('deadline', 'stale_', '_stale', 'freshness')):
        return 'DEADLINE_MISSED'
    if value.startswith('provider_') or value == 'immutable_evidence_wait_deadline':
        return 'PROVIDER_UNAVAILABLE'
    if any(x in value for x in ('execution_capacity', 'executable_size', 'quote_failure')):
        return 'EXECUTION_CAPACITY_UNAVAILABLE'
    if value in ('too_old', 'survivor_graduation_expired', 'strategy_horizon_expired'):
        return 'EXPIRED_BY_STRATEGY_HORIZON'
    if any(x in value for x in ('incomplete', 'missing', 'not_caught_up', 'reorg', 'event_capacity', 'point_capacity', 'disagreement', 'conflict', 'shape', 'identity', 'unavailable', 'trajectory_history', 'no_recent_canonical_buy')):
        return 'INCOMPLETE_EVIDENCE'
    if value in ('non_native_quote', 'natural_non_native_quote_not_supported'):
        return 'STRUCTURAL_INELIGIBLE'
    return 'OTHER_EXPLICIT_REASON'


def decision_category(decision):
    """A measured early veto is legitimate; missing evidence is never alpha."""
    vector = decision.get('vector', decision)
    passed = vector.get('current_threshold_pass', vector.get('candidate')) is True
    if passed:
        return 'QUALIFIED'
    reasons = vector.get('all_rejections') or []
    if ('token_age' in reasons and vector.get('token_age_seconds') is not None
            and vector.get('token_age_seconds')>(vector.get('thresholds') or {}).get('max_token_age_seconds',900)):
        return 'EXPIRED_BY_STRATEGY_HORIZON'
    capacity=(vector.get('proposed_size') or {}).get('execution_capacity') or {}
    if (capacity.get('final_size')==0 and capacity.get('evaluated_sizes')
            and capacity.get('binding_reason') in ('ordinary_execution','double_size_stress')):
        return 'EXECUTION_CAPACITY_UNAVAILABLE'
    for reason in reasons:
        category = failure_category(reason)
        if category in ('INCOMPLETE_EVIDENCE', 'DEADLINE_MISSED', 'PROVIDER_UNAVAILABLE', 'EXPIRED_BY_STRATEGY_HORIZON') or reason.startswith('missing_'):
            return category
    if any(x in reasons for x in ('non_native_quote', 'non_native_quote_allocation_disabled', 'already_graduated')):
        return 'STRUCTURAL_INELIGIBLE'
    if (vector.get('complete') is False and not decision.get('screened_out')
            and not vector.get('prospect_screen_only') and not vector.get('trajectory_screen_only')):
        return 'INCOMPLETE_EVIDENCE'
    return 'STRATEGY_REJECT' if reasons else 'INCOMPLETE_EVIDENCE'


class Attempts:
    """Idempotent records in the Pons plane's existing FULL-sync connection.

    No calls, funding, reservations or qualification are performed here. Results
    are separate from the rolling observer projection and survive its pruning.
    """
    def __init__(self, plane):
        self.plane = plane
        with plane.lock:
            plane.db.executescript('''
                CREATE TABLE IF NOT EXISTS pons_attempts(
                    id TEXT PRIMARY KEY, candidate TEXT NOT NULL, generation INTEGER NOT NULL,
                    phase TEXT NOT NULL, category TEXT NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS pons_attempt_candidate ON pons_attempts(candidate,generation);
                CREATE TRIGGER IF NOT EXISTS pons_attempt_no_update BEFORE UPDATE ON pons_attempts
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS pons_attempt_no_delete BEFORE DELETE ON pons_attempts
                    BEGIN SELECT RAISE(ABORT,'append_only'); END;
            ''')

    def record(self, candidate, generation, phase, category, *, at, reason=None, decision=None, execution=None):
        if category not in CATEGORIES | {'QUALIFIED'}:
            raise ValueError('pons_attempt_category')
        body = dict(candidate=candidate, generation=generation, phase=phase,
            category=category, at=at, reason=reason, decision=decision, execution=execution)
        checksum = digest(body)
        # Replaying an exact attempt cannot create a second funding disposition.
        with self.plane.transaction():
            self.plane.db.execute('INSERT OR IGNORE INTO pons_attempts VALUES(?,?,?,?,?,?,?)',
                (checksum, candidate, generation, phase, category, canonical(body), checksum))
        return body

    def rows(self, candidate=None):
        with self.plane.lock:
            rows = self.plane.db.execute('SELECT body,hash FROM pons_attempts' +
                (' WHERE candidate=?' if candidate is not None else '') + ' ORDER BY rowid',
                (candidate,) if candidate is not None else ()).fetchall()
        result = []
        for body, checksum in rows:
            value = json.loads(body)
            if digest(value) != checksum:
                raise ValueError('pons_attempt_corruption')
            result.append(value)
        return result

    def maintain(self, now, *, protected=()):
        """Retire only expired audit attempts, never by population count.

        Current has a shorter horizon, but its records remain for Survivor's
        entire seven-day eligibility domain. Open positions, claims, pending
        work and unconsumed decisions stay protected. Native ledgers retain
        accounting authority after an expired audit prefix is folded.
        """
        if now<getattr(self,'_maintenance_due',float('-inf')):return 0
        protected=set(protected)
        with self.plane.transaction():
            for row in self.plane.db.execute('SELECT id,pending,claim,result,generation FROM candidates'):
                if (row['pending'] or row['claim'] or row['result'] is not None and not
                        self.plane.db.execute('SELECT 1 FROM result_consumption WHERE candidate=? AND generation=?',
                            (row['id'],row['generation'])).fetchone()):
                    protected.update((row['id'],row['id'].rsplit(':',1)[-1]))
            for raw, in self.plane.db.execute("SELECT body FROM runtime WHERE key LIKE 'native_position:%'"):
                native=json.loads(raw)
                if native['position']['status']!='settled':protected.add(native['candidate'])
            old=self.plane.db.execute("SELECT id,candidate,body,hash FROM pons_attempts WHERE json_extract(body,'$.at')<? ORDER BY rowid LIMIT 4096",(now-7*86400,)).fetchall()
            expired=[r for r in old if r['candidate'] not in protected]
            if expired:
                previous=self.plane.checkpoint_read('pons_attempts_expired') or dict(count=0,hash=None,categories={})
                counts=dict(previous['categories']);tail=previous['hash']
                for identity,candidate,body,checksum in expired:
                    value=json.loads(body)
                    if digest(value)!=checksum:raise ValueError('pons_attempt_corruption')
                    counts[value['category']]=counts.get(value['category'],0)+1
                    tail=digest([tail,identity])
                prefix=dict(schema='pons-expired-attempt-prefix-v1',
                    count=previous['count']+len(expired),hash=tail,categories=counts,
                    before=now-7*86400,reason='expired_by_strategy_horizon')
                self.plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body',
                    ('pons_attempts_expired',canonical(prefix)))
                trigger=self.plane.db.execute("SELECT sql FROM sqlite_master WHERE name='pons_attempt_no_delete'").fetchone()[0]
                self.plane.db.execute('DROP TRIGGER pons_attempt_no_delete')
                self.plane.db.executemany('DELETE FROM pons_attempts WHERE id=?',((r[0],) for r in expired))
                self.plane.db.execute(trigger)
        self._maintenance_due=now+60
        return len(expired)
