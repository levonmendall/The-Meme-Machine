"""Deployed Pons V2 curve arithmetic and strict source-derived raw event readers.

The compiled curve comes from the verified launch deployer's complete source,
not the different curve file at the current public GitHub revision.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import BoundaryError
from .abi import decode_event, scalar, words
from .identity import authenticate, load, verify_compilation
from .protocols import PoolKey

TEMPLATE = Path(__file__).with_name('pons_curve_template.json')
MAX = 2**256 - 1


def uint(value):
    if not isinstance(value, int) or not 0 <= value <= MAX:
        raise BoundaryError('solidity_uint256_overflow')
    return value


def mul(a, b):
    return uint(a*b)


def authenticate_curve(address, code, *, factory_record):
    template = json.loads(TEMPLATE.read_text())
    verify_compilation(load('pons_deployer'))
    raw = bytes.fromhex(code[2:])
    expected = bytearray.fromhex(template['runtime']['object'])
    if len(raw) != len(expected):
        raise BoundaryError('curve_runtime_length')
    immutables = {}
    for ident, refs in template['runtime']['immutableReferences'].items():
        values = {raw[r['start']:r['start']+r['length']] for r in refs}
        if len(values) != 1:
            raise BoundaryError('curve_immutable_disagreement')
        value = values.pop()
        immutables[template['immutable_names'][ident]] = int.from_bytes(value,'big')
        for ref in refs:
            expected[ref['start']:ref['start']+ref['length']] = value
    if bytes(expected) != raw:
        raise BoundaryError('curve_compiled_bytecode_disagreement')
    factory = load('pons_v2_factory')['address'].lower()
    if immutables['factory'] != int(factory,16):
        raise BoundaryError('curve_factory_disagreement')
    if not factory_record['exists'] or factory_record['curve'].lower() != address.lower():
        raise BoundaryError('curve_factory_provenance')
    for name in ('pairToken','creatorTaxBps','graduationThreshold'):
        value = factory_record[name]
        if immutables[name] != (int(value,16) if isinstance(value,str) else value):
            raise BoundaryError('curve_launch_terms_disagreement')
    return dict(address=address.lower(),token=factory_record['token'],factory=factory,
                immutables=immutables,runtime_sha256=hashlib.sha256(raw).hexdigest(),
                compiler_version=template['compiler_version'],proxy=False)


def factory_record(raw, role='pons_v2_factory'):
    abi = load(role)['abi']
    spec = next(x for x in abi if x.get('name')=='getLaunchedToken')
    fields = spec['outputs'][0]['components']
    data = words(raw)
    if len(fields) != len(data):
        raise BoundaryError('factory_record_shape')
    return {field['name']:scalar(field['type'], word) for field,word in zip(fields,data)}


def curve_abi():
    return json.loads(TEMPLATE.read_text())['abi']


def raw_event(abi, event, *, address, receipt, header, observed_at, confirmation):
    """Retain full raw identity; receipt authenticates this log, not range coverage."""
    if event.get('removed'):
        raise BoundaryError('removed_log_reorg')
    if confirmation not in ('confirmed','finalized'):
        raise BoundaryError('unknown_confirmation')
    if (event['address'].lower() != address.lower() or event['blockHash'] != header['hash']
        or event['blockNumber'] != header['number'] or receipt['blockHash'] != header['hash']
        or receipt['transactionHash'] != event['transactionHash']
        or receipt['transactionIndex'] != event['transactionIndex']
        or int(receipt['status'],16) != 1 or event not in receipt['logs']):
        raise BoundaryError('raw_event_identity_disagreement')
    if int(header['timestamp'],16) > observed_at:
        raise BoundaryError('future_event')
    return dict(decoded=decode_event(abi,event), raw=event, block=int(event['blockNumber'],16),
                block_hash=event['blockHash'],transaction_hash=event['transactionHash'],
                transaction_index=int(event['transactionIndex'],16),log_index=int(event['logIndex'],16),
                event_at=int(header['timestamp'],16),observed_at=observed_at,confirmation=confirmation,
                protocol_address=address.lower())


@dataclass(frozen=True)
class CurveState:
    quote_reserve: int
    token_reserve: int
    real_quote: int
    reserved_tokens: int
    fee_bps: int
    creator_tax_bps: int
    graduated: bool
    launched_at: int
    snipe_start_bps: int
    snipe_seconds: int
    timestamp: int

    def check(self):
        for value in vars(self).values():
            uint(value)
        if self.quote_reserve < self.real_quote or self.fee_bps+self.creator_tax_bps > 2000:
            raise BoundaryError('invalid_curve_state')
        if self.snipe_start_bps > 9900 or self.timestamp < self.launched_at:
            raise BoundaryError('invalid_snipe_state')
        if self.graduated or self.token_reserve <= self.reserved_tokens:
            raise BoundaryError('curve_closed_pending_or_completed_graduation')

    def buy_with_snipe(self, received, current_snipe_bps):
        """Exact buy arithmetic when the deployed curve's current snipe bps is read onchain.

        This avoids relying on a state-changing eth_call from a funded account while
        preserving the source-derived arithmetic. The supplied snipe rate is evidence,
        not a locally predicted value.
        """
        self.check()
        if uint(received)==0 or type(current_snipe_bps) is not int:
            raise BoundaryError('missing_snipe_or_amount')
        maximum=9900-self.fee_bps-self.creator_tax_bps
        if not 0<=current_snipe_bps<=maximum:
            raise BoundaryError('invalid_current_snipe_bps')
        snipe=current_snipe_bps
        spent=received
        def charges(amount):
            return (mul(amount,self.fee_bps)//10000,mul(amount,self.creator_tax_bps)//10000,mul(amount,snipe)//10000)
        fee,tax,penalty=charges(spent)
        net=spent-fee-tax-penalty
        out=mul(mul(net,10000),self.token_reserve)//uint(mul(self.quote_reserve,10000)+mul(net,10000))
        if not out:
            raise BoundaryError('insufficient_output')
        sellable=self.token_reserve-self.reserved_tokens
        if out>sellable:
            out=sellable
            net=mul(mul(out,self.quote_reserve),10000)//mul(self.token_reserve-out,10000)+1
            denom=10000-self.fee_bps-self.creator_tax_bps-snipe
            if denom<=0:
                raise BoundaryError('invalid_buy_fee_sum')
            spent=min((mul(net,10000)+denom-1)//denom,received)
            fee,tax,penalty=charges(spent)
        return dict(spent=spent,refund=received-spent,tokens_out=out,fee=fee+penalty,
                    creator_tax=tax,snipe_tax=penalty,ready_to_graduate=out==sellable)

    def buy(self, received, *, recipient_exempt):
        """Exact native quote input using the source-derived snipe-decay schedule."""
        self.check()
        if type(recipient_exempt) is not bool or uint(received)==0:
            raise BoundaryError('missing_recipient_or_amount')
        elapsed=self.timestamp-self.launched_at
        snipe=0 if recipient_exempt or elapsed>=self.snipe_seconds else self.snipe_start_bps >> (elapsed*14//self.snipe_seconds)
        snipe=min(snipe,9900-self.fee_bps-self.creator_tax_bps)
        return self.buy_with_snipe(received,snipe)

    def sell(self, tokens):
        self.check()
        if uint(tokens)==0:
            raise BoundaryError('zero_sell')
        gross=mul(mul(tokens,10000),self.quote_reserve)//uint(mul(self.token_reserve,10000)+mul(tokens,10000))
        if not gross or gross>self.real_quote:
            raise BoundaryError('impossible_full_position_exit')
        fee=mul(gross,self.fee_bps)//10000
        tax=mul(gross,self.creator_tax_bps)//10000
        return dict(tokens_in=tokens,gross_quote=gross,quote_out=gross-fee-tax,fee=fee,creator_tax=tax)


def prove_v4_lineage(*, record, registration, initialization, graduation, hook, manager):
    """Inputs must be receipt-authenticated events from the pinned deployments."""
    if hook != load('pons_v2_hook')['address'].lower() or manager != load('uniswap_v4_manager')['address'].lower():
        raise BoundaryError('wrong_graduation_deployment')
    if not record['exists'] or record['phase'] != 2:
        raise BoundaryError('graduation_not_completed')
    token,quote=record['token'],record['pairToken']
    key=PoolKey(*sorted((token,quote)),record['poolFee'],record['tickSpacing'],hook)
    pool_id=key.pool_id()
    reg,init,grad=(e['decoded']['args'] for e in (registration,initialization,graduation))
    if (registration['protocol_address'] != hook or initialization['protocol_address'] != manager
        or graduation['protocol_address'] != load('pons_v2_factory')['address'].lower()
        or reg['poolId'] != pool_id or reg['memecoin'] != token or reg['quoteToken'] != quote
        or init['id'] != pool_id or init['currency0'] != key.currency0 or init['currency1'] != key.currency1
        or init['fee'] != key.fee or init['tickSpacing'] != key.tick_spacing or init['hooks'] != hook
        or grad['token'] != token):
        raise BoundaryError('unrelated_v4_or_lineage_disagreement')
    if len({e['transaction_hash'] for e in (registration,initialization,graduation)}) != 1:
        raise BoundaryError('graduation_transaction_disagreement')
    return dict(origin='pons_v2',token=token,curve=record['curve'],pool_id=pool_id,position_id=grad['positionId'])



def prove_v1_v3_lineage(*, record, launch, pool_created, factory, v3_factory):
    """Authenticate a Pons V1 launch into the exact Uniswap V3 pool.

    Both events must already have passed raw receipt/header authentication.  The
    proof binds the Pons factory record, the Pons TokenLaunched event, and the
    Uniswap V3 PoolCreated event from the same transaction.  Token appearance in
    a V3 pool without this provenance is intentionally insufficient.
    """
    expected_factory=load('pons_v1_factory')['address'].lower()
    expected_v3=load('uniswap_v3_factory')['address'].lower()
    if factory.lower()!=expected_factory or v3_factory.lower()!=expected_v3:
        raise BoundaryError('wrong_v1_v3_deployment')
    if launch['protocol_address']!=expected_factory or pool_created['protocol_address']!=expected_v3:
        raise BoundaryError('v1_v3_protocol_identity')
    if launch['decoded']['name']!='TokenLaunched' or pool_created['decoded']['name']!='PoolCreated':
        raise BoundaryError('v1_v3_event_identity')
    if launch['transaction_hash']!=pool_created['transaction_hash']:
        raise BoundaryError('v1_v3_transaction_disagreement')

    args=launch['decoded']['args'];created=pool_created['decoded']['args']
    token=args['token'];pair=args['pairToken'];pool=args['pool']
    if (args['dexFactory']!=expected_v3 or not record.get('exists')
        or record.get('token')!=token or record.get('pairedToken')!=pair
        or record.get('positionId')!=args['positionId']
        or record.get('dexId')!=args['dexId']
        or record.get('launchConfigId')!=args['launchConfigId']
        or record.get('restrictionsEndBlock')!=args['restrictionsEndBlock']
        or record.get('initialBuyAmount')!=args['initialBuyAmount']):
        raise BoundaryError('v1_factory_record_disagreement')

    tokens=tuple(sorted((token,pair),key=lambda x:int(x,16)))
    if (created['token0'],created['token1'])!=tokens:
        raise BoundaryError('v1_v3_currency_disagreement')
    if created['pool']!=pool or created['fee']!=record.get('poolFee'):
        raise BoundaryError('v1_v3_pool_disagreement')
    if bool(record.get('isToken0'))!=(token==created['token0']):
        raise BoundaryError('v1_v3_token_order_disagreement')

    return dict(origin='pons_v1_v3',token=token,market=pool,pair_token=pair,
                pool_fee=created['fee'],dex_id=record['dexId'],
                position_id=record['positionId'],
                transaction_hash=launch['transaction_hash'])
