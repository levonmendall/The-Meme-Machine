"""Count existing transaction breadcrumbs on matched synthetic owner work.

Compatible with the preserved44/f0 runtime: no new planner classes are imported.
These are diagnostic invocation counts, not proof of successful SQL, durability,
market capacity or the relative cost of a boundary. Root owns execution.
"""
from contextlib import ExitStack
from functools import wraps
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime import sqlite_failure
from meme_machine.solana_evidence_control import PriorityOwner
from tests import test_owner_throughput_comparison as comparison


VERBS = ('BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE')
OUTPUT_BYTES = 4096


def _is_candidate_callback(fn):
    """Recognize this unchanged harness's timed closure, never runtime state."""
    code = getattr(fn, '__code__', None)
    if (getattr(fn, '__module__', None) != comparison.__name__
            or getattr(fn, '__qualname__', None) !=
            'run_owner_throughput_comparison.<locals>.work.<locals>.timed'
            or code is None or fn.__closure__ is None):
        return False
    for name, cell in zip(code.co_freevars, fn.__closure__):
        if name == 'candidate':
            return cell.cell_contents is True
    return False


async def count_owner_transaction_boundaries(directory):
    counts = dict.fromkeys(VERBS, 0)
    state = dict(active=False, valid=True, callbacks=0, owner_ident=None, native_id=None)
    original_submit = PriorityOwner.submit
    original_breadcrumb = sqlite_failure._breadcrumb

    @wraps(original_breadcrumb)
    def breadcrumb(row):
        # Recording is optional to the runtime: preserve the original call,
        # return and exception even if this separate counter fails. The test
        # subsequently rejects invalid counting instead of mutating behavior.
        try:
            if state['active'] and threading.get_ident() == state['owner_ident']:
                if threading.get_native_id() != state['native_id']:
                    state['valid'] = False
                else:
                    verb = row.get('operation')
                    if verb in counts:
                        counts[verb] += 1
        except BaseException:
            state['valid'] = False
        return original_breadcrumb(row)

    @wraps(original_submit)
    def submit(owner, fn, *args, **options):
        try:
            candidate = _is_candidate_callback(fn)
        except BaseException:
            state['valid'] = False
            candidate = False
        if candidate:
            original = fn

            @wraps(original)
            def counted(*arguments, **keywords):
                previous = state['active']
                try:
                    ident, native = threading.get_ident(), threading.get_native_id()
                    if state['owner_ident'] is None:
                        state['owner_ident'], state['native_id'] = ident, native
                    if (previous or ident != owner.thread.ident
                            or ident != state['owner_ident'] or native != state['native_id']):
                        state['valid'] = False
                    state['active'] = True
                except BaseException:
                    state['valid'] = False
                try:
                    return original(*arguments, **keywords)
                finally:
                    try:
                        state['active'] = previous
                        state['callbacks'] += 1
                    except BaseException:
                        state['valid'] = False

            fn = counted
        # Preserve all admission options and return the original Future. A
        # rejected admission has not run counted(), so earns no callback count.
        return original_submit(owner, fn, *args, **options)

    with ExitStack() as stack:
        stack.enter_context(patch.object(PriorityOwner, 'submit', submit))
        stack.enter_context(patch.object(sqlite_failure, '_breadcrumb', breadcrumb))
        report = await comparison.run_owner_throughput_comparison(directory,
            schedule='idle-epochs', measured=False)
    summary = dict(schema='owner-transaction-boundary-counts-v1',
        scope='EXISTING_BREADCRUMB_COUNTS_SYNTHETIC_MECHANISM_NOT_CAPACITY_OR_SQL_SUCCESS',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        comparison_sha256=hashlib.sha256(Path(comparison.__file__).read_bytes()).hexdigest(),
        runtime=report['runtime'], cohort=report['cohort'],
        scheduling=report['scheduling'], schedule_observations=report['schedule_observations'],
        candidate_owner_callbacks=state['callbacks'], recording_valid=state['valid'],
        active_after_owner_join=state['active'], transaction_verb_counts=counts,
        fingerprints=dict(complete_initial_report=comparison._digest(report['before']),
            complete_final_report=comparison._digest(report['final']),
            initial_functional=report['before']['functional_sha256'],
            final_functional=report['final']['functional_sha256'],
            initial_canonical=report['before']['canonical_order_sha256'],
            final_canonical=report['final']['canonical_order_sha256']),
        provider_calls=report['provider_calls'], financial_authority=report['financial_authority'])
    encoded = json.dumps(summary, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > OUTPUT_BYTES:
        raise AssertionError('transaction count output exceeded fixed byte bound')
    print('OWNER_TRANSACTION_BOUNDARIES '+encoded, flush=True)
    checks = unittest.TestCase()
    comparison.OwnerThroughputComparisonTests.assert_conserved(checks, report)
    checks.assertTrue(state['valid'])
    checks.assertFalse(state['active'])
    checks.assertEqual(state['callbacks'], report['counters']['callbacks'])
    checks.assertGreater(state['callbacks'], 0)
    checks.assertIsNotNone(state['owner_ident'])
    checks.assertIsNotNone(state['native_id'])
    checks.assertEqual(report['schedule_observations']['final_outcome'], 'IDLE')
    checks.assertEqual(set(counts), set(VERBS))
    checks.assertTrue(all(type(value) is int and value >= 0 for value in counts.values()))
    checks.assertGreater(sum(counts.values()), 0)
    checks.assertFalse(report['measured'])
    return report, summary


class OwnerTransactionBoundariesTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_idle_epoch_owner_transaction_boundary_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            await count_owner_transaction_boundaries(Path(temporary)/'boundaries')

