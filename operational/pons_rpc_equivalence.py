"""Read-only offline provider-response comparisons; no network runner.

The existing PacedRpc diagnostic role already permits a second transport without
changing canonical authority. These comparisons publish no strategy evidence.
The future bounded capability run remains disabled pending separate authorization
and an endpoint-specific, independently checked monetary ceiling.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from meme_machine.lanes.pons import CHAIN_ID,BoundaryError
from meme_machine.lanes.pons.provider import READ_METHODS
from meme_machine.lanes.pons.evidence import canonical

ENVELOPE=dict(enabled=False,maximum_seconds=60,maximum_http_starts=64,
    maximum_logical_elements=256,maximum_delivered_bytes=16*1024*1024,
    maximum_response_bytes=2_000_000,maximum_physical_rps=2,
    maximum_inflight_bytes=2_000_000,throughput_limit_profile=None,
    retries=0,maximum_marginal_usd=None,verified_tariff=None,
    endpoint=None,canonical_authority_changed=False,stream_subscription=False)
STANDARD=READ_METHODS-{'alchemy_getAssetTransfers','eth_callMany'}


def validate_inactive_configuration(config):
    if config.get('enabled') is not True:raise BoundaryError('pons_rpc_comparison_disabled')
    for key in ('maximum_seconds','maximum_http_starts','maximum_logical_elements',
                'maximum_delivered_bytes','maximum_response_bytes','maximum_physical_rps','maximum_inflight_bytes'):
        if type(config.get(key)) not in (int,float) or not 0<config[key]<=ENVELOPE[key]:
            raise BoundaryError('pons_rpc_comparison_envelope')
    if config.get('retries')!=0 or config.get('canonical_authority_changed') is not False:
        raise BoundaryError('pons_rpc_comparison_authority_or_retry_change')
    tariff=config.get('verified_tariff')
    if (not isinstance(tariff,dict) or tariff.get('independently_verified') is not True
            or not tariff.get('source') or not tariff.get('endpoint_fingerprint')
            or not tariff.get('charged_failure_ceiling') or not tariff.get('batch_member_treatment')
            or not tariff.get('archive_rules') or not tariff.get('method_max_usd')):
        raise BoundaryError('pons_rpc_comparison_monetary_ceiling_unverified')
    try:
        ceiling=Decimal(str(config['maximum_marginal_usd']))
        prices={m:Decimal(str(p)) for m,p in tariff['method_max_usd'].items()}
        if (not ceiling.is_finite() or ceiling<=0 or not prices or
                any(m not in STANDARD or not p.is_finite() or p<0 for m,p in prices.items())):
            raise ValueError()
    except (ValueError,TypeError,KeyError,ArithmeticError):
        raise BoundaryError('pons_rpc_comparison_monetary_ceiling_unverified') from None
    return ceiling,prices


@dataclass
class OfflineEnvelope:
    """Reserve before a mock physical start; failures consume their reservation."""
    config:dict
    started:float
    starts:int=0
    elements:int=0
    bytes:int=0
    spending:Decimal=Decimal(0)
    last_start:float|None=None
    inflight:int=0

    def reserve(self,methods,*,now):
        ceiling,prices=validate_inactive_configuration(self.config)
        if now-self.started>=self.config['maximum_seconds']:raise BoundaryError('comparison_wall_ceiling')
        if self.last_start is not None and now-self.last_start<1/self.config['maximum_physical_rps']:
            raise BoundaryError('comparison_original_software_governor')
        if not methods or any(m not in prices for m in methods):raise BoundaryError('comparison_unpriced_method')
        amount=sum((prices[m] for m in methods),Decimal(0))
        if (self.starts+1>self.config['maximum_http_starts'] or
                self.elements+len(methods)>self.config['maximum_logical_elements'] or
                self.spending+amount>ceiling):raise BoundaryError('comparison_purchase_ceiling')
        if self.inflight+self.config['maximum_response_bytes']>self.config['maximum_inflight_bytes']:
            raise BoundaryError('comparison_inflight_payload_reservation')
        self.starts+=1;self.elements+=len(methods);self.spending+=amount;self.last_start=now
        self.inflight+=self.config['maximum_response_bytes']

    def delivered(self,size):
        if type(size) is not int or size<0:raise ValueError('comparison_byte_shape')
        self.bytes+=size
        self.inflight=max(0,self.inflight-self.config['maximum_response_bytes'])
        if self.bytes>self.config['maximum_delivered_bytes']:raise BoundaryError('comparison_payload_ceiling')


def compare_observations(original,candidate,*,decision_deadline):
    """Same exact canonical state and request; equality alone grants no authority.

    Native authentication/decoding supplies the observations in integration tests.
    This diagnostic refuses comparisons across chain states or fresh clocks.
    """
    for row in (original,candidate):
        if row['chain_id']!=CHAIN_ID:raise BoundaryError('wrong_chain')
        h=row['canonical_header']
        if not isinstance(h,dict) or any(k not in h for k in ('number','hash','parentHash','timestamp')):
            raise BoundaryError('comparison_header_incomplete')
        if row['available_at']>decision_deadline or row['observed_at']>row['available_at']:
            raise BoundaryError('comparison_original_deadline')
        if row['available_at']-row['observed_at']>5:raise BoundaryError('comparison_stale_observation')
        if row.get('canonical_after')!=h['hash']:raise BoundaryError('comparison_reorganized_evidence')
        if row['method'] not in STANDARD:raise BoundaryError('comparison_nonstandard_method')
    if original['canonical_header']!=candidate['canonical_header']:
        raise BoundaryError('comparison_different_canonical_states')
    if canonical([original['method'],original['params']])!=canonical([candidate['method'],candidate['params']]):
        raise BoundaryError('comparison_different_block_reference_or_request')
    if original.get('boundary') or candidate.get('boundary'):
        return dict(equivalent=False,qualification_authority=False,status='UNAVAILABLE_OR_ENDPOINT_FAILURE',
            original_boundary=original.get('boundary'),candidate_boundary=candidate.get('boundary'))
    if original.get('result') is None or candidate.get('result') is None:
        return dict(equivalent=False,qualification_authority=False,status='MISSING_EVIDENCE')
    equal=canonical(original['result'])==canonical(candidate['result'])
    return dict(equivalent=equal,qualification_authority=False,status='OFFLINE_PARITY' if equal else 'DISAGREEMENT',
        method=original['method'],canonical_hash=original['canonical_header']['hash'],
        response_digest=hashlib.sha256(canonical(original['result']).encode()).hexdigest() if equal else None)


def inactive_configuration(path):
    Path(path).write_text(json.dumps(ENVELOPE,indent=2)+'\n')
