"""Bounded startup reuse of genuine FULL-delivered canonical cold records.

All source, consumer, native and financial fixtures are disposable. The main
corpus uses original native frames, decoding, FULL delivery/ACK and retirement;
one separate producer record explicitly adds a synthetic nested field solely
to distinguish returned-object aliasing. No provider or readiness is mocked.
"""
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime.stop import Shutdown
from meme_machine.solana_evidence_plane import canonical, decode_body, digest
from meme_machine.solana_history_archive import prepare, apply
from meme_machine.solana_history_delivery import capture, deliver, acknowledge, generation
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_scoped_retirement import ScopedRetirement
from meme_machine.solana_selective_history import PROGRAMS, economic_records
from meme_machine.solana_selective_source import commit_candidate_batch, commit_control
from tests import test_candidate_commit_batches as native
from tests import test_retained_canonical_reference as retained
from tests.test_solana_closure import NOW, state_at


class ArchiveCorpus:
    def __init__(self,case,root,*,nested=False):
        self.case=case;self.root=Path(root)
        self.source=self.root/'solana-evidence.sqlite'
        self.consumer=self.root/'solana-candidate-history.sqlite'
        self.state,self.history=state_at(self.source)
        case.addCleanup(self.state.writer.close)
        self.life=self.history.lifecycle
        self.life.delivery_separated=True;self.life.path=self.consumer
        frames=[native.frame(slot) for slot in range(100,165 if not nested else 101)]
        first=economic_records('pump',PROGRAMS['pump'],frames[0].log_transactions[0],
            endpoint_identity='a'*64,seen=NOW,source='alchemy_finalized_stream')[0]
        self.mint=first.payload['event']['mint']
        self.history.bind('pump',self.mint)
        addresses={PROGRAMS[family]:program_scope(family) for family in ('pump','pumpswap')}
        for slot in range(100,frames[-1].update.block.slot+2):
            commit_control(self.state,native.frame(slot,logs=False))
        if nested:
            # A fixture-only field enters BEFORE the original canonical
            # producer, FULL receipt and archive hashes are established.
            first=replace(first,payload=dict(first.payload,event=dict(first.payload['event'],
                fixture_nested={'items':[{'value':1}]})))
            self.history.ingest([first])
        else:
            for start in range(0,len(frames),8):
                commit_candidate_batch(self.state,frames[start:start+8],addresses,
                    'startup-read-reuse',publish=False)
            commit_candidate_batch(self.state,[native.frame(165,logs=False)],addresses,
                'startup-read-reuse',publish=False)
        self.publish()
        with closing(CandidateHistory(self.consumer)) as shared:
            self.expected=shared.events('pump',self.mint)
            refs=shared.db.execute('SELECT identity,kind,body,hash FROM canonical_event_refs '
                'WHERE lane=? AND candidate=? ORDER BY slot,transaction_index,event_index,identity',
                ('pump',self.mint)).fetchall()
        case.assertGreaterEqual(len(refs),1 if nested else 65)
        self.refs=refs
        self.retired=refs if nested else refs[:64]
        self.identities={json.loads(row[2])['canonical_identity'] for row in self.retired}
        case.assertEqual(len(self.identities),1 if nested else 64)
        self.archive=self.retire(self.identities)
        self.archive_bytes=self.archive.read_bytes()
        self.archive_id=self.history.db.execute('SELECT id FROM scoped_cold_manifests WHERE path=?',
            (str(self.archive),)).fetchone()[0]
        self.archive_hash=hashlib.sha256(self.archive_bytes).hexdigest()
        for identity in self.identities:
            row=self.history.db.execute('SELECT body,archive FROM canonical_evidence WHERE identity=?',
                (identity,)).fetchone()
            case.assertEqual(row,(None,self.archive_id))
        if nested:
            record=decode_body(canonical(json.loads(zlib.decompress(self.archive_bytes))[0]['record']))
            with closing(CandidateHistory(self.consumer)) as shared:
                shared.append_reference('pump',self.mint,record,path=self.source,
                    identity='nested-second-reference',kind=self.retired[0][1])
                self.expected=shared.events('pump',self.mint)
                case.assertEqual(len(self.expected),2)
        from meme_machine.runtime.survivor_paper_book import PaperBook
        self.financial=self.root/'preserved-500.sqlite'
        with closing(PaperBook(self.financial,run_id='retained-500',lane='survivor',
                policy_hash='retained',initial=500)) as book:
            case.assertTrue(book.replay()['verified'])
        self.financial_hash=hashlib.sha256(self.financial.read_bytes()).hexdigest()
        self.snapshot()

    def publish(self):
        for _ in range(64):
            batch=capture(self.life)
            if batch is None:break
            self.case.assertTrue(acknowledge(self.life,batch,deliver(batch)))
            self.life.publish()
        self.life.publish()
        self.case.assertIsNone(self.life.unconsumed(program_scope('pump')))

    def retire(self,identities):
        ScopedRetirement(self.history)
        selected={identity:self.history.db.execute('SELECT * FROM canonical_evidence WHERE identity=?',
            (identity,)).fetchone() for identity in sorted(identities)}
        self.case.assertTrue(all(row is not None and row[9] is not None for row in selected.values()))
        plan=dict(selected=selected,pinned={},oldest=None,before=None,bindings=[],
            started=time.monotonic(),canonical_path=str(self.source.resolve()),
            generation=generation(self.life),limit=64,
            selection=dict(mode='disposable_actual_full_ack',metadata_rows=len(selected),
                metadata_row_bound=len(selected),candidate_scopes=1))
        prepared=prepare(plan)
        result=apply(self.history,plan,prepared)
        self.case.assertIsInstance(result,dict)
        self.case.assertTrue(result['canonical_generation_revalidated'])
        self.case.assertEqual(result['retired_records'],len(selected))
        return Path(prepared['receipt']['path'])

    def snapshot(self):
        self.source_before=retained.RetainedCanonicalReferenceTests.rows(self.source)
        self.consumer_before=retained.RetainedCanonicalReferenceTests.rows(self.consumer)

    def unchanged(self):
        self.case.assertEqual(retained.RetainedCanonicalReferenceTests.rows(self.source),self.source_before)
        self.case.assertEqual(retained.RetainedCanonicalReferenceTests.rows(self.consumer),self.consumer_before)
        self.case.assertEqual(hashlib.sha256(self.financial.read_bytes()).hexdigest(),self.financial_hash)

    @contextmanager
    def content(self,items):
        packed=zlib.compress(canonical(items).encode())
        self.archive.write_bytes(packed)
        self.history.db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
            (hashlib.sha256(packed).hexdigest(),self.archive_id))
        try:yield
        finally:
            self.archive.write_bytes(self.archive_bytes)
            self.history.db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
                (self.archive_hash,self.archive_id))


@contextmanager
def archive_io(directory):
    """Wrap actual file reads/inflate; never replace either result."""
    counts=dict(reads=0,decodes=0,paths=[]);packed=set()
    read=Path.read_bytes;factory=zlib.decompressobj
    def read_bytes(path):
        value=read(path)
        if path.parent==directory and path.suffix=='.zlib':
            counts['reads']+=1;counts['paths'].append(path);packed.add(value)
        return value
    class Decoder:
        def __init__(self,*args,**kwargs):self.original=factory(*args,**kwargs)
        def decompress(self,value,*args,**kwargs):
            if value in packed:counts['decodes']+=1
            return self.original.decompress(value,*args,**kwargs)
        def __getattr__(self,name):return getattr(self.original,name)
    with patch.object(Path,'read_bytes',read_bytes),patch.object(zlib,'decompressobj',Decoder):
        yield counts


class StartupArchiveReadReuseTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.enterContext(patch.dict(os.environ,MM_MODE='PAPER',MM_SOLANA_HISTORY_SEPARATED='1',clear=True))
        self.corpus=ArchiveCorpus(self,self.root/'corpus')

    @contextmanager
    def read(self,*,after=None):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            original=shared._reference_body;seen=[];caches=[]
            def resolve(*args,**kwargs):
                ref=args[4]
                cache=kwargs.get('_archive_cache')
                if cache is not None:caches.append(cache)
                result=original(*args,**kwargs)
                if ref['canonical_identity'] in self.corpus.identities:
                    seen.append(ref['canonical_identity'])
                    if after is not None:after(shared,ref,len(seen),result)
                return result
            with patch.object(shared,'_reference_body',side_effect=resolve):
                yield shared,seen,caches

    def test_explicit_cancelled_startup_read_reuses_one_archive_with_exact_order_and_no_writes(self):
        with self.read() as (shared,seen,caches),archive_io(self.corpus.archive.parent) as normal:
            expected=shared.events('pump',self.corpus.mint)
        self.assertEqual(expected,self.corpus.expected)
        self.assertEqual((normal['reads'],normal['decodes'],len(seen)),(64,64,64))
        self.assertEqual(caches,[])
        for _ in range(2):
            queries=dict(canonical=0,manifest=0)
            def trace(sql):
                if sql.startswith('SELECT body,hash,archive FROM canonical_evidence'):queries['canonical']+=1
                if sql.startswith('SELECT path,hash FROM scoped_cold_manifests'):queries['manifest']+=1
            def inspect(shared,ref,count,result):
                if count==1:
                    for db in shared._source_readers.values():db.set_trace_callback(trace)
            with self.read(after=inspect) as (shared,seen,caches),archive_io(self.corpus.archive.parent) as startup:
                actual=shared.events('pump',self.corpus.mint,cancelled=lambda:False)
            self.assertEqual(actual,expected)
            self.assertEqual((startup['reads'],startup['decodes'],len(seen)),(1,1,64))
            self.assertTrue(caches)
            self.assertTrue(all(cache=={} for cache in caches))
            self.assertEqual(queries['manifest'],63)
            self.assertGreaterEqual(queries['canonical'],63)
        self.corpus.unchanged()

    def test_one_startup_archive_slot_crosses_candidate_reads_without_changing_economics(self):
        # Same original FULL/ACK'd canonical manifest is reachable through two
        # disposable candidate-index scopes. The alias is an index fixture,
        # not a new canonical economic event or a funded/trading opportunity.
        alias='index-fixture-two'
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            shared.db.execute("""INSERT INTO canonical_event_refs
                SELECT lane,?,identity,slot,transaction_index,event_index,
                       market_time,kind,body,hash FROM canonical_event_refs
                WHERE lane='pump' AND candidate=?""",(alias,self.corpus.mint))
            self.assertTrue(shared.events('pump',alias,cancelled=lambda:False))
            with archive_io(self.corpus.archive.parent) as separate:
                original=shared.events('pump',self.corpus.mint,cancelled=lambda:False)
                second=shared.events('pump',alias,cancelled=lambda:False)
            self.assertEqual((separate['reads'],separate['decodes']),(2,2))
            self.assertEqual(original,self.corpus.expected)
            self.assertEqual([dict(v,candidate=self.corpus.mint) for v in second],original)
            cache={}
            with archive_io(self.corpus.archive.parent) as pooled:
                first=shared.events('pump',self.corpus.mint,cancelled=lambda:False,
                    _restore_archive_cache=cache)
                later=shared.events('pump',alias,cancelled=lambda:False,
                    _restore_archive_cache=cache)
            self.assertEqual((pooled['reads'],pooled['decodes']),(1,1))
            self.assertEqual(first,original)
            self.assertEqual(later,second)
            self.assertEqual(list(cache),['entry'])
            cache.clear()
            self.assertEqual(cache,{})
            with self.assertRaisesRegex(ValueError,'candidate_history_restore_archive_scope'):
                shared.events('pump',alias,_restore_archive_cache={})
            # A direct uncancelled reader keeps the original individual
            # archive-read semantics and never retains a process-wide slot.
            with archive_io(self.corpus.archive.parent) as normal:
                self.assertEqual(shared.events('pump',self.corpus.mint),original)
            self.assertEqual((normal['reads'],normal['decodes']),(64,64))
        self.assertEqual(hashlib.sha256(self.corpus.financial.read_bytes()).hexdigest(),
                         self.corpus.financial_hash)
        self.assertEqual(retained.RetainedCanonicalReferenceTests.rows(self.corpus.source),
                         self.corpus.source_before)

    def test_cross_candidate_cache_is_discarded_on_file_change_or_cancellation(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            cache={}
            expected=shared.events('pump',self.corpus.mint,cancelled=lambda:False,
                _restore_archive_cache=cache)
            self.assertEqual(expected,self.corpus.expected)
            self.assertTrue(cache)
            original=self.corpus.archive_bytes
            try:
                self.corpus.archive.write_bytes(original+b'new-source-identity')
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                    shared.events('pump',self.corpus.mint,cancelled=lambda:False,
                        _restore_archive_cache=cache)
                self.assertEqual(cache,{})
            finally:self.corpus.archive.write_bytes(original)
            cancelled=[False]
            def signal():return cancelled[0]
            self.assertEqual(shared.events('pump',self.corpus.mint,cancelled=signal,
                _restore_archive_cache=cache),expected)
            self.assertTrue(cache)
            cancelled[0]=True
            with self.assertRaises(Shutdown):
                shared.events('pump',self.corpus.mint,cancelled=signal,
                    _restore_archive_cache=cache)
            self.assertEqual(cache,{})
            self.assertEqual(shared.events('pump',self.corpus.mint),expected)
        self.corpus.unchanged()

    def test_every_cold_reference_rereads_canonical_row_manifest_and_authenticates_ref(self):
        targets=list(self.corpus.identities)
        for kind in ('canonical','manifest','record'):
            saved=[]
            def mutate(shared,ref,count,result):
                if count!=1:return
                if kind=='canonical':
                    identity=next(value for value in targets if value!=ref['canonical_identity'])
                    old=self.corpus.history.db.execute('SELECT hash FROM rolling_economic_events WHERE identity=?',
                        (identity,)).fetchone()
                    self.assertIsNotNone(old)
                    saved.append((identity,old[0]))
                    self.corpus.history.db.execute('UPDATE rolling_economic_events SET hash=? WHERE identity=?',
                        ('f'*64,identity))
                elif kind=='manifest':
                    saved.append(None)
                    self.corpus.history.db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
                        ('f'*64,self.corpus.archive_id))
                else:
                    sequence=caches[-1]['entry'][1]
                    target=next(item['record'] for item in sequence
                        if item['record']['identity']!=ref['canonical_identity'])
                    target['market_time']+=1
            try:
                with self.subTest(kind=kind),self.read(after=mutate) as (shared,_,caches):
                    with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                        shared.events('pump',self.corpus.mint,cancelled=lambda:False)
                    self.assertTrue(caches);self.assertTrue(all(cache=={} for cache in caches))
            finally:
                if saved and kind=='canonical':
                    identity,checksum=saved[0]
                    self.corpus.history.db.execute('UPDATE rolling_economic_events SET hash=? WHERE identity=?',
                        (checksum,identity))
                elif saved and kind=='manifest':self.corpus.history.db.execute('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
                    (self.corpus.archive_hash,self.corpus.archive_id))
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            identity,_,raw,checksum=self.corpus.retired[0]
            shared.db.execute('UPDATE canonical_event_refs SET hash=? WHERE lane=? AND candidate=? AND identity=?',
                ('f'*64,'pump',self.corpus.mint,identity))
            try:
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                    shared.events('pump',self.corpus.mint,cancelled=lambda:False)
            finally:shared.db.execute('UPDATE canonical_event_refs SET hash=? WHERE lane=? AND candidate=? AND identity=?',
                (checksum,'pump',self.corpus.mint,identity))
        self.corpus.unchanged()

    def test_file_change_between_hits_and_new_calls_never_reuses_stale_archive(self):
        def mutate(shared,ref,count,result):
            if count==1:self.corpus.archive.write_bytes(self.corpus.archive_bytes+b'changed')
        try:
            with self.read(after=mutate) as (shared,_,caches):
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                    shared.events('pump',self.corpus.mint,cancelled=lambda:False)
                self.assertTrue(all(cache=={} for cache in caches))
            with closing(CandidateHistory(self.corpus.consumer)) as shared:
                with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                    shared.events('pump',self.corpus.mint,cancelled=lambda:False)
        finally:self.corpus.archive.write_bytes(self.corpus.archive_bytes)
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            self.assertEqual(shared.events('pump',self.corpus.mint,cancelled=lambda:False),self.corpus.expected)
        self.corpus.unchanged()

    def test_cancellation_on_cache_miss_or_hit_clears_cache_and_progress_handler(self):
        for mode in ('miss','hit'):
            cancelled=[False];cold=[0]
            read_bytes=Path.read_bytes;stat=Path.stat
            def read_file(path):
                value=read_bytes(path)
                if mode=='miss' and path==self.corpus.archive:cancelled[0]=True
                return value
            def inspect(path,*args,**kwargs):
                value=stat(path,*args,**kwargs)
                if mode=='hit' and path==self.corpus.archive and cold[0]>=2:cancelled[0]=True
                return value
            with self.subTest(mode=mode),self.read() as (shared,_,caches):
                original=shared._reference_body
                def enter(*args,**kwargs):
                    if args[4]['canonical_identity'] in self.corpus.identities:cold[0]+=1
                    return original(*args,**kwargs)
                with patch.object(shared,'_reference_body',side_effect=enter), \
                        patch.object(Path,'read_bytes',read_file),patch.object(Path,'stat',inspect):
                    with self.assertRaises(Shutdown):
                        shared.events('pump',self.corpus.mint,cancelled=lambda:cancelled[0])
                self.assertTrue(caches)
                self.assertTrue(all(cache=={} for cache in caches))
                self.assertFalse(shared.db.in_transaction)
                self.assertGreater(shared.db.execute('WITH RECURSIVE p(n) AS (VALUES(0) UNION ALL '
                    'SELECT n+1 FROM p WHERE n<10000) SELECT SUM(n) FROM p').fetchone()[0],0)
                self.assertEqual(shared.events('pump',self.corpus.mint,cancelled=lambda:False),self.corpus.expected)
        self.corpus.unchanged()

    def test_metadata_change_inside_hit_cancel_callback_is_detected_before_return(self):
        phase=dict(cold=0,checks=0);mutated=[False]
        with self.read() as (shared,_,caches):
            original=shared._reference_body
            def enter(*args,**kwargs):
                if args[4]['canonical_identity'] in self.corpus.identities:
                    phase['cold']+=1;phase['checks']=0
                return original(*args,**kwargs)
            def check():
                if phase['cold']==2:
                    phase['checks']+=1
                    if phase['checks']==4:
                        self.corpus.archive.write_bytes(self.corpus.archive_bytes+b'changed')
                        mutated[0]=True
                return False
            try:
                with patch.object(shared,'_reference_body',side_effect=enter):
                    with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
                        shared.events('pump',self.corpus.mint,cancelled=check)
                self.assertTrue(mutated[0]);self.assertTrue(all(cache=={} for cache in caches))
            finally:self.corpus.archive.write_bytes(self.corpus.archive_bytes)
        self.corpus.unchanged()

    def test_original_duplicate_first_match_and_lazy_malformed_tail_semantics_are_preserved(self):
        items=json.loads(zlib.decompress(self.corpus.archive_bytes))
        altered=deepcopy(items[0]);altered['record']['market_time']+=1
        for changed in (items+[altered],items+[{}]):
            with self.corpus.content(changed),closing(CandidateHistory(self.corpus.consumer)) as shared:
                self.assertEqual(shared.events('pump',self.corpus.mint),self.corpus.expected)
                self.assertEqual(shared.events('pump',self.corpus.mint,cancelled=lambda:False),self.corpus.expected)
        for changed,error in (([altered]+items,ValueError),([{}]+items,KeyError)):
            with self.corpus.content(changed),closing(CandidateHistory(self.corpus.consumer)) as shared:
                for options in ({},dict(cancelled=lambda:False)):
                    with self.subTest(error=error.__name__,startup=bool(options)),self.assertRaises(error):
                        shared.events('pump',self.corpus.mint,**options)
        self.corpus.unchanged()

    def test_nested_payload_aliases_and_new_reads_are_independent(self):
        corpus=ArchiveCorpus(self,self.root/'nested',nested=True)
        with closing(CandidateHistory(corpus.consumer)) as shared:
            rows=shared.events('pump',corpus.mint,cancelled=lambda:False)
            self.assertEqual(len(rows),2)
            rows[0]['payload']['fixture_nested']['items'][0]['value']=99
            self.assertEqual(rows[1]['payload']['fixture_nested']['items'][0]['value'],1)
            self.assertTrue(all(row['payload']['fixture_nested']['items'][0]['value']==1
                for row in shared.events('pump',corpus.mint,cancelled=lambda:False)))
        corpus.unchanged();self.corpus.unchanged()

    def test_one_slot_archive_cache_evicts_a_b_a_without_reusing_stale_content(self):
        other=next(row for row in self.corpus.refs
            if json.loads(row[2])['canonical_identity'] not in self.corpus.identities)
        other_id=json.loads(other[2])['canonical_identity']
        archive_b=self.corpus.retire({other_id})
        self.assertNotEqual(archive_b,self.corpus.archive)
        self.corpus.snapshot() # This test's second genuine retirement is intentional.
        a=self.corpus.retired[0]
        with closing(CandidateHistory(self.corpus.consumer)) as shared,archive_io(self.corpus.archive.parent) as counts:
            cache={};results=[]
            # The same private slot used by events() is exercised in a known
            # order, independent of SQLite's unspecified reference scan order.
            for identity,kind,raw,checksum in (a,other,a):
                ref=json.loads(raw);self.assertEqual(digest(ref),checksum)
                results.append(shared._reference_body('pump',self.corpus.mint,identity,kind,ref,
                    _archive_cache=cache,_check=lambda:None))
                self.assertEqual(set(cache),{'entry'})
                self.assertEqual(cache['entry'][0][1],self.corpus.archive_id if identity==a[0]
                    else self.corpus.history.db.execute('SELECT archive FROM canonical_evidence WHERE identity=?',
                        (other_id,)).fetchone()[0])
            self.assertEqual(results[0],results[2])
            self.assertEqual((counts['reads'],counts['decodes']),(3,3))
            self.assertEqual(counts['paths'],[self.corpus.archive,archive_b,self.corpus.archive])
            cache.clear()
        self.corpus.unchanged()
