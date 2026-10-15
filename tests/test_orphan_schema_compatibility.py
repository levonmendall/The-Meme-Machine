"""Disposable maintenance indexes cannot change durable evidence or lineage."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3,tempfile,unittest
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_maintenance_state import install_housekeeping_witnesses,orphan_triggers
from tests.test_retention_progress import record

class OrphanSchemaCompatibilityTests(unittest.TestCase):
    @contextmanager
    def writer(self):
        with tempfile.TemporaryDirectory() as folder:
            writer=EvidenceWriter(Path(folder)/'db')
            try:yield writer
            finally:writer.close()

    def downgrade(self,db,version=None):
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'orphan_*'").fetchall():
            db.execute('DROP TRIGGER '+name)
        db.execute('DELETE FROM maintenance_orphans')
        db.execute("DELETE FROM meta WHERE key IN ('maintenance_orphans_v1','maintenance_orphans_v2')")
        if version==1:
            for sql in orphan_triggers(updates=False).values():db.execute(sql)
            db.execute("INSERT INTO meta VALUES('maintenance_orphans_v1','1')")

    def facts(self,db):
        return {name:db.execute('SELECT * FROM '+name+' ORDER BY 1').fetchall()
                for name in ('records','address_keys','address_refs','hot_chunks','hot_refs','archives','interests','cursors')}

    def test_old_schema_upgrade_and_restart_preserve_all_evidence_facts(self):
        with self.writer() as writer:
            writer.ingest([record()]);db=writer.db
            self.downgrade(db)
            db.execute("INSERT INTO address_keys(id,address) VALUES(100000,'orphan')")
            before=self.facts(db)
            install_housekeeping_witnesses(db)
            self.assertEqual(self.facts(db),before)
            self.assertEqual(db.execute("SELECT key FROM maintenance_orphans WHERE kind='address' AND key='100000'").fetchone(),('100000',))
            witnesses=db.execute('SELECT * FROM maintenance_orphans ORDER BY 1,2').fetchall()
            install_housekeeping_witnesses(db)
            self.assertEqual(self.facts(db),before)
            self.assertEqual(db.execute('SELECT * FROM maintenance_orphans ORDER BY 1,2').fetchall(),witnesses)

    def test_interrupted_trigger_install_restarts_without_losing_facts(self):
        with self.writer() as writer:
            writer.ingest([record()]);db=writer.db;self.downgrade(db)
            db.executemany('INSERT INTO address_keys(id,address) VALUES(?,?)',
                           [(100000+i,'orphan-'+str(i)) for i in range(600)])
            before=self.facts(db)
            def deny_trigger(action,*args):
                return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK
            db.set_authorizer(deny_trigger)
            try:
                with self.assertRaises(sqlite3.DatabaseError):install_housekeeping_witnesses(db)
            finally:db.set_authorizer(None)
            self.assertFalse(db.in_transaction)
            self.assertIsNone(db.execute("SELECT 1 FROM meta WHERE key='maintenance_orphans_v2'").fetchone())
            self.assertEqual(self.facts(db),before)
            install_housekeeping_witnesses(db)
            self.assertEqual(self.facts(db),before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM maintenance_orphans WHERE kind='address' AND CAST(key AS INTEGER)>=100000").fetchone()[0],600)

    def test_v1_upgrade_rebuilds_witnesses_missed_by_reference_updates(self):
        with self.writer() as writer:
            writer.ingest([record()]);db=writer.db;self.downgrade(db,version=1)
            rid=db.execute('SELECT rowid FROM records LIMIT 1').fetchone()[0]
            db.execute("INSERT INTO address_keys(id,address) VALUES(100000,'old')")
            db.execute("INSERT INTO address_keys(id,address) VALUES(100001,'new')")
            db.execute('INSERT INTO address_refs VALUES(?,?,?)',(100000,rid,1))
            db.execute('UPDATE address_refs SET address_id=100001 WHERE address_id=100000')
            before=self.facts(db)
            install_housekeeping_witnesses(db)
            self.assertEqual(self.facts(db),before)
            self.assertEqual(db.execute("SELECT key FROM maintenance_orphans WHERE kind='address' AND key IN ('100000','100001')").fetchall(),[('100000',)])

    def test_trigger_drift_fails_closed(self):
        with self.writer() as writer:
            db=writer.db;db.execute('DROP TRIGGER orphan_address_ref_update')
            with self.assertRaisesRegex(ValueError,'maintenance_synopsis_trigger_identity'):
                install_housekeeping_witnesses(db)
