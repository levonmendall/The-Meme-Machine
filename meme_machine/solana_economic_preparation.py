"""Bounded local economic preparation, before canonical-owner admission.

This is a decoder product, not consumer-supplied evidence. The owner still
checks its source coordinates, mutable continuity, conflicts and all durable
publication obligations. Optional read-only recipient hints close before CPU
preparation; no database mutation or provider access is permitted here.
"""
from dataclasses import dataclass,replace
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from .solana_evidence_plane import PreparedRecord,EvidenceUnavailable,canonical,digest
from .solana_native_evidence import economic_transaction,signature
from .solana_selective_history import economic_records,SelectiveHistory

MAX_BYTES=32*1024*1024
ARCHIVE_TRANSACTION_BYTES=1024*1024
OUTBOX_PREVIEW_RECIPIENTS=64


def archive_preparation_context(job,endpoint):
    """A reuse key only; mutable lease/coverage remain owner decisions."""
    try:
        coordinates=tuple(job[key] for key in ('id','family','address','lo','hi','priority',
            'deadline','token','pages','last_slot','last_index','lineage'))
        return digest([coordinates,endpoint])
    except Exception:return None


@dataclass(frozen=True)
class PreparedArchiveTransaction:
    context: str
    family: str
    input_hash: str
    events_json: str
    product_hash: str


def prepare_archive_transaction(context,family,raw):
    """One small immutable decode; no clock, SQL or provider access."""
    from .solana_program_decoders import pump_events,pumpswap_trade_events
    if (family not in ('pump','pumpswap') or type(raw) is not str
            or len(raw.encode())>ARCHIVE_TRANSACTION_BYTES):
        raise EvidenceUnavailable('archive_preparation_bound')
    events=(pump_events if family=='pump' else pumpswap_trade_events)(json.loads(raw))
    encoded=canonical(events)
    if len(events)>2048 or len(encoded.encode())>ARCHIVE_TRANSACTION_BYTES:
        raise EvidenceUnavailable('archive_preparation_bound')
    input_hash=hashlib.sha256(raw.encode()).hexdigest()
    return PreparedArchiveTransaction(context,family,input_hash,encoded,
        digest([context,family,input_hash,encoded]))


def archive_prepared_events(product,context,family,tx,*,raw=None):
    """Mismatches take the unchanged decoder, never trust caller evidence.

    ``raw`` is only the same local canonical transaction string already made
    for supplement lookup, after authentication if a supplement changed it.
    These products come from the private pinned decoder, not an untrusted IPC.
    Their unkeyed digest detects mismatch; it grants no evidence authority.
    """
    try:
        if (type(product) is not PreparedArchiveTransaction or context is None
                or product.context!=context or product.family!=family
                or type(product.events_json) is not str
                or len(product.events_json.encode())>ARCHIVE_TRANSACTION_BYTES
                or product.input_hash!=(hashlib.sha256(raw.encode()).hexdigest() if raw is not None else digest(tx))
                or product.product_hash!=digest([context,family,product.input_hash,product.events_json])):
            return None
        events=json.loads(product.events_json)
        return events if type(events) is list and len(events)<=2048 and all(type(e) is dict for e in events) else None
    except Exception:return None


@dataclass(frozen=True)
class SerializedEconomicBatch:
    records: tuple
    products: tuple


def prepare_serialized_economics(rows):
    """Success-only owner-local serialization before the page transaction.

    Failure is deferred to the original ingest point, after its original page
    receipt and lease checks. Keep plain records on the scalar ingestion path.
    """
    try:
        if len(rows)>2048:return None
        products=[];size=0
        for row in rows:
            product=row.serialized_body();size+=len(product[1].encode())
            if size>16*1024*1024:return None
            products.append(product)
        return SerializedEconomicBatch(tuple(rows),tuple(products))
    except Exception:return None


@dataclass(frozen=True)
class PreparedEconomicRecord(PreparedRecord):
    original_raw: str
    original_bytes: int
    economic_hash: str


def prepare_economic_record(record):
    original,raw=record.serialized_body()
    payload=original['payload'];body=original
    if 'raw_lineage' in payload:
        body=dict(original,payload=dict(event=payload['event'],raw_lineage_hash=digest(payload['raw_lineage'])))
    encoded=raw if body is original else canonical(body)
    return PreparedEconomicRecord(replace(record,payload=body['payload']),tuple(body['addresses']),
        hashlib.sha256(encoded.encode()).hexdigest(),len(encoded.encode()),encoded,(),
        raw,len(raw.encode()),SelectiveHistory.content_hash(body))


def coordinates(frame,addresses,session,endpoint):
    b=frame.update.block
    return (endpoint,session,tuple(addresses.items()),b.slot,b.parent_slot,b.blockhash,
        b.parent_blockhash,b.block_time.timestamp,frame.seen,frame.replay_from_slot,
        tuple((sig,index,tuple(scopes),error,available) for sig,index,scopes,error,available
              in frame.candidate_statuses))


@dataclass(frozen=True)
class PreparedCandidateFrame:
    coordinates: tuple
    rows: tuple
    censuses: dict
    census_hashes: dict
    outbox: tuple=()


@dataclass(frozen=True)
class PreparedOutboxRecord:
    record: object
    generation: tuple
    recipients: tuple
    canonical_raw: str
    available: float
    envelope: str
    checksum: str
    identities: tuple


def prepare_outbox(frames,path,endpoint,remaining):
    """Optional bounded hints; every authoritative decision remains in ingest.

    Read only identities/recipients in one short coherent WAL transaction. Close
    the cursor, transaction and connection before envelope/hash CPU or IPC. A
    busy, replaced, old or unavailable store simply retains inline preparation.
    """
    if remaining<=0:return tuple(frames),0
    from .solana_candidate_lifecycle import record_recipients,outbox_hashes
    previews=[];copied=0
    try:
        path=Path(path).resolve();before=path.stat()
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            try:
                session=db.execute('SELECT session FROM prewarm_startup WHERE id=1').fetchone()
                generation=(session,endpoint,before.st_dev,before.st_ino)
                for frame in frames:
                    selected=[]
                    for product in frame.rows:
                        row=product.record
                        if (row.kind!='event' or row.payload['event'].get('event_type') in ('create','migration')
                                or db.execute('SELECT 1 FROM canonical_evidence WHERE identity=?',
                                              (row.identity,)).fetchone()):continue
                        recipients=record_recipients(db,row,rolling=True,limit=OUTBOX_PREVIEW_RECIPIENTS+1)
                        if not recipients or len(recipients)>OUTBOX_PREVIEW_RECIPIENTS:continue
                        size=sum(len(value.encode())+16 for target in recipients for value in target)
                        if copied+size>remaining:continue
                        copied+=size;selected.append((product,tuple(recipients)))
                    previews.append(selected)
                after=path.stat()
                if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):return tuple(frames),0
            finally:db.rollback()
    except (OSError,sqlite3.Error):return tuple(frames),0
    # Products are local pinned decoder output, just like PreparedEconomicRecord.
    # Their checksums grant no source/recipient/availability authority. The fresh
    # owner checks all those inputs before reusing these deterministic bytes.
    results=[];retained=0
    for frame,selected in zip(frames,previews):
        outbox=[]
        for product,recipients in selected:
            available=float(product.record.observed_at) # Exact SQLite REAL affinity on fresh store.
            raw='{"available":'+canonical(available)+',"record":'+product.encoded+'}'
            hashes=tuple(outbox_hashes(family,address,'canonical',raw)
                         for family,address,_ in recipients)
            identities=tuple(value[0] for value in hashes)
            checksum=hashes[0][1] if hashes else hashlib.sha256(raw.encode()).hexdigest()
            size=len(raw.encode())+len(canonical([generation,recipients,identities,checksum]).encode())
            if retained+size>remaining:continue
            retained+=size
            outbox.append(PreparedOutboxRecord(product.record,generation,recipients,
                product.encoded,available,raw,checksum,identities))
        results.append(replace(frame,outbox=tuple(outbox)))
    return tuple(results),retained


def prepare_candidate_frames(frames,addresses,session,endpoint,canonical_path=None,result_limit=MAX_BYTES):
    if not 0<len(frames)<=8:raise EvidenceUnavailable('candidate_commit_batch_bound')
    begun=time.monotonic();cpu=time.thread_time();results=[];size=0
    reverse={scope:address for address,scope in addresses.items()}
    for frame in frames:
        b=frame.update.block
        bodies={signature(tx.signature):economic_transaction(tx,slot=b.slot,
            block_time=b.block_time.timestamp,rich=True) for tx in b.transactions}
        bodies.update({tx['transaction']['signatures'][0]:tx for tx in frame.log_transactions})
        rows={};censuses={scope:[] for scope in addresses.values()}
        for sig,index,scopes,error,available in frame.candidate_statuses:
            for scope in scopes:
                if scope not in reverse:raise EvidenceUnavailable('candidate_required_content_missing')
                address=reverse[scope];family=scope.split(':',2)[1]
                censuses[scope].append([sig,index,error])
                if error is not None:continue
                tx=bodies.get(sig)
                if tx is None:raise EvidenceUnavailable('candidate_required_content_missing')
                for record in economic_records(family,address,tx,endpoint_identity=endpoint,
                        seen=available,source='alchemy_finalized_stream'):
                    prepared=prepare_economic_record(record);previous=rows.get(record.identity)
                    if previous and previous.original_raw!=prepared.original_raw:
                        raise EvidenceUnavailable('candidate_economic_content_conflict')
                    if previous is None:
                        size+=prepared.original_bytes+prepared.byte_count
                        if size>MAX_BYTES:raise EvidenceUnavailable('candidate_preparation_result_bound')
                    rows[record.identity]=prepared
                    if len(rows)>2048:raise EvidenceUnavailable('ingestion_batch_bound')
        key=coordinates(frame,addresses,session,endpoint)
        size+=len(canonical([key,censuses]).encode())
        if size>MAX_BYTES:raise EvidenceUnavailable('candidate_preparation_result_bound')
        results.append(PreparedCandidateFrame(key,tuple(rows.values()),censuses,
            {scope:digest(census) for scope,census in censuses.items()}))
    if canonical_path is not None:
        results,extra=prepare_outbox(results,canonical_path,endpoint,min(MAX_BYTES,result_limit)-size)
        size+=extra
    return tuple(results),dict(cpu_seconds=time.thread_time()-cpu,
        wall_seconds=time.monotonic()-begun,prepared_bytes=size,
        records=sum(len(r.rows) for r in results))
