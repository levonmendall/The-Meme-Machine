"""Ramses pool work and exact-state route preflight; no entry authority."""
from .plane import Plane, digest, plane_path


class RouteIndex:
    def __init__(self,path,policy,*,source='authenticated_alchemy'):
        self.plane=Plane(path);self.policy=policy;self.source=digest(source);self.work={}
        import hashlib
        from pathlib import Path
        from robinhood_research import ramses_costs
        self.source_version=hashlib.sha256(Path(__file__).read_bytes()+Path(ramses_costs.__file__).read_bytes()).hexdigest()

    def begin(self,factory,row,frontier,inputs):
        from robinhood_research import CHAIN_ID, BoundaryError
        from robinhood_research.ramses_costs import COST_MODEL_VERSION
        key=f"ramses:{CHAIN_ID}:{factory.lower()}:{row['pool'].lower()}"
        target=dict(number=frontier['number'],hash=frontier['hash'],finality='finalized',inputs=digest(inputs))
        interpretation=dict(policy=self.policy,cost_model=COST_MODEL_VERSION,chain=CHAIN_ID,source=self.source,source_version=self.source_version,schema=1)
        obs=digest(dict(target=target,row=row));now=self.plane.clock()
        self.plane.observe(key,'ramses',obs,row,ordering=(int(frontier['number'],16),int(now*1_000_000_000)),
            watermark=target,interpretation=interpretation,observed=now,deadline=None,priority=3)
        saved=self.plane.get(key)
        if saved['completed']==saved['desired'] and saved['result']:
            import json
            return json.loads(saved['result'])
        work=self.plane.claim(lane='ramses',key=key)
        if work is None:raise BoundaryError('candidate_pool_work_unavailable')
        self.work[row['pool']]=work
        return None

    def check(self,rpc,factory,row,frontier,native_costs,state):
        from robinhood_research.ramses_costs import quote_native_cycle, COST_MODEL_VERSION
        from robinhood_research import CHAIN_ID, BoundaryError
        from .provider_authority import require_canonical
        try:require_canonical(rpc)
        except ValueError as exc:raise BoundaryError(str(exc)) from None
        target=dict(number=frontier['number'],hash=frontier['hash'],finality='finalized')
        interpretation=dict(policy=self.policy,cost_model=COST_MODEL_VERSION,chain=CHAIN_ID,source=self.source,source_version=self.source_version,schema=1)
        cache_key=digest(dict(factory=factory.lower(),target=target,native_costs=native_costs,row=row,interpretation=interpretation))
        cached=self.plane.evidence('ramses_route_v1',cache_key)
        if cached:return cached[0]
        if not self.current(row['pool']):raise BoundaryError('candidate_generation_superseded')
        costs,meta=quote_native_cycle(rpc,factory,row,int(frontier['number'],16),native_costs,state)
        value=dict(costs=costs,meta=meta,skip_deep=costs is None and meta.get('reason')=='no_executable_bounded_wnative_quote_route')
        self.plane.put('ramses_route_v1',cache_key,value,dict(target=target,interpretation=interpretation,authority='authenticated_alchemy'))
        if not self.current(row['pool']):raise BoundaryError('candidate_generation_superseded')
        return value

    def current(self,pool):
        work=self.work.get(pool)
        return bool(work and self.plane.current(work))

    def complete(self,pool,result,*,reason=None):
        from robinhood_research import BoundaryError
        work=self.work.pop(pool,None)
        if work is None:return  # Exact committed result, no new transition.
        if not self.plane.finish(work,result=result):raise BoundaryError('candidate_generation_superseded')
        state='qualified' if result.get('decision',{}).get('qualified') else 'strategy_rejected'
        self.plane.decision(work['id'],work['generation'],state,reason)
        self.plane.consume(work['id'],work['generation'])

    def fail(self,pool,reason):
        work=self.work.pop(pool,None)
        if work:self.plane.finish(work,state='authoritative_evidence_failure',reason=reason)

    def close(self):
        for pool in list(self.work):self.fail(pool,'interrupted_pool_evaluation')
        self.plane.close()


def pool_metadata(rpc,factory,address,block,build,default_path):
    """Reuse authenticated immutable CWIA arguments and append-only membership.

    The scanner has already authenticated the exact factory runtime. Dynamic
    hooks, reserves, fees and route capability are deliberately excluded.
    """
    from robinhood_research.identity import load
    endpoint=getattr(rpc,'endpoint',None)
    pins=getattr(rpc,'evidence_pins',{})
    if not isinstance(endpoint,str) or hex(block) not in pins:return build()
    from .provider_authority import require_canonical
    require_canonical(rpc)
    domain=digest(dict(source=endpoint,chain=4663,factory=factory.lower(),
        factory_runtime=load('ramses_factory')['runtime_sha256'],
        implementation=load('ramses_pool_implementation')['runtime_sha256'],schema=1))
    plane=Plane(plane_path(default_path))
    try:
        cached=plane.evidence('ramses_pool_metadata:'+domain,address.lower())
        if cached and cached[1]['origin_block']<=block:return cached[0]
        value=build()
        if cached and cached[0]!=value:raise ValueError('immutable_pool_identity_conflict')
        if not cached:
            plane.put('ramses_pool_metadata:'+domain,address.lower(),value,
                dict(authority='authenticated_alchemy',finality='finalized',origin_block=block,
                    origin_hash=pins[hex(block)],schema=1))
        return value
    finally:plane.close()
