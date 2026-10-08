"""Read-only evidence handles must stay on their creating worker thread."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests.test_solana_evidence_plane import proof

class RuntimeEvidenceOwnershipTests(unittest.TestCase):
    def test_shared_runtime_facade_owns_independent_reader_per_thread(self):
        for namespace in ('meme_machine','meme_machine.lanes.pump','meme_machine.lanes.meteora'):
            with self.subTest(namespace=namespace),tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'evidence.sqlite'
                writer=EvidenceWriter(path,clock=lambda:100)
                writer.ingest([],proof=proof(10,10,scope='program:meteora'))
                cls=importlib.import_module(namespace+'.solana_evidence_runtime').RuntimeEvidence
                plane=cls(path,owner='meteora',clock=lambda:100)
                try:
                    with patch.object(plane,'require_usable',return_value={'usable':True}):
                        main_db=plane.reader.db
                        self.assertEqual(plane.frontier('program:meteora'),10)
                        def work():
                            db=plane.reader.db
                            try:
                                self.assertIsNot(db,main_db)
                                self.assertEqual(plane.frontier('program:meteora'),10)
                            finally:plane.close()
                            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
                            return True
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            self.assertTrue(pool.submit(work).result(timeout=3))
                        self.assertIs(plane.reader.db,main_db)
                        self.assertEqual(plane.frontier('program:meteora'),10)
                finally:plane.close();writer.close()

    def test_actual_meteora_position_poll_does_not_use_main_reader(self):
        from meme_machine.lanes.meteora import runner
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'evidence.sqlite';writer=EvidenceWriter(path,clock=lambda:100)
            writer.ingest([],proof=proof(10,10,scope=runner.METEORA_SCOPE))
            plane=runner.RuntimeEvidence(path,owner='meteora',clock=lambda:100)
            try:
                with patch.object(runner,'EVIDENCE_PLANE',plane),patch.object(plane,'require_usable',return_value={'usable':True}):
                    self.assertEqual(plane.frontier(runner.METEORA_SCOPE),10)
                    def work():
                        try:return runner._new_finalized_swaps(None,'pool',10)
                        finally:plane.close()
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        rows,meta=pool.submit(work).result(timeout=3)
                    self.assertEqual(rows,[]);self.assertEqual(meta['head_slot'],10)
                    self.assertEqual(plane.frontier(runner.METEORA_SCOPE),10)
            finally:plane.close();writer.close()

    def test_unused_worker_close_never_opens_or_closes_main_handle(self):
        from meme_machine.solana_evidence_runtime import RuntimeEvidence
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'evidence.sqlite')
            plane=RuntimeEvidence(writer.path,owner='meteora')
            try:
                db=plane.reader.db
                with patch('meme_machine.solana_evidence_runtime.EvidenceReader',side_effect=AssertionError('close opened reader')):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(plane.close).result(timeout=3)
                self.assertIs(plane.reader.db,db);self.assertEqual(db.execute('SELECT 1').fetchone()[0],1)
            finally:plane.close();writer.close()

    def test_meteora_continuation_closes_reader_on_owning_thread(self):
        import threading
        from types import SimpleNamespace
        from meme_machine.runtime import lifecycle_timing
        from meme_machine.solana_evidence_runtime import RuntimeEvidence
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'evidence.sqlite')
            plane=RuntimeEvidence(writer.path,owner='meteora')
            main_db=plane.reader.db;closed=threading.Event();owners=[]
            def lifecycle(*args,**kwargs):
                db=plane.reader.db
                self.assertIsNot(db,main_db)
                self.assertEqual(db.execute('SELECT 1').fetchone()[0],1)
                owners.append(threading.get_ident())
                return {'complete':True},None
            module=SimpleNamespace(_triggered_warmup=lambda *a,**k:None,
                _lifecycle=lifecycle,provider=SimpleNamespace(AlchemyPacer=lambda:None),
                _prove_network_identity=lambda *a:None,_new_adapter=lambda *a:None,
                EvidenceBroker=lambda *a:SimpleNamespace(close=lambda:None),
                DLMM_BROKER_DB=str(Path(temp)/'broker.sqlite'),digest=lambda *a:'offline',
                EVIDENCE_PLANE=plane)
            book=SimpleNamespace(path=Path(temp)/'native.sqlite',reconcile=lambda:{'unsettled':0})
            real_close=plane.close
            def own_close():
                self.assertIn(threading.get_ident(),owners)
                try:real_close()
                finally:closed.set()
            try:
                lifecycle_timing.install_meteora(module)
                with patch.object(plane,'close',side_effect=own_close),patch.object(lifecycle_timing,'_atomic_json'):
                    proxy,_=module._lifecycle(None,'pool',{'slot':10,'time':100},{},
                        {'range':{'max_holding_seconds':60}},None,[],book=book)
                    self.assertTrue(closed.wait(2))
                    self.assertTrue(proxy.get('complete'),proxy)
                    self.assertEqual(len(owners),1)
                self.assertIs(plane.reader.db,main_db)
                self.assertEqual(main_db.execute('SELECT 1').fetchone()[0],1)
            finally:plane.close();writer.close()
