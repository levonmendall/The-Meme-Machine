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
from meme_machine.solana_candidate_join import CandidateTransactionJoin,scope_labels
from meme_machine.solana_stream_log_repair import authenticate_supplement,explicit_truncation,log_input_reason,rebase_log_join
from meme_machine.yellowstone import geyser_pb2 as pb


FIXTURE = json.loads((Path(__file__).parent/'fixtures/solana_selective_cohort.json').read_text())
ENDPOINT = 'a'*64
NOW = 1791400000.


class StreamFullLogContentTests(unittest.TestCase):
    def joined(self):
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
        u=pb.SubscribeUpdate(filters=['b']);m=u.block_meta;m.slot=slot;m.parent_slot=slot-1
        m.blockhash='native-hash';m.parent_blockhash='native-parent';m.block_time.timestamp=full['blockTime']
        m.executed_transaction_count=full['transactionIndex']+1
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
                    with self.assertRaisesRegex(EvidenceUnavailable, 'archive_log_supplement_identity_unverified'):
                        await source.acquire()
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
