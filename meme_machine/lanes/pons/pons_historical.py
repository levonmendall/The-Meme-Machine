"""Offline-tested historical preparation in the existing Pons history authority.

This is a single-worker path selected explicitly for prepared history databases,
not a second market-data service. The caller supplies the existing governed RPC
session factory. No endpoint, money book, candidate deadline or provider rate is
created here. Numeric log ranges are reusable only through their canonical range
checkpoints; the generic immutable RPC cache deliberately does not cache them.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
import json
import time

from meme_machine.runtime.journal import canonical, digest
from meme_machine.runtime.robinhood.provider_authority import require_canonical
from . import BoundaryError, CHAIN_ID
from .identity import load, authenticate
from .abi import decode_event, calldata
from .pons import raw_event, authenticate_curve
from .pons_natural_paper import _event_topic, _factory_record_at, _graduation_transition
from .pons_natural_observation import ZERO
from .pons_postgrad_survivor import POLICY, POLICY_HASH
from .pons_selective_v4 import collect_v4_activity
from .protocols import PoolKey
from .provider_admission import decision_work

SCHEMA = 'pons-historical-preparation-v1'
PLAN = 'pons_historical_plan'
FACTORY = load('pons_v2_factory')['address'].lower()
LAUNCH = _event_topic('pons_v2_factory', 'TokenLaunched')
GRADUATION = _event_topic('pons_v2_factory', 'PoolGraduated')
MANAGER = load('uniswap_v4_manager')['address'].lower()
SWAP = _event_topic('uniswap_v4_manager', 'Swap')
ACTIVITY = [SWAP] + [_event_topic('uniswap_v4_manager', n) for n in
                       ('ModifyLiquidity', 'Donate', 'ProtocolFeeUpdated')]
SCOPE = 'pons_historical_preparation'
SPLIT_ERRORS = {'provider_log_block_range_limit', 'provider_response_capacity',
                'provider_rpc_-32005', 'historical_response_saturation'}


def number(header):
    try:
        n = int(header['number'], 16)
        if n < 0 or not header.get('hash') or not header.get('parentHash'):
            raise ValueError()
        int(header['timestamp'], 16)
        return n
    except (KeyError, TypeError, ValueError):
        raise BoundaryError('historical_header_identity') from None


def compact_header(header):
    number(header)
    return {k:header[k] for k in ('number','hash','parentHash','timestamp')}


def event_id(event):
    """Native identity, independent of provider JSON ordering or overlap."""
    try:
        return ':'.join((event['blockHash'], event['transactionHash'],
                         str(int(event['logIndex'], 16))))
    except (KeyError, TypeError, ValueError):
        raise BoundaryError('historical_event_identity') from None


def order(event):
    return tuple(int(event[k], 16) for k in ('blockNumber', 'transactionIndex', 'logIndex'))


class _NativeReads:
    """Account native helper reads without changing their provider authority."""
    def __init__(self, preparation):
        self.preparation = preparation

    def call(self, method, params, *, scope):
        return self.preparation.calls([(method, params)])[0]

    def receipt(self, tx, block_hash, *, scope):
        p = self.preparation
        rpc = p.rpc()
        before = rpc.telemetry()
        completed = False
        try:
            with p.receipt_pins(rpc,{tx:block_hash}):
                value = rpc.receipt(tx, block_hash, scope=SCOPE)
            completed = True
            return value
        finally:
            p._usage(before, rpc.telemetry(), [('eth_getTransactionReceipt', [tx])],completed=completed)


class Preparation:
    def __init__(self, history, provider, *, range_blocks=10, support=None,
                 response_log_limit=1024, clock=time.time):
        if history.get_meta('policy') != POLICY_HASH:
            raise BoundaryError('historical_policy_identity')
        if not 1 <= range_blocks <= 10000 or not 2 <= response_log_limit <= 1024:
            raise BoundaryError('historical_work_bound')
        self.history = history
        self.provider = provider
        self.range_blocks = range_blocks
        self.support = support
        self.log_limit = response_log_limit
        self.clock = clock
        self.fingerprint = None
        self.restored = False
        history.db.executescript('''
          CREATE TABLE IF NOT EXISTS pons_historical_ranges(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, first INTEGER NOT NULL,
            last INTEGER NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL,
            valid INTEGER NOT NULL DEFAULT 1, through_at INTEGER NOT NULL);
          CREATE INDEX IF NOT EXISTS pons_historical_frontiers
            ON pons_historical_ranges(kind,valid,last);
          CREATE INDEX IF NOT EXISTS pons_historical_expiration ON pons_historical_ranges(through_at,kind,first);
          CREATE TABLE IF NOT EXISTS pons_historical_events(
            id TEXT NOT NULL, kind TEXT NOT NULL, block INTEGER NOT NULL,
            body TEXT NOT NULL, hash TEXT NOT NULL, valid INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(kind,id));
          CREATE INDEX IF NOT EXISTS pons_historical_population
            ON pons_historical_events(kind,valid,block);
          CREATE INDEX IF NOT EXISTS pons_historical_token_events
            ON pons_historical_events(kind,valid,json_extract(body,'$.topics[1]'),json_extract(body,'$.topics[0]'));
          CREATE TABLE IF NOT EXISTS pons_historical_gaps(
            kind TEXT NOT NULL, first INTEGER NOT NULL, last INTEGER NOT NULL,
            body TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(kind,first,last));
          CREATE TABLE IF NOT EXISTS pons_historical_members(
            candidate TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(candidate,kind));
          CREATE INDEX IF NOT EXISTS pons_historical_member_kind ON pons_historical_members(kind);
        ''')

    def rpc(self, needed=1):
        rpc = self.provider()
        fingerprint = require_canonical(rpc)
        if self.fingerprint is not None and fingerprint != self.fingerprint:
            raise BoundaryError('historical_provider_identity_changed')
        self.fingerprint = fingerprint
        if self.range_blocks > 10:
            s = self.support or {}
            if (s.get('schema') != 'pons-log-range-comparison-v1'
                    or s.get('provider_fingerprint') != fingerprint
                    or s.get('chain_id') != CHAIN_ID or s.get('equal') is not True
                    or s.get('range_blocks', 0) < self.range_blocks
                    or s.get('filter') != self.population_filter()
                    or not s.get('canonical_end_hash') or not s.get('baseline_digest')):
                raise BoundaryError('historical_range_capability_unverified')
        if getattr(rpc, 'used', 0) + needed > getattr(rpc, 'limit', 200):
            raise BoundaryError('historical_session_rotation_required')
        return rpc

    @staticmethod
    def population_filter():
        # Factory census is independent of Current and retained Survivor rows.
        return dict(address=FACTORY, topics=[[LAUNCH, GRADUATION]])

    @contextmanager
    def receipt_pins(self,rpc,pins):
        previous=getattr(rpc,'evidence_receipts',None)
        rpc.evidence_receipts=dict(previous or {},**pins)
        try:yield
        finally:
            if previous is None:del rpc.evidence_receipts
            else:rpc.evidence_receipts=previous

    def calls(self, calls, *, receipt_pins=None):
        rpc = self.rpc(len(calls))
        before = rpc.telemetry()
        completed = False
        try:
            with self.receipt_pins(rpc,receipt_pins or {}):
                values = rpc.batch(calls, scope=SCOPE)
            if not isinstance(values, list) or len(values) != len(calls):
                raise BoundaryError('historical_batch_incomplete')
            completed = True
            return values
        finally:
            self._usage(before, rpc.telemetry(), calls,completed=completed)

    def _usage(self, before, after, calls, *, completed):
        # Physical attempts come from transport telemetry, never batch length.
        old = self.history.get_meta('pons_historical_usage') or dict(
                logical_rpc_elements=0, physical_http_attempts=0, transport_batches=0,
                estimated_cu=0, cache_hits=0, methods={}, errors={}, actual_billed_cu=None,
                request_bytes=None, response_bytes=None)
        methods = Counter(old['methods'])
        methods.update(m for m, _ in calls)
        errors = Counter(old['errors'])
        for reason, count in after.get('failures', {}).items():
            errors[reason] += max(0, count - before.get('failures', {}).get(reason, 0))
        dispatched = max(0, after.get('requests', 0) - before.get('requests', 0))
        hits = max(0,len(calls)-dispatched) if completed else 0
        if isinstance(after.get('immutable_reuse'),dict):
            hits=max(hits,sum(max(0,n-(before.get('immutable_reuse') or {}).get(k,0))
                     for k,n in after['immutable_reuse'].items() if k.endswith((':hit',':session_hit'))))
        old.update(logical_rpc_elements=old['logical_rpc_elements'] + len(calls),
                physical_http_attempts=old['physical_http_attempts'] +
                    after.get('physical_http_requests', 0) - before.get('physical_http_requests', 0),
                transport_batches=old['transport_batches'] +
                    after.get('transport_requests', 0) - before.get('transport_requests', 0),
                estimated_cu=old['estimated_cu'] + 100 * dispatched,
                cache_hits=old['cache_hits'] + hits,
                methods=dict(methods), errors=dict(errors),
                estimate_basis='existing diagnostic 100 CU per requested transport element; conservative on local admission failure, not billing')
        for key in ('request_bytes','response_bytes'):
            if key in before and key in after:
                old[key]=(old[key] or 0)+max(0,after[key]-before[key])
        self.history.set_meta('pons_historical_usage', old)

    def header(self, block):
        h = self.calls([('eth_getBlockByNumber', [hex(block), False])])[0]
        if number(h) != block:
            raise BoundaryError('historical_header_number')
        return h

    @decision_work(5)
    def begin(self, *, prospective=False):
        """Freeze a head; one durable binary-search step per subsequent turn."""
        if self.history.get_meta(PLAN) is not None:
            return self.history.get_meta(PLAN)
        rpc = self.rpc(7)
        values = self.calls([('eth_chainId', []), ('eth_getBlockByNumber', ['0x0', False]),
            ('eth_getBlockByNumber', ['latest', False])] +
            [('eth_getCode', [load(r)['address'], 'latest']) for r in
             ('pons_v2_factory', 'pons_deployer', 'pons_v2_hook', 'uniswap_v4_manager')])
        if int(values[0], 16) != CHAIN_ID or number(values[1]) != 0:
            raise BoundaryError('historical_chain_identity')
        pins = [authenticate(r, load(r)['address'], code) for r, code in zip(
            ('pons_v2_factory', 'pons_deployer', 'pons_v2_hook', 'uniswap_v4_manager'), values[3:])]
        head = compact_header(values[2])
        top = number(head)
        cutoff = max(0, int(head['timestamp'], 16) - POLICY['universe']['max_seconds_after_graduation'])
        plan = dict(schema=SCHEMA, policy=POLICY_HASH, chain_id=CHAIN_ID,
            genesis_hash=values[1]['hash'], provider_fingerprint=require_canonical(rpc),
            deployments=pins, target=head, cutoff=cutoff, prospective=prospective,
            started_at=self.clock(), search=dict(low=-1, high=top), ready=False)
        if prospective:
            # Keep the seven-day requirement; readiness can mature only once the
            # domain floor moves past this independently authenticated enrollment.
            plan.update(first=top + 1, anchor=head, enrollment_at=int(head['timestamp'], 16))
        self.history.set_meta(PLAN, plan)
        self.restored = True
        return plan

    @decision_work(5)
    def boundary_step(self):
        p = self.history.get_meta(PLAN)
        if p is None:
            raise BoundaryError('historical_plan_missing')
        if 'first' in p:
            return p['first']
        lo, hi = p['search']['low'], p['search']['high']
        if lo + 1 < hi:
            mid = (lo + hi) // 2
            h = self.header(mid)
            p['search']['low' if int(h['timestamp'], 16) < p['cutoff'] else 'high'] = mid
        else:
            first = self.header(hi)
            prior = self.header(lo) if lo >= 0 else None
            target = self.header(number(p['target']))
            if (target['hash'] != p['target']['hash'] or int(first['timestamp'], 16) < p['cutoff']
                    or prior and (int(prior['timestamp'], 16) >= p['cutoff']
                                  or first['parentHash'] != prior['hash'])):
                raise BoundaryError('historical_domain_boundary_disagreement')
            p.update(first=hi, anchor=None if prior is None else compact_header(prior), first_header=compact_header(first))
        self.history.set_meta(PLAN, p)
        return p.get('first')

    def _frontier(self, kind, first, anchor):
        return self.history.get_meta('pons_historical_frontier:' + kind) or dict(
            block=first - 1, block_hash=None if anchor is None else anchor['hash'])

    def _gap(self, kind, first, last, reason):
        value = dict(category='INCOMPLETE_EVIDENCE', reason=reason, observed_at=self.clock())
        self.history.db.execute('INSERT OR REPLACE INTO pons_historical_gaps VALUES(?,?,?,?,?)',
            (kind, first, last, canonical(value), digest(value)))

    def _clear_gaps(self, kind, first, last):
        rows = self.history.db.execute('SELECT first,last,body,hash FROM pons_historical_gaps '
            'WHERE kind=? AND first<=? AND last>=?', (kind, last, first)).fetchall()
        for a, b, body, checksum in rows:
            value = self.history._verified((body, checksum))
            self.history.db.execute('DELETE FROM pons_historical_gaps WHERE kind=? AND first=? AND last=?', (kind, a, b))
            for lo, hi in ((a, first - 1), (last + 1, b)):
                if lo <= hi:
                    self.history.db.execute('INSERT OR REPLACE INTO pons_historical_gaps VALUES(?,?,?,?,?)',
                        (kind, lo, hi, body, digest(value)))

    def _validated(self, logs, query, first, last, *, response_bound=True):
        if not isinstance(logs, list):
            # eth_getLogs has no native page cursor. Never discard an envelope's
            # "next" field and mistake one page for the complete interval.
            raise BoundaryError('historical_pagination_or_response_shape')
        if response_bound and len(logs) >= self.log_limit:
            raise BoundaryError('historical_response_saturation')
        unique = {}
        ordered_identities = {}
        for event in logs:
            if (event.get('removed') or event.get('address', '').lower() != query['address']
                    or not first <= order(event)[0] <= last
                    or not event.get('topics') or event['topics'][0] not in query['topics'][0]
                    or len(query['topics']) > 1 and event['topics'][1] not in query['topics'][1]):
                raise BoundaryError('historical_log_filter_identity')
            ident = event_id(event)
            native_order = order(event)
            if native_order in ordered_identities and ordered_identities[native_order] != ident:
                raise BoundaryError('historical_canonical_order_conflict')
            ordered_identities[native_order] = ident
            if ident in unique and unique[ident] != event:
                raise BoundaryError('historical_duplicate_event_conflict')
            unique[ident] = event
        return sorted(unique.values(), key=order)

    def _witness(self, logs, query, first, last, *, response_bound=True):
        logs = self._validated(logs,query,first,last,response_bound=response_bound)
        # Aggregate the packet's immutable witnesses once, as the existing
        # multi-pool collector does. A ten-block slice is not a header/receipt
        # batching boundary and need not create four separate witness batches.
        blocks = sorted({order(e)[0] for e in logs})
        headers = {}
        for offset in range(0, len(blocks), 50):
            batch = blocks[offset:offset + 50]
            vals = self.calls([('eth_getBlockByNumber', [hex(b), False]) for b in batch])
            for b, h in zip(batch, vals):
                if number(h) != b:
                    raise BoundaryError('historical_event_header_number')
                headers[h['hash']] = h
        txs = list(dict.fromkeys((e['transactionHash'], e['blockHash']) for e in logs))
        receipts = {}
        transactions = {}
        for offset in range(0, len(txs), 50):
            batch = txs[offset:offset + 50]
            vals = self.calls([('eth_getTransactionReceipt', [tx]) for tx, _ in batch],receipt_pins=dict(batch))
            receipts.update(zip(batch, vals))
            if query['address'] == MANAGER:
                vals = self.calls([('eth_getTransactionByHash', [tx]) for tx, _ in batch])
                for (tx, bh), row in zip(batch, vals):
                    if row.get('hash') != tx or row.get('blockHash') != bh:
                        raise BoundaryError('historical_transaction_identity')
                transactions.update(zip(batch, vals))
        role = 'pons_v2_factory' if query['address'] == FACTORY else 'uniswap_v4_manager'
        abi = load(role)['abi']
        for event in logs:
            h = headers.get(event['blockHash'])
            if h is None:
                raise BoundaryError('historical_event_canonical_membership')
            raw_event(abi, event, address=query['address'],
                receipt=receipts[(event['transactionHash'], event['blockHash'])], header=h,
                observed_at=int(self.clock()), confirmation='confirmed')
        return dict(raw=logs, headers=headers, receipts=receipts, txs=transactions, sessions=[])

    def _put_events(self, kind, logs):
        for e in logs:
            ident = event_id(e)
            old = self.history.db.execute('SELECT body,hash FROM pons_historical_events WHERE kind=? AND id=?', (kind, ident)).fetchone()
            if old and self.history._verified(old) != e:
                raise BoundaryError('historical_event_conflict')
            self.history.db.execute('INSERT INTO pons_historical_events VALUES(?,?,?,?,?,1) '
                'ON CONFLICT(kind,id) DO UPDATE SET valid=1',
                (ident, kind, order(e)[0], canonical(e), digest(e)))

    def _packet(self, kind, query, first, last, anchor, consume=None, participants=None):
        frontier = self._frontier(kind, first, anchor)
        start = frontier['block'] + 1
        if start > last:
            return False
        pending_key = 'pons_historical_subdivision:' + kind
        pending = self.history.get_meta(pending_key) or []
        spans = pending[:4] if pending else [(b, min(last, b + self.range_blocks - 1))
             for b in range(start, min(last + 1, start + 4 * self.range_blocks), self.range_blocks)]
        if spans[0][0] != start or any(b[0] != a[1] + 1 for a, b in zip(spans, spans[1:])):
            raise BoundaryError('historical_checkpoint_gap')
        end = spans[-1][1]
        self._gap(kind, start, end, 'acquisition_in_progress')
        calls = [('eth_getLogs', [dict(query, fromBlock=hex(a), toBlock=hex(b))]) for a, b in spans]
        calls.append(('eth_getBlockByNumber', [hex(end), False]))
        if frontier['block'] >= 0:
            calls.append(('eth_getBlockByNumber', [hex(frontier['block']), False]))
        try:
            values = self.calls(calls)
            h = values[len(spans)]
            if number(h) != end:
                raise BoundaryError('historical_range_boundary_number')
            if frontier['block'] >= 0:
                prior = values[-1]
                if number(prior) != frontier['block'] or prior['hash'] != frontier['block_hash']:
                    self.restored = False
                    raise BoundaryError('historical_frontier_reorg')
            else:
                prior = None
            raw = []
            for (a, b), logs in zip(spans, values[:len(spans)]):
                raw.extend(self._validated(logs,query,a,b))
            shared = [self._witness(raw,query,start,end,response_bound=False)]
            all_logs = [e for s in shared for e in s['raw']]
            # A fresh post-witness boundary protects against reorg while receipts
            # and transaction senders were being acquired. Empty ranges already
            # have both canonical endpoints in the complete provider batch.
            if all_logs and self.header(end)['hash'] != h['hash']:
                self.restored = False
                raise BoundaryError('historical_range_reorg')
            evidence = dict(schema=SCHEMA, provider_fingerprint=self.fingerprint, policy=POLICY_HASH,
                chain_id=CHAIN_ID, query=query, spans=spans,
                previous=None if prior is None else compact_header(prior), end=compact_header(h),
                identities=[event_id(e) for e in all_logs], event_digest=digest(all_logs),
                participants=participants,
                response_contract='complete eth_getLogs arrays; canonical bounds and receipt membership',
                support=self.support if self.range_blocks > 10 else 'preserved ten-block runtime bound')
            with self.history.transaction():
                origin_key = 'pons_historical_origin:' + kind
                if self.history.get_meta(origin_key) is None:
                    self.history.set_meta(origin_key,dict(first=start,anchor=frontier,
                        participants=participants,provider_fingerprint=self.fingerprint,policy=POLICY_HASH))
                if participants and not self.history.db.execute(
                        'SELECT 1 FROM pons_historical_members WHERE kind=? LIMIT 1',(kind,)).fetchone():
                    self.history.db.executemany('INSERT OR IGNORE INTO pons_historical_members VALUES(?,?)',
                                               [(token,kind) for token in participants])
                self._put_events(kind, all_logs)
                if consume:
                    consume(end, h, shared)
                if kind == 'population':
                    grads = [e for e in all_logs if e['topics'][0] == GRADUATION]
                    self.history.retain_graduations(grads, end, block_hash=h['hash'])
                ident = digest([kind, start, end, evidence])
                self.history.db.execute('INSERT OR IGNORE INTO pons_historical_ranges VALUES(?,?,?,?,?,?,1,?)',
                    (ident, kind, start, end, canonical(evidence), digest(evidence),int(h['timestamp'],16)))
                self.history.set_meta('pons_historical_frontier:' + kind, dict(block=end, block_hash=h['hash']))
                self.history.set_meta(pending_key, pending[len(spans):])
                self._clear_gaps(kind, start, end)
                p = self.history.get_meta(PLAN)
                p['ready'] = False
                self.history.set_meta(PLAN, p)
            return True
        except (BoundaryError, ValueError) as exc:
            reason = str(exc)
            self._gap(kind, start, end, reason)
            if reason in SPLIT_ERRORS and any(a < b for a, b in spans):
                divided = []
                for a, b in spans:
                    if a == b:
                        divided.append((a, b))
                    else:
                        mid = (a + b) // 2
                        divided.extend(((a, mid), (mid + 1, b)))
                self.history.set_meta(pending_key, divided + pending[len(spans):])
                return False
            raise

    @decision_work(5)
    def discover_step(self):
        if not self.restored:
            raise BoundaryError('historical_restore_verification_required')
        p = self.history.get_meta(PLAN)
        if 'first' not in p:
            return self.boundary_step()
        return self._packet('population', self.population_filter(), p['first'], number(p['target']), p['anchor'])

    def population(self):
        rows = self.history.db.execute("SELECT body,hash FROM pons_historical_events WHERE kind='population' AND valid=1 ORDER BY block,id")
        return sorted((self.history._verified(r) for r in rows), key=order)

    def _launch_step(self, token, record, graduation_block):
        known = [self.history._verified(r) for r in self.history.db.execute(
            "SELECT body,hash FROM pons_historical_events WHERE kind='population' AND valid=1 "
            "AND json_extract(body,'$.topics[1]')=? AND json_extract(body,'$.topics[0]')=?",
            ('0x'+'0'*24+token[2:],LAUNCH))]
        kind = 'launch:' + token
        known += [self.history._verified(r) for r in self.history.db.execute(
            'SELECT body,hash FROM pons_historical_events WHERE kind=? AND valid=1', (kind,))]
        if known:
            if len(known) != 1:
                raise BoundaryError('historical_launch_ambiguous')
            e = known[0]
            args = decode_event(load('pons_v2_factory')['abi'], e)['args']
            if (args['curve'] != record['curve'] or args['deployer'] != record['deployer']
                    or args['pairToken'] != record['pairToken'] or order(e)[0] > graduation_block):
                raise BoundaryError('historical_launch_relationship')
            return e
        # A launch can precede the seven-day graduation domain. Locate its exact
        # timestamp via the authenticated curve, then census the entire second;
        # never infer the launch from previously retained runtime candidates.
        key = 'pons_historical_launch_search:' + token
        s = self.history.get_meta(key)
        if s is None:
            raw = self.calls([('eth_call', [dict(to=record['curve'], data=calldata('launchedAt()')),
                                          hex(graduation_block)])])[0]
            from .pons_natural_observation import _one_word
            at = _one_word(raw, 'uint256')
            s = dict(at=at, low=int(load('pons_v2_factory')['deployment']['blockNumber']) - 1,
                     high=graduation_block, phase='first')
            if not 0 <= at <= int(self.header(graduation_block)['timestamp'], 16):
                raise BoundaryError('historical_launch_time')
        lo, hi = s['low'], s['high']
        cutoff = s['at'] + (1 if s['phase'] == 'last' else 0)
        if lo + 1 < hi:
            mid = (lo + hi) // 2
            h = self.header(mid)
            s['low' if int(h['timestamp'], 16) < cutoff else 'high'] = mid
        elif s['phase'] == 'first':
            h = self.header(hi)
            if int(h['timestamp'], 16) != s['at']:
                raise BoundaryError('historical_launch_timestamp_missing')
            s.update(first=hi, anchor=self.header(lo), phase='last', low=hi, high=graduation_block + 1)
        else:
            first, last = s['first'], hi - 1
            self._packet(kind, dict(address=FACTORY, topics=[[LAUNCH], ['0x' + '0' * 24 + token[2:]]]),
                         first, last, s['anchor'])
            if self._frontier(kind, first, s['anchor'])['block'] == last:
                # Revisit the authenticated journal on the next bounded turn.
                s['complete'] = True
        self.history.set_meta(key, s)
        if s.get('complete') and not self.history.db.execute(
                'SELECT 1 FROM pons_historical_events WHERE kind=? AND valid=1', (kind,)).fetchone():
            raise BoundaryError('historical_launch_identity_missing')
        return None

    @decision_work(5)
    def authenticate_step(self):
        """Reuse native factory/graduation/curve authentication; never price-select."""
        if not self.restored:
            raise BoundaryError('historical_restore_verification_required')
        nominations = self.history.graduation_batch()
        if not nominations:
            return False
        ident, event = nominations[0]
        if not self.history.db.execute("SELECT 1 FROM pons_historical_events WHERE kind='population' AND valid=1 AND id=?",
                                       (event_id(event),)).fetchone():
            raise BoundaryError('historical_nomination_outside_census')
        args = decode_event(load('pons_v2_factory')['abi'], event)['args']
        token = args['token']
        block = order(event)[0]
        pending_key = 'pons_historical_authentication:' + ident
        pending = self.history.get_meta(pending_key)
        if pending is None:
            rpc = _NativeReads(self)
            report = {'reads': []}
            record = _factory_record_at(rpc, token, block, report)
            result = _graduation_transition(rpc, dict(token=token, curve=record['curve']), block, block, report)
            if result is None:
                raise BoundaryError('historical_graduation_missing')
            transition, key, h, record = result
            if h['hash'] != event['blockHash'] or self.header(block)['hash'] != h['hash']:
                raise BoundaryError('historical_graduation_membership')
            code = self.calls([('eth_getCode', [record['curve'], hex(block)])])[0]
            curve = authenticate_curve(record['curve'], code, factory_record=record)
            pending = dict(event_identity=event_id(event), record=record, transition=transition,
                           key=asdict(key), header=compact_header(h), curve=curve,
                           provider_fingerprint=self.fingerprint, policy=POLICY_HASH)
            # A launch predating the domain needs bounded timestamp searches.
            # Keep the already authenticated immutable lineage between turns.
            self.history.set_meta(pending_key,pending)
        elif (pending['event_identity'] != event_id(event) or pending['policy'] != POLICY_HASH
                or pending['provider_fingerprint'] != self.fingerprint):
            raise BoundaryError('historical_pending_lineage_identity')
        record,transition = pending['record'],pending['transition']
        key,h,curve = PoolKey(**pending['key']),pending['header'],pending['curve']
        launch = self._launch_step(token, record, block)
        if launch is None:
            return False
        if self.header(block)['hash'] != h['hash']:
            self.history.set_meta(pending_key,None)
            self.restored = False
            raise BoundaryError('historical_graduation_membership')
        evidence = dict(at=transition['graduation_at'], block=block, block_hash=h['hash'],
            transition=transition, key=asdict(key), record=record,
            source='robinhood_authenticated_candidate_evidence_plane')
        p = self.history.get_meta(PLAN)
        disposition = None
        if record['pairToken'] != ZERO:
            disposition = 'non_native_quote'
        elif self.history.get(token) is None and (self.history.expired(evidence)
                  or int(p['target']['timestamp'], 16) - evidence['at'] > POLICY['universe']['max_seconds_after_graduation']):
            disposition = 'strategy_horizon_expired'
        with self.history.transaction():
            self.history.set_meta('pons_historical_identity:' + token, dict(
                nomination=ident, event_identity=event_id(event), curve=curve, evidence=evidence,
                launch=launch,
                disposition=disposition, category='STRUCTURAL_INELIGIBLE' if disposition == 'non_native_quote'
                else 'EXPIRED_BY_STRATEGY_HORIZON' if disposition else 'PENDING_HISTORY'))
            if disposition is None:
                old = self.history.get(token)
                if old and old['graduation'] != evidence:
                    old_anchor = self.header(old['graduation']['block'])
                    if old_anchor['hash'] == old['graduation']['block_hash']:
                        raise BoundaryError('historical_conflicting_canonical_graduation')
                    old.update(complete=False, recovery='graduation_membership_unavailable')
                    self.history.save(old)
                    from .pons_survivor_runtime import price_index
                    row = self.history.replace_orphaned_graduation(token, evidence,
                        anchor_price=price_index(transition['initialization_sqrt_price_x96'], token, key))
                else:
                    row = self.history.graduate(token, evidence)
                if row.get('block') is None:
                    from .pons_survivor_runtime import price_index
                    self.history.append_block(token, block=block, header=h, events=[],
                        points=[(evidence['at'], str(price_index(transition['initialization_sqrt_price_x96'], token, key)))])
            self.history.graduation_complete(ident)
            self.history.set_meta(pending_key,None)
        return True

    @decision_work(5)
    def history_step(self, runtime, token):
        """Hydrate one retained candidate using the native tape/append reducer.

        No fake runtime/book is constructed here. Only _append_tape is reused;
        qualification, funding, deadlines and lifecycle controllers are untouched.
        """
        if runtime.history is not self.history or not self.restored:
            raise BoundaryError('historical_history_authority')
        row = self.history.get(token)
        if row is None or row.get('block') is None or row.get('recovery') not in (
                None, 'bounded_replay_from_canonical_graduation'):
            raise BoundaryError('historical_candidate_anchor_incomplete')
        p = self.history.get_meta(PLAN)
        kind = 'candidate:' + token
        grad = row['graduation']
        key = PoolKey(**grad['key'])
        first = grad['block'] + 1
        anchor = dict(hash=grad['block_hash'])
        # Existing native histories can only be reused after resume() verifies
        # their stored checkpoints; their cursor is never invented from a report.
        if self.history.get_meta('pons_historical_frontier:' + kind) is None and row['block'] >= first:
            self.history.set_meta('pons_historical_frontier:' + kind,
                dict(block=row['block'], block_hash=row.get('block_hash', grad['block_hash'])))
        query = dict(address=MANAGER, topics=[ACTIVITY, [grad['transition']['market']]])
        def consume(end, header, batches):
            combined = dict(raw=[], headers={}, receipts={}, txs={}, sessions=[])
            for s in batches:
                combined['raw'].extend(e for e in s['raw'] if e['topics'][0] == SWAP)
                for k in ('headers', 'receipts', 'txs'):
                    combined[k].update(s[k])
            tape = collect_v4_activity(None, pool_id=grad['transition']['market'], key=key,
                token=token, start_block=row['block'] + 1, end_block=end, _shared=combined)
            runtime._append_tape(row, end, header, tape)
            if end == number(p['target']):
                self.history.finish_recovery(token, block=end, block_hash=header['hash'])
        return self._packet(kind, query, first, number(p['target']), anchor, consume,participants=[token])

    @decision_work(5)
    def history_group_step(self, runtime, rows):
        """Reuse the existing 64-market transport bound without capping population."""
        if runtime.history is not self.history or not self.restored or not 1 <= len(rows) <= 64:
            raise BoundaryError('historical_history_group_authority')
        rows = [self.history.get(r['id']) for r in rows]
        if any(r is None or r.get('block') is None or r.get('recovery') not in
               (None, 'bounded_replay_from_canonical_graduation') for r in rows):
            raise BoundaryError('historical_candidate_anchor_incomplete')
        p = self.history.get_meta(PLAN)
        rows.sort(key=lambda r:r['id'])
        kind = 'candidates:' + digest([r['id'] for r in rows])
        first = min(r['block'] for r in rows) + 1
        earliest = next(r for r in rows if r['block'] == first - 1)
        anchor = dict(hash=earliest.get('block_hash',earliest['graduation']['block_hash']))
        markets = {r['id']:r['graduation']['transition']['market'] for r in rows}
        query = dict(address=MANAGER, topics=[ACTIVITY, sorted(markets.values())])
        def consume(end, header, batches):
            combined = dict(raw=[], headers={}, receipts={}, txs={}, sessions=[])
            for batch in batches:
                combined['raw'].extend(e for e in batch['raw'] if e['topics'][0] == SWAP)
                for k in ('headers','receipts','txs'):
                    combined[k].update(batch[k])
            for row in rows:
                if row['block'] >= end:
                    continue
                shared = dict(combined,raw=[e for e in combined['raw']
                    if e['topics'][1] == markets[row['id']] and order(e)[0] > row['block']])
                tape = collect_v4_activity(None,pool_id=markets[row['id']],key=PoolKey(**row['graduation']['key']),
                    token=row['id'],start_block=row['block']+1,end_block=end,_shared=shared)
                runtime._append_tape(row,end,header,tape)
                if end == number(p['target']):
                    self.history.finish_recovery(row['id'],block=end,block_hash=header['hash'])
        return self._packet(kind,query,first,number(p['target']),anchor,consume,
                            participants=[r['id'] for r in rows])

    @decision_work(5)
    def step(self, runtime):
        """One bounded turn for the existing Survivor worker, with durable resume.

        The caller runs native position management first and retains the existing
        admission guard. This method only acquires evidence; it never qualifies,
        funds or releases Current. Normal turns retain four ten-block queries.
        """
        if self.history.get_meta(PLAN) is None:
            self.begin()
        elif not self.restored:
            return self.resume()
        p = self.history.get_meta(PLAN)
        if 'first' not in p:
            self.boundary_step()
        elif self._frontier('population',p['first'],p['anchor'])['block'] < number(p['target']):
            self.discover_step()
        elif self.history.pending_graduations():
            self.authenticate_step()
        else:
            rows = self.history.rows()
            recovery = next((r for r in rows if r.get('recovery') not in
                             (None,'bounded_replay_from_canonical_graduation')),None)
            if recovery:
                self.recover_candidate(runtime,recovery['id'])
            else:
                for row in list(rows):
                    if not row.get('position') and row['graduation']['at'] < p['cutoff']:
                        self.history.retire(row,expired_before=p['cutoff'])
                rows = self.history.rows()
                # Stable cohorts preserve shared pool queries while newcomers
                # arrive. The 64 limit bounds one transport, never enrollment.
                cohorts = self.history.get_meta('pons_historical_cohorts') or []
                assigned = {token for group in cohorts for token in group}
                newcomers = [r['id'] for r in sorted(rows,key=lambda r:(r['graduation']['block'],r['id']))
                             if r['id'] not in assigned]
                # Freeze each cohort once first acquired. Appending a newcomer
                # would change its query identity and refetch older pool ranges.
                cohorts.extend(newcomers[i:i+64] for i in range(0,len(newcomers),64))
                self.history.set_meta('pons_historical_cohorts',cohorts)
                groups = [[self.history.get(t) for t in group] for group in cohorts]
                groups = [[r for r in group if r and r['state'] != 'retired'] for group in groups]
                pending = [group for group in groups if any(r['block'] < number(p['target']) for r in group)]
                if pending:
                    chosen = min(pending,key=lambda g:(max(r.get('history_attempt',0) for r in g),
                                                       min(r['block'] for r in g)))
                    self.history.history_batch(chosen,number(p['target']))
                    self.history_group_step(runtime,chosen)
        return self.readiness()

    @decision_work(5)
    def recover_candidate(self, runtime, token):
        if runtime.history is not self.history or not self.restored:
            raise BoundaryError('historical_history_authority')
        row = self.history.get(token)
        if row is None or not row.get('recovery'):
            return False
        # Native reset checks the graduation's canonical membership and preserves
        # position/controller fields. An orphan graduation remains incomplete.
        runtime._recover_reorg(row)
        row = self.history.get(token)
        if row.get('recovery') == 'graduation_membership_unavailable':
            return False
        kind = 'candidate:' + token
        with self.history.transaction():
            for group, body, checksum in self.history.db.execute(
                    "SELECT kind,body,hash FROM pons_historical_ranges WHERE kind LIKE 'candidates:%' AND valid=1").fetchall():
                if token in (self.history._verified((body,checksum)).get('participants') or []):
                    self.history.db.execute('UPDATE pons_historical_ranges SET valid=0 WHERE kind=?',(group,))
                    self.history.db.execute('UPDATE pons_historical_events SET valid=0 WHERE kind=?',(group,))
                    self.history.set_meta('pons_historical_frontier:'+group,None)
                    self.history.set_meta('pons_historical_origin:'+group,None)
                    self.history.set_meta('pons_historical_subdivision:'+group,[])
            self.history.db.execute('UPDATE pons_historical_ranges SET valid=0 WHERE kind=?', (kind,))
            self.history.db.execute('UPDATE pons_historical_events SET valid=0 WHERE kind=?', (kind,))
            self.history.set_meta('pons_historical_frontier:' + kind,
                dict(block=row['block'], block_hash=row['block_hash']))
            self.history.set_meta('pons_historical_origin:' + kind,None)
            self.history.set_meta('pons_historical_subdivision:' + kind, [])
            # Recovery itself does not make missing history complete. Subsequent
            # native append/reconstruction clears the bounded recovery state.
            row['complete'] = False
            self.history.save(row)
        return True

    def verify_database(self):
        if self.history.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise BoundaryError('historical_database_integrity')
        for table in ('meta', 'candidates', 'events', 'pons_graduation_intake',
                      'pons_historical_events', 'pons_historical_ranges', 'pons_historical_gaps'):
            for body, checksum in self.history.db.execute('SELECT body,hash FROM ' + table):
                self.history._verified((body, checksum))
        for row in self.history.rows(include_retired=True):
            if row['state'] != 'retired':
                self.history.facts(row['id'], row.get('through', row['graduation']['at']))
        for token,at,price,checksum in self.history.db.execute('SELECT candidate,at,price,hash FROM points'):
            if digest([token,at,price]) != checksum:
                raise BoundaryError('historical_price_replay_corruption')

    @decision_work(5)
    def resume(self):
        """Validate the database, original chain and frontier before reuse.

        Reorg rewind finds the latest proven checkpoint by binary search. Existing
        economic controllers remain in native history; only acquisition authority
        and noncanonical observations are invalidated.
        """
        self.restored = False
        self.verify_database()
        p = self.history.get_meta(PLAN)
        if p is None or p.get('schema') != SCHEMA or p.get('policy') != POLICY_HASH:
            raise BoundaryError('historical_restore_plan')
        vals = self.calls([('eth_chainId', []), ('eth_getBlockByNumber', ['0x0', False])])
        if (int(vals[0], 16) != p['chain_id'] or number(vals[1]) != 0
                or vals[1]['hash'] != p['genesis_hash'] or self.fingerprint != p['provider_fingerprint']):
            raise BoundaryError('historical_restore_source_identity')
        if 'first' not in p:
            # A search interrupted across a reorg cannot reuse number/timestamp
            # comparisons from the old fork. Retain the frozen time requirement.
            if self.header(number(p['target']))['hash'] != p['target']['hash']:
                raise BoundaryError('historical_search_target_reorg')
            self.restored = True
            return dict(ready=False, boundary_pending=True)
        if p['anchor'] is not None:
            anchor = self.header(p['first'] - 1)
            if anchor['hash'] != p['anchor']['hash']:
                raise BoundaryError('historical_domain_anchor_reorg')
        kinds = [r[0] for r in self.history.db.execute('SELECT DISTINCT kind FROM pons_historical_ranges WHERE valid=1')]
        population_frontier = self.history.get_meta('pons_historical_frontier:population')
        if population_frontier and population_frontier['block'] >= p['first'] and 'population' not in kinds:
            raise BoundaryError('historical_population_ranges_missing')
        for kind in kinds:
            rows = self.history.db.execute('SELECT id,first,last,body,hash FROM pons_historical_ranges '
                'WHERE kind=? AND valid=1 ORDER BY first,last', (kind,)).fetchall()
            origin = self.history.get_meta('pons_historical_origin:'+kind)
            retention = self.history.get_meta('pons_historical_retention_anchor:'+kind)
            if origin is None or origin['provider_fingerprint'] != p['provider_fingerprint'] or origin['policy'] != POLICY_HASH:
                raise BoundaryError('historical_range_origin')
            expected_first = retention['block']+1 if retention else origin['first']
            expected_hash = (retention or origin['anchor'])['block_hash']
            if kind == 'population':
                expected_first = p['first']
                expected_hash = None if p['anchor'] is None else p['anchor']['hash']
            if rows[0][1] != expected_first:
                raise BoundaryError('historical_range_replay_gap')
            prior_end = expected_first-1
            prior_hash = expected_hash
            for _, first, last, body, checksum in rows:
                e = self.history._verified((body, checksum))
                if (first != prior_end + 1 or number(e['end']) != last
                        or e['provider_fingerprint'] != p['provider_fingerprint']
                        or e['policy'] != POLICY_HASH
                        or prior_hash is not None and e['previous']['hash'] != prior_hash):
                    raise BoundaryError('historical_range_replay_gap')
                logs = [self.history._verified(r) for r in self.history.db.execute(
                    'SELECT body,hash FROM pons_historical_events WHERE kind=? AND valid=1 AND block BETWEEN ? AND ? ORDER BY block,id',
                    (kind, first, last))]
                logs.sort(key=order)
                if digest(logs) != e['event_digest'] or [event_id(x) for x in logs] != e['identities']:
                    raise BoundaryError('historical_range_event_replay')
                prior_end, prior_hash = last, e['end']['hash']
            frontier = self.history.get_meta('pons_historical_frontier:' + kind)
            if frontier != dict(block=prior_end, block_hash=prior_hash):
                raise BoundaryError('historical_frontier_replay')
            if self.header(prior_end)['hash'] == prior_hash:
                continue
            low, high = -1, len(rows)
            while low + 1 < high:
                mid = (low + high) // 2
                e = self.history._verified((rows[mid][3], rows[mid][4]))
                if self.header(rows[mid][2])['hash'] == e['end']['hash']:
                    low = mid
                else:
                    high = mid
            rewind = rows[0][1] - 1 if low < 0 else rows[low][2]
            h = self.header(rewind) if rewind >= 0 else None
            with self.history.transaction():
                self.history.db.execute('UPDATE pons_historical_ranges SET valid=0 WHERE kind=? AND last>?', (kind, rewind))
                self.history.db.execute('UPDATE pons_historical_events SET valid=0 WHERE kind=? AND block>?', (kind, rewind))
                self.history.set_meta('pons_historical_frontier:' + kind,
                    dict(block=rewind, block_hash=None if h is None else h['hash']))
                self.history.set_meta('pons_historical_subdivision:' + kind, [])
                if kind == 'population':
                    for nomination, body, checksum in self.history.db.execute(
                            'SELECT id,body,hash FROM pons_graduation_intake').fetchall():
                        if order(self.history._verified((body, checksum)))[0] > rewind:
                            self.history.db.execute('DELETE FROM pons_graduation_intake WHERE id=?', (nomination,))
                    self.history.set_meta('discovery_block', rewind)
                    self.history.set_meta('discovery_block_hash', None if h is None else h['hash'])
                else:
                    affected = e.get('participants') or [kind.split(':', 1)[1]]
                    if not kind.startswith('launch:'):
                        for token in affected:
                            row = self.history.get(token)
                            if row is not None and row.get('block',-1) > rewind:
                                row.update(complete=False, recovery='historical_frontier_reorg')
                                self.history.save(row)
                self._gap(kind, rewind + 1, prior_end, 'canonical_reorganization')
                p['ready'] = False
                self.history.set_meta(PLAN, p)
        # An authenticated population frontier does not certify retained economic
        # histories. Every retained row is checked, regardless of funding state.
        for row in self.history.rows():
            if row.get('block') is None:
                continue
            h = self.header(row['block'])
            if h['hash'] != row.get('block_hash', row['graduation']['block_hash']):
                row.update(complete=False, recovery='historical_frontier_reorg')
                self.history.save(row)
        # Refresh a forked frozen head only at its original height/time domain.
        h = self.header(number(p['target']))
        if h['hash'] != p['target']['hash']:
            if int(h['timestamp'], 16) - POLICY['universe']['max_seconds_after_graduation'] != p['cutoff']:
                raise BoundaryError('historical_reorg_domain_changed')
            p.update(target=compact_header(h), ready=False)
            self.history.set_meta(PLAN, p)
        self.restored = True
        return self.readiness()

    def readiness(self):
        p = self.history.get_meta(PLAN)
        if p is None or 'first' not in p:
            return dict(ready=False, category='INCOMPLETE_EVIDENCE', reason='boundary_pending')
        top = number(p['target'])
        frontier = self._frontier('population', p['first'], p['anchor'])
        # The eligibility ceiling is inclusive. At exact equality, an event in
        # the enrollment header could still be eligible but predates first=top+1.
        mature = not p['prospective'] or p['cutoff'] > p['enrollment_at']
        gaps = self.history.db.execute('SELECT COUNT(*) FROM pons_historical_gaps').fetchone()[0]
        incomplete = [r['id'] for r in self.history.rows() if r.get('block', -1) < top
                      or r.get('complete') is not True or r.get('recovery') or not self._candidate_coverage(r,top)]
        # Reconcile every graduation against a durable native identity/disposition.
        missing = []
        pending = self.history.pending_graduations()
        if self.restored and mature and frontier['block'] == top and not gaps and not incomplete and not pending:
            # Do not repeatedly materialize/decode the entire population during
            # each incomplete backfill turn. The final independent census check
            # streams indexed graduation rows only, with one native ABI load.
            abi=load('pons_v2_factory')['abi']
            for body,checksum in self.history.db.execute("SELECT body,hash FROM pons_historical_events WHERE kind='population' AND valid=1 AND json_extract(body,'$.topics[0]')=?",(GRADUATION,)):
                e=self.history._verified((body,checksum))
                token = decode_event(abi, e)['args']['token']
                disposition = self.history.get_meta('pons_historical_identity:' + token)
                if disposition is None or disposition['event_identity'] != event_id(e):
                    missing.append(event_id(e))
                elif disposition['disposition'] is None and self.history.get(token) is None:
                    missing.append(event_id(e))
        ready = (self.restored and mature and frontier['block'] == top and not gaps
                 and not incomplete and not missing and not pending)
        result = dict(ready=ready, category='COMPLETE' if ready else 'INCOMPLETE_EVIDENCE',
            population_through=frontier['block'], target_block=top, seven_day_domain_mature=mature,
            missing_ranges=gaps, incomplete_candidates=incomplete, missing_graduations=missing,
            pending_graduations=pending, provider_certified=False,
            current_readiness='owned by existing Current prerequisites and startup guard')
        p.update(ready=ready, readiness=result)
        self.history.set_meta(PLAN, p)
        return result

    def _candidate_coverage(self, row, top):
        first = row['graduation']['block']+1
        if first > top:
            return True
        intervals = []
        for (kind,) in self.history.db.execute('SELECT kind FROM pons_historical_members WHERE candidate=?',(row['id'],)):
            origin = self.history.get_meta('pons_historical_origin:'+kind)
            frontier = self.history.get_meta('pons_historical_frontier:'+kind)
            if origin and frontier and row['id'] in (origin.get('participants') or []):
                intervals.append((origin['first'],frontier['block']))
        through = first-1
        for a,b in sorted(intervals):
            if a > through+1:
                break
            through = max(through,b)
        return through >= top

    @decision_work(5)
    def extend(self, head):
        """Resume rolling acquisition; enrollment and candidate deadlines persist."""
        if not self.restored:
            raise BoundaryError('historical_restore_verification_required')
        p = self.history.get_meta(PLAN)
        if number(head) < number(p['target']) or self.header(number(head))['hash'] != head['hash']:
            raise BoundaryError('historical_extension_identity')
        p.update(target=compact_header(head), cutoff=max(0, int(head['timestamp'], 16) -
                 POLICY['universe']['max_seconds_after_graduation']), ready=False)
        self.history.set_meta(PLAN, p)

    def maintain(self, *, recovery_before, limit=256):
        """Retire only complete material outside strategy AND recovery retention.

        The caller supplies the original recovery retention floor, never a storage
        pressure target. Native candidate/controller/position journals are owned by
        their existing retention machinery and are not deleted here.
        """
        p = self.history.get_meta(PLAN)
        if (not self.restored or type(recovery_before) is not int or not p.get('ready')
                or type(limit) is not int or not 1 <= limit <= 512):
            raise BoundaryError('historical_retention_prerequisites')
        floor = min(recovery_before,p['cutoff'])
        removable = []
        cursor=self.history.get_meta('pons_historical_retention_scan') or [-1,'',-1,-1,'']
        def page(cursor):
            return self.history.db.execute('SELECT id,kind,first,last,body,hash,valid,through_at FROM pons_historical_ranges '
                'WHERE through_at<? AND (through_at,kind,first,last,id)>(?,?,?,?,?) '
                'ORDER BY through_at,kind,first,last,id LIMIT ?', (floor,*cursor,limit)).fetchall()
        rows=page(cursor)
        if not rows:rows=page([-1,'',-1,-1,''])
        identity_cursor=self.history.get_meta('pons_historical_identity_retention_scan') or ''
        identities=self.history.db.execute("SELECT key,body,hash FROM meta WHERE key LIKE 'pons_historical_identity:%' AND key>? ORDER BY key LIMIT ?",
                                           (identity_cursor,limit)).fetchall()
        if not identities:
            identities=self.history.db.execute("SELECT key,body,hash FROM meta WHERE key LIKE 'pons_historical_identity:%' ORDER BY key LIMIT ?",(limit,)).fetchall()
        next_population=p['first']
        for ident,kind,first,last,body,checksum,valid,through_at in rows:
            e = self.history._verified((body,checksum))
            if int(e['end']['timestamp'],16) >= floor:
                continue
            participants = e.get('participants') or ([kind.split(':',1)[1]] if kind.startswith('candidate:') else [])
            if any((self.history.get(t) or {}).get('position') for t in participants):
                continue
            if kind != 'population' and any((self.history.get(t) or {}).get('state') != 'retired' for t in participants):
                continue
            if kind == 'population' and valid:
                if first != next_population:
                    continue
                next_population=last+1
            removable.append((ident,kind,first,last,e,valid))
        with self.history.transaction():
            previous = self.history.get_meta('pons_historical_retired') or dict(count=0,hash=None)
            for ident,kind,first,last,e,valid in removable:
                self.history.db.execute('DELETE FROM pons_historical_ranges WHERE id=?',(ident,))
                previous.update(count=previous['count']+1,hash=digest([previous['hash'],ident,e]),before=floor)
                if valid:
                    self.history.set_meta('pons_historical_retention_anchor:'+kind,dict(block=last,block_hash=e['end']['hash']))
                if kind == 'population' and valid:
                    if first != p['first']:
                        raise BoundaryError('historical_retirement_prefix_gap')
                    p.update(first=last+1,anchor=e['end'])
            for _,kind,first,last,_,_ in removable:
                self.history.db.execute('DELETE FROM pons_historical_events AS e WHERE kind=? AND block BETWEEN ? AND ? '
                    'AND NOT EXISTS (SELECT 1 FROM pons_historical_ranges r WHERE r.kind=e.kind AND e.block BETWEEN r.first AND r.last)',
                    (kind,first,last))
            for kind in {r[1] for r in removable}:
                if not self.history.db.execute('SELECT 1 FROM pons_historical_ranges WHERE kind=? LIMIT 1',(kind,)).fetchone():
                    self.history.db.execute('DELETE FROM pons_historical_members WHERE kind=?',(kind,))
                    for prefix in ('origin:','frontier:','subdivision:','retention_anchor:'):
                        self.history.db.execute('DELETE FROM meta WHERE key=?',('pons_historical_'+prefix+kind,))
            for key,body,checksum in identities:
                identity=self.history._verified((body,checksum))
                row=self.history.get(key.split(':',1)[1])
                if (identity['evidence']['at'] >= floor or row and
                        (row['state'] != 'retired' or row.get('position')) or self.history.db.execute(
                        "SELECT 1 FROM pons_historical_events WHERE kind='population' AND valid=1 AND id=?",
                        (identity['event_identity'],)).fetchone()):
                    continue
                token=key.split(':',1)[1]
                for oldkey in (key,'pons_historical_launch_search:'+token,
                               'pons_historical_authentication:'+identity['nomination']):
                    self.history.db.execute('DELETE FROM meta WHERE key=?',(oldkey,))
            if identities:
                self.history.set_meta('pons_historical_identity_retention_scan',identities[-1][0])
            cohorts=self.history.get_meta('pons_historical_cohorts')
            if cohorts:
                self.history.set_meta('pons_historical_cohorts',[
                    group for group in cohorts if any((self.history.get(token) or {}).get('state') not in (None,'retired')
                                                     for token in group)])
            self.history.set_meta('pons_historical_retired',previous)
            self.history.set_meta(PLAN,p)
            if rows:
                ident,kind,first,last,_,_,_,through_at=rows[-1]
                self.history.set_meta('pons_historical_retention_scan',[through_at,kind,first,last,ident])
        return dict(retired_ranges=len(removable),before=floor,native_economic_state_mutated=False)
