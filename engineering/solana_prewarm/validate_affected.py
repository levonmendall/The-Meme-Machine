"""Offline affected OPERATIONAL acceptance, with a spawn-safe module entrypoint."""
import json,unittest
from pathlib import Path
from operational.tests import network_guard


def main():
    network_guard()
    modules=json.loads(Path('engineering/solana_capacity/validation.json').read_text())['AFFECTED_OPERATIONAL']['modules']
    modules=list(dict.fromkeys([*modules,'tests.test_solana_rolling_prewarm','tests.test_solana_prewarm_startup','tests.test_solana_mixed_proof_accounting',
        'tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged']))
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
    Path('engineering/solana_prewarm/affected_operational.json').write_text(json.dumps(dict(
        modules=modules,tests=result.testsRun,skipped=len(result.skipped),result='PASS' if result.wasSuccessful() else 'FAIL',
        failure_identities=[t.id() for t,_ in result.failures],error_identities=[t.id() for t,_ in result.errors]),indent=2)+'\n')
    return int(not result.wasSuccessful())


if __name__=='__main__':raise SystemExit(main())
