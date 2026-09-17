"""Single highest-ranked supported-pool replay with pressure-bounded verified chunks.

This wrapper changes only research evidence acquisition: one activity-ranked pool at
a time, two-second maximum chunk age, and early chunk closure when finalized pool
transaction pressure approaches the unchanged hard bound. Strategy, costs, activity
gate, finality predicates and `MAX_TRANSACTIONS=16` remain unchanged.
"""
import sys
from tests import dlmm_strategy_high_activity_batched as run
from tests import dlmm_dense_acquisition as dense

run.TARGET_SUPPORTED_POOLS=1
run.CHUNK_SECONDS=2
run.batched_advance=dense.pressure_advance

if __name__=='__main__':
    sys.argv[0]='tests.dlmm_strategy_high_activity_stonk'
    run.main()
