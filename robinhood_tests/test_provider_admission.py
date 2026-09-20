import json
from pathlib import Path
import tempfile
import unittest
from robinhood_research import BoundaryError
from robinhood_research.provider_admission import Admission,priority

class SharedAdmissionTests(unittest.TestCase):
    def test_two_sessions_share_physical_request_clock_and_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.0]
            def sleep(seconds):now[0]+=seconds
            kw=dict(clock=lambda:now[0],sleeper=sleep,lane='test')
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/secret',**kw)
            b=Admission(a.path,'https://example.com/secret/',**kw)
            self.assertEqual(a.endpoint,b.endpoint)
            a.acquire('discovery')
            wait=b.acquire('paper_exit')['wait_seconds']
            self.assertGreaterEqual(wait,0.5);self.assertLess(wait,0.502)
            def limited():raise BoundaryError('provider_http_429')
            with self.assertRaises(BoundaryError):a.invoke(limited,['eth_call'],'evidence')
            wait=b.acquire('paper_exit')['wait_seconds']
            self.assertGreaterEqual(wait,8.0)
            db=a.connect();raw=db.execute('SELECT body FROM transports').fetchone()[0];db.close()
            row=json.loads(raw)
            self.assertEqual(row['http_status'],429)
            self.assertNotIn('secret',raw)
    def test_open_position_precedes_research_and_queue_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            a=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='test')
            db=a.connect();now=a.clock()
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('research',a.endpoint,50,now-1,now+30))
            self.assertLess(a.acquire('lifecycle_unwind')['wait_seconds'],0.1)
            for n in range(255):
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(str(n),a.endpoint,50,now,now+30))
            with self.assertRaisesRegex(BoundaryError,'capacity'):a.acquire('candidate')
            db.close()
            self.assertLess(priority('pons_paper'),priority('research_history'))
