"""Deterministic transports for the existing proof, never production authority.

Recorded Pump messages retain their clocks/order; Pons uses the repository's
explicitly synthetic offline tape. Neither is an invented live eligible sample.
"""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import io
import json
from pathlib import Path
import threading
import time
import unittest
from urllib.request import Request
from .proof_limits import CeilingReached,endpoint_family

ROOT=Path(__file__).resolve().parents[2]
SOL='https://solana-mainnet.g.alchemy.com/v2/offline-test'
PONS='https://robinhood-mainnet.g.alchemy.com/v2/offline-test'


class FakeResponse(io.BytesIO):
    status=200
    headers={}


class FakeHTTP:
    def __init__(self):
        from tests.test_robinhood_scout import ObservationTape
        self.tape=ObservationTape(candidates=1,max_range=10)
        self.tape.top=self.tape.grad
        self.accounts=json.loads((ROOT/'tests/lanes/pump/fixtures/mainnet_candidate_accounts.json').read_text())
        self.trade=json.loads((ROOT/'tests/lanes/pump/fixtures/mainnet_trade.json').read_text())
        self.calls=[];self.lock=threading.RLock()
    def __call__(self,request,**kw):
        with self.lock:
            payload=json.loads(request.data);batch=isinstance(payload,list);rows=payload if batch else [payload]
            family=endpoint_family(request.full_url);answer=[]
            for row in rows:
                method,params=row['method'],row['params'];self.calls.append((family,method,deepcopy(params)))
                if family=='robinhood':value=self.tape._read(method,params)
                elif method=='getGenesisHash':
                    from meme_machine.solana_provider_config import GENESIS
                    value=GENESIS
                elif method=='getSlot':value=self.accounts['response']['context']['slot']
                elif method=='getMultipleAccounts' and params[0]==self.accounts['addresses']:value=self.accounts['response']
                elif method=='getTransaction' and params[0]==self.trade['signature']:value=self.trade['response']
                else:raise ValueError('unrecorded_fake_rpc')
                answer.append(dict(jsonrpc='2.0',id=row['id'],result=deepcopy(value)))
            return FakeResponse(json.dumps(answer if batch else answer[0],separators=(',',':')).encode())


def capital_fixtures(out):
    """Original native contention fixtures, exclusively in disposable state."""
    names=[
      'tests.lanes.pump.test_pump_acceleration_strategy.PumpAccelerationStrategyTests.test_strong_late_curve_can_qualify',
      'tests.lanes.pump.test_pumpswap_survivor.SurvivorTests.test_valid_survival_reset_base_continuation',
      'tests.lanes.pons.test_pons_selective_continuation.PonsSelectivePolicyTests.test_clean_late_curve_acceleration_can_qualify',
      'tests.lanes.pons.test_pons_postgrad_survivor.PonsPostgradSurvivorTests.test_open_market_style_survivor_breakout_qualifies',
      'tests.test_pump_pons_capital_preparation.RuntimeIntegrationTests.test_four_native_regimes_share_one_atomic_round_from_independent_connections',
      'tests.test_pump_pons_capital_preparation.RuntimeIntegrationTests.test_queued_deadline_is_preserved_and_expired_qualification_is_not_erased',
      'tests.lanes.pons.test_pons_finalization.CurrentRecheckEvidenceTests.test_age_gate_reopens_without_new_trade_using_real_receipt_decoder_and_current_state',
    ]
    suite=unittest.defaultTestLoader.loadTestsFromNames(names);log=io.StringIO()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (out/'capital-fixtures.log').write_text(log.getvalue())
    if not result.wasSuccessful():raise ValueError('original_capital_fixture_failed')
    return dict(tests=result.testsRun,passed=True,qualification_precedes_funding=True,
        four_native_regimes=True,production_books_opened=0,fixture_books='disposable original offline fixtures only')


async def offline_workload(out,budget,queues,transports):
    from meme_machine.lanes.pons.provider_topology import configured_rpc
    from meme_machine.lanes.pons.pons_natural_observation import MarketScout
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,POLICY_HASH
    from meme_machine.lanes.pons.pons_history import PonsHistory
    from meme_machine.lanes.pons.pons_attempts import Attempts
    from meme_machine.runtime.robinhood.plane import Plane
    from meme_machine import pump
    from meme_machine.solana_program_decoders import pump_events
    fake=transports.opener;result={};errors=[];stop=threading.Event();both=threading.Barrier(2)
    capital=dict(tests=0,passed=False)
    def raw_call(method,params):
        request=Request(SOL,json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),headers={'Content-Type':'application/json'})
        with transports.open(request) as response:return json.loads(response.read())['result']
    def pump_worker():
        try:
            both.wait(timeout=10)
            # Acquire the preserved quote/economic sample independently of
            # source replay startup and without claiming a funded position.
            decoded=pump_events(raw_call('getTransaction',[fake.trade['signature'],dict(encoding='json')]))
            result['pump_recorded_economic_events']=len(decoded)
            accounts=raw_call('getMultipleAccounts',[fake.accounts['addresses'],dict(encoding='base64')])
            curve=pump.curve(accounts['value'][0]);supply,_=pump.mint_info(accounts['value'][1])
            fees=pump.fees(accounts['value'][2],curve,supply);quote=pump.sell(curve,1_000_000_000,fees)
            result['pump_exit_quote_path']=dict(amount_out=str(quote[0]),authentic_position=False)
            result['pump_replay']=recorded_pump(out/'pump-replay',budget,queues,on_ready=lambda:result.update(pump_native_ready=True))
            while not stop.is_set() and not budget.admissions_stopped.is_set():
                identity='pump-account:'+str(budget.fake_dispatches)
                with queues.work(identity,queue='pump-read'):
                    accounts=raw_call('getMultipleAccounts',[fake.accounts['addresses'],dict(encoding='base64')])
                    # Actual canonical account decoding/sell quote, original
                    # deterministic quote input: never an authentic funded position.
                    curve=pump.curve(accounts['value'][0]);supply,_=pump.mint_info(accounts['value'][1])
                    fees=pump.fees(accounts['value'][2],curve,supply);quote=pump.sell(curve,1_000_000_000,fees)
                    result['pump_exit_quote_path']=dict(amount_out=str(quote[0]),authentic_position=False)
                stop.wait(1)
        except CeilingReached as exc:
            if exc.reason!='admission_closed':errors.append(exc.reason)
        except BaseException as exc:
            from .certify import safe_reason
            errors.append('pump_fake_'+safe_reason(exc));print(errors[-1],flush=True)

    def pons_worker():
        runtime=None;plane=None;history=None
        try:
            both.wait(timeout=10)
            p=out/'pons';p.mkdir()
            source_clock=lambda:int(fake.tape.header(fake.tape.top)['timestamp'],16)
            plane=Plane(p/'plane.sqlite',clock=source_clock);scout=MarketScout(plane)
            history=PonsHistory(p/'history.sqlite',policy=POLICY_HASH)
            runtime=Runtime.__new__(Runtime);runtime.root=p;runtime.history=history;runtime.plane=plane;runtime.scout=scout
            runtime.attempts=Attempts(plane);runtime.current=None;runtime.endpoint=PONS;runtime.now=source_clock
            runtime.rpc=configured_rpc(PONS,limit=200,per_scope=200,retries=0);runtime.deployments_verified=True
            # Preserved fixture clocks remain source clocks, separate from the
            # real monotonic observation/queue/resource clock.
            runtime.discover()
            plan=deepcopy(history.get_meta('pons_forward_plan'))
            scout.read_market(runtime.rpc,fake.tape.grad-12,fake.tape.grad)
            for _ in range(30):
                runtime.discover()
                if not history.pending_graduations():break
            if not history.rows():raise ValueError('fake_lineage_sample_missing')
            before=deepcopy(history.rows());frontier=deepcopy(history.get_meta('pons_historical_frontier:forward_population'))
            # One bounded clean provider disconnect. Reopen the same checkpoint
            # and resume production forward discovery, with no failed-RPC retry.
            runtime.rpc=None;history.close()
            history=PonsHistory(p/'history.sqlite',policy=POLICY_HASH);runtime.history=history
            runtime.rpc=configured_rpc(PONS,limit=200,per_scope=200,retries=0)
            runtime.discover()
            after=history.rows()
            if before!=after or frontier!=history.get_meta('pons_historical_frontier:forward_population'):
                raise ValueError('checkpoint_resume_identity_changed')
            result['recovery']=dict(disconnects=1,resumed=True,checkpoint_identity_preserved=True,
                candidate_identities=[r['id'] for r in after],original_source_clocks_preserved=True,event_order_preserved=True,
                transport='deterministic fake disconnect and native PonsHistory reopen')
            result['pons_lineage_candidates']=len(after)
            result['pons_scout_events']=len(scout.events('launch'))+len(scout.events('graduation'))
            # Shared-pool acquisition after authenticated graduation, rather than
            # a separate broad economic scan. Preserve fixture header identities.
            fake.tape.top+=1;scout.read_market(runtime.rpc,fake.tape.top,fake.tape.top)
            scout.read_pools(runtime.rpc,fake.tape.top)
            for row in history.rows():runtime._increment_candidates([row],fake.tape.top)
            while not stop.is_set() and not budget.admissions_stopped.is_set():
                with queues.work('pons-header:'+str(budget.fake_dispatches),queue='pons-read'):
                    runtime._provider()
                    runtime.rpc.batch([('eth_getBlockByNumber',[hex(fake.tape.top),False]),('eth_chainId',[])],scope='offline-proof')
                stop.wait(1)
        except CeilingReached as exc:
            if exc.reason!='admission_closed':errors.append(exc.reason)
        except BaseException as exc:
            from .certify import safe_reason
            errors.append('pons_fake_'+safe_reason(exc));print(errors[-1],flush=True)
        finally:
            if history:history.close()
            if plane:plane.close()
    workers=[threading.Thread(target=pump_worker,name='offline-pump',daemon=True),threading.Thread(target=pons_worker,name='offline-pons',daemon=True)]
    for w in workers:w.start()
    try:
        startup_end=budget.started+budget.time['maximum_startup_seconds']
        while 'pump_native_ready' not in result or 'recovery' not in result:
            if errors:budget.fail(errors[0])
            if not all(w.is_alive() for w in workers):budget.fail('fake_worker_stopped')
            if budget.clock()>=startup_end:budget.fail('startup_ceiling')
            queues.poll();await asyncio.sleep(.05)
        budget.ready()
        while budget.clock()-budget.ready_at<budget.time['minimum_steady_seconds']:
            if errors:budget.fail(errors[0])
            budget.check_time();queues.poll();await asyncio.sleep(.05)
        if errors:budget.fail(errors[0])
        if 'pump_exit_quote_path' not in result:budget.fail('recorded_workload_incomplete')
        if queues.pending or queues.running:await asyncio.sleep(.05)
        result.update(workload='concurrent original recorded Pump replay and optimized Pons scout/history',
            capital_fixtures=capital,qualification_samples='original deterministic fixtures; never live samples',
            authentic_position_samples=0,live_books_opened=0,production_epoch_modified=False,
            paused_workloads=dict(meteora=0,ramses=0),
            insufficient=['synthetic_and_recorded_inputs_do_not_certify_live_capacity',
                'authentic_native_positions_not_available','new_Survivor_candidates_cannot_mature_in_300_seconds'])
        return result
    finally:
        budget.stop_work();stop.set()
        until=min(budget.started+299.5,budget.shutdown_at+19.5)
        for w in workers:w.join(timeout=max(0,until-budget.clock()))
        if any(w.is_alive() for w in workers):budget.reason=budget.reason or 'fake_worker_shutdown_incomplete'


def recorded_pump(out,budget,queues,*,on_ready=lambda:None):
    """Read the existing tape's declared address filters using native joins.

    The older comparison replayer assumed all candidate filters were program
    addresses. This proof-only adapter reads the actual saved subscriptions.
    Paused-family captures are excluded before fake transport acquisition, as
    this contract never subscribes to them. No original clock/body is changed.
    """
    import based58
    from collections import Counter
    from types import SimpleNamespace
    from .offline_replay import frames,digest_rows
    from .certify import PUMP,SWAP_MINT
    from meme_machine.postgrad import pumpswap_pool
    from meme_machine.solana_evidence_plane import EvidenceWriter
    from meme_machine.solana_evidence_service import FinalizedFence
    from meme_machine.solana_selective_source import install,commit_scout,commit_control,commit_candidates
    from meme_machine.solana_selective_history import PROGRAMS,coverage_scope
    from meme_machine.solana_candidate_join import CandidateTransactionJoin
    from meme_machine.solana_source_intake import candidate_log_message
    from meme_machine.yellowstone import geyser_pb2 as pb
    capture=ROOT/'engineering/solana_capacity/captures/final-shared14';path=capture/'provider.frames.zlib'
    families={PUMP:'pump',pumpswap_pool(SWAP_MINT):'pumpswap'}
    # Owner/program identities are immutable fixture routing metadata, not
    # future strategy evidence. Only the second pass publishes original clocks.
    for m,raw in frames(path):
        if m['kind']=='delivery' and m['transport']=='yellowstone':
            u=pb.SubscribeUpdate.FromString(raw)
            if u.WhichOneof('update_oneof')=='account':
                owner=based58.b58encode(bytes(u.account.account.owner)).decode();address=based58.b58encode(bytes(u.account.account.pubkey)).decode()
                for family,program in PROGRAMS.items():
                    if owner==program:families[address]=family
    out.mkdir();record=json.loads((capture/'result.json').read_text());wall=[record['measurement_started']]
    writer=EvidenceWriter(out/'canonical.sqlite',clock=lambda:wall[0]);state=SimpleNamespace(writer=writer,
        fence=FinalizedFence(writer,endpoint_identity=record['endpoint_identity']))
    h=install(state);h.clock=h.lifecycle.clock=lambda:wall[0]
    sessions={};websockets={};acks={};early=[];count=Counter();commits=[];start=time.monotonic();ready=[False]
    def commit(frame,sid):
        if frame is None:return
        addresses,join=sessions[sid]
        identity='recorded-native-commit:'+sid+':'+str(len(commits))
        # This is actual durable source work, not a fabricated strategy window.
        # Original candidate deadlines remain in the unchanged native lifecycle.
        with queues.work(identity,queue='pump-source'):
            if addresses:commit_candidates(state,frame,addresses,sid,publish=False)
            else:commit_control(state,frame)
            h.lifecycle.publish();commits.append((sid,frame.update.block.slot,frame.seen))
        if not ready[0] and count['scout_deliveries'] and writer.db.execute('SELECT 1 FROM candidate_checkpoints LIMIT 1').fetchone():
            ready[0]=True;on_ready()
    try:
        for meta,raw in frames(path):
            if budget.reason:raise CeilingReached(budget.reason)
            if budget.admissions_stopped.is_set():break
            if meta['kind']=='subscribe':
                req=pb.SubscribeRequest.FromString(raw);sid=meta['id']
                if req.accounts:continue
                addresses={address:coverage_scope(families[address],address) for f in req.transactions_status.values()
                    for address in f.account_include if families.get(address) in ('pump','pumpswap')}
                all_addresses={address for f in req.transactions_status.values() for address in f.account_include}
                if all_addresses and set(addresses)!=all_addresses:count['paused_or_unidentified_sessions_excluded']+=1;continue
                full={address for f in req.transactions.values() for address in f.account_include}
                join=CandidateTransactionJoin(addresses,full,clock=lambda:0.,filtered_from_slot=req.from_slot,max_join_seconds=120)
                # Preserve the exact recorded label-to-address declaration.
                join.filter_scopes={label:addresses[f.account_include[0]] for label,f in req.transactions_status.items()}
                sessions[sid]=(addresses,join)
                for slot,sig,logs,seen,address in early:
                    if address in addresses:commit(join.feed_log(slot,sig,logs,None,seen),sid)
                continue
            if meta['kind']=='websocket_open':websockets[meta['id']]=meta['addresses'];continue
            if meta['kind']!='delivery':continue
            wall[0]=meta['seen']
            if meta['transport']=='yellowstone':
                update=pb.SubscribeUpdate.FromString(raw)
                if update.WhichOneof('update_oneof')=='account':
                    if set(update.filters)!={'p'}:continue
                    budget.native('yellowstone',len(raw));count['scout_deliveries']+=1;commit_scout(state,update,wall[0])
                elif meta['id'] in sessions:
                    budget.native('yellowstone',len(raw));count['native_deliveries']+=1
                    if update.WhichOneof('update_oneof') in ('ping','pong'):continue
                    commit(sessions[meta['id']][1].feed(update,len(raw),wall[0]),meta['id'])
            else:
                value=candidate_log_message(raw,max_bytes=16*1024*1024)
                if 'id' in value:
                    address=websockets[meta['id']][value['id']-1];acks[meta['id'],value['result']]=address
                    if families.get(address) in ('pump','pumpswap'):budget.native('solana_websocket',len(raw))
                    continue
                params=value['params'];v=params['result']['value'];address=acks[meta['id'],params['subscription']]
                if families.get(address) not in ('pump','pumpswap'):continue
                budget.native('solana_websocket',len(raw));count['websocket_deliveries']+=1
                if v['err'] is not None:continue
                slot=params['result']['context']['slot'];matched=False
                for sid,(addresses,join) in sessions.items():
                    if address in addresses:matched=True;commit(join.feed_log(slot,v['signature'],v['logs'],None,wall[0]),sid)
                if not matched:early.append((slot,v['signature'],v['logs'],wall[0],address))
        while h.lifecycle.flush():pass
        h.lifecycle.publish()
        rows=[list(r) for r in writer.db.execute('SELECT identity,scope,slot,signature,transaction_index,event_index,hash,first_seen FROM canonical_evidence ORDER BY scope,slot,transaction_index,event_index,identity')]
        result=dict(canonical_count=len(rows),canonical_digest=digest_rows(rows),original_clock_rows=rows,
            counters=dict(count),source_sha256=__import__('hashlib').sha256(path.read_bytes()).hexdigest(),
            candidate_history_rows=writer.db.execute('SELECT COUNT(*) FROM candidate_lifecycle').fetchone()[0],
            candidate_checkpoints=writer.db.execute('SELECT COUNT(*) FROM candidate_checkpoints').fetchone()[0],
            unresolved_join_tails=sum(len(j.pending) for a,j in sessions.values()),seconds=time.monotonic()-start,
            replay_stopped_at_contract_boundary=budget.admissions_stopped.is_set(),
            limitations=['Recorded tape tails and unavailable pre-enrollment intervals stay incomplete.',
                'Paused-family recorded sessions are excluded from this contract, before fake delivery.',
                'Historical probe addresses do not constitute authentic positions.'])
        (out/'result.json').write_text(json.dumps(result,indent=2));return result
    finally:writer.close()
