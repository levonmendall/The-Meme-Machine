"""Fixed synthetic Solana wire inputs for an explicit offline kernel rehearsal.

Only provider-shaped bytes/results are supplied. This module has no SQLite,
consumer, acknowledgement, provider connection or financial capability. Native
code must produce every decoded row, FULL publication and ACK itself. Nothing
here establishes mainnet coverage or processing capacity.
"""
import asyncio
import base64
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import threading

import based58


SCOPE = 'SYNTHETIC_KERNEL_LIFECYCLE_ONLY_NOT_MAINNET_OR_MARKET_CAPACITY'
TEMPLATE_SHA256 = 'be2aebae5e3955dfd8c73cabbf74ede5a7e4890db336ea5aa83c13be4f7cc1f0'
BASE_SLOT = 1
SLOTS = 16
MAX_STREAMS = 32
MAX_REQUESTS = 512
MAX_QUEUED = 128
CREATE = bytes((27,114,169,77,222,235,99,118))
TRADE = bytes((189,219,127,211,78,230,97,238))
SWAP = (bytes((103,244,82,31,44,245,119,119)), bytes((62,47,55,10,165,3,220,42)))


def _require(condition):
    if not condition: raise ValueError('isolated_kernel_solana_corpus_contract')


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _signature(label):
    from meme_machine import pump
    return pump.b58(hashlib.sha512(('isolated-kernel:'+label).encode()).digest())


class SolanaKernelCorpus:
    """Deterministic bounded synthetic ledger, given its explicit wall origin.

    Slots1..16 contain only the three listed fixture transactions; this closed
    artificial world is not a statement about any mainnet slot or account.
    Unknown accounts/methods fail rather than inventing real account evidence.
    Streams park after their fixed bytes until their owner closes them.
    """
    def __init__(self,started_at):
        _require(type(started_at) is int and 0 < started_at < 2**63)
        self.started_at = started_at
        self._lock = threading.Lock()
        self._counts = dict(opened=0,closed=0,wire_reads=0,wire_bytes=0,subscription_writes=0,
            rpc_calls=0,unmodeled_calls=0)
        self._streams = set()
        self._rpc_counts = {}
        with Path(__file__).with_name('isolated_native_kernel_solana.json').open('rb') as stream:
            raw = stream.read(65537)
        _require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==TEMPLATE_SHA256)
        template = json.loads(raw)
        _require(template['scope']==SCOPE and len(template['pump'])==2 and len(template['pumpswap'])==1)
        self._transactions = []
        from meme_machine import pump
        from meme_machine.solana_program_decoders import pump_events,pumpswap_trade_events
        for index,original in enumerate((*template['pump'],*template['pumpswap']),1):
            tx = deepcopy(original)
            tx.update(slot=BASE_SLOT+index,transactionIndex=0,blockTime=started_at)
            tx['transaction']['signatures'] = [_signature(str(index))]
            logs = []
            for line in tx['meta']['logMessages']:
                if line.startswith('Program data: '):
                    body = bytearray(base64.b64decode(line[14:],validate=True))
                    if body[:8]==CREATE:
                        offset=8
                        for _ in range(3): offset+=4+struct.unpack_from('<I',body,offset)[0]
                        struct.pack_into('<q',body,offset+128,started_at)
                    elif body[:8]==TRADE: struct.pack_into('<q',body,89,started_at)
                    elif bytes(body[:8]) in SWAP: struct.pack_into('<q',body,8,started_at)
                    line='Program data: '+base64.b64encode(body).decode()
                logs.append(line)
            tx['meta']['logMessages']=logs
            self._transactions.append(tx)
        creation=next(e for e in pump_events(self._transactions[0]) if e['event_type']=='create')
        _require(any(e['event_type']=='trade' for e in pump_events(self._transactions[1])))
        swap=next(iter(pumpswap_trade_events(self._transactions[2])))
        self.mint,self.curve,self.pool=creation['mint'],creation['bonding_curve'],swap['pool']
        self._creation=creation
        self._members=[]
        for tx in self._transactions:
            keys=tx['transaction']['message']['accountKeys']
            normalized={k['pubkey'] if type(k) is dict else k for k in keys}
            loaded=tx['meta'].get('loadedAddresses') or {}
            normalized.update(loaded.get('writable',()));normalized.update(loaded.get('readonly',()))
            self._members.append(normalized)
        self.corpus_sha256=hashlib.sha256(_json(dict(scope=SCOPE,started_at=started_at,
            slots=[1,BASE_SLOT+SLOTS-1],transactions=self._transactions))).hexdigest()

    def snapshot(self):
        with self._lock:
            return dict(schema='isolated-kernel-solana-corpus-v1',scope=SCOPE,
                template_sha256=TEMPLATE_SHA256,corpus_sha256=self.corpus_sha256,
                started_at=self.started_at,synthetic_finalized_head=BASE_SLOT+SLOTS-1,
                counters=dict(self._counts),rpc_methods=dict(self._rpc_counts),
                financial_authority=False,provider_calls=0,canonical_coverage=False,
                source_economics='UNVERIFIED_UNTIL_NATIVE_OUTPUT_INSPECTION',
                durable_publication='UNVERIFIED',consumer_acks='UNVERIFIED',
                control='WIRE_INPUT_ONLY',scout='WIRE_INPUT_ONLY',rolling='WIRE_INPUT_ONLY',
                candidate='UNEXERCISED_UNTIL_NATIVE_OUTPUT_INSPECTION',history='UNVERIFIED',
                production_equivalent=False,full_market_speed_proven=False)

    def _selected(self,address):
        return [tx for tx,keys in zip(self._transactions,self._members) if address in keys]

    def rpc(self,method,params):
        from meme_machine.solana_provider_config import GENESIS
        _require(type(method) is str and type(params) is list)
        with self._lock:
            self._counts['rpc_calls']+=1
            _require(self._counts['rpc_calls']<=MAX_REQUESTS)
            if method in ('getGenesisHash','getSlot','getTransactionsForAddress','getTransaction','getBlock'):
                self._rpc_counts[method]=self._rpc_counts.get(method,0)+1
            else:
                self._counts['unmodeled_calls']+=1
                raise ValueError('isolated_kernel_solana_unmodeled_rpc')
        head=BASE_SLOT+SLOTS-1
        if method=='getGenesisHash':
            _require(params==[]);return GENESIS
        if method=='getSlot':
            _require(params==[dict(commitment='finalized')]);return head
        if method=='getTransactionsForAddress':
            _require(len(params)==2 and type(params[0]) is str and type(params[1]) is dict)
            address,options=params
            from meme_machine.solana_selective_history import PROGRAMS
            _require(address in {self.mint,self.curve,self.pool,PROGRAMS['pump'],PROGRAMS['pumpswap']})
            _require(options.get('commitment')=='finalized' and options.get('maxSupportedTransactionVersion')==1
                and options.get('paginationToken') is None and options.get('sortOrder')=='asc')
            bounds=options['filters']['slot'];lower,upper=bounds['gte'],bounds['lte']
            _require(type(lower) is int and type(upper) is int and 0<=lower<=upper<=head)
            rows=[tx for tx in self._selected(address) if lower<=tx['slot']<=upper]
            return dict(data=deepcopy(rows),paginationToken=None)
        if method=='getTransaction':
            _require(len(params)==2 and type(params[0]) is str and type(params[1]) is dict
                and params[1].get('commitment')=='finalized'
                and params[1].get('maxSupportedTransactionVersion')==1)
            return deepcopy(next((tx for tx in self._transactions
                if tx['transaction']['signatures'][0]==params[0]),None))
        _require(len(params)==2 and type(params[0]) is int and type(params[1]) is dict
            and params[1].get('commitment')=='finalized'
            and params[1].get('maxSupportedTransactionVersion')==1 and 1<=params[0]<=head)
        slot=params[0]
        return dict(parentSlot=slot-1,blockhash=str(slot),previousBlockhash=str(slot-1),
            blockTime=self.started_at,transactions=[deepcopy(tx) for tx in self._transactions if tx['slot']==slot])

    async def open(self,transport):
        _require(transport in ('yellowstone','solana_websocket'))
        with self._lock:
            _require(len(self._streams)<MAX_STREAMS and self._counts['opened']<MAX_STREAMS)
            raw=_Raw(self,transport)
            self._streams.add(raw);self._counts['opened']+=1
            return raw

    def _yellowstone(self,body):
        from meme_machine import pump
        from meme_machine.yellowstone import geyser_pb2 as pb
        request=pb.SubscribeRequest.FromString(body)
        _require(request.commitment==pb.FINALIZED and not request.blocks and not request.transactions)
        if request.accounts:
            _require(set(request.accounts)=={'p'} and list(request.accounts['p'].owner)==[pump.PROGRAM])
            creation=self._creation;data=bytearray(49)
            data[:8]=hashlib.sha256(b'account:BondingCurve').digest()[:8]
            for offset,key in ((8,'initial_virtual_token_reserves'),(16,'initial_virtual_quote_reserves'),
                (24,'initial_real_token_reserves'),(40,'token_total_supply')):
                struct.pack_into('<Q',data,offset,creation[key])
            update=pb.SubscribeUpdate(filters=['p']);item=update.account
            item.slot=BASE_SLOT+1;item.is_startup=False
            item.account.pubkey=pump.un58(self.curve);item.account.owner=pump.un58(pump.PROGRAM)
            item.account.txn_signature=based58.b58decode(self._transactions[0]['transaction']['signatures'][0].encode())
            item.account.data=bytes(data)
            return [update.SerializeToString()]
        _require(set(request.blocks_meta)=={'b'} and set(request.slots)=={'f'})
        labels={name:set(row.account_include) for name,row in request.transactions_status.items()}
        _require(len(labels)<=8)
        frames=[]
        for slot in range(max(BASE_SLOT,request.from_slot),BASE_SLOT+SLOTS):
            for tx,keys in zip(self._transactions,self._members):
                matches=[label for label,addresses in labels.items() if addresses.intersection(keys)]
                if tx['slot']!=slot or not matches:continue
                update=pb.SubscribeUpdate(filters=matches);item=update.transaction_status
                item.slot=slot;item.index=0;item.signature=based58.b58decode(tx['transaction']['signatures'][0].encode())
                frames.append(update.SerializeToString())
            update=pb.SubscribeUpdate(filters=['b']);meta=update.block_meta
            meta.slot=slot;meta.parent_slot=slot-1;meta.blockhash=str(slot);meta.parent_blockhash=str(slot-1)
            meta.block_time.timestamp=self.started_at
            meta.executed_transaction_count=sum(tx['slot']==slot for tx in self._transactions)
            frames.append(update.SerializeToString())
            update=pb.SubscribeUpdate(filters=['f']);update.slot.slot=slot;update.slot.parent=slot-1
            update.slot.status=pb.SLOT_FINALIZED;frames.append(update.SerializeToString())
        _require(len(frames)<=MAX_QUEUED)
        return frames

    def _websocket(self,body):
        request=json.loads(body)
        _require(type(request) is dict and request.get('method')=='logsSubscribe'
            and type(request.get('id')) is int and request['params'][1]==dict(commitment='finalized'))
        addresses=request['params'][0]['mentions'];_require(type(addresses) is list and len(addresses)==1)
        address=addresses[0]
        from meme_machine.solana_selective_history import PROGRAMS
        _require(address in {self.mint,self.curve,self.pool,PROGRAMS['pump'],PROGRAMS['pumpswap']})
        subscription=request['id']+100
        def notification(slot,signature,logs,error):
            return _json(dict(jsonrpc='2.0',method='logsNotification',params=dict(subscription=subscription,
                result=dict(context=dict(slot=slot),value=dict(signature=signature,logs=logs,err=error)))))
        result=[_json(dict(jsonrpc='2.0',id=request['id'],result=subscription)),
            notification(BASE_SLOT,_signature('prefix:'+address),[],dict(InstructionError=[0,0]))]
        result.extend(notification(tx['slot'],tx['transaction']['signatures'][0],tx['meta']['logMessages'],None)
            for tx in self._selected(address))
        return result


class _Raw:
    """No background tasks; the original parent owns every read and cancellation."""
    def __init__(self,corpus,transport):
        self.corpus,self.transport=corpus,transport
        self.closed=False;self._queue=deque();self._available=asyncio.Event();self._writes=0

    async def write(self,body):
        _require(not self.closed and type(body) is bytes and 0<len(body)<=4*1024*1024)
        _require(self._writes<(1 if self.transport=='yellowstone' else 8))
        frames=self.corpus._yellowstone(body) if self.transport=='yellowstone' else self.corpus._websocket(body)
        _require(len(self._queue)+len(frames)<=MAX_QUEUED)
        self._writes+=1;self._queue.extend(frames);self._available.set()
        with self.corpus._lock:self.corpus._counts['subscription_writes']+=1

    async def read(self):
        import grpc
        while not self.closed and not self._queue:
            await self._available.wait();self._available.clear()
        if self.closed:return grpc.aio.EOF
        body=self._queue.popleft()
        with self.corpus._lock:
            self.corpus._counts['wire_reads']+=1;self.corpus._counts['wire_bytes']+=len(body)
        return len(body),body

    def cancel(self):
        if self.closed:return
        self.closed=True;self._queue.clear();self._available.set()
        with self.corpus._lock:
            self.corpus._counts['closed']+=1;self.corpus._streams.discard(self)

    async def aclose(self):self.cancel()
