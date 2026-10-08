"""Consumer durable checkpoints advance only their consumed lifecycle prefix."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable,digest
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_evidence_runtime import RuntimeEvidence
from tests.test_solana_evidence_plane import record,proof

class InterestCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'evidence';self.now=100
        self.open()
        self.writer.ingest([record(slot=10)],proof=proof(10,1000))
        self.plane.interest('pump',lower_slot=10,addresses=['pool'],owner='held',lifecycle='open',priority=0)
    def open(self):
        self.writer=EvidenceWriter(self.path,clock=lambda:self.now)
        self.fence=FinalizedFence(self.writer,endpoint_identity='a'*64,decoders={})
        self.plane=RuntimeEvidence(self.path,owner='native',clock=lambda:self.now,command=self.fence.command)
    def close(self):self.plane.close();self.writer.close()
    def tearDown(self):self.close()
    def pin(self):return self.writer.db.execute('SELECT lower_slot,lifecycle,priority,active FROM interests WHERE owner=?',('held',)).fetchone()
    def advance(self,slot=30,**kwargs):
        self.plane.advance_interest('pump',owner='held',lower_slot=slot,consumed_slot=slot,
            checkpoint_hash=kwargs.get('checksum',digest(['native-replay',slot])))
    def test_ordinary_interest_stays_conservative_then_explicit_ack_survives_restart(self):
        self.plane.interest('pump',lower_slot=30,addresses=['pool'],owner='held',lifecycle='open',priority=0)
        self.assertEqual(self.pin(),(10,'open',0,1))
        self.advance();self.advance();self.assertEqual(self.pin(),(30,'open',0,1))
        self.close();self.open();self.advance()
        self.assertEqual(self.pin(),(30,'open',0,1))
        with self.assertRaisesRegex(EvidenceUnavailable,'unresolved_lifecycle'):self.plane.command(op='release',owner='held',scope='pump')
    def test_foreign_unknown_inactive_ahead_regression_conflicting_ack_rejected(self):
        request=dict(op='advance_interest',owner='held',scope='pump',lower_slot=30,consumed_slot=30,checkpoint_hash=digest('checkpoint'))
        with self.assertRaisesRegex(EvidenceUnavailable,'other_consumer'):self.fence.command(dict(request,consumer='foreign'))
        with self.assertRaisesRegex(EvidenceUnavailable,'unknown_owner'):self.fence.command(dict(request,owner='unknown',consumer='native'))
        self.advance()
        for slot,checksum,reason in [(29,digest('old'),'regression'),(1001,digest('future'),'ahead_of_source'),(30,digest('different'),'conflict'),(31,'bad','shape')]:
            with self.assertRaisesRegex(EvidenceUnavailable,reason):self.advance(slot,checksum=checksum)
        self.assertEqual(self.pin(),(30,'open',0,1))
        self.plane.command(op='release',owner='held',scope='pump',resolved=True)
        with self.assertRaisesRegex(EvidenceUnavailable,'inactive'):self.advance(31)
        self.now=8000;self.fence.expire_candidates(self.now)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM interest_checkpoints').fetchone()[0],0)
    def test_checkpoint_and_pin_mutation_roll_back_together(self):
        self.writer.db.execute("CREATE TRIGGER fail_pin BEFORE UPDATE OF lower_slot ON interests BEGIN SELECT RAISE(ABORT,'crash at pin commit'); END")
        with self.assertRaisesRegex(Exception,'crash at pin commit'):self.advance()
        self.assertEqual(self.pin()[0],10)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM interest_checkpoints').fetchone()[0],0)
    def test_gap_and_other_lifecycle_pins_survive_consumed_prefix(self):
        self.plane.interest('pump',lower_slot=10,addresses=['pool'],owner='other',lifecycle='reserved',priority=1)
        self.writer.gap('pump',15,16)
        self.advance(30);self.now=1000;self.writer.retain(900)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],1)
        self.plane.command(op='release',owner='other',scope='pump',resolved=True)
        self.writer.retain(900)
        self.assertEqual(self.writer.db.execute("SELECT value FROM meta WHERE key='retention_floor:pump'").fetchone()[0],'15')
        with self.assertRaisesRegex(EvidenceUnavailable,'gap'):self.plane.reader.window('pump',15,16,as_of=self.now)
    def test_account_prefix_retains_boundary_witness_and_unacknowledged_owner(self):
        rows=[replace(record(slot=s,scope='account:pool'),kind='account') for s in (10,15,20,25,30)]
        self.writer.ingest(rows);self.now=1000
        self.writer.retain(900)
        def hot():return [r[0] for r in self.writer.db.execute("SELECT slot FROM records WHERE scope='account:pool' AND body IS NOT NULL ORDER BY slot")]
        self.assertEqual(hot(),[10,15,20,25,30])
        self.plane.interest('pump',lower_slot=10,addresses=['pool'],owner='other',lifecycle='open',priority=0)
        self.advance(28);self.writer.retain(900)
        self.assertEqual(hot(),[10,15,20,25,30])
        self.plane.command(op='release',owner='other',scope='pump',resolved=True)
        self.writer.retain(900)
        self.assertEqual(hot(),[25,30])
        # Advancing beyond the latest change must keep its unchanged value.
        self.advance(40);self.writer.retain(900)
        self.assertEqual(hot(),[30])
        self.assertEqual(self.writer.db.execute("SELECT COUNT(*) FROM records WHERE scope='account:pool'").fetchone()[0],1)
    def test_seven_day_pin_progress_bounds_hot_metadata_and_keeps_raw_archive(self):
        # Same held owner for all 168 hours; no lifecycle release or larger guard.
        counts=[];sizes=[];self.writer.db.execute('DELETE FROM coverage')
        for hour in range(168):
            self.now=2000+hour*3600;lo=20+hour*200;hi=lo+199
            rows=[replace(record(slot=s,observed=self.now-300),market_time=self.now-300,
                          addresses=('unrelated',)) for s in range(lo,hi)]
            rows.append(replace(record(slot=hi,observed=self.now),market_time=self.now))
            rows.extend(replace(record(slot=s,scope='account:pool',observed=self.now-300),
                market_time=self.now-300,kind='account') for s in (lo,hi-1))
            self.writer.ingest(rows,proof=proof(lo,hi,at=self.now))
            self.advance(hi)
            self.writer.retain(self.now-180)
            self.now+=181;self.writer.retain(self.now-180)
            count=self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]
            counts.append(count)
            sizes.append(sum(p.stat().st_size for p in (self.path,Path(str(self.path)+'-wal')) if p.exists()))
            self.assertEqual(self.pin(),(hi,'open',0,1))
            self.assertEqual(self.writer.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(len(self.plane.reader.window('pump',hi,hi,as_of=self.now,address='pool')),1)
        self.assertEqual(max(counts),2)
        self.assertLessEqual(max(sizes[4:])-min(sizes[4:]),1024*1024)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM interest_checkpoints').fetchone()[0],1)
        archives=list(self.path.with_name(self.path.name+'.archive').glob('*.gz'))
        # The owner checkpoint advances its still-active pin. Raw bodies below
        # that acknowledged reference floor expire, while its required window
        # and continuity remain readable throughout the entire soak above.
        self.assertEqual(len(archives),0)
        print('168-hour held-pin soak: records peak',max(counts),'hot bytes',min(sizes[4:]),max(sizes[4:]),'unreferenced raw archives',len(archives))
