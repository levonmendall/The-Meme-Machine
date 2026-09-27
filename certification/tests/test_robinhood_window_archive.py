"""Verified native handoffs bound raw history without granting replay authority."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from certification import campaign_state as transfer
from certification.robinhood.plane import Plane,canonical
from certification.robinhood.accounting import project,high_water
from certification.robinhood.window_archive import CACHE_LIMITS,logical_hash
from certification.tests import test_pons_window_archive as helpers


class RobinhoodWindowArchive(unittest.TestCase):
    fixture=helpers.PonsWindowArchive.fixture
    staged=helpers.PonsWindowArchive.staged
    def test_changing_rolling_keys_leave_only_preserved_raw_history(self):
        f,pons,ramses=self.initialize();sizes=[];parent=None
        for window in range(6):
            self.populate(f,pons,ramses,window,count=1)
            path=f.run/'shared-robinhood-evidence.candidates.sqlite'
            plane=Plane(path,clock=lambda:window*3600.)
            for index in range(40):
                plane.rolling_put('retired-curve:'+str(window*40+index),'tx:'+str(index),
                    window*3600+index,index,{'authenticated':index},
                    {'authority':'authenticated_receipt_header'})
            plane.close();output,runtime,artifact=self.staged(f,window)
            window_identity=dict(f.window,index=window,workflow_run_id=window+1)
            if parent:window_identity['parent_state_hash']=parent
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,
                window=window_identity,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            archived=artifact/'certification-hourly'/path.name
            with sqlite3.connect(archived) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],40)
            copied=output/'capsule/files/shared'/path.name
            with sqlite3.connect(copied) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],0)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(body['robinhood_history_handoff']['before']['rolling'],40)
            self.assertEqual(body['robinhood_history_handoff']['after']['rolling'],0)
            # Cache miss must reacquire and validate through the existing adapter;
            # a same-window conflicting value remains a hard failure.
            cache_probe=output/'cache-probe.sqlite';shutil.copyfile(copied,cache_probe)
            plane=Plane(cache_probe)
            proof={'authority':'authenticated_receipt_header'}
            self.assertIsNone(plane.rolling_get('retired-curve:0','tx:0',proof))
            plane.rolling_put('fresh','tx',window*3600,1,{'authenticated':1},proof)
            with self.assertRaisesRegex(ValueError,'rolling_evidence_conflict'):
                plane.rolling_put('fresh','tx',window*3600,1,{'authenticated':2},proof)
            with self.assertRaisesRegex(ValueError,'rolling_authority'):
                plane.rolling_put('fresh','untrusted',window*3600,1,{}, {})
            plane.close()
            # The sealed capsule remains immutable during the cache probe.
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,
                expected_identity=f.identity,expected_state_hash=body['state_hash'],
                campaign_id=window_identity['campaign_id'],prior_index=window,
                authorization_hash=window_identity['authorization_hash'])
            shutil.rmtree(f.lanes);shutil.rmtree(f.run)
            next_work.rename(f.lanes);next_run.rename(f.run);parent=body['state_hash']
            sizes.append(path.stat().st_size)
        self.assertLessEqual(max(sizes[2:])-min(sizes[2:]),65536)

    def test_rolling_archive_publication_cut_rolls_back_and_corruption_blocks_seal(self):
        from certification.robinhood import window_archive
        f,pons,ramses=self.initialize();self.populate(f,pons,ramses,0,count=1)
        path=f.run/'shared-robinhood-evidence.candidates.sqlite';plane=Plane(path)
        plane.rolling_put('old','tx',1,1,{'exact':True},{'authority':'authenticated_receipt_header'})
        plane.close();output,runtime,artifact=self.staged(f,0)
        original=window_archive.canonical
        def cut(value):
            if value.get('schema')=='robinhood-window-history-v1':raise SystemExit('after cache deletion before commit')
            return original(value)
        with patch.object(window_archive,'canonical',side_effect=cut),self.assertRaises(SystemExit):
            transfer.seal(output/'cut',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'cut/campaign-state.json').exists())
        with sqlite3.connect(output/'cut/files/shared'/path.name) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rolling').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0],3)
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM transitions')
        with sqlite3.connect(artifact/'certification-hourly'/path.name) as db:
            db.execute("UPDATE rolling SET body='{}'")
        with self.assertRaises(ValueError):
            transfer.seal(output/'corrupt',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'corrupt/campaign-state.json').exists())
    def test_d1_changing_identities_plateau_and_preserved_prefix_cannot_reenter(self):
        from tempfile import TemporaryDirectory
        from certification.resource_churn import robinhood
        from certification.robinhood import window_archive
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'old').mkdir();(root/'new').mkdir()
            # Same D1 driver: removing only retirement reproduces the old leak.
            with patch.object(window_archive,'_retire_identities',return_value={}):
                old=robinhood(root/'old',3,20)
            new=robinhood(root/'new',6,20)
            table='shared-robinhood-evidence.candidates.sqlite:candidates'
            self.assertEqual([s['tables'][table] for s in old],[20,40,60])
            self.assertEqual([s['tables'][table] for s in new],[1]*6)
            for sample in new:
                for name in ('observations','observation_archive','result_consumption'):
                    self.assertEqual(sample['tables'][table.rsplit(':',1)[0]+':'+name],1)
            archive=root/'new/window-5/artifact/certification-hourly/shared-robinhood-evidence.candidates.sqlite'
            with sqlite3.connect(archive) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],21)
            copied=root/'new/window-5/capsule/files/shared/shared-robinhood-evidence.candidates.sqlite'
            plane=Plane(copied,clock=lambda:22000.)
            try:
                before=plane.history_archive();latest=plane.get('curve:119')
                self.assertEqual(plane.observe('curve:0','pons','replayed',{},ordering=(0,),watermark={},
                    interpretation={'policy':'frozen'},observed=22000,deadline=22005,priority=4),'archived')
                self.assertIsNone(plane.get('curve:0'));self.assertEqual(plane.get('curve:119'),latest)
                self.assertEqual(plane.observe('new','pons','new',{},ordering=(120,),watermark={},
                    interpretation={'policy':'frozen'},observed=22000,deadline=22005,priority=4),'created')
                self.assertGreater(plane.db.execute('SELECT MAX(seq) FROM transitions').fetchone()[0],before['transition_high_water'])
                bad=dict(before,retired_ordering={'pons':[999999]});plane.checkpoint('window_history_archive',bad)
                with self.assertRaisesRegex(ValueError,'archive_corruption'):
                    plane.observe('unknown','pons','x',{},ordering=(121,),watermark={},
                        interpretation={},observed=22000,deadline=22005,priority=4)
            finally:plane.close()

    def test_scoped_native_terminal_projections_plateau_and_live_projection_survives(self):
        from certification.lifecycle_identity import scope,MARKER
        f,pons,ramses=self.initialize();parent=None;sizes=[]
        for window in range(6):
            identity=dict(f.window,index=window,workflow_run_id=window+1)
            if parent:identity['parent_state_hash']=parent
            tag=scope(identity);suffix=MARKER+tag['campaign']+':'+str(window)
            code="""import sys,json
from pathlib import Path
from certification.offline_tests import install_network_guard
install_network_guard()
from certification.robinhood.plane import Plane,project_native_position
from certification.robinhood.accounting import project
from robinhood_research.pipeline import Pipeline
from robinhood_research.evidence import Store
from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
root=Path(sys.argv[1]);plane_path=sys.argv[2];window=int(sys.argv[3]);suffix=sys.argv[4]
case=PartialAccountingTests();plane=Plane(plane_path,clock=lambda:window*3600+100.)
pipe=Pipeline(root/'opportunity-pipeline.sqlite','pons','frozen')
for n in range(4):
 at=window*3600+n*10;key='curve:'+str(window*4+n);identity='trial:'+str(window*4+n)+suffix
 plane.observe(key,'pons',key,{},ordering=(window*4+n,),watermark={},interpretation={},observed=at,deadline=at+500,priority=4)
 work=plane.claim(key=key);assert plane.finish(work,result={'rejected':False});assert plane.consume(key,work['generation'])
 path=root/('trial-'+str(window*4+n)+'.sqlite');store=Store(path)
 book=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH)
 book.reserve(identity,market='m',amount=100,gas_budget=20,now=at,features=case.features(at))
 p=book.advance(identity,now=at+1,action='entry',quote=case.quote(at+1,'buy',100,1000))
 project_native_position(plane_path,'pons',key,p,ledger_path=path,policy=POLICY_HASH)
 if not (window==0 and n==0):
  book.advance(identity,now=at+2,action='exit_intent')
  p=book.advance(identity,now=at+3,action='exit',quote=case.quote(at+3,'sell',1000,106))
  project_native_position(plane_path,'pons',key,p,ledger_path=path,policy=POLICY_HASH)
 book.reconcile();store.close()
while project(plane,pipe)==256:pass
pipe.close();plane.close()
"""
            native=subprocess.run([sys.executable,'-c',code,str(pons.parent),str(f.run/'shared-robinhood-evidence.candidates.sqlite'),str(window),suffix],
                cwd=Path(os.environ['MM_TEST_LANE_WORKTREES'])/'pons',env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=20)
            self.assertEqual(native.returncode,0,native.stdout+native.stderr)
            output,runtime,artifact=self.staged(f,window)
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=identity,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            self.assertEqual(body['robinhood_history_handoff']['retired_positions'],3 if window==0 else 4)
            copied=output/'capsule/files/shared/shared-robinhood-evidence.candidates.sqlite'
            with sqlite3.connect(copied) as db:
                projections=db.execute("SELECT body FROM runtime WHERE key LIKE 'native_position:%'").fetchall()
                self.assertEqual(len(projections),1);self.assertEqual(json.loads(projections[0][0])['position']['status'],'open')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],2)
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,
                expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=identity['campaign_id'],prior_index=window,authorization_hash=identity['authorization_hash'])
            shutil.rmtree(f.lanes);shutil.rmtree(f.run);next_work.rename(f.lanes);next_run.rename(f.run);parent=body['state_hash']
            sizes.append((f.run/copied.name).stat().st_size)
        self.assertLessEqual(max(sizes[2:])-min(sizes[2:]),8192)

    def native_pipeline(self,lane):
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not roots:self.skipTest('requires canonical prepared native lanes')
        path=Path(roots)/lane/'robinhood_research/pipeline.py'
        spec=importlib.util.spec_from_file_location('native_pipeline_'+lane,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.Pipeline
    def initialize(self):
        f=self.fixture();path=f.run/'shared-robinhood-evidence.candidates.sqlite';path.unlink()
        plane=Plane(path,clock=lambda:100.)
        pons=f.lanes/'pons/pons-selective-continuation-v1-cohort/opportunity-pipeline.sqlite'
        ramses=f.lanes/'ramses/robinhood-ramses-extended-market.sqlite.pipeline.sqlite'
        p=self.native_pipeline('pons')(pons,'pons','frozen');r=self.native_pipeline('ramses')(ramses,'ramses','frozen')
        p.close();r.close();plane.close()
        return f,pons,ramses
    def populate(self,f,pons,ramses,index,count=200):
        plane=Plane(f.run/'shared-robinhood-evidence.candidates.sqlite',clock=lambda:100.)
        p=self.native_pipeline('pons')(pons,'pons','frozen');r=self.native_pipeline('ramses')(ramses,'ramses','frozen')
        try:
            for i in range(count):
                n=index*count+i+1
                plane.observe('curve','pons',str(n),{'n':n},ordering=(n,),watermark={'n':n},
                    interpretation={'policy':'frozen'},observed=100,deadline=105,priority=4)
                work=plane.claim(key='curve');self.assertIsNotNone(work)
                self.assertTrue(plane.finish(work,result={'rejected':'frozen'}))
                self.assertTrue(plane.consume('curve',work['generation']))
                plane.put('domain:header_hash',canonical(f'{n:064x}'),{'hash':f'{n:064x}','number':hex(n)},
                    {'authority':'authenticated_alchemy','schema':1,'finality':'confirmed'})
                plane.put('ramses_route_v1',str(n),{'cost':n},{'authority':'authenticated_alchemy'})
                r.record('pool','rejected','frozen','strategy_rejection')
            through=high_water(plane)
            while project(plane,p,through=through)==256:pass
            saved=plane.get('curve');snapshot=p.snapshot()
        finally:p.close();r.close();plane.close()
        return saved,snapshot
    def test_repeated_native_windows_bound_history_cache_and_projection_receipts(self):
        f,pons,ramses=self.initialize();previous=None;sizes=[];chains=set();last_sequence=0
        for window in range(28):
            saved,snapshot=self.populate(f,pons,ramses,window)
            output,runtime,artifact=self.staged(f,window)
            identity=dict(f.window,index=window,workflow_run_id=window+1)
            if previous:identity['parent_state_hash']=previous
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=identity,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            proof=body['robinhood_history_handoff'];chains.add(proof['chain_hash'])
            self.assertGreater(proof['transition_high_water'],last_sequence);last_sequence=proof['transition_high_water']
            self.assertEqual(proof['pipelines'][0]['raw_records'],600)
            self.assertEqual(proof['pipelines'][0]['classes'],{'canonical_completion':1})
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,
                expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=identity['campaign_id'],
                prior_index=window,authorization_hash=identity['authorization_hash'])
            plane=Plane(next_run/'shared-robinhood-evidence.candidates.sqlite',clock=lambda:100.)
            try:
                self.assertEqual(plane.get('curve'),saved)
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],1)
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM transitions').fetchone()[0],0)
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM result_consumption').fetchone()[0],1)
                self.assertLessEqual(plane.db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],CACHE_LIMITS['header_hash'])
                self.assertEqual(plane.db.execute('SELECT COUNT(*) FROM observation_archive').fetchone()[0],1)
                if window:
                    self.assertEqual(plane.observe('curve','pons','1',{'changed_old_public_value':True},ordering=(1,),
                        watermark={},interpretation={'policy':'frozen'},observed=200,deadline=205,priority=4),'archived')
                    self.assertEqual(plane.get('curve'),saved)
                self.assertEqual(plane.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:plane.close()
            for lane,name in [('pons','pons-selective-continuation-v1-cohort/opportunity-pipeline.sqlite'),
                              ('ramses','robinhood-ramses-extended-market.sqlite.pipeline.sqlite')]:
                p=self.native_pipeline(lane)(next_work/lane/name,lane,'frozen')
                self.assertEqual(p.snapshot()['raw_records'],0)
                if lane=='pons':self.assertEqual(p.db.execute('SELECT COUNT(*) FROM progress_sources').fetchone()[0],1)
                p.close()
            sizes.append(sum(p.stat().st_size for p in next_work.rglob('*') if p.is_file())+
                         sum(p.stat().st_size for p in next_run.rglob('*') if p.is_file()))
            shutil.rmtree(f.lanes);shutil.rmtree(f.run)
            next_work.rename(f.lanes);next_run.rename(f.run);previous=body['state_hash']
        self.assertEqual(len(chains),28)
        self.assertLessEqual(max(sizes[23:])-min(sizes[23:]),65536,sizes)
        code='''import sys
from certification.robinhood.plane import Plane
from certification.robinhood.pons import durable_cache
from certification.robinhood.window_archive import CACHE_LIMITS
from robinhood_research.pons_selective_acquisition import CACHE_HEADERS,CACHE_RECEIPTS,CACHE_LAUNCHES
assert CACHE_LIMITS['header_hash']==CACHE_HEADERS and CACHE_LIMITS['receipt']==CACHE_RECEIPTS and CACHE_LIMITS['launch']==CACHE_LAUNCHES
p=Plane(sys.argv[1]);c=durable_cache(p,'domain')
assert c.header_by_hash(f'{1:064x}') is None
latest=c.header_by_hash(f'{5600:064x}');assert latest['number']==hex(5600)
try:c.remember_header(dict(latest,number=hex(5601)))
except ValueError as e:assert 'conflict' in str(e)
else:raise AssertionError('retained immutable evidence changed')
p.close()
'''
        native=subprocess.run([sys.executable,'-c',code,str(f.run/'shared-robinhood-evidence.candidates.sqlite')],
            cwd=Path(os.environ['MM_TEST_LANE_WORKTREES'])/'pons',env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),
            capture_output=True,text=True,timeout=20)
        self.assertEqual(native.returncode,0,native.stdout+native.stderr)
        from certification.market_assurance import pipeline
        report=pipeline(f.lanes/'pons',candidate_plane=f.run/'shared-robinhood-evidence.candidates.sqlite',lane='pons')
        self.assertEqual(report['history_archive']['chain_hash'],proof['chain_hash'])
        self.assertEqual(report['candidate_plane_consistency']['status'],'pass')
        print('Robinhood current-window hot bytes:',min(sizes[23:]),max(sizes[23:]),'; 5,600 raw observations preserved')
    def test_unpreserved_unprojected_and_interrupted_capsules_fail_closed(self):
        f,pons,ramses=self.initialize();self.populate(f,pons,ramses,0,count=3)
        output,runtime,artifact=self.staged(f,0)
        plane=Plane(runtime/'shared-robinhood-evidence.candidates.sqlite')
        plane.checkpoint('unpreserved',{'new':True});plane.close()
        with self.assertRaisesRegex(ValueError,'source_changed'):
            transfer.seal(output/'changed',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'changed/campaign-state.json').exists())
        shutil.copyfile(f.run/'shared-robinhood-evidence.candidates.sqlite',runtime/'shared-robinhood-evidence.candidates.sqlite')
        from certification.robinhood import window_archive
        erase=window_archive._erase
        def cut(db,table,*args,**kw):
            if table=='transitions':raise SystemExit('after observation prefix deletion')
            return erase(db,table,*args,**kw)
        with patch.object(window_archive,'_erase',side_effect=cut),self.assertRaises(SystemExit):
            transfer.seal(output/'cut',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'cut/campaign-state.json').exists())
        with sqlite3.connect(output/'cut/files/shared/shared-robinhood-evidence.candidates.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],3)
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM observations')
        # Missing projection is a failure, never hidden by erasing both histories.
        p=self.native_pipeline('pons')(pons,'pons','frozen')
        with p.db:p.db.execute('DELETE FROM progress_sources')
        p.close();other,runtime2,artifact2=self.staged(f,1)
        with self.assertRaisesRegex(ValueError,'projection_incomplete'):
            transfer.seal(other/'capsule',worktrees=f.lanes,run=runtime2,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact2)
        self.assertFalse((other/'capsule/campaign-state.json').exists())

    def test_position_only_native_updates_archive_but_unknown_risk_does_not(self):
        from certification.autonomous_window import stage
        f,pons,ramses=self.initialize();self.populate(f,pons,ramses,0,count=1)
        plane_path=f.run/'shared-robinhood-evidence.candidates.sqlite'
        book_path=pons.parent/'trial-000.sqlite'
        code="""import json,sys
from certification.offline_tests import install_network_guard
install_network_guard()
from robinhood_research.evidence import Store
from robinhood_research.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_tests.test_pons_partial_accounting import PartialAccountingTests
from robinhood_research.pipeline import Pipeline
from certification.robinhood.plane import Plane,project_native_position
from certification.robinhood.accounting import project
case=PartialAccountingTests();store=Store(sys.argv[1])
book=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH)
book.reserve('real-partial',market='m',amount=100,gas_budget=20,now=10,features=case.features(10))
p=book.advance('real-partial',now=11,action='entry',quote=case.quote(11,'buy',100,1000))
project_native_position(sys.argv[2],'pons','curve',p,ledger_path=sys.argv[1],policy=POLICY_HASH)
plane=Plane(sys.argv[2]);pipe=Pipeline(sys.argv[3],'pons','frozen')
while project(plane,pipe)==256:pass
pipe.close();plane.close()
book.advance('real-partial',now=12,action='exit_intent',exit_tokens=500)
p=book.advance('real-partial',now=13,action='exit',quote=case.quote(13,'sell',500,70))
assert p['tokens']==500 and p['status']=='open'
project_native_position(sys.argv[2],'pons','curve',p,ledger_path=sys.argv[1],policy=POLICY_HASH)
book.reconcile();store.close();print(json.dumps(p))
"""
        native=subprocess.run([sys.executable,'-c',code,str(book_path),str(plane_path),str(pons)],
            cwd=Path(os.environ['MM_TEST_LANE_WORKTREES'])/'pons',env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),
            capture_output=True,text=True,timeout=20)
        self.assertEqual(native.returncode,0,native.stdout+native.stderr);position=json.loads(native.stdout)
        for blocked in (False,True):
            if blocked:
                p=Plane(plane_path)
                with p.transaction():p._audit(p.get('curve'),'authoritative_evidence_failure','unresolved')
                p.close()
            output=f.root/('position-'+str(blocked));output.mkdir();runtime=output/'certification-position'
            shutil.copytree(f.run,runtime);terminal=dict(f.terminal,phase='position_continuation')
            (runtime/'result.json').write_text(canonical(terminal));artifact=stage(f.lanes,output,'position')
            args=dict(worktrees=f.lanes,run=runtime,window=f.window,terminal=terminal,
                      expected_identity=f.identity,preserved_artifact=artifact)
            if blocked:
                with self.assertRaisesRegex(ValueError,'accounting_unreconciled'):
                    transfer.seal(output/'capsule',**args)
                self.assertFalse((output/'capsule/campaign-state.json').exists())
            else:
                body=transfer.seal(output/'capsule',**args)
                self.assertEqual(body['robinhood_history_handoff']['after']['transitions'],0)
                with sqlite3.connect(output/'capsule/files/shared'/plane_path.name) as db:
                    retained=json.loads(db.execute('SELECT body FROM runtime WHERE key=?',('native_position:pons:'+position['id'],)).fetchone()[0])
                self.assertEqual(retained['position'],position)
