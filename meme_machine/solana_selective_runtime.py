"""Candidate-scoped provider interface, without strategy or funding authority."""
import json
import sqlite3
from .solana_evidence_plane import EvidenceUnavailable,decode_body
from .solana_selective_history import ConsumerReader,FAMILIES

CONTROL='control:solana'

def selective(reader):
    if reader is None:return False
    try:
        row=reader.db.execute("SELECT value FROM service_health WHERE key='topology'").fetchone()
        return bool(row and json.loads(row[0])=='candidate_hybrid_v1')
    except sqlite3.Error:return False

class SelectiveRuntime:
    def _selective_reader(self):
        reader=self.reader
        if selective(reader) and not isinstance(reader,ConsumerReader):
            reader=ConsumerReader(reader);self.reader=reader
        return reader

    def health(self,scope):
        reader=self._selective_reader()
        if not selective(reader):return super().health(scope)
        # This is transport/discovery health only. Every economic window below
        # independently requires a complete candidate-specific proof.
        from .solana_evidence_health import evidence_health
        original=reader.original if isinstance(reader,ConsumerReader) else reader
        health=evidence_health(original,CONTROL,self.clock());health=dict(health,scope=scope)
        self.health_observations[scope]=health
        return health

    def frontier(self,scope):
        reader=self._selective_reader()
        if not selective(reader):return super().frontier(scope)
        self.require_usable(scope)
        row=reader.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=? AND available<=?',(CONTROL,self.clock())).fetchone()
        if row is None or row[0] is None:raise EvidenceUnavailable('evidence_cold_start')
        return row[0]

    def bounds(self,scope,lower_time,upper_time,*,upper_slot=None):
        if not selective(self._selective_reader()):return super().bounds(scope,lower_time,upper_time,upper_slot=upper_slot)
        return super().bounds(CONTROL,lower_time,upper_time,upper_slot=upper_slot)

    def pump_events(self,scope,address,lower_time,upper_time,*,upper_slot=None):
        reader=self._selective_reader()
        if not selective(reader):return super().pump_events(scope,address,lower_time,upper_time,upper_slot=upper_slot)
        from .solana_evidence_queries import PumpEvidenceView
        family=next((f for f,s in FAMILIES.items() if s==scope),None)
        if family not in ('pump','pumpswap'):raise EvidenceUnavailable('candidate_reader_scope_mismatch')
        self.require_usable(scope);candidate=reader.candidate(family,address)
        lo,hi=self.bounds(scope,lower_time,upper_time,upper_slot=upper_slot)
        view=PumpEvidenceView(candidate,candidate.scope)
        rows=view.events(address,lower_slot=lo,upper_slot=hi,lower_time=lower_time,upper_time=upper_time,as_of=self.clock())
        self._thread_readers.pump_ordered_records=view.ordered_records
        self.acknowledge(scope,hi)
        return rows

    def meteora_interval(self,pool,start,end):
        reader=self._selective_reader()
        if not selective(reader):return super().meteora_interval(pool,start,end)
        from .solana_evidence_queries import MeteoraEvidenceView
        self.require_usable(FAMILIES['meteora']);candidate=reader.candidate('meteora',pool)
        result=MeteoraEvidenceView(candidate,candidate.scope).interval(pool,start_slot=start,end_slot=end,as_of=self.clock())
        self.acknowledge(FAMILIES['meteora'],end)
        return result

def consume_pump_discovery(tape,sequence):
    """Durably persist source rows before the same outbox checkpoint is returned."""
    from contextlib import closing
    from .runtime.candidate_history import open_candidate_history,order_economic_records
    reader=tape.plane._selective_reader();db=reader.db
    from .solana_prewarm_startup import require_released
    require_released(db)
    db.execute('BEGIN')
    try:
        rows=reader.discovery(sequence,as_of=tape.plane.clock())
        material=[decode_body(r[1],db) for r in rows]
        # Upgraded native-order attestations remain independent of old stored bytes.
        for row in material:
            if row['transaction_index'] is None:
                index=db.execute('SELECT transaction_index FROM native_order_attestations WHERE scope=? AND slot=? AND signature=?',
                    (row['scope'],row['slot'],row['signature'])).fetchone()
                if index:row['transaction_index']=index[0]
        ordered=order_economic_records(material,db,FAMILIES['pump']);orders={r['identity']:i for r,i in ordered}
        native={r['identity']:r['transaction_index'] for r in material}
        events=[];history_rows=[]
        for seq,raw,slot,identity,sig,index,event_index,market_time,available in rows:
            event=dict(decode_body(raw,db)['payload']['event'],_economic_order=orders[identity],available_time=int(available))
            history_rows.append(dict(identity=identity,signature=sig,slot=slot,
                transaction_index=native[identity],
                event_index=event_index,market_time=market_time,event=event))
            if event.get('event_type') not in ('create','migration'):events.append(event)
            sequence=seq
    finally:db.execute('ROLLBACK')
    history=open_candidate_history()
    if history is not None:
        with closing(history):history.retain_pump_source_history(history_rows)
    tape.candidate_history_rows=history_rows
    # Sequence belongs to this outbox, not to a global market slot. Late history
    # below a former discovery slot remains visible on the next durable read.
    return events,sequence
