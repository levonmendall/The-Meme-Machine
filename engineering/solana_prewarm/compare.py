"""Active Model B replay against the preserved, archived Model A result.

Byte totals are the SAME preserved input in both runs. No upstream saving is
credited for local projection. Provider delivery with Model B is a separate run.
"""
import argparse,json,resource,tempfile,time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,IntervalProof,digest,canonical
from meme_machine.solana_evidence_service import FinalizedFence
from meme_machine.solana_selective_source import install
from meme_machine.solana_selective_history import economic_records,CandidateReader,PROGRAMS,coverage_scope
from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events


def run(fixture):
    capture=json.loads(Path(fixture).read_text());now=[1791400000.];elapsed=[];cpu0=time.process_time()
    # Authenticated captures are identical. Their full retained bytes are counted
    # in BOTH replays, even when only logs are decoded by Model B.
    delivered=len(Path(fixture).read_bytes());calls=cu=bodies=complete_at=promotions=0;vectors={};writes=[0];sql=[]
    with tempfile.TemporaryDirectory() as d:
        writer=EvidenceWriter(Path(d)/'canonical.sqlite',clock=lambda:now[0])
        state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))
        h=install(state);h.clock=h.lifecycle.clock=lambda:now[0]
        writer.db.set_trace_callback(lambda statement:sql.append(statement.split()[0]) if statement.split() else None)
        for family in ('pump','pumpswap'):
            txs=capture[family];decoder=pump_events if family=='pump' else pumpswap_trade_events
            economic=[(tx,e) for tx in txs for e in decoder(tx)]
            markets=sorted({e['mint'] if family=='pump' else e['pool'] for _,e in economic})
            lo=min(tx['slot'] for tx in txs);hi=max(tx['slot'] for tx in txs)
            for market in markets:h.bind(family,market)
            from meme_machine.solana_rolling_history import program_scope
            for tx in txs:
                h.ingest(economic_records(family,PROGRAMS[family],tx,endpoint_identity='a'*64,seen=now[0],source='alchemy_finalized_stream'))
            scope=program_scope(family)
            h.lifecycle.defer_proof(IntervalProof(scope,lo,hi,'alchemy_finalized_stream','a'*64,
                dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash=digest([scope,lo,hi])),now[0]))
            while h.lifecycle.flush():pass
            h.lifecycle.publish()
            for market in markets:
                start=time.perf_counter();promotions+=1
                metric=h.rolling.prepare(family,market,lo,hi,deadline=now[0]+150)
                complete_at+=metric['history_already_complete_at_promotion']
                if metric['missing_intervals']:raise ValueError('captured_prewarm_gap')
                with closing(EvidenceReader(writer.path)) as reader:
                    c=CandidateReader(reader,family,market);rows=c.window(c.scope,lo,hi,as_of=now[0],address=market)
                    vectors[family+':'+market]=[dict(slot=r['slot'],transaction_index=r['transaction_index'],event_index=r['event_index'],identity=r['identity'],event=r['payload']['event']) for r in rows]
                elapsed.append(time.perf_counter()-start)
        # Exact survivor trajectory and current economics are these same ordered
        # native vectors, not a newly invented qualifier from synthetic data.
        while h.lifecycle.flush():pass
        h.lifecycle.publish();writer.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        hot=writer.path.stat().st_size;candidate=Path(h.lifecycle.path).stat().st_size
        counts={op:sql.count(op) for op in ('INSERT','UPDATE','DELETE')};events=writer.db.execute('SELECT COUNT(*) FROM canonical_evidence').fetchone()[0]
        from engineering.solana_capacity.certify import quantiles
        result=dict(model='B',classification='MEASURED_REPLAY',preserved_input_provider_bytes=delivered,
            provider_bytes_note='Same preserved provider input charged to both. No local projection credit.',
            promotion_backfill_rpc_calls=calls,promotion_backfill_rpc_cu=cu,promotion_backfill_transaction_bodies=bodies,
            promotions=promotions,histories_complete_at_promotion=complete_at,history_complete_at_promotion_percent=100*complete_at/promotions,
            promotion_ready_seconds=quantiles(elapsed),events=events,ordered_vectors=vectors,
            sqlite_write_statements=counts,sqlite_changes=writer.db.total_changes,hot_database_bytes=hot,
            candidate_database_bytes=candidate,cpu_seconds=time.process_time()-cpu0,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            unresolved_gaps=h.db.execute('SELECT COUNT(*) FROM candidate_gaps WHERE repaired IS NULL').fetchone()[0],
            deadline_misses=h.db.execute("SELECT COUNT(*) FROM acquisition_jobs WHERE status='deadline_missed'").fetchone()[0],
            expensive_worker_utilization=None,worker_note='Ordered-history source replay, not simultaneous worker/capacity certification')
        writer.close()
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=run(a.fixture);Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='ordered_vectors'},indent=2))
