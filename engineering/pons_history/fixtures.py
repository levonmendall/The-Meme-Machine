"""Deterministic authentic-shaped tape, with explicitly synthetic missing fields.

The primary graduation/registration/initialization and factory record come from
the preserved run 35378762520 fixture. Headers, launches, receipts, additional
candidates and swaps below are fabricated *offline test inputs*, never a seed.
"""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from meme_machine.lanes.pons import BoundaryError, CHAIN_ID
from meme_machine.lanes.pons.abi import signature, topic, calldata
from meme_machine.lanes.pons.identity import load
from meme_machine.lanes.pons.pons import factory_record, TEMPLATE
from meme_machine.lanes.pons.protocols import PoolKey
from meme_machine.lanes.pons.pons_historical import FACTORY, LAUNCH, GRADUATION, MANAGER, SWAP

CAPTURE = Path(__file__).resolve().parents[2] / 'tests/lanes/pons/fixtures/pons_lineage_35378762520.json'

@lru_cache(maxsize=8)
def pin(role):
    return load(role)


def checksum(value):
    return '0x' + hashlib.sha256(str(value).encode()).hexdigest()


def encoded_event(role, name, values, *, block, block_hash, tx, index=0, tx_index=0):
    spec = next(x for x in pin(role)['abi'] if x.get('type') == 'event' and x['name'] == name)
    topics = [topic(signature(spec))]
    data = []
    for field in spec['inputs']:
        value = values.get(field['name'], 0)
        value = int(value, 16) if isinstance(value, str) else int(value)
        word = f'{value % (1 << 256):064x}'
        (topics if field['indexed'] else data).append('0x' + word if field['indexed'] else word)
    return dict(address=pin(role)['address'].lower(), topics=topics, data='0x' + ''.join(data),
        blockNumber=hex(block), blockHash=block_hash, transactionHash=tx,
        transactionIndex=hex(tx_index), logIndex=hex(index), removed=False)


def encoded_record(record):
    fields = next(x for x in load('pons_v2_factory')['abi'] if x.get('name') == 'getLaunchedToken')['outputs'][0]['components']
    return '0x' + ''.join(f'{(int(record[f["name"]],16) if isinstance(record[f["name"]],str) else int(record[f["name"]])) % (1<<256):064x}' for f in fields)


def curve_code(record):
    template = json.loads(TEMPLATE.read_text())
    code = bytearray.fromhex(template['runtime']['object'])
    for ident, refs in template['runtime']['immutableReferences'].items():
        name = template['immutable_names'][ident]
        value = FACTORY if name == 'factory' else record.get(name, 0)
        value = int(value, 16) if isinstance(value, str) else int(value)
        for ref in refs:
            code[ref['start']:ref['start'] + ref['length']] = value.to_bytes(ref['length'], 'big')
    return '0x' + code.hex()


class Tape:
    canonical_authority = True
    chain_verified = True
    provider_fingerprint = 'offline-pons-tape'
    limit = 200

    def __init__(self, *, candidates=2, max_range=None):
        capture = json.loads(CAPTURE.read_text())['v2']
        self.grad = int(capture['graduation']['blockNumber'], 16)
        self.first = self.grad - 28
        self.top = self.grad + 140
        self.start_at = 1790800000
        self.forks = {}
        self.original_grad_hash = capture['graduation']['blockHash']
        self.logs = []
        self.records = {}
        self.launch_blocks = {}
        self.senders = {}
        self.tokens = []
        self.max_range = max_range
        self.error = None
        self.missing_block = None
        self.saturated = False
        self.paginated = False
        self.duplicates = False
        self.silent_truncation = False
        self.physical = self.logical = self.batches = 0
        self.used = 0
        self.methods = Counter()
        self.failures = Counter()
        self.request_bytes = self.response_bytes = 0
        self.request_log = []
        for i in range(candidates):
            record = factory_record(capture['factory_record_raw'])
            if i:
                record['token'] = f'0x{int(record["token"],16)+i:040x}'
                record['curve'] = f'0x{int(record["curve"],16)+i:040x}'
            token = record['token']
            self.tokens.append(token)
            self.records[token] = record
            block = self.grad + i
            launch_block = block - 10
            self.launch_blocks[token] = launch_block
            self.logs.append(encoded_event('pons_v2_factory', 'TokenLaunched', dict(record, launchConfigId=0),
                block=launch_block, block_hash=self.header(launch_block)['hash'], tx=checksum('launch' + token)))
            if i == 0:
                for k in ('initialization', 'registration', 'graduation'):
                    self.logs.append(deepcopy(capture[k]))
                key = PoolKey('0x'+'0'*40, token, record['poolFee'], record['tickSpacing'], load('pons_v2_hook')['address'].lower())
            else:
                key = PoolKey(*sorted((record['token'], record['pairToken']), key=lambda x:int(x,16)),
                              record['poolFee'], record['tickSpacing'], load('pons_v2_hook')['address'].lower())
                tx = checksum('graduation' + token)
                self.logs.extend([
                    encoded_event('uniswap_v4_manager', 'Initialize', dict(id=key.pool_id(), currency0=key.currency0,
                        currency1=key.currency1, fee=key.fee, tickSpacing=key.tick_spacing, hooks=key.hook,
                        sqrtPriceX96=1<<96, tick=0), block=block, block_hash=self.header(block)['hash'], tx=tx, index=0),
                    encoded_event('pons_v2_hook', 'PoolRegistered', dict(poolId=key.pool_id(), memecoin=token,
                        quoteToken=record['pairToken'], creator=record['creatorFeeRecipient']),
                        block=block, block_hash=self.header(block)['hash'], tx=tx, index=1),
                    encoded_event('pons_v2_factory', 'PoolGraduated', dict(token=token, positionId=2103714+i,
                        tokenAmount=100000, pairTokenAmount=200000), block=block, block_hash=self.header(block)['hash'], tx=tx, index=2),
                ])
            for b in range(block + 1, self.top + 1):
                tx = checksum('swap' + token + str(b))
                self.senders[tx] = f'0x{1+b%8:040x}'
                self.logs.append(encoded_event('uniswap_v4_manager', 'Swap', dict(id=key.pool_id(), sender=self.senders[tx],
                    amount0=10000 if b%3 else -7000, amount1=-10000 if b%3 else 7000,
                    sqrtPriceX96=(1<<96)*(100+b%17)//100, liquidity=1000000, tick=0, fee=record['poolFee']),
                    block=b, block_hash=self.header(b)['hash'], tx=tx, tx_index=i+4))
            tx = checksum('liquidity' + token)
            self.senders[tx] = f'0x{99:040x}'
            self.logs.append(encoded_event('uniswap_v4_manager', 'ModifyLiquidity', dict(id=key.pool_id(), sender=self.senders[tx],
                tickLower=-100, tickUpper=100, liquidityDelta=200000, salt=0), block=self.top,
                block_hash=self.header(self.top)['hash'], tx=tx, index=1, tx_index=i+100))

    def provider(self):
        # Production callers rotate ordinary bounded sessions, never raise limits.
        self.used = 0
        return self

    def header(self, n):
        fork = max((v for b, v in self.forks.items() if n >= b), default=0)
        def block_hash(b):
            version = max((v for start, v in self.forks.items() if b >= start), default=0)
            return self.original_grad_hash if b == self.grad and version == 0 else checksum((b, version))
        at = self.start_at + (n-self.first)*3600 if n >= self.first else self.start_at-max(1,(self.first-n+9)//10)
        return dict(number=hex(n), hash=block_hash(n), parentHash=block_hash(n-1), timestamp=hex(at))

    def receipt_value(self, tx):
        logs = [deepcopy(e) for e in self.logs if e['transactionHash'] == tx]
        if not logs:
            raise BoundaryError('provider_missing_result')
        e = logs[0]
        return dict(transactionHash=tx, blockHash=e['blockHash'], blockNumber=e['blockNumber'],
                    transactionIndex=e['transactionIndex'], status='0x1', gasUsed='0x493e0', logs=logs)

    def _read(self, method, params):
        self.request_log.append((method, deepcopy(params)))
        if self.error:
            error, self.error = self.error, None
            raise BoundaryError(error)
        if method == 'eth_chainId':
            return hex(CHAIN_ID)
        if method == 'eth_getBlockByNumber':
            n = self.top if params[0] == 'latest' else int(params[0],16)
            if n == self.missing_block:
                return None
            return self.header(n)
        if method == 'eth_getBlockByHash':
            for n in range(self.first - 100, self.top + 1):
                if self.header(n)['hash'] == params[0]:
                    return self.header(n)
            raise BoundaryError('provider_missing_result')
        if method == 'eth_getCode':
            for token, record in self.records.items():
                if params[0].lower() == record['curve']:
                    return curve_code(record)
            for role in ('pons_v2_factory', 'pons_deployer', 'pons_v2_hook', 'uniswap_v4_manager'):
                pin = load(role)
                if params[0].lower() == pin['address'].lower():
                    return pin['runtimeBytecode']['onchainBytecode']
            raise AssertionError(params)
        if method == 'eth_call':
            if params[0]['data'].startswith(calldata('getLaunchedToken(address)', int(self.tokens[0],16))[:10]):
                return encoded_record(self.records['0x' + params[0]['data'][-40:]])
            if params[0]['data'] == calldata('launchedAt()'):
                token = next(t for t,r in self.records.items() if r['curve'] == params[0]['to'])
                return '0x' + f'{int(self.header(self.launch_blocks[token])["timestamp"],16):064x}'
            raise AssertionError(params)
        if method == 'eth_getLogs':
            q = params[0]
            first, last = int(q['fromBlock'],16), int(q['toBlock'],16)
            if self.max_range and last - first + 1 > self.max_range:
                raise BoundaryError('provider_log_block_range_limit')
            rows = []
            for e in self.logs:
                if e['address'].lower() != q['address'].lower() or not first <= int(e['blockNumber'],16) <= last:
                    continue
                if all(wanted is None or e['topics'][i] in (wanted if isinstance(wanted,list) else [wanted]) for i,wanted in enumerate(q.get('topics',[]))):
                    rows.append(deepcopy(e))
            if self.paginated:
                return dict(logs=rows[:1], next='unsupported-page')
            if self.saturated and rows:
                rows = rows * 1024
            if self.duplicates:
                rows += deepcopy(rows)
            if self.silent_truncation and last-first+1 > 10:
                rows = rows[:1]
            return rows
        if method == 'eth_getTransactionReceipt':
            return self.receipt_value(params[0])
        if method == 'eth_getTransactionByHash':
            r = self.receipt_value(params[0])
            return dict(hash=params[0], blockHash=r['blockHash'], blockNumber=r['blockNumber'],
                        transactionIndex=r['transactionIndex'], **{'from':self.senders.get(params[0], '0x'+'01'*20)})
        raise AssertionError(method)

    def batch(self, calls, *, scope):
        self.physical += 1
        self.batches += 1
        self.logical += len(calls)
        self.used += len(calls)
        self.methods.update(m for m,_ in calls)
        self.request_bytes += len(json.dumps([dict(jsonrpc='2.0', id=i+1, method=m, params=p) for i,(m,p) in enumerate(calls)]).encode())
        try:
            result = [self._read(m,p) for m,p in calls]
            self.response_bytes += len(json.dumps([dict(jsonrpc='2.0', id=i+1, result=r) for i,r in enumerate(result)]).encode())
            return result
        except BoundaryError as exc:
            self.failures[str(exc)] += 1
            raise

    def call(self, method, params, *, scope='connectivity'):
        return self.batch([(method,params)], scope=scope)[0]

    def receipt(self, tx, block_hash, *, scope):
        r = self.call('eth_getTransactionReceipt', [tx], scope=scope)
        if r['blockHash'] != block_hash:
            raise BoundaryError('receipt_block_disagreement')
        return r

    def telemetry(self):
        return dict(logical_requests=self.logical, requests=self.logical,
                    physical_http_requests=self.physical, transport_requests=self.batches,
                    request_bytes=self.request_bytes,response_bytes=self.response_bytes,
                    methods=dict(self.methods), failures=dict(self.failures))

    def shared_activity(self, first, last, pool_ids):
        logs = [deepcopy(e) for e in self.logs if e['address'] == MANAGER and e['topics'][0] == SWAP
                and e['topics'][1] in pool_ids and first <= int(e['blockNumber'],16) <= last]
        return dict(raw=logs, headers={e['blockHash']:self.header(int(e['blockNumber'],16)) for e in logs},
            receipts={(e['transactionHash'],e['blockHash']):self.receipt_value(e['transactionHash']) for e in logs},
            txs={(e['transactionHash'],e['blockHash']):dict(hash=e['transactionHash'],blockHash=e['blockHash'],
                **{'from':self.senders[e['transactionHash']]}) for e in logs}, sessions=[])

    def reorg(self, first):
        self.forks[first] = max(self.forks.values(), default=0) + 1
        for e in self.logs:
            block = int(e['blockNumber'],16)
            if block >= first:
                e['blockHash'] = self.header(block)['hash']
