import json
from pathlib import Path
import tempfile
import unittest
from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.provider_admission import Admission,next_ticket,record_service,POSITION_BURST,position_work,foreground_work,priority


class SustainedPositionFairnessTests(unittest.TestCase):
    def test_lifecycle_scope_and_thread_exception_isolation(self):
        from concurrent.futures import ThreadPoolExecutor
        @position_work
        def lifecycle():
            self.assertEqual(priority('pons_natural'),0)
            self.assertEqual(priority('universe_identity'),0)
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(priority,'pons_natural').result(),10)
            raise BoundaryError('injected_lifecycle_failure')
        with self.assertRaises(BoundaryError):lifecycle()
        self.assertEqual(priority('pons_natural'),10)
        self.assertEqual(priority('universe_identity'),50)

    def exercise(self,lane,deadline,scope='universe_identity'):
        with tempfile.TemporaryDirectory() as td:
            now=[100.];positions=[];transport=[]
            def sleep(seconds):
                now[0]+=seconds
                db=gate.connect()
                next_at,cooldown,interval=db.execute('SELECT next_at,cooldown,interval FROM limits').fetchone()
                first=next_ticket(db,gate.endpoint,now[0],interval)
                if first and first[0]=='position' and now[0]>=max(next_at,cooldown):
                    positions.append(now[0]);record_service(db,gate.endpoint,'pons',True)
                    db.execute('UPDATE limits SET next_at=?',(now[0]+interval,))
                    db.execute("UPDATE queue SET created=?,deadline=? WHERE id='position'",(now[0],now[0]+30))
                db.close()
            gate=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane=lane,clock=lambda:now[0],sleeper=sleep)
            db=gate.connect()
            db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',('position',gate.endpoint,0,100.,130.))
            db.execute('INSERT INTO queue_meta VALUES(?,?)',('position','pons'));db.close()
            boundary=None
            try:gate.invoke(lambda:transport.append(now[0]),['eth_getCode'],scope,deadline=deadline)
            except BoundaryError as exc:boundary=str(exc)
            db=gate.connect()
            event=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            physical=db.execute('SELECT count(*) FROM transports').fetchone()[0]
            interval=db.execute('SELECT interval FROM limits').fetchone()[0]
            pending=next_ticket(db,gate.endpoint,now[0],interval);db.close()
            return boundary,positions,transport,event,physical,interval,pending

    def test_other_lane_bounded_service_preserves_ceiling(self):
        boundary,positions,transport,event,physical,interval,pending=self.exercise('ramses',110.)
        self.assertIsNone(boundary);self.assertEqual(len(positions),POSITION_BURST)
        self.assertEqual(len(transport),1);self.assertLess(transport[0],105.)
        times=positions+transport
        self.assertTrue(all(b-a>=.5-1e-9 for a,b in zip(times,times[1:])))
        self.assertEqual(interval,.5);self.assertEqual(physical,1)
        self.assertEqual(event['deadline'],110.);self.assertEqual(pending[0],'position')

    def test_same_lane_research_cannot_bypass_position_and_never_transports(self):
        boundary,positions,transport,event,physical,interval,pending=self.exercise('pons',105.)
        self.assertEqual(boundary,'provider_shared_admission_deadline')
        self.assertEqual(transport,[]);self.assertEqual(physical,0)
        self.assertEqual(event['deadline'],105.);self.assertEqual(event['reason'],boundary)
        self.assertEqual(event['methods'],['eth_getCode'])
        self.assertEqual(event['failure_domain'],'local_admission')
        self.assertFalse(event['transport_attempted'])

    def test_imminent_position_deadline_keeps_priority(self):
        with tempfile.TemporaryDirectory() as td:
            gate=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='ramses')
            db=gate.connect()
            for identity,lane,priority_value,deadline in [('position','pons',0,104.2),('research','ramses',50,110.)]:
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(identity,gate.endpoint,priority_value,100.,deadline))
                db.execute('INSERT INTO queue_meta VALUES(?,?)',(identity,lane))
            for _ in range(POSITION_BURST):record_service(db,gate.endpoint,'pons',True)
            self.assertEqual(next_ticket(db,gate.endpoint,104.,.5)[0],'position');db.close()

    def test_expired_consumer_never_enqueues_or_transports(self):
        with tempfile.TemporaryDirectory() as td:
            gate=Admission(str(Path(td)/'gate.db'),'https://example.com/key',lane='ramses',clock=lambda:100.)
            with self.assertRaisesRegex(BoundaryError,'deadline'):
                gate.invoke(lambda:self.fail('unexpected transport'),['eth_call'],'universe_identity',deadline=99.)
            db=gate.connect();row=json.loads(db.execute('SELECT body FROM admissions').fetchone()[0])
            self.assertEqual(row['deadline'],99.);self.assertEqual(row['methods'],['eth_call'])
            self.assertEqual(db.execute('SELECT count(*) FROM queue').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM transports').fetchone()[0],0);db.close()

    def test_same_lane_foreground_observation_has_bounded_service(self):
        boundary,positions,transport,event,physical,interval,pending=self.exercise('pons',110.,'pons_natural')
        self.assertIsNone(boundary)
        self.assertEqual(len(positions),POSITION_BURST)
        self.assertEqual(len(transport),1);self.assertLess(transport[0],105.)
        self.assertEqual(event['priority'],10);self.assertEqual(event['deadline'],110.)
        self.assertEqual(pending[0],'position');self.assertEqual(interval,.5)

    def test_429_can_only_reduce_shared_rate_and_success_recovers_to_existing_ceiling(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.]
            gate=Admission(str(Path(td)/'gate.db'),'https://example.com/key',
                lane='pons',clock=lambda:now[0],sleeper=lambda n:now.__setitem__(0,now[0]+n))
            with self.assertRaisesRegex(BoundaryError,'provider_http_429'):
                gate.invoke(lambda:(_ for _ in ()).throw(BoundaryError('provider_http_429')),
                    ['eth_getLogs'],'pons_natural',deadline=105.)
            db=gate.connect()
            _next,cooldown,slowed=db.execute(
                'SELECT next_at,cooldown,interval FROM limits').fetchone();db.close()
            self.assertEqual(cooldown,108.)
            self.assertGreater(slowed,.5);self.assertLessEqual(slowed,2.0)
            now[0]=109.
            gate.invoke(lambda:[],['eth_getLogs'],'pons_natural',deadline=114.)
            db=gate.connect()
            recovered=db.execute('SELECT interval FROM limits').fetchone()[0];db.close()
            self.assertGreaterEqual(recovered,.5)
            self.assertLess(recovered,slowed)

    def test_foreground_authentication_retains_position_precedence_and_context_isolation(self):
        @foreground_work
        def observation():
            self.assertEqual(priority('connectivity'),10)
            @position_work
            def position():self.assertEqual(priority('connectivity'),0)
            position()
            self.assertEqual(priority('connectivity'),10)
            raise BoundaryError('injected_observation_failure')
        with self.assertRaises(BoundaryError):observation()
        self.assertEqual(priority('connectivity'),50)
