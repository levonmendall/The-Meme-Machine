import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from certification.causal import reconcile,transition,native_states
from certification.worker import Observer


class CandidateCausalTests(unittest.TestCase):
    def test_capital_occupied_does_not_claim_missing_evidence_complete(self):
        state=dict(status='observed',evidence='evidence_not_required',required=False)
        state=transition(state,'evidence_required',None,None,{})
        state=transition(state,'terminal','paper_capital_occupied','reconstruction_incomplete',{})
        self.assertEqual(state['status'],'capital_occupied')
        self.assertEqual(state['evidence'],'evidence_required')

    def test_warmup_observation_is_not_a_position(self):
        state=dict(status='observed',evidence='not_yet_required',required=False)
        state=transition(state,'warmup_started',None,None,{})
        state=transition(state,'forward_observation',None,None,{})
        state=transition(state,'terminal','pressure_overflow','reconstruction_incomplete',{})
        self.assertEqual(state['status'],'genuine_reconstruction_incomplete')
        state=transition(state,'entry_filled',None,None,{})
        state=transition(state,'forward_observation','body_missing','reconstruction_incomplete',{})
        self.assertEqual(state['status'],'open_continuing')
        self.assertEqual(state['evidence'],'evidence_required')

    def test_lifecycle_truth_survives_later_rejected_candidate_generation(self):
        state=dict(status='observed',evidence='evidence_not_required',required=False)
        state=transition(state,'entry_cancelled','entry_fill_timeout','reconstruction_incomplete',{})
        state=transition(state,'rejected','net_demand','strategy_rejection',{})
        self.assertEqual(state['status'],'entry_cancelled')

    def test_streaming_summary_is_disjoint_preserves_history_and_bounds_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'pipeline.sqlite';out=Path(td)/'rows.jsonl'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE progress(sequence INTEGER PRIMARY KEY,candidate,stage,reason,classification,details)')
            db.executemany('INSERT INTO progress(candidate,stage,reason,classification,details) VALUES(?,?,?,?,?)',[
                ('occupied','terminal','paper_capital_occupied','reconstruction_incomplete','{}'),
                ('missing','evidence_required',None,None,'{}'),
                ('missing','terminal','body_missing','reconstruction_incomplete','{}'),
                ('open','entry_filled',None,None,'{}'),
                ('open:slot','trigger_terminal','done',None,'{}')])
            db.commit();before=path.read_bytes()
            summary=reconcile(path,rows_path=out,max_rows=2)
            self.assertEqual(summary['candidates'],3)
            self.assertEqual(sum(summary['terminal_counts'].values()),3)
            self.assertEqual(summary['terminal_counts']['capital_occupied'],1)
            self.assertEqual(summary['terminal_counts']['genuine_reconstruction_incomplete'],1)
            self.assertEqual(summary['candidate_rows_omitted'],1)
            self.assertEqual(len(out.read_text().splitlines()),2)
            self.assertEqual(path.read_bytes(),before)
            db.close()

    def test_native_compact_pons_lifecycle_reconciles_without_qualifier_array(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'pipeline.sqlite';db=sqlite3.connect(path)
            db.execute('CREATE TABLE progress(candidate,stage)')
            tx='0x'+'a'*64
            db.execute('INSERT INTO progress VALUES(?,?)',(tx+':0xd','qualified'))
            db.commit();db.close()
            report=dict(lifecycles=[dict(lifecycle_id='pons-selective:uuid:token:'+tx,
                status='entry_failed',index=0)])
            self.assertEqual(native_states('pons',report,path),{tx+':0xd':'entry_cancelled'})
            report['lifecycles'][0]['lifecycle_id']='unrelated'
            self.assertEqual(native_states('pons',report,path),{})

    def test_transport_context_is_thread_local_and_clears_on_terminal(self):
        class Pipeline:
            def record(self,*args,**kwargs):return 'recorded'
        module=SimpleNamespace(Pipeline=Pipeline)
        observer=object.__new__(Observer);observer.lane='pump';observer.context=threading.local()
        from collections import Counter
        observer.lock=threading.RLock();observer.solana_usage=Counter()
        with patch('certification.worker.importlib.import_module',return_value=module):
            observer.install_candidate_context()
        p=Pipeline();p.record('mint','evidence_requested',decision_at=123)
        self.assertEqual(observer.context.candidate,'mint')
        self.assertEqual(observer.context.obligation,'123')
        values=[]
        t=threading.Thread(target=lambda:values.append(getattr(observer.context,'candidate',None)))
        t.start();t.join();self.assertEqual(values,[None])
        p.record('mint','terminal','missing')
        self.assertIsNone(observer.context.candidate)
        p.record('mint','evidence_complete')
        p.record('mint','terminal','missing','reconstruction_incomplete')
        self.assertEqual(observer.solana_usage['complete_decisions'],1)
        self.assertEqual(observer.solana_usage['incomplete_decision_events'],1)


class RetainedDecisionsTests(unittest.TestCase):
    def test_five_record_digests_and_economic_replay_in_prepared_lanes(self):
        root=Path(__file__).resolve().parents[2]
        work=os.environ.get('MM_TEST_LANE_WORKTREES')
        if not work:self.skipTest('Prepared lanes required; exercised by exact-SHA non-market certification')
        for lane in ('pump','pons','ramses'):
            with self.subTest(lane=lane):
                env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(Path(work)/lane),str(root)]))
                run=subprocess.run([sys.executable,'-m','certification.retained_v9_replay',lane],
                    cwd=Path(work)/lane,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertTrue(json.loads(run.stdout)['passed'])
