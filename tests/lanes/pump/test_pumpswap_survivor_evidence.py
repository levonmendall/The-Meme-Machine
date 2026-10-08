import base64
import hashlib
import struct
import unittest
from meme_machine.lanes.pump import pump
from meme_machine.lanes.pump.postgrad import pumpswap_pool,WSOL
from meme_machine.lanes.pump.pumpswap_survivor_evidence import migration_events,MIGRATION_DISC,sol_usd_lower_micros,PYTH_RECEIVER,SOL_USD_FEED


class EvidenceTests(unittest.TestCase):
    def migration(self,quote=None):
        mint=pump.b58(bytes([42])*32);pool=pumpswap_pool(mint)
        raw=MIGRATION_DISC+bytes([5])*32+pump.un58(mint)+struct.pack('<QQQ',1000,400,2)
        raw+=pump.un58(pump.pda([b'bonding-curve',pump.un58(mint)]))+struct.pack('<q',100)+pump.un58(pool)
        if quote is not None:raw+=pump.un58(quote)
        return dict(slot=100,meta=dict(err=None,logMessages=[f'Program {pump.PROGRAM} invoke [1]',
            'Program data: '+base64.b64encode(raw).decode(),f'Program {pump.PROGRAM} success']))

    def test_authenticated_invocation_and_sol_lineage_legacy_and_current(self):
        for quote in (None,WSOL):
            rows=migration_events(self.migration(quote));self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['quote_asset'],'SOL');self.assertEqual(rows[0]['market_time'],100)
        tx=self.migration();tx['meta']['logMessages'][0]='Program unrelated invoke [1]'
        self.assertEqual(migration_events(tx),[])
        tx=self.migration();tx['meta']['err']={'error':1};self.assertEqual(migration_events(tx),[])

    def test_usdc_migration_is_excluded_without_poisoning_shared_plane(self):
        self.assertEqual(migration_events(self.migration(pump.b58(bytes([7])*32))),[])

    def oracle(self,**changes):
        fields=dict(price=10_000_000_000,confidence=10_000_000,exponent=-8,published=100,previous=90,ema=10_000_000_000,ema_conf=10_000_000,posted=90)
        fields.update(changes)
        raw=hashlib.sha256(b'account:PriceUpdateV2').digest()[:8]+bytes(32)+bytes([1])+SOL_USD_FEED
        raw+=struct.pack('<qQiqqqQQ',*fields.values())
        return dict(owner=PYTH_RECEIVER,executable=False,data=[base64.b64encode(raw).decode(),'base64'])

    def test_oracle_conservative_value_exact_age_boundary(self):
        self.assertEqual(sol_usd_lower_micros(self.oracle(),now=220,slot=90),99_900_000)
        for kw in (dict(published=99),dict(published=221),dict(posted=91),dict(confidence=10_000_000_000),dict(exponent=1)):
            with self.subTest(kw=kw),self.assertRaises(ValueError):sol_usd_lower_micros(self.oracle(**kw),now=220,slot=90)

    def test_oracle_unknown_partial_wrong_feed_owner_fail_closed(self):
        for offset in (0,40,41):
            account=self.oracle();raw=bytearray(base64.b64decode(account['data'][0]));raw[offset]^=1
            account['data'][0]=base64.b64encode(raw).decode()
            with self.assertRaises(ValueError):sol_usd_lower_micros(account,now=100,slot=90)
        a=self.oracle();a['owner']='wrong'
        with self.assertRaises(ValueError):sol_usd_lower_micros(a,now=100,slot=90)
