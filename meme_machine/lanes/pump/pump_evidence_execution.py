"""One physical current-state refresh for a reserved Pump entry.

Historical evidence is exclusively local. A refresh is delayed until the durable
finalized clock reaches the original two-second fill boundary. Rechecking a pending
reservation reuses its one response; it never launches another refresh round.
"""
from types import SimpleNamespace
import time
from . import pump
from .provider import PumpAdapter,Unavailable
from .postgrad import PostGraduationAdapter,pumpswap_pool
from .concentration import ConcentrationReader
from .solana_evidence_runtime import PUMP_SCOPE,SWAP_SCOPE


def execution_addresses(snapshot,session):
    mint=snapshot['mint'];curve=pump.pda([b'bonding-curve',pump.un58(mint)])
    addresses=[curve,mint,session.pump.fee_address]
    if snapshot.get('surface')=='pumpswap':
        addresses += [snapshot['pool'],snapshot['state']['base_vault'],snapshot['state']['quote_vault'],session.postgrad.fee_address]
    return list(dict.fromkeys(addresses))

class CachedExecutionRPC:
    def __init__(self,plane,addresses,response,*,clock=time.time):
        self.plane=plane;self.addresses=addresses;self.clock=clock;self.calls=0
        replies=response if isinstance(response,list) else [response]
        if len(replies)!=3 or {r.get('id') for r in replies}!={1,2,3}:
            raise Unavailable('execution_refresh_response_identity')
        self.replies={r['id']:r for r in replies}
        if any('error' in r or 'result' not in r for r in replies):
            raise Unavailable('execution_refresh_unavailable')
        account=self.replies[1]['result']
        if len(account.get('value') or [])!=len(addresses):raise Unavailable('execution_account_count')
    def transport(self,*args):raise Unavailable('execution_refresh_already_completed')
    def call(self,method,params=None,priority=False):
        self.calls+=1
        if method=='getMultipleAccounts':
            all_accounts=self.replies[1]['result'];lookup=dict(zip(self.addresses,all_accounts['value']))
            if any(key not in lookup for key in params[0]):raise Unavailable('execution_interest_incomplete')
            return dict(context=all_accounts['context'],value=[lookup[k] for k in params[0]])
        if method=='getGenesisHash':return self.replies[3]['result']
        if method=='getTokenLargestAccounts':return self.replies[2]['result']
        if method=='getBlockTime':return self.plane.block_time(params[0])
        raise Unavailable('execution_historical_or_unplanned_call_forbidden:'+method)


def prepare_reserved(session,row,*,new_rpc):
    plane=session.plane
    if plane is None:raise Unavailable('reserved_entry_evidence_plane_required')
    context=row['execution_context'];scope=context['scope'];at=plane.clock()
    life=row['lifecycle'];book=life.book
    saved=book.runtime_state(life.lifecycle_id,'execution_refresh') if book is not None else None
    if saved and saved.get('response') and 'execution_rpc' not in row:
        row['execution_rpc']=CachedExecutionRPC(plane,context['addresses'],saved['response'])
    elif saved and 'execution_rpc' not in row:
        row['refresh_attempted']=True
    frontier=plane.frontier(scope)
    if frontier<=row['decision_slot'] or plane.block_time(frontier)<row['due']:
        raise Unavailable('reserved_entry_waiting_finalized_fill_boundary')
    if row.get('refresh_failed'):raise Unavailable(row['refresh_failed'])
    if 'execution_rpc' not in row:
        # Mark before transport. A failed physical round is not silently repeated.
        if row.get('refresh_attempted'):raise Unavailable('execution_refresh_interrupted')
        if book is not None and not book.checkpoint_runtime(life.lifecycle_id,'execution_refresh',{'attempted':True},claim=True):
            raise Unavailable('execution_refresh_already_claimed')
        row['refresh_attempted']=True
        rpc=new_rpc(limit=40);rpc.evidence_priority=1;rpc.evidence_deadline=row['reserved_at']+20
        remaining=rpc.evidence_deadline-plane.clock()
        if remaining<=0:raise Unavailable('entry_fill_timeout')
        requests=[dict(jsonrpc='2.0',id=1,method='getMultipleAccounts',params=[context['addresses'],dict(encoding='base64',commitment='finalized',minContextSlot=row['decision_slot']+1)]),
                  dict(jsonrpc='2.0',id=2,method='getTokenLargestAccounts',params=[context['mint'],dict(commitment='finalized')]),
                  dict(jsonrpc='2.0',id=3,method='getGenesisHash',params=[])]
        started=time.monotonic()
        plane.count('pump.current_state_refreshes')
        try:
            # Separate client/pacer: no history queue or history lock can be ahead
            # of this request. Its wrapped physical transport uses shared priority 1.
            rpc.calls+=3;rpc.http_requests+=1
            rpc._pace(.5)
            response=rpc.transport(requests)
            row['execution_rpc']=CachedExecutionRPC(plane,context['addresses'],response)
            if book is not None:book.checkpoint_runtime(life.lifecycle_id,'execution_refresh',dict(attempted=True,response=response))
        except Exception as exc:
            row['refresh_failed']='execution_refresh_genuinely_unavailable'
            raise Unavailable(row['refresh_failed']) from exc
        finally:
            row['reserved_fill_latency']=dict(refresh_seconds=time.monotonic()-started,
                finalized_wait_seconds=max(0,at-row['due']),historical_queue_seconds=0)
    cached=row['execution_rpc']
    return SimpleNamespace(plane=plane,rpc=cached,pump=PumpAdapter(cached),postgrad=PostGraduationAdapter(cached,scan_rpc=None),
        reader=ConcentrationReader(cached),ensure=lambda *_:None)
