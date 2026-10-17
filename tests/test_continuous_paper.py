"""Accelerated continuous operation. Offline providers, isolated capital only."""
from copy import deepcopy
from contextlib import closing
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from meme_machine.operational.bounded_provider import Budget,CeilingReached,DeliveredResponse,MAX_FRAME
from meme_machine.operational.position_continuation import position_only,readiness,validate_continuous
from meme_machine.operational.admission import available,require_normal
from meme_machine.operational.supervisor import Supervisor
from meme_machine.shared_capital.model import CapitalError

PROFILE=Path(__file__).resolve().parents[1]/'operational/pump-first-release/deployment/paper-continuous.pump-first.json'


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.profile=json.loads(PROFILE.read_text())
        self.path=self.root/'usage.sqlite';self.file=self.root/'profile.json'
        self.file.write_text(json.dumps(self.profile));self.budget=Budget.create(self.path,continuous=self.profile)

    def test_31_days_restart_and_more_than_eight_openings_never_exhaust_healthy_usage(self):
        initial=self.budget.snapshot();start=float(initial['started_wall'])
        for day in range(32):
            with self.subTest(day=day),patch('time.time',return_value=start+day*86400):
                b=Budget(self.path);b.preflight_file(self.file)
                # Accelerated legitimate volume, not observed provider traffic.
                b.change(dict(rpc_cu=900000,rpc_elements=12000,http_attempts=12000,http_bytes=256*1024**2))
                for _ in range(16):
                    token=b.stream_open('yellowstone');b.native('yellowstone',1024,token=token)
                    b.stream_close(token,unread_possible=True)
                self.assertFalse(position_only(path=self.path,now=start+day*86400))
                self.assertFalse(b.snapshot()['reason']);self.assertIsNone(b.seconds)
                b.admission();report=b.usage()
                self.assertEqual(report['phase'],'CONTINUOUS')
                self.assertEqual(report['lifetime']['rpc_cu'],str((day+1)*900000))
        resumed=Budget(self.path);before=resumed.snapshot()
        self.assertEqual(before['native_opens'],'512');self.assertEqual(before['native_reserved'],'0')
        self.assertGreater(int(before['native_uncertain_bytes']),512*1024**2)
        self.assertEqual(before['started_wall'],initial['started_wall'])
        with resumed.db() as db:db.execute("UPDATE run SET value='earlier-host-boot' WHERE key='boot'")
        resumed=Budget(self.path);resumed.admission()
        self.assertEqual(resumed.snapshot()['rpc_cu'],before['rpc_cu'])
        with resumed.db() as db:
            self.assertEqual(db.execute('SELECT SUM(rpc_cu) FROM usage_hours').fetchone()[0],32*900000)

    def test_normal_deployment_selects_all_four_regimes_and_verified_pacing(self):
        folder=PROFILE.parent
        profile=json.loads((folder/'paper-continuous.four-regime.json').read_text())
        from meme_machine.operational.position_continuation import validate_continuous
        validate_continuous(profile)
        self.assertEqual(set(profile['funding_regimes']),{'pump_current','pump_survivor','pons_current','pons_survivor'})
        self.assertEqual(profile['physical_http_start_interval_seconds'],'0.5')
        self.assertEqual(profile['robinhood_http_start_interval_seconds'],'0.1')
        command=(folder/'paper-continuous.conf').read_text()
        self.assertIn('MM_CONTINUOUS_PROVIDER_ENVELOPE=/etc/meme-machine/paper-continuous.four-regime.json',command)
        self.assertIn('RuntimeMaxSec=infinity',command)
        self.assertIn('MM_VOLUME_QUALITY_ENABLED=1',command)

    def test_spend_warnings_do_not_close_admission_or_mutate_provider_health(self):
        b=self.budget;b.change(dict(rpc_cu=200000000))
        before=b.snapshot();r=b.usage();b.admission()
        self.assertEqual(b.snapshot(),before)
        self.assertTrue({'provider_spend_hourly_warning','provider_spend_daily_warning','provider_spend_monthly_warning'}<=set(r['warnings']))
        from meme_machine.operational.monitoring import protection_allowance_conditions
        self.assertEqual(protection_allowance_conditions(r),set(r['warnings']))
        self.assertFalse(r['provider_fault'])

    def test_inflight_capacity_blocks_only_excess_new_transport_and_recovers_without_refill(self):
        b=self.budget
        capacity=b.limits['native_inflight_bytes']//(4*MAX_FRAME)
        tokens=[b.stream_open('yellowstone') for _ in range(capacity)];before=b.snapshot()
        with self.assertRaisesRegex(CeilingReached,'native_inflight_limit'):b.stream_open('yellowstone')
        after=b.snapshot();self.assertEqual(after['native_opens'],before['native_opens'])
        self.assertFalse(after['reason']);self.assertEqual(after['new_risk_ready'],'false')
        # Existing priced protective RPC remains available during stream pressure.
        response=b.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getMultipleAccounts')])
        with DeliveredResponse(io.BytesIO(b'[]'),response) as delivered:delivered.read()
        for token in tokens:b.stream_close(token,unread_possible=True)
        b.stream_close(b.stream_open('yellowstone'));b.admission()
        self.assertEqual(b.snapshot()['native_opens'],str(capacity+1))

    def test_http_response_reservations_bound_current_memory_not_cumulative_bytes(self):
        b=self.budget;calls=[dict(method='getMultipleAccounts')];endpoint='https://solana-mainnet.g.alchemy.com/v2/offline'
        receipts=[b.reserve_http(endpoint,calls) for _ in range(8)]
        with self.assertRaisesRegex(CeilingReached,'http_inflight_limit'):b.reserve_http(endpoint,calls)
        self.assertEqual(b.snapshot()['rpc_elements'],'8')
        for receipt in receipts:receipt.close()
        next_receipt=b.reserve_http(endpoint,calls);next_receipt.close()
        self.assertEqual(b.snapshot()['rpc_elements'],'9');self.assertFalse(b.snapshot()['reason'])
        self.assertGreater(int(b.snapshot()['http_uncertain_bytes']),self.profile['limits']['http_inflight_bytes'])

    def test_repeated_native_failures_back_off_durably_while_protection_retains_priority(self):
        b=self.budget;now=time.time();token=b.stream_open('yellowstone')
        with patch('time.time',return_value=now):
            for _ in range(8):b.provider_error('native_stream_read_failed')
            resumed=Budget(self.path)
            with self.assertRaisesRegex(CeilingReached,'native_reconnect_circuit_open'):resumed.stream_open('yellowstone')
            resumed.native('yellowstone',7,token=token)
            receipt=resumed.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getMultipleAccounts')]);receipt.close()
            self.assertFalse(resumed.snapshot()['reason']);self.assertEqual(resumed.snapshot()['new_risk_ready'],'false')
        with patch('time.time',return_value=now+31):
            resumed=Budget(self.path);next_token=resumed.stream_open('yellowstone');resumed.stream_close(next_token)
            self.assertEqual(resumed.snapshot()['native_failures'],'8')
            self.assertEqual(resumed.snapshot()['native_opens'],'2')
            self.assertFalse(resumed.snapshot()['new_risk_ready']=='true')
        b.stream_close(token)

    def test_orphan_recovery_preserves_usage_once_without_charging_freed_memory_forever(self):
        b=self.budget;b.stream_open('yellowstone')
        receipt=b.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getMultipleAccounts')])
        before=b.snapshot()
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
            b.reap_orphans();resumed=Budget(self.path);resumed.reap_orphans()
        after=resumed.snapshot();self.assertEqual(after['native_reserved'],after['http_reserved']);self.assertEqual(after['http_reserved'],'0')
        self.assertEqual(after['native_uncertain_bytes'],str(4*MAX_FRAME));self.assertEqual(after['rpc_cu'],before['rpc_cu'])
        receipt.close();self.assertEqual(resumed.snapshot(),after)

    def test_response_frame_unpriced_method_and_configuration_guards_are_still_fatal(self):
        with self.assertRaisesRegex(CeilingReached,'unpriced_or_writing'):self.budget.reserve_http(
            'https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='sendTransaction')])
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')
        other=Budget.create(self.root/'frame.sqlite',continuous=self.profile);token=other.stream_open('yellowstone')
        with self.assertRaisesRegex(CeilingReached,'native_frame_bound'):other.native('yellowstone',MAX_FRAME+1,token=token)
        self.assertEqual(other.snapshot()['native_bytes'],'0')
        changed=Budget.create(self.root/'changed.sqlite',continuous=self.profile)
        with changed.db() as db:db.execute("UPDATE run SET value='10' WHERE key='modeled_spend_limit'")
        with self.assertRaises(CeilingReached):Budget(changed.path)
        self.assertEqual(changed.snapshot()['rpc_cu'],'0')

    def test_test_allowance_cannot_leak_into_continuous_transport_installation(self):
        from meme_machine.operational.bounded_provider import install
        with patch.dict(os.environ,MM_PROVIDER_OPERATION_MODE='CONTINUOUS',MM_PROVIDER_USAGE_DB=str(self.path),
                MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.file),MM_BOUNDED_PROVIDER_DB='consumed-test.sqlite'),patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError,'cannot_inherit'):install()
        network.assert_not_called();self.assertEqual(self.budget.snapshot()['http_attempts'],'0')
        bad=deepcopy(self.profile);bad['maximum_native_opens']=8
        with self.assertRaises(CapitalError):validate_continuous(bad)

    def test_operational_governor_uses_declared_two_rps_without_changing_historical_engineering(self):
        from meme_machine.runtime.governor import Governor
        from tests.test_bounded_provider_preflight import LIMITS,observation_file
        bounded=Budget.create(self.root/'bounded.sqlite',limits=LIMITS)
        file=observation_file(self.root,bounded)
        with patch.dict(os.environ,MM_SOLANA_EVIDENCE_PLANE_DB='offline',
                MM_BOUNDED_PROVIDER_DB=str(bounded.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(file)):
            self.assertEqual(Governor(self.root/'bounded-governor.sqlite').solana_interval,.5)
        with patch.dict(os.environ,MM_PROVIDER_OPERATION_MODE='CONTINUOUS',MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.file)):
            self.assertEqual(Governor(self.root/'continuous-governor.sqlite').solana_interval,.5)

    def test_bounded_continuation_pacing_does_not_reuse_an_expired_bootstrap_gate(self):
        from tests.test_position_continuation import envelope
        from meme_machine.operational.position_continuation import provider_interval
        bounded=Budget.create(self.root/'legacy-continuation.sqlite',continuation=envelope())
        with bounded.db() as db:db.execute("UPDATE run SET value='1' WHERE key='started_wall'")
        with patch.dict(os.environ,MM_PROVIDER_OPERATION_MODE='VALIDATION',MM_BOUNDED_PROVIDER_DB=str(bounded.path),
                MM_BOUNDED_PROVIDER_ENVELOPE=''):
            self.assertEqual(provider_interval('robinhood'),.5)
        self.assertEqual(Budget(bounded.path).snapshot()['rpc_cu'],'0')

    def test_explicit_robinhood_profile_preserves_usage_and_removes_both_serial_pacers(self):
        from meme_machine.lanes.pons.provider_admission import Admission
        from meme_machine.lanes.pons.provider_topology import configured_rpc
        endpoint='https://robinhood-mainnet.g.alchemy.com/v2/offline-fixture'
        path=self.root/'robinhood.sqlite'
        Admission(path,endpoint,lane='pons')
        profile=deepcopy(self.profile);profile['robinhood_http_start_interval_seconds']='0.25'
        self.file.write_text(json.dumps(profile))
        with patch.dict(os.environ,MM_PROVIDER_OPERATION_MODE='CONTINUOUS',MM_CONTINUOUS_PROVIDER_ENVELOPE=str(self.file),
                MM_PROVIDER_DB=str(path),MM_RPC_CACHE_DB=str(self.root/'cache.sqlite'),MM_RUNTIME_LANE='pons',
                MM_ROBINHOOD_READ_RPC_URL=endpoint,MM_ROBINHOOD_DLMM_RPC_URL=''):
            rpc=configured_rpc(endpoint,transport=lambda m,p:'0x1237')
            self.assertEqual(rpc.shared_admission.interval,.25)
            self.assertEqual(rpc.pacer.minimum_interval_seconds,.25)
            clock=[101.]
            def advance(seconds):clock[0]+=seconds
            rpc.shared_admission.clock=rpc.pacer.clock=lambda:clock[0]
            rpc.shared_admission.sleep=rpc.pacer.sleep=advance
            starts=[]
            for _ in range(4):
                rpc.pacer.pace()
                rpc.shared_admission.acquire('position_monitor')
                starts.append(clock[0]);advance(.01)
            self.assertEqual(starts,[101.,101.25,101.5,101.75])
            with closing(rpc.shared_admission.connect()) as db:
                self.assertEqual(db.execute('SELECT interval FROM limits').fetchone()[0],.25)
            rpc.verify_chain()
        self.assertEqual(self.budget.snapshot()['rpc_cu'],'0')


class AdmissionTests(unittest.TestCase):
    from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests as Native
    fixture=Native.fixture

    def service(self,*,all_regimes=False):
        from tests.test_shared_portfolio_epoch import shared_risk_candidate
        root,a,now,_=self.fixture(policy=shared_risk_candidate(),owners=False,new_epoch=True)
        profile=json.loads(PROFILE.read_text())
        if all_regimes:profile['funding_regimes']+=['pons_current','pons_survivor']
        file=root/'continuous.json';file.write_text(json.dumps(profile))
        env=patch.dict(os.environ,MM_PROVIDER_OPERATION_MODE='CONTINUOUS',MM_STATE_ROOT=str(root),
            MM_PROVIDER_USAGE_DB=str(root/'shared/continuous.sqlite'),MM_CONTINUOUS_PROVIDER_ENVELOPE=str(file),
            MM_BOUNDED_PROVIDER_DB='',MM_BOUNDED_PROVIDER_ENVELOPE='',MM_POSITION_CONTINUATION_ENVELOPE='')
        env.start();self.addCleanup(env.stop)
        s=Supervisor(root,offline=True,admission='NORMAL');s.shared_capital=a;s.configure_admission()
        for r in profile['funding_regimes']:a.owner(r,'offline-native-owner',os.getpid(),ready=True,at=now)
        return root,a,now,s

    def test_four_regime_scope_uses_one_approved_equity_and_excludes_paused_families(self):
        root,a,now,s=self.service(all_regimes=True)
        from meme_machine.shared_capital.runtime import allocation_regimes
        self.assertEqual(allocation_regimes(a.ledger()),('pump_current','pump_survivor','pons_current','pons_survivor'))
        s.provider_budget.publish_readiness(True,s.run_id)
        for regime in ('pump_current','pump_survivor','pons_current','pons_survivor'):
            self.assertIsNone(available(a.ledger(),time.time(),live=True,regime=regime))
        self.assertEqual(a.ledger()['cash'],'1000.00');self.assertFalse(a.ledger()['positions'])
        a.verify_replay()

    def test_continuous_observation_preserves_usage_and_cannot_open_funding(self):
        root,a,now,prior=self.service(all_regimes=True)
        prior.provider_budget.change(dict(rpc_cu=900000,http_attempts=2000,native_bytes=1024**3))
        before=prior.provider_budget.snapshot()
        economics={k:deepcopy(a.ledger()[k]) for k in ('cash','positions','realized','policy','inception')}
        for _ in range(2):
            observed=Supervisor(root,offline=True,admission='OBSERVATION')
            observed.shared_capital=a;observed.epoch=a.ledger()['epoch_id'];observed.configure_admission()
            self.assertEqual(observed.runtime_lanes(),('pump','pons'))
            self.assertEqual(a.ledger()['runtime_admission']['mode'],'OBSERVATION')
            self.assertEqual(a.ledger()['runtime_admission']['continuous_provider_db'],str(prior.provider_budget.path))
            for lane in ('pump','pons','solana'):
                child=observed.environment(lane)
                self.assertEqual(child['MM_PROVIDER_OPERATION_MODE'],'CONTINUOUS')
                self.assertEqual(child['MM_PROVIDER_USAGE_DB'],str(prior.provider_budget.path))
                self.assertNotIn('MM_BOUNDED_PROVIDER_DB',child)
            observed.provider_budget.publish_readiness(True,observed.run_id)
            for regime in ('pump_current','pump_survivor','pons_current','pons_survivor'):
                self.assertEqual(available(a.ledger(),time.time(),live=True,regime=regime),
                    'observation_only_funding_closed')
            self.assertEqual({k:a.ledger()[k] for k in economics},economics)
            self.assertEqual({k:observed.provider_budget.snapshot()[k] for k in ('rpc_cu','http_attempts','native_bytes','started_wall')},
                {k:before[k] for k in ('rpc_cu','http_attempts','native_bytes','started_wall')})
            a.verify_replay()

    def test_continuous_observation_refuses_lost_usage_history(self):
        root,a,now,prior=self.service()
        prior.provider_budget.path.unlink()
        observed=Supervisor(root,offline=True,admission='OBSERVATION');observed.shared_capital=a
        with self.assertRaisesRegex(ValueError,'restore_not_reseed'):
            observed.configure_admission()

    def test_enabling_independently_proven_family_keeps_lifetime_usage_and_closes_stale_readiness(self):
        root,a,now,s=self.service();b=s.provider_budget
        b.change(dict(rpc_cu=123456,http_attempts=123,native_bytes=987654));b.publish_readiness(True,s.run_id)
        old=b.snapshot();profile=deepcopy(b.envelope);profile['funding_regimes']+=['pons_current','pons_survivor']
        file=Path(os.environ['MM_CONTINUOUS_PROVIDER_ENVELOPE']);file.write_text(json.dumps(profile))
        resumed=Supervisor(root,offline=True,admission='NORMAL');resumed.shared_capital=a;resumed.configure_admission()
        current=resumed.provider_budget.snapshot()
        for key in ('started_wall','rpc_cu','http_attempts','native_bytes'):
            self.assertEqual(current[key],old[key])
        self.assertEqual(current['new_risk_ready'],'false')
        self.assertEqual(len(json.loads(current['continuous_configuration_changes'])),1)
        self.assertEqual(a.ledger()['runtime_admission']['funding_regimes'],profile['funding_regimes'])
        self.assertEqual(a.ledger()['cash'],'1000.00');a.verify_replay()

    def test_current_and_survivor_scope_has_no_test_age_or_lifecycle_count_and_no_pons_quorum(self):
        root,a,now,s=self.service();scope=a.ledger()['runtime_admission']
        self.assertFalse(any(k in scope for k in ('funding_until','stop_at','lifecycle_id','gross_reserved','continuation_envelope')))
        from meme_machine.shared_capital.runtime import allocation_regimes
        self.assertEqual(allocation_regimes(a.ledger()),('pump_current','pump_survivor'))
        for day in (1,7,30):
            at=now+day*86400
            with patch('time.time',return_value=at):
                s.provider_budget.publish_readiness(True,s.run_id)
                self.assertIsNone(available(a.ledger(),at,live=True,regime='pump_current'))
                self.assertIsNone(available(a.ledger(),at,live=True,regime='pump_survivor'))
                self.assertEqual(available(a.ledger(),at,live=True,regime='pons_current'),'selected_regime_not_ready')
        self.assertEqual(a.ledger()['cash'],'1000.00');a.verify_replay()

    def test_restart_preserves_accounting_and_usage_but_demands_fresh_protection_again(self):
        root,a,now,s=self.service();s.provider_budget.change(dict(rpc_cu=900000,native_bytes=1024**3))
        before=s.provider_budget.snapshot();economics={k:deepcopy(a.ledger()[k]) for k in ('cash','positions','realized','policy','inception')}
        resumed=Supervisor(root,offline=True,admission='NORMAL');resumed.shared_capital=a;resumed.configure_admission()
        self.assertEqual(resumed.run_id,s.run_id)
        for k in ('started_wall','rpc_cu','native_bytes'):self.assertEqual(resumed.provider_budget.snapshot()[k],before[k])
        self.assertEqual({k:a.ledger()[k] for k in economics},economics)
        self.assertEqual(available(a.ledger(),now,live=True,regime='pump_current'),'selected_regime_current_protection_not_ready')
        a.verify_replay()

    def test_restart_registers_new_process_identity_without_reusing_an_old_command(self):
        root,a,now,s=self.service();before=s.provider_budget.snapshot()
        resumed=Supervisor(root,offline=True,admission='NORMAL');resumed.shared_capital=a
        with patch('meme_machine.shared_capital.runtime.process_identity',return_value='new-process-start'),patch('time.time',return_value=now+86400):
            resumed.configure_admission()
        scope=a.ledger()['runtime_admission']
        self.assertEqual(scope['process_start'],'new-process-start');self.assertEqual(scope['run_id'],s.run_id)
        self.assertEqual(resumed.provider_budget.snapshot()['started_wall'],before['started_wall'])
        self.assertEqual(resumed.provider_budget.snapshot()['new_risk_ready'],'false');a.verify_replay()

    def test_normal_readiness_requires_progressing_current_coverage_and_survives_day_30(self):
        root,a,now,s=self.service()
        from tests.test_position_continuation import healthy
        health,portfolio,rss=healthy();health['providers'].pop('robinhood');health['lanes'].pop('pons')
        rows=[dict(scope='candidate:'+family,slot=100,updated=now,market_time=now) for family in ('pump','pumpswap')]
        health['providers']['evidence']['program_frontiers']=rows
        with patch('meme_machine.operational.acceptance.observe',return_value=(health,portfolio,rss)),patch('time.time',return_value=now):
            s.normal_tick();self.assertFalse(s.provider_budget.usage()['new_risk_ready'])
            s.ready_since-=61
            for r in rows:r['slot']+=1
            s.normal_tick();self.assertTrue(s.provider_budget.usage()['new_risk_ready'])
            health['providers']['evidence']['startup_released']=False
            s.normal_tick();self.assertFalse(s.provider_budget.usage()['new_risk_ready'])
            health['providers']['evidence']['startup_released']=True;s.ready_since=time.monotonic()-61
            rows[0]['market_time']=now-20
            s.normal_tick();self.assertFalse(s.provider_budget.usage()['new_risk_ready'])
        with patch('meme_machine.operational.acceptance.observe',return_value=(health,portfolio,rss)),patch('time.time',return_value=now+30*86400):
            for r in rows:r.update(slot=100000,updated=now+30*86400,market_time=now+30*86400)
            s.normal_tick();s.ready_since-=61
            for r in rows:r['slot']+=1
            s.normal_tick();self.assertTrue(s.provider_budget.usage()['new_risk_ready'])

    def test_health_never_attaches_new_market_time_to_an_older_unpublished_checkpoint(self):
        root,a,now,s=self.service()
        from types import SimpleNamespace
        from meme_machine.solana_evidence_plane import EvidenceWriter
        from meme_machine.solana_evidence_service import FinalizedFence
        from meme_machine.solana_selective_source import install
        from meme_machine.solana_rolling_history import program_scope
        path=root/'shared/solana-evidence.sqlite'
        with closing(EvidenceWriter(path)) as writer:
            state=SimpleNamespace(writer=writer,fence=FinalizedFence(writer,endpoint_identity='a'*64))
            install(state)
            scope=program_scope('pump')
            writer.db.execute('INSERT INTO candidate_checkpoints VALUES(?,?,?,?)',(scope,100,'receipt',time.time()))
            writer.db.execute('INSERT INTO candidate_blocks VALUES(?,?,?,?,?,?,?,?,?)',
                (scope,500,499,'h500','h499',int(time.time()),time.time(),'session','census'))
            self.assertEqual(s.provider_health()['evidence']['program_checkpoints'],[])
            writer.db.execute('UPDATE candidate_blocks SET slot=101 WHERE scope=?',(scope,))
            rows=s.provider_health()['evidence']['program_checkpoints']
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['slot'],100)

    def test_live_funding_expires_on_health_not_spend_and_dead_supervisor_never_grants(self):
        root,a,now,s=self.service();b=s.provider_budget
        with patch('time.time',return_value=now):
            b.change(dict(rpc_cu=200000000));b.publish_readiness(True,s.run_id)
            require_normal(state=a.ledger(),at=now,regime='pump_current')
            with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
                self.assertEqual(available(a.ledger(),now,live=True),'selected_regime_current_protection_not_ready')
        self.assertEqual(available(a.ledger(),now+6,live=True),'selected_regime_current_protection_not_ready')
        self.assertFalse(b.snapshot()['reason'])

    def test_read_only_acceptance_admission_uses_the_existing_reader_without_writer_setup(self):
        root,a,now,s=self.service(all_regimes=True)
        before=a.verify_replay()['events']
        with patch('time.time',return_value=now):
            s.provider_budget.publish_readiness(True,s.run_id)
            with patch('meme_machine.shared_capital.authority.CapitalAuthority.__init__',side_effect=AssertionError('writer setup forbidden')):
                profile=require_normal(at=now)
                self.assertEqual(set(profile['funding_regimes']),{'pump_current','pump_survivor','pons_current','pons_survivor'})
        self.assertEqual(a.verify_replay()['events'],before)

    def test_physical_queue_memory_and_exit_evidence_guards_remain_mandatory(self):
        root,a,now,s=self.service()
        from tests.test_position_continuation import healthy
        for failure in ('queue','rss','exit','evidence','reconciliation'):
            h,p,rss=healthy()
            if failure=='queue':h['providers']['solana']['oldest_wait_seconds']=6
            elif failure=='rss':rss=6*1024**3
            elif failure=='exit':h['lanes']['pump']['native_continuation']['exit_path_bound']=False
            elif failure=='evidence':h['providers']['evidence']['startup_released']=False
            elif failure=='reconciliation':p['reconciliation']['checks']['exact_conservation']=False
            with self.subTest(failure=failure),self.assertRaises(ValueError):readiness(h,p,rss,s.provider_budget.envelope)
        self.assertEqual(a.ledger()['positions'],{});a.verify_replay()

    def test_original_native_partial_settlement_then_next_lifecycle_compounds_shared_equity(self):
        root,a,now,s=self.service()
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.directional_continuation import native_sync
        from meme_machine.runtime.usd_valuation import USDValue
        from meme_machine.shared_capital.native_sleeve import FundingDenied
        (root/'pump').mkdir(exist_ok=True)
        policy=policies('pump');strategy=next(r for r in policy if 'survivor' not in r)
        book=PaperBook(root/'pump/native-continuous.sqlite',run_id=a.ledger()['epoch_id'],lane=strategy,
            policy_hash=policy[strategy],initial=1000000);self.addCleanup(book.close)
        sleeve=open_sleeve('pump',1000000);self.addCleanup(sleeve.close)
        fresh=lambda at:USDValue('offline-native',3,Decimal('1'),at-1,at+5,'offline-usd','e'*64)
        # New oracle evidence on each accelerated day, with the original TTL.
        # The fixture's original fixed oracle intentionally expires at day one.
        book.portfolio.value_reader=fresh
        with patch('meme_machine.runtime.usd_valuation.native_reader',return_value=fresh):
            for number,day in enumerate((0,7,30)):
                at=now+day*86400
                with patch('time.time',return_value=at):
                    s.provider_budget.publish_readiness(True,s.run_id)
                    units=sleeve.sizing_basis(500)['target'];identity=a.ledger()['epoch_id']+':original:'+str(number)
                    sleeve.reserve(identity,strategy=strategy,amount=units,at=at,asset=identity,
                        funding_evidence=dict(qualified=True,policy_hash=policy[strategy]))
                    book.reserve(identity,units,at,dict(qualified=True))
                    book.transition(identity,'filled',at,amount=units,tokens=100,evidence=dict(execution={'gas':0}))
                    book.transition(identity,'mark',at,amount=units);native_sync(book,sleeve,identity)
                    book.transition(identity,'partial_harvest',at+1,amount=units//4+2500,tokens=25);native_sync(book,sleeve,identity)
                    book.transition(identity,'settled',at+2,amount=units-units//4+2500);native_sync(book,sleeve,identity)
                    self.assertEqual(Decimal(a.snapshot()['capital']['deployed_basis']),0)
                    self.assertEqual(Decimal(a.snapshot()['capital']['actual_cash']),Decimal('1000')+Decimal(number+1)*5)
                    self.assertTrue(book.replay()['verified']);a.verify_replay()
            self.assertEqual(sleeve.sizing_basis(500)['target'],50750)
            # Removing count/age fences never makes invalid USD spendable.
            from meme_machine.runtime.usd_valuation import ValuationUnavailable
            with patch('meme_machine.runtime.usd_valuation.native_reader',side_effect=ValuationUnavailable('offline_stale_USD')):
                with self.assertRaises((FundingDenied,ValuationUnavailable)):
                    sleeve.reserve('invalid-usd',strategy=strategy,amount=50750,at=at+3,asset='invalid',funding_evidence=dict(qualified=True))

    def test_missing_usage_history_requires_restoration_and_never_reseeds_counters(self):
        root,a,now,s=self.service();original=s.provider_budget.path
        preserved=original.with_name('preserved.sqlite');original.rename(preserved)
        resumed=Supervisor(root,offline=True,admission='NORMAL');resumed.shared_capital=a
        with self.assertRaisesRegex(ValueError,'restore_not_reseed'):resumed.configure_admission()
        self.assertFalse(original.exists());self.assertTrue(preserved.exists());a.verify_replay()

    def test_delayed_shared_USD_sizing_and_grant_keep_original_expiry(self):
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.usd_valuation import USDValue,ValuationUnavailable
        root,a,now,s=self.service(all_regimes=True)
        sleeve=open_sleeve('pump',1000000);self.addCleanup(sleeve.close)
        strategy=next(k for k in policies('pump') if 'survivor' not in k)
        clock=[now]
        def delayed(at):
            clock[0]=max(clock[0],now+3)
            return USDValue('offline-native',3,Decimal('1'),now+2,now+5,'delayed','e'*64)
        with patch('time.time',side_effect=lambda:clock[0]),patch('meme_machine.runtime.usd_valuation.native_reader',return_value=delayed):
            s.provider_budget.publish_readiness(True,s.run_id)
            basis=sleeve.sizing_basis(500)
            self.assertEqual((basis['target'],basis['available']),(50000,1000000))
            sleeve.reserve('delayed-grant',strategy=strategy,amount=50000,at=now,asset='delayed-grant',
                funding_evidence=dict(qualified=True,policy_hash=policies('pump')[strategy]))
            req=next(iter(a.ledger()['requests'].values()))['value']
            self.assertEqual(req['valuation']['valid_until'],now+5)
            before=a.ledger()
            clock[0]=now+6
            s.provider_budget.publish_readiness(True,s.run_id)
            with self.assertRaises(ValuationUnavailable):sleeve.sizing_basis(500)
            with self.assertRaises(ValuationUnavailable):
                sleeve.reserve('expired-grant',strategy=strategy,amount=50000,at=now,asset='expired-grant',
                    funding_evidence=dict(qualified=True,policy_hash=policies('pump')[strategy]))
            self.assertEqual(a.ledger(),before)
        a.verify_replay()

    def test_failed_evidence_recovery_does_not_kill_native_owner_or_reset_backoff(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        root,a,now,s=self.service();s.evidence=SimpleNamespace(pid=1234,poll=lambda:None)
        s.start_services=Mock();s.stop_lanes=Mock()
        with patch('time.time',return_value=now):
            s.recover_evidence();s.recover_evidence()
            self.assertEqual(s.provider_budget.snapshot()['native_failures'],'1')
            s.start_services.assert_not_called();s.stop_lanes.assert_not_called()
            self.assertFalse(s.provider_budget.usage()['new_risk_ready'])
        with patch('time.time',return_value=now+3):s.recover_evidence()
        s.start_services.assert_called_once();s.stop_lanes.assert_not_called()

    def test_pump_only_environment_has_no_robinhood_startup_dependency(self):
        from meme_machine.operational.supervisor import validate_environment
        with patch.dict(os.environ,MM_ROBINHOOD_READ_RPC_URL=''):
            validate_environment(required_lanes=('pump',))
            with self.assertRaises(Exception):validate_environment(required_lanes=('pons',))


if __name__=='__main__':unittest.main()
