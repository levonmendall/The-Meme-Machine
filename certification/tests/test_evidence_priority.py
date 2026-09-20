import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from certification.worker import Observer
from certification.controls import record_unfinished_broker_jobs
from certification.journal import Journal


class EvidencePriorityTests(unittest.TestCase):
    def test_shutdown_preserves_unadmitted_consumers_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broker.sqlite'
            db=sqlite3.connect(path)
            db.executescript('''CREATE TABLE jobs(job_key,kind,priority,deadline,status);
                CREATE TABLE evidence_consumers(owner,signature,kind,deadline,state);
                INSERT INTO evidence_consumers VALUES('pump:a','x','pump_window',1,'waiting');
                INSERT INTO evidence_consumers VALUES('meteora:a','y','dlmm_fresh',99,'waiting');''')
            db.commit()
            journal=Journal(Path(tmp)/'journal.sqlite')
            try:
                result=record_unfinished_broker_jobs(path,journal,10)
                self.assertEqual(result['count'],0)
                self.assertEqual(result['consumer_count'],2)
                self.assertEqual(result['consumer_reasons'],{
                    'consumer_deadline_expired_at_shutdown':1,
                    'consumer_censored_at_campaign_shutdown':1})
                self.assertEqual(db.execute("SELECT COUNT(*) FROM evidence_consumers WHERE state='waiting'").fetchone()[0],2)
            finally:db.close();journal.close()

    def test_background_yields_and_position_context_always_wins(self):
        class Transport:
            evidence_priority=90
            def send(self, request):return {'result': 1}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,
                {'MM_CERT_GOVERNOR_DB':str(Path(tmp)/'governor.sqlite')}):
            observer=Observer(Path(tmp)/'lane','pump','frozen')
            priorities=[]
            observer.governor.acquire=lambda network,lane,priority,**kw:priorities.append(priority) or 0
            observer.wrap_transport(Transport,'send',solana=True)
            try:
                transport=Transport()
                transport.send({'method':'getTransaction'})
                transport.evidence_priority=20
                transport.send({'method':'getTransaction'})
                observer.context.priority=0
                transport.evidence_priority=90
                transport.send({'method':'getTransaction'})
                self.assertEqual(priorities,[90,20,0])
                self.assertEqual(observer.requests,3)
                self.assertEqual(observer.raw_records,3)
            finally:
                observer.raw.close()
                observer.journal.db.close()

    def test_local_expiry_is_not_provider_failure_or_physical_request(self):
        import time
        class Transport:
            evidence_deadline=time.time()-1
            def send(self,request):raise AssertionError('must never reach provider')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,
                {'MM_CERT_GOVERNOR_DB':str(Path(tmp)/'governor.sqlite')}):
            observer=Observer(Path(tmp)/'lane','pump','frozen')
            observer.wrap_transport(Transport,'send',solana=True)
            try:
                rpc=Transport()
                with self.assertRaisesRegex(TimeoutError,'evidence_deadline_before_transport'):
                    rpc.send({'method':'getTransaction'})
                self.assertEqual(observer.requests,0)
                self.assertEqual(observer.provider_method_errors,{})
                self.assertEqual(observer.local_admission_errors['getTransaction:evidence_deadline_before_transport'],1)
                self.assertEqual(rpc.evidence_local_failure,'evidence_deadline_before_transport')
            finally:observer.raw.close();observer.journal.db.close()
