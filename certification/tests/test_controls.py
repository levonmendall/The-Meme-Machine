import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from certification.controls import audit_telemetry,record_unfinished_broker_jobs,smoke_engineering,sustained_readiness
from certification.journal import Journal,digest
from certification.report import LANES,evaluate


class ControlsTests(unittest.TestCase):
    def smoke(self):
        return dict(phase='smoke',status='FINISHED',continuous_overlap_seconds=600,
            source_manifest_hash='manifest',integration_sha='commit',implementation_hash='code',
            shared_provider={n:dict(queues=[]) for n in ('solana','robinhood')},
            lanes={lane:dict(exit_code=0,unexpected_exit=False,process_restarts=0,
                open_positions=0,accounting_reconciled=True,provider_requests=1,
                gates={g:True for g in ('telemetry_complete','policy_unchanged','paper_only','responsive','state_isolated')}) for lane in LANES})

    def test_exact_clean_smoke_can_start_observation_but_never_proves_full_certification(self):
        good=self.smoke();self.assertEqual(smoke_engineering(good)['status'],'PASS')
        self.assertEqual(evaluate(good)['status'],'INCOMPLETE')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'smoke.json';path.write_text(json.dumps(good))
            self.assertEqual(sustained_readiness(path,manifest_hash='manifest',implementation_hash='code',integration_sha='commit'),[])
            self.assertIn('smoke_revision_mismatch:integration_sha',sustained_readiness(path,manifest_hash='manifest',implementation_hash='code',integration_sha='new'))
        for field,value in (('unexpected_exit',True),('process_restarts',1),('accounting_reconciled',False),('open_positions',None)):
            bad=self.smoke();bad['lanes']['pons'][field]=value
            self.assertEqual(smoke_engineering(bad)['status'],'FAIL')

    def test_raw_transport_hash_missing_record_and_terminal_policy_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);journal=Journal(root/'telemetry.sqlite')
            record=dict(sequence=1,lane='pons',request=[['eth_call',[]]],response='0x0')
            journal.append('pons','rpc','rpc_transport',dict(sequence=1,raw_hash=digest(record)))
            journal.append('pons','terminal','process_terminal',dict(status='returned',policy_hash='policy'));journal.close()
            def write(rows):
                with gzip.open(root/'rpc-evidence.jsonl.gz','wt') as handle:
                    for row in rows:handle.write(json.dumps(row)+'\n')
            write([record]);self.assertTrue(audit_telemetry(root,'pons','policy')['read_only'])
            with self.assertRaisesRegex(ValueError,'terminal_or_policy'):audit_telemetry(root,'pons','changed')
            write([dict(record,response='0x1')])
            with self.assertRaisesRegex(ValueError,'journal_mismatch'):audit_telemetry(root,'pons','policy')
            write([])
            with self.assertRaisesRegex(ValueError,'missing_raw'):audit_telemetry(root,'pons','policy')

    def test_empty_frozen_capital_book_is_not_clean_smoke_or_market_scarcity(self):
        bad=self.smoke();row=bad['lanes']['ramses']
        row['native_accounting']=dict(conservation=True,manifest=dict(
            genesis_by_quote_asset={},later_assets='unfunded_capacity_censoring'))
        self.assertEqual(smoke_engineering(bad)['status'],'FAIL')
        self.assertIn('ramses:permanently_unfunded_paper_book',evaluate(bad)['failures'])
        # Waiting for the first fundable screen is a recoverable native state,
        # not an initialized zero-capacity book or a natural lifecycle proof.
        row['native_accounting']=dict(funding_state='awaiting_first_fundable_pinned_screen',paper_entry_ready=False)
        self.assertEqual(smoke_engineering(bad)['status'],'PASS')
        self.assertEqual(evaluate(bad)['status'],'INCOMPLETE')

    def test_shutdown_retains_native_queue_and_records_explicit_censor_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath=Path(tmp)/'broker.sqlite';db=sqlite3.connect(dbpath)
            db.execute('CREATE TABLE jobs(job_key TEXT,kind TEXT,priority INTEGER,deadline REAL,status TEXT)')
            db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',[('a','research',90,5,'pending'),('b','exit',0,20,'inflight'),('c','candidate',20,5,'complete')]);db.commit();db.close()
            journal=Journal(Path(tmp)/'journal.sqlite')
            result=record_unfinished_broker_jobs(dbpath,journal,10)
            self.assertEqual(result['count'],2)
            rows=list(journal.records());self.assertEqual(len(rows),2)
            self.assertEqual({r['body']['terminal_reason'] for r in rows},{'evidence_deadline_expired_at_shutdown','uncompleted_evidence_at_campaign_shutdown'})
            with sqlite3.connect(dbpath) as db:self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0],1)
            journal.close()

    def test_native_read_only_asset_transfers_are_distinct_from_transaction_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            for method,allowed in [('alchemy_getAssetTransfers',True),('eth_sendRawTransaction',False)]:
                root=Path(tmp)/method;root.mkdir();journal=Journal(root/'telemetry.sqlite')
                record=dict(sequence=1,lane='pons',request=[[method,[]]],response={})
                journal.append('pons','rpc','rpc_transport',dict(sequence=1,raw_hash=digest(record)))
                journal.append('pons','end','process_terminal',dict(status='returned',policy_hash='policy'));journal.close()
                with gzip.open(root/'rpc-evidence.jsonl.gz','wt') as handle:handle.write(json.dumps(record)+'\n')
                self.assertEqual(audit_telemetry(root,'pons','policy')['read_only'],allowed)

    def test_retry_burden_differences_cumulative_counters_within_each_session(self):
        from certification.pressure import PressureView
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'provider.sqlite';db=sqlite3.connect(path)
            db.executescript('CREATE TABLE transports(seq INTEGER PRIMARY KEY,body TEXT); CREATE TABLE limits(endpoint TEXT,cooldown REAL,interval REAL); CREATE TABLE queue(endpoint TEXT,created REAL);')
            db.execute("INSERT INTO limits VALUES('endpoint',0,0.5)")
            for session,cumulative in [('a',0),('a',1),('a',1),('a',2),('a',2),('b',1)]:
                row=dict(lane='pons',endpoint_fingerprint='endpoint',session=session,methods=['eth_call'],retry_count=cumulative)
                db.execute('INSERT INTO transports(body) VALUES(?)',(json.dumps(row),))
            db.commit();db.close();view=PressureView(path)
            self.assertEqual(view.snapshot()['lanes']['pons']['retries'],3)
            self.assertEqual(view.snapshot()['lanes']['pons']['retries'],3)


if __name__=='__main__':unittest.main()
