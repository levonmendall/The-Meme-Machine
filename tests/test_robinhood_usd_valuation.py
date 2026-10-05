"""Offline USDG oracle and native quote composition; no market transport."""
import ast
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.ramses.abi import calldata
from meme_machine.lanes.ramses.identity import load
from meme_machine.runtime.usd_valuation import (
    USDG_ASSET,USDG_FEED,USDG_HEARTBEAT,NativeValueReader,
    ValuationUnavailable,robinhood_usd,sol_usd,
)

ROOT=Path(__file__).resolve().parents[1]
BASE='f05dcf09ebbded45e09aa7a95bfbe82c07b4fd38'
NOW=1791077122
ROUND=(1<<64)+121
UPDATED=1791042001
AGGREGATOR='0x8beee3503f6860d5dac4ce26b5eee92982951c2e'
WNATIVE='0x'+'a1'*20
POOL='0x'+'a2'*20


def baseline(path):
    try:
        return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # Normal CI uses a shallow checkout. No historical/network fetch belongs
        # to a deterministic unit suite; full source comparisons run locally.
        raise unittest.SkipTest('Historical source comparison needs the existing baseline commit') from None


def abi(*values):
    return '0x'+''.join(f'{int(v,16) if isinstance(v,str) else v%(1<<256):064x}' for v in values)


def text_abi(value):
    raw=value.encode()
    return abi(32,len(raw))+raw.hex()+('00'*((-len(raw))%32))


class ReadRPC:
    """The real authentication/route decoders consume these synthetic RPC facts."""
    def __init__(self):
        self.now=NOW
        self.answer=100013961
        self.round=[ROUND,self.answer,UPDATED-12,UPDATED,ROUND]
        self.description='USDG / USD'
        self.feed_decimals=8
        self.token_decimals=6
        self.chain=4663
        self.chain_verified=False
        self.feed_code='0x60006000'
        self.failed=False
        self.calls=[]
        self.route_output=2500000  # 0.001 ETH -> 2.5 USDG, including route fee
        self.unfilled=0
        self.hooks=0
        self.no_pairs=False
        self.bad_factory=False
        self.bad_pool=False
        self.router=load('ramses_router')
        self.factory=load('ramses_factory')
        implementation=load('ramses_pool_implementation')['address'][2:]
        self.pool_code=('0x363d3d373d3d3d3d61002c806035363936013d73'+implementation
            +'5af43d3d93803e603357fd5bf3'+WNATIVE[2:]+USDG_ASSET[2:]+'000a002c')

    def verify_chain(self):
        self.call('eth_chainId',[])
        self.chain_verified=True
        return self.chain

    def batch(self,calls,*,scope):
        return [self.call(method,params,scope=scope) for method,params in calls]

    def call(self,method,params,*,scope=None):
        self.calls.append((method,params,scope))
        if self.failed:raise OSError('https://example.invalid/private-provider-secret')
        if method=='eth_chainId':return hex(self.chain)
        if not self.chain_verified:raise AssertionError('provider_chain_identity_unverified')
        if method=='eth_getBlockByNumber':
            return dict(number='0x4bdc170',hash='0x'+'12'*32,timestamp=hex(self.now))
        if method=='eth_getCode':
            address=params[0].lower()
            if address==USDG_FEED.lower():return self.feed_code
            if address==self.router['address'].lower():return self.router['runtimeBytecode']['onchainBytecode']
            if address==self.factory['address'].lower():
                return '0x6000' if self.bad_factory else self.factory['runtimeBytecode']['onchainBytecode']
            if address==POOL:return '0x6000' if self.bad_pool else self.pool_code
            if address in (USDG_ASSET,AGGREGATOR):return '0x6000'
        if method=='eth_call':
            address=params[0]['to'].lower();data=params[0]['data']
            if address==USDG_FEED.lower():
                reads={
                    calldata('description()'):text_abi(self.description),
                    calldata('decimals()'):abi(self.feed_decimals),
                    calldata('latestRoundData()'):abi(*self.round),
                    calldata('aggregator()'):abi(AGGREGATOR),
                    calldata('version()'):abi(6),
                }
                return reads[data]
            if address==USDG_ASSET and data==calldata('decimals()'):return abi(self.token_decimals)
            if address==self.router['address'].lower() and data==calldata('getWNATIVE()'):return abi(WNATIVE)
            if address==self.factory['address'].lower():
                if data!=calldata('getAllLBPairs(address,address)',WNATIVE,USDG_ASSET):raise AssertionError('wrong route tokens')
                return abi(32,0) if self.no_pairs else abi(32,1,10,POOL,1,0)
            if address==POOL:
                if data==calldata('getLBHooksParameters()'):return abi(self.hooks)
                if data==calldata('getSwapOut(uint128,bool)',10**15,1):return abi(self.unfilled,self.route_output,1000)
        raise AssertionError('unexpected read-only RPC call')


class RobinhoodUSDTests(unittest.TestCase):
    def setUp(self):
        self.rpc=ReadRPC()
        clock=patch('meme_machine.runtime.usd_valuation.time.time',side_effect=lambda:self.rpc.now)
        clock.start();self.addCleanup(clock.stop)

    def value(self):return robinhood_usd(self.rpc,now=self.rpc.now)

    def unavailable(self,reason=None):
        with self.assertRaisesRegex(ValuationUnavailable,reason or 'VALUATION_UNAVAILABLE:USDG/USD'):
            self.value()

    def test_block_acquired_after_caller_time_succeeds(self):
        self.rpc.now=NOW+3
        self.rpc.round=[ROUND,100000000,NOW+1,NOW+2,ROUND]
        value=robinhood_usd(self.rpc,now=NOW)
        self.assertEqual(value.observed_at,NOW+2)
        self.assertEqual(value.amount(1000000,NOW+3),Decimal('1'))

    def test_future_block_after_completion_fails(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(NOW+4)
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            self.unavailable('invalid_block_time')

    def test_provider_delay_does_not_refresh_stale_oracle(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT+3
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):
            robinhood_usd(self.rpc,now=UPDATED+USDG_HEARTBEAT-1)

    def test_route_expiring_during_transport_fails_at_completion(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_call' and params[0]['data']==calldata('getSwapOut(uint128,bool)',10**15,1):
                self.rpc.now=NOW+6
            return result
        with patch.object(self.rpc,'call',side_effect=call):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_verified_readback_decode_and_decimal_normalization(self):
        value=self.value()
        self.assertEqual(value.usd_per_unit,Decimal('1.00013961'))
        self.assertEqual((value.asset,value.decimals),('USDG',6))
        self.assertEqual(value.amount(125000000,NOW),Decimal('125.01745125'))
        self.assertEqual(value.observed_at,UPDATED)
        self.assertEqual(value.valid_until,UPDATED+86400)
        self.assertEqual(len(value.evidence_hash),64)

    def test_positive_sub_parity_answer_reflects_depeg(self):
        self.rpc.round[1]=80000000
        self.assertEqual(self.value().amount(1000000,NOW),Decimal('.8'))

    def test_heartbeat_boundary_is_inclusive_and_never_extended(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT
        value=self.value()
        self.assertEqual(value.valid_until,self.rpc.now)
        self.rpc.now+=1
        self.unavailable('stale_round')

    def test_zero_and_negative_answer_rejected(self):
        for answer in (0,-1):
            with self.subTest(answer=answer):
                self.rpc.round[1]=answer;self.unavailable('nonpositive_answer')

    def test_incomplete_future_and_older_answered_rounds_rejected(self):
        for fields in (
            [0,100,UPDATED,UPDATED,ROUND],
            [1,100,UPDATED,UPDATED,1],
            [1<<64,100,UPDATED,UPDATED,1<<64],
            [ROUND,100,0,UPDATED,ROUND],
            [ROUND,100,UPDATED,0,ROUND],
            [ROUND,100,UPDATED+1,UPDATED,ROUND],
            [ROUND,100,NOW+1,NOW+1,ROUND],
            [ROUND,100,UPDATED,UPDATED,ROUND-1],
            [ROUND,100,UPDATED,UPDATED,(2<<64)+121],
            [1<<80,100,UPDATED,UPDATED,1<<80],
        ):
            with self.subTest(fields=fields):
                self.rpc.round=fields;self.unavailable()

    def test_malformed_round_length_and_hex_rejected(self):
        original=self.rpc.call
        for raw in ('0x','0xgg',abi(ROUND,1),abi(*self.rpc.round)+'00'):
            with self.subTest(raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata('latestRoundData()'):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_wrong_feed_description_rejected(self):
        for description in ('USDC / USD','USDG/USD','USDG / EUR'):
            with self.subTest(description=description):
                self.rpc.description=description;self.unavailable('wrong_feed_description')

    def test_wrong_feed_decimals_or_invalid_padding_rejected(self):
        for decimals in (0,6,18,256):
            with self.subTest(decimals=decimals):
                self.rpc.feed_decimals=decimals;self.unavailable()

    def test_missing_contract_code_rejected(self):
        for code in ('0x','0x00','0xxyz'):
            with self.subTest(code=code):self.rpc.feed_code=code;self.unavailable()

    def test_wrong_chain_rejected(self):
        self.rpc.chain=1;self.unavailable('wrong_chain')

    def test_exact_proxy_and_token_addresses_and_read_only_methods(self):
        self.value()
        calls=[params[0]['to'] for method,params,_ in self.rpc.calls if method=='eth_call']
        self.assertTrue(all(address in (USDG_FEED,USDG_ASSET) for address in calls))
        self.assertEqual(USDG_FEED,'0x61B7e5650328764B076A108EFF5fa7282a1B9aD2')
        self.assertLessEqual(set(method for method,_,_ in self.rpc.calls),
            {'eth_chainId','eth_getCode','eth_call','eth_getBlockByNumber'})

    def test_unavailable_rpc_has_no_price_fallback_or_credential_leak(self):
        self.rpc.failed=True
        with self.assertRaises(ValuationUnavailable) as caught:self.value()
        self.assertNotIn('private-provider-secret',str(caught.exception))
        self.assertIn('RPC_unavailable_or_invalid',str(caught.exception))

    def test_missing_config_fails_without_market_io(self):
        with patch.dict('os.environ',{},clear=True),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            with self.assertRaises(ValuationUnavailable):robinhood_usd(now=NOW)

    def test_cache_reuses_only_within_sixty_seconds(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+60),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now=NOW+61;self.rpc.round[1]=90000000
        self.assertEqual(reader(NOW+61).usd_per_unit,Decimal('.9'))
        self.assertGreater(len(self.rpc.calls),count)

    def test_expired_cache_does_not_fallback_during_outage(self):
        reader=NativeValueReader('ramses',rpc=self.rpc)
        value=reader(NOW);self.rpc.failed=True
        self.assertIs(reader(NOW+59),value)
        with self.assertRaises(ValuationUnavailable):reader(NOW+61)
        from meme_machine.runtime.status import snapshot
        self.assertEqual(snapshot()['phase'],'VALUATION_UNAVAILABLE')

    def test_cache_never_extends_oracle_heartbeat(self):
        self.rpc.now=UPDATED+USDG_HEARTBEAT-1
        reader=NativeValueReader('ramses',rpc=self.rpc)
        reader(self.rpc.now)
        self.rpc.now+=2
        with self.assertRaisesRegex(ValuationUnavailable,'stale_round'):reader(self.rpc.now)

    def test_ramses_usdg_to_usd_and_exact_quote_identity(self):
        book=SimpleNamespace(quote_asset=USDG_ASSET.upper())
        value=NativeValueReader('ramses',book,rpc=self.rpc)(NOW)
        self.assertEqual(value.amount(1000000,NOW),Decimal('1.00013961'))
        book.quote_asset=WNATIVE
        with self.assertRaisesRegex(ValuationUnavailable,'wrong_Ramses_quote_asset'):
            NativeValueReader('ramses',book,rpc=self.rpc)(NOW)

    def test_usdg_token_decimals_must_match_accounting_units(self):
        self.rpc.token_decimals=18;self.unavailable('wrong_USDG_token_decimals')

    def test_wrong_proxy_interface_and_address_padding_rejected(self):
        original=self.rpc.call
        for name,raw in (('aggregator()',abi(0)),('aggregator()',abi(1<<160)),('version()',abi(5))):
            with self.subTest(name=name,raw=raw):
                def call(method,params,**kw):
                    if method=='eth_call' and params[0]['data']==calldata(name):return raw
                    return original(method,params,**kw)
                with patch.object(self.rpc,'call',side_effect=call):self.unavailable()

    def test_round_must_exist_at_pinned_block(self):
        original=self.rpc.call
        def call(method,params,**kw):
            result=original(method,params,**kw)
            if method=='eth_getBlockByNumber':result['timestamp']=hex(UPDATED-1)
            return result
        with patch.object(self.rpc,'call',side_effect=call):self.unavailable('round_after_pinned_block')

    def test_pons_native_to_authenticated_executable_usdg_to_usd(self):
        value=NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual((value.asset,value.decimals),('ETH',18))
        self.assertEqual(value.usd_per_unit,Decimal('2500.349025'))
        self.assertEqual(value.amount(10**15,NOW),Decimal('2.500349025'))
        self.assertEqual(value.valid_until,NOW+5)
        self.assertLessEqual(len(value.evidence_id),150)
        # $125 family equity is translated by this live composed rate.
        capital=int(Decimal('125')*Decimal(10**18)/value.usd_per_unit)
        self.assertLessEqual(value.amount(capital,NOW),Decimal('125'))
        self.assertLess(Decimal('125')-value.amount(capital,NOW),value.amount(1,NOW))

    def test_pons_execution_capacity_and_route_identity_fail_closed(self):
        for field,value in (('no_pairs',True),('unfilled',1),('route_output',0),
                ('hooks',1),('bad_factory',True),('bad_pool',True)):
            with self.subTest(field=field):
                rpc=ReadRPC();setattr(rpc,field,value)
                with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=rpc)(NOW)

    def test_pons_quote_cache_expires_without_extending_five_second_window(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        first=reader(NOW);count=len(self.rpc.calls)
        self.assertIs(reader(NOW+5),first)
        self.assertEqual(len(self.rpc.calls),count)
        self.rpc.now+=6;self.rpc.route_output=2000000
        self.assertEqual(reader(self.rpc.now).usd_per_unit,Decimal('2000.27922'))
        self.assertGreater(len(self.rpc.calls),count)
        # A fresh production RPC session must verify chain even with a cached oracle.
        self.assertGreaterEqual(sum(1 for method,_,_ in self.rpc.calls if method=='eth_chainId'),2)

    def test_pons_cached_oracle_refresh_verifies_new_provider_session(self):
        reader=NativeValueReader('pons',rpc=self.rpc)
        reader(NOW)
        fresh=ReadRPC();fresh.now=NOW+6
        reader.rpc=fresh
        self.assertEqual(reader(NOW+6).usd_per_unit,Decimal('2500.349025'))
        self.assertTrue(fresh.chain_verified)
        self.assertNotIn(calldata('latestRoundData()'),
            [params[0]['data'] for method,params,_ in fresh.calls if method=='eth_call'])

    def test_pons_oracle_and_conversion_reuse_one_pinned_block(self):
        NativeValueReader('pons',rpc=self.rpc)(NOW)
        self.assertEqual(sum(method=='eth_getBlockByNumber' for method,_,_ in self.rpc.calls),1)
        blocks=[params[1] for method,params,_ in self.rpc.calls if method in ('eth_call','eth_getCode')]
        self.assertEqual(set(blocks),{'0x4bdc170'})

    def test_pons_feed_depeg_is_composed_without_fixed_dollar_fallback(self):
        self.rpc.round[1]=80000000
        self.assertEqual(NativeValueReader('pons',rpc=self.rpc)(NOW).usd_per_unit,Decimal('2000'))

    def test_pons_transport_delay_cannot_extend_execution_freshness(self):
        with patch('meme_machine.runtime.usd_valuation.time.monotonic',side_effect=[0,6]):
            with self.assertRaises(ValuationUnavailable):NativeValueReader('pons',rpc=self.rpc)(NOW)

    def test_outage_preserves_shared_capital_and_existing_positions(self):
        from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,LANES
        from meme_machine.runtime.native_boundary import NativeBoundary
        from meme_machine.runtime.usd_valuation import utc
        from meme_machine.runtime.journal import digest
        ids=dict(source_sha='a'*40,policy_hash='b'*64,config_hash='c'*64)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'offline-fixture.sqlite'
            with closing(PortfolioAccounting(path)) as account:
                account.establish_inception(inception_receipt('offline-usdg-fixture',utc(NOW),'offline-inception'),
                    portfolio_identities=ids,lane_identities={lane:ids for lane in LANES})
                account.configure_family_sleeves()
            reader=NativeValueReader('ramses',rpc=self.rpc)
            boundary=NativeBoundary(path,'ramses',SimpleNamespace(),value_reader=reader)
            value=reader(NOW)
            for key,kind,data in (
                ('reserve','reserve',{'amount':'6.25'}),
                ('enter','enter',{'asset':POOL,'basis':'6.25','fee':'0','strategy_id':'ramses'}),
            ):
                boundary.client.deliver('existing',event_key=key,journal_hash=digest([key,data]),kind=kind,
                    at=utc(NOW),data=data,value_evidence=value.evidence(NOW) if kind=='enter' else None)
            with closing(PortfolioAccounting(path)) as account:before=account.snapshot()
            self.rpc.failed=True
            for native,action in (('new','reserved'),('existing','settled')):
                with self.assertRaises(ValuationUnavailable):
                    boundary.record(native,action,{'reserved':1000000},None,at=NOW+61,checksum='b'*64)
            with closing(PortfolioAccounting(path)) as account:self.assertEqual(account.snapshot(),before)
            self.assertFalse(boundary.prepared)
            self.assertFalse(boundary.client.pending())

    def test_unavailable_robinhood_does_not_affect_solana_reader_or_decoder(self):
        from meme_machine.runtime.usd_valuation import USDValue
        for lane in ('pump','meteora'):
            reader=NativeValueReader(lane)
            reader.cached=USDValue('SOL',9,Decimal('100'),NOW,NOW+120,'offline-sol','a'*64)
            with patch('meme_machine.runtime.usd_valuation.robinhood_usd',side_effect=ValuationUnavailable('offline outage')):
                self.assertEqual(reader(NOW).amount(10**9,NOW),Decimal('100'))
        old=baseline('meme_machine/runtime/usd_valuation.py').decode()
        current=(ROOT/'meme_machine/runtime/usd_valuation.py').read_text()
        def decoder(source):
            node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='sol_usd')
            # The unchanged decoder now runs under the canonical exact-money
            # context. Compare the oracle parsing/finality/conversion body.
            node.decorator_list=[]
            return ast.dump(node)
        self.assertEqual(decoder(old),decoder(current))

    def test_strategy_sources_and_nine_change_tests_byte_unchanged(self):
        original_tests=baseline('tests/test_operational_nine.py')
        paths=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'meme_machine/lanes'],cwd=ROOT,text=True).splitlines()
        self.assertEqual((ROOT/'tests/test_operational_nine.py').read_bytes(),original_tests)
        for rel in paths:
            current=(ROOT/rel).read_bytes()
            if rel=='meme_machine/lanes/ramses/ramses_lifecycle_log_census.py':
                added=(b'    from contextlib import closing\n'
                       b'    with closing(sqlite3.connect(cache_path)) as db, db:\n')
                self.assertEqual(current.count(added),1)
                current=current.replace(added,b'    with sqlite3.connect(cache_path) as db:\n')
            if rel in ('meme_machine/lanes/pump/runner.py','meme_machine/lanes/pons/pons_selective_cohort.py'):
                # The CAPACITY repair changes only executor-owned initialization.
                self.assertEqual(current.count(b'survivor.prime()'),1)
                current=current.replace(b'survivor.prime()',b'survivor._step(False)')
            if rel=='meme_machine/lanes/pump/runner.py':
                # Explicitly close only the SELECT-only old-epoch startup reader.
                added=(b"        from contextlib import closing\n"
                       b"        with closing(sqlite3.connect(accounting_path.resolve().as_uri()+'?mode=ro',uri=True)) as prior:\n")
                original_reader=b"        with sqlite3.connect(accounting_path.resolve().as_uri()+'?mode=ro',uri=True) as prior:\n"
                self.assertEqual(current.count(added),1)
                current=current.replace(added,original_reader)
                # Receipt context consumes existing snapshots only. Every byte
                # outside its observation block and added argument is pinned.
                original=baseline(rel)
                start=current.index(b'    from meme_machine.runtime.directional_sleeve import open_sleeve',current.index(b'def _record_attempt('))
                end=current.index(b'    if ACCOUNTING is not None:',start)
                old_start=original.index(b'    from meme_machine.runtime.directional_sleeve import open_sleeve',original.index(b'def _record_attempt('))
                old_end=original.index(b'    if ACCOUNTING is not None:',old_start)
                current=current[:start]+original[old_start:old_end]+current[end:]
                current=current.replace(b'extra=None,*,snapshot=None):',b'extra=None):')
                self.assertEqual(current.count(b',snapshot=snapshot'),6)
                current=current.replace(b',snapshot=snapshot',b'')
            if rel=='meme_machine/lanes/pons/pons_selective_cohort.py':
                # Current receipt context is observation-only; the queue and
                # native decision after it remain pinned byte for byte.
                original=baseline(rel)
                start=current.index(b"                from meme_machine.runtime.directional_sleeve import open_sleeve",current.index(b'evaluation=finished.result()'))
                end=current.index(b'                provider_after=',start)
                old_start=original.index(b"                from meme_machine.runtime.directional_sleeve import open_sleeve",original.index(b'evaluation=finished.result()'))
                old_end=original.index(b'                provider_after=',old_start)
                current=current[:start]+original[old_start:old_end]+current[end:]
                # Approved shutdown engineering precedes the unchanged native
                # lifecycle collection. Compare every other source byte exactly.
                original=baseline(rel)
                start=current.index(b'        # One finite drain window')
                end=current.index(b'        discovery_pool.shutdown(wait=True)',start)
                old_start=original.index(b'        # Resolve any externally in-flight work;')
                old_end=original.index(b'        discovery_pool.shutdown(wait=True)',old_start)
                current=current[:start]+original[old_start:old_end]+current[end:]
            if rel=='meme_machine/lanes/pons/pons_selective_continuation.py':
                # Owner-approved ongoing scaling is a separate appended authority.
                # Every byte of the initial-entry/exit policy remains pinned.
                current=current[:current.index(b'\n\nPONS_ONGOING_SCALE_REQUALIFICATION =')]
            if rel=='meme_machine/lanes/pons/pons_selective_paper.py':
                # Only the existing scale path and its dedicated reader changed.
                original=baseline(rel)
                # Only cleanup nesting changed: preserve reconciliation errors and
                # every strategy byte while closing the owned store unconditionally.
                cleanup_start=current.index(b'    finally:\n        try:\n            if capital_guard is not None:')
                cleanup_end=current.index(b'\n\n\ndef _continuation_facts',cleanup_start)
                old_cleanup_start=original.index(b'    finally:\n        if capital_guard is not None:')
                old_cleanup_end=original.index(b'\n\n\ndef _continuation_facts',old_cleanup_start)
                expected=original[old_cleanup_start:old_cleanup_end].decode().splitlines()
                expected=['    finally:','        try:']+['    '+line for line in expected[1:6]]+['        finally:']+['    '+line for line in expected[6:]]
                self.assertEqual(current[cleanup_start:cleanup_end], '\n'.join(expected).encode())
                current=current[:cleanup_start]+original[old_cleanup_start:old_cleanup_end]+current[cleanup_end:]
                start=current.index(b'def _ongoing_scale_evidence(')
                end=current.index(b'\n\n# Public recovery entrypoint',start)
                old_start=original.index(b'def _attempt_current_scale(')
                old_end=original.index(b'\n\n# Public recovery entrypoint',old_start)
                current=current[:start]+original[old_start:old_end]+current[end:]


            if rel in ('meme_machine/lanes/pump/solana_evidence_service.py','meme_machine/lanes/meteora/solana_evidence_service.py'):
                grouping=(b'    # Prepared scopes already share the 16 MiB frame budget. Group their exact\n'
                          b'    # ordered records when the existing ingestion count bound permits it.\n'
                          b'    if len(batches)>1 and sum(map(len,batches))<=2048:\n'
                          b'        batches=[tuple(row for batch in batches for row in batch)]\n')
                self.assertEqual(current.count(grouping),1,rel)
                current=current.replace(grouping,b'')
                # Exactly reviewed pre-entry expiry; every other source byte pinned.
                gate=b"                        # Refuse an expired queued command before native arbitration.\n                        # FIFO, debt deadlines and the owner lease stay unchanged.\n                        if time.monotonic()-submitted>runtime.leases.owner:\n                            raise EvidenceUnavailable('evidence_command_expired')\n"
                reject=b"if str(exc) in ('evidence_admission_offer_expired','evidence_admission_offer_unavailable'):\n                        continue"
                retry=b"if str(exc) in ('evidence_admission_offer_expired','evidence_admission_offer_unavailable','evidence_command_expired'):\n                        await asyncio.sleep(0)\n                        continue"
                for part in (gate,retry):
                    self.assertEqual(current.count(part),1,rel)
                current=current.replace(gate,b'').replace(retry,reject)
            if rel in ('meme_machine/lanes/pump/solana_evidence_runtime.py','meme_machine/lanes/meteora/solana_evidence_runtime.py'):
                # Admit only the exact reviewed reader-ownership plumbing.
                # Every existing query, control and policy byte remains pinned.
                property_block=b"""    @property
    def reader(self):
        # The facade may be shared with a position worker; SQLite handles may not.
        if not hasattr(self._thread_readers,'reader'):
            try:self._thread_readers.reader=EvidenceReader(self.path)
            except sqlite3.Error:self._thread_readers.reader=None
        return self._thread_readers.reader
    @reader.setter
    def reader(self,value):
        self._thread_readers.reader=value
"""
                allocation=b"        self._thread_readers=threading.local()\n"
                close_block=b"""    def close(self):
        # Closing a worker must neither open a new handle nor close another owner.
        reader=getattr(self._thread_readers,'reader',None)
        if reader:reader.close()
        self._thread_readers.reader=None
"""
                for part in (property_block,allocation,close_block,b'import sqlite3\nimport threading\n'):
                    self.assertEqual(current.count(part),1,rel)
                current=current.replace(property_block,b'').replace(allocation,b'')
                current=current.replace(b'import sqlite3\nimport threading\n',b'import sqlite3\n')
                current=current.replace(close_block,b'    def close(self):\n        if self.reader:self.reader.close()\n')
            if rel=='meme_machine/lanes/pump/solana_evidence_consumers.py':
                # Optional provider observation may never initialize missing state.
                added=b"            from pathlib import Path\n            db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)\n"
                original=b'            db=sqlite3.connect(path,timeout=.1)\n'
                self.assertEqual(current.count(added),1,rel)
                current=current.replace(added,original)
            if rel=='meme_machine/lanes/pons/pons_selective_capital.py':
                # Only a consistent read snapshot for native terminal recovery.
                added=b"        with closing(sleeve),closing(self._connect()) as db:\n            db.execute('BEGIN')\n"
                original=b"        with closing(sleeve),closing(self._connect()) as db:\n"
                self.assertEqual(current.count(added),1,rel)
                current=current.replace(added,original)
            if rel in ('meme_machine/lanes/pump/pipeline.py','meme_machine/lanes/meteora/pipeline.py','meme_machine/lanes/ramses/pipeline.py'):
                # Only remove dangling cleanup for a table these lanes never create.
                removed=b"                    self.db.execute('DELETE FROM progress_sources WHERE sequence<(SELECT MAX(p.sequence) FROM progress_sources p WHERE p.source=progress_sources.source)')\n"
                anchor=b"                    audit_ring(self.db,'progress','progress_no_delete',key='sequence')\n"
                self.assertEqual(current.count(removed),0,rel)
                self.assertEqual(baseline(rel).count(removed),1,rel)
                self.assertEqual(current.count(anchor),1,rel)
                current=current.replace(anchor,anchor+removed)
            if rel in ('meme_machine/lanes/pons/pons_selective_acquisition.py','meme_machine/lanes/pons/provider_topology.py','meme_machine/lanes/ramses/provider_topology.py'):
                # Optional hint shape fallback only; every other source byte pinned.
                expanded=b'except (OSError,ValueError,KeyError,TypeError,AttributeError):pass'
                original=b'except (OSError,ValueError,KeyError):pass'
                expected=2 if rel.endswith('pons_selective_acquisition.py') else 1
                self.assertEqual(current.count(expanded),expected,rel)
                self.assertEqual(baseline(rel).count(original),expected,rel)
                current=current.replace(expanded,original)
            if rel in ('meme_machine/lanes/pump/solana_evidence_health.py','meme_machine/lanes/meteora/solana_evidence_health.py','meme_machine/lanes/pump/solana_evidence_plane.py','meme_machine/lanes/meteora/solana_evidence_plane.py'):
                # Only single-stat disappearing-WAL size accounting is permitted.
                added=b'from meme_machine.runtime.sqlite_files import transient_file_size\n'
                self.assertEqual(current.count(added),1,rel)
                current=current.replace(added,b'')
                pairs=[(b"sum(transient_file_size(p) for p in (reader.path,Path(str(reader.path)+'-wal')))",b"sum(p.stat().st_size for p in (reader.path,Path(str(reader.path)+'-wal')) if p.exists())")] if rel.endswith('solana_evidence_health.py') else [
                    (b"sum(transient_file_size(p) for p in (self.path,Path(str(self.path)+'-wal')))",b"sum(p.stat().st_size for p in (self.path,Path(str(self.path)+'-wal')) if p.exists())"),
                    (b"sum(transient_file_size(p) for p in (self.path, Path(str(self.path)+'-wal')))",b"sum(p.stat().st_size for p in (self.path, Path(str(self.path)+'-wal')) if p.exists())"),
                    (b"transient_file_size(Path(str(self.path)+'-wal'))",b"(Path(str(self.path)+'-wal').stat().st_size if Path(str(self.path)+'-wal').exists() else 0)")]
                for changed,original in pairs:
                    self.assertEqual(current.count(changed),1,rel)
                    current=current.replace(changed,original)
            if rel.endswith('/solana_evidence_plane.py'):
                # Exact bounded address-index plumbing; source/economic bodies remain pinned.
                pairs=[
                    (b'publish as publish_storage, publish_addresses',b'publish as publish_storage'),
                    (b'scope_insertions={};address_cache={}',b'scope_insertions={}'),
                    (b'                    publish_addresses(self.db,record.identity,record.slot,row.addresses,address_cache)',
                     b"                    self.db.executemany('INSERT OR IGNORE INTO addresses VALUES(?,?,?)',\n"
                     b'                        [(address, record.identity, record.slot) for address in row.addresses])'),
                ]
                for changed,original in pairs:
                    self.assertEqual(current.count(changed),1,rel)
                    current=current.replace(changed,original)
            if rel.endswith('/solana_evidence_storage.py'):
                from hashlib import sha256
                start=current.index(b'def publish_addresses(')
                end=current.index(b'def publish(db,',start)
                helper=current[start:end]
                self.assertEqual(sha256(helper).hexdigest(),'c80eecd05fa687516733d14b043afd1b39d6f02e1135e4a2dc68b4e108dc429b',rel)
                current=current[:start]+current[end:]
            self.assertEqual(current,baseline(rel),rel)

    def test_resolved_startup_check_uses_config_only_no_oracle_calls_or_state(self):
        from meme_machine.operational.supervisor import validate_environment
        env={'MM_ROBINHOOD_READ_RPC_URL':'https://robinhood-mainnet.g.alchemy.com/v2/offline-fixture'}
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            self.assertIsNone(validate_environment(environ=env))


if __name__=='__main__':unittest.main()
