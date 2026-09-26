"""Replay one complete retained Run-370 finalized census through Meteora's production trigger.

All 249 transactions and the original coverage witness are preserved. No
economic qualification claim and no synthetic replacement for missing state.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock,patch


def run(evidence,lane):
    sys.path.insert(0,str(Path(lane).resolve()))
    from meme_machine.solana_evidence_plane import EvidenceWriter,FinalizedRecord,IntervalProof,EvidenceUnavailable,digest
    from meme_machine.solana_evidence_runtime import RuntimeEvidence,METEORA_SCOPE
    from meme_machine.solana_evidence_service import FinalizedFence
    from tests import solana_dlmm_independent_v1 as strategy
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('retained_replay_network_forbidden')
    sys.addaudithook(guard)
    path=Path(evidence)/'certification-smoke/solana-evidence-plane.sqlite'
    db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
    slot=450532050;pool='EPGcGWGam81D5HRvUw8HEANKkoxRKg6vW5siXXbxtZbs'
    at,raw=db.execute('SELECT available,proof FROM coverage WHERE scope=? AND lo=? AND hi=? ORDER BY available LIMIT 1',(METEORA_SCOPE,slot,slot)).fetchone()
    witness=json.loads(raw)
    rows=db.execute('SELECT body,hash,first_seen FROM records WHERE scope=? AND slot=? ORDER BY transaction_index,event_index,identity',(METEORA_SCOPE,slot)).fetchall()
    assert len(rows)==witness['witness']['signature_count']==249
    assert all(body is not None for body,_,_ in rows),'retained_census_incomplete'
    records=[]
    for raw,checksum,seen in rows:
        body=json.loads(raw);assert digest(body)==checksum
        records.append(FinalizedRecord(**body,source=witness['source'],endpoint_identity=witness['endpoint_identity'],observed_at=seen))
    child=db.execute('SELECT * FROM stream_receipts WHERE scope=? AND slot=?',(METEORA_SCOPE,slot+1)).fetchone()
    assert child is not None
    db.close();now=[at]
    with tempfile.TemporaryDirectory() as tmp:
        writer=EvidenceWriter(Path(tmp)/'db',clock=lambda:now[0]);fence=FinalizedFence(writer,endpoint_identity=witness['endpoint_identity'])
        proof=IntervalProof(METEORA_SCOPE,slot,slot,witness['source'],witness['endpoint_identity'],witness['witness'],at)
        writer.ingest(records,proof=proof)
        writer.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',child)
        fence.health('phase','ACTIVE');fence.health('heartbeat',at)
        fence.health('finalized_frontier:'+METEORA_SCOPE,dict(slot=child[1],time=child[5],seen=at))
        plane=RuntimeEvidence(writer.path,owner='meteora',clock=lambda:now[0],command=fence.command)
        rpc=MagicMock();rpc.call.side_effect=rpc.call_many.side_effect=AssertionError('historical_rpc_forbidden')
        with patch.object(strategy,'EVIDENCE_PLANE',plane):
            swaps,meta=strategy._new_finalized_swaps(rpc,pool,slot-1)
            assert len(swaps)==1 and sum(r['swap_count'] for r in swaps)==1
            assert meta['historical_provider_calls']==0 and meta['source']=='local_finalized_evidence_plane'
            # The original observation time is retained; earlier access must not
            # borrow later sealing evidence.
            now[0]=at-.001
            try:strategy._new_finalized_swaps(rpc,pool,slot-1)
            except EvidenceUnavailable:pass
            else:raise AssertionError('future_coverage_leak')
        rpc.call.assert_not_called();rpc.call_many.assert_not_called()
        plane.close();writer.close()
    return dict(passed=True,artifact_id=10894299703,complete_retained_censuses=1,transactions=249,
        attempted_run370_pools_replayed=1,authenticated_swaps=1,historical_rpc_calls=0,
        point_in_time_fencing=True,qualified_economic_vectors='NOT_CLAIMED',
        limitation='One complete retained block proves lossless production trigger reconstruction, not a counterfactual replay of missing account/warmup intervals.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--lane',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=run(a.evidence,a.lane);Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
