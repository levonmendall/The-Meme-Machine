"""Post-join kernel receipt checks over genuine disposable native FULL/ACK.

The original native frame decoder, source outbox, CandidateHistory delivery and
source acknowledgement create the positive rows. Corruptions touch only these
disposable test copies; no fabricated acknowledgement supplies the positive.
"""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib
from unittest.mock import patch

from meme_machine.operational import isolated_native_kernel_validation as validation
from meme_machine.runtime.journal import canonical


class NativeKernelOutputTests(unittest.TestCase):
    def setUp(self):
        from tests.test_pump_cache_source_authority import PumpCacheSourceAuthorityTests
        self.case=PumpCacheSourceAuthorityTests('runTest');self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.source=self.case.root/'solana-evidence.sqlite'
        self.state,self.history,self.plane,_expected=self.case.selective_fixture(self.source)
        self.db=self.state.writer.db
        self.consumer=sqlite3.connect(self.case.cache_path,isolation_level=None)
        self.addCleanup(self.consumer.close)
        self.row=self.db.execute("SELECT id,family,address,body,hash FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        self.assertIsNotNone(self.row)
        self.identity=self.row[0];self.compact=json.loads(self.row[3])

    def count(self,endpoint=None):
        return validation._canonical_acks(self.db,self.consumer,self.source,
            endpoint_identity=endpoint or self.case.endpoint.identity)

    def test_actual_native_delivery_ack_binds_source_lineage_and_exact_candidate_reference(self):
        count=self.count()
        self.assertGreater(count,0)
        self.assertEqual(count,self.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL").fetchone()[0])
        with self.assertRaisesRegex(ValueError,'lineage'):self.count('0'*64)

    def test_actual_native_retirement_keeps_original_full_ack_verifiable(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        expected=self.count()
        retired=ScopedRetirement(self.history).retire(measure_hot_bytes=False)
        self.assertGreater(retired['retired_records'],0)
        self.assertTrue(self.db.execute('SELECT 1 FROM canonical_evidence WHERE body IS NULL AND archive IS NOT NULL').fetchone())
        before=(self.db.total_changes,self.consumer.total_changes)
        self.assertEqual(self.count(),expected)
        self.assertEqual((self.db.total_changes,self.consumer.total_changes),before)

    def retire(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        self.assertGreater(ScopedRetirement(self.history).retire(measure_hot_bytes=False)['retired_records'],0)
        archive=self.db.execute('SELECT archive FROM canonical_evidence WHERE identity=?',
            (self.compact['record']['identity'],)).fetchone()[0]
        self.assertIsNotNone(archive)
        return archive,Path(self.db.execute('SELECT path FROM scoped_cold_manifests WHERE id=?',
            (archive,)).fetchone()[0])

    def replace_archive(self,archive,path,records=None,*,packed=None):
        # Negative-only corruption: rehashing an altered archive must never
        # replace the original economic body/availability/source ACK identity.
        raw=None if records is None else canonical(records).encode()
        packed=zlib.compress(raw) if packed is None else packed
        replacement=hashlib.sha256(packed).hexdigest()
        target=path.with_name(replacement+'.zlib');target.write_bytes(packed)
        self.db.execute('UPDATE scoped_cold_manifests SET id=?,path=?,hash=?,records=?,cold_bytes=? WHERE id=?',
            (replacement,str(target),replacement,1 if records is None else len(records),len(packed),archive))
        for table in ('rolling_economic_events','scoped_cold_records'):
            self.db.execute('UPDATE '+table+' SET archive=? WHERE archive=?',(replacement,archive))
        return replacement,target

    def test_cold_archive_complete_hash_body_and_availability_are_all_required(self):
        archive,path=self.retire();original=path.read_bytes()
        records=json.loads(zlib.decompress(original));record_id=self.compact['record']['identity']
        target=next(index for index,item in enumerate(records) if item['record']['identity']==record_id)
        for field in ('body','available','first_duplicate'):
            altered=copy.deepcopy(records)
            if field=='body':altered[target]['record']['payload']['event']['PRIVATE']='forged'
            elif field=='available':altered[target]['available']+=1
            else:
                bad=copy.deepcopy(altered[target]);bad['record']['payload']['event']['PRIVATE']='forged'
                altered.insert(0,bad)
            replacement,file=self.replace_archive(archive,path,altered)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'canonical_source'):self.count()
            # Restore only this disposable archive's exact original metadata.
            self.db.execute('UPDATE scoped_cold_manifests SET id=?,path=?,hash=?,records=?,cold_bytes=? WHERE id=?',
                (archive,str(path),archive,len(records),len(original),replacement))
            for table in ('rolling_economic_events','scoped_cold_records'):
                self.db.execute('UPDATE '+table+' SET archive=? WHERE archive=?',(archive,replacement))
            if file!=path:file.unlink()
        path.write_bytes(original[:-1]+bytes([original[-1]^1]))
        with self.assertRaisesRegex(ValueError,'canonical_source'):self.count()

    def test_cold_archive_links_foreign_manifest_and_population_bounds_refuse(self):
        archive,path=self.retire();original=path.read_bytes()
        foreign=self.case.root/'unrelated';foreign.write_bytes(original)
        for kind in ('symlink','hardlink'):
            path.unlink()
            if kind=='symlink':path.symlink_to(foreign)
            else:os.link(foreign,path)
            with self.subTest(kind=kind),self.assertRaises((ValueError,OSError)):self.count()
            path.unlink();path.write_bytes(original)
        path.unlink();os.mkfifo(path)
        with self.assertRaisesRegex(ValueError,'canonical_source'):self.count()
        path.unlink();path.write_bytes(original)
        self.db.execute('UPDATE scoped_cold_manifests SET path=? WHERE id=?',(str(foreign),archive))
        with self.assertRaisesRegex(ValueError,'canonical_source'):self.count()
        self.db.execute('UPDATE scoped_cold_manifests SET path=? WHERE id=?',(str(path),archive))
        for field,value in (('records',1001),('hot_bytes',16*1024*1024+1),('cold_bytes',33*1024*1024+1)):
            old=self.db.execute('SELECT '+field+' FROM scoped_cold_manifests WHERE id=?',(archive,)).fetchone()[0]
            self.db.execute('UPDATE scoped_cold_manifests SET '+field+'=? WHERE id=?',(value,archive))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'canonical_source'):self.count()
            self.db.execute('UPDATE scoped_cold_manifests SET '+field+'=? WHERE id=?',(old,archive))
        self.assertEqual(foreign.read_bytes(),original)
        self.assertGreater(self.count(),0)

    def test_cold_archive_inflate_tail_missing_identity_and_changed_fd_fail_closed(self):
        archive,path=self.retire();original=path.read_bytes();records=json.loads(zlib.decompress(original))
        # Real bounded zlib decoder, with no guard or limit monkeypatch.
        for packed in (zlib.compress(b' '*(32*1024*1024+1)),original+b'private-tail',
                zlib.compress(canonical([dict(record=dict(identity='unrelated'),available=1)]).encode())):
            replacement,file=self.replace_archive(archive,path,packed=packed)
            with self.assertRaises((ValueError,StopIteration)):self.count()
            self.db.execute('UPDATE scoped_cold_manifests SET id=?,path=?,hash=?,records=?,cold_bytes=? WHERE id=?',
                (archive,str(path),archive,len(records),len(original),replacement))
            for table in ('rolling_economic_events','scoped_cold_records'):
                self.db.execute('UPDATE '+table+' SET archive=? WHERE archive=?',(archive,replacement))
            if file!=path:file.unlink()
        actual=validation.os.read;changed=False
        def reading(fd,size):
            nonlocal changed
            result=actual(fd,size)
            if not changed:
                changed=True
                with path.open('ab') as writer:writer.write(b'changed-after-read')
            return result
        with patch.object(validation.os,'read',reading),self.assertRaisesRegex(ValueError,'canonical_source'):
            self.count()

    def test_cold_archive_cache_never_bypasses_later_ack_or_reference_checks(self):
        self.retire()
        expected=self.count();self.assertGreater(expected,1)
        self.consumer.execute('DELETE FROM canonical_event_refs WHERE rowid=(SELECT rowid FROM canonical_event_refs ORDER BY rowid DESC LIMIT 1)')
        with self.assertRaisesRegex(ValueError,'canonical_reference'):self.count()

    def test_cold_archive_read_failure_closes_every_noninherited_owned_descriptor(self):
        self.retire();actual=validation.os.open;opened=[]
        def opening(*args,**kwargs):
            fd=actual(*args,**kwargs);opened.append(fd)
            self.assertFalse(os.get_inheritable(fd))
            return fd
        with patch.object(validation.os,'open',opening),patch.object(validation.os,'read',
                side_effect=OSError(5,'PRIVATE')):
            with self.assertRaises(OSError):self.count()
        self.assertEqual(len(opened),2)
        for fd in opened:
            with self.assertRaises(OSError):os.fstat(fd)

    def test_hot_sep1_uses_original_codec_and_hash_checks_before_and_after_retirement(self):
        from meme_machine.solana_evidence_storage import prepare
        rows=self.db.execute('SELECT identity,body FROM rolling_economic_events').fetchall()
        for identity,raw in rows:
            # The original lossless encoder accepts a validated canonical_body;
            # whitespace changes storage width only, never decoded economics or
            # the genuine source/ACK/reference hashes created in setUp.
            body=json.loads(raw);encoded,chunks=prepare(body,canonical_body=raw+' '*2048)
            self.assertTrue(encoded.startswith(b'SEP1'));self.assertEqual(chunks,())
            self.db.execute('UPDATE rolling_economic_events SET body=? WHERE identity=?',(encoded,identity))
        expected=self.count();self.assertGreater(expected,0)
        self.retire();self.assertEqual(self.count(),expected)

    def test_partial_output_checks_keep_real_full_ack_without_promoting_missing_reports(self):
        expected=self.count()
        references=self.consumer.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0]
        self.plane.close();self.state.writer.close();self.consumer.close()
        observation={}
        with self.assertRaises(FileNotFoundError):
            validation.native_outputs(self.case.root,endpoint_identity=self.case.endpoint.identity,
                _observation=observation)
        self.assertEqual(observation['status'],'PARTIAL')
        self.assertEqual(observation['canonical_full_ack'],expected)
        self.assertEqual(observation['candidate_references'],references)
        self.assertGreater(expected,0)
        self.assertEqual(observation['completed_stages'],
            ['ROOT','DATABASE_INVENTORY','HISTORY_COUNTS','FULL_ACK_BINDING'])
        self.assertIsNone(observation['pump_report_read'])
        self.assertEqual(observation['current_stage'],'PUMP_REPORT')
        self.assertFalse(observation['authoritative_readiness'])
        self.assertFalse(observation['historical_projection_eligible'])
        self.assertFalse(validation.verified(dict(child=dict(status='COMPLETED'),output_checks=observation)))

    def test_partial_output_checks_preserve_corrupt_ack_refusal_and_unknown_ack_count(self):
        self.db.execute('UPDATE candidate_history_outbox SET body=?,hash=? WHERE id=?',
            ('{}',hashlib.sha256(b'{}').hexdigest(),self.identity))
        self.plane.close();self.state.writer.close();self.consumer.close()
        observation={}
        with self.assertRaisesRegex(ValueError,'kernel_validation_source_ack_shape') as caught:
            validation.native_outputs(self.case.root,endpoint_identity=self.case.endpoint.identity,
                _observation=observation)
        self.assertEqual(validation._output_failure_code(caught.exception),'kernel_validation_source_ack_shape')
        self.assertEqual(observation['status'],'PARTIAL')
        self.assertGreater(observation['candidate_references'],0)
        self.assertIsNone(observation['canonical_full_ack'])
        self.assertEqual(observation['current_stage'],'FULL_ACK_BINDING')
        self.assertNotIn('FULL_ACK_BINDING',observation['completed_stages'])
        self.assertFalse(validation.verified(dict(output_checks=observation)))

    def test_self_hashed_empty_and_missing_or_cross_bound_receipts_do_not_count(self):
        self.db.execute('UPDATE candidate_history_outbox SET body=?,hash=? WHERE id=?',
            ('{}',hashlib.sha256(b'{}').hexdigest(),self.identity))
        with self.assertRaisesRegex(ValueError,'ack_shape'):self.count()
        self.db.execute('UPDATE candidate_history_outbox SET body=?,hash=? WHERE id=?',
            (self.row[3],self.row[4],self.identity))
        original=self.consumer.execute('SELECT * FROM source_receipts WHERE id=?',(self.identity,)).fetchone()
        proof=json.loads(original[5])
        for field,value in (('scope','candidate:pump:unrelated'),('canonical_identity','unrelated'),
                ('source_hash','0'*64)):
            bad=canonical(dict(proof,**{field:value}))
            self.consumer.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                (bad,hashlib.sha256(bad.encode()).hexdigest(),self.identity))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'ack_binding'):self.count()
        for body in ('{}','{"source_hash":null,"scope":null,"canonical_identity":null}'):
            self.consumer.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                (body,hashlib.sha256(body.encode()).hexdigest(),self.identity))
            with self.assertRaisesRegex(ValueError,'ack_binding'):self.count()
        self.consumer.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)
        for field,value in (('family','pumpswap'),('address','unrelated'),('kind','scout')):
            self.consumer.execute('UPDATE source_receipts SET '+field+'=? WHERE id=?',(value,self.identity))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'consumer_ack_hash'):self.count()
            self.consumer.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)
        self.consumer.execute('DELETE FROM source_receipts WHERE id=?',(self.identity,))
        with self.assertRaisesRegex(ValueError,'consumer_ack_hash'):self.count()

    def test_unrelated_reference_count_and_self_hashed_wrong_reference_cannot_supply_full_ack(self):
        record_id=self.compact['record']['identity']
        reference=self.consumer.execute("SELECT * FROM canonical_event_refs WHERE json_extract(body,'$.canonical_identity')=? LIMIT 1",(record_id,)).fetchone()
        self.assertIsNotNone(reference)
        ref=json.loads(reference[8])
        for field,value in (('path',str(self.case.root/'unrelated.sqlite')),
                ('canonical_identity','unrelated'),('canonical_hash','0'*64),('fields',{})):
            raw=canonical(dict(ref,**{field:value}))
            self.consumer.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE lane=? AND candidate=? AND identity=?',
                (raw,hashlib.sha256(raw.encode()).hexdigest(),*reference[:3]))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'canonical_reference_binding'):self.count()
            self.consumer.execute('INSERT OR REPLACE INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',reference)
        self.consumer.execute('DELETE FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',reference[:3])
        self.assertGreater(self.consumer.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'canonical_reference'):self.count()


class NativeKernelSQLitePathTests(unittest.TestCase):
    def test_output_failure_projection_retains_only_exact_local_literals(self):
        for error in (ValueError('kernel_validation_source_ack_shape'),
                ValueError('PRIVATE-provider-path-SQL'),ValueError(['PRIVATE']),
                type('PRIVATE',(ValueError,),{})('kernel_validation_source_ack_shape'),
                FileNotFoundError(2,'PRIVATE')):
            code=validation._output_failure_code(error)
            self.assertEqual(code,'kernel_validation_source_ack_shape' if type(error) is ValueError
                and error.args==('kernel_validation_source_ack_shape',) else None)
            self.assertNotIn('PRIVATE',str(code))

    def test_canonical_ack_census_overflow_refuses_before_decoding_any_body(self):
        # Deliberately malformed negative rows; no synthetic ACK is accepted.
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE candidate_history_outbox(id TEXT,family TEXT,address TEXT,body TEXT,hash TEXT,kind TEXT,consumed INTEGER)')
            db.executemany('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,?,?)',
                ((str(index),'pump','invalid','{}','invalid','canonical',1)
                    for index in range(1025)))
            with self.assertRaisesRegex(ValueError,'ack_bound'):
                validation._canonical_acks(db,db,Path('/unused'),endpoint_identity='a'*64)

    def test_existing_wal_commits_remain_visible_without_immutable_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'owned.sqlite'
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute('CREATE TABLE fixture(value INTEGER)');writer.execute('INSERT INTO fixture VALUES(7)');writer.commit()
                self.assertTrue(path.with_name(path.name+'-wal').exists())
                with closing(validation._readonly(path)) as reader:
                    self.assertEqual(reader.execute('SELECT value FROM fixture').fetchall(),[(7,)])

    def test_every_sqlite_sidecar_refuses_foreign_path_links_before_sqlite_opens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owned=root/'owned';owned.mkdir(mode=0o700)
            path=owned/'state.sqlite'
            with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE fixture(value)')
            foreign=root/'foreign';foreign.write_bytes(b'private unrelated bytes')
            for suffix in ('-wal','-shm','-journal'):
                sidecar=path.with_name(path.name+suffix)
                for kind in ('symlink','hardlink'):
                    if kind=='symlink':sidecar.symlink_to(foreign)
                    else:os.link(foreign,sidecar)
                    with self.subTest(suffix=suffix,kind=kind),patch.object(validation.sqlite3,'connect',
                            side_effect=AssertionError('SQLite must not open unsafe sidecars')):
                        with self.assertRaisesRegex(ValueError,'database_sidecar'):validation._readonly(path)
                    sidecar.unlink()
            self.assertEqual(foreign.read_bytes(),b'private unrelated bytes')


if __name__=='__main__':unittest.main()
