"""Synthetic provider inputs exercise real native parsers, not acknowledgements."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import grpc

from meme_machine.operational.isolated_native_kernel_corpus import (
    ADDITIONAL_CREATIONS,BASE_SLOT,MAX_REQUESTS,MAX_STREAMS,SAMPLED_HEAD,SCOPE,SLOTS,
    TEMPLATE_SHA256,SolanaKernelCorpus)
from meme_machine.solana_candidate_join import CandidateTransactionJoin,candidate_subscription
from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import scout_fact,scout_request
from meme_machine.solana_source_intake import candidate_log_message
from meme_machine.yellowstone import geyser_pb2 as pb


AT=1792270000


def archive_config(lower=1,upper=SAMPLED_HEAD):
    return dict(transactionDetails='full',sortOrder='asc',limit=100,
        commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,
        filters=dict(slot=dict(gte=lower,lte=upper)))


def archives(corpus,address,lower=1,upper=SAMPLED_HEAD):
    config=archive_config(lower,upper);rows=[]
    while True:
        result=corpus.rpc('getTransactionsForAddress',[address,config])
        rows.extend(result['data'])
        if result['paginationToken'] is None:return rows
        config=dict(config,paginationToken=result['paginationToken'])


def logs_request(address,number=1):
    return json.dumps(dict(jsonrpc='2.0',id=number,method='logsSubscribe',
        params=[dict(mentions=[address]),dict(commitment='finalized')])).encode()


class KernelCorpusTests(unittest.TestCase):
    def test_pinned_resource_determinism_and_no_authority_claims(self):
        from meme_machine.operational import isolated_native_kernel_corpus as module
        raw=Path(module.__file__).with_name('isolated_native_kernel_solana.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),TEMPLATE_SHA256)
        first,second=SolanaKernelCorpus(AT),SolanaKernelCorpus(AT)
        self.assertEqual(first.corpus_sha256,second.corpus_sha256)
        self.assertNotEqual(first.corpus_sha256,SolanaKernelCorpus(AT+1).corpus_sha256)
        state=first.snapshot()
        self.assertEqual(state['scope'],SCOPE)
        self.assertEqual(state['started_at'],AT)
        for key in ('financial_authority','canonical_coverage','production_equivalent','full_market_speed_proven'):
            self.assertIs(state[key],False)
        self.assertEqual(state['provider_calls'],0)
        self.assertEqual(state['consumer_acks'],'UNVERIFIED')
        self.assertEqual(state['durable_publication'],'UNVERIFIED')
        state['counters']['opened']=1000
        self.assertEqual(first.snapshot()['counters']['opened'],0)

    def test_native_rpc_decodes_rebased_create_trade_and_swap_and_returns_owned_values(self):
        corpus=SolanaKernelCorpus(AT)
        pump=[tx for tx in archives(corpus,corpus.curve) if tx['meta']['err'] is None]
        swap=[tx for tx in archives(corpus,PROGRAMS['pumpswap']) if tx['meta']['err'] is None]
        self.assertEqual(len(pump),2)
        self.assertEqual(len(swap),1)
        all_pump=[tx for tx in archives(corpus,PROGRAMS['pump']) if tx['meta']['err'] is None]
        self.assertEqual(len(all_pump),ADDITIONAL_CREATIONS+2)
        events=[event for tx in all_pump for event in pump_events(tx)]
        self.assertEqual([event['event_type'] for event in events].count('create'),ADDITIONAL_CREATIONS+1)
        self.assertEqual([event['event_type'] for event in events].count('trade'),ADDITIONAL_CREATIONS+2)
        events.extend(pumpswap_trade_events(swap[0]))
        self.assertTrue(all(event['market_time']==AT+event['slot']-SLOTS for event in events))
        self.assertEqual([tx['slot'] for tx in pump+swap],[2,3,3])
        signature=pump[0]['transaction']['signatures'][0]
        retrieved=corpus.rpc('getTransaction',[signature,dict(commitment='finalized',
            encoding='json',maxSupportedTransactionVersion=1)])
        self.assertEqual(retrieved,pump[0])
        pump[0]['meta']['logMessages'].clear()
        retrieved['transaction']['signatures'].clear()
        again=[tx for tx in archives(corpus,corpus.curve) if tx['meta']['err'] is None]
        self.assertTrue(again[0]['meta']['logMessages'])
        self.assertEqual(again[0]['transaction']['signatures'][0],signature)
        self.assertEqual(len(again[0]['transaction']['signatures']),
            again[0]['transaction']['message']['header']['numRequiredSignatures'])

    def test_paginated_program_census_tokens_bind_exact_address_and_interval(self):
        corpus=SolanaKernelCorpus(AT)
        config=archive_config()
        first=corpus.rpc('getTransactionsForAddress',[PROGRAMS['pump'],config])
        self.assertEqual(len(first['data']),100)
        token=first['paginationToken'];self.assertIsInstance(token,str)
        last=corpus.rpc('getTransactionsForAddress',[PROGRAMS['pump'],dict(config,paginationToken=token)])
        self.assertEqual(len(last['data']),ADDITIONAL_CREATIONS+3-100)
        self.assertIsNone(last['paginationToken'])
        for address,options in ((corpus.curve,config),(PROGRAMS['pump'],archive_config(2,3))):
            with self.subTest(address=address),self.assertRaises(ValueError):
                corpus.rpc('getTransactionsForAddress',[address,dict(options,paginationToken=token)])

    def test_fixed_rpc_unknown_version_scope_and_request_bounds_fail(self):
        corpus=SolanaKernelCorpus(AT)
        rejected=[('getTransactionsForAddress',[PROGRAMS['pump'],dict(archive_config(),maxSupportedTransactionVersion=0)]),
            ('getTransactionsForAddress',['foreign-account',archive_config()]),
            ('getTransactionsForAddress',[PROGRAMS['pump'],archive_config(1,BASE_SLOT+SLOTS)]),
            ('getSlot',[dict(commitment='processed')]),
            ('getBlock',[True,dict(commitment='finalized',maxSupportedTransactionVersion=1)]),
            ('getAccountInfo',[corpus.curve])]
        for method,params in rejected:
            with self.subTest(method=method),self.assertRaises(ValueError):corpus.rpc(method,params)
        bounded=SolanaKernelCorpus(AT)
        for _ in range(MAX_REQUESTS):bounded.rpc('getGenesisHash',[])
        with self.assertRaisesRegex(ValueError,'isolated_kernel_solana_corpus_contract'):
            bounded.rpc('getGenesisHash',[])
        self.assertEqual(corpus.snapshot()['counters']['unmodeled_calls'],1)


class KernelCorpusWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.corpus=SolanaKernelCorpus(AT)
        self.streams=[]

    async def asyncTearDown(self):
        for stream in self.streams:await stream.aclose()
        state=self.corpus.snapshot()['counters']
        self.assertEqual(state['opened'],state['closed'])

    async def stream(self,transport):
        stream=await self.corpus.open(transport)
        self.streams.append(stream)
        return stream

    async def test_original_scout_request_produces_locator_not_economic_history(self):
        with patch.dict(os.environ,MM_OPERATIONAL_PHASE='ISOLATED_NATIVE'):
            request=scout_request()
        raw=await self.stream('yellowstone')
        await raw.write(request.SerializeToString())
        size,body=await asyncio.wait_for(raw.read(),1)
        self.assertEqual(size,len(body))
        update=pb.SubscribeUpdate.FromString(body)
        fact=scout_fact(update,AT)
        self.assertEqual((fact['family'],fact['address'],fact['slot']),
            ('pump',self.corpus.curve,SAMPLED_HEAD))
        self.assertFalse(fact['fields']['economic_event'])
        self.assertFalse(fact['fields']['history_complete'])
        self.assertTrue(fact['fields']['activity'])
        from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY
        self.assertGreaterEqual(fact['fields']['development_upper_bps'],POLICY.min_curve_progress_bps)
        target=archives(self.corpus,self.corpus.curve)
        last=next(e for e in pump_events(target[-1]) if e['event_type']=='trade')
        self.assertEqual(fact['fields']['real_token_reserves'],last['real_token_reserves'])
        self.assertEqual(fact['signature'],target[-1]['transaction']['signatures'][0])

    async def test_body_free_wire_join_requires_actual_logs_and_preserves_native_economics(self):
        addresses={PROGRAMS['pump']:'program:pump',PROGRAMS['pumpswap']:'program:pumpswap'}
        joined=CandidateTransactionJoin(addresses,set(),filtered_from_slot=BASE_SLOT)
        websocket=await self.stream('solana_websocket')
        expected=[]
        for number,address in enumerate(addresses,1):
            await websocket.write(logs_request(address,number))
            transactions=archives(self.corpus,address)
            expected.extend(tx for tx in transactions if tx['meta']['err'] is None)
            for _ in range(1+len(transactions)):
                size,body=await asyncio.wait_for(websocket.read(),1)
                self.assertEqual(size,len(body))
                value=candidate_log_message(body,max_bytes=16*1024*1024)
                if 'id' in value:continue
                result=value['params']['result'];payload=result['value']
                # Failed subscription-prefix notifications establish only a
                # wire frontier. They do not represent economic events/statuses.
                if payload['err'] is None:
                    self.assertIsNone(joined.feed_log(result['context']['slot'],
                        payload['signature'],payload['logs'],None,AT))
        native=await self.stream('yellowstone')
        request=candidate_subscription(addresses,BASE_SLOT,full_addresses=set())
        await native.write(request.SerializeToString())
        output=[]
        while True:
            size,body=await asyncio.wait_for(native.read(),1)
            update=pb.SubscribeUpdate.FromString(body)
            frame=joined.feed(update,size,AT)
            if frame is not None:output.extend(frame.log_transactions)
            if update.WhichOneof('update_oneof')=='slot' and update.slot.slot==SLOTS:break
        self.assertEqual([row['transaction']['signatures'][0] for row in output],
            [row['transaction']['signatures'][0] for row in expected])
        decoded=lambda rows:[event for row in rows for event in (*pump_events(row),*pumpswap_trade_events(row))]
        self.assertEqual(decoded(output),decoded(expected))
        self.assertEqual(len(decoded(output)),2*ADDITIONAL_CREATIONS+4)
        self.assertEqual(joined.completed,SLOTS)
        self.assertEqual(joined.pending_bytes,0)
        # The corpus does not turn a successful parser join into source FULL,
        # native consumer ACK, financial authority or mainnet coverage.
        self.assertEqual(self.corpus.snapshot()['consumer_acks'],'UNVERIFIED')

    async def test_control_wire_covers_original_startup_overlap_and_rpc_blocks_match(self):
        head=self.corpus.rpc('getSlot',[dict(commitment='finalized')])
        from meme_machine.solana_selective_source import CONTROL_OVERLAP
        floor=max(1,head-CONTROL_OVERLAP)
        request=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=floor)
        request.blocks_meta['b'].SetInParent();request.slots['f'].filter_by_commitment=True
        native=await self.stream('yellowstone');await native.write(request.SerializeToString())
        joined=CandidateTransactionJoin({},set(),filtered_from_slot=floor)
        slots=[]
        while len(slots)<SLOTS-floor+1:
            size,body=await asyncio.wait_for(native.read(),1)
            update=pb.SubscribeUpdate.FromString(body)
            frame=joined.feed(update,size,AT)
            if frame is not None:
                block=frame.update.block;slots.append(block.slot)
                rpc=self.corpus.rpc('getBlock',[block.slot,dict(commitment='finalized',
                    encoding='json',maxSupportedTransactionVersion=1)])
                self.assertEqual((block.parent_slot,block.blockhash,block.parent_blockhash),
                    (rpc['parentSlot'],rpc['blockhash'],rpc['previousBlockhash']))
                self.assertEqual(block.executed_transaction_count,len(rpc['transactions']))
        self.assertEqual(slots,list(range(floor,SLOTS+1)))
        self.assertEqual(slots[-1],head+1) # Genuine later linked child seals sampled head.

    async def test_cancel_joins_parked_read_without_producing_eof_until_closed(self):
        native=await self.stream('yellowstone')
        reading=asyncio.create_task(native.read())
        await asyncio.sleep(0)
        self.assertFalse(reading.done())
        await native.aclose()
        self.assertIs(await asyncio.wait_for(reading,1),grpc.aio.EOF)
        native.cancel()
        self.assertEqual(self.corpus.snapshot()['counters']['closed'],1)

    async def test_stream_and_subscription_bounds_are_enforced_without_extra_owners(self):
        for _ in range(MAX_STREAMS):await self.stream('solana_websocket')
        with self.assertRaises(ValueError):await self.corpus.open('solana_websocket')
        stream=self.streams[0]
        for _ in range(8):await stream.write(logs_request(self.corpus.curve))
        with self.assertRaises(ValueError):await stream.write(logs_request(self.corpus.curve))
        with self.assertRaises(ValueError):await stream.write(b'')
        await stream.aclose()
        with self.assertRaises(ValueError):await stream.write(logs_request(PROGRAMS['pump']))


class KernelCorpusSourceConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def joined(self,corpus,addresses,*,floor):
        joined=CandidateTransactionJoin(addresses,set(),filtered_from_slot=floor)
        if addresses:
            websocket=await corpus.open('solana_websocket')
            try:
                for number,address in enumerate(addresses,1):
                    await websocket.write(logs_request(address,number))
                    for _ in range(1+len(archives(corpus,address))):
                        _,body=await websocket.read()
                        value=candidate_log_message(body,max_bytes=16*1024*1024)
                        if 'id' in value:continue
                        result=value['params']['result'];item=result['value']
                        if item['err'] is None:
                            joined.feed_log(result['context']['slot'],item['signature'],item['logs'],None,time.time())
            finally:await websocket.aclose()
        native=await corpus.open('yellowstone')
        try:
            if addresses:request=candidate_subscription(addresses,floor,full_addresses=set())
            else:
                request=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=floor)
                request.blocks_meta['b'].SetInParent();request.slots['f'].filter_by_commitment=True
            await native.write(request.SerializeToString());frames=[]
            while True:
                size,body=await native.read();update=pb.SubscribeUpdate.FromString(body)
                frame=joined.feed(update,size,time.time())
                if frame is not None:frames.append(frame)
                if update.WhichOneof('update_oneof')=='slot' and update.slot.slot==SLOTS:return frames
        finally:await native.aclose()

    async def test_same_wire_earns_native_interest_full_ack_and_real_economic_workers(self):
        """Source boundary proof; not the copied-main or Landlock acceptance."""
        from contextlib import closing
        from meme_machine import pump
        from meme_machine.lanes.pump.pump_acceleration_strategy import POLICY
        from meme_machine.lanes.pump.pump_acceleration_evidence import curve_progress_bps
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.runtime.isolated_native_executor import IsolatedSpawnExecutor
        from meme_machine.runtime.isolated_native_execution import install_isolated_native_execution
        from meme_machine.solana_evidence_plane import EvidenceWriter,canonical
        from meme_machine.solana_evidence_service import FinalizedFence,STREAM_PROCESS_DECODE_MIN_BYTES
        from meme_machine.solana_history_work import _isolated_worker_limits
        from meme_machine.solana_history_delivery import capture,deliver
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_runtime import CONTROL
        from meme_machine.solana_selective_source import (
            CandidateCommitQueue,SelectiveSource,commit_control,commit_scout,install,plan_live)
        at=int(time.time());corpus=SolanaKernelCorpus(at)
        addresses={PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
        controls=await self.joined(corpus,{},floor=1)
        frames=await self.joined(corpus,addresses,floor=2)
        heavy=next(frame for frame in frames if frame.update.block.slot==3)
        actual_bytes=heavy.source_bytes+sum(len(canonical(tx).encode()) for tx in heavy.log_transactions)
        self.assertGreaterEqual(actual_bytes,STREAM_PROCESS_DECODE_MIN_BYTES)
        self.assertLess(actual_bytes,32*1024*1024)
        self.assertEqual(len(heavy.log_transactions),ADDITIONAL_CREATIONS+2)
        for tx in heavy.log_transactions:
            self.assertLess(sum(len(line.encode())+1 for line in tx['meta']['logMessages']),10*1024)
        creations=[event for frame in frames for tx in frame.log_transactions
            for event in pump_events(tx) if event['event_type']=='create']
        self.assertEqual(len({event['mint'] for event in creations}),ADDITIONAL_CREATIONS+1)
        for event in creations:
            self.assertEqual(event['bonding_curve'],pump.pda([b'bonding-curve',pump.un58(event['mint'])]))
        target=[tx for tx in archives(corpus,corpus.curve) if tx['meta']['err'] is None]
        creation=next(event for event in pump_events(target[0]) if event['event_type']=='create')
        buys=[event for tx in target for event in pump_events(tx) if event['event_type']=='trade']
        self.assertTrue(all(event['buy'] for event in buys))
        previous=dict(virtual_token_reserves=creation['initial_virtual_token_reserves'],
            virtual_quote_reserves=creation['initial_virtual_quote_reserves'],
            real_token_reserves=creation['initial_real_token_reserves'],real_quote_reserves=0)
        for event in buys:
            self.assertEqual(previous['virtual_token_reserves']-event['tokens'],event['virtual_token_reserves'])
            self.assertEqual(previous['real_token_reserves']-event['tokens'],event['real_token_reserves'])
            self.assertEqual(previous['virtual_quote_reserves']+event['amount'],event['virtual_quote_reserves'])
            self.assertEqual(previous['real_quote_reserves']+event['amount'],event['real_quote_reserves'])
            previous=event
        self.assertGreaterEqual(curve_progress_bps(creation['initial_real_token_reserves'],
            buys[-1]['real_token_reserves']),POLICY.min_curve_progress_bps)

        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,
                MM_OPERATIONAL_PHASE='ISOLATED_NATIVE',MM_SOLANA_HISTORY_SEPARATED='1'):
            root=Path(temporary);path=root/'source.sqlite'
            writer=EvidenceWriter(path,clock=time.time)
            self.addCleanup(writer.close)
            state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))
            history=install(state);history.clock=history.lifecycle.clock=time.time
            history.startup.begin()
            # Match the real order: boot commits before native receipt clocks.
            controls=await self.joined(corpus,{},floor=1)
            frames=await self.joined(corpus,addresses,floor=2)
            for frame in controls:commit_control(state,frame)
            self.assertEqual(writer.db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0],SAMPLED_HEAD)
            self.assertFalse(history.startup.snapshot()['released'])
            scout=await corpus.open('yellowstone')
            try:
                await scout.write(scout_request().SerializeToString());_,body=await scout.read()
                commit_scout(state,pb.SubscribeUpdate.FromString(body),at)
            finally:await scout.aclose()
            self.assertEqual(history.development_candidates(POLICY.min_curve_progress_bps,16),[(corpus.curve,)])
            for family in ('pump','pumpswap'):history.startup.feed_ack(family,2,SAMPLED_HEAD)
            source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),None)
            source.stop=asyncio.Event();source.batched=True;source.history_separated=True
            source.canonical_path=str(path)
            observed=[];source.observer=lambda kind,value:observed.append((kind,value))
            stage=['publication']
            async def work(function,priority=1,**options):
                result=function(state)
                if stage[0]=='development' and writer.db.execute(
                        "SELECT 1 FROM rolling_preparation_jobs WHERE status='pending' LIMIT 1").fetchone():source.stop.set()
                if stage[0]=='history' and options.get('label')=='history_apply':source.stop.set()
                return result
            source.work=work
            decoder=IsolatedSpawnExecutor(max_workers=2,initializer=install_isolated_native_execution,role='decoder')
            historian=IsolatedSpawnExecutor(max_workers=1,initializer=_isolated_worker_limits,role='history')
            source.preparation_executor=decoder;source.historical_executor=historian
            try:
                queue=CandidateCommitQueue();done=asyncio.Event()
                for frame in frames:await queue.put(frame)
                self.assertGreaterEqual(queue.bytes,STREAM_PROCESS_DECODE_MIN_BYTES)
                done.set()
                await asyncio.wait_for(source.candidate_commits(queue,addresses,'synthetic-wire-session',
                    rolling=True,producer_done=done),20)
                preparations=[value for kind,value in observed if kind=='economic_prepared']
                self.assertEqual(len(preparations),1)
                self.assertEqual(preparations[0]['mode'],'existing_process_pool')
                self.assertEqual(preparations[0]['records'],2*ADDITIONAL_CREATIONS+4)
                self.assertEqual(len(decoder._processes),2)
                # Original FULL consumer commit, exact receipt ACK and native
                # proof publisher earn release. No fixture SQL seeds readiness.
                for _ in range(32):
                    snapshot=capture(history.lifecycle,schedule=True)
                    if snapshot is not None:
                        result=deliver(snapshot)
                        self.assertTrue(await source._complete_history_delivery(snapshot,result))
                    history.lifecycle.publish();history.startup.advance()
                    if history.startup.snapshot()['released']:break
                self.assertTrue(history.startup.snapshot()['released'])
                consumed=writer.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL").fetchone()[0]
                self.assertGreater(consumed,0)
                with closing(CandidateHistory(history.lifecycle.path,clock=time.time)) as shared:
                    references=shared.db.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0]
                    self.assertGreater(references,0)
                stage[0]='development'
                await asyncio.wait_for(source.acquire(),10)
                self.assertTrue(writer.db.execute("SELECT 1 FROM candidate_lifecycle WHERE family='pump' AND address=? AND state IN ('queued','warming','active')",(corpus.curve,)).fetchone())
                self.assertTrue(any(row['family']=='pump' and row['address']==corpus.curve for row in plan_live(state)))
                self.assertTrue(writer.db.execute("SELECT 1 FROM rolling_preparation_jobs WHERE status='pending'").fetchone())
                source.stop.clear();stage[0]='history'
                await asyncio.wait_for(source.historical_processing(),20)
                self.assertTrue(writer.db.execute("SELECT 1 FROM rolling_preparation_jobs WHERE status='complete'").fetchone())
                self.assertEqual(len(historian._processes),1)
                self.assertEqual(corpus.snapshot()['provider_calls'],0)
                print('SYNTHETIC_SOLANA_SOURCE_CONFORMANCE '+json.dumps(dict(
                    scope='SOURCE_BOUNDARY_ONLY_NOT_COPIED_MAIN_OR_KERNEL',
                    corpus_sha256=corpus.corpus_sha256,joined_slot3_bytes=actual_bytes,
                    process_prepared_records=preparations[0]['records'],decoder_processes=len(decoder._processes),
                    history_processes=len(historian._processes),native_canonical_full_ack=consumed,
                    native_candidate_references=references,startup_released=history.startup.snapshot()['released'],
                    true_target_progress_bps=curve_progress_bps(creation['initial_real_token_reserves'],
                        buys[-1]['real_token_reserves']),financial_authority=False,provider_calls=0,
                    market_coverage=False),sort_keys=True),flush=True)
            finally:
                source.stop.set()
                decoder.shutdown(wait=True,cancel_futures=True);historian.shutdown(wait=True,cancel_futures=True)
                writer.close()
            self.assertTrue(all(not process.is_alive() for pool in (decoder,historian)
                for process in pool._processes.values()))


if __name__=='__main__':unittest.main()
