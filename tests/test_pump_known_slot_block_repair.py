"""Captured log economics, synthetic native block density, no interval inference."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.solana_candidate_join import CandidateTransactionJoin,CONTINUITY,FINALITY,authenticated_block_logs
from meme_machine.solana_native_evidence import signature
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.yellowstone import geyser_pb2 as pb
from meme_machine.runtime.evidence_worker import RepairRPC
from meme_machine.runtime.provider_purchases import provider_work
from tests.test_solana_selective_evidence import FIXTURE

PROFILE=dict(validated=True,max_response_bytes=2_000_000,max_transactions=128,
    max_latency_seconds=.2,billed_cu=40,throughput_cu=40)
NOW=1791500000


def fixture(count=8,join_seconds=120):
    captured=next(tx for tx in FIXTURE['pump'] if tx['meta'].get('logMessages'))
    join=CandidateTransactionJoin({'address':'candidate:pump:address'},set(),clock=lambda:NOW,filtered_from_slot=100,max_join_seconds=join_seconds)
    txs=[];keys=[]
    with patch('time.time',return_value=NOW):
        for i in range(count):
            raw=bytes([i+1])*64;sig=signature(raw);keys.append((100,sig))
            tx=deepcopy(captured);tx['transaction']['signatures']=[sig];tx['meta']['err']=None;txs.append(tx)
            update=pb.SubscribeUpdate(filters=['0']);update.transaction_status.slot=100;update.transaction_status.signature=raw;update.transaction_status.index=i
            join.feed(update,len(update.SerializeToString()),NOW)
        update=pb.SubscribeUpdate(filters=[CONTINUITY]);meta=update.block_meta
        meta.slot=100;meta.parent_slot=99;meta.blockhash='native-100';meta.parent_blockhash='native-99'
        meta.executed_transaction_count=count;meta.block_time.timestamp=NOW
        join.feed(update,len(update.SerializeToString()),NOW)
        update=pb.SubscribeUpdate(filters=[FINALITY]);update.slot.slot=100;update.slot.parent=99;update.slot.status=pb.SLOT_FINALIZED
        join.feed(update,len(update.SerializeToString()),NOW)
    block=dict(blockhash='native-100',previousBlockhash='native-99',parentSlot=99,blockTime=NOW,transactions=txs)
    return join,keys,block


class KnownSlotTests(unittest.TestCase):
    def test_native_log_frames_equal_after_eight_individual_bodies_or_one_complete_block(self):
        original,keys,block=fixture();optimized,_,_=fixture()
        groups=optimized.block_repair_groups(keys,PROFILE,NOW)
        self.assertEqual(len(groups),1);required,witness=groups[0]
        logs=authenticated_block_logs(block,witness,required,PROFILE['max_response_bytes'])
        a=b=None
        for index,(slot,sig) in enumerate(keys):
            a=original.feed_log(slot,sig,block['transactions'][index]['meta']['logMessages'],None,NOW)
            b=optimized.feed_log(slot,sig,logs[(slot,sig)],None,NOW)
        self.assertEqual(a,b);self.assertEqual(len(a.log_transactions),8)
        self.assertEqual((len(keys)*40-40),280)
        # Block bodies satisfy known missing fields; they create no range proof.
        self.assertFalse(hasattr(optimized,'coverage'));self.assertEqual(optimized.pending,{})

    def test_sparse_default_deadline_unknown_capability_and_resource_bounds_keep_original(self):
        join,keys,_=fixture(count=1);self.assertEqual(join.block_repair_groups(keys,PROFILE,NOW),[])
        join,keys,_=fixture(join_seconds=10);self.assertEqual(join.block_repair_groups(keys,PROFILE,NOW),[])
        join,keys,_=fixture()
        self.assertEqual(join.block_repair_groups(keys[:2],PROFILE,NOW),[])
        for profile in (None,{},dict(PROFILE,validated=False),dict(PROFILE,throughput_cu=500),
                        dict(PROFILE,max_transactions=7),dict(PROFILE,max_response_bytes=16*1024*1024+1)):
            self.assertEqual(join.block_repair_groups(keys,profile,NOW),[])
        self.assertEqual(join.block_repair_groups(keys,PROFILE,NOW+100),[])
        join.pending[100]['finality']=98;self.assertEqual(join.block_repair_groups(keys,PROFILE,NOW),[])

    def test_partial_reorganization_transaction_status_and_order_refuse_all_block_evidence(self):
        join,keys,block=fixture();_,witness=join.block_repair_groups(keys,PROFILE,NOW)[0]
        broken=[]
        for field,value in (('blockhash','fork'),('previousBlockhash','fork'),('parentSlot',98),('blockTime',NOW+1)):
            broken.append(dict(block,**{field:value}))
        broken.append(dict(block,transactions=block['transactions'][:-1]))
        swapped=deepcopy(block);swapped['transactions'].reverse();broken.append(swapped)
        failed=deepcopy(block);failed['transactions'][0]['meta']['err']={'failed':True};broken.append(failed)
        missing=deepcopy(block);missing['transactions'][0]['meta'].pop('logMessages');broken.append(missing)
        for value in broken:
            with self.assertRaises(EvidenceUnavailable):authenticated_block_logs(value,witness,keys,PROFILE['max_response_bytes'])
            self.assertEqual(list(join.missing_log_keys(100)),keys)
        with self.assertRaises(EvidenceUnavailable):authenticated_block_logs(block,witness,keys,10)

    def test_existing_repair_transport_requires_capability_and_accounts_one_physical_purchase(self):
        class Governor:
            def acquire(self,*a,**kw):pass
            def succeeded(self,*a):pass
        rpc=RepairRPC('https://solana-mainnet.g.alchemy.com/v2/OFFLINE_REPAIR',Governor())
        with self.assertRaisesRegex(ValueError,'repair_method_forbidden'):rpc.call_delivered('getBlock',[100,{}])
        join,keys,block=fixture();rpc.block_repair_profile=PROFILE
        encoded=json.dumps(dict(jsonrpc='2.0',id=1,result=block)).encode()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return encoded[:n]
        with patch('urllib.request.urlopen',return_value=Response()),provider_work('recovery_restart',family='pump',consumer='recovery'):
            value,receipt=rpc.call_delivered('getBlock',[100,dict(commitment='finalized')],2)
        self.assertEqual(value,block);self.assertEqual(receipt['cu'],40)
        totals=rpc.telemetry()['provider_purchases']['totals']
        self.assertEqual(totals['physical_requests'],1);self.assertEqual(totals['estimated_throughput_cu'],40)
        self.assertEqual(totals['delivered_payload_bytes'],len(encoded))
