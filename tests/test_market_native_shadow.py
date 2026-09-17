import unittest

from meme_machine.market_native_shadow import (
    MIN_DISTINCT_NON_SYSTEM_WALLETS,
    MIN_WINDOW_EVENTS,
    classify_buckets,
    discover_market_native,
)


class Tape:
    def __init__(self, rows):
        self.rows = rows
    def window(self, mint, now):
        return [dict(x) for x in self.rows if x['mint'] == mint]


def event(i, wallet, mint='mint', buy=True, market_time=100):
    return dict(
        id=f'e{i}', wallet=wallet, mint=mint, buy=buy,
        market_time=market_time, available_time=market_time,
        type='trade', amount=1, tokens=1, slot=1,
    )


class MarketNativeShadow(unittest.TestCase):
    def test_discovery_depends_on_activity_not_named_wallet_identity(self):
        rows_a=[event(1,'wallet-a'),event(2,'wallet-b'),event(3,'wallet-c')]
        rows_b=[event(1,'other-a'),event(2,'other-b'),event(3,'other-c')]
        out_a=discover_market_native([rows_a[-1]],Tape(rows_a),100,set())
        out_b=discover_market_native([rows_b[-1]],Tape(rows_b),100,set())
        self.assertEqual(len(out_a),1)
        self.assertEqual(len(out_b),1)
        self.assertEqual(out_a[0]['window_events'],MIN_WINDOW_EVENTS)
        self.assertEqual(out_b[0]['window_events'],MIN_WINDOW_EVENTS)
        self.assertEqual(out_a[0]['distinct_non_system_wallets'],MIN_DISTINCT_NON_SYSTEM_WALLETS)
        self.assertEqual(out_b[0]['distinct_non_system_wallets'],MIN_DISTINCT_NON_SYSTEM_WALLETS)
        self.assertNotEqual(out_a[0]['nomination']['wallet'],out_b[0]['nomination']['wallet'])

    def test_sparse_or_sell_only_activity_does_not_nominate(self):
        sparse=[event(1,'a'),event(2,'b')]
        self.assertEqual(discover_market_native([sparse[-1]],Tape(sparse),100,set()),[])
        sells=[event(1,'a',buy=False),event(2,'b',buy=False),event(3,'c',buy=False)]
        self.assertEqual(discover_market_native([sells[-1]],Tape(sells),100,set()),[])

    def test_existing_mint_is_not_renominated(self):
        rows=[event(1,'a'),event(2,'b'),event(3,'c')]
        self.assertEqual(discover_market_native([rows[-1]],Tape(rows),100,{'mint'}),[])

    def test_four_way_bucket_accounting(self):
        buckets=classify_buckets(
            {'scout','both'}, {'market','both'}, {'scout','market','both','neither'})
        self.assertEqual(buckets['scout_only'],['scout'])
        self.assertEqual(buckets['market_native_only'],['market'])
        self.assertEqual(buckets['both'],['both'])
        self.assertEqual(buckets['neither_pending_retrospective_review'],['neither'])


if __name__=='__main__':
    unittest.main()
