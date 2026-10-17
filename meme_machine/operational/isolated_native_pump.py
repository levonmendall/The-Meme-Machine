"""Disposable public Pump economics projection, explicitly partial native parity.

The production protocol decoders, CandidateHistory transactions, ordered reads,
and Pump startup restoration are reused. Public RPC provenance never becomes an
Alchemy source, canonical completeness proof, historical callback, or funding
authority. No provider transport, native book, sleeve, or supervisor starts here.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.postgrad import PUMPSWAP_PROGRAM
from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
from meme_machine.runtime.candidate_history import CandidateHistory

SOURCE = 'isolated_public_rpc_finalized_block'
MAX_BLOCK_BYTES = 16 * 1024 * 1024
MAX_TRANSACTIONS = 8192
MAX_EVENTS = 32768
MAX_DATABASE_BYTES = 48 * 1024 * 1024
_RESTORE_LOCK = threading.Lock()
OMISSIONS = (
    'production_native_stream_acquisition_and_backpressure',
    'authenticated_alchemy_canonical_source_and_FULL_ACK_delivery',
    'complete_program_interval_proofs_and_historical_callback_recovery',
    'canonical_reference_and_retired_cold_archive_restoration',
    'Current_and_Survivor_economic_qualification_and_lifecycle_workers',
    'held_position_quotes_USD_valuation_and_financial_protection',
    'authoritative_full_market_throughput_or_one_hour_acceptance',
)


def _require(condition, code):
    if not condition:
        raise ValueError('isolated_pump_' + code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _private_root(root):
    root = Path(root).absolute()
    _require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
             'private_root_required')
    info = root.stat()
    _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
             'private_root_permissions')
    # Native library helpers consult process configuration. Do not let any
    # inherited production location or selected authority reach these calls.
    _require(not any(name.startswith('MM_') for name in os.environ),
             'production_environment_refused')
    return root


class PumpNativeProjection:
    """One owner of fresh, unbound CandidateHistory in a private scratch root."""
    def __init__(self, root):
        self.root = _private_root(root)
        self.path = self.root / 'pump-native-observations.sqlite'
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.history = None
        self.closed = False
        self.restore_measurements = []
        self._open()
        self.history.db.executescript('''
            CREATE TABLE isolated_public_blocks(
                slot INTEGER PRIMARY KEY, blockhash TEXT NOT NULL,
                body_sha256 TEXT NOT NULL, block_time INTEGER NOT NULL,
                first_observed REAL NOT NULL, offered_transactions INTEGER NOT NULL,
                relevant_transactions INTEGER NOT NULL, decoded_events INTEGER NOT NULL,
                source TEXT NOT NULL);
        ''')

    def _open(self):
        _private_root(self.root)
        _require(not self.path.is_symlink() and self.path.is_file(), 'owned_database_required')
        self.history = CandidateHistory(self.path, worker_capacity=1, write_wait_seconds=0)
        self.closed = False

    def _bound(self):
        size = sum(p.stat().st_size for p in self.root.iterdir()
                   if p.is_file() and not p.is_symlink())
        _require(size <= MAX_DATABASE_BYTES, 'database_byte_bound')

    @staticmethod
    def _transactions(slot, block, observed_at):
        _require(type(slot) is int and 0 <= slot < 2**63, 'slot_shape')
        _require(type(block) is dict and type(block.get('blockTime')) is int
                 and 0 < block['blockTime'] <= observed_at, 'block_time')
        _require(type(block.get('blockhash')) is str and bool(block['blockhash']),
                 'block_identity')
        _require(len(_canonical(block).encode()) <= MAX_BLOCK_BYTES, 'block_byte_bound')
        transactions = block.get('transactions')
        _require(type(transactions) is list and len(transactions) <= MAX_TRANSACTIONS,
                 'transaction_bound')
        relevant = []
        signatures = set()
        for index, tx in enumerate(transactions):
            try:
                message = tx['transaction']['message']
                keys = message['accountKeys']
                meta = tx['meta']
                signature = tx['transaction']['signatures'][0]
                _require(type(keys) is list and type(meta) is dict and 'err' in meta,
                         'transaction_shape')
                _require(type(signature) is str and bool(signature) and signature not in signatures,
                         'transaction_identity')
                signatures.add(signature)
                keys = [value if type(value) is str else value['pubkey'] for value in keys]
                loaded = meta.get('loadedAddresses') or {}
                keys += list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])
                _require(all(type(key) is str and bool(key) for key in keys),
                         'account_key_shape')
                _require('slot' not in tx or type(tx['slot']) is int and tx['slot'] == slot,
                         'transaction_slot')
                _require('blockTime' not in tx or tx['blockTime'] == block['blockTime'],
                         'transaction_time')
                # Public getBlock's full transaction array supplies native order.
                # A contradictory caller-supplied rank cannot overwrite it.
                _require('transactionIndex' not in tx or
                         type(tx['transactionIndex']) is int and tx['transactionIndex'] == index,
                         'transaction_order')
            except (KeyError, IndexError, TypeError):
                raise ValueError('isolated_pump_transaction_shape') from None
            families = []
            if pump.PROGRAM in keys:
                families.append('pump')
            if PUMPSWAP_PROGRAM in keys:
                families.append('pumpswap')
            if not families:
                continue
            if meta['err'] is None:
                logs = meta.get('logMessages')
                _require(type(logs) is list and all(type(line) is str for line in logs)
                         and not any('truncat' in line.lower() for line in logs),
                         'complete_logs_required')
            relevant.append((index, signature, families,
                             dict(tx, slot=slot, blockTime=block['blockTime'])))
        return transactions, relevant

    def consume(self, slot, block, *, observed_at=None):
        """Decode one full getBlock response without asserting interval coverage.

        The caller owns fixed-endpoint finalized-head selection and exact raw
        response capture. The component has no RPC adapter and cannot retry.
        A malformed block rolls back its entire candidate/public receipt batch.
        """
        _require(not self.closed, 'closed')
        _private_root(self.root)
        observed_at = time.time() if observed_at is None else observed_at
        _require(type(observed_at) in (int, float) and math.isfinite(observed_at)
                 and observed_at > 0, 'observation_time')
        begun, cpu = time.monotonic(), time.thread_time()
        transactions, relevant = self._transactions(slot, block, observed_at)
        block_sha = _digest(block)
        prior = self.history.db.execute(
            'SELECT body_sha256,decoded_events FROM isolated_public_blocks WHERE slot=?',
            (slot,)).fetchone()
        if prior:
            _require(prior[0] == block_sha, 'block_replay_conflict')
            return dict(slot=slot, duplicate=True, decoded_events=prior[1],
                        wall_seconds=time.monotonic()-begun, cpu_seconds=time.thread_time()-cpu)
        decoded = []
        counts = dict(pump=0, pumpswap=0)
        for index, signature, families, tx in relevant:
            for family in families:
                events = (pump_events if family == 'pump' else pumpswap_trade_events)(tx)
                for event in sorted(events, key=lambda row: row['index']):
                    _require(type(event.get('market_time')) is int
                             and 0 < event['market_time'] <= observed_at, 'economic_time')
                    decoded.append((family, index, signature, event))
                    counts[family] += 1
                    _require(len(decoded) <= MAX_EVENTS, 'event_bound')
        with self.history.transaction():
            for family, index, signature, event in decoded:
                candidate = event['mint'] if family == 'pump' else event['pool']
                kind = 'pump_' + event['event_type'] if family == 'pump' else 'pumpswap_trade'
                self.history.observe('pump', candidate,
                    surface='pump.fun' if family == 'pump' else 'pumpswap',
                    observed_at=event['market_time'],
                    metadata=dict(source=SOURCE, canonical_completeness=False))
                self.history.append_event('pump', candidate,
                    identity='isolated-public:'+family+':'+str(slot)+':'+signature+':'+str(event['index']),
                    slot=slot, transaction_index=index, event_index=event['index'],
                    market_time=event['market_time'], kind=kind, payload=event)
            self.history.db.execute('INSERT INTO isolated_public_blocks VALUES(?,?,?,?,?,?,?,?,?)',
                (slot, block['blockhash'], block_sha, block['blockTime'], observed_at,
                 len(transactions), len(relevant), len(decoded), SOURCE))
        self._bound()
        return dict(slot=slot, duplicate=False, offered_transactions=len(transactions),
                    relevant_transactions=len(relevant), decoded_events=len(decoded),
                    events_by_family=counts, wall_seconds=time.monotonic()-begun,
                    cpu_seconds=time.thread_time()-cpu)

    def _logical_digest(self):
        return _digest(dict(
            candidates=list(self.history.db.execute(
                'SELECT * FROM candidates ORDER BY lane,candidate')),
            events=list(self.history.db.execute(
                'SELECT * FROM events ORDER BY lane,candidate,identity'))))

    def reopen(self, *, now=None):
        """Close/reopen and execute the real Pump observation restoration reader.

        No native lifecycle starts. LocalPumpHistory objects only bind the
        independently owned, unavailable plane; no quote or completeness can be
        obtained. The registry below records restored interests locally only.
        """
        _require(not self.closed, 'closed')
        before = self._logical_digest()
        self.history.close()
        self.history = None
        self.closed = True
        begun, cpu = time.monotonic(), time.thread_time()
        self._open()
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
        confirmations = ConfirmationBook.from_files()
        created, postgrad, pools = {}, {}, set()
        registry = SimpleNamespace(add_address=pools.add)
        # The existing restore function owns a module-local history binding.
        # This isolated process never starts the runner or any financial owner.
        with _RESTORE_LOCK:
            previous = getattr(runner, 'CANDIDATE_HISTORY', None)
            runner.CANDIDATE_HISTORY = self.history
            try:
                restored = runner._restore_observed_pump_candidates(
                    created, postgrad, registry, SimpleNamespace(), confirmations,
                    int(time.time() if now is None else now))
            finally:
                runner.CANDIDATE_HISTORY = previous
        # Validate every persisted event through the production ordered/hash
        # checking reader, including Swap-only candidates excluded by restore.
        read_events = 0
        for candidate in self.history.candidates(lane='pump'):
            read_events += len(self.history.events('pump', candidate['candidate']))
        after = self._logical_digest()
        _require(before == after, 'restoration_mutated_economics')
        result = dict(restored_created_candidates=restored, restored_postgrad_candidates=len(postgrad),
                      restored_pool_interests=len(pools), authenticated_history_events=read_events,
                      logical_sha256=after, economic_history_unchanged=True,
                      wall_seconds=time.monotonic()-begun, cpu_seconds=time.thread_time()-cpu,
                      cold_archive_parity=False, canonical_source_parity=False)
        self.restore_measurements.append(result)
        self._bound()
        return result

    def snapshot(self):
        _require(not self.closed, 'closed')
        db = self.history.db
        counts = {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                  for table in ('candidates', 'events', 'funding', 'decisions',
                                'canonical_event_refs', 'history_coverage')}
        _require(all(counts[key] == 0 for key in
                     ('funding','decisions','canonical_event_refs','history_coverage')),
                 'unexpected_authority_or_proof')
        _require(not any((self.root / name).exists() for name in
                     ('portfolio.sqlite', 'shared-capital.sqlite', 'native-genesis.json')),
                 'financial_state_forbidden')
        blocks = list(db.execute('SELECT slot,body_sha256 FROM isolated_public_blocks ORDER BY slot'))
        self._bound()
        return dict(status='PARTIAL_NATIVE_PROJECTION', source=SOURCE,
                    workload='complete_offered_public_blocks_native_economic_decoders_and_CandidateHistory',
                    complete_market_coverage=False, canonical_completeness=False,
                    funding_authority=False, financial_database_access=False,
                    native_protocol_decoders=True, native_candidate_persistence=True,
                    sqlite_synchronous=db.execute('PRAGMA synchronous').fetchone()[0],
                    sqlite_journal_mode=db.execute('PRAGMA journal_mode').fetchone()[0],
                    blocks=len(blocks), captured_block_digest=_digest(blocks),
                    logical_sha256=self._logical_digest(), counts=counts,
                    restoration=list(self.restore_measurements), omissions=list(OMISSIONS))

    def close(self):
        if self.history is not None:
            self.history.close()
            self.history = None
        self.closed = True
