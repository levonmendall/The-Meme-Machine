"""Unchanged subscription polls must not preempt durable archive maintenance."""
import asyncio,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine import solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceUnavailable
from meme_machine.solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE
from meme_machine.postgrad import PUMPSWAP_PROGRAM
from tests.test_run373_dispatch_throughput import SustainedSocket
from tests.evidence_ipc_harness import ipc_transport

class FakeSocket(SustainedSocket):
 def __init__(self):super().__init__(frames=0,interval=0,padding_bytes=0)


class SubscriptionProgressTests(unittest.IsolatedAsyncioTestCase):
 async def wait_for(self,check):
  for _ in range(300):
   if check():return
   await asyncio.sleep(.01)
  self.fail('subscription reconciliation did not progress')

 async def test_unchanged_interests_do_not_enqueue_repeated_priority_zero_reads(self):
  calls=[];original=service.ServiceState.interests
  def observe(state):calls.append(time.monotonic());return original(state)
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service.ServiceState,'interests',observe):
   wire=FakeSocket();stop=asyncio.Event();path=Path(td)/'db'
   with patch('websockets.asyncio.client.connect',return_value=wire):
    runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
    try:
     await self.wait_for(lambda:bool(calls))
     await asyncio.sleep(service.STREAM_SUBSCRIPTION_SYNC_SECONDS*4.5)
     self.assertEqual(len(calls),1,'empty subscription polls interrupt priority-four archive transactions')
    finally:stop.set();await runner

 async def test_new_interest_during_subscription_send_and_release_are_not_lost(self):
  with tempfile.TemporaryDirectory() as td,ipc_transport():
   path=Path(td)/'db';stop=asyncio.Event()
   def command(**kw):
    p=RuntimeEvidence(path,owner='pump')
    try:return p.command(**kw)
    finally:p.close()
   class Wire(FakeSocket):
    async def send(self,raw):
     await super().send(raw)
     request=json.loads(raw)
     if request['method']=='accountSubscribe' and request['params'][0]==PUMPSWAP_PROGRAM:
      await asyncio.to_thread(command,op='interest',owner='pump:second',scope=PUMP_SCOPE,lower_slot=1,
        priority=0,lifecycle='reserved',addresses=['11111111111111111111111111111111'])
   wire=Wire()
   with patch('websockets.asyncio.client.connect',return_value=wire):
    runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
    try:
     await self.wait_for(lambda:bool(wire.subs))
     await asyncio.to_thread(command,op='interest',owner='pump:first',scope=PUMP_SCOPE,lower_slot=1,
       priority=0,lifecycle='reserved',addresses=[PUMPSWAP_PROGRAM])
     await self.wait_for(lambda:sum(r['method']=='accountSubscribe' for r in wire.subs.values())==2)
     await asyncio.to_thread(command,op='release',owner='pump:first',scope=PUMP_SCOPE,resolved=True)
     await self.wait_for(lambda:any(r['method']=='accountUnsubscribe' for r in wire.subs.values()))
    finally:stop.set();await runner

 async def test_disconnected_command_waiter_still_signals_subscription_change(self):
  import socket
  original=service.FinalizedFence._command
  def delayed(fence,request):
   if request.get('op')=='interest':time.sleep(.55)
   return original(fence,request)
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service.FinalizedFence,'_command',delayed):
   path=Path(td)/'db';wire=FakeSocket();stop=asyncio.Event()
   with patch('websockets.asyncio.client.connect',return_value=wire):
    runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
    try:
     await self.wait_for(lambda:bool(wire.subs))
     request=dict(op='interest',consumer='pump',owner='pump:gone',scope=PUMP_SCOPE,lower_slot=1,
       priority=0,lifecycle='reserved',addresses=[PUMPSWAP_PROGRAM],request_id='lost-waiter',expires_at=time.time()+3)
     def abandon():
      with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
       client.connect(str(path)+'.sock');client.sendall((json.dumps(request)+'\n').encode())
     await asyncio.to_thread(abandon)
     await self.wait_for(lambda:any(r['method']=='accountSubscribe' for r in wire.subs.values()))
    finally:stop.set();await runner


class SubscriptionSignalTests(unittest.TestCase):
 def test_only_committed_interest_changes_and_expiry_signal_and_restart_restores(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db';writer=EvidenceWriter(path,clock=lambda:100)
   try:
    fence=service.FinalizedFence(writer,endpoint_identity='a'*64)
    self.assertTrue(fence.subscriptions_dirty.is_set());fence.subscriptions_dirty.clear()
    fence.command(dict(op='counter',key='pump.example'))
    fence.expire_candidates(100)
    self.assertFalse(fence.subscriptions_dirty.is_set())
    request=dict(op='interest',owner='pump:signal',scope=PUMP_SCOPE,lower_slot=1,priority=3,
      lifecycle='candidate',addresses=[PUMPSWAP_PROGRAM])
    with self.assertRaises(EvidenceUnavailable):fence.command(dict(request,lower_slot=-1))
    self.assertFalse(fence.subscriptions_dirty.is_set())
    fence.command(request)
    self.assertTrue(fence.subscriptions_dirty.is_set());self.assertFalse(writer.db.in_transaction)
    fence.subscriptions_dirty.clear();fence.expire_candidates(1401)
    self.assertTrue(fence.subscriptions_dirty.is_set())
    fence.subscriptions_dirty.clear();fence.command(dict(request,lifecycle='reserved',priority=0))
   finally:writer.close()
   writer=EvidenceWriter(path,clock=lambda:1500)
   try:
    fence=service.FinalizedFence(writer,endpoint_identity='a'*64)
    self.assertTrue(fence.subscriptions_dirty.is_set())
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM interests WHERE active=1').fetchone()[0],1)
   finally:writer.close()

if __name__=='__main__':unittest.main()
