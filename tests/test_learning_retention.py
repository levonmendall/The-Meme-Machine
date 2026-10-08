"""Offline learning/raw-retention safety, with actual native SQLite reducers."""
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.runtime import learning
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
from tests.test_solana_evidence_plane import record,proof


class LearningRetention(unittest.TestCase):
    def test_learning_keeps_exact_derived_features_and_discards_full_raw_reconstruction(self):
        with closing(sqlite3.connect(':memory:')) as db,db:
            db.execute('BEGIN')
            features=dict(blocks=4,velocity='7/3',buyers=[1,2])
            learning.save(db,'decision','asset','current',1,dict(feature_vector=features,
                raw_payload='discard',transactions=[dict(raw='discard')],snapshot=dict(account_data='discard')))
            facts=learning.get(db,'decision')['facts']
            self.assertEqual(facts,dict(feature_vector=features))

    def test_open_position_reservation_gap_and_recovery_references_keep_raw(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.sqlite'
            writer=EvidenceWriter(path,clock=lambda:1000)
            rows=[replace(record(),identity='r'+str(i),signature='s'+str(i),slot=i,market_time=i) for i in range(10,31)]
            writer.ingest(rows,proof=proof(10,30))
            for owner,kind,floor in [('open-position','open',20),('reservation','reserved',22),('pending-recovery','open',24)]:
                writer.interest(owner,rows[0].scope,lower_slot=floor,priority=0,lifecycle=kind)
            writer.gap(rows[0].scope,25,26)
            writer.retain(1000)
            with closing(EvidenceReader(path)) as reader:
                self.assertEqual(len(reader.window(rows[0].scope,20,24,as_of=2000)),5)
            kept=writer.db.execute('SELECT slot,body FROM records ORDER BY slot').fetchall()
            self.assertEqual([s for s,_ in kept],list(range(20,31)))
            self.assertTrue(all(body is not None for _,body in kept))
            writer.close()
            writer=EvidenceWriter(path,clock=lambda:1001)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],11)
            writer.close()

    def test_rejected_fifty_x_winner_features_survive_raw_ring_and_low_value_pressure(self):
        from tests.test_opportunity_telemetry import OpportunityTelemetryTests
        from meme_machine.runtime import opportunity_telemetry as telemetry
        fixture=OpportunityTelemetryTests();fixture.setUp()
        try:
            before=fixture.financial();decision=fixture.decision();fixture.reject()
            db=fixture.sleeve.db
            receipt_id=db.execute("SELECT id FROM opportunity_journal_v1 WHERE kind='receipt'").fetchone()[0]
            with fixture.sleeve.transaction():
                telemetry.observe_prices(db,'pons','pons:token',[dict(at=200,price=str(51*10**18),low=str(10**18//2),high=str(51*10**18))],source_hash='observed-proof')
                telemetry.enrich(db,now=400)
                with patch.object(telemetry,'MAX_JOURNAL_ROWS',4):
                    for i in range(40):telemetry.append(db,'price:'+str(i),'price','pons:other',500+i,dict(price='1',low='1',high='1'))
                for i in range(100):learning.save(db,'ordinary:'+str(i),'other','current',1000+i,dict(rejected=True),priority=0,max_rows=16)
            self.assertIsNone(db.execute('SELECT 1 FROM opportunity_journal_v1 WHERE id=?',(receipt_id,)).fetchone())
            receipt=learning.get(db,receipt_id)
            self.assertEqual(receipt['facts']['feature_vector'],decision['vector'])
            self.assertEqual(receipt['facts']['rejection_reasons'],['curve_velocity'])
            outcome=learning.get(db,'outcome:'+receipt_id+':300')['facts']
            self.assertEqual(outcome['right_tail'],dict.fromkeys(('5x','10x','25x','50x'),True))
            self.assertEqual(outcome['evaluated_opportunity']['feature_vector'],decision['vector'])
            self.assertEqual(before,fixture.financial());self.assertTrue(telemetry.verify(db)['verified'])
        finally:fixture.tearDown()

    def test_incomplete_evidence_has_only_observed_lower_bound_no_fabricated_outcome(self):
        with closing(sqlite3.connect(':memory:')) as db,db:
            db.execute('BEGIN')
            body=dict(receipt_id='unknown',maximum_favorable_excursion_bps=None,
                      reference_price='1',observed_maximum_price='10',evidence_retention_complete=False)
            learning.opportunity(db,'partial','outcome','asset',10,body)
            facts=learning.get(db,'partial')['facts']
            self.assertIsNone(facts['right_tail']['5x'])
            self.assertTrue(facts['observed_right_tail']['10x'])
            self.assertFalse(facts['evidence_retention_complete'])

    def test_survivor_open_state_exact_then_terminal_learning_survives_deletion(self):
        from meme_machine.runtime.survivor_history import History
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite';h=History(path,policy='unchanged-policy')
            row=h.graduate('winner',dict(at=1,identity='winner'))
            h.append('winner',through=5,events=[],points=[(2,'1'),(3,'5'),(4,'25'),(5,'50')],complete=True)
            row=h.get('winner');row.update(position='native-open',state='filled');h.save(row)
            with self.assertRaisesRegex(ValueError,'open_position'):h.retire(row)
            original=h.facts('winner',5);h.close();h=History(path,policy='unchanged-policy')
            self.assertEqual(h.facts('winner',5),original);self.assertEqual(h.get('winner'),row)
            row.update(position=None,state='settled');h.retire(row,expired_before=10)
            self.assertEqual(h.db.execute('SELECT COUNT(*) FROM points').fetchone()[0],0)
            facts=learning.get(h.db,'survivor:winner')['facts']
            self.assertTrue(facts['right_tail']['50x']);self.assertEqual(facts['candidate_state']['state'],'settled')
            h.close();h=History(path,policy='unchanged-policy')
            self.assertEqual(learning.get(h.db,'survivor:winner')['facts'],facts);h.close()

    def test_raw_gc_replays_unlink_before_commit_and_preserves_referenced_archive(self):
        from meme_machine.solana_retention_outcome import RetentionProgress
        with tempfile.TemporaryDirectory() as td:
            w=EvidenceWriter(Path(td)/'evidence.sqlite',clock=lambda:1000)
            w.ingest([record()]);plan=w.archive_plan(1000);receipt=w.write_archive(w.path,plan);w.commit_archive(plan,receipt)
            directory=w.path.parent/(w.path.name+'.archive');target=directory/receipt['name']
            with w.transaction():w.db.execute('INSERT INTO archive_gc VALUES(?)',(receipt['name'],))
            w._retention_housekeeping(32,RetentionProgress())
            self.assertTrue(target.exists());self.assertTrue(w.db.execute('SELECT archive FROM records').fetchone()[0])
            w.retain(1000);self.assertFalse(target.exists())
            with w.transaction():w.db.execute('INSERT INTO archive_gc VALUES(?)',(receipt['name'],))
            w._retention_housekeeping(32,RetentionProgress())
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM archive_gc').fetchone()[0],0);w.close()

    def test_compact_learning_row_byte_limits_rollups_and_healthy_wal(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'learning.sqlite';db=sqlite3.connect(path)
            db.execute('PRAGMA journal_mode=WAL')
            for day in range(168):
                with db:
                    db.execute('BEGIN')
                    for i in range(20):learning.save(db,f'{day}:{i}','asset','current',day*86400+i,
                        dict(features=[(day+i+j)%101 for j in range(100)],rejection='gate'),max_rows=32,max_bytes=8192)
                busy,_,_=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone();self.assertEqual(busy,0)
                self.assertLessEqual(Path(str(path)+'-wal').stat().st_size,4096)
                self.assertLess(path.stat().st_size,128*1024)
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM learning_facts_v1').fetchone()[0],32)
            self.assertLessEqual(db.execute('SELECT SUM(bytes) FROM learning_facts_v1').fetchone()[0],8192)
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM learning_rollup_v1').fetchone()[0],4)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
            db.close()

    def test_killed_archive_publication_expires_only_after_all_references_end(self):
        with tempfile.TemporaryDirectory() as td:
            clock=[1000];w=EvidenceWriter(Path(td)/'evidence.sqlite',clock=lambda:clock[0])
            w.ingest([record()],proof=proof());plan=w.archive_plan(1000)
            receipt=w.write_archive(w.path,plan) # Simulate worker death before commit.
            directory=w.path.parent/(w.path.name+'.archive');target=directory/receipt['name']
            marker=directory/(receipt['name']+'.pending');os.utime(marker,(1000,1000))
            self.assertFalse(w.archive_orphan_probe_due())
            w._reclaim_published_orphans();self.assertTrue(marker.exists());self.assertTrue(target.exists())
            os.utime(marker,(0,0));clock[0]=90000
            self.assertTrue(w.archive_orphan_probe_due())
            w._reclaim_published_orphans();self.assertTrue(target.exists())
            w.ingest([record(slot=11,observed=100)],proof=proof(11,11))
            clock[0]+=1000;w.retain(clock[0]);clock[0]+=61;w.retain(clock[0])
            self.assertFalse(target.exists());self.assertFalse(marker.exists())
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0);w.close()

    def test_long_duration_raw_archive_and_debug_growth_bounded(self):
        from meme_machine.runtime.storage import jsonl_ring
        with tempfile.TemporaryDirectory() as td:
            clock=[1000];w=EvidenceWriter(Path(td)/'evidence.sqlite',clock=lambda:clock[0])
            for day in range(168):
                slot=10+day;clock[0]=1000+day*86400
                w.ingest([record(slot=slot,identity='r'+str(day),observed=clock[0])],proof=proof(slot,slot,at=clock[0]))
                clock[0]+=1000 # Authenticated continuity window has expired too.
                w.retain(clock[0]);w.finish_checkpoint()
                jsonl_ring(Path(td)/'debug.jsonl',dict(day=day),limit=8)
                self.assertLess(sum(p.stat().st_size for p in Path(td).rglob('*') if p.is_file()),512*1024)
                self.assertEqual(len(list(Path(td).glob('*.archive/*.gz'))),0)
            self.assertEqual(len((Path(td)/'debug.jsonl').read_text().splitlines()),8);w.close()

    def test_pipeline_learning_folds_without_changing_native_pipeline_decisions(self):
        from meme_machine.lanes.meteora.pipeline import Pipeline
        from meme_machine.runtime.storage import audit_ring
        with tempfile.TemporaryDirectory() as td:
            p=Pipeline(Path(td)/'pipeline.sqlite','meteora','original-policy')
            for i in range(20):p.record('candidate:'+str(i),'rejected',reason='liquidity',features=dict(depth=i))
            snapshot=p.snapshot()
            with p.db:audit_ring(p.db,'progress','progress_no_delete',key='sequence',limit=4)
            self.assertEqual(p.snapshot(),snapshot) # Learning does not touch the native in-memory decision/index.
            fact=learning.get(p.db,'pipeline:1')['facts'];self.assertEqual(fact['inputs_and_outcome']['features'],dict(depth=0))
            self.assertEqual(fact['rejection_reason'],'liquidity');p.close()

    def test_empty_survivor_observations_do_not_consume_learning_storage(self):
        from meme_machine.runtime.survivor_history import History
        with tempfile.TemporaryDirectory() as td:
            h=History(Path(td)/'history.sqlite',policy='unchanged')
            for i in range(50):
                row=h.graduate(str(i),dict(at=i));h.retire(row,expired_before=i+1)
            self.assertEqual(h.db.execute('SELECT COUNT(*) FROM learning_facts_v1').fetchone()[0],0)
            self.assertEqual(len(h.rows(include_retired=True)),50)
            h.close()

    def test_default_learning_bounds_plateau_under_long_material_churn(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'learning.sqlite';db=sqlite3.connect(path)
            db.execute('PRAGMA journal_mode=WAL')
            sizes=[]
            # Exercise the production bound itself, not a test-only small cap.
            for cycle in range(3):
                with db:
                    db.execute('BEGIN')
                    for i in range(9000 if cycle==0 else 3000):
                        identity=str(cycle)+':'+str(i)
                        learning.save(db,identity,'asset:'+identity,'current',cycle*86400+i,
                            dict(feature_vector=dict(velocity=i%37,liquidity=i%19),
                                 rejection_reasons=['liquidity'],strategy_policy_version='frozen'))
                self.assertEqual(db.execute('SELECT records FROM learning_usage_v1').fetchone()[0],learning.MAX_ROWS)
                self.assertLessEqual(db.execute('SELECT bytes FROM learning_usage_v1').fetchone()[0],learning.MAX_BYTES)
                self.assertLessEqual(db.execute('SELECT COUNT(*) FROM learning_rollup_v1').fetchone()[0],4)
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                sizes.append(path.stat().st_size)
            self.assertLessEqual(max(sizes)-min(sizes),256*1024,sizes)
            self.assertLess(Path(str(path)+'-wal').stat().st_size,4096)
            self.assertLess(sum(p.stat().st_size for p in Path(td).iterdir()),8*1024*1024)
            db.close()
