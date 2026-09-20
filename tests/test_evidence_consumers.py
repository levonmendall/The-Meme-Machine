import tempfile
import unittest

from meme_machine.provider import Unavailable
from meme_machine.solana_evidence_broker import EvidenceBroker, DynamicAddressLogStream
from meme_machine.solana_evidence_consumers import StreamEvidenceService
from tests.test_solana_evidence_broker import _Clock, _Rpc


class PacedRpc(_Rpc):
    def __init__(self, clock):
        super().__init__()
        self.clock, self.calls, self.limit = clock, 0, 240
    def call_many(self, method, params, *args, **kwargs):
        self.calls += len(params)
        self.clock.sleep(.5)  # Same conservative two-transport/second ceiling.
        return super().call_many(method, params, *args, **kwargs)
    def provider_telemetry(self): return dict(requests=len(self.batches), logical=self.calls)


class EvidenceConsumerTests(unittest.TestCase):
    def broker(self):
        clock=_Clock()
        b=EvidenceBroker(':memory:',clock=clock,sleeper=clock.sleep)
        self.addCleanup(b.close)
        return b,clock

    def test_incremental_completes_same_window_where_burst_censors_at_same_rate(self):
        burst,clock=self.broker()
        rpc=PacedRpc(clock)
        signatures=[f's-{i}' for i in range(80)]
        _,meta=burst.hydrate_transactions(rpc,signatures,kind='pump_window',deadline=clock()+4)
        self.assertEqual(meta['hydrated'],64)
        incremental,tick=self.broker()
        ahead=PacedRpc(tick)
        service=StreamEvidenceService(incremental,lambda:ahead)
        for i in range(10):
            incremental.consumers.register('pump:pool',signatures[i*8:(i+1)*8],
                                           'stream_prefetch',tick()+32)
            service.step()
            tick.sleep(.5)
        before=len(ahead.batches)
        _,complete=incremental.hydrate_transactions(ahead,signatures,kind='pump_window',
                                                     deadline=tick()+4)
        self.assertEqual(complete['hydrated'],80)
        self.assertEqual(len(ahead.batches),before)
        self.assertEqual(before,10)

    def test_burst_keeps_all_censoring_but_admits_only_serviceable_jobs(self):
        b,c=self.broker()
        _,meta=b.hydrate_transactions(PacedRpc(c),[str(i) for i in range(2000)],
                                     kind='pump_window',deadline=c()+4)
        self.assertEqual(meta['pending'],1936)
        self.assertLessEqual(b.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],72)
        c.sleep(.1)
        stats=b.consumers.telemetry()
        censored=sum(x['count'] for x in stats['consumers'] if x['state']=='consumer_deadline_expired')
        self.assertEqual(censored,1936)

    def test_retirement_preserves_other_owner_and_original_deadline(self):
        b,c=self.broker()
        b.consumers.register('pump:pool',['shared'],'stream_prefetch',c()+1)
        b.consumers.register('meteora:pool',['shared'],'dlmm_fresh',c()+20)
        b.consumers.register('pump:pool',['shared'],'stream_prefetch',c()+99)
        self.assertEqual(b.db.execute('SELECT deadline FROM evidence_consumers WHERE owner=?',
                                     ('pump:pool',)).fetchone()[0],1001)
        b.consumers.settle('pump:pool','consumer_retired')
        _,meta=b.hydrate_transactions(_Rpc(),['shared'],kind='dlmm_fresh',deadline=c()+10,
                                     owner='meteora:pool')
        self.assertEqual(meta['pending'],0)
        rows=dict(b.db.execute('SELECT owner,state FROM evidence_consumers'))
        self.assertEqual(rows,{'pump:pool':'consumer_retired','meteora:pool':'evidence_complete'})

    def test_late_cache_never_relabels_expired_consumer_complete(self):
        b,c=self.broker()
        b.consumers.register('one',['s'],'pump_window',c()+.1)
        c.sleep(.2)
        b.put_transaction('s',dict(slot=1,blockTime=1))
        b.consumers.settle()
        self.assertEqual(b.db.execute('SELECT state FROM evidence_consumers').fetchone()[0],
                         'consumer_deadline_expired')

    def test_local_budget_failure_is_not_provider_rate_pressure(self):
        class Failed(_Rpc):
            def call_many(self,*a,**k):raise Unavailable('provider_budget_exhausted')
        b,c=self.broker()
        b.hydrate_transactions(Failed(),['s'],kind='pump_window',deadline=c()+4)
        self.assertEqual(b.telemetry()['pressure']['rate_events'],0)
        self.assertEqual(b.consumers.telemetry()['acquisition_failures'],
                         {'local_request_budget_exhausted':1})

    def test_real_rate_pressure_still_backs_off(self):
        class Failed(_Rpc):
            failure_methods={}
            def call_many(self,*a,**k):
                self.failure_methods={'getTransaction:http_429':1}
                raise Unavailable('provider_request_failed')
        b,c=self.broker()
        b.hydrate_transactions(Failed(),['s'],kind='pump_window',deadline=c()+4)
        self.assertEqual(b.telemetry()['pressure']['rate_events'],1)

    def test_shared_interest_reuses_single_physical_fetch(self):
        with tempfile.TemporaryDirectory() as path:
            c=_Clock()
            a=EvidenceBroker(path+'/shared.sqlite',clock=c,sleeper=c.sleep)
            b=EvidenceBroker(path+'/shared.sqlite',clock=c,sleeper=c.sleep)
            try:
                a.consumers.register('pump',['s'],'pump_window',c()+4)
                b.consumers.register('meteora',['s'],'dlmm_fresh',c()+4)
                rpc=_Rpc()
                a.hydrate_transactions(rpc,['s'],kind='pump_window',deadline=c()+4,owner='pump')
                b.hydrate_transactions(rpc,['s'],kind='dlmm_fresh',deadline=c()+4,owner='meteora')
                self.assertEqual(len(rpc.batches),1)
                self.assertEqual(a.db.execute("SELECT COUNT(*) FROM evidence_terminals WHERE reason='evidence_complete'").fetchone()[0],2)
            finally:a.close();b.close()

    def test_cached_reuse_does_not_multiply_acquisition_consumers(self):
        b,c=self.broker();b.put_transaction('cached',dict(slot=1,blockTime=1))
        _,meta=b.hydrate_transactions(_Rpc(),['cached'],kind='pump_window',
                                      deadline=c()+4,owner='decision:one')
        self.assertEqual(meta['hydrated'],1)
        self.assertEqual(b.db.execute('SELECT COUNT(*) FROM evidence_consumers').fetchone()[0],0)

    def test_prefetch_filter_reduces_work_without_hiding_stream_signature(self):
        b,c=self.broker()
        stream=DynamicAddressLogStream('unused',b,'pool',prefetch=True,clock=c,
            prefetch_filter=lambda address,value,slot:value.get('economic') is True)
        owner=stream.add_address('a')
        b.record_event(owner,signature='noise',address='a',slot=1,observed_at=int(c()))
        self.assertFalse(stream.should_prefetch('a',{'economic':False},1))
        self.assertEqual([x['signature'] for x in b.recent_events(owner,since=c()-1)],['noise'])
        self.assertEqual(b.db.execute('SELECT COUNT(*) FROM evidence_consumers').fetchone()[0],0)
        self.assertTrue(stream.should_prefetch('a',{'economic':True},2))
        self.assertEqual(stream.status()['prefetch_notifications'],2)
        self.assertEqual(stream.status()['prefetch_admitted'],1)

    def test_stream_retirement_is_durable_and_does_not_fetch_more(self):
        b,c=self.broker()
        stream=DynamicAddressLogStream('unused',b,'pool',prefetch=True,clock=c)
        owner=stream.add_address('a')
        b.consumers.register(owner,['s'],'stream_prefetch',c()+32)
        stream.remove_address('a')
        self.assertEqual(b.consumers.batch(),[])
        self.assertEqual(b.db.execute('SELECT reason FROM evidence_terminals').fetchone()[0],
                         'consumer_retired')


if __name__=='__main__':unittest.main()
