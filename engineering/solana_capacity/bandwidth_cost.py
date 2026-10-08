"""Explicit 30-day sensitivity model. No inference of steady rates from replay.

Published list prices are distinct from account invoices, diagnostic CU and
throughput admission. Scenario activity and alternative transaction sizes are
assumptions, never measurements or certified market forecasts.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path

D = Decimal
SECONDS_30_DAYS = D(30 * 86400)
WS_CU_PER_BYTE = D('0.0002')
USD_PER_MILLION_CU = D('0.525')
YELLOWSTONE_USD_PER_TB = D(75)
TB_BYTES = D(10**12)  # Published TB is modeled as decimal; contract unit unverified.
RPC_CU = {'getGenesisHash': 10, 'getSlot': 20, 'getMultipleAccounts': 20,
          'getBlockTime': 20, 'getTransaction': 40, 'getTransactionsForAddress': 100}


def cost(ws_bytes, native_bytes, rpc_counts):
    if D(ws_bytes) < 0 or D(native_bytes) < 0 or any(D(n) < 0 for n in rpc_counts.values()):
        raise ValueError('negative_cost_workload')
    rpc_cu = sum((D(n) * RPC_CU[m] for m, n in rpc_counts.items()), D(0))
    ws_cu = D(ws_bytes) * WS_CU_PER_BYTE
    ws_usd = ws_cu * USD_PER_MILLION_CU / D(10**6)
    rpc_usd = rpc_cu * USD_PER_MILLION_CU / D(10**6)
    native_usd = D(native_bytes) * YELLOWSTONE_USD_PER_TB / TB_BYTES
    return dict(ws_bytes=D(ws_bytes), yellowstone_bytes=D(native_bytes),
                total_streaming_bytes=D(ws_bytes)+D(native_bytes),
                ws_cu=ws_cu, rpc_cu=rpc_cu, http_request_elements=sum((D(n) for n in rpc_counts.values()), D(0)),
                rpc_methods=rpc_counts, ws_usd=ws_usd, rpc_usd=rpc_usd,
                yellowstone_usd=native_usd, total_usage_usd=ws_usd+rpc_usd+native_usd)


def scenarios(audit):
    c = audit['components']
    means = {f: {kind: D(c[f+'_'+kind]['bytes']) / D(c[f+'_'+kind]['messages'])
                 for kind in ('successful', 'failed')} for f in ('pump', 'pumpswap')}
    status = c['pump:transaction_status']
    status_mean = {kind: D(status[kind+'_bytes']) / D(status[kind+'_messages']) for kind in ('successful', 'failed')}
    # Independent control and candidate continuity both stay. Account scouts
    # stay universal. Assumptions specify incidence, rather than replay cadence.
    fixed_native_rate = D('2.5') * sum((D(c[k]['bytes']) / D(c[k]['messages']) for k in
                               ('shared:block_meta', 'shared:slot', 'pump:block_meta', 'pump:slot')), D(0))
    scout_mean = D(c['pump:account']['bytes']) / D(c['pump:account']['messages'])
    inputs = [
        ('quiet', '0.2', '0.2', '2', '1', '0.1', '0.01', 0, 0),
        ('normal', '2', '2', '20', '15', '1', '0.1', 0, 0),
        ('busy', '10', '15', '100', '150', '5', '1', 0, 0),
        ('high_volume_stress', '40', '120', '400', '1600', '20', '4', 0, 0),
        ('normal_reconnect_recovery', '2', '2', '20', '15', '1', '0.1', 30, 60),
        ('normal_open_position_maintenance', '2', '2', '20', '15', '1', '0.1', 0, 0),
    ]
    rows = []
    for name, ps, pf, ss, sf, scouts, rpc_rate, reconnects, gap_seconds in inputs:
        rates = {'pump': {'successful': D(ps), 'failed': D(pf)},
                 'pumpswap': {'successful': D(ss), 'failed': D(sf)}}
        ws_rate = sum((rates[f][k] * means[f][k] for f in rates for k in rates[f]), D(0))
        native_rate = fixed_native_rate + D(scouts) * scout_mean + sum(
            (rates[f][k] * status_mean[k] for f in rates for k in rates[f]), D(0))
        # Explicit once-per-month startup prefix; never a steady-state rate.
        prefix_bytes = sum(D(v.get('below_requested_floor_bytes', 0)) for v in c.values())
        startup_native = prefix_bytes * D(1+reconnects)
        rpc_counts = {'getSlot': D(4*(1+reconnects)), 'getGenesisHash': D(3),
                      'getMultipleAccounts': D(rpc_rate)*SECONDS_30_DAYS}
        # Missing old WS content must be fetched against native identities.
        recovered_successes = sum((rates[f]['successful'] for f in rates), D(0)) * D(reconnects * gap_seconds)
        rpc_counts['getTransaction'] = recovered_successes
        restorations = 30 if name == 'normal_reconnect_recovery' else 0
        pages_per_restoration = 216 if restorations else 0
        # Separate exceptional history gaps on reactivation: a six-hour pool
        # history at an assumed 1 transaction/s, 100 transactions/page. Fully
        # retained complete Model B history needs no such provider refetch.
        rpc_counts['getTransactionsForAddress'] = D(restorations * pages_per_restoration)
        recovery_native = native_rate * D(reconnects * gap_seconds)
        position_http = D(0)
        position_ws = D(0)
        position_native = D(0)
        position_rates = {}
        if name == 'normal_open_position_maintenance':
            # One held position, one additional quote/account request per second;
            # retain the existing independent position WS/native subscription.
            # Those duplicate deliveries remain charged in BOTH configurations.
            position_http = SECONDS_30_DAYS
            rpc_counts['getMultipleAccounts'] += position_http
            position_rates = {'successful': D(5), 'failed': D(2)}
            position_ws = sum((position_rates[k]*means['pumpswap'][k] for k in position_rates), D(0))*SECONDS_30_DAYS+D(40)
            position_native = (sum((position_rates[k]*status_mean[k] for k in position_rates), D(0))+
                D('2.5')*sum((D(c[k]['bytes'])/D(c[k]['messages']) for k in ('pump:block_meta', 'pump:slot')), D(0)))*SECONDS_30_DAYS
            rpc_counts['getSlot'] += D(2)
        base_ws = ws_rate*SECONDS_30_DAYS + D(80*(1+reconnects)) + position_ws
        base_native = native_rate*SECONDS_30_DAYS + startup_native + recovery_native + position_native
        baseline = cost(base_ws, base_native, rpc_counts)
        alternatives = []
        for native_mean in (D(3000), D(4200), D(6000)):
            # Unknown full successful native payload, including routing clocks.
            # Preserve all original independent status and continuity bytes.
            pump_only = sum((rates['pump'][k]*means['pump'][k] for k in rates['pump']), D(0))
            alt_ws = pump_only*SECONDS_30_DAYS + D(40*(1+reconnects)) + position_ws
            successful_seconds = SECONDS_30_DAYS + D(reconnects * gap_seconds)
            alt_native = base_native + rates['pumpswap']['successful']*native_mean*successful_seconds
            # Prefix full-body replacement costs are additional and unmeasured.
            # The estimate exposes a distinct assumed 1-second startup body
            # overlap per session, alongside the exact known status prefix.
            alt_native += rates['pumpswap']['successful']*native_mean*D(1+reconnects)
            alt_rpc = dict(rpc_counts)
            # Potential RPC elimination is unverified; retain the baseline RPC
            # recovery counts instead of assuming replay is free/reliable.
            estimate = cost(alt_ws, alt_native, alt_rpc)
            estimate.update(native_success_mean_bytes_assumed=native_mean,
                            modeled_streaming_byte_difference=baseline['total_streaming_bytes']-estimate['total_streaming_bytes'],
                            modeled_usage_usd_difference=baseline['total_usage_usd']-estimate['total_usage_usd'],
                            verified_provider_savings_bytes=0)
            alternatives.append(estimate)
        # A universal status scout followed by one HTTP transaction per
        # PumpSwap success is a lower-streaming alternative, with real RPC load.
        rpc_only = dict(rpc_counts)
        rpc_only['getTransaction'] += rates['pumpswap']['successful']*SECONDS_30_DAYS
        targeted = cost(alternatives[0]['ws_bytes'], base_native, rpc_only)
        rows.append(dict(scenario=name, classification='MODELED_NOT_MARKET_MEASURED',
                         assumptions=dict(events_per_second=rates, scout_updates_per_second=D(scouts),
                             base_account_rpc_per_second=D(rpc_rate), reconnects=reconnects,
                             reconnect_gap_seconds=gap_seconds, additional_position_http=position_http,
                             exceptional_reactivation_history_gaps=restorations,
                             archive_pages_per_reactivation_gap=pages_per_restoration,
                             reactivation_history_seconds_assumed=21600 if restorations else 0,
                             reactivation_pool_transactions_per_second_assumed=1 if restorations else 0,
                             archive_transactions_per_page_assumed=100,
                             additional_position_events_per_second=position_rates,
                             unchanged_independent_position_ws_bytes=position_ws,
                             unchanged_independent_position_native_bytes=position_native,
                             baseline_native_subscribe_rpcs=4 if position_rates else 3,
                             alternative_native_subscribe_rpcs=4 if position_rates else 3,
                             baseline_ws_connections=2 if position_rates else 1,
                             alternative_ws_connections=2 if position_rates else 1,
                             startup_status_prefix_bytes_per_session=prefix_bytes,
                             startup_success_body_overlap_seconds_assumed=1),
                         baseline=baseline, retained_production_configuration=baseline,
                         success_native_sensitivity=alternatives, universal_status_plus_http=targeted,
                         additional_paid_capacity_purchased=False))
    return dict(schema='pump-provider-thirty-day-cost-model-v1', as_of='2026-10-08',
                prices=dict(solana_ws_cu_per_byte=WS_CU_PER_BYTE, usd_per_million_cu=USD_PER_MILLION_CU,
                            yellowstone_usd_per_tb=YELLOWSTONE_USD_PER_TB, tb_bytes_assumed=TB_BYTES,
                            rpc_cu=RPC_CU,
                            sources=['https://www.alchemy.com/docs/reference/compute-unit-costs', 'https://www.alchemy.com/pricing']),
                scenarios=rows, limitations=[
                    'Activity rates are independent scenario assumptions, not capture time extrapolations.',
                    'Captured packet averages are traffic-mix estimates and may change with market conditions.',
                    'Full native transaction sizes, replay bodies and provider overhead are unmeasured.',
                    'No free-tier allowances, credits, taxes or custom account prices are assumed.',
                    'Published general WS 0.04 CU/byte is not the Solana-specific tariff.',
                    'No throughput/connection allowance is inferred; admission must pass on existing account capacity.',
                    'HTTP response bytes for selective acquisition are unmeasured; method CU counts remain separate.',
                    'Exceptional reactivation history RPCs are explicitly modeled, not required for already complete retained histories.',
                    'Capital availability never reduces the modeled discovery/economic universe.',
                    'Independent position subscriptions and their duplicate bytes are retained in both modeled configurations.',
                    'Position traffic rates are assumptions; the capture has no complete funded-position sample.'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    report = scenarios(json.loads(args.audit.read_text()))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True,
                                     default=lambda obj: str(obj) if isinstance(obj, D) else obj)+'\n')
    for row in report['scenarios']:
        print(row['scenario'], 'baseline usage USD', row['baseline']['total_usage_usd'].quantize(D('.01')),
              'native sensitivity', [(str(a['native_success_mean_bytes_assumed']),
               str(a['total_usage_usd'].quantize(D('.01')))) for a in row['success_native_sensitivity']])


if __name__ == '__main__':
    main()
