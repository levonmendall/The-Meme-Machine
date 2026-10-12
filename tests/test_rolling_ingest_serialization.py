"""In-command body reuse preserves authenticated bytes and all refusal paths."""
from dataclasses import replace
from pathlib import Path
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


if __name__=='__main__':unittest.main()
