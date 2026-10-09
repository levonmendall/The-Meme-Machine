"""Bounded PAPER-only shadow evaluation of Pons event-driven held positions.

No execution, mutation, quote suppression, holding-policy override, funding,
subscriptions or second provider is created. The original Current/Survivor
monitors obtain fresh native quotes and make ALL exit decisions first. Only a
successful ordinary HOLD can request optional comparison evidence.

No call by this module can authorize the dormant event-first execution path.
The shadow uses the existing canonical owned RPC and shared governor.
"""
import os
from collections import Counter
from dataclasses import dataclass
from time import monotonic

from . import BoundaryError
from .held_event_coverage import NativeHeldCoverage


SHADOW_ENV='MM_PONS_HELD_PAPER_SHADOW'
MAX_SAMPLE_ENV='MM_PONS_HELD_SHADOW_MAX_SAMPLES'
EVERY_ENV='MM_PONS_HELD_SHADOW_EVERY_TICKS'
MAX_SAMPLES=32
MAX_BLOCK_GAP=40
MIN_MARGIN_BPS=1000
MAX_PROBE_SECONDS=2.0


def protective_margin_bps(*,current,high,stop,first_profit,
                           trail_bps,tight_arm=None,tight_trail_bps=None,
                           partial_taken=True):
    """Conservative cushion to the unchanged Pons mark-to-exit thresholds.

    Returns 0 if evidence is incomplete or a stop/trail is already near.
    This determines OPTIONAL shadow-provider work; it never changes exits.
    """
    if type(current) is not int or type(high) is not int:
        return 0
    distances=[current-int(stop)]
    high=max(current,high)
    if partial_taken and high>=first_profit:
        if high>=10000:
            distances.append(current-high*6000//10000)
        else:
            trail=(tight_trail_bps if tight_arm is not None
                   and high>=tight_arm else trail_bps)
            distances.append((10000+current)-
                (10000+high)*(10000-trail)//10000)
    return max(0,min(distances))


def _bounded_int(value,default,minimum,maximum):
    try:
        result=int(value)
    except (ValueError,TypeError):
        return default
    return result if minimum<=result<=maximum else default


@dataclass(frozen=True)
class QuoteSnapshot:
    pool_id: str
    quantity: int
    block: int
    block_hash: str
    net_proceeds: int
    gross_amount_out: int
    gas_quote: int
    observed_monotonic: float


class PaperHeldShadow:
    """Strictly capped per-controller observational counterfactual.

    A single existing native controller owns this object. No shared counters
    or duplicated subscriptions are created. Quoted net proceeds include gas,
    so a change in gas with an unchanged Swap must NOT count as equivalent.
    Run limits are also enforced by the external finite provider resource ledger.
    """
    def __init__(self,endpoint,*,environ=None,clock=monotonic):
        env=os.environ if environ is None else environ
        self.enabled=env.get(SHADOW_ENV)=='1'
        self.endpoint=endpoint
        self.clock=clock
        self.sample_limit=_bounded_int(env.get(MAX_SAMPLE_ENV),8,1,MAX_SAMPLES)
        self.every_ticks=_bounded_int(env.get(EVERY_ENV),10,1,300)
        self.counts=Counter()
        self.last={}
        self.last_result=None
        self.unsafe=False

    def status(self):
        return dict(enabled=self.enabled,mode='PAPER_SHADOW_ONLY',
            entry_authority=False,exit_authority=False,can_skip_quotes=False,
            quote_suppression_enabled=False,controller_policy_modified=False,
            sample_limit=self.sample_limit,every_ticks=self.every_ticks,
            unsafe=self.unsafe,counts=dict(self.counts),last_result=self.last_result,
            provider_invoice_savings_verified=False)

    def observe_after_hold(self,*,rpc,pool_id,quantity,quote_block,quote_hash,
                           net_proceeds,position_open=True,no_pending_exit=True,
                           no_pending_partial=True,owner_protected=True,
                           risk_distance_bps=0,gross_amount_out=None,
                           gas_quote=None):
        """Observe AFTER baseline quote, native risk decision and hold mark.

        Never call this method before an original safety decision or while an
        exit, partial harvest, pending action or unmatched ownership exists.
        """
        if not self.enabled:return None
        if not all((position_open,no_pending_exit,no_pending_partial,owner_protected)):
            self.counts['unsafe_position_state_no_work']+=1
            self.last.pop(pool_id,None)
            return None
        if (type(quantity) is not int or quantity<=0 or
            type(quote_block) is not int or quote_block<0 or
            type(net_proceeds) is not int or net_proceeds<0 or
            not isinstance(quote_hash,str) or
            not quote_hash.startswith('0x') or len(quote_hash)!=66):
            self.counts['unusable_native_quote_no_work']+=1
            self.last.pop(pool_id,None)
            return None
        gross=(net_proceeds if gross_amount_out is None else gross_amount_out)
        gas=(0 if gas_quote is None else gas_quote)
        if (type(gross) is not int or type(gas) is not int or
                gross<net_proceeds or gas<0):
            self.counts['invalid_native_quote_shape_no_work']+=1
            self.last.pop(pool_id,None)
            return None
        snapshot=QuoteSnapshot(str(pool_id).lower(),quantity,quote_block,
                               quote_hash.lower(),net_proceeds,gross,gas,self.clock())
        prior=self.last.get(snapshot.pool_id)
        self.last[snapshot.pool_id]=snapshot
        self.counts['baseline_native_hold_turns']+=1
        if prior is None or prior.quantity!=snapshot.quantity:
            self.counts['new_quantity_or_restart_no_work']+=1
            return None
        if (snapshot.block<prior.block or snapshot.block-prior.block>MAX_BLOCK_GAP
            or (snapshot.block==prior.block and snapshot.block_hash!=prior.block_hash)):
            self.counts['unproven_gap_no_work']+=1
            return None
        if (type(risk_distance_bps) is not int or
                risk_distance_bps<=MIN_MARGIN_BPS):
            self.counts['near_original_protective_exit_no_work']+=1
            return None
        if self.unsafe:
            self.counts['suspended_after_mismatch_no_work']+=1
            return None
        if self.counts['coverage_samples']>=self.sample_limit:
            self.counts['sample_limit_hit_no_work']+=1
            return None
        if self.counts['baseline_native_hold_turns']%self.every_ticks:
            self.counts['unsampled_hold_turns_no_work']+=1
            return None
        self.counts['coverage_samples']+=1
        prior_deadline=getattr(rpc,'evidence_deadline',None)
        acquisition_started=self.clock()
        try:
            deadline=acquisition_started+MAX_PROBE_SECONDS
            if prior_deadline is not None:
                deadline=min(deadline,float(prior_deadline))
            rpc.evidence_deadline=deadline
            proof=NativeHeldCoverage(
                rpc,self.endpoint,clock=self.clock,maximum_blocks=MAX_BLOCK_GAP
            ).observe(
                pool_id=snapshot.pool_id,
                quote_head=dict(number=hex(prior.block),hash=prior.block_hash),
                current_head=dict(number=hex(snapshot.block),hash=snapshot.block_hash),
                token_behavior_proven=False,
                hook_time_invariant_proven=False,
                gas_and_fee_bound_valid=False)
            self.counts['diagnostic_log_elements']+=(
                proof.scoped_elements+proof.global_elements)
            # Two numeric canonical boundaries, before and after acquisition;
            # modeled CU, NOT a separate billed-provider invoice attribution.
            self.counts['diagnostic_modeled_rpc_cu']+=(
                60*(proof.scoped_elements+proof.global_elements)+4*20)
            if proof.events:
                self.counts['observed_price_or_fee_mutations']+=1
            elif proof.window is not None:
                self.counts['complete_empty_event_intervals']+=1
                if prior.gross_amount_out!=snapshot.gross_amount_out:
                    self.counts['silent_native_simulation_output_differences']+=1
                    self.counts['silent_net_quote_differences']+=1
                    self.unsafe=True
                else:
                    self.counts['counterfactual_unchanged_native_output']+=1
                    if prior.net_proceeds!=snapshot.net_proceeds:
                        # Gas pricing can move without a Swap. An optimized
                        # quote scheduler would still need a fresh gas check.
                        self.counts['gas_only_net_quote_differences']+=1
                    else:
                        self.counts['counterfactual_unchanged_net_quote']+=1
                    # The following assumes independent semantic certification
                    # for a future candidate; the runtime has none today.
                    from dataclasses import replace
                    from .held_quote_wakeup import plan_held_quote
                    speculative=replace(proof.window,
                        source='authenticated_canonical_manager_hook_and_token',
                        token_behavior_proven=True,
                        gas_and_fee_bound_valid=True)
                    planned=plan_held_quote(
                        pool_id=snapshot.pool_id,quantity=quantity,
                        quote=dict(pool_id=snapshot.pool_id,quantity=quantity,
                            block=prior.block,block_hash=prior.block_hash,
                            acquired=prior.observed_monotonic),
                        proof=speculative,
                        current_head=dict(number=snapshot.block,
                                          hash=snapshot.block_hash),
                        now_monotonic=self.clock(),
                        risk_distance_bps=risk_distance_bps)
                    if planned.decision=='QUIET_HOLD_ONLY':
                        self.counts['hypothetical_native_simulation_omissions']+=1
                        if prior.net_proceeds==snapshot.net_proceeds:
                            self.counts['hypothetical_quote_omissions']+=1
            else:
                self.counts['incomplete_proof']+=1
            # The native proof deliberately refuses executable quote skipping
            # without independently verified hook, fee and token semantics.
            self.last_result=dict(status=proof.outcome,reason=proof.reason,
                pool_id=snapshot.pool_id,
                from_block=prior.block,to_block=snapshot.block,
                manager_hook_events=len(proof.events),
                unchanged_native_output=prior.gross_amount_out==snapshot.gross_amount_out,
                unchanged_net_quote=prior.net_proceeds==snapshot.net_proceeds,
                gas_price_change_observed=prior.gas_quote!=snapshot.gas_quote,
                logged_scope_elements=proof.scoped_elements+proof.global_elements,
                original_exit_completed_before_shadow=True,
                quote_skipped=False,
                theoretical_not_authorized_omissions=self.counts[
                    'hypothetical_quote_omissions'])
        except (BoundaryError,ValueError,TypeError,KeyError) as exc:
            self.counts['coverage_failures']+=1
            self.last_result=dict(status='INCONCLUSIVE',
                reason=type(exc).__name__+':'+str(exc)[:100],
                original_exit_completed_before_shadow=True,
                quote_skipped=False)
        finally:
            rpc.evidence_deadline=prior_deadline
            seconds=max(0.,self.clock()-acquisition_started)
            self.counts['shadow_elapsed_milliseconds']+=int(seconds*1000)
            if seconds>MAX_PROBE_SECONDS:
                self.unsafe=True
                self.counts['slow_shadow_probe_suspended']+=1
        return self.last_result
