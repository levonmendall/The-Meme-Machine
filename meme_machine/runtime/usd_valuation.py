"""Reuse authenticated native market evidence; never synthesize a USD rate."""
from dataclasses import dataclass
from datetime import datetime,timezone
from decimal import Decimal
from meme_machine.exact_money import arithmetic, money, exact
import re
import time

USDG_FEED='0x61B7e5650328764B076A108EFF5fa7282a1B9aD2'
USDG_ASSET='0x5fc5360d0400a0fd4f2af552add042d716f1d168'
USDG_HEARTBEAT=86400
USDG_CACHE_SECONDS=60
USDG_BLOCKER='VALUATION_UNAVAILABLE:USDG/USD: verified read-only oracle evidence required'

class ValuationUnavailable(ValueError):pass

def utc(seconds):return datetime.fromtimestamp(seconds,timezone.utc).isoformat().replace('+00:00','Z')

@dataclass(frozen=True)
class USDValue:
    asset: str
    decimals: int
    usd_per_unit: Decimal
    observed_at: int
    valid_until: int
    evidence_id: str
    evidence_hash: str

    def amount(self,raw,at):
        if type(raw) is not int or raw<0 or not self.observed_at<=at<=self.valid_until:
            raise ValuationUnavailable('native_USD_value_missing_or_stale')
        if self.usd_per_unit<=0:raise ValuationUnavailable('invalid_USD_rate')
        with arithmetic():
            return money(Decimal(raw)*self.usd_per_unit/(Decimal(10)**self.decimals))

    def evidence(self,at):
        self.amount(0,at)
        from meme_machine.portfolio_lane_integration import usd_evidence
        return usd_evidence(self.evidence_id,self.evidence_hash,utc(self.observed_at),utc(self.valid_until))


@exact
def sol_usd(account,*,now,slot,evidence_hash):
    from meme_machine.lanes.pump.pumpswap_survivor_evidence import sol_usd_lower_micros,SOL_USD_ACCOUNT
    micros=sol_usd_lower_micros(account,now=now,slot=slot)
    # The existing decoder checks a <=120s publish age; caller validity never extends it.
    import base64,struct
    published=struct.unpack_from('<q',base64.b64decode(account['data'][0]),93)[0]
    return USDValue('SOL',9,Decimal(micros)/Decimal(1000000),published,published+120,
        'sol-usd:'+str(slot),evidence_hash)


def _unavailable(reason):
    return ValuationUnavailable('VALUATION_UNAVAILABLE:USDG/USD:'+reason)


def _abi(raw,count):
    from meme_machine.lanes.ramses.abi import words
    if not isinstance(raw,str) or not re.fullmatch(r'0x[0-9a-fA-F]+',raw):
        raise _unavailable('malformed_ABI')
    result=words(raw)
    if len(result)!=count:raise _unavailable('malformed_ABI_length')
    return result


def _integer(raw,bits=256):
    from meme_machine.lanes.ramses.abi import scalar
    return scalar('uint'+str(bits),_abi(raw,1)[0])


def _description(raw):
    parts=_abi(raw,3)
    if int.from_bytes(parts[0],'big')!=32 or int.from_bytes(parts[1],'big')!=10:
        raise _unavailable('wrong_feed_description')
    if parts[2]!=b'USDG / USD'+bytes(22):
        raise _unavailable('wrong_feed_description')


def _code(raw):
    if (not isinstance(raw,str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){1,32768}',raw)
            or int(raw,16)==0):
        raise _unavailable('contract_code_missing_or_malformed')


def _block(rpc,now):
    block=rpc.call('eth_getBlockByNumber',['latest',False],scope='position_monitor')
    if (not isinstance(block,dict) or not re.fullmatch(r'0x[0-9a-fA-F]{64}',str(block.get('hash')))):
        raise _unavailable('malformed_block')
    now=max(now,int(time.time()))  # Fresh completion clock after admission/transport.
    number=int(block['number'],16);timestamp=int(block['timestamp'],16)
    if number<=0 or not 0<timestamp<=now:raise _unavailable('invalid_block_time')
    return number,timestamp,block['hash']


def _round(raw,decimals,now):
    from meme_machine.lanes.ramses.abi import scalar
    parts=_abi(raw,5)
    rid,answer,started,updated,answered=(scalar(typ,word) for typ,word in
        zip(('uint80','int256','uint256','uint256','uint80'),parts))
    # EAC proxy IDs contain a nonzero phase and aggregator round. Reject answers
    # from an earlier round, future observations and incomplete rounds.
    if (not rid>>64 or not rid&((1<<64)-1) or answered<rid
            or answered>>64!=rid>>64 or not answered&((1<<64)-1)
            or not 0<started<=updated<=now):
        raise _unavailable('malformed_round')
    if answer<=0:raise _unavailable('nonpositive_answer')
    if now-updated>USDG_HEARTBEAT:raise _unavailable('stale_round')
    if decimals!=8:raise _unavailable('wrong_feed_decimals')
    with arithmetic():
        price=Decimal(answer)/(Decimal(10)**decimals)
    return rid,price,updated


def _rpc(lane):
    if lane=='pons':
        from meme_machine.lanes.pons.provider_topology import configured_rpc as constructor
    else:
        from meme_machine.lanes.ramses.provider_topology import configured_dlmm_rpc as constructor
    return constructor(limit=200,per_scope=200,retries=0)


def robinhood_usd(rpc=None,*,now=None,_at_block=None):
    """Read the pinned Robinhood Chain USDG/USD proxy; never assume parity."""
    from meme_machine.lanes.ramses.abi import calldata,scalar
    from meme_machine.runtime.journal import digest
    now=int(time.time()) if now is None else now
    try:
        rpc=rpc if rpc is not None else _rpc('ramses')
        # A supplied pinned block comes only from the reader's verified session.
        if _at_block is None and rpc.verify_chain()!=4663:raise _unavailable('wrong_chain')
        block,timestamp,block_hash=_block(rpc,now) if _at_block is None else _at_block
        calls=[('eth_getCode',[USDG_FEED,hex(block)])]
        calls.extend(('eth_call',[dict(to=USDG_FEED,data=calldata(name)),hex(block)])
            for name in ('description()','decimals()','latestRoundData()','aggregator()','version()'))
        calls.extend([('eth_getCode',[USDG_ASSET,hex(block)]),
            ('eth_call',[dict(to=USDG_ASSET,data=calldata('decimals()')),hex(block)])])
        code,description,decimals,raw,aggregator,version,token_code,token_decimals=rpc.batch(calls,scope='position_monitor')
        _code(code);_description(description);_code(token_code)
        decimals=_integer(decimals,8)
        if _integer(token_decimals,8)!=6:raise _unavailable('wrong_USDG_token_decimals')
        aggregator=scalar('address',_abi(aggregator,1)[0])
        if int(aggregator,16)==0 or _integer(version)!=6:raise _unavailable('wrong_proxy_interface')
        # AggregatorV3 compatibility is proved by the strict getter/round decode;
        # the underlying aggregator must also be a deployed contract.
        _code(rpc.call('eth_getCode',[aggregator,hex(block)],scope='position_monitor'))
        now=max(now,int(time.time()))
        rid,price,updated=_round(raw,decimals,now)
        if updated>timestamp:raise _unavailable('round_after_pinned_block')
        evidence=dict(chain_id=4663,proxy=USDG_FEED,asset=USDG_ASSET,
            block=block,block_hash=block_hash,description='USDG / USD',decimals=decimals,
            round_data=raw,aggregator=aggregator,heartbeat=USDG_HEARTBEAT)
        return USDValue('USDG',6,price,updated,updated+USDG_HEARTBEAT,
            'usdg-usd:'+USDG_FEED.lower()+':'+str(rid)+':'+str(block),digest(evidence))
    except ValuationUnavailable:raise
    except Exception:
        # Provider exception strings can contain endpoints/credentials. Only a
        # bounded diagnostic crosses the accounting/health boundary.
        raise _unavailable('RPC_unavailable_or_invalid') from None


def _pons_usd(rpc,value,now,state,block_info):
    """Reuse the authenticated executable WNATIVE -> USDG route reader."""
    from meme_machine.lanes.ramses.identity import authenticate,load
    from meme_machine.lanes.ramses.ramses_costs import _wnative,_factory_direct_routes
    from meme_machine.runtime.journal import digest
    block,timestamp,block_hash=block_info
    factory=load('ramses_factory')['address']
    if not state.get('factory_verified'):
        authenticate('ramses_factory',factory,rpc.call('eth_getCode',[factory,hex(block)],scope='position_monitor'))
        state['factory_verified']=True
    wnative=_wnative(rpc,block,state)
    # A bounded executable reference quantity, not strategy sizing authority.
    probe=10**15
    routes=_factory_direct_routes(rpc,factory,wnative,USDG_ASSET,probe,block)
    if not routes:raise _unavailable('native_USDG_executable_route_unavailable')
    route=max(routes,key=lambda item:item['amount_out'])
    output=route['amount_out']
    if type(output) is not int or output<=0:raise _unavailable('native_USDG_invalid_quote')
    with arithmetic():
        price=Decimal(output)*Decimal(10**18)*value.usd_per_unit/(Decimal(probe)*Decimal(10**6))
    result=USDValue('ETH',18,price,max(value.observed_at,timestamp),
        min(value.valid_until,timestamp+5),
        'native-usdg-usd:'+str(block)+':'+route['route_pool'],
        digest(dict(oracle=value.evidence_hash,block_hash=block_hash,wnative=wnative,
            quote=USDG_ASSET,probe_raw=probe,route=route)))
    result.amount(0,max(now,int(time.time())))
    return result


class NativeValueReader:
    """Read the existing authenticated account through shared read-only RPC."""
    def __init__(self,lane,book=None,*,rpc=None):
        self.lane=lane
        self.book=book
        self.rpc=rpc
        self.cached=None
        self.oracle=None
        self.oracle_checked_at=None
        self.route_state={}

    def _robinhood(self,now):
        now=max(now,int(time.time()))
        try:
            if self.lane=='ramses' and self.book is not None and self.book.quote_asset.lower()!=USDG_ASSET:
                raise _unavailable('wrong_Ramses_quote_asset')
            if (self.cached and self.cached.observed_at<=now<=self.cached.valid_until
                    and self.oracle_checked_at<=now<=self.oracle_checked_at+USDG_CACHE_SECONDS):
                return self.cached
            started=time.monotonic()
            rpc=self.rpc if self.rpc is not None else _rpc(self.lane)
            block=None
            if self.lane=='pons':
                if rpc.verify_chain()!=4663:raise _unavailable('wrong_chain')
                block=_block(rpc,now)
            if not (self.oracle and self.oracle.observed_at<=now<=self.oracle.valid_until
                    and self.oracle_checked_at<=now<=self.oracle_checked_at+USDG_CACHE_SECONDS):
                self.oracle=robinhood_usd(rpc,now=now,_at_block=block)
                self.oracle_checked_at=max(now,int(time.time()))
            self.cached=_pons_usd(rpc,self.oracle,now,self.route_state,block) if self.lane=='pons' else self.oracle
            # Transport/admission waits cannot extend a quote or oracle deadline.
            self.cached.amount(0,max(int(time.time()),now+int(time.monotonic()-started)))
            return self.cached
        except Exception as error:
            failure=error if isinstance(error,ValuationUnavailable) else _unavailable('RPC_unavailable_or_invalid')
            from meme_machine.runtime.status import update
            update('VALUATION_UNAVAILABLE',asset='USDG/USD',reason=str(failure))
            raise failure from None

    def __call__(self,now):
        now=max(now,int(time.time()))
        if self.lane in ('pons','ramses'):
            return self._robinhood(now)
        if self.cached and self.cached.observed_at<=now<=self.cached.valid_until:
            return self.cached
        from meme_machine.solana_read_rpc import new_rpc
        from meme_machine.lanes.pump.pumpswap_survivor_evidence import SOL_USD_ACCOUNT
        from meme_machine.runtime.journal import digest
        rpc=new_rpc(limit=40)
        response=rpc.call('getMultipleAccounts',[[SOL_USD_ACCOUNT],dict(encoding='base64',commitment='finalized')],priority=True)
        self.cached=sol_usd(response['value'][0],now=max(now,int(time.time())),slot=response['context']['slot'],evidence_hash=digest(response))
        return self.cached


_readers={}
def native_reader(lane):
    if lane not in _readers:_readers[lane]=NativeValueReader(lane)
    return _readers[lane]
