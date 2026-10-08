"""Bounded adaptive Pons log acquisition; range hints never certify evidence.

Ten blocks is the fallback. A larger window requires a nonempty, hash-bound
comparison for this credential, static filter and indexed-filter cardinality.
Density, saturation and transport limits still constrain every acquired page.
The caller alone publishes canonical history/checkpoints after authentication.
"""
from collections import Counter
import json
import math
import os
from pathlib import Path
import time

from . import BoundaryError, CHAIN_ID
from meme_machine.runtime.journal import digest
from meme_machine.runtime.robinhood import provider_authority as authority

SAFE_BLOCKS = 10
MAX_BLOCKS = 160
PAGE_LOGS = 1000
TARGET_BYTES = 256_000
MAX_ATTEMPTS = 64
MAX_EVENTS = 16_384
SPLIT_ERRORS = frozenset({'provider_response_capacity', 'provider_rpc_-32005',
                         'provider_log_block_range_limit', 'pons_log_saturation'})


class CheckpointHints:
    """Planning hints in the existing shared Plane, never canonical cursors."""
    def __init__(self,plane):self.plane=plane
    def get_meta(self,key):return self.plane.checkpoint_read(key)
    def set_meta(self,key,value):self.plane.checkpoint(key,value)


def _choices(value):
    if isinstance(value, str): return [value.lower()]
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return sorted(set(v.lower() for v in value))
    raise BoundaryError('pons_log_filter_shape')


def filter_profile(query):
    """Exact static filter, plus cardinality of dynamic indexed pool IDs.

    No dynamic curve address allowlist is inferred. These profiles describe
    requests; they never remove a contract, topic, pool or candidate.
    """
    topics = query.get('topics')
    if not isinstance(topics, list) or not 1 <= len(topics) <= 4:
        raise BoundaryError('pons_log_filter_shape')
    static = dict(topics0=_choices(topics[0]))
    if 'address' in query: static['address'] = _choices(query['address'])
    counts = []
    for value in topics[1:]:
        counts.append(0 if value is None else len(_choices(value)))
    return static, counts


def load_capability(endpoint, query, *, path=None):
    """Read a small protected runtime capability record. Never probe a provider."""
    path = path or os.environ.get('MM_PONS_LOG_CAPABILITY_FILE')
    if not path: return None
    try:
        p = Path(path)
        if p.stat().st_size > 65_536: return None
        body = json.loads(p.read_text())
        static, counts = filter_profile(query)
        fp = authority.fingerprint(endpoint)
        for row in body.get('comparisons', []):
            if (row.get('schema') == 'pons-log-window-capability-v1'
                    and row.get('provider_fingerprint') == fp
                    and row.get('chain_id') == CHAIN_ID
                    and row.get('entitlement_status') == 'VERIFIED'
                    and row.get('app_id') and row.get('team_id')
                    and row.get('equal') is True
                    and type(row.get('event_count')) is int and row['event_count'] > 0
                    and row.get('canonical_end_hash') and row.get('baseline_digest')
                    and row.get('filter') == static
                    and len(row.get('indexed_filter_counts', [])) == len(counts)
                    and all(type(n) is int and n >= c for n, c in
                            zip(row['indexed_filter_counts'], counts))
                    and type(row.get('range_blocks')) is int
                    and SAFE_BLOCKS < row['range_blocks'] <= MAX_BLOCKS):
                return row
    except (OSError, ValueError, TypeError, KeyError, AttributeError, BoundaryError):
        pass
    return None


class LogWindows:
    def __init__(self, endpoint, query, *, state=None, capability_path=None,
                 clock=time.monotonic,batch_elements=4):
        if type(batch_elements) is not int or not 1<=batch_elements<=50:
            raise BoundaryError('pons_log_batch_bound')
        self.batch_elements=batch_elements
        self.query = {k:v for k,v in query.items() if k not in ('fromBlock', 'toBlock')}
        static, counts = filter_profile(self.query)
        self.support = load_capability(endpoint, self.query, path=capability_path)
        self.ceiling = self.support['range_blocks'] if self.support else SAFE_BLOCKS
        # At most seven cardinality buckets per filter and credential; changing
        # cohorts cannot create an unbounded population of planning records.
        buckets = [(max(1, c)-1).bit_length() for c in counts]
        try: fp = authority.fingerprint(endpoint)
        except ValueError: fp = digest(endpoint)
        self.key = 'pons_log_windows:' + digest([fp, static, buckets])
        self.state = state
        saved = state.get_meta(self.key) if state is not None else None
        self.saved = dict(saved) if isinstance(saved,dict) else {}
        self.support_digest = digest(self.support) if self.support else None
        same_support=self.saved.get('support_digest')==self.support_digest
        if same_support and self.saved.get('range_rejected'): self.ceiling = SAFE_BLOCKS
        if not same_support:self.saved.pop('range_rejected',None)
        try:
            width=int(self.saved.get('width', self.ceiling)) if same_support else self.ceiling
            density=float(self.saved.get('bytes_per_block',0))
            if not math.isfinite(density):raise ValueError()
        except (ValueError,TypeError,OverflowError):
            width,density=self.ceiling,0.
        self.width = max(1, min(self.ceiling,width))
        self.bytes_per_block = max(0.,density)
        self.clock = clock
        self.counts = Counter()
        self.events = 0
        self.splits = 0
        self.largest_success = 0
        self.attempts = 0

    def _save(self, **changes):
        self.saved.update(width=self.width, bytes_per_block=self.bytes_per_block,
                          largest_success=self.largest_success,support_digest=self.support_digest, **changes)
        if self.state is not None: self.state.set_meta(self.key, self.saved)

    def turn_blocks(self):
        width = self.width
        if self.bytes_per_block:
            width = min(width, max(1, int(TARGET_BYTES / self.bytes_per_block)))
        return min(MAX_BLOCKS, 4 * width)

    def spans(self, first, last, *, maximum=4):
        width = self.width
        if self.bytes_per_block:
            width = min(width, max(1, int(TARGET_BYTES / self.bytes_per_block)))
        result = []
        while first <= last and len(result) < maximum:
            end = min(last, first + width - 1)
            result.append((first, end)); first = end + 1
        return result

    def _validate(self, rows, first, last, *, query=None,response_bound=True):
        query=self.query if query is None else query
        if not isinstance(rows, list): raise BoundaryError('pons_log_array_required')
        if response_bound and len(rows) >= PAGE_LOGS: raise BoundaryError('pons_log_saturation')
        identities = {}; ordered = {};blocks={}
        try:
            for row in rows:
                order = tuple(int(row[k], 16) for k in ('blockNumber','transactionIndex','logIndex'))
                topics = row['topics']
                if (row.get('removed') or min(order)<0 or not first <= order[0] <= last or
                        not isinstance(topics, list) or len(topics) < len(query['topics']) or
                        'address' in query and row['address'].lower() not in _choices(query['address'])):
                    raise BoundaryError('pons_log_filter_identity')
                for actual, wanted in zip(topics, query['topics']):
                    if wanted is not None and actual.lower() not in _choices(wanted):
                        raise BoundaryError('pons_log_filter_identity')
                ident = (row['blockHash'], row['transactionHash'], order[2])
                if order[0] in blocks and blocks[order[0]]!=row['blockHash']:
                    raise BoundaryError('pons_log_mixed_block_forks')
                blocks[order[0]]=row['blockHash']
                if (ident in identities and identities[ident] != row or
                        order in ordered and ordered[order] != ident):
                    raise BoundaryError('pons_log_identity_conflict')
                identities[ident] = row; ordered[order] = ident
        except BoundaryError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            raise BoundaryError('pons_log_identity_shape') from None
        return sorted(identities.values(), key=lambda e:tuple(int(e[k],16) for k in
                     ('blockNumber','transactionIndex','logIndex')))

    def _request(self, acquire, spans, *, query=None):
        if self.attempts >= MAX_ATTEMPTS: raise BoundaryError('pons_log_recovery_work_bound')
        self.attempts += 1
        calls = [('eth_getLogs', [dict(self.query if query is None else query,
                 fromBlock=hex(a), toBlock=hex(b))]) for a,b in spans]
        self.counts['logical_elements'] += len(calls)
        self.counts['acquire_attempts'] += 1
        start = self.clock()
        try:
            values = acquire(calls)
            if not isinstance(values, list) or len(values) != len(spans):
                raise BoundaryError('pons_log_batch_shape')
            return values
        finally:
            self.counts['acquire_seconds'] += max(0., self.clock()-start)

    def _split(self, acquire, first, last, error):
        self.counts['failure:'+str(error)] += 1
        if str(error) not in SPLIT_ERRORS:raise error
        if first==last:
            if str(error) in ('pons_log_saturation','provider_response_capacity','provider_rpc_-32005'):
                return self._partition_filter(acquire,first,self.query,error)
            raise error
        self.splits += 1
        if str(error) == 'provider_log_block_range_limit':
            self.ceiling = min(self.ceiling, SAFE_BLOCKS)
            self.width = min(self.width, self.ceiling)
            self._save(range_rejected=True)
            if last-first+1 > SAFE_BLOCKS:
                spans = [(a, min(last,a+SAFE_BLOCKS-1)) for a in range(first,last+1,SAFE_BLOCKS)]
                return [e for i in range(0,len(spans),self.batch_elements) for page in
                        self._batch(acquire,spans[i:i+self.batch_elements]) for e in page]
        self.width = max(1, min(self.width, (last-first+1)//2))
        self._save()
        middle = (first+last)//2
        return [e for page in self._batch(acquire,[(first,middle),(middle+1,last)]) for e in page]

    def _partition_filter(self,acquire,block,query,error):
        """A saturated single block may split an OR set, never drop its members."""
        choices=[(i,_choices(value)) for i,value in enumerate(query['topics'])
                 if isinstance(value,list) and len(_choices(value))>1]
        if not choices:raise error
        index,values=max(choices,key=lambda item:(len(item[1]),item[0]))
        middle=len(values)//2;self.counts['filter_subdivisions']+=1
        rows=[];total_bytes=0
        for part in (values[:middle],values[middle:]):
            topics=list(query['topics']);topics[index]=part;child=dict(query,topics=topics)
            try:
                value=self._request(acquire,[(block,block)],query=child)[0]
                page=self._validate(value,block,block,query=child)
            except BoundaryError as exc:
                if str(exc) not in ('pons_log_saturation','provider_response_capacity','provider_rpc_-32005'):raise
                rows.extend(self._partition_filter(acquire,block,child,exc));continue
            size=len(json.dumps(value,separators=(',',':')).encode());total_bytes+=size
            self.events+=len(page);self.counts['response_array_bytes']+=size
            if self.events>MAX_EVENTS:raise BoundaryError('pons_log_event_work_bound')
            rows.extend(page)
        self.width=1;self.bytes_per_block=max(self.bytes_per_block,total_bytes)
        self._save()
        return self._validate(rows,block,block,query=query,response_bound=False)

    def _page(self, acquire, first, last, value):
        try: rows = self._validate(value, first, last)
        except BoundaryError as error: return self._split(acquire, first, last, error)
        size = len(json.dumps(value, separators=(',',':')).encode())
        span = last-first+1
        # Keep a conservative recent peak. An empty page cannot erase a dense
        # interval's hint and immediately trigger a giant recovery response.
        self.bytes_per_block = max(size/span, self.bytes_per_block*.9)
        self.largest_success = max(self.largest_success, span)
        self.events += len(rows)
        self.counts['response_array_bytes'] += size
        if self.events > MAX_EVENTS: raise BoundaryError('pons_log_event_work_bound')
        if not self.splits and size < TARGET_BYTES//4 and len(rows) < PAGE_LOGS//4:
            self.width = min(self.ceiling, max(self.width, span*2))
        self._save()
        return rows

    def _batch(self, acquire, spans):
        try: values = self._request(acquire, spans)
        except BoundaryError as error:
            if str(error) not in SPLIT_ERRORS: raise
            if len(spans) == 1: return [self._split(acquire,*spans[0],error)]
            # A bounded aggregate response can overflow even when its pages fit.
            # Halve the physical batch before reducing individual block spans.
            if str(error) == 'provider_response_capacity':
                middle = len(spans)//2
                self.counts['batch_subdivisions'] += 1
                return self._batch(acquire,spans[:middle]) + self._batch(acquire,spans[middle:])
            return [self._split(acquire,a,b,error) for a,b in spans]
        return [self._page(acquire,a,b,value) for (a,b),value in zip(spans,values)]

    def read(self, first, last, acquire):
        if not 0 <= first <= last:
            raise BoundaryError('pons_log_turn_bound')
        rows = [];begin=first
        while first <= last:
            spans = self.spans(first,last,maximum=self.batch_elements)
            for page in self._batch(acquire,spans): rows.extend(page)
            first = spans[-1][1]+1
        return self._validate(rows,begin,last,response_bound=False)

    def telemetry(self):
        return dict(self.counts, window_blocks=self.width, ceiling_blocks=self.ceiling,
                    larger_range_verified=self.support is not None, split_intervals=self.splits,
                    events=self.events, largest_success_blocks=self.largest_success,
                    verified_billed_cu=None, checkpoint_authority=False)
