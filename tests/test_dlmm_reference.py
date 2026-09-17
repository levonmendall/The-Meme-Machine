import json
import unittest
import tempfile
from pathlib import Path
from meme_machine import dlmm
from meme_machine.provider import Unavailable
from tests.dlmm_support import snapshot

FIXTURES=Path(__file__).parent/'fixtures'


class OfficialReference(unittest.TestCase):
    def test_official_historical_pool_and_bins_without_invented_timestamp(self):
        fixture=json.loads((FIXTURES/'dlmm_official_historical.json').read_text())
        self.assertIsNone(fixture['finalized_slot']);self.assertIsNone(fixture['capture_time'])
        p=dlmm.pool(fixture['files']['lb_pair.bin']['account'])
        self.assertEqual(p['active'],15);self.assertEqual(p['step'],250)
        bins={}
        for name in ('bin_array_1.bin','bin_array_2.bin'):
            a=fixture['files'][name]
            bins.update(dlmm.bin_array(a['account'],fixture['pool'],a['index'],p['step']))
        self.assertEqual(len(bins),140);self.assertGreater(bins['15']['supply'],0)

    def test_official_executed_sdk_vectors(self):
        v=json.loads((FIXTURES/'dlmm_sdk_vectors.json').read_text())
        self.assertEqual(v['commit'],'576919e3e4368e542c402f000b4264724f7f23ec')
        for row in v['prices']:
            with self.subTest(price=row):
                if int(row['value'])==0:
                    with self.assertRaises(ValueError):dlmm.price(row['id'],row['step'])
                else:self.assertEqual(dlmm.price(row['id'],row['step']),int(row['value']))
        for row in v['fees']:
            p=dlmm.validate(snapshot(),100);p['step']=row['step'];p['volatility_accumulator']=row['volatility']
            self.assertEqual(dlmm.total_fee(p),int(row['rate']))
        for row in v['swaps']:
            with self.subTest(swap=row):
                p=dlmm.validate(snapshot(),100)
                p.update(active=row['id'],step=row['step'],volatility_reference=row['volatility'],
                    index_reference=row['id'],volatility_accumulator=row['volatility'])
                p['bins']={str(row['id']):dict(x=200000000,y=200000000,price=dlmm.price(row['id'],row['step']),
                    supply=400000000*dlmm.Q,fee_x=0,fee_y=0)}
                if int(row['amountOut'])==0:
                    with self.assertRaises(Unavailable):dlmm.swap(p,int(row['amountIn']),row['direction'],100)
                    continue
                _,quote=dlmm.swap(p,int(row['amountIn']),row['direction'],100)
                self.assertEqual(quote['output'],int(row['amountOut']))
                self.assertEqual(quote['fee']-quote['protocol_fee'],int(row['lpFee']))
                self.assertEqual(quote['protocol_fee'],int(row['protocolFee']))

    def test_idl_account_offsets_and_sizes(self):
        idl=json.loads((FIXTURES/'dlmm_idl_subset.json').read_text())
        self.assertEqual(idl['address'],dlmm.PROGRAM)
        types={x['name']:x['type'] for x in idl['types']}
        def size(t):
            if isinstance(t,str):return {'u8':1,'bool':1,'u16':2,'u32':4,'i32':4,'u64':8,'i64':8,'u128':16,'pubkey':32}[t]
            if 'array' in t:return size(t['array'][0])*t['array'][1]
            return sum(size(f['type']) for f in types[t['defined']['name']]['fields'])
        for name,expected in [('LbPair',904),('BinArray',10136),('Bin',144)]:
            offset=0 if name=='Bin' else 8;offsets={}
            for f in types[name]['fields']:
                offsets[f['name']]=offset;offset+=size(f['type'])
            self.assertEqual(offset,expected)
            if name=='LbPair':
                self.assertEqual(offsets['active_id'],76);self.assertEqual(offsets['token_x_mint'],88)
                self.assertEqual(offsets['token_mint_x_program_flag'],880)
            if name=='Bin':self.assertEqual(offsets['fee_amount_x_per_token_stored'],80)

    def test_captured_current_pool_rejects_missing_active_array(self):
        snap=json.loads((FIXTURES/'dlmm_mainnet.json').read_text())
        self.assertEqual(snap['kind'],'real');self.assertEqual(snap['commitment'],'finalized')
        p=dlmm.pool(snap['accounts'][snap['pool']]);self.assertEqual(p['y'],dlmm.WSOL)
        self.assertEqual(p['active'],-78);self.assertEqual(p['step'],250)
        # Authentic current observation is NOT upgraded to an eligible pool.
        with self.assertRaisesRegex(ValueError,'missing_active'):
            dlmm.validate(snap,snap['available_time'])

    def test_current_mainnet_pool_through_runtime_decoders_and_scout(self):
        snap=json.loads((FIXTURES/'dlmm_mainnet_eligible.json').read_text())
        p=dlmm.validate(snap,snap['available_time'],'real')
        self.assertEqual(p['pool'],'J8a3ZKcDZA8HSinuCyjJggU8hnDgwkZKmwH8qDZ9nUcY')
        self.assertIn(dlmm.WSOL,(p['x'],p['y']))
        self.assertIn(str(p['active']),p['bins'])
        self.assertGreater(p['bins'][str(p['active'])]['supply'],0)
        c=dlmm.scout(snap,snap['available_time'])
        self.assertFalse(c['allocation_eligible'])

    def test_mainnet_bytes_deposit_withdraw_restart_and_cost_only_loss(self):
        from meme_machine.store import Store
        from meme_machine.dlmm_paper import Replay,ENTRY_COST,EXIT_COST
        snap=json.loads((FIXTURES/'dlmm_mainnet_eligible.json').read_text());now=snap['available_time']
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'p.db';s=Store(path,'captured',100_000_000,'captured protocol mechanics')
            r=Replay(s);r.reserve('lp',snap,now);r.deposit('lp',snap,now);s.close()
            s=Store(path,'captured',100_000_000,'captured protocol mechanics');r=Replay(s)
            try:
                mark=r.mark('lp',now);self.assertTrue(mark['resolved'])
                self.assertEqual(mark['assets']['fee_x']+mark['assets']['fee_y'],0)
                r.exit_intent('lp','captured_accounting_check',now);r.withdraw('lp',now)
                settled=r.settle('lp',now)
                self.assertEqual(settled['realized'],-350002)  # costs plus 2 lamports of share rounding
                self.assertEqual(settled['costs'],ENTRY_COST+EXIT_COST)
                self.assertTrue(s.reconcile())
            finally:s.close()

    def test_real_captured_empty_interval_awards_no_fees(self):
        from meme_machine.dlmm_tape import reconstruct
        p=json.loads((FIXTURES/'dlmm_mainnet_interval.json').read_text())
        start=dlmm.validate(p['start'],p['start']['available_time'],'real')
        tape=reconstruct(start,p['end'],p['signatures'],p['transactions'],p['validated_at'],
                         [start['slot'],2**31-1,2**31-1])
        self.assertEqual(len(tape.events),0)
        self.assertEqual(tape.terminal['bins'],start['bins'])
        # Historical interval verification cannot turn expired evidence into a current quote.
        with self.assertRaisesRegex(ValueError,'stale'):
            dlmm.validate(p['end'],p['validated_at'],'real')
