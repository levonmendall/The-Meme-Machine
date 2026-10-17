"""Fixed synthetic Pons wire inputs for native kernel/component validation.

Source deployment bytecodes authenticate through the original native readers.
Headers and Nitro messages are synthetic; economic events are still unexercised.
No captured production record, provider transport or financial authority exists.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct
import threading
import time


class PonsKernelFixtureRefused(RuntimeError):pass


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class PonsKernelCorpus:
    """Original canonical RPC/parser shapes; no economic candidate claim."""
    def __init__(self,started_at):
        if type(started_at) is not int or started_at<200:
            raise PonsKernelFixtureRefused('kernel_fixture_pons_timestamp')
        self.started_at=started_at
        self.requests=0;self.feed_messages=0;self.streams=[]
        from meme_machine.lanes.pons.identity import metadata
        self.codes={metadata(role)['address'].lower():metadata(role)['runtimeBytecode']['onchainBytecode']
            for role in ('pons_v2_factory','pons_deployer','pons_v2_hook','uniswap_v4_manager')}

    def header(self,number):
        if type(number) is not int or not 0<=number<=200:
            raise PonsKernelFixtureRefused('kernel_fixture_pons_block')
        # The synthetic genesis has a nonempty, fixed identity. Parent links
        # agree for every subsequent block without borrowing a mainnet hash.
        return dict(number=hex(number),timestamp=hex(self.started_at+number-200),
            hash='0x'+f'{number+1:064x}',parentHash='0x'+f'{number:064x}')

    def rpc(self,method,params):
        self.requests+=1
        if method=='eth_chainId':return hex(4663)
        if method=='eth_blockNumber':return hex(200)
        if method=='eth_getCode' and params[0].lower() in self.codes:return self.codes[params[0].lower()]
        if method=='eth_getBlockByNumber':
            number=200 if params[0] in ('latest','safe','finalized') else int(params[0],16)
            return self.header(number)
        if method=='eth_getLogs':return []
        raise PonsKernelFixtureRefused('kernel_fixture_pons_method')

    async def open(self):
        raw=_NitroFixture(self)
        self.streams.append(raw)
        return raw

    def counters(self):
        return dict(synthetic_rpc_elements=self.requests,synthetic_nitro_messages=self.feed_messages,
            streams=len(self.streams),streams_closed=sum(row.closed for row in self.streams),
            economic_candidates='UNEXERCISED')


class _NitroFixture:
    """Actual Nitro framing parser over an anonymous local socketpair.

    External TLS/HTTP and real signature authentication are unexercised. The
    messages carry only the original explicit synthetic signature marker.
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
            body=_encoded(value)
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
            raise PonsKernelFixtureRefused('kernel_fixture_nitro_cancelled')
        self.pending=asyncio.get_running_loop().run_in_executor(self.executor,receive)
        try:return await asyncio.shield(self.pending)
        finally:
            if self.pending.done():self.pending=None

    async def write(self,body):raise PonsKernelFixtureRefused('kernel_fixture_nitro_write')

    async def aclose(self):
        if self.closed:return
        self.cancel();self.sending.cancel()
        await asyncio.gather(self.sending,return_exceptions=True)
        if self.pending is not None:
            await asyncio.gather(self.pending,return_exceptions=True)
            self.pending=None
        self.client.close();self.reader.close();self.writer.close()
        self.executor.shutdown(wait=True);self.closed=True
