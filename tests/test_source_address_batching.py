"""Native frame address indexing preserves the old view contract with bounded work."""
import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine import solana_evidence_service as service
from meme_machine import solana_evidence_storage as storage
from meme_machine import solana_evidence_plane as plane
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run380_production_pressure import Wire


def old_view(db,identity,slot,addresses,cache):
    db.executemany('INSERT OR IGNORE INTO addresses VALUES(?,?,?)',
                   [(address,identity,slot) for address in addresses])


class SourceAddressBatchingTests(unittest.TestCase):
    def test_dense_frame_preserves_original_address_and_retirement_facts(self):
        config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
        raw=Wire().template;seen=time.time()
        prepared,_,_=service.decode_source_message(raw,config.credential,
            tuple(s.address for s in service.program_subscriptions()),config.identity,seen)
        sub=Subscription('service','blocks','all','blocks',4)
        with tempfile.TemporaryDirectory() as td:
            legacy=service.ServiceState(Path(td)/'legacy',config)
            current=service.ServiceState(Path(td)/'current',config)
            try:
                with patch.object(plane,'publish_addresses',old_view):
                    legacy.source_batch([(sub,prepared,seen,len(raw))])
                current.source_batch([(sub,prepared,seen,len(raw))])
                # The exact old view insertion is the independent semantic reference.
                for table in ('records','addresses','address_keys','address_refs',
                    'maintenance_orphans','lineage','stream_order'):
                    with self.subTest(table=table):
                        query='SELECT * FROM '+table+' ORDER BY 1,2'
                        self.assertEqual(current.writer.db.execute(query).fetchall(),legacy.writer.db.execute(query).fetchall())
                # Duplicate frames and a rolled-back address publication retain the same indices.
                current.source_batch([(sub,prepared,seen,len(raw))])
                before=current.writer.db.execute('SELECT * FROM address_refs ORDER BY 1,2').fetchall()
                with self.assertRaisesRegex(RuntimeError,'cut'):
                    with current.writer.transaction():
                        storage.publish_addresses(current.writer.db,
                            current.writer.db.execute('SELECT identity FROM records LIMIT 1').fetchone()[0],1000,['new-address'],{})
                        raise RuntimeError('cut')
                self.assertEqual(before,current.writer.db.execute('SELECT * FROM address_refs ORDER BY 1,2').fetchall())
                self.assertIsNone(current.writer.db.execute("SELECT id FROM address_keys WHERE address='new-address'").fetchone())
                self.assertEqual(current.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:current.close();legacy.close()

    def test_repeated_shared_addresses_need_one_lookup_per_batch(self):
        from tests.test_retention_progress import record
        from dataclasses import replace
        from meme_machine.solana_evidence_plane import EvidenceWriter
        addresses=tuple('shared-'+str(i) for i in range(100))
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'db');trace=[]
            try:
                writer.db.set_trace_callback(trace.append)
                writer.ingest([replace(record(),identity='repeated-'+str(i),signature='s'+str(i),addresses=addresses) for i in range(40)])
                lookups=sum('SELECT id FROM address_keys WHERE address=' in sql for sql in trace)
                self.assertGreater(lookups,0,'exercise actual key indexing')
                self.assertLessEqual(lookups,100,'address lookups must be bounded by unique shared keys')
                self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM addresses').fetchone()[0],4000)
            finally:writer.close()

    def test_cache_bound_and_post_rollback_retry_preserve_all_keys(self):
        from tests.test_retention_progress import record
        from dataclasses import replace
        from meme_machine.solana_evidence_plane import EvidenceWriter
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'db');cache={}
            try:
                writer.ingest([record()]);identity=record().identity
                storage.publish_addresses(writer.db,identity,record().slot,tuple('key-'+str(i) for i in range(8192)),cache)
                self.assertLessEqual(len(cache),4096)
                self.assertEqual(writer.db.execute("SELECT COUNT(*) FROM addresses WHERE address LIKE 'key-%'").fetchone()[0],8192)
                with self.assertRaisesRegex(RuntimeError,'cut'):
                    with writer.transaction():
                        storage.publish_addresses(writer.db,identity,record().slot,['rollback-key'],{})
                        raise RuntimeError('cut')
                storage.publish_addresses(writer.db,identity,record().slot,['rollback-key'],{})
                self.assertEqual(writer.db.execute("SELECT COUNT(*) FROM addresses WHERE address='rollback-key'").fetchone()[0],1)
                self.assertEqual(writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:writer.close()
