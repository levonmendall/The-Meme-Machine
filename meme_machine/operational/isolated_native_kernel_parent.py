"""Fixed synthetic parent for native kernel validation, never market evidence.

Only anonymous local sockets and disposable nonfinancial ledgers are used. The
original native parsers, Budget, Governor, Admission and transport FULL handoff
remain active; deterministic responses replace external providers explicitly.
"""
from dataclasses import replace
import hashlib
import io
import json
import threading
from types import MappingProxyType

from .bounded_provider import Budget
from .parent_transport import ParentHTTP,SourceBinding,NativeSourceBinding,NativeFactoryMap
from .parent_channel import ParentChannel
from .pons_native_profile import ParentPonsProfiles
from .isolated_native_pons_kernel_corpus import PonsKernelCorpus
from .transport_bridge import EndpointAlias,READ_METHODS

SOLANA='https://solana-mainnet.g.alchemy.com/v2/SYNTHETIC_KERNEL_NO_CREDENTIAL'
PONS='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_KERNEL_NO_CREDENTIAL'
PROVENANCE='SYNTHETIC_KERNEL_LIFECYCLE_ONLY_NOT_MARKET_OR_FINANCIAL_EVIDENCE'
MAX_REQUESTS=256


class KernelFixtureRefused(RuntimeError):pass


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def require_registry(sources,native):
    """Check the complete fixed fixture registry before copying or launching.

    Stream aliases have source-identity attribution, distinct from the six
    native runner RPC selectors. This checks the existing child selectors'
    exact operation/read-class contract without adding a child fallback.
    """
    expected={}
    for lane,family in (('pump','solana'),('pons','robinhood')):
        for regime in ('current','survivor','discovery'):
            operation=lane+'_discovery' if regime=='discovery' else lane+'_'+regime+'_qualification'
            expected[lane+'-'+regime]=(family,operation,'native')
    for operation in ('pump_history_receipt','pump_recovery_restart','pump_source_identity'):
        for priority in range(1,7):
            expected[operation+'_'+str(priority)]=('solana',operation,'solana_evidence_'+str(priority))
    for alias in ('yellowstone','solana-websocket'):
        expected[alias]=('solana','pump_source_identity','native')
    if (type(sources) not in (dict,MappingProxyType) or set(sources)!=set(expected)
            or any(type(row) is not SourceBinding or row.alias.name!=alias
                or (row.alias.family,row.operation,row.read_class)!=expected[alias]
                or row.alias.methods!=READ_METHODS[row.alias.family]
                for alias,row in sources.items())):
        raise KernelFixtureRefused('kernel_fixture_source_registry')
    for family in ('solana','robinhood'):
        identities={row.identity for row in sources.values() if row.alias.family==family}
        if len(identities)!=1:raise KernelFixtureRefused('kernel_fixture_source_identity')
    streams={'yellowstone':'yellowstone','solana-websocket':'solana_websocket',
        'pons-discovery':'robinhood_sequencer'}
    if (len(native)!=len(streams) or any(type(row) is not NativeSourceBinding for row in native)
            or {row.source.alias.name:row.transport for row in native}!=streams
            or any(row.source is not sources[row.source.alias.name] for row in native)):
        raise KernelFixtureRefused('kernel_fixture_stream_registry')


class _Body(io.BytesIO):
    status=200


class SyntheticParent:
    def __init__(self,root,solana):
        from meme_machine.runtime.governor import Governor
        from meme_machine.lanes.pons.provider_admission import Admission
        self.solana=solana;self.pons=PonsKernelCorpus(solana.started_at,economic=True)
        self.calls=0;self.elements=0;self.bytes=0;self.lock=threading.Lock()
        self.budget=Budget.create(root/'synthetic-usage.sqlite',wall_seconds=180,
            modeled_spend_limit='3',maximum_native_opens=32)
        governor=Governor(root/'synthetic-governor.sqlite')
        admission=Admission(root/'synthetic-pons-admission.sqlite',PONS,lane='pons')
        sol=SourceBinding.configured(EndpointAlias('pump-discovery','solana',READ_METHODS['solana']),
            'pump_discovery',environ={'MM_SOLANA_READ_RPC_URL':SOLANA},governor=governor)
        pons=SourceBinding.configured(EndpointAlias('pons-discovery','robinhood',READ_METHODS['robinhood']),
            'pons_discovery',environ={'MM_ROBINHOOD_READ_RPC_URL':PONS},admission=admission)
        sources=[]
        for base,lane in ((sol,'pump'),(pons,'pons')):
            for regime in ('current','survivor','discovery'):
                sources.append(replace(base,alias=EndpointAlias(lane+'-'+regime,base.alias.family,base.alias.methods),
                    operation=lane+'_discovery' if regime=='discovery' else lane+'_'+regime+'_qualification'))
        for operation in ('pump_history_receipt','pump_recovery_restart','pump_source_identity'):
            for priority in range(1,7):
                sources.append(replace(sol,alias=EndpointAlias(operation+'_'+str(priority),'solana',sol.alias.methods),
                    operation=operation,read_class='solana_evidence_'+str(priority)))
        for alias in ('yellowstone','solana-websocket'):
            sources.append(replace(sol,alias=EndpointAlias(alias,'solana',sol.alias.methods),
                operation='pump_source_identity'))
        self.http=ParentHTTP(self.budget,sources,opener=self._physical)
        by_name=self.http.sources
        native=(NativeSourceBinding(by_name['yellowstone'],'yellowstone'),
            NativeSourceBinding(by_name['solana-websocket'],'solana_websocket'),
            NativeSourceBinding(by_name['pons-discovery'],'robinhood_sequencer'))
        require_registry(by_name,native)
        async def yellowstone():return await self.solana.open('yellowstone')
        async def websocket():return await self.solana.open('solana_websocket')
        factories=NativeFactoryMap(self.http,native,{('yellowstone','yellowstone'):yellowstone,
            ('solana-websocket','solana_websocket'):websocket,('pons-discovery','robinhood_sequencer'):self.pons.open})
        self.channel=ParentChannel(self.http,native_sources=native,native_factories=factories,
            pons_profiles=ParentPonsProfiles.configured(self.http,environ={}),seconds=150)

    def _physical(self,request,timeout):
        with self.lock:
            self.calls+=1
            if self.calls>MAX_REQUESTS:raise KernelFixtureRefused('kernel_fixture_request_bound')
            calls=json.loads(request.data);rows=calls if isinstance(calls,list) else [calls]
            self.elements+=len(rows)
            # Identity selection is fixed here; the child cannot choose URLs.
            if request.full_url==SOLANA:corpus=self.solana
            elif request.full_url==PONS:corpus=self.pons
            else:raise KernelFixtureRefused('kernel_fixture_external_endpoint')
            replies=[dict(jsonrpc='2.0',id=row['id'],result=corpus.rpc(row['method'],row['params'])) for row in rows]
            body=encoded(replies if isinstance(calls,list) else replies[0]);self.bytes+=len(body)
            return _Body(body)

    def counters(self):
        return dict(provenance=PROVENANCE,external_provider_calls=0,synthetic_requests=self.calls,
            synthetic_elements=self.elements,synthetic_body_bytes=self.bytes,
            pons=self.pons.counters(),solana=self.solana.snapshot())

    async def close(self):
        await self.channel.aclose()
        await self.http.aclose()


def sizing_receipt(approval,*,session,at,sequence):
    from meme_machine.runtime.directional_sleeve import policies
    value=approval.value()
    lanes={lane:dict(realized_equity=0,available=0,reserved=0,policies=policies(lane),
        native_unit='lamports' if lane=='pump' else 'wei',
        usd_evidence_hash=hashlib.sha256((PROVENANCE+lane).encode()).hexdigest(),
        valuation_observed_at=at,valuation_valid_until=at+(120 if lane=='pump' else 5)) for lane in ('pump','pons')}
    return dict(schema='protected-parent-native-sizing-v1',session=session,facts=dict(
        schema='isolated-native-sizing-v1',scope='synthetic-kernel-'+value['source_commit'][:16],
        source_commit=value['source_commit'],source_tree=value['source_tree'],
        epoch_reference='SYNTHETIC_NO_FINANCIAL_EPOCH',portfolio_sequence=sequence,
        observed_at=at,valid_until=at+5,lanes=lanes))
