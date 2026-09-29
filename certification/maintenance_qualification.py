"""E24 fixed cohort: unchanged workload, joint lifecycle and durable-window evidence."""
from contextlib import ExitStack,contextmanager
from pathlib import Path
import sys
import hashlib
import json
from unittest.mock import patch
from certification import cleanup_recovery as recovery
from certification import combined_pressure as legacy
from certification.combined_observer import Interaction,verified,observation_verified
from certification.lifecycle_capacity import LifecycleObserver,assessment
from certification.qualification_environment import require as require_environment

PLAN_PATH=Path(__file__).with_name('stagee24_qualification_plan.json')
original_extended_verified=recovery.extended_verified
original_frozen_inputs=recovery.frozen_inputs


def extended_verified(row,frames):
    return (original_extended_verified(row,frames) and observation_verified(row)
            and 0<row.get('oldest_hot_age_peak',float('inf'))<240
            and 0<row.get('oldest_retained_age_peak',float('inf'))<240)


def frozen_inputs():
    plan=json.loads(PLAN_PATH.read_text())
    return original_frozen_inputs() and all(
        hashlib.sha256((recovery.ROOT/name).read_bytes()).hexdigest()==expected
        for name,expected in plan['observation_sources'].items())


@contextmanager
def qualification():
    with ExitStack() as stack:
        stack.enter_context(patch.object(recovery,'PLAN_PATH',PLAN_PATH))
        stack.enter_context(patch.object(recovery,'frozen_inputs',frozen_inputs))
        stack.enter_context(patch.object(recovery,'BacklogObserver',LifecycleObserver))
        stack.enter_context(patch.object(recovery,'recovery_assessment',assessment))
        stack.enter_context(patch.object(legacy,'Interaction',Interaction))
        stack.enter_context(patch.object(legacy,'verified',verified))
        stack.enter_context(patch.object(recovery,'extended_verified',extended_verified))
        yield


def main():
    # Verification of already preserved artifacts is portable. Execution of an
    # authoritative new trial is not allowed on a different Python/dependency set.
    if '--aggregate' not in sys.argv:require_environment()
    with qualification():
        return recovery.main()


if __name__=='__main__':
    raise SystemExit(main())
