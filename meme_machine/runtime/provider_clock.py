"""Bind durable provider timers to their kernel monotonic clock domain.

Provider deadlines are leases, not historical wall times. A restored lease has
no meaning on another boot. Untagged state therefore requires an explicitly
fenced adoption; its complete old scheduling state is retained before rebasing.
The caller owns its existing SQLite write transaction and operational fences.
"""
import json
import math
import os
import re
import time
import uuid
from pathlib import Path


class ProviderClockError(RuntimeError):
    pass


def validate_timer(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value < 0):
        raise ProviderClockError('provider_clock_timer_invalid')
    return float(value)


def _identity(value):
    try:
        if not isinstance(value,str) or len(value)>512:raise ValueError()
        row=json.loads(value)
        if set(row)!={'version','boot_id','time_namespace_device','time_namespace_inode'}:
            raise ValueError()
        if type(row['version']) is not int or row['version']!=1:
            raise ValueError()
        if str(uuid.UUID(row['boot_id']))!=row['boot_id']:
            raise ValueError()
        if uuid.UUID(row['boot_id']).int==0:raise ValueError()
        if (type(row['time_namespace_device']) is not int or row['time_namespace_device']<0 or
                type(row['time_namespace_inode']) is not int or row['time_namespace_inode']<=0):
            raise ValueError()
        if json.dumps(row,sort_keys=True,separators=(',',':'))!=value:
            raise ValueError()
        return row
    except (ValueError,TypeError,KeyError,AttributeError):
        raise ProviderClockError('provider_clock_identity_invalid') from None


def current_identity():
    """Linux boot and time-namespace identity; unavailable identity contains work."""
    try:
        boot=Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
        namespace=os.stat('/proc/self/ns/time')
        value=json.dumps(dict(version=1,boot_id=boot,
            time_namespace_device=namespace.st_dev,time_namespace_inode=namespace.st_ino),
            sort_keys=True,separators=(',',':'))
        _identity(value)
        return value
    except (OSError,UnicodeError):
        raise ProviderClockError('provider_clock_identity_unavailable') from None


def _component(value):
    if value not in ('source_governor','pons_admission'):
        raise ProviderClockError('provider_clock_component_invalid')


def _metadata(db,component):
    rows=db.execute('SELECT component,identity,last_observed,quiet_until,transition_id '
                    'FROM provider_clock_domain WHERE singleton=1').fetchall()
    if len(rows)!=1:raise ProviderClockError('provider_clock_metadata_invalid')
    name,identity,last,quiet,sequence=rows[0]
    _identity(identity);validate_timer(last);validate_timer(quiet)
    if name!=component or type(sequence) is not int or sequence<0:
        raise ProviderClockError('provider_clock_metadata_invalid')
    return identity,float(last),float(quiet),sequence


def bind_clock_domain(db,*,component,clock,quiet_seconds,snapshot,rebase,
                      adoption_identity=None):
    """Validate/bind clocks within the caller's ``BEGIN IMMEDIATE`` transaction.

    ``snapshot(db)`` returns ``(has_state, archive)`` and validates all old lease
    values. ``rebase(db, now, quiet_until)`` changes scheduling leases only. They
    run for bootstrap/transition, never an ordinary same-domain observation.
    An explicit adoption identity attests to externally held stopped ownership
    and no-inflight fences; this API does not acquire or replace those fences.
    """
    _component(component)
    if not db.in_transaction:
        raise ProviderClockError('provider_clock_write_transaction_required')
    quiet_seconds=validate_timer(quiet_seconds(db) if callable(quiet_seconds) else quiet_seconds)
    if quiet_seconds>60:raise ProviderClockError('provider_clock_quiet_bound')
    if adoption_identity is not None and (not isinstance(adoption_identity,str) or
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',adoption_identity) is None):
        raise ProviderClockError('provider_clock_adoption_identity_invalid')
    identity=current_identity();domain=_identity(identity)
    # Read after acquiring the database write lock. Earlier process-local samples
    # could look regressed merely because another writer obtained the lock first.
    now=validate_timer(clock())
    db.execute('CREATE TABLE IF NOT EXISTS provider_clock_domain('
        'singleton INTEGER PRIMARY KEY CHECK(singleton=1),component TEXT NOT NULL,'
        'identity TEXT NOT NULL,last_observed REAL NOT NULL,quiet_until REAL NOT NULL,'
        'transition_id INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS provider_clock_history('
        'id INTEGER PRIMARY KEY,body TEXT NOT NULL)')
    db.execute("CREATE TRIGGER IF NOT EXISTS provider_clock_history_no_delete BEFORE DELETE "
        "ON provider_clock_history BEGIN SELECT RAISE(ABORT,'append_only'); END")
    db.execute("CREATE TRIGGER IF NOT EXISTS provider_clock_history_no_update BEFORE UPDATE "
        "ON provider_clock_history BEGIN SELECT RAISE(ABORT,'append_only'); END")
    count=db.execute('SELECT count(*) FROM provider_clock_domain').fetchone()[0]
    if count==0:
        if db.execute('SELECT count(*) FROM provider_clock_history').fetchone()[0]:
            raise ProviderClockError('provider_clock_metadata_invalid')
        has_state,archive=snapshot(db)
        if type(has_state) is not bool:raise ProviderClockError('provider_clock_snapshot_invalid')
        if not has_state:
            db.execute('INSERT INTO provider_clock_domain VALUES(1,?,?,?,?,?)',
                       (component,identity,now,0.0,0))
            return dict(identity=identity,now=now,quiet_until=0.0,
                        transition='bootstrap',transition_id=0)
        if adoption_identity is None:
            raise ProviderClockError('provider_clock_legacy_unbound')
        previous=None;last=None;sequence=0;reason='legacy_adopted'
    elif count==1:
        previous,last,quiet,sequence=_metadata(db,component)
        if previous==identity:
            if now<last:raise ProviderClockError('provider_clock_regression')
            db.execute('UPDATE provider_clock_domain SET last_observed=? WHERE singleton=1',(now,))
            return dict(identity=identity,now=now,quiet_until=quiet,
                        transition='same_domain',transition_id=sequence)
        old=_identity(previous)
        # A prior boot cannot still own leases. Two live time namespaces on one
        # boot can; require the same exclusive controlled adoption in that case.
        if old['boot_id']==domain['boot_id'] and adoption_identity is None:
            raise ProviderClockError('provider_clock_namespace_changed')
        has_state,archive=snapshot(db)
        if type(has_state) is not bool:raise ProviderClockError('provider_clock_snapshot_invalid')
        reason='domain_changed'
    else:raise ProviderClockError('provider_clock_metadata_invalid')
    quiet_until=validate_timer(now+quiet_seconds)
    record=dict(version=1,component=component,reason=reason,
        adoption_identity=adoption_identity,previous_identity=previous,
        previous_last_observed=last,identity=identity,now=now,
        quiet_until=quiet_until,archive=archive)
    try:body=json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (ValueError,TypeError):
        raise ProviderClockError('provider_clock_snapshot_invalid') from None
    if len(body.encode('utf-8'))>16*1024*1024:
        raise ProviderClockError('provider_clock_snapshot_bound')
    next_id=db.execute('SELECT COALESCE(MAX(id),0)+1 FROM provider_clock_history').fetchone()[0]
    if next_id!=sequence+1:raise ProviderClockError('provider_clock_history_invalid')
    db.execute('INSERT INTO provider_clock_history(id,body) VALUES(?,?)',(next_id,body))
    rebase(db,now,quiet_until)
    db.execute('INSERT OR REPLACE INTO provider_clock_domain VALUES(1,?,?,?,?,?)',
               (component,identity,now,quiet_until,next_id))
    return dict(identity=identity,now=now,quiet_until=quiet_until,
                transition=reason,transition_id=next_id)


def inspect_clock_domain(db,*,component,clock=time.monotonic):
    """Observe an existing binding without creating, rebasing, or updating rows."""
    _component(component)
    identity=current_identity();_identity(identity)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                      "name='provider_clock_domain'").fetchone():
        return dict(state='UNBOUND',identity=identity,now=validate_timer(clock()))
    previous,last,quiet,sequence=_metadata(db,component)
    # A reader does not hold the write lock. Sample after reading the stored row
    # so a concurrent admission cannot make an earlier sample look regressed.
    now=validate_timer(clock())
    state=('CLOCK_DOMAIN_CHANGED' if previous!=identity else
           'CLOCK_REGRESSION' if now<last else 'BOUND')
    return dict(state=state,identity=identity,stored_identity=previous,now=now,
        last_observed=last,quiet_until=quiet,
        quiet_remaining_seconds=max(0.0,quiet-now) if previous==identity else None,
        transition_id=sequence)
