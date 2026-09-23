import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from certification.lifecycle_timing import (
    METEORA_PREENTRY_RESERVE_SECONDS,
    RAMSES_MAX_HOLD_SECONDS,
    RAMSES_RECENTER_DEADLINE_SECONDS,
    RAMSES_RECENTER_TARGET_SECONDS,
    install_meteora,
    meteora_preentry_remaining_ok,
)


class LifecycleTimingTests(unittest.TestCase):
    def test_meteora_preentry_reserve_is_exact_trigger_warmup_plus_evidence(self):
        self.assertEqual(METEORA_PREENTRY_RESERVE_SECONDS,162)
        self.assertFalse(meteora_preentry_remaining_ok(1161,clock=lambda:1000))
        self.assertTrue(meteora_preentry_remaining_ok(1162,clock=lambda:1000))

    def test_hourly_meteora_refuses_late_trigger_before_any_entry_work(self):
        calls=[]
        def original(*args,**kwargs):
            calls.append((args,kwargs))
            return ('original',)
        module=SimpleNamespace(
            _triggered_warmup=original,
            _lifecycle=lambda *a,**k:('life','adapter'),
            _cert_lifecycle_timing_installed=False,
        )
        install_meteora(module)
        with patch.dict(os.environ,{'MM_CERTIFICATION_PHASE':'hourly'}), \
             patch('certification.lifecycle_timing.time.monotonic',return_value=1000):
            result=module._triggered_warmup(
                'adapter',{'address':'pool'},{}, {}, 'pacer',[],1161,None)
        self.assertEqual(calls,[])
        self.assertEqual(result[0]['reason'],'campaign_window_insufficient_preentry_time')
        self.assertTrue(result[0]['admission_capacity'])
        self.assertFalse(result[0]['economic_rejection'])

    def test_non_hourly_meteora_retains_original_entry_behavior(self):
        calls=[]
        def original(*args,**kwargs):
            calls.append(1);return ('original',)
        module=SimpleNamespace(
            _triggered_warmup=original,
            _lifecycle=lambda *a,**k:('life','adapter'),
            _cert_lifecycle_timing_installed=False,
        )
        install_meteora(module)
        with patch.dict(os.environ,{'MM_CERTIFICATION_PHASE':'smoke'}):
            self.assertEqual(module._triggered_warmup(
                'adapter',{}, {}, {}, 'pacer',[],1,None),('original',))
        self.assertEqual(calls,[1])

    def test_ramses_frozen_operational_clocks_are_not_relaxed(self):
        self.assertEqual(RAMSES_RECENTER_TARGET_SECONDS,180)
        self.assertEqual(RAMSES_RECENTER_DEADLINE_SECONDS,210)
        self.assertEqual(RAMSES_MAX_HOLD_SECONDS,604800)


if __name__=='__main__':
    unittest.main()
