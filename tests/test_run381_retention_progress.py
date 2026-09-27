"""Run 381 retention must make durable progress under urgent control work."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile, unittest, sqlite3, pickle, gzip, json, hashlib
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceReader, EvidenceUnavailable, FinalizedRecord, IntervalProof, digest

def record():
 return FinalizedRecord('pump:signature:10:0','pump',10,'signature:10','program',('pool',),10,
                        {'value':1},'alchemy_finalized_stream','a'*64,100)

def proof(lo,hi):
 return IntervalProof('pump',lo,hi,'alchemy_finalized_stream','a'*64,
                      dict(finalized=True,complete=True,scope='pump',lower_slot=lo,upper_slot=hi,
                           lineage_hash=digest(['pump',lo,hi])),100)

class RetentionProgressTests(unittest.TestCase):
 def test_next_snapshot_excludes_durable_predecessor_before_cleanup(self):
  from meme_machine.solana_evidence_service import ServiceState
  from meme_machine.solana_provider_config import AlchemyEndpoint
  with tempfile.TemporaryDirectory() as td:
   state=ServiceState(Path(td)/'db',AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
   try:
    state.writer.ingest([replace(record(),identity='pipeline:%04d'%i) for i in range(1001)])
    snapshot=state.archive_plan();commit,receipt=state.writer.prepare_and_write_archive(state.writer.path,snapshot)
    next_snapshot=state.archive_commit_and_plan(commit,receipt)
    self.assertEqual(len(commit),1000);self.assertEqual(len(next_snapshot['rows']),1)
    self.assertTrue({r['identity'] for r in commit}.isdisjoint(r['identity'] for r in next_snapshot['rows']))
    self.assertEqual(state.storage_metrics.get('retention.calls',0),0)
    self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0],1000)
    self.assertEqual(state.storage_metrics['archive_worker.records.total'],1000)
    state.retention()
    self.assertEqual(state.storage_metrics['retention.calls'],1)
   finally:state.close()

 def test_worker_publishes_identical_archive_and_returns_only_bounded_commit_identity(self):
  from unittest.mock import patch
  from meme_machine import solana_evidence_storage as storage
  with tempfile.TemporaryDirectory() as td:
   writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   try:
    rows=[replace(record(),identity='worker:'+str(i),signature='s:'+str(i),
      payload={'raw_lineage':{'logs':['log'+str(j)+'x'*80 for j in range(100)]}}) for i in range(20)]
    writer.ingest(rows);snapshot=writer.archive_snapshot(1000)
    ordinary=writer.prepare_archive(snapshot);expected=writer.write_archive(writer.path,ordinary)
    with patch.object(storage,'_inflate',wraps=storage._inflate) as inflate:
     commit,receipt=writer.prepare_and_write_archive(writer.path,snapshot)
    self.assertEqual({k:receipt[k] for k in expected},expected)
    self.assertEqual(inflate.call_count,21,'the same immutable log chunk was inflated per record')
    self.assertLess(len(pickle.dumps(commit)),len(pickle.dumps(ordinary))//10)
    self.assertTrue(all(set(r['body'])=={'scope','slot'} for r in commit))
    writer.interest('late-position','pump',lower_slot=10,priority=0,lifecycle='open')
    self.assertEqual(writer.commit_archive(commit,receipt),0)
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],20)
    writer.release('late-position','pump',lifecycle_resolved=True)
    self.assertEqual(writer.commit_archive(commit,receipt),20)
    self.assertEqual(writer.commit_archive(commit,receipt),0)
    archive=Path(str(writer.path)+'.archive')/receipt['name']
    saved=[json.loads(line) for line in gzip.decompress(archive.read_bytes()).splitlines()]
    self.assertEqual(saved,ordinary)
   finally:writer.close()

 def test_empty_filtered_blocks_do_not_skip_bounded_continuity_cleanup(self):
  from meme_machine.solana_evidence_service import ServiceState
  from meme_machine.solana_provider_config import AlchemyEndpoint
  with tempfile.TemporaryDirectory() as td:
   state=ServiceState(Path(td)/'db',AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
   try:
    db=state.writer.db
    db.execute("INSERT INTO cursors VALUES('program:pump',1005,100)")
    db.executemany('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
      [('program:pump',i,i-1,'h'+str(i),'h'+str(i-1),100,'[]','fixture',100,0) for i in range(1,1006)])
    self.assertIsNone(state.maintenance({}))
    self.assertEqual(db.execute('SELECT COUNT(*) FROM stream_receipts').fetchone()[0],0)
    self.assertEqual(db.execute("SELECT value FROM meta WHERE key='retention_floor:program:pump'").fetchone()[0],'1006')
    self.assertEqual(state.storage_metrics['retention.calls'],1)
   finally:state.close()

 def test_archive_publication_preserves_bodies_and_refuses_credentials_before_writing(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db';row=dict(body=record().body(),hash=digest(record().body()),lineage=[dict(source='stream')])
   receipt=EvidenceWriter.write_archive(path,[row]);archive=Path(str(path)+'.archive')/receipt['name']
   self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),receipt['hash'])
   self.assertEqual(json.loads(gzip.decompress(archive.read_bytes())),row)
   self.assertEqual(EvidenceWriter.write_archive(path,[row]),receipt)
   before=list(archive.parent.iterdir())
   with self.assertRaisesRegex(ValueError,'provider_credential_publication_rejected'):
    EvidenceWriter.write_archive(path,[dict(row,secret='https://solana-mainnet.g.alchemy.com/v2/not-a-real-secret')])
   self.assertEqual(list(archive.parent.iterdir()),before)

 def test_interrupted_archive_snapshot_releases_cursor_even_with_retained_traceback(self):
  with tempfile.TemporaryDirectory() as td:
   writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   writer.ingest([replace(record(),identity='cursor:'+str(i)) for i in range(10)])
   class InterruptedDB:
    def __init__(self,db):self.db=db;self.interrupt=True
    def __getattr__(self,key):return getattr(self.db,key)
    def execute(self,sql,*args):
     if self.interrupt and sql.startswith('SELECT scope,slot FROM records'):
      raise sqlite3.OperationalError('interrupted')
     return self.db.execute(sql,*args)
   db=InterruptedDB(writer.db);writer.db=db;held=[]
   try:
    try:writer.archive_snapshot(1000)
    except sqlite3.OperationalError as exc:held.append(exc)
    self.assertEqual(len(held),1);db.interrupt=False
    writer.retain(1000,archive_first=False)
    self.assertEqual(db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()[0],0)
   finally:writer.close()

 def test_bounded_archive_snapshot_survives_hot_gc_and_partial_worker_budget(self):
  with tempfile.TemporaryDirectory() as td:
   writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
   rows=[replace(record(),identity='archive:'+str(i),signature='s:'+str(i),
          payload={'raw_lineage':{'logs':['line'+str(j)+'x'*80 for j in range(80)]}}) for i in range(20)]
   try:
    writer.ingest(rows)
    snapshot=writer.archive_snapshot(1000,max_records=20,max_bytes=2048)
    self.assertLess(len(snapshot['rows']),20)
    self.assertTrue(snapshot['encoded_bytes']<=2048 or len(snapshot['rows'])==1)
    snapshot=pickle.loads(pickle.dumps(snapshot))
    plan=writer.prepare_archive(snapshot,max_bytes=8000)
    self.assertLessEqual(len(plan),len(snapshot['rows']))
    receipt=writer.write_archive(writer.path,plan);self.assertEqual(writer.commit_archive(plan,receipt),len(plan))
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],20-len(plan))
    # All old hot chunks can disappear while a previously admitted snapshot is
    # prepared off-owner. Its exact immutable content remains self-contained.
    writer.retain(1000)
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM hot_chunks').fetchone()[0],0)
    restored=writer.prepare_archive(snapshot,max_bytes=8000)
    self.assertEqual(restored,plan)
    original={r.identity:r.body() for r in rows}
    self.assertTrue(all(r['body']==original[r['identity']] for r in restored))
   finally:writer.close()

 def test_legacy_address_layout_migrates_atomically_and_preserves_exact_queries(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db';writer=EvidenceWriter(path,clock=lambda:1000)
   rows=[replace(record(),identity='row:'+str(i),signature='sig:'+str(i),slot=10+i) for i in range(3)]
   writer.ingest(rows,proof=proof(10,12));writer.close()
   db=sqlite3.connect(path,isolation_level=None)
   definitions=db.execute("SELECT type,name,sql FROM sqlite_master WHERE name IN ('addresses','addresses_insert','addresses_delete','record_storage_delete')").fetchall()
   db.execute('BEGIN')
   for kind,name,sql in definitions:db.execute('DROP '+kind+' IF EXISTS '+name)
   db.execute('CREATE TABLE old_refs(address_id INTEGER,record_id INTEGER,slot INTEGER,PRIMARY KEY(address_id,record_id)) WITHOUT ROWID')
   db.execute('INSERT INTO old_refs SELECT * FROM address_refs');db.execute('DROP TABLE address_refs')
   db.execute('ALTER TABLE old_refs RENAME TO address_refs')
   db.execute('CREATE INDEX address_record ON address_refs(record_id)')
   db.execute('CREATE INDEX address_window ON address_refs(address_id,slot)')
   for kind,name,sql in definitions:db.execute(sql)
   db.execute('COMMIT');before=db.execute('SELECT * FROM addresses ORDER BY identity,address').fetchall();db.close()
   # A failed capacity precheck cannot destroy the old schema or references.
   import meme_machine.solana_evidence_plane as plane
   original=plane.require_storage
   def capacity(path,*,required_bytes=0):
    if required_bytes:raise EvidenceUnavailable('storage_capacity_critical')
    return original(path)
   with patch.object(plane,'require_storage',side_effect=capacity):
    with self.assertRaisesRegex(EvidenceUnavailable,'storage_capacity_critical'):EvidenceWriter(path)
   db=sqlite3.connect(path);self.assertEqual(db.execute('SELECT * FROM addresses ORDER BY identity,address').fetchall(),before);db.close()
   writer=EvidenceWriter(path,clock=lambda:1000);reader=EvidenceReader(path)
   try:
    self.assertEqual(writer.db.execute('SELECT * FROM addresses ORDER BY identity,address').fetchall(),before)
    self.assertEqual({r[1]:r[5] for r in writer.db.execute('PRAGMA table_info(address_refs)')}['record_id'],1)
    self.assertIsNone(writer.db.execute("SELECT name FROM sqlite_master WHERE name='address_record'").fetchone())
    self.assertEqual({r['identity']:r for r in reader.window('pump',10,12,as_of=1000,address='pool')},{r.identity:r.body() for r in rows})
    self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
   finally:reader.close();writer.close()
   writer=EvidenceWriter(path,clock=lambda:1000)
   self.assertEqual(writer.db.execute('SELECT * FROM addresses ORDER BY identity,address').fetchall(),before);writer.close()

 def test_urgent_arrival_cannot_roll_back_every_completed_compaction_slice(self):
  with tempfile.TemporaryDirectory() as td:
   def factory():
    writer=EvidenceWriter(Path(td)/'db',clock=lambda:1000)
    rows=[replace(record(),identity='row:%04d'%i,signature='sig:%04d'%i,slot=i,market_time=i,observed_at=1000,addresses=tuple('address:%d'%j for j in range(32))) for i in range(200)]
    writer.ingest(rows);writer.archive(1000)
    return SimpleNamespace(writer=writer,close=writer.close)
   owner=PriorityOwner(factory);owner.ready.result(5);urgent=[]
   def compact(state):
    def on_statement(sql):
     if not urgent and sql.startswith('DELETE FROM lineage'):
      urgent.append(owner.submit(lambda s:s.writer.db.execute('SELECT 1').fetchone()[0],priority=0))
    state.writer.db.set_trace_callback(on_statement)
    try:state.writer.retain(1000,max_records=128,archive_first=False)
    finally:state.writer.db.set_trace_callback(None)
   try:
    task=owner.submit(compact,priority=4)
    try:task.result(5)
    except EvidenceUnavailable as exc:self.assertEqual(str(exc),'evidence_background_yield')
    self.assertEqual(urgent[0].result(5),1)
    n=owner.submit(lambda s:s.writer.db.execute("SELECT value FROM counters WHERE key='compacted_records'").fetchone(),priority=0).result(5)
    self.assertGreater(n[0] if n else 0,0,'every compaction transaction was rolled back by recurring urgent work')
   finally:owner.close()

if __name__=='__main__':unittest.main()
