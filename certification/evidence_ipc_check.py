"""Real Unix IPC with a fake authoritative socket; no external connections."""
import asyncio,json,tempfile
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_service import serve
from meme_machine.solana_evidence_runtime import RuntimeEvidence,SWAP_SCOPE
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from tests.test_solana_evidence_service_runtime import FakeSocket

async def main():
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'evidence';socket=FakeSocket();stop=asyncio.Event()
        with patch('websockets.asyncio.client.connect',return_value=socket):
            task=asyncio.create_task(serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-fixture',stop=stop))
            try:
                for _ in range(200):
                    if task.done():await task
                    if Path(str(path)+'.sock').exists():break
                    await asyncio.sleep(.01)
                def consumer():
                    client=RuntimeEvidence(path,owner='pump')
                    try:
                        client.interest(SWAP_SCOPE,lower_slot=100,addresses=['offline-account'],lifecycle='reserved',priority=1)
                        assert client.reader.db.execute('SELECT lifecycle FROM interests').fetchone()[0]=='reserved'
                        try:client.command(op='coverage',lower_slot=0,upper_slot=100000)
                        except EvidenceUnavailable:pass
                        else:raise AssertionError('consumer_manufactured_coverage')
                        assert client.reader.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0]==0
                        try:client.command(op='release',scope=SWAP_SCOPE,resolved=False)
                        except EvidenceUnavailable:pass
                        else:raise AssertionError('unresolved_reservation_unpinned')
                        return dict(real_unix_ipc=True,coverage_authority_rejected=True,reservation_pin_preserved=True)
                    finally:client.close()
                result=await asyncio.to_thread(consumer)
                print(json.dumps(result,sort_keys=True))
            finally:stop.set();await task

if __name__=='__main__':asyncio.run(main())
