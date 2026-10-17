"""Security and economic-coverage regressions for the isolated PUBLIC sampler.

All RPC is mocked; never a live endpoint, PAPER service or portfolio.
"""
import ast
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
    def test_fixed_programs_match_production_and_decode_to_32_bytes(self):
        def configured(path, name):
            tree = ast.parse((SCRIPT.parents[2] / path).read_text())
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == name
                        for target in node.targets):
                    return ast.literal_eval(node.value)
            self.fail('missing production program constant: '+name)
        for path in ('meme_machine/pump.py',
                     'meme_machine/lanes/pump/pump.py'):
            self.assertEqual(observer.PUMP_PROGRAM, configured(path, 'PROGRAM'))
        for path in ('meme_machine/postgrad.py',
                     'meme_machine/lanes/pump/postgrad.py'):
            self.assertEqual(observer.PUMPSWAP_PROGRAM,
                             configured(path, 'PUMPSWAP_PROGRAM'))
        programs=configured('meme_machine/solana_selective_history.py','PROGRAMS')
        self.assertEqual(observer.PUMP_PROGRAM,programs['pump'])
        self.assertEqual(observer.PUMPSWAP_PROGRAM,programs['pumpswap'])
        for value in (observer.PUMP_PROGRAM, observer.PUMPSWAP_PROGRAM, '1'*32):
            self.assertEqual(observer._solana_program(value),value)
        # AWS 39053728978 rejected the truncated, 30-byte PumpSwap address.
        for value in ('pAMMBay6oceH9fJKBRHGP5D4sWpmSwMn52FMfXEA',
                      '0'*44, '1'*31, '1'*33, None):
            with self.subTest(value=value), self.assertRaisesRegex(
                    observer.ObservationUnavailable,'solana_program_invalid'):
                observer._solana_program(value)

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

    def test_rpc_rejection_retains_only_approved_method_and_integer_code(self):
        for code, expected in ((-32602,-32602), ('SECRET_CANARY',None),
                               (True,None), (2**64,None)):
            def transport(endpoint,payload):
                packet=json.loads(payload)
                return json.dumps(dict(jsonrpc='2.0',id=packet['id'],
                    error=dict(code=code,message='SECRET_CANARY',
                               data={'endpoint':'SECRET_CANARY'}))).encode()
            rpc=observer.RPC(transport=transport,clock=lambda:42,sleeper=lambda _:None)
            with self.subTest(code=code), self.assertRaisesRegex(
                    observer.ObservationUnavailable,'^rpc_rejected$'):
                rpc.call(observer.SOLANA,'getSignaturesForAddress',
                         [observer.PUMPSWAP_PROGRAM,{'limit':32}])
            self.assertEqual(rpc.rejection,
                             dict(method='getSignaturesForAddress',code=expected))
            self.assertNotIn('SECRET_CANARY',json.dumps(rpc.rejection))


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
    def test_invalid_fixed_program_refused_before_any_provider_call(self):
        client=types.SimpleNamespace(call=lambda *_:self.fail('provider contacted'))
        with patch.object(observer,'PUMPSWAP_PROGRAM',
                          'pAMMBay6oceH9fJKBRHGP5D4sWpmSwMn52FMfXEA'):
            with self.assertRaisesRegex(observer.ObservationUnavailable,
                                        'solana_program_invalid'):
                observer.Observer(client,self.journal)
        self.assertEqual(self.journal.summary(),{})

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

    def test_public_provider_finalized_head_race_excludes_future_without_aborting(self):
        """Observed AWS 39051089747: signatures can outrun sampled finalized slot.

        A reference ahead of *this* independent head is never treated as a
        finalized trade, but does not abort a 120-second keyless sample.
        """
        heads=iter([100,108])
        counts={observer.PUMP_PROGRAM:0,observer.PUMPSWAP_PROGRAM:0}
        def response(endpoint,method,params):
            if method=='getSlot':return next(heads)
            if method=='getSignaturesForAddress':
                program=params[0]
                counts[program]+=1
                if program==observer.PUMP_PROGRAM:
                    return ([dict(signature='1'*64,slot=103),
                             dict(signature='2'*64,slot=100)] if counts[program]==1
                            else [dict(signature='1'*64,slot=103),
                                  dict(signature='2'*64,slot=100)])
                return [dict(signature='3'*64,slot=106)]
            raise AssertionError('unexpected method '+method)
        client=types.SimpleNamespace(call=response,attempts=0,rate_limited=0)
        o=observer.Observer(client,self.journal)
        o.solana(0)
        self.assertEqual(o.unverified_future,
            dict(solana_pump=1,solana_pumpswap=1))
        self.assertEqual(o.last_signature['solana_pump'],'2'*64)
        self.assertIsNone(o.last_signature['solana_pumpswap'])
        before=self.journal.summary()
        self.assertEqual(before['solana_pump']['written'],1)
        self.assertEqual(before['solana_pumpswap']['written'],0)
        self.assertEqual(before['solana_pump']['possible_gaps'],1)
        self.assertEqual(before['solana_pumpswap']['possible_gaps'],1)
        self.assertEqual(self.journal.db.execute('SELECT max(head) FROM observations '
            'WHERE lane=?',('solana_pump',)).fetchone()[0],100)
        o.solana(1)
        after=self.journal.summary()
        self.assertEqual(o.unverified_future,dict(solana_pump=1,solana_pumpswap=1))
        self.assertEqual(after['solana_pump']['written'],2)
        self.assertEqual(after['solana_pumpswap']['written'],1)
        self.assertEqual(o.last_signature['solana_pump'],'1'*64)
        self.assertEqual(o.last_signature['solana_pumpswap'],'3'*64)
        self.assertEqual(after['solana_pumpswap']['possible_gaps'],1)
        self.assertTrue(all(head<=108 for (head,) in self.journal.db.execute(
            'SELECT head FROM observations')))

    def test_finalized_pages_precede_independent_head_and_still_exclude_true_future(self):
        """AWS 39055008603 excluded all 1,280 references under head-first sampling.

        The provider here reports head 100 if sampled first and head 104 after
        the two paced pages. Every reference is newer than 100. Slot 105 still
        cannot be promoted by the later independently reported head 104.
        """
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        pages={observer.PUMP_PROGRAM:[dict(signature='1'*63+alphabet[index],
                                          slot=101+index%3) for index in range(32)],
               observer.PUMPSWAP_PROGRAM:[dict(signature='2'*63+alphabet[index],
                                              slot=102+index%3) for index in range(32)]}
        pages[observer.PUMPSWAP_PROGRAM][-1]['slot']=105
        self.assertTrue(all(row['slot']>100 for page in pages.values() for row in page))
        calls=[];now=[0]
        def transport(endpoint,payload):
            packet=json.loads(payload)
            method=packet['method'];params=packet['params']
            calls.append((endpoint,method,params,now[0]))
            if method=='getSignaturesForAddress':
                self.assertEqual(params[1],dict(limit=32,commitment='finalized'))
                result=pages[params[0]]
            elif method=='getSlot':
                self.assertEqual(params,[dict(commitment='finalized')])
                result=104 if len(calls)==3 else 100
            else:self.fail('unexpected RPC method')
            return json.dumps(dict(jsonrpc='2.0',id=packet['id'],result=result)).encode()
        def sleep(delta):now[0]+=delta
        rpc=observer.RPC(transport=transport,sleeper=sleep,clock=lambda:now[0])
        o=observer.Observer(rpc,self.journal)
        o.solana(0)
        self.assertEqual([method for _,method,_,_ in calls],
            ['getSignaturesForAddress','getSignaturesForAddress','getSlot'])
        self.assertEqual([params[0] for _,_,params,_ in calls[:2]],
                         [observer.PUMP_PROGRAM,observer.PUMPSWAP_PROGRAM])
        self.assertEqual([at for _,_,_,at in calls],[0,1,2])
        self.assertEqual(rpc.attempts,3)
        self.assertEqual(o.heads['solana'],[104])
        self.assertEqual(o.unverified_future,dict(solana_pump=0,solana_pumpswap=1))
        summary=self.journal.summary()
        self.assertEqual(summary['solana_pump']['written'],32)
        self.assertEqual(summary['solana_pumpswap']['written'],31)
        self.assertEqual(summary['solana_pump']['possible_gaps'],1)
        self.assertEqual(summary['solana_pumpswap']['possible_gaps'],1)
        self.assertEqual(self.journal.db.execute('SELECT count(*),max(head) '
            'FROM observations').fetchone(),(63,104))
        self.assertEqual(o.last_signature['solana_pumpswap'],
                         pages[observer.PUMPSWAP_PROGRAM][0]['signature'])

    def test_pages_without_independent_finalized_head_never_reach_journal(self):
        calls=[]
        def response(endpoint,method,params):
            calls.append(method)
            if method=='getSignaturesForAddress':
                return [dict(signature='1'*64,slot=101)]
            if method=='getSlot':raise observer.ObservationUnavailable('provider_429')
            self.fail('unexpected RPC method')
        client=types.SimpleNamespace(call=response,attempts=0,rate_limited=0)
        o=observer.Observer(client,self.journal)
        with self.assertRaisesRegex(observer.ObservationUnavailable,'provider_429'):
            o.solana(0)
        self.assertEqual(calls,['getSignaturesForAddress','getSignaturesForAddress','getSlot'])
        self.assertEqual(self.journal.summary(),{})
        self.assertEqual(o.heads['solana'],[])
        self.assertEqual(o.last_signature,dict(solana_pump=None,solana_pumpswap=None))

    def test_all_future_references_keep_prior_overlap_and_log_gap(self):
        heads=iter([101,100])
        count=[0]
        def response(endpoint,method,params):
            if method=='getSlot':return next(heads)
            if method=='getSignaturesForAddress':
                if params[0]==observer.PUMP_PROGRAM:
                    count[0]+=1
                    if count[0]==1:
                        return [dict(signature='1'*64,slot=101)]
                    return [dict(signature='4'*64,slot=105)]
                return []
            raise AssertionError('unexpected method')
        client=types.SimpleNamespace(call=response,attempts=0,rate_limited=0)
        o=observer.Observer(client,self.journal)
        o.solana(0)
        self.assertEqual(o.last_signature['solana_pump'],'1'*64)
        o.solana(1)
        self.assertEqual(o.last_signature['solana_pump'],'1'*64)
        self.assertEqual(o.regressed_finalized_heads,1)
        self.assertEqual(o.unverified_future['solana_pump'],1)
        summary=self.journal.summary()['solana_pump']
        self.assertEqual(summary['written'],1)
        self.assertEqual(summary['samples'],2)
        self.assertEqual(summary['possible_gaps'],1)
        self.assertEqual(self.journal.db.execute(
            'SELECT count(*) FROM observations').fetchone()[0],1)

    def test_malformed_future_signature_is_still_refused(self):
        def response(endpoint,method,params):
            if method=='getSlot':return 100
            if method=='getSignaturesForAddress':
                return [dict(signature='BAD',slot=105)]
            raise AssertionError('unexpected method')
        client=types.SimpleNamespace(call=response,attempts=0,rate_limited=0)
        o=observer.Observer(client,self.journal)
        with self.assertRaisesRegex(observer.ObservationUnavailable,
                                    'solana_signature_identity'):
            o.solana(0)
        self.assertEqual(self.journal.summary(),{})

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
