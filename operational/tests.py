"""FAST / OPERATIONAL deterministic suites. No market providers or real epoch."""
import argparse,ipaddress,socket,unittest,urllib.request

FAST=[
 'tests.test_operational_capacity_repairs',
 'tests.test_operational_nine','tests.test_operational_portfolio',
 'tests.test_robinhood_usd_valuation',
 'tests.test_portfolio_accounting','tests.test_portfolio_lane_integration',
 'tests.test_provider_retry',
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
 'tests.test_dispatch_throughput',
 'tests.test_retention_outcomes','tests.test_retention_progress',
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
