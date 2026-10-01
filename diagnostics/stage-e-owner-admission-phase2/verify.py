"""Finite Phase 2A verification on the exact repaired M1 base; paper only."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = 'b11b16fbdc4ea0312b2c6f51de37e4d68e1f2da1'

def prerequisite(output):
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location('lane_a_prerequisite',
        Path(__file__).with_name('native_completion_prerequisite.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(
        unittest.defaultTestLoader.loadTestsFromModule(module))
    row = dict(module.EVIDENCE, tested_sha=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True).strip(),
        base=BASE, tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped))
    (output / 'M1_PREREQUISITE.json').write_text(json.dumps(row, indent=2, sort_keys=True)+'\n')
    print('PHASE2_M1 ' + json.dumps(row, sort_keys=True), flush=True)
    return result.wasSuccessful() and not result.skipped

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prerequisite-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    return 0 if prerequisite(args.output) else 1

if __name__ == '__main__':
    raise SystemExit(main())
