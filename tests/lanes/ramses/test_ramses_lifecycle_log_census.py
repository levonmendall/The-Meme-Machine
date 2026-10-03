import tempfile
from pathlib import Path
import unittest
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.ramses_lifecycle_log_census import collect

class LogCensusTests(unittest.TestCase):
    def test_complete_large_interval_and_repeat_reuse_without_authoritative_calls(self):
        calls=[];configs=[]
        class Reader:
            def __init__(self,*a,**kw):configs.append(kw)
            def verify_chain(self):pass
            def batch(self,batch,*,scope):
                calls.extend(batch)
                return [[dict(address='pool',blockNumber=c[1][0]['fromBlock'],removed=False)] for c in batch]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'cache.sqlite'
            first=collect(100,18000,'pool',cache_path=p,reader_factory=Reader)
            again=collect(100,18000,'pool',cache_path=p,reader_factory=Reader)
            self.assertEqual(first,again);self.assertEqual(len(calls),18)
            bounds=[(int(c[1][0]['fromBlock'],16),int(c[1][0]['toBlock'],16)) for c in calls]
            self.assertEqual(bounds[0][0],100);self.assertEqual(bounds[-1][1],18000)
            self.assertTrue(all(b[0]==a[1]+1 for a,b in zip(bounds,bounds[1:])))
            self.assertEqual(configs[0]['provider_role'],'public_observation')
            self.assertEqual((configs[0]['batch_size'],configs[0]['batch_pause'],configs[0]['rate_retries']),(1,1,0))
    def test_failed_page_is_not_an_empty_success_and_successful_prefix_is_reused(self):
        calls=[];fail=[True]
        class Reader:
            def __init__(self,*a,**kw):pass
            def verify_chain(self):pass
            def batch(self,batch,*,scope):
                first=int(batch[0][1][0]['fromBlock'],16);calls.append(first)
                if first==1001 and fail[0]:raise BoundaryError('provider_http_503')
                return [[]]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'cache.sqlite'
            with self.assertRaisesRegex(BoundaryError,'503'):collect(1,2000,'pool',cache_path=p,reader_factory=Reader)
            fail[0]=False;self.assertEqual(collect(1,2000,'pool',cache_path=p,reader_factory=Reader),[])
            self.assertEqual(calls,[1,1001,1001])

if __name__=='__main__':unittest.main()
