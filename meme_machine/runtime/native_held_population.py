"""Dormant original-native book observations, never held/readiness authority.

Capture runs on the real native owner and reuses its successful original replay
and outer COMMIT. Path/inode metadata associates that owned handle; it is not a
kernel SQLite-FD proof. Approved code/exclusive launch and trusted root/OS are
the same append-only premises as held_financial_prefix. No default path enables
this observer, and no book/candidate/provider scan is introduced by this module.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from meme_machine.shared_capital.model import CapitalError, digest
from .held_financial_prefix import _FinancialPrefix, _lease_check

_MAX_BYTES = 32 * 1024 * 1024
_MAX_MEMBERS = 32768
_MAX_STAGE = 64
_MAX_BOOKS = 512
_BOOK_PATHS = {
    'PUMP_CURRENT':'pump/pump-acceleration-natural-prospective.accounting.sqlite3',
    'PUMP_SURVIVOR':'pump/pump-survivor/paper.sqlite',
    'PONS_SURVIVOR':'pons/pons-selective-continuation-v1-cohort/pons-survivor/paper.sqlite',
}
_COHORT = 'pons/pons-selective-continuation-v1-cohort'
_MISSING = ('COHORT_TRIAL_CENSUS', 'PUMP_SLEEVE', 'PONS_SLEEVE',
            'NATIVE_CONTROLLERS_AND_HISTORY', 'PAUSED_AND_LEGACY',
            'LIVE_PHYSICAL_OWNER_COMPOSITION')


def _encode(value, remaining, check):
    """Admit ASCII JSON size before allocating its detached encoded copy."""
    size = 0
    def add(n):
        nonlocal size
        size += n
        if size > remaining:raise ValueError('native_held_metadata_bound')
    def walk(row):
        check()
        if type(row) is str:
            add(2)
            for index, char in enumerate(row):
                if index % 1024 == 0:check()
                code = ord(char)
                add(2 if char in '"\\\b\f\n\r\t' else 6 if code < 32 or 126 < code <= 65535
                    else 12 if code > 65535 else 1)
        elif row is None:add(4)
        elif type(row) is bool:add(4 if row else 5)
        elif type(row) in (int, float):
            add(len(json.dumps(row, allow_nan=False)))
        elif type(row) in (list, tuple):
            add(2 + max(0, len(row)-1))
            for item in row:walk(item)
        elif type(row) is dict:
            add(2 + max(0, len(row)-1))
            for key, item in row.items():
                if type(key) is not str:raise ValueError('native_held_json_key')
                walk(key);add(1);walk(item)
        else:raise ValueError('native_held_json_type')
    walk(value)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    check()
    if len(raw) != size:raise ValueError('native_held_json_size')
    return raw


@dataclass(frozen=True)
class _Member:
    identity: str
    version: int
    previous_hash: str | None
    journal_hash: str
    body: str = field(repr=False)
    body_sha256: str


@dataclass(frozen=True)
class _NativeView:
    status: str
    reason: str
    role: str | None
    owner_sha256: str
    book_key: str | None
    genesis: str | None = field(repr=False)
    members: tuple = field(repr=False)
    committed_events: int
    staged_events: int
    error: Exception | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _NativeJoin:
    status: str
    link_status: str
    financial_sequence: int
    financial_journal_hash: str
    links: tuple = field(repr=False)
    unresolved: tuple
    financial_pending_counts: tuple
    financial_pending: tuple = field(repr=False)
    missing: tuple
    protection: str = 'UNEXERCISED'
    funding_authority: bool = False
    readiness: bool = False

    def summary(self):
        """Fixed bounded counts only; identities and native bodies stay private."""
        return dict(schema='native-held-book-links-v1', status='INCOMPLETE',
            link_status=self.link_status, financial_sequence=self.financial_sequence,
            financial_journal_hash=self.financial_journal_hash,
            matched_native_versions=len(self.links), unresolved=len(self.unresolved),
            native_committed_global_pending=sum(row[-1]=='NATIVE_COMMITTED_GLOBAL_PENDING' for row in self.links),
            financial_pending_counts=self.financial_pending_counts,
            missing=self.missing, protection='UNEXERCISED',
            funding_authority=False, readiness=False, held_boot=False)


class _NativePopulationCapture:
    """Bounded local owner collection; not a complete cross-owner census."""
    def __init__(self, owner, *, deadline, cancelled):
        from meme_machine.operational import normal_pump_boot as pump, normal_pons_boot as pons
        if type(owner) is pump.NativePumpOwnerContext:self._require = pump.require_pump_owner_context
        elif type(owner) is pons.NativePonsOwnerContext:self._require = pons.require_pons_owner_context
        else:raise TypeError('native_held_private_owner_required')
        self._owner = self._require(owner)
        self._identity, self._owner_sha = owner.identity(), owner.identity_sha256
        self._thread = os.getpid(), threading.get_ident()
        self._check_lease = _lease_check(deadline, cancelled)
        self._books, self._used, self._staged_count, self._member_count = [], 0, 0, 0
        self._check()

    def __reduce__(self):raise TypeError('native_held_population_is_process_private')

    def _check(self):
        if self._thread != (os.getpid(), threading.get_ident()):
            raise CapitalError('native_held_foreign_owner')
        self._check_lease()
        if self._require(self._owner) is not self._owner or self._owner.identity_sha256 != self._owner_sha:
            raise CapitalError('native_held_owner_changed')

    def book(self):
        self._check()
        if len(self._books) >= _MAX_BOOKS:raise ValueError('native_held_book_bound')
        result = _NativePaperCapture(self)
        self._books.append(result)
        return result


class _NativePaperCapture:
    """One original book, issued by its bounded private owner collection."""
    def __init__(self, population):
        if type(population) is not _NativePopulationCapture:
            raise TypeError('native_held_private_population_required')
        population._check()
        self._population = population
        self._identity, self._owner_sha = population._identity, population._owner_sha
        self._book = self._db = self._physical = self._key = self._role = self._genesis = None
        self._members, self._staged = {}, []
        self._bytes, self._head, self._committed = 0, (0, '0'*64), 0
        self._initialized, self._failure = False, None
        self._incomplete = None
        self._check()

    def __reduce__(self):raise TypeError('native_held_capture_is_process_private')

    def _check(self):
        self._population._check()

    def _observe(self, method, *args):
        if self._failure is not None:return None
        try:
            self._check()
            return method(*args)
        except Exception as exc:
            # Observer errors must not retain replay/staging input frames
            # outside the shared metadata allowance. Native exceptions never
            # pass through this path and retain their original traceback.
            exc.__traceback__ = exc.__context__ = exc.__cause__ = None
            self._failure = exc
            return None

    def _attach(self, book, path, genesis, issuer):
        return self._observe(self._binding, book, path, genesis, issuer)

    def _binding(self, book, path, genesis, issuer):
        from meme_machine.runtime import survivor_paper_book as survivor
        from meme_machine.lanes.pump.paper_accounting import PaperBook as Current
        from meme_machine.lanes.pons import pons_selective_ledger as pons
        from .directional_sleeve import policies
        from .policy_compatibility import known_hash
        if self._book is not None:raise ValueError('native_held_book_already_bound')
        if type(book) in (survivor.PaperBook, Current) and issuer is survivor._HELD_PAPER_ISSUER:
            strategy = book.identity['lane']
            family = 'pump' if strategy in policies('pump') else 'pons'
            if strategy not in policies(family):raise ValueError('native_held_unknown_strategy')
            regime = family+('_survivor' if 'survivor' in strategy else '_current')
            if regime == 'pons_current' or type(book) is Current and regime != 'pump_current':
                raise ValueError('native_held_book_type')
            if not known_hash(regime, book.identity['policy_hash']):
                raise ValueError('native_held_policy_unknown')
            role, db = regime.upper(), book.db
        elif type(book) is pons.SelectivePaper and issuer is pons._HELD_PAPER_ISSUER:
            family, role, db = 'pons', 'PONS_CURRENT_TRIAL', book.store.db
            if (book.experiment != pons.STRATEGY_NAMESPACE
                    or not known_hash('pons_current', genesis['natural_policy_hash'])
                    or not known_hash('pons_current', book.natural_policy_hash)):
                raise ValueError('native_held_pons_genesis_or_policy')
        else:raise ValueError('native_held_original_book_required')
        if self._identity['schema'] != 'normal-'+family+'-owner-subcap-v1':
            raise ValueError('native_held_crossed_owner')
        path = Path(path).absolute()
        root = Path(self._identity['root'])
        if path.resolve() != path or path == root or root not in path.parents:
            raise ValueError('native_held_physical_scope')
        if role == 'PONS_CURRENT_TRIAL':
            number = path.stem.removeprefix('trial-')
            if (path.parent != root/_COHORT or not number.isascii() or not number.isdecimal()
                    or path.name != f'trial-{int(number):03d}.sqlite'):
                raise ValueError('native_held_trial_locator')
        elif path != root/_BOOK_PATHS[role]:raise ValueError('native_held_configured_book_missing')
        key = str(path.relative_to(root))
        if any(other is not self and other._key == key for other in self._population._books):
            raise ValueError('native_held_duplicate_owned_book')
        # Association only, under the configured-owner/no-replacement premise.
        metadata = path.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()):raise ValueError('native_held_book_metadata')
        self._book, self._db = book, db
        self._issuer = issuer
        self._physical = path, metadata.st_dev, metadata.st_ino
        self._key, self._role = key, role
        self._genesis = _encode(genesis, _MAX_BYTES-self._population._used, self._check)
        self._bytes = len(self._genesis)
        self._population._used += self._bytes

    def _bound(self, book):
        self._check()
        if self._book is not book:raise ValueError('native_held_crossed_book')
        db = book.store.db if self._role == 'PONS_CURRENT_TRIAL' else book.db
        if db is not self._db:raise ValueError('native_held_connection_changed')
        # Accessing the original handle's transaction state refuses a closed
        # connection without issuing SQL or inventing retained FD authority.
        db.in_transaction
        path, dev, ino = self._physical
        current = path.lstat()
        if ((current.st_dev, current.st_ino) != (dev, ino) or not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1 or current.st_uid != os.geteuid()):
            raise ValueError('native_held_book_replaced')

    def _replay_start(self, book, issuer):
        if self._book is None or self._initialized or self._failure is not None or self._incomplete is not None:return None
        return self._observe(self._new_replay, book, issuer)

    def _new_replay(self, book, issuer):
        self._bound(book)
        if issuer is not self._issuer:raise ValueError('native_held_original_replay_issuer')
        return [{}, len(self._genesis)]

    def _member(self, members, used, position, version, previous, checksum):
        identity = position['id']
        if (type(identity) is not str or not identity or type(version) is not int or version < 0
                or type(checksum) is not str or len(checksum) != 64):
            raise ValueError('native_held_member_version')
        if self._role == 'PONS_CURRENT_TRIAL' and position.get('version') != version:
            raise ValueError('native_held_pons_version')
        old = members.get(identity)
        remaining = _MAX_BYTES-self._population._used
        body = _encode(position, remaining, self._check)
        result = _Member(identity, version, previous, checksum, body, hashlib.sha256(body.encode()).hexdigest())
        if old and (version < old.version or version == old.version and result != old):
            raise ValueError('native_held_member_fork')
        if old is None and len(members) >= _MAX_MEMBERS:raise ValueError('native_held_member_bound')
        delta = len(body)-(len(old.body) if old else 0)
        self._population._used += delta
        return result, used+delta

    def _replay_row(self, book, token, position, version, previous, checksum):
        if token is not None:self._observe(self._replayed_row, book, token, position, version, previous, checksum)

    def _replayed_row(self, book, token, position, version, previous, checksum):
        self._check()
        if book is not self._book:raise ValueError('native_held_crossed_replay_book')
        if position['id'] not in token[0]:
            if self._population._member_count >= _MAX_MEMBERS:raise ValueError('native_held_member_bound')
            self._population._member_count += 1
        item, token[1] = self._member(token[0], token[1], position, version, previous, checksum)
        token[0][item.identity] = item

    def _replay_done(self, book, token, positions, head):
        if token is not None:self._observe(self._replayed, book, token, positions, head)

    def _replayed(self, book, token, positions, head):
        self._bound(book)
        if self._db.in_transaction:
            # A compatibility/recovery replay inside an outer transaction is
            # not an issued startup snapshot. A later original replay can issue.
            self._population._used -= token[1]-len(self._genesis)
            self._population._member_count -= len(token[0])
            token[0].clear()
            return
        if set(positions) != set(token[0]):
            self._incomplete = 'ARCHIVE_MEMBER_VERSION_UNAVAILABLE'
            self._population._used -= token[1]-len(self._genesis)
            self._population._member_count -= len(token[0])
            token[0].clear()
            return
        # Original replay has just compared this complete rebuilt map with its
        # projection. Each latest captured item came from that same traversal;
        # do not serialize/replay the whole population a second time here.
        self._bound(book)
        self._members, self._bytes, self._head = token[0], token[1], head
        self._initialized, self._incomplete = True, None

    def _stage(self, book, position, version, previous, checksum, issuer):
        self._observe(self._staging, book, position, version, previous, checksum, issuer)

    def _staging(self, book, position, version, previous, checksum, issuer):
        self._bound(book)
        if issuer is not self._issuer:raise ValueError('native_held_original_record_issuer')
        if not self._initialized or not self._db.in_transaction:
            raise ValueError('native_held_replay_or_outer_transaction_missing')
        if self._population._staged_count >= _MAX_STAGE:raise ValueError('native_held_staged_bound')
        # Charge retained committed and ALL staged bodies together, including
        # repeated updates of one member; rollback cannot hide staging memory.
        staged_bytes = sum(len(item.body) for item in self._staged)
        item, _ = self._member({}, self._bytes+staged_bytes, position, version, previous, checksum)
        self._staged.append(item)
        self._population._staged_count += 1

    def _commit(self, book, issuer):self._observe(self._committed_outer, book, issuer)

    def _committed_outer(self, book, issuer):
        self._bound(book)
        if issuer is not self._issuer:raise ValueError('native_held_original_commit_issuer')
        if self._db.in_transaction:raise ValueError('native_held_outer_commit_missing')
        # At most64 touched native records, independent of whole-book size.
        # Startup alone traverses the complete population; marks do not clone
        # or hash that population again just to publish one native COMMIT.
        updates, used, head = {}, self._bytes, self._head
        for item in self._staged:
            old = updates.get(item.identity, self._members.get(item.identity))
            if self._role != 'PONS_CURRENT_TRIAL':
                if item.version != head[0]+1 or item.previous_hash != head[1]:
                    raise ValueError('native_held_native_sequence_gap')
                head = item.version, item.journal_hash
            elif old is not None and (item.version != old.version+1 or item.previous_hash != old.journal_hash):
                raise ValueError('native_held_pons_sequence_gap')
            elif old is None and (item.version != 0 or item.previous_hash is not None):
                raise ValueError('native_held_pons_initial_version')
            used += len(item.body)-(len(old.body) if old else 0)
            updates[item.identity] = item
        old_bytes = self._bytes+sum(len(item.body) for item in self._staged)
        new_count = self._population._member_count+sum(key not in self._members for key in updates)
        if new_count > _MAX_MEMBERS:raise ValueError('native_held_member_bound')
        self._bound(book)
        for key, item in updates.items():self._members[key] = item
        self._bytes, self._head = used, head
        self._population._used += used-old_bytes
        self._population._member_count = new_count
        self._population._staged_count -= len(self._staged)
        self._committed += len(self._staged)
        self._staged = []

    def _rollback(self, book, issuer):
        # Actual native failure remains authoritative. Clearing metadata is
        # allowed only after actual ROLLBACK; uncertain COMMIT keeps its debt.
        try:
            if issuer is not self._issuer:raise ValueError('native_held_original_rollback_issuer')
            if self._book is book and not self._db.in_transaction:
                self._population._used -= sum(len(item.body) for item in self._staged)
                self._population._staged_count -= len(self._staged)
                self._staged = []
        except Exception as exc:
            if self._failure is None:
                exc.__traceback__ = exc.__context__ = exc.__cause__ = None
                self._failure = exc

    def _uncertain(self, book, issuer):
        if self._book is book and issuer is self._issuer and self._failure is None:
            self._failure = ValueError('native_held_commit_outcome_unknown')

    def view(self, *, deadline, cancelled):
        check = _lease_check(deadline, cancelled)
        self._check()
        if self._book is not None:self._bound(self._book)
        members = tuple(sorted(self._members.values(), key=lambda row:row.identity))
        active = self._db is not None and self._db.in_transaction
        status = 'OBSERVED' if self._initialized and self._failure is None and not self._staged and not active else 'INCOMPLETE'
        reason = ('NATIVE_BOOK_CUT' if status == 'OBSERVED' else 'OBSERVATION_FAILED' if self._failure
                  else 'NATIVE_COMMIT_UNRESOLVED' if self._staged else 'NATIVE_TRANSACTION_ACTIVE' if active
                  else self._incomplete or 'ORIGINAL_REPLAY_MISSING')
        result = _NativeView(status, reason, self._role, self._owner_sha, self._key,
                             self._genesis, members, self._committed, len(self._staged), self._failure)
        check();self._check()
        return result


def join_native_population(prefix, captures, *, deadline, cancelled):
    """Join actual captured native versions to one bounded genuine financial cut.

    Even matched links do not close missing configured books/trials/controllers/
    sleeves/legacy/protection. No dictionary/status/hash can issue this value.
    """
    check = _lease_check(deadline, cancelled);check()
    if type(prefix) is not _FinancialPrefix or type(captures) not in (tuple, list):
        raise TypeError('native_held_original_prefix_and_captures_required')
    if len(captures) > _MAX_BOOKS or any(type(item) is not _NativePaperCapture for item in captures):
        raise TypeError('native_held_original_capture_required')
    populations = {id(item._population):item._population for item in captures}
    if sum(item._used for item in populations.values()) > _MAX_BYTES:
        raise ValueError('native_held_join_metadata_bound')
    financial = prefix.advance(deadline=deadline, cancelled=cancelled)
    sequence, journal, _, state = prefix._state_for_join(deadline=deadline, cancelled=cancelled)
    native, books, roles, unresolved, links = {}, set(), set(), [], []
    launch = prefix._capture._identity['launch']
    for capture in captures:
        check()
        view = capture.view(deadline=deadline, cancelled=cancelled)
        if (capture._identity['launch'] != launch
                or capture._identity['root'] != prefix._capture._identity['root']):
            raise ValueError('native_held_crossed_launch')
        if view.book_key in books:raise ValueError('native_held_duplicate_book')
        books.add(view.book_key)
        if view.status == 'OBSERVED':roles.add(view.role)
        if view.status != 'OBSERVED':unresolved.append((view.book_key, view.reason))
        lane = 'pump' if (view.role or '').startswith('PUMP') else 'pons'
        regime = lane+('_survivor' if (view.role or '').endswith('SURVIVOR') else '_current')
        for member in view.members:
            key = lane+':'+member.identity
            if key in native:raise ValueError('native_held_duplicate_lifecycle')
            native[key] = regime, member
    for key, (regime, member) in sorted(native.items()):
        check()
        life = state['native_aliases'].get(key)
        request_id = state.get('runtime_native_requests', {}).get(key)
        request = state['requests'].get(request_id) or {}
        position = state['positions'].get(life) or {}
        actual_regime = position.get('regime') or request.get('value', {}).get('regime')
        if life is None or actual_regime != regime:
            unresolved.append((key, 'NATIVE_GLOBAL_ALIAS_OR_REGIME'));continue
        pending = state.get('runtime_pending', {}).get(key)
        event_id = 'native:'+member.journal_hash
        cursor = state['native_cursors'].get(regime+':'+life)
        event = dict(epoch_id=state['epoch_id'], regime=regime, lifecycle_id=life,
                     event_id=event_id, sequence=cursor, journal_sha256=member.journal_hash)
        if pending is not None:
            if (pending['event_key'] != event_id or pending['journal_hash'] != member.journal_hash
                    or pending['lifecycle_id'] != life or pending['request_id'] != request_id
                    and pending['request_id'] != state.get('runtime_native_requests', {}).get(key+':scale')):
                unresolved.append((key, 'NATIVE_VERSION_BEHIND_PENDING'));continue
            phase = 'NATIVE_COMMITTED_GLOBAL_PENDING'
        elif state['native_deliveries'].get(regime+':'+life+':'+event_id) == digest(event):
            phase = 'DELIVERY_RECORDED_AT_FINANCIAL_CUT'
        else:
            unresolved.append((key, 'EXACT_NATIVE_DELIVERY_UNESTABLISHED'));continue
        links.append((key, life, regime, request_id, member.version, member.journal_hash,
                      member.body_sha256, phase))
    # Every alias remains visible, including funded unmaterialized intents and
    # terminal retirement debt. This leaf cannot silently drop an absent book.
    for key in sorted(state['native_aliases']):
        check()
        if key not in native:unresolved.append((key, 'FINANCIAL_NATIVE_MEMBER_UNOBSERVED'))
    if financial.status != 'COVERED_CUT':unresolved.append(('SHARED', financial.reason))
    missing = _MISSING+tuple(sorted(set(_BOOK_PATHS)-roles))
    result = _NativeJoin('INCOMPLETE', 'MATCHED_AT_CUT' if not unresolved else 'UNESTABLISHED',
        sequence, journal, tuple(links), tuple(unresolved), financial.counts,
        financial.pending, missing)
    prefix._bound()
    for capture in captures:capture._check()
    check()
    return result
