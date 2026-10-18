"""Ordinary subprocess ownership, durable recovery and bounded publication."""
from datetime import datetime,timezone,timedelta
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from meme_machine.portfolio_accounting import PortfolioAccounting,inception_receipt,digest,LANES,_atomic_json
from meme_machine.runtime.usd_valuation import ValuationUnavailable,utc

SOURCE_ROOT=Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProviderHealthSample:
    collected_at: float
    completed_at: float
    providers: dict
    error: str | None = None

# Owner-directed reversible pause. Accounting identity/state remains four-lane so
# historical paused-family evidence and future owner-directed reactivation stay
# attributable. Only Pump and Pons receive operational processes and evidence.
from meme_machine.runtime.operating_families import ACTIVE_LANES,PAUSED_LANES,require_active


def identities(receipt=None):
    from meme_machine.lanes.pump.pump_acceleration_strategy import policy_hash
    from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH as pons
    from meme_machine.lanes.ramses.ramses_strategy import POLICY_HASH as ramses
    from meme_machine.lanes.meteora.runner import load_policy
    config=digest(dict(paper_only=True,starting_capital='500.00',family_genesis='125.00'))
    if receipt is not None:
        from meme_machine.portfolio_accounting import validate_inception
        value=validate_inception(receipt)
        if value.get('funding_authority')=='SHARED':
            config=digest(dict(paper_only=True,starting_capital=value['starting_capital'],sizing_basis=value['sizing_basis'],funding_authority='SHARED'))
    sources=dict(pump='3c9553afb3caa92ab5f3db769f870df033a9630f',pons='3de3d376847531ccb90e260cfcc96c37587ccb23',meteora='a3579b4cc748fdbb7b4a466680f8a224773adc8b',ramses='41b5f263efc31bedf9b39039a9f66bed264b70d3')
    policies=dict(pump=policy_hash(),pons=pons,meteora=digest(load_policy()),ramses=ramses)
    return {lane:dict(source_sha=sources[lane],policy_hash=policies[lane],config_hash=config) for lane in LANES}


def pons_held_shadow_settings(environ):
    """Nonsecret optional PAPER diagnostic flags; never quote-skip authority."""
    enabled=environ.get('MM_PONS_HELD_PAPER_SHADOW','0')
    if enabled not in ('0','1'):
        raise ValueError('invalid_pons_held_paper_shadow')
    values={'MM_PONS_HELD_PAPER_SHADOW':enabled}
    if enabled=='1':
        for name,default,minimum,maximum in (
            ('MM_PONS_HELD_SHADOW_MAX_SAMPLES',8,1,32),
            ('MM_PONS_HELD_SHADOW_EVERY_TICKS',10,1,300),
        ):
            raw=environ.get(name,str(default))
            try: number=int(raw)
            except (ValueError,TypeError):
                raise ValueError('invalid_'+name.lower()) from None
            if not minimum<=number<=maximum:
                raise ValueError('invalid_'+name.lower())
            values[name]=str(number)
    return values


def pons_capability_path(environ):
    """Forward an existing endpoint-bound file, never an arbitrary parent hint."""
    value=environ.get('MM_RPC_CAPABILITIES')
    if not value:return None
    try:
        import hashlib,stat
        from meme_machine.runtime.robinhood import provider_authority as authority
        path=Path(value)
        if not path.is_absolute() or path.is_symlink():return None
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o022:return None
        with path.open('rb') as stream:body=stream.read(16385)
        if len(body)>16384:return None
        endpoint=authority.endpoint(environ=environ)
        domain=hashlib.sha256(('4663:'+endpoint).encode()).hexdigest()
        row=json.loads(body)['endpoints'][domain]
        if (row.get('chain_id')!=4663 or row.get('provider_domain')!=domain
                or row.get('provider_fingerprint')!=authority.fingerprint(endpoint)
                or not isinstance(row.get('methods'),dict)):return None
        return str(path)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def validate_environment(*,offline=False,environ=None,required_lanes=ACTIVE_LANES):
    env=os.environ if environ is None else environ
    if env.get('MM_MODE','PAPER')!='PAPER':raise ValueError('PAPER_only_service')
    from meme_machine.paper_policy_revision import selected_revision
    selected_revision(env)
    if any(env.get(key) for key in ('WALLET_PRIVATE_KEY','SOLANA_PRIVATE_KEY','ETH_PRIVATE_KEY','MM_LIVE_TRADING')):
        raise ValueError('PAPER_service_rejects_wallet_or_live_configuration')
    if env.get('MM_PUMP_HELD_RPC_MODE','baseline') not in ('baseline','optimized'):
        raise ValueError('invalid_pump_held_rpc_mode')
    pons_held_shadow_settings(env)
    if sys.version_info[:3]!=(3,12,14):raise RuntimeError('CPython_3.12.14_required')
    if sqlite3.sqlite_version_info<(3,45,1):raise RuntimeError('SQLite_3.45.1_or_tested_successor_required')
    if not offline and 'pons' in required_lanes:
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
        return getattr(self,'continuation_lanes',getattr(self,'observation_lanes',ACTIVE_LANES))

    def _assert_paused_lanes_clear(self,account):
        from .pause import assert_clear
        return assert_clear(self.root,account)

    def initialize(self):
        required=ACTIVE_LANES
        if not self.offline and (self.admission in ('NORMAL','AUTONOMY') or
                self.admission=='OBSERVATION' and os.environ.get('MM_PROVIDER_OPERATION_MODE')=='CONTINUOUS'):
            from .admission import require_normal
            from .position_continuation import funding_lanes
            required=funding_lanes(require_normal(startup=True))
        elif not self.offline and self.admission=='OBSERVATION' and os.environ.get('MM_BOUNDED_PROVIDER_ENVELOPE'):
            required=tuple(json.loads(Path(os.environ['MM_BOUNDED_PROVIDER_ENVELOPE']).read_text())['lanes'])
        validate_environment(offline=self.offline,required_lanes=required)
        if not self.offline:
            from .admission import require_normal,require_autonomy
            if self.admission=='NORMAL':require_normal(startup=True)
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
            if not self.offline and self.admission in ('NORMAL','AUTONOMY'):
                # Root seals the actual systemd/kernel instance after start.
                # Wait and independently replay under original ownership before
                # selected()/connection() can open a financial runtime writer.
                from .normal_boot import consume_normal_boot
                self.normal_boot=consume_normal_boot(self,cancelled=lambda:self.stop_requested)
            from meme_machine.shared_capital.runtime import selected,connection
            shared=selected(database)
            if not self.offline and self.admission=='BOOTSTRAP' and shared is None:
                raise RuntimeError('bootstrap_requires_observation_only_shared_cutover')
            if shared:
                self.shared_capital=connection(shared)
                state=self.shared_capital.snapshot()['ledger']
                from meme_machine.runtime.policy_compatibility import assert_shared_transition
                assert_shared_transition(self.root,state)
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
                if binding and binding['receipt'].get('funding_authority')=='SHARED':
                    raise RuntimeError('shared_epoch_requires_selected_authority')
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
                binding=account.binding()
                from meme_machine.paper_policy_revision import historical_hashes, current_hashes
                active_hashes=current_hashes()
                if any(binding['identities']['lanes'][lane]['policy_hash'] in
                        historical_hashes(lane+'_current')-{active_hashes[lane+'_current']}
                        for lane in ('pump','pons')):
                    from meme_machine.runtime.policy_compatibility import require_flat_portfolio
                    require_flat_portfolio(account.snapshot())
                self.pause_proof=self._assert_paused_lanes_clear(account)
        except BaseException:
            context=getattr(self,'normal_boot',None)
            if context is not None:context.close()
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
        if not self.offline:allowed.add('MM_STORAGE_GUARD_CONFIG')
        env={k:v for k,v in os.environ.items() if k in allowed}
        if not self.offline and lane=='pons':
            capability=pons_capability_path(os.environ)
            if capability:env['MM_RPC_CAPABILITIES']=capability
            # The existing Pons adaptive planner consumes only exact,
            # endpoint-bound comparisons. Do not silently drop its protected
            # file at the family-worker boundary or expose it to other lanes.
            from meme_machine.lanes.pons.log_windows import protected_capability_path
            log_capability=protected_capability_path(os.environ.get('MM_ROBINHOOD_READ_RPC_URL',''),
                path=os.environ.get('MM_PONS_LOG_CAPABILITY_FILE'))
            if log_capability:env['MM_PONS_LOG_CAPABILITY_FILE']=log_capability
        env['PYTHONPATH']=str(SOURCE_ROOT)
        env.update(MM_MODE='PAPER',MM_RUNTIME_LANE=lane,MM_PAPER_EPOCH=self.epoch,
            MM_STATE_ROOT=str(self.root),MM_OPERATIONAL_PHASE='continuous',
            MM_DIRECTIONAL_SLEEVE_DB=str(self.root/lane/'directional-sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=self.epoch,MM_DIRECTIONAL_COMPOSITE_REQUIRED='1')
        if lane=='solana' and getattr(self,'admission','NORMAL')=='OBSERVATION':env['MM_OPERATIONAL_PHASE']='OBSERVATION'
        if lane in ('pump','pons','solana'):
            env['MM_OPERATION_COST_DIAGNOSTICS']='1' if os.environ.get('MM_OPERATION_COST_DIAGNOSTICS')=='1' else '0'
        from meme_machine.paper_policy_revision import ACTIVE_REVISION
        env['MM_PAPER_POLICY_REVISION']=ACTIVE_REVISION
        if lane in ('pump','pons'):
            # Explicit operational attention switch reaches both Current and
            # Survivor in the existing family worker; it cannot grant funding.
            value=os.environ.get('MM_VOLUME_QUALITY_ENABLED','0')
            env['MM_VOLUME_QUALITY_ENABLED']='1' if value=='1' else '0'
            env['MM_PONS_USD_ACQUISITION_OVERLAP']='1' if (
                lane=='pons' and os.environ.get('MM_PONS_USD_ACQUISITION_OVERLAP')=='1') else '0'
        if lane=='pump':
            # Explicit opt-in to a reversible PAPER test; other strategy workers
            # cannot inherit Pump's held-quote optimization switch.
            held_mode=os.environ.get('MM_PUMP_HELD_RPC_MODE','baseline')
            if held_mode not in ('baseline','optimized'):
                raise ValueError('invalid_pump_held_rpc_mode')
            env['MM_PUMP_HELD_RPC_MODE']=held_mode
        if lane=='pons':
            # Forward the existing explicit observation choice to its native
            # consumer only. This grants no provider capability or funding.
            observation_route=os.environ.get('MM_PONS_OBSERVATION_ROUTE') or 'public_existing'
            if observation_route not in ('public_existing','canonical_primary'):
                raise ValueError('invalid_pons_observation_route')
            if not self.offline:env['MM_PONS_OBSERVATION_ROUTE']=observation_route
            # Native USD acquisition may use the separately verified two-hop
            # route. Keep this opt-in confined to the actual Pons worker;
            # dropping it here would silently restore an unavailable direct
            # route. It grants no funding or provider-capacity readiness.
            bridge_mode=os.environ.get('MM_PONS_USD_BRIDGE_ROUTES','')
            if bridge_mode not in ('','verified_two_hop_v1'):
                raise ValueError('invalid_pons_usd_bridge_routes')
            if not self.offline and bridge_mode:
                env['MM_PONS_USD_BRIDGE_ROUTES']=bridge_mode
            # The supervisor drops unallowlisted parent variables. Explicitly
            # forward ONLY capped PAPER diagnostic settings to Pons workers.
            shadow=pons_held_shadow_settings(os.environ)
            if (shadow['MM_PONS_HELD_PAPER_SHADOW']=='1'
                    and not self.offline and
                    getattr(self,'provider_budget',None) is None):
                raise ValueError('pons_shadow_requires_existing_finite_provider_budget')
            env.update(shadow)
        if getattr(self,'provider_budget',None):
            if getattr(self.provider_budget,'continuous',False):
                env['MM_PROVIDER_OPERATION_MODE']='CONTINUOUS'
                env['MM_PROVIDER_USAGE_DB']=str(self.provider_budget.path)
                env['MM_CONTINUOUS_PROVIDER_ENVELOPE']=os.environ['MM_CONTINUOUS_PROVIDER_ENVELOPE']
            else:
                env['MM_BOUNDED_PROVIDER_DB']=str(self.provider_budget.path)
                if os.environ.get('MM_BOUNDED_PROVIDER_ENVELOPE'):
                    env['MM_BOUNDED_PROVIDER_ENVELOPE']=os.environ['MM_BOUNDED_PROVIDER_ENVELOPE']
        if solana:
            if lane=='solana':
                value=os.environ.get('MM_SOLANA_HISTORY_SEPARATED','0')
                if value not in ('0','1'):raise ValueError('historical_processing_configuration')
                env['MM_SOLANA_HISTORY_SEPARATED']=value
                # The opt-in diagnostic belongs to the canonical source only.
                # Normal protection does not depend on recorder availability.
                if not self.offline:
                    for key in ('MM_SQLITE_DIAGNOSTIC_REQUIRED',
                                'MM_SQLITE_TERMINAL_RECORD_PATH'):
                        if os.environ.get(key):env[key]=os.environ[key]
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
        if not hasattr(self,'evidence'):self.evidence=None
        if self.offline:return
        if 'pump' not in self.runtime_lanes():self.evidence=None;return
        budget=getattr(self,'provider_budget',None)
        if getattr(budget,'continuous',False) and time.time()<float(budget.snapshot()['backoff_until']):return
        (self.root/'shared').mkdir(exist_ok=True,mode=0o700)
        # Preserve Pump's existing relative broker location while sharing it
        # with the evidence worker, which starts before the lane process.
        (self.root/'pump').mkdir(exist_ok=True,mode=0o700)
        env=self.environment('solana')
        self.evidence=subprocess.Popen([sys.executable,'-m','meme_machine.runtime.evidence_worker'],cwd=self.root,env=env,start_new_session=True)
        ticks=self._source_start_ticks(self.evidence.pid)
        if ticks is None:raise RuntimeError('source_process_identity_unavailable')
        self.evidence._mm_source_start_ticks=ticks
        deadline=time.monotonic()+15
        while not Path(env['MM_SOLANA_EVIDENCE_PLANE_DB']+'.sock').exists():
            if self.evidence.poll() is not None:raise RuntimeError('shared_evidence_failed')
            if time.monotonic()>=deadline:raise RuntimeError('shared_evidence_start_timeout')
            time.sleep(.05)

    def publish(self,*,provider_sample=None):
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
        if hasattr(self,'continuation_lanes') or hasattr(self,'observation_lanes'):
            for lane in ACTIVE_LANES:
                if lane not in health:
                    health[lane]=dict(lane=lane,phase='CONTINUATION_IDLE' if hasattr(self,'continuation_lanes') else 'FUNDING_DISABLED',paper_only=True,at=utc(now),
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
            sample=provider_sample if provider_sample is not None else self.collect_provider_health()
            providers=self.providers_for_sample(sample)
            # Publish this cycle's already-reconciled facts. Publishing before
            # building them inserted a full extra cycle of age under load; a
            # healthy portfolio then failed the observer's unchanged 15s TTL.
            _atomic_json(self.root/'health.json',dict(paper_only=True,offline=self.offline,pid=os.getpid(),epoch_id=self.epoch,at=utc(time.time()),stopping=self.stop_requested,lanes=health,providers=providers,python=sys.version.split()[0],sqlite=sqlite3.sqlite_version,
                admission_mode=self.admission,bootstrap_armed=getattr(self,'bootstrap_armed',False),
                position_continuation=self.provider_budget.usage() if hasattr(getattr(self,'provider_budget',None),'usage') else None,
                continuation_resources=getattr(self,'resource_measurement',None),
                portfolio_observation=getattr(self,'portfolio_observation',None),
                shared_capital_projection_error=getattr(self,'shared_capital_projection_error',None),
                provider_health_sample=dict(collected_at=sample.collected_at,completed_at=sample.completed_at,error=sample.error),
                learning_observation=getattr(self,'learning_observation',None),
                native_shutdown=getattr(self,'native_shutdown',None)))
        except OSError as error:
            print('health publication failed:',type(error).__name__,flush=True)
        self.last_publish=time.monotonic()

    def publish_shared_capital(self,health,now):
        from meme_machine.shared_capital.reporting import reporting_snapshot,export_from_snapshot,summary_from_snapshot
        from meme_machine.portfolio_snapshot_transport import publish_snapshot
        for lane in ACTIVE_LANES:
            row=health.get(lane,{})
            proc=self.processes.get(lane)
            if proc is None or proc.poll() is not None:continue
            ready=row.get('reconciled') is True and row.get('phase') in ('DISCOVERING','MANAGING')
            for suffix in ('current','survivor'):
                self.shared_capital.owner(lane+'_'+suffix,self.process_instances[lane],proc.pid,
                    ready=ready and not self.stop_requested,at=int(now))
        if self.shared_capital.ledger()['inception'].get('sizing_basis')=='shared_realized_equity':
            self.shared_capital.command('portfolio-history:'+str(int(now)),'runtime_publish',{},int(now))
        # All authority mutations finish first. Capture once, then project and
        # write files after the read transaction has closed.
        view=reporting_snapshot(self.shared_capital,at=int(now))
        projection=export_from_snapshot(view)
        projection['shared_capital']['allocation_latency']={lane:health.get(lane,{}).get('shared_capital_metrics',
            {'state':'UNMEASURED'}) for lane in ACTIVE_LANES}
        self.portfolio_observation=dict(state='CURRENT',timestamp=now,valid_until=projection['valid_until'],
            **summary_from_snapshot(view))
        _atomic_json(self.root/'inception.json',view.snapshot['ledger']['inception'])
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
                result[provider]=dict(state='CURRENT',sampled_at=time.time(),queue_depth=depth,
                    oldest_wait_seconds=max(0,time.monotonic()-oldest) if oldest is not None else 0)
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
                evidence_sampled_at=time.time()
                db.execute('BEGIN') # One coherent read snapshot of proof and child.
                result['evidence']=dict(state='CURRENT',hot_records=db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],open_gaps=db.execute('SELECT COUNT(*) FROM gaps WHERE repaired IS NULL').fetchone()[0],frontiers=[dict(scope=s,slot=slot,updated=updated) for s,slot,updated in db.execute('SELECT * FROM cursors')])
                from meme_machine.solana_prewarm_startup import released,published_program_frontiers
                result['evidence']['startup_released']=released(db)
                result['evidence']['program_frontiers']=published_program_frontiers(db)
                for key,raw in db.execute("SELECT key,value FROM service_health WHERE key IN ('pid','phase','heartbeat','native_streams')"):
                    result['evidence'][key]=json.loads(raw)
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='candidate_checkpoints'").fetchone():
                    from meme_machine.solana_rolling_history import program_scope
                    result['evidence']['program_checkpoints']=[dict(scope=s,slot=slot,updated=updated,market_time=market)
                        for s,slot,updated,market in db.execute('SELECT c.scope,c.slot,c.updated,b.market_time FROM candidate_checkpoints c JOIN candidate_blocks b ON b.scope=c.scope AND b.slot BETWEEN c.slot AND c.slot+1 WHERE c.scope IN (?,?)',
                            (program_scope('pump'),program_scope('pumpswap')))]
                result['evidence']['sampled_at']=evidence_sampled_at
            except (OSError,sqlite3.Error,ValueError):result['evidence']={'state':'UNAVAILABLE'}
            finally:
                if db:db.close()
        return result

    def collect_provider_health(self):
        started=time.time()
        try:
            providers=self.provider_health()
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:
            return ProviderHealthSample(started,time.time(),{},type(error).__name__)
        return ProviderHealthSample(started,time.time(),providers)

    @staticmethod
    def providers_for_sample(sample):
        """No persistent cache; freshness and queue age are checked at use."""
        now=time.time()
        if sample.error or not 0<=now-sample.completed_at<=15:
            reason=sample.error or 'provider_health_sample_stale'
            return {key:dict(state='UNAVAILABLE',reason=reason,
                sampled_at=sample.collected_at) for key in ('solana','robinhood','evidence')}
        result={key:dict(row) for key,row in sample.providers.items()}
        for key,row in result.items():
            observed=row.get('sampled_at',sample.collected_at)
            if not 0<=now-observed<=15:
                result[key]=dict(state='UNAVAILABLE',reason='provider_health_sample_stale',sampled_at=observed)
            elif key in ('solana','robinhood') and row.get('state')=='CURRENT' and row.get('queue_depth',0)>0:
                row['oldest_wait_seconds']=row.get('oldest_wait_seconds',0)+max(0,now-observed)
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
        transition_id=self.run_id
        continuous_observation=(self.admission=='OBSERVATION' and
            os.environ.get('MM_PROVIDER_OPERATION_MODE')=='CONTINUOUS')
        if self.admission in ('NORMAL','AUTONOMY') or continuous_observation:
            from .admission import require_normal
            from .position_continuation import funding_lanes,position_lanes
            envelope=require_normal(startup=True)
            path=Path(os.environ['MM_PROVIDER_USAGE_DB'])
            original_path=previous.get('continuous_provider_db')
            if original_path and (original_path!=str(path) or not path.is_file()):
                from .restored_provider_history import require_restored_history
                require_restored_history(self,state,path,envelope)
            self.provider_budget=Budget(path) if original_path or path.exists() else Budget.create(path,continuous=envelope)
            if not self.provider_budget.continuous:raise ValueError('continuous_cannot_reuse_bounded_validation_database')
            self.provider_budget.configure_continuous_scope(envelope)
            self.provider_budget.preflight_file()
            if previous.get('mode') in ('NORMAL','AUTONOMY') and previous.get('provider_db')==str(path):
                self.run_id=previous['run_id']
            self.provider_budget.publish_readiness(False,self.run_id,reason=(
                'observation_funding_closed' if continuous_observation else
                'startup_reconcile_and_canonical_progress_required'))
            selected=set(funding_lanes(envelope))|set(position_lanes(state))
            self.observation_lanes=tuple(lane for lane in ACTIVE_LANES if lane in selected)
        elif self.admission=='BOOTSTRAP':
            original=Budget.create(self.root/'shared'/('bootstrap-'+self.run_id+'.sqlite'),continuation=envelope)
            self.provider_budget=PhaseBudget(original.path)
        elif self.admission=='OBSERVATION' and os.environ.get('MM_BOUNDED_PROVIDER_DB'):
            # A prepared observation allowance must reach every existing child
            # transport. Open its durable counters; never create or replenish it.
            self.provider_budget=Budget(os.environ['MM_BOUNDED_PROVIDER_DB'])
            envelope=self.provider_budget.preflight_file()
            from .position_continuation import position_lanes
            if set(position_lanes(state))-set(envelope['lanes']):
                self.provider_budget.fail('bounded_observation_cannot_omit_existing_owner')
            self.observation_lanes=tuple(envelope['lanes'])
        self.admission_data=dict(mode='OBSERVATION' if self.admission=='BOOTSTRAP' else self.admission,
            run_id=self.run_id,pid=os.getpid(),process_start=process_identity(os.getpid()))
        if getattr(self,'provider_budget',None):self.admission_data['provider_db']=str(self.provider_budget.path)
        if self.admission=='BOOTSTRAP':self.admission_data['continuation_envelope']=envelope
        if self.admission in ('NORMAL','AUTONOMY'):
            self.admission_data['funding_regimes']=list(envelope['funding_regimes'])
        if getattr(getattr(self,'provider_budget',None),'continuous',False):
            self.admission_data['continuous_provider_db']=str(self.provider_budget.path)
        operation='run-scope:'+self.run_id
        if self.admission in ('NORMAL','AUTONOMY'):
            # The usage run survives restarts; each actual process registration
            # is a new event, never a conflicting replay of the first PID/time.
            operation+=':'+transition_id
        self.shared_capital.command(operation,'runtime_admission',self.admission_data,int(time.time()))
        self.ready_since=None;self.ready_frontiers={};self.bootstrap_armed=False

    def normal_tick(self):
        """Current selected protection conditions, no lifetime funding clock."""
        budget=self.provider_budget;budget.reap_orphans()
        from .acceptance import observe
        from .position_continuation import readiness,funding_lanes
        try:
            health,portfolio,rss=observe(self.root,funding_lanes=funding_lanes(budget.envelope))
            readiness(health,portfolio,rss,budget.envelope)
            failure=getattr(self,'current_readiness_failure',None)
            if failure:raise ValueError(failure)
            frontiers={}
            if 'pump' in funding_lanes(budget.envelope):
                rows=health['providers']['evidence'].get('program_frontiers',[])
                if len(rows)!=2 or any(not 0<=time.time()-r['updated']<=5 or not 0<=time.time()-r['market_time']<=15 for r in rows):
                    raise ValueError('pump_canonical_program_coverage_not_current')
                frontiers.update({r['scope']:r['slot'] for r in rows})
            if 'pons' in funding_lanes(budget.envelope):frontiers['pons:canonical']=health['active_evidence']['pons_canonical_cursor']
            if self.ready_since is None:
                self.ready_since=time.monotonic();self.ready_frontiers=frontiers
            ready=(time.monotonic()-self.ready_since>=60 and
                all(frontiers[k]>value for k,value in self.ready_frontiers.items()))
            budget.publish_readiness(ready,self.run_id)
        except (OSError,ValueError,KeyError) as error:
            self.ready_since=None;self.ready_frontiers={}
            import re
            detail=str(error)
            if not re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}',detail):detail=type(error).__name__
            budget.publish_readiness(False,self.run_id,reason='selected_regime_protection_not_ready:'+detail)

    def bootstrap_tick(self):
        """Reuse operational health; readiness never replaces native qualification."""
        from .acceptance import observe
        budget=getattr(self.provider_budget,'bootstrap',self.provider_budget)
        if budget.snapshot()['reason']:
            from .position_continuation import close_bootstrap
            close_bootstrap(self,'bootstrap_provider_exposure_closed');return
        try:
            from .position_continuation import readiness,funding_lanes
            lanes=funding_lanes(self.admission_data['continuation_envelope'])
            health,portfolio,rss=observe(self.root,funding_lanes=lanes)
            proof=readiness(health,portfolio,rss,self.admission_data['continuation_envelope'])
            if rss>=6*1024**3:raise ValueError('bootstrap_memory_limit')
            for provider in ('solana' if lane=='pump' else 'robinhood' for lane in lanes):
                row=health['providers'].get(provider,{})
                if row.get('state')!='CURRENT' or row['oldest_wait_seconds']>5:
                    raise ValueError('bootstrap_provider_queue_or_health')
            frontiers={}
            if 'pump' in lanes:
                frontiers.update({row['scope']:row['slot'] for row in health['providers']['evidence']['frontiers']
                    if row['scope'] in ('program:pump','program:pumpswap')})
            if 'pons' in lanes:frontiers['pons:canonical']=health['active_evidence']['pons_canonical_cursor']
            if len(frontiers)!=2*('pump' in lanes)+('pons' in lanes):
                raise ValueError('bootstrap_selected_coverage_required')
            if self.ready_since is None:
                self.ready_since=time.monotonic();self.ready_frontiers=frontiers
            if not self.bootstrap_armed and time.monotonic()>=self.ready_since+60:
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

    def continuation_health(self,*,provider_sample=None):
        from decimal import localcontext
        from .position_continuation import cpu_capacity,outstanding,provider_failure,provider_recovered
        from meme_machine.shared_capital.model import CapitalError
        budget=getattr(self,'provider_budget',None)
        if budget is None:return
        sample=provider_sample if provider_sample is not None else self.collect_provider_health()
        providers=self.providers_for_sample(sample);now=time.time();reason=None
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
            configured_cpu=cpu_capacity(budget.envelope)
            group=Path('/sys/fs/cgroup/system.slice/meme-machine-paper.service')
            memory=int((group/'memory.current').read_text())
            use=int(dict(line.split() for line in (group/'cpu.stat').read_text().splitlines())['usage_usec'])
            prior=getattr(self,'resource_prior',(now,use))
            cpu=(use-prior[1])/1000000/max(.001,now-prior[0]);self.resource_prior=(now,use)
            quota,period=(group/'cpu.max').read_text().split()
            period=int(period)
            if period<=0:raise ValueError('invalid_cgroup_cpu_period')
            quota=None if quota=='max' else int(quota)
            actual_cpu=None if quota is None else quota/period
            with localcontext() as context:
                # Exact product without expanding a tiny decimal capacity into
                # an arbitrarily large integer denominator.
                context.prec=max(28,len(configured_cpu.as_tuple().digits)+len(str(period)))
                within_cpu_limit=quota is not None and quota<=configured_cpu*period
            memory_high=int((group/'memory.high').read_text())
            memory_max=int((group/'memory.max').read_text())
            verified=(actual_cpu is not None and math.isfinite(actual_cpu) and actual_cpu>0
                and within_cpu_limit
                and 0<memory_high<=6*1024**3 and 0<memory_max<=7*1024**3)
            self.resource_measurement=dict(cgroup_memory_bytes=memory,cpu_cores=cpu,
                cpu_quota_cores=actual_cpu,configured_cpu_cores=str(configured_cpu),
                cpu_quota_state='UNBOUNDED' if quota is None else 'FINITE',
                maximum_queue_depth=64,maximum_queue_wait_seconds=5,limits_verified=verified)
            if not verified:reason='continuation_existing_service_resource_limits_unavailable'
            if memory>=budget.envelope['maximum_rss_bytes']:reason='continuation_cgroup_memory_exhausted'
        except (OSError,ValueError,KeyError,ArithmeticError,CapitalError):
            self.resource_measurement=dict(state='UNAVAILABLE',reason='existing_PAPER_cgroup_measurement_unavailable')
            reason=reason or 'continuation_cgroup_resource_measurement_unavailable'
        if outstanding(self.shared_capital.ledger()):
            if reason:provider_failure(self,reason)
            else:provider_recovered(self)
        self.current_readiness_failure=reason

    def recover_evidence(self):
        """An incident blocks new risk; existing native owners keep priority."""
        if self.evidence.poll() is not None:
            self.stop_process(self.evidence,45,cooperative_parent=True)
        if getattr(getattr(self,'provider_budget',None),'continuous',False):
            now=time.time()
            if getattr(self,'reported_evidence_failure',None)!=self.evidence.pid:
                self.reported_evidence_failure=self.evidence.pid
                self.provider_budget.provider_error('canonical_evidence_process_failed')
                self.next_evidence_retry=now+2
            if now>=self.next_evidence_retry and now>=float(self.provider_budget.snapshot()['backoff_until']):
                self.start_services();self.next_evidence_retry=now+2
            return
        # Bounded historical validation keeps its original ownership handoff.
        self.stop_lanes()
        if hasattr(getattr(self,'provider_budget',None),'bootstrap'):
            from .position_continuation import provider_failure
            provider_failure(self,'shared_authenticated_evidence_process_failed')
        time.sleep(2);self.start_services()
        for lane in self.runtime_lanes():self.start_lane(lane)

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
                if not self.offline and self.evidence is None and 'pump' in self.runtime_lanes():self.start_services()
                if not self.offline and self.evidence is not None and self.evidence.poll() is not None:self.recover_evidence()
                if not self.offline and self.evidence is not None and 'pump' not in self.runtime_lanes():
                    self.stop_process(self.evidence,45,cooperative_parent=True);self.evidence=None
                if time.monotonic()-self.last_publish>=2:
                    provider_sample=self.collect_provider_health()
                    if self.admission in ('BOOTSTRAP','CONTINUATION','NORMAL','AUTONOMY') and not self.offline:
                        self.continuation_health(provider_sample=provider_sample)
                    self.publish(provider_sample=provider_sample)
                    if self.admission=='BOOTSTRAP' and not self.offline:self.bootstrap_tick()
                    if self.admission in ('NORMAL','AUTONOMY') and not self.offline:self.normal_tick()
                    if self.admission in ('BOOTSTRAP','CONTINUATION') and not self.offline:
                        from .exceptional_window import tick
                        tick(self)
                time.sleep(.05)
        finally:
            self.stop_requested=True
            budget=getattr(self,'provider_budget',None)
            if getattr(budget,'continuous',False):budget.publish_readiness(False,self.run_id,reason='supervisor_stopping')
            if budget and hasattr(budget,'bootstrap'):
                # Termination never leaves a grant that a child or restart can
                # spend. The same continuation usage/state resumes on failure.
                budget.bootstrap.change(reason='service_stopping_funding_closed',check=False)
            self.stop_lanes()
            evidence=getattr(self,'evidence',None)
            if evidence is not None:self.stop_process(evidence,45,cooperative_parent=True)
            self.publish()
            for sig,handler in prior.items():signal.signal(sig,handler)
            if self.lock:self.lock.close();self.lock=None

    @staticmethod
    def _source_start_ticks(pid):
        try:raw=Path('/proc',str(pid),'stat').read_text()
        except FileNotFoundError:return None
        try:
            leader,tail=raw.rsplit(')',1)
            fields=tail.split()
            if (int(leader.split('(',1)[0])!=pid or int(fields[2])!=pid
                    or int(fields[3])!=pid or int(fields[19])<=0):
                raise ValueError
            return int(fields[19])
        except (ValueError,IndexError):
            raise RuntimeError('source_process_identity_unverified') from None

    @staticmethod
    def stop_process(proc,timeout=15,*,signal_sent=False,observe=None,cooperative_parent=False):
        def note(operation,**fields):
            if observe is not None:
                try:observe(dict(operation=operation,at=time.time(),monotonic=time.monotonic(),
                    caller_pid=os.getpid(),caller_native_thread_id=threading.get_native_id(),
                    target_pid=proc.pid,**fields))
                except Exception:pass
        def cleanup_descendants():
            # The source owns accepted pool work through its cooperative
            # drain. Once that owner exits, no descendant may outlive it.
            current=Supervisor._source_start_ticks(proc.pid)
            if current is not None and current!=source_ticks:
                raise RuntimeError('source_process_identity_changed')
            note('descendant_cleanup_requested',signal=int(signal.SIGKILL))
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:
                proc._mm_source_group_closed=True
                return
            proc._mm_source_group_closed=True
            note('descendant_cleanup_sent',signal=int(signal.SIGKILL))
        code=proc.poll()
        if cooperative_parent:
            if getattr(proc,'_mm_source_group_closed',False):
                if code is None:code=proc.wait(timeout=5)
                note('already_cleaned',exit_code=code)
                return
            source_ticks=getattr(proc,'_mm_source_start_ticks',None)
            if source_ticks is None:
                if code is not None:raise RuntimeError('source_process_identity_unavailable')
                source_ticks=Supervisor._source_start_ticks(proc.pid)
                if source_ticks is None:raise RuntimeError('source_process_identity_unavailable')
                proc._mm_source_start_ticks=source_ticks
            current=Supervisor._source_start_ticks(proc.pid)
            if current is not None and current!=source_ticks:
                raise RuntimeError('source_process_identity_changed')
        if code is not None:
            note('already_exited',exit_code=code)
            if cooperative_parent:cleanup_descendants()
            return
        if not signal_sent:
            note('signal_requested',signal=int(signal.SIGTERM))
            if cooperative_parent:proc.send_signal(signal.SIGTERM)
            else:os.killpg(proc.pid,signal.SIGTERM)
            note('signal_sent',signal=int(signal.SIGTERM))
        note('wait_started',timeout_seconds=timeout)
        escalated=False
        try:code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            note('wait_timeout',timeout_seconds=timeout)
            note('signal_requested',signal=int(signal.SIGKILL))
            if cooperative_parent:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc._mm_source_group_closed=True
            else:os.killpg(proc.pid,signal.SIGKILL)
            note('signal_sent',signal=int(signal.SIGKILL))
            code=proc.wait(timeout=5)
            escalated=True
        note('wait_completed',exit_code=code)
        if cooperative_parent and not escalated:cleanup_descendants()

    def stop_lanes(self):
        self.native_shutdown=[]
        def record(lane,row):
            try:
                if len(self.native_shutdown)<48:
                    self.native_shutdown.append(dict(row,lane=lane,run_id=getattr(self,'run_id',None)))
            except Exception:pass
        for lane,proc in self.processes.items():
            if proc.poll() is None:
                record(lane,dict(operation='signal_requested',signal=int(signal.SIGTERM),
                    at=time.time(),monotonic=time.monotonic(),caller_pid=os.getpid(),
                    caller_native_thread_id=threading.get_native_id(),target_pid=proc.pid))
                os.killpg(proc.pid,signal.SIGTERM)
                record(lane,dict(operation='signal_sent',signal=int(signal.SIGTERM),
                    at=time.time(),monotonic=time.monotonic(),caller_pid=os.getpid(),
                    caller_native_thread_id=threading.get_native_id(),target_pid=proc.pid))
        deadline=time.monotonic()+15
        for lane,proc in self.processes.items():
            self.stop_process(proc,max(.1,deadline-time.monotonic()),signal_sent=True,
                observe=lambda row,lane=lane:record(lane,row))
