"""Original offline public-pacing workload, now checking its reviewed correction.

Run with the pinned interpreter from the repository root using -m. Actual
PacedRpc/Admission execute against tiny disposable ledgers. HTTP is synthetic;
the repository network guard additionally refuses external connections.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import sqlite3
import time
from unittest.mock import patch
from urllib.error import HTTPError


def scenario(root, *, rejection):
    from meme_machine.lanes.pons import BoundaryError
    from meme_machine.lanes.pons.provider_admission import Admission
    from meme_machine.lanes.pons.provider_topology import PacedRpc, ProviderPacer

    now = [100.0]
    starts = []
    statuses = []
    def sleep(seconds):
        now[0] += seconds
    clock = lambda: now[0]
    endpoint = 'https://rpc.mainnet.chain.robinhood.com'
    with patch('meme_machine.operational.position_continuation.provider_interval', return_value=.1):
        gate = Admission(root / ('rejection.sqlite' if rejection else 'control.sqlite'),
                         endpoint, lane='pons', clock=clock, sleeper=sleep)
    with patch('meme_machine.lanes.pons.provider_admission.configured', return_value=gate):
        rpc = PacedRpc(endpoint, role='pons_discovery_public_observation',
                       requests_per_second=2,
                       pacer=ProviderPacer(2, clock=clock, sleeper=sleep), retries=0)

    def http(request, **kwargs):
        starts.append(clock())
        sleep(.125)  # Explicit synthetic service latency, not a provider measurement.
        if rejection and len(starts) == 1:
            raise HTTPError(endpoint, 429, 'synthetic_fixture', {}, io.BytesIO(b'{}'))
        calls = json.loads(request.data)
        return io.BytesIO(json.dumps([
            dict(jsonrpc='2.0', id=call['id'], result=[]) for call in calls
        ]).encode())

    # Exact existing batch/physical-transport path, without discovery, fallback,
    # canonical evidence writes, subscriptions, or retries.
    calls = [('eth_getLogs', [dict(fromBlock='0x1', toBlock='0xa')])] * 4
    with patch('meme_machine.lanes.pons.provider.urlopen', side_effect=http):
        for _ in range(5):
            try:
                assert rpc._http_batch(calls) == [[], [], [], []]
                statuses.append(200)
            except BoundaryError as error:
                assert rejection and len(starts) == 1 and str(error) == 'provider_http_429'
                statuses.append(429)

    with sqlite3.connect(gate.path) as connection:
        transport_rows = [json.loads(row[0]) for row in
                          connection.execute('SELECT body FROM transports ORDER BY seq')]
        configured_interval = connection.execute('SELECT interval FROM limits').fetchone()[0]
    assert len(transport_rows) == len(starts) == 5
    assert [row['http_status'] for row in transport_rows] == statuses
    assert all(row['physical_requests'] == 1 for row in transport_rows)
    assert all(row['retry_attempt'] == 0 for row in transport_rows)
    gaps = [b-a for a, b in zip(starts, starts[1:])]
    return dict(physical_starts=starts, inter_start_seconds=gaps, statuses=statuses,
                configured_shared_interval_seconds=configured_interval,
                configured_role_interval_seconds=rpc.pacer.minimum_interval_seconds,
                admitted_at=[row['admitted_at'] for row in transport_rows],
                shared_wait_seconds=[row['wait_seconds'] for row in transport_rows],
                role_pacer=rpc.pacer.telemetry(), synthetic_physical_attempts=len(starts),
                minimum_gap_seconds=min(gaps), retries=0,
                synthetic_service_latency_seconds=.125)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from operational.tests import network_guard
    network_guard()
    from meme_machine.operational.artifact_storage import Scratch, tree_bytes
    wall, cpu = time.monotonic(), time.process_time()
    with Scratch() as scratch:
        scratch.check()
        # No production state, credential, provider-cache, or ledger path may be
        # inherited by these fixture constructors.
        with patch.dict(os.environ, {}, clear=True):
            control = scenario(scratch.path, rejection=False)
            cooldown = scenario(scratch.path, rejection=True)
        scratch.check()
        fixture_bytes = tree_bytes(scratch.path)
        assert control['minimum_gap_seconds'] >= .5
        assert cooldown['statuses'] == [429, 200, 200, 200, 200]
        assert cooldown['minimum_gap_seconds'] >= .5
        from meme_machine.lanes.pons import provider_topology, provider_admission
        sources = {str(Path(module.__file__).relative_to(Path.cwd())):
                   hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                   for module in (provider_topology, provider_admission)}
        result = dict(
            status='OFFLINE_DISPATCH_SPACING_CORRECTION_PASS',
            at=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
            question='Does shared dispatch retain the adaptive interval after cooldown?',
            control=control, cooldown=cooldown,
            fixture_bytes=fixture_bytes, wall_seconds=time.monotonic()-wall,
            process_cpu_seconds=time.process_time()-cpu,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            market_provider_requests=0, production_database_writes=0,
            limitations=['Synthetic clock/service latency and synthetic 429.',
                         'Does not establish the original public-provider quota or first-429 cause.',
                         'Does not demonstrate sustainable combined throughput or protection readiness.'])
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
        scratch.success = True
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
