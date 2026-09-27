"""Actual capsule handoff bounds consumed logs without resetting native sequence."""
from copy import deepcopy
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
from certification.autonomous_window import stage,verify_snapshot
from certification.journal import canonical
from certification.pons_window_archive import FOLDER,LOGS
from certification.tests import test_campaign_state as fixture

class PonsWindowArchive(unittest.TestCase):
    def fixture(self):
        f=fixture.CampaignStateTests();f.setUp();self.addCleanup(f.doCleanups)
        return f
    def save(self,f,window,summary=None):
        folder=f.lanes/'pons'/FOLDER;folder.mkdir(exist_ok=True)
        rows=[dict(sequence=(summary or {}).get('count',0)+n,
                   vector={'all_rejections':['frozen_rejection']},raw='x'*1024) for n in range(200)]
        result=dict(policy_hash='frozen',rows=[],qualifiers=[dict(index=0,curve='original',
            vector={'frozen':True},wallet_convergence={'converged':False})],
            lifecycles=[dict(index=0,curve='original',status='still_open')],
            native_archive_paths={k:FOLDER+'/'+v for k,v in LOGS.items()})
        if summary:result['archived_observations']=summary
        for key,name in LOGS.items():
            values=rows if key=='rows' else [dict(at=window['index']*3600,kind=key)]
            (folder/name).write_text(''.join(canonical(row)+'\n' for row in values))
            result[key]=[]
        saved=dict(result=result,phase='finalizing',owner='dead-owner',cursor=window['index'],
            autonomous_window={k:window[k] for k in ('campaign_id','authorization_hash','index','workflow_run_id')},
            archive_counts=dict(rows=200,discovery_sessions=1,sequencer_recoveries=1))
        with sqlite3.connect(f.run/'shared-robinhood-evidence.candidates.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS runtime(key PRIMARY KEY,body)')
            db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('pons_cohort',canonical(saved)))
        return saved
    def staged(self,f,index):
        output=f.root/('output-'+str(index));output.mkdir();runtime=output/'certification-hourly'
        shutil.copytree(f.run,runtime);(runtime/'result.json').write_text(canonical(f.terminal))
        artifact=stage(f.lanes,output,'hourly')
        return output,runtime,artifact
    def test_seven_day_raw_logs_stay_in_artifacts_and_next_sequence_remains_cumulative(self):
        f=self.fixture();summary=None;previous=None;hot=[];proofs=[]
        for hour in range(168):
            window=dict(f.window,index=hour,workflow_run_id=hour+1)
            if previous:window['parent_state_hash']=previous
            saved=self.save(f,window,summary);output,runtime,artifact=self.staged(f,hour)
            original=(artifact/'certification-native/hourly/pons'/FOLDER/LOGS['rows']).read_bytes()
            body=transfer.seal(output/'capsule',worktrees=f.lanes,run=runtime,window=window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
            self.assertEqual(body['accounting'],f.body['accounting'])
            self.assertTrue(verify_snapshot(artifact)['snapshot_complete'])
            self.assertEqual((artifact/'certification-native/hourly/pons'/FOLDER/LOGS['rows']).read_bytes(),original)
            next_work=f.root/'next-lanes';next_run=f.root/'next-run'
            transfer.restore(output/'capsule',worktrees=next_work,run=next_run,
                expected_identity=f.identity,expected_state_hash=body['state_hash'],campaign_id=window['campaign_id'],
                prior_index=hour,authorization_hash=window['authorization_hash'])
            with sqlite3.connect(next_run/'shared-robinhood-evidence.candidates.sqlite') as db:
                after=json.loads(db.execute("SELECT body FROM runtime WHERE key='pons_cohort'").fetchone()[0])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            summary=after['result']['archived_observations'];proofs.append(summary['chain_hash'])
            self.assertEqual(summary['count'],(hour+1)*200)
            self.assertEqual(summary['rejections'],{'frozen_rejection':(hour+1)*200})
            for key in ('qualifiers','lifecycles'):self.assertEqual(after['result'][key],saved['result'][key])
            for key,name in LOGS.items():
                self.assertFalse((next_work/'pons'/FOLDER/name).exists())
                self.assertEqual(after['archive_counts'][key],0)
                self.assertEqual(after['result'][key],[])
            hot.append(sum(p.stat().st_size for p in next_work.rglob('*') if p.is_file())+
                       sum(p.stat().st_size for p in next_run.rglob('*') if p.is_file()))
            shutil.rmtree(f.lanes);shutil.rmtree(f.run)
            if hour!=167:shutil.rmtree(output)
            next_work.rename(f.lanes);next_run.rename(f.run);previous=body['state_hash']
        self.assertEqual(len(set(proofs)),168)
        self.assertLessEqual(max(hot[4:])-min(hot[4:]),65536)
        f.body=body;f.capsule=output/'capsule'
        claim=f.claim(index=168)
        claim['previous'].update(index=167,workflow_run_id=168,discovery_window=window)
        claim['previous']['positions']={lane:['original-paper-books:position'] if lane in ('pump','pons') else [] for lane in transfer.LANES}
        claim['window']['positions']=deepcopy(claim['previous']['positions'])
        f.target_run.mkdir()
        transfer.prepare_window(claim,worktrees=f.target,run=f.target_run,phase='hourly',seconds=3600,prior_state=f.capsule)
        roots=os.environ.get('MM_TEST_LANE_WORKTREES')
        if roots:
            code='''import json,sys,os
from pathlib import Path
from contextlib import chdir
from unittest.mock import patch
from robinhood_research.pons_selective_cohort import _enrolled_count,_window_observations,_summary_snapshot
from certification.robinhood.pons import recover_cohort
from certification import campaign_state
expected=json.loads(sys.argv[2]);root=Path(sys.argv[3]);runtime=Path(sys.argv[4])
with chdir(root),patch.object(campaign_state,'identity',return_value=expected),patch.dict(os.environ,
 MM_AUTONOMOUS_STATE_RECEIPT=str(runtime/'restored-campaign-state.json'),MM_CERTIFICATION_RUN_ID='original-paper-books'):
 value=recover_cohort(runtime/'shared-robinhood-evidence.candidates.sqlite','frozen')
assert value['rows']==[] and value['autonomous_observation_offset']==0
assert value['qualifiers']==json.loads(sys.argv[1])['qualifiers']
value['rows']=[{'vector':{'all_rejections':['fresh']}}]
assert _enrolled_count(value)==33601
assert _window_observations(value)==1
summary=_summary_snapshot(value)
assert summary['enrolled']==33601 and summary['rejection_counts']=={'frozen_rejection':33600,'fresh':1}
'''
            result=subprocess.run([sys.executable,'-c',code,canonical(after['result']),canonical(f.identity),str(f.target/'pons'),str(f.target_run)],cwd=Path(roots)/'pons',
                env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[2])),capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print('168-hour Pons raw-log handoff:',min(hot[4:]),max(hot[4:]),'hot bytes;',summary['count'],'preserved observations')
    def test_missing_preservation_changed_bytes_and_interrupted_seal_cannot_restore(self):
        f=self.fixture();self.save(f,f.window);output,runtime,artifact=self.staged(f,0)
        source=f.lanes/'pons'/FOLDER/LOGS['rows'];before=source.read_bytes()
        source.write_bytes(before+b'{}\n')
        with self.assertRaisesRegex(ValueError,'not_preserved'):
            transfer.seal(output/'changed',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'changed/campaign-state.json').exists())
        source.write_bytes(before)
        original=Path.unlink
        def cut(path,*args,**kw):
            if path.name==LOGS['rows']:raise SystemExit('seal cut')
            return original(path,*args,**kw)
        with patch.object(Path,'unlink',cut),self.assertRaises(SystemExit):
            transfer.seal(output/'cut',worktrees=f.lanes,run=runtime,window=f.window,
                terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertFalse((output/'cut/campaign-state.json').exists())
        self.assertEqual(source.read_bytes(),before)
        self.assertTrue(verify_snapshot(artifact)['snapshot_complete'])
        body=transfer.seal(output/'good',worktrees=f.lanes,run=runtime,window=f.window,
            terminal=f.terminal,expected_identity=f.identity,preserved_artifact=artifact)
        self.assertIn('pons_observation_handoff',body)
