"""Sample actual owner callbacks to explain CPU work, never measure capacity.

Run only through the repository offline driver. The unchanged comparison helper
provides the population, actual acquisition callbacks, owner and conservation
checks. Profiling may change the candidate's five-ms quantum and turn count.
"""
import cProfile
from functools import wraps
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.solana_evidence_control import PriorityOwner
from tests.test_owner_throughput_comparison import run_owner_throughput_comparison


SAMPLE_EVERY = 5
MAX_SAMPLES = 64
TOP_FUNCTIONS = 30
OUTPUT_BYTES = 32768
SCOPE = 'PROFILE_PERTURBED_SYNTHETIC_MECHANISM_NOT_CAPACITY_RATE'


def _function_name(code):
    if isinstance(code, str):
        return code[:224]
    path = Path(code.co_filename)
    root = Path(__file__).resolve().parent.parent
    try:
        filename = str(path.resolve().relative_to(root))
    except ValueError:
        filename = path.name
    return (filename[:96]+':'+str(code.co_firstlineno)+':'+code.co_name[:120])[:224]


async def profile_owner_throughput(directory):
    """One identical helper workload, with one profiler used by its owner only.

    Callback ordinal1 is sampled, then6,11,... . Admission rejection cannot
    consume a sample: counters advance only when the real callback executes.
    Detached stats are read after the helper has closed/joined its owner.
    """
    original_submit = PriorityOwner.submit
    state = dict(observed=0, sampled=0, profile=None, owner_thread=None,
        sampling_ordinals=[], active=False)

    def submit(owner, function, *args, **options):
        if getattr(function, '__name__', None) != 'timed':
            return original_submit(owner, function, *args, **options)

        @wraps(function)
        def sampled(actual_state):
            current = threading.get_ident()
            if current != owner.thread.ident:
                raise AssertionError('profile callback escaped actual owner thread')
            if state['owner_thread'] is None:
                state['owner_thread'] = current
            if state['owner_thread'] != current:
                raise AssertionError('one profile cannot span owners or threads')
            state['observed'] += 1
            if ((state['observed']-1) % SAMPLE_EVERY
                    or state['sampled'] >= MAX_SAMPLES):
                return function(actual_state)
            if state['active'] or sys.getprofile() is not None:
                raise AssertionError('owner already has an active profiler')
            if state['profile'] is None:
                state['profile'] = cProfile.Profile(timer=time.thread_time)
            state['sampled'] += 1
            state['sampling_ordinals'].append(state['observed'])
            state['active'] = True
            state['profile'].enable()
            try:
                return function(actual_state)
            finally:
                state['profile'].disable()
                state['active'] = False

        # wraps preserves owner_operation and other function metadata. Admission
        # options and the exact returned concurrent Future remain untouched.
        return original_submit(owner, sampled, *args, **options)

    with patch.object(PriorityOwner, 'submit', submit):
        report = await run_owner_throughput_comparison(directory, measured=False)
    if state['active']:
        raise AssertionError('owner profile remained active after shutdown')
    functions = []
    for entry in (() if state['profile'] is None else state['profile'].getstats()):
        functions.append(dict(function=_function_name(entry.code),
            primitive_calls=entry.callcount-entry.reccallcount, calls=entry.callcount,
            cumulative_seconds=entry.totaltime, exclusive_seconds=entry.inlinetime,
            cumulative_seconds_per_profiled_owner_callback=entry.totaltime/state['sampled'],
            exclusive_seconds_per_profiled_owner_callback=entry.inlinetime/state['sampled']))
    cumulative = sorted(functions, key=lambda row: (-row['cumulative_seconds'], row['function']))[:TOP_FUNCTIONS]
    exclusive = sorted(functions, key=lambda row: (-row['exclusive_seconds'], row['function']))[:TOP_FUNCTIONS]
    final = report['final']
    summary = dict(schema='sampled-owner-throughput-profile-v1', scope=SCOPE,
        profile_timer='time.thread_time_owner_cpu_excludes_waits_custom_timer_adds_overhead',
        profile_overhead_can_change_turn_counts=True, sampled_costs_extrapolated=False,
        profile_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        comparison_source_sha256=hashlib.sha256(Path(sys.modules[
            run_owner_throughput_comparison.__module__].__file__).read_bytes()).hexdigest(),
        cohort=report['cohort'], runtime=report['runtime'],
        sampling=dict(first_ordinal=1, every=SAMPLE_EVERY, maximum_samples=MAX_SAMPLES,
            observed_callbacks=state['observed'], profiled_callbacks=state['sampled'],
            ordinals=state['sampling_ordinals'], same_owner_thread=True),
        turns=report['turns'], maximum_turns=report['maximum_turns'],
        benchmark_vm_instrumentation=report['measured'], owner_counters=report['counters'],
        fingerprints=dict(initial_functional=report['before']['functional_sha256'],
            final_functional=final['functional_sha256'],
            initial_canonical=report['before']['canonical_order_sha256'],
            final_canonical=final['canonical_order_sha256']),
        final=dict((key, final[key]) for key in ('complete', 'deadlines_preserved',
            'pending_jobs', 'pending_history', 'inflight', 'preparation_tickets',
            'transaction_open', 'synchronous')),
        provider_calls=report['provider_calls'], financial_authority=report['financial_authority'],
        top_cumulative=cumulative, top_exclusive=exclusive)
    encoded = json.dumps(summary, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > OUTPUT_BYTES:
        raise AssertionError('bounded profile output exceeded declared byte limit')
    print('OWNER_THROUGHPUT_PROFILE '+encoded, flush=True)
    return report, summary


class OwnerThroughputProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_sampled_actual_owner_work_preserves_synthetic_obligations(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, profile = await profile_owner_throughput(Path(temporary)/'profile')
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
        self.assertFalse(profile['benchmark_vm_instrumentation'])
        self.assertEqual(profile['sampling']['observed_callbacks'], report['counters']['callbacks'])
        self.assertGreater(profile['sampling']['profiled_callbacks'], 0)
        self.assertLessEqual(profile['sampling']['profiled_callbacks'], MAX_SAMPLES)
        self.assertEqual(profile['sampling']['ordinals'],
            list(range(1, profile['sampling']['observed_callbacks']+1, SAMPLE_EVERY))[:MAX_SAMPLES])
        self.assertLessEqual(len(profile['top_cumulative']), TOP_FUNCTIONS)
        self.assertLessEqual(len(profile['top_exclusive']), TOP_FUNCTIONS)
        self.assertTrue(profile['top_cumulative'])

