"""CPU configuration portability; isolated host/cgroup fixtures, no market I/O."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational.position_continuation import (
    cpu_capacity,validate_continuous,validate_envelope)
from meme_machine.operational.supervisor import SOURCE_ROOT,Supervisor
from meme_machine.shared_capital.model import CapitalError


def profiles():
    return (
        (validate_continuous,json.loads((SOURCE_ROOT/
            'operational/pump-first-release/deployment/paper-continuous.four-regime.json').read_text())),
        (validate_envelope,json.loads((SOURCE_ROOT/
            'operational/position-continuation/RESOURCE_ENVELOPE.example.json').read_text())),
        (validate_envelope,json.loads((SOURCE_ROOT/
            'operational/position-continuation/RESOURCE_ENVELOPE.maintenance.example.json').read_text())),
    )


class CpuProfileTests(unittest.TestCase):
    def host(self,count=4,affinity=None):
        self.enterContext(patch('meme_machine.operational.position_continuation.os.cpu_count',return_value=count))
        self.enterContext(patch('meme_machine.operational.position_continuation.os.sched_getaffinity',
            return_value=set(range(count if affinity is None else affinity))))

    def test_existing_profiles_retain_explicit_one_point_eight_default(self):
        self.host(2)
        for validate,profile in profiles():
            with self.subTest(schema=profile['schema']):
                before=deepcopy(profile)
                self.assertIs(validate(profile),profile)
                self.assertEqual(profile,before)
                self.assertEqual(cpu_capacity(profile),Decimal('1.8'))

    def test_explicit_three_point_six_is_valid_on_four_available_cpus(self):
        self.host(4)
        for validate,profile in profiles():
            with self.subTest(schema=profile['schema']):
                profile['maximum_cpu_cores']='3.6'
                self.assertIs(validate(profile),profile)
                self.assertEqual(cpu_capacity(profile),Decimal('3.6'))

    def test_larger_profile_is_rejected_on_two_cpu_host_or_two_cpu_affinity(self):
        for count,affinity in ((2,2),(4,2),(2,4)):
            with self.subTest(count=count,affinity=affinity), \
                    patch('meme_machine.operational.position_continuation.os.cpu_count',return_value=count), \
                    patch('meme_machine.operational.position_continuation.os.sched_getaffinity',
                        return_value=set(range(affinity))):
                for validate,profile in profiles():
                    profile['maximum_cpu_cores']='3.6'
                    with self.assertRaisesRegex(CapitalError,'host_bounded_cpu_capacity'):
                        validate(profile)

    def test_nonfinite_nonpositive_nonstring_missing_and_overhost_capacity_fail_closed(self):
        self.host(4)
        for value in ('NaN','sNaN','Infinity','-Infinity','0','-0.1','4.0001','',None,True,4,3.6):
            for validate,profile in profiles():
                with self.subTest(value=value,schema=profile['schema']):
                    profile['maximum_cpu_cores']=value
                    with self.assertRaisesRegex(CapitalError,'host_bounded_cpu_capacity'):
                        validate(profile)
        for validate,profile in profiles():
            del profile['maximum_cpu_cores']
            with self.assertRaises(CapitalError):validate(profile)

    def test_cpu_availability_failure_cannot_accept_an_unverified_capacity(self):
        self.host(4)
        with patch('meme_machine.operational.position_continuation.os.sched_getaffinity',side_effect=OSError):
            with self.assertRaisesRegex(CapitalError,'host_bounded_cpu_capacity'):
                cpu_capacity(dict(maximum_cpu_cores='1.8'))
        with patch('meme_machine.operational.position_continuation.os.sched_getaffinity',return_value=set()):
            with self.assertRaisesRegex(CapitalError,'host_bounded_cpu_capacity'):
                cpu_capacity(dict(maximum_cpu_cores='1.8'))

    def test_cpu_configuration_preserves_queue_memory_and_recovery_guards(self):
        self.host(4)
        for validate,profile in profiles():
            profile['maximum_cpu_cores']='3.6'
            for key,value in (('maximum_queue_depth',65),('maximum_queue_wait_seconds',6),
                    ('maximum_rss_bytes',7*1024**3)):
                with self.subTest(schema=profile['schema'],key=key):
                    bad=deepcopy(profile);bad[key]=value
                    with self.assertRaises(CapitalError):validate(bad)
            if 'continuation' in profile:
                for key,value in (('recovery_seconds',3601),('maximum_reconnects',33)):
                    bad=deepcopy(profile);bad[key]=value
                    with self.assertRaises(CapitalError):validate(bad)
                bad=deepcopy(profile);bad['continuation']['native_inflight_bytes']=1
                with self.assertRaises(CapitalError):validate(bad)
            else:
                bad=deepcopy(profile);bad['limits']['native_inflight_bytes']=1
                with self.assertRaises(CapitalError):validate(bad)
                bad=deepcopy(profile);bad['failures_before_backoff']=9
                with self.assertRaises(CapitalError):validate(bad)


class SupervisorCpuTests(unittest.TestCase):
    def sample(self,*,configured='3.6',quota='360000 100000',host=4,
            memory_high=6*1024**3,memory_max=7*1024**3,queue_depth=0,queue_wait=0):
        now=1000.
        service=Supervisor.__new__(Supervisor)
        profile=profiles()[0][1];profile['maximum_cpu_cores']=configured
        service.provider_budget=SimpleNamespace(envelope=profile)
        service.runtime_lanes=lambda:('pons',)
        service.providers_for_sample=lambda sample:sample
        service.shared_capital=SimpleNamespace(ledger=lambda:dict(positions={}))
        service.last_native_health=dict(pons=dict(progress_at=now,reconciled=True))
        sample=dict(robinhood=dict(state='CURRENT',queue_depth=queue_depth,oldest_wait_seconds=queue_wait))
        files={'memory.current':'1024','cpu.stat':'usage_usec 2000000\n','cpu.max':quota,
            'memory.high':str(memory_high),'memory.max':str(memory_max)}
        with patch('meme_machine.operational.position_continuation.os.cpu_count',return_value=host), \
                patch('meme_machine.operational.position_continuation.os.sched_getaffinity',
                    return_value=set(range(host))), \
                patch('meme_machine.operational.supervisor.time.time',return_value=now), \
                patch.object(Path,'read_text',lambda path,*args,**kwargs:files[path.name]):
            service.continuation_health(provider_sample=sample)
        return service

    def test_actual_continuation_health_verifies_explicit_four_cpu_profile(self):
        service=self.sample()
        self.assertTrue(service.resource_measurement['limits_verified'])
        self.assertEqual(service.resource_measurement['cpu_quota_cores'],3.6)
        self.assertEqual(service.resource_measurement['configured_cpu_cores'],'3.6')
        self.assertIsNone(service.current_readiness_failure)

    def test_measured_quota_is_reported_instead_of_assumed_profile_limit(self):
        service=self.sample(configured='1.8',quota='140000 100000',host=2)
        self.assertTrue(service.resource_measurement['limits_verified'])
        self.assertEqual(service.resource_measurement['cpu_quota_cores'],1.4)
        self.assertEqual(service.resource_measurement['configured_cpu_cores'],'1.8')

    def test_unbounded_and_excess_quota_do_not_verify_resource_limits(self):
        for quota in ('max 100000','400000 100000','360001 100000',
                '3600000000000000001 1000000000000000000'):
            with self.subTest(quota=quota):
                service=self.sample(quota=quota)
                self.assertFalse(service.resource_measurement['limits_verified'])
                self.assertEqual(service.current_readiness_failure,
                    'continuation_existing_service_resource_limits_unavailable')
                if quota.startswith('max'):
                    self.assertIsNone(service.resource_measurement['cpu_quota_cores'])
                    self.assertEqual(service.resource_measurement['cpu_quota_state'],'UNBOUNDED')

    def test_invalid_cgroup_quota_or_capacity_never_verifies_limits(self):
        for quota in ('0 100000','-1 100000','360000 0','360000 -1','NaN 100000',
                'Infinity 100000','360000','9'*400+' 1'):
            with self.subTest(quota=quota):
                service=self.sample(quota=quota)
                self.assertIsNot(service.resource_measurement.get('limits_verified'),True)
                self.assertIsNotNone(service.current_readiness_failure)
        service=self.sample(host=2)
        self.assertEqual(service.resource_measurement['state'],'UNAVAILABLE')
        self.assertIsNotNone(service.current_readiness_failure)
        service=self.sample(configured='1e-999999',quota='1 100000')
        self.assertFalse(service.resource_measurement['limits_verified'])

    def test_existing_memory_and_provider_queue_guards_still_close_readiness(self):
        for settings in (dict(memory_high=6*1024**3+1),dict(memory_max=7*1024**3+1)):
            with self.subTest(settings=settings):
                service=self.sample(**settings)
                self.assertFalse(service.resource_measurement['limits_verified'])
                self.assertIsNotNone(service.current_readiness_failure)
        for settings in (dict(queue_depth=65),dict(queue_wait=6)):
            with self.subTest(settings=settings):
                service=self.sample(**settings)
                self.assertTrue(service.resource_measurement['limits_verified'])
                self.assertIn('protective_queue',service.current_readiness_failure)


if __name__=='__main__':unittest.main()
