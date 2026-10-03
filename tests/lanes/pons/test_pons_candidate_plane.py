import dataclasses
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from certification.robinhood.pons import Broker, durable_cache, normalized_cached
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons.pons import CurveState


def event(n=1):
    return dict(address='0x'+'12'*20,transactionHash='0x'+f'{n:064x}',logIndex='0x0',
        transactionIndex='0x0',blockNumber=hex(n),blockHash='0x'+f'{n:064x}',topics=[],data='0x')


class CandidatePlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'plane';self.now=100
        self.b=Broker(self.path,POLICY_HASH,clock=lambda:self.now);self.addCleanup(lambda:self.b.close())
    def test_ten_events_one_native_curve_one_job(self):
        for n in range(1,11):self.b.enqueue(event(n))
        self.assertEqual(len(self.b.rows),1)
        job=self.b.pop();self.assertEqual(job['event']['blockNumber'],'0xa')
        self.assertIsNone(self.b.pop())
        self.assertEqual(self.b.telemetry()['observation_events'],10)
    def test_sell_supersedes_active_buy_without_new_entry(self):
        self.b.enqueue(event());work=self.b.pop();self.b.enqueue(event(2),needs_work=False)
        self.assertFalse(self.b.plane.current(work['work']))
        self.assertFalse(self.b.plane.finish(work['work'],result={}))
        self.assertIsNone(self.b.pop())
    def test_update_during_provider_request_fences_result(self):
        self.b.enqueue(event());work=self.b.pop();entered=threading.Event();resume=threading.Event();out=[]
        def provider():
            entered.set();resume.wait();out.append(self.b.plane.finish(work['work'],result={'qualified':True}))
        thread=threading.Thread(target=provider);thread.start();entered.wait()
        self.b.enqueue(event(2));resume.set();thread.join()
        self.assertEqual(out,[False]);self.assertEqual(self.b.pop()['work']['generation'],2)
    def test_committed_typed_result_replays_without_hydration(self):
        self.b.enqueue(event());work=self.b.pop()
        state=CurveState(100,1000,50,10,100,200,False,1,0,1,2)
        value=dict(candidate=dict(state=state,receipt={'blockHash':'retained'}),vector={'qualified':False})
        self.assertTrue(self.b.finish(work,value,.1))
        self.b.close();self.b=Broker(self.path,POLICY_HASH,clock=lambda:self.now)
        scheduled,restored=next(self.b.committed())
        self.assertEqual(restored['candidate']['state'],state)
        self.assertEqual(restored['candidate']['receipt'],{'blockHash':'retained'})
        self.assertIsNone(self.b.pop());self.b.acknowledge(scheduled)
        self.assertEqual(list(self.b.committed()),[])
    def test_duplicate_after_restart_keeps_deadline(self):
        self.b.enqueue(event());self.b.close();self.now=102
        self.b=Broker(self.path,POLICY_HASH,clock=lambda:self.now)
        self.assertFalse(self.b.enqueue(event()))
        self.assertEqual(self.b.pop()['deadline'],105)
    def test_receipts_and_headers_reused_after_restart(self):
        cache=durable_cache(self.b.plane,'authority:policy')
        header=dict(hash='0x01',number='0x1',timestamp='0x2')
        cache.remember_header(header);cache.remember_receipt('tx','0x01',{'status':'0x1','transactionHash':'tx','blockHash':'0x01'})
        self.b.close();self.b=Broker(self.path,POLICY_HASH,clock=lambda:self.now)
        cache=durable_cache(self.b.plane,'authority:policy')
        self.assertEqual(cache.header_by_number(1),header)
        self.assertEqual(cache.receipt('tx','0x01'),{'status':'0x1','transactionHash':'tx','blockHash':'0x01'})
        self.assertIsNone(cache.receipt('tx','other'))
        self.assertIsNone(durable_cache(self.b.plane,'other-authority').header_by_number(1))
    def test_immutable_code_origin_and_conflict(self):
        cache=durable_cache(self.b.plane,'authority:policy')
        cache.remember_compiled('curve','token','code',10,{'hash':'h'},{'runtime_sha256':'r'})
        self.assertIsNone(cache.immutable_curve('curve',9))
        self.assertEqual(cache.immutable_curve('curve',11)['code'],'code')
        with self.assertRaisesRegex(ValueError,'conflict'):
            cache.remember_compiled('curve','token','different',11,{'hash':'h2'},{'runtime_sha256':'r'})
    def test_incremental_normalization_is_exact_and_restarts(self):
        cache=durable_cache(self.b.plane,'authority:policy');ctx=type('Context',(),{'cache':cache})()
        row=dict(event_at=100,group='buyer',buy=True,quote=10)
        calls=[]
        def build():calls.append(1);return row
        self.assertEqual(normalized_cached(ctx,event(),build),row)
        self.assertEqual(normalized_cached(ctx,event(),build),row)
        self.assertEqual(len(calls),1)
        self.b.close();self.b=Broker(self.path,POLICY_HASH,clock=lambda:self.now)
        ctx.cache=durable_cache(self.b.plane,'authority:policy')
        self.assertEqual(normalized_cached(ctx,event(),build),row)
        self.assertEqual(len(calls),1)
        conflicting=event();conflicting['data']='0xdead'
        with self.assertRaisesRegex(ValueError,'conflict'):normalized_cached(ctx,conflicting,build)
