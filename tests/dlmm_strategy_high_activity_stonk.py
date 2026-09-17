"""Single highest-ranked supported-pool rerun with tighter verified chunks.

This wrapper changes only research transport scope: one activity-ranked pool at a
time and two-second independently terminal-verified chunks. Strategy, costs, activity
gate, finalized evidence predicates and `MAX_TRANSACTIONS=16` remain unchanged.
"""
import sys
from tests import dlmm_strategy_high_activity_batched as run

run.TARGET_SUPPORTED_POOLS=1
run.CHUNK_SECONDS=2

if __name__=='__main__':
    sys.argv[0]='tests.dlmm_strategy_high_activity_stonk'
    run.main()
