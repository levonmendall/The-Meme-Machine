"""Authenticate exceptional complete logs against native finalized witnesses.

This module fetches nothing and decodes no economics. Truncated log strings
never become complete evidence; a separate managed getTransaction response is
bound to native order, program membership and the observed WS prefix/suffix.
"""
import copy
import hashlib

from .solana_evidence_plane import EvidenceUnavailable,canonical,digest
from .solana_candidate_join import CandidateTransactionJoin
from .solana_selective_history import (
    complete_archive_transaction,join_archive_log_supplement,rpc_economic_transaction,
)

FATAL_REPAIR_REASONS=frozenset(('candidate_stream_log_supplement_incomplete',
    'candidate_stream_log_supplement_identity_unverified','incomplete_finalized_logs'))


def explicit_truncation(logs):
    return (type(logs) is list and all(type(line) is str for line in logs)
        and logs.count('Log truncated')==1
        and not any('truncat' in line.lower() and line!='Log truncated' for line in logs))


def log_input_reason(logs):
    """Fixed shape categories; never include packet strings in public errors."""
    if logs is None:return 'candidate_stream_logs_null_or_missing'
    if type(logs) is not list:return 'candidate_stream_logs_not_array'
    if any(type(line) is not str for line in logs):return 'candidate_stream_logs_nonstring'
    if explicit_truncation(logs):return 'candidate_stream_logs_explicit_marker'
    if any('truncat' in line.lower() for line in logs):return 'candidate_stream_logs_truncation_text'
    return 'candidate_stream_logs_complete_array'


def rebase_log_join(join,floor):
    """Carry buffered packets across a verified live subscription boundary."""
    replacement=CandidateTransactionJoin(join.programs,join.full,clock=join.clock,
        filtered_from_slot=floor,max_join_seconds=120)
    for (slot,sig),(logs,error,seen) in tuple(join.early_logs.items()):
        if (slot,sig) in join.incomplete_logs:replacement.defer_log(slot,sig,logs,seen)
        else:replacement.feed_log(slot,sig,logs,error,seen)
        if slot>=floor and (slot,sig) in join.recent_incomplete_logs:
            replacement.recent_incomplete_logs[(slot,sig)]=join.recent_incomplete_logs[(slot,sig)]
        if slot>=floor and (slot,sig) in join.deferred_complete_logs:
            replacement.deferred_complete_logs[(slot,sig)]=join.deferred_complete_logs[(slot,sig)]
    return replacement


def authenticate_supplement(join,witness,fetched,endpoint_identity):
    """Return complete original-order logs and a durable provider-input receipt."""
    try:
        slot,sig,index=(witness[key] for key in ('slot','signature','transaction_index'))
        key=(slot,sig)
        if join.deferred_log_witness(slot,sig)!=witness:raise KeyError()
        observed=join.early_logs[key][0]
        if not explicit_truncation(observed) or type(fetched) is not dict:raise KeyError()
        logs=fetched['meta']['logMessages']
        if type(logs) is list and any(type(line) is str and 'truncat' in line.lower() for line in logs):
            raise EvidenceUnavailable('candidate_stream_log_supplement_incomplete')
        if (fetched['slot']!=slot or type(fetched['slot']) is not int
                or fetched['blockTime']!=witness['block_time'] or type(fetched['blockTime']) is not int
                or fetched['transaction']['signatures'][0]!=sig or fetched['meta']['err'] is not None
                or 'transactionIndex' in fetched and fetched['transactionIndex']!=index):raise KeyError()
        # getTransaction does not supply chain transaction order. Only the
        # independently delivered finalized native status supplies this index.
        ordered=dict(fetched,transactionIndex=index)
        normalized=rpc_economic_transaction(ordered,rich=False)
        keys=set(normalized['transaction']['message']['accountKeys'])
        scopes={scope for address,scope in join.programs.items() if address in keys}
        if scopes!=set(witness['scopes']):raise KeyError()
        original=copy.deepcopy(ordered);original['meta']['logMessages']=list(observed)
        supplement=join_archive_log_supplement(original,fetched,endpoint_identity=endpoint_identity)
        complete=complete_archive_transaction(original,supplement,endpoint_identity=endpoint_identity)
        other=join.deferred_complete_logs.get(key)
        if other is not None and other!=digest([complete['meta']['logMessages'],None]):raise KeyError()
        raw=canonical(fetched);partial=canonical(observed)
        receipt=dict(method='getTransaction',commitment='finalized',endpoint_identity=endpoint_identity,
            native_witness=witness,observed_websocket_logs=list(observed),response=fetched,
            observed_websocket_seen=join.early_logs[key][2],
            websocket_logs_sha256=hashlib.sha256(partial.encode()).hexdigest(),
            response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            complete_log_sha256=hashlib.sha256(canonical(complete['meta']['logMessages']).encode()).hexdigest(),
            native_order_preserved=True,truncated_logs_used_as_complete=False)
        return complete['meta']['logMessages'],receipt
    except EvidenceUnavailable as error:
        if str(error) in FATAL_REPAIR_REASONS:raise
    except (KeyError,IndexError,TypeError,ValueError):pass
    raise EvidenceUnavailable('candidate_stream_log_supplement_identity_unverified') from None
