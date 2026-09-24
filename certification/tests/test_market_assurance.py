import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from certification import decision_conformance as dc
from certification.market_assurance import continuity, lane_report, native_positions, pipeline, ratio
from certification.position_continuation import _meteora_exit_progress

def rule(*,amount,limit):return {'authorized':amount<=limit}

class AssuranceTests(unittest.TestCase):
    def test_worker_identity_survives_secret_sanitized_environment(self):
        from certification.run import lane_environment
        with patch.dict(os.environ,{'GITHUB_SHA':'wrong-parent','MM_CERT_INTEGRATION_SHA':'stale'}),patch('certification.run.git',return_value='exact-checked-out-sha'):
            env=lane_environment('meteora',dict(source_sha='lane',rpc_configuration_variables=[]),Path('/tmp/run'))
        self.assertEqual(env['MM_CERT_INTEGRATION_SHA'],'exact-checked-out-sha')
        self.assertNotIn('GITHUB_SHA',env)

    def test_unknown_denominator_never_becomes_full_coverage(self):
        self.assertIsNone(ratio(5,None));self.assertIsNone(ratio(0,0))
        self.assertEqual(ratio(5,10),.5)

    def test_broad_factory_inventory_is_not_counted_as_observed_target_market(self):
        with tempfile.TemporaryDirectory() as td:
            native=native_positions(td,'ramses')
        row=dict(scan_progress=dict(pools_total=287,state='complete',log_pages_completed=18,
            log_pages_total=18,quiet_activity_deferred=0,identity_preflight_failures=0,
            strategy_identity_candidates=4,quiet_activity_candidates=5,frontier_block=100,frontier_hash='h100'))
        pipe=dict(available=True,stages=dict(discovered=4,screened=4),classes={},
            discovery_frontiers=[dict(block=100,hash='h100')],discovery_frontier_membership_complete=True)
        report=lane_report('ramses',row,native,dict(status='pass'),pipe,dict(verified=True),100)
        self.assertEqual(report['target_market_universe_count'],4)
        self.assertEqual(report['discovered_count'],4)
        self.assertEqual(report['upstream_acquisition']['factory_inventory_count'],287)
        row['scan_progress']['identity_preflight_failures']=1
        self.assertIsNone(lane_report('ramses',row,native,dict(status='pass'),pipe,dict(verified=True),100)['discovery_coverage'])

    def test_multiple_target_scans_never_use_latest_census_for_union(self):
        # Captured smoke shape: four targets then three, two shared. Also cover
        # equal-sized sets, where an invalid denominator need not yield >100%.
        for first,second in ((('a','b','c','d'),('c','d','e')),(('a','b'),('a','b'))):
            with self.subTest(first=first,second=second),tempfile.TemporaryDirectory() as td:
                with sqlite3.connect(Path(td)/'native.pipeline.sqlite') as db:
                    db.execute('CREATE TABLE progress(sequence INTEGER PRIMARY KEY,candidate TEXT,stage TEXT,at REAL,details TEXT,classification TEXT,reason TEXT)')
                    for block,candidates in ((100,first),(200,second)):
                        for candidate in candidates:
                            db.execute('INSERT INTO progress(candidate,stage,at,details) VALUES(?,?,?,?)',
                                (candidate,'discovered',block,json.dumps(dict(frontier=[block,'h'+str(block)]))))
                row=dict(scan_progress=dict(state='complete',log_pages_completed=18,log_pages_total=18,
                    quiet_activity_deferred=0,identity_preflight_failures=0,
                    strategy_identity_candidates=len(second),frontier_block=200,frontier_hash='h200'))
                report=lane_report('ramses',row,native_positions(td,'ramses'),dict(status='pass'),
                    pipeline(td),dict(verified=True),300)
                self.assertEqual(report['discovered_count'],len(set(first)|set(second)))
                self.assertIsNone(report['target_market_universe_count'])
                self.assertIsNone(report['discovery_coverage'])
                self.assertEqual(report['coverage_health'],'coverage_unknown')
                self.assertEqual(report['upstream_acquisition']['known_target_candidates'],len(second))
                self.assertFalse(report['upstream_acquisition']['observation_window_matches_latest_census'])

    def test_unproven_or_different_discovery_frontier_has_unknown_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            native=native_positions(td,'ramses')
        row=dict(scan_progress=dict(state='complete',log_pages_completed=18,log_pages_total=18,
            quiet_activity_deferred=0,identity_preflight_failures=0,
            strategy_identity_candidates=4,frontier_block=200,frontier_hash='h200'))
        for provenance in ({},dict(discovery_frontiers=[dict(block=100,hash='h100')],
                discovery_frontier_membership_complete=True),dict(discovery_frontiers=[dict(block=200,hash='h200')],
                discovery_frontier_membership_complete=False)):
            with self.subTest(provenance=provenance):
                pipe=dict(available=True,stages=dict(discovered=4),classes={},**provenance)
                report=lane_report('ramses',row,native,dict(status='pass'),pipe,dict(verified=True),300)
                self.assertIsNone(report['discovery_coverage'])

    def test_directional_source_events_do_not_become_target_observations(self):
        for lane in ('pump','pons'):
            with self.subTest(lane=lane),tempfile.TemporaryDirectory() as td:
                native=native_positions(td,lane)
                pipe=dict(available=True,stages=dict(discovered=1000,screened=100),classes={})
                report=lane_report(lane,{},native,dict(status='pass'),pipe,dict(verified=True),100)
                self.assertIsNone(report['discovered_count'])
                self.assertIsNone(report['preflight_coverage'])
                self.assertEqual(report['upstream_acquisition']['native_candidate_discovered_count'],1000)
                self.assertFalse(report['upstream_acquisition']['broader_source_rows_are_strategy_observations'])

    def test_lost_open_position_and_eventless_state_changes_fail(self):
        before=dict(positions={'p':dict(status='open',tokens=10)},journals=[dict(id='p',event_hashes=['one'])])
        missing=dict(positions={},journals=[])
        self.assertEqual(continuity(before,missing)['status'],'fail')
        changed=deepcopy(before);changed['positions']['p']['tokens']=9
        self.assertEqual(continuity(before,changed)['status'],'fail')
        changed['journals'][0]['event_hashes'].append('two')
        self.assertEqual(continuity(before,changed)['status'],'pass')
        changed['journals'][0]['event_hashes'][0]='tamper'
        self.assertEqual(continuity(before,changed)['status'],'fail')

    def test_replay_detects_forged_decision_even_with_recomputed_trace_hashes(self):
        import sys
        module=sys.modules[__name__]
        with tempfile.TemporaryDirectory() as td,patch.dict(dc.FUNCTIONS,{'test':{__name__:('rule',)}}),\
                patch.dict(os.environ,{'MM_CERT_INTEGRATION_SHA':'revision'}):
            rec=dc.Recorder(td,'test','policy')
            wrapped=rec.wrap(module,'rule')
            try:wrapped(amount=5,limit=3)
            finally:module.rule=wrapped.__wrapped__
            rec.close()
            self.assertEqual(dc.replay(rec.path,lane='test',policy_hash='policy',runtime_sha='revision')['status'],'pass')
            row=json.loads(rec.path.read_text());row['result']=dc.encode({'authorized':True});row.pop('sha256')
            row['sha256']=dc.digest(row);rec.path.write_text(json.dumps(row)+'\n')
            status=Path(td)/'decision-trace-status.json';s=json.loads(status.read_text());s['sha256']=row['sha256'];status.write_text(json.dumps(s))
            result=dc.replay(rec.path,lane='test',policy_hash='policy',runtime_sha='revision')
            self.assertEqual(result['status'],'fail');self.assertEqual(result['failures'][0]['classification'],'strategy_conformance_failure')
            with self.assertRaisesRegex(ValueError,'identity'):dc.replay(rec.path,lane='test',policy_hash='different',runtime_sha='revision')

    def test_missing_decision_trace_is_unknown_not_zero_failures_pass(self):
        with tempfile.TemporaryDirectory() as td:
            result=dc.replay(Path(td)/'missing',lane='pump',policy_hash='p',runtime_sha='sha')
            self.assertEqual(result['status'],'unknown')

    def test_meteora_restart_retains_native_core_hold_and_consecutive_counters(self):
        root=Path(os.environ.get('MM_TEST_LANE_WORKTREES',str(Path(__file__).resolve().parents[3]/'fresh-lanes')))
        source=root/'meteora/tests/solana_dlmm_independent_v1.py'
        if not source.exists():self.skipTest('prepared exact lane sources unavailable')
        parsed=ast.parse(source.read_text())
        node=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=='_eligible_exit_reasons')
        ns={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        module=SimpleNamespace(_eligible_exit_reasons=ns['_eligible_exit_reasons'])
        policy=json.loads((root/'meteora/SOLANA_DLMM_INDEPENDENT_V1.json').read_text())
        core=policy['prospective_test']['minimum_hold_seconds_for_nonrisk_exit']
        streaks={'volume_collapse':0,'fee_density_collapse':0}
        elapsed,streaks,reasons=_meteora_exit_progress(module,['volume_collapse'],elapsed=core-600,observed=300,streaks=streaks,policy=policy)
        self.assertEqual(reasons,[]);self.assertEqual(streaks['volume_collapse'],1)
        # Serialization is a process/block cut. It must neither reset a counter
        # nor turn that boundary into another strategy confirmation.
        saved=json.loads(json.dumps(dict(elapsed=elapsed,streaks=streaks)))
        elapsed,streaks,reasons=_meteora_exit_progress(module,['volume_collapse'],elapsed=saved['elapsed'],observed=300,streaks=saved['streaks'],policy=policy)
        self.assertEqual(reasons,['volume_collapse']);self.assertEqual(elapsed,core)
        _,streaks,reasons=_meteora_exit_progress(module,[],elapsed=elapsed,observed=300,streaks=streaks,policy=policy)
        self.assertEqual(streaks['volume_collapse'],0);self.assertEqual(reasons,[])
        _,_,reasons=_meteora_exit_progress(module,['range_boundary'],elapsed=0,observed=300,streaks=streaks,policy=policy)
        self.assertEqual(reasons,['range_boundary'])

if __name__=='__main__':unittest.main()
