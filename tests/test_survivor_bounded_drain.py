import threading,time,unittest
from concurrent.futures import TimeoutError
from meme_machine.runtime.survivor_history import Worker

class SurvivorBoundedDrainTests(unittest.TestCase):
    def test_blocked_step_has_bounded_close_and_one_owned_eventual_close(self):
        entered=threading.Event();release=threading.Event();owners=[];closed=[]
        class Service:
            def __init__(self):owners.append(threading.get_ident())
            def step(self,*,admit):entered.set();release.wait(5);return {'last_boundary':None}
            def close(self):owners.append(threading.get_ident());closed.append(True)
        worker=Worker(Service)
        try:
            with self.assertRaises(TimeoutError):worker.prime(timeout=.01)
            self.assertTrue(entered.wait(1));started=time.monotonic()
            with self.assertRaises(TimeoutError):worker.close(timeout=.02)
            self.assertLess(time.monotonic()-started,.5)
            with self.assertRaises(TimeoutError):worker.close(timeout=.01)
            with self.assertRaisesRegex(RuntimeError,'closed'):worker.tick(6)
            self.assertFalse(closed)
        finally:release.set();worker.close(timeout=2)
        self.assertEqual(closed,[True]);self.assertEqual(owners[0],owners[1])
        self.assertEqual(worker.close()['machinery']['completed_steps'],1)
        self.assertEqual(closed,[True])

    def test_failed_step_still_closes_once_on_owner(self):
        closed=[]
        class Service:
            def step(self,*,admit):raise ValueError('offline_failure')
            def close(self):closed.append(threading.get_ident())
        worker=Worker(Service)
        with self.assertRaisesRegex(ValueError,'offline_failure'):worker.prime()
        with self.assertRaisesRegex(ValueError,'offline_failure'):worker.close()
        with self.assertRaisesRegex(ValueError,'offline_failure'):worker.close()
        self.assertEqual(len(closed),1)

    def test_blocked_worker_sigterm_preserves_committed_epoch_and_reservation(self):
        import os,signal,sqlite3,subprocess,sys,tempfile
        from pathlib import Path
        from meme_machine.operational.supervisor import Supervisor
        source='''
import signal,sqlite3,sys,time,threading
from concurrent.futures import TimeoutError
from meme_machine.runtime.survivor_history import Worker
class Service:
 def __init__(self):
  self.db=sqlite3.connect(sys.argv[1])
  self.db.execute('CREATE TABLE facts(epoch TEXT,reservation TEXT,amount INTEGER)')
  self.db.execute("INSERT INTO facts VALUES('preserved-epoch','original-reservation',5000)")
  self.db.commit()
 def step(self,*,admit):
  print('committed',flush=True)
  threading.Event().wait(60)
  return {}
 def close(self):self.db.close()
w=Worker(Service)
def stop(*args):
 try:w.close(timeout=.05)
 except TimeoutError:pass
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
w.tick(6)
while True:time.sleep(.01)
'''
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'fixture.sqlite'
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            child=subprocess.Popen([sys.executable,'-c',source,str(path)],env=env,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'committed')
                started=time.monotonic();Supervisor.stop_process(child,timeout=.2)
                self.assertLess(time.monotonic()-started,2)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT * FROM facts').fetchall(),
                                     [('preserved-epoch','original-reservation',5000)])
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:
                if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
                child.stdout.close();child.stderr.close()
