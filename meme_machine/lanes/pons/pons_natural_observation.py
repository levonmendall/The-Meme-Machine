"""One bounded natural Pons V2 observation with unchanged five-second freshness.

Selection is prospective and outcome-blind: after startup, take the first current
CurveBuy/CurveSell whose deployed curve bytecode and factory record authenticate.
The entry observation uses a confirmed block in the existing Finality ledger and
must still satisfy the repository's five-second state gate after all quote inputs
have been read.  No order/reservation/allocation authority exists here.

The observer then waits a fixed 60 seconds, records subsequent authentic curve events,
rechecks canonical block identity, and promotes the original dependency to finalized
only if the finalized frontier has actually reached it with the same hash.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time

from . import BoundaryError, CHAIN_ID
from .abi import calldata, decode_event, topic, words, scalar
from .evidence import Stamp, Store
from .evidence_queue import DeadlineEvidenceQueue
from .finality import Finality
from .identity import load
from .pons import (
    CurveState, authenticate_curve, curve_abi, factory_record, raw_event,
)
from .provider_topology import configured_discovery_rpc, configured_rpc
from .provider_admission import decision_work
from .sequencer_feed import SequencerBlockClock

REPORT=Path(os.environ.get("MM_ROBINHOOD_PONS_NATURAL_REPORT","robinhood-pons-natural-report.json"))
OBSERVE_SECONDS=60
DISCOVERY_SECONDS=90
POLL_SECONDS=1.0
DISCOVERY_MAX_BLOCKS=10
DISCOVERY_FALLBACK_COALESCE_SECONDS=0.75
DISCOVERY_DEDICATED_COALESCE_SECONDS=0.20
RESEARCH_BUY_WEI=10**16
RESEARCH_RECIPIENT="0x1111111111111111111111111111111111111111"
ZERO="0x0000000000000000000000000000000000000000"


class MarketScout:
    """Raw observation projection in the existing Candidate/Evidence Plane.

    This is a journal, not a provider, candidate registry or qualification
    authority. The existing cohort owns the only broad discovery loop. Both
    strategies read the same identities; public prices never enter canonical
    History. A cursor commits only after the entire filtered array is retained.
    """
    def __init__(self, plane):
        from meme_machine.runtime.operating_families import require_active
        require_active('pons')
        from .pons_natural_paper import _event_topic
        self.plane = plane
        self.factory = load('pons_v2_factory')['address'].lower()
        self.manager = load('uniswap_v4_manager')['address'].lower()
        self.launch = _event_topic('pons_v2_factory', 'TokenLaunched')
        self.graduation = _event_topic('pons_v2_factory', 'PoolGraduated')
        self.curve_topics = [topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)'),
                             topic('CurveSell(address,address,uint256,uint256,uint256,uint256)')]
        self.activity_topics = [_event_topic('uniswap_v4_manager', name) for name in
                         ('Swap', 'ModifyLiquidity', 'Donate', 'ProtocolFeeUpdated')]
        with plane.lock:
            plane.db.executescript('''
                CREATE TABLE IF NOT EXISTS pons_scout_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT UNIQUE, kind TEXT,
                    subject TEXT, block INTEGER, body TEXT, hash TEXT, observed REAL);
                CREATE INDEX IF NOT EXISTS pons_scout_subject ON pons_scout_events(kind,subject,block);
                CREATE INDEX IF NOT EXISTS pons_scout_retention ON pons_scout_events(kind,observed);
                CREATE TABLE IF NOT EXISTS pons_scout_pools(
                    token TEXT PRIMARY KEY, pool TEXT, graduation INTEGER,
                    expires REAL, cursor INTEGER, attempt INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS pons_scout_pool_active ON pons_scout_pools(expires,cursor);
            ''')

    def _checkpoint(self, key, value):
        # Called inside our existing Plane transaction, never a nested BEGIN.
        from meme_machine.runtime.journal import canonical
        self.plane.db.execute('INSERT INTO runtime VALUES(?,?) ON CONFLICT(key) '
            'DO UPDATE SET body=excluded.body WHERE runtime.body<>excluded.body',(key,canonical(value)))

    def _retain(self, events, observed):
        from collections import Counter
        from meme_machine.runtime.journal import canonical, digest
        from .pons_historical import event_id, order
        counts=Counter(self.plane.checkpoint_read('pons_scout_event_counts') or {})
        for e in events:
            signature = e['topics'][0].lower()
            if signature in (self.launch, self.graduation):
                if e['address'].lower() != self.factory:
                    continue
                kind = 'launch' if signature == self.launch else 'graduation'
                subject = '0x' + e['topics'][1][-40:]
            elif signature in self.curve_topics:
                kind, subject = 'curve', e['address'].lower()
            else:
                kind, subject = 'pool', e['topics'][1].lower()
            # Variants are retained nominations. Only receipt authentication
            # can resolve a conflicting public body on an otherwise equal id.
            identity = event_id(e) + ':' + digest(e)
            inserted=self.plane.db.execute('INSERT OR IGNORE INTO pons_scout_events '
                '(identity,kind,subject,block,body,hash,observed) VALUES(?,?,?,?,?,?,?)',
                (identity,kind,subject,order(e)[0],canonical(e),digest(e),observed))
            counts[kind]+=inserted.rowcount
        self._checkpoint('pons_scout_event_counts',dict(counts))

    def events(self, kind, *, subject=None, after=0, limit=256):
        from meme_machine.runtime.journal import digest
        query = 'SELECT seq,body,hash,observed FROM pons_scout_events WHERE kind=? AND seq>?'
        args = [kind,after]
        if subject is not None:
            query += ' AND subject=?'; args.append(subject.lower())
        query += ' ORDER BY seq LIMIT ?'; args.append(limit)
        with self.plane.lock:
            rows = self.plane.db.execute(query,args).fetchall()
        result = []
        for seq,body,checksum,observed in rows:
            e = json.loads(body)
            if digest(e) != checksum: raise BoundaryError('scout_journal_corruption')
            result.append((seq,e,observed))
        return result

    def gap(self, first, last, reason, *, kind='market'):
        old=self.plane.checkpoint_read('pons_scout_gap:'+kind)
        if old:first,last=min(first,old['first']),max(last,old['last'])
        self.plane.checkpoint('pons_scout_gap:'+kind,dict(first=first,last=last,
            reason=str(reason),authority='observation_only',complete=False))

    def _clear_gap(self,kind,first,last):
        key='pons_scout_gap:'+kind;old=self.plane.checkpoint_read(key)
        if old is None:return
        if first<=old['first'] and last>=old['last']:old=None
        elif first<=old['first']<=last:old=dict(old,first=last+1)
        elif first<=old['last']<=last:old=dict(old,last=first-1)
        self._checkpoint(key,old)

    def _pages(self,rpc,queries):
        """Public reads stay proven; canonical fallback can use verified windows."""
        from .log_windows import LogWindows,CheckpointHints
        endpoint=getattr(rpc,'endpoint',None)
        if getattr(rpc,'canonical_authority',False) and endpoint and queries:
            windows=LogWindows(endpoint,queries[0],state=CheckpointHints(self.plane))
            if windows.support:
                # Callers supply contiguous pages of one complete filter. Never
                # infer a curve address list or remove a pool/topic here.
                base={k:v for k,v in queries[0].items() if k not in ('fromBlock','toBlock')}
                cursor=int(queries[0]['fromBlock'],16)
                for query in queries:
                    if ({k:v for k,v in query.items() if k not in ('fromBlock','toBlock')}!=base
                            or int(query['fromBlock'],16)!=cursor):
                        raise BoundaryError('scout_adaptive_page_identity')
                    cursor=int(query['toBlock'],16)+1
                rows=windows.read(int(queries[0]['fromBlock'],16),cursor-1,
                    lambda calls:rpc.batch(calls,scope='pons_scout_discovery'))
                return [rows]
        try:
            pages=rpc.batch([('eth_getLogs',[q]) for q in queries],scope='pons_scout_discovery')
        except BoundaryError as exc:
            if str(exc)!='provider_response_capacity':raise
            return [self._logs(rpc,q) for q in queries]
        if not isinstance(pages,list) or len(pages)!=len(queries):
            raise BoundaryError('scout_log_batch_shape')
        return [self._logs(rpc,q,provided=page) for q,page in zip(queries,pages)]

    def _logs(self, rpc, query, **prefetched):
        """Split saturated responses; a single-block overflow stays an open gap."""
        first,last = int(query['fromBlock'],16),int(query['toBlock'],16)
        try:
            rows = prefetched['provided'] if 'provided' in prefetched else rpc.call(
                'eth_getLogs',[query],scope='pons_scout_discovery')
            if not isinstance(rows,list): raise BoundaryError('scout_log_array_required')
            if len(rows) >= 1000: raise BoundaryError('scout_response_saturation')
        except BoundaryError as exc:
            if str(exc) not in ('scout_response_saturation','provider_response_capacity',
                    'provider_log_block_range_limit','provider_rpc_-32005') or first == last:
                if query.get('address')!=self.manager:self.gap(first,last,str(exc))
                raise
            mid = (first+last)//2
            return (self._logs(rpc,dict(query,toBlock=hex(mid))) +
                    self._logs(rpc,dict(query,fromBlock=hex(mid+1))))
        unique = {}
        from .pons_historical import event_id, order
        for e in rows:
            if (e.get('removed') or not first <= order(e)[0] <= last or
                    not e.get('topics') or e['topics'][0].lower() not in query['topics'][0] or
                    query.get('address') and e.get('address','').lower() != query['address'] or
                    len(query['topics']) > 1 and e['topics'][1].lower() not in query['topics'][1]):
                raise BoundaryError('scout_log_filter_identity')
            ident = event_id(e)
            if ident in unique and unique[ident] != e: raise BoundaryError('scout_log_conflict')
            unique[ident] = e
        return sorted(unique.values(),key=order)

    @decision_work(3)
    def read_market(self, rpc, first, last, *, nominate=None):
        """One topic-OR query serves launches, graduations, buys and sells.

        Curve addresses are created dynamically; factory signatures are retained
        only at the pinned factory. No unrelated V4/Ramses pool is scanned.
        """
        from .pons_historical import order
        rows = []
        try:
            expected=self.plane.checkpoint_read('pons_scout_market_boundary')
            calls=[('eth_getBlockByNumber',[hex(last),False])]
            if expected:calls.append(('eth_getBlockByNumber',[hex(expected['block']),False]))
            headers=rpc.batch(calls,scope='pons_scout_discovery')
            if len(headers)!=len(calls) or headers[0].get('number')!=hex(last):
                raise BoundaryError('scout_public_boundary_identity')
            if expected and headers[-1].get('hash')!=expected['hash']:
                enrollment=self.plane.checkpoint_read('pons_scout_enrollment')
                rewind=enrollment['first']-1
                with self.plane.transaction():
                    self._checkpoint('pons_scout_market_cursor',rewind)
                    self._checkpoint('pons_scout_market_boundary',None)
                    self._checkpoint('pons_scout_reorganizations',
                        (self.plane.checkpoint_read('pons_scout_reorganizations') or 0)+1)
                    self.plane.db.execute('UPDATE pons_scout_pools SET cursor=graduation-1')
                raise BoundaryError('scout_public_reorg')
            queries=[dict(fromBlock=hex(start),toBlock=hex(min(last,start+9)),
                topics=[[self.launch,self.graduation,*self.curve_topics]]) for start in range(first,last+1,10)]
            for offset in range(0,len(queries),4):
                for page in self._pages(rpc,queries[offset:offset+4]):
                    observed = self.plane.clock()
                    with self.plane.transaction(): self._retain(page,observed)
                    # Current's clock starts before deferred pool scouting.
                    if nominate:
                        for e in page:
                            if e['topics'][0].lower() in self.curve_topics: nominate(e,observed)
                    rows.extend(page)
            with self.plane.transaction():
                if self.plane.checkpoint_read('pons_scout_enrollment') is None:
                    self._checkpoint('pons_scout_enrollment',dict(first=first,
                        observed_at=self.plane.clock(),pre_enrollment_coverage='UNOBSERVED'))
                self._checkpoint('pons_scout_market_cursor',last)
                self._checkpoint('pons_scout_market_boundary',dict(block=last,hash=headers[0]['hash']))
                self._clear_gap('market',first,last)
        except (BoundaryError,ValueError) as exc:
            if str(exc)=='scout_public_reorg':first=self.plane.checkpoint_read('pons_scout_market_cursor')+1
            self.gap(first,last,str(exc)); raise
        return [e for e in sorted(rows,key=order) if e['topics'][0].lower() in self.curve_topics]

    def register_pool(self, row):
        grad = row['graduation']
        with self.plane.transaction():
            old = self.plane.db.execute('SELECT pool,graduation FROM pons_scout_pools WHERE token=?',
                (row['id'],)).fetchone()
            identity = (grad['transition']['market'],grad['block'])
            if old and tuple(old) != identity:
                # The native history has already proved the old anchor orphaned.
                self.plane.db.execute('DELETE FROM pons_scout_pools WHERE token=?',(row['id'],))
            self.plane.db.execute('INSERT OR IGNORE INTO pons_scout_pools '
                '(token,pool,graduation,expires,cursor) VALUES(?,?,?,?,?)',
                (row['id'],*identity,grad['at']+7*86400,grad['block']-1))

    def maintain(self):
        """Retain identities forever; compact raw events after their horizon.

        Pending nominations and unknown pool relationships are never pruned.
        Native funded positions own independent canonical histories. A small
        maintenance turn cannot monopolize discovery or provider capacity.
        """
        from meme_machine.runtime.journal import digest
        now=self.plane.clock()
        with self.plane.transaction():
            previous=self.plane.checkpoint_read('pons_scout_retention') or dict(at=0,count=0,hash=None)
            if now-previous['at']<60:return
            rows=self.plane.db.execute("SELECT seq,kind,body,hash FROM pons_scout_events WHERE observed<? "
                "AND (kind='curve' OR kind='pool' AND subject IN "
                "(SELECT pool FROM pons_scout_pools WHERE expires<?)) ORDER BY observed LIMIT 4096",
                (now-8*86400,now-86400)).fetchall()
            counts=self.plane.checkpoint_read('pons_scout_event_counts') or {}
            for seq,kind,body,checksum in rows:
                if digest(json.loads(body))!=checksum:raise BoundaryError('scout_journal_corruption')
                self.plane.db.execute('DELETE FROM pons_scout_events WHERE seq=?',(seq,))
                counts[kind]-=1
            self._checkpoint('pons_scout_event_counts',counts)
            self._checkpoint('pons_scout_retention',dict(at=now,count=previous['count']+len(rows),
                hash=digest([previous['hash'],[(r['seq'],r['hash']) for r in rows]]),
                basis='raw public observations outside original candidate and recovery horizons',
                qualification_authority=False))

    @decision_work(3)
    def read_pools(self, rpc, top):
        """One fair bounded pool cohort per turn; no population count limit."""
        with self.plane.transaction():
            now=self.plane.clock()
            oldest=self.plane.db.execute('SELECT cursor FROM pons_scout_pools WHERE cursor<? AND expires>=? '
                'ORDER BY attempt,cursor,token LIMIT 1',(top,now)).fetchone()
            if oldest is None:return
            first_cursor=oldest['cursor']
            # Claim only overlapping checkpoints. An old pool's recovery may
            # not consume a newer pool's turn without advancing its coverage.
            rows=self.plane.db.execute('SELECT * FROM pons_scout_pools WHERE cursor<? AND expires>=? '
                'AND cursor>=? AND cursor<? ORDER BY attempt,cursor,token LIMIT 64',
                (top,now,first_cursor,first_cursor+40)).fetchall()
            seq = (self.plane.checkpoint_read('pons_scout_pool_turn') or 0)+1
            self._checkpoint('pons_scout_pool_turn',seq)
            self.plane.db.executemany('UPDATE pons_scout_pools SET attempt=? WHERE token=?',
                [(seq,r['token']) for r in rows])
        first = min(r['cursor'] for r in rows)+1; end = min(top,first+39)
        active = [r for r in rows if r['cursor'] < end]
        ids = sorted({r['pool'] for r in active})
        events = []
        try:
            queries=[dict(address=self.manager,fromBlock=hex(start),toBlock=hex(min(end,start+9)),
                topics=[self.activity_topics,ids]) for start in range(first,end+1,10)]
            for page in self._pages(rpc,queries):events.extend(page)
            with self.plane.transaction():
                self._retain(events,self.plane.clock())
                self.plane.db.executemany('UPDATE pons_scout_pools SET cursor=? WHERE token=?',
                    [(end,r['token']) for r in active])
                for r in active:self._clear_gap('pools:'+r['pool'],r['cursor']+1,end)
        except (BoundaryError,ValueError) as exc:
            for r in active:self.gap(r['cursor']+1,end,str(exc),kind='pools:'+r['pool'])
            raise

    def signal(self, pool):
        with self.plane.lock:
            return self.plane.db.execute("SELECT COALESCE(MAX(seq),0) FROM pons_scout_events "
                "WHERE kind='pool' AND subject=?",(pool,)).fetchone()[0]

    def activity(self,row):
        """Bounded provisional momentum; UNKNOWN schedules canonical recovery."""
        from .abi import decode_event
        from .pons_survivor_runtime import price_index
        from .protocols import PoolKey
        pool=row['graduation']['transition']['market']
        with self.plane.lock:
            checkpoint=self.plane.db.execute('SELECT cursor FROM pons_scout_pools WHERE token=?',(row['id'],)).fetchone()
            raw=self.plane.db.execute("SELECT body FROM pons_scout_events WHERE kind='pool' AND subject=? "
                "ORDER BY block DESC,seq DESC LIMIT 64",(pool,)).fetchall()
        complete=(checkpoint is not None and checkpoint[0] >=
            (self.plane.checkpoint_read('pons_scout_market_cursor') or 0) and
            not self.plane.checkpoint_read('pons_scout_gap:pools:'+pool) and
            not self.plane.checkpoint_read('pons_scout_gap:market'))
        prices=[]
        key=PoolKey(**row['graduation']['key'])
        for body, in raw:
            event=json.loads(body)
            if event['topics'][0]==self.activity_topics[0]:
                args=decode_event(load('uniswap_v4_manager')['abi'],event)['args']
                prices.append(price_index(args['sqrtPriceX96'],row['id'],key))
        anchor=price_index(row['graduation']['transition']['initialization_sqrt_price_x96'],row['id'],key)
        return dict(authority='observation_only',complete=complete,activity_samples=len(raw),
            swap_samples=len(prices),latest_price_index=prices[0] if prices else anchor,
            high_price_index=max(prices,default=anchor),graduation_price_index=anchor,
            improving=bool(prices and prices[0]>anchor),buyer_independence='UNKNOWN')

    def snapshot(self):
        with self.plane.lock:
            counts = self.plane.checkpoint_read('pons_scout_event_counts') or {}
            pools = self.plane.db.execute('SELECT COUNT(*) FROM pons_scout_pools').fetchone()[0]
            frontier = self.plane.db.execute('SELECT MIN(cursor) FROM pons_scout_pools WHERE expires>=?',
                (self.plane.clock(),)).fetchone()[0]
            gaps=[json.loads(r[0]) for r in self.plane.db.execute("SELECT body FROM runtime WHERE "
                "key LIKE 'pons_scout_gap:pools:%' AND body<>'null'")]
        return dict(authority='observation_only',events=counts,retained_pool_identities=pools,
            market_cursor=self.plane.checkpoint_read('pons_scout_market_cursor'),
            market_gap=self.plane.checkpoint_read('pons_scout_gap:market'),
            pool_gap=gaps or None,
            minimum_active_pool_cursor=frontier,
            pre_enrollment_coverage='UNOBSERVED',candidate_count_limit=None)


def _one_word(raw,typ="uint256"):
    data=words(raw)
    if len(data)!=1:
        raise BoundaryError("natural_call_shape")
    return scalar(typ,data[0])


def _two_uints(raw):
    data=words(raw)
    if len(data)!=2:
        raise BoundaryError("natural_reserve_shape")
    return tuple(scalar("uint256",x) for x in data)


def _call(rpc,address,sig,args,block,report):
    raw=rpc.call(
        "eth_call",
        [dict(to=address,data=calldata(sig,*args)),hex(block)],
        scope="pons_natural",
    )
    report["reads"].append(dict(
        address=address,signature=sig,args=list(args),block=block,
        value=raw,observed_at=time.time(),
    ))
    return raw


def _latest_header(rpc):
    return rpc.call("eth_getBlockByNumber",["latest",False],scope="pons_natural")

def _next_discovery_end(feed,cursor,discovery,*,timeout):
    coalesce=(
        DISCOVERY_FALLBACK_COALESCE_SECONDS
        if getattr(discovery,"primary_fallback",False)
        else DISCOVERY_DEDICATED_COALESCE_SECONDS
    )
    return feed.wait_for_range_after(
        cursor,timeout=timeout,max_blocks=DISCOVERY_MAX_BLOCKS,
        coalesce_seconds=coalesce,
    )


def _current_curve_events(rpc,start,end):
    if end<start:
        return []
    rows=[]
    signatures=[
        topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)"),
        topic("CurveSell(address,address,uint256,uint256,uint256,uint256)"),
    ]
    # Provider already proved small-range log reads. Never widen past 10 blocks.
    for first in range(start,end+1,10):
        rows.extend(rpc.call("eth_getLogs",[dict(
            fromBlock=hex(first),toBlock=hex(min(end,first+9)),
            topics=[signatures],
        )],scope="pons_natural"))
        if len(rows)>1000:
            raise BoundaryError("natural_event_capacity")
    rows.sort(key=lambda e:(int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)))
    return rows


def _curve_state(rpc,curve,block,auth,report):
    quote_reserve,token_reserve=_two_uints(_call(rpc,curve,"getReserves()",(),block,report))
    real_quote=_one_word(_call(rpc,curve,"realQuoteReserve()",(),block,report))
    reserved=_one_word(_call(rpc,curve,"reservedTokens()",(),block,report))
    graduated=_one_word(_call(rpc,curve,"graduated()",(),block,report),"bool")
    header=rpc.call("eth_getBlockByNumber",[hex(block),False],scope="pons_natural")
    timestamp=int(header["timestamp"],16)
    # Sell arithmetic does not use snipe parameters.  Current buy execution is quoted
    # by eth_call against the actual deployed contract below rather than recreating
    # the snipe schedule from stale local inputs.
    return CurveState(
        quote_reserve=quote_reserve,token_reserve=token_reserve,real_quote=real_quote,
        reserved_tokens=reserved,fee_bps=int(auth["immutables"]["feeBps"]),
        creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),graduated=bool(graduated),
        launched_at=timestamp,snipe_start_bps=0,snipe_seconds=1,timestamp=timestamp,
    ),header


def _quote_native_buy(rpc,curve,block,record,state,report):
    if record["pairToken"].lower()!=ZERO:
        raise BoundaryError("natural_non_native_quote_not_supported")
    current_snipe=_one_word(_call(
        rpc,curve,"currentSnipeTaxBps(address)",(RESEARCH_RECIPIENT,),block,report
    ))
    quote=state.buy_with_snipe(RESEARCH_BUY_WEI,current_snipe)
    return dict(
        quote_in=RESEARCH_BUY_WEI,tokens_out=quote["tokens_out"],
        spent=quote["spent"],refund=quote["refund"],fee=quote["fee"],
        creator_tax=quote["creator_tax"],snipe_tax=quote["snipe_tax"],
        ready_to_graduate=quote["ready_to_graduate"],
        current_snipe_bps=current_snipe,recipient=RESEARCH_RECIPIENT,
        execution="source_verified_arithmetic_plus_onchain_current_snipe",
    )


def _authenticate_candidate(
    rpc,event,report,*,evidence_observed_at=None,
    evidence_observed_monotonic=None,max_evidence_latency_seconds=5,
):
    """Authenticate one current candidate in exactly two HTTP batch transports.

    Legacy callers retain chain-timestamp freshness. Selective-continuation callers
    may supply the instant the log was first observed; for those callers the hard
    freshness gate measures local evidence-acquisition latency instead of chain clock
    lag. Chain timestamp lag remains explicit telemetry.
    """
    started=time.time()
    started_monotonic=time.monotonic()
    latency_mode=evidence_observed_monotonic is not None
    if latency_mode:
        if evidence_observed_at is None:
            raise BoundaryError("missing_evidence_observation_wall_time")
        if float(evidence_observed_monotonic)>started_monotonic:
            raise BoundaryError("future_evidence_observation")
        if not 0<float(max_evidence_latency_seconds)<=10:
            raise BoundaryError("invalid_evidence_latency_limit")
        if started_monotonic-float(evidence_observed_monotonic)>float(max_evidence_latency_seconds):
            raise BoundaryError("stale_evidence_acquisition")
    block=int(event["blockNumber"],16)
    block_hex=hex(block)
    curve=event["address"].lower()
    tx=event["transactionHash"]

    first_calls=[
        ("eth_chainId",[]),
        ("eth_getBlockByNumber",[block_hex,False]),
        ("eth_getTransactionReceipt",[tx]),
        ("eth_call",[dict(to=curve,data=calldata("token()")),block_hex]),
        ("eth_getCode",[curve,block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("getReserves()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("realQuoteReserve()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("reservedTokens()")),block_hex]),
        ("eth_call",[dict(to=curve,data=calldata("graduated()")),block_hex]),
        ("eth_call",[dict(
            to=curve,
            data=calldata("currentSnipeTaxBps(address)",RESEARCH_RECIPIENT),
        ),block_hex]),
        ("eth_gasPrice",[]),
    ]
    factory=load("pons_v2_factory")["address"].lower()
    hint=rpc.factory_token_hint(curve) if hasattr(rpc,'factory_token_hint') else None
    if hint:
        first_calls.append(('eth_call',[dict(to=factory,data=calldata('getLaunchedToken(address)',hint)),block_hex]))
    auth_batch_started=time.monotonic()
    first=rpc.batch(first_calls,scope="pons_natural")
    report.setdefault("timing",{})["header_receipt_state_cost_shared_batch_seconds"]=time.monotonic()-auth_batch_started
    (chain_raw,header,receipt,token_raw,code,reserves_raw,real_raw,reserved_raw,
     graduated_raw,snipe_raw,gas_raw)=first[:11]
    if int(chain_raw,16)!=CHAIN_ID:
        raise BoundaryError("wrong_chain")
    if (
        header["hash"]!=event["blockHash"]
        or header["number"]!=event["blockNumber"]
        or receipt["transactionHash"]!=tx
        or receipt["blockHash"]!=event["blockHash"]
    ):
        raise BoundaryError("candidate_identity_disagreement")

    observed=int(time.time())
    event_at=int(header["timestamp"],16)
    if latency_mode:
        first_batch_latency=time.monotonic()-float(evidence_observed_monotonic)
        if first_batch_latency<0 or first_batch_latency>float(max_evidence_latency_seconds):
            raise BoundaryError("stale_evidence_acquisition")
    elif observed-event_at>5:
        raise BoundaryError("stale_state")
    decoded=raw_event(
        curve_abi(),event,address=curve,receipt=receipt,header=header,
        observed_at=observed,confirmation="confirmed",
    )
    token=_one_word(token_raw,"address")
    factory=load("pons_v2_factory")["address"].lower()

    second_calls=[
        ("eth_call",[dict(
            to=factory,data=calldata("getLaunchedToken(address)",token)
        ),block_hex]),
    ]
    factory_started=time.monotonic()
    if hint and hint.lower()==token.lower():
        second=[first[11]]
        report['timing']['factory_record_in_first_batch']=True
    else:
        second=rpc.batch(second_calls,scope="pons_natural")
        report['timing']['factory_record_in_first_batch']=False
    report.setdefault("timing",{})["launch_metadata_seconds"]=time.monotonic()-factory_started
    record=factory_record(second[0],"pons_v2_factory")
    auth=authenticate_curve(curve,code,factory_record=record)
    if hasattr(rpc,'remember_compiled_identity'):
        rpc.remember_compiled_identity(curve,token,code,block,header,auth)
    # Authenticated identity can shape a later batch even when this observation
    # fails structural/current-state gates. Every later factory/state read is new.
    if hasattr(rpc,'remember_factory_identity'):
        rpc.remember_factory_identity(curve,token)

    quote_reserve,token_reserve=_two_uints(reserves_raw)
    state=CurveState(
        quote_reserve=quote_reserve,token_reserve=token_reserve,
        real_quote=_one_word(real_raw),reserved_tokens=_one_word(reserved_raw),
        fee_bps=int(auth["immutables"]["feeBps"]),
        creator_tax_bps=int(auth["immutables"]["creatorTaxBps"]),
        graduated=bool(_one_word(graduated_raw,"bool")),
        launched_at=event_at,snipe_start_bps=0,snipe_seconds=1,timestamp=event_at,
    )
    current_snipe=_one_word(snipe_raw)
    maximum=9900-state.fee_bps-state.creator_tax_bps
    def authenticated_rejection(boundary):
        # These reads already passed header/receipt/log, curve bytecode and
        # factory authentication. Preserve the narrow proof when quote creation
        # stops, so the selective strategy can classify an existing early veto.
        # This does not authorize a quote or relax this primitive's boundaries.
        age=(time.monotonic()-float(evidence_observed_monotonic) if latency_mode
             else time.time()-event_at)
        report['authenticated_rejection']=dict(
            boundary=boundary,curve=curve,token=token,block=block,
            block_hash=header['hash'],source_transaction=tx,
            source_log_index=int(event['logIndex'],16),
            pair_token=record['pairToken'].lower(),
            current_snipe_bps=current_snipe,fee_bps=state.fee_bps,
            creator_tax_bps=state.creator_tax_bps,
            decision_age_seconds=age,authentication_complete=True,
        )
    if not 0<=current_snipe<=maximum:
        authenticated_rejection('invalid_current_snipe_bps')
        raise BoundaryError("invalid_current_snipe_bps")
    if record["pairToken"].lower()!=ZERO:
        authenticated_rejection('natural_non_native_quote_not_supported')
        raise BoundaryError("natural_non_native_quote_not_supported")
    quote=state.buy_with_snipe(RESEARCH_BUY_WEI,current_snipe)
    quote=dict(
        quote_in=RESEARCH_BUY_WEI,tokens_out=quote["tokens_out"],
        spent=quote["spent"],refund=quote["refund"],fee=quote["fee"],
        creator_tax=quote["creator_tax"],snipe_tax=quote["snipe_tax"],
        ready_to_graduate=quote["ready_to_graduate"],
        current_snipe_bps=current_snipe,recipient=RESEARCH_RECIPIENT,
        execution="source_verified_arithmetic_plus_onchain_current_snipe",
    )
    gas_units=int(receipt.get("gasUsed","0x0"),16)
    gas_price=int(gas_raw,16)
    if not 21_000<=gas_units<=5_000_000:
        raise BoundaryError("sample_gas_units_bounds")
    if gas_price<=0:
        raise BoundaryError("sample_invalid_gas_price")

    quote_at=int(time.time())
    quote_monotonic=time.monotonic()
    stamp=Stamp(
        CHAIN_ID,block,header["hash"],event_at,observed,"confirmed","natural",
    )
    if latency_mode:
        evidence_latency=quote_monotonic-float(evidence_observed_monotonic)
        if evidence_latency<0 or evidence_latency>float(max_evidence_latency_seconds):
            raise BoundaryError("stale_evidence_acquisition")
        chain_lag=float(evidence_observed_at)-float(event_at)
    else:
        evidence_latency=float(quote_at-event_at)
        chain_lag=float(observed-event_at)
        if quote_at-event_at>5:
            raise BoundaryError("stale_state")
    report.setdefault("reads",[]).extend([
        dict(kind="candidate_batch",round=1,block=block,
             methods=[method for method,_ in first_calls],observed_at=observed),
        dict(kind="factory_record",round=1 if report['timing']['factory_record_in_first_batch'] else 2,block=block,
             methods=[] if report['timing']['factory_record_in_first_batch'] else [method for method,_ in second_calls],observed_at=quote_at),
    ])
    return dict(
        curve=curve,token=token,block=block,header=header,receipt=receipt,
        source_event=event,decoded_event=decoded,record=record,auth=auth,
        state=state,quote=quote,stamp=stamp,quote_at=quote_at,
        freshness_seconds=evidence_latency,
        evidence_observed_at=(
            float(evidence_observed_at) if latency_mode else None
        ),
        evidence_acquisition_latency_seconds=evidence_latency,
        chain_timestamp_lag_seconds=chain_lag,
        current_snipe_bps=current_snipe,
        roundtrip_gas_wei=2*gas_units*gas_price,
        gas_meta=dict(units_per_side=gas_units,gas_price=gas_price),
        auth_latency_ms=round((time.time()-started)*1000,2),
        auth_transport_rounds=1 if report['timing']['factory_record_in_first_batch'] else 2,
    )


def _chunks(rows,size):
    for i in range(0,len(rows),size):
        yield rows[i:i+size]


def _authenticate_followup_events(rpc,candidate,events):
    """Authenticate fixed follow-up events with bounded immutable batch reads."""
    selected=[
        event for event in events
        if event["address"].lower()==candidate["curve"]
    ]
    if len(selected)>200:
        raise BoundaryError("natural_followup_capacity")
    if not selected:
        return []

    block_hashes=list(dict.fromkeys(event["blockHash"] for event in selected))
    headers={}
    for group in _chunks(block_hashes,50):
        values=rpc.batch(
            [("eth_getBlockByHash",[block_hash,False]) for block_hash in group],
            scope="pons_natural",
        )
        for block_hash,header in zip(group,values):
            if header["hash"]!=block_hash:
                raise BoundaryError("followup_block_hash_disagreement")
            headers[block_hash]=header

    tx_rows=list(dict.fromkeys(
        (event["transactionHash"],event["blockHash"]) for event in selected
    ))
    receipts={}
    for group in _chunks(tx_rows,50):
        values=rpc.batch(
            [("eth_getTransactionReceipt",[tx]) for tx,_ in group],
            scope="pons_natural",
        )
        for (tx,block_hash),receipt in zip(group,values):
            if (
                receipt["transactionHash"]!=tx
                or receipt["blockHash"]!=block_hash
            ):
                raise BoundaryError("receipt_block_disagreement")
            receipts[(tx,block_hash)]=receipt

    observed=int(time.time())
    authentic=[]
    for event in selected:
        block_hash=event["blockHash"]
        authentic.append(raw_event(
            curve_abi(),event,address=candidate["curve"],
            receipt=receipts[(event["transactionHash"],block_hash)],
            header=headers[block_hash],observed_at=observed,
            confirmation="confirmed",
        ))
    return authentic


def _final_mark(rpc,candidate,block,report):
    try:
        state,_=_curve_state(rpc,candidate["curve"],block,candidate["auth"],report)
        if state.graduated:
            return dict(available=False,reason="graduated_requires_v4_mark")
        sell=state.sell(candidate["quote"]["tokens_out"])
        return dict(
            available=True,quote_out=sell["quote_out"],gross_quote=sell["gross_quote"],
            fee=sell["fee"],creator_tax=sell["creator_tax"],
            gross_return_bps=(sell["quote_out"]-candidate["quote"]["quote_in"])*10000
                             // candidate["quote"]["quote_in"],
            gas_unmodeled=True,after_cost_return=None,
        )
    except BoundaryError as exc:
        return dict(available=False,reason=str(exc),after_cost_return=None)


def run(endpoint):
    rpc=configured_rpc(endpoint,limit=180,per_scope=170,retries=0)
    discovery=configured_discovery_rpc(
        endpoint,limit=180,per_scope=170,retries=0
    )
    feed=SequencerBlockClock()
    report=dict(
        kind="natural_pons_v2_bounded_observation",
        research_only=True,allocation_authority=False,paper_orders=0,
        selection_rule="first_current_authenticated_pons_v2_curve_trade_after_start",
        outcome_used_for_selection=False,freshness_gate_seconds=5,
        discovery_seconds=DISCOVERY_SECONDS,followup_seconds=OBSERVE_SECONDS,
        research_buy_wei=RESEARCH_BUY_WEI,reads=[],events=[],started_at=time.time(),
        discovery_mode="sequencer_range_batch_plus_deadline_queue_v3",
    )
    candidate=None
    outcome_rpc=None
    evidence_queue=DeadlineEvidenceQueue(limit=256,nominal_deadline_seconds=5.0)
    discovery_ranges=0
    discovered_events=0
    try:
        rpc.verify_chain()
        discovery.verify_chain()
        feed.connect()
        cursor=feed.wait_for_after(-1,timeout=5.0)
        if cursor is None:
            raise BoundaryError("sequencer_discovery_start_timeout")
        start_header=discovery.call(
            "eth_getBlockByNumber",[hex(cursor),False],scope="pons_natural"
        )
        if int(start_header["number"],16)!=cursor:
            raise BoundaryError("sequencer_discovery_block_disagreement")
        report["start_block"]=cursor
        deadline=time.monotonic()+DISCOVERY_SECONDS
        attempted_curves=set()

        while time.monotonic()<deadline and candidate is None:
            end=_next_discovery_end(
                feed,cursor,discovery,timeout=POLL_SECONDS
            )
            if end is None:
                continue
            start=cursor+1
            if end>=start:
                fresh=_current_curve_events(discovery,start,end)
                discovery_ranges+=1
                discovered_events+=len(fresh)
                cursor=end
                now=time.time()
                for event in fresh:
                    curve=event.get("address","").lower()
                    if curve in attempted_curves:
                        continue
                    attempted_curves.add(curve)
                    evidence_queue.enqueue(event,now=now)

            while candidate is None:
                scheduled=evidence_queue.pop(
                    now=time.time(),minimum_remaining_seconds=1.0
                )
                if scheduled is None:
                    break
                event=scheduled["event"]
                try:
                    item=_authenticate_candidate(rpc,event,report)
                    with tempfile.TemporaryDirectory() as td:
                        store=Store(td+"/natural.sqlite",max_records=128)
                        ledger=Finality(store,scope="pons-natural",max_blocks=16)
                        ledger.observe(item["stamp"],item["header"]["parentHash"])
                        item["stamp"].check(item["quote_at"],5,finality_ledger=ledger)
                        dependency="candidate:"+item["token"]+":"+item["source_event"]["transactionHash"]
                        ledger.bind(dependency,[item["stamp"]],asof=item["quote_at"])
                        item["dependency_status_at_quote"]=ledger.check_dependency(dependency)
                        store.close()
                    candidate=item
                except BoundaryError as exc:
                    report.setdefault("candidate_rejections",[]).append(dict(
                        address=event.get("address"),block=event.get("blockNumber"),
                        reason=str(exc),
                    ))
                    if len(report["candidate_rejections"])>50:
                        raise BoundaryError("natural_rejection_capacity")

        report["sequencer_discovery"]=feed.status()
        report["discovery_ranges"]=discovery_ranges
        report["discovered_events"]=discovered_events
        report["evidence_queue"]=evidence_queue.telemetry()
        feed.close()
        if candidate is None:
            raise BoundaryError("no_current_authenticated_pons_candidate")

        report["candidate"]={
            key:value for key,value in candidate.items()
            if key not in ("stamp","state")
        }
        report["candidate"]["stamp"]=asdict(candidate["stamp"])
        report["candidate"]["state"]=asdict(candidate["state"])

        # Outcome clock starts only after the candidate/quote is frozen.
        _stop_sleep(OBSERVE_SECONDS)
        final_header=_latest_header(discovery)
        final_block=int(final_header["number"],16)
        follow=_current_curve_events(discovery,candidate["block"],final_block)

        # Outcome reconstruction is after the candidate/quote is frozen. Use a new
        # bounded logical session on the same authoritative provider and shared 2-RPS
        # physical pacer so outcome history cannot consume the entry evidence budget.
        outcome_rpc=configured_rpc(endpoint,limit=200,per_scope=200,retries=0)
        authentic=_authenticate_followup_events(outcome_rpc,candidate,follow)
        report["events"]=authentic

        # Re-fetch the original height. A replacement block invalidates the research
        # observation rather than being silently substituted.
        canonical=outcome_rpc.call(
            "eth_getBlockByNumber",[hex(candidate["block"]),False],scope="pons_natural"
        )
        now=int(time.time())
        if canonical["hash"]!=candidate["stamp"].block_hash:
            report["dependency_status"]="invalidated"
            raise BoundaryError("confirmed_candidate_reorged")

        finalized=outcome_rpc.call(
            "eth_getBlockByNumber",["finalized",False],scope="pons_natural"
        )
        finalized_number=int(finalized["number"],16)
        report["finalized_frontier"]={
            k:finalized[k] for k in ("number","hash","timestamp","parentHash")
        }
        report["dependency_status"]=(
            "finalized" if finalized_number>=candidate["block"] else "confirmed"
        )
        report["finalization_preserves_original_observed_at"]=candidate["stamp"].observed_at
        report["outcome"]={
            "seconds":OBSERVE_SECONDS,
            "end_block":final_block,
            "authenticated_trade_events":len(authentic),
            "mark":_final_mark(outcome_rpc,candidate,final_block,report),
            "graduated_during_followup":any(
                row["decoded"]["name"]=="CurveCompleted" for row in authentic
            ),
            "after_cost_profitability_established":False,
        }
    except BoundaryError as exc:
        report["boundary"]=str(exc)
    finally:
        feed.close()
    report["provider"]=rpc.telemetry()
    report["outcome_provider"]=(
        None if outcome_rpc is None else outcome_rpc.telemetry()
    )
    report["discovery_provider"]=discovery.telemetry()
    report.setdefault("sequencer_discovery",feed.status())
    report.setdefault("discovery_ranges",discovery_ranges)
    report.setdefault("discovered_events",discovered_events)
    report.setdefault("evidence_queue",evidence_queue.telemetry())
    report["ended_at"]=time.time()
    return report


if __name__=="__main__":
    result=run(os.environ.get("MM_ROBINHOOD_READ_RPC_URL",""))
    raw=json.dumps(result,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>2_000_000:
        raise BoundaryError("natural_report_capacity")
    REPORT.write_bytes(raw)
    print(json.dumps(dict(
        boundary=result.get("boundary"),
        candidate=(result.get("candidate") or {}).get("token"),
        freshness=(result.get("candidate") or {}).get("freshness_seconds"),
        dependency_status=result.get("dependency_status"),
        outcome=result.get("outcome"),
        provider=result["provider"],
    ),sort_keys=True))


def _stop_sleep(seconds):
    from meme_machine.runtime.stop import sleep
    return sleep(seconds,sleeper=time.sleep)
