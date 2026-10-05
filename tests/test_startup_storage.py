import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from meme_machine.startup_storage import recover
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
from meme_machine.solana_evidence_service import FinalizedFence
from tests.test_solana_evidence_plane import record,proof


class StartupStorage(unittest.IsolatedAsyncioTestCase):
    async def test_old_cold_debt_drains_without_resetting_pins_gaps_or_source_time(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.sqlite';writer=EvidenceWriter(path,clock=lambda:1000)
            FinalizedFence(writer,endpoint_identity='offline')
            rows=[replace(record(),identity='r'+str(i),signature='s'+str(i),slot=i,market_time=i) for i in range(10,41)]
            writer.ingest(rows,proof=proof(10,40))
            writer.interest('position',rows[0].scope,lower_slot=30,priority=0,lifecycle='open')
            writer.gap(rows[0].scope,35,36)
            original_interests=writer.db.execute('SELECT * FROM interests').fetchall()
            original_gaps=writer.db.execute('SELECT * FROM gaps').fetchall()
            class State:
                def __init__(self):self.writer=writer;self.fence=SimpleNamespace(session='cold-generation')
                def archive_plan(self):return writer.archive_snapshot(820,max_records=1000)
                def archive_commit_slice(self,plan,receipt):
                    writer.commit_archive(plan[:512],receipt);return plan[512:]
                def retention(self):return writer.retain(820,archive_first=False,checkpoint=False)
            state=State();calls=[]
            async def work(fn,priority,**kwargs):
                calls.append(kwargs['label']);return fn(state)
            with ThreadPoolExecutor(max_workers=1) as pool:
                await recover(work,pool,path,asyncio.Event(),wall=lambda:1000)
            self.assertIn('archive_commit_plan',calls)
            self.assertEqual(writer.db.execute('SELECT * FROM interests').fetchall(),original_interests)
            self.assertEqual(writer.db.execute('SELECT * FROM gaps').fetchall(),original_gaps)
            self.assertEqual(writer.db.execute('SELECT MIN(market_time) FROM records').fetchone()[0],30)
            self.assertEqual(writer.db.execute('SELECT MIN(observed) FROM lineage').fetchone()[0],100)
            writer.close()

    async def test_fresh_store_skips_cleanup_entirely(self):
        with tempfile.TemporaryDirectory() as td:
            writer=EvidenceWriter(Path(td)/'evidence.sqlite',clock=lambda:100)
            FinalizedFence(writer,endpoint_identity='offline')
            writer.ingest([record()],proof=proof())
            state=SimpleNamespace(writer=writer,fence=SimpleNamespace(session='fresh'))
            calls=[]
            async def work(fn,priority,**kwargs):calls.append(kwargs['label']);return fn(state)
            await recover(work,None,writer.path,asyncio.Event(),wall=lambda:100)
            self.assertEqual(calls,['maintenance_decision']);self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
            writer.close()
