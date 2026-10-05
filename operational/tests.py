"""FAST / OPERATIONAL deterministic suites. No market providers or real epoch."""
import argparse,ipaddress,socket,unittest,urllib.request

FAST=[
 'tests.test_operational_capacity_repairs','tests.test_runtime_evidence_thread_ownership',
 'tests.test_operational_nine','tests.test_operational_portfolio',
 'tests.test_robinhood_usd_valuation','tests.test_native_valuation_completion',
 'tests.test_opportunity_telemetry','tests.test_pons_ongoing_scale','tests.test_strategic_reference','tests.test_current_survivor_independence',
 'tests.test_portfolio_accounting','tests.test_portfolio_lane_integration',
 'tests.test_provider_retry','tests.test_provider_usage_wal_race','tests.test_runtime_wal_races','tests.test_lifecycle_snapshot_connection','tests.test_pump_restart_connection','tests.test_pons_recovery_connection','tests.test_pons_capital_recovery_snapshot','tests.test_sleeve_reconciliation_snapshot','tests.test_pipeline_retention_boundary','tests.test_optional_capability_shapes','tests.test_prefetch_governor_readonly',
 'tests.lanes.pump.test_pump_acceleration_strategy','tests.lanes.pump.test_pump_acceleration_paper',
 'tests.lanes.pump.test_pumpswap_survivor','tests.lanes.pump.test_paper_accounting',
 'tests.lanes.meteora.test_solana_dlmm_independent_v1',
 'tests.lanes.pons.test_pons_selective_continuation','tests.lanes.pons.test_pons_partial_accounting',
 'tests.lanes.pons.test_pons_postgrad_survivor',
 'tests.lanes.ramses.test_ramses_strategy','tests.lanes.ramses.test_ramses_capital_replay',
]
OPERATIONAL=FAST+[
 'tests.test_operational_supervisor','tests.test_operational_storage',
 'tests.test_operational_dashboard','tests.test_portfolio_snapshot_transport',
 'tests.lanes.pons.test_pons_current_recovery','tests.lanes.pons.test_pons_position_provider_recovery',
 'tests.test_work_admission','tests.test_m1_maintenance_completion',
 'tests.test_housekeeping_integration','tests.test_production_maintenance_arbiter',
 'tests.test_maintenance_batch_fairness','tests.test_maintenance_integrity',
 'tests.test_maintenance_overlap',
 'tests.test_run376_dispatch_pressure', 'tests.test_run381_subscription_progress',
 'tests.test_meteora_host_fee','tests.test_meteora_discovery_scheduler','tests.test_meteora_safe_token2022','tests.test_meteora_missing_fee_context','tests.test_meteora_mint_supply','tests.test_meteora_evidence_recovery_isolated','tests.test_meteora_market_scope_efficiency',
 'tests.test_meteora_tape',
 'tests.test_meteora_bin_array_neutral','tests.test_meteora_pool_neutral',
 'tests.test_run377_persistence', 'tests.test_run380_atomic_frame', 'tests.test_run380_production_pressure',
 'tests.test_dispatch_throughput','tests.test_run372_large_frame_runtime',
 'tests.test_retention_outcomes','tests.test_retention_progress',
 'tests.test_orphan_schema_compatibility','tests.test_survivor_bounded_drain','tests.test_ramses_census_connection',
 'tests.lanes.ramses.test_ramses_dynamic_event_capacity','tests.lanes.ramses.test_ramses_scan_capacity_recovery',
 'tests.test_solana_evidence_plane','tests.test_solana_evidence_broker',
 'tests.test_solana_read_rpc', 'tests.test_solana_retained_raw', 'tests.test_solana_retention_working_set', 'tests.test_run381_repair_pagination',
 'tests.test_solana_checkpoint_owner', 'tests.test_checkpoint_handoff', 'tests.test_run381_archive_canonical', 'tests.test_retention_access_path',
 'tests.test_solana_health_atomicity', 'tests.test_run379_control_pressure', 'tests.test_solana_evidence_transport', 'tests.test_solana_evidence_retention',
 'tests.test_solana_evidence_queries','tests.test_solana_evidence_fences','tests.test_run369_runtime',
 'tests.test_run370_storage','tests.test_provider_partial_batch_retry','tests.test_concentration_reader',
 'tests.test_runtime_resource_contract','tests.test_ramses_source_attribution',
 'tests.test_durable_publication','tests.test_report_publisher_isolation',
 'dashboard.tests.test_dashboard','dashboard.tests.test_server_security',
]

def network_guard():
    original=socket.socket.connect
    def connect(sock,address):
        if sock.family==socket.AF_UNIX:return original(sock,address)
        try:local=ipaddress.ip_address(address[0]).is_loopback
        except (ValueError,TypeError):local=False
        if not local:raise RuntimeError('market I/O forbidden in repository tests')
        return original(sock,address)
    socket.socket.connect=connect
    socket.socket.connect_ex=lambda sock,address:(connect(sock,address) or 0)
    original_urlopen=urllib.request.urlopen
    def urlopen(request,*args,**kwargs):
        from urllib.parse import urlsplit
        url=request.full_url if hasattr(request,'full_url') else request
        if urlsplit(url).hostname not in ('127.0.0.1','::1','localhost'):raise RuntimeError('market HTTP forbidden in repository tests')
        return original_urlopen(request,*args,**kwargs)
    urllib.request.urlopen=urlopen

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('level',choices=('FAST','OPERATIONAL'))
    args=parser.parse_args();network_guard()
    suite=unittest.defaultTestLoader.loadTestsFromNames(FAST if args.level=='FAST' else OPERATIONAL)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
