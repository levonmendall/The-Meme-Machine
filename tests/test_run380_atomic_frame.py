"""Run 380 serial-owner work and late-failure rollback, without market access."""
import copy,gzip,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_service import ServiceState
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable

def frame(slot):
 path=Path(__file__).parent/'fixtures/solana_evidence_plane/run380-production-templates.json.gz'
 templates=json.loads(gzip.decompress(path.read_bytes()))['templates']['meteora']
 txs=[]
 for i in range(32):
  tx=copy.deepcopy(templates[i%len(templates)]);tx['transaction']['signatures']=[f'run380:{slot}:{i}'];txs.append(tx)
 msg=dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(slot=slot,err=None,
  block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=int(time.time())-1,transactions=txs)))))
 return Subscription('service','blocks','all','blocks',4),msg,time.time(),len(json.dumps(msg).encode())

class AtomicSourceFrameTests(unittest.TestCase):
 def make_state(self,path):return ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))

 def test_dense_frame_does_not_create_per_record_rollback_boundaries(self):
  with tempfile.TemporaryDirectory() as td:
   state=self.make_state(Path(td)/'db');sql=[]
   try:
    state.writer.db.set_trace_callback(sql.append);self.assertEqual(state.source_batch([frame(1000),frame(1001)]),2)
    state.writer.db.set_trace_callback(None)
    # SQL rollback bookkeeping stays proportional to admitted frames, not their
    # economic-record/address count. The old path creates hundreds of savepoints.
    self.assertLessEqual(sum(s.startswith('SAVEPOINT ') for s in sql),2)
    self.assertEqual(state.writer.db.execute("select count(*) from records where kind='transaction'").fetchone()[0],64)
    reader=EvidenceReader(state.writer.path)
    try:self.assertEqual(len(reader.window('program:meteora',1000,1000,as_of=time.time())),32)
    finally:reader.close()
   finally:state.close()

 def test_late_frame_failure_rolls_back_its_records_but_retains_prior_frame(self):
  with tempfile.TemporaryDirectory() as td:
   state=self.make_state(Path(td)/'db');original=state.writer.ingest
   def fail_after_write(records,**kwargs):
    records=tuple(records);original(records,**kwargs)
    if any(r.slot==1001 and r.kind=='transaction' for r in records):raise EvidenceUnavailable('injected_after_durable_record_work')
   try:
    with patch.object(state.writer,'ingest',fail_after_write):
     with self.assertRaisesRegex(EvidenceUnavailable,'injected_after'):state.source_batch([frame(1000),frame(1001)])
    db=sqlite3.connect(state.writer.path)
    try:
     self.assertEqual(db.execute('select distinct slot from records').fetchall(),[(1000,)])
     self.assertEqual(db.execute("select value from counters where key='stream_accepted_messages'").fetchone(),(1,))
     self.assertEqual(db.execute('pragma integrity_check').fetchone(),('ok',))
    finally:db.close()
    self.assertEqual(state.source_batch([frame(1001)]),1)
    # A failed source frame must not alter ordinary nested command/repair rollback.
    with state.writer.transaction():
     state.writer._count('outer-survives')
     try:
      with state.writer.transaction():state.writer._count('inner-rolled-back');raise ValueError('injected')
     except ValueError:pass
    self.assertIsNone(state.writer.db.execute("select value from counters where key='inner-rolled-back'").fetchone())
    self.assertEqual(state.writer.db.execute("select value from counters where key='outer-survives'").fetchone(),(1,))
   finally:state.close()

class PreparedSourceTests(unittest.TestCase):
 def test_prepared_frame_storage_checks_are_bounded_by_program_scopes(self):
  from meme_machine import solana_evidence_service as service
  from tests.test_run380_production_pressure import Wire
  config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
  raw=Wire().template;seen=time.time()
  prepared,_,_=service.decode_source_message(raw,config.credential,
    tuple(s.address for s in service.program_subscriptions()),config.identity,seen)
  with tempfile.TemporaryDirectory() as td:
   state=service.ServiceState(Path(td)/'db',config)
   try:
    with patch.object(state.writer,'ingest',wraps=state.writer.ingest) as ingest:
     state.source_batch([(Subscription('service','blocks','all','blocks',4),prepared,seen,len(raw))])
    # A dense admitted frame must not repeat filesystem/capacity checks for
    # every transaction. Each bounded program scope has one ingestion unit.
    self.assertLessEqual(ingest.call_count,3)
    self.assertGreater(state.writer.db.execute('select count(*) from records').fetchone()[0],128)
   finally:state.close()

 def test_multi_event_fanout_preserves_the_existing_ingestion_record_bound(self):
  from meme_machine import solana_evidence_service as service
  from meme_machine.solana_evidence_plane import EvidenceWriter
  sub,msg,seen,size=frame(1000)
  address=msg['params']['result']['value']['block']['transactions'][0]['transaction']['message']['accountKeys'][0]
  address=address if isinstance(address,str) else address['pubkey']
  for tx in msg['params']['result']['value']['block']['transactions']:
   tx['meta']['logMessages']=['Program log: synthetic finalized events']
   tx['transaction']['message']['accountKeys']=[address]
  census=Subscription('service','synthetic-census',address,'census',4)
  decode=lambda tx:[dict(index=i,pool='pool',market_time=int(seen)) for i in range(65)]
  prepared=service.prepare_block_scope(census,msg,seen,'a'*64,
    {census.scope:decode},include_logs=True,budget=[service.STREAM_PREPARED_MAX_BYTES])
  self.assertEqual(sum(map(len,prepared['batches'])),2080)
  self.assertTrue(all(len(batch)<=2048 for batch in prepared['batches']))
  with tempfile.TemporaryDirectory() as td:
   writer=EvidenceWriter(Path(td)/'db')
   try:
    with writer.source_frame():
     for batch in prepared['batches']:writer.ingest(batch)
    self.assertEqual(writer.db.execute('select count(*) from records').fetchone()[0],2080)
    with self.assertRaisesRegex(EvidenceUnavailable,'ingestion_batch_bound'):
     writer.ingest(tuple(row for batch in prepared['batches'] for row in batch))
   finally:writer.close()

 def test_shared_pump_codecs_do_not_depend_on_predecessor_lane_helpers(self):
  import hashlib
  from meme_machine import solana_program_decoders as codecs
  path=Path(__file__).parent/'fixtures/solana_evidence_plane/run380-production-templates.json.gz'
  templates=json.loads(gzip.decompress(path.read_bytes()))['templates']['pump']
  # Golden output was computed from the approved integration's original Pump
  # codecs. The Meteora predecessor lacks create_events and has an older trade
  # shape, so neither predecessor helper may own the shared evidence authority.
  with patch.object(codecs.pump,'create_events',create=True,side_effect=AssertionError('legacy_create_codec')), \
       patch.object(codecs.pump,'trade_events',side_effect=AssertionError('legacy_trade_codec')):
   events=[event for tx in templates for event in codecs.pump_events(dict(tx,slot=1000))]
  self.assertEqual(len(events),17)
  self.assertEqual(hashlib.sha256(json.dumps(events,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
    '156e865a72d75311af3cd6c62a749004a95807ccb979950debc818d5542ecc10')

 def test_preparation_is_byte_identical_and_keeps_authority_in_the_owner(self):
  from meme_machine import solana_evidence_service as service
  from meme_machine.solana_evidence_plane import decode_body
  import pickle
  config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
  from tests.test_run380_production_pressure import Wire
  sub,msg,seen,size=frame(1000)
  msg=json.loads(Wire().template);size=len(json.dumps(msg).encode())
  raw=json.dumps(msg).encode();targets=tuple(s.address for s in service.program_subscriptions())
  prepared,_,_=service.decode_source_message(raw,config.credential,targets,config.identity,seen)
  original=prepared
  prepared=pickle.loads(pickle.dumps(original))
  original_rows=[row for scope in original.scopes.values() for batch in scope['batches'] for row in batch]
  wire_rows=[row for scope in prepared.scopes.values() for batch in scope['batches'] for row in batch]
  self.assertTrue(any(row.record.payload for row in original_rows))
  self.assertTrue(all(row.record.payload=={} for row in wire_rows))
  # IPC drops only the redundant parsed tree. The authoritative native bytes,
  # hashes, chunk bodies and record metadata are exactly preserved.
  from dataclasses import replace
  self.assertEqual(wire_rows,[replace(row,record=replace(row.record,payload={})) for row in original_rows])
  self.assertLess(len(pickle.dumps(prepared)),len(pickle.dumps((dict(original),original.__dict__))))
  self.assertIsInstance(prepared,service.PreparedSource)
  self.assertLessEqual(prepared.prepared_bytes,service.STREAM_MAX_MESSAGE_BYTES)
  self.assertEqual(prepared['params']['result']['value']['block']['transactions'],[])
  with tempfile.TemporaryDirectory() as td:
   a=service.ServiceState(Path(td)/'serial',config);b=service.ServiceState(Path(td)/'prepared',config)
   try:
    # Preparation has no authority: only the ordered owner may publish coverage.
    self.assertEqual(b.writer.db.execute('select count(*) from records').fetchone()[0],0)
    a.source_batch([(sub,msg,seen,size)]);b.source_batch([(sub,prepared,seen,size)])
    for table,columns in [('records','identity,hash'),('stream_deliveries','scope,slot,signature,hash'),('addresses','address,identity,slot')]:
     self.assertEqual(a.writer.db.execute('select '+columns+' from '+table+' order by 1,2,3' if table!='records' else 'select '+columns+' from '+table+' order by 1').fetchall(),
                      b.writer.db.execute('select '+columns+' from '+table+' order by 1,2,3' if table!='records' else 'select '+columns+' from '+table+' order by 1').fetchall())
    self.assertEqual([decode_body(r[0],a.writer.db) for r in a.writer.db.execute('select body from records order by identity')],
                     [decode_body(r[0],b.writer.db) for r in b.writer.db.execute('select body from records order by identity')])
    bad=pickle.loads(pickle.dumps(prepared));bad.scopes['program:meteora']['endpoint_identity']='b'*64
    with self.assertRaisesRegex(EvidenceUnavailable,'prepared_source_identity_mismatch'):
     b.source_batch([(sub,bad,seen,size)])
   finally:a.close();b.close()

 def test_prepared_late_failure_rolls_back_frame_and_preserves_prior_durable_order(self):
  from meme_machine import solana_evidence_service as service
  config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
  with tempfile.TemporaryDirectory() as td:
   state=service.ServiceState(Path(td)/'db',config);original=state.writer.ingest;items=[]
   for slot in (1000,1001):
    sub,msg,seen,size=frame(slot)
    prepared,_,_=service.decode_source_message(json.dumps(msg).encode(),config.credential,
      tuple(s.address for s in service.program_subscriptions()),config.identity,seen)
    items.append((sub,prepared,seen,size))
   def fail_late(records,**kwargs):
    rows=tuple(records);original(rows,**kwargs)
    if any(r.record.slot==1001 for r in rows):raise EvidenceUnavailable('prepared_late_failure')
   try:
    with patch.object(state.writer,'ingest',side_effect=fail_late):
     with self.assertRaisesRegex(EvidenceUnavailable,'prepared_late_failure'):state.source_batch(items)
    db=sqlite3.connect(state.writer.path)
    try:self.assertEqual(db.execute('select distinct slot from records').fetchall(),[(1000,)])
    finally:db.close()
    state.source_batch([items[1]])
    state.writer.gap('program:meteora',1000,1000,'explicit_test_gap')
    reader=EvidenceReader(state.writer.path)
    try:
     with self.assertRaises(EvidenceUnavailable):reader.window('program:meteora',1000,1000,as_of=time.time())
    finally:reader.close()
   finally:state.close()

 def test_preparation_budget_falls_back_without_changing_content(self):
  from meme_machine import solana_evidence_service as service
  config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
  sub,msg,seen,size=frame(1000);raw=json.dumps(msg).encode()
  with patch.object(service,'STREAM_PREPARED_MAX_BYTES',1):
   prepared,_,_=service.decode_source_message(raw,config.credential,tuple(s.address for s in service.program_subscriptions()),config.identity,seen)
  import pickle
  prepared=pickle.loads(pickle.dumps(prepared))
  self.assertIsNone(prepared.scopes)
  self.assertEqual(prepared,msg)
  with tempfile.TemporaryDirectory() as td:
   state=service.ServiceState(Path(td)/'db',config)
   try:
    state.source_batch([(sub,prepared,seen,size)])
    self.assertEqual(state.writer.db.execute('select count(*) from records').fetchone()[0],32)
   finally:state.close()

if __name__=='__main__':unittest.main()
