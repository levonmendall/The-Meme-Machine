"""Existing owner phase counters on synthetic work, never a capacity rate.

The prior custom-timer cProfile evidence was invalid on this runtime. This
replacement installs no profiler or new phase timers. It captures the actual
source and reads its existing six direct-clock rows after the owner joins.
"""
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.solana_candidate_phases import DEVELOPMENT_PHASES
from meme_machine.solana_selective_source import SelectiveSource
from tests.test_owner_throughput_comparison import run_owner_throughput_comparison


OUTPUT_BYTES = 16384
CPU_ROUNDING_ALLOWANCE_SECONDS = .0001
SCOPE = 'EXISTING_OWNER_PHASE_COUNTERS_SYNTHETIC_MECHANISM_NOT_CAPACITY_RATE'
FIELDS = ('calls', 'failed_calls', 'unmeasured_calls', 'runnable_measured_calls',
    'runnable_unavailable_calls', 'wall_seconds_total_microseconds',
    'wall_seconds_peak_microseconds', 'cpu_seconds_total_microseconds',
    'cpu_seconds_peak_microseconds', 'runnable_wait_seconds_total_microseconds',
    'runnable_wait_seconds_peak_microseconds')


async def phase_owner_throughput(directory):
    """Capture one actual source; retain original constructor return/behavior.

    No admission wrapper, profiler, clock replacement, SQL probe or runtime
    guard modification is introduced here. measured=False disables the helper's
    optional SQL/VM probes; the runtime's original phase telemetry stays active.
    """
    original_init = SelectiveSource.__init__
    created = []

    @wraps(original_init)
    def capture(source, *args, **options):
        original_init(source, *args, **options)
        created.append(source)

    with patch.object(SelectiveSource, '__init__', capture):
        report = await run_owner_throughput_comparison(directory, measured=False)
    if len(created) != 1:
        raise AssertionError('phase capture requires exactly one actual source')
    rows = {}
    for phase in DEVELOPMENT_PHASES:
        original = created[0].pipeline_metrics.get('development_phase:'+phase)
        if not isinstance(original, dict) or any(name not in original for name in FIELDS):
            raise AssertionError('original phase counter unavailable: '+phase)
        row = {name: original[name] for name in FIELDS}
        if any(type(value) is not int or value < 0 for value in row.values()):
            raise AssertionError('original phase counter invalid: '+phase)
        rows[phase] = row
    callback_cpu = report['counters']['callback_thread_cpu_seconds']
    if type(callback_cpu) not in (int, float) or not math.isfinite(callback_cpu) or callback_cpu < 0:
        raise AssertionError('actual callback CPU counter invalid')
    phase_cpu = sum(row['cpu_seconds_total_microseconds'] for row in rows.values())/1_000_000
    valid = phase_cpu <= callback_cpu+CPU_ROUNDING_ALLOWANCE_SECONDS
    final = report['final']
    summary = dict(schema='existing-owner-development-phases-v1', scope=SCOPE,
        instrumentation='existing_CandidatePhases_direct_monotonic_and_thread_time_counters',
        profiler_enabled=False, new_phase_timers_installed=False,
        phase_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        comparison_source_sha256=hashlib.sha256(Path(sys.modules[
            run_owner_throughput_comparison.__module__].__file__).read_bytes()).hexdigest(),
        cohort=report['cohort'], runtime=report['runtime'],
        turns=report['turns'], maximum_turns=report['maximum_turns'],
        benchmark_vm_instrumentation=report['measured'], owner_counters=report['counters'],
        development_phases=rows, phase_cpu_seconds_sum=phase_cpu,
        phase_wall_seconds_sum=sum(row['wall_seconds_total_microseconds'] for row in rows.values())/1_000_000,
        phase_calls_sum=sum(row['calls'] for row in rows.values()),
        cpu_rounding_allowance_seconds=CPU_ROUNDING_ALLOWANCE_SECONDS,
        phase_cpu_within_callback_cpu=valid,
        fingerprints=dict(initial_functional=report['before']['functional_sha256'],
            final_functional=final['functional_sha256'],
            initial_canonical=report['before']['canonical_order_sha256'],
            final_canonical=final['canonical_order_sha256']),
        final=dict((key, final[key]) for key in ('complete', 'deadlines_preserved',
            'pending_jobs', 'pending_history', 'inflight', 'preparation_tickets',
            'transaction_open', 'synchronous')),
        provider_calls=report['provider_calls'], financial_authority=report['financial_authority'],
        limitations=['Existing telemetry has its existing recording overhead; no profiler hook is installed.',
            'Phase totals are reported separately from whole owner callback costs, not a whole-machine rate.',
            'Synthetic fresh population is not authenticated live upgrade or market-speed acceptance.'])
    encoded = json.dumps(summary, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > OUTPUT_BYTES:
        raise AssertionError('bounded phase output exceeded declared byte limit')
    print('OWNER_THROUGHPUT_PHASES '+encoded, flush=True)
    if not valid:
        raise AssertionError('phase CPU exceeds measured actual callback CPU; attribution invalid')
    return report, summary


class OwnerThroughputProfileTests(unittest.IsolatedAsyncioTestCase):
    # Preserve the registered case name; its evidence is now phase-counter-only.
    async def test_sampled_actual_owner_work_preserves_synthetic_obligations(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, phases = await phase_owner_throughput(Path(temporary)/'phases')
        final = report['final']
        self.assertTrue(final['complete'])
        self.assertTrue(final['deadlines_preserved'])
        self.assertFalse(final['transaction_open'])
        self.assertEqual((final['inflight'], final['preparation_tickets']), (0, 0))
        self.assertEqual(final['synchronous'], 2)
        self.assertEqual(final['canonical_order'], report['before']['canonical_order'])
        for table in ('canonical_evidence', 'rolling_economic_events',
                'candidate_content_receipts', 'rolling_event_lineage', 'native_order_attestations'):
            self.assertGreater(report['before']['tables'][table]['rows'], 0, table)
            self.assertEqual(final['tables'][table], report['before']['tables'][table], table)
        self.assertGreater(final['pending_jobs']+final['pending_history'], 0)
        self.assertEqual(report['provider_calls'], 0)
        self.assertFalse(report['financial_authority'])
        self.assertFalse(phases['profiler_enabled'])
        self.assertFalse(phases['new_phase_timers_installed'])
        self.assertFalse(phases['benchmark_vm_instrumentation'])
        self.assertTrue(phases['phase_cpu_within_callback_cpu'])
        self.assertEqual(set(phases['development_phases']), set(DEVELOPMENT_PHASES))
        for name, row in phases['development_phases'].items():
            self.assertGreater(row['calls'], 0, name)
            self.assertEqual(row['unmeasured_calls'], 0, name)
            self.assertEqual(row['failed_calls'], 0, name)
