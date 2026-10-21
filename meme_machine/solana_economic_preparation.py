"""Bounded local economic preparation, before canonical-owner admission.

This is a decoder product, not consumer-supplied evidence. The owner still
checks its source coordinates, mutable continuity, conflicts and all durable
publication obligations. No database or provider is accessed here.
"""
from dataclasses import dataclass,replace
import hashlib
import json
import time
from .solana_evidence_plane import PreparedRecord,EvidenceUnavailable,canonical,digest
from .solana_native_evidence import economic_transaction,signature
from .solana_selective_history import economic_records,SelectiveHistory

MAX_BYTES=32*1024*1024
ARCHIVE_TRANSACTION_BYTES=1024*1024


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


def prepare_candidate_frames(frames,addresses,session,endpoint):
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
    return tuple(results),dict(cpu_seconds=time.thread_time()-cpu,
        wall_seconds=time.monotonic()-begun,prepared_bytes=size,
        records=sum(len(r.rows) for r in results))
