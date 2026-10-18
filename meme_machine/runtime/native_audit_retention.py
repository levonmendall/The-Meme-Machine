"""Connection-private deletion of the two original bounded Plane audit rings.

This replaces trigger DDL during a native prune, not the original boundary or
participation calculation. It assumes the approved Python source and owned
connection; it is not a sandbox against arbitrary Python registering SQL UDFs.
"""
import os
from pathlib import Path
import sqlite3
import threading
import weakref


_FUNCTION = 'mm_native_audit_delete'
_RINGS = {
    'transitions': ('history_no_delete', 'seq'),
    'observations': ('observations_no_delete', 'rowid'),
}


def _sql(value):
    return ' '.join(value.replace('IF NOT EXISTS ', '').split()).rstrip(';') if type(value) is str else None


def _legacy(table, trigger):
    return ('CREATE TRIGGER ' + trigger + ' BEFORE DELETE ON ' + table +
            " BEGIN SELECT RAISE(ABORT,'append_only'); END")


def _canonical(table, trigger, key):
    return ('CREATE TRIGGER ' + trigger + ' BEFORE DELETE ON ' + table +
            " WHEN " + _FUNCTION + "('" + table + "',OLD." + key +
            ") IS NOT 1 BEGIN SELECT RAISE(ABORT,'append_only'); END")


class _NativeAuditRetention:
    def __init__(self, owner, previous):
        from .robinhood.plane import Plane
        if type(owner) is not Plane:
            raise ValueError('native_audit_owner')
        self._owner = weakref.ref(owner)
        self._db = owner.db
        self._pid = os.getpid()
        info = Path(owner.path).stat()
        self._inode = info.st_dev, info.st_ino
        self._enabled = False
        self._transaction = None
        self._permit = None
        self._probe = None
        self._seen = None
        self._previous = previous
        self._db.create_function(_FUNCTION, 2, self._predicate)

    def _owned(self, *, locked=True):
        owner = self._owner()
        return (owner is not None and not owner._closed and os.getpid() == self._pid
                and owner.db is self._db and (not locked or owner.lock._is_owned()))

    def install(self):
        """Validate the whole pair before atomically replacing known old guards."""
        if not self._owned() or not self._db.in_transaction:
            raise ValueError('native_audit_install_transaction')
        changes = []
        # The original constructor may reconstruct a missing old guard. That
        # default repair is not evidence for enabling this new fast path.
        for table, (trigger, key) in _RINGS.items():
            if table in self._previous and _sql(self._previous.get(trigger)) not in (
                    _sql(_legacy(table, trigger)), _sql(_canonical(table, trigger, key))):
                return False
        for table, (trigger, key) in _RINGS.items():
            row = self._db.execute('SELECT CASE WHEN octet_length(sql)<=1024 THEN sql END FROM sqlite_master WHERE type=\'trigger\' AND name=? AND tbl_name=? LIMIT 1',
                                   (trigger, table)).fetchone()
            actual = _sql(row[0]) if row else None
            if actual == _sql(_canonical(table, trigger, key)):
                continue
            if actual != _sql(_legacy(table, trigger)):
                self._enabled = False
                return False
            changes.append((table, trigger, key))
        for table, trigger, key in changes:
            self._db.execute('DROP TRIGGER ' + trigger)
            self._db.execute(_canonical(table, trigger, key))
        self._enabled = True
        return bool(changes)

    def begin(self):
        if self._transaction is not None or self._permit is not None:
            raise ValueError('native_audit_nested_transaction')
        if not self._enabled or not self._owned() or not self._db.in_transaction:
            return None
        token = object()
        self._transaction = token, threading.get_ident()
        return token

    def finish(self, token):
        # No SQL, callbacks or fallible cleanup can leave a permit alive.
        self._permit = None
        self._transaction = None

    def close(self):
        self._enabled = False
        self.finish(None)
        self._probe = self._seen = None

    def _predicate(self, table, key):
        if self._probe is not None and table is None and key is None:
            self._seen = self._probe
            return 0
        permit = self._permit
        if (permit is None or not self._enabled or not self._owned()
                or not self._db.in_transaction or self._transaction != permit[:2]
                or threading.get_ident() != permit[1]):
            return 0
        return int(type(table) is str and table == permit[2] and type(key) is int
                   and -(2**63) <= key < permit[3])

    def delete(self, db, table, trigger, *, key, where, cutoff, rowid, guard, limit):
        if self._permit is not None:
            raise ValueError('native_audit_reentrant_delete')
        if not self._owned(locked=False) or db is not self._db or not db.in_transaction:
            raise ValueError('native_audit_delete_owner')
        if not self._enabled:
            return False
        if self._transaction is None:
            # The original standalone storage hook may own its own BEGIN.
            # It keeps the original guarded DROP/delete/restore path.
            return False
        if not self._owned() or self._transaction[1] != threading.get_ident():
            raise ValueError('native_audit_delete_transaction')
        owner = self._owner()
        info = Path(owner.path).stat()
        if (info.st_dev, info.st_ino) != self._inode or getattr(owner, '_owner_inode', None) != self._inode:
            raise ValueError('native_audit_delete_inode')
        from .operating_families import active_sql
        expected_where = 'candidate NOT IN (SELECT id FROM candidates WHERE NOT (' + active_sql('lane') + '))'
        if (type(table) is not str or _RINGS.get(table) != (trigger, key)
                or where != expected_where or rowid is not True or type(limit) is not int or limit != 4096
                or type(cutoff) is not int or not -(2**63) <= cutoff < 2**63):
            raise ValueError('native_audit_delete_shape')
        if _sql(guard) != _sql(_canonical(table, trigger, key)):
            return False
        expected = {}
        for ring, (name, column) in _RINGS.items():
            expected[name] = _sql(_canonical(ring, name, column))
            update = 'history_no_update' if ring == 'transitions' else 'observations_no_update'
            expected[update] = _sql('CREATE TRIGGER ' + update + ' BEFORE UPDATE ON ' + ring +
                                    " BEGIN SELECT RAISE(ABORT,'append_only'); END")
        actual = {name: _sql(sql) for name, sql in db.execute(
            "SELECT CASE WHEN octet_length(name)<=64 THEN name END,"
            "CASE WHEN octet_length(sql)<=1024 THEN sql END FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name IN ('transitions','observations') LIMIT 5")}
        if actual != expected:
            return False
        # A replacement registered function must not silently acquire a permit.
        # This closed probe cannot authorize a row and never renews a permit.
        probe = object()
        self._probe, self._seen = probe, None
        try:
            try:
                result = db.execute('SELECT ' + _FUNCTION + '(NULL,NULL)').fetchone()
                intact = self._seen is probe and result is not None and type(result[0]) is int and result[0] == 0
            except sqlite3.OperationalError as error:
                if getattr(error, 'sqlite_errorcode', None) != sqlite3.SQLITE_ERROR:
                    raise
                # Missing/replaced UDF: retain the original serialized route.
                # Interrupt, busy, I/O and other native failures still propagate.
                intact = False
        finally:
            self._probe = self._seen = None
        if not intact:
            self._enabled = False
            return False
        self._permit = (*self._transaction, table, cutoff)
        try:
            db.execute('DELETE FROM ' + table + ' WHERE (' + where + ') AND ' + key + '<?', (cutoff,))
        finally:
            self._permit = None
        return True


def delete(retention, db, table, trigger, **kwargs):
    if retention is None:
        return False
    if type(retention) is not _NativeAuditRetention:
        raise ValueError('native_audit_retention_type')
    return retention.delete(db, table, trigger, **kwargs)
