"""Finite 300-second read-only Model B technical proof; offline by default.

Live execution requires --execute --authorized-live-proof, an explicit isolated
output and credentials file, and a pinned source commit. This is a deliberate
separate invocation, not an owner-permit/activation system. --child is private
and requires the supervising parent's inherited UNIX control socket.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from .proof_limits import (Budget, CeilingReached, QueueEvidence, load_contract, endpoint_family,
                           CONTRACT_PATH, STREAM_HOST,validate_native_bindings)


def observe_budgeted(budget,observer,kind,value):
    try:
        if kind=='delivery':budget.native('solana_websocket' if value.get('transport')=='websocket' else 'yellowstone',len(value['raw']))
    finally:observer(kind,value)


def pons(out,endpoint,budget,queues):
    """Use production discovery/authentication and read-only position functions.

    The Survivor controller constructor is intentionally unused: no native
    monetary book exists in this proof. Its evidence methods remain unchanged.
    Survivor discovery enrolls forward with the production runtime. No seven-day
    seed or census is an operational prerequisite. This technical harness still
    cannot certify full candidate qualification or native position acceptance.
    """
    from meme_machine.lanes.pons import BoundaryError
    from meme_machine.lanes.pons.pons_selective_cohort import _discovery,_discovery_curve_events
    from meme_machine.lanes.pons.pons_selective_acquisition import SelectiveEvidenceContext,evaluate_candidate
    from meme_machine.lanes.pons.pons_natural_observation import _latest_header
    from meme_machine.lanes.pons.pons_selective_paper import STRATEGY_CAPITAL_QUOTE
    from meme_machine.lanes.pons.provider_admission import position_work
    from meme_machine.lanes.pons.evidence import Store
    from meme_machine.lanes.pons.pons_survivor_runtime import Runtime,Quotes,POLICY_HASH
    from meme_machine.lanes.pons.pons_history import PonsHistory
    from meme_machine.runtime.robinhood.plane import Plane
    from meme_machine.lanes.pons.pons_attempts import Attempts
    out.mkdir(exist_ok=True);survivor=object.__new__(Runtime);survivor.root=out;survivor.endpoint=endpoint;survivor.rpc=None
    survivor.history=PonsHistory(out/'history.sqlite',policy=POLICY_HASH);survivor.plane=Plane(out/'candidates.sqlite')
    survivor.attempts=Attempts(survivor.plane);survivor.current=None
    from meme_machine.lanes.pons.pons_natural_observation import MarketScout
    survivor.scout=MarketScout(survivor.plane)
    # Nominal quote context has no capital authority or writable book.
    class TechnicalSizing:
        def sizing_basis(self,*a,**kw):return dict(target=STRATEGY_CAPITAL_QUOTE,minimum=max(1,STRATEGY_CAPITAL_QUOTE//1000),realized_equity=20*STRATEGY_CAPITAL_QUOTE)
    survivor.sleeve=TechnicalSizing()
    context=SelectiveEvidenceContext(endpoint);rpc=None;cursor=None;results=[];positions=[];coverage=[];errors=[];current=None;tape=[]
    from meme_machine.runtime.robinhood.pons import Broker
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as CURRENT_HASH
    broker=Broker(survivor.plane.path,CURRENT_HASH,source=endpoint)
    current_jobs={}
    def current_identity(scheduled):return 'pons-current:'+scheduled['key']+':'+str(scheduled['work']['generation'])
    def nominate(event,observed):
        broker.enqueue(event,now=observed,needs_work=event['topics'][0].lower()==survivor.scout.curve_topics[0])
        for scheduled in broker.rows.values():
            identity=current_identity(scheduled)
            if identity not in current_jobs:
                current_jobs[identity]=scheduled
                queues.enqueue(identity,kind='candidate',queue='pons-current',
                    deadline=budget.clock()+scheduled['deadline']-time.time(),
                    original_deadline=scheduled['deadline'],enqueued=budget.clock()+scheduled['queued_at']-time.time())
    def current_done(identity,*,error=None,cancelled=False):
        if identity in queues.pending or identity in queues.running:queues.finish(identity,error=error,cancelled=cancelled)
        current_jobs.pop(identity,None)
    try:
        while not budget.stop.is_set() and not budget.admissions_stopped.is_set():
            try:
                if rpc is None or rpc.used>150:rpc=_discovery(endpoint)
                header=_latest_header(rpc);top=int(header['number'],16)
                if cursor is None:cursor=max(0,top-1)
                end=min(top,cursor+40)
                if end>cursor:
                    observed=survivor.scout.read_market(rpc,cursor+1,end,nominate=nominate)
                    events=[event for _,event,_ in survivor.scout.events('curve') if cursor<int(event['blockNumber'],16)<=end]
                    survivor.scout.read_pools(rpc,top)
                    coverage.append(dict(first=cursor+1,last=end,events=len(events)));cursor=end;tape.extend(events)
                # Use the existing native Current broker: original nomination,
                # generation, five-second deadline and canonical refresh survive.
                scheduled=broker.pop(now=time.time())
                if scheduled is not None:
                    identity=current_identity(scheduled)
                    if identity not in current_jobs:
                        current_jobs[identity]=scheduled
                        queues.enqueue(identity,kind='candidate',queue='pons-current',
                            deadline=budget.clock()+scheduled['deadline']-time.time(),original_deadline=scheduled['deadline'],
                            enqueued=budget.clock()+scheduled['queued_at']-time.time())
                    queues.dispatch(identity);start=budget.clock();wall=scheduled['queued_at'];error=None
                    observed_monotonic=budget.clock()-max(0,time.time()-wall)
                    try:
                        result=evaluate_candidate(endpoint,scheduled['event'],list(tape),strategy_capital_quote=STRATEGY_CAPITAL_QUOTE,
                            evidence_context=context,evidence_observed_at=wall,evidence_observed_monotonic=observed_monotonic,
                            canonical_refresh=scheduled.get('canonical_refresh',False))
                        broker.finish(scheduled,result,budget.clock()-start);broker.acknowledge(scheduled)
                        results.append(dict(at=wall,seconds=budget.clock()-start,token=result['token'],
                            current_vector=result.get('vector',{}),original_deadline=scheduled['deadline']))
                    except BoundaryError as exc:
                        from .certify import safe_reason
                        error=safe_reason(exc);broker.failure(scheduled,error)
                        results.append(dict(at=wall,seconds=budget.clock()-start,reason=error,original_deadline=scheduled['deadline']))
                    finally:current_done(identity,error=error)
                for identity,old in list(current_jobs.items()):
                    row=broker.plane.get(old['key'])
                    if row is None or row['generation']!=old['work']['generation'] or not row['pending']:
                        current_done(identity,cancelled=True,error='native_superseded_or_deadline_disposition')
                queues.poll()
                # Quotes are acquisition evidence; no new/native position is
                # fabricated and no funded-position certification is claimed.
                survivor._provider();survivor.discover()
                for row in survivor.history.rows():
                    if row['state']=='retired':continue
                    started=time.monotonic()
                    try:
                        if survivor.scout is not None:
                            survivor._increment_candidates([row],top)
                        else:survivor._increment(row,min(top,row['block']+39))
                        from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY
                        age=survivor.now()-row['graduation']['at']
                        if age>=POLICY['universe']['min_seconds_after_graduation']:
                            with queues.work('pons-survivor:'+row['id']+':'+str(top),kind='candidate',wall_deadline=time.time()+5):
                                state=survivor.fresh_state(row['id'])
                                quotes=survivor.fresh_quotes(state,STRATEGY_CAPITAL_QUOTE)
                                decision=survivor.qualify(survivor.reconstruct(state,quotes))
                                positions.append(dict(regime='pons_survivor_candidate_qualification',seconds=time.monotonic()-started,
                                    qualified=decision['candidate'],authentic_position=False))
                    except BoundaryError as error:positions.append(dict(regime='pons_survivor',seconds=time.monotonic()-started,reason=str(error),ready=False))
            except CeilingReached as exc:
                if exc.reason!='admission_closed':budget.reason=budget.reason or exc.reason
                break
            except BoundaryError as error:errors.append(dict(type='BoundaryError',reason=str(error)))
            budget.stop.wait(.5)
    except Exception as error:
        # Unexpected errors carry a type only, never an endpoint-bearing repr.
        errors.append(dict(type=type(error).__name__,reason='unexpected_provider_proof_error'));budget.reason=budget.reason or 'pons_worker_failure';budget.stop.set()
    finally:
        status=dict(discovery_cursor=cursor,survivor_discovery_cursor=survivor.history.get_meta('discovery_block'),
            survivor_bootstrap=survivor.history.get_meta('discovery_bootstrap'),coverage=coverage,
            candidates=results,position_equivalence=positions,errors=errors,
            sizing_context='original nominal technical input only; no production economic acceptance or funding',
            ramses_acquisition_calls=0,authentic_position_samples=0,full_provider_coverage_certified=False)
        (out/'result.json').write_text(json.dumps(status,indent=2)+'\n')
        survivor.history.close();survivor.plane.close();broker.close()


def source_identity():
    root=Path(__file__).resolve().parents[2]
    def git(*a):return subprocess.check_output(['git','-C',str(root),*a],text=True,timeout=2).strip()
    paths=['engineering/solana_capacity/pump_pons_proof.py','engineering/solana_capacity/proof_limits.py',
           'engineering/solana_capacity/proof_host.py','engineering/solana_capacity/proof_transport.py',
           'engineering/solana_capacity/proof_workload.py','engineering/solana_capacity/final_mixed.py',
           'operational/forward-survivor/NEXT_PROOF.json']
    return dict(commit=git('rev-parse','HEAD'),tree=git('rev-parse','HEAD^{tree}'),
        dirty=bool(git('status','--porcelain')),
        hashes={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})


def environment(path):
    allowed={'MM_SOLANA_READ_RPC_URL','MM_SOLANA_YELLOWSTONE_TOKEN','MM_ROBINHOOD_READ_RPC_URL'};values={}
    source=Path(path)
    if not source.is_file() or source.stat().st_size>32768:raise ValueError('proof_credentials_file_bound')
    for line in source.read_text().splitlines():
        if '=' not in line or line.lstrip().startswith('#'):continue
        key,raw=line.removeprefix('export ').split('=',1)
        if key in allowed:
            tokens=shlex.split(raw,comments=True)
            if len(tokens)!=1:raise ValueError('proof_credentials_shape')
            values[key]=tokens[0]
    if set(values)!=allowed:raise ValueError('explicit_proof_credentials_required')
    if endpoint_family(values['MM_SOLANA_READ_RPC_URL'])!='solana' or endpoint_family(values['MM_ROBINHOOD_READ_RPC_URL'])!='robinhood':
        raise ValueError('proof_provider_family')
    return values


def isolated_environment(out):
    scratch=out/'state';scratch.mkdir(exist_ok=True)
    os.environ.update(TMPDIR=str(scratch),SQLITE_TMPDIR=str(scratch),PYTHONDONTWRITEBYTECODE='1',
        MM_PROVIDER_GOVERNOR_DB=str(out/'governor.sqlite'),MM_PROVIDER_DB=str(out/'robinhood-provider.sqlite'),
        MM_OPERATIONAL_PHASE='BOUNDED_PROVIDER_PROOF',MM_RPC_CACHE_DB=str(out/'robinhood-evidence.sqlite'),
        MM_ROBINHOOD_STATE_DIR=str(out/'pons'),MM_SOLANA_EVIDENCE_PLANE_DB=str(scratch/'canonical.sqlite'),
        MM_SOLANA_CANDIDATE_HISTORY_DB=str(out/'candidate.sqlite'))
    import tempfile
    tempfile.tempdir=str(scratch)
    if len(os.fsencode(str(scratch/'canonical.sqlite')+'.sock'))>=108:raise ValueError('isolated_socket_path_too_long')
    for key in ('MM_STATE_ROOT','MM_PORTFOLIO_ACCOUNTING_DB','MM_DIRECTIONAL_SLEEVE_DB','MM_DIRECTIONAL_COHORT_ID'):
        os.environ.pop(key,None)


def recovery_checkpoint(state):
    from meme_machine.solana_selective_runtime import CONTROL
    db=state.writer.db
    return dict(control_checkpoint=db.execute('SELECT MAX(hi) FROM coverage WHERE scope=?',(CONTROL,)).fetchone()[0],
        candidates=[list(r) for r in db.execute('SELECT family,address,first_slot,first_seen FROM candidate_lifecycle ORDER BY family,address')],
        checkpoints=[list(r) for r in db.execute('SELECT scope,slot FROM candidate_checkpoints ORDER BY scope')])


def validate_resume(before,after):
    old=before['control_checkpoint'];new=after['control_checkpoint']
    if old is None or new is None or new<old:return False
    identities={tuple(r) for r in after['candidates']}
    checkpoints=dict(after['checkpoints'])
    return all(tuple(r) in identities for r in before['candidates']) and all(
        checkpoints.get(scope,-1)>=slot for scope,slot in before['checkpoints'])


async def live_workload(out,env,budget,queues,transports,source):
    from .final_mixed import FinalMixed,reconcile
    from . import certify
    from meme_machine.solana_evidence_service import serve
    from .proof_workload import capital_fixtures
    class Mixed(FinalMixed):
        def state(self,state):
            row=super().state(state)
            if row['startup'].get('released'):budget.ready()
            queues.scheduler_snapshot(row['acquisitions'])
            return row
        def should_finish(self,snapshot,cohort_debt):
            # Wall timestamps in the original strategy remain original. The
            # proof's observation and termination clock is monotonic only.
            if budget.ready_at is None or budget.clock()-budget.ready_at<budget.time['minimum_steady_seconds']:return False
            return super().should_finish(snapshot,cohort_debt)
    c=Mixed(out,budget.time['minimum_steady_seconds'],env,proof_source=source)
    async def checkpoint():return await c.source.work(recovery_checkpoint,2)
    transports.recovery_probe=checkpoint
    # No authentic preserved native positions were supplied. Static old quote
    # probes are omitted; they cannot become funded-position deadline samples.
    c.position_families=();c.meter.install();stop=asyncio.Event();c.worker_stop.clear()
    c.capital_fixture_receipt=dict(executed_by_supervisor_child=True)
    robin=threading.Thread(target=pons,args=(out/'pons',env['MM_ROBINHOOD_READ_RPC_URL'],budget,queues),name='proof-pons',daemon=True)
    robin.start()
    async def bridge():
        while not budget.stop.is_set() and not budget.admissions_stopped.is_set():
            recovery=transports.disconnect_receipt
            if recovery and recovery.get('resubscribed') and not recovery.get('resumed') and c.source.control_connected:
                after=await checkpoint()
                if not validate_resume(recovery['checkpoint_before'],after):budget.fail('checkpoint_resume_identity_changed')
                recovery.update(resumed=True,checkpoint_after=after,checkpoint_identity_preserved=True,
                    original_source_clocks_preserved=True,event_order_preserved=True)
            budget.check_time();queues.poll();await asyncio.sleep(.05)
        stop.set();c.worker_stop.set()
    bridge_task=asyncio.create_task(bridge())
    try:
        await asyncio.to_thread(c.rpc.validate_network)
        await serve(out/'state/canonical.sqlite',c.config.http_url,repair_rpc=c.rpc,stop=stop,source_driver=c)
        if c.errors:budget.fail('model_b_workload_error')
    finally:
        budget.stop_work();stop.set();c.worker_stop.set();bridge_task.cancel()
        await asyncio.gather(bridge_task,return_exceptions=True)
        robin.join(timeout=max(0,min(budget.started+299.5,budget.shutdown_at+19.5)-budget.clock()))
        if robin.is_alive():budget.reason=budget.reason or 'pons_worker_shutdown_incomplete'
        c.write();c.meter.close();c.transport.close()
        reconcile(out)
    reconciliation=json.loads((out/'reconciliation.json').read_text())
    if reconciliation['status']!='PASS':budget.fail('checkpoint_reconciliation_failure')
    if not transports.disconnect or not transports.disconnect_receipt.get('resumed'):budget.fail('disconnect_resume_exercise_missing')
    normal_drain=json.loads((out/'result.json').read_text())['owner_observation']['normal_drain']['proven']
    return dict(workload='existing_optimized_Model_B',capital_fixtures=c.capital_fixture_receipt,
      recovery=transports.disconnect_receipt,reconciliation=reconciliation,authentic_position_samples=0,
      normal_drain_proven=normal_drain,
      pump_qualification_samples=sum('qualification_ready' in r for r in (c.pump_candidates.rows if c.pump_candidates else [])),
      paused_workloads=dict(meteora=0,ramses=0),live_books_opened=0,production_epoch_modified=False,
      insufficient=['authentic_native_positions_not_available','new_Survivor_candidates_cannot_mature_in_300_seconds'])


def child(control_fd,contract):
    # --child alone has no network, environment-file read, or workload authority.
    if control_fd is None or os.environ.get('CI'):raise ValueError('supervised_child_required')
    control=socket.socket(fileno=control_fd)
    if control.family!=socket.AF_UNIX or control.getsockopt(socket.SOL_SOCKET,socket.SO_TYPE)!=socket.SOCK_SEQPACKET:
        raise ValueError('supervised_control_socket_required')
    import struct,ctypes
    peer=struct.unpack('3i',control.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
    if peer[0]!=os.getppid():raise ValueError('supervisor_parent_identity')
    control.settimeout(2);init=json.loads(control.recv(16384))
    if init.get('mode') not in ('OFFLINE','LIVE') or init.get('contract_sha256')!=contract.sha256:
        raise ValueError('supervisor_contract_identity')
    if init['mode']=='LIVE' and init.get('authorized_live_proof') is not True:raise ValueError('live_invocation_not_authorized')
    from .proof_host import install_notifications,HostUnavailable
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0:raise HostUnavailable('parent_death_signal_unavailable')
    if init['mode']=='OFFLINE' and libc.unshare(0x40000000)!=0:raise HostUnavailable('offline_network_namespace_unavailable')
    # Attach before constructing workers. All descendants inherit this cgroup.
    (Path(init['group'])/'cgroup.procs').write_text(str(os.getpid()))
    install_notifications(control)
    out=Path(init['output']);isolated_environment(out)
    budget=Budget(contract,out,started=init['started']);queues=QueueEvidence(budget)
    env={} if init['mode']=='OFFLINE' else environment(init['env'])
    os.environ.update(env)
    from .proof_transport import Transports
    from .proof_workload import FakeHTTP,offline_workload
    transports=Transports(budget,queues,offline=init['mode']=='OFFLINE',
        opener=FakeHTTP() if init['mode']=='OFFLINE' else None)
    # Prevent indirect SDK/database paths from opening production monetary state.
    def isolation(event,args):
        if event=='sqlite3.connect' and str(args[0])!=':memory:':
            p=Path(str(args[0]).split('?',1)[0].removeprefix('file:')).resolve()
            if not p.is_relative_to(out):budget.fail('production_database_access')
    sys.addaudithook(isolation)
    validate_native_bindings(contract)
    from .proof_workload import capital_fixtures
    capital=capital_fixtures(out)
    transports.install()
    receipt={};done=threading.Event();loop=None
    def stop_signal(*_):budget.stop_work();budget.stop.set()
    signal.signal(signal.SIGTERM,stop_signal);signal.signal(signal.SIGINT,stop_signal)
    def report():
        while not done.wait(.05):
            try:
                snapshot=budget.snapshot();q=queues.snapshot()
                control.sendmsg([json.dumps(dict(kind='status',ready_elapsed=snapshot['ready_elapsed'],
                    reason=budget.reason,counts=snapshot['counts'],queue_depths=q['depths'],
                    queue_completed=q['completed'],shutdown=budget.admissions_stopped.is_set())).encode()])
            except (OSError,TimeoutError):budget.stop_work();budget.stop.set();return
    reporter=threading.Thread(target=report,name='proof-receipt-channel',daemon=True);reporter.start()
    try:
        work=offline_workload(out,budget,queues,transports) if init['mode']=='OFFLINE' else live_workload(out,env,budget,queues,transports,init['source'])
        receipt=asyncio.run(work);receipt['capital_fixtures']=capital
    except CeilingReached as exc:
        if exc.reason!='admission_closed':budget.reason=budget.reason or exc.reason
    except BaseException as exc:
        budget.reason=budget.reason or 'workload_exception_'+type(exc).__name__
    finally:
        done.set();reporter.join(timeout=.2);transports.close()
        state=budget.snapshot();receipt.update(budget=state,queues=queues.snapshot(),reason=budget.reason,
            authorized_provider_execution=init['mode']=='LIVE',production_financial_books_opened=0,
            isolated_original_epoch=contract.body['preserved_original_epoch'])
        raw=json.dumps(receipt,indent=2).encode()
        if len(raw)>1_500_000:raise ValueError('receipt_size_bound')
        (out/'ceilings.json').write_bytes(raw)
        control.sendmsg([json.dumps(dict(kind='done',reason=budget.reason,ready_elapsed=state['ready_elapsed'],
            elapsed=state['elapsed'],shutdown_elapsed=state['shutdown_elapsed'],counts=state['counts'],insufficient=receipt.get('insufficient',[]),
            queue_pending=len(queues.pending)+len(queues.running),recovery=receipt.get('recovery'),
            normal_drain_proven=receipt.get('normal_drain_proven',queues.snapshot()['drain_proven']),
            real_provider_dispatches=budget.dispatched,fake_provider_dispatches=budget.fake_dispatches)).encode()])
        control.close()
    return 1 if budget.reason else 0


def classify(*,reason,returncode,forced,ready_elapsed,elapsed,minimum_steady=180,insufficient=(),done=False,descendants_survived=False,normal_drain_proven=True):
    if reason or returncode!=0 or forced or descendants_survived:return 'FAIL'
    if not done:return 'FAIL'
    if ready_elapsed is None or ready_elapsed>60 or elapsed-ready_elapsed<minimum_steady:return 'FAIL'
    if not normal_drain_proven:return 'INSUFFICIENT_SAMPLE'
    return 'INSUFFICIENT_SAMPLE' if insufficient else 'PASS'


def supervise(args,contract):
    # Preflight (including DNS/files/git) belongs to the same absolute wall
    # contract. It cannot precede and therefore extend the supervised window.
    from .proof_host import HostUnavailable
    started=time.monotonic()
    if signal.getitimer(signal.ITIMER_REAL)[0]:raise HostUnavailable('existing_wall_alarm')
    def expired(*_):raise HostUnavailable('wall_time_ceiling')
    previous=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,contract.time['total_wall_seconds']-.25)
    try:return _supervise(args,contract,started)
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)


def _supervise(args,contract,started):
    from .proof_host import (LinuxGroup,ResourceWatch,KernelAdmission,receive_listener,group_sample,
                             HostUnavailable,RECEIPT_RESERVE,supervisor_sample)
    import ctypes
    if sys.version_info[:3]!=(3,12,14):raise HostUnavailable('pinned_python_3_12_14_required')
    parent_baseline=supervisor_sample();deadline=started+contract.time['total_wall_seconds'];source=source_identity()
    if not args.offline:
        if os.environ.get('CI') or not args.authorized_live_proof or not args.env or not args.source_commit:
            raise ValueError('separate_authorized_live_invocation_required')
        if source['dirty'] or source['commit']!=args.source_commit:raise ValueError('exact_clean_source_commit_required')
    out=Path(args.output).resolve()
    if out.exists() or out.is_relative_to(Path('/opt/meme-machine')) or str(out).startswith('/var/lib/meme-machine'):
        raise ValueError('new_disposable_output_required')
    if len(os.fsencode(str(out/'state/canonical.sqlite.sock')))>=108:raise ValueError('isolated_socket_path_too_long')
    if len(os.sched_getaffinity(0))!=2:raise HostUnavailable('dedicated_two_vcpu_host_required')
    mem={k:int(v.split()[0])*1024 for k,v in (line.split(':') for line in Path('/proc/meminfo').read_text().splitlines())}
    if mem['MemTotal']<7_500_000_000 or mem['MemAvailable']<contract.limits['minimum_system_available_bytes']:
        raise HostUnavailable('eight_gib_host_with_available_memory_required')
    # Live preflight resolves only explicitly approved hosts after deliberate
    # authorization. Offline has no DNS or credential inspection.
    ips=[]
    if not args.offline:
        env=environment(args.env)
        hosts={urlsplit_hostname(v) for k,v in env.items() if k.endswith('RPC_URL')}
        hosts.update(('rpc.mainnet.chain.robinhood.com',STREAM_HOST.split(':')[0]))
        for host in hosts:
            for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):ips.append((item[4][0],443))
        # Native libc DNS uses the local resolver only. No endpoint aliases or
        # unknown destination IP may be opened by an indirect SDK.
        for line in Path('/etc/resolv.conf').read_text().splitlines():
            if line.startswith('nameserver '):ips.append((line.split()[1],53))
    out.mkdir(parents=True);group=None;process=None;kernel=None;forced=False;reason=None;shutdown_at=None;terminated=False
    status={};finished={};samples=[];last_status=None;watch=ResourceWatch(contract.limits);parent,worker=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    parent.setblocking(False)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise HostUnavailable('subreaper_unavailable')
    def hard_stop(*_):
        nonlocal forced,reason
        forced=True;reason=reason or 'wall_time_ceiling'
        if group is not None:group.kill()
    old_alarm=signal.signal(signal.SIGALRM,hard_stop)
    signal.setitimer(signal.ITIMER_REAL,max(.001,deadline-time.monotonic()-.25))
    try:
        group=LinuxGroup(contract.limits,output=out)
        # Keep only runtime variables. Real provider credentials are never
        # inherited into offline tests, including child SDK/background paths.
        child_env={k:v for k,v in os.environ.items() if k in ('PATH','LD_LIBRARY_PATH','LANG','LC_ALL','VIRTUAL_ENV')}
        child_env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
        log=(out/'worker.log').open('wb')
        process=subprocess.Popen([sys.executable,'-m',__spec__.name,'--child','--control-fd',str(worker.fileno()),
            '--contract',str(args.contract)],cwd=Path(__file__).resolve().parents[2],env=child_env,pass_fds=(worker.fileno(),),
            stdout=log,stderr=log,start_new_session=True)
        log.close();worker.close()
        init=dict(mode='OFFLINE' if args.offline else 'LIVE',authorized_live_proof=bool(args.authorized_live_proof),
             contract_sha256=contract.sha256,started=started,output=str(out),group=str(group.path),env=args.env,source=source)
        parent.send(json.dumps(init).encode())
        import select
        next_sample=started
        while time.monotonic()<deadline-.25:
            now=time.monotonic()
            if kernel is None and select.select([parent],[],[],0)[0]:
                fd=receive_listener(parent);kernel=KernelAdmission(fd,contract.limits,out,offline=args.offline,allowed_ips=ips,group=group,
                    provider_deadline=started+contract.time['stop_new_work_at_seconds'])
            if kernel is not None:
                kernel.service(maximum=32)
                if kernel.reason:reason=reason or kernel.reason
                while select.select([parent],[],[],0)[0]:
                    try:raw=parent.recv(65536)
                    except BlockingIOError:break
                    if not raw:break
                    data=json.loads(raw)
                    if data['kind']=='status':status=data;last_status=now
                    elif data['kind']=='done':finished=data
                    else:raise HostUnavailable('unknown_child_receipt')
                    reason=reason or data.get('reason')
                    ready=data.get('ready_elapsed')
                    if ready is not None and (type(ready) not in (int,float) or not 0<=ready<=min(60,now-started+.25)):
                        reason=reason or 'invalid_monotonic_ready_receipt'
                    for key,value in data.get('counts',{}).items():
                        if key not in contract.limits or type(value) is not int or not 0<=value<=contract.limits[key]:
                            reason=reason or 'invalid_budget_receipt'
            if now>=next_sample:
                row=group_sample(group,out);parent_resources=supervisor_sample()
                row['supervisor_resources']=parent_resources
                if parent_resources['rss']>=128*1024*1024:reason=reason or 'supervisor_memory_reserve'
                row['group_rss_bytes']+=parent_resources['rss']
                row['cpu_seconds']+=parent_resources['cpu']-parent_baseline['cpu']
                row['cumulative_process_write_bytes']+=parent_resources['writes']-parent_baseline['writes']
                row['reserved_process_write_bytes']=0 if kernel is None else kernel.writes.writes
                row['reserved_output_extent_bytes']=0 if kernel is None else kernel.writes.stock
                reason=reason or watch.check(row);samples.append(row);next_sample=now+.1
            if status.get('ready_elapsed') is None and now-started>=contract.time['maximum_startup_seconds']:
                reason=reason or 'startup_ceiling'
            if last_status is not None and now-last_status>5 and not finished:reason=reason or 'scheduler_telemetry_stalled'
            if now-started>=contract.time['stop_new_work_at_seconds'] or reason or status.get('shutdown'):
                if kernel is not None:kernel.network_closed=True
                if shutdown_at is None:shutdown_at=now
                if shutdown_at==now and process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
            if reason:
                # A safety failure stops immediately, not after allowing another
                # 30 seconds of unmetered CPU/memory/write growth.
                group.kill();forced=True
            elif shutdown_at is not None:
                if now-shutdown_at>=contract.time['term_after_shutdown_seconds'] and not terminated:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                    terminated=True;forced=True;reason=reason or 'termination_escalation'
                if now-shutdown_at>=contract.time['kill_after_shutdown_seconds']-.25:
                    group.kill();forced=True;reason=reason or 'shutdown_deadline'
            if process.poll() is not None:
                if group.populated():group.kill();forced=True;reason=reason or 'descendant_survived_worker'
                break
            if kernel is None and process.poll() is not None:break
            # Servicing notifications never waits on the application. Short
            # polling keeps the independent deadline/resource monitor runnable.
            select.select([parent],[],[],.005)
        if process.poll() is None:
            group.kill();forced=True;reason=reason or 'wall_time_ceiling'
        # Bound reaping and never use an unbounded process.wait/thread.join.
        reap_until=min(deadline-.05,time.monotonic()+.15)
        # Let Popen reap its own worker and preserve its actual exit status.
        # Only then reap adopted descendants; waitpid(-1) before poll() would
        # lose a killed worker's return code.
        while time.monotonic()<reap_until:
            process.poll()
            if process.returncode is not None:
                while True:
                    try:
                        pid,_=os.waitpid(-1,os.WNOHANG)
                        if pid==0:break
                    except ChildProcessError:break
                if not group.populated():break
            time.sleep(.002)
        process.poll();survived=group.populated()
        if survived:group.kill();reason=reason or 'descendants_not_reaped';forced=True
        if kernel is not None and not kernel.close():reason=reason or 'kernel_broker_shutdown_incomplete';forced=True
        elapsed=time.monotonic()-started
        observation_end=finished.get('shutdown_elapsed')
        if observation_end is None or type(observation_end) not in (int,float) or not 0<=observation_end<=elapsed:
            reason=reason or 'missing_or_invalid_observation_end'
        classification=classify(reason=reason,returncode=process.returncode,forced=forced,
            ready_elapsed=finished.get('ready_elapsed'),elapsed=observation_end or 0,
            insufficient=finished.get('insufficient',()),done=bool(finished),descendants_survived=survived,
            normal_drain_proven=finished.get('normal_drain_proven',False))
        receipt=dict(schema='forward-survivor-finite-proof-receipt-v1',classification=classification,
            mode='OFFLINE_VALIDATION' if args.offline else 'AUTHORIZED_READ_ONLY_PROVIDER_PROOF',
            source=source,contract_sha256=contract.sha256,reason=reason,worker_exit_code=process.returncode,
            forced_termination=forced,descendants_survived=survived,elapsed_seconds=elapsed,final_child=finished,
            peaks=dict(group_rss_bytes=watch.peak_rss,output_stock_bytes=watch.peak_stock,
                       group_cpu_cores_30_second_average=watch.peak_cpu),
            resources=samples,independent_watchdog=True,cgroup_hard_limits=dict(memory_max=contract.limits['proof_group_rss_bytes']-128*1024*1024,supervisor_memory_reserve=128*1024*1024,cpu_max='175000 100000',io_device=group.device,io_wbps=group.io_rate),
            kernel_write_admission=dict(reserved_bytes=0 if kernel is None else kernel.writes.writes,
                reserved_output_extents=0 if kernel is None else kernel.writes.stock,
                fork_duplicated_rss_reserved=0 if kernel is None else kernel.fork_rss_reserved,
                denied=0 if kernel is None else kernel.writes.denied),
            network=dict(real_provider_dispatches=finished.get('real_provider_dispatches'),
                kernel_connections=0 if kernel is None else kernel.network_connections,
                forbidden_socket_attempts=0 if kernel is None else kernel.network_denied,
                offline_network_namespace=args.offline),production_state_write_scope='kernel-denied; disposable output only',
            original_epoch=contract.body['preserved_original_epoch'],production_restarted=False,
            paused_workloads=contract.body['paused_operational_workloads'],minimum_steady_seconds=contract.time['minimum_steady_seconds'])
        raw=json.dumps(receipt,indent=2).encode()
        if len(raw)>RECEIPT_RESERVE:raise HostUnavailable('supervisor_receipt_reservation')
        if time.monotonic()<deadline-.05:(out/'process.json').write_bytes(raw)
        print(json.dumps(dict(classification=classification,reason=reason,output=str(out),elapsed_seconds=round(elapsed,3))))
        return 1 if classification=='FAIL' else 0
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_alarm)
        if group is not None:
            if group.populated():group.kill()
            group.close()
        if kernel is not None and not kernel.closed.is_set():kernel.close()
        parent.close();worker.close()


def urlsplit_hostname(value):
    from urllib.parse import urlsplit
    return urlsplit(value).hostname


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--contract','--limits',default=str(CONTRACT_PATH));p.add_argument('--output')
    p.add_argument('--env');p.add_argument('--source-commit');p.add_argument('--execute',action='store_true')
    p.add_argument('--authorized-live-proof',action='store_true',help='Explicit acknowledgement of separate owner authorization; never used in CI')
    p.add_argument('--offline',action='store_true',help='Run deterministic fake providers, with kernel networking disabled')
    p.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--control-fd',type=int,help=argparse.SUPPRESS);args=p.parse_args(argv)
    try:
        contract=load_contract(args.contract)
        if args.child:return child(args.control_fd,contract)
        if args.offline and args.execute:raise ValueError('offline_live_mode_conflict')
        if not args.execute and not args.offline:
            print(json.dumps(dict(mode='OFFLINE_DESCRIPTION',provider_calls=0,contract=contract.body),indent=2));return 0
        if not args.output:raise ValueError('disposable_output_required')
        return supervise(args,contract)
    except (ValueError,OSError,RuntimeError) as exc:
        # No exception text from SDKs, URLs or credential files reaches output.
        print(json.dumps(dict(classification='BLOCKED',reason=str(exc) if type(exc).__name__ in ('HostUnavailable','ValueError') and __import__('re').fullmatch('[a-z_0-9]+',str(exc)) else type(exc).__name__,provider_calls=0 if not args.execute else 'NOT_STARTED_OR_UNRESOLVED')),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
