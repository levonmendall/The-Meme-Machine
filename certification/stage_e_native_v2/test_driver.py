"""Execute only exact classified test IDs; no broad discovery or workloads."""
import argparse
import io
from pathlib import Path
import unittest
from .contract import HERE,canonical,read
from .firewall import classified_tests


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    suite=unittest.defaultTestLoader.discover(str(HERE/'tests'),pattern='test_*.py',top_level_dir=str(HERE.parents[1]))
    classes=read(HERE/'test-classifications-v2.json')['tests']
    classified=classified_tests(suite,classes)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    (output/'classification-before-execution.json').write_bytes(canonical(classified))
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (output/'tests.log').write_text(log.getvalue())
    row=dict(classification='STATIC + DETERMINISTIC_BOUNDED',tests_run=result.testsRun,
        failures=[dict(test=x.id(),traceback=s) for x,s in result.failures],
        errors=[dict(test=x.id(),traceback=s) for x,s in result.errors],
        skipped=[dict(test=x.id(),reason=s) for x,s in result.skipped],
        passed=result.wasSuccessful() and not result.skipped,material_executions=0,
        observer_measurements=0,qualification_authority=False,canonical_authority=False)
    (output/'test-results.json').write_bytes(canonical(row))
    print(log.getvalue());return 0 if row['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
