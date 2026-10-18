"""Pure bounded native cohort metadata; no source or consumer authority."""
import hashlib
import unittest
from unittest.mock import patch
from meme_machine.runtime.economic_cohort import EconomicCohorts,checksum

NOW=1700000000.0

def fanout(rows,obligations):
    return tuple((row[0],row[1],sum(o[1:3]==row[:2] for o in obligations),
        hashlib.sha256(b''.join(len(o[0].encode()).to_bytes(4,'big')+o[0].encode() for o in obligations if o[1:3]==row[:2])).hexdigest()) for row in rows)



class EconomicCohortTests(unittest.TestCase):
    def meter(self):return EconomicCohorts('pump',dict(source_pid=123,run_identity='a'*32))

    def test_requires_complete_source_exact_economics_and_every_fanout_ack(self):
        meter=self.meter();meter.open('window',('program:pump',))
        row=('program:pump','event',checksum('body'),10,NOW)
        meter.arrivals('window',(row,row))
        obligations=(('one',*row[:2],checksum('first'),'consumer-1'),
            ('two',*row[:2],checksum('second'),'consumer-2'))
        meter.committed('window',((*row,True),),obligations,fanout_complete=fanout((row,),obligations))
        meter.seal('window',10,10,checksum('source'),complete=False)
        meter.acknowledged((('one',checksum('first')),('two',checksum('second'))))
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        self.assertEqual(meter.snapshot()['full_market_rate'],
            'UNKNOWN_REQUIRES_CONTIGUOUS_SOURCE_AND_FRESH_HEAD_CENSUS')

    def test_reconciles_only_after_final_ack_and_keeps_detached_summary(self):
        meter=self.meter();meter.open('window',('program:pump',))
        row=('program:pump','event',checksum('body'),10,NOW)
        meter.arrivals('window',(row,));obligations=(('one',*row[:2],checksum('source'),'consumer'),)
        meter.committed('window',((*row,False),),obligations,fanout_complete=fanout((row,),obligations))
        meter.seal('window',10,10,checksum('coverage'),complete=True,expected_economics=(1,checksum([row[:4]])))
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter.acknowledged((('one',checksum('source')),))
        result=meter.snapshot();self.assertEqual(result['completed_cohorts'],1)
        self.assertEqual(result['closed'][0]['replay_canonical'],1)
        self.assertEqual(result['closed'][0]['new_canonical'],0)
        result['closed'][0]['unique_economics']=999
        self.assertEqual(meter.snapshot()['closed'][0]['unique_economics'],1)
        meter.open('window',('program:pump',))
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_bounds_and_conflicts_remain_unknown_with_no_partial_positive(self):
        for kind in ('bound','hash','ack','scope'):
            with self.subTest(kind=kind):
                meter=self.meter();meter.open('window',('program:pump',))
                row=('program:pump','event',checksum('body'),10,NOW)
                meter.arrivals('window',(row,))
                if kind=='bound':
                    with patch('meme_machine.runtime.economic_cohort.MAX_BYTES',meter.bytes):
                        meter.arrivals('window',(('program:pump','another',checksum('body'),10,NOW),))
                elif kind=='hash':meter.committed('window',((row[0],row[1],checksum('changed'),10,NOW,True),),())
                elif kind=='scope':meter.arrivals('window',(('foreign','event',checksum('body'),10,NOW),))
                else:
                    obligations=(('one',*row[:2],checksum('source'),'consumer'),)
                    meter.committed('window',((*row,True),),obligations,fanout_complete=fanout((row,),obligations))
                    meter.acknowledged((('one',checksum('changed')),))
                result=meter.snapshot();self.assertEqual(result['state'],'UNKNOWN')
                self.assertFalse(result['funding_authority']);self.assertEqual(result['completed_cohorts'],0)


    def test_pons_native_history_publication_is_not_source_full_ack_completion(self):
        meter=EconomicCohorts('pons',dict(source_pid=123,stage='current'))
        meter.open('window',('curve',))
        row=('curve','block:tx:log',checksum('body'),10,NOW)
        meter.arrivals('window',(row,));meter.committed('window',((*row,True),),())
        meter.seal('window',10,10,checksum('bounded-query'),complete=False)
        result=meter.snapshot()
        self.assertEqual(result['active'][0]['canonical_publications'],1)
        self.assertEqual(result['active'][0]['native_new'],1)
        self.assertEqual(result['delivery_contract'],'PONS_CONSUMER_COMPLETION_UNESTABLISHED')
        self.assertEqual(result['completed_cohorts'],0)
        meter.acknowledged(())
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_fixed_container_and_native_positions_are_bounded_before_iteration_or_retention(self):
        meter=self.meter();visited=[]
        def unbounded():
            visited.append(True)
            while True:yield 'scope'
        meter.open('window',unbounded())
        self.assertEqual(visited,[]);self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
        meter=self.meter()
        with patch('meme_machine.runtime.economic_cohort.MAX_BYTES',96):meter.open('window',('scope',))
        self.assertEqual(meter.snapshot()['active_cohorts'],0)
        meter=self.meter();meter.open('window',('scope',))
        meter.arrivals('window',(('scope','event',checksum('body'),2**63,NOW),))
        self.assertEqual(meter.snapshot()['active_identities'],0)
        self.assertEqual(meter.snapshot()['state'],'UNKNOWN')

    def test_missing_or_partial_fanout_witness_cannot_become_a_zero_fanout_success(self):
        for kind in ('missing','partial','inconsistent'):
            meter=self.meter();meter.open('window',('scope',))
            row=('scope','event',checksum('body'),10,NOW);meter.arrivals('window',(row,))
            full=(('one',*row[:2],checksum('source'),'consumer'),)
            proof=None if kind=='missing' else fanout((row,),full)
            selected=full if kind!='partial' else ()
            if kind=='inconsistent':proof=((row[0],row[1],0,hashlib.sha256(b'').hexdigest()),)
            meter.committed('window',((*row,True),),selected,fanout_complete=proof)
            meter.seal('window',10,10,checksum('source'),complete=True,expected_economics=(1,checksum([row[:4]])))
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
            self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter=self.meter();meter.open('window',('scope',));meter.arrivals('window',(row,))
        meter.committed('window',((*row,True),),(),fanout_complete=fanout((row,),()))
        meter.seal('window',10,10,checksum('source'),complete=True,expected_economics=(1,checksum([row[:4]])))
        self.assertEqual(meter.snapshot()['completed_cohorts'],1)

    def test_explicit_complete_decoder_census_is_required_even_for_an_empty_window(self):
        for expected in (None,(1,checksum([['scope','missing',checksum('body'),10]]))):
            meter=self.meter();meter.open('empty',('scope',))
            meter.seal('empty',10,10,checksum('native-proof'),complete=True,expected_economics=expected)
            self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
            self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter=self.meter();meter.open('empty',('scope',))
        meter.seal('empty',10,10,checksum('native-proof'),complete=True,expected_economics=(0,checksum([])))
        self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter.committed('empty',(),(),fanout_complete=())
        self.assertEqual(meter.snapshot()['completed_cohorts'],1)

    def test_complete_source_census_cannot_expand_while_waiting_for_commit_or_ack(self):
        for delayed in ('commit','ack'):
            with self.subTest(delayed=delayed):
                meter=self.meter();meter.open('window',('scope',))
                row=('scope','one',checksum('first'),10,NOW);meter.arrivals('window',(row,))
                obligations=(('outbox',*row[:2],checksum('source'),'consumer'),)
                if delayed=='ack':
                    meter.committed('window',((*row,True),),obligations,fanout_complete=fanout((row,),obligations))
                meter.seal('window',10,11,checksum('native-proof'),complete=True,
                    expected_economics=(1,checksum([row[:4]])))
                meter.arrivals('window',(('scope','two',checksum('second'),11,NOW),))
                meter.acknowledged((('outbox',checksum('source')),))
                self.assertEqual(meter.snapshot()['state'],'UNKNOWN')
                self.assertEqual(meter.snapshot()['completed_cohorts'],0)
        meter=self.meter();meter.open('window',('scope',));meter.arrivals('window',(row,))
        meter.seal('window',10,10,checksum('native-proof'),complete=True,
            expected_economics=(1,checksum([row[:4]])))
        meter.arrivals('window',(row,)) # Exact duplicate remains idempotent.
        meter.committed('window',((*row,True),),(),fanout_complete=fanout((row,),()))
        self.assertEqual(meter.snapshot()['completed_cohorts'],1)

    def test_metadata_covers_two_full_original_native_batches_and_finite_fanout(self):
        from meme_machine.runtime.economic_cohort import MAX_IDENTITIES,MAX_OBLIGATIONS
        meter=self.meter()
        for batch in range(2):
            cohort='batch-'+str(batch);meter.open(cohort,('program:pump',))
            for offset in range(0,8*2048,2048):
                rows=[];obligations=[];proof=[]
                for n in range(offset,offset+2048):
                    identity=checksum(['identity',batch,n]);scope='program:pump'
                    row=(scope,identity,checksum(['body',batch,n]),100+batch*8+n//2048,NOW)
                    rows.append(row);ids=(checksum(['first',identity]),checksum(['second',identity]))
                    obligations.extend((key,scope,identity,checksum(['source',key]),'candidate:'+str(i))
                        for i,key in enumerate(ids))
                    witness=hashlib.sha256(b''.join(len(k.encode()).to_bytes(4,'big')+k.encode() for k in ids)).hexdigest()
                    proof.append((scope,identity,2,witness))
                meter.arrivals(cohort,rows)
                meter.committed(cohort,[(*r,True) for r in rows],obligations,fanout_complete=proof)
        result=meter.snapshot();self.assertIsNone(result['reason'])
        self.assertEqual(result['active_identities'],MAX_IDENTITIES)
        self.assertEqual(result['active_fanout'],MAX_OBLIGATIONS)
        meter.open('overflow',('program:pump',))
        meter.arrivals('overflow',(('program:pump','extra',checksum('extra'),200,NOW),))
        self.assertEqual(meter.snapshot()['reason'],'BOUND')
        self.assertEqual(meter.snapshot()['active_identities'],MAX_IDENTITIES)
