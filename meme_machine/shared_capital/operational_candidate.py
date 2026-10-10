"""Preserved two-family coordinator used by the gated PAPER runtime bridge.

Reuses the published allocator and preserved-epoch migration. RiskPolicy must be
selected explicitly when preparing a plan; feature defaults are not approved
deployment limits. A verified preserved-epoch cutover selects shared funding;
native journals retain their economic identities and accounting.
"""
from .authority import CapitalAuthority
from .migration import plan_migration,validate_plan
from .model import CapitalError,FAMILIES
from meme_machine.portfolio_accounting import SCHEMA_SHARED_INCEPTION
from meme_machine.runtime.operating_families import ACTIVE_LANES,PAUSED_LANES

ACTIVE_REGIMES=('pump_current','pump_survivor','pons_current','pons_survivor')


def verify_sizing_policy(seed):
    # The inception binds the economic model. Old epochs keep their original
    # denominator; a new shared epoch cannot accidentally restore that policy.
    expected = ('shared_realized_equity' if seed['inception']['schema'] == SCHEMA_SHARED_INCEPTION
                else 'effective_family_equivalence')
    if seed['policy']['sizing_basis'] != expected or seed['policy']['adaptive']:
        raise CapitalError('fixed_native_equivalent_sizing_required' if expected == 'effective_family_equivalence'
                           else 'shared_inception_sizing_policy_mismatch')


def verify_two_family_plan(plan):
    checked=validate_plan(plan)
    policy=checked['policy'];seed=checked['seed']
    verify_sizing_policy(seed)
    for kind in ('positions','reservations','commitments','obligations'):
        for identity,row in seed[kind].items():
            if FAMILIES[row['regime']] in PAUSED_LANES and (
                    kind!='positions' or row['status']=='OPEN'):
                raise CapitalError('paused_family_migration_obligation:'+kind+':'+identity)
    for pending in seed['pending_deliveries']:
        if pending['lane'] in PAUSED_LANES:
            raise CapitalError('paused_family_migration_delivery:'+pending['native'])
    return checked


def prepare_plan(preserved_database,mapping,*,policy):
    """Reads an isolated coherent backup only; neither installs nor reseeds it."""
    return verify_two_family_plan(plan_migration(preserved_database,mapping,policy))


def initialize_new_epoch(root, receipt, *, portfolio_identities, lane_identities, contracts, policy):
    """Explicit, separate inception preparation; never called by service startup.

    The caller must separately authorize genuine operational initialization.
    Tests supply a new temporary root. Selection uses the existing cutover after
    its original prerequisites; this function neither starts nor funds anything.
    """
    from pathlib import Path
    from contextlib import closing
    from meme_machine.portfolio_accounting import PortfolioAccounting, validate_inception, PLANNED_SHARED_CAPITAL
    from .model import REGIMES, RiskPolicy
    value = validate_inception(receipt)
    if value['schema'] != SCHEMA_SHARED_INCEPTION or value['starting_capital'] != PLANNED_SHARED_CAPITAL:
        raise CapitalError('new_1000_shared_inception_required')
    selected_policy = policy.value() if isinstance(policy, RiskPolicy) else RiskPolicy(**policy).value()
    verify_sizing_policy(dict(inception=value, policy=selected_policy))
    if set(contracts) != set(REGIMES):
        raise CapitalError('all_six_strategy_contracts_required')
    root = Path(root)
    # Exclusive creation refuses an old epoch, a replica, or interrupted state.
    root.mkdir(mode=0o700)
    with closing(PortfolioAccounting(root/'portfolio.sqlite')) as account:
        account.establish_inception(value, portfolio_identities=portfolio_identities, lane_identities=lane_identities)
    mapping = dict(contracts=contracts, position_meta={}, reservation_meta={}, pending={}, cursor_mapping={}, obligations={},
                   retired={r:dict(pnl='0',costs='0',count=0) for r in REGIMES})
    return prepare_plan(root/'portfolio.sqlite', mapping, policy=selected_policy)


class PumpPonsCapital(CapitalAuthority):
    def __init__(self,database,**kwargs):
        super().__init__(database,**kwargs)
        try:
            with self._transaction(write=False):
                state=self._read()
                if state is not None:
                    verify_sizing_policy(state)
                    for kind in ('positions','reservations','commitments','obligations'):
                        for identity,row in state[kind].items():
                            if FAMILIES[row['regime']] in PAUSED_LANES and (kind!='positions' or row['status']=='OPEN'):
                                raise CapitalError('paused_family_existing_obligation:'+kind+':'+identity)
                    for pending in state['pending_deliveries']:
                        if pending['lane'] in PAUSED_LANES:
                            raise CapitalError('paused_family_existing_delivery:'+pending['native'])
        except BaseException:
            self.close();raise

    def install_migration(self,plan,*,operation_id='install-preserved-epoch'):
        return super().install_migration(verify_two_family_plan(plan),operation_id=operation_id)

    def _write(self,operation_id,action,at,data):
        regime=data.get('regime')
        if action in ('observe','submit','obligation') and regime and FAMILIES[regime] not in ACTIVE_LANES:
            raise CapitalError('paused_family_capital_admission:'+regime)
        if action=='seal' and regime in PAUSED_LANES and data['request_ids']:
            raise CapitalError('paused_family_manifest_must_be_empty:'+regime)
        return super()._write(operation_id,action,at,data)

    def open_round(self,*,operation_id,round_id,at,cutoff):
        result=super().open_round(operation_id=operation_id,round_id=round_id,at=at,cutoff=cutoff)
        # Definitive empty manifests survive restart. Active manifests remain
        # mandatory; a coordinator cannot infer them from silence or a timeout.
        for regime in PAUSED_LANES:
            self.seal(operation_id='paused:'+round_id+':'+regime,round_id=round_id,
                regime_name=regime,request_ids=[],at=at)
        return result
