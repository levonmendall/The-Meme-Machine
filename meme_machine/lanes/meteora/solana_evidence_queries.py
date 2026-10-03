"""Read-only lane views. There is deliberately no RPC fallback in these classes."""
from .solana_evidence_plane import EvidenceUnavailable


class PumpEvidenceView:
    def __init__(self,reader,scope):
        self.reader=reader;self.scope=scope
        self.local_decisions=0;self.blocked_by_gaps=0
        self.foreground_historical_rpc=0

    def events(self,address,*,lower_slot,upper_slot,lower_time,upper_time,as_of):
        # The caller must supply authentic slot boundaries for the requested time
        # interval. Earliest/latest observed trade is never a boundary proof.
        if lower_time>upper_time:
            raise EvidenceUnavailable('invalid_pump_time_window')
        try:
            rows=self.reader.window(self.scope,lower_slot,upper_slot,
                as_of=as_of,address=address,kind='event',limit=10000)
        except EvidenceUnavailable:
            self.blocked_by_gaps+=1
            raise
        events=[]
        for row in rows:
            event=row['payload'].get('event')
            if not isinstance(event,dict) or row['market_time'] is None:
                raise EvidenceUnavailable('pump_normalized_event_missing')
            if not lower_time<=row['market_time']<=upper_time:
                continue
            if event.get('slot')!=row['slot'] or event.get('market_time')!=row['market_time']:
                raise EvidenceUnavailable('pump_event_lineage_mismatch')
            events.append(dict(event))
        self.local_decisions+=1
        return events

    def telemetry(self):
        return dict(decisions_fully_local=self.local_decisions,
                    decisions_blocked_by_gaps=self.blocked_by_gaps,
                    foreground_historical_rpc_count=self.foreground_historical_rpc)


class MeteoraEvidenceView:
    def __init__(self,reader,scope):
        self.reader=reader;self.scope=scope
        self.local_intervals=0;self.blocked_by_gaps=0
        self.historical_reconstruction_rpc=0

    def interval(self,pool,*,start_slot,end_slot,as_of):
        # Preserve the existing verifier's real lower-bound signature witness.
        # Never invent a transaction at start_slot for an empty interval.
        boundary=self.reader.db.execute('''SELECT r.slot FROM addresses a JOIN records r ON r.identity=a.identity
            WHERE a.address=? AND r.scope=? AND r.kind='transaction'
              AND a.slot<=? AND r.first_seen<=?
            ORDER BY a.slot DESC LIMIT 1''',(pool,self.scope,start_slot,as_of)).fetchone()
        if boundary is None:
            raise EvidenceUnavailable('dlmm_signature_census_missing_start_boundary')
        try:
            rows=self.reader.window(self.scope,boundary[0],end_slot,
                as_of=as_of,address=pool,kind='transaction',limit=65)
        except EvidenceUnavailable:
            self.blocked_by_gaps+=1
            raise
        signatures=[];transactions={};witnesses=[]
        for row in rows:
            tx=row['payload'];index=row['transaction_index']
            order=None
            if index is None:
                receipt=self.reader.db.execute('SELECT rank,blockhash FROM stream_order WHERE scope=? AND slot=? AND signature=?',
                    (self.scope,row['slot'],row['signature'])).fetchone()
                if receipt is not None:order=dict(kind='filtered_finalized_block',rank=receipt[0],blockhash=receipt[1],scope=self.scope)
            if ((type(index) is not int and order is None) or tx.get('slot')!=row['slot']
                    or (tx.get('transaction') or {}).get('signatures',[None])[0]!=row['signature']):
                raise EvidenceUnavailable('dlmm_local_transaction_identity_or_order')
            signature=dict(signature=row['signature'],slot=row['slot'],
                transactionIndex=index,blockTime=row['market_time'],
                err=(tx.get('meta') or {}).get('err'),confirmationStatus='finalized')
            if order is not None:signature['transactionOrder']=order
            if row['slot']<=start_slot:
                witnesses.append(signature)
            else:
                signatures.append(signature)
                transactions[row['signature']]=tx
        if not witnesses:
            raise EvidenceUnavailable('dlmm_signature_census_missing_start_boundary')
        key=lambda row:(row['slot'],row['transactionIndex'] if row['transactionIndex'] is not None else row['transactionOrder']['rank'])
        signatures.append(max(witnesses,key=key))
        signatures.sort(key=key,reverse=True)
        self.local_intervals+=1
        return signatures,transactions,dict(source='local_finalized_evidence_plane',
            historical_provider_calls=0,relevant_successful=sum(not s['err'] and s['slot']>start_slot for s in signatures))

    def telemetry(self):
        return dict(intervals_satisfied_locally=self.local_intervals,
                    gaps_blocking_reconstruction=self.blocked_by_gaps,
                    historical_reconstruction_rpc_count=self.historical_reconstruction_rpc)
