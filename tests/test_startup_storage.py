import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from meme_machine.startup_storage import recover
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
from meme_machine.solana_evidence_service import FinalizedFence, ServiceState
from tests.test_solana_evidence_plane import record,proof


class StartupStorage(unittest.IsolatedAsyncioTestCase):
    async def test_sparse_address_pin_observation_fits_existing_vm_budget(self):
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.solana_maintenance_state import DebtAgeAdapter, OBSERVATION_VM_STEPS
        with tempfile.TemporaryDirectory() as td:
            state=ServiceState(Path(td)/'evidence.sqlite',AlchemyEndpoint.parse(
                'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            writer=state.writer;writer.clock=lambda:1000
            self.addCleanup(writer.close)
            rows=[replace(record(),identity='dense'+str(i),signature='s'+str(i),
                scope='program:meteora',slot=1000+i//20,market_time=800,observed_at=1000,
                addresses=('protected-pool',) if i%4000==0 else ('unrelated-pool',))
                for i in range(20000)]
            for start in range(0,len(rows),1000):writer.ingest(rows[start:start+1000])
            writer.interest('position','program:meteora',lower_slot=1000,priority=0,lifecycle='open')
            writer.interest('overlapping-position','program:meteora',lower_slot=1200,priority=0,lifecycle='open')
            with writer.transaction():
                writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',
                    ('position','program:meteora','protected-pool','transactions'))
                writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',
                    ('overlapping-position','program:meteora','protected-pool','transactions'))
            before=writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0]
            adapter=DebtAgeAdapter(writer,wall=lambda:1000)
            observation=adapter.observe(state.fence.session)
            scope=next(s for s in observation.scopes if s.scope=='program:meteora')
            self.assertEqual(scope.hot_eligible,19995)
            self.assertEqual(scope.hot_oldest,800)
            self.assertEqual(scope.pins,2)
            self.assertLessEqual(adapter.steps,OBSERVATION_VM_STEPS)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],before)
            while writer.archive(820):pass
            remaining=writer.db.execute('SELECT identity FROM records WHERE body IS NOT NULL').fetchall()
            self.assertEqual({r[0] for r in remaining},{'dense'+str(i) for i in range(0,20000,4000)})

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
