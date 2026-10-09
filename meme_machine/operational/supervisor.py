"""Ordinary subprocess ownership, durable recovery and bounded publication."""
from datetime import datetime,timezone,timedelta
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,digest,LANES,_atomic_json
from meme_machine.runtime.usd_valuation import ValuationUnavailable,utc

SOURCE_ROOT=Path(__file__).resolve().parents[2]

# Owner-directed reversible pause. Accounting identity/state remains four-lane so
# historical paused-family evidence and future owner-directed reactivation stay
# attributable. Only Pump and Pons receive operational processes and evidence.
from meme_machine.runtime.operating_families import ACTIVE_LANES,PAUSED_LANES,require_active


def identities():
    from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as pons
    from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH as ramses
    from meme_machine.lanes.meteora.runner import load_policy
    config=digest(dict(paper_only=True,starting_capital='500.00',family_genesis='125.00'))
    sources=dict(pump='3c9553afb3caa92ab5f3db769f870df033a9630f',pons='3de3d376847531ccb90e260cfcc96c37587ccb23',meteora='a3579b4cc748fdbb7b4a466680f8a224773adc8b',ramses='41b5f263efc31bedf9b39039a9f66bed264b70d3')
    policies=dict(pump=policy_hash(),pons=pons,meteora=digest(load_policy()),ramses=ramses)
    return {lane:dict(source_sha=sources[lane],policy_hash=policies[lane],config_hash=config) for lane in LANES}


def validate_environment(*,offline=False,environ=None):
    env=os.environ if environ is None else environ
    if env.get('MM_MODE','PAPER')!='PAPER':raise ValueError('PAPER_only_service')
    if any(env.get(key) for key in ('WALLET_PRIVATE_KEY','SOLANA_PRIVATE_KEY','ETH_PRIVATE_KEY','MM_LIVE_TRADING')):
        raise ValueError('PAPER_service_rejects_wallet_or_live_configuration')
    if sys.version_info[:3]!=(3,12,14):raise RuntimeError('CPython_3.12.14_required')
    if sqlite3.sqlite_version_info<(3,45,1):raise RuntimeError('SQLite_3.45.1_or_tested_successor_required')
    if not offline:
        # Configuration only. Oracle availability is checked by Robinhood value
        # readers before economic exposure, independently of the Solana lanes.
        from meme_machine.runtime.robinhood.provider_authority import endpoint
        try:endpoint(environ=env)
        except ValueError:
            raise ValuationUnavailable('VALUATION_UNAVAILABLE:USDG/USD:MM_ROBINHOOD_READ_RPC_URL unavailable or invalid') from None


class Supervisor:
    def __init__(self,state_root,*,offline=False,admission='NORMAL'):
        self.root=Path(state_root).resolve()
        self.offline=offline
        from .admission import MODES
        if admission not in MODES:raise ValueError('PAPER_admission_mode')
        self.admission=admission
        self.processes={}
        self.process_instances={}
        self.restarts={lane:0 for lane in LANES}
        self.next_start={lane:0 for lane in LANES}
        self.stop_requested=False
        self.lock=None
        self.last_publish=0

    def runtime_lanes(self):
        return getattr(self,'continuation_lanes',ACTIVE_LANES)

    def _assert_paused_lanes_clear(self,account):
        from .pause import assert_clear
        return assert_clear(self.root,account)

    def initialize(self):
        validate_environment(offline=self.offline)
        if not self.offline:
            from .admission import require_normal,require_autonomy
            if self.admission=='NORMAL':require_normal()
            if self.admission=='AUTONOMY':require_autonomy(self.root)
            from .storage_guard import verify_storage
            verify_storage(self.root)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=(self.root/'supervisor.lock').open('a')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close();self.lock=None
            raise RuntimeError('one_PAPER_supervisor_already_running') from None
        database=self.root/'portfolio.sqlite'
        try:
            from meme_machine.shared_capital.runtime import selected,connection
            shared=selected(database)
            if not self.offline and self.admission=='BOOTSTRAP' and shared is None:
                raise RuntimeError('bootstrap_requires_observation_only_shared_cutover')
            if shared:
                self.shared_capital=connection(shared)
                state=self.shared_capital.snapshot()['ledger']
                self.epoch=state['epoch_id']
                if self.offline != self.epoch.startswith('offline-fixture-'):
                    raise RuntimeError('offline_and_operational_state_must_be_separate')
                from contextlib import closing
                with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
                    reader=object.__new__(PortfolioAccounting);reader.db=db
                    reader.snapshot=lambda:reader._replay()
                    frozen=reader.snapshot();reader._reconcile(frozen)
                    if frozen['receipt_hash']!=state['inception_sha256'] or frozen['receipt']['epoch_id']!=self.epoch:
                        raise RuntimeError('shared_authority_epoch_mismatch')
                    self.pause_proof=self._assert_paused_lanes_clear(reader)
                if not self.offline:self.configure_admission()
                return
            existing_state=self.existing_epoch_state()
            if existing_state and not database.exists():
                raise RuntimeError('existing_epoch_state_requires_bound_portfolio')
            with self.account() as account:
                binding=account.binding()
                if binding is None:
                    if existing_state:raise RuntimeError('existing_epoch_state_requires_bound_portfolio')
                    if not self.offline:raise RuntimeError('preserved_PAPER_epoch_required_no_reseed')
                    epoch=('offline-fixture-' if self.offline else 'paper-')+str(time.time_ns())
                    values=identities()
                    account.establish_inception(inception_receipt(epoch,utc(time.time()),epoch+':inception'),portfolio_identities=values['pump'],lane_identities=values)
                    account.configure_family_sleeves()
                elif self.offline != binding['receipt']['epoch_id'].startswith('offline-fixture-'):
                    raise RuntimeError('offline_and_operational_state_must_be_separate')
                self.epoch=account.binding()['receipt']['epoch_id']
                self.pause_proof=self._assert_paused_lanes_clear(account)
        except BaseException:
            self.lock.close();self.lock=None
            raise
        if self.offline:_atomic_json(self.root/'OFFLINE_ONLY.json',dict(offline=True,market_calls=0,epoch_id=self.epoch))

    def existing_epoch_state(self):
        # These are reset-prevention markers, never replacement capital or
        # recovery authority. A bound canonical portfolio remains mandatory.
        return any((self.root/name).exists() for name in
                   ('inception.json','OFFLINE_ONLY.json','portfolio.sqlite-wal','portfolio.sqlite-shm')) or any(
            (self.root/lane/'native-genesis.json').exists() or any((self.root/lane).glob('*.sqlite*'))
            for lane in LANES)

    def account(self):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            account=PortfolioAccounting(self.root/'portfolio.sqlite',wait_for_writer=True)
            try:yield account
            finally:account.close()
        return opened()

    def environment(self,lane):
        if lane not in (*LANES,'solana'):raise ValueError('unknown_runtime_lane')
        require_active(lane,production=True)
        solana=lane in ('pump','meteora','solana')
        # Parent credentials, strategy overrides and state paths are not child
        # configuration. Retain only interpreter/OS transport needs and explicitly
        # sanctioned provider inputs; durable paths below belong to this epoch.
        transport={'PATH','HOME','LANG','LC_ALL','LC_CTYPE','TZ','TMPDIR',
            'VIRTUAL_ENV','PYTHONHOME','PYTHONUNBUFFERED','PYTHONDONTWRITEBYTECODE',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
            'http_proxy','https_proxy','all_proxy','no_proxy',
            'SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE'}
        providers=({'MM_SOLANA_READ_RPC_URL','MM_SOLANA_PUBLIC_RPC_URL',
            'MM_ONFINALITY_SOLANA_RPC_URL','MM_ONFINALITY_SOLANA_WS_URL'} if solana
            else {'MM_ROBINHOOD_READ_RPC_URL',
                  'MM_ROBINHOOD_SEQUENCER_FEED_URL'})
        allowed=transport | (set() if self.offline else providers)
        env={k:v for k,v in os.environ.items() if k in allowed}
        env['PYTHONPATH']=str(SOURCE_ROOT)
        env.update(MM_MODE='PAPER',MM_RUNTIME_LANE=lane,MM_PAPER_EPOCH=self.epoch,
            MM_STATE_ROOT=str(self.root),MM_OPERATIONAL_PHASE='continuous',
            MM_DIRECTIONAL_SLEEVE_DB=str(self.root/lane/'directional-sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=self.epoch,MM_DIRECTIONAL_COMPOSITE_REQUIRED='1')
        if lane=='pump':
            # Explicit opt-in to a reversible PAPER test; other strategy workers
            # cannot inherit Pump's held-quote optimization switch.
            held_mode=os.environ.get('MM_PUMP_HELD_RPC_MODE','baseline')
            if held_mode not in ('baseline','optimized'):
                raise ValueError('invalid_pump_held_rpc_mode')
            env['MM_PUMP_HELD_RPC_MODE']=held_mode
        if getattr(self,'provider_budget',None):env['MM_BOUNDED_PROVIDER_DB']=str(self.provider_budget.path)
        if solana:
            env.update(MM_PROVIDER_GOVERNOR_DB=str(self.root/'shared/solana-provider.sqlite'),
                MM_SOLANA_EVIDENCE_PLANE_DB=str(self.root/'shared/solana-evidence.sqlite'),
                MM_SOLANA_CANDIDATE_HISTORY_DB=str(self.root/'shared/solana-candidate-history.sqlite'),
                MM_SOLANA_EVIDENCE_BROKER_DB=str(self.root/'pump/solana-evidence-broker.sqlite3'),
                MM_SOLANA_EXPENSIVE_WORKERS='2')
        else:
            env.update(MM_PROVIDER_DB=str(self.root/'shared/robinhood-provider.sqlite'),
                MM_RPC_CACHE_DB=str(self.root/'shared/robinhood-evidence.sqlite'),
                MM_ROBINHOOD_STATE_DIR=str(self.root/'shared'))
        if self.offline:
            # The fixture worker constructs its explicit mock value reader. It
            # receives no provider credentials or production transport config.
            env={k:v for k,v in env.items() if 'RPC_URL' not in k and 'API_KEY' not in k and not k.startswith('MM_PORTFOLIO_')}
        else:env['MM_PORTFOLIO_ACCOUNTING_DB']=str(self.root/'portfolio.sqlite')
        return env

    def start_lane(self,lane):
        require_active(lane,production=True)
        folder=self.root/lane;folder.mkdir(exist_ok=True,mode=0o700)
        args=[sys.executable,'-m','meme_machine.operational.lane','--lane',lane,'--state-root',str(self.root)]
        if self.offline:args.append('--offline')
        import uuid
        instance=uuid.uuid4().hex
        env=self.environment(lane);env['MM_LANE_PROCESS_INSTANCE']=instance
        self.processes[lane]=subprocess.Popen(args,cwd=folder,env=env,start_new_session=True)
        self.process_instances[lane]=instance
        if getattr(self,'shared_capital',None):
            for suffix in ('current','survivor'):
                self.shared_capital.owner(lane+'_'+suffix,instance,self.processes[lane].pid,ready=False,at=int(time.time()))

    def start_services(self):
        if self.offline:return
        if 'pump' not in self.runtime_lanes():self.evidence=None;return
        (self.root/'shared').mkdir(exist_ok=True,mode=0o700)
        # Preserve Pump's existing relative broker location while sharing it
        # with the evidence worker, which starts before the lane process.
        (self.root/'pump').mkdir(exist_ok=True,mode=0o700)
        env=self.environment('solana')
        self.evidence=subprocess.Popen([sys.executable,'-m','meme_machine.runtime.evidence_worker'],cwd=self.root,env=env,start_new_session=True)
        deadline=time.monotonic()+15
        while not Path(env['MM_SOLANA_EVIDENCE_PLANE_DB']+'.sock').exists():
            if self.evidence.poll() is not None:raise RuntimeError('shared_evidence_failed')
            if time.monotonic()>=deadline:raise RuntimeError('shared_evidence_start_timeout')
            time.sleep(.05)

    def publish(self):
        now=time.time()
        health={}
        for lane,proc in self.processes.items():
            path=self.root/lane/'health.json'
            try:
                with path.open('rb') as stream:body=stream.read(262145)
                if len(body)>262144:raise ValueError('health_bound')
                row=json.loads(body)
                if not isinstance(row,dict):raise ValueError('health_shape')
                if (row.get('pid')!=proc.pid or row.get('process_instance')!=self.process_instances.get(lane)):
                    raise ValueError('health_predecessor_instance')
            except (OSError,ValueError):row=dict(phase='STARTING')
            health[lane]=dict(row,pid=proc.pid,exit_code=proc.poll(),restarts=self.restarts[lane])
        self.last_native_health=health
        if hasattr(self,'continuation_lanes'):
            for lane in ACTIVE_LANES:
                if lane not in health:
                    health[lane]=dict(lane=lane,phase='CONTINUATION_IDLE',paper_only=True,at=utc(now),
                        discovery_enabled=False,pid=None,process_instance=None,exit_code=None,
                        reconciled=None,ownership_required=False,restarts=self.restarts[lane])
        for lane,reason in PAUSED_LANES.items():
            health[lane]=dict(lane=lane,phase='PAUSED',paper_only=True,at=utc(now),
                paused=True,pause_reason=reason,discovery_enabled=False,reconciled=True,
                pid=None,process_instance=None,exit_code=None,restarts=0)
        if getattr(self,'shared_capital',None):
            try:self.publish_shared_capital(health,now)
            except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:
                self.shared_capital_projection_error=str(error)
        try:
            if getattr(self,'shared_capital',None):raise RuntimeError('shared_projection_already_published')
            with self.account() as account:
                sequence=account.snapshot()['sequence']
                account.export_path=self.root/'portfolio.json'
                _atomic_json(self.root/'inception.json',account.binding()['receipt'])
                if now-getattr(self,'last_history',0)>=60:
                    account.record_history_sample(epoch_id=self.epoch,event_id='history:'+str(sequence+1),at=utc(now))
                    sequence=account.snapshot()['sequence'];self.last_history=now
                account.publish(epoch_id=self.epoch,event_id='snapshot:'+str(sequence+1),as_of=utc(now),valid_until=utc(now+30))
                if account.db.execute('SELECT COUNT(*) FROM portfolio_events').fetchone()[0]>1024:
                    account.compact()
                from .observation import portfolio_summary
                state=account.snapshot()
                summary=portfolio_summary(account,state,utc(now))
                valid_until=account._export(state)['valid_until']
                # Diagnostic capture time follows reconciliation. Market/report
                # validity retains its original bound; this cannot renew a mark.
                self.portfolio_observation=dict(state='CURRENT',timestamp=time.time(),
                    valid_until=valid_until,**summary)
            from meme_machine.portfolio_snapshot_transport import publish_snapshot
            publish_snapshot(self.root/'inception.json',self.root/'portfolio.json',self.root/'dashboard-snapshot.json')
        except (OSError,ValueError,RuntimeError):
            # Read-only dashboard files have no authority over native execution.
            pass
        try:
            from .observation import owner_learning_observation
            self.learning_observation=owner_learning_observation(self.root)
        except (OSError,ValueError,RuntimeError):self.learning_observation=None
        try:
            providers=self.provider_health()
            # Publish this cycle's already-reconciled facts. Publishing before
            # building them inserted a full extra cycle of age under load; a
            # healthy portfolio then failed the observer's unchanged 15s TTL.
            _atomic_json(self.root/'health.json',dict(paper_only=True,offline=self.offline,pid=os.getpid(),epoch_id=self.epoch,at=utc(time.time()),stopping=self.stop_requested,lanes=health,providers=providers,python=sys.version.split()[0],sqlite=sqlite3.sqlite_version,
                admission_mode=self.admission,bootstrap_armed=getattr(self,'bootstrap_armed',False),
                position_continuation=self.provider_budget.usage() if hasattr(getattr(self,'provider_budget',None),'usage') else None,
                continuation_resources=getattr(self,'resource_measurement',None),
                portfolio_observation=getattr(self,'portfolio_observation',None),
                shared_capital_projection_error=getattr(self,'shared_capital_projection_error',None),
                learning_observation=getattr(self,'learning_observation',None)))
        except OSError as error:
            print('health publication failed:',type(error).__name__,flush=True)
        self.last_publish=time.monotonic()

    def publish_shared_capital(self,health,now):
        from meme_machine.shared_capital.reporting import export,summary
        from meme_machine.portfolio_snapshot_transport import publish_snapshot
        for lane in ACTIVE_LANES:
            row=health.get(lane,{})
            proc=self.processes.get(lane)
            if proc is None or proc.poll() is not None:continue
            ready=row.get('reconciled') is True and row.get('phase') in ('DISCOVERING','MANAGING')
            for suffix in ('current','survivor'):
                self.shared_capital.owner(lane+'_'+suffix,self.process_instances[lane],proc.pid,
                    ready=ready and not self.stop_requested,at=int(now))
        projection=export(self.shared_capital,at=int(now))
        projection['shared_capital']['allocation_latency']={lane:health.get(lane,{}).get('shared_capital_metrics',
            {'state':'UNMEASURED'}) for lane in ACTIVE_LANES}
        self.portfolio_observation=dict(state='CURRENT',timestamp=now,valid_until=projection['valid_until'],
            **summary(self.shared_capital,int(now)))
        _atomic_json(self.root/'inception.json',self.shared_capital.snapshot()['ledger']['inception'])
        _atomic_json(self.root/'portfolio.json',projection)
        publish_snapshot(self.root/'inception.json',self.root/'portfolio.json',self.root/'dashboard-snapshot.json')

    def provider_health(self):
        result={}
        for provider,name in (('solana','solana-provider.sqlite'),('robinhood','robinhood-provider.sqlite')):
            path=self.root/'shared'/name
            if not path.exists():result[provider]={'state':'UNAVAILABLE'};continue
            db=None
            try:
                db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
                from .observation import provider_queue
                depth,oldest=provider_queue(db,provider=='solana')
                result[provider]=dict(state='CURRENT',queue_depth=depth,oldest_wait_seconds=max(0,time.monotonic()-oldest) if oldest is not None else 0)
                if provider=='solana':
                    result[provider]['pressure']=[dict(provider=p,grants=g,rate_errors=e,cooldown_seconds=max(0,c-time.monotonic())) for p,_,c,g,e in db.execute('SELECT * FROM pressure')]
                else:
                    result[provider]['usage']=[dict(lane=lane,metric=metric,value=value) for lane,metric,value in db.execute('SELECT lane,metric,SUM(value) FROM provider_usage GROUP BY lane,metric')]
            except (OSError,sqlite3.Error):result[provider]={'state':'UNAVAILABLE'}
            finally:
                if db:db.close()
        path=self.root/'shared/solana-evidence.sqlite'
        if path.exists():
            db=None
            try:
                db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)
                result['evidence']=dict(state='CURRENT',hot_records=db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],open_gaps=db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],frontiers=[dict(scope=s,slot=slot,updated=updated) for s,slot,updated in db.execute('SELECT * FROM cursors')])
                from meme_machine.solana_prewarm_startup import released
                result['evidence']['startup_released']=released(db)
                for key,raw in db.execute("SELECT key,value FROM service_health WHERE key IN ('pid','phase','heartbeat','native_streams')"):
                    result['evidence'][key]=json.loads(raw)
            except (OSError,sqlite3.Error):result['evidence']={'state':'UNAVAILABLE'}
            finally:
                if db:db.close()
        return result

    def configure_admission(self):
        import uuid
        from meme_machine.shared_capital.runtime import process_identity
        from .bounded_provider import Budget,PhaseBudget
        state=self.shared_capital.ledger()
        previous=state.get('runtime_admission',{})
        if self.admission=='BOOTSTRAP':
            from .position_continuation import load_envelope
            envelope=load_envelope()
            if previous.get('continuation_envelope'):
                if envelope!=previous['continuation_envelope']:
                    raise RuntimeError('continuation_allowance_cannot_expand_on_restart')
                self.run_id=previous['run_id'];self.admission='CONTINUATION'
                self.provider_budget=PhaseBudget(previous['provider_db'])
                self.provider_budget.reap_orphans()
                self.provider_budget.bootstrap.change(reason='service_restart_funding_closed',check=False)
                self.provider_budget.set_phase('CONTINUATION','service_restart_funding_closed')
                self.admission_data=dict(previous,mode='CONTINUATION',pid=os.getpid(),
                    process_start=process_identity(os.getpid()))
                # Instance token makes a repeated normal restart idempotent
                # without resetting its economic/resource clocks or allowances.
                self.shared_capital.command('resume-continuation:'+self.run_id+':'+
                    self.admission_data['process_start'],'runtime_admission',self.admission_data,int(time.time()))
                from .position_continuation import position_lanes
                self.continuation_lanes=position_lanes(state)
                if self.provider_budget.phase() in ('FAULT','FLAT'):
                    self.continuation_fault=self.provider_budget.fault();self.stop_requested=True
                return
            if previous.get('bootstrap_used'):
                raise RuntimeError('old_bootstrap_without_continuation_requires_disposition')
        self.run_id=uuid.uuid4().hex
        if self.admission=='BOOTSTRAP':
            original=Budget.create(self.root/'shared'/('bootstrap-'+self.run_id+'.sqlite'),continuation=envelope)
            self.provider_budget=PhaseBudget(original.path)
        self.admission_data=dict(mode='OBSERVATION' if self.admission=='BOOTSTRAP' else self.admission,
            run_id=self.run_id,pid=os.getpid(),process_start=process_identity(os.getpid()))
        if getattr(self,'provider_budget',None):self.admission_data['provider_db']=str(self.provider_budget.path)
        if self.admission=='BOOTSTRAP':self.admission_data['continuation_envelope']=envelope
        self.shared_capital.command('run-scope:'+self.run_id,'runtime_admission',self.admission_data,int(time.time()))
        self.ready_since=None;self.ready_frontiers={};self.bootstrap_armed=False

    def bootstrap_tick(self):
        """Reuse operational health; readiness never replaces native qualification."""
        from .acceptance import observe
        budget=getattr(self.provider_budget,'bootstrap',self.provider_budget)
        if budget.snapshot()['reason']:
            from .position_continuation import close_bootstrap
            close_bootstrap(self,'bootstrap_provider_exposure_closed');return
        try:
            health,portfolio,rss=observe(self.root)
            from .position_continuation import readiness
            proof=readiness(health,portfolio,rss,self.admission_data['continuation_envelope'])
            if rss>=6*1024**3:raise ValueError('bootstrap_memory_limit')
            for provider in ('solana','robinhood'):
                row=health['providers'].get(provider,{})
                if row.get('state')!='CURRENT' or row['oldest_wait_seconds']>5:
                    raise ValueError('bootstrap_provider_queue_or_health')
            frontiers={row['scope']:row['slot'] for row in health['providers']['evidence']['frontiers']
                       if row['scope'] in ('program:pump','program:pumpswap')}
            frontiers['pons:canonical']=health['active_evidence']['pons_canonical_cursor']
            if len(frontiers)!=3:raise ValueError('bootstrap_full_coverage_required')
            if self.ready_since is None:
                self.ready_since=time.monotonic();self.ready_frontiers=frontiers
            if not self.bootstrap_armed and time.monotonic()-self.ready_since>=60:
                if any(frontiers[k]<=old for k,old in self.ready_frontiers.items()):
                    raise ValueError('bootstrap_canonical_progress_required')
                self.shared_capital.command('arm-bootstrap:'+self.run_id,'runtime_admission',
                    dict(self.admission_data,mode='BOOTSTRAP',continuation_ready=proof),int(time.time()))
                self.bootstrap_armed=True
        except (OSError,ValueError,KeyError) as error:
            self.ready_since=None;self.ready_frontiers={}
            if self.bootstrap_armed:
                # Fail closed on new exposure immediately; existing native
                # safety/recovery events never depend on an admission grant.
                from .position_continuation import close_bootstrap
                close_bootstrap(self,'bootstrap_health_or_deadline_failure')
        if not self.bootstrap_armed and time.monotonic()-self.provider_budget.started>=600:
            from .position_continuation import close_bootstrap
            close_bootstrap(self,'bootstrap_readiness_not_demonstrated')

    def continuation_health(self):
        from .position_continuation import outstanding,provider_failure,provider_recovered
        budget=getattr(self,'provider_budget',None)
        if budget is None:return
        providers=self.provider_health();now=time.time();reason=None
        for lane in self.runtime_lanes():
            provider='solana' if lane=='pump' else 'robinhood'
            row=providers.get(provider,{})
            if row.get('state')!='CURRENT':reason=provider+'_provider_unavailable'
            elif row.get('queue_depth',0)>budget.envelope['maximum_queue_depth']:
                reason=provider+'_protective_queue_depth_exceeded'
            elif row.get('oldest_wait_seconds',0)>budget.envelope['maximum_queue_wait_seconds']:
                reason=provider+'_protective_queue_latency_exceeded'
            native=getattr(self,'last_native_health',{}).get(lane,{})
            if not 0<=now-native.get('progress_at',0)<=15 or native.get('reconciled') is not True:
                reason=lane+'_native_manager_or_evidence_not_ready'
            for safety in native.get('native_continuation',{}).get('position_safety',[]):
                if safety.get('evidence_current') is not True or not 0<=now-safety.get('at',0)<=15:
                    reason=safety.get('blocker') or lane+'_position_evidence_stale'
        if 'pump' in self.runtime_lanes():
            row=providers.get('evidence',{})
            if row.get('phase')!='ACTIVE' or not 0<=now-row.get('heartbeat',0)<=15:
                reason='authenticated_solana_position_evidence_unavailable'
        try:
            group=Path('/sys/fs/cgroup/system.slice/meme-machine-paper.service')
            memory=int((group/'memory.current').read_text())
            use=int(dict(line.split() for line in (group/'cpu.stat').read_text().splitlines())['usage_usec'])
            prior=getattr(self,'resource_prior',(now,use))
            cpu=(use-prior[1])/1000000/max(.001,now-prior[0]);self.resource_prior=(now,use)
            quota,period=(group/'cpu.max').read_text().split()
            verified=(quota!='max' and int(quota)/int(period)<=1.8 and
                int((group/'memory.high').read_text())<=6*1024**3 and
                int((group/'memory.max').read_text())<=7*1024**3)
            self.resource_measurement=dict(cgroup_memory_bytes=memory,cpu_cores=cpu,
                cpu_quota_cores=1.8,maximum_queue_depth=64,maximum_queue_wait_seconds=5,limits_verified=verified)
            if not verified:reason='continuation_existing_service_resource_limits_unavailable'
            if memory>=budget.envelope['maximum_rss_bytes']:reason='continuation_cgroup_memory_exhausted'
        except (OSError,ValueError,KeyError):
            self.resource_measurement=dict(state='UNAVAILABLE',reason='existing_PAPER_cgroup_measurement_unavailable')
            reason=reason or 'continuation_cgroup_resource_measurement_unavailable'
        if outstanding(self.shared_capital.ledger()):
            if reason:provider_failure(self,reason)
            else:provider_recovered(self)

    def run(self,*,seconds=None):
        self.initialize()
        started=time.monotonic()
        prior={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
        for sig in prior:signal.signal(sig,lambda *_:setattr(self,'stop_requested',True))
        try:
            if not self.stop_requested:
                self.start_services()
                for lane in self.runtime_lanes():self.start_lane(lane)
            while not self.stop_requested and (seconds is None or time.monotonic()-started<seconds):
                for lane,proc in list(self.processes.items()):
                    if lane not in self.runtime_lanes():
                        self.stop_process(proc)
                        del self.processes[lane];continue
                    if lane in ACTIVE_LANES and proc.poll() is not None and time.monotonic()>=self.next_start[lane]:
                        self.restarts[lane]+=1
                        self.next_start[lane]=time.monotonic()+min(30,2**min(self.restarts[lane],5))
                        self.start_lane(lane)
                if not self.offline and self.evidence is not None and self.evidence.poll() is not None:
                    # Stop lane owners before shared evidence replacement; their
                    # next start must prove native journals and pending delivery.
                    self.stop_lanes()
                    if getattr(self,'provider_budget',None):
                        from .position_continuation import provider_failure
                        provider_failure(self,'shared_authenticated_evidence_process_failed')
                    # Native state is durable; close funding before reconnecting.
                    time.sleep(2)
                    self.start_services()
                    for lane in self.runtime_lanes():self.start_lane(lane)
                if not self.offline and self.evidence is not None and 'pump' not in self.runtime_lanes():
                    self.stop_process(self.evidence,45);self.evidence=None
                if time.monotonic()-self.last_publish>=2:
                    if self.admission in ('BOOTSTRAP','CONTINUATION') and not self.offline:
                        self.continuation_health()
                    self.publish()
                    if self.admission=='BOOTSTRAP' and not self.offline:self.bootstrap_tick()
                    if self.admission in ('BOOTSTRAP','CONTINUATION') and not self.offline:
                        from .exceptional_window import tick
                        tick(self)
                time.sleep(.05)
        finally:
            self.stop_requested=True
            budget=getattr(self,'provider_budget',None)
            if budget and hasattr(budget,'bootstrap'):
                # Termination never leaves a grant that a child or restart can
                # spend. The same continuation usage/state resumes on failure.
                budget.bootstrap.change(reason='service_stopping_funding_closed',check=False)
            self.stop_lanes()
            evidence=getattr(self,'evidence',None)
            if evidence is not None:self.stop_process(evidence,45)
            self.publish()
            for sig,handler in prior.items():signal.signal(sig,handler)
            if self.lock:self.lock.close();self.lock=None

    @staticmethod
    def stop_process(proc,timeout=15,*,signal_sent=False):
        if proc.poll() is not None:return
        if not signal_sent:os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

    def stop_lanes(self):
        for proc in self.processes.values():
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
        deadline=time.monotonic()+15
        for proc in self.processes.values():self.stop_process(proc,max(.1,deadline-time.monotonic()),signal_sent=True)
