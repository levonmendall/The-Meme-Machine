"""Isolated PUBLIC market sampling only. Never a PAPER or canonical-history worker.

This intentionally does not import Supervisor, EvidenceWriter, positions, capital,
wallets, native replay or production provider state. It does NOT benchmark full
Pump/Pons production throughput or resolve historical source acknowledgements.
Only public chain heads and bounded, point-in-time raw program/factory references
are written to a fresh disposable SQLite database owned by the AWS runner.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

SOLANA = 'https://api.mainnet-beta.solana.com'
ROBINHOOD = 'https://rpc.mainnet.chain.robinhood.com'
PUMP_PROGRAM = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
PUMPSWAP_PROGRAM = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
PONS_FACTORY = '0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e'
PONS_CHAIN_ID = 4663
MAX_DURATION = 180
MIN_INTERVAL = 6
MAX_TICKS = 30
MAX_RPC_REQUESTS = 150
MAX_RESPONSE = 512 * 1024
MAX_SIGNATURES = 32
MAX_LOGS = 128
SCHEMA = 'isolated-public-market-observer-v1'
METHODS = {
    SOLANA: frozenset(('getSlot', 'getSignaturesForAddress')),
    ROBINHOOD: frozenset(('eth_chainId', 'eth_blockNumber', 'eth_getLogs')),
}
FORBIDDEN_ENV_PREFIXES = ('MM_', 'AWS_SECRET_', 'ALCHEMY_')


class ObservationUnavailable(RuntimeError):
    """Typed, sanitized failure: never leak endpoint bodies or credentials."""


def require(condition, code):
    if not condition:
        raise ObservationUnavailable(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ObservationUnavailable('redirect_refused')


class RPC:
    """Fixed-keyless mainnet JSON-RPC. No retries, dynamic endpoint or writes."""
    def __init__(self, *, transport=None, sleeper=time.sleep, clock=time.monotonic,
                 max_requests=MAX_RPC_REQUESTS):
        require(type(max_requests) is int and 1 <= max_requests <= MAX_RPC_REQUESTS,
                'request_ceiling_invalid')
        self.transport = transport or self._transport
        self.sleeper, self.clock = sleeper, clock
        self.max_requests = max_requests
        self.attempts = 0
        self.rate_limited = 0
        self.last_request = None
        self.rejection = None

    @staticmethod
    def _transport(url, body):
        require(url in METHODS, 'endpoint_not_approved')
        request = Request(url, data=body,
            headers={'Content-Type': 'application/json', 'User-Agent': 'MM-Isolated-Public-Observer/1'},
            method='POST')
        with build_opener(NoRedirect()).open(request, timeout=6) as response:
            result = response.read(MAX_RESPONSE + 1)
        require(len(result) <= MAX_RESPONSE, 'rpc_body_limit')
        return result

    def call(self, endpoint, method, params):
        require(endpoint in METHODS and method in METHODS[endpoint],
                'method_or_endpoint_not_approved')
        require(type(params) is list, 'rpc_params_shape')
        require(self.attempts < self.max_requests, 'rpc_request_ceiling')
        now = self.clock()
        if self.last_request is not None and now - self.last_request < 1.0:
            self.sleeper(1.0 - (now - self.last_request))
        self.last_request = self.clock()
        self.attempts += 1
        packet = canonical({'jsonrpc': '2.0', 'id': self.attempts,
                            'method': method, 'params': params}).encode()
        require(len(packet) < 1024, 'request_body_limit')
        try:
            raw = self.transport(endpoint, packet)
            require(type(raw) is bytes and len(raw) <= MAX_RESPONSE,
                    'rpc_response_bound')
            row = json.loads(raw)
            require(type(row) is dict and row.get('jsonrpc') == '2.0'
                    and row.get('id') == self.attempts, 'rpc_response_identity')
            if 'error' in row:
                error = row['error']
                code = error.get('code') if type(error) is dict else None
                # Retain only an approved method and a bounded JSON-RPC code.
                # Provider messages/data may contain endpoints or credentials.
                self.rejection = dict(method=method, code=code
                    if type(code) is int and -(2**31) <= code < 2**31 else None)
                raise ObservationUnavailable('rpc_rejected')
            require('result' in row, 'rpc_rejected')
            return row['result']
        except HTTPError as e:
            if e.code == 429:
                self.rate_limited += 1
                raise ObservationUnavailable('provider_429') from None
            raise ObservationUnavailable('provider_http_error') from None
        except (URLError, TimeoutError, OSError):
            raise ObservationUnavailable('provider_transport_error') from None
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            raise ObservationUnavailable('rpc_decode_error') from None


def _integer(value, name):
    require(type(value) is int and 0 <= value < 2**63, name)
    return value


def _solana_program(value):
    require(type(value) is str and 32 <= len(value) <= 44
            and re.fullmatch('[1-9A-HJ-NP-Za-km-z]+', value) is not None,
            'solana_program_invalid')
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = 0
    for character in value:
        number = number * 58 + alphabet.index(character)
    length = len(value) - len(value.lstrip('1')) + (number.bit_length()+7)//8
    require(length == 32, 'solana_program_invalid')
    return value


def _hex(value, name, *, bytes_count=None):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]+', value) is not None,
            name)
    if bytes_count is not None:
        require(len(value) == 2 + 2 * bytes_count, name)
    return value.lower()


class DisposableJournal:
    """Bounded SQLite writer in a new directory under RUNNER_TEMP ONLY."""
    def __init__(self, root):
        self.root = Path(root)
        require(self.root.is_dir() and not self.root.is_symlink(),
                'scratch_directory_required')
        info = self.root.stat()
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'scratch_permissions')
        self.path = self.root / 'sample.sqlite3'
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE observations(
                lane TEXT NOT NULL, identity TEXT NOT NULL, head INTEGER NOT NULL,
                body_digest TEXT NOT NULL, observed REAL NOT NULL,
                PRIMARY KEY(lane, identity));
            CREATE TABLE measurements(
                tick INTEGER NOT NULL, lane TEXT NOT NULL, head INTEGER,
                offered INTEGER NOT NULL, written INTEGER NOT NULL,
                duplicates INTEGER NOT NULL, possible_gap INTEGER NOT NULL,
                elapsed REAL NOT NULL, PRIMARY KEY(tick,lane));
        ''')
        self.offered = 0
        self.written = 0
        self.duplicates = 0
        self.samples = 0

    def record(self, tick, lane, head, items, possible_gap, *, clock=time.monotonic):
        _integer(tick, 'tick_number')
        require(lane in ('solana_pump', 'solana_pumpswap', 'robinhood_pons'),
                'lane_invalid')
        _integer(head, 'head_invalid')
        require(type(items) is list and len(items) <= MAX_LOGS, 'event_bound')
        require(type(possible_gap) is bool, 'gap_flag_invalid')
        start = clock()
        self.db.execute('BEGIN IMMEDIATE')
        inserted = 0
        try:
            for identity, at, payload in items:
                require(type(identity) is str and re.fullmatch('[0-9a-f]{64}', identity),
                        'identity_digest_invalid')
                _integer(at, 'event_head_invalid')
                require(at <= head, 'future_event_refused')
                data = digest(payload)
                before = self.db.total_changes
                self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)',
                    (lane, identity, at, data, time.time()))
                inserted += self.db.total_changes - before
                require(self.db.total_changes <= 5000, 'journal_row_limit')
            self.db.execute('INSERT INTO measurements VALUES(?,?,?,?,?,?,?,?)',
                (tick, lane, head, len(items), inserted, len(items)-inserted,
                 int(possible_gap), clock()-start))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self.offered += len(items)
        self.written += inserted
        self.duplicates += len(items)-inserted
        self.samples += 1
        require(self.path.stat().st_size < 8*1024*1024, 'journal_disk_bound')
        return inserted

    def summary(self):
        rows=self.db.execute('SELECT lane,count(*),sum(possible_gap),'
            'sum(offered),sum(written),sum(duplicates) FROM measurements GROUP BY lane').fetchall()
        return {lane:dict(samples=n,possible_gaps=g,offered=o,written=w,duplicates=d)
                for lane,n,g,o,w,d in rows}

    def close(self):
        self.db.close()


class Observer:
    """Best-effort *sampled* public references, not canonical coverage proof."""
    def __init__(self, rpc, journal, *, clock=time.monotonic):
        # Validate our fixed public addresses before contacting either provider.
        _solana_program(PUMP_PROGRAM)
        _solana_program(PUMPSWAP_PROGRAM)
        self.rpc,self.journal,self.clock=rpc,journal,clock
        self.last_signature = {'solana_pump':None, 'solana_pumpswap':None}
        self.last_pons_head = None
        self.last_solana_head = None
        self.pons_chain_verified = False
        self.error = None
        self.completed = 0
        self.heads = {'solana': [], 'robinhood': []}
        # Cross-backend/public-RPC differences can return signatures newer
        # than a just-read finalized head. Record these as explicitly excluded
        # references, not as finalized evidence and not as a fatal error.
        self.unverified_future = {'solana_pump':0, 'solana_pumpswap':0}
        self.regressed_finalized_heads = 0

    def solana(self, tick):
        head=_integer(self.rpc.call(SOLANA,'getSlot',[{'commitment':'finalized'}]),
                      'solana_head')
        head_regressed=(self.last_solana_head is not None
                        and head < self.last_solana_head)
        if head_regressed:
            self.regressed_finalized_heads += 1
        self.heads['solana'].append(head)
        for lane,program in (('solana_pump',PUMP_PROGRAM),
                             ('solana_pumpswap',PUMPSWAP_PROGRAM)):
            rows=self.rpc.call(SOLANA,'getSignaturesForAddress',[program,
                {'limit': MAX_SIGNATURES, 'commitment': 'finalized'}])
            require(type(rows) is list and len(rows) <= MAX_SIGNATURES,
                    'solana_reference_shape')
            result=[]
            eligible_signatures=[]
            future=0
            for row in rows:
                require(type(row) is dict, 'solana_reference_shape')
                sig=row.get('signature')
                slot=_integer(row.get('slot'), 'solana_signature_slot')
                require(type(sig) is str and re.fullmatch('[1-9A-HJ-NP-Za-km-z]{50,100}',sig),
                        'solana_signature_identity')
                if slot > head:
                    # Distinct finalized RPC frontiers may be observed from
                    # different public backends. Do not persist, acknowledge,
                    # or claim this signature is verified under our head.
                    future += 1
                    continue
                key=digest([lane,sig,slot])
                result.append((key,slot,dict(slot=slot,signature_sha256=digest(sig))))
                eligible_signatures.append(sig)
            self.unverified_future[lane] += future
            # An empty first page or a page without the previous newest
            # reference cannot prove every intermediate market event. Only
            # head-bounded verified references can update our overlap cursor.
            latest=eligible_signatures[0] if eligible_signatures else None
            overlap=self.last_signature[lane] in eligible_signatures
            missing=bool(self.last_signature[lane] and not overlap)
            self.journal.record(tick,lane,head,result,
                bool(future or head_regressed or missing or len(rows)==MAX_SIGNATURES))
            if latest is not None:
                self.last_signature[lane]=latest
        self.last_solana_head=head

    def pons(self, tick):
        if not self.pons_chain_verified:
            chain=self.rpc.call(ROBINHOOD,'eth_chainId',[])
            require(type(chain) is str and int(_hex(chain,'pons_chain_id'),16)==PONS_CHAIN_ID,
                    'pons_chain_mismatch')
            self.pons_chain_verified=True
        raw=self.rpc.call(ROBINHOOD,'eth_blockNumber',[])
        head=int(_hex(raw,'pons_block_number'),16)
        _integer(head,'pons_head_invalid')
        self.heads['robinhood'].append(head)
        if self.last_pons_head is not None and head < self.last_pons_head:
            raise ObservationUnavailable('pons_head_regressed')
        low=head if self.last_pons_head is None else min(head,self.last_pons_head+1)
        gap=self.last_pons_head is not None and head-self.last_pons_head > 3
        low=max(low,head-2)  # Never widen a public-RPC query to cover backlog.
        logs=self.rpc.call(ROBINHOOD,'eth_getLogs',[dict(
            address=PONS_FACTORY,fromBlock=hex(low),toBlock=hex(head))])
        require(type(logs) is list and len(logs)<=MAX_LOGS,'pons_log_bound')
        records=[]
        for value in logs:
            require(type(value) is dict and value.get('removed') is not True,
                    'pons_log_removed_or_bad')
            require(value.get('address','').lower()==PONS_FACTORY,
                    'pons_factory_mismatch')
            block=int(_hex(value.get('blockNumber'),'pons_log_block'),16)
            require(low<=block<=head,'pons_log_outside_window')
            signature=_hex(value.get('transactionHash'),'pons_tx_hash',bytes_count=32)
            ordinal=int(_hex(value.get('logIndex'),'pons_log_index'),16)
            require(0<=ordinal<=MAX_LOGS*1024,'pons_log_index_bound')
            identity=digest([signature,ordinal,block])
            records.append((identity,block,dict(block=block,
                transaction_sha256=digest(signature),log_index=ordinal)))
        self.journal.record(tick,'robinhood_pons',head,records,bool(gap))
        self.last_pons_head=head

    def run(self, *, duration=120, interval=MIN_INTERVAL, sleeper=time.sleep,
            clock=time.monotonic):
        require(type(duration) is int and 12 <= duration <= MAX_DURATION,
                'duration_bound')
        require(type(interval) is int and MIN_INTERVAL <= interval <= 30,
                'interval_bound')
        require((duration+interval-1)//interval<=MAX_TICKS,'tick_count_bound')
        start=clock()
        for tick in range((duration+interval-1)//interval):
            until=start+tick*interval
            if clock() < until: sleeper(until-clock())
            if clock()-start>=duration: break
            try:
                self.solana(tick)
                self.pons(tick)
            except ObservationUnavailable as error:
                self.error=str(error)
                break
            self.completed += 1
        elapsed=clock()-start
        return dict(schema=SCHEMA,scope='ISOLATED_PUBLIC_RPC_SAMPLED_REFERENCE_ONLY',
            result='SAMPLED' if self.completed>0 and self.error is None else 'PARTIAL_OR_BLOCKED',
            completed_ticks=self.completed,requested_duration_seconds=duration,
            elapsed_seconds=round(elapsed,3),provider_requests=self.rpc.attempts,
            provider_429=self.rpc.rate_limited,error_code=self.error,
            provider_rpc_rejection=getattr(self.rpc,'rejection',None),
            unverified_future_signatures_excluded=dict(self.unverified_future),
            regressed_finalized_heads=self.regressed_finalized_heads,
            lane_measurements=self.journal.summary(),
            head_start_end={k:[v[0],v[-1]] if v else None for k,v in self.heads.items()},
            financial_authority=False,paper_started=False,
            production_state_written=False,original_history_recovered=False,
            full_market_speed_proven=False,complete_economic_coverage_proven=False)


def safe_runtime(environ=None):
    env=os.environ if environ is None else environ
    require(os.geteuid()!=0, 'root_worker_forbidden')
    try:
        require(pwd.getpwnam('meme-machine').pw_uid!=os.geteuid(),
                'production_service_user_forbidden')
    except KeyError:
        pass
    require(not any(key.startswith(FORBIDDEN_ENV_PREFIXES) for key in env),
            'production_environment_inherited')
    require(env.get('GITHUB_RUN_ID','').isdigit(), 'run_identity_required')
    require('RUNNER_TEMP' in env,'runner_temp_required')
    require(not os.access('/srv/meme-machine/state/shared-1000',os.W_OK),
            'production_state_write_access_forbidden')
    require(not os.access('/etc/meme-machine/paper.aws.env',os.R_OK),
            'provider_secrets_access_forbidden')


def main():
    safe_runtime()
    base=Path(os.environ['RUNNER_TEMP'])
    require(base.is_dir() and not base.is_symlink(), 'runner_temp_invalid')
    with os.scandir(base) as entries:
        pass  # No production folder traversal, only fixed scratch parent.
    os.umask(0o077)
    target=Path(tempfile.mkdtemp(prefix='mm-isolated-public-'+os.environ['GITHUB_RUN_ID']+'-',
                                dir=base))
    journal=DisposableJournal(target)
    try:
        observer=Observer(RPC(),journal)
        result=observer.run()
        with (target/'summary.json').open('x') as f:
            f.write(canonical(result)+'\n')
        print(canonical(dict(result,archive='PRIVATE_RUNNER_TEMP_ARTIFACT')))
        return 0 if result['result']=='SAMPLED' else 2
    finally:
        journal.close()


if __name__=='__main__':
    raise SystemExit(main())
