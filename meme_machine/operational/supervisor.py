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
from meme_machine.runtime.usd_valuation import USDG_BLOCKER,ValuationUnavailable,utc

SOURCE_ROOT=Path(__file__).resolve().parents[2]


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
        # No market I/O and no inception occurs before the missing value is fixed.
        raise ValuationUnavailable(USDG_BLOCKER)


class Supervisor:
    def __init__(self,state_root,*,offline=False):
        self.root=Path(state_root).resolve()
        self.offline=offline
        self.processes={}
        self.restarts={lane:0 for lane in LANES}
        self.next_start={lane:0 for lane in LANES}
        self.stop_requested=False
        self.lock=None
        self.last_publish=0

    def initialize(self):
        validate_environment(offline=self.offline)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=(self.root/'supervisor.lock').open('a')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close();self.lock=None
            raise RuntimeError('one_PAPER_supervisor_already_running') from None
        database=self.root/'portfolio.sqlite'
        with self.account() as account:
            binding=account.binding()
            if binding is None:
                epoch=('offline-fixture-' if self.offline else 'paper-')+str(time.time_ns())
                values=identities()
                account.establish_inception(inception_receipt(epoch,utc(time.time()),epoch+':inception'),portfolio_identities=values['pump'],lane_identities=values)
                account.configure_family_sleeves()
            elif self.offline != binding['receipt']['epoch_id'].startswith('offline-fixture-'):
                raise RuntimeError('offline_and_operational_state_must_be_separate')
            self.epoch=account.binding()['receipt']['epoch_id']
        if self.offline:_atomic_json(self.root/'OFFLINE_ONLY.json',dict(offline=True,market_calls=0,epoch_id=self.epoch))

    def account(self):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            account=PortfolioAccounting(self.root/'portfolio.sqlite',wait_for_writer=True)
            try:yield account
            finally:account.close()
        return opened()

    def environment(self,lane):
        env=dict(os.environ)
        env['PYTHONPATH']=str(SOURCE_ROOT)+os.pathsep+env.get('PYTHONPATH','')
        env.update(MM_MODE='PAPER',MM_RUNTIME_LANE=lane,MM_PAPER_EPOCH=self.epoch,
            MM_STATE_ROOT=str(self.root),MM_OPERATIONAL_PHASE='continuous',
            MM_PROVIDER_DB=str(self.root/'shared/robinhood-provider.sqlite'),
            MM_RPC_CACHE_DB=str(self.root/'shared/robinhood-evidence.sqlite'),
            MM_ROBINHOOD_STATE_DIR=str(self.root/'shared'),
            MM_PROVIDER_GOVERNOR_DB=str(self.root/'shared/solana-provider.sqlite'),
            MM_SOLANA_EVIDENCE_PLANE_DB=str(self.root/'shared/solana-evidence.sqlite'),
            MM_DIRECTIONAL_SLEEVE_DB=str(self.root/lane/'directional-sleeve.sqlite'),
            MM_DIRECTIONAL_COHORT_ID=self.epoch,MM_DIRECTIONAL_COMPOSITE_REQUIRED='1')
        if self.offline:
            # The fixture worker constructs its explicit mock value reader. It
            # receives no provider credentials or production transport config.
            env={k:v for k,v in env.items() if 'RPC_URL' not in k and 'API_KEY' not in k and not k.startswith('MM_PORTFOLIO_')}
        else:env['MM_PORTFOLIO_ACCOUNTING_DB']=str(self.root/'portfolio.sqlite')
        return env

    def start_lane(self,lane):
        folder=self.root/lane;folder.mkdir(exist_ok=True,mode=0o700)
        args=[sys.executable,'-m','meme_machine.operational.lane','--lane',lane,'--state-root',str(self.root)]
        if self.offline:args.append('--offline')
        self.processes[lane]=subprocess.Popen(args,cwd=folder,env=self.environment(lane),start_new_session=True)

    def start_services(self):
        if self.offline:return
        (self.root/'shared').mkdir(exist_ok=True,mode=0o700)
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
                row=json.loads(path.read_text())
                if path.stat().st_size>262144:raise ValueError('health_bound')
            except (OSError,ValueError):row=dict(phase='STARTING')
            health[lane]=dict(row,pid=proc.pid,exit_code=proc.poll(),restarts=self.restarts[lane])
        try:
            _atomic_json(self.root/'health.json',dict(paper_only=True,offline=self.offline,epoch_id=self.epoch,at=utc(now),stopping=self.stop_requested,lanes=health,python=sys.version.split()[0],sqlite=sqlite3.sqlite_version))
        except OSError as error:
            print('health publication failed:',type(error).__name__,flush=True)
        try:
            with self.account() as account:
                sequence=account.snapshot()['sequence']
                account.export_path=self.root/'portfolio.json'
                account.publish(epoch_id=self.epoch,event_id='snapshot:'+str(sequence+1),as_of=utc(now),valid_until=utc(now+30))
                if account.db.execute('SELECT COUNT(*) FROM portfolio_events').fetchone()[0]>1024:
                    account.compact()
        except (OSError,ValueError):
            # Read-only dashboard files have no authority over native execution.
            pass
        self.last_publish=time.monotonic()

    def run(self,*,seconds=None):
        self.initialize()
        started=time.monotonic()
        prior={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
        for sig in prior:signal.signal(sig,lambda *_:setattr(self,'stop_requested',True))
        try:
            self.start_services()
            for lane in ('pump','pons','meteora','ramses'):self.start_lane(lane)
            while not self.stop_requested and (seconds is None or time.monotonic()-started<seconds):
                for lane,proc in list(self.processes.items()):
                    if proc.poll() is not None and time.monotonic()>=self.next_start[lane]:
                        self.restarts[lane]+=1
                        self.next_start[lane]=time.monotonic()+min(30,2**min(self.restarts[lane],5))
                        self.start_lane(lane)
                if not self.offline and self.evidence.poll() is not None:
                    # Stop lane owners before shared evidence replacement; their
                    # next start must prove native journals and pending delivery.
                    self.stop_lanes()
                    self.start_services()
                    for lane in LANES:self.start_lane(lane)
                if time.monotonic()-self.last_publish>=2:self.publish()
                time.sleep(.05)
        finally:
            self.stop_requested=True
            self.stop_lanes()
            evidence=getattr(self,'evidence',None)
            if evidence is not None:self.stop_process(evidence,45)
            self.publish()
            for sig,handler in prior.items():signal.signal(sig,handler)
            if self.lock:self.lock.close();self.lock=None

    @staticmethod
    def stop_process(proc,timeout=15):
        if proc.poll() is not None:return
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

    def stop_lanes(self):
        for proc in self.processes.values():
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
        deadline=time.monotonic()+15
        for proc in self.processes.values():self.stop_process(proc,max(.1,deadline-time.monotonic()))
