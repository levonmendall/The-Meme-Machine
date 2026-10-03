import asyncio,tempfile,time,unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tests.lanes.meteora.test_run381_retention_progress import record
from unittest.mock import patch

from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceReader,EvidenceWriter
import meme_machine.lanes.meteora.solana_evidence_service as service
from meme_machine.lanes.meteora.solana_retention_outcome import RetentionOutcome
from tests.lanes.meteora.test_run373_dispatch_throughput import SustainedSocket,database_ready,local_server


class StageE19MaintenanceBatchFairnessTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self,predicate,attempts=5000,delay=.01):
        for _ in range(attempts):
            if predicate():return
            await asyncio.sleep(delay)
        self.fail('condition_not_met')

    async def test_maintenance_pressure_limits_source_batches_to_one_frame(self):
        frames=32
        socket=SustainedSocket(
            frames=frames,interval=.005,padding_bytes=64*1024,
            relevant_transactions=4,
        )
        stop=asyncio.Event()
        original_transaction=EvidenceWriter.transaction
        class SeededState(service.ServiceState):
            def __init__(self,path,config):
                super().__init__(path,config)
                # Single-authority pressure must come from actual eligible
                # evidence, not a fabricated outcome of an independent loop.
                now=time.time()
                self.writer.ingest([replace(record(),scope='program:meteora',
                    identity='maintenance-pressure:'+str(i),slot=10+i,
                    market_time=int(now)-185,observed_at=now) for i in range(400)])

        @contextmanager
        def delayed_transaction(writer):
            outer=not writer.db.in_transaction
            with original_transaction(writer):
                yield
            if outer:
                time.sleep(.02)

        with tempfile.TemporaryDirectory() as temp,patch(
            'meme_machine.lanes.meteora.solana_evidence_service.time.time',return_value=1790439000
        ),patch.object(
            EvidenceWriter,'transaction',delayed_transaction
        ),patch.object(
            service.ServiceState,'archive_plan',return_value=None
        ),patch.object(
            service.ServiceState,'retention',return_value=RetentionOutcome(pending=True)
        ),patch(
            'websockets.asyncio.client.connect',return_value=socket
        ),patch.object(service,'ServiceState',SeededState),patch(
            'asyncio.start_unix_server',side_effect=local_server
        ):
            path=Path(temp)/'db'
            runner=asyncio.create_task(service.serve(
                path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop
            ))
            try:
                await self.wait_for(lambda:database_ready(path),attempts=2500)
                reader=EvidenceReader(path)
                await self.wait_for(
                    lambda:(reader.telemetry()['service_health'].get('ipc') or {}).get(
                        'stream.commit_messages',0
                    )>=frames+1,
                    attempts=5000,
                )
                ipc=reader.telemetry()['service_health']['ipc']
                limited=ipc.get('stream.maintenance_limited_commit_batches',0)
                self.assertGreater(limited,0)
                self.assertEqual(
                    ipc.get('stream.maintenance_limited_commit_messages',0),
                    limited,
                )
                self.assertEqual(ipc.get('stream.dispatch_queue_overflow',0),0)
                self.assertLessEqual(
                    ipc.get('stream.commit_batch_bytes_peak',0),
                    service.STREAM_COMMIT_BATCH_MAX_BYTES,
                )
                reader.close()
            finally:
                stop.set()
                await asyncio.gather(runner,return_exceptions=True)


if __name__=='__main__':
    unittest.main()
