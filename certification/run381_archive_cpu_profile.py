"""Bounded archive CPU profile using preserved public production bodies."""
import cProfile,hashlib,io,json,pstats,tempfile,time
from pathlib import Path
from meme_machine.solana_evidence_service import ServiceState,decode_source_message,program_subscriptions
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.test_run380_production_pressure import Wire
wire=Wire();config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test')
addresses=tuple(sorted({s.address for s in program_subscriptions()}))
with tempfile.TemporaryDirectory() as td:
 state=ServiceState(Path(td)/'db',config)
 try:
  for i in range(12):
   slot=1000+i
   raw=wire.template.replace(b'run380:1000:',('run380:'+str(slot)+':').encode())
   for old,new in [(b'"slot":1000,',f'"slot":{slot},'.encode()),(b'"parentSlot":999,',f'"parentSlot":{slot-1},'.encode()),(b'"blockhash":"h1000"',f'"blockhash":"h{slot}"'.encode()),(b'"previousBlockhash":"h999"',f'"previousBlockhash":"h{slot-1}"'.encode())]:raw=raw.replace(old,new)
   seen=time.time()
   message=decode_source_message(raw,config.credential,addresses,config.identity,seen)
   state.source(Subscription('service','chain:solana','all','blocks',2),message,seen,len(raw))
  snapshot=state.writer.archive_snapshot(time.time()-180)
  assert len(snapshot['rows'])==1000
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
