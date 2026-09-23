import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from certification.journal import Accounting,Journal,canonical,digest
from certification.governor import Governor
from certification.report import evaluate,REQUIRED,LANES,summarize
from certification.run import lane_environment


def request_slot(path,output,lane):
    g=Governor(path);g.acquire('test',lane)
    with open(output,'a') as f:f.write(str(time.monotonic())+'\n')

class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.book=Accounting('run','pump','SOL',1000,'a'*64)
        self.id=self.book.lifecycle_id('candidate')

    def event(self,action,at,**kw):
        return dict(lane='pump',asset='SOL',policy_hash='a'*64,lifecycle_id=self.id,
                    evidence_hash='b'*64,action=action,at_ns=at,**kw)

    def test_partial_exit_recycled_capital_and_exact_replay(self):
        b=self.book
        events=[self.event('reserve',0,amount=500),self.event('fill',1_000_000_000,cost=400,tokens=10),
                self.event('exit',11_000_000_000,tokens=4,basis=160,gross_proceeds=200,costs=dict(network=2,protocol=3,unwind=1)),
                self.event('exit',21_000_000_000,tokens=6,basis=240,gross_proceeds=270,costs=dict(network=2,protocol=3,unwind=1))]
        for e in events:b.apply(e)
        r=b.reconcile();self.assertTrue(r['balanced']);self.assertEqual(r['cash'],1058)
        self.assertEqual(r['capital_unit_nanoseconds'],6_900_000_000_000)
        self.assertEqual(r['settled'],1)
        replay=Accounting('run','pump','SOL',1000,'a'*64)
        for e in json.loads(canonical(events)):replay.apply(e)
        self.assertEqual(r,replay.reconcile())
        self.id=b.lifecycle_id('next-candidate');b.apply(self.event('reserve',22_000_000_000,amount=500))
        self.assertEqual(b.reconcile()['genesis'],1000)

    def test_rejects_double_settlement_and_missing_cost_without_mutation(self):
        b=self.book;b.apply(self.event('reserve',0,amount=100));b.apply(self.event('fill',1,cost=100,tokens=1))
        before=b.reconcile()
        with self.assertRaises(ValueError):b.apply(self.event('exit',2,tokens=1,basis=100,gross_proceeds=110,costs=dict(network=1)))
        self.assertEqual(before,b.reconcile())
        e=self.event('exit',2,tokens=1,basis=100,gross_proceeds=110,costs=dict(network=1,protocol=0,unwind=0));b.apply(e)
        with self.assertRaises(ValueError):b.apply(e)

    def test_foreign_policy_and_overallocation_fail_closed(self):
        e=self.event('reserve',0,amount=100);e['lane']='pons'
        with self.assertRaises(ValueError):self.book.apply(e)
        with self.assertRaises(ValueError):self.book.apply(self.event('reserve',0,amount=1001))
        with self.assertRaises(ValueError):self.book.apply(self.event('reserve',0,amount=1.0))
        self.assertEqual(self.book.cash,1000)
        other=Accounting('run','pons','ETH',1000,'a'*64)
        self.assertNotEqual(other.lifecycle_id('candidate'),self.id)

class JournalTests(unittest.TestCase):
    def test_append_duplicate_conflict_and_sql_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'journal.sqlite')
            h=j.append('pump','event','mark',dict(value=1),at_ns=1)
            self.assertEqual(h,j.append('pump','event','mark',dict(value=1),at_ns=2))
            with self.assertRaises(ValueError):j.append('pump','event','mark',dict(value=2))
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute('DELETE FROM events')
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute("UPDATE events SET kind='changed'")
            self.assertEqual(len(list(j.records())),1);j.close()

class CertificationTests(unittest.TestCase):
    def test_hourly_scope_does_not_satisfy_four_hour_certification(self):
        result=self.complete();result.update(phase='hourly',continuous_overlap_seconds=3600)
        for row in result['lanes'].values():row['continuous_uptime_seconds']=3600
        verdict=evaluate(result)
        self.assertEqual(verdict['status'],'PASS')
        self.assertEqual(verdict['scope'],'one_hour_paper_campaign')
        self.assertEqual(verdict['required_observation_seconds'],3600)
        result['phase']='sustained'
        self.assertEqual(evaluate(result)['status'],'INCOMPLETE')
        result['phase']='hourly';result['continuous_overlap_seconds']=3599
        self.assertEqual(evaluate(result)['status'],'INCOMPLETE')

    def test_hourly_retains_natural_and_accounting_requirements(self):
        result=self.complete();result['phase']='hourly'
        result['lanes']['pump']['natural_settled']=0
        result['lanes']['pump']['forced_settled']=3
        self.assertEqual(evaluate(result)['status'],'INCOMPLETE')
        result['lanes']['pons']['gates']['accounting_reconciled']=False
        self.assertEqual(evaluate(result)['status'],'FAIL')

    def test_launch_duration_rejected_before_any_work(self):
        from certification.run import launch
        for phase,seconds,message in [('hourly',3599,'one_hour_window_required'),
                                      ('hourly',14400,'one_hour_window_required'),
                                      ('sustained',3600,'four_hour_minimum')]:
            with self.assertRaisesRegex(ValueError,message):
                launch(None,None,seconds,phase,None)

    def complete(self):
        return dict(elapsed_seconds=14400,continuous_overlap_seconds=14400,lanes={lane:dict(continuous_uptime_seconds=14400,
                    natural_settled=1,open_positions=0,process_restarts=0,gates={g:True for g in REQUIRED}) for lane in LANES})

    def test_forced_zero_missing_unknown_and_restart_cannot_pass(self):
        good=self.complete();self.assertEqual(evaluate(good)['status'],'PASS')
        for name in ('forced','missing','restart','short','unsettled','unknown_exposure','short_overlap'):
            x=json.loads(json.dumps(good));r=x['lanes']['pons']
            if name=='forced':r.update(natural_settled=0,forced_settled=3)
            elif name=='missing':del r['gates']['accounting_reconciled']
            elif name=='restart':r['process_restarts']=1
            elif name=='short':r['continuous_uptime_seconds']=14399
            elif name=='unknown_exposure':r['open_positions']=None
            elif name=='short_overlap':x['continuous_overlap_seconds']=14399
            else:r['open_positions']=1
            self.assertNotEqual(evaluate(x)['status'],'PASS',name)

    def test_virtual_meteora_result_is_not_ledger_settlement(self):
        x=summarize('meteora',dict(complete_lifecycle_count=5,qualified_lifecycles=[dict(complete=True)]))
        self.assertEqual(x['natural_settled'],0);self.assertIsNone(x['accounting_reconciled'])

    def test_pons_cancel_not_natural_trade(self):
        x=summarize('pons',dict(lifecycles=[dict(final_position=dict(status='settled',entry_tokens=0))]))
        self.assertEqual(x['natural_settled'],0)

    def test_pons_writeoff_never_counts_as_natural_sale_after_compaction(self):
        position=dict(status='settled',entry_tokens=10,realized=-100,
            reason='liquidity_writeoff:impossible_full_position_exit')
        for life in (dict(final_position=position,settlement_kind='liquidity_writeoff'),
                     dict(final_position=position)):
            with self.subTest(explicit_kind='settlement_kind' in life):
                report=summarize('pons',dict(lifecycles=[life,dict(
                    final_position=dict(status='settled',entry_tokens=10,reason='momentum_failure'))]))
                self.assertEqual(report['natural_settled'],1)
                self.assertEqual(report['funnel']['liquidity_writeoffs'],1)

    def test_pump_cancelled_qualification_is_visible_but_not_a_trade(self):
        report=dict(qualifiers=[dict(entry_status='cancelled',entry_limitation='entry_fill_timeout')],
            full_evidence_candidates=[{}],settled=[],attempts=[],open_positions=[],pending_entries=[])
        result=summarize('pump',report)
        self.assertEqual(result['funnel']['qualified'],1)
        self.assertEqual(result['funnel']['entry_cancelled'],1)
        self.assertEqual(result['funnel']['entry_filled'],0)
        self.assertEqual(result['natural_settled'],0)
        self.assertEqual(result['terminal_reasons']['entry_cancelled:entry_fill_timeout'],1)

    def test_ramses_natural_uses_native_ledger_fields_and_terminal_equality(self):
        report=dict(policy_hash='frozen',natural_qualifier_found=True,connected_lifecycle=dict(
            ledger_final=dict(status='settled',policy_hash='frozen'),ledger_reconciliation=dict(open_positions=0),
            segments=[dict(terminal_equality=True)]))
        self.assertEqual(summarize('ramses',report)['natural_settled'],1)
        report['connected_lifecycle']['ledger_final']['forced_machinery_test']=True
        self.assertEqual(summarize('ramses',report)['natural_settled'],0)
        report['connected_lifecycle']['ledger_final'].pop('forced_machinery_test')
        report['connected_lifecycle']['segments'][0]['terminal_equality']=False
        self.assertEqual(summarize('ramses',report)['natural_settled'],0)

    def test_campaign_counts_distinct_ramses_settlements_without_summing_quote_cash(self):
        lives=[dict(lifecycle_id=str(i),ledger_final=dict(id=str(i),status='settled',policy_hash='frozen'),
            ledger_reconciliation=dict(open_positions=0),segments=[dict(terminal_equality=True)]) for i in range(3)]
        report=dict(policy_hash='frozen',continuous_campaign=True,natural_qualifier_found=True,
            natural_lifecycles=lives+[lives[0]],campaign_accounting=dict(conservation=True,open_positions=0,
                by_quote_asset=dict(a=dict(available=10),b=dict(available=20)),unlike_quote_units_summed=False))
        result=summarize('ramses',report)
        self.assertEqual(result['natural_settled'],3)
        self.assertEqual(result['open_positions'],0)
        self.assertFalse(result['native_accounting']['unlike_quote_units_summed'])

    def test_terminal_native_report_survives_other_lanes_draining(self):
        from certification.run import observe_checkpoint_report
        row=dict(exit_code=0,natural_settled=1,forced_settled=0,open_positions=0,
            accounting_reconciled=True,funnel=dict(scans=4))
        before=json.loads(json.dumps(row))
        stale=dict(report=dict(frontier_gate={'progress':'unchanged'}))
        observe_checkpoint_report('ramses',row,stale,0)
        self.assertEqual(row,before)

    def test_environment_does_not_leak_other_lane_secrets(self):
        from unittest.mock import patch
        env=dict(MM_SOLANA_READ_RPC_URL='solana',MM_ROBINHOOD_READ_RPC_URL='rh',GITHUB_TOKEN='secret',PRIVATE_KEY='secret')
        with patch.dict(os.environ,env):
            selected=lane_environment('meteora',dict(source_sha='a',rpc_configuration_variables=['MM_SOLANA_READ_RPC_URL']),Path('/tmp/run'))
        self.assertNotIn('MM_ROBINHOOD_READ_RPC_URL',selected)
        self.assertNotIn('GITHUB_TOKEN',selected);self.assertNotIn('PRIVATE_KEY',selected)

    def test_global_governor_covers_independent_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'governor.sqlite');output=str(Path(tmp)/'times');Governor(path)
            ctx=multiprocessing.get_context("spawn")
            children=[ctx.Process(target=request_slot,args=(path,output,lane)) for lane in LANES]
            for p in children:p.start()
            for p in children:p.join(10);self.assertEqual(p.exitcode,0)
            times=sorted(float(s) for s in Path(output).read_text().splitlines())
            self.assertEqual(len(times),4)
            # Child output is written after acquire() returns and can be scheduler-delayed;
            # keep enough tolerance that process preemption cannot masquerade as a rate
            # increase. Four grants still must span well beyond two ungoverned 0.5s slots.
            self.assertGreaterEqual(times[-1]-times[0],1.25)
            status=Governor(path).status()
            self.assertEqual(status['queues'],[])
            self.assertEqual(status['providers'][0]['grants'],4)

class SolanaMethodPressureTests(unittest.TestCase):
    def test_getprogramaccounts_method_cooldown_fails_before_transport_admission(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'governor.sqlite';g=Governor(path)
            now=time.monotonic()
            db=sqlite3.connect(path)
            db.execute('INSERT OR IGNORE INTO pressure VALUES(?,0,0,0,0)',('solana',))
            db.execute('INSERT OR REPLACE INTO method_pressure VALUES(?,?,?,?,?,?)',
                       ('solana','getProgramAccounts',now+30,1,1,0))
            db.commit();db.close()
            with self.assertRaisesRegex(TimeoutError,'method_cooldown'):
                g.acquire('solana','pump',methods=['getProgramAccounts'],
                          deadline_seconds=1)
            status=g.status()
            row=next(x for x in status['method_pressure']
                     if x['method']=='getProgramAccounts')
            self.assertEqual(row['rate_errors'],1)
            self.assertGreater(row['cooldown_remaining_seconds'],20)

    def test_rate_limit_records_exact_method_pressure(self):
        with tempfile.TemporaryDirectory() as td:
            g=Governor(Path(td)/'governor.sqlite')
            g.rate_limited('solana',['getProgramAccounts'])
            status=g.status()
            row=next(x for x in status['method_pressure']
                     if x['method']=='getProgramAccounts')
            self.assertEqual(row['rate_errors'],1)
            self.assertEqual(row['rate_streak'],1)
            self.assertGreaterEqual(row['cooldown_remaining_seconds'],29)
    def test_signature_rate_limit_uses_longer_method_backoff(self):
        with tempfile.TemporaryDirectory() as td:
            g=Governor(Path(td)/'governor.sqlite')
            before=time.monotonic()
            g.rate_limited('solana',['getSignaturesForAddress'])
            row=next(x for x in g.status()['method_pressure']
                     if x['method']=='getSignaturesForAddress')
            self.assertEqual(row['rate_errors'],1)
            self.assertGreaterEqual(row['cooldown_remaining_seconds'],14)



class IntegrationRegressionTests(unittest.TestCase):
    def test_expired_ticket_and_capacity_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'gate.sqlite';g=Governor(path)
            db=sqlite3.connect(path)
            db.execute('INSERT INTO queue(id,provider,lane,priority,created) VALUES(?,?,?,?,?)',('stale','solana','dead',0,time.monotonic()-31))
            db.commit()
            g.acquire('solana','pump')
            self.assertEqual(g.status()['queues'],[])
            now=time.monotonic()
            db.executemany('INSERT INTO queue(id,provider,lane,priority,created) VALUES(?,?,?,?,?)',[(str(i),'solana','research',50,now) for i in range(256)])
            db.commit()
            with self.assertRaisesRegex(TimeoutError,'capacity'):g.acquire('solana','pump')
            db.close()

    def test_terminal_status_keeps_report_and_rpc_error_code(self):
        import gzip
        from unittest.mock import patch
        from certification.worker import Observer
        class Rpc:
            def transport(self,request):return {'error':{'code':429}}
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'MM_CERT_GOVERNOR_DB':str(Path(td)/'governor.sqlite')}):
                o=Observer(Path(td)/'lane','pump','policy')
            o.checkpoint({'accounting':{'cash':100}},'checkpoint')
            o.wrap_transport(Rpc,'transport',solana=True)
            rpc=Rpc();rpc.transport({'method':'getTransaction','params':['signature']})
            o.status('returned')
            status=json.loads((Path(td)/'lane/status.json').read_text())
            self.assertEqual(status['report']['accounting']['cash'],100)
            self.assertIsNotNone(status['terminal_monotonic'])
            o.raw.close();o.journal.close()
            raw=json.loads(gzip.open(Path(td)/'lane/rpc-evidence.jsonl.gz','rt').readline())
            self.assertEqual(raw['http_status'],200)
            self.assertEqual(raw['json_rpc_error_codes'],[429])
            self.assertTrue(raw['transport_attempted'])
            activity=json.loads((Path(td)/'lane/activity.json').read_text())
            self.assertFalse(activity['evidence_qualification_inferred'])
            self.assertEqual(activity['provider_requests'],1)
            self.assertEqual(activity['pid'],os.getpid())
            self.assertEqual(activity['lane'],'pump')
            self.assertEqual(
                status['provider_rpc_error_codes']['getTransaction:429'],1)
            self.assertEqual(status['errors']['getTransaction:rpc_429'],1)

class EvidenceDenominatorTests(unittest.TestCase):
    def test_missing_or_late_pons_evidence_is_not_economic_discrimination_sample(self):
        from certification.analysis import partition_pons
        def row(complete,age):return dict(vector=dict(complete=complete,decision_state_age_seconds=age,
            thresholds=dict(max_state_age_seconds=5),all_rejections=['curve_progress']))
        good,censored=partition_pons([row(True,4.9),row(True,5.1),row(False,2),row(True,None)])
        self.assertEqual(len(good),1);self.assertEqual(len(censored),3)
        self.assertEqual(good[0]['decision_state_age_seconds'],4.9)

class EvidenceWorkTests(unittest.TestCase):
    def test_stage_timing_preserves_return_and_exception_without_qualification_claim(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from certification.worker import Observer
        value={'qualified':False};error=ValueError('unavailable')
        def work(fail=False):
            if fail:raise error
            return value
        module=SimpleNamespace(work=work)
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'MM_CERT_GOVERNOR_DB':str(Path(td)/'provider.sqlite')}):
                observer=Observer(Path(td)/'lane','pons','frozen')
            observer.observe_work(module,'work','candidate')
            self.assertIs(module.work(),value)
            with self.assertRaises(ValueError) as caught:module.work(True)
            self.assertIs(caught.exception,error)
            events=list(observer.journal.records())
            self.assertEqual([x['body']['outcome'] for x in events],['returned','exception'])
            self.assertTrue(all(x['body']['qualification_inferred'] is False for x in events))
            observer.raw.close();observer.journal.close()

class ObservationRetentionTests(unittest.TestCase):
    def test_compact_progress_retains_each_candidate_once(self):
        from unittest.mock import patch
        from certification.worker import Observer
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ,{'MM_CERT_GOVERNOR_DB':str(Path(td)/'provider.sqlite')}):
                observer=Observer(Path(td)/'lane','pons','frozen-policy')
            result=dict(rows=[dict(vector={'complete':True},raw_evidence='x'*10000)],qualifiers=[],lifecycles=[])
            observer.pons_progress(result,dict(summary=dict(enrolled=1,qualified=0)),'candidate')
            observer.pons_progress(result,dict(summary=dict(enrolled=1,qualified=0)),'idle_progress')
            result['rows'].append(dict(vector={'complete':False},reason='evidence_deadline'))
            observer.pons_progress(result,dict(summary=dict(enrolled=2,qualified=0)),'candidate')
            events=list(observer.journal.records());candidates=[x for x in events if x['kind']=='candidate_observation']
            self.assertEqual([x['body']['observation'] for x in candidates],result['rows'])
            checkpoints=[x for x in events if x['kind']=='checkpoint']
            self.assertNotIn('raw_evidence',json.dumps(checkpoints))
            self.assertEqual(summarize('pons',checkpoints[-1]['body']['report'])['funnel']['evaluated'],2)
            observer.raw.close();observer.journal.close()

class ContentionPreflightTests(unittest.TestCase):
    def test_mixed_ci_live_job_is_not_hidden_by_workflow_name(self):
        from certification.guard import active_market_job
        self.assertTrue(active_market_job('paper-milestone',dict(name='live-diagnostic',status='in_progress')))
        self.assertFalse(active_market_job('paper-milestone',dict(name='test',status='in_progress')))
        self.assertFalse(active_market_job('paper-milestone',dict(name='live-diagnostic',status='completed')))
        self.assertTrue(active_market_job('unrecognized',dict(name='unknown-market-task',status='in_progress')))
        self.assertTrue(active_market_job('robinhood-ramses-extended',dict(name='probe',status='in_progress')))
        spec={'lanes':{'pump':{'source_sha':'pump-pinned'}}}
        run={'head_sha':'pump-pinned'}
        self.assertFalse(active_market_job(
            'paper-milestone',dict(name='live-diagnostic',status='in_progress'),run,spec))
        self.assertTrue(active_market_job(
            'paper-milestone',dict(name='live-diagnostic',status='in_progress'),
            {'head_sha':'different'},spec))

class TerminalReportRegressionTests(unittest.TestCase):
    def test_pons_final_report_keeps_native_12mb_contract(self):
        from certification.worker import persist_pons_terminal
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'terminal.json';result=dict(evidence='a'*5_000_000)
            persist_pons_terminal(path,result)
            self.assertEqual(json.loads(path.read_bytes()),result)
            with self.assertRaisesRegex(ValueError,'cohort_report_capacity'):
                persist_pons_terminal(path,dict(evidence='b'*12_000_000))
            self.assertEqual(json.loads(path.read_bytes()),result)

class PressureViewTests(unittest.TestCase):
    def test_incremental_observation_never_rebooks_or_mutates_admission(self):
        from certification.pressure import PressureView
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'shared.sqlite';view=PressureView(path)
            self.assertEqual(view.snapshot()['state'],'not_initialized')
            db=sqlite3.connect(path)
            db.executescript('CREATE TABLE transports(seq INTEGER PRIMARY KEY,body TEXT); CREATE TABLE limits(endpoint TEXT,cooldown REAL,interval REAL); CREATE TABLE queue(endpoint TEXT,created REAL);')
            db.execute('INSERT INTO limits VALUES(?,?,?)',('opaque',time.monotonic()+8,.5))
            def append(lane):
                row=dict(lane=lane,endpoint_fingerprint='opaque',methods=['eth_call'],http_status=429,rpc_error_code=None,retry_count=1,queue_depth=2,wait_seconds=.2,latency_seconds=.1)
                db.execute('INSERT INTO transports(body) VALUES(?)',(json.dumps(row),));db.commit()
            append('pons')
            self.assertEqual(view.snapshot()['lanes']['pons']['requests'],1)
            self.assertEqual(view.snapshot()['lanes']['pons']['requests'],1)
            append('ramses');r=view.snapshot()
            self.assertEqual(r['endpoints'][0]['requests'],2)
            self.assertEqual(r['lanes']['ramses']['requests'],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM transports').fetchone()[0],2)
            db.close()


class OverlayCanonicalizationTests(unittest.TestCase):
    def test_blob_ids_are_metadata_but_patch_content_remains_authoritative(self):
        from certification.run import canonical_patch_bytes
        a=b"diff --git a/x.py b/x.py\nindex 1111111..2222222 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
        b=b"diff --git a/x.py b/x.py\nindex aaaaaaa..bbbbbbb 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
        changed=b"diff --git a/x.py b/x.py\nindex aaaaaaa..ccccccc 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+different\n"
        self.assertEqual(canonical_patch_bytes(a),canonical_patch_bytes(b))
        self.assertNotEqual(canonical_patch_bytes(a),canonical_patch_bytes(changed))

if __name__=='__main__':unittest.main()
