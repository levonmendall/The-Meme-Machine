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


class NativeComponentPerformance(unittest.TestCase):
    def test_actual_paper_original_add_rounding_and_final_settlement(self):
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.component_performance import paper_report
        for lane in ('pump-acceleration','pumpswap-survivor-momentum-v1','pons-postgrad-survivor-momentum-v1'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td,closing(
                    PaperBook(Path(td)/'native.sqlite',run_id='run',lane=lane,policy_hash='p',initial=10000)) as book:
                identity='run:trade';book.reserve(identity,200,1,{})
                book.transition(identity,'filled',2,amount=101,tokens=7,evidence={'execution':{'gas':1}})
                book.transition(identity,'partial_harvest',3,amount=37,tokens=2)
                book.transition(identity,'scale_add',4,amount=51,tokens=3,evidence={'request':'actual-add','execution':{'gas':1}})
                book.transition(identity,'mark',5,amount=99999)
                before=book.reconcile();marked=paper_report(book,identity)
                self.assertEqual(book.reconcile(),before)
                self.assertEqual(marked['totals']['booked_cost'],152)
                self.assertEqual(marked['totals']['realized_pnl'],9)
                self.assertIsNone(marked['component_unrealized_pnl'])
                book.transition(identity,'partial_harvest',6,amount=65,tokens=3)
                partial=paper_report(book,identity)
                self.assertEqual(partial['events'][-1]['allocations']['original'],
                    dict(quantity=1,basis_released=27,net_proceeds=21,realized_pnl=-6))
                self.assertEqual(partial['events'][-1]['allocations']['add'],
                    dict(quantity=2,basis_released=19,net_proceeds=44,realized_pnl=25))
                book.transition(identity,'settled',7,amount=147)
                report=paper_report(book,identity);p=book._load(identity)
                self.assertEqual(report['state'],'AVAILABLE')
                self.assertEqual(report['totals']['realized_pnl'],p['realized'])
                self.assertEqual(report['totals']['realized_pnl'],97)
                self.assertEqual(report['totals']['booked_cost'],152)
                self.assertEqual(report['totals']['net_proceeds'],249)
                self.assertEqual(report['totals']['remaining_quantity'],0)
                self.assertEqual(report['totals']['remaining_basis'],0)
                self.assertEqual(report['components']['original']['realized_pnl'],74)
                self.assertEqual(report['components']['add']['realized_pnl'],23)
                self.assertEqual([e['at'] for e in report['events']],[2,3,4,6,7])
                self.assertIsNone(report['hypothetical_no_add'])
                self.assertIsNone(report['causal_profit_from_add'])

    def test_pons_prefix_restart_and_read_only_completed_adapter(self):
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.runtime.component_performance import pons_report,pons_path_report
        from meme_machine.runtime.storage import compact_pons
        fixture=PartialAccountingTests()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'native.sqlite';store=Store(path)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000000,delay=1,natural_policy_hash=POLICY_HASH)
            identity='actual-lifecycle'
            paper.reserve(identity,market='m',amount=100,gas_budget=20,now=100,features=fixture.features(100))
            paper.advance(identity,now=101,action='entry',quote=fixture.quote(101,'buy',100,7))
            paper.advance(identity,now=102,action='exit_intent',exit_tokens=2)
            paper.advance(identity,now=103,action='exit',quote=fixture.quote(103,'sell',2,37))
            before=pons_report(paper,identity)
            self.assertTrue(compact_pons(paper,limit=1))
            self.assertEqual(pons_report(paper,identity),before)
            store.close();store=Store(path)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000000,delay=1,natural_policy_hash=POLICY_HASH)
            paper.advance(identity,now=104,action='scale_add',quote=fixture.quote(104,'buy',50,3),cancel_reason='actual-add')
            paper.advance(identity,now=105,action='exit_intent')
            paper.advance(identity,now=106,action='exit',quote=fixture.quote(106,'sell',8,147))
            expected=paper._get(identity);report=pons_report(paper,identity)
            self.assertEqual(report['state'],'AVAILABLE')
            self.assertEqual(report['totals']['booked_cost'],expected['cost'])
            self.assertEqual(report['totals']['net_proceeds'],expected['realized_proceeds'])
            self.assertEqual(report['totals']['realized_pnl'],expected['realized_pnl'])
            store.close()
            original=path.read_bytes()
            self.assertEqual(pons_path_report(path,expected),report)
            self.assertEqual(path.read_bytes(),original)
            store=Store(path)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000000,delay=1,natural_policy_hash=POLICY_HASH)
            self.assertTrue(compact_pons(paper,limit=1))
            from meme_machine.lanes.pons.evidence import canonical,digest
            saved=json.loads(store.db.execute('SELECT body FROM pons_journal_checkpoint WHERE id=1').fetchone()[0])
            saved['positions'][identity].pop('component_performance')
            store.db.execute('UPDATE pons_journal_checkpoint SET body=?,hash=? WHERE id=1',(canonical(saved),digest(saved)))
            missing=pons_report(paper,identity)
            self.assertEqual(missing['state'],'UNAVAILABLE')
            self.assertEqual(missing['reason'],'retired_component_detail')
            self.assertEqual(missing['totals']['booked_cost'],expected['cost'])
            store.close()

    def test_duplicate_economic_event_and_missing_original_detail(self):
        from meme_machine.runtime.component_performance import extend_native,coverage
        reserve=dict(action='reserved',at=1,position=dict(id='x',status='reserved',tokens=0,basis=0,realized=0))
        fill=dict(action='filled',at=2,position=dict(id='x',status='open',tokens=3,basis=101,realized=0))
        report=extend_native([reserve,fill],adapter='paper',lifecycle_id='x')
        self.assertEqual(extend_native([fill],report,adapter='paper',lifecycle_id='x'),report)
        missing=extend_native([fill],adapter='paper',lifecycle_id='x')
        self.assertEqual(missing['state'],'UNAVAILABLE')
        self.assertIsNone(missing['components'])
        self.assertEqual(missing['totals']['remaining_basis'],101)
        counts=coverage([report,missing],missing_records=4)
        self.assertEqual((counts['records'],counts['available'],counts['unavailable']),(6,1,5))
        self.assertFalse(counts['complete_component_coverage'])

    def test_native_rounding_zero_quantity_basis_allocation_is_reported_until_final_release(self):
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.component_performance import paper_report
        with tempfile.TemporaryDirectory() as td,closing(PaperBook(Path(td)/'native.sqlite',
                run_id='run',lane='fixture',policy_hash='p',initial=10000)) as book:
            identity='run:rounding';book.reserve(identity,100,1,{})
            book.transition(identity,'filled',2,amount=1,tokens=99)
            book.transition(identity,'scale_add',3,amount=99,tokens=1,evidence={'request':'native-add'})
            book.transition(identity,'partial_harvest',4,amount=5,tokens=1)
            report=paper_report(book,identity)
            self.assertEqual(report['components']['add']['remaining_quantity'],0)
            self.assertEqual(report['components']['add']['remaining_basis'],98)
            self.assertEqual(report['totals']['remaining_basis'],book._load(identity)['basis'])
            book.transition(identity,'settled',5,amount=99)
            final=paper_report(book,identity)
            self.assertEqual(final['components']['add']['remaining_basis'],0)
            self.assertEqual(sum(c['realized_pnl'] for c in final['components'].values()),book._load(identity)['realized'])


class LearningRetention(unittest.TestCase):
    def test_robinhood_empty_tape_maintenance_seeks_retirement_boundaries(self):
        from meme_machine.runtime.robinhood.plane import Plane
        with tempfile.TemporaryDirectory() as td:
            p=Plane(Path(td)/'plane.sqlite',clock=lambda:100.)
            self.addCleanup(p.close)
            p.observe('base','pons','first',{},ordering=(1,),watermark={},interpretation={},
                observed=100,deadline=105,priority=2)
            columns=[r[1] for r in p.db.execute('PRAGMA table_info(candidates)')]
            expressions=["'candidate:'||?" if col=='id' else col for col in columns]
            with p.transaction():
                p.db.executemany('INSERT INTO candidates SELECT '+','.join(expressions)+
                    " FROM candidates WHERE id='base'",[(n,) for n in range(2000)])
                p.db.execute('UPDATE candidates SET pending=0')
            before=p.db.execute('SELECT * FROM candidates ORDER BY id').fetchall()
            steps=[0]
            p.db.set_progress_handler(lambda:steps.__setitem__(0,steps[0]+1) or 0,1)
            try:p.maintain()
            finally:p.db.set_progress_handler(None,0)
            self.assertLess(steps[0],1000,'maintenance traverses the quiet population on an empty tape')
            self.assertEqual(p.db.execute('SELECT * FROM candidates ORDER BY id').fetchall(),before)
            self.assertEqual(p._maintenance_due,160.)
            self.assertEqual(p.db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],0)

    def test_robinhood_retirement_seek_preserves_paused_orphan_and_null_clocks(self):
        from meme_machine.runtime.robinhood.plane import Plane
        with tempfile.TemporaryDirectory() as td:
            now=[86409.]
            p=Plane(Path(td)/'plane.sqlite',clock=lambda:now[0]);self.addCleanup(p.close)
            p.observe('active','pons','first',{},ordering=(1,),watermark={},interpretation={},
                observed=100,deadline=90000,priority=2)
            p.observe('paused','ramses','first',{},ordering=(1,),watermark={},interpretation={},
                observed=100,deadline=90000,priority=2)
            p.db.execute('UPDATE candidates SET pending=0')
            p.db.executemany('INSERT INTO rolling VALUES(?,?,?,?,?,?)',[
                ('paused','p',1,1,'{}','{}'),('orphan','o',2,2,'{}','{}'),
                ('active','n',None,3,'{}','{}'),('active','a',10,10,'{}','{}')])
            with patch.dict(os.environ,MM_OPERATIONAL_PHASE='continuous'):
                old_min=p.db.execute("SELECT MIN(at) FROM rolling WHERE candidate IN (SELECT id FROM candidates WHERE lane IN ('pump','pons'))").fetchone()[0]
                p.maintain()
                self.assertEqual(old_min,10)
                self.assertAlmostEqual(p._maintenance_due,86410.000001)
                self.assertEqual(p.db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],4)
                now[0]=86411.;p.maintain()
                self.assertEqual([tuple(r) for r in p.db.execute('SELECT candidate,identity FROM rolling ORDER BY candidate,identity')],
                    [('active','n'),('orphan','o'),('paused','p')])
                self.assertEqual(p.get('active')['generation'],1)
                self.assertEqual(p.get('paused')['generation'],1)

    def test_gapped_retained_audit_population_avoids_repeated_filtered_offset_scan(self):
        import sqlite3
        from meme_machine.runtime.storage import audit_ring
        db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(db.close)
        db.execute('CREATE TABLE diagnostic(seq INTEGER PRIMARY KEY,value TEXT)')
        db.executemany('INSERT INTO diagnostic VALUES(?,?)',[(n,'old') for n in (10,100,1000,10000)])
        db.execute("CREATE TRIGGER guard BEFORE DELETE ON diagnostic BEGIN SELECT RAISE(ABORT,'append_only'); END")
        sql=[];db.set_trace_callback(sql.append)
        for _ in range(20):audit_ring(db,'diagnostic','guard',limit=4,where="value='old'")
        self.assertFalse(any('OFFSET' in s for s in sql))
        self.assertEqual(db.execute('SELECT seq FROM diagnostic ORDER BY seq').fetchall(),[(10,),(100,),(1000,),(10000,)])
        db.execute("INSERT INTO diagnostic VALUES(10001,'old')")
        audit_ring(db,'diagnostic','guard',limit=4,where="value='old'")
        self.assertEqual(db.execute('SELECT seq FROM diagnostic ORDER BY seq').fetchall(),[(100,),(1000,),(10000,),(10001,)])
        with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):db.execute('DELETE FROM diagnostic')
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
