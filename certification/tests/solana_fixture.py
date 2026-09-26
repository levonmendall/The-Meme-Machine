def pump_evidence():
    """Complete synthetic local-evidence smoke proof, not mere process liveness."""
    return dict(evidence_liveness=dict(usable_observations=500,failure=None,last=dict(usable=True)),
        stream_state=dict(counters={'stream_accepted_messages':100,'stream_bytes':1000000,
            'pump.complete_local_reads':10,'pump.foreground_historical_rpc_calls':0},
            service_health=dict(provider=dict(provider='alchemy_solana_mainnet',network='solana-mainnet',endpoint_identity='a'*64))),
        funnel=dict(discovered=5))
