"""Single highest-ranked supported-pool replay with bounded verified acquisition.

This wrapper changes only research evidence acquisition: one activity-ranked pool at
a time, pressure-bounded chunk closure, and one boundary-only signature pagination
fallback when the first page cannot prove the starting slot. Strategy, costs, activity
gate, finality predicates and `MAX_TRANSACTIONS=16` remain unchanged.
"""
import sys
from tests import dlmm_strategy_high_activity_batched as run
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_boundary_acquisition as boundary

run.TARGET_SUPPORTED_POOLS=1
run.CHUNK_SECONDS=2
run._capture_chunk=boundary.capture_chunk
run.batched_advance=dense.pressure_advance

if __name__=='__main__':
    sys.argv[0]='tests.dlmm_strategy_high_activity_stonk'
    run.main()
