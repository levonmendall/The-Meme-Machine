"""Explicit stopped, constructor-free native readers; no start/funding authority.

The protected caller owns source authentication, the complete physical census
and the original stopped fences. Original absolute identities are map keys, so
a future pinned snapshot resolver need not rewrite hash-bearing native bodies.
This module never opens a file, changes cwd/environment, or creates a database.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import fcntl
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time

from meme_machine.runtime.journal import digest

MAX_ROWS = 100000
MAX_FIELD = 4 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class NativeDependencyUnavailable(ValueError):
    pass


def _require(value, code):
    if not value:
        raise NativeDependencyUnavailable(code)


def _identity(value):
    path = Path(value)
    _require(path.is_absolute() and '..' not in path.parts,
             'native_restore_original_absolute_identity_required')
    return path


class StoppedNativeReadContext:
    """One owner/fence-bound closed mapping of already-open readonly snapshots.

    ``databases`` maps immutable ORIGINAL absolute locators to real query-only
    connections. The caller must authenticate each connection's actual inode
    against its stopped census (or a verified retained-snapshot mapping).
    ``validate_snapshot`` rechecks that original scope, including exit fences;
    its return is not serialized or accepted from a native/provider document.
    No object here can itself attest those external acquisition premises.
    """
    def __init__(self, root, databases, *, validate_snapshot, deadline, artifacts=None,
                 validate_owner=None, pons_interpretation=None):
        _require(type(databases) is dict and 0 < len(databases) <= 512,
                 'native_restore_database_population')
        _require(callable(validate_snapshot) and type(deadline) in (int, float)
                 and math.isfinite(deadline),
                 'native_restore_snapshot_owner_required')
        self.root = _identity(root)
        self._databases = {_identity(path): db for path, db in databases.items()}
        _require(len(self._databases) == len(databases)
                 and all(path.is_relative_to(self.root) for path in self._databases)
                 and len({id(db) for db in self._databases.values()}) == len(databases),
                 'native_restore_database_identity')
        artifacts = {} if artifacts is None else artifacts
        _require(type(artifacts) is dict and len(artifacts) <= 4096,
                 'native_restore_artifact_population')
        self._artifacts = {}
        for name, fd in artifacts.items():
            path = _identity(name)
            _require(path.is_relative_to(self.root) and type(fd) is int and fd >= 0,
                     'native_restore_artifact_identity')
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
                     and fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC,
                     'native_restore_artifact_readonly_required')
            self._artifacts[path] = (fd, self._file_identity(info))
        self._validate_snapshot = validate_snapshot
        _require(validate_owner is None or callable(validate_owner), 'native_restore_owner_reader')
        self._validate_owner = validate_owner
        _require(pons_interpretation is None or type(pons_interpretation) is dict,
                 'native_restore_pons_interpretation')
        self._pons_interpretation = deepcopy(pons_interpretation)
        self._stopped_owners = set()
        self.deadline = deadline
        self._owner = (os.getpid(), threading.get_ident())
        self._used = set()
        self._closed = False
        self._state = None
        self._legacy_state = None
        self._input_bytes = 0
        self._bounded_tables = set()
        self._bounded_artifacts = set()
        self._bounded_source_records = set()
        self._row_factories = {}
        self._views = {}
        self.check()
        self.verify_boundary()

    def _check_owner_deadline(self):
        _require(not self._closed and self._owner == (os.getpid(), threading.get_ident()),
                 'native_restore_context_owner')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('native_restore_deadline')

    def check(self):
        self._check_owner_deadline()
        for db in self._databases.values():
            _require(type(db) is sqlite3.Connection and db.in_transaction
                     and db.execute('PRAGMA query_only').fetchone()[0] == 1,
                     'native_restore_readonly_snapshot_required')

    def verify_boundary(self):
        self.check()
        _require(self._validate_snapshot() is True, 'native_restore_snapshot_changed')

    def require_owner_stopped(self, identity):
        self.check()
        _require(type(identity) is str and 0 < len(identity) <= 512,
                 'native_restore_owner_unverified')
        if identity in self._stopped_owners:
            return
        _require(len(self._stopped_owners) < 32 and self._validate_owner is not None
                 and self._validate_owner(identity) is True,
                 'native_restore_owner_unverified')
        # This context cannot outlive the original stopped fence. Rechecking a
        # repeated saved identity per candidate would add arbitrary proc probes.
        self._stopped_owners.add(identity)

    @property
    def pons_interpretation(self):
        self.check()
        return deepcopy(self._pons_interpretation)

    def identity(self, value, *, base=None):
        path = Path(value)
        if not path.is_absolute():
            _require(base is not None and '..' not in path.parts,
                     'native_restore_relative_identity_without_base')
            path = _identity(base) / path
        return _identity(path)

    def trial_identity(self, value, *, root):
        # Native relative trial locators are relative to the Pons family cwd,
        # not the cohort directory. Keep their original body bytes unchanged.
        path = self.identity(value, base=self.root / 'pons')
        _require(path.parent == self.identity(root), 'native_restore_trial_root')
        return path

    @staticmethod
    def _file_identity(info):
        return tuple(getattr(info, key) for key in
                     ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))

    def read_artifact(self, value, *, sha256, maximum=MAX_ARTIFACT_BYTES):
        self.check()
        _require(type(maximum) is int and 0 <= maximum <= MAX_ARTIFACT_BYTES,
                 'native_restore_artifact_bound')
        path = self.identity(value)
        _require(path in self._artifacts, 'native_restore_artifact_outside_census')
        fd, identity = self._artifacts[path]
        _require(identity == self._file_identity(os.fstat(fd)) and 0 <= identity[4] <= maximum,
                 'native_restore_artifact_changed')
        if path not in self._bounded_artifacts:
            self._input_bytes += identity[4]
            _require(self._input_bytes <= MAX_INPUT_BYTES, 'native_restore_payload_bound')
        parts = []
        offset = 0
        checksum = hashlib.sha256()
        while offset < identity[4]:
            self.check()
            data = os.pread(fd, min(65536, identity[4] - offset), offset)
            _require(bool(data), 'native_restore_artifact_changed')
            checksum.update(data)
            parts.append(data)
            offset += len(data)
        _require(identity == self._file_identity(os.fstat(fd)) and checksum.hexdigest() == sha256,
                 'native_restore_artifact_hash')
        self._used.add(path)
        self._bounded_artifacts.add(path)
        return b''.join(parts)

    def contains(self, value, *, base=None):
        self.check()
        return self.identity(value, base=base) in self._databases

    def reference_identity(self, value, *, candidate_path, cold=False):
        """Existing fixed restored-cohort alias, authenticated by this census."""
        path = self.identity(value)
        population = self._artifacts if cold else self._databases
        if path in population:
            return path
        from .candidate_history import (RETAINED_REFERENCE_LEGACY_ROOT,
                                        RETAINED_REFERENCE_AWS_ROOT, RETAINED_REFERENCE_EPOCH)
        old = RETAINED_REFERENCE_LEGACY_ROOT / 'shared/solana-evidence.sqlite'
        source = self.root / 'shared/solana-evidence.sqlite'
        _require(self.root == RETAINED_REFERENCE_AWS_ROOT
                 and self.cohort_id == RETAINED_REFERENCE_EPOCH
                 and candidate_path == self.root / 'shared/solana-candidate-history.sqlite',
                 'native_restore_reference_cohort_unverified')
        if cold:
            name = path.name
            _require(path.parent == old.with_suffix('.scoped-cold') and len(name) == 69
                     and name.endswith('.zlib') and all(c in '0123456789abcdef' for c in name[:-5]),
                     'native_restore_reference_cohort_unverified')
            target = source.with_suffix('.scoped-cold') / name
        else:
            _require(path == old, 'native_restore_reference_cohort_unverified')
            target = source
        _require(target in population, 'native_restore_dependency_outside_census')
        return target

    def require_database(self, db):
        self.check()
        _require(any(db is owned for owned in self._databases.values()),
                 'native_restore_database_outside_census')
        return db

    def bound_bodies(self, db, tables):
        """Prebound all fields of complete fixed reducer populations.

        Scalar discovery tables and duplicate identity columns are inputs too;
        checking only a JSON body would leave those populations unbounded.
        """
        self.require_database(db)
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 257")}
        _require(len(present) <= 256, 'native_restore_schema_bound')
        for table in tables:
            _require(type(table) is str and table.replace('_', '').isalnum(),
                     'native_restore_fixed_table_required')
            key = (id(db), table)
            if table not in present or key in self._bounded_tables:
                continue
            columns = [row[1] for row in db.execute('PRAGMA table_info("' + table + '")')]
            _require(0 < len(columns) <= 64 and all(type(name) is str
                     and name.replace('_', '').isalnum() for name in columns),
                     'native_restore_schema_bound')
            lengths = ','.join('length(CAST("' + name + '" AS BLOB))' for name in columns)
            count = 0
            for row in db.execute('SELECT ' + lengths + ' FROM "' + table + '"'):
                count += 1
                _require(count <= MAX_ROWS and all(length is None
                         or type(length) is int and 0 <= length <= MAX_FIELD for length in row),
                         'native_restore_payload_bound')
                self._input_bytes += sum(length or 0 for length in row)
                _require(self._input_bytes <= MAX_INPUT_BYTES, 'native_restore_payload_bound')
                if count % 128 == 0:
                    self.check()
            self._bounded_tables.add(key)
        self.check()

    def paper(self, path, regime):
        from meme_machine.runtime.policy_compatibility import known_hash, regime_for, require_flat_rows
        from meme_machine.runtime.survivor_paper_book import PaperBook
        if regime == 'pump_current':
            from meme_machine.lanes.pump.paper_accounting import PaperBook
        _require(regime in ('pump_current', 'pump_survivor', 'pons_survivor'), 'native_restore_regime')
        key = ('paper', self.identity(path), regime)
        if key not in self._views:
            with self.database(path) as db:
                self.bound_bodies(db, ('genesis', 'positions', 'journal', 'journal_archive', 'runtime_state'))
                book = object.__new__(PaperBook)
                book.db = db
                book.lock = threading.RLock()
                book.identity = json.loads(db.execute('SELECT body FROM genesis WHERE id=1').fetchone()[0])
                book._readonly_shared_authority = self
                _require(known_hash(regime, book.identity['policy_hash']), 'native_restore_paper_policy')
                _require(set(book.identity) == {'run_id','lane','policy_hash','initial'}
                         and type(book.identity['initial']) is int and book.identity['initial'] >= 0
                         and regime_for(book.identity['lane']) == regime,
                         'native_restore_paper_identity')
                _require(book.identity['run_id'] == self.cohort_id, 'native_restore_paper_epoch')
                book.replay()
                rows = [json.loads(raw) for raw, in db.execute('SELECT body FROM positions')]
                require_flat_rows(rows, kind='pump')
                for identity, name in db.execute('SELECT identity,key FROM runtime_state'):
                    book.runtime_state(identity, name)
                self._views[key] = book
        return self._views[key]

    def sleeve(self, lane):
        from meme_machine.shared_capital.native_sleeve import SharedSleeve
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.policy_compatibility import known_hash, regime_for, require_flat_rows
        key = ('sleeve', lane)
        if key not in self._views:
            with self.database(self.sleeve_path(lane)) as db:
                self.bound_bodies(db, ('sleeve_genesis', 'sleeve_positions', 'sleeve_journal',
                                      'sleeve_archive', 'sleeve_candidates', 'sleeve_rallies'))
                sleeve = object.__new__(SharedSleeve)
                sleeve.db = db
                sleeve.lock = threading.RLock()
                sleeve.authority = self
                sleeve.identity = json.loads(db.execute('SELECT body FROM sleeve_genesis WHERE id=1').fetchone()[0])
                _require(sleeve.identity['lane'] == lane and sleeve.identity['cohort'] == self.cohort_id
                         and sleeve.identity['paper_only'] is True
                         and set(sleeve.identity['policies']) == set(policies(lane))
                         and all(known_hash(regime_for(strategy), policy)
                                 for strategy, policy in sleeve.identity['policies'].items()),
                         'native_restore_sleeve_identity')
                sleeve.reconcile()
                require_flat_rows([json.loads(raw) for raw, in db.execute('SELECT body FROM sleeve_positions')],
                                  kind='sleeve')
                self._views[key] = sleeve
        return self._views[key]

    def bound_trial(self, db):
        self.bound_bodies(db, ('records', 'pons_selective_paper', 'pons_journal_checkpoint',
                              'pons_selective_controller_groups'))

    def store(self, path):
        from meme_machine.lanes.pons.evidence import Store
        with self.database(path) as db:
            self.bound_trial(db)
            store = object.__new__(Store)
            store.db = db
            for category, identity in db.execute('SELECT category,id FROM records'):
                store.get(category, identity)
            return store

    def history(self, path, lane):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.policy_compatibility import known_hash
        cls = History
        if lane == 'pons':
            from meme_machine.lanes.pons.pons_history import PonsHistory
            cls = PonsHistory
        _require(lane in ('pump', 'pons'), 'native_restore_lane')
        with self.database(path) as db:
            self.bound_bodies(db, ('meta', 'candidates', 'events', 'points', 'pons_graduation_intake'))
            history = object.__new__(cls)
            history.db = db
            history.path = self.identity(path)
            history.maximum_candidates = None
            history.maximum_points = 100000
            for (name,) in db.execute('SELECT key FROM meta'):
                history.get_meta(name)
            _require(known_hash(lane + '_survivor', history.get_meta('policy')),
                     'native_restore_history_policy')
            history.rows(include_retired=True)
            return history

    def candidate_history(self, path):
        from .candidate_history import CandidateHistory
        with self.database(path) as db:
            self.bound_bodies(db, ('candidates', 'events', 'canonical_event_refs', 'state_checkpoints',
                                  'decisions', 'funding', 'work', 'work_observations', 'history_coverage'))
            history = object.__new__(CandidateHistory)
            history.path = self.identity(path)
            history.db = db
            history.clock = time.time
            history._native_read_context = self
            history._source_readers = {}
            return history

    def canonical_record(self, path, identity):
        """Bound the original canonical lookup before fetching encoded content."""
        with self.database(path) as db:
            self.bound_bodies(db, ('hot_chunks', 'scoped_cold_manifests'))
            key = (id(db), identity)
            if key not in self._bounded_source_records:
                lengths = db.execute('SELECT length(CAST(body AS BLOB)),length(CAST(hash AS BLOB)),'
                    'length(CAST(archive AS BLOB)) FROM canonical_evidence WHERE identity=?',
                    (identity,)).fetchone()
                if lengths is None:
                    return None, db
                _require(len(self._bounded_source_records) < MAX_ROWS and all(length is None
                         or type(length) is int and 0 <= length <= MAX_FIELD for length in lengths),
                         'native_restore_payload_bound')
                self._input_bytes += sum(length or 0 for length in lengths)
                _require(self._input_bytes <= MAX_INPUT_BYTES, 'native_restore_payload_bound')
                self._bounded_source_records.add(key)
            row = db.execute('SELECT body,hash,archive FROM canonical_evidence WHERE identity=?',
                             (identity,)).fetchone()
            return row, db

    def pons_plane(self, path):
        from .robinhood.plane import Plane
        with self.database(path) as db:
            self.bound_bodies(db, ('runtime', 'pons_attempts', 'pons_current_watch', 'observations',
                                  'evidence', 'rolling', 'candidates', 'transitions',
                                  'observation_archive', 'result_consumption', 'window_history_archive',
                                  'pons_scout_events', 'pons_scout_pools'))
            plane = object.__new__(Plane)
            plane.db = db
            self._row_factories.setdefault(db, db.row_factory)
            db.row_factory = sqlite3.Row
            plane.path = str(self.identity(path))
            plane.lock = threading.RLock()
            return plane

    def capital(self, path):
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import STRATEGY_NAMESPACE
        from .policy_compatibility import known_hash, require_flat_rows
        with self.database(path) as db:
            self.bound_bodies(db, ('capital_genesis', 'capital_positions', 'capital_journal',
                                  'capital_archive', 'runtime_state'))
            genesis = json.loads(db.execute('SELECT body FROM capital_genesis WHERE id=1').fetchone()[0])
            _require(known_hash('pons_current', genesis['policy_hash']), 'native_restore_capital_policy')
            _require(type(genesis['capital']) is int and genesis['capital'] > 0 and genesis ==
                     dict(capital=genesis['capital'],policy_hash=genesis['policy_hash'],
                          namespace=STRATEGY_NAMESPACE,asset='robinhood_native_quote',paper_only=True),
                     'native_restore_capital_identity')
            book = object.__new__(CohortCapital)
            book.path = str(self.identity(path))
            book.capital = genesis['capital']
            proof = book.reconcile(read_context=self)
            _require(proof.get('conservation') is True
                     and proof.get('native_observation_complete') is True
                     and proof.get('cash_basis_conservation') is True
                     and proof.get('capital_integral_complete') is True,
                     'native_restore_capital_replay')
            require_flat_rows([json.loads(raw) for raw, in db.execute('SELECT body FROM capital_positions')],
                              kind='capital')
            return book, proof

    @contextmanager
    def database(self, value, *, base=None):
        self.check()
        path = self.identity(value, base=base)
        _require(path in self._databases, 'native_restore_dependency_outside_census')
        self._used.add(path)
        yield self._databases[path]
        self.check()

    @property
    def portfolio_path(self):
        return self.root / 'portfolio.sqlite'

    @property
    def shared_path(self):
        return self.root / 'shared-capital.sqlite'

    def sleeve_path(self, lane):
        _require(lane in ('pump', 'pons'), 'native_restore_lane')
        return self.root / lane / 'directional-sleeve.sqlite'

    def authenticate_authority(self):
        """Original financial replay/selection and global all-regime flatness."""
        self.check()
        _require(self._state is None, 'native_restore_authority_already_authenticated')
        from meme_machine.shared_capital.runtime import RuntimeCapital
        from meme_machine.portfolio_accounting import PortfolioAccounting
        from meme_machine.runtime.policy_compatibility import require_flat_portfolio

        class ReadOnlyCapital(RuntimeCapital):
            @contextmanager
            def _transaction(reader, *, write=True):
                _require(write is False, 'native_restore_financial_write_refused')
                with self.database(self.shared_path) as db:
                    _require(reader.db is db, 'native_restore_authority_connection')
                    yield

            def _replay_prefix_key(reader):
                # Full cold replay on this detached stopped scope. No host path
                # stat or cross-evaluation process cache authenticates a copy.
                return None

            def command(reader, *args, **kwargs):
                raise NativeDependencyUnavailable('native_restore_financial_write_refused')

        with self.database(self.shared_path) as db:
            self.bound_bodies(db, ('shared_capital_projection', 'shared_capital_events',
                                  'shared_capital_archive'))
            reader = object.__new__(ReadOnlyCapital)
            reader.db = db
            reader.path = self.shared_path
            reader.fault = None
            reader._replaying = False
            # Reuse the original per-event cold replay cancellation boundary.
            # This checks only local owner/deadline; full snapshot/fence checks
            # still bracket the scope, without one PRAGMA per DB per event.
            reader._startup_replay_cancel = self._check_owner_deadline
            proof = reader.verify_replay()
            state = reader._read()
            _require(proof.get('conservation') is True and state is not None,
                     'native_restore_authority_replay')
            require_flat_portfolio(state)
            _require(not any(state.get(key) for key in (
                'reservations', 'commitments', 'obligations', 'pending_deliveries',
                'pending_backing', 'runtime_pending', 'runtime_inbox')),
                'native_restore_authority_obligations')
        with self.database(self.portfolio_path) as db:
            self.bound_bodies(db, ('portfolio_inception', 'portfolio_sleeves',
                                  'portfolio_checkpoint', 'portfolio_native_ids',
                                  'portfolio_native_pending', 'portfolio_events',
                                  'portfolio_funding_authority'))
            account = object.__new__(PortfolioAccounting)
            account.db = db
            legacy = account._replay()
            _require(legacy is not None, 'native_restore_legacy_replay')
            reconciliation = account._reconcile(legacy)
            _require(not legacy['reservations'] and reconciliation['deployed'] == 0
                     and not any(position.get('state') == 'OPEN'
                                 for position in legacy['positions'].values()),
                     'native_restore_legacy_obligations')
            selected = db.execute('SELECT body FROM portfolio_funding_authority WHERE id=1').fetchone()
            _require(selected is not None, 'native_restore_selected_authority')
            selected = json.loads(selected[0])
            _require(selected.get('state') == 'SHARED'
                     and selected.get('epoch_id') == state['epoch_id']
                     and selected.get('inception_sha256') == state['inception_sha256']
                     and selected.get('policy_sha256') == digest(state['policy'])
                     and legacy['receipt_hash'] == state['inception_sha256']
                     and legacy['receipt']['epoch_id'] == state['epoch_id'],
                     'native_restore_authority_selection_join')
            _require(not db.execute('SELECT 1 FROM portfolio_native_pending LIMIT 1').fetchone(),
                     'native_restore_legacy_native_pending')
        self._state = deepcopy(state)
        self._legacy_state = deepcopy(legacy)
        self._authority_proof = deepcopy(proof)
        self.check()
        return deepcopy(proof)

    def ledger(self):
        self.check()
        _require(self._state is not None, 'native_restore_authority_not_authenticated')
        return deepcopy(self._state)

    @property
    def cohort_id(self):
        return self.ledger()['epoch_id']

    @property
    def database_identities(self):
        self.check()
        return frozenset(self._databases)

    def close(self):
        # Borrowed handles/fences belong to the protected original caller.
        _require(not self._closed and self._owner == (os.getpid(), threading.get_ident()),
                 'native_restore_context_owner')
        try:
            self.verify_boundary()
        finally:
            for db, factory in self._row_factories.items():
                db.row_factory = factory
            self._closed = True


def require_read_context(value):
    _require(type(value) is StoppedNativeReadContext, 'native_restore_read_context_required')
    value.check()
    return value
