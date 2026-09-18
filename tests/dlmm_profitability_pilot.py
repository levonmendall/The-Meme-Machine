"""First bounded multi-pool DLMM profitability research batch."""
import sys
from tests import dlmm_strategy_high_activity_batched as run
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_boundary_acquisition as boundary

run.TARGET_SUPPORTED_POOLS=3
run.CHUNK_SECONDS=2
run._capture_chunk=boundary.capture_chunk
run.ENDPOINT_DIAGNOSTICS=boundary.ENDPOINT_DIAGNOSTICS

def _profitability_advance(adapter,states,wait_seconds):
    # Research batches do not bridge external LP mutations. Affected pools fail
    # closed and the surviving point-in-time sample continues.
    return dense.pressure_advance(
        adapter,states,wait_seconds,allow_snapshot_reset=False)

run.batched_advance=_profitability_advance

if __name__=='__main__':
    sys.argv[0]='tests.dlmm_profitability_pilot'
    run.main()
