"""One observed PAPER restore keeps its original continuous usage history.

The fixed stopped AWS proof is Actions run38963014958. This verifier grants no
funding, native-recovery or relocation authority beyond that exact cohort. It
opens only existing selected AWS files, before the ordinary Budget constructor
and the original startup bookkeeping. Old journal entries remain unchanged.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat


RESTORED_IDENTITY = dict(
    root='/srv/meme-machine/state/shared-1000',
    old_path='/mnt/volume_nyc1_1790918115030/meme-machine-paper-shared-1000/shared/provider-usage.continuous.sqlite',
    epoch='paper-shared-1000-20261011T071207Z',
    inception='aea262d34d976cddeddf83f57045508cf09f3c8e28cf8a2c73ae49d38cc261b1',
    projection='12756b16cd16c8e452290537d63c1f79a324218303af8e96f1b0ce81a15a07a7',
    journal='63570518d16a12e1071a9cb968f1f928b1e5dbf43c80159a93285424a31ca48c',
    sequence=12608,
    admission='16c8a1313aa5dd241990d16a8a749d000505cc2060cb32402d125a9cdcc39f46',
    provider='324da041f85b939dcc6d9db77c13af06b01783a0601ec46db9aab848e9f0cecc',
)
FAILURE = 'continuous_usage_history_requires_restore_not_reseed'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def provider_facts(db):
    """The existing admin _clock_usage_facts complete logical-facts algorithm.

    Include schema and every row of all four original tables, then both original
    configuration keys. No constructor, schema setup, reaping or counter writes.
    Bounds reject a larger input instead of hashing a silently clipped subset.
    """
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables != {'run', 'streams', 'http_receipts', 'usage_hours'}:
        raise ValueError(FAILURE)
    checksum = hashlib.sha256()
    rows = size = 0
    counts = {}
    def include(value):
        nonlocal size
        raw = _canonical(value)
        size += len(raw)
        if size > 32 * 1024 * 1024:
            raise ValueError(FAILURE)
        checksum.update(len(raw).to_bytes(8, 'big'))
        checksum.update(raw)
    include(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall())
    for name, sql in (
            ('run', "SELECT key,value FROM run WHERE key NOT IN ('continuous_envelope','continuous_configuration_changes') ORDER BY key"),
            ('streams', 'SELECT id,remaining,closed FROM streams ORDER BY id'),
            ('http_receipts', 'SELECT id,remaining,closed,owner FROM http_receipts ORDER BY id'),
            ('usage_hours', 'SELECT * FROM usage_hours ORDER BY hour')):
        counts[name] = 0
        include(name)
        for row in db.execute(sql):
            rows += 1
            if rows > 100000:
                raise ValueError(FAILURE)
            counts[name] += 1
            include(tuple(row))
    special = db.execute("SELECT key,value FROM run WHERE key IN "
        "('continuous_envelope','continuous_configuration_changes') ORDER BY key").fetchall()
    if len(special) != 2 or len(_canonical(special)) > 128 * 1024:
        raise ValueError(FAILURE)
    original = dict(sha256=checksum.hexdigest(), rows=counts)
    return dict(sha256=_digest(dict(original=original, configuration=special)),
        rows=counts, all_provider_facts_included=True)


def require_restored_history(supervisor, state, path, profile):
    """Permit only the authenticated observation restore before Budget opens.

    A successful original runtime_admission command records the AWS binding.
    That consumes this exact projection/cohort opportunity; ordinary same-path
    restarts subsequently use the existing guard without this exception.
    """
    try:
        from meme_machine.runtime.policy_compatibility import require_flat_portfolio
        from meme_machine.shared_capital.runtime import selected
        from .bounded_provider import Budget, resource_configuration
        expected = RESTORED_IDENTITY
        root = Path(expected['root'])
        target = root / 'shared/provider-usage.continuous.sqlite'
        previous = state.get('runtime_admission', {})
        if (supervisor.admission != 'OBSERVATION' or os.environ.get('MM_MODE', 'PAPER') != 'PAPER'
                or os.environ.get('MM_PROVIDER_OPERATION_MODE') != 'CONTINUOUS'
                or supervisor.root != root or os.environ.get('MM_STATE_ROOT') != str(root)
                or root.resolve() != root or path != target or os.environ.get('MM_PROVIDER_USAGE_DB') != str(target)
                or os.environ.get('MM_PAPER_EPOCH') not in (None, expected['epoch'])
                or supervisor.epoch != expected['epoch'] or state.get('epoch_id') != expected['epoch']
                or state.get('inception_sha256') != expected['inception']
                or _digest(state) != expected['projection']
                or previous.get('mode') != 'OBSERVATION'
                or previous.get('provider_db') != expected['old_path']
                or previous.get('continuous_provider_db') != expected['old_path']
                or _digest(previous) != expected['admission']):
            raise ValueError(FAILURE)
        require_flat_portfolio(state)
        shared = root / 'shared-capital.sqlite'
        if selected(root / 'portfolio.sqlite') != shared:
            raise ValueError(FAILURE)
        with closing(sqlite3.connect(shared.as_uri() + '?mode=ro', uri=True, timeout=0)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            projection = db.execute('SELECT body,hash FROM shared_capital_projection WHERE id=1').fetchone()
            head = db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
            if (projection is None or _digest(json.loads(projection[0])) != expected['projection']
                    or projection[1] != expected['projection']
                    or head != (expected['sequence'], expected['journal'], expected['projection'])):
                raise ValueError(FAILURE)
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or target.resolve() != target:
            raise ValueError(FAILURE)
        # Original Budget verification on a read-only object, never __init__:
        # malformed configuration must not write a failure into this cohort.
        budget = object.__new__(Budget)
        budget.prefix = ''
        budget.continuous = True
        budget.envelope = profile
        budget.configuration = resource_configuration(profile['limits'], None, None, None, continuous=True)
        with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=0)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            usage = budget.read(db)
            if (provider_facts(db)['sha256'] != expected['provider']
                    or budget.verify_configuration(usage) or usage.get('reason') != ''
                    or usage.get('new_risk_ready') != 'false'
                    or usage.get('http_reserved') != '0' or usage.get('native_reserved') != '0'
                    or usage.get('readiness_owner') != previous.get('run_id')
                    or not usage.get('readiness_owner')
                    or db.execute('SELECT 1 FROM streams WHERE closed=0 LIMIT 1').fetchone()
                    or db.execute('SELECT 1 FROM http_receipts WHERE closed=0 LIMIT 1').fetchone()):
                raise ValueError(FAILURE)
        after = target.lstat()
        if (info.st_dev, info.st_ino, info.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
            raise ValueError(FAILURE)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        raise ValueError(FAILURE) from None
