"""Offline captured-transaction supplementation through the real durable owner.

Truncation is injected into retained mainnet fixtures; no provider is contacted.
The archive page supplies native order. A separately checked full transaction
supplies log content only, and never bypasses the consumer/publication fences.
"""
from contextlib import closing
import asyncio
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import (
    EvidenceUnavailable, EvidenceWriter, canonical, digest,
)
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_program_decoders import pump_events, pumpswap_trade_events
from meme_machine.solana_selective_history import (
    PROGRAMS, archive_page_evidence, complete_archive_transaction,
    economic_records, join_archive_log_supplement, missing_archive_log_transactions,
)
from meme_machine.solana_selective_source import SelectiveSource, install
from meme_machine.solana_candidate_join import CandidateTransactionJoin,scope_labels,candidate_commit_size
from meme_machine.solana_native_evidence import signature
from meme_machine.solana_stream_log_repair import authenticate_supplement,explicit_truncation,log_input_reason,rebase_log_join
from meme_machine.yellowstone import geyser_pb2 as pb


FIXTURE = json.loads((Path(__file__).parent/'fixtures/solana_selective_cohort.json').read_text())
ENDPOINT = 'a'*64
NOW = 1791400000.


class StreamFullLogContentTests(unittest.TestCase):
    def joined(self,*,extra_missing=0):
        import based58
        original,fetched,full,_=truncated_transaction()
        slot=full['slot'];sig=full['transaction']['signatures'][0]
        address=PROGRAMS['pump'];scope='program:pump'
        join=CandidateTransactionJoin({address:scope},set(),filtered_from_slot=slot,max_join_seconds=120)
        # Inject truncation into captured complete mainnet logs. This exercises
        # the retained incomplete_finalized_logs failure; the actual startup's
        # seventeen failures did not expose their packet shape or exact marker.
        with self.assertRaisesRegex(EvidenceUnavailable,'incomplete_finalized_logs'):
            join.feed_log(slot,sig,original['meta']['logMessages'],None,NOW)
        join.defer_log(slot,sig,original['meta']['logMessages'],NOW)
        u=pb.SubscribeUpdate(filters=[scope_labels({address:scope})[scope]])
        u.transaction_status.slot=slot;u.transaction_status.index=full['transactionIndex']
        u.transaction_status.signature=based58.b58decode(sig.encode())
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW))
        for n in range(extra_missing):
            u=pb.SubscribeUpdate(filters=[scope_labels({address:scope})[scope]])
            u.transaction_status.slot=slot;u.transaction_status.index=full['transactionIndex']+n+1
            u.transaction_status.signature=bytes([n+2])*64
            self.assertIsNone(join.feed(u,u.ByteSize(),NOW))
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
        m.blockhash='native-hash';m.parent_blockhash='native-parent';m.block_time.timestamp=full['blockTime']
        m.executed_transaction_count=full['transactionIndex']+1+extra_missing
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW))
        u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot;u.slot.parent=slot-1;u.slot.status=pb.SLOT_FINALIZED
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW))
        return join,original,fetched,full,join.deferred_log_witness(slot,sig)

    def test_native_status_and_authenticated_full_response_complete_original_events(self):
        join,original,fetched,full,witness=self.joined()
        self.assertEqual(join.diagnostic()['incomplete_log_count'],1)
        self.assertIsNone(join.drain())
        logs,receipt=authenticate_supplement(join,witness,fetched,ENDPOINT)
        self.assertEqual(logs,full['meta']['logMessages'])
        self.assertEqual(receipt['native_witness']['transaction_index'],full['transactionIndex'])
        self.assertEqual(receipt['response_sha256'],hashlib.sha256(canonical(fetched).encode()).hexdigest())
        self.assertFalse(receipt['truncated_logs_used_as_complete'])
        frame=join.complete_deferred_log(full['slot'],full['transaction']['signatures'][0],logs,NOW+1)
        self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(full))
        self.assertEqual(join.incomplete_logs,set());self.assertEqual(join.early_log_bytes,0)
        self.assertEqual(frame.log_transactions[0]['transactionIndex'],full['transactionIndex'])
        self.assertIsNone(join.feed_log(full['slot'],full['transaction']['signatures'][0],logs,None,NOW+2))
        join.defer_log(full['slot'],full['transaction']['signatures'][0],original['meta']['logMessages'],NOW+2)
        self.assertFalse(join.incomplete_logs)
        altered=list(original['meta']['logMessages']);altered[0]='changed prefix'
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_late_log_content'):
            join.defer_log(full['slot'],full['transaction']['signatures'][0],altered,NOW+3)

    def test_supplement_refuses_wrong_slot_signature_error_time_index_scope_and_prefix(self):
        for field in ('slot','signature','error','time','index','scope','prefix'):
            with self.subTest(field=field):
                join,original,fetched,full,witness=self.joined()
                if field=='slot':fetched['slot']+=1
                elif field=='signature':fetched['transaction']['signatures'][0]='wrong'
                elif field=='error':fetched['meta']['err']={'InstructionError':[0,1]}
                elif field=='time':fetched['blockTime']+=1
                elif field=='index':fetched['transactionIndex']=full['transactionIndex']+1
                elif field=='scope':fetched['transaction']['message']['accountKeys']=[];fetched['meta']['loadedAddresses']={}
                else:fetched['meta']['logMessages'][0]='different original prefix'
                with self.assertRaisesRegex(EvidenceUnavailable,'supplement_identity_unverified'):
                    authenticate_supplement(join,witness,fetched,ENDPOINT)
                self.assertEqual(len(join.incomplete_logs),1);self.assertIsNone(join.drain())

    def test_complete_http_growth_at_join_bound_preserves_original_evidence_and_missing_native_work(self):
        # A second genuinely missing native field prevents an atomic oldest
        # transfer. Capacity refusal must still retain every original byte.
        join,original,fetched,full,witness=self.joined(extra_missing=1);slot=full['slot'];sig=full['transaction']['signatures'][0]
        join.hold_complete_log(slot,sig,full['meta']['logMessages'])
        future_logs=['Program log: bounded future packet']
        future_size=len(str(future_logs).encode());bound=join.early_log_bytes+future_size
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            join.feed_log(slot+1,'future-signature',future_logs,None,NOW+1)
            complete,_=authenticate_supplement(join,witness,fetched,ENDPOINT)
            self.assertGreater(len(str(complete).encode()),len(str(original['meta']['logMessages']).encode()))
            before=(copy.deepcopy(join.early_logs),join.early_log_bytes,set(join.incomplete_logs),
                dict(join.deferred_complete_logs),dict(join.recent_incomplete_logs),join.completed,
                set(join.pending[slot]['missing_logs']))
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                join.complete_deferred_log(slot,sig,complete,NOW+2)
            after=(copy.deepcopy(join.early_logs),join.early_log_bytes,set(join.incomplete_logs),
                dict(join.deferred_complete_logs),dict(join.recent_incomplete_logs),join.completed,
                set(join.pending[slot]['missing_logs']))
            self.assertEqual(after,before)
            self.assertEqual(join.early_log_bytes,bound)
            self.assertEqual(join.deferred_log_witness(slot,sig),witness)
            self.assertIsNone(join.drain())
        # The unchanged authenticated input remains admissible after capacity
        # becomes available; native order, exact events and duplicate handling
        # still pass the existing join, without new provider acquisition.
        self.assertIsNone(join.complete_deferred_log(slot,sig,complete,NOW+3))
        frame=join.feed_log(slot,signature(bytes([2])*64),[],None,NOW+3)
        self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(full))
        self.assertEqual(frame.log_transactions[0]['transactionIndex'],full['transactionIndex'])
        self.assertNotIn((slot,sig),join.incomplete_logs)
        self.assertEqual(join.early_log_bytes,future_size)

    def pressured(self,**options):
        join,original,fetched,full,witness=self.joined(**options)
        slot=full['slot'];sig=full['transaction']['signatures'][0]
        complete,receipt=authenticate_supplement(join,witness,fetched,ENDPOINT)
        # Unlike a larger buffer, these retained future bytes remain exactly
        # where they were. The complete field itself fits the original bound.
        future=['x'*(len(str(complete).encode())+128)]
        join.feed_log(slot+1,signature(bytes([9])*64),future,None,NOW+1)
        bound=join.early_log_bytes
        self.assertGreater(len(str(complete).encode()),len(str(original['meta']['logMessages']).encode()))
        self.assertLess(len(str(complete).encode()),bound)
        return join,original,full,complete,receipt,bound

    def multi_pressured(self,count=2):
        """Several full fields, one full early-log budget, unused native bytes."""
        join,original,fetched,full,_=self.joined(extra_missing=count-1)
        slot=full['slot'];repairs=[]
        for n in range(count):
            complete=copy.deepcopy(full)
            if n:
                complete['transaction']['signatures']=[signature(bytes([n+1])*64)]
                complete['transactionIndex']+=n
            sig=complete['transaction']['signatures'][0]
            if n:join.defer_log(slot,sig,original['meta']['logMessages'],NOW)
            witness=join.deferred_log_witness(slot,sig)
            logs,receipt=authenticate_supplement(join,witness,complete,ENDPOINT)
            repairs.append(((slot,sig),logs,receipt,NOW+n+2))
        # Both original budgets remain ample for the bounded head as a whole;
        # only the early-log budget is occupied by later authenticated fields.
        needed=join.pending_bytes+sum(len(canonical(dict(slot=slot,
            blockTime=full['blockTime'],transactionIndex=full['transactionIndex']+n,
            transaction=dict(signatures=[key[1]]),meta=dict(err=None,logMessages=logs))).encode())
            for n,(key,logs,_,_) in enumerate(repairs))
        join.feed_log(slot+1,signature(bytes([9])*64),['x'*(needed+128)],None,NOW+1)
        return join,repairs,join.early_log_bytes

    def test_multiple_authenticated_head_fields_share_existing_native_budget_until_complete(self):
        for count in (2,3):
            with self.subTest(count=count):
                join,repairs,bound=self.multi_pressured(count);reference=copy.deepcopy(join)
                slot=repairs[0][0][0];native_bytes=join.pending_bytes
                future={k:copy.deepcopy(v) for k,v in join.early_logs.items() if k[0]>slot}
                prefixes=copy.deepcopy(join.early_logs)
                expected=None
                for (current,sig),logs,_,seen in repairs:
                    expected=reference.complete_deferred_log(current,sig,logs,seen)
                with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
                    for n,((current,sig),logs,_,seen) in enumerate(repairs):
                        frame=join.complete_deferred_log(current,sig,logs,seen)
                        self.assertLessEqual(join.pending_bytes,bound)
                        self.assertLessEqual(join.early_log_bytes,bound)
                        if n<count-1:
                            self.assertIsNone(frame);self.assertIsNone(join.drain())
                            self.assertEqual(join.completed,-1)
                            self.assertEqual(join.early_logs,prefixes)
                            retained=sum(value[1] for value in join.completed_log_fields.values())
                            self.assertEqual(join.pending_bytes,native_bytes+retained)
                            self.assertEqual(len(join.pending[slot]['missing_logs']),count-n-1)
                    self.assertEqual(frame,expected)
                self.assertEqual(join.pending_bytes,0);self.assertFalse(join.completed_log_fields)
                self.assertFalse(join.incomplete_logs);self.assertFalse(join.deferred_complete_logs)
                self.assertEqual(join.early_logs,future)
                self.assertEqual(join.recent,reference.recent)
                self.assertEqual(join.recent_logs,reference.recent_logs)
                self.assertEqual(join.recent_incomplete_logs,reference.recent_incomplete_logs)
                for (_,sig),logs,_,seen in repairs:
                    self.assertEqual(frame.observed_at[sig],seen)
                    self.assertIsNone(join.feed_log(slot,sig,logs,None,NOW+20))
                    join.defer_log(slot,sig,prefixes[(slot,sig)][0],NOW+20)

    def test_retained_head_duplicate_is_idempotent_and_conflicts_preserve_both_budgets(self):
        join,repairs,bound=self.multi_pressured(3);(slot,sig),logs,_,seen=repairs[0]
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertIsNone(join.complete_deferred_log(slot,sig,logs,seen))
            before=copy.deepcopy(join.__dict__)
            self.assertIsNone(join.complete_deferred_log(slot,sig,list(logs),seen+50))
            self.assertEqual(join.__dict__,before)
            # The join owns the retained list rather than the caller's mutable
            # provider response, and keeps the original authenticated seen.
            changed=list(logs);changed[-1]+=' changed'
            for function in (lambda:join.complete_deferred_log(slot,sig,changed,seen+1),
                             lambda:join.hold_complete_log(slot,sig,changed)):
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_content_conflict'):function()
                self.assertEqual(join.__dict__,before)
            logs.append('caller changed after admission')
            self.assertEqual(join.__dict__,before)

    def test_partial_preparation_cannot_be_retired_or_exposed_as_a_frame(self):
        join,repairs,_=self.multi_pressured();key,logs,_,seen=repairs[0]
        before=copy.deepcopy(join.__dict__)
        plan=join._prepare_drain((key,(logs,None,seen)),partial=True)
        self.assertIsNone(plan[3]);self.assertEqual(join.__dict__,before)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_required_content_missing'):
            join._finish_drain(plan)
        self.assertEqual(join.__dict__,before)

    def test_retained_head_admission_and_native_arrival_enforce_one_combined_byte_budget(self):
        join,repairs,bound=self.multi_pressured();(slot,sig),logs,_,seen=repairs[0]
        s=join.pending[slot]
        charge=len(canonical(dict(slot=slot,blockTime=s['meta'].block_time.timestamp,
            transactionIndex=next(i for i in s['log_required'] if s['signature_text'][i]==sig),
            transaction=dict(signatures=[sig]),meta=dict(err=None,logMessages=logs))).encode())
        # This simulates other retained native packets occupying the same
        # already-existing budget, without allocating another large fixture.
        s['bytes']=join.pending_bytes=bound-charge+1
        before=copy.deepcopy(join.__dict__)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                join.complete_deferred_log(slot,sig,logs,seen)
            self.assertEqual(join.__dict__,before)
            s['bytes']-=1;join.pending_bytes-=1
            self.assertIsNone(join.complete_deferred_log(slot,sig,logs,seen))
            self.assertEqual(join.pending_bytes,bound)
            before=copy.deepcopy(join.__dict__)
            u=pb.SubscribeUpdate(filters=['b']);u.block_meta.slot=slot+2
            with self.assertRaisesRegex(EvidenceUnavailable,'yellowstone_census_buffer_bound'):
                join.feed(u,u.ByteSize(),NOW+10)
            self.assertEqual(join.__dict__,before)

    def test_partial_head_never_retains_invalid_census_or_an_oversized_assembled_frame(self):
        for fault in ('duplicate','index','frame'):
            with self.subTest(fault=fault):
                join,repairs,bound=self.multi_pressured();(slot,sig),logs,_,seen=repairs[0]
                s=join.pending[slot]
                if fault=='duplicate':
                    index=max(s['statuses'])+1;s['statuses'][index]=next(iter(s['statuses'].values()))
                    s['status_seen'][index]=NOW;s['meta'].executed_transaction_count=index+1;s['max_index']=index
                elif fault=='index':s['max_index']=s['meta'].executed_transaction_count
                before=copy.deepcopy(join.__dict__)
                reason={'duplicate':'yellowstone_duplicate_signature','index':'yellowstone_transaction_index_shape',
                    'frame':'candidate_commit_batch_bound'}[fault]
                with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound), \
                        patch('meme_machine.solana_candidate_join.CANDIDATE_COMMIT_BYTES',1 if fault=='frame' else 32*1024*1024):
                    with self.assertRaisesRegex(EvidenceUnavailable,reason):
                        join.complete_deferred_log(slot,sig,logs,seen)
                self.assertEqual(join.__dict__,before)

    def test_last_completion_checks_whole_frame_before_retiring_any_retained_field(self):
        join,repairs,bound=self.multi_pressured();reference=copy.deepcopy(join)
        expected=None
        for key,logs,_,seen in repairs:expected=reference.complete_deferred_log(*key,logs,seen)
        first,second=repairs
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertIsNone(join.complete_deferred_log(*first[0],first[1],first[3]))
            before=copy.deepcopy(join.__dict__)
            with patch('meme_machine.solana_candidate_join.CANDIDATE_COMMIT_BYTES',candidate_commit_size(expected)-1):
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_commit_batch_bound'):
                    join.complete_deferred_log(*second[0],second[1],second[3])
            self.assertEqual(join.__dict__,before)
            actual=join.complete_deferred_log(*second[0],second[1],second[3])
            self.assertEqual(actual,expected)

    def test_new_earlier_native_slot_keeps_retained_later_head_fields_and_fifo_order(self):
        join,repairs,bound=self.multi_pressured();(slot,sig),logs,_,seen=repairs[0]
        join.filtered_from_slot=slot-1;reference=copy.deepcopy(join)
        def earlier(target):
            u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot-1;m.parent_slot=slot-2
            m.blockhash='earlier';m.parent_blockhash='earlier-parent';m.block_time.timestamp=int(NOW)
            return target.feed(u,u.ByteSize(),NOW+5)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertIsNone(join.complete_deferred_log(slot,sig,logs,seen))
            retained=copy.deepcopy(join.completed_log_fields);charge=join.pending_bytes
            self.assertIsNone(earlier(join));self.assertIsNone(earlier(reference))
            self.assertEqual(join.completed_log_fields,retained);self.assertGreater(join.pending_bytes,charge)
            second=repairs[1];before=copy.deepcopy(join.__dict__)
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                join.complete_deferred_log(*second[0],second[1],second[3])
            self.assertEqual(join.__dict__,before)
            u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=slot-1;u.slot.parent=slot-2;u.slot.status=pb.SLOT_FINALIZED
            first=join.feed(u,u.ByteSize(),NOW+6);expected_first=reference.feed(u,u.ByteSize(),NOW+6)
            self.assertEqual(first,expected_first);self.assertEqual(first.update.block.slot,slot-1)
            self.assertEqual(join.completed_log_fields,retained)
            self.assertIsNone(reference.complete_deferred_log(slot,sig,logs,seen))
            actual=join.complete_deferred_log(*second[0],second[1],second[3])
            expected=reference.complete_deferred_log(*second[0],second[1],second[3])
            self.assertEqual(actual,expected);self.assertEqual(actual.update.block.slot,slot)
            self.assertEqual(join.pending_bytes,0);self.assertFalse(join.completed_log_fields)

    def test_only_ready_oldest_supplement_transfers_without_transient_overadmission(self):
        join,original,full,complete,receipt,bound=self.pressured()
        slot=full['slot'];sig=full['transaction']['signatures'][0]
        reference=copy.deepcopy(join)
        expected=reference.complete_deferred_log(slot,sig,complete,NOW+2)
        future={key:copy.deepcopy(value) for key,value in join.early_logs.items() if key[0]>slot}
        old_size=len(str(original['meta']['logMessages']).encode())
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            self.assertGreater(bound-old_size+len(str(complete).encode()),bound)
            frame=join.complete_deferred_log(slot,sig,complete,NOW+2)
            self.assertLessEqual(join.early_log_bytes,bound)
        self.assertEqual(frame,expected)
        self.assertEqual(join.__dict__,reference.__dict__)
        self.assertEqual(join.early_logs,future)
        self.assertEqual(join.early_log_bytes,bound-old_size)
        self.assertEqual(frame.observed_at[sig],NOW+2)
        self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(full))
        self.assertEqual(receipt['native_witness']['transaction_index'],full['transactionIndex'])
        self.assertIsNone(join.feed_log(slot,sig,complete,None,NOW+3))
        join.defer_log(slot,sig,original['meta']['logMessages'],NOW+3)
        altered=list(complete);altered[-1]+=' changed'
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_late_log_content'):
            join.feed_log(slot,sig,altered,None,NOW+3)

    def test_not_ready_or_future_replacement_cannot_release_capacity(self):
        for fault in ('future','meta','finality','body'):
            with self.subTest(fault=fault):
                join,_,full,complete,_,bound=self.pressured()
                slot=full['slot'];sig=full['transaction']['signatures'][0];s=join.pending[slot]
                if fault=='future':join.pending[slot-1]=dict(started=join.clock(),meta=None,last_seen=NOW)
                elif fault=='meta':s['meta']=None
                elif fault=='finality':s['finality']=None
                elif fault=='body':s['required'][0]=next(iter(s['statuses'].values()))
                before=copy.deepcopy(join.__dict__)
                with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
                    with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                        join.complete_deferred_log(slot,sig,complete,NOW+2)
                self.assertEqual(join.__dict__,before)

    def test_fitting_nonrequired_deferred_key_retains_full_logs_when_its_slot_drains(self):
        # A later slot can become ready behind the oldest pending slot, while
        # retaining an unmatched prefix received before its native identities.
        # The public join API must preserve that fitting content even though
        # managed HTTP cannot obtain a deferred_log_witness for the stray key.
        join,_,fetched,full,witness=self.joined();slot=full['slot'];future=slot+1
        sig=full['transaction']['signatures'][0];stray=signature(bytes([8])*64)
        prefix=['original prefix','Log truncated'];complete=['original prefix','complete suffix']
        join.defer_log(future,stray,prefix,NOW)
        join.hold_complete_log(future,stray,complete)
        actual=signature(bytes([9])*64);actual_logs=['native required complete field']
        join.feed_log(future,actual,actual_logs,None,NOW+1)
        scope=next(iter(join.programs.values()))
        u=pb.SubscribeUpdate(filters=[scope_labels(join.programs)[scope]])
        u.transaction_status.slot=future;u.transaction_status.index=0;u.transaction_status.signature=bytes([9])*64
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=future;m.parent_slot=slot
        m.blockhash='future';m.parent_blockhash='native-hash';m.block_time.timestamp=full['blockTime']+1;m.executed_transaction_count=1
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=future;u.slot.parent=slot;u.slot.status=pb.SLOT_FINALIZED
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        original_complete,_=authenticate_supplement(join,witness,fetched,ENDPOINT)
        self.assertEqual(join.complete_deferred_log(slot,sig,original_complete,NOW+2).update.block.slot,slot)
        self.assertFalse(join.pending[future]['missing_logs'])
        self.assertIsNone(join.deferred_log_witness(future,stray))
        frame=join.complete_deferred_log(future,stray,complete,NOW+3)
        self.assertEqual(frame.update.block.slot,future)
        self.assertEqual([tx['transaction']['signatures'][0] for tx in frame.log_transactions],[actual])
        self.assertEqual(frame.log_transactions[0]['meta']['logMessages'],actual_logs)
        self.assertEqual(frame.observed_at[actual],NOW+1)
        self.assertEqual(join.early_logs,{(future,stray):(complete,None,NOW+3)})
        self.assertEqual(join.early_log_bytes,len(str(complete).encode()))
        self.assertNotIn((future,stray),join.incomplete_logs)
        self.assertNotIn((future,stray),join.deferred_complete_logs)
        self.assertEqual(join.recent_incomplete_logs[(future,stray)],digest([prefix,None]))

    def test_prepared_frame_checks_do_not_mutate_signature_cache_or_truncated_evidence(self):
        for pressured in (False,True):
            with self.subTest(pressured=pressured):
                join,_,full,complete,_,bound=self.pressured();slot=full['slot'];sig=full['transaction']['signatures'][0]
                s=join.pending[slot];index=s['meta'].executed_transaction_count
                fact=next(iter(s['statuses'].values()))
                # A failed scoped identity needs conversion during validation.
                # The following duplicate must not leave that cache mutation
                # behind, or replace the original truncated packet.
                failed=(bytes([2])*64,False,b'\0'*4,fact[3],fact[4])
                for offset in (0,1):
                    s['statuses'][index+offset]=failed;s['status_seen'][index+offset]=NOW
                s['meta'].executed_transaction_count+=2;s['max_index']=index+1
                before=copy.deepcopy(join.__dict__)
                limit=bound if pressured else 32*1024*1024
                with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',limit):
                    with self.assertRaisesRegex(EvidenceUnavailable,'yellowstone_duplicate_signature'):
                        join.complete_deferred_log(slot,sig,complete,NOW+2)
                self.assertEqual(join.__dict__,before)

    def test_whole_frame_bound_is_checked_before_normal_or_overfull_completion_mutates(self):
        for pressured in (False,True):
            with self.subTest(pressured=pressured):
                join,_,full,complete,_,bound=self.pressured();slot=full['slot'];sig=full['transaction']['signatures'][0]
                reference=copy.deepcopy(join)
                frame=reference.complete_deferred_log(slot,sig,complete,NOW+2)
                limit=candidate_commit_size(frame)-1
                self.assertLess(frame.source_bytes,limit)
                before=copy.deepcopy(join.__dict__)
                with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound if pressured else 32*1024*1024), \
                        patch('meme_machine.solana_candidate_join.CANDIDATE_COMMIT_BYTES',limit):
                    with self.assertRaisesRegex(EvidenceUnavailable,'candidate_commit_batch_bound'):
                        join.complete_deferred_log(slot,sig,complete,NOW+2)
                self.assertEqual(join.__dict__,before)
        # Normal drain shares the same preflight; even its local signature
        # cache cannot change when full log bytes exceed the frame bound.
        join,_,full,complete,_,_=self.pressured();slot=full['slot'];sig=full['transaction']['signatures'][0]
        old=join.early_logs[(slot,sig)];join.early_logs[(slot,sig)]=(complete,None,old[2])
        join.early_log_bytes+=len(str(complete).encode())-len(str(old[0]).encode())
        join.incomplete_logs.remove((slot,sig));join.pending[slot]['missing_logs'].remove(sig)
        before=copy.deepcopy(join.__dict__)
        with patch('meme_machine.solana_candidate_join.CANDIDATE_COMMIT_BYTES',1):
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_commit_batch_bound'):join.drain()
        self.assertEqual(join.__dict__,before)

    def test_transfer_keeps_future_native_frames_in_order_and_replay_identical(self):
        join,_,full,complete,_,bound=self.pressured();slot=full['slot'];sig=full['transaction']['signatures'][0]
        future=slot+1;raw=bytes([9])*64;scope=next(iter(join.programs.values()))
        u=pb.SubscribeUpdate(filters=[scope_labels(join.programs)[scope]])
        u.transaction_status.slot=future;u.transaction_status.index=0;u.transaction_status.signature=raw
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=future;m.parent_slot=slot
        m.blockhash='future';m.parent_blockhash='native-hash';m.block_time.timestamp=full['blockTime']+1;m.executed_transaction_count=1
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=future;u.slot.parent=slot;u.slot.status=pb.SLOT_FINALIZED
        self.assertIsNone(join.feed(u,u.ByteSize(),NOW+1))
        replay=copy.deepcopy(join)
        expected=[replay.complete_deferred_log(slot,sig,complete,NOW+2),replay.drain()]
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound):
            actual=[join.complete_deferred_log(slot,sig,complete,NOW+2),join.drain()]
        self.assertEqual(actual,expected)
        self.assertEqual([frame.update.block.slot for frame in actual],[slot,future])
        self.assertEqual(join.__dict__,replay.__dict__)
        self.assertFalse(join.pending);self.assertEqual(join.early_log_bytes,0)

    def test_repeated_truncation_is_explicitly_unavailable_without_partial_coverage(self):
        join,original,fetched,full,witness=self.joined()
        fetched['meta']['logMessages']=original['meta']['logMessages']
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_stream_log_supplement_incomplete'):
            authenticate_supplement(join,witness,fetched,ENDPOINT)
        self.assertEqual(join.completed,-1);self.assertIsNone(join.drain())

    def test_full_ws_duplicate_waits_for_same_authenticated_http_repair(self):
        join,original,fetched,full,witness=self.joined()
        logs=full['meta']['logMessages']
        join.hold_complete_log(full['slot'],full['transaction']['signatures'][0],logs)
        self.assertIsNone(join.drain());self.assertEqual(len(join.incomplete_logs),1)
        complete,_=authenticate_supplement(join,witness,fetched,ENDPOINT)
        frame=join.complete_deferred_log(full['slot'],full['transaction']['signatures'][0],complete,NOW+1)
        self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(full))
        self.assertFalse(join.deferred_complete_logs)

    def test_different_full_ws_candidate_cannot_replace_authenticated_http_content(self):
        join,original,fetched,full,witness=self.joined()
        wrong=list(full['meta']['logMessages']);wrong[-1]='different unobserved suffix'
        join.hold_complete_log(full['slot'],full['transaction']['signatures'][0],wrong)
        with self.assertRaisesRegex(EvidenceUnavailable,'supplement_identity_unverified'):
            authenticate_supplement(join,witness,fetched,ENDPOINT)
        self.assertIsNone(join.drain())

    def test_repaired_partial_duplicate_is_rejected_after_original_recent_horizon_expires(self):
        join,original,fetched,full,witness=self.joined();slot=full['slot'];sig=full['transaction']['signatures'][0]
        logs,_=authenticate_supplement(join,witness,fetched,ENDPOINT)
        join.complete_deferred_log(slot,sig,logs,NOW+1)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_SLOTS',2):
            for current in (slot+1,slot+2):
                u=pb.SubscribeUpdate(filters=['b']);meta=u.block_meta;meta.slot=current;meta.parent_slot=current-1
                meta.blockhash=str(current);meta.parent_blockhash=str(current-1)
                meta.block_time.timestamp=full['blockTime']+current-slot;meta.executed_transaction_count=0
                self.assertIsNone(join.feed(u,u.ByteSize(),NOW+current-slot))
                u=pb.SubscribeUpdate(filters=['f']);u.slot.slot=current;u.slot.parent=current-1;u.slot.status=pb.SLOT_FINALIZED
                self.assertIsNotNone(join.feed(u,u.ByteSize(),NOW+current-slot))
        self.assertNotIn((slot,sig),join.recent_incomplete_logs)
        with self.assertRaisesRegex(EvidenceUnavailable,'candidate_late_log_content'):
            join.defer_log(slot,sig,original['meta']['logMessages'],NOW+3)

    def test_truncation_keys_coalesce_in_same_original_log_budget_and_rebase(self):
        from meme_machine.solana_candidate_join import MAX_PENDING_BYTES
        join,original,fetched,full,witness=self.joined();slot=full['slot'];sig=full['transaction']['signatures'][0]
        size=join.early_log_bytes
        join.defer_log(slot,sig,original['meta']['logMessages'],NOW+1)
        self.assertEqual(join.early_log_bytes,size);self.assertEqual(len(join.incomplete_logs),1)
        replacement=rebase_log_join(join,slot)
        self.assertEqual(replacement.incomplete_logs,{(slot,sig)})
        self.assertEqual(replacement.early_log_bytes,size)
        self.assertEqual(replacement.filtered_from_slot,slot)
        excluded=rebase_log_join(join,slot+1)
        self.assertFalse(excluded.incomplete_logs);self.assertEqual(excluded.early_log_bytes,0)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',size):
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                join.defer_log(slot+1,'another-native-signature',original['meta']['logMessages'],NOW+1)
        self.assertLess(size,MAX_PENDING_BYTES)

    def test_only_explicit_marker_enters_repair_and_incomplete_status_cannot_authorize_it(self):
        for malformed in (None,'Log truncated',[1],['arbitrary truncation text'],['Log truncated']*2):
            self.assertFalse(explicit_truncation(malformed))
        self.assertEqual(log_input_reason(None),'candidate_stream_logs_null_or_missing')
        self.assertEqual(log_input_reason('Log truncated'),'candidate_stream_logs_not_array')
        self.assertEqual(log_input_reason([1]),'candidate_stream_logs_nonstring')
        self.assertEqual(log_input_reason(['arbitrary truncation text']),'candidate_stream_logs_truncation_text')
        self.assertEqual(log_input_reason(['Log truncated']),'candidate_stream_logs_explicit_marker')
        join,original,fetched,full,witness=self.joined()
        altered=dict(witness,transaction_index=witness['transaction_index']+1)
        with self.assertRaisesRegex(EvidenceUnavailable,'supplement_identity_unverified'):
            authenticate_supplement(join,altered,fetched,ENDPOINT)


def truncated_transaction(family='pump'):
    """Keep real original line offsets, including at least one decoded event."""
    full = copy.deepcopy(FIXTURE[family][0])
    events = (pump_events if family == 'pump' else pumpswap_trade_events)(full)
    prefix_length = min(event['index'] for event in events)+1
    original = copy.deepcopy(full)
    original['meta']['logMessages'] = full['meta']['logMessages'][:prefix_length]+['Log truncated']
    # getTransaction has no native transactionIndex. Its absence must not be
    # repaired by sorting signatures, timestamps, or assigning a fresh index.
    fetched = copy.deepcopy(full)
    fetched.pop('transactionIndex', None)
    return original, fetched, full, prefix_length


def retained_suffix_transaction(family='pump'):
    """Retain real fixture lines after an omitted middle log segment."""
    original, fetched, full, prefix_length = truncated_transaction(family)
    start = prefix_length+2
    suffix = full['meta']['logMessages'][start:start+3]
    original['meta']['logMessages'].extend(suffix)
    return original, fetched, full, prefix_length, start


def ordered_event_suffix_transaction(family='pump'):
    """Keep real lines around an omitted economic event, with no log edits."""
    full = copy.deepcopy(FIXTURE[family][0])
    decoder = pump_events if family == 'pump' else pumpswap_trade_events
    event_index = min(event['index'] for event in decoder(full))
    prefix_length = event_index-2
    positions = (event_index-1, event_index+1)
    original, fetched = copy.deepcopy(full), copy.deepcopy(full)
    original['meta']['logMessages'] = full['meta']['logMessages'][:prefix_length]+['Log truncated']+[
        full['meta']['logMessages'][index] for index in positions]
    fetched.pop('transactionIndex', None)
    return original, fetched, full, prefix_length, positions


class ArchiveFullLogContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'canonical.sqlite'
        self.now = [NOW]
        self.open_owner()
        self.addCleanup(lambda: self.state.writer.close())

    def open_owner(self):
        writer = EvidenceWriter(self.path, clock=lambda: self.now[0])
        self.state = SimpleNamespace(writer=writer,
            fence=FinalizedFence(writer, endpoint_identity=ENDPOINT))
        self.h = install(self.state)
        self.h.clock = self.h.lifecycle.clock = lambda: self.now[0]
        self.h.lifecycle.delivery_separated = True

    def request(self, original):
        event = next(event for event in pump_events(FIXTURE['pump'][0])
                     if event['event_type'] == 'create')
        self.address, self.mint = event['bonding_curve'], event['mint']
        self.scope = self.h.bind('pump', self.address, market_address=self.mint,
                                 aliases=(self.mint,))
        self.h.request('pump', self.address, original['slot'], original['slot'],
                       priority=3, deadline=self.now[0]+1000)
        return self.h.plan()[0]

    def snapshot(self):
        tables = ('acquisition_jobs', 'acquisition_page_receipts', 'acquisition_observations',
                  'rolling_economic_events', 'rolling_economic_addresses',
                  'candidate_history_outbox', 'candidate_pending_proofs',
                  'candidate_coverage', 'candidate_checkpoints',
                  'native_order_attestations')
        return {table: self.h.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                for table in tables}

    def assert_unpublished(self):
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_coverage').fetchone(), (0,))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone(), (0,))

    def test_retained_post_marker_lines_match_one_contiguous_complete_segment(self):
        before = self.snapshot()
        for family, decoder in (('pump', pump_events), ('pumpswap', pumpswap_trade_events)):
            with self.subTest(family=family):
                original, fetched, full, prefix_length, start = retained_suffix_transaction(family)
                logs = original['meta']['logMessages']
                complete = fetched['meta']['logMessages']
                self.assertEqual(logs[prefix_length], 'Log truncated')
                self.assertEqual(logs[prefix_length+1:], complete[start:start+3])
                self.assertGreater(start, prefix_length)
                self.assertLess(start+3, len(complete))
                self.assertEqual(sum(complete[index:index+3] == logs[prefix_length+1:]
                    for index in range(prefix_length, len(complete)-2)), 1)
                raw_inputs = canonical(original), canonical(fetched)
                supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
                repaired = complete_archive_transaction(original, supplement, endpoint_identity=ENDPOINT)
                self.assertEqual(repaired, full)
                self.assertEqual(decoder(repaired), decoder(full))
                self.assertEqual(repaired['transactionIndex'], original['transactionIndex'])
                self.assertEqual((canonical(original), canonical(fetched)), raw_inputs)
                self.assertFalse(any('truncat' in line.lower() for line in repaired['meta']['logMessages']))
        # Reproduce the observed 136-line archive shape: marker at 134, one
        # retained known line, and 154 complete lines. Extra inert fixture logs
        # model the provider's complete tail without inventing economic events.
        full = copy.deepcopy(FIXTURE['pump'][0])
        full['meta']['logMessages'].extend('Program log: offline complete tail '+str(index)
            for index in range(154-len(full['meta']['logMessages'])))
        original, fetched = copy.deepcopy(full), copy.deepcopy(full)
        original['meta']['logMessages'] = full['meta']['logMessages'][:134]+['Log truncated',
            full['meta']['logMessages'][145]]
        fetched.pop('transactionIndex', None)
        self.assertEqual(len(original['meta']['logMessages']), 136)
        self.assertEqual(len(fetched['meta']['logMessages']), 154)
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        self.assertEqual(complete_archive_transaction(original, supplement, endpoint_identity=ENDPOINT), full)
        self.assertEqual(pump_events(full), pump_events(FIXTURE['pump'][0]))
        # Reconstruct the prior marker-last metadata byte for byte, including
        # its original len(logs)-1 prefix. Existing page/input/lineage hashes
        # must remain identical for already retained ordinary supplements.
        old, response, _, _ = truncated_transaction()
        old_page = dict(data=[old], paginationToken=None)
        old_supplement = join_archive_log_supplement(old, response, endpoint_identity=ENDPOINT)
        job = dict(family='pump', address=PROGRAMS['pump'], lo=old['slot'], hi=old['slot'],
            pages=0, token=None, lineage=digest([]))
        old_observation = dict(endpoint_identity=ENDPOINT, method='getTransaction', commitment='finalized',
            slot=old['slot'], signature=old['transaction']['signatures'][0], transaction_index=old['transactionIndex'],
            original_transaction_hash=digest(old), fetched_transaction_hash=digest(response),
            original_prefix_length=len(old['meta']['logMessages'])-1, response=response)
        old_receipt = dict({key: value for key, value in old_observation.items() if key != 'response'},
            observation_body_hash=digest(old_observation))
        old_page_hash = digest(dict(method='getTransactionsForAddress+getTransaction',
            archive_page_hash=digest(old_page), archive_log_supplements=[old_receipt]))
        evidence = archive_page_evidence(job, old_page, endpoint_identity=ENDPOINT, supplements=(old_supplement,))
        self.assertEqual(canonical(evidence['supplement_observations']), canonical([old_observation]))
        self.assertEqual(canonical(evidence['supplement_receipts']), canonical([old_receipt]))
        self.assertEqual(evidence['page_hash'], old_page_hash)
        self.assertEqual(evidence['input_hash'], digest([None, dict(archive_page_hash=digest(old_page),
            archive_supplemented_page_hash=old_page_hash, archive_log_supplements=[old_receipt])]))
        self.assertEqual(evidence['lineage_hash'], digest([job['lineage'], old_page_hash]))
        self.assertEqual(self.snapshot(), before)
        self.assert_unpublished()

    def test_repeated_retained_segments_preserve_whole_complete_response_and_native_indices(self):
        before = self.snapshot()
        for family, decoder in (('pump', pump_events), ('pumpswap', pumpswap_trade_events)):
            for suffix, offsets in ((['Program log: known A', 'Program log: known B'], (153, 160)),
                                    (['Program log: repeated known line'], (153, 159, 166))):
                with self.subTest(family=family, matches=len(offsets), retained_lines=len(suffix)):
                    full = copy.deepcopy(FIXTURE[family][0])
                    full['meta']['logMessages'].extend('Program log: offline complete padding '+str(index)
                        for index in range(170-len(full['meta']['logMessages'])))
                    for start in offsets:
                        full['meta']['logMessages'][start:start+len(suffix)] = suffix
                    original, fetched = copy.deepcopy(full), copy.deepcopy(full)
                    original['meta']['logMessages'] = full['meta']['logMessages'][:152]+['Log truncated']+suffix
                    fetched.pop('transactionIndex', None)
                    complete = fetched['meta']['logMessages']
                    self.assertEqual(len(complete), 170)
                    self.assertEqual(sum(complete[start:start+len(suffix)] == suffix
                        for start in range(152, len(complete)-len(suffix)+1)), len(offsets))
                    raw_inputs = canonical(original), canonical(fetched)
                    supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
                    repaired = complete_archive_transaction(original, supplement, endpoint_identity=ENDPOINT)
                    # Multiple placements are consistent known content, not an
                    # alignment choice: the one entire full response supplies
                    # every event and its original full-log index unchanged.
                    self.assertEqual(repaired, full)
                    self.assertEqual(repaired['meta']['logMessages'], complete)
                    self.assertEqual(repaired['transactionIndex'], original['transactionIndex'])
                    self.assertEqual(decoder(repaired), decoder(FIXTURE[family][0]))
                    self.assertEqual([event['index'] for event in decoder(repaired)],
                                     [event['index'] for event in decoder(full)])
                    self.assertEqual((canonical(original), canonical(fetched)), raw_inputs)
                    metadata = archive_page_evidence(dict(family=family, address=PROGRAMS[family],
                        lo=original['slot'], hi=original['slot'], pages=0, token=None, lineage=digest([])),
                        dict(data=[original]), endpoint_identity=ENDPOINT, supplements=(supplement,))
                    self.assertEqual(metadata['supplement_observations'][0]['original_prefix_length'], 152)
                    self.assertEqual(metadata['supplement_observations'][0]['response'], fetched)
        self.assertEqual(self.snapshot(), before)
        self.assert_unpublished()

    def test_ordered_noncontiguous_lines_restore_real_omitted_events_at_full_log_indices(self):
        before = self.snapshot()
        for family, decoder, omitted_index in (('pump', pump_events, 86),
                                               ('pumpswap', pumpswap_trade_events, 44)):
            with self.subTest(family=family):
                original, fetched, full, prefix_length, positions = ordered_event_suffix_transaction(family)
                logs, complete = original['meta']['logMessages'], fetched['meta']['logMessages']
                self.assertEqual(full, FIXTURE[family][0])
                self.assertEqual(prefix_length, omitted_index-2)
                self.assertEqual(positions, (omitted_index-1, omitted_index+1))
                self.assertEqual(logs[prefix_length+1:], [complete[index] for index in positions])
                self.assertNotIn(complete[omitted_index], logs)
                self.assertTrue(complete[omitted_index].startswith('Program data: '))
                self.assertEqual(sum(complete[index:index+2] == logs[prefix_length+1:]
                    for index in range(prefix_length, len(complete)-1)), 0)
                inputs = canonical(original), canonical(fetched)
                supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
                repaired = complete_archive_transaction(original, supplement, endpoint_identity=ENDPOINT)
                self.assertEqual(canonical(repaired), canonical(full))
                self.assertEqual(repaired['meta']['logMessages'], complete)
                self.assertEqual(repaired['transactionIndex'], original['transactionIndex'])
                self.assertEqual(decoder(repaired), decoder(FIXTURE[family][0]))
                self.assertIn(omitted_index, [event['index'] for event in decoder(repaired)])
                records = economic_records(family, PROGRAMS[family], repaired,
                    endpoint_identity=ENDPOINT, seen=NOW, source='alchemy_finalized_repair')
                self.assertEqual([record.event_index for record in records],
                                 [event['index'] for event in decoder(full)])
                self.assertTrue(all(record.transaction_index == original['transactionIndex'] for record in records))
                self.assertEqual((canonical(original), canonical(fetched)), inputs)
        self.assertEqual(self.snapshot(), before)
        self.assert_unpublished()

    def test_141_prefix_ordered_mappings_preserve_all_164_complete_lines_and_multiplicity(self):
        before = self.snapshot()
        a, b = 'Program log: retained known A', 'Program log: retained known B'
        cases = (([a, b], ((142, a), (144, b)), 1),
                 ([a, b], ((142, a), (144, b), (150, a), (155, b)), 3),
                 ([a, a], ((142, a), (144, a), (150, a)), 3))
        for family, decoder in (('pump', pump_events), ('pumpswap', pumpswap_trade_events)):
            for suffix, placements, mappings in cases:
                with self.subTest(family=family, suffix=suffix, placements=placements):
                    full = copy.deepcopy(FIXTURE[family][0])
                    full['meta']['logMessages'].extend('Program log: inert complete padding '+str(index)
                        for index in range(164-len(full['meta']['logMessages'])))
                    for index, line in placements:full['meta']['logMessages'][index] = line
                    original, fetched = copy.deepcopy(full), copy.deepcopy(full)
                    original['meta']['logMessages'] = full['meta']['logMessages'][:141]+['Log truncated']+suffix
                    fetched.pop('transactionIndex', None)
                    self.assertEqual(len(original['meta']['logMessages']), 144)
                    self.assertEqual(len(fetched['meta']['logMessages']), 164)
                    complete = fetched['meta']['logMessages']
                    self.assertEqual(sum(complete[index:index+2] == suffix for index in range(141, 163)), 0)
                    self.assertEqual(sum(complete[first] == suffix[0] and complete[second] == suffix[1]
                        for first in range(141, 164) for second in range(first+1, 164)), mappings)
                    inputs = canonical(original), canonical(fetched)
                    supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
                    repaired = complete_archive_transaction(original, supplement, endpoint_identity=ENDPOINT)
                    self.assertEqual(canonical(repaired), canonical(full))
                    self.assertEqual(repaired['meta']['logMessages'], complete)
                    self.assertEqual(decoder(repaired), decoder(FIXTURE[family][0]))
                    self.assertEqual(repaired['transactionIndex'], original['transactionIndex'])
                    self.assertEqual((canonical(original), canonical(fetched)), inputs)
                    job = dict(family=family, address=PROGRAMS[family], lo=original['slot'], hi=original['slot'],
                               pages=0, token=None, lineage=digest([]))
                    evidence = archive_page_evidence(job, dict(data=[original]), endpoint_identity=ENDPOINT,
                                                     supplements=(supplement,))
                    self.assertEqual(evidence['supplement_observations'][0]['original_prefix_length'], 141)
                    self.assertEqual(evidence['supplement_observations'][0]['response'], fetched)
        self.assertEqual(self.snapshot(), before)
        self.assert_unpublished()

    def test_retained_suffix_mismatch_ambiguity_and_marker_failures_are_atomic(self):
        original, fetched, _, _ = truncated_transaction()
        prefix = ['Program log: verified prefix A', 'Program log: verified prefix B']
        suffix = ['Program log: retained suffix A', 'Program log: retained suffix B']
        original['meta']['logMessages'] = prefix+['Log truncated']+suffix
        fetched['meta']['logMessages'] = prefix+['Program log: omitted middle']+suffix+['Program log: later tail']
        job = self.request(original)
        baseline = self.snapshot()
        variants = {}
        def variant(name, original_logs=None, complete_logs=None):
            old, new = copy.deepcopy(original), copy.deepcopy(fetched)
            if original_logs is not None:old['meta']['logMessages'] = original_logs
            if complete_logs is not None:new['meta']['logMessages'] = complete_logs
            variants[name] = old, new
        variant('missing_known_line', complete_logs=prefix+suffix[:1])
        variant('altered_known_line', original_logs=prefix+['Log truncated']+suffix[:1]+['changed known line'])
        variant('reordered_known_lines', original_logs=prefix+['Log truncated']+list(reversed(suffix)))
        variant('insufficient_duplicate_occurrences', original_logs=prefix+['Log truncated']+suffix+suffix)
        # Repeated full placements are now covered by the positive whole-output
        # test: no placement is selected and no event/index is reconstructed.
        variant('prefix_only_overlap', original_logs=prefix+['Log truncated']+prefix)
        variant('partial_prefix_overlap', original_logs=prefix+['Log truncated', prefix[-1], 'Program log: omitted middle'])
        variant('multiple_markers', original_logs=prefix+['Log truncated']+suffix+['Log truncated'])
        variant('missing_marker', original_logs=prefix+suffix)
        variant('complete_still_truncated', complete_logs=fetched['meta']['logMessages']+['Log truncated'])
        variant('changed_prefix', complete_logs=['changed prefix']+fetched['meta']['logMessages'][1:])
        for name, (old, new) in variants.items():
            with self.subTest(shape=name):
                raw_inputs = canonical(old), canonical(new)
                with self.assertRaisesRegex(EvidenceUnavailable, 'archive_log_supplement_identity_unverified'):
                    supplement = join_archive_log_supplement(old, new, endpoint_identity=ENDPOINT)
                    self.h.commit_page(job, dict(data=[old]), finalized_through=job['hi'],
                                       supplements=(supplement,))
                self.assertEqual((canonical(old), canonical(new)), raw_inputs)
                self.assertEqual(self.snapshot(), baseline)
                self.assertFalse(self.h.db.in_transaction)
        self.assert_unpublished()

    def test_retained_suffix_keeps_raw_receipts_and_full_consumer_ack_across_restart(self):
        original, fetched, full, prefix_length, _ = retained_suffix_transaction()
        self.assert_retained_suffix_consumer_restart(original, fetched, full, prefix_length)

    def test_ordered_retained_lines_keep_full_consumer_ack_and_receipts_across_restart(self):
        original, fetched, full, prefix_length, _ = ordered_event_suffix_transaction()
        self.assert_retained_suffix_consumer_restart(original, fetched, full, prefix_length)

    def assert_retained_suffix_consumer_restart(self, original, fetched, full, prefix_length):
        job = self.request(original)
        page = dict(data=[original], paginationToken=None)
        raw_page = canonical(page)
        baseline = self.snapshot()
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        evidence = archive_page_evidence(job, page, endpoint_identity=ENDPOINT, supplements=(supplement,))
        self.assertEqual(self.snapshot(), baseline)
        with self.assertRaisesRegex(EvidenceUnavailable, 'incomplete_finalized_logs'):
            self.h.commit_page(job, page, finalized_through=job['hi'])
        self.assertEqual(self.snapshot(), baseline)
        result = self.h.commit_page(job, page, finalized_through=job['hi'], supplements=(supplement,))
        self.assertTrue(result['complete'])
        self.assertGreater(result['records'], 0)
        self.assertEqual(canonical(page), raw_page)
        self.assertEqual(result['archive_page_hash'], digest(page))
        self.assertEqual(evidence['value_hash'], hashlib.sha256(raw_page.encode()).hexdigest())
        self.assertEqual(result['archive_supplemented_page_hash'], evidence['page_hash'])
        provenance = result['archive_log_supplements'][0]
        self.assertEqual(provenance['original_prefix_length'], prefix_length)
        self.assertEqual(original['meta']['logMessages'][prefix_length], 'Log truncated')
        self.assertNotEqual(provenance['original_prefix_length'], len(original['meta']['logMessages'])-1)
        self.assertEqual(provenance['original_transaction_hash'], digest(original))
        self.assertEqual(provenance['fetched_transaction_hash'], digest(fetched))
        identity, encoded = self.h.db.execute("SELECT id,body FROM acquisition_observations "
            "WHERE kind='archive_log_supplement'").fetchone()
        self.assertEqual(provenance['observation_id'], identity)
        self.assertEqual(provenance['observation_body_hash'], hashlib.sha256(encoded.encode()).hexdigest())
        self.assertEqual(json.loads(encoded)['original_prefix_length'], prefix_length)
        self.assertEqual(json.loads(encoded)['response'], fetched)
        receipt = self.h.db.execute('SELECT input_hash,result FROM acquisition_page_receipts').fetchone()
        self.assertEqual(receipt[0], evidence['input_hash'])
        self.assertEqual(json.loads(receipt[1]), result)
        self.assert_unpublished()
        retained = self.snapshot()
        self.state.writer.close()
        self.open_owner()
        self.now[0] += 1
        self.assertEqual(self.snapshot(), retained)
        self.assertEqual(self.h.commit_page(job, page, finalized_through=job['hi'],
                                           supplements=(supplement,)), result)
        self.assertEqual(self.snapshot(), retained)
        life = self.h.lifecycle
        snapshot = capture(life)
        self.assertTrue(snapshot['rows'])
        self.assertEqual(snapshot['proofs'], [])
        delivered = deliver(snapshot)
        with closing(CandidateHistory(life.path, clock=lambda: NOW)) as consumer:
            self.assertEqual(consumer.db.execute('PRAGMA synchronous').fetchone(), (2,))
            receipts = consumer.db.execute('SELECT id,kind FROM source_receipts').fetchall()
            self.assertEqual(set(receipts), {(row[0], row[3]) for row in snapshot['rows']})
        life.publish()
        self.assert_unpublished()
        self.state.writer.close()
        self.open_owner()
        life = self.h.lifecycle
        self.assertEqual(capture(life)['rows'], snapshot['rows'])
        self.assertTrue(acknowledge(life, snapshot, delivered))
        proof_snapshot = capture(life)
        self.assertEqual(proof_snapshot['rows'], [])
        self.assertTrue(proof_snapshot['proofs'])
        life.publish()
        self.assert_unpublished()
        deliver(proof_snapshot)
        self.state.writer.close()
        self.open_owner()
        self.h.lifecycle.publish()
        self.assertEqual(self.h.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',
            (self.scope,)).fetchone(), (original['slot'],))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone(), (0,))
        expected = economic_records('pump', self.address, full, endpoint_identity=ENDPOINT,
            seen=NOW, source='alchemy_finalized_repair')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone(), (len(expected),))
        self.assertEqual(self.h.rolling.missing('pump', self.scope, job['lo'], job['hi']), [])
        final = self.snapshot()
        self.assertEqual(self.h.commit_page(job, page, finalized_through=job['hi'],
            supplements=(supplement,)), result)
        self.assertEqual(self.snapshot(), final)
        self.assertEqual(canonical(page), raw_page)

    def test_full_transaction_preserves_both_program_decoders_and_original_event_order(self):
        for family, decoder in (('pump', pump_events), ('pumpswap', pumpswap_trade_events)):
            with self.subTest(family=family):
                original, fetched, full, prefix_length = truncated_transaction(family)
                before = canonical(original), canonical(fetched)
                with self.assertRaisesRegex(EvidenceUnavailable, 'incomplete_finalized_logs'):
                    economic_records(family, PROGRAMS[family], original,
                        endpoint_identity=ENDPOINT, seen=NOW, source='alchemy_finalized_repair')
                supplement = join_archive_log_supplement(original, fetched,
                                                         endpoint_identity=ENDPOINT)
                repaired = complete_archive_transaction(original, supplement,
                                                         endpoint_identity=ENDPOINT)
                self.assertEqual(repaired, full)
                self.assertEqual((canonical(original), canonical(fetched)), before)
                self.assertNotIn('transactionIndex', fetched)
                self.assertEqual(repaired['transactionIndex'], original['transactionIndex'])
                self.assertEqual(decoder(repaired), decoder(full))
                prefix = copy.deepcopy(original)
                prefix['meta']['logMessages'].pop()
                self.assertEqual(decoder(prefix), [event for event in decoder(full)
                                                   if event['index'] < prefix_length])
                records = economic_records(family, PROGRAMS[family], repaired,
                    endpoint_identity=ENDPOINT, seen=NOW, source='alchemy_finalized_repair')
                self.assertEqual([record.event_index for record in records],
                                 [event['index'] for event in decoder(full)])
                self.assertTrue(all(record.transaction_index == original['transactionIndex']
                                    for record in records))
                with self.assertRaises(FrozenInstanceError):
                    supplement.fetched_json = '{}'
                fetched['meta']['logMessages'][0] = 'caller changed its mutable input'
                self.assertEqual(complete_archive_transaction(original, supplement,
                                 endpoint_identity=ENDPOINT), full)

    def test_original_failure_is_atomic_and_supplemented_page_keeps_raw_page_hash(self):
        original, fetched, _, prefix_length = truncated_transaction()
        job = self.request(original)
        page = dict(data=[original], paginationToken=None)
        raw = canonical(page)
        before = self.snapshot()
        with self.assertRaisesRegex(EvidenceUnavailable, 'incomplete_finalized_logs'):
            self.h.commit_page(job, page, finalized_through=job['hi'])
        self.assertEqual(self.snapshot(), before)
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        evidence = archive_page_evidence(job, page, endpoint_identity=ENDPOINT,
                                         supplements=(supplement,))
        result = self.h.commit_page(job, page, finalized_through=job['hi'],
                                    supplements=(supplement,))
        self.assertTrue(result['complete'])
        self.assertGreater(result['records'], 0)
        self.assertEqual(canonical(page), raw)
        self.assertEqual(evidence['value_hash'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertNotEqual(evidence['page_hash'], evidence['value_hash'])
        receipt = self.h.db.execute('SELECT input_hash FROM acquisition_page_receipts').fetchone()
        self.assertEqual(receipt, (evidence['input_hash'],))
        lineage = self.h.db.execute('SELECT lineage FROM acquisition_jobs WHERE id=?',
                                    (job['id'],)).fetchone()[0]
        self.assertEqual(lineage, evidence['lineage_hash'])
        witness = json.loads(self.h.db.execute('SELECT body FROM candidate_pending_proofs').fetchone()[0])
        self.assertEqual(witness['lineage_hash'], lineage)
        self.assertEqual(witness['method'], 'getTransactionsForAddress+getTransaction')
        self.assertEqual(witness['transaction_order_method'], 'getTransactionsForAddress')
        self.assertEqual(witness['log_content_method'], 'getTransaction')
        self.assertEqual(witness['log_content_commitment'], 'finalized')
        self.assertEqual(result['archive_page_hash'], digest(page))
        self.assertEqual(result['archive_supplemented_page_hash'], evidence['page_hash'])
        provenance = result['archive_log_supplements']
        self.assertEqual(len(provenance), 1)
        self.assertEqual(provenance[0]['original_transaction_hash'], digest(original))
        self.assertEqual(provenance[0]['fetched_transaction_hash'], digest(fetched))
        self.assertEqual(provenance[0]['original_prefix_length'], prefix_length)
        self.assertEqual(provenance[0]['transaction_index'], original['transactionIndex'])
        self.assertEqual(provenance[0]['endpoint_identity'], ENDPOINT)
        self.assertNotIn('response', provenance[0])
        observation = self.h.db.execute('SELECT id,body FROM acquisition_observations '
            "WHERE kind='archive_log_supplement'").fetchone()
        self.assertEqual(provenance[0]['observation_id'], observation[0])
        self.assertEqual(provenance[0]['observation_body_hash'],
                         hashlib.sha256(observation[1].encode()).hexdigest())
        self.assertEqual(json.loads(observation[1])['response'], fetched)
        # Input and lineage both bind hashes of the original unchanged archive
        # page and the separately retained authenticated provider response.
        bound = [{key: value for key, value in provenance[0].items() if key != 'observation_id'}]
        expected_page = digest(dict(method='getTransactionsForAddress+getTransaction',
                                    archive_page_hash=digest(page), archive_log_supplements=bound))
        self.assertEqual(evidence['page_hash'], expected_page)
        self.assertEqual(lineage, digest([job['lineage'], expected_page]))
        self.assertEqual(evidence['input_hash'], digest([job['token'],
            dict(archive_page_hash=digest(page), archive_supplemented_page_hash=expected_page,
                 archive_log_supplements=bound)]))
        receipt_result = json.loads(self.h.db.execute('SELECT result FROM acquisition_page_receipts').fetchone()[0])
        self.assertNotIn('response', canonical(receipt_result))
        self.h.lifecycle.publish()
        self.assert_unpublished()

    def test_failed_owner_transaction_rolls_back_supplement_receipts_and_economics(self):
        original, fetched, _, _ = truncated_transaction()
        job = self.request(original)
        page = dict(data=[original])
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        before = self.snapshot()
        ingest = self.h.ingest
        def interrupted_ingest(rows):
            ingest(rows)
            raise RuntimeError('injected-after-original-economic-ingest')
        with patch.object(self.h, 'ingest', side_effect=interrupted_ingest):
            with self.assertRaisesRegex(RuntimeError, 'injected-after-original-economic-ingest'):
                self.h.commit_page(job, page, finalized_through=job['hi'],
                                   supplements=(supplement,))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.h.db.in_transaction)
        result = self.h.commit_page(job, page, finalized_through=job['hi'], supplements=(supplement,))
        self.assertTrue(result['complete'])
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM acquisition_page_receipts').fetchone(), (1,))
        self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM acquisition_observations "
                                          "WHERE kind='archive_log_supplement'").fetchone(), (1,))
        self.assert_unpublished()

    def test_six_original_pages_keep_legacy_chain_before_supplemented_seventh_page(self):
        original, fetched, _, _ = truncated_transaction()
        job = self.request(original)
        lineage = digest([])
        for number in range(6):
            page = dict(data=[], paginationToken='original-token-'+str(number))
            expected_hash = digest(page)
            expected_input = digest([job['token'], page])
            lineage = digest([lineage, expected_hash])
            evidence = archive_page_evidence(job, page, endpoint_identity=ENDPOINT)
            self.assertEqual(evidence['value_hash'], expected_hash)
            self.assertEqual(evidence['page_hash'], expected_hash)
            self.assertEqual(evidence['input_hash'], expected_input)
            self.assertEqual(evidence['lineage_hash'], lineage)
            self.h.commit_page(job, page, finalized_through=job['hi'])
            stored = self.h.db.execute('SELECT input_hash FROM acquisition_page_receipts WHERE page=?',
                                       (number,)).fetchone()
            self.assertEqual(stored, (expected_input,))
            job = self.h.plan()[0]
            self.assertEqual(job['lineage'], lineage)
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        page = dict(data=[original], paginationToken=None)
        self.h.commit_page(job, page, finalized_through=job['hi'], supplements=(supplement,))
        witness = json.loads(self.h.db.execute('SELECT body FROM candidate_pending_proofs').fetchone()[0])
        self.assertEqual(witness['page_count'], 7)
        self.assertEqual(witness['method'], 'getTransactionsForAddress+getTransaction')
        self.assert_unpublished()

    def test_restart_preserves_token_supplement_provenance_and_idempotent_receipt(self):
        original, fetched, _, _ = truncated_transaction()
        old_job = self.request(original)
        page = dict(data=[original], paginationToken='retained-next-page-token')
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        result = self.h.commit_page(old_job, page, finalized_through=old_job['hi'],
                                    supplements=(supplement,))
        self.assertFalse(result['complete'])
        original_state = self.snapshot()
        self.state.writer.close()
        self.open_owner()
        self.now[0] += 1
        self.assertEqual(self.h.commit_page(old_job, page, finalized_through=old_job['hi'],
                                           supplements=(supplement,)), result)
        self.assertEqual(self.snapshot(), original_state)
        job = self.h.plan()[0]
        self.assertEqual((job['token'], job['pages'], job['last_slot'], job['last_index']),
                         ('retained-next-page-token', 1, original['slot'], original['transactionIndex']))
        self.h.request('pump', self.address, job['lo'], job['hi'], priority=3,
                       deadline=self.now[0]+1000)
        self.assertEqual(self.h.plan()[0], job)
        final_page = dict(data=[], paginationToken=None)
        evidence = archive_page_evidence(job, final_page, endpoint_identity=ENDPOINT,
                                         supplemented_before=True)
        self.h.commit_page(job, final_page, finalized_through=job['hi'])
        witness = json.loads(self.h.db.execute('SELECT body FROM candidate_pending_proofs').fetchone()[0])
        self.assertEqual(witness['page_count'], 2)
        self.assertEqual(witness['method'], 'getTransactionsForAddress+getTransaction')
        self.assertEqual(witness['log_content_method'], 'getTransaction')
        self.assertEqual(witness['lineage_hash'], evidence['lineage_hash'])
        self.assertEqual(witness['lineage_hash'], digest([job['lineage'], digest(final_page)]))
        old_result = json.loads(self.h.db.execute('SELECT result FROM acquisition_page_receipts '
            'WHERE job=? AND page=0', (job['id'],)).fetchone()[0])
        self.assertEqual(old_result['archive_log_supplements'][0]['fetched_transaction_hash'], digest(fetched))
        self.assert_unpublished()

    def test_invalid_supplements_never_acquire_financial_or_checkpoint_authority(self):
        original, fetched, _, _ = truncated_transaction()
        job = self.request(original)
        baseline = self.snapshot()
        changes = {
            'slot': lambda row: row.update(slot=row['slot']+1),
            'missing_slot': lambda row: row.pop('slot'),
            'boolean_slot': lambda row: row.update(slot=True),
            'block_time': lambda row: row.update(blockTime=row['blockTime']+1),
            'missing_block_time': lambda row: row.pop('blockTime'),
            'null_block_time': lambda row: row.update(blockTime=None),
            'native_index': lambda row: row.update(transactionIndex=original['transactionIndex']+1),
            'signature': lambda row: row['transaction']['signatures'].__setitem__(0, 'different'),
            'message': lambda row: row['transaction']['message']['accountKeys'].append('different'),
            'failed_transaction': lambda row: row['meta'].update(err={'InstructionError': [0, 'InvalidArgument']}),
            'missing_error': lambda row: row['meta'].pop('err'),
            'prefix': lambda row: row['meta']['logMessages'].__setitem__(0, 'changed prefix'),
            'still_truncated': lambda row: row['meta']['logMessages'].append('Log truncated'),
            'missing_logs': lambda row: row['meta'].pop('logMessages'),
            'null_logs': lambda row: row['meta'].update(logMessages=None),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                invalid = copy.deepcopy(fetched)
                change(invalid)
                with self.assertRaises(EvidenceUnavailable):
                    bad = join_archive_log_supplement(original, invalid, endpoint_identity=ENDPOINT)
                    self.h.commit_page(job, dict(data=[original]), finalized_through=job['hi'],
                                       supplements=(bad,))
                self.assertEqual(self.snapshot(), baseline)
        valid = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        variants = {
            'wrong_endpoint': (replace(valid, endpoint_identity='b'*64),),
            'duplicate': (valid, valid),
            'unrelated_transaction': (join_archive_log_supplement(
                *self.unrelated(original, fetched), endpoint_identity=ENDPOINT),),
            'tampered_original_json': (replace(valid, original_json='{}'),),
            'tampered_fetched_json': (replace(valid, fetched_json='{}'),),
            'untyped_mapping': (dict(original=original, fetched=fetched),),
        }
        for name, supplements in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(EvidenceUnavailable):
                    self.h.commit_page(job, dict(data=[original]), finalized_through=job['hi'],
                                       supplements=supplements)
                self.assertEqual(self.snapshot(), baseline)
        mutated = copy.deepcopy(original)
        mutated['transactionIndex'] += 1
        with self.assertRaises(EvidenceUnavailable):
            self.h.commit_page(job, dict(data=[mutated]), finalized_through=job['hi'],
                               supplements=(valid,))
        self.assertEqual(self.snapshot(), baseline)
        self.assert_unpublished()

    def test_fallback_selection_requires_explicit_successful_truncation(self):
        original, fetched, full, _ = truncated_transaction()
        self.assertEqual(missing_archive_log_transactions('pump', dict(data=[original])), (original,))
        self.assertEqual(missing_archive_log_transactions('pumpswap', dict(data=[original])), (original,))
        self.assertEqual(missing_archive_log_transactions('meteora', dict(data=[original])), ())
        for kind in ('complete', 'absent', 'null', 'error', 'missing_error'):
            with self.subTest(kind=kind):
                row = copy.deepcopy(full if kind == 'complete' else original)
                if kind == 'absent':row['meta'].pop('logMessages')
                if kind == 'null':row['meta']['logMessages'] = None
                if kind == 'error':row['meta']['err'] = {'InstructionError': [0, 'Custom']}
                if kind == 'missing_error':row['meta'].pop('err')
                self.assertEqual(missing_archive_log_transactions('pump', dict(data=[row])), ())
                with self.assertRaises(EvidenceUnavailable):
                    join_archive_log_supplement(row, fetched, endpoint_identity=ENDPOINT)
        malformed = copy.deepcopy(original)
        malformed['meta']['logMessages'].append('retained line after truncation marker')
        with self.assertRaises(EvidenceUnavailable):
            join_archive_log_supplement(malformed, fetched, endpoint_identity=ENDPOINT)
        for invalid_time in (None, True, -1, float(original['blockTime'])):
            with self.subTest(block_time=invalid_time):
                old, new = copy.deepcopy(original), copy.deepcopy(fetched)
                old['blockTime'] = new['blockTime'] = invalid_time
                with self.assertRaises(EvidenceUnavailable):
                    join_archive_log_supplement(old, new, endpoint_identity=ENDPOINT)

    @staticmethod
    def unrelated(original, fetched):
        original, fetched = copy.deepcopy(original), copy.deepcopy(fetched)
        original['slot'] += 1
        fetched['slot'] += 1
        return original, fetched

    def test_external_full_commit_ack_and_proof_publication_are_separate_fences(self):
        original, fetched, full, _ = truncated_transaction()
        job = self.request(original)
        supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
        self.h.commit_page(job, dict(data=[original]), finalized_through=job['hi'],
                           supplements=(supplement,))
        life = self.h.lifecycle
        snapshot = capture(life)
        self.assertTrue(snapshot['rows'])
        self.assertEqual(snapshot['proofs'], [])
        life.publish()
        self.assert_unpublished()
        result = deliver(snapshot)
        # Observe the existing FULL-durability consumer and exact real receipts;
        # an external commit still cannot ACK itself or publish canonical proof.
        with closing(CandidateHistory(life.path, clock=lambda: NOW)) as consumer:
            self.assertEqual(consumer.db.execute('PRAGMA synchronous').fetchone(), (2,))
            # The real Create event also passes RollingHistory.adopt(), which
            # emits its original scout receipt. Verify that receipt too, using
            # the actual kind rather than labeling every delivery canonical.
            external = consumer.db.execute('SELECT id,kind FROM source_receipts').fetchall()
            self.assertIn('scout', {row[3] for row in snapshot['rows']})
            self.assertEqual(set(external), {(row[0], row[3]) for row in snapshot['rows']})
            expected_canonical = {row[0] for row in snapshot['rows'] if row[3] == 'canonical'}
            self.assertTrue(expected_canonical)
            self.assertEqual({identity for identity, kind in external if kind == 'canonical'},
                             expected_canonical)
        life.publish()
        self.assert_unpublished()
        self.assertTrue(acknowledge(life, snapshot, result))
        proof_snapshot = capture(life)
        self.assertTrue(proof_snapshot['proofs'])
        self.assertEqual(proof_snapshot['rows'], [])
        life.publish()
        self.assert_unpublished()
        deliver(proof_snapshot)
        life.publish()
        self.assertEqual(self.h.db.execute('SELECT slot FROM candidate_checkpoints WHERE scope=?',
                                           (self.scope,)).fetchone(), (original['slot'],))
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone(), (0,))
        expected = economic_records('pump', self.address, full, endpoint_identity=ENDPOINT,
                                    seen=NOW, source='alchemy_finalized_repair')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone(), (len(expected),))
        before = self.snapshot()
        self.h.commit_page(job, dict(data=[original]), finalized_through=job['hi'],
                           supplements=(supplement,))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.h.db.execute('SELECT 1 FROM candidate_history_outbox WHERE consumed IS NULL').fetchone())
        self.assertEqual(self.h.rolling.missing('pump', self.scope, job['lo'], job['hi']), [])

    def test_actual_acquisition_cancellation_and_invalid_supplement_preserve_retry(self):
        from tests.test_solana_prewarm_startup import quiet_model_b
        original, fetched, full, _, _ = ordered_event_suffix_transaction()
        self.request(original)
        page = dict(data=[original], paginationToken=None)
        original_raw = canonical(page)
        attempts = []

        async def exercise():
            async def fixture_work(callback, priority=1, **metadata):
                return callback(self.state)
            # Reuse the existing real Model B fixture to establish startup;
            # this test's new acquisition still uses the separated consumer.
            self.h.lifecycle.delivery_separated = False
            boot_done = asyncio.Event()
            boot_done.set()
            try:
                await quiet_model_b(fixture_work, boot_done)
            finally:
                self.h.lifecycle.delivery_separated = True
            self.assertTrue(self.h.startup.snapshot()['released'])
            first_job = self.h.plan()[0]
            self.h.commit_page(first_job, dict(data=[], paginationToken='retained-archive-token'),
                               finalized_through=first_job['hi'])
            job, expected_config = self.h.plan()
            baseline = self.snapshot()

            for mode in ('cancel', 'invalid', 'success'):
                source = SelectiveSource(SimpleNamespace(credential='offline', identity=ENDPOINT), None)
                source.stop = asyncio.Event()
                source.batched = True
                supplement_started = asyncio.Event()
                calls = []

                async def work(callback, priority=1, **metadata):
                    value = callback(self.state)
                    if metadata.get('label') == 'source_commit':source.stop.set()
                    return value

                async def rpc(method, params, family, priority=4):
                    calls.append((method, copy.deepcopy(params), family, priority))
                    if method == 'getTransactionsForAddress':return page
                    if method == 'getSlot':return original['slot']
                    self.assertEqual(method, 'getTransaction')
                    if mode == 'cancel':
                        supplement_started.set()
                        await asyncio.Future()
                    result = copy.deepcopy(fetched)
                    if mode == 'invalid':result['slot'] += 1
                    return result

                source.work, source.measured_rpc = work, rpc
                if mode == 'cancel':
                    task = asyncio.create_task(source.acquire())
                    try:
                        await asyncio.wait_for(supplement_started.wait(), 1)
                        self.assertEqual(self.state.acquisition_inflight, {job['id']})
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):await task
                    finally:
                        if not task.done():task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                elif mode == 'invalid':
                    with self.assertRaisesRegex(EvidenceUnavailable, 'archive_log_supplement_identity_unverified') as caught:
                        await source.acquire()
                    from meme_machine.runtime.evidence_worker import failure_diagnostic
                    self.assertEqual(caught.exception.archive_log_failure_check,'fetched_slot')
                    self.assertIn(':archive_log_check=fetched_slot',failure_diagnostic(caught.exception))
                else:
                    await asyncio.wait_for(source.acquire(), 2)
                self.assertEqual(self.state.acquisition_inflight, set())
                self.assertEqual(canonical(page), original_raw)
                self.assertEqual(calls, [
                    ('getTransactionsForAddress', [self.address, expected_config], 'pump', job['priority']),
                    ('getSlot', [dict(commitment='finalized')], 'shared', job['priority']),
                    ('getTransaction', [original['transaction']['signatures'][0],
                        dict(commitment='finalized', encoding='json', maxSupportedTransactionVersion=1)],
                        'pump', job['priority']),
                ])
                attempts.append(calls)
                if mode != 'success':
                    self.assertEqual(self.snapshot(), baseline)
                    self.assertEqual(self.h.plan()[0], job)
                    self.assertFalse(self.h.db.in_transaction)

            completed = self.snapshot()
            self.assertEqual(self.h.db.execute('SELECT token,pages,status FROM acquisition_jobs '
                'WHERE id=?', (job['id'],)).fetchone(), (None, 2, 'complete'))
            self.assertEqual(self.h.db.execute("SELECT COUNT(*) FROM acquisition_observations "
                "WHERE kind='archive_log_supplement'").fetchone(), (1,))
            observation = json.loads(self.h.db.execute("SELECT body FROM acquisition_observations "
                "WHERE kind='archive_log_supplement'").fetchone()[0])
            self.assertEqual(observation['response'], fetched)
            self.assertEqual(observation['original_transaction_hash'], digest(original))
            expected = economic_records('pump', self.address, full, endpoint_identity=ENDPOINT,
                                        seen=NOW, source='alchemy_finalized_repair')
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM rolling_economic_events').fetchone(),
                             (len(expected),))
            self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM candidate_pending_proofs').fetchone(), (1,))
            self.assertFalse(self.h.db.execute('SELECT 1 FROM candidate_checkpoints WHERE scope=?',
                                               (self.scope,)).fetchone())
            supplement = join_archive_log_supplement(original, fetched, endpoint_identity=ENDPOINT)
            self.h.commit_page(job, page, finalized_through=job['hi'], supplements=(supplement,))
            self.assertEqual(self.snapshot(), completed)

        asyncio.run(exercise())
        self.assertEqual(len(attempts), 3)

    async def incomplete_archive_source(self,original,fetched,*,priority=3,upgrade=False):
        """Real supplement authentication after an already committed page."""
        from tests.test_solana_prewarm_startup import quiet_model_b
        self.request(original)
        self.h.gap(self.scope,original['slot'],original['slot'],'offline_archive_incomplete')
        async def work(callback,*args,**metadata):return callback(self.state)
        self.h.lifecycle.delivery_separated=False
        done=asyncio.Event();done.set()
        try:await quiet_model_b(work,done)
        finally:self.h.lifecycle.delivery_separated=True
        job,_=self.h.plan()
        self.h.commit_page(job,dict(data=[],paginationToken='retained-archive-token'),
            finalized_through=job['hi'])
        if priority<=2:
            self.h.request('pump',self.address,job['lo'],job['hi'],priority=priority,
                deadline=job['deadline'])
        job,_=self.h.plan()
        baseline=self.snapshot()
        source=SelectiveSource(SimpleNamespace(credential='offline',identity=ENDPOINT),None)
        source.stop=asyncio.Event();source.batched=True
        calls=[]
        async def rpc(method,params,family,priority=4):
            calls.append(method)
            if method=='getTransactionsForAddress':return dict(data=[original],paginationToken=None)
            if method=='getSlot':return original['slot']
            self.assertEqual(method,'getTransaction')
            if upgrade:
                self.h.request('pump',self.address,job['lo'],job['hi'],priority=1,
                    deadline=self.now[0]+3)
            source.stop.set()
            return fetched
        source.work,source.measured_rpc=work,rpc
        return source,job,baseline,calls

    def test_optional_truncated_provider_supplement_retains_job_gap_and_restart_without_false_coverage(self):
        original,fetched,_,_=truncated_transaction()
        fetched['meta']['logMessages'].append('Log truncated')
        inputs=canonical(original),canonical(fetched)
        async def exercise():
            source,job,baseline,calls=await self.incomplete_archive_source(original,fetched)
            await source.acquire()
            after=self.snapshot()
            for table in baseline:
                if table not in ('acquisition_jobs','acquisition_observations'):
                    self.assertEqual(after[table],baseline[table],table)
            row=self.h.db.execute('SELECT status,deadline,pages,token,lineage,error FROM acquisition_jobs '
                'WHERE id=?',(job['id'],)).fetchone()
            self.assertEqual(row[:5],('failed',job['deadline'],job['pages'],job['token'],job['lineage']))
            error=json.loads(row[5])
            self.assertEqual(error['kind'],'archive_provider_failure')
            self.assertIn(':archive_log_check=fetched_log_truncation',error['diagnostic'])
            for key in ('complete','economic_rejection','deadline_reset'):self.assertIs(error[key],False)
            self.assertIs(error['candidate_retained'],True)
            self.assertEqual(error['deadline'],job['deadline'])
            self.assertEqual(calls,['getTransactionsForAddress','getSlot','getTransaction'])
            self.assertFalse(self.state.acquisition_inflight)
            self.assertIsNone(self.h.plan())
            self.assertEqual(self.h.lifecycle.missing(self.scope,job['lo'],job['hi']),[(job['lo'],job['hi'])])
            self.assert_unpublished()
            self.assertEqual((canonical(original),canonical(fetched)),inputs)
            self.state.writer.close();self.open_owner()
            self.assertEqual(self.snapshot(),after)
            self.assertIsNone(self.h.plan())
            self.assertEqual(self.h.lifecycle.missing(self.scope,job['lo'],job['hi']),[(job['lo'],job['hi'])])
            self.assert_unpublished()
        asyncio.run(exercise())

    def test_accepted_optional_truncation_failure_commits_once_after_waiter_cancellation(self):
        original,fetched,_,_=truncated_transaction()
        fetched['meta']['logMessages'].append('Log truncated')
        async def exercise():
            source,job,baseline,calls=await self.incomplete_archive_source(original,fetched)
            queued=asyncio.Event();accepted=[]
            async def queued_work(callback,*args,**metadata):
                # Accept the first owner command after the physical supplement
                # response, but run it only after its async waiter has exited.
                if calls and calls[-1]=='getTransaction' and not accepted:
                    accepted.append(callback);queued.set()
                    await asyncio.Future()
                return callback(self.state)
            source.work=queued_work
            task=asyncio.create_task(source.acquire())
            try:
                await asyncio.wait_for(queued.wait(),1)
                self.assertEqual(self.h.db.execute('SELECT status FROM acquisition_jobs WHERE id=?',
                    (job['id'],)).fetchone(),('pending',))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
            self.assertEqual(len(accepted),1)
            self.assertFalse(self.state.acquisition_inflight)
            accepted[0](self.state)
            row=self.h.db.execute('SELECT status,deadline,pages,token,lineage,error FROM acquisition_jobs '
                'WHERE id=?',(job['id'],)).fetchone()
            self.assertEqual(row[:5],('failed',job['deadline'],job['pages'],job['token'],job['lineage']))
            failure=json.loads(row[5])
            self.assertIn(':archive_log_check=fetched_log_truncation',failure['diagnostic'])
            for key in ('complete','economic_rejection','deadline_reset'):self.assertIs(failure[key],False)
            self.assertIs(failure['candidate_retained'],True)
            self.assertEqual(len(self.snapshot()['acquisition_observations']),
                len(baseline['acquisition_observations'])+1)
            after=self.snapshot()
            accepted[0](self.state)
            self.assertEqual(self.snapshot(),after)
            for table in baseline:
                if table not in ('acquisition_jobs','acquisition_observations'):
                    self.assertEqual(after[table],baseline[table],table)
            self.assertEqual(self.h.lifecycle.missing(self.scope,job['lo'],job['hi']),[(job['lo'],job['hi'])])
            self.assert_unpublished()
        asyncio.run(exercise())

    def test_critical_truncated_provider_supplement_still_fails_closed(self):
        original,fetched,_,_=truncated_transaction()
        fetched['meta']['logMessages'].append('Log truncated')
        async def exercise():
            for priority in (2,1,0):
                with self.subTest(priority=priority):
                    self.state.writer.close()
                    self.path=Path(self.tmp.name)/('critical-'+str(priority)+'.sqlite')
                    self.open_owner()
                    source,job,baseline,_=await self.incomplete_archive_source(original,fetched,priority=priority)
                    with self.assertRaisesRegex(EvidenceUnavailable,'archive_log_supplement_identity_unverified') as caught:
                        await source.acquire()
                    self.assertEqual(caught.exception.archive_log_failure_check,'fetched_log_truncation')
                    self.assertEqual(self.snapshot(),baseline)
                    self.assertFalse(self.state.acquisition_inflight)
                    self.assert_unpublished()
        asyncio.run(exercise())

    def test_inflight_protective_upgrade_cannot_borrow_optional_truncation_isolation(self):
        original,fetched,_,_=truncated_transaction()
        fetched['meta']['logMessages'].append('Log truncated')
        async def exercise():
            source,job,baseline,_=await self.incomplete_archive_source(original,fetched,upgrade=True)
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_protective_acquisition_failed'):
                await source.acquire()
            self.assertEqual(self.h.db.execute('SELECT status,priority,deadline,pages,token,lineage FROM '
                'acquisition_jobs WHERE id=?',(job['id'],)).fetchone(),
                ('pending',1,self.now[0]+3,job['pages'],job['token'],job['lineage']))
            self.assertEqual(self.snapshot()['acquisition_observations'],baseline['acquisition_observations'])
            self.assertFalse(self.state.acquisition_inflight)
            self.assert_unpublished()
        asyncio.run(exercise())

    def test_optional_archive_identity_corruption_still_aborts_instead_of_becoming_provider_incomplete(self):
        original,fetched,_,_=truncated_transaction()
        fetched['transaction']['signatures'][0]='wrong-native-identity'
        # A truncation marker must not hide the earlier identity contradiction.
        fetched['meta']['logMessages'].append('Log truncated')
        async def exercise():
            source,_,baseline,_=await self.incomplete_archive_source(original,fetched)
            with self.assertRaisesRegex(EvidenceUnavailable,'archive_log_supplement_identity_unverified') as caught:
                await source.acquire()
            self.assertEqual(caught.exception.archive_log_failure_check,'transaction_identity')
            self.assertEqual(self.snapshot(),baseline)
            self.assertFalse(self.state.acquisition_inflight)
            self.assert_unpublished()
        asyncio.run(exercise())

    def test_optional_complete_supplement_with_conflicting_prefix_still_aborts(self):
        original,fetched,_,_=truncated_transaction()
        fetched['meta']['logMessages'][0]='different original prefix'
        async def exercise():
            source,_,baseline,_=await self.incomplete_archive_source(original,fetched)
            with self.assertRaisesRegex(EvidenceUnavailable,'archive_log_supplement_identity_unverified') as caught:
                await source.acquire()
            self.assertEqual(caught.exception.archive_log_failure_check,'prefix')
            self.assertEqual(self.snapshot(),baseline)
            self.assertFalse(self.state.acquisition_inflight)
            self.assert_unpublished()
        asyncio.run(exercise())

    def test_optional_truncation_with_hidden_log_contradictions_still_aborts(self):
        async def exercise():
            for fault in ('prefix','malformed_after_marker','original_marker_count',
                          'fetched_marker_count','unproven_retained_suffix'):
                with self.subTest(fault=fault):
                    self.state.writer.close()
                    self.path=Path(self.tmp.name)/(fault+'.sqlite');self.open_owner()
                    original,fetched,_,_=truncated_transaction()
                    fetched['meta']['logMessages'].append('Log truncated')
                    if fault=='prefix':fetched['meta']['logMessages'][0]='conflicting original prefix'
                    elif fault=='malformed_after_marker':fetched['meta']['logMessages'].append(17)
                    elif fault=='original_marker_count':original['meta']['logMessages'].append('Log truncated')
                    elif fault=='fetched_marker_count':fetched['meta']['logMessages'].append('Log truncated')
                    else:original['meta']['logMessages'].append('Program log: unproven retained suffix')
                    inputs=canonical(original),canonical(fetched)
                    source,_,baseline,_=await self.incomplete_archive_source(original,fetched)
                    with self.assertRaisesRegex(EvidenceUnavailable,'archive_log_supplement_identity_unverified') as caught:
                        await source.acquire()
                    # Preserve the original authenticator's rejection order;
                    # containment must independently reject these mixed faults.
                    self.assertEqual(caught.exception.archive_log_failure_check,'fetched_log_truncation')
                    self.assertEqual(self.snapshot(),baseline)
                    self.assertFalse(self.state.acquisition_inflight)
                    self.assertEqual((canonical(original),canonical(fetched)),inputs)
                    self.assert_unpublished()
        asyncio.run(exercise())

    def test_optional_truncation_with_all_retained_suffix_lines_remains_local(self):
        original,fetched,_,_,_=retained_suffix_transaction()
        fetched['meta']['logMessages'].append('Log truncated')
        async def exercise():
            source,job,baseline,_=await self.incomplete_archive_source(original,fetched)
            await source.acquire()
            self.assertEqual(self.h.db.execute('SELECT status,deadline,pages,token FROM acquisition_jobs '
                'WHERE id=?',(job['id'],)).fetchone(),
                ('failed',job['deadline'],job['pages'],job['token']))
            after=self.snapshot()
            for table in baseline:
                if table not in ('acquisition_jobs','acquisition_observations'):
                    self.assertEqual(after[table],baseline[table],table)
            self.assertEqual(self.h.lifecycle.missing(self.scope,job['lo'],job['hi']),[(job['lo'],job['hi'])])
            self.assert_unpublished()
        asyncio.run(exercise())


class ArchiveFailureDiscriminatorTests(unittest.TestCase):
    """Fixed attribution leaves every existing rejection and raw input intact."""
    def variants(self):
        original,fetched,_,_=truncated_transaction()
        rows=[]
        def add(check,mutate=lambda old,new:None,*,endpoint=ENDPOINT):
            old,new=copy.deepcopy(original),copy.deepcopy(fetched)
            mutate(old,new);rows.append((check,old,new,endpoint))
        add('endpoint_identity',endpoint='https://provider.invalid/private-fixture-key')
        rows.append(('response_shape',None,copy.deepcopy(fetched),ENDPOINT))
        add('original_slot',lambda old,new:old.pop('slot'))
        add('original_slot',lambda old,new:old.update(slot=True))
        add('original_index',lambda old,new:old.pop('transactionIndex'))
        add('original_index',lambda old,new:old.update(transactionIndex=False))
        add('original_signatures',lambda old,new:old['transaction'].pop('signatures'))
        add('original_signatures',lambda old,new:old['transaction'].update(signatures=[]))
        add('original_meta',lambda old,new:old.pop('meta'))
        add('fetched_meta',lambda old,new:new.pop('meta'))
        add('original_logs',lambda old,new:old['meta'].pop('logMessages'))
        add('fetched_logs',lambda old,new:new['meta'].pop('logMessages'))
        add('fetched_slot',lambda old,new:new.update(slot=old['slot']+1))
        add('original_time',lambda old,new:old.update(blockTime=True))
        add('fetched_time',lambda old,new:new.update(blockTime=False))
        add('block_time',lambda old,new:new.update(blockTime=old['blockTime']+1))
        add('transaction_identity',lambda old,new:new['transaction'].update(signatures=['private-signature-fixture']))
        add('original_error',lambda old,new:old['meta'].update(err={'private':'provider-message'}))
        add('fetched_error',lambda old,new:new['meta'].update(err={'private':'provider-message'}))
        add('fetched_index',lambda old,new:new.update(transactionIndex=old['transactionIndex']+1))
        add('original_log_shape',lambda old,new:old['meta'].update(logMessages=None))
        add('fetched_log_shape',lambda old,new:new['meta'].update(logMessages=None))
        add('fetched_log_line',lambda old,new:new['meta'].update(logMessages=[{'private':'fixture-log'}]))
        add('fetched_log_truncation',lambda old,new:new['meta']['logMessages'].append('Log truncated'))
        add('marker_count',lambda old,new:old['meta'].update(logMessages=list(new['meta']['logMessages'])))
        add('prefix',lambda old,new:new['meta']['logMessages'].__setitem__(0,'private-altered-prefix'))
        add('retained_suffix',lambda old,new:old['meta']['logMessages'].append('private-missing-suffix'))
        return rows

    def test_every_fixed_failure_check_preserves_generic_exception_and_raw_inputs(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        from meme_machine.solana_selective_history import ARCHIVE_LOG_FAILURE_CHECKS
        checked=set()
        for check,original,fetched,endpoint in self.variants():
            with self.subTest(check=check):
                before=canonical(original),canonical(fetched)
                with self.assertRaises(EvidenceUnavailable) as caught:
                    join_archive_log_supplement(original,fetched,endpoint_identity=endpoint)
                error=caught.exception
                self.assertIs(type(error),EvidenceUnavailable)
                self.assertEqual(error.args,('archive_log_supplement_identity_unverified',))
                self.assertEqual(error.archive_log_failure_check,check);checked.add(check)
                diagnostic=failure_diagnostic(error)
                self.assertIn(':archive_log_supplement_identity_unverified',diagnostic)
                self.assertIn(':archive_log_check='+check,diagnostic)
                self.assertNotIn('private-',diagnostic);self.assertNotIn('provider.invalid',diagnostic)
                self.assertEqual((canonical(original),canonical(fetched)),before)
        self.assertEqual(checked,set(ARCHIVE_LOG_FAILURE_CHECKS))

    def test_success_bytes_order_and_optional_real_native_index_remain_unchanged(self):
        original,fetched,full,_=truncated_transaction()
        for supplied_index in (False,True):
            with self.subTest(supplied_index=supplied_index):
                response=copy.deepcopy(fetched)
                if supplied_index:response['transactionIndex']=original['transactionIndex']
                before=canonical(original),canonical(response)
                supplement=join_archive_log_supplement(original,response,endpoint_identity=ENDPOINT)
                self.assertEqual(complete_archive_transaction(original,supplement,endpoint_identity=ENDPOINT),full)
                self.assertEqual((canonical(original),canonical(response)),before)

    def test_boolean_and_nonfinite_native_fields_keep_original_strict_rejections(self):
        cases=(('original','slot','original_slot'),('original','transactionIndex','original_index'),
            ('original','blockTime','original_time'),('fetched','slot','fetched_slot'),
            ('fetched','transactionIndex','fetched_index'),('fetched','blockTime','fetched_time'))
        for side,field,check in cases:
            for value in (True,float('nan'),float('inf')):
                with self.subTest(side=side,field=field,value=value):
                    original,fetched,_,_=truncated_transaction()
                    (original if side=='original' else fetched)[field]=value
                    with self.assertRaises(EvidenceUnavailable) as caught:
                        join_archive_log_supplement(original,fetched,endpoint_identity=ENDPOINT)
                    self.assertEqual(caught.exception.args,('archive_log_supplement_identity_unverified',))
                    self.assertEqual(caught.exception.archive_log_failure_check,check)

    def test_emitter_refuses_unknown_nonstring_or_foreign_exception_attributes(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        for reason in ('archive_log_supplement_identity_unverified','private-unknown-message'):
            for check in ([],{},None,True,7,'private-signature-fixture','prefix\nprivate-credential'):
                with self.subTest(reason=reason,check=check):
                    error=EvidenceUnavailable(reason);error.archive_log_failure_check=check
                    diagnostic=failure_diagnostic(error)
                    self.assertNotIn('archive_log_check=',diagnostic)
                    self.assertNotIn('private-',diagnostic)
        class ForeignEvidenceUnavailable(EvidenceUnavailable):pass
        for error in (ValueError('archive_log_supplement_identity_unverified'),
                      ForeignEvidenceUnavailable('archive_log_supplement_identity_unverified'),
                      EvidenceUnavailable('unresolved_evidence_gap')):
            error.archive_log_failure_check='prefix'
            self.assertNotIn('archive_log_check=',failure_diagnostic(error))

    def test_existing_redacted_cause_chain_retains_only_fixed_check(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        original,fetched,_,_=truncated_transaction()
        fetched['transaction']['signatures']=['private-signature-fixture']
        try:
            try:join_archive_log_supplement(original,fetched,endpoint_identity=ENDPOINT)
            except EvidenceUnavailable as error:
                raise ValueError('https://provider.invalid/private-credential') from error
        except ValueError as error:diagnostic=failure_diagnostic(error)
        self.assertIn(':caused_by:EvidenceUnavailable:archive_log_supplement_identity_unverified',diagnostic)
        self.assertIn(':archive_log_check=transaction_identity',diagnostic)
        self.assertNotIn('private-',diagnostic);self.assertNotIn('provider.invalid',diagnostic)
