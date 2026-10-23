"""Candidate-scoped acquisition and durable delivery accounting.

Discovery locators are never economic interval proofs. Canonical content remains
shared by the three lanes; completeness belongs to an address and its requested
interval. Archive work advances only in the transaction committing that content.
No capital, portfolio, signing or transaction-submission interface exists here.
"""
from .runtime.operation_costs import measured

from dataclasses import dataclass,replace
import hashlib
import json
import time
import zlib
from functools import lru_cache
from .solana_evidence_plane import FinalizedRecord,IntervalProof,EvidenceUnavailable,EvidenceConflict,canonical,digest,decode_body
from .solana_program_decoders import pump_events,pumpswap_trade_events
from .solana_native_evidence import normalize_zero_display
from .solana_candidate_phases import phase as candidate_phase

FAMILIES={'pump':'program:pump','pumpswap':'program:pumpswap','meteora':'program:meteora'}
PROGRAMS={'pump':'6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',
          'pumpswap':'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA',
          'meteora':'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'}
# NULL is the original complete/unknown-progress attention branch. Other
# values retain the exact original SQLite comparison with the policy minimum.
DEVELOPMENT_BOUND="CASE WHEN json_extract(fields,'$.complete') OR json_extract(fields,'$.development_upper_bps') IS NULL THEN NULL ELSE json_extract(fields,'$.development_upper_bps') END"
SCHEMA='''
CREATE TABLE IF NOT EXISTS market_observations(
 family TEXT NOT NULL,address TEXT NOT NULL,first_slot INTEGER NOT NULL,
 last_slot INTEGER NOT NULL,first_seen REAL NOT NULL,last_seen REAL NOT NULL,
 source_signature TEXT NOT NULL,fields TEXT NOT NULL,hash TEXT NOT NULL,
 PRIMARY KEY(family,address));
CREATE TABLE IF NOT EXISTS evidence_bindings(
 family TEXT NOT NULL,address TEXT NOT NULL,market_address TEXT NOT NULL,
 canonical_scope TEXT NOT NULL,coverage_scope TEXT NOT NULL,metadata TEXT NOT NULL,
 PRIMARY KEY(family,address));
CREATE INDEX IF NOT EXISTS evidence_binding_canonical_market
 ON evidence_bindings(canonical_scope,market_address);
-- Publication resolves only the aliases of its exact candidate scope. Scanning
-- every retained Pump binding per proof eventually delays canonical intake.
CREATE INDEX IF NOT EXISTS evidence_binding_coverage_lookup
 ON evidence_bindings(family,coverage_scope,market_address,address);
-- Retirement checks all aliases of an exact scope, independent of family.
CREATE INDEX IF NOT EXISTS evidence_binding_scope_aliases
 ON evidence_bindings(coverage_scope,address);
CREATE TABLE IF NOT EXISTS acquisition_jobs(
 id TEXT PRIMARY KEY,family TEXT NOT NULL,address TEXT NOT NULL,
 lo INTEGER NOT NULL,hi INTEGER NOT NULL,priority INTEGER NOT NULL,deadline REAL NOT NULL,
 status TEXT NOT NULL,token TEXT,pages INTEGER NOT NULL,last_slot INTEGER,last_index INTEGER,
 lineage TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,error TEXT);
CREATE INDEX IF NOT EXISTS acquisition_priority ON acquisition_jobs(status,priority,deadline,created);
CREATE INDEX IF NOT EXISTS acquisition_candidate_status ON acquisition_jobs(family,address,status);
CREATE INDEX IF NOT EXISTS acquisition_expiry_quantum_v1 ON acquisition_jobs(family,status,deadline,id);
CREATE TABLE IF NOT EXISTS acquisition_page_receipts(
 job TEXT NOT NULL,page INTEGER NOT NULL,input_hash TEXT NOT NULL,
 result TEXT NOT NULL,committed REAL NOT NULL,PRIMARY KEY(job,page));
CREATE TABLE IF NOT EXISTS native_order_attestations(
 scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 transaction_index INTEGER NOT NULL,hash TEXT NOT NULL,
 PRIMARY KEY(scope,slot,signature));
CREATE TABLE IF NOT EXISTS provider_delivery(
 day INTEGER NOT NULL,family TEXT NOT NULL,transport TEXT NOT NULL,
 raw_bytes INTEGER NOT NULL DEFAULT 0,retained_bytes INTEGER NOT NULL DEFAULT 0,
 canonical_bytes INTEGER NOT NULL DEFAULT 0,ipc_bytes INTEGER NOT NULL DEFAULT 0,
 rpc_cu INTEGER NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(day,family,transport));
CREATE TABLE IF NOT EXISTS acquisition_observations(
 id INTEGER PRIMARY KEY,job TEXT,kind TEXT NOT NULL,at REAL NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_coverage(
 scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER NOT NULL,count INTEGER NOT NULL,
 first_available REAL NOT NULL,last_available REAL NOT NULL,points BLOB NOT NULL,
 hash TEXT NOT NULL,lineage TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(scope,lo));
CREATE INDEX IF NOT EXISTS candidate_coverage_bounds ON candidate_coverage(scope,hi,lo);
CREATE TABLE IF NOT EXISTS candidate_gaps(
 id INTEGER PRIMARY KEY,scope TEXT NOT NULL,lo INTEGER NOT NULL,hi INTEGER,
 created REAL NOT NULL,repaired REAL,reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_gap_scope_bounds ON candidate_gaps(scope,lo,hi);
CREATE INDEX IF NOT EXISTS candidate_gap_availability ON candidate_gaps(scope,repaired,lo,hi,created);
CREATE TABLE IF NOT EXISTS shared_history_cache(
 identity TEXT PRIMARY KEY,scope TEXT NOT NULL,slot INTEGER NOT NULL,signature TEXT NOT NULL,
 program TEXT NOT NULL,market_time INTEGER,event_index INTEGER NOT NULL,transaction_index INTEGER,
 kind TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,first_seen REAL NOT NULL,archive TEXT);
CREATE TABLE IF NOT EXISTS cached_addresses(identity TEXT NOT NULL,address TEXT NOT NULL,
 PRIMARY KEY(identity,address),FOREIGN KEY(identity) REFERENCES shared_history_cache(identity) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS cached_address_lookup ON cached_addresses(address,identity);
CREATE VIEW IF NOT EXISTS canonical_evidence AS
 SELECT * FROM records WHERE body IS NOT NULL OR NOT EXISTS(
   SELECT 1 FROM shared_history_cache c WHERE c.identity=records.identity)
 UNION ALL SELECT * FROM shared_history_cache c WHERE NOT EXISTS(
   SELECT 1 FROM records r WHERE r.identity=c.identity AND r.body IS NOT NULL);
CREATE VIEW IF NOT EXISTS canonical_addresses AS
 SELECT identity,address FROM addresses UNION SELECT identity,address FROM cached_addresses;
CREATE TABLE IF NOT EXISTS candidate_outbox(
 sequence INTEGER PRIMARY KEY,identity TEXT NOT NULL UNIQUE,scope TEXT NOT NULL,
 slot INTEGER NOT NULL,first_seen REAL NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_outbox_scope ON candidate_outbox(scope,sequence);
CREATE TABLE IF NOT EXISTS candidate_content_receipts(
 identity TEXT PRIMARY KEY,economic_hash TEXT NOT NULL,transaction_index INTEGER,
 first_seen REAL NOT NULL);
'''

@lru_cache(maxsize=8192)
def pump_curve_address(mint):
    """Cache immutable PDA computation, never candidate eligibility or history."""
    from . import pump
    return pump.pda([b'bonding-curve',pump.un58(mint)],pump.PROGRAM)

def coverage_scope(family,address):
    if family not in FAMILIES or not isinstance(address,str) or not address:
        raise EvidenceUnavailable('candidate_scope_shape')
    return 'candidate:'+family+':'+address

def rpc_economic_transaction(tx,*,rich):
    """Same economic interface for native, archive and selective body fallback."""
    try:
        message=tx['transaction']['message'];meta=tx['meta']
        if not isinstance(message,dict) or not isinstance(meta,dict) or 'err' not in meta:
            raise KeyError()
        keys=[k if isinstance(k,str) else k['pubkey'] for k in message['accountKeys']]
        loaded=meta.get('loadedAddresses') or {}
        keys+=list(loaded.get('writable') or [])+list(loaded.get('readonly') or [])
        if not tx['transaction']['signatures'] or not all(isinstance(k,str) for k in keys):raise KeyError()
        logs=meta['logMessages']
        if meta['err'] is None and not isinstance(logs,list):raise KeyError()
        body=dict(slot=tx['slot'],blockTime=tx['blockTime'],transactionIndex=tx['transactionIndex'],
            transaction=dict(signatures=list(tx['transaction']['signatures']),message=dict(accountKeys=keys)),
            meta=dict(err=meta['err'],logMessages=logs))
        if rich:
            for field in ('innerInstructions','preTokenBalances','postTokenBalances'):
                body['meta'][field]=meta[field]
            body['transaction']['message']['instructions']=[
                {k:v for k,v in instruction.items() if k!='stackHeight'}
                for instruction in message['instructions']]
        return normalize_zero_display(body)
    except (KeyError,TypeError):raise EvidenceUnavailable('candidate_economic_fields_missing') from None

@dataclass(frozen=True)
class ArchiveLogSupplement:
    """Immutable provider inputs, not a caller-supplied economic projection."""
    original_json: str
    fetched_json: str
    endpoint_identity: str

# Fixed rejection attribution only. None of these values carries provider data,
# changes authentication, or permits a rejected page to be committed.
ARCHIVE_LOG_FAILURE_CHECKS=frozenset((
    'endpoint_identity','response_shape','original_slot','original_index',
    'original_signatures','original_meta','fetched_meta','original_logs',
    'fetched_logs','fetched_slot','original_time','fetched_time','block_time',
    'transaction_identity','original_error','fetched_error','fetched_index',
    'original_log_shape','fetched_log_shape','fetched_log_line',
    'fetched_log_truncation','marker_count','prefix','retained_suffix',
))


def _archive_log_join(original,fetched,endpoint_identity):
    """Join complete logs only to the exact finalized, ordered archive row."""
    check='endpoint_identity'
    try:
        if (not isinstance(endpoint_identity,str) or len(endpoint_identity)!=64
                or any(c not in '0123456789abcdef' for c in endpoint_identity)):
            raise KeyError()
        check='response_shape'
        if not isinstance(original,dict) or not isinstance(fetched,dict):raise KeyError()
        # Keep the original lookup order before its validation predicates. The
        # marker records the exact field whose lookup or predicate rejected;
        # values, logs, identifiers and provider messages never enter it.
        check='original_slot';slot=original['slot']
        check='original_index';index=original['transactionIndex']
        check='original_signatures';signatures=original['transaction']['signatures']
        check='original_meta';old=original['meta']
        check='fetched_meta';new=fetched['meta']
        check='original_logs';logs=old['logMessages']
        check='fetched_logs';complete=new['logMessages']
        check='original_slot'
        if type(slot) is not int or slot<0:raise KeyError()
        check='original_index'
        if type(index) is not int or index<0:raise KeyError()
        check='original_signatures'
        if (not isinstance(signatures,list) or not signatures
                or any(not isinstance(sig,str) or not sig for sig in signatures)):raise KeyError()
        check='fetched_slot'
        if type(fetched['slot']) is not int or fetched['slot']!=slot:raise KeyError()
        check='original_time'
        if type(original['blockTime']) is not int or original['blockTime']<0:raise KeyError()
        check='fetched_time'
        if type(fetched['blockTime']) is not int:raise KeyError()
        check='block_time'
        if canonical(fetched['blockTime'])!=canonical(original['blockTime']):raise KeyError()
        check='transaction_identity'
        if canonical(fetched['transaction'])!=canonical(original['transaction']):raise KeyError()
        check='original_error'
        if old['err'] is not None:raise KeyError()
        check='fetched_error'
        if new['err'] is not None:raise KeyError()
        check='fetched_index'
        if 'transactionIndex' in fetched and (type(fetched['transactionIndex']) is not int
                or fetched['transactionIndex']!=index):raise KeyError()
        validate_log_supplement_fields(logs,complete)
    except (KeyError,TypeError,ValueError) as cause:
        if (type(cause) is EvidenceUnavailable
                and getattr(cause,'archive_log_failure_check',None) in ARCHIVE_LOG_FAILURE_CHECKS):raise
        error=EvidenceUnavailable('archive_log_supplement_identity_unverified')
        error.archive_log_failure_check=check
        raise error from None
    # Preserve every original economic/provider field except the separately
    # authenticated missing log suffix. Its genuine native index is unchanged.
    tx=json.loads(canonical(original));tx['meta']['logMessages']=list(complete)
    return tx


def validate_log_supplement_fields(logs,complete):
    """The existing prefix/suffix check, without transaction/source authority.

    This can refuse a later truncated WS duplicate of an already authenticated
    native HTTP field without fabricating a transaction envelope or retaining
    another full RPC response. Validation and rejection precedence are shared
    with the original archive supplement authenticator.
    """
    check='original_log_shape'
    try:
        if (not isinstance(logs,list) or not logs
                or any(not isinstance(line,str) for line in logs)):raise KeyError()
        check='fetched_log_shape'
        if not isinstance(complete,list):raise KeyError()
        # Preserve the original generator's per-line short-circuit order while
        # distinguishing malformed elements from a genuinely incomplete reply.
        for line in complete:
            check='fetched_log_line'
            if not isinstance(line,str):raise KeyError()
            check='fetched_log_truncation'
            if 'truncat' in line.lower():raise KeyError()
        check='marker_count'
        markers=[i for i,line in enumerate(logs) if 'truncat' in line.lower()]
        if len(markers)!=1:raise KeyError()
        marker=markers[0];prefix=logs[:marker];suffix=logs[marker+1:]
        check='prefix'
        if len(complete)<len(prefix) or complete[:len(prefix)]!=prefix:raise KeyError()
        # The archive may retain sparse lines after its truncation marker.
        # Match every line in order at a distinct position beyond the prefix;
        # only the entire complete response supplies decoded event indices.
        check='retained_suffix'
        position=len(prefix)
        for line in suffix:
            while position<len(complete) and complete[position]!=line:position+=1
            if position==len(complete):raise KeyError()
            position+=1
    except (KeyError,TypeError,ValueError):
        error=EvidenceUnavailable('archive_log_supplement_identity_unverified')
        error.archive_log_failure_check=check
        raise error from None

def join_archive_log_supplement(original,fetched,*,endpoint_identity):
    _archive_log_join(original,fetched,endpoint_identity)
    original_json=canonical(original);fetched_json=canonical(fetched)
    if len(fetched_json.encode())>16*1024*1024:
        raise EvidenceUnavailable('archive_log_supplement_bound')
    return ArchiveLogSupplement(original_json,fetched_json,endpoint_identity)

def complete_archive_transaction(original,supplement,*,endpoint_identity):
    if (type(supplement) is not ArchiveLogSupplement or supplement.endpoint_identity!=endpoint_identity
            or type(supplement.original_json) is not str or type(supplement.fetched_json) is not str
            or canonical(original)!=supplement.original_json):
        raise EvidenceUnavailable('archive_log_supplement_binding_unverified')
    try:fetched=json.loads(supplement.fetched_json)
    except (TypeError,ValueError):raise EvidenceUnavailable('archive_log_supplement_binding_unverified') from None
    if len(supplement.fetched_json.encode())>16*1024*1024:
        raise EvidenceUnavailable('archive_log_supplement_bound')
    if canonical(fetched)!=supplement.fetched_json:
        raise EvidenceUnavailable('archive_log_supplement_binding_unverified')
    return _archive_log_join(original,fetched,endpoint_identity)

def missing_archive_log_transactions(family,value):
    """Only successful, explicitly truncated log rows justify this fallback."""
    if (family not in ('pump','pumpswap') or not isinstance(value,dict)
            or not isinstance(value.get('data'),list) or len(value['data'])>100):return ()
    return tuple(tx for tx in value['data'] if isinstance(tx,dict)
        and isinstance(tx.get('meta'),dict) and tx['meta'].get('err',True) is None
        and isinstance(tx['meta'].get('logMessages'),list)
        and any(isinstance(line,str) and 'truncat' in line.lower() for line in tx['meta']['logMessages']))

def archive_interval_witness(job,scope,lineage_hash,*,supplemented=False,page_count=None):
    witness=dict(finalized=True,complete=True,scope=scope,lower_slot=job['lo'],upper_slot=job['hi'],
        lineage_hash=lineage_hash,method='getTransactionsForAddress',pagination_exhausted=True,
        page_count=job['pages'] if page_count is None else page_count,
        address=job['address'],canonical_scope=FAMILIES[job['family']])
    if supplemented:
        witness.update(method='getTransactionsForAddress+getTransaction',
            transaction_order_method='getTransactionsForAddress',log_content_method='getTransaction',
            log_content_commitment='finalized')
    return witness

def archive_page_evidence(job,value,*,endpoint_identity,supplements=(),supplemented_before=False):
    """One hash/proof contract for the owner and its restricted recovery caller."""
    if type(supplements) is not tuple or len(supplements)>100:
        raise EvidenceUnavailable('archive_log_supplement_shape')
    value_raw=canonical(value);value_hash=hashlib.sha256(value_raw.encode()).hexdigest()
    raw_rows=value.get('data') if isinstance(value,dict) else None
    if not isinstance(raw_rows,list) or len(raw_rows)>100:
        raise EvidenceUnavailable('address_history_response_shape_unverified')
    originals={};receipts=[];observations=[];supplement_bytes=0
    for supplement in supplements:
        if type(supplement) is not ArchiveLogSupplement:
            raise EvidenceUnavailable('archive_log_supplement_shape')
        matches=[(n,tx) for n,tx in enumerate(raw_rows) if canonical(tx)==supplement.original_json]
        if len(matches)!=1 or matches[0][0] in originals:
            raise EvidenceUnavailable('archive_log_supplement_binding_unverified')
        n,original=matches[0]
        complete_archive_transaction(original,supplement,endpoint_identity=endpoint_identity)
        originals[n]=supplement
    # Bind supplements in original page order, independent of fetch completion.
    for n,supplement in sorted(originals.items()):
        tx=raw_rows[n]
        body=dict(endpoint_identity=endpoint_identity,method='getTransaction',commitment='finalized',
            slot=tx['slot'],signature=tx['transaction']['signatures'][0],transaction_index=tx['transactionIndex'],
            original_transaction_hash=hashlib.sha256(supplement.original_json.encode()).hexdigest(),
            fetched_transaction_hash=hashlib.sha256(supplement.fetched_json.encode()).hexdigest(),
            original_prefix_length=next(i for i,line in enumerate(tx['meta']['logMessages'])
                if 'truncat' in line.lower()),response=json.loads(supplement.fetched_json))
        body_raw=canonical(body);supplement_bytes+=len(body_raw.encode())
        if supplement_bytes>16*1024*1024:raise EvidenceUnavailable('archive_log_supplement_bound')
        observations.append(body)
        receipts.append(dict({key:value for key,value in body.items() if key!='response'},
            observation_body_hash=hashlib.sha256(body_raw.encode()).hexdigest()))
    bound=receipts
    page_hash=(digest(dict(method='getTransactionsForAddress+getTransaction',
        archive_page_hash=value_hash,archive_log_supplements=bound)) if receipts else value_hash)
    input_hash=(digest([job['token'],dict(archive_page_hash=value_hash,
        archive_supplemented_page_hash=page_hash,archive_log_supplements=bound)]) if receipts else
        hashlib.sha256(('['+canonical(job['token'])+','+value_raw+']').encode()).hexdigest())
    lineage=digest([job['lineage'],page_hash])
    return dict(value_hash=value_hash,page_hash=page_hash,input_hash=input_hash,lineage_hash=lineage,
        witness=archive_interval_witness(job,coverage_scope(job['family'],job['address']),lineage,
            supplemented=bool(receipts) or supplemented_before,page_count=job['pages']+1),
        supplement_receipts=receipts,supplement_observations=observations)

def economic_records(family,address,tx,*,endpoint_identity,seen,source,
                     prepared=None,preparation_context=None,prepared_raw=None):
    scope=FAMILIES[family];index=tx['transactionIndex'];slot=tx['slot']
    signature=tx['transaction']['signatures'][0]
    if type(index) is not int or index<0 or type(slot) is not int or slot<0:
        raise EvidenceUnavailable('candidate_native_order_missing')
    if family=='meteora':
        body=rpc_economic_transaction(tx,rich=True)
        keys=body['transaction']['message']['accountKeys']
        if address not in keys:raise EvidenceUnavailable('candidate_address_membership_missing')
        return [FinalizedRecord(scope+':tx:'+signature,scope,slot,signature,PROGRAMS[family],
            tuple(sorted(set(keys+[PROGRAMS[family]]))),body['blockTime'],body,source,endpoint_identity,seen,
            transaction_index=index,kind='transaction')]
    meta=tx['meta']
    if 'err' not in meta or 'logMessages' not in meta:raise EvidenceUnavailable('candidate_economic_fields_missing')
    if meta['err'] is not None:return []
    logs=meta['logMessages']
    if not isinstance(logs,list) or any('truncat' in line.lower() for line in logs):
        raise EvidenceUnavailable('incomplete_finalized_logs')
    events=None
    if prepared is not None:
        from .solana_economic_preparation import archive_prepared_events
        events=archive_prepared_events(prepared,preparation_context,family,tx,raw=prepared_raw)
    if events is None:events=(pump_events if family=='pump' else pumpswap_trade_events)(tx)
    rows=[]
    for event in events:
        # A transaction can mention multiple candidates. Acquire it once, but
        # do not put an unrelated event inside this candidate's coverage proof.
        if family=='pumpswap' and address!=PROGRAMS[family] and event.get('pool')!=address:continue
        if family=='pump' and address!=PROGRAMS[family] and event.get('mint')!=address and event.get('bonding_curve')!=address:
            from . import pump
            mint=event.get('mint')
            if not mint or pump_curve_address(mint)!=address:continue
        addresses=tuple(sorted({str(event[k]) for k in ('pool','mint','wallet') if event.get(k)}))
        payload=dict(event=event,raw_lineage=dict(logs=logs,err=meta['err']))
        rows.append(FinalizedRecord(f'{scope}:{slot}:{signature}:{event["index"]}',scope,slot,
            signature,PROGRAMS[family],addresses,event['market_time'],payload,source,endpoint_identity,seen,
            event_index=event['index'],transaction_index=index))
    return rows


class SelectiveHistory:
    """Runs exclusively on the existing canonical SQLite owner thread."""
    def __init__(self,writer,endpoint_identity,*,clock=time.time):
        self.writer=writer;self.db=writer.db;self.endpoint_identity=endpoint_identity;self.clock=clock
        self.db.executescript(SCHEMA)
        self.db.execute('CREATE INDEX IF NOT EXISTS market_development_progress ON market_observations(family,'+
            DEVELOPMENT_BOUND+',first_seen,address)')
        from .runtime.operating_families import solana_families
        self.active_families=solana_families()

    def development_candidates(self,minimum,limit):
        # Disjoint indexed ranges are equivalent to the original OR predicate.
        # Do not scan every retained low-progress scout on each owner poll.
        return self.db.execute('''SELECT address FROM (
            SELECT address,first_seen FROM market_observations WHERE family='pump' AND '''+
            DEVELOPMENT_BOUND+''' IS NULL UNION ALL
            SELECT address,first_seen FROM market_observations WHERE family='pump' AND '''+
            DEVELOPMENT_BOUND+'''>=?) m WHERE NOT EXISTS(
                SELECT 1 FROM evidence_bindings b WHERE b.family='pump' AND b.address=m.address)
            ORDER BY first_seen,address LIMIT ?''',(minimum,limit)).fetchall()

    def observe_many(self,facts):
        """Reuse mutable selection reads only within this atomic scout command."""
        from .solana_scout_selection import ScoutSelection
        selection=ScoutSelection(self,facts)
        for fact in facts:
            if fact is not None:self.observe(**fact,_selection=selection)

    def observe(self,family,address,*,slot,signature,fields,seen=None,_selection=None):
        """Lossless cheap retention. This record cannot authorize qualification."""
        if family not in self.active_families:raise EvidenceUnavailable('paused_family_activity_forbidden')
        if family not in FAMILIES or not isinstance(fields,dict):raise EvidenceUnavailable('candidate_scout_shape')
        seen=self.clock() if seen is None else seen
        # Validate incoming JSON even for an older locator, as the scalar path
        # did. Reuse its bytes when no merge with retained fields is required.
        body=canonical(fields)
        with self.writer.transaction():
            prior=(_selection.market.get((family,address)) if _selection is not None else
                self.db.execute('SELECT last_slot,last_seen,fields FROM market_observations WHERE family=? AND address=?',(family,address)).fetchone())
            if prior and (slot,seen)<tuple(prior[:2]):return
            if prior:
                fields=dict(json.loads(prior[2]),**fields)
                body=canonical(fields)
            checksum=hashlib.sha256(body.encode()).hexdigest()
            self.db.execute('''INSERT INTO market_observations VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(family,address) DO UPDATE SET last_slot=excluded.last_slot,
                last_seen=excluded.last_seen,source_signature=excluded.source_signature,
                fields=excluded.fields,hash=excluded.hash''',
                (family,address,slot,slot,seen,seen,signature,body,checksum))
            if _selection is not None:_selection.market[family,address]=(slot,seen,body)
            if hasattr(self,'lifecycle'):
                self.lifecycle.observe(family,address,slot=slot,seen=seen,signature=signature,fields=fields,
                    activity=fields.get('activity',False),_selection=_selection)

    @measured('owner.binding')
    def bind(self,family,address,*,market_address=None,aliases=(),metadata=None):
        if family not in self.active_families:raise EvidenceUnavailable('paused_family_activity_forbidden')
        base=FAMILIES[family];scoped=coverage_scope(family,address)
        with self.writer.transaction():
            current=self.db.execute('SELECT market_address FROM evidence_bindings WHERE family=? AND address=?',
                (family,address)).fetchone()
            # Repeated provider-interest registration must retain an authenticated
            # curve-to-mint upgrade. An explicit different identity still fails.
            market=market_address or (current[0] if current else address)
            # A mint interest must reuse the curve's already proved identity.
            # Conversely, a creation backfill can attach a provisional curve to
            # an existing mint interest without changing its durable scope.
            existing=[self.db.execute('SELECT market_address,coverage_scope FROM evidence_bindings WHERE family=? AND address=?',
                (family,a)).fetchone() for a in dict.fromkeys((address,*aliases))]
            matching={row[1] for row in existing if row and row[0]==market}
            if len(matching)>1:raise EvidenceConflict('candidate_binding_conflict')
            if matching:scoped=matching.pop()
            for alias in dict.fromkeys((address,*aliases)):
                old=self.db.execute('SELECT market_address,coverage_scope FROM evidence_bindings WHERE family=? AND address=?',(family,alias)).fetchone()
                target=(market,scoped)
                if old and tuple(old)!=target:raise EvidenceConflict('candidate_binding_conflict')
                inserted=self.db.execute('INSERT OR IGNORE INTO evidence_bindings VALUES(?,?,?,?,?,?)',
                    (family,alias,market,base,scoped,canonical(metadata or {}))).rowcount
                if inserted:
                    from .solana_history_notifications import changed
                    changed(self)
        return scoped

    def scope_for(self,family,address):
        row=self.db.execute('SELECT coverage_scope FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        return coverage_scope(family,address) if row is None else row[0]

    def _archive_preparation_tightened(self,identity,priority,deadline):
        # This bounded volatile map is installed only for actual in-flight RPC
        # claims. It grants no durable state, lease or readiness authority.
        ticket=getattr(self,'_archive_preparation_tickets',{}).get(identity)
        if ticket is not None:
            try:ticket.tighten(priority,deadline)
            except Exception:pass

    def request(self,family,address,lo,hi,*,priority,deadline):
        if family not in self.active_families:raise EvidenceUnavailable('paused_family_activity_forbidden')
        if type(lo) is not int or type(hi) is not int or not 0<=lo<=hi or not 0<=priority<=6:
            raise EvidenceUnavailable('candidate_history_request_shape')
        now=self.clock();identity=digest([family,address,lo,hi])
        # This code runs on the sole canonical owner. An already stronger request
        # needs no transaction, cursor rewrite or repeated pressure observation.
        # A genuinely earlier deadline/higher priority still takes the old path.
        prior=self.db.execute('SELECT priority,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone()
        if prior and prior[0]<=priority and prior[1]<=deadline:return identity
        with self.writer.transaction():
            self.db.execute('''INSERT OR IGNORE INTO acquisition_jobs VALUES(?,?,?,?,?,?,?,
                'pending',NULL,0,NULL,NULL,?,?,?,NULL)''',
                (identity,family,address,lo,hi,priority,deadline,digest([]),now,now))
            # Reasserting an interval may increase urgency, never reset its cursor.
            self.db.execute('UPDATE acquisition_jobs SET priority=MIN(priority,?),deadline=MIN(deadline,?) WHERE id=?',
                (priority,deadline,identity))
            self._archive_preparation_tightened(identity,priority,deadline)
            scheduler=getattr(self,'acquisition_scheduler',None)
            depth=(scheduler.pending_count() if scheduler is not None else
                self.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE status='pending'").fetchone()[0])
            if depth>8:self._observation(identity,'capacity_pressure',dict(queue_depth=depth,economic_rejection=False))
        return identity

    def _observation(self,job,kind,body):
        self.db.execute('INSERT INTO acquisition_observations(job,kind,at,body) VALUES(?,?,?,?)',
            (job,kind,self.clock(),canonical(body)))

    def defer_provider_failure(self,job,*,retryable,diagnostic):
        """Keep optional missing history local; retain its lease and deadline.

        The existing error field holds a durable bounded backoff. Mandatory
        work cannot borrow this deferral, including a concurrently upgraded job.
        No failed request supplies rows, a cursor, or coverage.
        """
        now=self.clock()
        with self.writer.transaction():
            row=self.db.execute('SELECT priority,deadline,status,token,pages,error FROM acquisition_jobs WHERE id=?',
                (job['id'],)).fetchone()
            if row is None or row[2]!='pending' or (row[3],row[4])!=(job['token'],job['pages']):return
            if row[0]<=2:raise EvidenceUnavailable('candidate_protective_acquisition_failed')
            previous={}
            if row[5]:
                try:previous=json.loads(row[5])
                except (ValueError,TypeError):pass
            attempts=(previous.get('attempts',0) if isinstance(previous,dict)
                and previous.get('kind')=='archive_provider_failure' else 0)+1
            retry_after=now+min(30,2**min(attempts,5))
            status='deadline_missed' if row[1]<=now else 'pending' if retryable and retry_after<row[1] else 'failed'
            body=dict(kind='archive_provider_failure',attempts=attempts,retry_after=retry_after,
                diagnostic=diagnostic,complete=False,economic_rejection=False,
                candidate_retained=True,deadline=row[1],deadline_reset=False)
            self.db.execute('UPDATE acquisition_jobs SET status=?,updated=?,error=? WHERE id=?',
                (status,now,canonical(body),job['id']))
            self._observation(job['id'],'archive_provider_failure',dict(body,status=status))

    def install_planner(self):
        """Install additive owner scheduling before native producers start."""
        if not hasattr(self,'acquisition_scheduler'):
            from .solana_acquisition_scheduler import AcquisitionScheduler
            self.acquisition_scheduler=AcquisitionScheduler(self)
        if hasattr(self,'historical_tasks') and not hasattr(self,'dispatch_probe'):
            from .solana_dispatch_probe import DispatchProbe
            self.dispatch_probe=DispatchProbe(self)

    @measured('owner.history_plan')
    def plan_step(self,*,excluding=(),urgent_only=False):
        """One finite dispatch quantum; DEFERRED never means empty/complete.

        The authoritative row, original deadline, local completeness and
        publication guard are rechecked on this sole owner. One optional child
        is created at a time; its unchanged parent retains the entire original
        obligation until real coverage, not the child list, proves completion.
        """
        from .solana_candidate_development import PlanningStep, DISPATCH, DEFERRED, IDLE
        from .solana_acquisition_scheduler import DEFERRED as SCHEDULE_DEFERRED, IDLE as SCHEDULE_IDLE
        from .operational.position_continuation import position_only
        self.install_planner()
        scheduler=self.acquisition_scheduler
        only_urgent=urgent_only or position_only()
        with self.writer.transaction():
            # Expiry is an original obligation, including position-only
            # operation. Fixed indexed streams retire at most sixteen rows;
            # remaining expiry debt never prevents selecting a fresh urgent
            # head in this same quantum.
            expired=[];now=self.clock()
            for family in sorted(self.active_families):
                if only_urgent:
                    for priority in range(3):
                        expired.extend(self.db.execute("SELECT id,deadline FROM acquisition_jobs "
                            "INDEXED BY acquisition_schedule_source_urgent_v1 WHERE family=? AND status='pending' "
                            "AND priority=? AND deadline<=? ORDER BY deadline,created,id LIMIT 17",
                            (family,priority,now)).fetchall())
                else:
                    expired.extend(self.db.execute("SELECT id,deadline FROM acquisition_jobs "
                        "INDEXED BY acquisition_expiry_quantum_v1 WHERE family=? AND status='pending' "
                        "AND deadline<=? ORDER BY deadline,id LIMIT 17",(family,now)).fetchall())
            expiry_more=len(expired)>16
            for identity,_ in sorted(expired,key=lambda row:(row[1],row[0]))[:16]:
                self.db.execute("UPDATE acquisition_jobs SET status='deadline_missed',updated=?,"
                    "error='candidate_decision_deadline_missed' WHERE id=?",(now,identity))
                self._observation(identity,'deadline_missed',dict(economic_rejection=False))
            job=scheduler.next(excluding=excluding,urgent=only_urgent)
            if job==SCHEDULE_DEFERRED:return PlanningStep(DEFERRED)
            if job==SCHEDULE_IDLE:return PlanningStep(DEFERRED if expiry_more else IDLE)
            now=self.clock()
            if job['deadline']<=now:return PlanningStep(DEFERRED)
            if job['priority']>2 and job['error']:
                retry=self.db.execute("SELECT CASE WHEN json_valid(error) THEN CASE WHEN "
                    "json_extract(error,'$.kind')='archive_provider_failure' THEN "
                    "json_extract(error,'$.retry_after') END END FROM acquisition_jobs WHERE id=?",
                    (job['id'],)).fetchone()[0]
                if type(retry) in (int,float) and retry>now:
                    scheduler.defer(job,retry)
                    return PlanningStep(DEFERRED)
            scope=self.scope_for(job['family'],job['address']) if hasattr(self,'rolling') else None
            probe=None
            fanout_after=scheduler.fanout_after(job) if not job['pages'] else None
            if scope is None:
                interval=(job['lo'],job['hi'])
            elif job['priority']>2 and hasattr(self,'historical_tasks') and job['family'] in ('pump','pumpswap'):
                from .solana_dispatch_probe import READY, COMPLETE
                probe=self.dispatch_probe.step(job,after_slot=fanout_after)
                if probe.state==COMPLETE:
                    if not self.dispatch_probe.current(job,probe):return PlanningStep(DEFERRED)
                    self.db.execute("UPDATE acquisition_jobs SET status='complete',updated=? WHERE id=?",(now,job['id']))
                    self._observation(job['id'],'shared_coverage_reused',dict(scope=scope,
                        lo=job['lo'],hi=job['hi'],deadline_reset=False))
                    self.dispatch_probe.reset()
                    return PlanningStep(DEFERRED)
                if probe.state!=READY:
                    if probe.reason=='FANOUT_COMPLETE' and fanout_after is not None:
                        scheduler.fanout_wait(job)
                    elif not probe.continuation:
                        scheduler.defer(job,now+.1,probe.dependency)
                    return PlanningStep(DEFERRED)
                interval=probe.interval
            else:
                # Existing urgent/native completeness runs synchronously. It
                # must not wait for optional preparation or borrow its verdict.
                missing=self.rolling.missing(job['family'],scope,job['lo'],job['hi'])
                if not missing:
                    self.db.execute("UPDATE acquisition_jobs SET status='complete',updated=? WHERE id=?",(now,job['id']))
                    self._observation(job['id'],'shared_coverage_reused',dict(scope=scope,
                        lo=job['lo'],hi=job['hi'],deadline_reset=False))
                    return PlanningStep(DEFERRED)
                scopes=self.rolling.scopes(job['family'],scope)
                publishing=self.db.execute('SELECT lo,hi FROM candidate_pending_proofs WHERE scope IN ('+
                    ','.join('?' for _ in scopes)+') AND lo<=? AND hi>=?',(*scopes,job['hi'],job['lo'])).fetchall()
                required=missing
                for lo,hi in publishing:
                    required=[p for a,b in required for p in ((a,min(b,lo-1)),(max(a,hi+1),b)) if p[0]<=p[1]]
                if not required:
                    scheduler.defer(job,now+.1)
                    return PlanningStep(DEFERRED)
                if not job['pages'] and fanout_after is not None:
                    required=[(max(a,fanout_after+1),b) for a,b in required if b>fanout_after]
                    if not required:
                        scheduler.fanout_wait(job)
                        return PlanningStep(DEFERRED)
                interval=required[0]
            a,b=interval
            # At most the eight bounded archive workers can own physical pages.
            overlapping=[]
            for identity in excluding:
                flight=self.db.execute("SELECT family,address,lo,hi FROM acquisition_jobs "
                    "WHERE id=? AND status='pending'",(identity,)).fetchone()
                if (flight and flight[0]==job['family'] and self.scope_for(flight[0],flight[1])==scope
                        and flight[2]<=(job['hi'] if job['pages'] else b)
                        and flight[3]>=(job['lo'] if job['pages'] else a)):overlapping.append(identity)
            if overlapping:
                for identity in overlapping:
                    self.db.execute('UPDATE acquisition_jobs SET priority=MIN(priority,?),deadline=MIN(deadline,?) WHERE id=?',
                        (job['priority'],job['deadline'],identity))
                    self._archive_preparation_tightened(identity,job['priority'],job['deadline'])
                if job['pages'] or interval==(job['lo'],job['hi']):
                    scheduler.defer(job,now+.1)
                    if probe is not None:self.dispatch_probe.reset()
                    return PlanningStep(DEFERRED)
            if probe is not None and not self.dispatch_probe.current(job,probe):
                return PlanningStep(DEFERRED)
            if not job['pages'] and interval!=(job['lo'],job['hi']):
                # Materialize independent children over committed quanta before
                # waiting for any physical page. Never move the original job's
                # cursor, bounds, deadline or coverage status. Reusing the same
                # verified probe permits parallel archive workers to acquire
                # later pieces while the earliest child remains in flight.
                self.request(job['family'],job['address'],a,b,priority=job['priority'],deadline=job['deadline'])
                scheduler.fanout_advance(job,b)
                return PlanningStep(DEFERRED)
            if probe is not None:self.dispatch_probe.reset()
            config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
                encoding='json',maxSupportedTransactionVersion=1,
                filters=dict(slot=dict(gte=job['lo'],lte=job['hi'])))
            if job['token'] is not None:config['paginationToken']=job['token']
            return PlanningStep(DISPATCH,(job,config))

    @measured('owner.history_plan')
    def plan(self,*,excluding=()):
        """Recheck shared evidence at dispatch; retain each original obligation."""
        from .runtime.operating_families import active_sql
        live=active_sql('family',solana=True)
        from .operational.position_continuation import position_only
        if position_only():live+=' AND priority<=2'
        now=self.clock()
        with self.writer.transaction():
            for identity in [r[0] for r in self.db.execute("SELECT id FROM acquisition_jobs WHERE "+live+" AND status='pending' AND deadline<=?",(now,))]:
                self.db.execute("UPDATE acquisition_jobs SET status='deadline_missed',updated=?,error='candidate_decision_deadline_missed' WHERE id=?",(now,identity))
                self._observation(identity,'deadline_missed',dict(economic_rejection=False))
            # In-flight work is an obligation, never a completeness witness.
            # Waiting consumers keep their own deadlines and can be serviced by
            # the same physical acquisition even when their bounds differ.
            flights=[]
            for identity in excluding:
                row=self.db.execute('SELECT family,address,lo,hi FROM acquisition_jobs WHERE id=? AND status=\'pending\'',(identity,)).fetchone()
                if row:flights.append((identity,*row))
            skipped=set(excluding)
            skipped.update(r[0] for r in self.db.execute('''SELECT id FROM acquisition_jobs
                WHERE priority>2 AND status='pending' AND CASE WHEN json_valid(error) THEN
                json_extract(error,'$.kind')='archive_provider_failure'
                AND json_extract(error,'$.retry_after')>? ELSE 0 END''',(now,)))
            while True:
                exclusion='' if not skipped else ' AND id NOT IN ('+','.join('?' for _ in skipped)+')'
                historical=getattr(self,'historical_tasks',None)
                if historical is not None:
                    # Exact pending local preparation is a durable obligation,
                    # not missing evidence or a reason to repurchase history.
                    # Urgent protection retains its synchronous checks.
                    exclusion+=''' AND NOT (priority>2 AND EXISTS(
                        SELECT 1 FROM rolling_preparation_jobs h WHERE h.status IN ('pending','active')
                        AND json_extract(h.body,'$.kind') IS NULL
                        AND json_extract(h.body,'$.family')=acquisition_jobs.family
                        AND json_extract(h.body,'$.address')=acquisition_jobs.address
                        AND json_extract(h.body,'$.lo')=acquisition_jobs.lo
                        AND json_extract(h.body,'$.hi')>=acquisition_jobs.hi AND h.deadline<=acquisition_jobs.deadline))'''
                row=self.db.execute('''SELECT id,family,address,lo,hi,priority,deadline,token,pages,last_slot,last_index,lineage
                    FROM acquisition_jobs WHERE '''+live+''' AND status='pending'
                    '''+exclusion+''' ORDER BY CASE WHEN priority<=2 THEN priority ELSE 3 END,deadline,priority,created,id LIMIT 1''',tuple(skipped)).fetchone()
                if row is None:return None
                job=dict(zip(('id','family','address','lo','hi','priority','deadline','token','pages','last_slot','last_index','lineage'),row))
                if not hasattr(self,'rolling'):break
                scope=self.scope_for(job['family'],job['address'])
                missing=(historical.missing_for_dispatch(job) if historical is not None and job['priority']>2
                    else self.rolling.missing(job['family'],scope,job['lo'],job['hi']))
                if missing is None:
                    skipped.add(job['id'])
                    continue
                if not missing:
                    self.db.execute("UPDATE acquisition_jobs SET status='complete',updated=? WHERE id=?",(now,job['id']))
                    self._observation(job['id'],'shared_coverage_reused',dict(scope=scope,lo=job['lo'],hi=job['hi'],deadline_reset=False))
                    continue
                overlapping=[identity for identity,family,address,lo,hi in flights
                    if family==job['family'] and self.scope_for(family,address)==scope
                    and any(lo<=b and hi>=a for a,b in missing)]
                if overlapping:
                    for identity in overlapping:
                        self.db.execute('UPDATE acquisition_jobs SET priority=MIN(priority,?),deadline=MIN(deadline,?) WHERE id=?',
                            (job['priority'],job['deadline'],identity))
                        self._archive_preparation_tightened(identity,job['priority'],job['deadline'])
                    skipped.add(job['id']);continue
                scopes=self.rolling.scopes(job['family'],scope)
                marks=','.join('?' for _ in scopes)
                publishing=self.db.execute('SELECT lo,hi FROM candidate_pending_proofs WHERE scope IN ('+marks+') AND lo<=? AND hi>=?',
                    (*scopes,job['hi'],job['lo'])).fetchall()
                required=missing
                for lo,hi in publishing:
                    required=[p for a,b in required for p in ((a,min(b,lo-1)),(max(a,hi+1),b)) if p[0]<=p[1]]
                if not required:
                    skipped.add(job['id']);continue
                if not job['pages'] and required!=[(job['lo'],job['hi'])]:
                    # Children buy only the missing pieces. The original row is
                    # completed only when real coverage satisfies every piece;
                    # no cursor, launch boundary or deadline is rewritten.
                    for lo,hi in required:
                        self.request(job['family'],job['address'],lo,hi,priority=job['priority'],deadline=job['deadline'])
                    skipped.add(job['id']);continue
                break
        config=dict(transactionDetails='full',sortOrder='asc',limit=100,commitment='finalized',
            encoding='json',maxSupportedTransactionVersion=1,filters=dict(slot=dict(gte=job['lo'],lte=job['hi'])))
        if job['token'] is not None:config['paginationToken']=job['token']
        return job,config

    def has_archive_log_supplements(self,job_id):
        return self.db.execute('''SELECT 1 FROM acquisition_page_receipts WHERE job=?
            AND json_array_length(result,'$.archive_log_supplements')>0 LIMIT 1''',(job_id,)).fetchone() is not None

    def commit_page(self,job,value,*,finalized_through,seen=None,supplements=(),prepared=()):
        if job['family'] not in self.active_families:raise EvidenceUnavailable('paused_family_activity_forbidden')
        """No page-count discard; every physical page remains bounded to 100."""
        seen=self.clock() if seen is None else seen
        if finalized_through<job['hi']:raise EvidenceUnavailable('repair_upper_boundary_not_finalized')
        if not isinstance(value,dict) or not isinstance(value.get('data'),list) or len(value['data'])>100:
            raise EvidenceUnavailable('address_history_response_shape_unverified')
        token=value.get('paginationToken')
        if token is not None and (not isinstance(token,str) or not token or token==job['token']):
            raise EvidenceUnavailable('repair_pagination_stalled')
        evidence=archive_page_evidence(job,value,endpoint_identity=self.endpoint_identity,supplements=supplements,
            supplemented_before=self.has_archive_log_supplements(job['id']))
        from .solana_economic_preparation import archive_preparation_context,prepare_serialized_economics
        context=archive_preparation_context(job,self.endpoint_identity) if prepared else None
        products=prepared if type(prepared) is tuple and len(prepared)==len(value['data']) else ()
        supplement_by_original={item.original_json:item for item in supplements}
        rows=[];last=None if job['last_slot'] is None else (job['last_slot'],job['last_index'])
        for index,tx in enumerate(value['data']):
            pair=(tx.get('slot'),tx.get('transactionIndex'))
            if any(type(n) is not int for n in pair) or not job['lo']<=pair[0]<=job['hi'] or pair[1]<0:
                raise EvidenceUnavailable('repair_order_or_bounds')
            if last is not None and pair<=last:raise EvidenceUnavailable('repair_order_or_bounds')
            last=pair
            raw=canonical(tx);supplement=supplement_by_original.get(raw)
            complete=(complete_archive_transaction(tx,supplement,endpoint_identity=self.endpoint_identity)
                if supplement is not None else tx)
            product=products[index] if products else None
            if supplement is not None and product is not None:raw=canonical(complete)
            rows.extend(economic_records(job['family'],job['address'],complete,
                endpoint_identity=self.endpoint_identity,seen=seen,source='alchemy_finalized_repair',
                prepared=product,preparation_context=context,prepared_raw=raw))
        scoped=self.scope_for(job['family'],job['address']);lineage=evidence['lineage_hash']
        proof=None
        if token is None:
            proof=IntervalProof(scoped,job['lo'],job['hi'],'alchemy_finalized_repair',self.endpoint_identity,
                dict(evidence['witness'],scope=scoped),seen)
        serialized=prepare_serialized_economics(rows)
        with self.writer.transaction():
            input_hash=evidence['input_hash']
            receipt=self.db.execute('SELECT input_hash,result FROM acquisition_page_receipts WHERE job=? AND page=?',
                (job['id'],job['pages'])).fetchone()
            if receipt:
                if receipt[0]!=input_hash:raise EvidenceConflict('candidate_archive_page_conflict')
                return json.loads(receipt[1])
            current=self.db.execute('SELECT token,pages,status FROM acquisition_jobs WHERE id=?',(job['id'],)).fetchone()
            if current is None or tuple(current)!=(job['token'],job['pages'],'pending'):
                raise EvidenceUnavailable('candidate_page_lease_stale')
            retained_supplements=[]
            for receipt,body in zip(evidence['supplement_receipts'],evidence['supplement_observations']):
                observation=self.db.execute('INSERT INTO acquisition_observations(job,kind,at,body) VALUES(?,?,?,?)',
                    (job['id'],'archive_log_supplement',seen,canonical(body)))
                retained_supplements.append(dict(receipt,observation_id=observation.lastrowid))
            # This private product is valid only for these newly built records
            # in this synchronous owner turn, with no await or shared payload.
            self._page_serialization=serialized
            try:self.ingest(rows)
            finally:self._page_serialization=None
            if proof is not None:
                actual=self.scope_for(job['family'],job['address'])
                if proof.scope!=actual:
                    proof=replace(proof,scope=actual,witness=dict(proof.witness,scope=actual))
                if hasattr(self,'lifecycle'):self.lifecycle.defer_proof(proof)
                else:self.prove(proof)
            for row in rows:self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
            self.db.execute('''UPDATE acquisition_jobs SET token=?,pages=pages+1,last_slot=?,last_index=?,
                lineage=?,status=?,updated=? WHERE id=?''',(token,*((None,None) if last is None else last),
                lineage,'complete' if token is None else 'pending',seen,job['id']))
            if job['pages']+1>16:self._observation(job['id'],'capacity_pressure',dict(pages=job['pages']+1,economic_rejection=False))
            result=dict(complete=token is None,records=len(rows),pages=job['pages']+1)
            if retained_supplements:
                result.update(archive_page_hash=evidence['value_hash'],archive_supplemented_page_hash=evidence['page_hash'],
                    archive_log_supplements=retained_supplements)
            self.db.execute('INSERT INTO acquisition_page_receipts VALUES(?,?,?,?,?)',
                (job['id'],job['pages'],input_hash,canonical(result),seen))
        return result

    @measured('owner.economic_ingest')
    def ingest(self,rows,*,restored=None,timing=None,prepared_serialization=None,defer_fanout=False):
        """One identity; a bounded shared cache permits late scoped backfill.

        The global hot-retention floor remains monotonic. It cannot prevent an
        older retained candidate being warmed into an address-scoped cache.
        Existing archived bytes must be independently restored and verified;
        neither their immutable content nor original availability is rewritten.
        """
        with candidate_phase(timing,'ingest_setup'):
            rows=tuple(rows);restored=restored or {}
            from .solana_economic_preparation import PreparedEconomicRecord,SerializedEconomicBatch
            if prepared_serialization is None:
                prepared_serialization=getattr(self,'_page_serialization',None)
            prepared_rows=rows
            rows=tuple(r.record if isinstance(r,PreparedEconomicRecord) else r for r in rows)
            from .runtime.operating_families import require_scope
            for row in rows:require_scope(row.scope)
            if len(rows)>2048:
                raise EvidenceUnavailable('ingestion_batch_bound')
            reusable=(type(prepared_serialization) is SerializedEconomicBatch
                and prepared_serialization is getattr(self,'_page_serialization',None)
                and len(prepared_serialization.records)==len(rows)==len(prepared_serialization.products)
                and all(before is current for before,current in zip(prepared_serialization.records,rows)))
            # Validate/serialize once on this owner command. The same exact bytes
            # establish its physical bound and immutable rolling-store hash. This
            # is never a cache across calls, replay, blocks or mutable payloads.
            serialized=[];retained_bytes=0
            for index,(row,product) in enumerate(zip(rows,prepared_rows)):
                if isinstance(product,PreparedEconomicRecord):
                    if not hasattr(self,'rolling'):raise EvidenceUnavailable('prepared_economic_store_required')
                    prepared=product;retained_bytes+=product.original_bytes
                else:
                    prepared=(prepared_serialization.products[index] if reusable else row.serialized_body())
                    retained_bytes+=len(prepared[1].encode())
                if retained_bytes>16*1024*1024:raise EvidenceUnavailable('ingestion_batch_bound')
                serialized.append(prepared)
            from .solana_evidence_plane import require_storage
            require_storage(self.writer.path,required_bytes=32*1024*1024)
            hot=[];cached=[]
        with self.writer.transaction():
            with candidate_phase(timing,'rolling_adopt'):
                if hasattr(self,'rolling'):self.rolling.adopt(rows)
            with candidate_phase(timing,'economic_store'):
                # Fresh local decoder products may share bounded mutable lookups
                # and companion writes, inside this exact owner transaction.
                # Every replay/legacy/restore/mixed case retains the scalar path.
                stored_fresh=(hasattr(self,'rolling') and self.rolling.store_many(rows,serialized))
                if timing is not None:timing.storage(stored_fresh,len(rows))
                remaining=() if stored_fresh else zip(rows,serialized)
                for row,prepared in remaining:
                    if hasattr(self,'rolling') and row.kind in ('event','transaction'):
                        self.rolling.store(row,serialized=prepared)
                        continue
                    incoming=prepared[0]
                    economic_hash=self.content_hash(incoming)
                    receipt=self.db.execute('SELECT economic_hash,transaction_index,first_seen FROM candidate_content_receipts WHERE identity=?',(row.identity,)).fetchone()
                    if receipt:
                        if receipt[0]!=economic_hash:raise EvidenceConflict('candidate_economic_content_conflict')
                        if receipt[1] is not None and row.transaction_index is not None and receipt[1]!=row.transaction_index:
                            raise EvidenceConflict('candidate_native_order_conflict')
                        # Global hot maintenance can remove a fully consumed record.
                        # Its immutable receipt remains the original availability on
                        # later selective reconstruction, not the new HTTP delivery.
                        row=replace(row,observed_at=receipt[2])
                    old=self.db.execute('SELECT body,hash,first_seen,archive FROM records WHERE identity=?',(row.identity,)).fetchone()
                    previous_cache=self.db.execute('SELECT body,hash,first_seen FROM shared_history_cache WHERE identity=?',(row.identity,)).fetchone()
                    cold=(self.db.execute('SELECT body,hash,first_seen,archive FROM scoped_cold_records WHERE identity=?',(row.identity,)).fetchone()
                          if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_records'").fetchone() else None)
                    available=next((copy[2] for copy in (previous_cache,old,cold) if copy),row.observed_at)
                    self.db.execute('INSERT OR IGNORE INTO candidate_content_receipts VALUES(?,?,?,?)',
                        (row.identity,economic_hash,row.transaction_index,available))
                    if row.transaction_index is not None:
                        self.db.execute('UPDATE candidate_content_receipts SET transaction_index=? WHERE identity=? AND transaction_index IS NULL',
                            (row.transaction_index,row.identity))
                    if old or previous_cache or cold:
                        # A verified scoped cache is the current body pointer; an
                        # older empty records row must not hide it. All durable
                        # copies still have to agree on hash and first availability.
                        prior=previous_cache if previous_cache and previous_cache[0] is not None else old or cold or previous_cache
                        if any(tuple(copy[1:3])!=tuple(prior[1:3]) for copy in (old,previous_cache,cold) if copy):
                            raise EvidenceConflict('local_evidence_hash_mismatch')
                        if prior[0] is not None:body=decode_body(prior[0],self.db)
                        else:
                            body=restored.get(row.identity)
                            if body is None and cold:
                                from .solana_scoped_retirement import ScopedRetirement
                                body=ScopedRetirement(self).body(row.identity)
                            if body is None and receipt:
                                # A selective physical refetch can restore a globally
                                # archived body, but only as the exact old immutable
                                # body. Native-order enrichment remains an attestation.
                                table='records' if old else 'scoped_cold_records'
                                original_index=self.db.execute('SELECT transaction_index FROM '+table+' WHERE identity=?',(row.identity,)).fetchone()[0]
                                body=dict(incoming,transaction_index=original_index)
                                if digest(body)!=prior[1]:raise EvidenceConflict('local_evidence_hash_mismatch')
                            if body is None:raise EvidenceUnavailable('selective_archive_restore_required')
                        if digest(body)!=prior[1]:raise EvidenceConflict('local_evidence_hash_mismatch')
                        self._compatible(body,incoming)
                        self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
                        if old and old[0] is not None:continue
                        cached.append((row,body,prior[2]))
                        continue
                    floor=self.db.execute('SELECT value FROM meta WHERE key=?',('retention_floor:'+row.scope,)).fetchone()
                    from .solana_maintenance_state import PRESERVATION_SECONDS
                    historical=row.market_time is not None and row.market_time<=self.clock()-PRESERVATION_SECONDS
                    # Backfill and overlapping native replay may introduce evidence
                    # whose market-age maintenance lease has already elapsed. Keep
                    # its complete body in the candidate cache instead of creating
                    # instantly overdue debt in the current global hot pipeline.
                    # Both are part of canonical_evidence and use the same pins,
                    # scoped retirement guards and physical storage limit.
                    if historical or floor and row.slot<int(floor[0]):cached.append((row,incoming,row.observed_at))
                    else:hot.append(row)
                self.writer.ingest(hot)
                for row,body,available in cached:
                    raw=canonical(body)
                    self.db.execute('''INSERT OR IGNORE INTO shared_history_cache VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)''',
                        (row.identity,row.scope,row.slot,row.signature,row.program,row.market_time,
                         body['event_index'],body['transaction_index'],row.kind,raw,digest(body),available))
                    for address in body['addresses']:
                        self.db.execute('INSERT OR IGNORE INTO cached_addresses VALUES(?,?)',(row.identity,address))
                    self.attest_order(row.scope,row.slot,row.signature,row.transaction_index)
            with candidate_phase(timing,'delivery_outbox'):
                self._queue_events(rows)
                if hasattr(self,'lifecycle'):
                    if defer_fanout:self.lifecycle.queue_records(rows,defer=True)
                    else:self.lifecycle.queue_records(rows)
            # Retain the owner's same physical storage reservation and the
            # explicit file cap for offline/bounded synthetic stores.
            with candidate_phase(timing,'ingest_setup'):
                if self.writer.hot_capacity_exceeded():
                    raise EvidenceUnavailable('hot_store_capacity')

    def _queue_events(self,rows):
        """Allocate the original ordered outbox sequence once per transaction.

        Existing identities (including repeats within the batch) consume no
        sequence, exactly as the scalar INSERT OR IGNORE/MAX path. Availability
        comes from the committed canonical representation, never the new input.
        """
        events=[row for row in rows if row.kind=='event']
        if not events:return
        identities=tuple(dict.fromkeys(row.identity for row in events))
        available={};existing=set()
        for offset in range(0,len(identities),256):
            group=identities[offset:offset+256];marks=','.join('?' for _ in group)
            available.update(self.db.execute('SELECT identity,first_seen FROM canonical_evidence WHERE identity IN ('+marks+')',group))
            existing.update(r[0] for r in self.db.execute('SELECT identity FROM candidate_outbox WHERE identity IN ('+marks+')',group))
        top=self.db.execute('SELECT MAX(sequence) FROM candidate_outbox').fetchone()[0]
        sequence=4611686018427387904 if top is None else top+1
        pending=[]
        for row in events:
            if row.identity in existing:continue
            pending.append((sequence,row.identity,row.scope,row.slot,available[row.identity]))
            sequence+=1;existing.add(row.identity)
        self.db.executemany('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',pending)

    @staticmethod
    def content_hash(body):
        economic=dict(body);economic.pop('transaction_index')
        if economic['kind']=='transaction':
            economic['payload']=rpc_economic_transaction(dict(economic['payload'],transactionIndex=0),rich=True)
        return digest(economic)

    @staticmethod
    def _compatible(old,new):
        old=dict(old);new=dict(new)
        old_index=old.pop('transaction_index');new_index=new.pop('transaction_index')
        if old_index is not None and old_index!=new_index:raise EvidenceConflict('candidate_native_order_conflict')
        if old['kind']=='transaction':
            old['payload']=rpc_economic_transaction(dict(old['payload'],transactionIndex=new_index),rich=True)
            new['payload']=rpc_economic_transaction(dict(new['payload'],transactionIndex=new_index),rich=True)
        if old!=new:raise EvidenceConflict('candidate_economic_content_conflict')

    def prove(self,proof):
        """Compact address coverage without unbounded maintenance scope IDs.

        Each point retains its original availability. A later append/repair can
        never make a prospective interval complete before it actually arrived.
        Compression avoids one repeated JSON proof per candidate per block.
        """
        proof.validate();scope=proof.scope
        if not scope.startswith('candidate:'):raise EvidenceUnavailable('candidate_scope_shape')
        from .solana_rolling_history import program_scope
        family=scope.split(':',2)[1]
        rolling_stream=(family in ('pump','pumpswap') and scope==program_scope(family) or
            proof.witness.get('method')=='scoped_native_membership_census_with_linked_child')
        at=float(proof.observed_at);point=[proof.lower_slot,proof.upper_slot,at]
        with self.writer.transaction():
            prior=self.db.execute('''SELECT lo,hi,count,first_available,last_available,points,hash,lineage,source
                FROM candidate_coverage WHERE scope=? ORDER BY lo DESC LIMIT 1''',(scope,)).fetchone()
            append=prior and prior[2]<256 and prior[1]+1==proof.lower_slot and prior[4]<=at and prior[8]==proof.source
            if append:
                points=coverage_points(prior[5],prior[6]);points.append(point)
                lo=prior[0];first=prior[3];lineage=digest([prior[7],proof.witness['lineage_hash']])
            else:points=[point];lo=proof.lower_slot;first=at;lineage=proof.witness['lineage_hash']
            packed=zlib.compress(canonical(points).encode(),1);checksum=hashlib.sha256(packed).hexdigest()
            existing=self.db.execute('SELECT points,hash FROM candidate_coverage WHERE scope=? AND lo=?',(scope,lo)).fetchone()
            if existing and not append:
                # An overlapping later repair stays a distinct version; it may
                # not replace the first point's availability or lineage.
                original=coverage_points(existing[0],existing[1])
                if any(a==point[0] and b==point[1] and available<=at for a,b,available in original):
                    if proof.source=='alchemy_finalized_repair' or rolling_stream:
                        self._repair_gap_segments(proof,at)
                    return
                points=original+[point];packed=zlib.compress(canonical(points).encode(),1)
                checksum=hashlib.sha256(packed).hexdigest();first=min(p[2] for p in points)
            self.db.execute('INSERT OR REPLACE INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',
                (scope,lo,max(p[1] for p in points),len(points),first,at,packed,checksum,lineage,proof.source))
            if proof.source=='alchemy_finalized_repair' or rolling_stream:
                self._repair_gap_segments(proof,at)

    def _repair_gap_segments(self,proof,at):
        """Retain the gap audit and only the still-unproved residual intervals."""
        repaired_at=max(at,float(self.clock()))
        rows=self.db.execute('''SELECT id,lo,hi,created,reason FROM candidate_gaps
            WHERE scope=? AND repaired IS NULL AND lo<=? AND (hi IS NULL OR hi>=?)''',
            (proof.scope,proof.upper_slot,proof.lower_slot)).fetchall()
        for identity,lo,hi,created,reason in rows:
            self.db.execute('UPDATE candidate_gaps SET repaired=? WHERE id=?',(repaired_at,identity))
            residual=[]
            if lo<proof.lower_slot:residual.append((lo,proof.lower_slot-1))
            if hi is None or hi>proof.upper_slot:residual.append((proof.upper_slot+1,hi))
            for a,b in residual:
                self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                    (proof.scope,a,b,created,reason))

    def gap(self,scope,lo,hi,reason):
        with self.writer.transaction():
            self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                (scope,lo,hi,self.clock(),reason))
            from .solana_history_notifications import changed
            changed(self)

    @measured('owner.order_attest')
    def attest_order(self,scope,slot,signature,index):
        checksum=digest([scope,slot,signature,index])
        old=self.db.execute('SELECT transaction_index,hash FROM native_order_attestations WHERE scope=? AND slot=? AND signature=?',(scope,slot,signature)).fetchone()
        if old and tuple(old)!=(index,checksum):raise EvidenceConflict('candidate_native_order_conflict')
        self.db.execute('INSERT OR IGNORE INTO native_order_attestations VALUES(?,?,?,?,?)',(scope,slot,signature,index,checksum))

    def delivery(self,family,transport,*,raw_bytes,rpc_cu=0,calls=0,retained_bytes=0,canonical_bytes=0,ipc_bytes=0,seen=None):
        from .runtime.operating_families import require_active
        require_active(family)
        values=(raw_bytes,retained_bytes,canonical_bytes,ipc_bytes,rpc_cu,calls)
        if any(type(n) is not int or n<0 for n in values):raise EvidenceUnavailable('provider_meter_shape')
        if transport not in ('yellowstone','websocket','rpc'):raise EvidenceUnavailable('provider_meter_transport')
        day=int(self.clock() if seen is None else seen)//86400
        with self.writer.transaction():
            self.db.execute('''INSERT INTO provider_delivery VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day,family,transport) DO UPDATE SET raw_bytes=raw_bytes+excluded.raw_bytes,
                retained_bytes=retained_bytes+excluded.retained_bytes,canonical_bytes=canonical_bytes+excluded.canonical_bytes,
                ipc_bytes=ipc_bytes+excluded.ipc_bytes,rpc_cu=rpc_cu+excluded.rpc_cu,calls=calls+excluded.calls''',
                (day,family,transport,*values))

    def telemetry(self):
        from .runtime.operating_families import active_sql
        live=active_sql('family',solana=True)
        jobs=dict(self.db.execute('SELECT status,COUNT(*) FROM acquisition_jobs WHERE '+live+' GROUP BY status'))
        oldest=self.db.execute("SELECT MIN(created) FROM acquisition_jobs WHERE "+live+" AND status='pending'").fetchone()[0]
        return dict(candidates=self.db.execute('SELECT COUNT(*) FROM market_observations WHERE '+live).fetchone()[0],
            jobs=jobs,oldest_queued_seconds=0 if oldest is None else max(0,self.clock()-oldest),
            deadline_misses=self.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='deadline_missed'").fetchone()[0],
            capacity_pressure=self.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='capacity_pressure'").fetchone()[0])


class CandidateReader:
    """Address coverage over a single shared canonical content store."""
    def __init__(self,reader,family,address):
        self.reader=reader;self.db=reader.db;self.family=family;self.address=address
        binding=self.db.execute('SELECT canonical_scope,coverage_scope,market_address FROM evidence_bindings WHERE family=? AND address=?',(family,address)).fetchone()
        if binding is None:raise EvidenceUnavailable('candidate_binding_incomplete')
        self.base,self.scope,self.market_address=binding
        self.canonical_scope=self.base

    def window(self,scope,lower_slot,upper_slot,*,as_of,address=None,kind='event',limit=10000):
        if scope!=self.scope or address is not None and address!=self.address:
            raise EvidenceUnavailable('candidate_reader_scope_mismatch')
        if not 1<=limit<=10000:raise EvidenceUnavailable('query_bound')
        self.db.execute('BEGIN')
        try:
            if not self.covered(self.scope,lower_slot,upper_slot,as_of=as_of):
                raise EvidenceUnavailable('unresolved_evidence_gap')
            # The proof covers this candidate only. Content identities and first
            # availability remain shared; no global coverage is minted here.
            sql='''SELECT r.body,r.identity,r.hash,r.archive,r.first_seen FROM canonical_evidence r JOIN canonical_addresses a
                ON a.identity=r.identity WHERE a.address=? AND r.scope=?
                AND r.slot BETWEEN ? AND ? AND r.first_seen<=?'''
            args=[self.market_address,self.base,lower_slot,upper_slot,as_of]
            if kind:sql+=' AND r.kind=?';args.append(kind)
            sql+=' ORDER BY r.slot,r.transaction_index,r.event_index,r.identity LIMIT ?'
            rows=self.db.execute(sql,(*args,limit+1)).fetchall()
            if len(rows)>limit:raise EvidenceUnavailable('local_evidence_query_bound')
            result=[];archives={}
            for raw,identity,checksum,archive,available in rows:
                if raw is None:
                    if not archive or not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='scoped_cold_manifests'").fetchone():
                        raise EvidenceUnavailable('evidence_requires_offline_archive_restore')
                    from .solana_scoped_retirement import cold_record
                    item=cold_record(self.db,identity,archive,cache=archives)
                    if item['available']!=available:raise EvidenceConflict('local_evidence_hash_mismatch')
                    row=item['record']
                else:row=decode_body(raw,self.db)
                if digest(row)!=checksum:raise EvidenceConflict('local_evidence_hash_mismatch')
                if row['transaction_index'] is None:
                    native=self.db.execute('''SELECT transaction_index,hash FROM native_order_attestations
                        WHERE scope=? AND slot=? AND signature=?''',(self.base,row['slot'],row['signature'])).fetchone()
                    if native:
                        if native[1]!=digest([self.base,row['slot'],row['signature'],native[0]]):
                            raise EvidenceConflict('candidate_native_order_conflict')
                        row=dict(row,transaction_index=native[0])
                result.append(row)
            return result
        finally:self.db.execute('ROLLBACK')

    def covered(self,scope,lo,hi,*,as_of):
        self.reader._healthy()
        if scope!=self.scope or type(lo) is not int or type(hi) is not int or not 0<=lo<=hi:
            raise EvidenceUnavailable('invalid_query_window')
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='rolling_origins'").fetchone():
            from .solana_rolling_history import RollingHistory
            from types import SimpleNamespace
            view=object.__new__(RollingHistory);view.db=self.db;view.history=SimpleNamespace(clock=lambda:as_of)
            return not view.missing(self.family,scope,lo,hi,as_of=as_of)
        if self.db.execute('''SELECT 1 FROM candidate_gaps WHERE scope=? AND lo<=?
            AND (hi IS NULL OR hi>=?) AND created<=? AND (repaired IS NULL OR repaired>?) LIMIT 1''',
            (scope,hi,lo,as_of,as_of)).fetchone():return False
        intervals=[]
        for packed,checksum in self.db.execute('''SELECT points,hash FROM candidate_coverage
            WHERE scope=? AND hi>=? AND lo<=? AND first_available<=? ORDER BY lo''',(scope,lo,hi,as_of)):
            intervals.extend((a,b) for a,b,at in coverage_points(packed,checksum) if at<=as_of)
        cursor=lo
        for a,b in sorted(intervals):
            if b<cursor:continue
            if a>cursor:return False
            cursor=max(cursor,b+1)
            if cursor>hi:return True
        return False

    def boundary(self,slot,as_of):
        row=self.db.execute('''SELECT MAX(r.slot) FROM canonical_evidence r JOIN canonical_addresses a
            ON a.identity=r.identity WHERE a.address=? AND r.scope=? AND r.kind='transaction'
            AND r.slot<=? AND r.first_seen<=?''',(self.market_address,self.base,slot,as_of)).fetchone()
        return None if not row or row[0] is None else row


def coverage_points(packed,checksum):
    if hashlib.sha256(packed).hexdigest()!=checksum:raise EvidenceConflict('candidate_coverage_corrupt')
    if len(packed)>1024*1024:raise EvidenceUnavailable('candidate_coverage_bound')
    decoder=zlib.decompressobj();raw=decoder.decompress(packed,1024*1024+1)
    if len(raw)>1024*1024 or not decoder.eof:raise EvidenceUnavailable('candidate_coverage_bound')
    points=json.loads(raw)
    if not isinstance(points,list) or not points or len(points)>4096:
        raise EvidenceUnavailable('candidate_coverage_bound')
    return points


class ConsumerReader:
    """Narrow facade: discovery can enumerate content but cannot qualify a market."""
    def __init__(self,reader):
        self.original=reader;self.db=ReadTables(reader.db);self.path=reader.path
    def __getattr__(self,name):return getattr(self.original,name)
    def candidate(self,family,address):return CandidateReader(self.original,family,address)
    def window(self,scope,lo,hi,*,as_of,address=None,kind=None,limit=2048):
        family=next((f for f,s in FAMILIES.items() if s==scope),None)
        if family and address:
            candidate=self.candidate(family,address)
            return candidate.window(candidate.scope,lo,hi,as_of=as_of,address=address,kind=kind,limit=limit)
        raise EvidenceUnavailable('candidate_specific_coverage_required')
    def discovery(self,sequence,*,as_of,limit=5000):
        self.original._healthy()
        if not 1<=limit<=5000:raise EvidenceUnavailable('query_bound')
        original='''SELECT o.sequence,r.body,r.slot,r.identity,r.signature,
            r.transaction_index,r.event_index,r.market_time,r.first_seen FROM candidate_outbox o
            JOIN canonical_evidence r ON r.identity=o.identity WHERE o.scope='program:pump'
            AND o.sequence>? AND o.first_seen<=? ORDER BY o.sequence LIMIT ?'''
        # SQLite distributes this join over every canonical UNION branch. An
        # empty legacy branch otherwise rescans the entire unconsumed outbox,
        # even when the original limit is satisfied by current economics.
        # Materialize only the same bounded ordered prefix, never the market
        # population. Retain the original path for a legacy dangling identity.
        bounded='''WITH pending AS MATERIALIZED (
            SELECT sequence,identity FROM candidate_outbox WHERE scope='program:pump'
            AND sequence>? AND first_seen<=? ORDER BY sequence LIMIT ?)
            SELECT o.sequence,r.body,r.slot,r.identity,r.signature,r.transaction_index,
            r.event_index,r.market_time,r.first_seen,(SELECT COUNT(*) FROM pending)
            FROM pending o JOIN canonical_evidence r ON r.identity=o.identity ORDER BY o.sequence'''
        selected=self.db.execute(bounded,(sequence,as_of,limit)).fetchall()
        if selected and len(selected)==selected[0][-1]:rows=[r[:-1] for r in selected]
        else:rows=self.db.execute(original,(sequence,as_of,limit)).fetchall()
        archives={};result=[]
        for row in rows:
            if row[1] is None:
                # Normalized economics can leave hot storage after durable
                # CandidateHistory publication. A later consumer resolves the
                # same local canonical pointer, without provider reconstruction.
                checksum,archive=self.db.execute('SELECT hash,archive FROM canonical_evidence WHERE identity=?',(row[3],)).fetchone()
                if not archive:raise EvidenceUnavailable('pump_consumer_backlog_archived')
                from .solana_scoped_retirement import cold_record
                item=cold_record(self.db,row[3],archive,cache=archives)
                if digest(item['record'])!=checksum or item['available']!=row[8]:raise EvidenceConflict('local_evidence_hash_mismatch')
                row=(row[0],canonical(item['record']),*row[2:])
            result.append(row)
        return result


class ReadTables:
    """Read-only compatibility for the immutable canonical content views."""
    def __init__(self,db):self.original=db
    def __getattr__(self,name):return getattr(self.original,name)
    def execute(self,sql,params=()):
        import re
        if sql.lstrip().upper().startswith('SELECT'):
            sql=re.sub(r'\brecords\b','canonical_evidence',sql)
            sql=re.sub(r'\baddresses\b','canonical_addresses',sql)
        return self.original.execute(sql,params)
