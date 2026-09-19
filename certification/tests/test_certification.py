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
    def complete(self):
        return dict(elapsed_seconds=14400,lanes={lane:dict(continuous_uptime_seconds=14400,
                    natural_settled=1,process_restarts=0,gates={g:True for g in REQUIRED}) for lane in LANES})

    def test_forced_zero_missing_unknown_and_restart_cannot_pass(self):
        good=self.complete();self.assertEqual(evaluate(good)['status'],'PASS')
        for name in ('forced','missing','restart','short','unsettled'):
            x=json.loads(json.dumps(good));r=x['lanes']['pons']
            if name=='forced':r.update(natural_settled=0,forced_settled=3)
            elif name=='missing':del r['gates']['accounting_reconciled']
            elif name=='restart':r['process_restarts']=1
            elif name=='short':r['continuous_uptime_seconds']=14399
            else:r['open_positions']=1
            self.assertNotEqual(evaluate(x)['status'],'PASS',name)

    def test_virtual_meteora_result_is_not_ledger_settlement(self):
        x=summarize('meteora',dict(complete_lifecycle_count=5,qualified_lifecycles=[dict(complete=True)]))
        self.assertEqual(x['natural_settled'],0);self.assertIsNone(x['accounting_reconciled'])

    def test_pons_cancel_not_natural_trade(self):
        x=summarize('pons',dict(lifecycles=[dict(final_position=dict(status='settled',entry_tokens=0))]))
        self.assertEqual(x['natural_settled'],0)

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
            self.assertGreaterEqual(times[-1]-times[0],1.4)
            status=Governor(path).status()
            self.assertEqual(status['queues'],[])
            self.assertEqual(status['providers'][0]['grants'],4)

if __name__=='__main__':unittest.main()
