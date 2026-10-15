"""In-command body reuse preserves authenticated bytes and all refusal paths."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_plane import FinalizedRecord,EvidenceUnavailable,EvidenceConflict,canonical,digest
from meme_machine.solana_selective_history import economic_records,PROGRAMS
from tests.test_solana_closure import NOW,state_at
from tests.test_solana_selective_evidence import FIXTURE


class RollingSerializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.state,self.history=state_at(self.path)
        self.addCleanup(lambda:self.state.writer.close())
        self.rows=economic_records('pump',PROGRAMS['pump'],FIXTURE['pump'][0],
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')

    def test_grouped_event_outbox_matches_scalar_sequence_and_replay_availability(self):
        from types import MethodType
        from meme_machine.solana_economic_preparation import prepare_economic_record
        original,h=state_at(Path(self.tmp.name)/'scalar-outbox.sqlite')
        def scalar(target,rows):
            for row in rows:
                if row.kind!='event':continue
                available=target.db.execute('SELECT first_seen FROM canonical_evidence WHERE identity=?',(row.identity,)).fetchone()[0]
                target.db.execute('''INSERT OR IGNORE INTO candidate_outbox
                    SELECT COALESCE(MAX(sequence)+1,4611686018427387904),?,?,?,?
                    FROM candidate_outbox''',(row.identity,row.scope,row.slot,available))
        h._queue_events=MethodType(scalar,h)
        try:
            base=self.rows[0]
            products=[prepare_economic_record(replace(base,identity='outbox-'+str(n),slot=base.slot+n,
                signature='outbox-signature-'+str(n),observed_at=NOW+n)) for n in range(64)]
            for target in (h,self.history):
                target.ingest(products[:8])
                target.db.execute('DELETE FROM candidate_outbox WHERE identity=?',('outbox-3',))
                target.ingest([products[3],*products[8:],products[2],products[3]])
                target.ingest([prepare_economic_record(replace(products[2].record,observed_at=NOW+100))])
            for table in ('candidate_outbox','candidate_content_receipts','native_order_attestations'):
                self.assertEqual(self.history.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),
                    h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall(),table)
            self.assertEqual(self.history.db.execute('SELECT first_seen FROM candidate_outbox WHERE identity=?',('outbox-2',)).fetchone(),(NOW+2,))
            # Failure after allocation rolls back sequence and content together.
            before=self.history.db.execute('SELECT * FROM candidate_outbox ORDER BY sequence').fetchall()
            with self.assertRaisesRegex(RuntimeError,'after_outbox'):
                with self.history.writer.transaction():
                    self.history.db.execute("DELETE FROM candidate_outbox WHERE identity='outbox-0'")
                    self.history._queue_events([products[0].record])
                    raise RuntimeError('after_outbox')
            self.assertEqual(self.history.db.execute('SELECT * FROM candidate_outbox ORDER BY sequence').fetchall(),before)
        finally:original.writer.close()

    def test_one_validated_snapshot_retains_hash_addresses_and_original_availability(self):
        calls=[];original=FinalizedRecord.serialized_body
        expected={}
        for r in self.rows:
            body=r.body();p=body['payload']
            if 'raw_lineage' in p:body=dict(body,payload=dict(event=p['event'],raw_lineage_hash=digest(p['raw_lineage'])))
            expected[r.identity]=body
        def capture(row):calls.append(row.identity);return original(row)
        with patch.object(FinalizedRecord,'serialized_body',capture):self.history.ingest(self.rows)
        self.assertEqual(calls,[r.identity for r in self.rows])
        for r in self.rows:
            raw,hash_value,seen=self.history.db.execute(
                'SELECT body,hash,first_seen FROM rolling_economic_events WHERE identity=?',(r.identity,)).fetchone()
            self.assertEqual((raw,hash_value,seen),(canonical(expected[r.identity]),digest(expected[r.identity]),NOW))
            self.assertEqual({a for a, in self.history.db.execute(
                'SELECT address FROM rolling_economic_addresses WHERE identity=?',(r.identity,))},set(r.addresses))
        before=self.history.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall()
        self.history.ingest([replace(r,observed_at=NOW+10) for r in self.rows])
        self.state.writer.close();self.state,self.history=state_at(self.path)
        self.assertEqual(self.history.db.execute('SELECT identity,hash,first_seen FROM rolling_economic_events ORDER BY identity').fetchall(),before)

    def test_payload_change_on_next_ingest_is_revalidated_and_conflicts(self):
        self.history.ingest(self.rows);r=self.rows[0]
        changed=replace(r,payload=dict(r.payload,event=dict(r.payload['event'],changed_economic_value=1)))
        with self.assertRaisesRegex(EvidenceConflict,'candidate_economic_content_conflict'):
            self.history.ingest([changed])
        self.assertFalse(self.history.db.in_transaction)

    def test_credentials_shapes_and_actual_batch_bytes_still_fail_before_publication(self):
        r=self.rows[0]
        for bad in (replace(r,source='authorization=secret'),
                    replace(r,payload={'event':{},'extra':'api_key=secret'})):
            with self.assertRaisesRegex(ValueError,'credential'):
                self.history.ingest([bad])
        with self.assertRaisesRegex(EvidenceUnavailable,'invalid_finalized_record'):
            self.history.ingest([replace(r,transaction_index=-1)])
        with self.assertRaisesRegex(EvidenceUnavailable,'ingestion_batch_bound'):
            self.history.ingest([replace(r,payload={'event':{},'extra':'x'*(16*1024*1024)})])
        self.assertEqual(self.history.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)

    def test_direct_store_validates_and_retired_exact_body_is_restored_without_new_availability(self):
        r=self.rows[0]
        with self.assertRaisesRegex(ValueError,'credential'):
            self.history.rolling.store(replace(r,payload={'bad':'authorization=secret'}))
        self.history.ingest([r]);before=self.history.db.execute(
            'SELECT hash,first_seen,body FROM rolling_economic_events WHERE identity=?',(r.identity,)).fetchone()
        with self.history.writer.transaction():
            self.history.db.execute('UPDATE rolling_economic_events SET body=NULL,archive=? WHERE identity=?',('retained',r.identity))
        self.history.ingest([replace(r,observed_at=NOW+20)])
        after=self.history.db.execute('SELECT hash,first_seen,body FROM rolling_economic_events WHERE identity=?',(r.identity,)).fetchone()
        self.assertEqual(after,before)
        self.assertEqual(self.history.db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    def test_page_reuse_keeps_exact_original_input_and_lineage_hashes(self):
        import meme_machine.solana_selective_history as module
        self.history.request('pump','mint',1,2,priority=3,deadline=NOW+100)
        job,_=self.history.plan()
        value=dict(data=[],paginationToken='next-\"-é',note={'escaped':'a\\b'})
        expected_input=digest([job['token'],value])
        expected_lineage=digest([job['lineage'],digest(value)])
        original=module.canonical;calls=[]
        def capture(body):
            if body is value:calls.append(body)
            return original(body)
        with patch.object(module,'canonical',capture):
            first=self.history.commit_page(job,value,finalized_through=2)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.history.db.execute('SELECT input_hash FROM acquisition_page_receipts WHERE job=?',(job['id'],)).fetchone()[0],expected_input)
        self.assertEqual(self.history.db.execute('SELECT lineage FROM acquisition_jobs WHERE id=?',(job['id'],)).fetchone()[0],expected_lineage)
        self.assertEqual(self.history.commit_page(job,value,finalized_through=2),first)
        with self.assertRaisesRegex(EvidenceConflict,'candidate_archive_page_conflict'):
            self.history.commit_page(job,dict(value,note='different'),finalized_through=2)

    def test_creation_attention_misses_expire_on_every_delivery_poll(self):
        from types import SimpleNamespace
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape
        from meme_machine.solana_evidence_plane import EvidenceReader
        reader=EvidenceReader(self.path);self.addCleanup(reader.close)
        tape=LocalPumpTape(SimpleNamespace(frontier=lambda _:-1,reader=reader,clock=lambda:NOW))
        creation=dict(mint='mint',event_type='create',available_time=10)
        with patch.object(tape,'_creation',side_effect=[None,creation]) as lookup:
            self.assertEqual(tape.events_since(0),([],0))
            for _ in range(200):self.assertIsNone(tape.creation('mint'))
            self.assertEqual(lookup.call_count,1)
            # Even an empty new poll discards observation-only misses. A later
            # authentic creation is reconsidered; no absence/coverage proof or
            # durable rejection is produced by the cache.
            self.assertEqual(tape.events_since(0),([],0))
            self.assertEqual(tape.creation('mint'),creation)
            self.assertEqual(lookup.call_count,2)
        tape.events_since(0)
        with patch.object(tape,'_creation',return_value=None) as lookup:
            for index in range(300):tape.creation(str(index))
            self.assertEqual(len(tape._creation_batch),256)
            self.assertEqual(lookup.call_count,300)


class RollingBulkStoreTests(unittest.TestCase):
    """Disposable SQL-contract fixtures, never a market throughput proof."""
    tables=('rolling_economic_events','rolling_economic_addresses',
        'candidate_content_receipts','native_order_attestations',
        'rolling_event_lineage','cursors','counters')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.number=0

    def history(self):
        self.number+=1
        state,history=state_at(Path(self.tmp.name)/('bulk-'+str(self.number)+'.sqlite'))
        self.addCleanup(state.writer.close)
        return history

    def products(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        rows={}
        for family in ('pump','pumpswap'):
            for tx in FIXTURE[family]:
                for row in economic_records(family,PROGRAMS[family],tx,
                        endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'):
                    rows.setdefault(row.identity,row)
        self.assertTrue(rows)
        return tuple(prepare_economic_record(row) for row in rows.values())

    def snapshot(self,history):
        return {table:history.db.execute('SELECT rowid,* FROM '+table+' ORDER BY rowid').fetchall()
                for table in self.tables}

    @staticmethod
    def inputs(products):return tuple(product.record for product in products)

    def test_fresh_bulk_matches_scalar_bytes_row_order_counts_and_last_clock(self):
        scalar=self.history();bulk=self.history();products=self.products();rows=self.inputs(products)
        times=[NOW+100-index for index in range(len(rows))]
        for history in (scalar,bulk):
            values=iter(times);history.clock=lambda values=values:next(values)
            with history.writer.transaction():
                for scope in dict.fromkeys(row.scope for row in rows):
                    history.db.execute('INSERT INTO cursors VALUES(?,?,?)',
                        (scope,max(row.slot for row in rows)+1000,NOW-1))
                history.writer._count('ingested_event',7)
                first=rows[0]
                history.db.execute('INSERT INTO native_order_attestations VALUES(?,?,?,?,?)',
                    (first.scope,first.slot,first.signature,first.transaction_index,
                     digest([first.scope,first.slot,first.signature,first.transaction_index])))
        with scalar.writer.transaction():
            for row,product in zip(rows,products):scalar.rolling.store(row,serialized=product)
        with bulk.writer.transaction():self.assertTrue(bulk.rolling.store_many(rows,products))
        self.assertEqual(self.snapshot(bulk),self.snapshot(scalar))
        self.assertEqual(bulk.db.execute("SELECT value FROM counters WHERE key='ingested_event'").fetchone(),
            (7+len(rows),))
        for scope in dict.fromkeys(row.scope for row in rows):
            expected=next(times[index] for index in reversed(range(len(rows))) if rows[index].scope==scope)
            self.assertEqual(bulk.db.execute('SELECT updated FROM cursors WHERE scope=?',(scope,)).fetchone(),
                (expected,))

    def test_unsupported_inputs_and_missing_transaction_return_without_writes(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        history=self.history();product=self.products()[0];row=product.record
        null=prepare_economic_record(replace(row,transaction_index=None))
        unrelated=prepare_economic_record(replace(row,observed_at=NOW+1))
        initial=self.snapshot(history)
        self.assertFalse(history.rolling.store_many((row,),(product,)))
        variants=[((),()),((row,),()),((row,),(row.serialized_body(),)),
            ((row,row),(product,product)),((null.record,),(null,)),
            ((row,),(unrelated,)),((row,),(replace(product,original_bytes=16*1024*1024+1),)),
            (iter((row,)),(product,))]
        with history.writer.transaction():
            for rows,serialized in variants:
                before=history.db.total_changes
                self.assertFalse(history.rolling.store_many(rows,serialized))
                self.assertEqual(history.db.total_changes,before)
        self.assertEqual(self.snapshot(history),initial)

    def test_transaction_records_and_repeated_addresses_keep_scalar_semantics(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        scalar=self.history();bulk=self.history();base=self.products()[0].record
        payload=dict(slot=base.slot,blockTime=base.market_time,transactionIndex=base.transaction_index,
            transaction=dict(signatures=[base.signature],message=dict(accountKeys=list(base.addresses),instructions=[])),
            meta=dict(err=None,logMessages=[],innerInstructions=[],preTokenBalances=[],postTokenBalances=[]))
        product=prepare_economic_record(replace(base,identity=base.identity+':transaction-fixture',
            kind='transaction',payload=payload,addresses=base.addresses+(base.addresses[0],)))
        with scalar.writer.transaction():scalar.rolling.store(product.record,serialized=product)
        with bulk.writer.transaction():self.assertTrue(bulk.rolling.store_many((product.record,),(product,)))
        self.assertEqual(self.snapshot(bulk),self.snapshot(scalar))
        self.assertEqual(bulk.db.execute("SELECT value FROM counters WHERE key='ingested_event'").fetchone(),(1,))

    def test_any_retained_representation_falls_back_before_new_rows_are_written(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        product=self.products()[0];row=product.record
        fresh=prepare_economic_record(replace(row,identity=row.identity+':fresh'))
        for representation in ('rolling','archived','legacy','receipt'):
            with self.subTest(representation=representation):
                history=self.history()
                with history.writer.transaction():
                    if representation in ('rolling','archived'):
                        history.rolling.store(row,serialized=product)
                        if representation=='archived':
                            history.db.execute('UPDATE rolling_economic_events SET body=NULL,archive=?',('retained',))
                    elif representation=='legacy':
                        history.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                            (row.identity,row.scope,row.slot,row.signature,row.program,row.market_time,
                             row.event_index,row.transaction_index,row.kind,product.encoded,product.checksum,NOW-5))
                    else:
                        history.db.execute('INSERT INTO candidate_content_receipts VALUES(?,?,?,?)',
                            (row.identity,product.economic_hash,row.transaction_index,NOW-5))
                before=self.snapshot(history)
                with history.writer.transaction():
                    changes=history.db.total_changes
                    self.assertFalse(history.rolling.store_many((fresh.record,row),(fresh,product)))
                    self.assertEqual(history.db.total_changes,changes)
                self.assertEqual(self.snapshot(history),before)

    def test_native_index_or_hash_conflicts_fail_before_any_writes(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        product=self.products()[0];row=product.record
        for bad in ('index','hash','within_batch'):
            with self.subTest(bad=bad):
                history=self.history();products=(product,)
                with history.writer.transaction():
                    if bad=='within_batch':
                        other=prepare_economic_record(replace(row,identity=row.identity+':conflict',
                            transaction_index=row.transaction_index+1))
                        products+=(other,)
                    else:
                        index=row.transaction_index+(bad=='index')
                        checksum='0'*64 if bad=='hash' else digest([row.scope,row.slot,row.signature,index])
                        history.db.execute('INSERT INTO native_order_attestations VALUES(?,?,?,?,?)',
                            (row.scope,row.slot,row.signature,index,checksum))
                before=self.snapshot(history)
                with history.writer.transaction():
                    changes=history.db.total_changes
                    with self.assertRaisesRegex(EvidenceConflict,'candidate_native_order_conflict'):
                        history.rolling.store_many(self.inputs(products),products)
                    self.assertEqual(history.db.total_changes,changes)
                self.assertEqual(self.snapshot(history),before)

    def test_mid_write_failure_rolls_back_and_identical_retry_remains_fresh(self):
        history=self.history();products=self.products();rows=self.inputs(products)
        original=sqlite3.OperationalError('offline_original_bulk_write_failure')
        db=history.db
        class Interrupted:
            def __getattr__(self,name):return getattr(db,name)
            def executemany(self,sql,parameters):
                if sql.startswith('INSERT OR IGNORE INTO rolling_economic_addresses'):
                    db.executemany(sql,list(parameters)[:1])
                    raise original
                return db.executemany(sql,parameters)
        before=self.snapshot(history);history.rolling.db=Interrupted()
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                with history.writer.transaction():history.rolling.store_many(rows,products)
            self.assertIs(caught.exception,original)
        finally:history.rolling.db=db
        self.assertFalse(db.in_transaction)
        self.assertEqual(self.snapshot(history),before)
        with history.writer.transaction():self.assertTrue(history.rolling.store_many(rows,products))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],len(rows))
        with history.writer.transaction():self.assertFalse(history.rolling.store_many(rows,products))

    def test_lookup_chunks_are_bounded_and_same_transaction_key_is_not_duplicated(self):
        from meme_machine.solana_economic_preparation import prepare_economic_record
        history=self.history();base=self.products()[0].record
        # Synthetic identities test only parameter bounds and SQL semantics.
        products=tuple(prepare_economic_record(replace(base,identity=base.identity+':bound-'+str(index)))
            for index in range(257))
        db=history.db;lookups=[]
        class Observed:
            def __getattr__(self,name):return getattr(db,name)
            def execute(self,sql,parameters=()):
                if sql.startswith('SELECT identity FROM '):lookups.append(len(parameters))
                return db.execute(sql,parameters)
        history.rolling.db=Observed()
        try:
            with history.writer.transaction():
                self.assertTrue(history.rolling.store_many(self.inputs(products),products))
        finally:history.rolling.db=db
        self.assertEqual(lookups,[256,1]*3)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM native_order_attestations').fetchone(),(1,))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone(),(257,))
        self.assertEqual(db.execute("SELECT value FROM counters WHERE key='ingested_event'").fetchone(),(257,))


if __name__=='__main__':unittest.main()
