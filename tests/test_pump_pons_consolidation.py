"""Disposable restored-state pressure, physical-call guards and frozen economics.

These measurements prove offline isolation, never prospective provider capacity.
"""
import asyncio
from contextlib import closing
import json
import os
import sqlite3
import time
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from meme_machine.runtime.operating_families import PausedFamily
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.governor import Governor
from meme_machine.runtime.robinhood.plane import Plane
from meme_machine.lanes.pons.provider_admission import Admission
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_evidence_service import program_subscriptions
from meme_machine.solana_selective_source import SelectiveSource,scout_request,plan_live
from meme_machine.solana_selective_history import PROGRAMS,economic_records
from tests.test_solana_closure import state_at,NOW
from tests.test_solana_selective_evidence import FIXTURE

OPERATIONAL={'MM_OPERATIONAL_PHASE':'continuous','MM_MODE':'PAPER'}


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_solana_filters_keep_complete_pump_programs_and_remove_dlmm(self):
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            request=scout_request()
            self.assertEqual(set(request.accounts),{'p'})
            self.assertEqual(list(request.accounts['p'].owner),[PROGRAMS['pump']])
            subs=program_subscriptions()
            self.assertEqual({r.scope for r in subs},{'program:pump','program:pumpswap'})
            self.assertEqual(len(subs),4)
            self.assertFalse(any(r.address==PROGRAMS['meteora'] for r in subs))

    def test_restored_meteora_jobs_and_lifecycle_are_frozen_under_pump_pressure(self):
        path=self.root/'evidence.sqlite'
        with patch.dict(os.environ,{},clear=True):
            state,h=state_at(path)
            h.observe('meteora','old-pool',slot=1,signature='',seen=NOW-10,fields={'activity':True})
            h.bind('meteora','old-pool')
            h.request('meteora','old-pool',1,2,priority=0,deadline=NOW-1)
            while h.lifecycle.flush():pass
            before={t:state.writer.db.execute('SELECT * FROM '+t).fetchall() for t in
                    ('acquisition_jobs','candidate_lifecycle','market_observations','evidence_bindings')}
            state.writer.close()
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            state,h=state_at(path)
            self.addCleanup(state.writer.close)
            for i in range(100):
                h.observe('pump','curve-'+str(i),slot=3,signature='',seen=NOW,fields={'activity':False})
                h.request('pump','curve-'+str(i),3,4,priority=4,deadline=NOW+150)
            h.lifecycle.refresh();h.lifecycle.flush();h.rolling.resume_boundaries();h.rolling.resume_publication()
            jobs=h.plan();live=plan_live(state)
            self.assertIsNotNone(jobs);self.assertEqual(jobs[0]['family'],'pump')
            self.assertFalse(any(r['family']=='meteora' for r in live))
            self.assertEqual(state.writer.db.execute("SELECT COUNT(*) FROM market_observations WHERE family='pump'").fetchone()[0],100)
            for t,rows in before.items():
                self.assertEqual(state.writer.db.execute('SELECT * FROM '+t+" WHERE family='meteora'").fetchall(),rows)
            self.assertEqual(state.writer.db.execute("SELECT COUNT(*) FROM provider_delivery WHERE family='meteora'").fetchone()[0],0)
            for operation in (
                lambda:h.observe('meteora','new',slot=5,signature='',fields={}),
                lambda:h.request('meteora','old-pool',5,6,priority=0,deadline=NOW+150),
                lambda:h.delivery('meteora','rpc',raw_bytes=5,rpc_cu=70,calls=1)):
                with self.assertRaises((EvidenceUnavailable,PausedFamily)):operation()

    def test_expired_and_active_paused_leases_cannot_starve_active_workers(self):
        with patch.dict(os.environ,{},clear=True),closing(CandidateHistory(self.root/'history.sqlite',clock=lambda:NOW,worker_capacity=2)) as h:
            paused=[]
            for lane in ('meteora','ramses'):
                identity=h.enqueue(lane,lane,kind='history',ready_at=NOW-1,deadline=NOW+200,estimate_seconds=1)
                h.db.execute("UPDATE work SET status='active',worker='dead',lease_until=? WHERE id=?",(NOW-1 if lane=='meteora' else NOW+100,identity))
                paused.append(tuple(h.db.execute('SELECT * FROM work WHERE id=?',(identity,)).fetchone()))
            with patch.dict(os.environ,OPERATIONAL,clear=True):
                for lane in ('pump','pons'):
                    h.enqueue(lane,lane,kind='candidate',ready_at=NOW,deadline=NOW+150,estimate_seconds=1)
                selected=[h.claim('one'),h.claim('two')]
                self.assertEqual({r['lane'] for r in selected},{'pump','pons'})
                self.assertIsNone(h.claim('third'))
                self.assertEqual(h.db.execute("SELECT * FROM work WHERE lane IN ('meteora','ramses') ORDER BY lane").fetchall(),sorted(paused,key=lambda r:r[1]))
                for lane in ('meteora','ramses'):
                    with self.assertRaises(PausedFamily):h.enqueue(lane,'new',kind='candidate',ready_at=NOW,deadline=NOW+1,estimate_seconds=1)

    def test_robinhood_recovery_does_not_resume_or_maintain_old_ramses(self):
        with patch.dict(os.environ,{},clear=True),closing(Plane(self.root/'rh.sqlite',clock=lambda:NOW)) as plane:
            def nominate(key,lane):
                plane.observe(key,lane,key,{},ordering=[1],watermark={'block':1},interpretation={},observed=NOW-1,deadline=NOW+150,priority=3)
            nominate('ramses:old','ramses')
            plane.claim(lane='ramses')
            plane.db.execute("UPDATE candidates SET owner='dead',claim_until=? WHERE lane='ramses'",(NOW-1,))
            before=dict(plane.get('ramses:old'))
            with patch.dict(os.environ,OPERATIONAL,clear=True):
                for i in range(100):nominate('pons:'+str(i),'pons')
                self.assertEqual(plane.claim()['lane'],'pons')
                plane.recover();plane.maintain()
                self.assertEqual(dict(plane.get('ramses:old')),before)
                self.assertIsNone(plane.claim(lane='ramses'))
                with self.assertRaises(PausedFamily):nominate('ramses:new','ramses')
                with self.assertRaises(PausedFamily):plane.put('ramses:headers','1',{}, {})
                with self.assertRaises(PausedFamily):plane.rolling_put('ramses:old','1',NOW,1,{},dict(authority='authenticated_receipt_header'))

    def test_paused_calls_fail_before_physical_provider_or_acquisition(self):
        rpc=Mock();source=SelectiveSource(SimpleNamespace(credential='offline'),rpc)
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            asyncio.run(source.structural_census())
            with self.assertRaises(PausedFamily):asyncio.run(source.measured_rpc('getProgramAccounts',[],'meteora'))
            rpc.assert_not_called();rpc.call_delivered.assert_not_called()
            with self.assertRaises(PausedFamily):Admission(self.root/'admission.sqlite','offline',lane='ramses')
            self.assertFalse((self.root/'admission.sqlite').exists())
            governor=Governor(self.root/'governor.sqlite')
            db=sqlite3.connect(governor.path);self.addCleanup(db.close)
            before=list(db.iterdump())
            for lane in ('ramses','meteora'):
                with self.assertRaises(PausedFamily):governor.acquire('offline',lane)
            self.assertEqual(list(db.iterdump()),before)

    def test_shared_provider_queue_ignores_paused_tickets_without_mutating_them(self):
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            governor=Governor(self.root/'governor.sqlite')
            with closing(sqlite3.connect(governor.path)) as db:
                now=time.monotonic()
                for i in range(256):
                    db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',(str(i),'solana','meteora',0,now,now+30))
                db.commit()
            self.assertLess(governor.acquire('solana','pump',deadline_seconds=1),1)
            with closing(sqlite3.connect(governor.path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM queue WHERE lane='meteora'").fetchone()[0],256)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM grants WHERE lane='meteora'").fetchone()[0],0)
            admission=Admission(self.root/'admission.sqlite','offline',lane='pons')
            with closing(admission.connect()) as db:
                now=time.monotonic()
                for i in range(256):
                    db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(str(i),admission.endpoint,0,now,now+30))
                    db.execute('INSERT INTO queue_meta VALUES(?,?)',(str(i),'ramses'))
            result=admission.acquire('candidate',deadline=time.monotonic()+1)
            self.assertEqual(result['queue_depth'],1)
            with closing(admission.connect()) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_meta WHERE lane='ramses'").fetchone()[0],256)

    def test_paused_native_intent_and_canonical_reservation_create_no_capital_claim(self):
        from meme_machine.operational.supervisor import Supervisor
        from meme_machine.runtime.portfolio import NativePortfolio
        from tests.shared_capital_support import legacy_proof,utc
        service=Supervisor(self.root,offline=True);service.initialize()
        self.addCleanup(service.lock.close)
        with service.account() as account:
            before=account.snapshot()
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            for lane in ('meteora','ramses'):
                client=NativePortfolio(self.root/'portfolio.sqlite',lane)
                with self.assertRaises(PausedFamily):
                    client.prepare('new',event_key='reserve',journal_hash='a'*64,kind='reserve',at=utc(1),data={'amount':'6.25'})
                with service.account() as account:
                    with self.assertRaises(PausedFamily):
                        account.reserve(epoch_id=service.epoch,event_id='new:'+lane,reservation_id='new',lane=lane,amount='6.25',at=utc(1),provenance=legacy_proof(lane,1))
                    self.assertEqual(account.snapshot(),before)
                    self.assertEqual(account.db.execute('SELECT COUNT(*) FROM portfolio_native_pending').fetchone()[0],0)
                    self.assertEqual(account.db.execute('SELECT COUNT(*) FROM portfolio_native_ids').fetchone()[0],0)
                    self.assertEqual(str(account.snapshot()['receipt']['starting_capital']),'500.00')

    def test_fixed_program_receipt_reactivates_retained_pumpswap_without_status_shards(self):
        from meme_machine.solana_program_decoders import pumpswap_trade_events
        tx=FIXTURE['pumpswap'][0];pool=next(e['pool'] for e in pumpswap_trade_events(tx))
        path=self.root/'evidence.sqlite'
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            state,h=state_at(path)
            h.observe('pumpswap',pool,slot=tx['slot']-1,signature='',seen=NOW-1,fields={'activity':False})
            h.lifecycle.demote('pumpswap',pool,reason='quiet')
            state.writer.close()
            state,h=state_at(path);self.addCleanup(state.writer.close)
            rows=economic_records('pumpswap',PROGRAMS['pumpswap'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')
            self.assertTrue(rows)
            h.ingest(rows)
            self.assertEqual(h.db.execute("SELECT state FROM candidate_lifecycle WHERE family='pumpswap' AND address=?",(pool,)).fetchone()[0],'reactivated')
            count=h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0]
            self.assertEqual(count,len(rows))
            h.ingest(rows)
            self.assertEqual(h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],count)
            self.assertFalse(any(r['family']=='meteora' for r in plan_live(state)))

    def test_stream_measurement_separates_attempts_first_delivery_and_errors(self):
        source=SelectiveSource(SimpleNamespace(credential='offline'),Mock())
        source.observe('subscribe',stream_id='one',family='pump')
        source.observe('subscribe',stream_id='two',family='control')
        source.observe('delivery',stream_id='one',family='pump')
        source.observe('native_error',stream_id='two',family='control',status='RESOURCE_EXHAUSTED')
        source.observe('unsubscribe',stream_id='two',family='control')
        stats=source.stream_telemetry()
        self.assertEqual((stats['client_open_streams'],stats['peak_client_streams'],stats['delivering_streams']),(1,2,1))
        self.assertEqual(stats['errors'],{'control:RESOURCE_EXHAUSTED':1})
        self.assertFalse(stats['provider_quota_verified'])

    def test_shared_retention_expiry_and_restart_freeze_meteora_and_its_accounts(self):
        from tests.maintenance_production_harness import Clock,rows,ingest
        from meme_machine.solana_maintenance_state import DebtAgeAdapter
        from meme_machine.solana_evidence_service import FinalizedFence
        clock=Clock();path=self.root/'evidence.sqlite'
        account='account:meteora-only-account'
        with patch.dict(os.environ,{},clear=True):
            state,h=state_at(path,clock.time);w=state.writer
            ingest(w,rows(clock,'program:meteora',5,age=400))
            ingest(w,rows(clock,account,5,age=400))
            w.interest('meteora',account,lower_slot=1)
            before={t:w.db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ('records','interests','gaps')}
            w.close()
        with patch.dict(os.environ,OPERATIONAL,clear=True):
            state,h=state_at(path,clock.time);w=state.writer;self.addCleanup(w.close)
            state.fence.expire_candidates(clock.time()+8000)
            state.fence.disconnect('recovery')
            ingest(w,rows(clock,'program:pump',5,age=400))
            plan=w.archive_plan(clock.time()-180)
            self.assertTrue(plan)
            self.assertTrue(all(r['body']['scope']=='program:pump' for r in plan))
            adapter=DebtAgeAdapter(w,monotonic=clock.monotonic,wall=clock.time)
            observation=adapter.observe('offline')
            self.assertFalse(any(r.scope in ('program:meteora',account) for r in observation.scopes))
            w.retain(clock.time()-180,max_records=64,checkpoint=False)
            self.assertEqual(w.db.execute("SELECT * FROM records WHERE scope='program:meteora' OR scope=? ORDER BY identity",(account,)).fetchall(),before['records'])
            self.assertEqual(w.db.execute('SELECT * FROM interests WHERE owner=?',('meteora',)).fetchall(),before['interests'])
            self.assertEqual(w.db.execute("SELECT * FROM gaps WHERE scope='program:meteora' OR scope=?",(account,)).fetchall(),before['gaps'])
            self.assertEqual(w.db.execute("SELECT COUNT(*) FROM maintenance_progress WHERE scope='program:meteora' OR scope=?",(account,)).fetchone()[0],0)

    def test_operational_queue_readers_ignore_archived_tickets_without_producer_env(self):
        from meme_machine.operational.observation import provider_queue
        with patch.dict(os.environ,{},clear=True):
            governor=Governor(self.root/'q.sqlite')
            with closing(sqlite3.connect(governor.path)) as db:
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',('old','solana','meteora',0,0,100))
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',('live','solana','pump',0,1,100))
                self.assertEqual(provider_queue(db,True),(1,1))

    def test_frozen_pons_policy_identities(self):
        from meme_machine.lanes.pons import pons_selective_continuation as current
        from meme_machine.lanes.pons import pons_postgrad_survivor as survivor
        self.assertEqual(current.POLICY_HASH,'888904d0e58865f1a701560a5be8386f57d88f66a0c25d7094c994cafa7f448f')
        self.assertEqual(survivor.POLICY_HASH,'ed17402a75470801fda47877b6b1f3b1266793b7e0750b7a7cd821f327541e5f')


if __name__=='__main__':unittest.main()
