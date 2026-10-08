"""Offline validation receipts using the existing engineering storage policy."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from .capability_executor import load_storage, write_receipt

FOCUSED = [
    'tests.test_pump_capability_executor', 'tests.test_provider_efficiency',
    'tests.test_solana_selective_evidence', 'tests.test_solana_rolling_prewarm',
    'tests.test_solana_prewarm_startup', 'tests.test_candidate_history',
    'tests.test_current_survivor_independence',
    'tests.lanes.pump.test_pumpswap_survivor_evidence',
    'tests.lanes.pump.test_pump_acceleration_history',
    'tests.lanes.pump.test_pump_durable_strategy_recovery',
    'tests.test_shared_capital_economics', 'tests.test_shared_capital_recovery',
]


def run(label, command, storage, receipts, *, collect=None, deadline=600):
    with storage.Scratch() as scratch:
        env = dict(os.environ, TMPDIR=str(scratch.path), SQLITE_TMPDIR=str(scratch.path),
                   PYTHONDONTWRITEBYTECODE='1')
        for key in tuple(env):
            if key.startswith('MM_') and 'STORAGE' not in key and 'ENGINEERING' not in key:
                env.pop(key)
        started = time.monotonic()
        with (receipts/(label+'.log')).open('w') as log:
            command = ['/usr/bin/time', '-v', '-o', str(receipts/(label+'-resources.txt')), *command]
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            try:
                while process.poll() is None:
                    scratch.check()
                    if time.monotonic()-started > deadline:
                        raise RuntimeError('offline_validation_wall_budget')
                    time.sleep(0.1)
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
                raise
        scratch.success = process.returncode == 0
        text = (receipts/(label+'.log')).read_text()
        match = re.search(r'Ran (\d+) tests', text)
        receipt = dict(label=label, exit_code=process.returncode, wall_seconds=time.monotonic()-started,
                       tests=int(match.group(1)) if match else None,
                       network_guard=True, market_provider_calls=0,
                       scratch_retained=not scratch.success, command=command,
                       scratch_policy='maintenance/engineering-storage-retention-20261008',
                       validation='OFFLINE_ONLY')
        if collect:
            receipt['frozen_comparison'] = collect(scratch.path)
        write_receipt(receipts/(label+'-receipt.json'), receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)
        return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('executor', 'affected', 'FAST', 'frozen-reference'))
    parser.add_argument('--storage-policy-source', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--capture', type=Path)
    args = parser.parse_args()
    args.receipts.mkdir(parents=True, exist_ok=True)
    storage = load_storage(args.storage_policy_source)
    if args.mode == 'FAST':
        return run('FAST', [sys.executable, '-m', 'operational.tests', 'FAST'], storage, args.receipts)
    if args.mode in ('executor', 'affected'):
        names = ['tests.test_pump_capability_executor'] if args.mode == 'executor' else FOCUSED
        code = ('from operational.tests import network_guard; network_guard(); import unittest; '
                'r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames('+repr(names)+')); '
                'raise SystemExit(not r.wasSuccessful())')
        return run(args.mode, [sys.executable, '-c', code], storage, args.receipts)
    if not args.capture:
        parser.error('--capture required for frozen-reference')
    capture = args.capture.resolve()
    with storage.Scratch() as outer:
        output = outer.path/'replay'
        frozen = json.loads(Path('operational/pumpswap-provider-bandwidth/PARITY.json').read_text())
        def collect(_):
            result = json.loads((output/'result.json').read_text())
            expected = frozen['measurements']['full-reference']['output_digests']
            published = {table: result['output_digests'].get(table)==checksum for table,checksum in expected.items()}
            comparison = dict(canonical_count_matches=result['canonical_count']==frozen['canonical_events'],
                              canonical_digest_matches=result['canonical_digest']==frozen['canonical_digest'],
                              canonical_digest=result['canonical_digest'],
                              projections=published, provider_calls=result['provider_calls'])
            for file in ('result.json', 'profile.txt'):
                shutil.copyfile(output/file, args.receipts/('frozen-reference-'+file))
            if not comparison['canonical_count_matches'] or not comparison['canonical_digest_matches'] or not all(published.values()):
                raise RuntimeError('frozen_canonical_output_changed')
            return comparison
        command = [sys.executable, '-m', 'engineering.solana_capacity.offline_replay', '--source', str(Path.cwd()),
                   '--capture', str(capture), '--output', str(output)]
        code = run('frozen-reference', command, storage, args.receipts, collect=collect, deadline=120)
        outer.success = code == 0
        return code


if __name__ == '__main__':
    raise SystemExit(main())
