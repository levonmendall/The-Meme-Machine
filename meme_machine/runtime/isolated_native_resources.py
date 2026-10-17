"""Explicit nonfinancial native resources for a future contained bootstrap.

This is a component contract, not a sandbox or a complete native runner. The
protected parent must authenticate sizing receipts and contain filesystem and
transport access. No environment variable selects this path. Held positions,
fills, settlement and authoritative readiness are deliberately unexercised.
"""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import sqlite3
import threading

from meme_machine.runtime.journal import canonical, digest
from meme_machine.runtime.sleeve_reservations import SleeveReservations


class IsolatedFinancialWriteDenied(ValueError):
    pass


def reject_financial_construction(native_resources):
    """Run before path creation, SQLite open, genesis, replay or recovery."""
    if native_resources is not None:
        require_resources(native_resources)
        raise IsolatedFinancialWriteDenied('isolated_native_financial_constructor_denied')


def require_resources(value):
    if type(value) is not IsolatedNativeResources or value.closed:
        raise ValueError('isolated_native_resources_required')
    return value


class AuthenticatedSizingFacts:
    """Immutable, read-only facts; the caller supplies the parent authenticator.

    A checksum is not authentication. There is no default verifier, epoch DB
    reader, capital fallback or local positive-book constructor here.
    """
    __slots__ = ('_encoded', 'receipt_hash')

    def __init__(self, receipt, *, authenticate):
        encoded = canonical(receipt)
        # Verify the exact detached value retained below, not a mutable caller
        # object that could change between verification and consumption.
        value = json.loads(encoded)
        if not callable(authenticate) or authenticate(json.loads(encoded)) is not True:
            raise ValueError('isolated_sizing_authentication_required')
        expected = {'schema', 'scope', 'source_commit', 'source_tree',
                    'epoch_reference', 'portfolio_sequence', 'observed_at',
                    'valid_until', 'lanes'}
        if set(value) != expected or value['schema'] != 'isolated-native-sizing-v1':
            raise ValueError('isolated_sizing_shape')
        for field in ('source_commit', 'source_tree'):
            if (not isinstance(value[field], str) or len(value[field]) != 40
                    or any(c not in '0123456789abcdef' for c in value[field])):
                raise ValueError('isolated_sizing_source')
        if (not isinstance(value['scope'], str) or not value['scope']
                or not isinstance(value['epoch_reference'], str) or not value['epoch_reference']
                or type(value['portfolio_sequence']) is not int or value['portfolio_sequence'] < 0
                or type(value['observed_at']) is not int or type(value['valid_until']) is not int
                or not 0 < value['valid_until'] - value['observed_at'] <= 300
                or set(value['lanes']) != {'pump', 'pons'}):
            raise ValueError('isolated_sizing_identity')
        from meme_machine.runtime.directional_sleeve import policies
        for lane, facts in value['lanes'].items():
            if set(facts) != {'realized_equity', 'available', 'reserved', 'policies',
                              'native_unit', 'usd_evidence_hash', 'valuation_observed_at',
                              'valuation_valid_until'}:
                raise ValueError('isolated_sizing_lane_shape')
            if (any(type(facts[k]) is not int or facts[k] < 0
                    for k in ('realized_equity', 'available', 'reserved'))
                    or facts['policies'] != policies(lane)
                    or facts['native_unit'] != {'pump':'lamports','pons':'wei'}[lane]
                    or not isinstance(facts['usd_evidence_hash'], str)
                    or len(facts['usd_evidence_hash']) != 64
                    or any(c not in '0123456789abcdef' for c in facts['usd_evidence_hash'])
                    or type(facts['valuation_observed_at']) is not int
                    or type(facts['valuation_valid_until']) is not int
                    or not facts['valuation_observed_at'] <= value['observed_at'] <= facts['valuation_valid_until']
                    or not 0 < facts['valuation_valid_until']-facts['valuation_observed_at'] <=
                        {'pump':120,'pons':5}[lane]
                    or value['valid_until'] > facts['valuation_valid_until']):
                raise ValueError('isolated_sizing_lane_facts')
        object.__setattr__(self, '_encoded', encoded)
        object.__setattr__(self, 'receipt_hash', digest(value))

    def __setattr__(self, name, value):
        raise AttributeError('immutable_sizing_facts')

    def value(self):
        return json.loads(self._encoded)

    def require_fresh(self, lane, at):
        value = self.value()
        if lane not in value['lanes']:
            raise ValueError('isolated_sizing_lane')
        facts = value['lanes'][lane]
        if (type(at) is not int or not value['observed_at'] <= at <= value['valid_until']
                or not facts['valuation_observed_at'] <= at <= facts['valuation_valid_until']):
            raise ValueError('isolated_sizing_stale')
        return facts

    def basis(self, lane, target_bps, *, minimum_bps=0, at):
        if (type(target_bps) is not int or not 0 < target_bps <= 10000
                or type(minimum_bps) is not int or not 0 <= minimum_bps <= target_bps):
            raise ValueError('directional_sizing_bps')
        facts = self.require_fresh(lane, at)
        equity = facts['realized_equity']
        target = equity * target_bps // 10000
        return dict(realized_equity=equity, available=facts['available'],
                    reserved=facts['reserved'], target=target,
                    minimum=equity * minimum_bps // 10000,
                    target_bps=target_bps, minimum_bps=minimum_bps,
                    allocatable_target=min(target, facts['available']),
                    sizing_receipt_hash=self.receipt_hash,
                    provenance='authenticated_parent_readonly',
                    allocation_authority=False)


class IsolatedNativeResources:
    """Own a new disposable root without opening any financial authority.

    Existing directories are refused. A caller cannot redirect this component
    to an installed portfolio, a copied epoch or an old diagnostic root.
    The protected process boundary remains a separate required integration.
    """
    def __init__(self, root, *, sizing_facts, clock):
        if type(sizing_facts) is not AuthenticatedSizingFacts or not callable(clock):
            raise ValueError('isolated_native_construction')
        root = Path(root)
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError('isolated_native_root')
        # Do not create a root inside an authoritative state tree, even if the
        # requested leaf does not exist. No epoch/financial files are copied.
        markers = ('portfolio.sqlite', 'portfolio.sqlite3', 'native-genesis.json',
                   'paper.sqlite', 'directional-sleeve.sqlite')
        if any((parent / marker).exists() for parent in root.parents for marker in markers):
            raise ValueError('isolated_native_financial_ancestor')
        self.root = root
        self.facts = sizing_facts
        self.clock = clock
        self.closed = False
        self._lock = threading.RLock()
        self._sleeves = set()
        self._histories = []
        self._candidate_history = None
        self._native_histories = {}
        self._pons_plane = None
        root.mkdir(mode=0o700)  # Exclusive creation; never adopt existing state.
        self._owner = (root / '.isolated-native-owner').open('x+')
        fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self._owner.write(canonical(dict(schema='isolated-native-resources-v1',
            scope=sizing_facts.value()['scope'], sizing_receipt_hash=sizing_facts.receipt_hash,
            financial_authority=False, full_bootstrap_supported=False)))
        self._owner.flush()

    def basis(self, lane, target_bps, *, minimum_bps=0):
        require_resources(self)
        return self.facts.basis(lane, target_bps, minimum_bps=minimum_bps, at=int(self.clock()))

    def open_sleeve(self, lane, *, policies):
        require_resources(self)
        if lane not in ('pump', 'pons') or policies != self.facts.value()['lanes'][lane]['policies']:
            raise ValueError('isolated_native_policy')
        with self._lock:
            require_resources(self)
            sleeve = NativeObservationState(self, lane=lane, policies=policies)
            self._sleeves.add(sleeve)
            return sleeve

    def candidate_history(self):
        require_resources(self)
        with self._lock:
            require_resources(self)
            if self._candidate_history is None:
                from meme_machine.runtime.candidate_history import CandidateHistory
                self._candidate_history = CandidateHistory(self._unused_native_path('candidate-history.sqlite'), clock=self.clock)
                self._histories.append(self._candidate_history)
            return self._candidate_history

    def survivor_history(self, lane):
        require_resources(self)
        if lane not in ('pump','pons'):
            raise ValueError('isolated_native_history_lane')
        with self._lock:
            require_resources(self)
            if lane not in self._native_histories:
                if lane == 'pump':
                    from meme_machine.runtime.survivor_history import History
                    from meme_machine.lanes.pump.pumpswap_survivor import POLICY_HASH
                else:
                    from meme_machine.lanes.pons.pons_history import PonsHistory as History
                    from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY_HASH
                history = History(self._unused_native_path(lane+'-survivor-history.sqlite'), policy=POLICY_HASH)
                self._histories.append(history)
                self._native_histories[lane] = history
            return self._native_histories[lane]

    def pons_plane(self):
        require_resources(self)
        with self._lock:
            require_resources(self)
            if self._pons_plane is None:
                from meme_machine.runtime.robinhood.plane import Plane
                self._pons_plane = Plane(self._unused_native_path('pons-candidates.sqlite'), clock=self.clock)
                self._histories.append(self._pons_plane)
            return self._pons_plane

    def _unused_native_path(self, name):
        # These factories construct each owned store once. A preexisting file
        # is not a recovery point and cannot be adopted merely by its filename.
        path = self.root / name
        for suffix in ('','-wal','-shm','-journal'):
            member = Path(str(path)+suffix)
            if member.is_symlink():
                raise ValueError('isolated_native_state_symlink')
            if member.exists():
                raise ValueError('isolated_native_foreign_state')
        return path

    def require_survivor_history(self, history, lane):
        require_resources(self)
        if (history is None or self._native_histories.get(lane) is not history or
                history.path != self.root / (lane+'-survivor-history.sqlite') or history.path.is_symlink()):
            raise ValueError('isolated_native_survivor_history_owner')

    def require_pons_plane(self, plane):
        require_resources(self)
        if (plane is None or plane is not self._pons_plane or
                Path(plane.path) != self.root / 'pons-candidates.sqlite' or Path(plane.path).is_symlink()):
            raise ValueError('isolated_native_pons_plane_owner')

    def require_observation_state(self, state, lane):
        require_resources(self)
        if (type(state) is not NativeObservationState or state.resources is not self
                or state.closed or state.identity['lane'] != lane):
            raise ValueError('isolated_native_observation_owner')

    def require_history(self, history):
        require_resources(self)
        if (history not in self._histories or history.path != self.root / 'candidate-history.sqlite'
                or history.path.is_symlink()):
            raise ValueError('isolated_native_history_owner')

    def deny_qualified(self, history, decision_id, lane, candidate, *, mode, at,
                       qualification=None, vector=None, stage=None):
        """Preserve a genuine committed decision before recording denial.

        This is a nonfinancial funding observation. It does not create a native
        reservation, controller intent, portfolio delivery, ACK or settlement.
        """
        self.require_history(history)
        self.facts.require_fresh(lane, int(self.clock()))
        self.facts.require_fresh(lane, at)
        if history.db.in_transaction:
            raise ValueError('isolated_native_uncommitted_qualification')
        with history.transaction():
            row = history.db.execute('SELECT lane,candidate,mode,observed_at,qualified,body,hash '
                                     'FROM decisions WHERE id=?', (decision_id,)).fetchone()
            if not row:
                raise ValueError('isolated_native_durable_qualification_required')
            body = json.loads(row[5])
            if (digest(body) != row[6] or row[:3] != (lane, candidate, mode)
                    or row[4] != 1 or body.get('qualified') is not True
                    or body != dict(lane=lane, candidate=candidate, mode=mode,
                                    observed_at=row[3], qualified=True, decision=body['decision'])
                    or decision_id != digest([lane, candidate, mode, row[3], body])
                    or at < row[3]):
                raise ValueError('isolated_native_durable_qualification_invalid')
            decision = body['decision']
            if ((qualification is not None and canonical(decision.get('qualification')) != canonical(qualification))
                    or (vector is not None and canonical(decision.get('vector')) != canonical(vector))
                    or (stage is not None and decision.get('stage') != stage)):
                raise ValueError('isolated_native_qualification_mismatch')
            # The original decision was committed before entry. Verification
            # and native funding observation now share one writer transaction;
            # a concurrent writer cannot replace a row between those checks.
            history.record_funding(decision_id, lane, candidate, status='denied', at=at,
                reason='isolated_native_no_allocation', details=dict(
                    sizing_receipt_hash=self.facts.receipt_hash, allocation_authority=False,
                    qualification_preserved=True))
        return dict(decision_id=decision_id, status='denied', at=at,
                    reason='isolated_native_no_allocation', economic_rejection=False,
                    qualification_preserved=True, allocation_authority=False)

    def close(self):
        with self._lock:
            if self.closed:
                return
            for resource in (*self._sleeves, *reversed(self._histories)):
                resource.close()
            self._owner.close()
            self.closed = True


class NativeObservationState:
    """Native directional observation algorithms with no monetary tables.

    Only the listed native methods are reused. Financial methods, reconciliation
    and replay are absent, so a caller cannot interpret this as a funded book.
    """
    asset_key = SleeveReservations.asset_key
    candidate = SleeveReservations.candidate
    rally = SleeveReservations.rally
    _observe_rally = SleeveReservations._observe_rally
    observe = SleeveReservations.observe
    opportunity = SleeveReservations.opportunity
    _opportunity = SleeveReservations._opportunity

    def __init__(self, resources, *, lane, policies):
        self.resources = require_resources(resources)
        self.identity = dict(lane=lane, policies=dict(policies),
                             cohort=resources.facts.value()['scope'], financial_authority=False)
        self.lock = threading.RLock()
        self.closed = False
        path = resources.root / (lane + '-observations.sqlite')
        if any(p.is_symlink() for p in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm'))):
            raise ValueError('isolated_native_state_symlink')
        self.db = sqlite3.connect(path, timeout=1, isolation_level=None, check_same_thread=False)
        try:
            allowed = {'observation_identity', 'sleeve_candidates', 'sleeve_rallies',
                       'observation_journal', 'opportunity_links', 'opportunity_receipts',
                       'opportunity_journal_v1', 'opportunity_targets_v1', 'opportunity_scans_v1',
                       'opportunity_meta_v1', 'learning_facts_v1', 'learning_rollup_v1',
                       'learning_usage_v1'}
            existing = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing - allowed:
                raise ValueError('isolated_native_foreign_state')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS observation_identity(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sleeve_candidates(id TEXT PRIMARY KEY,generation INTEGER NOT NULL,body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sleeve_rallies(id TEXT PRIMARY KEY,body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS observation_journal(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS opportunity_links(asset TEXT PRIMARY KEY,body TEXT NOT NULL,at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS opportunity_receipts(id TEXT PRIMARY KEY,asset TEXT NOT NULL,at INTEGER NOT NULL,body TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS observation_no_update BEFORE UPDATE ON observation_journal BEGIN SELECT RAISE(ABORT,'append_only_observation'); END;
              CREATE TRIGGER IF NOT EXISTS observation_no_delete BEFORE DELETE ON observation_journal BEGIN SELECT RAISE(ABORT,'append_only_observation'); END;
            ''')
            self.db.execute('INSERT OR IGNORE INTO observation_identity VALUES(1,?)', (canonical(self.identity),))
            if self.db.execute('SELECT body FROM observation_identity WHERE id=1').fetchone()[0] != canonical(self.identity):
                raise ValueError('isolated_native_state_identity')
            self.verify_observations()
            from meme_machine.runtime.opportunity_telemetry import install
            with self.transaction():
                install(self.db, self.identity)
            self.opportunity_ready = True
            self.opportunity_error = None
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        require_resources(self.resources)
        if self.closed:
            raise ValueError('isolated_native_state_closed')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def _event(self, kind, row):
        if kind not in ('candidate', 'rally'):
            raise IsolatedFinancialWriteDenied('isolated_native_financial_event_denied')
        old = self.db.execute('SELECT seq,hash FROM observation_journal ORDER BY seq DESC LIMIT 1').fetchone()
        seq, previous = (old[0]+1, old[1]) if old else (1, '0'*64)
        if seq > 10000 or len(canonical(row).encode()) > 65536:
            raise ValueError('isolated_native_observation_bound')
        body = dict(kind=kind, row=row, identity=self.identity)
        self.db.execute('INSERT INTO observation_journal VALUES(?,?,?,?)',
                        (seq, canonical(body), previous, digest([seq, previous, body])))
        if kind == 'candidate':
            self.db.execute('INSERT OR REPLACE INTO sleeve_candidates VALUES(?,?,?)',
                            (row['id'], row['generation'], canonical(row)))
        else:
            self.db.execute('INSERT OR REPLACE INTO sleeve_rallies VALUES(?,?)', (row['id'], canonical(row)))

    def _protected_opportunity_assets(self):
        # No positions or financial constructor exist in this adapter. This
        # method is not used in a production sleeve and cannot release one.
        return set()

    def sizing_basis(self, target_bps, *, minimum_bps=0):
        return self.resources.basis(self.identity['lane'], target_bps, minimum_bps=minimum_bps)

    def verify_observations(self):
        previous = '0'*64
        count = 0
        projected = dict(candidate={}, rally={})
        for seq, raw, prior, checksum in self.db.execute('SELECT * FROM observation_journal ORDER BY seq'):
            body = json.loads(raw)
            if (seq != count+1 or prior != previous or checksum != digest([seq, prior, body])
                    or body.get('identity') != self.identity or body.get('kind') not in projected):
                raise ValueError('isolated_native_observation_corruption')
            projected[body['kind']][body['row']['id']] = body['row']
            count, previous = seq, checksum
        for kind, table in (('candidate', 'sleeve_candidates'), ('rally', 'sleeve_rallies')):
            actual = {key: json.loads(raw) for key, raw in self.db.execute('SELECT id,body FROM '+table)}
            if actual != projected[kind]:
                raise ValueError('isolated_native_observation_projection')
        return dict(schema='isolated-native-observation-verification-v1', events=count,
                    final_hash=previous, financial_authority=False,
                    full_bootstrap_supported=False, held_protection='UNEXERCISED',
                    fills='UNEXERCISED', settlement='UNEXERCISED')

    def close(self):
        with self.resources._lock:
            if not self.closed:
                self.db.close()
                self.closed = True
                self.resources._sleeves.discard(self)
