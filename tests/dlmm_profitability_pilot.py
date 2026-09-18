"""First bounded sequential multi-pool DLMM profitability research batch."""
import sys
from tests import dlmm_strategy_high_activity_batched as run
from tests import dlmm_dense_acquisition as dense
from tests import dlmm_boundary_acquisition as boundary

run.TARGET_SUPPORTED_POOLS=3
run.CHUNK_SECONDS=2
run._capture_chunk=boundary.capture_chunk
run.ENDPOINT_DIAGNOSTICS=boundary.ENDPOINT_DIAGNOSTICS

_phase={'calls':0}

def _sequential_profitability_advance(adapter,states,wait_seconds):
    """Observe each pool independently so provider load is not multiplied by pool count."""
    warmup=(_phase['calls'] % 2)==0
    _phase['calls']+=1
    advanced={};tapes={};errors=[]
    for address,state in list(states.items()):
        a,t,e=dense.pressure_advance(
            adapter,{address:state},wait_seconds,
            allow_snapshot_reset=warmup)
        advanced.update(a);tapes.update(t);errors.extend(e)
    return advanced,tapes,errors

run.batched_advance=_sequential_profitability_advance

if __name__=='__main__':
    sys.argv[0]='tests.dlmm_profitability_pilot'
    run.main()
