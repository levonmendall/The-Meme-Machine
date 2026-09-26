"""Exact native completion contract; exit code zero alone grants nothing."""
def pump_flat_completion(row):
    terminal=row.get('pump_discovery_terminal') or {}
    live=row.get('evidence_liveness') or {}
    return (row.get('exit_code')==0 and row.get('process_restarts')==0
            and terminal.get('reason')=='flat_after_discovery'
            and terminal.get('configured_seconds')==600
            and type(terminal.get('deadline')) in (int,float)
            and type(terminal.get('completed_at')) in (int,float)
            and terminal['completed_at']>=terminal['deadline']
            and row.get('continuous_uptime_seconds',0)>=599
            and row.get('open_positions')==0
            and row.get('accounting_reconciled') is True
            and not row.get('infrastructure_failure') and not live.get('failure')
            and live.get('usable_observations',0)>0
            and (live.get('last') or {}).get('usable') is True)


def authoritative_activity(row):
    live=row.get('evidence_liveness') or {}
    stream=row.get('stream_state') or {}
    counts=stream.get('counters') or {};local=stream.get('lane_counters') or counts
    provider=(stream.get('service_health') or {}).get('provider') or {}
    methods=row.get('method_counts') or {}
    return (live.get('usable_observations',0)>0 and not live.get('failure')
            and (live.get('last') or {}).get('usable') is True
            and not row.get('infrastructure_failure')
            and provider.get('provider')=='alchemy_solana_mainnet'
            and provider.get('network')=='solana-mainnet'
            and len(provider.get('endpoint_identity',''))==64
            and counts.get('stream_accepted_messages',0)>0
            and counts.get('stream_bytes',0)>0
            and (row.get('funnel') or {}).get('discovered',0)>0
            and local.get('pump.complete_local_reads',0)>0
            and counts.get('pump.foreground_historical_rpc_calls')==0
            and not any(methods.get(k,0) for k in ('getTransaction','getTransactionsForAddress','getSignaturesForAddress','getBlock')))
