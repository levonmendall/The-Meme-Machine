import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from certification.journal import Journal
from certification.report import LANES,dashboard,evaluate
from certification.run import finish_lanes,launch

class ShutdownTests(unittest.TestCase):
    def test_live_native_cursor_and_frontier_shapes_render_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for state in (67632563,0,None,{'polls':4,'advances':1}):
                row={'finality_state':state,'policy_hash':'a'*64}
                result={'lanes':{'pons':row}}
                before=json.dumps(result,sort_keys=True)
                path=Path(tmp)/'status.html';dashboard(result,path)
                self.assertEqual(json.dumps(result,sort_keys=True),before)
                if isinstance(state,int):self.assertIn('<td>'+str(state)+'</td>',path.read_text())
                else:self.assertIn('frontier polls',path.read_text())

    def test_damaged_archive_does_not_leave_other_children_or_skip_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);processes={};files={};rows={};times={}
            for i,lane in enumerate(LANES):
                process=MagicMock(pid=200+i,returncode=-2);process.poll.return_value=None
                processes[lane]=(process,0);files[lane]=MagicMock()
                rows[lane]={'policy_hash':'a'*64,'gates':{},'accounting_reconciled':True}
                folder=root/lane;folder.mkdir();j=Journal(folder/'telemetry.sqlite')
                j.append(lane,'terminal','process_terminal',dict(status='returned',policy_hash='a'*64));j.close()
                (folder/'rpc-evidence.jsonl.gz').write_bytes(gzip.compress(b'')[:-4] if lane=='pump' else gzip.compress(b''))
            journal=Journal(root/'supervisor.sqlite')
            from certification.run import audit_telemetry
            def audited(*args):
                self.assertTrue(all(p.wait.called for p,_ in processes.values()))
                return audit_telemetry(*args)
            with patch('certification.run.os.killpg'),patch('certification.run.audit_telemetry',side_effect=audited) as audit:
                self.assertTrue(finish_lanes(processes,files,rows,times,journal,root))
                self.assertEqual(audit.call_count,4)
            self.assertEqual(rows['pump']['telemetry_audit']['error_type'],'EOFError')
            self.assertFalse(rows['pump']['gates']['telemetry_complete'])
            for lane in LANES:
                self.assertTrue(rows[lane]['unexpected_exit']);self.assertIn(lane,times)
                self.assertFalse(rows[lane]['accounting_reconciled'])
                self.assertEqual(rows[lane]['shutdown_positions'],'explicitly_unresolved')
            self.assertTrue(rows['ramses']['gates']['telemetry_complete'])
            self.assertEqual(len(list(journal.records())),4);journal.close()

    def test_supervisor_exception_persists_four_lane_failed_terminal_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);gate=root/'gate.json';out=root/'run'
            spec={'lanes':{lane:dict(policy_hash='a'*64,strategy_version='frozen',source_sha='head',file_hashes={},rpc_configuration_variables=[]) for lane in LANES}}
            gate.write_text(json.dumps(dict(passed=True,source_manifest_hash='hash',integration_sha='head',implementation_hash='impl',source_diff_hashes={})))
            children=[]
            def spawn(*a,**kw):
                p=MagicMock(pid=100+len(children),returncode=-2);p.poll.return_value=None;children.append(p);return p
            with patch('certification.run.manifest',return_value=spec),patch('certification.run.digest',return_value='hash'),patch('certification.run.git',return_value='head'),patch('certification.run.implementation_hash',return_value='impl'),patch('certification.run.source_integrity',return_value={}),patch('certification.run.subprocess.Popen',side_effect=spawn),patch('certification.run.os.killpg'),patch('certification.run.dashboard',side_effect=[AttributeError('injected_renderer_failure'),None]),patch('certification.run.audit_telemetry',side_effect=EOFError('truncated')),patch('certification.analysis.report'),patch.dict(os.environ,{'MM_SOLANA_READ_RPC_URL':'read-only','MM_ROBINHOOD_READ_RPC_URL':'read-only'}):
                with self.assertRaises(AttributeError):launch(root,out,600,'smoke',gate)
            terminal=json.loads((out/'result.json').read_text())
            self.assertEqual(terminal['status'],'FAILED');self.assertEqual(terminal['certification']['status'],'FAIL')
            self.assertEqual(terminal['supervisor_error']['error_type'],'AttributeError')
            self.assertEqual(set(terminal['lanes']),set(LANES))
            self.assertTrue(all(p.wait.called for p in children))
            self.assertTrue(all(r['telemetry_audit']['error_type']=='EOFError' for r in terminal['lanes'].values()))
            self.assertTrue(all(r['health']=='terminated' for r in terminal['lanes'].values()))
            self.assertEqual(evaluate(dict(status='FAILED',lanes={}))['status'],'FAIL')
