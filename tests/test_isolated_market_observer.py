"""Security and economic-coverage regressions for the isolated PUBLIC sampler.

All RPC is mocked; never a live endpoint, PAPER service or portfolio.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPT = Path(__file__).resolve().parents[1] / 'meme_machine/operational/isolated_market_observer.py'
spec = importlib.util.spec_from_file_location('isolated_public_market_observer', SCRIPT)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'bounded'
        self.root.mkdir(mode=0o700)
        self.journal=observer.DisposableJournal(self.root)
        self.addCleanup(self.journal.close)


class RPCBoundaries(unittest.TestCase):
    def test_rpc_is_fixed_endpoint_method_and_bounded_response(self):
        calls = []
        def transport(endpoint, payload):
            facts=json.loads(payload)
            calls.append((endpoint, facts))
            return json.dumps(dict(jsonrpc='2.0', id=facts['id'], result=123)).encode()
        rpc=observer.RPC(transport=transport, sleeper=lambda _:None,
            clock=lambda:10, max_requests=2)
        self.assertEqual(rpc.call(observer.SOLANA, 'getSlot', []),123)
        self.assertEqual(rpc.call(observer.ROBINHOOD,'eth_blockNumber',[]),123)
        self.assertEqual(rpc.attempts,2)
        for endpoint, method in (
                (observer.SOLANA,'sendTransaction'),
                (observer.ROBINHOOD,'eth_sendRawTransaction'),
                ('http://127.0.0.1:8545','eth_blockNumber'),
                ('https://provider.invalid','getSlot')):
            with self.subTest(endpoint=endpoint,method=method), \
                    self.assertRaisesRegex(observer.ObservationUnavailable,
                                           'method_or_endpoint_not_approved'):
                rpc.call(endpoint,method,[])
        self.assertEqual(len(calls),2)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'rpc_request_ceiling'):
            rpc.call(observer.SOLANA,'getSlot',[])
        self.assertNotIn('Authorization',str(calls))

    def test_invalid_identity_provider_error_and_limit_fail_closed(self):
        def transport(endpoint,payload):
            return json.dumps(dict(jsonrpc='2.0',id=9,result=12)).encode()
        rpc=observer.RPC(transport=transport,clock=lambda:42,sleeper=lambda _:None)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'rpc_response_identity'):
            rpc.call(observer.SOLANA,'getSlot',[])
        self.assertEqual(rpc.attempts,1)
        rpc=observer.RPC(transport=lambda e,p:b'{',
            clock=lambda:42,sleeper=lambda _:None)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'rpc_decode_error'):
            rpc.call(observer.SOLANA,'getSlot',[])
        rpc=observer.RPC(transport=lambda e,p:b'x'*(observer.MAX_RESPONSE+1),
            clock=lambda:42,sleeper=lambda _:None)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'rpc_response_bound'):
            rpc.call(observer.SOLANA,'getSlot',[])
        def too_many(endpoint,packet):
            raise HTTPError(endpoint,429,'limited',{},None)
        rpc=observer.RPC(transport=too_many,clock=lambda:42,sleeper=lambda _:None)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'provider_429'):
            rpc.call(observer.SOLANA,'getSlot',[])
        self.assertEqual(rpc.rate_limited,1)


class DurableIsolation(Scratch):
    def test_commit_reopen_duplicate_and_no_completeness_promotion(self):
        one=observer.digest('one')
        two=observer.digest('two')
        row=[(one,100,{'at':100,'valid':True})]
        self.assertEqual(self.journal.record(0,'solana_pump',101,row,True),1)
        self.assertEqual(self.journal.record(1,'solana_pump',102,row,False),0)
        self.assertEqual(self.journal.record(2,'robinhood_pons',105,
            [(two,105,{'block':105})],True),1)
        summary=self.journal.summary()
        self.assertEqual(summary['solana_pump'],dict(
            samples=2,possible_gaps=1,offered=2,written=1,duplicates=1))
        self.assertEqual(summary['robinhood_pons']['written'],1)
        self.assertEqual(self.journal.written,2)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'future_event_refused'):
            self.journal.record(3,'solana_pump',101,[(two,102,{'slot':102})],False)
        self.assertEqual(self.journal.db.execute(
            'SELECT count(*) FROM measurements').fetchone()[0],3)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'lane_invalid'):
            self.journal.record(3,'real_portfolio',105,[],False)
        self.assertEqual({p.name for p in self.root.iterdir()},
                         {'sample.sqlite3'})

    def test_filename_is_disposable_fails_existing_or_symlink(self):
        with self.assertRaisesRegex(OSError,'File exists'):
            observer.DisposableJournal(self.root)
        linked=self.root.parent/'bad'
        linked.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'scratch_directory_required'):
            observer.DisposableJournal(linked)
        wrong=self.root.parent/'world_writable'
        wrong.mkdir(mode=0o777)
        wrong.chmod(0o777)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'scratch_permissions'):
            observer.DisposableJournal(wrong)


class SampleBoundaries(Scratch):
    def fixture_rpc(self,*,bad_chain=False):
        seen=[]
        slots=[100,102,108]
        blocks=[222,224,231]
        def response(endpoint,method,params):
            seen.append((endpoint,method,params))
            if method=='getSlot':return slots.pop(0)
            if method=='getSignaturesForAddress':
                program=params[0]
                if program==observer.PUMP_PROGRAM:
                    return [dict(signature='1'*64,slot=100)]
                return [dict(signature='2'*64,slot=100)]
            if method=='eth_chainId':return '0x1238' if bad_chain else '0x1237'
            if method=='eth_blockNumber':return hex(blocks.pop(0))
            if method=='eth_getLogs':
                return [dict(address=observer.PONS_FACTORY,
                    blockNumber=params[0]['toBlock'],transactionHash='0x'+'12'*32,
                    logIndex='0x0',removed=False)]
            raise AssertionError('unexpected RPC method')
        return types.SimpleNamespace(call=response,attempts=0,rate_limited=0,seen=seen)

    def test_realistic_reference_samples_dedupe_but_mark_gaps(self):
        client=self.fixture_rpc()
        o=observer.Observer(client,self.journal)
        o.solana(0);o.pons(0)
        o.solana(1);o.pons(1)
        o.solana(2);o.pons(2)
        totals=self.journal.summary()
        self.assertEqual(totals['solana_pump']['offered'],3)
        self.assertEqual(totals['solana_pump']['written'],1)
        self.assertEqual(totals['robinhood_pons']['written'],3)
        self.assertEqual(totals['robinhood_pons']['possible_gaps'],1)
        self.assertEqual([h for h in o.heads['solana']],[100,102,108])
        self.assertEqual([h for h in o.heads['robinhood']],[222,224,231])
        q=[params for endpoint,method,params in client.seen if method=='eth_getLogs']
        self.assertEqual([(x[0]['fromBlock'],x[0]['toBlock']) for x in q],
                         [('0xde','0xde'),('0xdf','0xe0'),('0xe5','0xe7')])
        self.assertIs(o.pons_chain_verified,True)

    def test_wrong_chain_refused_without_fabricated_pons_journal(self):
        client=self.fixture_rpc(bad_chain=True)
        o=observer.Observer(client,self.journal)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'pons_chain_mismatch'):
            o.pons(0)
        self.assertEqual(self.journal.summary(),{})

    def test_runnable_observation_always_denies_market_parity_and_financial_authority(self):
        client=self.fixture_rpc()
        o=observer.Observer(client,self.journal)
        now=[0]
        def clock():return now[0]
        def sleep(delta):now[0]+=delta
        result=o.run(duration=12,interval=6,clock=clock,sleeper=sleep)
        self.assertEqual(result['result'],'SAMPLED')
        self.assertEqual(result['completed_ticks'],2)
        self.assertEqual(result['scope'],'ISOLATED_PUBLIC_RPC_SAMPLED_REFERENCE_ONLY')
        for key in ('financial_authority','paper_started','production_state_written',
                    'original_history_recovered','full_market_speed_proven',
                    'complete_economic_coverage_proven'):
            self.assertIs(result[key],False)
        self.assertEqual(result['head_start_end']['solana'],[100,102])
        with self.assertRaisesRegex(observer.ObservationUnavailable,'duration_bound'):
            o.run(duration=7200,interval=6)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'interval_bound'):
            o.run(duration=60,interval=1)


class HostIsolation(unittest.TestCase):
    def test_rejects_meme_machine_environment_privilege_or_wallet_secrets(self):
        good=dict(GITHUB_RUN_ID='1234',RUNNER_TEMP='/tmp')
        with patch.object(observer.os,'geteuid',return_value=1001), \
             patch.object(observer.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_uid=999)), \
             patch.object(observer.os,'access',return_value=False):
            observer.safe_runtime(good)
            for key in ('MM_STATE_ROOT','MM_PORTFOLIO_ACCOUNTING_DB',
                        'AWS_SECRET_KEY','ALCHEMY_KEY'):
                with self.subTest(key=key), \
                     self.assertRaisesRegex(observer.ObservationUnavailable,'production_environment_inherited'):
                    observer.safe_runtime(dict(good,**{key:'UNUSABLE_SECRET_CANARY'}))
            with patch.object(observer.os,'access',return_value=True):
                with self.assertRaisesRegex(observer.ObservationUnavailable,
                                            'production_state_write_access_forbidden'):
                    observer.safe_runtime(good)
            with patch.object(observer.pwd,'getpwnam',return_value=types.SimpleNamespace(pw_uid=1001)):
                with self.assertRaisesRegex(observer.ObservationUnavailable,'production_service_user_forbidden'):
                    observer.safe_runtime(good)
        with patch.object(observer.os,'geteuid',return_value=0):
            with self.assertRaisesRegex(observer.ObservationUnavailable,'root_worker_forbidden'):
                observer.safe_runtime(good)

    def test_normal_market_observer_module_has_no_trading_or_private_state_imports(self):
        src=SCRIPT.read_text()
        forbidden=('from meme_machine.shared_capital','import meme_machine.shared_capital',
                   'from meme_machine.operational.supervisor',
                   'from meme_machine.runtime.sleeve_reservations','eth_sendRawTransaction',
                   'sendTransaction', 'private_key', 'mnemonic', 'MM_PORTFOLIO_ACCOUNTING_DB')
        # The safety test names forbidden strings, so examine only the actual
        # module body; no wallet, investment or provider write API is reachable.
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value,src)


if __name__=='__main__':
    unittest.main()
