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
SLOTS = 4
SAMPLED_HEAD = 3
ADDITIONAL_CREATIONS = 110
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


def _blockhash(slot):
    from meme_machine import pump
    return pump.b58(hashlib.sha256(('isolated-kernel-block:'+str(slot)).encode()).digest())


def _replace(value,replacements):
    if type(value) is str:return replacements.get(value,value)
    if type(value) is list:return [_replace(item,replacements) for item in value]
    if type(value) is dict:return {key:_replace(item,replacements) for key,item in value.items()}
    return value


def _creation_offset(body):
    offset=8
    for _ in range(3):offset+=4+struct.unpack_from('<I',body,offset)[0]
    return offset


def _trade_body(original,*,at,mint,wallet,creator,tokens,amount,buy,reserves):
    from meme_machine import pump
    body=bytearray(original)
    body[8:40]=pump.un58(mint);body[57:89]=pump.un58(wallet);body[177:209]=pump.un58(creator)
    struct.pack_into('<QQ?',body,40,amount,tokens,buy)
    struct.pack_into('<qQQQQ',body,89,at,*reserves)
    struct.pack_into('<Q',body,161,100)
    struct.pack_into('<Q',body,169,amount//100)
    struct.pack_into('<Q',body,209,25)
    struct.pack_into('<Q',body,217,amount//400)
    return bytes(body)


class SolanaKernelCorpus:
    """Deterministic bounded synthetic ledger, given its explicit wall origin.

    Slots1..4 form one closed artificial chain. RPC samples finalized head3;
    the later native stream supplies its finalized linked child4. Only slots
    through3 can therefore earn native interval publication. These fixed
    captured observations never establish continuous freshness or mainnet data.
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
        original_create=template['pump'][0]
        original_creation=next(e for e in pump_events(original_create) if e['event_type']=='create')
        self.mint,self.curve=original_creation['mint'],original_creation['bonding_curve']

        def transaction(original,*,slot,index,label,replacements=None,trade=None):
            replacements={} if replacements is None else replacements
            tx=_replace(deepcopy(original),replacements)
            at=started_at+slot-SLOTS
            tx.update(slot=slot,transactionIndex=index,blockTime=at)
            signatures=tx['transaction']['message']['header']['numRequiredSignatures']
            tx['transaction']['signatures']=[_signature(label+':'+str(n)) for n in range(signatures)]
            tx['transaction']['message']['recentBlockhash']=_blockhash(slot-1)
            # Generic transaction balances from the recorded template are not
            # synthetic VM execution evidence. Do not retain contradictory
            # balances; original Pump consumers require logs/identity only.
            tx['meta']={key:tx['meta'][key] for key in ('err','logMessages','loadedAddresses')}
            logs = []
            for line in tx['meta']['logMessages']:
                if line.startswith('Program data: '):
                    body = bytearray(base64.b64decode(line[14:],validate=True))
                    for before,after in replacements.items():
                        body=bytearray(bytes(body).replace(pump.un58(before),pump.un58(after)))
                    if body[:8]==CREATE:
                        offset=_creation_offset(body)
                        struct.pack_into('<q',body,offset+128,at)
                    elif body[:8]==TRADE:
                        struct.pack_into('<q',body,89,at)
                        if trade is not None:body=bytearray(trade)
                    elif bytes(body[:8]) in SWAP:struct.pack_into('<q',body,8,at)
                    line='Program data: '+base64.b64encode(body).decode()
                logs.append(line)
            tx['meta']['logMessages']=logs
            return tx

        # A single eligible target has a fully represented create+buy followed
        # by a small buy. Its account scout is the exact last post-trade state.
        creation=original_creation
        vt,vq,rt=(creation['initial_virtual_token_reserves'],creation['initial_virtual_quote_reserves'],
            creation['initial_real_token_reserves'])
        invariant=vt*vq;seed_tokens=500_000_000_000_000
        seeded_vt=vt-seed_tokens;seeded_vq=(invariant+seeded_vt-1)//seeded_vt
        trade_template=next(base64.b64decode(line[14:]) for line in original_create['meta']['logMessages']
            if line.startswith('Program data: ') and base64.b64decode(line[14:])[:8]==TRADE)
        seed=_trade_body(trade_template,at=started_at-2,mint=self.mint,wallet=creation['wallet'],
            creator=creation['creator'],tokens=seed_tokens,amount=seeded_vq-vq,buy=True,
            reserves=(seeded_vq,seeded_vt,seeded_vq-vq,rt-seed_tokens))
        target=transaction(original_create,slot=2,index=0,label='target-create',trade=seed)
        # Keep the real instruction's discriminator/optional ABI suffix; change
        # its exact token/max-cost arguments with the represented synthetic buy.
        buy_instruction=next(row for row in target['transaction']['message']['instructions']
            if based58.b58decode(row['data'].encode())[:8]==hashlib.sha256(b'global:buy_v2').digest()[:8])
        encoded=bytearray(based58.b58decode(buy_instruction['data'].encode()))
        seed_amount=seeded_vq-vq
        struct.pack_into('<QQ',encoded,8,seed_tokens,seed_amount+seed_amount//100+seed_amount//400)
        buy_instruction['data']=based58.b58encode(bytes(encoded)).decode()
        self._transactions.append(target)
        final_tokens=1_000_000_000;final_vt=seeded_vt-final_tokens
        final_vq=(invariant+final_vt-1)//final_vt
        final=_trade_body(trade_template,at=started_at-1,mint=self.mint,wallet=creation['wallet'],
            creator=creation['creator'],tokens=final_tokens,amount=final_vq-seeded_vq,buy=True,
            reserves=(final_vq,final_vt,final_vq-vq,rt-seed_tokens-final_tokens))
        trade_tx=transaction(original_create,slot=3,index=0,label='target-trade')
        trade_tx['meta']['logMessages']=['Program '+pump.PROGRAM+' invoke [1]',
            'Program data: '+base64.b64encode(final).decode(),'Program '+pump.PROGRAM+' success']
        trade_tx['transaction']['message']['instructions']=[deepcopy(buy_instruction)]
        encoded=bytearray(based58.b58decode(buy_instruction['data'].encode()))
        final_amount=final_vq-seeded_vq
        struct.pack_into('<QQ',encoded,8,final_tokens,final_amount+final_amount//100+final_amount//400)
        trade_tx['transaction']['message']['instructions'][0]['data']=based58.b58encode(bytes(encoded)).decode()
        self._transactions.append(trade_tx)
        for index in range(1,ADDITIONAL_CREATIONS+1):
            attempt=0
            while True:
                raw=hashlib.sha256(('isolated-kernel-mint:'+str(index)+':'+str(attempt)).encode()).digest()
                if pump.on_curve(raw):break
                attempt+=1
            mint=pump.b58(raw);curve=pump.pda([b'bonding-curve',raw],pump.PROGRAM)
            self._transactions.append(transaction(original_create,slot=3,index=index,
                label='creation:'+str(index),replacements={self.mint:mint,self.curve:curve}))
        swap=transaction(template['pumpswap'][0],slot=3,index=ADDITIONAL_CREATIONS+1,label='pumpswap')
        self._transactions.append(swap)
        self.pool=next(iter(pumpswap_trade_events(swap)))['pool']
        # These actual failed ledger entries, rather than invented frontier
        # notifications, supply both programs' first WS slot. They have native
        # failed statuses and count in slot1's full header census; no economics.
        from meme_machine.solana_selective_history import PROGRAMS
        for index,(family,addresses) in enumerate((('pump',[self.mint,self.curve]),('pumpswap',[self.pool]))):
            self._transactions.append(dict(slot=1,transactionIndex=index,blockTime=started_at-3,
                version='legacy',transaction=dict(signatures=[_signature('failed-prefix:'+family)],
                    message=dict(header=dict(numRequiredSignatures=1,numReadonlySignedAccounts=0,
                        numReadonlyUnsignedAccounts=1),accountKeys=[creation['wallet'],*addresses,PROGRAMS[family]],
                        instructions=[],recentBlockhash=_blockhash(0))),
                meta=dict(err='AccountNotFound',logMessages=[],loadedAddresses=dict(writable=[],readonly=[]))))
        self._transactions.sort(key=lambda tx:(tx['slot'],tx['transactionIndex']))
        self._scout=next(e for e in pump_events(trade_tx) if e['event_type']=='trade')
        self._scout_signature=trade_tx['transaction']['signatures'][0]
        self._creation=creation
        self._members=[]
        for tx in self._transactions:
            keys=tx['transaction']['message']['accountKeys']
            normalized={k['pubkey'] if type(k) is dict else k for k in keys}
            loaded=tx['meta'].get('loadedAddresses') or {}
            normalized.update(loaded.get('writable',()));normalized.update(loaded.get('readonly',()))
            self._members.append(normalized)
        self.corpus_sha256=hashlib.sha256(_json(dict(schema='kernel-solana-v2',scope=SCOPE,
            started_at=started_at,sampled_head=SAMPLED_HEAD,linked_child=SLOTS,
            transactions=self._transactions))).hexdigest()

    def snapshot(self):
        with self._lock:
            return dict(schema='isolated-kernel-solana-corpus-v2',scope=SCOPE,
                template_sha256=TEMPLATE_SHA256,corpus_sha256=self.corpus_sha256,
                started_at=self.started_at,synthetic_finalized_head=SAMPLED_HEAD,
                wire_expected=dict(transactions=ADDITIONAL_CREATIONS+5,
                    failed_transactions=2,economic_transactions=ADDITIONAL_CREATIONS+3,
                    economic_records=2*ADDITIONAL_CREATIONS+4,slot_first=BASE_SLOT,
                    sampled_head=SAMPLED_HEAD,linked_child=SLOTS,
                    target_mint=self.mint,target_curve=self.curve,target_pool=self.pool),
                counters=dict(self._counts),rpc_methods=dict(self._rpc_counts),
                financial_authority=False,provider_calls=0,canonical_coverage=False,
                rpc_projection='NATIVE_PUMP_IDENTITY_LOG_FIELDS_ONLY_NOT_VM_EXECUTION',
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
        head=SAMPLED_HEAD
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
                and options.get('sortOrder')=='asc' and options.get('limit')==100)
            bounds=options['filters']['slot'];lower,upper=bounds['gte'],bounds['lte']
            _require(type(lower) is int and type(upper) is int and 0<=lower<=upper<=head)
            rows=[tx for tx in self._selected(address) if lower<=tx['slot']<=upper]
            token='kernel-v2:'+hashlib.sha256(_json([address,lower,upper,100])).hexdigest()
            supplied=options.get('paginationToken')
            _require(supplied is None or (len(rows)>100 and supplied==token))
            offset=0 if supplied is None else 100
            return dict(data=deepcopy(rows[offset:offset+100]),
                paginationToken=token if offset==0 and len(rows)>100 else None)
        if method=='getTransaction':
            _require(len(params)==2 and type(params[0]) is str and type(params[1]) is dict
                and params[1].get('commitment')=='finalized'
                and params[1].get('maxSupportedTransactionVersion')==1)
            return deepcopy(next((tx for tx in self._transactions
                if tx['transaction']['signatures'][0]==params[0]),None))
        _require(len(params)==2 and type(params[0]) is int and type(params[1]) is dict
            and params[1].get('commitment')=='finalized'
            and params[1].get('maxSupportedTransactionVersion')==1 and 1<=params[0]<=SLOTS)
        slot=params[0]
        return dict(parentSlot=slot-1,blockhash=_blockhash(slot),previousBlockhash=_blockhash(slot-1),
            blockTime=self.started_at+slot-SLOTS,
            transactions=[deepcopy(tx) for tx in self._transactions if tx['slot']==slot])

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
            creation=self._creation;scout=self._scout;data=bytearray(49)
            data[:8]=hashlib.sha256(b'account:BondingCurve').digest()[:8]
            for offset,key in ((8,'virtual_token_reserves'),(16,'virtual_quote_reserves'),(24,'real_token_reserves')):
                struct.pack_into('<Q',data,offset,scout[key])
            struct.pack_into('<Q',data,32,scout['real_quote_reserves'])
            struct.pack_into('<Q',data,40,creation['token_total_supply'])
            update=pb.SubscribeUpdate(filters=['p']);item=update.account
            item.slot=SAMPLED_HEAD;item.is_startup=False
            item.account.pubkey=pump.un58(self.curve);item.account.owner=pump.un58(pump.PROGRAM)
            item.account.txn_signature=based58.b58decode(self._scout_signature.encode())
            item.account.data=bytes(data)
            return [update.SerializeToString()]
        _require(set(request.blocks_meta)=={'b'} and set(request.slots)=={'f'})
        labels={name:set(row.account_include) for name,row in request.transactions_status.items()}
        _require(len(labels)<=8)
        frames=[]
        for slot in range(max(BASE_SLOT,request.from_slot),SLOTS+1):
            for tx,keys in zip(self._transactions,self._members):
                matches=[label for label,addresses in labels.items() if addresses.intersection(keys)]
                if tx['slot']!=slot or not matches:continue
                update=pb.SubscribeUpdate(filters=matches);item=update.transaction_status
                item.slot=slot;item.index=tx['transactionIndex'];item.signature=based58.b58decode(tx['transaction']['signatures'][0].encode())
                if tx['meta']['err'] is not None:
                    from meme_machine.solana_native_evidence import TRANSACTION_ERRORS
                    item.err.err=struct.pack('<I',TRANSACTION_ERRORS.index(tx['meta']['err']))
                frames.append(update.SerializeToString())
            update=pb.SubscribeUpdate(filters=['b']);meta=update.block_meta
            meta.slot=slot;meta.parent_slot=slot-1;meta.blockhash=_blockhash(slot);meta.parent_blockhash=_blockhash(slot-1)
            meta.block_time.timestamp=self.started_at+slot-SLOTS
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
        result=[_json(dict(jsonrpc='2.0',id=request['id'],result=subscription))]
        result.extend(notification(tx['slot'],tx['transaction']['signatures'][0],tx['meta']['logMessages'],tx['meta']['err'])
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
