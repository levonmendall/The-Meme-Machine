"""Package bounded measurements without manufacturing production incidence.

Run after the offline replay commands in REPORT.md. No network, operational
store, monetary book, or service is opened. The short activity-first cohort is
reported as a daily-normalized stress sample, never a monthly central tendency.
"""
import argparse
import json
import zlib
from pathlib import Path

from .measure_replay import distribution
from .replay_positive import frames,run as positive_replay

HERE=Path(__file__).resolve().parent


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')


def read(path):
    path=Path(path)
    return path.read_bytes() if path.exists() else zlib.decompress(path.with_name(path.name+'.zlib').read_bytes())


def package(artifacts):
    artifacts=Path(artifacts)
    positive=positive_replay(HERE.parents[1]/'tests/fixtures/solana_positive_meteora')
    write(HERE/'positive_parity.json',positive)
    capacity=json.loads((HERE/'simultaneous_provider.json').read_text())
    recovery=json.loads((HERE/'recovery_measurements.json').read_text())
    positions=json.loads(read(artifacts/'warming-20261007T043221Z/position-result.json'))
    transport=json.loads(read(artifacts/'warming-20261007T044454Z/position-transport.json'))
    write(HERE/'pump_position_measurements.json',positions)
    write(HERE/'position_transport_measurements.json',transport)

    # Real fresh-trigger warmups. The earlier untriggered window and a failed
    # diagnostic clock comparison are not production hydration samples.
    warmups=[]
    for name in ('warming-20261007T041321Z','warming-20261007T041506Z'):
        source=artifacts/name
        if name=='warming-20261007T041506Z' and not source.exists():
            source=HERE.parents[1]/'tests/fixtures/solana_positive_meteora'
        summary=json.loads(read(source/'result.json'))
        rpc=[json.loads(line) for line in read(source/'rpc.ndjson').splitlines()]
        for w in summary['warmups']:
            lo=w.get('rpc_start_index',3);hi=w.get('rpc_end_index',len(rpc))
            rows=rpc[lo:hi]
            warmups.append(dict(source=name,utc=summary['at'],pool=w['pool'],
                qualified=w['qualification']['passes'],window_seconds=w['wall_seconds'],
                rpc_calls=w['rpc_calls'],rpc_cu=w['rpc_cu'],http_provider_bytes=w['rpc_bytes'],
                account_fetches=sum(len(r['params'][0]) for r in rows if r['method']=='getMultipleAccounts'),
                transaction_body_rpc_fetches=sum(r['method']=='getTransaction' for r in rows),
                block_fetches=sum(r['method']=='getBlock' for r in rows),
                hydration_type='account_only_rpc_plus_scoped_native_transactions'))
    hydration=dict(classification='MEASURED_LIVE',sample_count=len(warmups),
        observation_windows=[w['window_seconds'] for w in warmups],samples=warmups,
        distributions={k:distribution([w[k] for w in warmups]) for k in (
            'rpc_calls','rpc_cu','http_provider_bytes','account_fetches',
            'transaction_body_rpc_fetches','block_fetches','window_seconds')},
        limitation='Four fresh-trigger warmups of one compatible real pool; mechanical unit costs, not independent promotion incidence.')

    # Position-equivalent replay uses the exact 12 native observation chunks
    # and exact valuation/exit-confirmation functions, never a position book.
    capture=artifacts/'warming-20261007T041506Z'
    if not capture.exists():capture=HERE.parents[1]/'tests/fixtures/solana_positive_meteora'
    summary=json.loads(read(capture/'result.json'))
    w=next(w for w in summary['warmups'] if w['qualification']['passes'])
    rpc=[json.loads(line) for line in read(capture/'rpc.ndjson').splitlines()]
    chunks=rpc[w['rpc_end_index']-24:w['rpc_end_index']]
    seconds=w['warming_completion']-w['warming_start']
    payload=list(frames(capture/'native.frames'))
    by_kind={}
    for at,raw,u in payload:
        if w['warming_start']<=at<=w['warming_completion']:
            kind=u.WhichOneof('update_oneof');entry=by_kind.setdefault(kind,dict(bytes=0,messages=0))
            entry['bytes']+=len(raw);entry['messages']+=1
    # Alchemy's HTTP JSON newline can be verified against the recorded total
    # for this whole warmup. This subset remains explicitly DERIVED.
    def response_bytes(rows):
        return sum(len(json.dumps(r['response'],separators=(',',':')).encode())+1 for r in rows)
    assert response_bytes(rpc[w['rpc_start_index']:w['rpc_end_index']])==w['rpc_bytes']
    http=response_bytes(chunks);native=sum(v['bytes'] for v in by_kind.values())
    met_position=dict(classification='MEASURED_REPLAY_POSITION_TRAFFIC',
        provider_unit_classification='DERIVED_FROM_MEASURED',window_seconds=seconds,
        sample_count=12,source='tests/fixtures/solana_positive_meteora',
        raw_http_bytes=http,raw_native_bytes=native,raw_by_kind=by_kind,
        rpc_calls=len(chunks),rpc_cu=20*len(chunks),
        account_fetches=sum(len(r['params'][0]) for r in chunks if r['method']=='getMultipleAccounts'),
        transaction_body_rpc_fetches=0,block_fetches=0,
        native_transaction_bodies=by_kind.get('transaction',{}).get('messages',0),
        provider_bytes_per_position_hour=(native+http)*3600/seconds,
        http_bytes_per_position_hour=http*3600/seconds,native_bytes_per_position_hour=native*3600/seconds,
        rpc_cu_per_position_hour=480*3600/seconds,rpc_calls_per_position_hour=24*3600/seconds,
        subscription_messages_per_position_hour=sum(v['messages'] for v in by_kind.values())*3600/seconds,
        selective_fetches_per_position_hour=0,
        authority='Exact evidence/mark/confirmation/exit/settlement-input replay, without reservation, entry, signature or submission.',
        limitation='Isolated provider-equivalent interval; simultaneous governed provider latency remains blocker 4.')
    write(HERE/'meteora_position_measurements.json',met_position)

    scouts={label:dict(raw_bytes=0,messages=0) for label in ('p','m','n','a')}
    scout_frames=list(frames(HERE/'captures/delivery-20261007T023339Z/scout.frames'))
    for at,raw,u in scout_frames:
        if u.WhichOneof('update_oneof')!='account':continue
        # Multiple matching labels are one delivered update, counted once.
        label=next((k for k in ('p','m','n','a') if k in u.filters),None)
        if label:
            scouts[label]['raw_bytes']+=len(raw);scouts[label]['messages']+=1
    window=capacity['window_seconds']['scout']
    for row in scouts.values():
        row.update(window_seconds=window,bytes_per_second=row['raw_bytes']/window,
            bytes_per_day_normalized=row['raw_bytes']*86400/window,classification='MEASURED_REPLAY')

    observed=[];diagnostic_cost=0.
    cu_table=dict(getGenesisHash=10,getSlot=20,getBlockTime=20,getMultipleAccounts=20,
        getTokenLargestAccounts=20,getTransactionsForAddress=100,getProgramAccountsV2=20)
    for folder in sorted(artifacts.glob('warming-*')):
        rpc_path=folder/'rpc.ndjson'
        if not rpc_path.exists():continue
        records=[json.loads(line) for line in rpc_path.read_text().splitlines()]
        cu=sum(cu_table.get(r['method'],40) for r in records)
        raw_native=sum(len(raw) for _,raw,_ in frames(folder/'native.frames')) if (folder/'native.frames').exists() else 0
        diagnostic_cost+=cu*.525/1e6+raw_native*75/1e12
        for result_name in ('result.json','position-transport.json'):
            path=folder/result_name
            if path.exists():
                result=json.loads(path.read_text())
                if result.get('duration_seconds') or result.get('window_seconds'):
                    observed.append(dict(source=folder.name,seconds=result.get('duration_seconds',result.get('window_seconds')),natural_reconnects=0))
                break
    budget=dict(successful_recorded_rpc_and_native_cost_usd=diagnostic_cost,
        additional_diagnostic_cost_conservative_ceiling_usd=.01,
        owner_authorized_limit_usd=10.,
        note='The ceiling includes failed short diagnostic attempts, JSON/WebSocket payloads and framing margin; all were read-only and are stopped.')
    # The public capture bundle includes the independently saved aggregate for
    # unsuccessful diagnostics as well. Do not recount its compressed subset
    # as if that were the full original observation window or billed total.
    if artifacts.resolve()==(HERE/'captures').resolve():
        diagnostic=json.loads(read(artifacts/'diagnostic-summary.json'))
        budget=diagnostic['budget'];observed=diagnostic['natural_observation_windows']
        diagnostic_cost=budget['successful_recorded_rpc_and_native_cost_usd']
    assert diagnostic_cost<budget['additional_diagnostic_cost_conservative_ceiling_usd']
    natural_seconds=sum(r['seconds'] for r in observed)
    recovery.update(natural_reconnects=0,natural_observation_seconds=natural_seconds,
        natural_observation_windows=observed,
        natural_rate_statement=f'0 natural reconnects in {natural_seconds/3600:.6f} bounded observed hours; this does not establish zero production recovery cost.')
    write(HERE/'recovery_measurements.json',recovery)

    # Lossless retirement measurements over authentic pool transactions; open
    # consumers stay pinned. Physical file bytes and hot payload bytes differ.
    from tests.test_solana_closure import ClosureTests
    from meme_machine.solana_scoped_retirement import ScopedRetirement
    test=ClosureTests();test.setUp()
    try:
        address,rows=test.ingest_fixture('meteora');test.life.demote('meteora',address,reason='quiet');test.drain()
        cold=ScopedRetirement(test.h);retirement=cold.retire();test.restart()
        retirement['restart_restored_records']=ScopedRetirement(test.h).restore('meteora',address)
        retirement['candidate_first_seen_preserved']=test.state.writer.db.execute('SELECT first_seen FROM candidate_lifecycle').fetchone()[0]
        retirement['provider_cost_credit_usd']=0
    finally:test.tearDown()
    write(HERE/'retirement_measurements.json',retirement)

    result=dict(promotion=capacity['candidate_rates'],promotion_window_note=
        'Short activity-first/cold-interest cohort. Daily normalizations are stress rates, not measured births/day or sustainable production central tendencies.',
        hydration=hydration,scouting=scouts,positive=positive,
        position=dict(pump=positions['pump'],pumpswap=positions['pumpswap'],meteora=met_position,
            transport=transport,incidence_position_hours_per_day=None,
            limitation='No natural monetary positions were started. No production position occupancy is inferred.'),
        replay=recovery,capacity=capacity,retirement=retirement,diagnostic_budget=budget,
        byte_accounting=dict(raw_provider='Captured protobuf/HTTP/WS payloads before routing/dedup; duplicated shard payloads included.',
            local_materialized=capacity['retirement']['hot_bytes_before'],
            canonical_logical_bytes=capacity['byte_boundaries']['canonical_logical_bytes'],
            canonical_note='Normalized economic lineage remains durable; no local compression/dedup credit is applied to provider billing.',
            local_ipc=0,local_ipc_note='In-process replay used zero IPC bytes; production IPC/day is unmeasured.'))
    write(HERE/'measurements.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',default=HERE/'captures')
    args=parser.parse_args();result=package(args.artifacts)
    print(json.dumps(dict(hydration_samples=result['hydration']['sample_count'],
        meteora_position_bytes_per_hour=result['position']['meteora']['provider_bytes_per_position_hour'],
        diagnostic_cost_ceiling_usd=result['diagnostic_budget']['additional_diagnostic_cost_conservative_ceiling_usd']),indent=2))


if __name__=='__main__':main()
