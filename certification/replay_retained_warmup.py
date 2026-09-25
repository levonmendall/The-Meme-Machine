"""Offline replay of exact retained Alchemy receipts; never fetches market data."""
import argparse,gzip,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class WarmupParity(unittest.TestCase):
    fixture=None
    def test_real_capture_reconstructs_retained_twelve_second_warmup(self):
        from meme_machine import dlmm
        from meme_machine.store import digest
        from meme_machine.dlmm_tape import chain_verified_tapes
        from meme_machine.solana_evidence_plane import EvidenceWriter,FinalizedRecord,IntervalProof
        from meme_machine.solana_evidence_service import FinalizedFence
        from meme_machine.solana_evidence_runtime import RuntimeEvidence
        from tests import solana_dlmm_independent_v1 as lane
        data=json.load(gzip.open(self.fixture));pool=data['pool'];scope='pool:meteora:'+pool
        def snapshot(slot):
            receipt=data['snapshots'][str(slot)];q=receipt['request'];r=receipt['response']['result'];accounts=dict(zip(q['params'][0],r['value']))
            state=dlmm.pool(accounts[pool]);center=state['active']//70
            indices=[i for i in range(center-1,center+2) if accounts.get(dlmm.array_address(pool,i)) is not None]
            return dict(pool=pool,accounts=accounts,array_indices=indices,slot=slot,market_time=data['block_times'][str(slot)]['response']['result'],
                available_time=int(data['block_times'][str(slot)]['observed_at']),network='solana-mainnet',commitment='finalized',kind='real')
        endpoint={r['provider']['endpoint_identity'] for r in data['transactions'].values()}
        self.assertEqual(len(endpoint),1);endpoint=endpoint.pop()
        self.assertTrue(all(r['provider']['provider_kind']=='alchemy' for r in data['transactions'].values()))
        clock=[data['block_times'][str(data['slots'][0])]['observed_at']]
        with tempfile.TemporaryDirectory() as temp,patch('socket.socket.connect',side_effect=AssertionError('network_forbidden')):
            writer=EvidenceWriter(Path(temp)/'evidence',clock=lambda:clock[0]);fence=FinalizedFence(writer,endpoint_identity=endpoint)
            plane=RuntimeEvidence(writer.path,owner='meteora',clock=lambda:clock[0],command=fence.command)
            indexes={s['signature']:s for c in data['chunks'] for s in c['signatures']}
            records=[]
            for signature,receipt in data['transactions'].items():
                tx=receipt['response']['result'];sig=indexes[signature]
                self.assertEqual(receipt['request']['method'],'getTransaction');self.assertEqual(receipt['request']['params'][1]['commitment'],'finalized')
                self.assertEqual(tx['slot'],sig['slot']);self.assertEqual(tx['transaction']['signatures'][0],signature)
                records.append(FinalizedRecord(scope+':'+signature,scope,tx['slot'],signature,dlmm.PROGRAM,(pool,),tx['blockTime'],tx,'alchemy_finalized_repair',endpoint,receipt['observed_at'],transaction_index=sig['transactionIndex'],kind='transaction'))
            writer.ingest(records);ledger={};current=dlmm.validate(snapshot(data['slots'][0]),int(clock[0]));origin=current;cursor=[current['slot'],2**31-1,2**31-1];tapes=[]
            with patch.object(lane,'EVIDENCE_PLANE',plane),patch.object(lane.time,'sleep') as sleep:
                for chunk in data['chunks']:
                    receipt=chunk['census'];req=receipt['request'];page=receipt['response']['result']
                    self.assertEqual(req['method'],'getSignaturesForAddress');self.assertEqual(req['params'][0],pool)
                    self.assertEqual(req['params'][1]['commitment'],'finalized');self.assertGreaterEqual(receipt['observed_at'],data['snapshots'][str(chunk['end'])]['observed_at'])
                    until=req['params'][1].get('until')
                    if until:self.assertIn(until,ledger)
                    else:ledger={}
                    ledger.update({r['signature']:r for r in page})
                    expected=[r for r in ledger.values() if chunk['start']<r['slot']<=chunk['end'] and not r.get('err')]
                    self.assertEqual({r['signature'] for r in expected},{r['signature'] for r in chunk['signatures'] if r['slot']>chunk['start']})
                    boundary=min(r['slot'] for r in chunk['signatures'])
                    clock[0]=max([clock[0],receipt['observed_at'],data['block_times'][str(chunk['end'])]['observed_at']]+[data['transactions'][r['signature']]['observed_at'] for r in chunk['signatures']])
                    witness=dict(finalized=True,complete=True,scope=scope,lower_slot=boundary,upper_slot=chunk['end'],lineage_hash=digest(receipt),contract='retained_finalized_pool_census_and_verified_incremental_prefix')
                    writer.ingest([],proof=IntervalProof(scope,boundary,chunk['end'],'alchemy_finalized_repair',endpoint,witness,clock[0]))
                    end=snapshot(chunk['end']);adapter=SimpleNamespace(snapshot_from_state=lambda *a,**k:end)
                    with patch.object(lane.time,'time',return_value=clock[0]):
                        tape,cursor,meta=lane._capture_chunk(adapter,current,cursor,1)
                    self.assertEqual(meta['historical_provider_calls'],0);tapes.append(tape);current=tape.terminal
            self.assertEqual(sleep.call_count,12)
            combined=chain_verified_tapes(origin,tapes)
            a=data['attempt'];features=lane.pre_entry_features(origin,combined,current,a['candidate_at_warmup'],lane.load_policy())
            self.assertEqual(features,a['pre_entry_features'])
            self.assertEqual(lane.qualify(features,lane.load_policy()),a['qualification'])
            self.assertEqual(len(combined.events),a['fresh_swap_trigger_and_warmup']['swaps'])
            plane.close();writer.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);args=p.parse_args();WarmupParity.fixture=args.fixture
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WarmupParity));raise SystemExit(not result.wasSuccessful())
if __name__=='__main__':main()
