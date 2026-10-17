"""Fixed synthetic parent for native kernel validation, never market evidence.

Only anonymous local sockets and disposable nonfinancial ledgers are used. The
original native parsers, Budget, Governor, Admission and transport FULL handoff
remain active; deterministic responses replace external providers explicitly.
"""
import asyncio
from dataclasses import replace
import hashlib
import io
import json
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .bounded_provider import Budget
from .parent_transport import ParentHTTP,SourceBinding,NativeSourceBinding,NativeFactoryMap
from .parent_channel import ParentChannel
from .pons_native_profile import ParentPonsProfiles
from .transport_bridge import EndpointAlias,READ_METHODS

SOLANA='https://solana-mainnet.g.alchemy.com/v2/SYNTHETIC_KERNEL_NO_CREDENTIAL'
PONS='https://robinhood-mainnet.g.alchemy.com/v2/SYNTHETIC_KERNEL_NO_CREDENTIAL'
PROVENANCE='SYNTHETIC_KERNEL_LIFECYCLE_ONLY_NOT_MARKET_OR_FINANCIAL_EVIDENCE'
MAX_REQUESTS=256


class KernelFixtureRefused(RuntimeError):pass


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class _Body(io.BytesIO):
    status=200


class PonsKernelCorpus:
    """Original canonical RPC/parser shapes; no Pons economic candidate claim."""
    def __init__(self,started_at):
        self.started_at=started_at
        self.requests=0;self.feed_messages=0;self.streams=[]
        from meme_machine.lanes.pons.identity import metadata
        self.codes={metadata(role)['address'].lower():metadata(role)['runtimeBytecode']['onchainBytecode']
            for role in ('pons_v2_factory','pons_v2_hook','uniswap_v4_manager')}

    def rpc(self,method,params):
        self.requests+=1
        if method=='eth_chainId':return hex(4663)
        if method=='eth_blockNumber':return hex(200)
        if method=='eth_getCode' and params[0].lower() in self.codes:return self.codes[params[0].lower()]
        if method=='eth_getBlockByNumber':
            number=200 if params[0] in ('latest','safe','finalized') else int(params[0],16)
            if not 0<=number<=200:raise KernelFixtureRefused('kernel_fixture_pons_block')
            return dict(number=hex(number),timestamp=hex(self.started_at+number-200),
                hash='0x'+f'{number:064x}')
        if method=='eth_getLogs':return []
        raise KernelFixtureRefused('kernel_fixture_pons_method')

    async def open(self):
        raw=_NitroFixture(self)
        self.streams.append(raw)
        return raw

    def counters(self):
        return dict(synthetic_rpc_elements=self.requests,synthetic_nitro_messages=self.feed_messages,
            streams=len(self.streams),streams_closed=sum(row.closed for row in self.streams),
            economic_candidates='UNEXERCISED')


class _NitroFixture:
    """Actual Nitro WebSocket framing parser over an anonymous local socketpair.

    External TLS/HTTP acquisition is unexercised. The fixed JSON messages carry
    synthetic signature-presence markers; no real signature is authenticated.
    """
    def __init__(self,corpus):
        from meme_machine.lanes.pons.sequencer_feed import _WebSocket
        self.corpus=corpus;self.closed=False;self.stopped=threading.Event();self.pending=None
        self.reader,self.writer=socket.socketpair()
        self.reader.settimeout(.5);self.writer.setblocking(False)
        self.client=_WebSocket('wss://feed.mainnet.chain.robinhood.com',timeout=.5)
        self.client.sock=self.reader
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='synthetic-nitro')
        self.sending=asyncio.create_task(self._send())

    async def _send(self):
        for sequence in range(1,129):
            if self.stopped.is_set():return
            value=dict(version=1,messages=[dict(sequenceNumber=sequence,signatureV2='SYNTHETIC_NOT_A_SIGNATURE',
                message=dict(message=dict(header=dict(kind=3,sender='0x0',blockNumber=200,
                    timestamp=int(time.time())),l2Msg='AA==')))])
            body=encoded(value)
            frame=b'\x81\x7e'+struct.pack('!H',len(body))+body
            await asyncio.get_running_loop().sock_sendall(self.writer,frame)
            self.corpus.feed_messages+=1
            await asyncio.sleep(.5)

    def cancel(self):
        self.stopped.set()
        try:self.reader.shutdown(socket.SHUT_RDWR)
        except OSError:pass

    async def read(self):
        import grpc
        def receive():
            while not self.stopped.is_set():
                try:value=self.client.recv_message()
                except socket.timeout:continue
                if value is None:return grpc.aio.EOF
                body=value.encode();return len(body),body
            raise KernelFixtureRefused('kernel_fixture_nitro_cancelled')
        self.pending=asyncio.get_running_loop().run_in_executor(self.executor,receive)
        try:return await asyncio.shield(self.pending)
        finally:
            if self.pending.done():self.pending=None

    async def write(self,body):raise KernelFixtureRefused('kernel_fixture_nitro_write')

    async def aclose(self):
        if self.closed:return
        self.cancel();self.sending.cancel()
        await asyncio.gather(self.sending,return_exceptions=True)
        if self.pending is not None:
            await asyncio.gather(self.pending,return_exceptions=True)
            self.pending=None
        self.client.close();self.reader.close();self.writer.close()
        self.executor.shutdown(wait=True);self.closed=True


class SyntheticParent:
    def __init__(self,root,solana):
        from meme_machine.runtime.governor import Governor
        from meme_machine.lanes.pons.provider_admission import Admission
        self.solana=solana;self.pons=PonsKernelCorpus(solana.started_at)
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
            sources.append(replace(sol,alias=EndpointAlias(alias,'solana',sol.alias.methods)))
        self.http=ParentHTTP(self.budget,sources,opener=self._physical)
        by_name=self.http.sources
        native=(NativeSourceBinding(by_name['yellowstone'],'yellowstone'),
            NativeSourceBinding(by_name['solana-websocket'],'solana_websocket'),
            NativeSourceBinding(by_name['pons-discovery'],'robinhood_sequencer'))
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
