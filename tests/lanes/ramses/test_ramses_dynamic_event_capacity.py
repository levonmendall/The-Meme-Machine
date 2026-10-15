"""Regression for the archived 140-bin withdrawal that stopped a broad scan."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from meme_machine.lanes.ramses import BoundaryError
from meme_machine.lanes.ramses.abi import topic
from meme_machine.lanes.ramses.identity import load
from meme_machine.lanes.ramses.ramses import MAX_EVENT_DATA_BYTES,decode_ramses_event
from meme_machine.lanes.ramses.ramses_universe import _decode_economic_logs

FIXTURE=Path(__file__).with_name('fixtures')/'ramses_140_bin_withdrawal_35578433187.json'

def word(value):
    return int(value).to_bytes(32,'big')

def liquidity_event(count,name='WithdrawnFromBins'):
    transfer=name=='TransferBatch'
    indexed=3 if transfer else 2
    signature=(name+'('+','.join(['address']*indexed)+',uint256[],'
               +('uint256[]' if transfer else 'bytes32[]')+')')
    ids=b''.join(word(8_000_000+i) for i in range(count))
    amounts=b''.join(word(((i+1)<<128)|(i+2)) for i in range(count))
    raw=word(64)+word(96+32*count)+word(count)+ids+word(count)+amounts
    return dict(topics=[topic(signature)]+['0x'+word(i+1).hex() for i in range(indexed)],
                data='0x'+raw.hex())

class DynamicLiquidityEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abi=load('ramses_pool_implementation')['abi']
        cls.fixture=json.loads(FIXTURE.read_text())

    def test_archived_140_bin_withdrawal_decodes_losslessly(self):
        event=self.fixture['event']
        raw=bytes.fromhex(event['data'][2:])
        self.assertEqual(len(raw),9088)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            '8f9c2ed07850ee35e19f1d207c019a45981c63c5871c0ad8bfa2a510cff0261f')
        decoded=decode_ramses_event(self.abi,event)
        self.assertEqual(decoded['name'],'WithdrawnFromBins')
        ids=decoded['args']['ids'];amounts=decoded['args']['amounts']
        self.assertEqual((len(ids),len(amounts)),(140,140))
        rebuilt=(word(64)+word(4576)+word(140)+b''.join(word(x) for x in ids)
                 +word(140)+b''.join(bytes.fromhex(x[2:]) for x in amounts))
        self.assertEqual(rebuilt,raw)

    def test_broad_census_retains_large_liquidity_and_other_pool_swap(self):
        event=self.fixture['event']
        swap=deepcopy(event);swap.update(address='0x'+'11'*20,logIndex='0xe')
        swap['topics']=[topic('Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)')]+event['topics'][1:]
        swap['data']='0x'+b''.join(word(x) for x in (8_388_608,1,2,3,4,5)).hex()
        histories,costs=_decode_economic_logs([swap,event],[event['address'],swap['address']])
        self.assertEqual([row['category'] for row in costs],['remove_liquidity','unwind'])
        self.assertEqual(costs[0]['transaction_hash'],event['transactionHash'])
        self.assertEqual(set(histories),{swap['address']})
        self.assertEqual(histories[swap['address']][0]['args']['id'],8_388_608)

    def test_large_arrays_across_liquidity_event_shapes(self):
        for name in ('DepositedToBins','WithdrawnFromBins','TransferBatch'):
            for count in (64,65,140,256):
                with self.subTest(name=name,count=count):
                    decoded=decode_ramses_event(self.abi,liquidity_event(count,name))
                    self.assertEqual(len(decoded['args']['ids']),count)
                    self.assertEqual(len(decoded['args']['amounts']),count)
                    self.assertEqual(decoded['args']['ids'][-1],8_000_000+count-1)

    def test_original_byte_ceiling_still_bounds_work(self):
        self.assertEqual(MAX_EVENT_DATA_BYTES,65536)
        boundary=liquidity_event(1022)
        self.assertEqual(len(bytes.fromhex(boundary['data'][2:])),65536)
        self.assertEqual(len(decode_ramses_event(self.abi,boundary)['args']['ids']),1022)
        with self.assertRaisesRegex(BoundaryError,'event_data_length'):
            decode_ramses_event(self.abi,liquidity_event(1023))

    def test_declared_huge_count_fails_before_allocation(self):
        event=liquidity_event(65);raw=bytearray.fromhex(event['data'][2:])
        raw[64:96]=word(2**256-1);event['data']='0x'+raw.hex()
        with self.assertRaisesRegex(BoundaryError,'event_dynamic_capacity'):
            decode_ramses_event(self.abi,event)

    def test_truncated_large_array_fails_closed(self):
        event=deepcopy(self.fixture['event']);event['data']=event['data'][:-64]
        with self.assertRaisesRegex(BoundaryError,'event_dynamic_capacity'):
            decode_ramses_event(self.abi,event)

    def test_dynamic_offsets_cannot_alias_head_or_leave_payload(self):
        template=liquidity_event(65)
        for offset in (0,32,65,len(bytes.fromhex(template['data'][2:]))+32):
            with self.subTest(offset=offset):
                event=deepcopy(template);raw=bytearray.fromhex(event['data'][2:])
                raw[:32]=word(offset);event['data']='0x'+raw.hex()
                with self.assertRaisesRegex(BoundaryError,'event_dynamic_offset'):
                    decode_ramses_event(self.abi,event)

    def test_removed_or_unregistered_large_event_remains_fail_closed(self):
        event=deepcopy(self.fixture['event']);event['removed']=True
        with self.assertRaisesRegex(BoundaryError,'ramses_universe_log_identity'):
            _decode_economic_logs([event],[event['address']])
        event['removed']=False
        with self.assertRaisesRegex(BoundaryError,'ramses_universe_log_identity'):
            _decode_economic_logs([event],['0x'+'22'*20])
