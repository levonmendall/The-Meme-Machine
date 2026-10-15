"""Lifecycle and crash counterexamples. All stores/providers are disposable.

Synthetic qualification inputs exercise policy authority only; they are never
evidence of a positive mainnet Meteora opportunity or a production cost rate.
"""
import asyncio
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import based58

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable,IntervalProof,digest
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_selective_history import CandidateReader,coverage_scope,economic_records
from meme_machine.solana_selective_source import install,commit_scout,plan_live
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.yellowstone import geyser_pb2 as pb
from meme_machine import pump
from tests.test_solana_selective_evidence import FIXTURE,METEORA

NOW=1791400000.


def state_at(path,clock=lambda:NOW):
    writer=EvidenceWriter(path,clock=clock)
    state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))
    history=install(state);history.clock=clock;history.lifecycle.clock=clock
    return state,history


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=[NOW]
        self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.state,self.h=state_at(self.path,lambda:self.now[0]);self.life=self.h.lifecycle
    def tearDown(self):self.state.writer.close();self.tmp.cleanup()
    def restart(self):
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0]);self.life=self.h.lifecycle
    def drain(self):
        while self.life.flush():pass
        self.life.publish()

    def test_source_worker_fairness_restores_on_success_and_failure(self):
        from meme_machine.runtime import evidence_worker
        from types import SimpleNamespace
        previous=sys.getswitchinterval();observed=[]
        class RPC:
            def __init__(self,endpoint,governor):self.config=SimpleNamespace(credential='offline')
            def validate_network(self):observed.append(('identity',sys.getswitchinterval()))
        async def serve(path,endpoint,**kwargs):
            self.assertEqual(path,Path(self.tmp.name)/'source.sqlite')
            self.assertTrue(kwargs['source_driver'])
            observed.append(('source',sys.getswitchinterval()))
            if fail:raise RuntimeError('original_source_failure')
        for fail in (False,True):
            with (patch.dict(os.environ,MM_SOLANA_READ_RPC_URL='https://provider.invalid/rpc',
                    MM_SOLANA_EVIDENCE_PLANE_DB=str(Path(self.tmp.name)/'source.sqlite'),
                    MM_PROVIDER_GOVERNOR_DB=str(Path(self.tmp.name)/'governor.sqlite')),
                    patch('meme_machine.operational.bounded_provider.install'),
                    patch('meme_machine.solana_selective_source.SelectiveSource',return_value=object()),
                    patch.object(evidence_worker,'Governor'),patch.object(evidence_worker,'RepairRPC',RPC),
                    patch.object(evidence_worker,'serve',serve)):
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'original_source_failure'):asyncio.run(evidence_worker.main_async())
                else:asyncio.run(evidence_worker.main_async())
            self.assertEqual(sys.getswitchinterval(),previous)
        self.assertEqual(observed,[('identity',previous),('source',.0005)]*2)

    def test_native_owner_durability_under_busy_intake_thread(self):
        """Reproduce intake/SQLite interpreter contention without provider work."""
        from meme_machine.solana_evidence_plane import FinalizedRecord
        import threading,time
        outputs=[];measurements=[]
        original=sys.getswitchinterval()
        payload=json.dumps(dict(logs=['Program log: '+str(n)*30 for n in range(80)],values=list(range(80))))
        try:
            for interval in (.005,.001,.0005):
                stop=threading.Event();ready=threading.Event()
                def intake():
                    ready.set()
                    while not stop.is_set():
                        value=json.loads(payload)
                        sum(value['values'])
                state,h=state_at(Path(self.tmp.name)/('busy-'+str(interval)+'.sqlite'))
                producer=threading.Thread(target=intake,name='offline-native-intake')
                try:
                    sys.setswitchinterval(interval);producer.start();self.assertTrue(ready.wait(2))
                    rows=[FinalizedRecord('owner-'+str(n),'program:pump',100+n,'signature-'+str(n),
                        'program',('mint','wallet-'+str(n)),int(NOW),
                        dict(event=dict(mint='mint',event_type='trade',market_time=int(NOW),native_buy=n),
                             raw_lineage=dict(logs=['Program log: authenticated fixture'],err=None)),
                        'alchemy_finalized_stream','a'*64,NOW,transaction_index=n,event_index=0)
                        for n in range(64)]
                    started=time.perf_counter();cpu=time.thread_time();h.ingest(rows)
                    measurements.append(dict(switch_seconds=interval,wall_seconds=time.perf_counter()-started,
                        owner_cpu_seconds=time.thread_time()-cpu,records=len(rows)))
                    outputs.append(dict(records=state.writer.db.execute('SELECT * FROM rolling_economic_events ORDER BY slot,identity').fetchall(),
                        ordering=state.writer.db.execute('SELECT * FROM native_order_attestations ORDER BY slot,signature').fetchall(),
                        outbox=state.writer.db.execute('SELECT * FROM candidate_outbox ORDER BY sequence').fetchall()))
                finally:
                    stop.set();producer.join(2);self.assertFalse(producer.is_alive());state.writer.close()
            self.assertEqual(outputs[0],outputs[1])
            self.assertEqual(outputs[0],outputs[2])
            self.assertEqual(len(outputs[0]['records']),64)
            print('NATIVE_OWNER_BUSY_INTAKE_DIAGNOSTIC '+json.dumps(measurements),flush=True)
        finally:sys.setswitchinterval(original)

    def test_native_reference_batch_reuses_metadata_fold_with_identical_economics(self):
        from meme_machine.solana_evidence_plane import FinalizedRecord
        paths=[Path(self.tmp.name)/'sequential.sqlite',self.life.path]
        for path in paths:
            with closing(CandidateHistory(path,clock=lambda:self.now[0])) as shared:
                shared.observe('pump','mint',surface='pump.fun',observed_at=int(NOW)-200,
                    metadata=dict(volume_quality={'retained':True}))
        with self.state.writer.transaction():
            for n in range(64):
                at=int(NOW)-100+n
                event=dict(mint='mint',market_time=at,event_type='migration' if n==1 else 'trade',native_buy=n)
                if n==1:event.update(creator='é',pool='pool-a')
                if n==63:event['pool']='pool-b'
                row=FinalizedRecord('economic:'+str(n),'program:pump',100+n,'signature:'+str(n),
                    'program',('mint',),at,dict(event=event),'alchemy_finalized_stream','a'*64,NOW,
                    transaction_index=n,event_index=0)
                self.h.rolling.store(row)
                self.life.emit('pump','mint','canonical',dict(record=row.body(),available=NOW))
        original=self.h.db.execute('SELECT id,body,hash FROM candidate_history_outbox ORDER BY rowid').fetchall()
        self.life.path=paths[0]
        while self.life.flush(limit=1):pass
        with closing(CandidateHistory(paths[0])) as shared:
            expected_candidate=shared.candidate('pump','mint');expected_events=shared.events('pump','mint')
            expected_receipts=shared.db.execute('SELECT * FROM source_receipts ORDER BY id').fetchall()
        with self.state.writer.transaction():
            self.h.db.executemany('UPDATE candidate_history_outbox SET consumed=NULL,body=?,hash=? WHERE id=?',
                [(raw,checksum,identity) for identity,raw,checksum in original])
        self.life.path=paths[1];calls=[];observe=CandidateHistory.observe
        def measured(shared,*args,**kwargs):
            calls.append((args,kwargs));return observe(shared,*args,**kwargs)
        with patch.object(CandidateHistory,'observe',measured):self.assertEqual(self.life.flush(),64)
        self.assertEqual(len(calls),2)
        with closing(CandidateHistory(paths[1])) as shared:
            self.assertEqual(shared.candidate('pump','mint'),expected_candidate)
            self.assertEqual(shared.events('pump','mint'),expected_events)
            self.assertEqual(shared.db.execute('SELECT * FROM source_receipts ORDER BY id').fetchall(),expected_receipts)
        self.restart()
        with closing(CandidateHistory(paths[1])) as shared:
            self.assertEqual(shared.candidate('pump','mint'),expected_candidate)
            self.assertEqual(shared.events('pump','mint'),expected_events)

    def test_reference_metadata_fold_preserves_later_promotion_precedence_and_rollback(self):
        from meme_machine.solana_evidence_plane import FinalizedRecord
        row=FinalizedRecord('economic','program:pump',100,'sig','program',('mint',),int(NOW)-1,
            dict(event=dict(mint='mint',event_type='trade',market_time=int(NOW)-1)),
            'alchemy_finalized_stream','a'*64,NOW,transaction_index=1)
        with self.state.writer.transaction():
            self.h.rolling.store(row)
            self.life.emit('pump','mint','canonical',dict(record=row.body(),available=NOW))
            self.life.emit('pump','mint','promotion',dict(first_seen=NOW,observed_at=NOW,
                decision_deadline=NOW+150,lower_slot=100,ready_at=NOW))
        self.life.flush()
        with closing(CandidateHistory(self.life.path)) as shared:
            before=shared.candidate('pump','mint')
            self.assertEqual(before['surface'],'pump')
            self.assertEqual(before['decision_deadline'],int(NOW)+150)
            events=shared.events('pump','mint')
        with self.state.writer.transaction():
            self.life.emit('pump','mint','canonical',dict(record=row.body(),available=NOW+1))
            self.h.db.execute("UPDATE candidate_history_outbox SET hash='bad' WHERE consumed IS NULL")
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_history_outbox_corrupt'):self.life.flush()
        with closing(CandidateHistory(self.life.path)) as shared:
            self.assertEqual(shared.candidate('pump','mint'),before)
            self.assertEqual(shared.events('pump','mint'),events)

    def test_development_selection_keeps_original_order_unknowns_and_live_changes(self):
        def original(minimum,limit):
            return self.h.db.execute('''SELECT address FROM market_observations m WHERE family='pump'
                AND NOT EXISTS(SELECT 1 FROM evidence_bindings b WHERE b.family=m.family AND b.address=m.address)
                AND (json_extract(fields,'$.complete') OR json_extract(fields,'$.development_upper_bps') IS NULL
                    OR json_extract(fields,'$.development_upper_bps')>=?) ORDER BY first_seen,address LIMIT ?''',
                (minimum,limit)).fetchall()
        cases=[('a',{}),('b',dict(complete=True,development_upper_bps=0)),
            ('c',dict(complete=False,development_upper_bps=8500)),
            ('d',dict(complete=False,development_upper_bps=100)),
            ('e',dict(development_upper_bps=None)),('f',dict(development_upper_bps=7500))]
        for address,fields in cases:
            self.h.observe('pump',address,slot=100,signature='',fields=fields,seen=NOW)
        self.h.bind('pump','c')
        for minimum in (0,7500,8500,10000):
            for limit in (1,4,100):
                self.assertEqual(self.h.development_candidates(minimum,limit),original(minimum,limit))
        self.h.observe('pump','d',slot=101,signature='',fields=dict(development_upper_bps=9000),seen=NOW+1)
        self.h.observe('pump','b',slot=101,signature='',fields=dict(complete=False,development_upper_bps=0),seen=NOW+1)
        before=original(7500,100);self.assertIn(('d',),before);self.assertNotIn(('b',),before)
        self.restart();self.assertEqual(self.h.development_candidates(7500,100),before)

    def test_idle_development_and_reactivation_do_not_traverse_the_retained_population(self):
        from meme_machine.solana_evidence_plane import canonical,digest
        fields=dict(complete=False,development_upper_bps=100);raw=canonical(fields);checksum=digest(fields)
        with self.state.writer.transaction():
            self.h.db.executemany('INSERT INTO market_observations VALUES(?,?,?,?,?,?,?,?,?)',
                (('pump','quiet-'+str(n),100,100,NOW,NOW,'',raw,checksum) for n in range(10000)))
            self.h.db.executemany('INSERT INTO candidate_lifecycle VALUES(?,?,?,?,?,?,?,?,?,?)',
                (('pump','quiet-'+str(n),'demoted',0,100,100,NOW,NOW,None,100) for n in range(10000)))
            self.h.db.execute("UPDATE candidate_lifecycle SET state='reactivated' WHERE address='quiet-9999'")
        steps=[0];self.h.db.set_progress_handler(lambda:steps.__setitem__(0,steps[0]+1) or 0,1)
        try:
            self.assertEqual(self.h.development_candidates(7500,4),[])
            self.assertEqual(self.h.db.execute("SELECT address FROM candidate_lifecycle WHERE family IN ('pump','pumpswap') AND state='reactivated' AND rowid>? ORDER BY rowid LIMIT ?",(0,4)).fetchall(),[('quiet-9999',)])
            self.assertLess(steps[0],1000)
        finally:self.h.db.set_progress_handler(None,0)

    def test_pending_history_cursor_does_not_rescan_resolved_population(self):
        with self.state.writer.transaction():
            self.h.db.executemany('INSERT INTO rolling_boundary_waits VALUES(?,?,?,?,?,?,?,?)',
                (('pump','old-'+str(n),100,101,NOW+150,3,NOW,'resolved') for n in range(10000)))
            self.h.db.executemany('INSERT INTO rolling_publication_waits VALUES(?,?,?,?,?,?,?,?)',
                (('pump','old-'+str(n),100,101,NOW+150,3,NOW,'resolved') for n in range(10000)))
            for table in ('rolling_boundary_waits','rolling_publication_waits'):
                self.h.db.execute("UPDATE "+table+" SET status='pending' WHERE address='old-9999'")
        steps=[0];self.h.db.set_progress_handler(lambda:steps.__setitem__(0,steps[0]+1) or 0,1)
        try:
            for table in ('rolling_boundary_waits','rolling_publication_waits'):
                selected=self.h.rolling.pending_slice(table,'family,address,deadline',limit=4,after=0)
                self.assertEqual([(r[1],r[2],r[3]) for r in selected],[('pump','old-9999',NOW+150)])
                # A completed keyset wraps fairly without losing the original
                # pending obligation or extending its absolute deadline.
                self.assertEqual(self.h.rolling.pending_slice(table,'family,address,deadline',limit=4,after=selected[0][0]),selected)
            self.assertLess(steps[0],1000)
        finally:self.h.db.set_progress_handler(None,0)
    def seed(self,family,address,slot=100):
        self.h.observe(family,address,slot=slot,signature='',seen=self.now[0],fields=dict(wsol_pair_locator=True,activity=False))
        self.h.bind(family,address);self.drain()
    def ingest_fixture(self,family):
        tx=METEORA['transaction'] if family=='meteora' else FIXTURE['pumpswap'][0]
        address=METEORA['counterexample']['pools'][0]['pool'] if family=='meteora' else next(
            r['pool'] for r in __import__('meme_machine.solana_program_decoders',fromlist=['pumpswap_trade_events']).pumpswap_trade_events(tx))
        self.seed(family,address,tx['slot'])
        rows=economic_records(family,address,tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
        self.h.ingest(rows);self.drain()
        return address,rows

    def test_scout_quiet_restart_reactivate_promote_and_native_edf_qualification(self):
        address=METEORA['counterexample']['pools'][0]['pool']
        update=pb.SubscribeUpdate(filters=['m']);item=update.account;item.slot=100;item.is_startup=True
        item.account.pubkey=pump.un58(address);item.account.owner=pump.un58('LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo')
        item.account.data=b'\0'*56
        commit_scout(self.state,update,NOW);self.drain();self.restart()
        with closing(CandidateHistory(self.life.path,clock=lambda:self.now[0])) as shared:
            first=shared.candidate('meteora',address);self.assertEqual(first['first_observed'],NOW)
            self.assertEqual(shared.pending(),0)
        item.slot=101;item.is_startup=False;item.account.txn_signature=b'1'*64
        self.now[0]+=1;commit_scout(self.state,update,self.now[0])
        promotion=self.life.promote('meteora',address,deadline=NOW+150);self.drain();self.restart()
        with closing(CandidateHistory(self.life.path,clock=lambda:self.now[0])) as shared:
            from meme_machine.lanes.meteora import runner
            class EmptySource:
                on_discovered=None
                def start(self):pass
                def snapshot(self):return dict(pending=0,first_seen=0,census_cycles=0)
                def next_candidate(self):return None
                def close(self):pass
            with patch.object(runner,'CANDIDATE_HISTORY',shared):
                stream=runner._campaign_candidates(runner.load_policy(),{},float('inf'),lambda s:None,EmptySource())
                candidate=next(stream);stream.close()
            self.assertEqual(candidate['address'],address)
            self.assertEqual(candidate['_candidate_work_id'],'provider:'+promotion)
            self.assertTrue(candidate['provider_structural'])
            self.assertEqual(shared.candidate('meteora',address)['first_observed'],NOW)
            self.assertEqual(shared.db.execute('SELECT deadline FROM work').fetchone()[0],NOW+150)
            # Deterministic mechanics, explicitly not a positive provider case.
            features=dict(authenticated_fee_density_24h_pct=4.,competing_liquidity_to_capital_multiple=4.,
                two_way_balance=.2,drift_ratio=.8,reversal_count=0,
                stress_inventory_roundtrip=dict(loss_bps=200.),expected_net_lamports=1)
            decision=runner.qualify(features,runner.load_policy());self.assertTrue(decision['passes'])
            d=shared.record_decision('meteora',address,mode='dlmm',observed_at=int(NOW+2),qualified=True,decision=decision)
            shared.record_funding(d,'meteora',address,status='denied',at=int(NOW+2),reason='capital_occupied')
            shared.complete('provider:'+promotion,now=NOW+2)
            self.assertEqual(shared.funding_outcome(d)['status'],'denied')

    def test_demotion_has_no_tombstone_and_duplicate_activity_cannot_promote_twice(self):
        self.seed('meteora','pool')
        self.life.demote('meteora','pool',reason='temporary_weakness');self.drain();self.restart()
        self.assertTrue(self.life.wake('meteora','pool',slot=101,seen=NOW+1,signature='new',evidence=dict(ambiguous=True)))
        first=self.life.promote('meteora','pool',deadline=NOW+150);self.drain()
        self.assertIsNone(self.life.promote('meteora','pool',deadline=NOW+300))
        self.life.demote('meteora','pool',reason='quiet_again')
        self.assertFalse(self.life.wake('meteora','pool',slot=101,seen=NOW+5,signature='new',evidence={}))
        self.assertTrue(self.life.wake('meteora','pool',slot=102,seen=NOW+6,signature='later',evidence={}))
        second=self.life.promote('meteora','pool',deadline=NOW+200)
        self.assertNotEqual(first,second)

    def test_retire_reactivate_reconstruct_preserves_exact_bytes_age_and_order(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h)
        expected=[r.body() for r in rows]
        self.life.demote('meteora',address,reason='quiet');self.drain()
        result=cold.retire();self.assertGreater(result['hot_bytes_before'],result['hot_bytes_after'])
        self.assertEqual(result['retired_records'],len(rows));self.restart();cold=ScopedRetirement(self.h)
        self.assertTrue(self.life.wake('meteora',address,slot=rows[0].slot+1,seen=NOW+1,signature='later',evidence={}))
        self.assertEqual(cold.restore('meteora',address),len(rows))
        stored=self.state.writer.db.execute('SELECT body,first_seen FROM canonical_evidence ORDER BY identity').fetchall()
        self.assertEqual([json.loads(r[0]) for r in stored],sorted(expected,key=lambda r:r['identity']))
        self.assertTrue(all(r[1]==NOW for r in stored))
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],len(rows))

    def test_every_required_pin_and_open_position_survives_storage_pressure(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h);scope=coverage_scope('meteora',address)
        for reason in ('right_tail_hwm','tail_bridge','staged_add','current_survivor','warming','pending_qualification','decision_audit'):
            with self.subTest(reason=reason):
                self.life.pin(scope,'consumer',reason,rows[0].slot)
                self.assertEqual(cold.retire()['retired_records'],0)
                self.life.unpin(scope,'consumer',reason)
        w=self.state.writer;w.interest('position','program:meteora',lower_slot=rows[0].slot,priority=0,lifecycle='open')
        w.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',('position','program:meteora',address,'account'))
        result=cold.retire();self.assertEqual(result['retired_records'],0);self.assertGreater(result['pinned_bytes'],0)
        # Lowering a physical storage budget never turns an open pin into eviction.
        w.max_hot_bytes=w.path.stat().st_size
        self.assertEqual(cold.retire()['retired_records'],0)

    def test_live_retirement_defers_totals_without_changing_pins_or_recovery(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h)
        scope=coverage_scope('meteora',address)
        expected=sorted((r.body() for r in rows),key=lambda r:r['identity'])
        self.life.demote('meteora',address,reason='quiet');self.drain()
        self.life.pin(scope,'position','right_tail_hwm',rows[0].slot)
        with patch.object(cold,'hot_bytes',side_effect=AssertionError('global scan on live owner')):
            pinned=cold.retire(measure_hot_bytes=False)
            self.assertEqual(pinned['retired_records'],0)
            self.assertGreater(pinned['pinned_bytes'],0)
            self.life.unpin(scope,'position','right_tail_hwm')
            retired=cold.retire(measure_hot_bytes=False)
        self.assertEqual(retired['retired_records'],len(rows))
        self.assertIsNone(retired['hot_bytes_before']);self.assertIsNone(retired['hot_bytes_after'])
        self.assertEqual(retired['hot_bytes_measurement'],'deferred')
        self.restart();cold=ScopedRetirement(self.h)
        self.assertEqual(cold.restore('meteora',address),len(rows))
        stored=self.h.db.execute('SELECT body,first_seen FROM canonical_evidence ORDER BY identity').fetchall()
        self.assertEqual([json.loads(r[0]) for r in stored],expected)
        self.assertTrue(all(r[1]==NOW for r in stored))

    def test_deferred_totals_preserve_unacknowledged_oldest_witness(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h)
        self.life.demote('meteora',address,reason='quiet');self.drain()
        self.now[0]+=self.h.rolling.retention('meteora',address)['window_seconds']+1
        self.h.db.execute("DELETE FROM candidate_history_outbox WHERE kind='canonical'")
        exact=cold.retire()
        with patch.object(cold,'hot_bytes',side_effect=AssertionError('global scan on live owner')):
            deferred=cold.retire(measure_hot_bytes=False)
        self.assertEqual(deferred['retired_records'],0)
        self.assertEqual(deferred['oldest_unretired_scope'],exact['oldest_unretired_scope'])
        self.assertEqual(deferred['oldest_unretired_scope']['reason'],'batch_bound_or_unacknowledged_consumer')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence WHERE body IS NOT NULL').fetchone()[0],len(rows))

    def test_oldest_unacknowledged_retained_identity_matches_the_join_oracle(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h)
        # A missing durable receipt prohibits retirement and exercises the
        # fallback metric, rather than the already-pinned branch.
        self.life.demote('meteora',address,reason='quiet');self.drain()
        self.now[0]+=self.h.rolling.retention('meteora',address)['window_seconds']+1
        self.state.writer.db.execute("DELETE FROM candidate_history_outbox WHERE kind='canonical'")
        # Multiple consumer views must not change the oldest economic identity.
        for n in range(20):
            self.h.bind('meteora','consumer-'+str(n),market_address=address)
        expected=self.state.writer.db.execute('''SELECT MIN(r.slot) FROM canonical_evidence r
            JOIN canonical_addresses a ON a.identity=r.identity JOIN evidence_bindings b
            ON b.market_address=a.address AND b.canonical_scope=r.scope WHERE r.body IS NOT NULL''').fetchone()[0]
        # No consumer can advance during this read-only retirement check.
        result=cold.retire()
        self.assertEqual(result['retired_records'],0)
        self.assertEqual(result['oldest_unretired_scope']['slot'],expected)
        self.assertEqual(result['oldest_unretired_scope']['reason'],'batch_bound_or_unacknowledged_consumer')
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence WHERE body IS NOT NULL').fetchone()[0],len(rows))

    def test_duplicate_after_retirement_or_restore_keeps_original_identity_and_availability(self):
        for cache_only in (False,True):
            with self.subTest(cache_only=cache_only):
                self.state.writer.close();self.path=Path(self.tmp.name)/str(cache_only)/'canonical.sqlite'
                self.state,self.h=state_at(self.path,lambda:self.now[0]);self.life=self.h.lifecycle
                if cache_only:
                    # Reproduce a late candidate below the global hot floor,
                    # with no corresponding records-table row at all.
                    self.h.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                        ('retention_floor:program:meteora',str(METEORA['transaction']['slot']+1)))
                address,rows=self.ingest_fixture('meteora')
                if cache_only:
                    self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
                cold=ScopedRetirement(self.h);self.life.demote('meteora',address,reason='quiet');self.drain()
                cold.retire();self.restart();cold=ScopedRetirement(self.h)
                before=self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0]
                # Paid overlap after retirement uses verified cold bytes, not
                # newly delivered bytes as an invented historical timestamp.
                self.h.ingest(rows);self.drain();cold.restore('meteora',address)
                self.h.ingest(rows);self.drain()
                stored=self.state.writer.db.execute('SELECT hash,first_seen FROM canonical_evidence').fetchall()
                self.assertEqual(stored,[(digest(r.body()),NOW) for r in rows])
                self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],before)

    def test_oldest_seek_matches_canonical_oracle_for_hot_cold_shadow_and_restart(self):
        # These metadata-only rows test retirement telemetry, never economics.
        address,_=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h);db=self.h.db
        sample=list(db.execute('SELECT * FROM canonical_evidence WHERE body IS NOT NULL LIMIT 1').fetchone())
        tables=('records','shared_history_cache','scoped_cold_records','rolling_economic_events')
        aliases=('addresses','cached_addresses','scoped_cold_addresses','rolling_economic_addresses')
        for index,(table,alias) in enumerate(zip(tables,aliases)):
            row=list(sample);row[0]='telemetry-hot-'+str(index);row[2]=10+index;row[12]='telemetry-cold'
            db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)
            if alias=='addresses':db.execute('INSERT INTO addresses(address,identity,slot) VALUES(?,?,?)',(address,row[0],row[2]))
            else:db.execute('INSERT INTO '+alias+' VALUES(?,?)',(row[0],address))
        # A cold rolling representation shadows an older hot records body.
        row=list(sample);row[0]='telemetry-shadow';row[2]=1
        db.execute('INSERT INTO records VALUES('+','.join('?' for _ in row)+')',row)
        db.execute('INSERT INTO addresses(address,identity,slot) VALUES(?,?,?)',(address,row[0],row[2]))
        row[9]=None;row[12]='telemetry-cold'
        db.execute('INSERT INTO rolling_economic_events VALUES('+','.join('?' for _ in row)+')',row)
        oracle='''SELECT r.identity,r.scope,r.slot FROM canonical_evidence r
            WHERE r.body IS NOT NULL AND EXISTS(SELECT 1 FROM canonical_addresses a
                JOIN evidence_bindings b ON b.market_address=a.address AND b.canonical_scope=r.scope
                WHERE a.identity=r.identity) ORDER BY r.slot,r.identity LIMIT 1'''
        def equal():self.assertEqual(cold.oldest_hot_bound_record(),db.execute(oracle).fetchone())
        equal();self.assertEqual(cold.oldest_hot_bound_record()[0],'telemetry-hot-0')
        for table in tables:
            mutation='DELETE FROM '+table if table=='shared_history_cache' else 'UPDATE '+table+' SET body=NULL'
            db.execute(mutation+' WHERE identity LIKE ? AND identity!=?',('telemetry-hot-%','telemetry-hot-3'))
            equal()
        self.restart();cold=ScopedRetirement(self.h);db=self.h.db;equal()
        self.assertEqual(cold.oldest_hot_bound_record()[0],'telemetry-hot-3')

    def test_shared_content_cannot_retire_through_a_different_unpinned_binding(self):
        address,rows=self.ingest_fixture('meteora');other=next(a for a in rows[0].addresses if a!=address)
        self.seed('meteora',other,rows[0].slot)
        self.life.pin(coverage_scope('meteora',other),'position','right_tail_hwm',rows[0].slot)
        self.assertEqual(ScopedRetirement(self.h).retire()['retired_records'],0)

    def test_retirement_slice_checks_pinned_shared_owner_outside_its_cursor(self):
        address,rows=self.ingest_fixture('meteora');other=next(a for a in rows[0].addresses if a!=address)
        self.seed('meteora',other,rows[0].slot)
        self.life.pin(coverage_scope('meteora',other),'position','right_tail_hwm',rows[0].slot)
        scope=self.h.scope_for('meteora',address)
        self.h.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scoped_retirement_cursor',scope[:-1]))
        result=ScopedRetirement(self.h).retire(limit=1)
        self.assertEqual(result['candidate_scopes_examined'],1)
        self.assertEqual(result['retired_records'],0)
        self.assertGreater(result['pinned_bytes'],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_cold_records').fetchone()[0],0)

    def test_retirement_large_shared_fanout_keeps_hot_history(self):
        address,rows=self.ingest_fixture('meteora')
        for n in range(70):self.h.bind('meteora','view-'+str(n),market_address=address)
        scope=self.h.scope_for('meteora',address)
        self.h.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('scoped_retirement_cursor',scope[:-1]))
        result=ScopedRetirement(self.h).retire(limit=1)
        self.assertEqual(result['retired_records'],0)
        self.assertEqual(result['oldest_unretired_scope']['reason'],'shared_binding_bound')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence WHERE body IS NOT NULL').fetchone()[0],len(rows))

    def test_retirement_cursor_advances_boundedly_and_survives_restart(self):
        for n in range(150):self.h.bind('pump',f'quiet-{n:03d}')
        result=ScopedRetirement(self.h).retire()
        self.assertEqual(result['candidate_scopes_examined'],64)
        self.assertEqual(self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone()[0],coverage_scope('pump','quiet-063'))
        self.restart();result=ScopedRetirement(self.h).retire()
        self.assertEqual(result['candidate_scopes_examined'],64)
        self.assertEqual(self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone()[0],coverage_scope('pump','quiet-127'))
        result=ScopedRetirement(self.h).retire()
        self.assertEqual(result['candidate_scopes_examined'],22)
        self.assertEqual(ScopedRetirement(self.h).retire()['candidate_scopes_examined'],64)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM evidence_bindings').fetchone()[0],150)

    def test_hot_byte_indexes_preserve_identity_precedence_updates_and_restart(self):
        # Measurement-only representations, including Unicode byte lengths.
        # No synthetic row is consumed as trading or canonical coverage proof.
        self.ingest_fixture('meteora');cold=ScopedRetirement(self.h);db=self.h.db
        sample=list(db.execute('SELECT * FROM canonical_evidence WHERE body IS NOT NULL LIMIT 1').fetchone())
        tables=('records','shared_history_cache','scoped_cold_records','rolling_economic_events')
        identity='offline-byte-measurement'
        for index,table in enumerate(tables):
            row=list(sample);row[0]=identity
            row[9]=json.dumps({'unicode':'雪'*(index+1)},ensure_ascii=False)
            row[10]=digest(json.loads(row[9]));row[12]='offline-archive-identity'
            db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in row)+')',row)
        original='SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM canonical_evidence WHERE body IS NOT NULL'
        def equal():self.assertEqual(cold.hot_bytes(),db.execute(original).fetchone()[0])
        equal()
        for table in ('rolling_economic_events','records','scoped_cold_records'):
            db.execute('UPDATE '+table+' SET body=NULL WHERE identity=?',(identity,));equal()
        db.execute('DELETE FROM rolling_economic_events WHERE identity=?',(identity,));equal()
        db.execute('DELETE FROM shared_history_cache WHERE identity=?',(identity,));equal()
        self.restart();cold=ScopedRetirement(self.h);db=self.h.db;equal()
        # Length changes roll back with their rows; no independent counter can
        # survive a failed append or fabricate capacity across restart.
        with self.assertRaisesRegex(RuntimeError,'offline rollback'):
            with self.state.writer.transaction():
                db.execute('UPDATE records SET body=body||? WHERE body IS NOT NULL',(' ',))
                equal();raise RuntimeError('offline rollback')
        equal()

    def test_retirement_reads_do_not_block_on_an_unrelated_wal_writer(self):
        import threading,time
        cold=ScopedRetirement(self.h)
        with closing(CandidateHistory(self.life.path)) as writer:
            writer.db.execute('BEGIN IMMEDIATE')
            release=threading.Event()
            def unlock():
                release.wait(1);writer.db.execute('ROLLBACK')
            helper=threading.Thread(target=unlock);helper.start()
            before=self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone()
            started=time.monotonic()
            try:
                self.assertIsInstance(cold.retire(measure_hot_bytes=False),dict)
                self.assertLess(time.monotonic()-started,.25,'retirement waited for an unrelated consumer writer')
                self.assertEqual(self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone(),before)
                self.assertFalse(self.h.db.in_transaction)
            finally:release.set();helper.join(2)
        self.assertIsInstance(cold.retire(measure_hot_bytes=False),dict)

    def test_retirement_busy_consumer_preserves_cursor_and_retries_original_slice(self):
        import sqlite3
        cold=ScopedRetirement(self.h)
        before=self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone()
        error=sqlite3.OperationalError('database is locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch('meme_machine.solana_scoped_retirement.CandidateHistory',side_effect=error) as opened:
            self.assertEqual(cold.retire(measure_hot_bytes=False),0)
            self.assertEqual(opened.call_args.kwargs['write_wait_seconds'],0)
        self.assertEqual(self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone(),before)
        self.assertFalse(self.h.db.in_transaction)
        error=sqlite3.OperationalError('disk I/O error');error.sqlite_errorcode=sqlite3.SQLITE_IOERR
        with patch('meme_machine.solana_scoped_retirement.CandidateHistory',side_effect=error):
            with self.assertRaises(sqlite3.OperationalError):cold.retire(measure_hot_bytes=False)
        self.assertIsInstance(cold.retire(measure_hot_bytes=False),dict)

    def test_retirement_metadata_selection_bounds_rows_and_keeps_canonical_precedence(self):
        # Metadata-only representations; these rows are never consumed as
        # economic evidence or used to qualify a market opportunity.
        self.ingest_fixture('meteora');cold=ScopedRetirement(self.h);db=self.h.db
        sample=list(db.execute('SELECT * FROM canonical_evidence WHERE body IS NOT NULL LIMIT 1').fetchone())
        address='offline-wide-history'
        with self.state.writer.transaction():
            for n in range(1024):
                row=list(sample);row[0]='selection-'+str(n);row[2]=1024-n
                db.execute('INSERT INTO rolling_economic_events VALUES('+','.join('?' for _ in row)+')',row)
                db.execute('INSERT INTO rolling_economic_addresses VALUES(?,?)',(row[0],address))
            # A hot legacy copy must not defeat the canonical cold shadow.
            shadow=list(sample);shadow[0]='selection-1023';shadow[2]=1
            db.execute('INSERT INTO shared_history_cache VALUES('+','.join('?' for _ in shadow)+')',shadow)
            db.execute('UPDATE rolling_economic_events SET body=NULL WHERE identity=?',(shadow[0],))
        baseline=('SELECT r.identity,r.slot FROM canonical_evidence r WHERE r.identity IN '
            '(SELECT identity FROM canonical_addresses WHERE address=?) AND r.scope=? AND r.body IS NOT NULL')
        expected=sorted(db.execute(baseline,(address,sample[1])),key=lambda r:(r[1],r[0]))
        for limit in (1,16,64):
            statements=[];db.set_trace_callback(statements.append)
            try:selected=cold._oldest_hot_identities('meteora',address,limit)
            finally:db.set_trace_callback(None)
            self.assertEqual(selected,[r[0] for r in expected[:limit]])
            self.assertEqual(len(statements),1,'retirement expanded history through repeated Python queries')
            self.assertNotIn(shadow[0],selected)
        self.assertEqual(cold._oldest_hot_identities('meteora','unobserved',64),[])

    def test_retirement_shared_owner_seek_does_not_scan_unrelated_bindings(self):
        address,rows=self.ingest_fixture('meteora');cold=ScopedRetirement(self.h);db=self.h.db
        row=db.execute('SELECT identity,scope FROM canonical_evidence LIMIT 1').fetchone()
        oracle='''SELECT DISTINCT b.family,b.coverage_scope FROM canonical_addresses a
            JOIN evidence_bindings b ON b.market_address=a.address AND b.canonical_scope=?
            WHERE a.identity=? ORDER BY b.coverage_scope LIMIT 65'''
        with self.state.writer.transaction():
            db.executemany('INSERT INTO evidence_bindings VALUES(?,?,?,?,?,?)',
                [('meteora','unrelated-'+str(n),'unrelated-market-'+str(n),row[1],
                    coverage_scope('meteora','unrelated-'+str(n)),'{}') for n in range(4096)])
        expected=db.execute(oracle,(row[1],row[0])).fetchall();steps=[0]
        db.set_progress_handler(lambda:steps.__setitem__(0,steps[0]+100) or 0,100)
        try:actual=cold.shared_owners(row[1],row[0])
        finally:db.set_progress_handler(None,0)
        self.assertEqual(actual,expected)
        print('RETIREMENT_SHARED_OWNER_VM '+json.dumps(dict(unrelated=4096,steps=steps[0])),flush=True)
        self.assertLess(steps[0],2000,'shared-owner check scanned unrelated program bindings')

    def test_retirement_pin_seeks_do_not_scan_unrelated_obligations(self):
        cold=ScopedRetirement(self.h);db=self.h.db;self.h.bind('pump','target')
        with closing(CandidateHistory(self.life.path,clock=lambda:NOW)) as shared:
            def measured():
                steps=[0]
                def tick():steps[0]+=100;return 0
                db.set_progress_handler(tick,100);shared.db.set_progress_handler(tick,100)
                try:self.assertIsNone(cold.pinned('pump','target',100,110,shared))
                finally:db.set_progress_handler(None,0);shared.db.set_progress_handler(None,0)
                return steps[0]
            before=measured()
            with self.state.writer.transaction():
                db.executemany('INSERT INTO evidence_bindings VALUES(?,?,?,?,?,?)',
                    [('pump','unrelated-'+str(n),'unrelated-market-'+str(n),'program:pump',
                        coverage_scope('pump','unrelated-'+str(n)),'{}') for n in range(4096)])
                db.executemany('INSERT INTO candidate_pending_proofs VALUES(?,?,?,?,?,?,?,?)',
                    [(str(n),coverage_scope('pump','unrelated-'+str(n)),100,110,'source','endpoint','{}',NOW) for n in range(4096)])
                db.executemany('INSERT INTO acquisition_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    [(str(n),'pump','unrelated-'+str(n),100,110,4,NOW+60,'pending',None,0,None,None,'[]',NOW,NOW,None) for n in range(4096)])
            shared.db.executemany('INSERT INTO work VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [(str(n),'pump','unrelated-'+str(n),'history',NOW,NOW+60,1,4,'pending',None,None,NOW,NOW,'{}','hash') for n in range(4096)])
            after=measured()
            print('RETIREMENT_PIN_VM '+json.dumps(dict(unrelated=4096,before=before,after=after)),flush=True)
            self.assertLess(after,before+3000,'pin check scanned unrelated candidates or obligations')

    def test_failed_retirement_journal_does_not_skip_its_cursor(self):
        self.h.bind('pump','quiet')
        cold=ScopedRetirement(self.h)
        self.h.db.execute("CREATE TRIGGER fail_retirement_journal BEFORE INSERT ON scoped_retirement_observations BEGIN SELECT RAISE(ABORT,'offline journal fault'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):cold.retire(limit=1)
        self.assertIsNone(self.h.db.execute("SELECT value FROM meta WHERE key='scoped_retirement_cursor'").fetchone())
        self.h.db.execute('DROP TRIGGER fail_retirement_journal')
        self.restart();result=ScopedRetirement(self.h).retire(limit=1)
        self.assertEqual(result['candidate_scopes_examined'],1)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM scoped_retirement_observations').fetchone()[0],1)

    def test_large_legal_records_split_into_recoverable_cold_batches(self):
        from dataclasses import replace
        address,rows=self.ingest_fixture('meteora');original=rows[0]
        large=[]
        for i in range(2):
            payload=copy.deepcopy(original.payload);payload['diagnostic_padding']='x'*(9*1024*1024)
            row=replace(original,identity=original.identity+':large:'+str(i),payload=payload)
            self.h.ingest([row]);self.drain();large.append(row)
        self.life.demote('meteora',address,reason='quiet');self.drain();cold=ScopedRetirement(self.h)
        first=cold.retire(limit=64);self.assertEqual(first['retired_records'],2)
        self.assertIsNotNone(first['oldest_unretired_scope'])
        # Row count 64 is not enough: the second large row remains hot until a
        # separate batch so every archive fits the bounded verified loader.
        self.assertEqual(cold.retire(limit=64)['retired_records'],1)
        self.restart();cold=ScopedRetirement(self.h)
        self.assertEqual(cold.restore('meteora',address),3)
        for row in large:
            body=self.state.writer.db.execute('SELECT body FROM canonical_evidence WHERE identity=?',(row.identity,)).fetchone()[0]
            self.assertEqual(json.loads(body),row.body())

    def test_partial_history_never_advances_checkpoint_or_marks_a_window_complete(self):
        address,rows=self.ingest_fixture('meteora');slot=rows[0].slot
        self.h.request('meteora',address,slot,slot+2,priority=3,deadline=NOW+150);job=self.h.plan()[0]
        self.h.commit_page(job,dict(data=[],paginationToken='still-more'),finalized_through=slot+2)
        self.life.publish()
        self.assertIsNone(self.state.writer.db.execute('SELECT slot FROM candidate_checkpoints').fetchone())
        with closing(EvidenceReader(self.path)) as reader:
            self.assertFalse(CandidateReader(reader,'meteora',address).covered(coverage_scope('meteora',address),slot,slot+2,as_of=NOW))
        self.restart();job=self.h.plan()[0]
        self.assertEqual(job['token'],'still-more');self.assertEqual(job['deadline'],NOW+150)
        self.h.commit_page(job,dict(data=[]),finalized_through=slot+2);self.life.publish()
        self.assertEqual(self.state.writer.db.execute('SELECT slot FROM candidate_checkpoints').fetchone()[0],slot+2)

    def test_restart_repairs_only_missing_intervals_with_original_position_priority(self):
        for family,address,priority in [('pump','candidate',4),('meteora','position',1)]:
            self.seed(family,address)
            scope=coverage_scope(family,address)
            self.h.prove(IntervalProof(scope,100,110,'alchemy_finalized_repair','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=110,lineage_hash=digest([scope,110])),NOW))
            self.life.checkpoint(scope,110,digest([scope,110]))
        self.restart()
        desired=[dict(family=f,address=a,scope=coverage_scope(f,a),priority=p,lower_slot=100,deadline=NOW+150)
                 for f,a,p in [('pump','candidate',4),('meteora','position',1)]]
        self.life.repair(desired,120);job=self.h.plan()[0]
        self.assertEqual((job['address'],job['lo'],job['hi'],job['deadline']),('position',111,120,NOW+150))
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],2)
        self.life.repair(desired,120)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],2)

    def test_curve_creation_upgrade_reuses_native_mint_identity_before_and_after_restart(self):
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_program_decoders import pump_events
        txs=FIXTURE['pump'];created=next(e for e in pump_events(txs[0]) if e['event_type']=='create')
        curve,mint=created['bonding_curve'],created['mint'];lo=min(t['slot'] for t in txs);hi=max(t['slot'] for t in txs)
        for native_first in (False,True):
            with self.subTest(native_first=native_first):
                self.state.writer.close();self.path=Path(self.tmp.name)/('alias-'+str(native_first))/'canonical.sqlite'
                self.state,self.h=state_at(self.path,lambda:self.now[0]);self.life=self.h.lifecycle
                if native_first:self.h.bind('pump',mint)
                self.seed('pump',curve,lo);self.life.promote('pump',curve,deadline=NOW+150,lower_slot=lo)
                old_scope=self.h.scope_for('pump',curve);self.life.pin(old_scope,'continuation','current_survivor',lo)
                self.h.request('pump',curve,lo,hi,priority=1,deadline=NOW+150)
                async def acquire():
                    source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
                    async def work(fn,priority=1,**kw):return fn(self.state)
                    async def rpc(method,params,family,priority=4):
                        if method=='getSlot':source.stop.set();return hi
                        return dict(data=copy.deepcopy(txs))
                    source.work=work;source.measured_rpc=rpc
                    from tests.test_solana_prewarm_startup import quiet_model_b
                    boot_done=asyncio.Event();boot_done.set();await quiet_model_b(work,boot_done)
                    await source.acquire()
                asyncio.run(acquire());self.drain();self.restart()
                actual=self.h.scope_for('pump',curve)
                self.assertEqual(self.h.bind('pump',mint),actual)
                self.assertEqual(self.state.writer.db.execute('SELECT scope,lower_slot FROM candidate_evidence_pins').fetchone(),(actual,lo))
                self.state.writer.interest('position','program:pump',lower_slot=lo,priority=0,lifecycle='open')
                self.state.writer.db.execute('INSERT INTO service_interests VALUES(?,?,?,?)',('position','program:pump',mint,'account'))
                desired=plan_live(self.state)
                self.assertTrue(desired);self.assertTrue(all(r['scope']==actual for r in desired))
                with closing(EvidenceReader(self.path)) as reader:
                    candidate=CandidateReader(reader,'pump',mint)
                    self.assertEqual(candidate.scope,actual)
                    self.assertTrue(candidate.covered(actual,lo,hi,as_of=NOW))
                    records=candidate.window(actual,lo,hi,as_of=NOW,address=mint)
                    self.assertGreater(len(records),0)
                self.assertEqual(ScopedRetirement(self.h).retire()['retired_records'],0)

    def test_native_creation_lookup_uses_canonical_point_reads_without_market_scan(self):
        from meme_machine.solana_program_decoders import pump_events
        from meme_machine.solana_selective_history import ConsumerReader
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape
        tx=FIXTURE['pump'][0];event=next(e for e in pump_events(tx) if e['event_type']=='create')
        rows=economic_records('pump',event['mint'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
        for row in rows:self.h.rolling.store(row)
        db=self.state.writer.db
        with self.state.writer.transaction():
            db.executemany('INSERT INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('unrelated-'+str(n),'program:pump',n,'','',0,0,0,'event',None,'',NOW,None) for n in range(5000)])
            # One identity used the PK, but a realistic multi-identity mint made
            # SQLite choose the whole-program ordering index again. These same
            # token identities are not creation events and cannot change it.
            db.executemany('INSERT INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('token-fact-'+str(n),'program:pump',n,'','',0,0,0,'transaction',None,'',NOW,None) for n in range(10)])
            db.executemany('INSERT INTO rolling_economic_addresses VALUES(?,?)',
                [('token-fact-'+str(n),event['mint']) for n in range(10)])
        with closing(EvidenceReader(self.path)) as original:
            reader=ConsumerReader(original);plane=SimpleNamespace(reader=reader,clock=lambda:self.now[0])
            tape=LocalPumpTape(plane);steps=[];original.db.set_progress_handler(lambda:steps.append(1) or 0,1000)
            created=tape.creation(event['mint']);original.db.set_progress_handler(None,0)
            self.assertEqual(created,dict(event,available_time=int(NOW)))
            self.assertLess(len(steps),2,'one token lookup rescanned retained market content')
            self.now[0]=NOW-1
            self.assertIsNone(tape.creation(event['mint']))
            self.now[0]=NOW;self.assertEqual(tape.creation(event['mint']),created)
        self.restart()
        with closing(EvidenceReader(self.path)) as original:
            tape=LocalPumpTape(SimpleNamespace(reader=ConsumerReader(original),clock=lambda:NOW))
            self.assertEqual(tape.creation(event['mint']),created)

    def test_large_creation_identity_set_retains_original_query_fallback(self):
        from meme_machine.solana_program_decoders import pump_events
        from meme_machine.solana_selective_history import ConsumerReader
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape
        tx=FIXTURE['pump'][0];event=next(e for e in pump_events(tx) if e['event_type']=='create')
        for row in economic_records('pump',event['mint'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair'):self.h.rolling.store(row)
        db=self.state.writer.db
        with self.state.writer.transaction():
            db.executemany('INSERT INTO rolling_economic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('same-address-'+str(n),'program:pump',n,'','',0,0,0,'transaction',None,'',NOW,None) for n in range(2049)])
            db.executemany('INSERT INTO rolling_economic_addresses VALUES(?,?)',
                [('same-address-'+str(n),event['mint']) for n in range(2049)])
        with closing(EvidenceReader(self.path)) as original:
            statements=[];original.db.set_trace_callback(statements.append)
            tape=LocalPumpTape(SimpleNamespace(reader=ConsumerReader(original),clock=lambda:NOW))
            self.assertEqual(tape.creation(event['mint']),dict(event,available_time=int(NOW)))
            self.assertTrue(any('JOIN canonical_evidence' in sql for sql in statements))


class StructuralCensusTests(unittest.TestCase):
    def test_quiet_census_resumes_cursor_and_retains_both_wsol_orientations(self):
        import base64,hashlib
        from meme_machine.postgrad import WSOL
        from meme_machine.solana_selective_source import SelectiveSource,PROGRAMS,require_certified,PRODUCTION_BLOCKERS
        def account(address,x,y):
            raw=bytearray(152);raw[:8]=hashlib.sha256(b'account:LbPair').digest()[:8]
            raw[88:120]=pump.un58(x);raw[120:152]=pump.un58(y)
            return dict(pubkey=address,account=dict(owner=PROGRAMS['meteora'],data=[base64.b64encode(raw).decode(),'base64']))
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'canonical.sqlite')
            async def census(*,restart=False):
                source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
                async def work(fn,priority=6,**kw):return fn(state)
                async def rpc(method,params,family,priority=6):
                    self.assertEqual(method,'getProgramAccountsV2');options=params[1]
                    self.assertEqual(options['dataSlice'],dict(offset=0,length=152))
                    self.assertEqual(options['filters'][-1]['memcmp']['bytes'],WSOL)
                    x=options['filters'][-1]['memcmp']['offset']==88
                    if not restart:
                        source.stop.set()
                        return dict(context=dict(slot=100),value=dict(accounts=[account('quiet-x',WSOL,pump.PROGRAM)],paginationKey='resume-me'))
                    if x:
                        self.assertEqual(options['paginationKey'],'resume-me')
                        rows=[account('quiet-x2',WSOL,pump.PROGRAM),account('double-wsol',WSOL,WSOL)]
                    else:
                        self.assertNotIn('paginationKey',options);rows=[account('quiet-y',pump.PROGRAM,WSOL)]
                    return dict(context=dict(slot=101),value=dict(accounts=rows))
                source.work=work;source.measured_rpc=rpc;source.canonical_path=str(h.writer.path)
                from tests.test_solana_prewarm_startup import quiet_model_b
                boot_done=asyncio.Event();boot_done.set();await quiet_model_b(work,boot_done)
                await source.structural_census()
            asyncio.run(census())
            self.assertEqual(state.writer.db.execute('SELECT cursor,status FROM structural_census WHERE label=\'m\'').fetchone(),('resume-me','pending'))
            state.writer.close();state,h=state_at(Path(d)/'canonical.sqlite')
            try:
                asyncio.run(census(restart=True))
                while h.lifecycle.flush():pass
                self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM candidate_lifecycle').fetchone()[0],3)
                self.assertTrue(all(r[0]=='cheap_retained' for r in state.writer.db.execute('SELECT state FROM candidate_lifecycle')))
                with closing(CandidateHistory(h.lifecycle.path,clock=lambda:NOW)) as shared:
                    self.assertEqual(shared.pending(),0)
                    self.assertEqual(shared.candidate('meteora','quiet-x')['first_observed'],int(NOW))
                self.assertEqual(PRODUCTION_BLOCKERS,())
                with self.assertRaisesRegex(Exception,'continuous_profile'):require_certified()
            finally:state.writer.close()


class WebSocketHandoffTests(ClosureTests):
    def test_ack_precedes_replay_fence_and_rebuild_overlap_is_idempotent(self):
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_candidate_join import scope_labels
        tx=FIXTURE['pump'][1];mint=__import__('meme_machine.solana_program_decoders',fromlist=['pump_events']).pump_events(tx)[0]['mint']
        self.seed('pump',mint,tx['slot']);scope=coverage_scope('pump',mint);trace=[]
        desired=[dict(family='pump',address=mint,scope=scope,priority=1,lower_slot=tx['slot'],deadline=NOW+150)]
        async def run_once():
            source=SelectiveSource(SimpleNamespace(credential='offline',stream_url='offline'),None,token='offline')
            source.stop=asyncio.Event();local_stop=asyncio.Event();slot_calls=[0]
            async def work(fn,priority=1,**kwargs):return fn(self.state)
            async def rpc(method,params,family,priority=4):
                trace.append(method)
                if method=='getSlot':
                    slot_calls[0]+=1
                    return tx['slot']-1 if slot_calls[0]==1 else tx['slot']
                self.assertIn('ack',trace)
                self.assertEqual(params[1]['filters']['slot']['lte'],tx['slot'])
                return dict(data=[copy.deepcopy(tx)])
            source.work=work;source.measured_rpc=rpc
            class Socket:
                def __init__(self):self.queue=asyncio.Queue()
                async def send(self,raw):
                    request=json.loads(raw);self.queue.put_nowait(json.dumps(dict(id=request['id'],result=17)))
                    # An overlapping live delivery is paid even though replay
                    # delivers the same immutable economic event again.
                    self.queue.put_nowait(json.dumps(dict(params=dict(subscription=17,result=dict(context=dict(slot=tx['slot']),
                        value=dict(signature=tx['transaction']['signatures'][0],logs=tx['meta']['logMessages'],err=None))))))
                async def recv(self):
                    raw=await self.queue.get()
                    if 'id' in json.loads(raw):trace.append('ack')
                    return raw
            class Connection:
                async def __aenter__(self):return Socket()
                async def __aexit__(self,*args):pass
            async def native(channel,request,handler,family,local_stop):
                trace.append('native_replay')
                label=scope_labels({mint:scope})[scope]
                u=pb.SubscribeUpdate(filters=[label]);u.transaction_status.slot=tx['slot'];u.transaction_status.index=tx['transactionIndex'];u.transaction_status.signature=based58.b58decode(tx['transaction']['signatures'][0].encode())
                await handler(u,u.ByteSize(),NOW)
                for slot in (tx['slot'],tx['slot']+1):
                    u=pb.SubscribeUpdate(filters=['b']);b=u.block_meta;b.slot=slot;b.parent_slot=slot-1;b.blockhash='h'+str(slot);b.parent_blockhash='h'+str(slot-1);b.block_time.timestamp=tx['blockTime'];b.executed_transaction_count=tx['transactionIndex']+1
                    await handler(u,u.ByteSize(),NOW)
                    u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
                    await handler(u,u.ByteSize(),NOW)
            source.stream=native
            with patch('meme_machine.solana_selective_source.connect',lambda *a,**k:Connection()):
                await source.live(None,desired,local_stop)
        asyncio.run(run_once());count=self.state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
        self.assertGreater(count,0);self.assertLess(trace.index('ack'),trace.index('getTransactionsForAddress'))
        # An unfinished recovery archive must keep this covered island from
        # becoming a falsely complete durable handoff checkpoint.
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        trace.clear();asyncio.run(run_once())
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],count)
        self.assertGreater(self.state.writer.db.execute("SELECT raw_bytes FROM provider_delivery WHERE transport='websocket'").fetchone()[0],0)


class CrashBoundaryTests(unittest.TestCase):
    def test_hard_process_death_at_commit_history_and_checkpoint_boundaries(self):
        for boundary in ('before_canonical','after_canonical','after_history','after_checkpoint'):
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as d:
                path=Path(d)/'canonical.sqlite'
                child=subprocess.run([sys.executable,'-m','tests.test_solana_closure','crash',str(path),boundary],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(child.returncode,73,child.stderr)
                state,h=state_at(path);life=h.lifecycle
                try:
                    canonical_before=state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
                    self.assertEqual(canonical_before==0,boundary=='before_canonical')
                    if boundary!='after_checkpoint':self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
                    tx=FIXTURE['pump'][0];event=next(e for e in __import__('meme_machine.solana_program_decoders',fromlist=['pump_events']).pump_events(tx) if e['event_type']=='create')
                    rows=economic_records('pump',event['bonding_curve'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
                    h.ingest(rows)
                    while life.flush():pass
                    life.publish()
                    self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],len(rows))
                    with closing(CandidateHistory(life.path,clock=lambda:NOW)) as shared:
                        events=shared.events('pump',event['mint'])
                        self.assertEqual(len(events),len(rows));self.assertEqual(len({e['identity'] for e in events}),len(rows))
                finally:state.writer.close()

    def test_all_eight_restart_states_preserve_age_work_deadline_and_economic_decisions(self):
        for stage in ('cheap_retained','reactivated','queued','warming','history_backfill','qualified_unfunded','funded_reserved','current_rejected_survivor'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as d:
                path=Path(d)/'canonical.sqlite'
                child=subprocess.run([sys.executable,'-m','tests.test_solana_closure','state',str(path),stage],capture_output=True,text=True,timeout=10)
                self.assertEqual(child.returncode,73,child.stderr)
                state,h=state_at(path)
                try:
                    while h.lifecycle.flush():pass
                    with closing(CandidateHistory(h.lifecycle.path,clock=lambda:NOW)) as shared:
                        self.assertEqual(shared.candidate('pump','mint')['first_observed'],int(NOW-100))
                        self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
                        for deadline, in shared.db.execute('SELECT deadline FROM work'):self.assertEqual(deadline,NOW+150)
                        before=shared.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0]
                        if stage=='funded_reserved':
                            row=shared.db.execute('SELECT id FROM decisions').fetchone()[0]
                            shared.record_funding(row,'pump','mint',status='funded',at=int(NOW+2))
                            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM funding').fetchone()[0],before)
                        if stage=='current_rejected_survivor':self.assertTrue(shared.candidate('pump','mint')['metadata']['survivor_eligible'])
                        # Each state reconstructs precisely the missing suffix,
                        # including original archive work/deadline after death.
                        scope=coverage_scope('pump','mint')
                        h.bind('pump','mint')
                        desired=[dict(family='pump',address='mint',scope=scope,
                            priority=1 if stage=='funded_reserved' else 4,lower_slot=100,deadline=NOW+150)]
                        h.lifecycle.repair(desired,110)
                        job=h.plan()[0]
                        self.assertEqual((job['lo'],job['hi'],job['deadline']),(100,110,NOW+150))
                        h.commit_page(job,dict(data=[]),finalized_through=110);h.lifecycle.publish()
                        self.assertEqual(h.lifecycle.missing(scope,100,110),[])
                        if stage=='warming':
                            # An abandoned active lease returns to EDF without
                            # manufacturing a fresh candidate or deadline.
                            with shared.transaction():shared.db.execute("UPDATE work SET lease_until=? WHERE id='original-work'",(NOW-1,))
                            restored=shared.claim('replacement-worker',now=NOW)
                            self.assertEqual(restored['id'],'original-work');self.assertEqual(restored['deadline'],NOW+150)
                finally:state.writer.close()


class PositiveMeteoraTests(unittest.TestCase):
    def test_authenticated_positive_full_reference_and_native_minimal_path(self):
        from engineering.solana_closure.replay_positive import run
        result=run(Path(__file__).parent/'fixtures/solana_positive_meteora')
        self.assertEqual(result['full_vector'],result['minimal_vector'])
        self.assertTrue(result['full_qualification']['passes']);self.assertTrue(result['minimal_qualification']['passes'])
        self.assertTrue(result['trigger']['authenticated']);self.assertGreater(result['trigger']['slot'],result['trigger']['compatibility_slot'])
        self.assertEqual(len(result['chunks']),12);self.assertGreater(result['lead_time_margin_seconds'],0)
        self.assertEqual(result['transaction_body_rpc_fetches'],0)


def crash_child(path,boundary):
    state,h=state_at(path);tx=FIXTURE['pump'][0]
    event=next(e for e in __import__('meme_machine.solana_program_decoders',fromlist=['pump_events']).pump_events(tx) if e['event_type']=='create')
    h.bind('pump',event['bonding_curve'],market_address=event['mint'],aliases=(event['mint'],))
    rows=economic_records('pump',event['bonding_curve'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
    if boundary=='before_canonical':
        with state.writer.source_frame():h.ingest(rows);os._exit(73)
    h.ingest(rows)
    scope=coverage_scope('pump',event['bonding_curve'])
    with state.writer.transaction():h.lifecycle.defer_proof(IntervalProof(scope,tx['slot'],tx['slot'],
        'alchemy_finalized_repair','a'*64,dict(finalized=True,complete=True,scope=scope,
        lower_slot=tx['slot'],upper_slot=tx['slot'],lineage_hash=digest([scope,tx['slot']])),NOW))
    if boundary=='after_canonical':os._exit(73)
    while h.lifecycle.flush():pass
    if boundary=='after_history':os._exit(73)
    h.lifecycle.publish();os._exit(73)


def state_child(path,stage):
    state,h=state_at(path)
    h.observe('pump','mint',slot=100,signature='',seen=NOW-100,fields={})
    while h.lifecycle.flush():pass
    with closing(CandidateHistory(h.lifecycle.path,clock=lambda:NOW)) as shared:
        shared.append_event('pump','mint',identity='pregraduation',slot=100,transaction_index=1,event_index=0,
            market_time=int(NOW-100),kind='pump_create',payload=dict(survivor_eligible=True))
        if stage in ('queued','warming','history_backfill'):
            work=shared.enqueue('pump','mint',kind='history',ready_at=NOW,deadline=NOW+150,estimate_seconds=1,identity='original-work')
            if stage=='warming':shared.claim('dead-worker',now=NOW)
        if stage in ('qualified_unfunded','funded_reserved','current_rejected_survivor'):
            ident=shared.record_decision('pump','mint',mode='current',observed_at=int(NOW),
                qualified=stage!='current_rejected_survivor',decision=dict(stage=stage))
            if stage=='funded_reserved':shared.record_funding(ident,'pump','mint',status='funded',at=int(NOW))
            if stage=='current_rejected_survivor':shared.observe('pump','mint',surface='pumpswap',observed_at=int(NOW),metadata=dict(survivor_eligible=True))
        if stage=='history_backfill':h.request('pump','mint',100,110,priority=3,deadline=NOW+150)
        if stage=='reactivated':h.lifecycle.wake('pump','mint',slot=101,seen=NOW,signature='new',evidence={})
    os._exit(73)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='crash':crash_child(Path(sys.argv[2]),sys.argv[3])
    elif len(sys.argv)>1 and sys.argv[1]=='state':state_child(Path(sys.argv[2]),sys.argv[3])
    else:unittest.main()
