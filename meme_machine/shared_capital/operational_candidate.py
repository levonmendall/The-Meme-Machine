"""Preserved two-family coordinator used by the gated PAPER runtime bridge.

Reuses the published allocator and preserved-epoch migration. RiskPolicy must be
selected explicitly when preparing a plan; feature defaults are not approved
deployment limits. A verified preserved-epoch cutover selects shared funding;
native journals retain their economic identities and accounting.
"""
from .authority import CapitalAuthority
from .migration import plan_migration,validate_plan
from .model import CapitalError,FAMILIES
from meme_machine.runtime.operating_families import ACTIVE_LANES,PAUSED_LANES

ACTIVE_REGIMES=('pump_current','pump_survivor','pons_current','pons_survivor')


def verify_two_family_plan(plan):
    checked=validate_plan(plan)
    policy=checked['policy'];seed=checked['seed']
    if policy['sizing_basis']!='effective_family_equivalence' or policy['adaptive']:
        raise CapitalError('fixed_native_equivalent_sizing_required')
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


class PumpPonsCapital(CapitalAuthority):
    def __init__(self,database,**kwargs):
        super().__init__(database,**kwargs)
        try:
            with self._transaction(write=False):
                state=self._read()
                if state is not None:
                    if state['policy']['sizing_basis']!='effective_family_equivalence' or state['policy']['adaptive']:
                        raise CapitalError('fixed_native_equivalent_sizing_required')
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
