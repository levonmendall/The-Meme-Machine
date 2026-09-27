"""Production Survivor acquisition at bounded capacity; no network or entry bypass."""
import unittest
from certification.tests import test_survivor_candidate_progress as launcher


PONS_SCHEDULING = r'''
import tempfile
from pathlib import Path
from unittest.mock import MagicMock,patch
from certification.survivor_history import History
from robinhood_research import pons_survivor_runtime as native
from robinhood_research.protocols import PoolKey
from dataclasses import asdict
clock=[0];calls=[]
class RPC:
 def call(self,method,params,scope):
  calls.append((method,params))
  if method=='eth_getBlockByNumber':
   block=clock[0]*5 if params[0]=='latest' else int(params[0],16)
   return dict(number=hex(block),hash='h'+str(block),timestamp=hex(block//5))
  if method=='eth_getLogs':
   assert int(params[0]['toBlock'],16)-int(params[0]['fromBlock'],16)<10
   return []
  raise AssertionError(method)
 def batch(self,requests,scope):return [self.call(m,p,scope) for m,p in requests]
def batched(endpoint,requests,scope,**kw):return RPC().batch(requests,scope),[]
with tempfile.TemporaryDirectory() as td:
 h=History(Path(td)/'history',policy='offline-scheduling')
 for i in range(64):
  token='0x'+f'{i+1:040x}'
  row=h.graduate(token,dict(at=0,block_hash='h0',transition=dict(market='0x'+f'{i+1:064x}'),
   key=asdict(PoolKey(native.ZERO,token,0,0,'0x'+'aa'*20))))
  row['block']=0;h.save(row)
 r=native.Runtime.__new__(native.Runtime);r.history=h;r.rpc=RPC();r.endpoint='offline'
 r._provider=lambda:None;r.now=lambda:clock[0];r.last_error=None
 r.book=MagicMock();r.book.positions.return_value=[];r.sleeve=MagicMock();r.sleeve.identity={'policies':{}}
 r.plane=MagicMock()
 with patch('robinhood_research.pons_selective_v4._batched',side_effect=batched):
  for tick in range(1,25):
   clock[0]=tick*5
   result=r.step(admit=True)
   assert not result['last_boundary'],result['last_boundary']
 lag=max(clock[0]*5-row['block'] for row in h.rows())
 assert lag<=40,('candidate lag grows with bounded hot-set size',lag)
 assert all(row['complete'] for row in h.rows())
 h.close()
 # Independent discovery has the same clock and must keep up without widening
 # the provider's ten-block query or adding another authority.
 h=History(Path(td)/'discovery',policy='offline-scheduling');r.history=h
 h.set_meta('discovery_block',0)
 for tick in range(1,25):
  clock[0]=tick*5;r.discover()
 lag=clock[0]*5-h.get_meta('discovery_block')
 assert lag<=40,('discovery lag grows',lag)
 assert not h.rows()
 h.close()
print('64 candidate cursors and discovery keep pace; all log ranges <=10 blocks')
'''


PONS_LINEAGE = r'''
import copy,json,os,tempfile
from pathlib import Path
from unittest.mock import patch
from robinhood_research import BoundaryError
from robinhood_research.pons_survivor_runtime import Runtime
from robinhood_tests.test_captured_pons_lineage import FIXTURE
capture=json.loads(FIXTURE.read_text())['v2'];grad=capture['graduation']
block=int(grad['blockNumber'],16);token=capture['expected']['token']
# The log/ABI/lineage bytes are preserved captured evidence. Header/receipt
# envelopes below are deterministic offline transport fixtures, not market proof.
header=dict(number=grad['blockNumber'],hash=grad['blockHash'],timestamp='0x64')
receipt=dict(blockHash=grad['blockHash'],transactionHash=grad['transactionHash'],
 transactionIndex=grad['transactionIndex'],status='0x1',gasUsed='0x123',
 logs=[capture[k] for k in ('initialization','registration','graduation')])
class RPC:
 def __init__(self,corrupt=False):self.corrupt=corrupt
 def call(self,method,params,scope):
  if method in ('eth_getBlockByNumber','eth_getBlockByHash'):return dict(header)
  if method=='eth_getLogs':return [copy.deepcopy(grad)]
  if method=='eth_call':return capture['factory_record_raw']
  raise AssertionError(method)
 def batch(self,calls,scope):return [self.call(m,p,scope) for m,p in calls]
 def receipt(self,tx,bh,scope):
  result=copy.deepcopy(receipt)
  if self.corrupt:result['logs']=result['logs'][1:]
  return result
for corrupt in (False,True):
 with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
  'MM_DIRECTIONAL_SLEEVE_DB':td+'/sleeve','MM_DIRECTIONAL_COHORT_ID':'acquisition'},clear=True):
  runtime=Runtime(td+'/survivor',10**18,'acquisition','https://robinhood-mainnet.g.alchemy.com/v2/offline')
  runtime.rpc=RPC(corrupt);runtime.history.set_meta('discovery_block',block-1)
  try:
   if corrupt:
    try:runtime.discover()
    except BoundaryError as exc:assert str(exc)=='natural_graduation_lineage_incomplete',str(exc)
    else:raise AssertionError('missing initialization acquired authority')
    assert runtime.history.get_meta('discovery_block')==block-1 and not runtime.history.rows()
   else:
    runtime.discover();row=runtime.history.get(token)
    assert row['graduation']['transition']['proof']==capture['expected']
    assert row['graduation']['source']=='robinhood_authenticated_candidate_evidence_plane'
    assert runtime.history.get_meta('discovery_block')==block
    runtime.discover();assert len(runtime.history.rows())==1
    points,events=runtime.history.facts(token,100);assert len(points)==1 and not events
   assert runtime.book.reconcile()['open_positions']==0
  finally:runtime.close()
print('captured V2 lineage traversed production discovery, receipt/ABI proof, history and duplicate gate')
'''


PONS_AUTHENTICATION = r'''
import copy,tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from certification.survivor_history import History
from robinhood_research import BoundaryError
from robinhood_research import pons_selective_v4 as v4
from robinhood_research import pons_survivor_runtime as native
from robinhood_research.identity import load
from robinhood_research.protocols import PoolKey
manager=load('uniswap_v4_manager')['address'];hook=load('pons_v2_hook')['address']
tokens=['0x'+f'{i:040x}' for i in (1,2)];pools=['0x'+f'{i:064x}' for i in (1,2)]
def event(i):
 values=(100+i,-10-i,1<<96,1000,0,0)
 return dict(address=manager,blockNumber='0x1',blockHash='h1',transactionHash='tx'+str(i),
  transactionIndex=hex(i),logIndex=hex(i),removed=False,
  topics=[v4._event_topic('uniswap_v4_manager','Swap'),pools[i],'0x'+f'{3:064x}'],
  data='0x'+''.join(f'{n%(1<<256):064x}' for n in values))
original=[event(0),event(1)];raw=copy.deepcopy(original);fault=[None];seen=[]
def batched(endpoint,calls,scope,**kw):
 assert endpoint=='canonical-offline' and scope=='pons_selective_v4'
 out=[]
 for method,params in calls:
  seen.append((method,params))
  if fault[0]=='timeout':raise BoundaryError('provider_timeout')
  if method=='eth_getLogs':out.append(copy.deepcopy(raw))
  elif method=='eth_getBlockByHash':out.append(dict(hash='h1',number='0x1',timestamp='0x1'))
  elif method=='eth_getTransactionByHash':out.append(dict(hash=params[0],blockHash='h1',**{'from':'buyer'+params[0]}))
  elif method=='eth_getTransactionReceipt':
   e=next(e for e in original if e['transactionHash']==params[0])
   out.append(dict(transactionHash=params[0],blockHash='bad' if fault[0]=='receipt' else 'h1',
    transactionIndex=e['transactionIndex'],status='0x1',logs=[copy.deepcopy(e)]))
  else:raise AssertionError(method)
 return out,[]
markets=[dict(pool_id=p,key=PoolKey(native.ZERO,t,0,0,hook),token=t) for p,t in zip(pools,tokens)]
class RPC:
 def batch(self,calls,scope):
  assert len(calls)<=50
  return [dict(number=p[0],hash='fork' if fault[0]=='reorg' else 'h'+str(int(p[0],16)),timestamp=p[0]) for m,p in calls]
with patch.object(v4,'_batched',side_effect=batched):
 result=v4.collect_v4_activities('canonical-offline',markets=markets,start_block=1,end_block=1)
 assert result[tokens[0]]['buy_quote']==100 and result[tokens[1]]['buy_quote']==101
 assert all(len(t['swaps'])==1 for t in result.values())
 assert sum(m=='eth_getLogs' for m,p in seen)==1
 # Routing/receipt corruption cannot enter any candidate's history.
 for problem in ('foreign','receipt'):
  fault[0]=problem;raw=copy.deepcopy(original)
  if problem=='foreign':raw[0]['topics'][1]='0x'+'ff'*32
  try:v4.collect_v4_activities('canonical-offline',markets=markets,start_block=1,end_block=1)
  except BoundaryError:pass
  else:raise AssertionError(problem)
 raw=copy.deepcopy(original)
 with tempfile.TemporaryDirectory() as td:
  h=History(Path(td)/'h',policy='offline-authentication')
  for m in markets:
   row=h.graduate(m['token'],dict(at=0,block_hash='h0',key=asdict(m['key']),transition=dict(market=m['pool_id'])))
   row['block']=0;h.save(row)
  r=native.Runtime.__new__(native.Runtime);r.history=h;r.rpc=RPC();r.endpoint='canonical-offline'
  for problem in ('timeout','receipt','reorg'):
   fault[0]=problem
   try:r._increment_candidates(h.rows(),1)
   except BoundaryError:pass
   else:raise AssertionError(problem)
   assert all(row['block']==0 and row['through']==0 for row in h.rows())
   assert all(h.facts(t,1)==([],[]) for t in tokens)
  fault[0]=None;r._increment_candidates(h.rows(),1)
  assert all(row['block']==1 and row['through']==1 for row in h.rows())
  assert [h.facts(t,1)[1][0]['quote'] for t in tokens]==[100,101]
  h.close();h=History(Path(td)/'h',policy='offline-authentication');r.history=h
  before=len(seen);r._increment_candidates(h.rows(),1);assert len(seen)==before
  assert all(len(h.facts(t,1)[1])==1 for t in tokens)
  h.close()
print('native shared acquisition authenticates separate pools, fails closed, recovers and reopens without duplicate evidence')
'''


PUMP_LINEAGE = r'''
import tempfile
from pathlib import Path
from unittest.mock import patch
from meme_machine import pump
from meme_machine.pumpswap_survivor_runtime import Runtime,POLICY_HASH
from meme_machine.solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE,SWAP_SCOPE
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceUnavailable
from meme_machine.solana_evidence_service import FinalizedFence,program_decoders
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.pumpswap_survivor_evidence import migration_events
from tests.test_pumpswap_survivor_evidence import EvidenceTests
from certification.survivor_history import History
for excluded in (False,True):
 with tempfile.TemporaryDirectory() as td,patch('socket.socket.connect',side_effect=AssertionError('network forbidden')):
  now=[101];writer=EvidenceWriter(Path(td)/'evidence',clock=lambda:now[0])
  fence=FinalizedFence(writer,endpoint_identity='a'*64,decoders=program_decoders())
  plane=RuntimeEvidence(writer.path,owner='pump:survivor',clock=lambda:now[0],command=fence.command)
  h=History(Path(td)/'history',policy=POLICY_HASH);h.set_meta('discovery_slot',99)
  r=Runtime.__new__(Runtime);r.history=h;r.plane=plane
  tx=EvidenceTests().migration(pump.b58(bytes([7])*32) if excluded else None)
  mint=migration_events(EvidenceTests().migration())[0]['mint']
  logs=Subscription('service',PUMP_SCOPE,pump.PROGRAM,'logs',4)
  census=Subscription('service',PUMP_SCOPE,pump.PROGRAM,'census',4)
  def block(slot,transaction=None):
   transactions=[]
   if transaction:
    transactions=[dict(transaction=dict(signatures=['migration'],message=dict(accountKeys=[pump.PROGRAM])),meta=transaction['meta'])]
   fence.block(census,dict(params=dict(result=dict(value=dict(slot=slot,err=None,
    block=dict(parentSlot=slot-1,blockTime=slot,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
      transactions=transactions))))),101)
  try:
   block(99)
   fence.logs(logs,dict(method='logsNotification',params=dict(result=dict(context=dict(slot=100),
    value=dict(signature='migration',logs=tx['meta']['logMessages'],err=None)))),101)
   block(100,tx);fence.health('phase','ACTIVE');fence.health('heartbeat',101)
   r.discover();assert not h.rows(),'unsealed migration admitted'
   block(101);r.discover()
   assert h.get_meta('discovery_slot')==100
   assert len(h.rows())==(0 if excluded else 1)
   if not excluded:
    row=h.get(mint)
    assert row['graduation']['source']=='solana_finalized_evidence_plane'
    assert row['graduation']['quote_asset']=='SOL'
    assert writer.db.execute('SELECT COUNT(*) FROM interests WHERE scope=? AND active=1',(SWAP_SCOPE,)).fetchone()[0]==1
    h.close();h=History(Path(td)/'history',policy=POLICY_HASH);r.history=h
    r.discover();assert h.get(mint)==row
   writer.gap(PUMP_SCOPE,100,100)
   h.set_meta('discovery_slot',99)
   try:r.discover()
   except EvidenceUnavailable:pass
   else:raise AssertionError('unresolved finalized gap admitted')
   assert h.get_meta('discovery_slot')==99
  finally:h.close();plane.close();writer.close()
print('Pump raw migration decoding, linked finalized census, correct universe, durable discovery and gap gate passed')
'''


class SurvivorAcquisitionTests(unittest.TestCase):
    run_native = launcher.SurvivorCandidateProgressTests.run_native

    def test_pons_full_hot_set_and_discovery_keep_pace(self):
        self.run_native(PONS_SCHEDULING,lanes=('pons',))

    def test_pons_captured_graduation_through_authoritative_discovery(self):
        self.run_native(PONS_LINEAGE,lanes=('pons',))

    def test_pons_shared_transport_keeps_pool_authority_and_recovers(self):
        self.run_native(PONS_AUTHENTICATION,lanes=('pons',))

    def test_pump_raw_migration_finality_and_target_market(self):
        self.run_native(PUMP_LINEAGE,lanes=('pump',))
