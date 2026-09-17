import base64
import copy
import gzip
import json
import unittest
import tempfile
from pathlib import Path
from meme_machine import dlmm
from meme_machine.provider import Unavailable
from tests.dlmm_support import snapshot

FIXTURES=Path(__file__).parent/'fixtures'


def mainnet_swap_interval():
    raw=base64.b64decode((FIXTURES/'dlmm_mainnet_swap_interval.json.gz.b64').read_text())
    capture=json.loads(gzip.decompress(raw))
    for address in capture.pop('end_account_reuse'):
        capture['end']['accounts'][address]=copy.deepcopy(capture['start']['accounts'][address])
    return capture


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
        self.assertEqual(v['hashes']['ts-client/src/dlmm/helpers/rebalance/rebalancePosition.ts'],
                         '3acdf01b77a895b4fef148fa24a4cd1160b1f50b7b22adc1a8004aa46e0394ad')
        for row in v['accounting']:
            with self.subTest(accounting=row):
                b=dict(x=int(row['binX']),y=int(row['binY']),price=int(row['price']),
                       supply=int(row['supply']))
                share=dlmm.deposit_share(b,int(row['inX']),int(row['inY']))
                self.assertEqual(share,int(row['share']))
                post_supply=b['supply']+share
                self.assertEqual(dlmm.withdraw_amount(share,b['x']+int(row['inX']),post_supply),
                                 int(row['withdrawX']))
                self.assertEqual(dlmm.withdraw_amount(share,b['y']+int(row['inY']),post_supply),
                                 int(row['withdrawY']))
                self.assertEqual(dlmm.claim_fee(share,int(row['feeDelta'])),int(row['claim']))
                # The pinned rebalance preview divides inventory by Q64 supply
                # before multiplying by share, returning zero for these cases.
                # Program/share semantics retain the exact 0-or-1-unit dust shown
                # by withdrawX/Y; keep this known SDK-helper deviation explicit.
                self.assertEqual((int(row['sdkSimulatedX']),int(row['sdkSimulatedY'])),(0,0))

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
            mark=r.mark('lp',now);self.assertTrue(mark['resolved'])
            self.assertEqual(mark['assets']['fee_x']+mark['assets']['fee_y'],0)
            r.exit_intent('lp','captured_accounting_check',now);s.close()
            s=Store(path,'captured',100_000_000,'captured protocol mechanics');r=Replay(s)
            r.withdraw('lp',now);s.close()
            s=Store(path,'captured',100_000_000,'captured protocol mechanics');r=Replay(s)
            try:
                settled=r.settle('lp',now)
                self.assertEqual(settled['realized'],-350002)  # costs plus 2 lamports of share rounding
                self.assertEqual(settled['costs'],ENTRY_COST+EXIT_COST)
                self.assertTrue(s.reconcile())
            finally:s.close()

    def test_real_captured_swap_interval_exact_state_and_fee_attribution(self):
        from meme_machine.dlmm_tape import reconstruct
        p=mainnet_swap_interval()
        start=dlmm.validate(p['start'],p['start']['available_time'],'real')
        tape=reconstruct(start,p['end'],p['signatures'],p['transactions'],p['validated_at'],
                         [start['slot'],2**31-1,2**31-1])
        self.assertEqual(len(tape.events),1)
        event=tape.events[0]
        self.assertEqual(event['cursor'],[447856269,148,0])
        self.assertEqual(event['observed'],dict(start=1073,end=1074,output=593490,fee=21841,protocol_fee=2183))
        end=tape.terminal
        self.assertEqual(end['vault_x_amount']-start['vault_x_amount'],-593490)
        self.assertEqual(end['vault_y_amount']-start['vault_y_amount'],8692234)
        self.assertEqual(end['protocol_fee_y']-start['protocol_fee_y'],2183)
        accounted=0
        for bid in ('1073','1074'):
            growth=end['bins'][bid]['fee_y']-start['bins'][bid]['fee_y']
            accounted+=dlmm.claim_fee(start['bins'][bid]['supply'],growth)
        # 19,658 LP-fee units: 19,656 represented by the two integer fee-growth
        # increments and exactly 2 units of per-bin division dust.
        self.assertEqual((event['observed']['fee']-event['observed']['protocol_fee'],accounted),
                         (19658,19656))
        # Historical interval verification cannot turn expired evidence into a current quote.
        with self.assertRaisesRegex(ValueError,'stale'):
            dlmm.validate(p['end'],p['validated_at'],'real')

    def test_authentic_swap_tape_restart_and_zero_fee_for_untraversed_virtual_bins(self):
        from meme_machine.dlmm_tape import reconstruct
        from meme_machine.dlmm_paper import Replay
        from meme_machine.store import Store,digest
        p=mainnet_swap_interval();start=dlmm.validate(p['start'],p['start']['available_time'],'real')
        tape=reconstruct(start,p['end'],p['signatures'],p['transactions'],p['validated_at'],
                         [start['slot'],2**31-1,2**31-1])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'real.db';store=Store(path,'captured',100_000_000,'authentic finalized swap')
            replay=Replay(store);replay.reserve('lp',p['start'],p['start']['available_time'])
            replay.deposit('lp',p['start'],p['start']['available_time']);store.close()
            store=Store(path,'captured',100_000_000,'authentic finalized swap');replay=Replay(store)
            replay.process_tape('lp',tape,p['validated_at']);before=digest(store.state);store.close()
            store=Store(path,'captured',100_000_000,'authentic finalized swap');replay=Replay(store)
            try:
                self.assertEqual(before,digest(store.state))
                position=store.state['liquidity_positions']['lp']
                self.assertEqual(position['events'],1)
                # The fixed one-sided experiment occupies 1071/1072; the real
                # swap traversed 1073/1074, so zero fees are the exact attribution.
                self.assertEqual(position['inventory']['fee_x']+position['inventory']['fee_y'],0)
                with self.assertRaisesRegex(Unavailable,'anchor'):
                    replay.process_tape('lp',tape,p['validated_at'])
                self.assertTrue(store.reconcile())
            finally:store.close()
