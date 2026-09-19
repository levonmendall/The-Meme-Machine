"""Deterministic connected certification for the high-throughput Pump paper machinery.

No network, signing, or submission authority. Synthetic inputs are used only to force
production discovery/qualification/storage/PumpSwap machinery through hard boundaries.
"""
import json
import tempfile
from pathlib import Path

from meme_machine import pump
from meme_machine.engine import Engine
from meme_machine.market_native_runtime import MarketNativeRuntime
from meme_machine.pumpswap_runtime import PumpSwapPaperRuntime
from meme_machine.solana_read_rpc import SolanaReadPacer
from meme_machine.store import Store
from meme_machine.stream import PumpTape
from tests.support import event, snapshot
from tests.test_postgrad import (
    CREATOR as POST_CREATOR,
    MINT as POST_MINT,
    complete_pump_snapshot,
    pumpswap_snapshot,
)


MINT_A=pump.b58(bytes([81])*32)
MINT_B=pump.b58(bytes([82])*32)
STALE_MINT=pump.b58(bytes([83])*32)
CREATOR_A=pump.b58(bytes([91])*32)
CREATOR_B=pump.b58(bytes([92])*32)


class Clock:
    def __init__(self,value=100):
        self.value=int(value)
    def __call__(self):
        return self.value
    def set(self,value):
        self.value=int(value)
        return self.value


class CertificationRPC:
    """Synthetic read transport with the same bounded session telemetry surface."""
    def __init__(self,pacer,initial_calls=37):
        self.limit=240
        self.calls=int(initial_calls)
        self.http_requests=int(initial_calls)
        self.failures=0
        self.cache_hits=0
        self.retries=0
        self.failure_kinds={}
        self.failover_count=0
        self.read_pacer=pacer
    def record(self,count=1):
        self.calls+=int(count)
        self.http_requests+=int(count)
    def provider_telemetry(self):
        return dict(
            topology='certification_authenticated_primary',
            primary_provider='onfinality_solana_mainnet',
            secondary_provider='alchemy_solana_mainnet_existing_secret',
            secondary_configured=True,
            logical_calls=self.calls,
            physical_http_requests=self.http_requests,
            failover_count=0,
            pacing=self.read_pacer.telemetry(),
        )


class CertificationAdapter:
    def __init__(self,clock,creators,pacer,initial_calls=37):
        self.clock=clock
        self.creators=creators
        self.rpc=CertificationRPC(pacer,initial_calls=initial_calls)
        self.scan_calls=0
    def snapshot(self,mint,now,priority=False):
        self.rpc.record()
        return snapshot(
            now=int(now),mint=mint,creator=self.creators[mint],slot=int(now))
    def concentration(self,mint,snap,priority=False):
        self.rpc.record()
        self.scan_calls+=1
        return 1000
    def concentration_status(self):
        return dict(
            initialized=True,
            program_scan_logical_requests=self.scan_calls,
            provider_spend_usd=0,
        )


class CertificationPostgradAdapter:
    def __init__(self,clock):
        self.clock=clock
        self.graduation_calls=0
        self.pumpswap_calls=0
    def graduation_snapshot(self,mint,now,priority=True):
        self.graduation_calls+=1
        if mint!=POST_MINT:
            raise ValueError('unexpected_certification_mint')
        return complete_pump_snapshot(
            now=int(self.clock()),mint=mint,creator=POST_CREATOR,retired=True)
    def pumpswap_snapshot(self,handoff,now,priority=True):
        self.pumpswap_calls+=1
        if handoff.mint!=POST_MINT:
            raise ValueError('unexpected_certification_handoff')
        # Match the Pump curve's approximate entry price so the synthetic clock,
        # not a fabricated price move, is what exercises the 900-second timeout.
        return pumpswap_snapshot(
            kind='synthetic',now=int(self.clock()),slot=int(self.clock()),
            quote=50_000_000_000,base=1_000_000_000_000_000)


def _inject_window(tape,mint,now,wallet_seed):
    """Inject four finalized-like buys: one anchor + three independent buyers."""
    rows=[]
    for offset in range(4):
        wallet=pump.b58(bytes([wallet_seed+offset])*32)
        row=event(
            now=int(now),wallet=wallet,mint=mint,
            id=f'cert:{mint}:{int(now)}:{offset}',buy=True)
        rows.append(row)
    with tape._lock:
        for row in rows:
            tape.sequence+=1
            tape._events.append((tape.sequence,dict(row)))
            tape.trade_events+=1
        tape._prune_locked(int(now))
    return rows


def _order_for_mint(store,mint):
    rows=[(oid,row) for oid,row in store.state['orders'].items()
          if row.get('mint')==mint]
    if len(rows)!=1:
        raise AssertionError(f'expected_one_order_for_mint:{mint}:{len(rows)}')
    return rows[0]


def run_certification(report_path=None):
    clock=Clock(100)
    pacer=SolanaReadPacer(minimum_interval=0.5)
    creators={MINT_A:CREATOR_A,MINT_B:CREATOR_B,POST_MINT:POST_CREATOR}
    adapters=[]

    def new_adapter():
        row=CertificationAdapter(clock,creators,pacer,initial_calls=37)
        adapters.append(row)
        return row

    with tempfile.TemporaryDirectory() as td:
        store=Store(str(Path(td)/'certification.db'),'synthetic',100_000_000,
                    'high-throughput deterministic certification')
        engine=Engine(store,[])
        tape=PumpTape(clock=clock)
        adapter=new_adapter()
        runtime=MarketNativeRuntime(
            engine,adapter,session_seconds=12,
            clock=clock,provider_rotation_threshold=40,
            evidence_queue_limit=100)

        def rotate_if_due():
            if runtime.provider_rotation_due():
                runtime.replace_adapter(new_adapter())
                return True
            return False

        # Warm initial finalized window and establish market-native cursor.
        tape.begin(40)
        cursor=runtime.tick(tape,clock(),None)
        if not tape.covered(clock()) or cursor is None:
            raise AssertionError('initial_coverage_not_ready')

        # Candidate A qualifies through real discovery -> full evidence -> Engine.consider.
        clock.set(101);_inject_window(tape,MINT_A,clock(),101)
        cursor=runtime.tick(tape,clock(),cursor)
        clock.set(105);cursor=runtime.tick(tape,clock(),cursor)
        if runtime.qualified!=1:
            raise AssertionError(f'candidate_a_not_qualified:{runtime.status()}')
        if not rotate_if_due():
            raise AssertionError('first_provider_rotation_not_triggered')
        oid_a,_=_order_for_mint(store,MINT_A)
        clock.set(107)
        if engine.fill(oid_a,snapshot(clock(),mint=MINT_A,creator=CREATOR_A,slot=clock()),clock())!='settled':
            raise AssertionError('candidate_a_fill_failed')

        # A continuity loss must stop new discovery but never disable existing-position monitoring.
        clock.set(110);tape.gap(clock())
        cursor=runtime.tick(tape,clock(),cursor)
        if cursor is not None:
            raise AssertionError('gap_did_not_reset_cursor')
        clock.set(115)
        if engine.monitor(MINT_A,snapshot(clock(),mint=MINT_A,creator=CREATOR_A,slot=clock()),clock())!='holding':
            raise AssertionError('existing_position_not_monitorable_during_gap')

        # Reconnect immediately, but fail closed until a complete new 60-second window exists.
        clock.set(111);tape.begin(clock(),preserve_loss=True)
        clock.set(120);_inject_window(tape,STALE_MINT,clock(),131)
        cursor=runtime.tick(tape,clock(),cursor)
        if cursor is not None or tape.covered(clock()):
            raise AssertionError('rewarm_admitted_early_evidence')
        clock.set(170)
        cursor=runtime.tick(tape,clock(),cursor)
        if cursor is not None or tape.covered(clock()):
            raise AssertionError('rewarm_completed_before_full_60_seconds')
        clock.set(171)
        cursor=runtime.tick(tape,clock(),cursor)
        if cursor is None or not tape.covered(clock()):
            raise AssertionError('rewarm_did_not_restore_coverage')
        if STALE_MINT in runtime.discovered:
            raise AssertionError('prewarm_candidate_leaked_into_discovery')

        # Candidate B is processed immediately by the adaptive deadline queue.
        clock.set(172);_inject_window(tape,MINT_B,clock(),141)
        cursor=runtime.tick(tape,clock(),cursor)
        if runtime.qualified!=2:
            raise AssertionError(f'candidate_b_not_qualified:{runtime.status()}')
        if not rotate_if_due():
            raise AssertionError('second_provider_rotation_not_triggered')
        oid_b,_=_order_for_mint(store,MINT_B)
        clock.set(174)
        if engine.fill(oid_b,snapshot(clock(),mint=MINT_B,creator=CREATOR_B,slot=clock()),clock())!='settled':
            raise AssertionError('candidate_b_fill_failed')

        # Candidate C is independently processed on the next scheduler turn.
        clock.set(176);_inject_window(tape,POST_MINT,clock(),151)
        cursor=runtime.tick(tape,clock(),cursor)
        if runtime.qualified!=3:
            raise AssertionError(f'candidate_c_not_qualified:{runtime.status()}')
        if not rotate_if_due():
            raise AssertionError('third_provider_rotation_not_triggered')
        oid_c,_=_order_for_mint(store,POST_MINT)
        clock.set(182)
        if engine.fill(oid_c,snapshot(clock(),mint=POST_MINT,creator=POST_CREATOR,slot=clock()),clock())!='settled':
            raise AssertionError('candidate_c_fill_failed')

        # Two distinct Pump exits.
        clock.set(190)
        if engine.monitor(MINT_A,snapshot(clock(),sol=65_000_000_000,mint=MINT_A,
                                          creator=CREATOR_A,slot=clock()),clock())!='exit_intended':
            raise AssertionError('candidate_a_exit_not_intended')
        if engine.monitor(MINT_B,snapshot(clock(),sol=40_000_000_000,mint=MINT_B,
                                          creator=CREATOR_B,slot=clock()),clock())!='exit_intended':
            raise AssertionError('candidate_b_exit_not_intended')
        clock.set(195)
        if engine.monitor(MINT_A,snapshot(clock(),sol=65_000_000_000,mint=MINT_A,
                                          creator=CREATOR_A,slot=clock()),clock())!='settled':
            raise AssertionError('candidate_a_not_settled')
        if engine.monitor(MINT_B,snapshot(clock(),sol=40_000_000_000,mint=MINT_B,
                                          creator=CREATOR_B,slot=clock()),clock())!='settled':
            raise AssertionError('candidate_b_not_settled')

        # Third position continues through the real PumpSwap continuation machinery,
        # then uses the unchanged 900-second timeout boundary.
        postgrad_adapter=CertificationPostgradAdapter(clock)
        postgrad=PumpSwapPaperRuntime(store,postgrad_adapter,clock=clock)
        clock.set(1083)  # C opened at 182 -> 901 seconds.
        first=postgrad.monitor_existing_position(POST_MINT)
        if first!='exit_intended':
            raise AssertionError(f'pumpswap_exit_not_intended:{first}')
        if store.state['positions'][POST_MINT].get('surface')!='pumpswap':
            raise AssertionError('pumpswap_transition_missing')
        if store.state['positions'][POST_MINT].get('exit_reason')!='timeout':
            raise AssertionError(
                f"expected_timeout_exit:{store.state['positions'][POST_MINT].get('exit_reason')}")
        clock.set(1088)
        if postgrad.monitor_existing_position(POST_MINT)!='settled':
            raise AssertionError('pumpswap_position_not_settled')

        runtime_status=runtime.status()
        if runtime_status['provider_rotations']!=3:
            raise AssertionError(f"provider_rotations:{runtime_status['provider_rotations']}")
        if len(runtime_status['prior_provider_sessions'])!=3:
            raise AssertionError('provider_session_lineage_incomplete')
        if any(s['requests']<40 for s in runtime_status['prior_provider_sessions']):
            raise AssertionError('rotation_happened_before_threshold')
        if any((s.get('provider_topology') or {}).get('failover_count')
               for s in runtime_status['prior_provider_sessions']):
            raise AssertionError('unexpected_rescue_during_certification')
        if pacer.minimum_interval!=0.5 or any(a.rpc.read_pacer is not pacer for a in adapters):
            raise AssertionError('shared_two_rps_pacer_not_preserved')

        reconciled=bool(store.reconcile())
        archive_verified=bool(store.verify_archive())
        settled=[row for row in store.state['orders'].values()
                 if row.get('status')=='settled' and row.get('exit')]
        pumpswap_settled=[row for row in settled
                          if (row.get('exit') or {}).get('surface')=='pumpswap']
        if len(settled)!=3 or len(pumpswap_settled)!=1:
            raise AssertionError('terminal_settlement_accounting_mismatch')
        if store.state['positions'] or store.state['reserved']!=0 or store.state['rent']!=0:
            raise AssertionError('terminal_exposure_not_zero')
        if store.state['funnel']['settled_exits']!=3:
            raise AssertionError('settled_exit_funnel_mismatch')

        report=dict(
            kind='high_throughput_end_to_end_certification',
            success=True,
            synthetic_inputs=True,
            live_money=False,
            signing_authority=False,
            submission_authority=False,
            qualification_policy='continuation-v1',
            economic_timing=dict(evidence_window_seconds=60,exit_timeout_seconds=900),
            stream=dict(
                gaps=tape.status(clock())['gaps'],
                rewarm_proven=True,
                prewarm_candidate_rejected=STALE_MINT not in runtime.discovered,
            ),
            evidence=dict(
                discovered=runtime_status['discovered'],
                preflight_selected=runtime_status['preflight_selected'],
                full_evidence_attempted=runtime_status['full_evidence_attempted'],
                qualified=runtime_status['qualified'],
            ),
            provider=dict(
                rotations=runtime_status['provider_rotations'],
                prior_sessions=len(runtime_status['prior_provider_sessions']),
                shared_pacer=True,
                minimum_interval_seconds=pacer.minimum_interval,
                failovers=0,
            ),
            lifecycle=dict(
                entries=store.state['entry_count'],
                settled_exits=store.state['funnel']['settled_exits'],
                pump_settlements=2,
                pumpswap_settlements=1,
                pumpswap_graduation_reads=postgrad_adapter.graduation_calls,
                pumpswap_quote_reads=postgrad_adapter.pumpswap_calls,
                terminal_positions=len(store.state['positions']),
                terminal_reserved_lamports=store.state['reserved'],
                terminal_rent_lamports=store.state['rent'],
            ),
            accounting=dict(
                reconciled=reconciled,
                archive_verified=archive_verified,
                cash_lamports=store.state['cash'],
                realized_lamports=store.state['realized'],
                fees_lamports=store.state['fees'],
            ),
        )
        if report_path:
            Path(report_path).write_text(json.dumps(report,sort_keys=True,indent=2))
        store.close()
        return report


def main():
    path='high-throughput-e2e-certification.json'
    report=run_certification(path)
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
