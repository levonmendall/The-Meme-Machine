"""Fixed synthetic Pons wire inputs for native kernel/component validation.

Source deployment bytecodes authenticate through the original native readers.
Headers, Nitro messages and optional economic event bodies are synthetic inputs;
native economic publication is unverified until its private outputs are inspected.
No captured production record, provider transport or financial authority exists.
"""
import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct
import threading


class PonsKernelFixtureRefused(RuntimeError):pass


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class PonsKernelCorpus:
    """Original canonical RPC/parser shapes; no economic candidate claim."""
    def __init__(self,started_at,*,economic=False):
        if type(started_at) is not int or started_at<200:
            raise PonsKernelFixtureRefused('kernel_fixture_pons_timestamp')
        if type(economic) is not bool:raise PonsKernelFixtureRefused('kernel_fixture_pons_mode')
        self.started_at=started_at
        self.economic=economic;self.top=200;self.current_block=200;self.maximum=263
        self.requests=0;self.feed_messages=0;self.streams=[]
        from meme_machine.lanes.pons.identity import metadata
        self.codes={metadata(role)['address'].lower():metadata(role)['runtimeBytecode']['onchainBytecode']
            for role in ('pons_v2_factory','pons_deployer','pons_v2_hook','uniswap_v4_manager')}
        self.logs=[];self.records={};self.launch_blocks={};self.receipts={}
        self.curve_codes={};self.methods={};self.refused=0;self.last_sequence=0
        if economic:self._economic_wire()

    @staticmethod
    def _word(value):return f'{int(value) % (1<<256):064x}'

    def _event(self,abi,name,values,*,address,block,tx_index,index=0):
        from meme_machine.lanes.pons.abi import signature,topic
        spec=next(e for e in abi if e.get('type')=='event' and e.get('name')==name)
        topics=[topic(signature(spec))];data=[]
        for field in spec['inputs']:
            value=values[field['name']]
            word=self._word(int(value,16) if isinstance(value,str) else value)
            (topics if field['indexed'] else data).append('0x'+word if field['indexed'] else word)
        return dict(address=address.lower(),topics=topics,data='0x'+''.join(data),
            blockNumber=hex(block),blockHash=self._wire_header(block)['hash'],
            transactionHash='0x'+self._word(block*100+tx_index),
            transactionIndex=hex(tx_index),logIndex=hex(index),removed=False)

    def _economic_wire(self):
        from meme_machine.lanes.pons.identity import metadata
        from meme_machine.lanes.pons.pons import _template
        from meme_machine.lanes.pons.protocols import PoolKey
        source=metadata('pons_v2_factory');factory=source['address'].lower()
        hook=metadata('pons_v2_hook');manager=metadata('uniswap_v4_manager')
        base=int(source['deployment']['blockNumber'])
        self.current_block=base+200;self.top=self.current_block;self.maximum=self.current_block+63
        self.current_token='0x'+f'{0x1001:040x}';self.survivor_token='0x'+f'{0x1002:040x}'
        self.current_curve='0x'+f'{0x2001:040x}'
        template=_template()
        for offset,token in enumerate((self.current_token,self.survivor_token)):
            curve='0x'+f'{0x2001+offset:040x}';creator='0x'+f'{0x3001+offset:040x}'
            record=dict(token=token,curve=curve,deployer=creator,creatorFeeRecipient=creator,
                pairToken='0x'+'00'*20,graduationThreshold=10**18,poolFee=3000,tickSpacing=60,
                creatorTaxBps=50,buybackEnabled=False,phase=1+offset,sweptQuote=0,
                sweptTokens=0,sweptAt=0,exists=True)
            self.records[token]=record;self.launch_blocks[curve]=base+(50 if offset==0 else 180)
            code=bytearray.fromhex(template['runtime']['object'])
            values=dict(record,factory=factory,feeBps=100,phantomQuote=12*10**17)
            for identity,refs in template['runtime']['immutableReferences'].items():
                value=values.get(template['immutable_names'][identity],0)
                value=int(value,16) if isinstance(value,str) else int(value)
                for ref in refs:code[ref['start']:ref['start']+ref['length']]=value.to_bytes(ref['length'],'big')
            self.curve_codes[curve]='0x'+code.hex()
            launch=self._event(source['abi'],'TokenLaunched',dict(record,launchConfigId=0),
                address=factory,block=self.launch_blocks[curve],tx_index=0)
            self.logs.append(launch)
        curve_abi=template['abi']
        for index,relative in enumerate((178,180,190,191,192,190,191,200)):
            group='0x'+f'{20+(index if index<2 else index-2):040x}'
            quote=10**14 if index<2 else 10**15
            self.logs.append(self._event(curve_abi,'CurveBuy',dict(buyer=group,recipient=group,
                quoteIn=quote,tokensOut=10**20,fee=quote//100,tax=quote//200),
                address=self.current_curve,block=base+relative,tx_index=index+10,index=index+10))
        seller='0x'+f'{20:040x}'
        self.logs.append(self._event(curve_abi,'CurveSell',dict(seller=seller,recipient=seller,
            tokensIn=10**20,quoteOut=10**14,fee=10**12,tax=5*10**11),
            address=self.current_curve,block=base+197,tx_index=1,index=1))
        record=self.records[self.survivor_token]
        # Its launch is observed in the same enrollment block as graduation.
        # The separate transaction retains original causal order and lets the
        # native scout authenticate it without a pre-enrollment census.
        self.logs=[e for e in self.logs if not (e['address']==factory and
            e['topics'][1]=='0x'+self.survivor_token[2:].zfill(64))]
        self.launch_blocks[record['curve']]=self.current_block
        self.logs.append(self._event(source['abi'],'TokenLaunched',dict(record,launchConfigId=0),
            address=factory,block=self.current_block,tx_index=0))
        key=PoolKey(record['pairToken'],record['token'],record['poolFee'],record['tickSpacing'],hook['address'].lower())
        self.pool_id=key.pool_id()
        for role,name,values,index in (
            (manager,'Initialize',dict(id=self.pool_id,currency0=key.currency0,currency1=key.currency1,
                fee=key.fee,tickSpacing=key.tick_spacing,hooks=key.hook,sqrtPriceX96=1<<96,tick=0),0),
            (hook,'PoolRegistered',dict(poolId=self.pool_id,memecoin=record['token'],
                quoteToken=record['pairToken'],creator=record['creatorFeeRecipient']),1),
            (source,'PoolGraduated',dict(token=record['token'],positionId=1,
                tokenAmount=100000,pairTokenAmount=200000),2)):
            self.logs.append(self._event(role['abi'],name,values,address=role['address'],
                block=self.current_block,tx_index=1,index=index+1))
        self.logs.append(self._event(manager['abi'],'Swap',dict(id=self.pool_id,
            sender='0x'+f'{77:040x}',amount0=10**15,amount1=-10**15,
            sqrtPriceX96=(1<<96)*101//100,liquidity=10**18,tick=0,fee=3000),
            address=manager['address'],block=self.current_block+1,tx_index=0))
        self.logs.sort(key=lambda e:tuple(int(e[k],16) for k in ('blockNumber','transactionIndex','logIndex')))
        for event in self.logs:
            tx=event['transactionHash']
            if tx not in self.receipts:
                self.receipts[tx]=dict(transactionHash=tx,blockHash=event['blockHash'],
                    blockNumber=event['blockNumber'],transactionIndex=event['transactionIndex'],
                    status='0x1',gasUsed=hex(100000),logs=[],**{'from':'0x'+f'{77:040x}'})
            self.receipts[tx]['logs'].append(deepcopy(event))

    def header(self,number):
        if type(number) is not int or not 0<=number<=self.top:
            raise PonsKernelFixtureRefused('kernel_fixture_pons_block')
        return self._wire_header(number)

    def _wire_header(self,number):
        if type(number) is not int or not 0<=number<=self.maximum:
            raise PonsKernelFixtureRefused('kernel_fixture_pons_block')
        # The synthetic genesis has a nonempty, fixed identity. Parent links
        # agree for every subsequent block without borrowing a mainnet hash.
        return dict(number=hex(number),timestamp=hex(self.started_at+number-self.current_block),
            hash='0x'+f'{number+1:064x}',parentHash='0x'+f'{number:064x}')

    def publish(self,sequence):
        if type(sequence) is not int or not 1<=sequence<=128:
            raise PonsKernelFixtureRefused('kernel_fixture_nitro_sequence')
        number=self.current_block+(sequence-1)//2
        if number<self.top:raise PonsKernelFixtureRefused('kernel_fixture_nitro_regression')
        self.top=number
        self.last_sequence=max(sequence,self.last_sequence)
        return self.header(number)

    def next_frame(self):
        if self.last_sequence>=128:return None
        sequence=self.last_sequence+1
        return sequence,self.publish(sequence)

    def rpc(self,method,params):
        self.requests+=1
        self.methods[method]=self.methods.get(method,0)+1
        if method=='eth_chainId':return hex(4663)
        if method=='eth_blockNumber':return hex(self.top)
        if method=='eth_getCode' and params[0].lower() in self.codes:return self.codes[params[0].lower()]
        if method=='eth_getBlockByNumber':
            number=self.top if params[0] in ('latest','safe','finalized') else int(params[0],16)
            return self.header(number)
        if self.economic:return self._economic_read(method,params)
        if method=='eth_getLogs':return []
        self.refused+=1
        raise PonsKernelFixtureRefused('kernel_fixture_pons_method')

    def _economic_read(self,method,params):
        from meme_machine.lanes.pons.abi import calldata
        from meme_machine.lanes.pons.identity import metadata
        if method=='eth_getBlockByHash':
            number=int(params[0],16)-1
            value=self.header(number)
            if value['hash']!=params[0]:raise PonsKernelFixtureRefused('kernel_fixture_pons_hash')
            return value
        if method=='eth_getLogs':
            query=params[0];first,last=int(query['fromBlock'],16),int(query['toBlock'],16)
            if not 0<=first<=last<=self.top:raise PonsKernelFixtureRefused('kernel_fixture_pons_range')
            address=query.get('address')
            return deepcopy([e for e in self.logs if first<=int(e['blockNumber'],16)<=last
                and (address is None or e['address']==address.lower()) and all(
                    wanted is None or e['topics'][i] in (wanted if isinstance(wanted,list) else [wanted])
                    for i,wanted in enumerate(query.get('topics',[])))])
        if method in ('eth_getTransactionReceipt','eth_getTransactionByHash') and params[0] in self.receipts:
            value=deepcopy(self.receipts[params[0]])
            if method=='eth_getTransactionReceipt':return value
            return dict(hash=value['transactionHash'],blockHash=value['blockHash'],
                blockNumber=value['blockNumber'],transactionIndex=value['transactionIndex'],**{'from':value['from']})
        if method=='eth_getCode' and params[0].lower() in self.curve_codes:return self.curve_codes[params[0].lower()]
        if method=='eth_gasPrice':return hex(1000000)
        if method=='eth_call':
            target=params[0]['to'].lower();data=params[0]['data'];block=int(params[1],16)
            self.header(block)
            factory=metadata('pons_v2_factory')
            if target==factory['address'].lower() and data.startswith(calldata('getLaunchedToken(address)',0)[:10]):
                record=self.records.get('0x'+data[-40:])
                if record is not None:
                    fields=next(e for e in factory['abi'] if e.get('name')=='getLaunchedToken')['outputs'][0]['components']
                    return '0x'+''.join(self._word(int(record[f['name']],16) if isinstance(record[f['name']],str)
                        else record[f['name']]) for f in fields)
            record=next((r for r in self.records.values() if r['curve']==target),None)
            if record is not None:
                real=(68*10**16 if block<=self.current_block-15 else
                    74*10**16 if block<=self.current_block-5 else 8*10**17)
                values={calldata('token()'):int(record['token'],16),
                    calldata('realQuoteReserve()'):real,calldata('reservedTokens()'):100*10**24,
                    calldata('graduated()'):record['phase']==2,
                    calldata('launchedAt()'):int(self.header(self.launch_blocks[target])['timestamp'],16)}
                if data==calldata('getReserves()'):return '0x'+self._word(2*10**18)+self._word(800*10**24)
                if data.startswith(calldata('currentSnipeTaxBps(address)',0)[:10]):return '0x'+self._word(0)
                if data in values:return '0x'+self._word(values[data])
        self.refused+=1
        raise PonsKernelFixtureRefused('kernel_fixture_pons_method')

    async def open(self):
        raw=_NitroFixture(self)
        self.streams.append(raw)
        return raw

    def counters(self):
        return dict(synthetic_rpc_elements=self.requests,synthetic_nitro_messages=self.feed_messages,
            streams=len(self.streams),streams_closed=sum(row.closed for row in self.streams),
            economic_candidates='SYNTHETIC_WIRE_ONLY_UNTIL_NATIVE_OUTPUT_INSPECTION' if self.economic else 'UNEXERCISED',
            synthetic_economic_mode=self.economic,unmodeled_calls=self.refused,
            methods=dict(self.methods),synthetic_wire_events=len(self.logs))


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
        for _ in range(128):
            if self.stopped.is_set():return
            next_frame=self.corpus.next_frame()
            if next_frame is None:return
            _,header=next_frame
            # Native discovery uses the Nitro L2 sequence as its block cursor.
            # Each half-second pair repeats the same complete logical message;
            # the internal frame bound must never become a different block ID.
            value=dict(version=1,messages=[dict(sequenceNumber=int(header['number'],16),signatureV2='SYNTHETIC_NOT_A_SIGNATURE',
                message=dict(message=dict(header=dict(kind=3,sender='0x0',blockNumber=int(header['number'],16),
                    timestamp=int(header['timestamp'],16)),l2Msg='AA==')))])
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
