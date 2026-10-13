"""Model B reuses canonical truth; fixtures prove parity, never live rates."""
from contextlib import closing
import copy,json,os,tempfile,time,unittest,zlib
from pathlib import Path
from unittest.mock import patch
from tests.test_solana_closure import state_at,NOW
from tests.test_solana_selective_evidence import FIXTURE
from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable,IntervalProof,digest
from meme_machine.solana_selective_history import CandidateReader,PROGRAMS,economic_records,coverage_scope
from meme_machine.solana_rolling_history import program_scope
from meme_machine.runtime.candidate_history import CandidateHistory

class RollingPrewarmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.now=[NOW];self.state,self.h=state_at(self.path,lambda:self.now[0])
    def tearDown(self):self.state.writer.close();self.tmp.cleanup()
    def seal(self,scope,lo,hi):
        self.h.lifecycle.defer_proof(IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([scope,lo,hi])),self.now[0]))
        while self.h.lifecycle.flush():pass
        self.h.lifecycle.publish()
    def pump(self):
        txs=FIXTURE['pump'];rows=[]
        for tx in txs:
            # Real captured logs, authentic native index, NO transaction body.
            minimal={k:copy.deepcopy(tx[k]) for k in ('slot','blockTime','transactionIndex')}
            minimal.update(transaction=dict(signatures=tx['transaction']['signatures']),
                meta=dict(err=tx['meta']['err'],logMessages=tx['meta']['logMessages']))
            rows.extend(economic_records('pump',PROGRAMS['pump'],minimal,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream'))
        self.h.ingest(rows);self.seal(program_scope('pump'),txs[0]['slot'],txs[-1]['slot'])
        mint=next(r.payload['event']['mint'] for r in rows if r.payload['event']['event_type']=='create')
        return mint,rows
    def test_program_pending_membership_matches_original_query_and_uses_slot_index(self):
        life=self.h.lifecycle;scope=program_scope('pump')
        with self.state.writer.transaction():
            identity=life.emit('pump','mint','canonical',dict(record=dict(slot=101)),at=NOW)
            life.emit('pump','mint','activity',dict(slot=99),at=NOW)
            life.emit('pumpswap','other','canonical',dict(record=dict(slot=100)),at=NOW)
        captured=[];self.h.db.set_trace_callback(captured.append)
        for through in (None,99,100,101,200):
            bound='' if through is None else " AND (kind!='canonical' OR json_extract(body,'$.record.slot')<=?)"
            params=('pump',) if through is None else ('pump',through)
            original=self.h.db.execute("SELECT 1 FROM candidate_history_outbox WHERE family=? AND kind='canonical' AND consumed IS NULL"+bound+' LIMIT 1',params).fetchone()
            self.assertEqual(life.unconsumed(scope,through=through),original)
        statement=next(sql for sql in reversed(captured) if 'candidate_history_outbox' in sql and "$.record.slot" in sql and "kind!='canonical'" not in sql)
        self.h.db.set_trace_callback(None)
        plan=self.h.db.execute('EXPLAIN QUERY PLAN '+statement).fetchall()
        self.assertTrue(any('candidate_history_canonical_pending' in row[-1] and '<expr>' in row[-1] for row in plan),plan)
        with self.state.writer.transaction():
            self.h.db.execute('UPDATE candidate_history_outbox SET consumed=? WHERE id=?',(NOW+1,identity))
        self.assertIsNone(life.unconsumed(scope,through=200))
        # Noncanonical obligations still block their own candidate. They never
        # disappear just because program publication has no pending economics.
        self.assertIsNotNone(life.unconsumed(coverage_scope('pump','mint'),through=100))
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertIsNone(self.h.lifecycle.unconsumed(scope,through=200))
        self.assertIsNotNone(self.h.lifecycle.unconsumed(coverage_scope('pump','mint'),through=100))

    def test_publication_alias_lookup_uses_exact_scope_index_after_restart(self):
        scope=self.h.bind('pump','curve',market_address='mint',aliases=('mint',))
        self.h.bind('pump','unrelated',market_address='other-mint',aliases=('other-mint',))
        self.h.bind('pumpswap','pool',market_address='mint')
        query='SELECT address FROM evidence_bindings WHERE family=? AND coverage_scope=?'
        expected={'curve','mint'}
        self.assertEqual({r[0] for r in self.h.db.execute(query,('pump',scope))},expected)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertEqual({r[0] for r in self.h.db.execute(query,('pump',scope))},expected)
        plan=self.h.db.execute('EXPLAIN QUERY PLAN '+query,('pump',scope)).fetchall()
        self.assertTrue(any('evidence_binding_coverage_lookup' in row[-1] and 'coverage_scope=?' in row[-1] for row in plan),plan)

    def test_creation_boundary_lookup_does_not_scan_retained_candidates(self):
        mint,rows=self.pump();scope=self.h.scope_for('pump',mint)
        lo=min(r.slot for r in rows);hi=max(r.slot for r in rows)
        with self.state.writer.transaction():
            self.h.db.executemany('INSERT INTO evidence_bindings VALUES(?,?,?,?,?,?)',
                [('pump','retained-'+str(n),'old-'+str(n),'program:pump',
                  coverage_scope('pump','old-'+str(n)),'{}') for n in range(5000)])
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        steps=[0]
        def bounded():steps[0]+=100;return int(steps[0]>3000)
        self.h.db.set_progress_handler(bounded,100)
        try:
            self.assertEqual(self.h.rolling.missing('pump',scope,0,hi),[])
        finally:self.h.db.set_progress_handler(None,0)
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM evidence_bindings WHERE address LIKE 'retained-%'").fetchone()[0],5000)
        # The indexed creation lookup retains availability and fresh gap checks.
        self.assertEqual(self.h.rolling.missing('pump',scope,0,hi,as_of=NOW-1),[(0,hi)])
        self.h.gap(program_scope('pump'),lo,hi,'offline_reorganization')
        self.assertEqual(self.h.rolling.missing('pump',scope,0,hi),[(lo,hi)])

    def test_same_observation_slot_reuses_only_the_same_command_publication_answer(self):
        with self.state.writer.transaction():
            for n in range(400):
                address='waiting-'+str(n)
                self.h.observe('pump',address,slot=100+n%2,signature='',seen=NOW,fields={})
                self.h.bind('pump',address)
                self.h.db.execute('INSERT INTO rolling_boundary_waits VALUES(?,?,?,?,?,?,?,?)',
                    ('pump',address,100+n%2,110,NOW+150,4,NOW,'pending'))
        original=self.h.rolling.missing
        with patch.object(self.h.rolling,'missing',wraps=original) as missing:
            self.h.rolling.resume_boundaries()
            self.assertEqual(missing.call_count,2)
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM rolling_boundary_waits WHERE status='pending' AND deadline=?",(NOW+150,)).fetchone()[0],400)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.seal(program_scope('pump'),100,101)
        with patch.object(self.h.rolling,'missing',wraps=original) as missing:
            self.h.rolling.resume_boundaries()
            questions=[c for c in missing.call_args_list if c.args[1]==program_scope('pump') and c.args[2:]==(100,100)]
            self.assertGreaterEqual(len(questions),1)
        # The old creation/history deficit remains required. A new same-slot
        # publication answer never promotes incomplete economics into entry.
        self.assertGreater(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],0)

    def test_bounded_wait_turns_visit_every_obligation_and_preserve_restart_deadlines(self):
        for method,table in (('resume_boundaries','rolling_boundary_waits'),
                ('resume_publication','rolling_publication_waits')):
            with self.subTest(method=method):
                with self.state.writer.transaction():
                    for n in range(53):
                        address=method+'-'+str(n);self.h.bind('pump',address)
                        self.h.db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?,?,?)',
                            ('pump',address,100,110,NOW+10,4,NOW,'pending'))
                visited=set();cursor=0
                for _ in range(7):
                    selected=self.h.rolling.pending_slice(table,
                        'family,address',limit=8,after=cursor)
                    self.assertLessEqual(len(selected),8)
                    cursor=getattr(self.h.rolling,method)(limit=8,after=cursor)
                    self.assertEqual(cursor,selected[-1][0])
                    visited.update(r[2] for r in selected)
                self.assertEqual(len(visited),53)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM '+table+" WHERE status='pending' AND deadline=?",(NOW+10,)).fetchone()[0],53)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
                # A new obligation and an old unresolved one are both reached
                # after wrap; a restart cannot grant a new evidence/deadline.
                self.h.db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?,?,?)',
                    ('pump',method+'-new',100,110,NOW+10,4,NOW,'pending'))
                selected=self.h.rolling.pending_slice(table,'family,address',limit=8,after=cursor)
                self.assertIn(method+'-new',[r[2] for r in selected])
                self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
                self.now[0]=NOW+11;cursor=0
                while self.h.db.execute('SELECT 1 FROM '+table+" WHERE status='pending' LIMIT 1").fetchone():
                    cursor=getattr(self.h.rolling,method)(limit=8,after=cursor)
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM '+table+" WHERE status='deadline_missed' AND deadline=?",(NOW+10,)).fetchone()[0],54)
                self.now[0]=NOW

    def test_program_branch_is_not_read_twice_but_candidate_branch_is_preserved(self):
        scope=program_scope('pump');candidate=self.h.bind('pump','one-mint')
        self.assertEqual(self.h.rolling.scopes('pump',scope),(scope,))
        self.assertEqual(self.h.rolling.scopes('pump',candidate),(candidate,scope))
        self.seal(scope,100,101);self.seal(candidate,102,103)
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,104),[(104,104)])
        self.h.gap(scope,101,101,'native_outage')
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,104),[(101,101),(104,104)])

    def test_compact_proof_reuse_still_checks_new_gaps_bytes_and_availability(self):
        from meme_machine import solana_rolling_history as module
        from meme_machine.solana_evidence_plane import EvidenceConflict
        scope=program_scope('pump');candidate=self.h.bind('pump','cache-mint')
        self.seal(scope,100,103)
        original=module.coverage_points
        with patch.object(module,'coverage_points',wraps=original) as decoder:
            self.assertEqual(self.h.rolling.missing('pump',candidate,100,104),[(104,104)])
            decoded=decoder.call_count
            self.assertEqual(self.h.rolling.missing('pump',candidate,100,104),[(104,104)])
            self.assertEqual(decoder.call_count,decoded)
        # The same immutable proofs cannot hide a newly observed outage.
        self.h.gap(scope,101,102,'native_outage')
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,104),[(101,102),(104,104)])
        # Future/past calls do not gain publication-time authority from a cache.
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,104,as_of=NOW-1),[(100,104)])
        with self.state.writer.transaction():
            self.h.db.execute('UPDATE candidate_coverage SET points=? WHERE scope=?',(b'corrupt',scope))
        with self.assertRaisesRegex(EvidenceConflict,'candidate_coverage_corrupt'):
            self.h.rolling.missing('pump',candidate,100,104)

    def test_compact_proof_cache_is_bounded_and_restart_has_no_cached_verdict(self):
        scope=program_scope('pump')
        for n in range(12):
            self.seal(scope,100+n*2,100+n*2)
            self.h.rolling.missing('pump',scope,100,125)
        self.assertLessEqual(len(self.h.rolling._coverage_span_cache),8)
        expected=self.h.rolling.missing('pump',scope,100,125)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertFalse(hasattr(self.h.rolling,'_coverage_span_cache'))
        self.assertEqual(self.h.rolling.missing('pump',scope,100,125),expected)

    def test_mutable_tail_reuses_only_freshly_authenticated_immutable_prefix(self):
        import hashlib
        from meme_machine import solana_rolling_history as module
        from meme_machine.solana_evidence_plane import EvidenceConflict
        scope=program_scope('pump');candidate=self.h.bind('pump','growing-proof-mint')
        def replace(lo,points):
            packed=zlib.compress(json.dumps(points).encode())
            with self.state.writer.transaction():
                self.h.db.execute('INSERT OR REPLACE INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (scope,lo,max(p[1] for p in points),len(points),min(p[2] for p in points),
                     max(p[2] for p in points),packed,hashlib.sha256(packed).hexdigest(),'offline-prefix','offline'))
        replace(100,[[100,199,NOW]]);replace(200,[[200,299,NOW]]);replace(300,[[300,300,NOW]])
        with patch.object(module,'coverage_points',wraps=module.coverage_points) as decoded:
            self.assertEqual(self.h.rolling.missing('pump',candidate,100,303),[(301,303)])
            self.assertEqual(decoded.call_count,3)
            replace(300,[[300,300,NOW],[301,301,NOW+1]])
            before=decoded.call_count
            self.assertEqual(self.h.rolling.missing('pump',candidate,100,303,as_of=NOW+1),[(302,303)])
            self.assertEqual(decoded.call_count-before,1)
            # Appending a separate proof also reuses the exact verified prefix.
            replace(302,[[302,302,NOW+1]])
            before=decoded.call_count
            self.assertEqual(self.h.rolling.missing('pump',candidate,100,303,as_of=NOW+1),[(303,303)])
            self.assertEqual(decoded.call_count-before,1)
        # A cached union never overrides availability, a new gap, or corruption.
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,303,as_of=NOW),[(301,303)])
        self.h.gap(scope,150,160,'new-outage')
        self.assertEqual(self.h.rolling.missing('pump',candidate,100,303,as_of=NOW+1),[(150,160),(303,303)])
        with self.state.writer.transaction():
            self.h.db.execute('UPDATE candidate_coverage SET points=? WHERE scope=? AND lo=100',(b'corrupt',scope))
        with self.assertRaisesRegex(EvidenceConflict,'candidate_coverage_corrupt'):
            self.h.rolling.missing('pump',candidate,100,303,as_of=NOW+1)

    def test_large_immutable_proof_cohort_retains_only_bounded_compact_spans(self):
        import hashlib,sys
        from meme_machine import solana_rolling_history as module
        scope=program_scope('pumpswap');candidate=self.h.bind('pumpswap','large-proof-pool')
        packed_bytes=0
        # More than the former 64-KiB input cutoff, with a small exact union.
        # These synthetic proofs exercise representation size, not market rates.
        with self.state.writer.transaction():
            for part in range(4):
                lo=100+part*4096;hi=lo+4095
                points=[[lo+n,lo+n,NOW-((part*4096+n)*7919%16381)/10000] for n in range(4096)]
                packed=zlib.compress(json.dumps(points).encode());packed_bytes+=len(packed)
                self.h.db.execute('INSERT INTO candidate_coverage VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (scope,lo,hi,0,min(p[2] for p in points),max(p[2] for p in points),
                     packed,hashlib.sha256(packed).hexdigest(),'synthetic-proof-cohort','offline'))
        self.assertGreater(packed_bytes,64*1024)
        with patch.object(module,'coverage_points',wraps=module.coverage_points) as decoded:
            self.assertEqual(self.h.rolling.missing('pumpswap',candidate,100,16483),[])
            calls=decoded.call_count;self.assertEqual(calls,4)
            self.assertEqual(self.h.rolling.missing('pumpswap',candidate,100,16483),[])
            self.assertEqual(decoded.call_count,calls)
        for key,compact in self.h.rolling._coverage_span_cache.items():
            self.assertIsInstance(key,bytes);self.assertEqual(len(key),32)
            retained=(sys.getsizeof(key)+sys.getsizeof(compact)+sys.getsizeof(compact[0])+
                sys.getsizeof(compact[1])+sys.getsizeof(compact[2])+sum(sys.getsizeof(s)+sum(sys.getsizeof(n) for n in s)
                for s in compact[0]))
            self.assertLessEqual(retained,64*1024)
        self.h.gap(scope,103,106,'new-outage-after-cache-hit')
        self.assertEqual(self.h.rolling.missing('pumpswap',candidate,100,16483),[(103,106)])
        # Original point-in-time availability is still applied to every point.
        self.assertEqual(self.h.rolling.missing('pumpswap',candidate,100,16483,as_of=NOW-2),[(100,16483)])
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertFalse(hasattr(self.h.rolling,'_coverage_span_cache'))
        self.assertEqual(self.h.rolling.missing('pumpswap',candidate,100,16483),[(103,106)])

    def test_gap_sweep_matches_original_subtraction_for_overlapping_outages(self):
        import random
        from meme_machine.solana_rolling_history import _subtract_intervals
        rng=random.Random(381)
        for _ in range(100):
            covered=[tuple(sorted((rng.randrange(200),rng.randrange(200)))) for n in range(30)]
            gaps=[tuple(sorted((rng.randrange(200),rng.randrange(200)))) for n in range(75)]
            original=[]
            for a,b in covered:
                pieces=[(a,b)]
                for x,y in gaps:
                    if x>b or y<a:continue
                    pieces=[p for c,d in pieces for p in ((c,min(d,x-1)),(max(c,y+1),d)) if p[0]<=p[1]]
                original.extend(pieces)
            expected={slot for a,b in original for slot in range(a,b+1)}
            actual=_subtract_intervals(covered,gaps)
            self.assertEqual({slot for a,b in actual for slot in range(a,b+1)},expected)
            self.assertTrue(all(a<=b for a,b in actual))
            self.assertTrue(all(actual[n][1]+1<actual[n+1][0] for n in range(len(actual)-1)))
        self.assertEqual(_subtract_intervals([(1,10),(20,30)],[(5,25)]),[(1,4),(26,30)])

    def test_observation_lease_refresh_commits_once_and_rollback_retains_identities(self):
        with self.state.writer.transaction():
            for n in range(400):
                address='lease-'+str(n)
                self.h.observe('pump',address,slot=100,signature='',seen=NOW,fields={})
                self.h.lifecycle.promote('pump',address,deadline=NOW+1)
        self.now[0]=NOW+2;real=self.h.lifecycle.emit;count=[0]
        def fault(*args,**kwargs):
            result=real(*args,**kwargs);count[0]+=1
            if count[0]==10:raise EvidenceUnavailable('offline_lease_disposition_failure')
            return result
        with patch.object(self.h.lifecycle,'emit',side_effect=fault),self.assertRaises(EvidenceUnavailable):
            self.h.lifecycle.refresh()
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state='queued'").fetchone()[0],400)
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='demoted'").fetchone()[0],0)
        statements=[];self.h.db.set_trace_callback(statements.append)
        try:self.h.lifecycle.refresh()
        finally:self.h.db.set_trace_callback(None)
        self.assertEqual(sum(s=='COMMIT' for s in statements),1)
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM candidate_lifecycle WHERE state='demoted' AND first_seen=?",(NOW,)).fetchone()[0],400)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='demoted'").fetchone()[0],400)

    def test_expired_wait_backlog_commits_once_per_owner_command_without_coverage(self):
        deadline=NOW-1
        with self.state.writer.transaction():
            for n in range(200):
                address='expired-'+str(n)
                self.h.db.execute('INSERT INTO rolling_boundary_waits VALUES(?,?,?,?,?,?,?,?)',
                    ('pump',address,100,110,deadline,4,NOW-150,'pending'))
                self.h.db.execute('INSERT INTO rolling_publication_waits VALUES(?,?,?,?,?,?,?,?)',
                    ('pump',address,100,110,deadline,4,NOW-150,'pending'))
        statements=[];self.h.db.set_trace_callback(statements.append)
        try:
            self.h.rolling.resume_boundaries();self.h.rolling.resume_publication()
        finally:self.h.db.set_trace_callback(None)
        self.assertEqual(sum(s=='COMMIT' for s in statements),2)
        for table in ('rolling_boundary_waits','rolling_publication_waits'):
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM '+table+" WHERE status='deadline_missed' AND deadline=?",(deadline,)).fetchone()[0],200)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_observations').fetchone()[0],400)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM rolling_publication_waits WHERE status='deadline_missed'").fetchone()[0],200)
    def test_wait_disposition_failure_rolls_back_original_deadlines_and_diagnostics(self):
        for method,table,values in (
                ('resume_boundaries','rolling_boundary_waits',('pump','one',100,110,NOW-1,4,NOW-150,'pending')),
                ('resume_publication','rolling_publication_waits',('pump','one',100,110,NOW-1,4,NOW-150,'pending'))):
            with self.subTest(method=method):
                self.h.db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?,?,?)',values)
                original=self.h._observation
                def fail_after_diagnostic(*args,**kwargs):
                    original(*args,**kwargs)
                    raise EvidenceUnavailable('offline_disposition_failure')
                with patch.object(self.h,'_observation',side_effect=fail_after_diagnostic),self.assertRaises(EvidenceUnavailable):
                    getattr(self.h.rolling,method)()
                self.assertFalse(self.h.db.in_transaction)
                self.assertEqual(self.h.db.execute('SELECT status,deadline FROM '+table).fetchone(),('pending',NOW-1))
                self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_observations').fetchone()[0],0)
                getattr(self.h.rolling,method)()
                self.assertEqual(self.h.db.execute('SELECT status,deadline FROM '+table).fetchone(),('deadline_missed',NOW-1))
                self.h.db.execute('DELETE FROM acquisition_observations')
    def test_pending_canonical_fence_ignores_consumed_history_without_ignoring_obligations(self):
        scope=program_scope('pump');db=self.h.db
        raw=json.dumps(dict(record=dict(slot=99),available=NOW-100))
        with self.state.writer.transaction():
            db.executemany('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,?,?,?,?)',
                [('consumed-'+str(n),'pump','old','canonical',raw,digest(json.loads(raw)),NOW-100,NOW-1,0)
                 for n in range(30000)])
            future=json.dumps(dict(record=dict(slot=101),available=NOW))
            db.execute('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,?,?,?,?)',
                ('pending','pump','current','canonical',future,digest(json.loads(future)),NOW,None,0))
        steps=[0]
        def bound():steps[0]+=100;return int(steps[0]>5000)
        db.set_progress_handler(bound,100)
        try:
            self.assertIsNone(self.h.lifecycle.unconsumed(scope,through=100))
            self.assertIsNotNone(self.h.lifecycle.unconsumed(scope,through=101))
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_checkpoint_ahead_of_history'):
                self.h.lifecycle.checkpoint(scope,101,digest([scope,101]))
        finally:db.set_progress_handler(None,0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],30001)
        self.assertIsNone(db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',(scope,)).fetchone())
        db.execute('UPDATE candidate_history_outbox SET consumed=? WHERE id=?',(NOW,'pending'))
        self.assertIsNone(self.h.lifecycle.unconsumed(scope,through=101))
        # A recovered unresolved obligation is visible after restart; neither
        # index membership nor a prior negative lookup is reused as evidence.
        db.execute("UPDATE candidate_history_outbox SET consumed=NULL WHERE id='consumed-1'")
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.assertIsNotNone(self.h.lifecycle.unconsumed(scope,through=100))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox').fetchone()[0],30001)
    def test_first_sight_meteora_installs_history_before_promotion_without_rpc_or_entry(self):
        from meme_machine.solana_selective_source import plan_live
        self.h.observe('meteora','pool',slot=100,signature='',seen=NOW,fields=dict(wsol_pair_locator=True,activity=False))
        desired=plan_live(self.state)
        self.assertEqual([(r['address'],r['priority']) for r in desired],[('pool',5)])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.assertEqual(self.h.db.execute("SELECT state FROM candidate_lifecycle").fetchone()[0],'cheap_retained')
        self.assertFalse(self.h.db.execute('SELECT 1 FROM promotion_history_metrics').fetchone())
    def test_non_wsol_bin_locator_has_no_rich_prewarm_interest(self):
        from meme_machine.solana_selective_source import plan_live
        self.h.observe('meteora','other',slot=100,signature='',seen=NOW,fields=dict(bin_array_locator='bin',activity=False))
        self.assertEqual(plan_live(self.state),[])
    def test_body_free_shared_reservoir_and_creation_boundary_are_complete_at_promotion(self):
        mint,rows=self.pump();lo=rows[0].slot;hi=FIXTURE['pump'][-1]['slot']
        metric=self.h.rolling.prepare('pump',mint,0,hi,deadline=NOW+150)
        self.assertTrue(metric['history_already_complete_at_promotion']);self.assertEqual(metric['backfill_jobs'],[])
        with closing(EvidenceReader(self.path)) as reader:
            candidate=CandidateReader(reader,'pump',mint)
            self.assertTrue(candidate.covered(candidate.scope,0,hi,as_of=NOW))
            self.assertEqual(len(candidate.window(candidate.scope,lo,hi,as_of=NOW,address=mint)),len(rows))
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            self.assertEqual(shared.event_order_status('pump',mint)['events'],len(rows))
            self.assertEqual(len(shared.events('pump',mint)),len(rows))
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0],len(rows))

    def test_scout_before_creation_publication_waits_durably_instead_of_cold_backfill(self):
        from meme_machine.solana_program_decoders import pump_events
        creation=next(e for e in pump_events(FIXTURE['pump'][0]) if e['event_type']=='create')
        curve=creation['bonding_curve'];slot=FIXTURE['pump'][0]['slot']
        self.h.observe('pump',curve,slot=slot,signature='',seen=NOW,fields={'activity':True})
        self.h.bind('pump',curve)
        self.h.rolling.prepare('pump',curve,0,FIXTURE['pump'][-1]['slot'],deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        mint,rows=self.pump();self.now[0]+=2;self.h.rolling.resume_boundaries()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_boundary_waits').fetchone(),('resolved',NOW+150))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
    def test_only_small_missing_gap_is_requested_and_original_deadline_survives_restart(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,103);self.seal(scope,106,110)
        metric=self.h.rolling.prepare('pumpswap','pool',100,110,deadline=NOW+150)
        self.assertEqual(metric['missing_intervals'],[(104,105)])
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(104,105,NOW+150)])
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.now[0]+=10;self.h.rolling.prepare('pumpswap','pool',100,110,deadline=NOW+300)
        self.assertEqual(self.h.db.execute('SELECT lo,hi,deadline FROM acquisition_jobs').fetchall(),[(104,105,NOW+150)])

    def test_authenticated_creation_still_waits_for_unpublished_tail_across_restart(self):
        mint,rows=self.pump();hi=FIXTURE['pump'][-1]['slot'];deadline=NOW+150
        metric=self.h.rolling.prepare('pump',mint,0,hi+2,deadline=deadline)
        self.assertEqual(metric['publication_pending_intervals'],[(hi+1,hi+2)])
        self.assertEqual(metric['backfill_jobs'],[])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        self.now[0]+=5;self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_publication_waits').fetchone(),('pending',deadline))
        self.seal(program_scope('pump'),hi+1,hi+2);self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status,deadline FROM rolling_publication_waits').fetchone(),('resolved',deadline))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)

    def test_proven_closed_gap_is_repaired_while_live_tail_waits(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,103);self.seal(scope,106,110)
        metric=self.h.rolling.prepare('pumpswap','pool',100,112,deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT lo,hi FROM acquisition_jobs').fetchall(),[(104,105)])
        self.assertEqual(metric['publication_pending_intervals'],[(111,112)])
        self.assertFalse(metric['history_already_complete_at_promotion'])

    def test_first_native_membership_waits_without_coverage_and_keeps_deadline(self):
        self.h.bind('meteora','pool')
        self.h.rolling.prepare('meteora','pool',100,110,deadline=NOW+10)
        self.h.rolling.prepare('meteora','pool',100,110,deadline=NOW+150)
        self.assertEqual(self.h.db.execute('SELECT deadline FROM rolling_publication_waits').fetchone()[0],NOW+10)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],0)
        self.now[0]+=11;self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status FROM rolling_publication_waits').fetchone()[0],'deadline_missed')
        self.seal(coverage_scope('meteora','pool'),100,110);self.h.rolling.resume_publication()
        self.assertEqual(self.h.db.execute('SELECT status FROM rolling_publication_waits').fetchone()[0],'deadline_missed')
    def test_open_upper_boundary_and_unresolved_gap_never_fabricate_completeness(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,109);self.h.gap(scope,105,None,'disconnect')
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[(105,110)])
        with closing(EvidenceReader(self.path)) as reader:
            candidate=CandidateReader(reader,'pumpswap','pool')
            self.assertFalse(candidate.covered(scope,100,110,as_of=NOW))
    def test_independent_overlap_really_repairs_candidate_gap_without_global_inference(self):
        self.h.bind('pumpswap','pool');scope=coverage_scope('pumpswap','pool')
        self.seal(scope,100,110);self.h.gap(scope,105,106,'rebuild')
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[(105,106)])
        self.seal(program_scope('pumpswap'),105,106)
        self.assertEqual(self.h.lifecycle.missing(scope,100,110),[])
        self.assertEqual(self.h.lifecycle.missing(scope,100,111),[(111,111)])
    def test_seal_makes_both_independent_jobs_runnable_without_resetting_deadline(self):
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            for name in ('one','two'):
                shared.enqueue('meteora',name,kind='warmup',ready_at=NOW,deadline=NOW+150,estimate_seconds=12,priority=30,identity=name,payload={})
                shared.wait_for_history(name,'candidate:meteora:'+name,100,110,retry_at=NOW+120)
            self.assertIsNone(shared.claim('first'))
        for name in ('one','two'):
            self.h.bind('meteora',name);self.seal(coverage_scope('meteora',name),100,110)
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            a=shared.claim('first');b=shared.claim('second')
            self.assertEqual({a['id'],b['id']},{'one','two'})
            self.assertEqual([a['deadline'],b['deadline']],[NOW+150,NOW+150])
            self.assertIsNone(shared.claim('third'))
    def test_authoritative_checkpoint_does_not_seal_missing_deltas_and_survives_restart(self):
        from engineering.solana_closure.replay_positive import ReplayRPC
        from meme_machine.lanes.meteora import dlmm
        folder=Path('tests/fixtures/solana_positive_meteora');summary=json.loads((folder/'result.json').read_text())
        positive=next(x for x in summary['warmups'] if x.get('qualification',{}).get('passes'))
        rows=[json.loads(x) for x in zlib.decompress((folder/'rpc.ndjson.zlib').read_bytes()).decode().splitlines()]
        rpc=ReplayRPC(rows[positive['rpc_start_index']:]);snap=dlmm.Adapter(rpc,network_verified=True).snapshot(positive['pool'],int(positive['first_scout_time']),True,True)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            shared.checkpoint('program:meteora',positive['pool'],snap,proof=digest(snap),frontier=snap['slot'])
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            cp=shared.latest_checkpoint('program:meteora',positive['pool'],as_of=snap['available_time'])
            self.assertEqual(cp['snapshot'],snap)
            self.assertIsNone(shared.latest_checkpoint('program:meteora',positive['pool'],as_of=snap['available_time']-1))
        scope=self.h.bind('meteora',positive['pool'])
        self.assertNotEqual(self.h.lifecycle.missing(scope,snap['slot'],snap['slot']+1),[])
    def test_pinned_position_history_cannot_retire_under_storage_pressure(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump();scope=self.h.scope_for('pump',mint)
        self.h.lifecycle.pin(scope,'position','right_tail',rows[0].slot)
        retired=ScopedRetirement(self.h).retire()
        self.assertEqual(retired['retired_records'],0);self.assertGreater(retired['pinned_bytes'],0)

    def test_quiet_views_do_not_scan_whole_program_during_retirement(self):
        from dataclasses import replace
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump()
        # Deterministic storage pressure, not strategy or market evidence.
        self.h.ingest([replace(rows[-1],identity='storage-pressure:'+str(i)) for i in range(500)])
        while self.h.lifecycle.flush():pass
        self.h.lifecycle.pin(coverage_scope('pump',mint),'position','open_position',0)
        for i in range(200):self.h.bind('pump','quiet-view:'+str(i))
        steps=[0]
        def budget():
            steps[0]+=1000
            return int(steps[0]>350000)
        self.h.db.set_progress_handler(budget,1000)
        try:retired=ScopedRetirement(self.h).retire()
        finally:self.h.db.set_progress_handler(None,0)
        self.assertEqual(retired['retired_records'],0)
        self.assertGreater(retired['pinned_bytes'],0)
        self.assertLess(steps[0],350000)
    def test_normalized_history_remains_readable_after_hot_retirement(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump()
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:before=shared.events('pump',mint)
        retired=ScopedRetirement(self.h).retire()
        self.assertGreater(retired['retired_records'],0)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('pump',mint),before)
        with closing(EvidenceReader(self.path)) as reader:
            c=CandidateReader(reader,'pump',mint)
            self.assertEqual(len(c.window(c.scope,rows[0].slot,FIXTURE['pump'][-1]['slot'],as_of=NOW)),len(rows))
            from meme_machine.solana_selective_history import ConsumerReader
            self.assertEqual(len(ConsumerReader(reader).discovery(0,as_of=NOW)),len(rows))
        ScopedRetirement(self.h).restore('pump',mint)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM shared_history_cache').fetchone()[0],0)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events WHERE body IS NOT NULL').fetchone()[0],len(rows))

    def test_pump_retirement_avoids_unused_meteora_retention_scan(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        mint,rows=self.pump()
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:before=shared.events('pump',mint)
        with patch.object(self.h.rolling,'retention',side_effect=AssertionError('Meteora-only retention scanned Pump')):
            retired=ScopedRetirement(self.h).retire()
        self.assertGreater(retired['retired_records'],0)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('pump',mint),before)
        self.assertEqual(self.h.lifecycle.missing(coverage_scope('pump',mint),rows[0].slot,rows[0].slot),[])

    def test_global_raw_retirement_cannot_delete_normalized_reservoir_or_candidate_view(self):
        mint,rows=self.pump()
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:before=shared.events('pump',mint)
        # Global raw maintenance owns records/chunks, never rolling economics.
        self.h.db.execute('DELETE FROM records')
        self.h.db.execute('DELETE FROM shared_history_cache')
        self.state.writer.close();self.state,self.h=state_at(self.path,lambda:self.now[0])
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            self.assertEqual(shared.events('pump',mint),before)
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],len(rows))

    def test_model_a_migration_preserves_hash_and_original_availability(self):
        from meme_machine.solana_selective_history import SelectiveHistory
        from dataclasses import replace
        tx=FIXTURE['pump'][0]
        e=__import__('meme_machine.solana_program_decoders',fromlist=['pump_events']).pump_events(tx)[0]
        legacy=SelectiveHistory(self.state.writer,'a'*64,clock=lambda:NOW)
        rows=economic_records('pump',e['mint'],tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_repair')
        legacy.ingest(rows)
        before=self.h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence ORDER BY identity').fetchall()
        self.now[0]+=100
        self.h.ingest([replace(r,observed_at=self.now[0]) for r in rows])
        self.h.ingest([replace(r,observed_at=self.now[0]+1) for r in rows])
        self.assertEqual(self.h.db.execute('SELECT identity,hash,first_seen FROM canonical_evidence ORDER BY identity').fetchall(),before)

    def test_meteora_normalized_packet_is_shared_once_across_candidate_and_cold_views(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        capture=json.loads(Path('tests/fixtures/meteora_account_coalescence.json').read_text())
        tx=capture['transaction'];pool=capture['counterexample']['pools'][0]['pool']
        self.h.bind('meteora',pool)
        rows=economic_records('meteora',pool,tx,endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')
        self.h.ingest(rows)
        while self.h.lifecycle.flush():pass
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:
            before=shared.events('meteora',pool)
            self.assertEqual(len(before),len(rows))
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.h.db.execute('DELETE FROM records');self.h.db.execute('DELETE FROM shared_history_cache')
        self.h.ingest(rows)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('meteora',pool),before)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone()[0],len(rows))
        self.now[0]+=1000
        retired=ScopedRetirement(self.h).retire();self.assertEqual(retired['retired_records'],len(rows))
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.events('meteora',pool),before)
    def test_two_worker_limit_and_provider_filter_limit_are_unchanged_in_authority(self):
        from meme_machine.solana_selective_source import MAX_LIVE_CANDIDATES
        from meme_machine.solana_candidate_join import candidate_subscription
        addresses={PROGRAMS['meteora']:coverage_scope('meteora',PROGRAMS['meteora'])}
        request=candidate_subscription(addresses,100,full_addresses=set(addresses))
        self.assertLessEqual((MAX_LIVE_CANDIDATES-1)+3,50)
        with closing(CandidateHistory(self.h.lifecycle.path)) as shared:self.assertEqual(shared.worker_capacity,2)
        self.assertFalse(request.blocks)

    def test_quiet_group_shares_proof_but_cannot_cover_a_nonmember_or_earlier_time(self):
        from meme_machine.solana_selective_source import commit_rolling_group
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={a:coverage_scope('meteora',a) for a in ('one','two')}
        for a in addresses:self.h.bind('meteora',a)
        self.h.bind('meteora','other')
        for slot in (100,101):
            u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
            b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
            commit_rolling_group(self.state,YellowstoneTransactionFrame(u,10,NOW),addresses,'same')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],1)
        with closing(EvidenceReader(self.path)) as reader:
            for a in addresses:
                c=CandidateReader(reader,'meteora',a);self.assertTrue(c.covered(c.scope,100,100,as_of=NOW))
                self.assertFalse(c.covered(c.scope,99,100,as_of=NOW))
            c=CandidateReader(reader,'meteora','other');self.assertFalse(c.covered(c.scope,100,100,as_of=NOW))

    def test_new_program_history_starts_at_delivered_frontier_without_archive_census(self):
        import asyncio
        from types import SimpleNamespace
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.yellowstone import geyser_pb2 as pb
        calls=[];floors=[]
        async def run():
            source=SelectiveSource(SimpleNamespace(credential='offline',stream_url='offline'),None)
            source.stop=asyncio.Event();slot_calls=[0]
            async def work(fn,priority=1,**kwargs):return fn(self.state)
            async def rpc(method,params,family,priority=4):
                calls.append(method);self.assertEqual(method,'getSlot')
                slot_calls[0]+=1;return 100 if slot_calls[0]==1 else 104
            source.work=work;source.measured_rpc=rpc
            class Socket:
                def __init__(self):self.queue=asyncio.Queue();self.notifications=iter((11,12))
                async def send(self,raw):
                    request=json.loads(raw);self.queue.put_nowait(json.dumps(dict(id=request['id'],result=request['id']+10)))
                async def recv(self):
                    if not self.queue.empty():return await self.queue.get()
                    subscription=next(self.notifications,None)
                    if subscription is None:return await self.queue.get()
                    return json.dumps(dict(method='logsNotification',params=dict(subscription=subscription,
                        result=dict(context=dict(slot=105),value=dict(signature='failed',logs=[],err={'InstructionError':[0,0]})))))
            class Connection:
                async def __aenter__(self):return Socket()
                async def __aexit__(self,*args):pass
            async def native(channel,request,handler,family,local_stop):
                floors.append(request.from_slot)
                self.assertFalse(request.transactions)
                for slot in (106,107):
                    u=pb.SubscribeUpdate(filters=['b']);b=u.block_meta;b.slot=slot;b.parent_slot=slot-1
                    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
                    await handler(u,u.ByteSize(),NOW)
                    u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
                    await handler(u,u.ByteSize(),NOW)
            source.stream=native
            desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,deadline=NOW+150,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]
            with patch('meme_machine.solana_selective_source.connect',lambda *a,**kw:Connection()):await source.live(None,desired,asyncio.Event())
        asyncio.run(run())
        self.assertEqual(calls,['getSlot','getSlot']);self.assertEqual(floors,[106])
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),106,106),[])
        self.assertEqual(self.h.lifecycle.missing(program_scope('pump'),105,106),[(105,105)])

    def test_group_readiness_publication_closes_read_cursor_before_concurrent_write(self):
        from meme_machine.solana_selective_source import commit_rolling_group
        from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
        from meme_machine.yellowstone import geyser_pb2 as pb
        addresses={a:coverage_scope('meteora',a) for a in ('one','two')}
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            for a in addresses:
                self.h.bind('meteora',a)
                shared.enqueue('meteora',a,kind='warmup',ready_at=NOW,deadline=NOW+150,
                    estimate_seconds=12,priority=30,identity=a,payload={})
                shared.wait_for_history(a,addresses[a],100,100,retry_at=NOW+120)
        original=CandidateHistory.commit_history_readiness
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as other:
            def competing_write(shared,scope,*args,**kwargs):
                if scope in addresses.values():
                    other.observe('pump','concurrent',surface='pump.fun',observed_at=int(NOW))
                return original(shared,scope,*args,**kwargs)
            with patch.object(CandidateHistory,'commit_history_readiness',competing_write):
                for slot in (100,101):
                    u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
                    b.blockhash=str(slot);b.parent_blockhash=str(slot-1);b.block_time.timestamp=int(NOW)
                    commit_rolling_group(self.state,YellowstoneTransactionFrame(u,10,NOW),addresses,'same')
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM work_history_requirements').fetchone()[0],0)
            self.assertIsNotNone(shared.claim('first'));self.assertIsNotNone(shared.claim('second'))

    def test_pump_readiness_publication_batches_durable_facts_without_dropping_proofs(self):
        from meme_machine import solana_candidate_lifecycle as lifecycle
        scopes=[]
        for n in range(16):
            address='publish-'+str(n);scope=self.h.bind('pump',address);scopes.append(scope)
            self.h.lifecycle.defer_proof(IntervalProof(scope,100,100,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=100,lineage_hash=digest([scope,100])),NOW))
        while self.h.lifecycle.flush():pass
        commits=[];original=CandidateHistory
        def traced(*args,**kw):
            shared=original(*args,**kw)
            shared.db.set_trace_callback(lambda sql:commits.append(sql) if sql=='COMMIT' else None)
            return shared
        with patch.object(lifecycle,'CandidateHistory',side_effect=traced):self.h.lifecycle.publish()
        self.assertEqual(len(commits),1)
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM work_history_proofs').fetchone()[0],16)
            for scope in scopes:
                self.assertEqual(self.h.lifecycle.missing(scope,100,100),[])
                self.assertEqual(shared.db.execute('SELECT available FROM work_history_proofs WHERE scope=?',(scope,)).fetchone()[0],NOW)

    def test_pump_proof_batch_failure_cannot_publish_partial_readiness_or_coverage(self):
        scopes=[]
        for n in range(3):
            scope=self.h.bind('pump','failed-publish-'+str(n));scopes.append(scope)
            self.h.lifecycle.defer_proof(IntervalProof(scope,100,100,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=100,lineage_hash=digest([scope,100])),NOW))
        while self.h.lifecycle.flush():pass
        original=CandidateHistory.commit_history_readiness
        def fail(shared,scope,*args,**kw):
            if scope==scopes[1]:raise RuntimeError('offline_readiness_commit_fault')
            return original(shared,scope,*args,**kw)
        with patch.object(CandidateHistory,'commit_history_readiness',fail):
            with self.assertRaisesRegex(RuntimeError,'offline_readiness_commit_fault'):self.h.lifecycle.publish()
        self.assertEqual(self.state.writer.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],3)
        with closing(CandidateHistory(self.h.lifecycle.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM work_history_proofs').fetchone()[0],0)
        for scope in scopes:self.assertEqual(self.h.lifecycle.missing(scope,100,100),[(100,100)])
        self.h.lifecycle.publish()
        for scope in scopes:self.assertEqual(self.h.lifecycle.missing(scope,100,100),[])

    def test_pending_proofs_yield_after_64_and_restart_replays_every_remaining_identity(self):
        life=self.h.lifecycle;scopes=[]
        for n in range(130):
            scope=coverage_scope('pump' if n%2==0 else 'pumpswap','bounded-'+str(n));scopes.append(scope)
            life.defer_proof(IntervalProof(scope,100,100,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=100,
                    lineage_hash=digest([scope,100])),NOW))
        pending=lambda:self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0]
        life.publish();self.assertEqual(pending(),66)
        # Reconstruct only the existing consumer. Its cursor is scheduling state,
        # not canonical authority and cannot drop the remaining durable proofs.
        from meme_machine.solana_candidate_lifecycle import CandidateLifecycle
        self.h.lifecycle=CandidateLifecycle(self.h,candidate_path=life.path)
        self.h.lifecycle.publish();self.assertEqual(pending(),2)
        self.h.lifecycle.publish();self.assertEqual(pending(),0)
        with closing(CandidateHistory(life.path,clock=lambda:NOW)) as shared:
            self.assertEqual(shared.db.execute('SELECT COUNT(*) FROM work_history_proofs').fetchone()[0],130)
        for scope in scopes:self.assertEqual(self.h.lifecycle.missing(scope,100,100),[])

    def test_blocked_proof_prefix_cannot_starve_other_family_or_new_earlier_proofs(self):
        life=self.h.lifecycle;blocked=[]
        for n in range(64):
            address='blocked-'+str(n);scope=coverage_scope('pump',address);blocked.append(scope)
            life.emit('pump',address,'activity',dict(slot=100),at=NOW)
            life.defer_proof(IntervalProof(scope,100,100,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=100,
                    lineage_hash=digest([scope,100])),NOW))
        ready=coverage_scope('pumpswap','ready')
        life.defer_proof(IntervalProof(ready,101,101,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=ready,lower_slot=101,upper_slot=101,
                lineage_hash=digest([ready,101])),NOW))
        # Model an external consumer which has not yet durably ACKed its tape.
        # The real pending outbox rows must keep every earlier proof unavailable.
        with patch.object(life,'flush',return_value=0):
            life.publish()
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],65)
            earlier=coverage_scope('pumpswap','arrived-earlier')
            life.defer_proof(IntervalProof(earlier,99,99,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=earlier,lower_slot=99,upper_slot=99,
                    lineage_hash=digest([earlier,99])),NOW))
            life.publish();self.assertEqual(life.missing(ready,101,101),[])
            self.assertEqual(life.missing(earlier,99,99),[(99,99)])
            life.publish();self.assertEqual(life.missing(earlier,99,99),[])
        for scope in blocked:self.assertEqual(life.missing(scope,100,100),[(100,100)])
        # Original consumer recovery, without deleting or bypassing obligations.
        for _ in range(3):life.publish()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone()[0],0)
        for scope in blocked:self.assertEqual(life.missing(scope,100,100),[])

    def test_owner_queue_rejection_retries_the_same_frame_without_silent_loss(self):
        import asyncio
        from meme_machine.solana_selective_source import source_work
        async def run():
            stop=asyncio.Event();calls=[]
            def frame(state):return 'committed'
            async def work(fn,priority,**options):
                calls.append((fn,priority,options))
                if len(calls)==1:raise EvidenceUnavailable('evidence_control_overloaded')
                return fn(None)
            wrapped=source_work(work,stop)
            self.assertEqual(await wrapped(frame,2,label='source_commit'),'committed')
            self.assertEqual(calls,[(frame,2,{'label':'source_commit'})]*2)
            async def unavailable(*args,**kwargs):raise EvidenceUnavailable('unresolved_evidence_gap')
            with self.assertRaisesRegex(EvidenceUnavailable,'unresolved_evidence_gap'):
                await source_work(unavailable,stop)(frame,2)
        asyncio.run(run())

if __name__=='__main__':unittest.main()
