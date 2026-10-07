"""Bounded finalized transaction join with an explicit candidate-specific status witness.

An ACK, root, header, count or silence cannot close this join. Every chain index
must have an authenticated status carrying all matching program-filter labels;
every relevant successful body must match that independent identity census.
Failed Pump/PumpSwap attempts have no committed events and need identities only.
Failed Meteora attempts cannot mutate the pool either. Their compact signature/
error/index records preserve canonical identities; a real successful pool witness
remains required by the existing interval view. No failed bodies are requested.
"""
from dataclasses import dataclass,field
import time
import based58
from .solana_evidence_plane import EvidenceUnavailable,digest
from .solana_native_evidence import NativeFrame,signature,transaction_error
from .yellowstone import geyser_pb2 as pb

# Filter names are repeated on every paid update. One-byte routing labels
# suffice; descriptive canonical scope names stay entirely inside the machine.
CONTENT='t'
CENSUS='c'
CONTINUITY='b'
FINALITY='f'
MAX_CHAIN_TRANSACTIONS=8192
MAX_RELEVANT_TRANSACTIONS=2048
MAX_PENDING_SLOTS=256
MAX_PENDING_BYTES=32*1024*1024
MAX_SLOT_BYTES=16*1024*1024
MAX_JOIN_SECONDS=10
FILTERED_REPLAY_CONTRACT='alchemy_finalized_filtered_from_slot_replay_with_target_status_census_and_linked_finalized_child'
REPLAY_OVERLAP_SLOTS=32


def scope_labels(programs):
    return {scope:str(n) for n,scope in enumerate(sorted(set(programs.values())))}


def filter_identity(programs):
    return digest(dict(contract=FILTERED_REPLAY_CONTRACT,commitment='FINALIZED',
        vote=False,successful_content=True,target_statuses=True,programs=sorted(programs.items())))


def candidate_subscription(addresses, from_slot, *, full_addresses=None):
    """One union body feed and address-specific identities, never all statuses."""
    if type(from_slot) is not int or from_slot<=0:
        raise EvidenceUnavailable('candidate_replay_floor_required')
    if not addresses:
        raise EvidenceUnavailable('candidate_addresses_required')
    request=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=from_slot)
    full_addresses=set(addresses if full_addresses is None else full_addresses)
    if not full_addresses.issubset(addresses):raise EvidenceUnavailable('candidate_content_scope')
    if full_addresses:
        request.transactions[CONTENT].vote=False
        request.transactions[CONTENT].failed=False
        request.transactions[CONTENT].account_include.extend(sorted(full_addresses))
    labels=scope_labels(addresses)
    for address,scope in addresses.items():
        status=request.transactions_status[labels[scope]];status.vote=False
        status.account_include.append(address)
    request.blocks_meta[CONTINUITY].SetInParent()
    request.slots[FINALITY].filter_by_commitment=True
    return request


@dataclass(frozen=True)
class YellowstoneTransactionFrame(NativeFrame):
    failed_statuses: tuple=()
    observed_at: dict=field(default_factory=dict)
    status_count: int=0
    continuity_bytes: int=0
    status_bytes: int=0
    content_bytes: int=0
    replay_from_slot: int=0
    log_transactions: tuple=()
    candidate_statuses: tuple=()


class CandidateTransactionJoin:
    """One bounded transient join, never a SQLite owner or market decision maker."""
    def __init__(self,programs,full_programs,*,clock=time.monotonic,filtered_from_slot,max_join_seconds=MAX_JOIN_SECONDS):
        if type(filtered_from_slot) is not int or filtered_from_slot<=0:raise EvidenceUnavailable("candidate_replay_floor_required")
        self.programs=dict(programs);self.full=set(full_programs);self.clock=clock
        if not 0<max_join_seconds<=120:raise EvidenceUnavailable('candidate_join_wait_bound')
        self.max_join_seconds=max_join_seconds
        self.scope_keys={scope:based58.b58decode(address.encode()) for address,scope in programs.items()}
        self.filter_scopes={label:scope for scope,label in scope_labels(programs).items()}
        self.full_scopes={programs[a] for a in self.full}
        self.pending={};self.pending_bytes=0;self.completed=-1
        self.peak_bytes=0;self.peak_slots=0
        self.filtered_from_slot=filtered_from_slot
        self.recent={};self.recent_bytes=0
        self.replay_prefix_bytes=0
        self.early_logs={};self.early_log_bytes=0
        self.recent_logs={}

    def feed_log(self,slot,sig,logs,error,seen):
        """Body-free content; the independent native identity grants its order."""
        if (type(slot) is not int or slot<=0 or not isinstance(sig,str)
                or not isinstance(logs,list) or any(not isinstance(line,str)
                    or 'truncat' in line.lower() for line in logs)):
            raise EvidenceUnavailable('incomplete_finalized_logs')
        fact=(logs,error,seen)
        key=(slot,sig);prior=self.early_logs.get(key)
        if slot<self.filtered_from_slot:return None
        if slot<=self.completed:
            checksum=self.recent_logs.get(key)
            if checksum==digest([logs,error]):return None
            raise EvidenceUnavailable('candidate_late_log_content')
        if prior is not None:
            if prior[:2]!=fact[:2]:raise EvidenceUnavailable('candidate_log_content_conflict')
            return self.drain()
        size=len(str(logs).encode())
        if len(self.early_logs)>=32768 or self.early_log_bytes+size>MAX_PENDING_BYTES:
            raise EvidenceUnavailable('candidate_log_buffer_pressure')
        self.early_logs[key]=fact;self.early_log_bytes+=size
        return self.drain()

    def feed(self,update,size,seen):
        now=self.clock()
        if any(now-s['started']>self.max_join_seconds for s in self.pending.values()):
            raise EvidenceUnavailable('yellowstone_incomplete_status_census')
        kind=update.WhichOneof('update_oneof')
        if kind not in ('transaction','transaction_status','block_meta','slot'):
            raise EvidenceUnavailable('yellowstone_transaction_plane_required')
        labels=set(update.filters);item=getattr(update,kind);slot=item.slot
        if type(size) is not int or not 0<size<=MAX_SLOT_BYTES or not 0<slot:
            raise EvidenceUnavailable('yellowstone_frame_bound')
        if self.filtered_from_slot is not None and slot<self.filtered_from_slot:
            # Alchemy currently includes ~31 earlier finalized slots on replay.
            # Keep their paid-byte cost visible but do no canonical work on them.
            self.replay_prefix_bytes+=size
            return None
        # Later slot notifications can repeat an already-verified finality update.
        # A late body/status is a discontinuity, never silently discarded.
        if slot<=self.completed:
            if kind=='slot' and labels=={FINALITY} and item.status==pb.SLOT_FINALIZED:
                if self.filtered_from_slot is None:return None
                old=self.recent.get(slot)
                if old is not None and item.HasField('parent') and item.parent==old['finality']:return None
            if self.filtered_from_slot is not None:
                old=self.recent.get(slot)
                if old is not None:
                    if kind=='transaction' and labels=={CONTENT} and old['bodies'].get(item.transaction.index)==item.transaction:return None
                    if kind=='block_meta' and labels=={CONTINUITY} and old['meta']==item:return None
                    if kind=='transaction_status' and labels and labels.issubset(self.filter_scopes):
                        scopes=tuple(sorted(self.filter_scopes[label] for label in labels))
                        fact=(bytes(item.signature),item.is_vote,bytes(item.err.err) if item.HasField('err') else None,scopes,item.bank_id)
                        if old['statuses'].get(item.index)==fact:return None
            raise EvidenceUnavailable('yellowstone_late_census_content')
        s=self.pending.setdefault(slot,dict(started=now,statuses={},bodies={},body_seen={},status_seen={},banks=set(),meta=None,finality=None,expected=None,bytes=0,status_bytes=0,content_bytes=0,continuity_bytes=0))
        s['last_seen']=seen
        if item.bank_id:s['banks'].add(item.bank_id)
        if len(s['banks'])>1:raise EvidenceUnavailable('yellowstone_finalized_bank_mismatch')
        s['bytes']+=size;self.pending_bytes+=size
        if len(self.pending)>MAX_PENDING_SLOTS or self.pending_bytes>MAX_PENDING_BYTES or s['bytes']>MAX_SLOT_BYTES:
            raise EvidenceUnavailable('yellowstone_census_buffer_bound')
        self.peak_bytes=max(self.peak_bytes,self.pending_bytes);self.peak_slots=max(self.peak_slots,len(self.pending))
        if kind=='transaction_status':
            valid=(bool(labels) and labels.issubset(self.filter_scopes) if self.filtered_from_slot is not None
                else CENSUS in labels and labels.issubset({CENSUS,*self.filter_scopes}))
            if not valid:
                raise EvidenceUnavailable('yellowstone_status_filter_identity')
            if item.index>=MAX_CHAIN_TRANSACTIONS or len(item.signature)!=64:
                raise EvidenceUnavailable('yellowstone_transaction_index_shape')
            scopes=tuple(sorted(self.filter_scopes[label] for label in labels-{CENSUS}))
            if item.is_vote and scopes:raise EvidenceUnavailable('yellowstone_status_filter_identity')
            err=bytes(item.err.err) if item.HasField('err') else None
            # Unrelated identity/status never gets base58 conversion, error
            # decoding, canonical hashing, compression, IPC or durable storage.
            fact=(bytes(item.signature),item.is_vote,err,scopes,item.bank_id)
            old=s['statuses'].get(item.index)
            if old is not None and old!=fact:raise EvidenceUnavailable('yellowstone_conflicting_status_census')
            s['statuses'][item.index]=fact;s['status_seen'].setdefault(item.index,seen)
            s['status_bytes']+=size
        elif kind=='transaction':
            tx=item.transaction;failed=tx.meta.HasField('err')
            if labels!={CONTENT} or failed or tx.is_vote or tx.index>=MAX_CHAIN_TRANSACTIONS:
                raise EvidenceUnavailable('yellowstone_content_filter_identity')
            old=s['bodies'].get(tx.index)
            if old is not None and old!=tx:
                raise EvidenceUnavailable('yellowstone_conflicting_content')
            if old is None:s['bodies'][tx.index]=tx
            s['body_seen'].setdefault(tx.index,seen);s['content_bytes']+=size
            if len(s['bodies'])>MAX_RELEVANT_TRANSACTIONS:raise EvidenceUnavailable('yellowstone_census_buffer_bound')
        elif kind=='block_meta':
            if labels!={CONTINUITY} or item.executed_transaction_count>MAX_CHAIN_TRANSACTIONS:
                raise EvidenceUnavailable('yellowstone_finalized_block_shape')
            if s['meta'] is not None and s['meta'].SerializeToString()!=item.SerializeToString():
                raise EvidenceUnavailable('yellowstone_conflicting_content')
            s['meta']=item;s['continuity_bytes']+=size
        else:
            if labels!={FINALITY} or item.status!=pb.SLOT_FINALIZED or not item.HasField('parent'):
                raise EvidenceUnavailable('yellowstone_finalized_block_shape')
            if s['finality'] is not None and s['finality']!=item.parent:
                raise EvidenceUnavailable('yellowstone_conflicting_content')
            s['finality']=item.parent;s['continuity_bytes']+=size
        return self.drain()

    def drain(self):
        if not self.pending:return None
        slot=min(self.pending);s=self.pending[slot];seen=s['last_seen'];meta=s['meta']
        if meta is None or s['finality'] is None:return None
        count=meta.executed_transaction_count
        if s['finality']!=meta.parent_slot or not meta.HasField('block_time'):
            raise EvidenceUnavailable('yellowstone_finalized_block_shape')
        if len(s['statuses'])>count:raise EvidenceUnavailable('yellowstone_content_census_mismatch')
        if self.filtered_from_slot is None and len(s['statuses'])!=count:return None
        if s['expected'] is None:
            if self.filtered_from_slot is None:
                if set(s['statuses'])!=set(range(count)):raise EvidenceUnavailable('yellowstone_transaction_index_shape')
            elif any(i>=count for i in set(s['statuses'])|set(s['bodies'])):
                raise EvidenceUnavailable('yellowstone_transaction_index_shape')
            relevant={i:r for i,r in s['statuses'].items() if r[3]}
            if len(relevant)>MAX_RELEVANT_TRANSACTIONS:raise EvidenceUnavailable('yellowstone_census_buffer_bound')
            s['expected']={i:r for i,r in relevant.items() if r[2] is None}
        successful=s['expected']
        required={i:r for i,r in successful.items() if self.full_scopes.intersection(r[3])}
        log_required={i:r for i,r in successful.items() if not self.full_scopes.intersection(r[3])}
        if len(s['bodies'])<len(required):return None
        if not set(s['bodies']).issubset(required):raise EvidenceUnavailable('yellowstone_unfiltered_transaction')
        if set(required)!=set(s['bodies']):return None
        failed=[];seen_by_signature={};identities=set();log_transactions=[];candidate_statuses=[]
        for index,fact in log_required.items():
            sig=signature(fact[0]);log=self.early_logs.get((slot,sig))
            if log is None:return None
            if log[1] is not None:raise EvidenceUnavailable('candidate_log_status_conflict')
            log_transactions.append(dict(slot=slot,blockTime=meta.block_time.timestamp,
                transactionIndex=index,transaction=dict(signatures=[sig]),
                meta=dict(err=log[1],logMessages=log[0])))
        for index,fact in s['statuses'].items():
            sig,vote,err,scopes,bank=fact
            if sig in identities:raise EvidenceUnavailable('yellowstone_duplicate_signature')
            identities.add(sig)
            if not scopes:continue
            text=signature(sig)
            seen_by_signature[text]=s['body_seen'][index] if index in required else (
                max(s['status_seen'][index],self.early_logs[(slot,text)][2]) if index in log_required else s['status_seen'][index])
            candidate_statuses.append((text,index,scopes,None if err is None else transaction_error(err),seen_by_signature[text]))
            if index in required:
                tx=s['bodies'][index]
                keys=set(tx.transaction.message.account_keys)|set(tx.meta.loaded_writable_addresses)|set(tx.meta.loaded_readonly_addresses)
                matches={scope for scope,key in self.scope_keys.items() if key in keys}
                txerr=bytes(tx.meta.err.err) if tx.meta.HasField('err') else None
                if bytes(tx.signature)!=sig or txerr!=err or set(scopes)!=matches:
                    raise EvidenceUnavailable('yellowstone_content_census_mismatch')
            if err is not None:
                decoded=transaction_error(err)
                if decoded is None:raise EvidenceUnavailable('yellowstone_transaction_error_encoding')
                failed.extend((scope,text,index,decoded,s['status_seen'][index]) for scope in scopes)
        # This block-shaped LOCAL join is internal transport compatibility, not
        # an incoming full-block subscription or an inference from a header.
        out=pb.SubscribeUpdate(filters=['meme-machine-relevant'])
        block=out.block;block.slot=slot;block.parent_slot=meta.parent_slot
        block.blockhash=meta.blockhash;block.parent_blockhash=meta.parent_blockhash
        block.block_time.CopyFrom(meta.block_time);block.executed_transaction_count=count
        block.transactions.extend(s['bodies'][i] for i in sorted(s['bodies']))
        result=YellowstoneTransactionFrame(out,s['bytes'],seen,tuple(failed),seen_by_signature,len(s['statuses']),s['continuity_bytes'],s['status_bytes'],s['content_bytes'],self.filtered_from_slot or 0,tuple(log_transactions),tuple(candidate_statuses))
        for index,fact in log_required.items():
            key=(slot,signature(fact[0]));old=self.early_logs.pop(key)
            self.recent_logs[key]=digest([old[0],old[1]])
            self.early_log_bytes-=len(str(old[0]).encode())
        self.pending_bytes-=s['bytes'];del self.pending[slot];self.completed=slot
        if self.filtered_from_slot is not None:
            self.recent[slot]=s;self.recent_bytes+=s['bytes']
            while len(self.recent)>MAX_PENDING_SLOTS or self.recent_bytes>MAX_PENDING_BYTES:
                oldest=min(self.recent);self.recent_bytes-=self.recent.pop(oldest)['bytes']
                self.recent_logs={key:value for key,value in self.recent_logs.items() if key[0]>oldest}
        return result
