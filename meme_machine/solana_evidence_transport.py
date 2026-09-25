"""Alchemy-only finalized transport boundary and bounded offline-testable repair.

A subscription notification is authoritative content, NOT an interval-completeness
receipt. Only an adapter with a verified completeness witness can advance coverage.
Public discovery is intentionally not accepted by these interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

from .solana_evidence_plane import (
    EvidenceUnavailable, FinalizedRecord, IntervalProof, digest,
)


@dataclass(frozen=True)
class Subscription:
    owner: str
    scope: str
    address: str
    evidence_class: str
    priority: int

    def request(self, identity):
        if (not self.owner or not self.scope or not self.address
                or self.priority not in range(5)):
            raise EvidenceUnavailable('invalid_subscription_interest')
        if self.evidence_class == 'logs':
            method='logsSubscribe'
            params=[{'mentions':[self.address]}, {'commitment':'finalized'}]
        elif self.evidence_class == 'account':
            method='accountSubscribe'
            params=[self.address, {'commitment':'finalized','encoding':'base64'}]
        elif self.evidence_class == 'transactions':
            method='blockSubscribe'
            params=[{'mentionsAccountOrProgram':self.address},
                {'commitment':'finalized','encoding':'json','transactionDetails':'full',
                 'showRewards':False,'maxSupportedTransactionVersion':1}]
        else:
            raise EvidenceUnavailable('unsupported_evidence_class')
        return dict(jsonrpc='2.0',id=identity,method=method,params=params)


def alchemy_stream_endpoint(http_url):
    parts=urlsplit(http_url)
    if (parts.scheme!='https' or parts.hostname!='solana-mainnet.g.alchemy.com'
            or parts.username or parts.password or parts.port not in (None,443)
            or not parts.path.startswith('/v2/') or len(parts.path)<=4
            or parts.query or parts.fragment):
        raise EvidenceUnavailable('authoritative_alchemy_endpoint_required')
    # Same existing app key, documented streaming host; no app/key mutation.
    return urlunsplit(('wss','solana-mainnet.streaming.alchemy.com',parts.path,'',''))


class FinalizedNotificationDecoder:
    """Decode content without inventing timestamps, transaction indexes or coverage.

    log_decoder is the frozen lane decoder, returning normalized event dictionaries.
    Unsupported/truncated logs become explicit gaps at the caller's stream boundary.
    """
    def __init__(self, *, endpoint_identity, log_decoder=None):
        self.endpoint_identity=endpoint_identity
        self.log_decoder=log_decoder

    def decode(self, subscription, message, observed_at):
        result=message['params']['result']
        expected={'logs':'logsNotification','account':'accountNotification',
                  'transactions':'blockNotification'}[subscription.evidence_class]
        if message.get('method')!=expected:
            raise EvidenceUnavailable('notification_subscription_mismatch')
        if subscription.evidence_class=='transactions':
            value=result['value']
            if value.get('err') is not None or not isinstance(value.get('block'),dict):
                raise EvidenceUnavailable('finalized_block_unavailable')
            slot=value['slot'];block=value['block'];rows=[]
            transactions=block.get('transactions')
            if not isinstance(transactions,list) or len(transactions)>2048:
                raise EvidenceUnavailable('filtered_block_bound')
            for raw in transactions:
                signature=raw['transaction']['signatures'][0]
                body=dict(raw,slot=slot,blockTime=block.get('blockTime'))
                # Enumeration of a filtered response is not the transaction's
                # actual chain index. Missing explicit ordering fails at the reader.
                transaction_index=raw.get('transactionIndex')
                rows.append(FinalizedRecord(
                    f'{subscription.scope}:tx:{signature}',subscription.scope,slot,
                    signature,subscription.address,(subscription.address,),
                    block.get('blockTime'),body,'alchemy_finalized_stream',
                    self.endpoint_identity,observed_at,transaction_index=transaction_index,
                    kind='transaction'))
            return rows
        slot=result['context']['slot'];value=result['value']
        if subscription.evidence_class=='account':
            return [FinalizedRecord(
                f'{subscription.scope}:account:{subscription.address}:{slot}',
                subscription.scope,slot,'',str(value.get('owner') or 'unknown'),
                (subscription.address,),None,value,'alchemy_finalized_stream',
                self.endpoint_identity,observed_at,kind='account')]
        if self.log_decoder is None:
            raise EvidenceUnavailable('frozen_log_decoder_required')
        logs=value.get('logs')
        if not isinstance(logs,list) or any(not isinstance(line,str) or 'truncat' in line.lower() for line in logs):
            raise EvidenceUnavailable('incomplete_finalized_logs')
        events=self.log_decoder(dict(slot=slot,meta=dict(err=value.get('err'),logMessages=logs)))
        rows=[]
        for event in events:
            index=event['index'];signature=value['signature']
            addresses=tuple(sorted({str(event[k]) for k in ('pool','mint','wallet') if event.get(k)}))
            if not addresses:
                raise EvidenceUnavailable('decoded_event_address_missing')
            payload=dict(event=event,raw_lineage=dict(logs=logs,err=value.get('err')))
            rows.append(FinalizedRecord(
                f'{subscription.scope}:{signature}:{index}',subscription.scope,slot,signature,
                subscription.address,addresses,event.get('market_time'),payload,
                'alchemy_finalized_stream',self.endpoint_identity,observed_at,event_index=index))
        return rows


class AddressGapRepair:
    """One bounded page per call, outside strategy processing, no implicit fallback.

    Uses the existing governed RPC interface. Entitlement/unsupported-method errors
    leave the gap unresolved; this code never increases throughput or probes another
    provider. A caller must keep this worker at background/active-gap priority.
    """
    def __init__(self, rpc, writer, *, endpoint_identity, max_pages=16):
        if not 1<=max_pages<=16:
            raise EvidenceUnavailable('repair_page_budget')
        self.rpc=rpc;self.writer=writer
        self.endpoint_identity=endpoint_identity;self.max_pages=max_pages

    def step(self, gap_id, address, *, now, finalized_through):
        row=self.writer.db.execute('SELECT scope,lo,hi,repaired,repair_cursor,pages FROM gaps WHERE id=?',(gap_id,)).fetchone()
        if not row or row[3] is not None or row[2] is None or row[5]>=self.max_pages:
            raise EvidenceUnavailable('repair_not_bounded_or_exhausted')
        scope,lo,hi,_,cursor,pages=row
        # The finalized boundary is supplied by authenticated service state, not
        # inferred from wall time or an empty address-history response.
        if type(finalized_through) is not int or finalized_through < hi:
            raise EvidenceUnavailable('repair_upper_boundary_not_finalized')
        state=json.loads(cursor) if cursor else {'next':None,'page_hashes':[],'signatures':[]}
        cfg=dict(transactionDetails='full',sortOrder='asc',limit=100,
                 commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,
                 filters={'slot':{'gte':lo,'lte':hi}})
        if state['next'] is not None:
            cfg['paginationToken']=state['next']
        # priority=False: current-state/reserved work retains the existing governor's
        # authority. This class never waits for repair from a foreground query.
        result=self.rpc.call('getTransactionsForAddress',[address,cfg],False)
        if not isinstance(result,dict) or not isinstance(result.get('data'),list):
            raise EvidenceUnavailable('address_history_response_shape_unverified')
        data=result['data']
        if len(data)>100:
            raise EvidenceUnavailable('address_history_page_bound')
        records=[];seen=set(state['signatures'])
        for tx in data:
            slot=tx.get('slot');index=tx.get('transactionIndex')
            if type(slot) is not int or not lo<=slot<=hi or type(index) is not int or index<0:
                raise EvidenceUnavailable('repair_order_or_bounds')
            signature=tx['transaction']['signatures'][0]
            if signature in seen:
                raise EvidenceUnavailable('repair_duplicate_signature')
            seen.add(signature)
            records.append(FinalizedRecord(f'{scope}:tx:{signature}',scope,slot,signature,address,
                (address,),tx.get('blockTime'),tx,'alchemy_finalized_repair',
                self.endpoint_identity,now,transaction_index=index,kind='transaction'))
        token=result.get('paginationToken')
        if token is not None and (not isinstance(token,str) or not token or token==state['next']):
            raise EvidenceUnavailable('repair_pagination_stalled')
        page_hashes=state['page_hashes']+[digest(result)]
        # Commit page content, resume cursor and terminal coverage atomically.
        proof = None
        if token is None:
            witness=dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,
                         lineage_hash=digest(page_hashes),method='getTransactionsForAddress',
                         pagination_exhausted=True,page_count=pages+1)
            proof=IntervalProof(scope,lo,hi,'alchemy_finalized_repair',self.endpoint_identity,witness,now)
        self.writer.ingest(records, proof=proof, repair_receipt=(gap_id,
            dict(next=token,page_hashes=page_hashes,signatures=sorted(seen)), self.max_pages))
        return dict(complete=token is None,pages=pages+1,records=len(records))
