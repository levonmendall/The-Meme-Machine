"""Observed WS handoff boundaries with disposable state and offline transports.

These are bookkeeping/completeness counterexamples, never mainnet recovery
proofs. The real live coordinator still chooses its floor and performs cleanup.
"""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine import solana_selective_source as source_module
from meme_machine.solana_evidence_plane import IntervalProof,digest
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.yellowstone import geyser_pb2 as pb
from tests.test_solana_closure import state_at,NOW


class RollingStartupGapBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=[NOW]
        self.state,self.h=state_at(Path(self.tmp.name)/'canonical.sqlite',lambda:self.now[0])
        self.addCleanup(self.state.writer.close)
        self.desired=[dict(family=f,address=PROGRAMS[f],scope=program_scope(f),priority=6,
            deadline=NOW+150,lower_slot=0,rolling=True) for f in ('pump','pumpswap')]

    def protected(self):
        # Include historical failure bytes and durable ACK/proof/checkpoint
        # stores; a new gap has no authority to alter any of them.
        tables=('records','lineage','cursors','coverage','gaps','consumers','interest_checkpoints',
            'candidate_coverage','candidate_pending_proofs','candidate_checkpoints',
            'candidate_history_outbox','rolling_economic_events','service_health')
        return {table:self.h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            for table in tables}

    def prefix(self):
        return self.h.db.execute('''SELECT scope,lo,hi,created,repaired FROM candidate_gaps
            WHERE reason='rolling_partial_subscription_prefix' ORDER BY scope''').fetchall()

    def handoff(self,tip=262,floor=265,desired=None):
        source_module.preserve_subscription_handoff(self.state,
            self.desired if desired is None else desired,tip,rolling_floor=floor)

    async def live_handoff(self,tip=262,frontiers=(263,264),*,native_slots=(),after_commit=None):
        source=source_module.SelectiveSource(
            SimpleNamespace(credential='offline',identity='a'*64,stream_url='offline'),None)
        source.stop=asyncio.Event();local_stop=asyncio.Event();requests=[];rpc=[];committed=asyncio.Event()
        async def work(fn,priority=2,**options):
            value=fn(self.state)
            if options.get('component')=='candidate':committed.set()
            return value
        async def measured_rpc(method,*args):
            rpc.append(method);self.assertEqual(method,'getSlot');return tip
        source.work=work;source.measured_rpc=measured_rpc

        class Socket:
            def __init__(socket):
                socket.acks=asyncio.Queue();socket.frontiers=iter(enumerate(frontiers,11))
            async def send(socket,raw):
                request=json.loads(raw)
                await socket.acks.put(json.dumps(dict(id=request['id'],result=request['id']+10)))
            async def recv(socket):
                if not socket.acks.empty():return await socket.acks.get()
                first=next(socket.frontiers,None)
                if first is None:await asyncio.Event().wait()
                subscription,slot=first
                # Failed transactions provide real finalized delivery frontiers
                # without pretending that their content is economic evidence.
                return json.dumps(dict(params=dict(subscription=subscription,result=dict(
                    context=dict(slot=slot),value=dict(err={'InstructionError':[0,0]},
                        signature='offline-failed',logs=[])))))
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        async def stream(channel,request,handler,family,closed):
            requests.append(request.from_slot)
            for slot in native_slots:
                update=pb.SubscribeUpdate(filters=['b']);meta=update.block_meta
                meta.slot=slot;meta.parent_slot=slot-1
                meta.blockhash=str(slot);meta.parent_blockhash=str(slot-1)
                meta.block_time.timestamp=int(NOW)
                await handler(update,update.ByteSize(),NOW)
                update=pb.SubscribeUpdate(filters=['f'])
                update.slot.slot=slot;update.slot.parent=slot-1;update.slot.status=pb.SLOT_FINALIZED
                await handler(update,update.ByteSize(),NOW)
            if native_slots:
                while source.source_drain['queues']['rolling']['committed']<len(native_slots):
                    committed.clear();await asyncio.wait_for(committed.wait(),1)
            if after_commit is not None:await after_commit(source,handler)
            local_stop.set()
        source.stream=stream
        before=self.protected()
        with patch('meme_machine.solana_selective_source.connect',lambda *args,**kw:Connection()):
            await asyncio.wait_for(source.live(None,self.desired,local_stop),2)
        self.assertEqual(rpc,['getSlot','getSlot'])
        self.assertEqual(requests,[max(frontiers)+1])
        if not native_slots and after_commit is None:self.assertEqual(self.protected(),before)
        self.assertEqual(source.source_drain['unpreserved_sessions'],0)
        self.assertEqual(source.source_drain['queues']['rolling'],
            dict(accepted=len(native_slots),committed=len(native_slots)))
        return source

    def assert_prefix(self):
        self.assertEqual(self.prefix(),sorted((r['scope'],263,264,NOW,None) for r in self.desired))
        for row in self.desired:
            self.assertEqual(self.h.rolling.missing(row['family'],row['scope'],263,264),[(263,264)])

    async def test_actual_live_old_open_gap_cannot_omit_observed_partial_prefix(self):
        self.now[0]=NOW-20
        for row in self.desired:self.h.gap(row['scope'],200,None,'old_disconnect')
        self.now[0]=NOW
        await self.live_handoff()
        self.assert_prefix()
        old=self.h.db.execute("SELECT lo,hi,created,repaired FROM candidate_gaps WHERE reason='old_disconnect'").fetchall()
        self.assertEqual(old,[(200,262,NOW-20,None)]*2)
        tails=self.h.db.execute("SELECT lo,hi FROM candidate_gaps WHERE reason='candidate_live_disconnect_or_filter_rebuild'").fetchall()
        self.assertEqual(tails,[(265,None)]*2)

    async def test_actual_live_first_start_preserves_prefix_without_any_existing_gap(self):
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_gaps').fetchone()[0],0)
        await self.live_handoff()
        self.assert_prefix()

    async def test_actual_live_already_closed_replay_gap_retains_original_bounds_and_timing(self):
        self.now[0]=NOW-10
        for row in self.desired:self.h.gap(row['scope'],200,262,'rolling_reconnect_missing_websocket_history')
        old=self.h.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall()
        self.now[0]=NOW
        await self.live_handoff()
        self.assert_prefix()
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_gaps WHERE id<=2 ORDER BY id').fetchall(),old)

    async def test_actual_live_http_tip_at_or_ahead_of_ws_floor_adds_no_new_prefix(self):
        await self.live_handoff(tip=266)
        self.assertEqual(self.prefix(),[])

    def latest_tails(self):
        return self.h.db.execute('''SELECT scope,lo,hi FROM candidate_gaps
            WHERE reason='candidate_live_disconnect_or_filter_rebuild'
            ORDER BY id DESC LIMIT 2''').fetchall()

    async def test_actual_live_disconnect_keeps_proved_current_island_behind_old_gap(self):
        await self.live_handoff(native_slots=(265,266))
        self.assert_prefix()
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_checkpoints').fetchall(),[])
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],266,None) for r in self.desired))
        for row in self.desired:
            self.assertEqual(self.h.rolling.missing(row['family'],row['scope'],265,265),[])
            self.assertEqual(self.h.rolling.missing(row['family'],row['scope'],264,266),[(264,264),(266,266)])

    async def test_actual_live_unsealed_first_block_never_moves_disconnect_to_head_plus_one(self):
        await self.live_handoff(native_slots=(265,))
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],265,None) for r in self.desired))
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_coverage').fetchall(),[])
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_checkpoints').fetchall(),[])

    async def test_actual_live_old_session_is_not_a_current_session_proved_prefix(self):
        await self.live_handoff(native_slots=(265,266))
        old=self.h.db.execute('SELECT * FROM candidate_blocks ORDER BY scope').fetchall()
        await self.live_handoff()
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_blocks ORDER BY scope').fetchall(),old)
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],265,None) for r in self.desired))

    async def test_actual_live_incomplete_current_prefix_preserves_the_lower_obligation(self):
        async def unavailable(source,handler):
            for row in self.desired:self.h.gap(row['scope'],265,265,'offline_current_history_unavailable')
        await self.live_handoff(native_slots=(265,266),after_commit=unavailable)
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],265,None) for r in self.desired))
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_checkpoints').fetchall(),[])

    async def test_actual_live_pending_consumer_ack_blocks_a_higher_disconnect_boundary(self):
        async def pending(source,handler):
            for row in self.desired:
                self.h.lifecycle.emit(row['family'],'offline-pending','canonical',dict(record=dict(slot=265)),at=NOW)
        await self.live_handoff(native_slots=(265,266),after_commit=pending)
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],265,None) for r in self.desired))
        for row in self.desired:
            self.assertIsNotNone(self.h.lifecycle.unconsumed(row['scope'],through=265))

    async def test_actual_live_interrupted_earlier_handler_overrides_proved_prefix(self):
        async def interrupted(source,handler):
            number=source.handlers.accept('offline-interrupted',handler.source_session,
                'yellowstone','shared','block_meta',NOW,slot=265,
                scopes=tuple(row['scope'] for row in self.desired))
            source.handlers.fail(number,asyncio.CancelledError())
        await self.live_handoff(native_slots=(265,266),after_commit=interrupted)
        self.assertEqual(sorted(self.latest_tails()),sorted((r['scope'],265,None) for r in self.desired))
        retained=json.loads(self.h.db.execute("SELECT value FROM service_health WHERE key='source_handler_recovery'").fetchone()[0])
        self.assertEqual(len(retained['records']),1)
        self.assertEqual(retained['records'][0]['state'],'RECOVERABLE')
        self.assertEqual(retained['records'][0]['slot'],265)

    async def test_disconnect_prefix_helper_keeps_nonfresh_checkpoint_rule_unchanged(self):
        await self.live_handoff(native_slots=(265,266))
        for row in self.desired:
            session=self.h.db.execute('SELECT session FROM candidate_blocks WHERE scope=?',(row['scope'],)).fetchone()[0]
            self.assertEqual(source_module.subscription_disconnect_lower(
                self.h,row,265,session,fresh_rolling=False),265)
            self.assertEqual(source_module.subscription_disconnect_lower(
                self.h,dict(row,rolling=False),265,session,fresh_rolling=True),265)

    def test_nonfresh_handoff_and_other_shards_preserve_original_boundary_behavior(self):
        other=dict(self.desired[0],scope='candidate:pump:other-shard',rolling=False)
        future=dict(self.desired[0],scope='candidate:pump:future-shard',rolling=False)
        self.now[0]=NOW-10
        for row,lo in ((self.desired[0],200),(other,200),(future,270)):
            self.h.gap(row['scope'],lo,None,'old_disconnect')
        before=self.h.db.execute('SELECT * FROM candidate_gaps WHERE scope!=?',(self.desired[0]['scope'],)).fetchall()
        self.now[0]=NOW
        self.handoff(floor=None,desired=[self.desired[0]])
        self.assertEqual(self.prefix(),[])
        self.assertEqual(self.h.db.execute('SELECT lo,hi,created,repaired FROM candidate_gaps WHERE scope=?',
            (self.desired[0]['scope'],)).fetchone(),(200,262,NOW-10,None))
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_gaps WHERE scope!=?',(self.desired[0]['scope'],)).fetchall(),before)

    def test_fresh_prefix_is_only_for_rolling_scopes_and_excludes_complete_floor(self):
        nonrolling=dict(self.desired[0],scope='candidate:pump:held-position',rolling=False)
        self.handoff(desired=[*self.desired,nonrolling])
        self.assert_prefix()
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE scope=?',
            (nonrolling['scope'],)).fetchone()[0],0)
        self.assertFalse(any(lo<=265 and (hi is None or hi>=265) for lo,hi in
            self.h.db.execute('SELECT lo,hi FROM candidate_gaps')))

    def test_adjacent_or_earlier_floor_never_creates_empty_or_reversed_prefix(self):
        for floor in (261,262,263):
            with self.subTest(floor=floor):self.handoff(floor=floor)
        self.assertEqual(self.prefix(),[])

    def test_gap_does_not_change_proofs_checkpoints_pending_acks_or_historical_failure(self):
        scope=self.desired[0]['scope']
        # Explicitly synthetic old proof: new uncertainty must not overwrite
        # its bytes or make the same proof imply current subscription coverage.
        self.h.prove(IntervalProof(scope,263,264,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=263,upper_slot=264,
                lineage_hash=digest(['offline',scope,263,264])),NOW-2))
        self.h.lifecycle.defer_proof(IntervalProof(scope,10,11,'alchemy_finalized_stream','a'*64,
            dict(finalized=True,complete=True,scope=scope,lower_slot=10,upper_slot=11,
                lineage_hash=digest(['offline',scope,10,11])),NOW-2))
        self.h.db.execute('INSERT INTO candidate_checkpoints VALUES(?,?,?,?)',(scope,250,'old-receipt',NOW-5))
        self.h.db.execute('INSERT INTO cursors VALUES(?,?,?)',('native:offline',250,NOW-5))
        self.h.lifecycle.emit('pump','offline-mint','canonical',dict(record=dict(slot=251)),at=NOW-1)
        self.state.fence.health('source_drain',dict(state='RECOVERY_REQUIRED',accepted=7,settled=5))
        before=self.protected()
        self.assertEqual(self.h.rolling.missing('pump',scope,263,264),[])
        self.handoff()
        self.assertEqual(self.protected(),before)
        self.assertEqual(self.h.rolling.missing('pump',scope,263,264),[(263,264)])
        self.assertEqual(self.h.rolling.missing('pump',scope,263,264,as_of=NOW-1),[])
        self.assertIsNotNone(self.h.lifecycle.unconsumed(scope,through=264))

    def test_failed_prefix_recording_rolls_back_old_gap_closure_and_all_new_prefixes(self):
        for row in self.desired:self.h.gap(row['scope'],200,None,'old_disconnect')
        before=self.h.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall()
        gap=self.h.gap;calls=[]
        def fail_second(*args):
            calls.append(args)
            if len(calls)==2:raise RuntimeError('offline_gap_write_failure')
            return gap(*args)
        with patch.object(self.h,'gap',side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,'offline_gap_write_failure'):self.handoff()
        self.assertEqual(self.h.db.execute('SELECT * FROM candidate_gaps ORDER BY id').fetchall(),before)
        self.assertFalse(self.h.db.in_transaction)
