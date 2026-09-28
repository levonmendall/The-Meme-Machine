"""E23 fixed-cohort runner: same workload/limits, versioned observed commit windows."""
from contextlib import ExitStack,contextmanager
from pathlib import Path
from unittest.mock import patch
from certification import cleanup_recovery as recovery
from certification import combined_pressure as legacy
from certification.combined_observer import Interaction,verified,observation_verified

PLAN_PATH=Path(__file__).with_name('maintenance_qualification_plan.json')
original_extended_verified=recovery.extended_verified


def extended_verified(row,frames):
    return original_extended_verified(row,frames) and observation_verified(row)


@contextmanager
def qualification():
    with ExitStack() as stack:
        stack.enter_context(patch.object(recovery,'PLAN_PATH',PLAN_PATH))
        stack.enter_context(patch.object(legacy,'Interaction',Interaction))
        stack.enter_context(patch.object(legacy,'verified',verified))
        stack.enter_context(patch.object(recovery,'extended_verified',extended_verified))
        yield


def main():
    with qualification():
        return recovery.main()


if __name__=='__main__':
    raise SystemExit(main())
