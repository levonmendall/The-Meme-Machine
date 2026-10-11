"""Necessary add checks; unchanged native eligibility remains authoritative."""
from .directional_continuation import BRIDGE_GATES,scale_budget


def scale_necessary_budget(state,*,now,sizing,after_cost_return_bps=None):
    """Optimistic upper bound for this observation; never authority to buy.

    Unknown price is optimistically at the high. The original scale_budget
    expression supplies every threshold. Fresh requalification, executable
    sizing and the final capital fence remain mandatory. No decision is cached.
    """
    from types import SimpleNamespace
    facts={gate:True for gate in BRIDGE_GATES}
    facts.update(fresh_strategy_requalified=True,fresh_execution_requalified=True,
        after_cost_return_bps=state.get('high_water_bps',0) if after_cost_return_bps is None
            else after_cost_return_bps)
    return scale_budget(state,facts,now=now,
        sleeve=SimpleNamespace(sizing_basis=lambda *args:sizing),
        execution_allowance=sizing['target'])
