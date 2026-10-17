"""Synthetic provider inputs exercise real native parsers, not acknowledgements."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import grpc

from meme_machine.operational.isolated_native_kernel_corpus import (
    BASE_SLOT,MAX_REQUESTS,MAX_STREAMS,SCOPE,SLOTS,TEMPLATE_SHA256,SolanaKernelCorpus)
from meme_machine.solana_candidate_join import CandidateTransactionJoin,candidate_subscription
from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
from meme_machine.solana_selective_history import PROGRAMS
from meme_machine.solana_selective_source import scout_fact,scout_request
from meme_machine.solana_source_intake import candidate_log_message
from meme_machine.yellowstone import geyser_pb2 as pb


AT=1792270000


def archive_config(lower=1,upper=BASE_SLOT+SLOTS-1):
    return dict(transactionDetails='full',sortOrder='asc',limit=100,
        commitment='finalized',encoding='json',maxSupportedTransactionVersion=1,
        filters=dict(slot=dict(gte=lower,lte=upper)))


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
        pump=corpus.rpc('getTransactionsForAddress',[PROGRAMS['pump'],archive_config()])
        swap=corpus.rpc('getTransactionsForAddress',[PROGRAMS['pumpswap'],archive_config()])
        self.assertEqual(len(pump['data']),2)
        self.assertEqual(len(swap['data']),1)
        events=[event for tx in pump['data'] for event in pump_events(tx)]
        self.assertEqual([event['event_type'] for event in events].count('create'),1)
        self.assertEqual([event['event_type'] for event in events].count('trade'),2)
        events.extend(pumpswap_trade_events(swap['data'][0]))
        self.assertTrue(all(event['market_time']==AT for event in events))
        self.assertEqual([tx['slot'] for tx in pump['data']+swap['data']],
            [BASE_SLOT+1,BASE_SLOT+2,BASE_SLOT+3])
        signature=pump['data'][0]['transaction']['signatures'][0]
        retrieved=corpus.rpc('getTransaction',[signature,dict(commitment='finalized',
            encoding='json',maxSupportedTransactionVersion=1)])
        self.assertEqual(retrieved,pump['data'][0])
        pump['data'][0]['meta']['logMessages'].clear()
        retrieved['transaction']['signatures'].clear()
        again=corpus.rpc('getTransactionsForAddress',[PROGRAMS['pump'],archive_config()])
        self.assertTrue(again['data'][0]['meta']['logMessages'])
        self.assertEqual(again['data'][0]['transaction']['signatures'],[signature])

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
            ('pump',self.corpus.curve,BASE_SLOT+1))
        self.assertFalse(fact['fields']['economic_event'])
        self.assertFalse(fact['fields']['history_complete'])
        self.assertTrue(fact['fields']['activity'])

    async def test_body_free_wire_join_requires_actual_logs_and_preserves_native_economics(self):
        addresses={PROGRAMS['pump']:'program:pump',PROGRAMS['pumpswap']:'program:pumpswap'}
        joined=CandidateTransactionJoin(addresses,set(),filtered_from_slot=BASE_SLOT)
        websocket=await self.stream('solana_websocket')
        expected=[]
        for number,address in enumerate(addresses,1):
            await websocket.write(logs_request(address,number))
            transactions=self.corpus.rpc('getTransactionsForAddress',[address,archive_config()])['data']
            expected.extend(transactions)
            for _ in range(2+len(transactions)):
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
            if update.WhichOneof('update_oneof')=='slot' and update.slot.slot==BASE_SLOT+SLOTS-1:break
        self.assertEqual([row['transaction']['signatures'][0] for row in output],
            [row['transaction']['signatures'][0] for row in expected])
        decoded=lambda rows:[event for row in rows for event in (*pump_events(row),*pumpswap_trade_events(row))]
        self.assertEqual(decoded(output),decoded(expected))
        self.assertEqual(len(decoded(output)),4) # Create transaction includes an initial buy.
        self.assertEqual(joined.completed,BASE_SLOT+SLOTS-1)
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
        while len(slots)<head-floor+1:
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
        self.assertEqual(slots,list(range(floor,head+1)))

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
        for _ in range(8):await stream.write(logs_request(PROGRAMS['pump']))
        with self.assertRaises(ValueError):await stream.write(logs_request(PROGRAMS['pump']))
        with self.assertRaises(ValueError):await stream.write(b'')
        await stream.aclose()
        with self.assertRaises(ValueError):await stream.write(logs_request(PROGRAMS['pump']))


if __name__=='__main__':unittest.main()
