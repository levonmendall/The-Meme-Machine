"""Bounded Pump native quote/USD component check; no network without --execute.

Owner authorization is separate from this diagnostic. A successful sample does
not certify discovery, flow history, complete protection or PAPER activation.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from unittest.mock import patch

APP='9bin99s96t7ga5e9'
CU={'getGenesisHash':10,'getMultipleAccounts':20,'getBlockTime':20}
LIMITS=dict(seconds=15,http_starts=8,logical_elements=8,modeled_cu=160,
    delivered_bytes=4*1024**2,response_bytes=2_000_000,inflight=1,
    physical_rps=2,retries=0,subscriptions=0,maximum_usd='0.01')


class Stopped(BaseException):pass


def number(value):
    if value is None or isinstance(value,bool):raise ValueError('verified_numeric_fact_required')
    n=Decimal(str(value))
    if not n.is_finite() or n<0:raise ValueError('invalid_numeric_fact')
    return n


def preflight(record,*,now):
    if (record.get('app_id')!=APP or record.get('network')!='SOLANA_MAINNET'
            or record.get('evidence_kind')!='AUTHENTICATED_ACCOUNT_RECORD'
            or record.get('runtime_application_binding_verified') is not True
            or record.get('shared_obligations_reserved') is not True
            or not record.get('account_source') or not record.get('plan')
            or type(record.get('payg_enabled')) is not bool):
        raise ValueError('actual_account_binding_and_entitlement_required')
    if not 0<=now-number(record.get('capacity_observed_at_unix'))<=300:
        raise ValueError('fresh_reserved_account_capacity_required')
    for field,minimum in dict(reserved_cu=160,available_cu_per_ten_seconds=160,
            reserved_physical_rps=2,maximum_inflight=1,maximum_response_bytes=2_000_000,
            reserved_usd=Decimal('.01')).items():
        if number(record.get(field))<minimum:raise ValueError('insufficient_reserved_capacity')
    tariff=record.get('tariff',{})
    if (not tariff.get('source') or tariff.get('charged_failures_included') is not True
            or tariff.get('exceptional_charges_included') is not True
            or set(tariff.get('method_max_cu',{}))!=set(CU)
            or set(tariff.get('method_max_usd',{}))!=set(CU)):
        raise ValueError('complete_authenticated_upper_tariff_required')
    for method in CU:
        if not CU[method]<=number(tariff['method_max_cu'][method])<=20:
            raise ValueError('charged_CU_outside_fixed_component_envelope')
    prices={method:number(tariff['method_max_usd'][method]) for method in CU}
    overhead=(number(tariff.get('fixed_max_usd'))+8*number(tariff.get('start_max_usd'))
        +LIMITS['delivered_bytes']*number(tariff.get('byte_max_usd')))
    worst=overhead+8*max(prices.values())
    if worst>Decimal('.01'):raise ValueError('worst_case_exceeds_one_cent')
    return prices,overhead,worst


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise Stopped('redirect_forbidden')


class Boundary:
    def __init__(self,endpoint,prices,overhead,*,expires,opener,clock=time.monotonic,
                 wall=time.time,sleep=time.sleep):
        self.endpoint,self.prices,self.spending=endpoint,prices,overhead
        self.opener,self.clock,self.wall,self.sleep=opener,clock,wall,sleep
        self.started=clock();self.deadline=min(self.started+15,self.started+expires-wall())
        self.expires=expires;self.last_start=None;self.active=False
        self.starts=self.bytes=self.charged_cu=0;self.methods=Counter();self.rows=[]
        self.reason=None;self.closed=False

    def stop(self,reason):
        self.reason=reason;self.closed=True;raise Stopped(reason)

    def check(self):
        if self.closed:raise Stopped(self.reason or 'completed')
        if self.clock()>=self.deadline or self.wall()>=self.expires:self.stop('hard_time_limit')

    def transport(self,call):
        self.check();method=call.get('method')
        if method not in CU or self.active:self.stop('method_or_concurrency_limit')
        if self.last_start is not None:
            wait=self.last_start+.5-self.clock()
            if wait>0:self.sleep(wait)
        self.check()
        if (self.starts>=8 or self.charged_cu+20>160
                or self.spending+self.prices[method]>Decimal('.01')):
            self.stop('request_or_spend_limit')
        body=json.dumps(call).encode()
        if len(body)>65536:self.stop('request_payload_limit')
        self.starts+=1;self.charged_cu+=20;self.methods[method]+=1
        self.spending+=self.prices[method];self.last_start=self.clock();self.active=True
        row=dict(method=method,started_seconds=self.clock()-self.started)
        self.rows.append(row)
        try:
            request=Request(self.endpoint,data=body,headers={'Content-Type':'application/json'})
            with self.opener(request,timeout=max(.001,self.deadline-self.clock())) as response:
                chunks=[];size=0
                while True:
                    self.check()
                    remaining=min(2_000_000-size,4*1024**2-self.bytes)
                    if remaining<=0:self.stop('response_or_delivery_limit')
                    chunk=getattr(response,'read1',response.read)(min(65536,remaining))
                    self.bytes+=len(chunk);size+=len(chunk);self.check()
                    if not chunk:break
                    chunks.append(chunk)
                raw=b''.join(chunks);value=json.loads(raw)
            if (not isinstance(value,dict) or value.get('jsonrpc')!='2.0'
                    or value.get('id')!=call['id'] or value.get('error') is not None
                    or value.get('result') is None):self.stop('RPC_failure_no_retry')
            row.update(response_bytes=size,response_sha256=hashlib.sha256(raw).hexdigest(),
                completed_seconds=self.clock()-self.started)
            return value
        except Stopped:raise
        except Exception:self.stop('transport_or_JSON_failure_no_retry')
        finally:self.active=False

    def receipt(self):
        return dict(reason=self.reason,physical_starts=self.starts,logical_elements=self.starts,
            modeled_cu=sum(CU[m]*n for m,n in self.methods.items()),
            charged_cu_reserved=self.charged_cu,delivered_bytes=self.bytes,
            upper_spend_reserved_usd=str(self.spending),actual_invoice_usd=None,
            elapsed_seconds=self.clock()-self.started,methods=dict(self.methods),requests=self.rows)


@contextmanager
def hard_timer(boundary):
    previous=signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM,lambda *_:boundary.stop('hard_time_limit'))
    signal.setitimer(signal.ITIMER_REAL,max(.000001,boundary.deadline-boundary.clock()))
    try:yield
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)


def acquire(rpc,boundary,mint):
    from meme_machine.lanes.pump.postgrad import PostGraduationAdapter,buy_quote,sell_quote,validate_postgrad_snapshot
    from meme_machine.runtime.usd_valuation import NativeValueReader
    # Same original native reader/decoder; only the isolated RPC injection differs.
    with patch('meme_machine.solana_read_rpc.new_rpc',return_value=rpc):
        value=NativeValueReader('pump')(int(boundary.wall()))
    adapter=PostGraduationAdapter(rpc);samples=[];tokens=None
    for kind in ('cold','warm'):
        started=boundary.clock()
        snapshot=adapter.pumpswap_snapshot(mint,int(boundary.wall()),
            reuse_verified_pool=True,held_curve_inline=True)
        now=int(boundary.wall());validate_postgrad_snapshot(snapshot,now,'prospective')
        # Floor the diagnostic dollar budget using exact rational arithmetic;
        # native accounting's Decimal traps remain enabled and unchanged.
        budget=(Fraction(Decimal('6.25'))*10**9)//Fraction(value.amount(10**9,now))
        bought=buy_quote(snapshot,budget)
        if tokens is None:tokens=bought.output_amount
        full=sell_quote(snapshot,tokens);partial=sell_quote(snapshot,max(1,tokens//2))
        value.amount(full.output_amount,now);value.amount(partial.output_amount,now)
        elapsed=boundary.clock()-started
        if elapsed>5:boundary.stop('original_five_second_acquisition_deadline')
        samples.append(dict(kind=kind,slot=snapshot['slot'],market_time=snapshot['market_time'],
            elapsed_seconds=elapsed,buy=asdict(bought),full_sell=asdict(full),partial_sell=asdict(partial)))
        if kind=='cold':boundary.sleep(max(0,started+5-boundary.clock()));boundary.check()
    return dict(native_samples=samples,usd=asdict(value),
        complete_protection_proven=False,discovery_proven=False,paper_ready=False,
        runtime_mode_changed=False,orders=0,subscriptions=0)


def protected(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_mode&0o077 or path.stat().st_size>16384:
        raise ValueError('bounded_private_configuration_required')
    return path.read_text()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    for name in ('account-record','env-file','mint','expires-unix','source-commit','output'):
        parser.add_argument('--'+name)
    args=parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(dict(status='NOT_RUN',owner_authorization_required=True,
            limits=LIMITS,expected_maximum_starts=7,expected_maximum_cu=130,paper_ready=False)))
        return 0
    if os.environ.get('CI') or not all((args.account_record,args.env_file,args.mint,
            args.expires_unix,args.source_commit,args.output)):parser.error('explicit authorized component inputs required')
    from engineering.solana_capacity.pump_pons_proof import source_identity
    source=source_identity()
    if source['dirty'] or source['commit']!=args.source_commit:parser.error('exact clean frozen source required')
    import sys
    if sys.version_info[:3]!=(3,12,14):parser.error('pinned Python 3.12.14 required')
    from meme_machine.lanes.pump.pump import un58
    if len(un58(args.mint))!=32:parser.error('one valid locally retained Pump mint required')
    source['component_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    from meme_machine.lanes.pump.solana_provider_config import AlchemyEndpoint
    lines=[line.split('=',1)[1] for line in protected(args.env_file).splitlines()
        if line.startswith('MM_SOLANA_READ_RPC_URL=')]
    if len(lines)!=1:parser.error('one configured authenticated Solana endpoint required')
    endpoint=AlchemyEndpoint.parse(' '.join(shlex.split(lines[0])))
    prices,overhead,worst=preflight(json.loads(protected(args.account_record)),now=Decimal(str(time.time())))
    expires=number(args.expires_unix)
    if expires<=Decimal(str(time.time())):parser.error('unexpired separately authorized UTC window required')
    output=Path(args.output).resolve()
    if output.exists() or str(output).startswith(('/opt/','/etc/','/mnt/','/var/lib/')):
        parser.error('new isolated engineering output required')
    from meme_machine.operational.artifact_storage import Scratch
    from meme_machine.lanes.pump.provider import RPC
    with Scratch() as scratch:
        boundary=Boundary(endpoint.http_url,prices,overhead,expires=float(expires),
            opener=build_opener(NoRedirect()).open)
        # Retain the provider client's original minimum; the independent
        # transport boundary restricts this component to eight physical starts.
        rpc=RPC(endpoint.http_url,limit=40,transport=boundary.transport)
        result=None
        try:
            with hard_timer(boundary):result=acquire(rpc,boundary,args.mint);boundary.check()
        except (Stopped,Exception):
            if boundary.reason is None:boundary.reason='native_evidence_unavailable_or_invalid'
        boundary.closed=True
        receipt=dict(source=source,app_id=APP,status='PASS_COMPONENT_ONLY' if result and not boundary.reason else 'FAIL',
            limits=LIMITS,actual_worst_case_usd=str(worst),acquisition=boundary.receipt(),result=result)
        output.parent.mkdir(parents=True,exist_ok=True)
        # Decimal rates remain exact in a secret-free, private diagnostic receipt.
        output.write_text(json.dumps(receipt,indent=2,default=str)+'\n');output.chmod(0o600)
        scratch.check();scratch.success=receipt['status']=='PASS_COMPONENT_ONLY'
    print(json.dumps(dict(status=receipt['status'],output=str(output),paper_ready=False)))
    return 0 if receipt['status']=='PASS_COMPONENT_ONLY' else 1


if __name__=='__main__':raise SystemExit(main())
