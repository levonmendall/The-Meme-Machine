"""Bounded witnesses: actual native source, selectors, mutators and SQLite reads.

SQLite has no public transaction UUID. The qualification trace names each outer
BEGIN/COMMIT by its ordered statement hashes, database identity and generation.
Independent connections establish that its effects are committed. No trace or
observer writes a record, floor, counter, progress ledger or receipt.
"""
from contextlib import contextmanager, closing
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from . import HELD_READER
from .clock import DeterministicClock, validate_clock_samples
from .contract import canonical, sha256
from .fixtures import build_frame, spec

ENDPOINT = 'https://solana-mainnet.g.alchemy.com/v2/offline-test'
SCOPES = ('program:pump','program:meteora','program:pumpswap')


class TransactionTrace:
    def __init__(self, writer, generation, database_id):
        self.writer = writer; self.generation = generation; self.database_id = database_id
        self.active = None; self.commits = []; self.attempts = []; self.ordinal = 0
        writer.db.set_trace_callback(self.capture)

    def capture(self, sql):
        if sql == 'BEGIN IMMEDIATE':
            self.ordinal += 1; self.active = dict(ordinal=self.ordinal, statements=[])
        if self.active is not None:
            self.active['statements'].append(sha256(sql.encode()))
            if sql in ('COMMIT','ROLLBACK'):
                row = dict(self.active, generation=self.generation, database_id=self.database_id,
                           committed=sql=='COMMIT')
                row['transaction_id'] = sha256(canonical(row))
                self.attempts.append(row)
                if row['committed']:
                    self.commits.append(row)
                self.active = None

    def close(self):
        self.writer.db.set_trace_callback(None)


@contextmanager
def native_state(path, clock):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_provider_config import AlchemyEndpoint
    with patch.object(service, 'time', clock):
        state = service.ServiceState(path, AlchemyEndpoint.parse(ENDPOINT))
        state.writer.clock = clock.time
        try:
            yield state
        finally:
            state.close()


def empty_frame(slot, at):
    return canonical(dict(method='blockNotification',params=dict(result=dict(value=dict(
        slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),
            previousBlockhash='h'+str(slot-1),blockTime=at,transactions=[]))))))


def source(state, raw, clock):
    from meme_machine import solana_evidence_service as service
    from meme_machine.solana_evidence_transport import Subscription
    targets = tuple(sorted({s.address for s in service.program_subscriptions()}))
    decoded, total, retained = service.decode_source_message(raw, '', targets,
        state.fence.endpoint_identity, clock.time())
    sub = Subscription('service','all','all','blocks',4)
    state.source(sub, decoded, clock.time(), len(raw))
    return dict(source_transactions=total, retained_transactions=retained)


def snapshot(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        records = [dict(identity=i,hash=h,scope=s,slot=slot,body_present=body is not None,archive=archive,
                        event_at=at,first_seen=seen)
            for i,h,s,slot,body,archive,at,seen in db.execute(
                'SELECT identity,hash,scope,slot,body,archive,market_time,first_seen FROM records ORDER BY identity')]
        return dict(records=records, floors=dict(db.execute("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'")),
            progress=[list(r) for r in db.execute('SELECT scope,side,at,units,record_at,records FROM maintenance_progress ORDER BY scope,side')],
            episodes=[list(r) for r in db.execute('SELECT * FROM maintenance_episodes ORDER BY scope,side')],
            counters=dict(db.execute('SELECT key,value FROM counters')),
            coverage=[list(r) for r in db.execute('SELECT scope,lo,hi,available FROM coverage ORDER BY scope,lo')],
            gaps=db.execute('SELECT count(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0])


def transitions(output, *, held=False):
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_queries import PumpEvidenceView, MeteoraEvidenceView
    from meme_machine.solana_maintenance_runtime import MaintenanceRuntime
    # All bytes, including the later finalized source clocks, are fixed in setup.
    clock = DeterministicClock()
    initial = tuple(build_frame('run380', n, bounded=True) for n in range(3))
    tail = tuple(empty_frame(1003+n,clock.wall_epoch+185+n) for n in range(3))
    assert clock.elapsed_us == 0 and not clock.executing
    path = Path(output)/'native.sqlite'; reader = None
    with native_state(path,clock) as state:
        clock.begin()
        clock_samples=[]
        def clock_sample():
            durable=snapshot(path)
            frontiers=[json.loads(value)['time'] for value, in state.writer.db.execute(
                "SELECT value FROM service_health WHERE key LIKE 'finalized_frontier:%'")]
            clock_samples.append(dict(wall=clock.time(),monotonic=clock.monotonic(),
                source=min(frontiers),economic_now=clock.time(),residence_now=clock.time(),
                records=[dict(identity=r['identity'],event_at=r['event_at'] if r['event_at'] is not None else r['first_seen'])
                         for r in durable['records']]))
        for n, raw in enumerate(initial):
            clock.advance_to(n*270_000); source(state,raw,clock);clock_sample()
        before_source = snapshot(path)
        pump = PumpEvidenceView(__import__('meme_machine.solana_evidence_plane',fromlist=['EvidenceReader']).EvidenceReader(path),'program:pump')
        meteora = MeteoraEvidenceView(pump.reader,'program:meteora')
        try:
            p = pump.reader.db.execute("SELECT a.address FROM addresses a JOIN records r ON r.identity=a.identity WHERE r.scope='program:pump' LIMIT 1").fetchone()[0]
            events = pump.events(p,lower_slot=1000,upper_slot=1001,lower_time=clock.wall_epoch-1,
                upper_time=clock.wall_epoch+1,as_of=clock.time())
            assert events
            # Native filtering excludes a foreign address; no injected demand vector.
            excluded = pump.events('not-the-candidate',lower_slot=1000,upper_slot=1001,
                lower_time=clock.wall_epoch-1,upper_time=clock.wall_epoch+1,as_of=clock.time())
            assert excluded == []
            pool = pump.reader.db.execute("SELECT a.address FROM addresses a JOIN records r ON r.identity=a.identity WHERE r.scope='program:meteora' LIMIT 1").fetchone()[0]
            signatures, transactions, info = meteora.interval(pool,start_slot=1000,end_slot=1001,as_of=clock.time())
            assert signatures and transactions and info['historical_provider_calls']==0
            try:
                meteora.interval('not-the-candidate',start_slot=1000,end_slot=1001,as_of=clock.time())
                raise AssertionError('foreign_meteora_candidate_selected')
            except __import__('meme_machine.solana_evidence_plane',fromlist=['EvidenceUnavailable']).EvidenceUnavailable:
                pass
            selection = dict(pump=dict(candidate=p,selected_events=events,excluded_candidate='not-the-candidate',
                exclusion='native address join',generation=state.fence.session,telemetry=pump.telemetry()),
                meteora=dict(candidate=pool,signatures=signatures,selected_transactions=sorted(transactions),
                    exclusion='native missing start boundary',generation=state.fence.session,telemetry=meteora.telemetry()))
        finally:
            pump.reader.close()
        clock.advance_to(185_000_000)
        source(state,tail[0],clock);clock_sample()
        clock.advance_to(186_000_000);source(state,tail[1],clock);clock_sample()
        clock.advance_to(187_000_000);source(state,tail[2],clock);clock_sample()
        validate_clock_samples(clock_samples,spec('run380')['clock'])
        assert snapshot(path)['counters']['stream_accepted_messages'] > before_source['counters']['stream_accepted_messages']
        generation = state.fence.session
        runtime = MaintenanceRuntime(state,monotonic=clock.monotonic,wall=clock.time)
        observation = runtime.adapter.observe(generation)
        assert observation.generation == generation
        for scope in SCOPES:
            assert state.writer.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(scope,)).fetchone()[0] == 1004
        # Keep native pin exclusions visible in selection; no direct SQL mutator.
        for scope in ('program:pump','program:meteora'):
            state.writer.interest('v2-pinned-candidate',scope,lower_slot=1001)
        snapshot_input = state.archive_plan()
        plan, receipt = EvidenceWriter.prepare_and_write_archive(path,snapshot_input)
        assert plan and receipt and all(row['body']['slot']==1000 for row in plan if row['body']['scope'] in ('program:pump','program:meteora'))
        hot = snapshot(path)
        ids = [row['identity'] for row in plan]
        assert all(row['body_present'] for row in hot['records'] if row['identity'] in ids)
        trace = TransactionTrace(state.writer,generation,'native.sqlite')
        held_proof = None
        if held:
            reader = sqlite3.connect(path,isolation_level=None)
            reader.execute('PRAGMA query_only=ON');reader.execute('BEGIN')
            # BEGIN alone does not establish a snapshot. This read does.
            query = 'SELECT identity,hash,body,archive FROM records ORDER BY identity'
            established = reader.execute(query).fetchall()
            assert established
            established_hash = sha256(canonical([[i,h,sha256(body) if body is not None else None,a]
                for i,h,body,a in established]))
            read_id = sha256(canonical(dict(query=query,result_hash=established_hash,generation=generation,
                before_writer_commit_ordinal=trace.ordinal)))
        start = len(trace.commits)
        state.archive_commit_slice(plan,receipt)
        archived = snapshot(path)
        archive_commits = trace.commits[start:]
        assert archive_commits
        archive_file=path.parent/(path.name+'.archive')/receipt['name']
        assert archive_file.is_file() and sha256(archive_file.read_bytes())==receipt['hash']
        archived_ids = {r['identity'] for r in archived['records'] if not r['body_present']}
        assert set(ids) <= archived_ids
        for scope in ('program:pump','program:meteora'):
            state.writer.release('v2-pinned-candidate',scope)
        before_retirement = snapshot(path); start = len(trace.commits)
        outcome = state.retention()  # Floor publication and retirement may share the transaction.
        retired = snapshot(path); retirement_commits = trace.commits[start:]
        retired_ids = set(ids)-{r['identity'] for r in retired['records']}
        assert retired_ids and retired_ids <= set(ids) and outcome.retired_records >= len(retired_ids) and outcome.committed_slices > 0
        assert {'program:pump','program:meteora'} <= {r['scope'] for r in before_retirement['records'] if r['identity'] in retired_ids}
        assert retirement_commits and any(r[1]=='retirement' and r[-1]>0 for r in retired['progress'])
        assert all(int(retired['floors']['retention_floor:'+r['scope']]) > r['slot'] for r in before_retirement['records'] if r['identity'] in retired_ids)
        if held:
            assert reader.execute(query).fetchall() == established
            blocked = EvidenceWriter.checkpoint(path)
            blocked_finish = state.writer.finish_checkpoint()
            assert blocked[1]>blocked[2] and blocked_finish[0]==1
            reader.execute('ROLLBACK')
            after_release = reader.execute(query).fetchall()
            assert after_release != established
            completed = EvidenceWriter.checkpoint(path)
            finish = state.writer.finish_checkpoint()
            assert completed[0]==0 and completed[1]==completed[2] and finish==(0,0,0)
            assert reader.execute('PRAGMA integrity_check').fetchone()==('ok',)
            reader.close(); reader=None
            held_proof = dict(contract=HELD_READER,generation=generation,snapshot_read_id=read_id,
                snapshot_query=query,snapshot_result_hash=established_hash,
                established_before_transaction=archive_commits[0]['transaction_id'],
                held_across_transactions=[r['transaction_id'] for r in archive_commits+retirement_commits],
                snapshot_preserved=True,reader_released=True,passive_while_held=list(blocked),
                truncate_while_held=list(blocked_finish),passive_after_release=list(completed),
                truncate_after_release=list(finish),integrity='ok')
        trace.close()
        return dict(generation=generation,clock_samples=clock_samples,input_record_identities=ids,retired_record_identities=sorted(retired_ids),source_before=before_source,
            source_after=retired,selection=selection,hot_before=hot,archived_after=archived,
            archive_receipt=receipt,durable_archive_hash=sha256(archive_file.read_bytes()),archive_transactions=archive_commits,
            retirement_before=before_retirement,retired_after=retired,
            retirement_transactions=retirement_commits,retention_outcome=vars(outcome),
            native_observation=dict(generation=observation.generation,wall=observation.wall,
                monotonic=observation.monotonic,scopes=[vars(s) for s in observation.scopes]),
            held_reader=held_proof,integrity=retired['integrity'])
