"""Bounded archive CPU profile using preserved public production bodies."""
import asyncio,cProfile,hashlib,io,json,pstats,tempfile,time
from pathlib import Path
from meme_machine.solana_evidence_service import ServiceState,decode_source_message,program_subscriptions
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
from certification.run381_pressure import Wire
wire=Wire();wire.start=time.time()-600;config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
addresses=tuple(sorted({s.address for s in program_subscriptions()}))
with tempfile.TemporaryDirectory() as td:
 state=ServiceState(Path(td)/'db',config)
 try:
  for i in range(12):
   raw=asyncio.run(wire.recv())
   seen=time.time()
   message,_,_=decode_source_message(raw,config.credential,addresses,config.identity,seen)
   state.source(Subscription('service','chain:solana','all','blocks',2),message,seen,len(raw))
  snapshot=state.writer.archive_snapshot(time.time()-180)
  assert snapshot and len(snapshot['rows'])>=256
  observations=[];profile=cProfile.Profile()
  for _ in range(3):
   started=time.perf_counter()
   profile.enable()
   commit,receipt=EvidenceWriter.prepare_and_write_archive(state.writer.path,snapshot,max_bytes=16*1024*1024)
   profile.disable()
   observations.append(dict(elapsed=time.perf_counter()-started,records=len(commit),bytes=receipt['bytes'],worker=receipt['worker_metrics']))
  output=io.StringIO();pstats.Stats(profile,stream=output).sort_stats('cumulative').print_stats(45)
  print('ARCHIVE_PROFILE',json.dumps(dict(rows=len(snapshot['rows']),encoded_bytes=snapshot['encoded_bytes'],observations=observations)))
  print(output.getvalue())
 finally:state.close()
