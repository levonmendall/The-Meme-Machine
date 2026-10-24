"""One separate experimental PAPER epoch using the ordinary Pons economics.

Preparation and reporting are usable without a market connection. Live commands
fail closed until the standalone resource/storage integration is available; they
never borrow the original service or protected pilot's identity or acceptance.
"""
import argparse
from contextlib import closing
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time


EXPERIMENT = Path('/workspace/experiments/pons-simulator-20261024')
STATE = EXPERIMENT / 'state'
EPOCH = 'paper-pons-simulator-1000-20261024'
SOURCE = Path(__file__).resolve().parents[2]
RISK_FILE = SOURCE / 'operational/shared-capital-activation/risk-policy.shared-1000.proposed.json'
RISK_FILE_SHA256 = 'f2da6f2fa3f1451c1313be20bc3592d53070b70c62725cb0ac43fa6f3a73d034'
RISK_SHA256 = 'b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c'
OBLIGATIONS = ('reservations', 'commitments', 'obligations', 'pending_deliveries',
               'pending_backing', 'runtime_pending', 'runtime_inbox')


class SimulatorFailure(ValueError):
    """Fixed diagnostic codes only; provider configuration never enters output."""


def require(value, code):
    if not value:
        raise SimulatorFailure(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def physical(path):
    """Refuse an alias into an existing epoch, including dangling aliases."""
    path = Path(path)
    require(path.is_absolute(), 'SIMULATOR_ABSOLUTE_PATH_REQUIRED')
    for parent in reversed(path.parents):
        require(stat.S_ISDIR(parent.lstat().st_mode), 'SIMULATOR_PATH_NOT_PHYSICAL')
    require(not path.is_symlink(), 'SIMULATOR_PATH_NOT_PHYSICAL')
    return path


def new_ancestors(path):
    for node in reversed((path, *path.parents)):
        try:
            info = node.lstat()
        except FileNotFoundError:
            node.mkdir(mode=0o700)
            info = node.lstat()
        require(stat.S_ISDIR(info.st_mode), 'SIMULATOR_PATH_NOT_PHYSICAL')


def approved_risk():
    physical(RISK_FILE)
    before = RISK_FILE.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 65536,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    fd = os.open(RISK_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_gid, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        require(identity(os.fstat(fd)) == identity(before), 'SIMULATOR_RISK_CHANGED')
        raw = os.read(fd, 65537)
        require(identity(os.fstat(fd)) == identity(before) and len(raw) == before.st_size,
                'SIMULATOR_RISK_CHANGED')
    finally:
        os.close(fd)
    require(hashlib.sha256(raw).hexdigest() == RISK_FILE_SHA256,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    value = json.loads(raw)
    require(hashlib.sha256(canonical(value)).hexdigest() == RISK_SHA256,
            'SIMULATOR_APPROVED_RISK_REQUIRED')
    return value


def readonly(path):
    physical(path)
    require(path.is_file(), 'SIMULATOR_EXISTING_DATABASE_REQUIRED')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def export_state():
    """Replay the actual selected authority; never construct a financial writer."""
    from meme_machine.shared_capital.reporting import read_authority, export
    from meme_machine.shared_capital.runtime import selected
    physical(STATE)
    database = STATE / 'portfolio.sqlite'
    physical(database)
    physical(STATE / 'shared-capital.sqlite')
    require(selected(database) == STATE / 'shared-capital.sqlite', 'SIMULATOR_SHARED_AUTHORITY_REQUIRED')
    with closing(readonly(STATE / 'shared-capital.sqlite')) as db:
        reader = read_authority(db)
        reader.path = STATE / 'shared-capital.sqlite'
        replay = reader.verify_replay()
        ledger = reader._read()
        head = db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
        require(head and (replay['events'], replay['journal_hash'], replay['state_sha256']) == head,
                'SIMULATOR_REPLAY_HEAD_INVALID')
        require(ledger['epoch_id'] == EPOCH and Decimal(ledger['initial_capital']) == 1000
                and ledger['policy'] == approved_risk(), 'SIMULATOR_EPOCH_OR_RISK_MISMATCH')
        projection = export(reader, at=int(time.time()))
    with closing(readonly(database)) as db:
        pending = db.execute('SELECT count(*) FROM portfolio_native_pending').fetchone()[0]
    counts = {key: len(ledger.get(key, {})) for key in OBLIGATIONS}
    counts.update(positions_open=sum(p['status'] == 'OPEN' for p in ledger['positions'].values()),
                  legacy_native_pending=pending)
    require(not any(p['regime'] != 'pons_current' and p['status'] == 'OPEN'
                    for p in ledger['positions'].values()), 'SIMULATOR_FOREIGN_OPEN_POSITION')
    for bucket in ('reservations', 'commitments', 'obligations'):
        require(all(p['regime'] == 'pons_current' for p in ledger[bucket].values()),
                'SIMULATOR_FOREIGN_OBLIGATION')
    return dict(epoch_id=EPOCH, inception_sha256=ledger['inception_sha256'],
        sequence=head[0], journal_hash=head[1], projection_sha256=head[2],
        replay=replay, obligations=counts, portfolio=projection,
        admission_mode=ledger.get('runtime_admission', {}).get('mode'),
        current_readiness_verified=False, held_protection_demonstrated=False,
        autonomous_acceptance=False)


def prepare():
    """Create one new $1,000 epoch; existing or interrupted state is preserved."""
    require(not STATE.exists() and not STATE.is_symlink(), 'SIMULATOR_EPOCH_EXISTS_NO_RESEED')
    risk = approved_risk()
    # Only the experiment's new ancestors may be created. The native constructor
    # below owns the exclusive state-directory creation and refuses all reuse.
    new_ancestors(STATE.parent)
    physical(STATE)
    from meme_machine.portfolio_accounting import inception_receipt, PortfolioAccounting
    from meme_machine.operational.supervisor import identities
    from meme_machine.runtime.directional_sleeve import policies
    from meme_machine.runtime.usd_valuation import utc
    from meme_machine.shared_capital.operational_candidate import initialize_new_epoch
    from meme_machine.shared_capital.cutover import install
    from meme_machine.operational.backup import snapshot_database
    receipt = inception_receipt(EPOCH, utc(time.time()), EPOCH + ':inception',
                                starting_capital='1000.00', shared=True)
    ids = identities(receipt)
    contracts = {lane: dict(strategy_id=lane, policy_hash=ids[lane]['policy_hash'])
                 for lane in ('meteora', 'ramses')}
    for family in ('pump', 'pons'):
        for strategy, checksum in policies(family).items():
            regime = family + ('_survivor' if 'survivor' in strategy else '_current')
            contracts[regime] = dict(strategy_id=strategy, policy_hash=checksum)
    plan = initialize_new_epoch(STATE, receipt, portfolio_identities=ids['pump'],
        lane_identities=ids, contracts=contracts, policy=risk)
    backup = STATE / 'simulator-inception-backup.sqlite'
    snapshot_database(STATE / 'portfolio.sqlite', backup, time.monotonic() + 15)
    with closing(readonly(backup)) as db:
        reader = object.__new__(PortfolioAccounting)
        reader.db = db
        seed = reader._replay()
        reader._reconcile(seed)
        require(seed['receipt'] == receipt and not seed['positions'] and not seed['reservations'],
                'SIMULATOR_INCEPTION_BACKUP_INVALID')
    marker = install(STATE, plan, approved_policy=plan['policy'], observation_only=True,
        prerequisites=dict(writers_stopped=True, coherent_backup_verified=True,
            native_mapping_verified=True, recovery_verified=True, provider_proof_verified=False))
    (STATE / 'shared').mkdir(mode=0o700)
    return dict(state='PREPARED_FUNDING_CLOSED', marker=marker, financial=export_state(),
                original_state_imported=False, provider_history_imported=False,
                paper_only=True, real_money_authority=False)


def runtime_blockers(environ=None):
    """Configuration checks only: no provider call, public fallback or allowance."""
    env = os.environ if environ is None else environ
    blockers = []
    if not STATE.exists():
        blockers.append('SIMULATOR_NOT_PREPARED')
    from meme_machine.runtime.robinhood.provider_authority import endpoint
    try:
        endpoint(environ=env)
    except ValueError:
        blockers.append('CANONICAL_ALCHEMY_PROVIDER_NOT_CONFIGURED')
    # ba6 Supervisor authenticates only the original/protected-pilot cgroups and
    # ext4 storage identities. Neither proof applies to this workspace process.
    # No caller flag, borrowed service name or invented resource proof opens it.
    blockers.extend(('STANDALONE_RESOURCE_BINDING_UNAVAILABLE',
                     'STANDALONE_STORAGE_BINDING_UNAVAILABLE'))
    return blockers


def status():
    result = dict(state='UNPREPARED', epoch_id=EPOCH, paper_only=True,
                  real_money_authority=False, blockers=runtime_blockers())
    if STATE.exists() or STATE.is_symlink():
        result.update(state='LEDGER_RECONCILED', financial=export_state())
    return result


def runtime(command):
    require(command in ('shadow', 'run'), 'SIMULATOR_COMMAND_INVALID')
    result = status()
    # This adapter deliberately has no alternate strategy/quote/financial loop.
    # The ordinary Supervisor/lane must be used once its actual standalone
    # resource, storage and provider contracts have been implemented/validated.
    result.update(state='BLOCKED', requested_command=command, native_runtime_started=False,
                  shadow_accepted=False, held_protection_demonstrated=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'status', 'shadow', 'run'))
    args = parser.parse_args(argv)
    try:
        result = prepare() if args.command == 'prepare' else status() if args.command == 'status' else runtime(args.command)
    except (SimulatorFailure, OSError, ValueError, sqlite3.Error) as error:
        reason = str(error) if type(error) is SimulatorFailure else 'SIMULATOR_STATE_UNAVAILABLE'
        result = dict(state='REFUSED', reason=reason, paper_only=True, real_money_authority=False)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 2 if result['state'] in ('REFUSED', 'BLOCKED') else 0


if __name__ == '__main__':
    raise SystemExit(main())
