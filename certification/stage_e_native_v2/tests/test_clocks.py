import copy
import gzip
import json
from pathlib import Path
import unittest

from certification.stage_e_native_v2.clock import DeterministicClock, validate_clock_samples
from certification.stage_e_native_v2.fixtures import (build_frame, construct_bounded,
    economic_projection, spec, templates, timestamp_offset)
from certification.stage_e_native_v2.contract import HERE, ROOT, read, sha256


def bounded_clock_proof():
    result={}
    for run in ('run373','run379','run380'):
        clock,frames=construct_bounded(run)
        before=(clock.time(),clock.monotonic());clock.begin()
        decoded=[]
        from meme_machine import solana_evidence_service as service
        targets=tuple(s.address for s in service.program_subscriptions())
        for i,raw in enumerate(frames):
            clock.advance_to(i*spec(run)['cadence_us'])
            message,total,retained=service.decode_source_message(raw,'',targets)
            decoded.append(dict(raw_hash=sha256(raw),source_transactions=total,
                retained_transactions=retained,source_timestamp=message['params']['result']['value']['block']['blockTime']))
        result[run]=dict(setup_wall=before[0],setup_monotonic=before[1],setup_elapsed_us=0,
            final_elapsed_us=clock.elapsed_us,bounded_frames=decoded,full_shape_executed=False)
    return result


class ClockTests(unittest.TestCase):
    def samples(self):
        clock=spec('run380')['clock']
        row=dict(wall=clock['wall_epoch'],monotonic=clock['monotonic_epoch'],
            source=clock['wall_epoch']-1,economic_now=clock['wall_epoch'],residence_now=clock['wall_epoch'],
            records=[dict(identity='fixed-economic-record',event_at=clock['wall_epoch']-1)],
            episodes=[dict(scope='program:meteora',side='archive',episode_id='episode1',
                source_origin=clock['wall_epoch']-1,wall_origin=clock['wall_epoch'],source_deadline=clock['wall_epoch']+119)])
        later=copy.deepcopy(row)
        for key in ('wall','monotonic','source','economic_now','residence_now'):later[key]+=1
        return [row,later],clock

    def test_coherent_wall_monotonic_and_unchanged_three_second_contract(self):
        from meme_machine.solana_maintenance_arbiter import ClockModel, ServiceLeases
        self.assertEqual(ServiceLeases().clock_error,3)
        rows,clock=self.samples();self.assertTrue(validate_clock_samples(rows,clock))
        native=ClockModel(clock['wall_epoch'],clock['monotonic_epoch'],3)
        native.check(clock['wall_epoch']+1,clock['monotonic_epoch']+1,{})

    def test_greater_than_three_second_incoherence_rejected_natively(self):
        from meme_machine.solana_maintenance_arbiter import ClockModel
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        rows,clock=self.samples();rows[1]['wall']+=3.0001
        with self.assertRaisesRegex(ValueError,'incoherence'):validate_clock_samples(rows,clock)
        native=ClockModel(clock['wall_epoch'],clock['monotonic_epoch'],3)
        with self.assertRaisesRegex(EvidenceUnavailable,'clock_relationship'):
            native.check(clock['wall_epoch']+4.0001,clock['monotonic_epoch']+1,{})

    def test_stale_timestamp_and_equal_240_rejected(self):
        for age in (240,241,300):
            rows,clock=self.samples();rows[0]['records'][0]['event_at']=clock['wall_epoch']-age
            with self.subTest(age=age),self.assertRaisesRegex(ValueError,'stale_economic'):
                validate_clock_samples(rows,clock)

    def test_fresh_source_cannot_disguise_stale_economic_events(self):
        rows,clock=self.samples();rows[0]['source']=rows[0]['wall']
        rows[0]['records'][0]['event_at']=clock['wall_epoch']-241
        with self.assertRaisesRegex(ValueError,'stale_economic'):validate_clock_samples(rows,clock)

    def test_source_advance_with_frozen_economic_aging_rejected(self):
        rows,clock=self.samples();rows[1]['economic_now']=rows[0]['economic_now']
        with self.assertRaisesRegex(ValueError,'aging_frozen'):validate_clock_samples(rows,clock)

    def test_timestamp_refresh_that_extends_eligibility_rejected(self):
        rows,clock=self.samples();rows[1]['records'][0]['event_at']+=1
        with self.assertRaisesRegex(ValueError,'timestamp_refreshed'):validate_clock_samples(rows,clock)

    def test_recovery_rebase_replacement_episode_and_origin_refresh_rejected(self):
        for key in ('episode_id','source_origin','wall_origin','source_deadline'):
            rows,clock=self.samples();e=rows[1]['episodes'][0]
            e[key]='replacement' if key=='episode_id' else e[key]+1
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'rebas'):
                validate_clock_samples(rows,clock)

    def test_clock_setup_is_nonaging_and_schedule_is_explicit(self):
        from unittest.mock import patch
        import time
        with patch.object(time,'time',side_effect=AssertionError('real_wall_clock_forbidden')):
            clock,frames=construct_bounded('run379')
            seed=build_frame('run379',0,bounded=True,historical_seed=True)
        self.assertEqual(clock.elapsed_us,0);self.assertFalse(clock.executing)
        self.assertEqual(seed,build_frame('run379',0,bounded=True,historical_seed=True))
        with self.assertRaisesRegex(ValueError,'illegal'):clock.advance_to(50000)
        clock.begin();clock.advance_to(50000)
        self.assertEqual(clock.time(),clock.wall_epoch+.05)
        with self.assertRaisesRegex(ValueError,'already_started'):clock.begin()

    def test_full_shapes_and_original_limits_declared_without_execution(self):
        a,b,c=(spec(run) for run in ('run373','run379','run380'))
        self.assertEqual((a['frames'],a['padding_bytes'],a['relevant_transactions_per_frame'],a['cadence_us']),(14,10*1024**2,80,750000))
        self.assertEqual((b['frames'],b['transactions_per_frame'],b['cadence_us'],b['control_commands']),(120,160,50000,25))
        self.assertEqual((c['frames'],c['cadence_us'],sum(c['transaction_mix'].values())),(240,270000,512))
        for s in (a,b,c):
            self.assertEqual((s['hot_residence_comparator'],s['retained_residence_comparator']),('<240','<240'))
            self.assertEqual(s['clock']['wall_monotonic_error_seconds'],3)

    def test_non_clock_economic_fields_unchanged_and_native_events_coherent(self):
        from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
        for run,old in [('run379','run379-production-transactions'),('run380','run380-production-templates')]:
            historical=json.loads(gzip.decompress((ROOT/'certification/tests/fixtures'/(old+'.json.gz')).read_bytes()))
            oldts={'transactions':historical['transactions']} if run=='run379' else historical['templates']
            newts=templates(run)
            self.assertEqual(set(newts),set(oldts))
            for lane,rows in oldts.items():
                for before,after in zip(rows,newts[lane]):
                    self.assertEqual(economic_projection(before),economic_projection(after))
            raw=json.loads(build_frame(run,0,bounded=True));block=raw['params']['result']['value']['block']
            times=[]
            for tx in block['transactions']:
                transaction=dict(tx,slot=spec(run)['start_slot'])
                times += [e['market_time'] for e in pump_events(transaction)+pumpswap_trade_events(transaction)]
            if run=='run380':self.assertTrue(times)
            self.assertTrue(all(t==block['blockTime'] for t in times))
            self.assertTrue(all(len(tx['transaction']['signatures'])==1 and ':' not in tx['transaction']['signatures'][0] for tx in block['transactions']))

    def test_run373_and_run380_bounded_decoding_proof(self):
        proof=bounded_clock_proof()
        self.assertEqual(set(proof),{'run373','run379','run380'})
        self.assertTrue(all(p['setup_elapsed_us']==0 and p['full_shape_executed'] is False for p in proof.values()))


if __name__=='__main__':unittest.main()
