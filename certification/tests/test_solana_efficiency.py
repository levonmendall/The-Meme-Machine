import hashlib,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from certification.governor import Governor
from certification.report import provider_efficiency
from certification.cu import estimate

class SolanaEfficiencyTests(unittest.TestCase):
    def test_physical_governor_foreground_fairness_and_position_priority(self):
        with tempfile.TemporaryDirectory() as td:
            g=Governor(Path(td)/'g.db');db=sqlite3.connect(g.path)
            def add(i,l,p,c,d):db.execute('INSERT INTO queue VALUES(?,?,?,?,?,?)',(i,'solana',l,p,c,d))
            add('prefetch','pump',90,0,101);add('pump','pump',20,99,102);add('dlmm','meteora',30,99,101)
            self.assertEqual(g._head(db,'solana',100)[0],'dlmm') # common EDF urgency
            db.execute("DELETE FROM queue WHERE id='dlmm'");add('dlmm','meteora',30,96,120)
            self.assertEqual(g._head(db,'solana',100)[0],'dlmm') # bounded wait
            add('exit','pump',0,100,130)
            self.assertEqual(g._head(db,'solana',100)[0],'exit')
            db.execute("DELETE FROM queue WHERE id IN ('exit','pump')");add('pump','pump',20,95,130)
            self.assertEqual(g._head(db,'solana',100)[0],'pump') # symmetric guarantee
            db.close()
    def test_member_billing_not_transport_discount_and_zero_vector_unknown(self):
        r=dict(lanes={'pump':dict(provider_requests=1,method_counts={'getTransaction':8},funnel={'evidence_complete':2}),
                      'meteora':dict(provider_requests=2,method_counts={'getTransaction':8},funnel={'complete_economic_vectors':0})})
        provider_efficiency(r);a=r['lanes']['pump']['rpc_efficiency'];b=r['lanes']['meteora']['rpc_efficiency']
        self.assertEqual(a['logical_rpc_members'],8);self.assertEqual(a['physical_per_complete'],.5)
        self.assertEqual(a['logical_per_complete'],4);self.assertIsNone(b['physical_per_complete'])
        self.assertEqual(a['estimated_cu'],b['estimated_cu'])
    def test_execution_source_files_remain_explicitly_hash_pinned(self):
        m=json.loads((Path(__file__).parents[1]/'sources.json').read_text())
        for lane,key in [('pump','meme_machine/pump_acceleration_strategy.py'),('meteora','SOLANA_DLMM_INDEPENDENT_V1.json'),('pons','robinhood_research/pons_selective_continuation.py'),('ramses','robinhood_research/ramses_strategy.py')]:
            row=m['lanes'][lane]
            self.assertRegex(row['source_sha'],r'^[0-9a-f]{40}
    def test_both_phases_publish_capabilities_next_to_exact_gate(self):
        text=(Path(__file__).parents[2]/'.github/workflows/four-lane-certification.yml').read_text()
        self.assertEqual(text.count('--output certification-gates/rpc-capabilities.json'),2)
        self.assertNotIn('--output certification-hourly-gates/rpc-capabilities.json',text)
    def test_contention_wait_never_retries_source_drift_or_launches_work(self):
        from unittest.mock import patch
        from certification import guard
        with tempfile.TemporaryDirectory() as td,patch('sys.argv',['guard','--wait-seconds','3600']),patch.object(guard,'Path',lambda p:Path(td)/p),patch.object(guard,'check',return_value=dict(passed=False,lane_heads_changed=['pump'],conflicting_market_runs=[])) as check,patch.object(guard.time,'sleep') as sleep:
            with self.assertRaises(SystemExit):guard.main()
            self.assertEqual(check.call_count,1);sleep.assert_not_called()
)
            self.assertRegex(row['policy_hash'],r'^[0-9a-f]{64}
    def test_both_phases_publish_capabilities_next_to_exact_gate(self):
        text=(Path(__file__).parents[2]/'.github/workflows/four-lane-certification.yml').read_text()
        self.assertEqual(text.count('--output certification-gates/rpc-capabilities.json'),2)
        self.assertNotIn('--output certification-hourly-gates/rpc-capabilities.json',text)
    def test_contention_wait_never_retries_source_drift_or_launches_work(self):
        from unittest.mock import patch
        from certification import guard
        with tempfile.TemporaryDirectory() as td,patch('sys.argv',['guard','--wait-seconds','3600']),patch.object(guard,'Path',lambda p:Path(td)/p),patch.object(guard,'check',return_value=dict(passed=False,lane_heads_changed=['pump'],conflicting_market_runs=[])) as check,patch.object(guard.time,'sleep') as sleep:
            with self.assertRaises(SystemExit):guard.main()
            self.assertEqual(check.call_count,1);sleep.assert_not_called()
)
            self.assertEqual(len(row['file_hashes'][key]),64)
            self.assertIsInstance(row['strategy_version'],str)
            self.assertTrue(row['strategy_version'].strip())
    def test_both_phases_publish_capabilities_next_to_exact_gate(self):
        text=(Path(__file__).parents[2]/'.github/workflows/four-lane-certification.yml').read_text()
        self.assertEqual(text.count('--output certification-gates/rpc-capabilities.json'),2)
        self.assertNotIn('--output certification-hourly-gates/rpc-capabilities.json',text)
    def test_contention_wait_never_retries_source_drift_or_launches_work(self):
        from unittest.mock import patch
        from certification import guard
        with tempfile.TemporaryDirectory() as td,patch('sys.argv',['guard','--wait-seconds','3600']),patch.object(guard,'Path',lambda p:Path(td)/p),patch.object(guard,'check',return_value=dict(passed=False,lane_heads_changed=['pump'],conflicting_market_runs=[])) as check,patch.object(guard.time,'sleep') as sleep:
            with self.assertRaises(SystemExit):guard.main()
            self.assertEqual(check.call_count,1);sleep.assert_not_called()
