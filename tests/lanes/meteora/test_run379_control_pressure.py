"""Run 379: bounded control retries and maintenance progress under ordered writes."""
import threading,time,unittest
from types import SimpleNamespace
from meme_machine.lanes.meteora.solana_evidence_control import PriorityOwner,PendingCommands
from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceUnavailable


class ControlPressureTests(unittest.TestCase):
 def test_continuous_commits_do_not_starve_counter_or_maintenance(self):
  entered=threading.Event();release=threading.Event();now=[0.0];order=[]
  owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None))
  owner.clock=lambda:now[0]
  try:
   owner.ready.result(1)
   first=owner.submit(lambda s:(entered.set(),release.wait(2)),priority=0)
   self.assertTrue(entered.wait(1))
   counter=owner.submit(lambda s:order.append(('counter',now[0])),priority=3)
   maintenance=owner.submit(lambda s:order.append(('maintenance',now[0])),priority=4)
   def commit(s):order.append(('commit',now[0]));now[0]+=.25
   commits=[owner.submit(commit,priority=2) for _ in range(40)]
   foreground=owner.submit(lambda s:order.append(('foreground',now[0])),priority=1)
   lifecycle=owner.submit(lambda s:order.append(('lifecycle',now[0])),priority=0)
   release.set()
   for f in (first,*commits,counter,maintenance,foreground,lifecycle):f.result(2)
   self.assertEqual([x[0] for x in order[:2]],['lifecycle','foreground'])
   self.assertLessEqual(dict(order)['counter'],1.0)
   self.assertLessEqual(dict(order)['maintenance'],1.0)
   self.assertEqual(sum(x[0]=='commit' for x in order),40)
   self.assertGreater(owner.telemetry()['nonurgent_fifo_selections'],0)
   self.assertEqual([x[0] for x in order[2:4]],['counter','maintenance'])
   self.assertLessEqual(owner.telemetry()['queue_peak'],64)
   self.assertEqual(owner.enqueued,{})
  finally:release.set();owner.close()

 def test_retries_share_one_bounded_admission_and_reject_conflicts(self):
  entered=threading.Event();release=threading.Event();calls=[]
  state=SimpleNamespace(close=lambda:None,
    fence=SimpleNamespace(command=lambda request:(calls.append(request),{'ok':True})[1]))
  owner=PriorityOwner(lambda:state,capacity=4,reserved=1);pending=PendingCommands(owner)
  request=dict(consumer='pump',request_id='same',op='counter',key='pump.reads',count=1,expires_at=time.time()+3)
  try:
   owner.ready.result(1)
   blocker=owner.submit(lambda s:(entered.set(),release.wait(2)),priority=0)
   self.assertTrue(entered.wait(1))
   futures=[pending.submit(dict(request)) for _ in range(100)]
   self.assertTrue(all(f is futures[0] for f in futures))
   self.assertEqual(len(owner.queue),1);self.assertEqual(len(pending.pending),1)
   with self.assertRaisesRegex(EvidenceUnavailable,'identity_conflict'):
    pending.submit(dict(request,count=2))
   others=[pending.submit(dict(request,request_id=str(i))) for i in range(2)]
   with self.assertRaisesRegex(EvidenceUnavailable,'evidence_control_overloaded'):
    pending.submit(dict(request,request_id='overflow'))
   urgent=owner.submit(lambda s:'exit',priority=0)
   self.assertEqual(len(owner.queue),4)
   release.set();blocker.result(1);urgent.result(1)
   for f in (*futures,*others):self.assertEqual(f.result(1),{'ok':True})
   owner.submit(lambda s:None,priority=0).result(1)
   self.assertEqual(len(calls),3);self.assertEqual(len(pending.pending),3)
  finally:release.set();owner.close()

 def test_completed_reply_retry_bypasses_busy_owner_until_receipt_expiry(self):
  entered=threading.Event();release=threading.Event();calls=[];now=[100.0]
  state=SimpleNamespace(close=lambda:None,
    fence=SimpleNamespace(command=lambda request:(calls.append(request),{'ok':True})[1]))
  owner=PriorityOwner(lambda:state);pending=PendingCommands(owner)
  pending.capacity=2;pending.clock=lambda:now[0]
  request=dict(consumer='pump',request_id='committed',op='counter',key='pump.reads',count=1,expires_at=103)
  try:
   owner.ready.result(1);first=pending.submit(request);self.assertEqual(first.result(1),{'ok':True})
   blocker=owner.submit(lambda s:(entered.set(),release.wait(2)),priority=2)
   self.assertTrue(entered.wait(1))
   # Every original socket waiter has already returned pending. A later retry
   # still reads the completed receipt without a second owner admission.
   reply=pending.submit(dict(request));self.assertIs(reply,first)
   self.assertEqual(reply.result(.05),{'ok':True});self.assertEqual(len(owner.queue),0)
   with self.assertRaisesRegex(EvidenceUnavailable,'identity_conflict'):
    pending.submit(dict(request,count=2))
   second=pending.submit(dict(request,request_id='second'))
   with self.assertRaisesRegex(EvidenceUnavailable,'evidence_receipt_capacity'):
    pending.submit(dict(request,request_id='overflow'))
   release.set();blocker.result(1);second.result(1);self.assertEqual(len(calls),2)
   now[0]=110
   with self.assertRaisesRegex(EvidenceUnavailable,'evidence_command_envelope'):pending.submit(request)
   new=pending.submit(dict(request,request_id='fresh',expires_at=113))
   self.assertEqual(new.result(1),{'ok':True});self.assertEqual(len(pending.pending),1)
  finally:release.set();owner.close()


if __name__=='__main__':unittest.main()
