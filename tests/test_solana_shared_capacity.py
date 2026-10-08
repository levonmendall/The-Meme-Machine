"""Scheduling regressions using the actual owner, governor and native adapters."""
import asyncio,contextlib,json,os,sqlite3,tempfile,time,unittest,zlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.solana_stable_shards import StableShards
from meme_machine.runtime.governor import Governor

class SharedCapacityTests(unittest.TestCase):
    def test_separate_pump_pons_proof_counts_wire_batches_retries_and_stops_before_next_rpc(self):
        from engineering.solana_capacity.pump_pons_proof import Budget,CeilingReached
        from urllib.request import Request
        limits=json.loads(Path('operational/shared-capital-activation/provider-ceilings.proposed.json').read_text())
        limits.update(solana_rpc_requests=2,estimated_rpc_cu=40)
        with tempfile.TemporaryDirectory() as tmp:
            budget=Budget(limits,Path(tmp));physical=[];budget.original=lambda *a,**kw:physical.append(a)
            request=Request('https://solana-mainnet.g.alchemy.com/v2/OFFLINE',data=json.dumps([
                dict(jsonrpc='2.0',id=i,method='getSlot',params=[]) for i in range(2)]).encode())
            budget.open(request)
            with self.assertRaisesRegex(CeilingReached,'solana_request_ceiling'):budget.open(request)
            self.assertEqual(len(physical),1)
            self.assertEqual(budget.snapshot()['requests'],{'solana':2})
            self.assertEqual(budget.snapshot()['estimated_rpc_cu'],40)

    def test_separate_proof_denies_writes_and_unapproved_hosts_and_counts_native_payload(self):
        from engineering.solana_capacity.pump_pons_proof import Budget,CeilingReached
        from urllib.request import Request
        limits=json.loads(Path('operational/shared-capital-activation/provider-ceilings.proposed.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            for host,method in [('solana-mainnet.g.alchemy.com','sendTransaction'),('example.com','getSlot')]:
                b=Budget(limits,Path(tmp));b.original=lambda *a,**kw:self.fail('must not open a physical connection')
                request=Request('https://'+host+'/v2/OFFLINE',data=json.dumps(dict(method=method,params=[])).encode())
                with self.assertRaises(CeilingReached):b.open(request)
                self.assertEqual(b.snapshot()['requests'],{})
            limits['native_delivery_bytes']=10;b=Budget(limits,Path(tmp))
            b.delivery('delivery',dict(raw=b'12345'))
            with self.assertRaisesRegex(CeilingReached,'native_delivery_byte_ceiling'):b.delivery('delivery',dict(raw=b'123456'))
            self.assertEqual(b.snapshot()['native_delivery_bytes'],11)

    def test_proof_stops_before_full_native_allowance_with_production_frame_margin(self):
        from engineering.solana_capacity.pump_pons_proof import Budget,CeilingReached
        limits=json.loads(Path('operational/shared-capital-activation/provider-ceilings.proposed.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            b=Budget(limits,Path(tmp));b.native_bytes=48*1024*1024-2
            with self.assertRaisesRegex(CeilingReached,'inflight_margin_stop'):
                b.delivery('delivery',dict(raw=b'12'))
            self.assertLess(b.native_bytes,limits['native_delivery_bytes'])
            self.assertTrue(b.stop.is_set())

    def test_subscription_rebuild_shares_pending_history_without_claiming_coverage(self):
        from tests.test_solana_closure import state_at,NOW
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite')
            try:
                scope=h.bind('pump','curve',market_address='mint',aliases=('mint',))
                first=h.request('pump','curve',100,110,priority=4,deadline=NOW+120)
                desired=[dict(family='pump',address='mint',scope=scope,priority=1,lower_slot=100,deadline=NOW+150)]
                jobs=h.lifecycle.repair(desired,120)
                self.assertIn(first,jobs)
                self.assertEqual(h.db.execute('SELECT lo,hi,priority,deadline FROM acquisition_jobs ORDER BY lo').fetchall(),
                    [(100,110,1,NOW+120),(111,120,1,NOW+150)])
                self.assertEqual(h.lifecycle.missing(scope,100,120),[(100,120)])
                self.assertEqual(len(h.lifecycle.repair(desired,120)),2)
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM acquisition_jobs').fetchone()[0],2)
                job=h.plan()[0];h.commit_page(job,dict(data=[]),finalized_through=120);h.lifecycle.publish()
                self.assertEqual(h.lifecycle.missing(scope,100,120),[(111,120)])
            finally:state.writer.close()

    def test_partial_repair_preserves_unproved_suffix_and_original_gap_audit_after_restart(self):
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.solana_evidence_plane import IntervalProof,digest
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'c.sqlite';clock=[NOW];state,h=state_at(path,lambda:clock[0])
            scope=h.bind('pump','mint')
            def proof(lo,hi,at):return IntervalProof(scope,lo,hi,'alchemy_finalized_repair','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([lo,hi])),at)
            try:
                h.gap(scope,100,None,'disconnected')
                h.prove(proof(100,110,NOW))
                self.assertEqual(h.lifecycle.missing(scope,100,150),[(111,150)])
                self.assertEqual(h.db.execute('SELECT lo,hi,repaired FROM candidate_gaps ORDER BY id').fetchall(),[(100,None,NOW),(111,None,None)])
                h.prove(proof(100,110,NOW+1))
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()[0],2)
                state.writer.close();state,h=state_at(path,lambda:clock[0])
                self.assertEqual(h.lifecycle.missing(scope,100,150),[(111,150)])
                h.prove(proof(120,130,NOW+2))
                self.assertEqual(h.lifecycle.missing(scope,100,150),[(111,150)])
                clock[0]=NOW+2
                self.assertEqual(h.lifecycle.missing(scope,100,150),[(111,119),(131,150)])
            finally:state.writer.close()

    def test_reactivation_keeps_proven_curve_mint_binding_and_original_deadline(self):
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.solana_evidence_plane import EvidenceConflict
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'evidence.sqlite')
            try:
                h.observe('pump','curve',slot=100,signature='first',seen=NOW,
                    fields=dict(activity=False))
                scope=h.bind('pump','curve',market_address='mint',aliases=('mint',))
                first=h.lifecycle.promote('pump','curve',deadline=NOW+150,lower_slot=0)
                h.lifecycle.demote('pump','curve',reason='temporarily_quiet')
                h.lifecycle.wake('pump','curve',slot=101,seen=NOW+1,signature='later',evidence={})
                second=h.lifecycle.promote('pump','curve',deadline=NOW+150,lower_slot=0)
                self.assertNotEqual(first,second)
                self.assertEqual(h.bind('pump','curve'),scope)
                self.assertEqual(h.db.execute("SELECT market_address FROM evidence_bindings WHERE family='pump' AND address='curve'").fetchone()[0],'mint')
                self.assertEqual(h.db.execute("SELECT deadline FROM candidate_lifecycle WHERE family='pump' AND address='curve'").fetchone()[0],NOW+150)
                with self.assertRaises(EvidenceConflict):h.bind('pump','curve',market_address='other')
            finally:state.writer.close()

    def test_candidate_arrivals_and_demotion_preserve_position_subscription(self):
        planner=StableShards(3)
        def row(address,priority=4):return dict(family='meteora',address=address,priority=priority,deadline=100)
        first=planner.reconcile([row('position',1),row('a')]);position=next(n for n,g in first.items() if g['position']);identity=first[position]['identity']
        for candidates in (['a','b'],['a','b','c','d','e'],['d','e'],['e','f','g','h']):
            groups=planner.reconcile([row('position',1)]+[row(a) for a in candidates])
            self.assertEqual(groups[position]['identity'],identity)
            all_rows=[r for g in groups.values() for r in g['rows']]
            self.assertEqual({r['address'] for r in all_rows},{'position',*candidates})
            self.assertEqual(len(all_rows),len(candidates)+1)
            self.assertTrue(all(len(g['rows'])<=3 for g in groups.values()))

    def test_candidate_priority_changes_do_not_reset_continuity_session(self):
        p=StableShards();r=dict(family='pump',address='mint',priority=4,deadline=100)
        first=p.reconcile([r]);second=p.reconcile([dict(r,priority=2,deadline=95)])
        self.assertEqual(first[0]['identity'],second[0]['identity'])
        self.assertEqual(second[0]['rows'][0]['deadline'],95)

    def test_position_promotion_moves_only_affected_candidate_shard(self):
        p=StableShards(2);rows=[dict(family='pump',address=x,priority=4) for x in 'abcd']
        before=p.reconcile(rows);rows[0]['priority']=1;after=p.reconcile(rows)
        self.assertEqual(before[1]['identity'],after[1]['identity'])
        self.assertTrue(any(g['position'] and g['rows'][0]['address']=='a' for g in after.values()))

    def test_curve_to_mint_upgrade_rebuilds_only_its_coverage_namespace(self):
        p=StableShards(1)
        rows=[dict(family='pump',address=x,priority=4,scope='candidate:pump:'+x) for x in ('curve','other')]
        before=p.reconcile(rows);rows[0]['scope']='candidate:pump:mint'
        after=p.reconcile(rows)
        self.assertNotEqual(before[0]['identity'],after[0]['identity'])
        self.assertEqual(before[1]['identity'],after[1]['identity'])

    def test_solana_capacity_does_not_raise_other_provider_ceiling(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,MM_SOLANA_EVIDENCE_PLANE_DB='disposable'):
            governor=Governor(Path(d)/'g.sqlite');self.assertEqual(governor.interval,.5);self.assertEqual(governor.solana_interval,.05)
            governor.acquire('solana','candidate',4)
            with sqlite3.connect(governor.path) as db:
                sol=db.execute("SELECT next_at FROM pressure WHERE provider='solana'").fetchone()[0]
            governor.acquire('evm','existing',50)
            with sqlite3.connect(governor.path) as db:
                other=db.execute("SELECT next_at FROM pressure WHERE provider='evm'").fetchone()[0]
            self.assertGreater(other-sol,.35)
            with self.assertRaises(ValueError):Governor(Path(d)/'forbidden.sqlite',interval=.1)

    def test_structural_candidate_native_identity_uses_authoritative_snapshot(self):
        from engineering.solana_closure.replay_positive import ReplayRPC
        from meme_machine.lanes.meteora import dlmm,runner
        from meme_machine.runtime.solana_warming import install
        install(runner)
        folder=Path('tests/fixtures/solana_positive_meteora')
        result=json.loads((folder/'result.json').read_text());positive=next(r for r in result['warmups'] if r.get('qualification',{}).get('passes'))
        rows=[json.loads(s) for s in zlib.decompress((folder/'rpc.ndjson.zlib').read_bytes()).decode().splitlines()]
        rpc=ReplayRPC(rows[positive['rpc_start_index']:]);adapter=dlmm.Adapter(rpc,network_verified=True)
        candidate=dict(address=positive['pool'],provider_structural=True,decision_deadline=positive['decision_deadline'])
        with patch.object(runner,'time',SimpleNamespace(time=lambda:positive['first_scout_time'])):
            state=runner._fresh_supported_start(adapter,candidate)
        self.assertEqual((candidate['token_x'],candidate['token_y']),(state['x'],state['y']))
        self.assertEqual(candidate['decision_deadline'],positive['decision_deadline'])
        self.assertEqual(len(rpc.calls),3)

    def test_structural_deadline_is_not_rejected_by_campaign_end_estimate(self):
        from meme_machine.runtime.lifecycle_timing import install_meteora
        calls=[]
        def trigger(*args):calls.append(args);return 'native'
        module=SimpleNamespace(_triggered_warmup=trigger,_lifecycle=lambda *a:None)
        install_meteora(module);deadline=time.monotonic()+150
        self.assertEqual(module._triggered_warmup(None,dict(provider_structural=True),None,{},None,[],deadline),'native')
        self.assertEqual(calls[0][-2],deadline)
        result=module._triggered_warmup(None,dict(provider_structural=False),None,{},None,[],deadline)
        self.assertEqual(result[0]['reason'],'campaign_window_insufficient_preentry_time')

class TriggerWaitTests(unittest.TestCase):
    def test_quiet_wait_releases_worker_and_survives_restart_without_new_deadline(self):
        from meme_machine.runtime import solana_warming as warming
        from meme_machine.runtime.candidate_history import CandidateHistory
        now=time.time();clock=[now];state=dict(pool='pool',x='x',y='y',slot=100)
        module=SimpleNamespace(_fresh_supported_start=lambda *a:dict(state),
            _new_finalized_swaps=lambda *a:([],dict(head_slot=101)),
            _runtime_expired=lambda *a:False,FRESH_SWAP_TRIGGER_MAX_SECONDS=120)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(Path(d)/'history.sqlite')):
            with closing(CandidateHistory()) as history:
                history.observe('meteora','pool',surface='meteora-dlmm',observed_at=int(now))
                work=history.enqueue('meteora','pool',kind='warmup',ready_at=now,deadline=now+150,estimate_seconds=147,priority=30,payload={},identity='job')
                history.claim('worker')
            candidate=dict(address='pool',provider_structural=True,_candidate_work_id='job',decision_deadline=now+150)
            with patch.object(warming,'time',SimpleNamespace(time=lambda:clock[0])):
                baseline=warming.compatibility(module,SimpleNamespace(rpc=SimpleNamespace()),candidate)
                with self.assertRaises(warming.WarmingDeferred):warming.trigger(module,SimpleNamespace(rpc=None),candidate,baseline,{},None,[],1)
                with closing(CandidateHistory()) as recovered:
                    self.assertEqual(recovered.db.execute('SELECT status,deadline,worker FROM work').fetchone(),('pending',now+150,None))
                self.assertEqual(warming.load('job')['started'],now)
                self.assertEqual(warming.load('job')['cursor'],101)
                clock[0]=now+121
                result=warming.trigger(module,SimpleNamespace(rpc=None),candidate,baseline,{},None,[],1)
                self.assertEqual(result[0]['reason'],'fresh_swap_trigger_timeout')
                self.assertEqual(warming.load('job')['started'],now)

    def test_delayed_body_free_logs_fit_the_existing_ten_second_join_bound(self):
        from meme_machine.solana_candidate_join import CandidateTransactionJoin,CONTENT,CONTINUITY,FINALITY
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.solana_native_evidence import signature
        address='So11111111111111111111111111111111111111112';scope='candidate:pump:'+address
        join=CandidateTransactionJoin({address:scope},set(),filtered_from_slot=100)
        for slot in range(100,107):
            if slot==100:
                u=pb.SubscribeUpdate(filters=['0']);u.transaction_status.slot=slot;u.transaction_status.signature=b'1'*64;u.transaction_status.index=0
                self.assertIsNone(join.feed(u,len(u.SerializeToString()),time.time()))
            u=pb.SubscribeUpdate(filters=[CONTINUITY]);u.block_meta.slot=slot;u.block_meta.parent_slot=slot-1;u.block_meta.blockhash=str(slot);u.block_meta.parent_blockhash=str(slot-1);u.block_meta.executed_transaction_count=1 if slot==100 else 0;u.block_meta.block_time.timestamp=int(time.time())
            self.assertIsNone(join.feed(u,len(u.SerializeToString()),time.time()))
            u=pb.SubscribeUpdate(filters=[FINALITY]);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
            self.assertIsNone(join.feed(u,len(u.SerializeToString()),time.time()))
        frame=join.feed_log(100,signature(b'1'*64),['authenticated captured log'],None,time.time())
        self.assertEqual(frame.update.block.slot,100)
        self.assertEqual(len(frame.log_transactions),1)

class SourceLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_retry_counts_failed_delivery_without_resetting_candidate_deadline(self):
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.runtime.evidence_worker import DeliveredRPCError
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite')
            try:
                h.observe('meteora','pool',slot=100,signature='activity',fields=dict(wsol_pair_locator=True))
                h.lifecycle.promote('meteora','pool',deadline=NOW+150)
                calls=[]
                def read(*args):
                    calls.append(args)
                    if len(calls)==1:raise DeliveredRPCError('repair_response_unavailable',dict(bytes=7,cu=20),retryable=True,cause_kind='JSONDecodeError')
                    return 101,dict(bytes=11,cu=20)
                source=SelectiveSource(SimpleNamespace(credential=None),SimpleNamespace(call_delivered=read))
                async def work(fn,priority=1,**kw):return fn(state)
                source.work=work
                self.assertEqual(await source.measured_rpc('getSlot',[],'shared',1),101)
                self.assertEqual(h.db.execute("SELECT raw_bytes,rpc_cu,calls FROM provider_delivery WHERE family='shared'").fetchone(),(18,40,2))
                self.assertEqual(h.db.execute("SELECT deadline FROM candidate_lifecycle WHERE address='pool'").fetchone()[0],NOW+150)
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
                source.rpc.call_delivered=lambda *a:(_ for _ in ()).throw(DeliveredRPCError('repair_response_unavailable',dict(bytes=5,cu=20)))
                with self.assertRaises(DeliveredRPCError):await source.measured_rpc('getSlot',[],'shared',1)
                self.assertEqual(h.db.execute("SELECT calls FROM provider_delivery WHERE family='shared'").fetchone()[0],3)
            finally:state.writer.close()

    async def test_unsupported_archive_page_preserves_scope_gap_and_position_interest(self):
        import copy,base64
        from tests.test_solana_closure import state_at,NOW
        from tests.test_solana_selective_evidence import FIXTURE
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.solana_program_decoders import pump_events
        tx=copy.deepcopy(next(tx for tx in FIXTURE['pump'] if any(e['event_type']=='trade' for e in pump_events(tx))))
        mint=next(e['mint'] for e in pump_events(tx) if e['event_type']=='trade')
        for n,line in enumerate(tx['meta']['logMessages']):
            if line.startswith('Program data: '):
                raw=base64.b64decode(line[14:])
                if raw[:8]==bytes([189,219,127,211,78,230,97,238]):
                    tx['meta']['logMessages'][n]='Program data: '+base64.b64encode(raw[:64]).decode()
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:NOW)
            try:
                h.observe('pump',mint,slot=tx['slot'],signature='',fields={},seen=NOW);h.bind('pump',mint)
                identity=h.request('pump',mint,0,tx['slot'],priority=4,deadline=NOW+150)
                state.writer.interest('position','program:meteora',lower_slot=tx['slot'],priority=0,lifecycle='open')
                source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
                async def work(fn,*args,**kwargs):
                    result=fn(state)
                    if h.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',(identity,)).fetchone()[0]=='failed':source.stop.set()
                    return result
                async def rpc(method,*args):return dict(data=[tx]) if method=='getTransactionsForAddress' else tx['slot']
                source.work=work;source.measured_rpc=rpc
                from tests.test_solana_prewarm_startup import quiet_model_b
                boot_done=asyncio.Event();boot_done.set();await quiet_model_b(work,boot_done)
                await source.acquire()
                self.assertEqual(h.db.execute('SELECT status,deadline,error FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),('failed',NOW+150,'candidate_archive_decoder_unavailable'))
                self.assertEqual(h.db.execute('SELECT state FROM candidate_lifecycle WHERE address=?',(mint,)).fetchone(),('cheap_retained',))
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE repaired IS NULL').fetchone()[0],1)
                self.assertEqual(h.db.execute("SELECT active FROM interests WHERE owner='position'").fetchone()[0],1)
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_coverage WHERE scope=?',(h.scope_for('pump',mint),)).fetchone()[0],0)
            finally:state.writer.close()

    async def test_partial_census_page_restart_does_not_advance_cursor_or_lose_pools(self):
        import base64,hashlib
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.solana_selective_source import SelectiveSource,PROGRAMS,SCOUT_COMMIT_BATCH
        from meme_machine import pump
        from meme_machine.postgrad import WSOL
        raw=bytearray(152);raw[:8]=hashlib.sha256(b'account:LbPair').digest()[:8]
        raw[88:120]=pump.un58(WSOL);raw[120:152]=pump.un58(pump.PROGRAM)
        accounts=[dict(pubkey='pool-'+str(n),account=dict(owner=PROGRAMS['meteora'],data=[base64.b64encode(raw).decode(),'base64'])) for n in range(200)]
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:NOW)
            try:
                chunks=[];interrupt=[True];source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
                async def rpc(method,params,*args):
                    x=params[1]['filters'][-1]['memcmp']['offset']==88
                    return dict(context=dict(slot=100),value=dict(accounts=accounts if x else []))
                async def work(fn,*args,**kwargs):
                    count=h.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]
                    if interrupt[0] and count>=2*SCOUT_COMMIT_BATCH:
                        interrupt[0]=False;raise RuntimeError('injected_partial_page_crash')
                    result=fn(state)
                    updated=h.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]
                    if updated>count:chunks.append(updated-count)
                    return result
                source.work=work;source.measured_rpc=rpc
                source.canonical_path=str(h.writer.path)
                from tests.test_solana_prewarm_startup import quiet_model_b
                boot_done=asyncio.Event();boot_done.set();await quiet_model_b(work,boot_done)
                with self.assertRaisesRegex(RuntimeError,'injected_partial_page_crash'):await source.structural_census()
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM structural_census').fetchone()[0],0)
                state.writer.close();state,h=state_at(Path(d)/'c.sqlite',lambda:NOW)
                await source.structural_census()
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],200)
                self.assertTrue(all(n<=SCOUT_COMMIT_BATCH for n in chunks))
                self.assertEqual(h.db.execute("SELECT status FROM structural_census WHERE label='m'").fetchone()[0],'complete')
            finally:state.writer.close()

    async def test_scout_reconnect_reuses_original_overlap_without_coverage_claim(self):
        from meme_machine.solana_selective_source import SelectiveSource,CONTROL_OVERLAP
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        floors=[];receipts=[]
        history=SimpleNamespace(_observation=lambda *args:receipts.append(args))
        async def work(fn,*args,**kwargs):return fn(SimpleNamespace())
        async def stream(channel,request,*args):
            floors.append(request.from_slot)
            if len(floors)==1:raise EvidenceUnavailable('candidate_native_internal')
            source.stop.set()
        source.work=work;source.stream=stream
        with patch('meme_machine.solana_selective_source.install',return_value=history):
            await source.scout_stream(None,1000,None)
        self.assertEqual(floors,[1000-CONTROL_OVERLAP]*2)
        self.assertFalse(receipts[0][2]['checkpoint_advanced'])
        self.assertFalse(receipts[0][2]['economic_coverage_claim'])

    async def test_batched_delivery_counts_every_duplicate_byte(self):
        from meme_machine.solana_selective_source import SelectiveSource
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.batched=True
        totals=[]
        class Writer:
            @contextlib.contextmanager
            def transaction(self):yield
        state=SimpleNamespace(writer=Writer())
        history=SimpleNamespace(delivery=lambda *args,**kw:totals.append((args,kw)))
        async def work(fn,*a,**kw):return fn(state)
        source.work=work
        with patch('meme_machine.solana_selective_source.install',return_value=history):
            for size in (100,100,50):await source.delivered('candidate_live','yellowstone',size,1791400000.)
            self.assertFalse(totals)
            await source.flush_delivery();await source.flush_delivery()
        self.assertEqual(len(totals),1);self.assertEqual(totals[0][1]['raw_bytes'],250)

    async def test_control_reconnect_begins_before_durable_checkpoint(self):
        from meme_machine.solana_selective_source import SelectiveSource,CONTROL_OVERLAP
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        source=SelectiveSource(SimpleNamespace(credential='offline'),None);source.stop=asyncio.Event()
        checkpoints=iter((900,920));floors=[];phases=[]
        state=SimpleNamespace(writer=SimpleNamespace(db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:(next(checkpoints),)))),
                              fence=SimpleNamespace(_health=lambda *args:phases.append(args)))
        history=SimpleNamespace(_observation=lambda *a:None)
        async def work(fn,*a,**kw):return fn(state)
        async def stream(channel,request,*a):
            floors.append(request.from_slot)
            if len(floors)==1:raise EvidenceUnavailable('candidate_native_internal')
            source.stop.set()
        source.work=work;source.stream=stream
        with patch('meme_machine.solana_selective_source.install',return_value=history):
            await source.control_stream(None,1000,asyncio.Queue(64))
        self.assertEqual(floors,[900-CONTROL_OVERLAP,920-CONTROL_OVERLAP])
        self.assertIn(('phase','DEGRADED'),phases)

    async def test_completed_structural_census_keeps_live_source_running(self):
        from meme_machine.solana_selective_source import SelectiveSource
        class Channel:
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
        source=SelectiveSource(SimpleNamespace(credential='offline'),None)
        census=asyncio.Event();stop=asyncio.Event()
        async def finite():census.set()
        async def forever(*a):await stop.wait()
        async def rpc(*a):return 100
        async def work(*a,**kw):return None
        with patch('meme_machine.solana_selective_source.grpc.aio.secure_channel',return_value=Channel()),patch.object(source,'measured_rpc',rpc),patch.object(source,'structural_census',finite),patch.object(source,'stream',forever),patch.object(source,'acquire',forever),patch.object(source,'live_manager',forever),patch.object(source,'rolling_programs',forever),patch.object(source,'activity_manager',forever),patch.object(source,'cold_maintenance',forever):
            task=asyncio.create_task(source.run(work,stop))
            await census.wait();await asyncio.sleep(.01)
            self.assertFalse(task.done())
            stop.set();await asyncio.wait_for(task,1)

class DurableBatchTests(unittest.TestCase):
    def test_committed_archive_page_retry_preserves_cursor_and_rejects_changed_response(self):
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.solana_evidence_plane import EvidenceConflict
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:NOW)
            try:
                h.bind('pump','mint');identity=h.request('pump','mint',100,110,priority=4,deadline=NOW+150)
                job=h.plan()[0];response=dict(data=[],paginationToken='next-page')
                first=h.commit_page(job,response,finalized_through=110)
                state.writer.close();state,h=state_at(Path(d)/'c.sqlite',lambda:NOW+10)
                retry=h.commit_page(job,response,finalized_through=110)
                self.assertEqual(retry,first)
                self.assertEqual(h.db.execute('SELECT token,pages,deadline FROM acquisition_jobs WHERE id=?',(identity,)).fetchone(),('next-page',1,NOW+150))
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM acquisition_page_receipts').fetchone()[0],1)
                with self.assertRaisesRegex(EvidenceConflict,'candidate_archive_page_conflict'):
                    h.commit_page(job,dict(data=[],paginationToken='different-page'),finalized_through=110)
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone()[0],0)
            finally:state.writer.close()

    def test_verified_physical_refetch_restores_archived_body_without_rewriting_hash(self):
        from dataclasses import replace
        from tests.test_solana_closure import state_at,NOW
        from tests.test_solana_selective_evidence import FIXTURE
        from meme_machine.solana_program_decoders import pump_events
        from meme_machine.solana_selective_history import economic_records
        from meme_machine.solana_evidence_plane import digest,EvidenceConflict
        tx=FIXTURE['pump'][0];creation=next(e for e in pump_events(tx) if e['event_type']=='create');seen=tx['blockTime']+1
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:seen)
            try:
                rows=economic_records('pump',creation['mint'],tx,endpoint_identity='a'*64,seen=seen,source='alchemy_finalized_repair')
                h.ingest(rows);h.db.execute('UPDATE rolling_economic_events SET body=NULL')
                state.writer.close();state,h=state_at(Path(d)/'c.sqlite',lambda:seen+100)
                h.ingest([replace(r,observed_at=seen+100) for r in rows])
                self.assertEqual(h.db.execute('SELECT first_seen FROM rolling_economic_events ORDER BY identity').fetchall(),[(seen,)]*len(rows))
                self.assertTrue(all(body for body, in h.db.execute('SELECT body FROM rolling_economic_events')))
                wrong=replace(rows[0],payload=dict(rows[0].payload,event=dict(rows[0].payload['event'],wallet='wrong')))
                with self.assertRaises(EvidenceConflict):h.ingest([wrong])
            finally:state.writer.close()

    def test_selective_reconstruction_after_hot_metadata_retirement_keeps_availability(self):
        from dataclasses import replace
        from tests.test_solana_closure import state_at,NOW
        from tests.test_solana_selective_evidence import FIXTURE
        from meme_machine.solana_program_decoders import pump_events
        from meme_machine.solana_selective_history import economic_records
        from meme_machine.solana_evidence_plane import EvidenceConflict
        from meme_machine.runtime.candidate_history import CandidateHistory
        tx=FIXTURE['pump'][0];creation=next(e for e in pump_events(tx) if e['event_type']=='create');seen=tx['blockTime']+1
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:seen)
            try:
                h.bind('pump',creation['bonding_curve'],market_address=creation['mint'],aliases=(creation['mint'],))
                rows=economic_records('pump',creation['bonding_curve'],tx,endpoint_identity='a'*64,seen=seen,source='alchemy_finalized_repair')
                h.ingest(rows)
                while h.lifecycle.flush():pass
                identities=[r.identity for r in rows]
                # Reproduce globally retired, fully consumed hot metadata; the
                # compact economic receipt and ordered consumer history survive.
                for identity in identities:
                    h.db.execute('DELETE FROM addresses WHERE identity=?',(identity,))
                    h.db.execute('DELETE FROM address_refs WHERE record_id IN (SELECT rowid FROM records WHERE identity=?)',(identity,))
                    h.db.execute('DELETE FROM hot_refs WHERE identity=?',(identity,))
                    h.db.execute('DELETE FROM lineage WHERE identity=?',(identity,))
                    h.db.execute('DELETE FROM records WHERE identity=?',(identity,))
                h.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',
                    ('retention_floor:program:pump',str(tx['slot']+1)))
                state.writer.close();state,h=state_at(Path(d)/'c.sqlite',lambda:seen+150)
                h.ingest([replace(r,observed_at=seen+150) for r in rows])
                while h.lifecycle.flush():pass
                self.assertEqual(h.db.execute('SELECT DISTINCT first_seen FROM rolling_economic_events').fetchall(),[(seen,)])
                with closing(CandidateHistory(h.lifecycle.path)) as history:
                    self.assertEqual(len(history.events('pump',creation['mint'])),len(rows))
                changed=replace(rows[0],payload=dict(rows[0].payload,event=dict(rows[0].payload['event'],creator='altered')))
                with self.assertRaisesRegex(EvidenceConflict,'candidate_economic_content_conflict'):h.ingest([changed])
            finally:state.writer.close()

    def test_parallel_archive_pages_exclude_claimed_work_without_deadline_reset(self):
        from tests.test_solana_closure import state_at,NOW
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'c.sqlite',lambda:NOW)
            try:
                for address,deadline in (('a',NOW+10),('b',NOW+20),('c',NOW+30)):
                    h.bind('pump',address);h.request('pump',address,100,110,priority=4,deadline=deadline)
                first=h.plan()[0];second=h.plan(excluding=(first['id'],))[0]
                third=h.plan(excluding=(first['id'],second['id']))[0]
                self.assertEqual([r['address'] for r in (first,second,third)],['a','b','c'])
                self.assertEqual(first['deadline'],NOW+10)
                self.assertIsNone(h.plan(excluding=(first['id'],second['id'],third['id'])))
                self.assertEqual(h.plan()[0],first)
            finally:state.writer.close()

    def test_shared_lane_history_uses_independent_thread_transactions(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from meme_machine.runtime.candidate_history import open_candidate_history
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(Path(d)/'h.sqlite')):
            shared=open_candidate_history();barrier=threading.Barrier(2)
            def observe(candidate):
                connection=shared.db;barrier.wait()
                for at in range(100,110):shared.observe('meteora',candidate,surface='meteora-dlmm',observed_at=at)
                shared.close();return id(connection)
            with ThreadPoolExecutor(2) as executor:
                handles=list(executor.map(observe,('a','b')))
            self.assertEqual(len(set(handles)),2)
            self.assertEqual(len(shared.candidates()),2);shared.close()

    def test_creation_lookup_uses_slot_from_selective_canonical_record(self):
        from tests.test_solana_selective_evidence import FIXTURE
        from meme_machine.solana_program_decoders import pump_events
        from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader
        from meme_machine.solana_selective_history import SelectiveHistory,ConsumerReader,economic_records
        from meme_machine.lanes.pump.solana_evidence_runtime import LocalPumpTape
        now=1791400000.;tx=FIXTURE['pump'][0]
        creation=next(e for e in pump_events(tx) if e['event_type']=='create')
        with tempfile.TemporaryDirectory() as d:
            with closing(EvidenceWriter(Path(d)/'e.sqlite',clock=lambda:now)) as writer:
                history=SelectiveHistory(writer,'a'*64,clock=lambda:now)
                history.bind('pump',creation['bonding_curve'],market_address=creation['mint'],aliases=(creation['mint'],))
                history.ingest(economic_records('pump',creation['bonding_curve'],tx,endpoint_identity='a'*64,seen=now,source='alchemy_finalized_stream'))
                with closing(EvidenceReader(writer.path)) as reader:
                    tape=LocalPumpTape(SimpleNamespace(reader=ConsumerReader(reader),clock=lambda:now))
                    self.assertEqual(tape.creation(creation['mint'])['mint'],creation['mint'])

    def test_external_commit_before_consumed_receipt_survives_retry(self):
        from contextlib import contextmanager
        from tests.test_solana_closure import state_at,NOW
        from meme_machine.runtime.candidate_history import CandidateHistory
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'canonical.sqlite',lambda:NOW)
            try:
                for address in ('a','b','c'):
                    h.observe('meteora',address,slot=100,signature='',fields=dict(wsol_pair_locator=True),seen=NOW)
                native_transaction=state.writer.transaction
                @contextmanager
                def fail_receipt():
                    with native_transaction():
                        yield
                        raise RuntimeError('injected_receipt_crash')
                with patch.object(state.writer,'transaction',fail_receipt):
                    with self.assertRaisesRegex(RuntimeError,'injected_receipt_crash'):h.lifecycle.flush()
                self.assertEqual(h.db.execute('SELECT COUNT(*) FROM candidate_history_outbox WHERE consumed IS NULL').fetchone()[0],3)
                with closing(CandidateHistory(h.lifecycle.path)) as reader:
                    self.assertEqual(len(reader.candidates()),3)
                h.lifecycle.flush()
                with closing(CandidateHistory(h.lifecycle.path)) as reader:
                    self.assertEqual(len(reader.candidates()),3)
                    self.assertEqual(reader.db.execute('SELECT COUNT(*) FROM source_receipts').fetchone()[0],3)
                    self.assertTrue(all(r['first_observed']==NOW for r in reader.candidates()))
            finally:state.writer.close()

    def test_census_source_then_real_activity_keeps_existing_identity(self):
        from tests.test_solana_closure import state_at,NOW
        with tempfile.TemporaryDirectory() as d:
            state,h=state_at(Path(d)/'canonical.sqlite',lambda:NOW+1)
            try:
                h.observe('meteora','pool',slot=100,signature='',fields=dict(wsol_pair_locator=True,source='paginated_structural_census'),seen=NOW)
                h.observe('meteora','pool',slot=101,signature='sig',fields=dict(activity=True),seen=NOW+1)
                row=h.db.execute('SELECT first_seen,state FROM candidate_lifecycle').fetchone()
                self.assertEqual(row,(NOW,'reactivated'))
            finally:state.writer.close()

if __name__=='__main__':unittest.main()
