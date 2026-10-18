"""Exact parent-side sizing data, never a financial authority or frozen fence.

The protected administration caller must hold its existing stopped_snapshot_fence
and supply the actual _financial(frozen=True) full replay result/state. This module
cannot establish that fence or authenticate caller-supplied financial JSON. The
caller also authenticates the exact produced receipt over the fixed private IPC.
No financial book, allocation, epoch, database or provider fallback is created.
"""
from fractions import Fraction
import json
import re
import threading
import time

from meme_machine.exact_money import exact,money
from meme_machine.runtime.journal import canonical,digest
from meme_machine.runtime.usd_valuation import NativeValueReader,USDValue,sol_usd
from meme_machine.shared_capital.authority import _size_equity,capital_view


class ParentSizingUnavailable(ValueError):pass


def require(condition,code):
    if not condition:raise ParentSizingUnavailable(code)


def _hash(value,length):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None


def financial_basis(financial,state):
    """Check the original replay result's binding; do not pretend to replay it.

    The protected caller's actual read-only full replay and continuously held
    original production fence remain mandatory. Recomputing a hash here is an
    integrity check, not source/fence authentication.
    """
    require(type(financial) is dict and type(state) is dict,'parent_sizing_financial_shape')
    require(financial.get('state')=='VERIFIED_FULL_REPLAY'
        and financial.get('full_replay_verified') is True
        and financial.get('financial_obligations_verified') is True
        and financial.get('no_financial_exposure') is True,'parent_sizing_full_flat_replay_required')
    names=('reservations','commitments','obligations','pending_deliveries',
        'pending_backing','runtime_pending','runtime_inbox','positions_open','legacy_native_pending')
    counts=financial.get('obligations')
    require(type(counts) is dict and set(counts)==set(names)
        and all(type(counts[k]) is int and counts[k]==0 for k in names),
        'parent_sizing_obligations_not_flat')
    for name in names[:7]:
        value=state.get(name,{}) if name in ('runtime_pending','runtime_inbox') else state.get(name)
        require(type(value) is (list if name=='pending_deliveries' else dict)
            and not value,'parent_sizing_state_not_flat')
    positions=state.get('positions')
    require(type(positions) is dict and all(p.get('status') in ('SETTLED','CANCELLED')
        for p in positions.values()),'parent_sizing_state_not_flat')
    require(_hash(financial.get('journal_hash'),64) and _hash(financial.get('projection_hash'),64)
        and _hash(financial.get('inception_sha256'),64)
        and financial['projection_hash']==digest(state)
        and financial.get('epoch_id')==state.get('epoch_id')
        and type(state.get('epoch_id')) is str and bool(state['epoch_id'])
        and financial['inception_sha256']==state.get('inception_sha256'),
        'parent_sizing_financial_binding')
    raw,combined,source=(financial.get(k) for k in ('raw_journal_sequence','combined_sequence','source_sequence'))
    require(all(type(n) is int and n>=0 for n in (raw,combined,source))
        and combined==source+raw and source==state.get('migration_source',{}).get('sequence'),
        'parent_sizing_sequence_binding')
    require(type(state.get('policy')) is dict and state['policy'].get('sizing_basis') in
        ('shared_realized_equity','effective_family_equivalence') and type(state.get('contracts')) is dict,
        'parent_sizing_policy')
    view=capital_view(state)
    require(view['conservation'] is True and money(view['deployed_basis'])==0
        and money(view['active_reservations'])==0
        and money(view['pending_authoritative_commitments'])==0
        and money(view['required_funding_obligations'])==0
        and money(financial.get('cash_usd'),nonnegative=True)==money(view['free_cash'])
        and money(financial.get('initial_capital_usd'),nonnegative=True)==money(state['initial_capital']),
        'parent_sizing_capital_binding')
    return dict(view)


class ProducedSizingReceipt:
    """Detached data/provenance only; not AuthenticatedSizingFacts or authority."""
    __slots__=('_encoded','_proof','receipt_hash')
    def __init__(self,value,proof):
        object.__setattr__(self,'_encoded',canonical(value))
        object.__setattr__(self,'_proof',canonical(proof))
        object.__setattr__(self,'receipt_hash',digest(value))

    def __setattr__(self,name,value):raise AttributeError('immutable_produced_sizing_receipt')
    def value(self):return json.loads(self._encoded)
    def proof(self):return json.loads(self._proof)


@exact
def build_sizing_receipt(financial,state,*,scope,source_commit,source_tree,pump_value,pons_value,now):
    """Use production shared sizing formulas and original decoded USD validity."""
    view=financial_basis(financial,state)
    require(type(scope) is str and 0<len(scope)<=256 and _hash(source_commit,40)
        and _hash(source_tree,40) and type(now) is int,'parent_sizing_identity')
    from meme_machine.runtime.directional_sleeve import policies
    values={'pump':pump_value,'pons':pons_value};lanes={}
    for lane,value in values.items():
        asset,decimals,ttl={'pump':('SOL',9,120),'pons':('ETH',18,5)}[lane]
        require(type(value) is USDValue and value.asset==asset and value.decimals==decimals
            and type(value.observed_at) is int and type(value.valid_until) is int
            and 0<value.valid_until-value.observed_at<=ttl
            and _hash(value.evidence_hash,64) and type(value.evidence_id) is str and bool(value.evidence_id),
            'parent_sizing_valuation_identity')
        unit=value.amount(1,now)
        # Same state/formula as SharedNativePortfolio.equity, for either genuine
        # policy. Fraction computes the native integer floor exactly without a
        # Decimal division that depends on ambient precision or rounding.
        equity=_size_equity(state,lane+'_current')
        require(equity>=0,'parent_sizing_negative_equity')
        lanes[lane]=dict(realized_equity=int(Fraction(equity)/Fraction(unit)),
            available=int(Fraction(money(view['free_cash']))/Fraction(unit)),
            # This is proven zero by every original obligation bucket above,
            # never a substitute for unknown or unsettled production exposure.
            reserved=0,policies=policies(lane),native_unit='lamports' if lane=='pump' else 'wei',
            usd_evidence_hash=value.evidence_hash,valuation_observed_at=value.observed_at,
            valuation_valid_until=value.valid_until)
    valid_until=min(value.valid_until for value in values.values())
    require(now<valid_until,'parent_sizing_refresh_required')
    value=dict(schema='isolated-native-sizing-v1',scope=scope,source_commit=source_commit,
        source_tree=source_tree,epoch_reference=state['epoch_id'],
        portfolio_sequence=financial['combined_sequence'],observed_at=now,valid_until=valid_until,lanes=lanes)
    proof=dict(schema='parent-sizing-provenance-v1',epoch_id=state['epoch_id'],
        inception_sha256=state['inception_sha256'],portfolio_sequence=financial['combined_sequence'],
        raw_journal_sequence=financial['raw_journal_sequence'],journal_hash=financial['journal_hash'],
        projection_hash=financial['projection_hash'],policy_sha256=digest(state['policy']),
        contracts_sha256=digest(state['contracts']),sizing_basis=state['policy']['sizing_basis'],
        original_obligations=dict(financial['obligations']),
        financial_authority=False,fence_verified_here=False,authentication_performed_here=False)
    return ProducedSizingReceipt(value,proof)


class ParentSizingProducer:
    """Acquire through supplied original native RPCs with exact parent ports.

    The protected owner constructs these RPCs with existing Budget/Governor/
    Admission and disposable private caches. No URL, credential, new provider
    allowance or implicit RPC constructor is accepted here. It keeps the native
    Pons oracle/route cache and rechecks each original expiry after all waits.
    """
    def __init__(self,pump_rpc,pons_rpc,*,clock=time.time):
        from meme_machine.lanes.pump.solana_read_rpc import ReadOnlyFailoverRPC
        from meme_machine.lanes.pons.provider_topology import PacedRpc
        from .child_transport import require_rpc_port
        require(type(pump_rpc) is ReadOnlyFailoverRPC and type(pons_rpc) is PacedRpc
            and callable(clock),'parent_sizing_native_rpcs')
        pump=require_rpc_port(pump_rpc.parent_port,'solana')
        pons=require_rpc_port(pons_rpc.parent_port,'robinhood')
        require(pump.source.read_class==pons.source.read_class=='native'
            and pump.source.operation in ('pump_current_qualification','pump_discovery')
            and pons.source.operation in ('pons_current_qualification','pons_discovery'),
            'parent_sizing_rpc_roles')
        self.pump_rpc,self.pons_rpc,self.clock=pump_rpc,pons_rpc,clock
        self._pump=None;self._pons=NativeValueReader('pons',rpc=pons_rpc)
        self._lock=threading.Lock()

    def produce(self,financial,state,*,scope,source_commit,source_tree,renew_pons=False):
        # No provider work is purchased for an unbound/non-flat replay result.
        financial_basis(financial,state)
        require(type(renew_pons) is bool,'parent_sizing_renewal_shape')
        require(self._lock.acquire(blocking=False),'parent_sizing_acquisition_in_flight')
        try:
            now=int(self.clock())
            from meme_machine.solana_provider_config import GENESIS
            require(self.pump_rpc.call('getGenesisHash',[],priority=True)==GENESIS,
                'parent_sizing_solana_chain')
            pump=self._pump
            if pump is None or not pump.observed_at<=now<pump.valid_until:
                from meme_machine.lanes.pump.pumpswap_survivor_evidence import SOL_USD_ACCOUNT
                response=self.pump_rpc.call('getMultipleAccounts',[[SOL_USD_ACCOUNT],
                    dict(encoding='base64',commitment='finalized')],priority=True)
                pump=sol_usd(response['value'][0],now=int(self.clock()),
                    slot=response['context']['slot'],evidence_hash=digest(response))
                self._pump=pump
            # Only this producer owns this reader. A publication needs positive
            # remaining lifetime; the ordinary native reader also legitimately
            # serves equality at its expiry. Drop its optional *result* cache
            # when renewal is requested or equality has been reached, so the
            # original route/oracle/canonical acquisition earns new evidence.
            # Never relabel an old value or discard the oracle/route safeguards.
            now=int(self.clock());cached=self._pons.cached
            if renew_pons or (cached is not None and not cached.observed_at<=now<cached.valid_until):
                self._pons.cached=None
            pons=self._pons(now)
            return build_sizing_receipt(financial,state,scope=scope,source_commit=source_commit,
                source_tree=source_tree,pump_value=pump,pons_value=pons,now=int(self.clock()))
        finally:self._lock.release()
