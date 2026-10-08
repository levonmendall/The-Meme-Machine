"""Exclusive preserved-epoch selection. Operates only on a verified stopped root.

Uses the original writer fence, migration and ledger. SQL triggers also fence an
older executable which does not understand the new selection. No reseeding CLI.
"""
from contextlib import closing
from pathlib import Path
import fcntl
import json
import os
import sqlite3

from meme_machine.portfolio_accounting import canonical
from .model import CapitalError, digest
from .migration import plan_migration
from .operational_candidate import verify_two_family_plan
from .runtime import RuntimeCapital

TABLES=('portfolio_events','portfolio_native_pending','portfolio_native_ids','portfolio_sleeves','portfolio_checkpoint')


def install(root,plan,*,approved_policy,prerequisites,observation_only=False):
    root=Path(root).resolve();database=root/'portfolio.sqlite';shared=root/'shared-capital.sqlite'
    checked=verify_two_family_plan(plan)
    # Native recovery must finish against the preserved authority before its
    # pending deliveries/reservations can change authority. Existing migration
    # can represent them; runtime cutover never guesses their acknowledgements.
    if checked['seed']['pending_deliveries'] or checked['seed']['reservations'] or checked['seed']['commitments']:
        raise CapitalError('native_pending_recovery_required_before_cutover')
    if approved_policy!=checked['policy']:raise CapitalError('explicit_matching_risk_cap_approval_required')
    required=('writers_stopped','coherent_backup_verified','native_mapping_verified','recovery_verified','provider_proof_verified')
    proofs=required[:-1] if observation_only else required
    if (set(prerequisites)!=set(required) or any(prerequisites[k] is not True for k in proofs)
            or observation_only and prerequisites['provider_proof_verified'] is not False):
        raise CapitalError('unverified_cutover_prerequisites')
    if observation_only and any(checked['seed'].get(k) for k in
            ('positions','reservations','commitments','pending_deliveries','obligations')):
        raise CapitalError('observation_cutover_requires_empty_preserved_epoch')
    with open(str(database)+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with closing(sqlite3.connect(database,timeout=1,isolation_level=None)) as db:
            # Idempotency requires the complete same migration and approved caps.
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='portfolio_funding_authority'").fetchone()
            if exists:
                row=db.execute('SELECT body FROM portfolio_funding_authority WHERE id=1').fetchone()
                if row is None or json.loads(row[0])['migration_sha256']!=checked['migration_sha256']:
                    raise CapitalError('conflicting_or_incomplete_authority_cutover')
                with closing(RuntimeCapital(shared)) as authority:
                    if authority.snapshot()['ledger']['migration_mapping']!=checked['mapping']:raise CapitalError('conflicting_authority_mapping')
                return json.loads(row[0])
            db.execute('BEGIN IMMEDIATE')
            try:
                fresh=plan_migration(database,checked['mapping'],checked['policy'])
                if fresh!=checked:raise CapitalError('preserved_epoch_changed_before_cutover')
                with closing(RuntimeCapital(shared)) as authority:
                    authority.install_migration(checked)
                    if observation_only:
                        from .runtime import process_identity
                        authority.command('cutover-observation','runtime_admission',dict(mode='OBSERVATION',
                            run_id='cutover-observation',pid=os.getpid(),process_start=process_identity(os.getpid())),
                            checked['seed']['at'])
                    authority.verify_replay()
                marker=dict(schema='paper-funding-authority-v1',state='SHARED',epoch_id=checked['seed']['epoch_id'],
                    inception_sha256=checked['seed']['inception_sha256'],migration_sha256=checked['migration_sha256'],
                    policy_sha256=digest(approved_policy),prerequisites=prerequisites,
                    admission='OBSERVATION' if observation_only else 'NORMAL')
                db.execute('CREATE TABLE portfolio_funding_authority(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
                db.execute('INSERT INTO portfolio_funding_authority VALUES(1,?)',(canonical(marker),))
                for table in TABLES:
                    for action in ('INSERT','UPDATE','DELETE'):
                        db.execute(f"CREATE TRIGGER shared_fence_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'legacy_funding_authority_retired'); END")
                db.execute('COMMIT')
                return marker
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise


def rollback_unused(root):
    """An unused selection can revert. Durable new economics require shared code."""
    root=Path(root).resolve();database=root/'portfolio.sqlite';shared=root/'shared-capital.sqlite'
    with open(str(database)+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with closing(RuntimeCapital(shared)) as authority:
            # Refuse even new durable reservations or acknowledgements; never
            # restart an old cash reconstruction against unaccounted activity.
            if authority.db.execute('SELECT count(*) FROM shared_capital_events').fetchone()[0]!=1:
                raise CapitalError('rollback_requires_shared_compatible_runtime_after_activity')
        with closing(sqlite3.connect(database,isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for table in TABLES:
                    for action in ('insert','update','delete'):db.execute(f'DROP TRIGGER shared_fence_{table}_{action}')
                db.execute('DROP TABLE portfolio_funding_authority');db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                raise
