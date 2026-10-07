"""Read-only obligation proof before any active lane or evidence worker starts."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from meme_machine.runtime.operating_families import PAUSED_LANES


class PauseExposure(RuntimeError):
    def __init__(self, obligations):
        self.obligations = obligations
        super().__init__('paused_lane_has_active_or_pending_exposure:' +
                         json.dumps(obligations, sort_keys=True, separators=(',', ':')))


def native_positions(db, lane):
    """Use existing pure replay, without constructors, migrations or providers."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = []
    if 'events' in tables and lane == 'meteora':
        from meme_machine.lanes.meteora.dlmm_independent_accounting import PaperBook
        reader = object.__new__(PaperBook)
        first = db.execute('SELECT body FROM events WHERE seq=1').fetchone()
        if first is None:raise ValueError('native_genesis_unavailable')
        reader.genesis = json.loads(first[0])['data']
        reader.run_id=reader.genesis['run_id'];reader.policy_hash=reader.genesis['policy_hash']
        rows.extend(dict(row,id=identity) for identity,row in reader._replay(db)['positions'].items())
    if 'ramses_strategy_position' in tables:
        from meme_machine.lanes.ramses.ramses_strategy_ledger import RamsesStrategyLedger,_digest
        reader = object.__new__(RamsesStrategyLedger);reader.db = db
        raw, checksum = db.execute("SELECT body,hash FROM ramses_strategy_meta WHERE id='genesis'").fetchone()
        genesis = json.loads(raw)
        if _digest(genesis) != checksum:raise ValueError('native_genesis_corrupt')
        reader.paper_capital = genesis['paper_capital'];reader.quote_asset = genesis['quote_asset']
        reader._reconcile()
        rows.extend(json.loads(r[0]) for r in db.execute('SELECT body FROM ramses_strategy_position'))
    if 'sleeve_positions' in tables:
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        reader = object.__new__(SleeveReservations);reader.db = db
        reader.identity = json.loads(db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
        reader._reconcile()
        rows.extend(json.loads(r[0]) for r in db.execute('SELECT body FROM sleeve_positions'))
    # A previously unknown economic store cannot be treated as empty just
    # because the current portfolio lacks its delivery. Evidence-only stores
    # have no positions/orders/intents/obligations tables.
    known = {'ramses_strategy_position', 'sleeve_positions'}
    unknown = {t for t in tables if any(x in t for x in ('position','order','intent','obligation')) and
               t not in known and t not in {'candidate_pending_proofs','rolling_order_assignments'}}
    if unknown:raise ValueError('unverified_native_economic_tables:' + ','.join(sorted(unknown)))
    return rows


def assert_clear(root, account):
    root = Path(root);state = account.snapshot();obligations = []
    def add(lane, kind, identity, **fields):
        obligations.append(dict(lane=lane,kind=kind,identity=identity,**fields))
    shared=root/'shared/robinhood-evidence.candidates.sqlite'
    if shared.exists():
        try:
            if shared.is_symlink():raise ValueError('symlink')
            with closing(sqlite3.connect(shared.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                for key,raw in db.execute("SELECT key,body FROM runtime WHERE key LIKE 'native_position:ramses:%'"):
                    row=json.loads(raw)['position']
                    if row['status'] not in ('settled','cancelled','written_off') or row.get('held',0):
                        add('ramses','shared_native_projection',row['id'],path=str(shared.relative_to(root)))
        except (sqlite3.Error,ValueError,KeyError,TypeError) as exc:
            add('ramses','unverified_shared_store',str(shared.relative_to(root)),reason=str(exc))
    for lane in PAUSED_LANES:
        for kind in ('positions','reservations'):
            for identity,row in state[kind].items():
                if row['lane'] == lane:add(lane,kind,identity)
        for native,body in account.db.execute('SELECT native,body FROM portfolio_native_pending WHERE lane=?',(lane,)):
            event=json.loads(body)
            add(lane,'native_delivery',native,event_id=event.get('native_event_id'),action=event.get('kind'))
        folder = root/lane
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                add(lane,'unverified_state',str(path.relative_to(root)),reason='symlink');continue
            if not path.is_file():continue
            if path.name.endswith(('.sqlite','.sqlite3')):
                try:
                    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
                        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                        if db.execute('PRAGMA quick_check(1)').fetchall() != [('ok',)]:
                            raise ValueError('native_integrity')
                        for row in native_positions(db,lane):
                            if row.get('status') not in ('settled','cancelled','written_off') or row.get('held',0):
                                add(lane,'native_position',row.get('id','unknown'),
                                    path=str(path.relative_to(root)),status=row.get('status'))
                except (sqlite3.Error,ValueError,KeyError,TypeError) as exc:
                    add(lane,'unverified_native_store',str(path.relative_to(root)),reason=str(exc))
            elif 'continuation' in path.name or 'intent' in path.name:
                try:
                    value=json.loads(path.read_text())
                    if value.get('active') or value.get('pending_intent') or value.get('pending'):
                        add(lane,'native_intent',str(path.relative_to(root)))
                except (OSError,ValueError,AttributeError):
                    add(lane,'unverified_native_intent',str(path.relative_to(root)))
    if obligations:raise PauseExposure(obligations)
    return {lane:dict(economic_obligations=0,native_state_verified=True) for lane in PAUSED_LANES}
