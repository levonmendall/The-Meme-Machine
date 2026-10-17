"""Real fixed copied main with an explicitly missing Landlock boundary.

The private fixture installs actual seccomp to deny all external socket paths,
but can never satisfy public kernel validation. Providers remain offline.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational import isolated_native_image as image
from meme_machine.operational import isolated_native_kernel_validation as validation
from meme_machine.operational.isolated_native_landlock_launcher import NativeLandlockChild,_entry_command
from meme_machine.operational.isolated_native_layout import NativeChildLayout,PROFILE


def copied_seccomp_fixture(scope,approval,transport,facts):
    """No public selector: this test-only dependency can never attest Landlock."""
    staged=image.build(scope,approval,profile=PROFILE)
    root=Path(scope);work=root/'native-work';work.mkdir(mode=0o700)
    (work/'native').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
    layout=NativeChildLayout(PROFILE,str(staged['root']),str(work),os.getpid(),staged['manifest_sha256'])
    source=Path(__file__).resolve().parents[1]
    code=('import ctypes,os,sys;sys.path.insert(0,'+repr(str(source))+');'+
        'from meme_machine.operational.isolated_native_launcher import _prune_descriptors;'+
        '_prune_descriptors('+str(transport.fileno())+','+str(facts)+');'+
        'from meme_machine.operational.native_landlock_policy import NativePolicy;'+
        'k=NativePolicy();'+
        'k.call(157,ctypes.c_int(38),ctypes.c_ulong(1),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code="fixture_nnp");'+
        'k.call(157,ctypes.c_int(1),ctypes.c_ulong(9),ctypes.c_ulong(0),ctypes.c_ulong(0),ctypes.c_ulong(0),code="fixture_pdeath");'+
        'k.seccomp();os.execve('+repr(str(layout.executable))+','+
        repr([str(layout.executable),'-I','-B','-S','-c',_entry_command(layout)])+','+repr(layout.environment())+')')
    child=subprocess.Popen([sys.executable,'-I','-B','-S','-c',code],stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=layout.native_directory,
        env={},close_fds=True,pass_fds=(transport.fileno(),facts),start_new_session=True)
    return NativeLandlockChild(child,time.monotonic())


class NativeKernelValidationTests(unittest.TestCase):
    def test_policy_receipt_requires_one_exact_supported_install_observation(self):
        raw=b'NATIVE_POLICY_INSTALLED {"profile":"'+PROFILE.encode()+b'","landlock_abi":8,"installed":true}\n'
        self.assertEqual(validation._policy_record(raw)['landlock_abi'],8)
        for bad in (b'',raw+raw,raw.replace(b'8',b'5'),raw.replace(b'true',b'false'),
                raw.replace(b'8',b'8,"extra":true')):
            self.assertIsNone(validation._policy_record(bad))

    def test_unknown_partial_and_injected_kernel_observations_never_pass(self):
        for value in (None,{},dict(schema='synthetic-native-kernel-validation-v1',kernel_applied=False),
                dict(schema='synthetic-native-kernel-validation-v1',kernel_applied=True,landlock_abi=8)):
            self.assertFalse(validation.verified(value))

    def test_actual_fixed_copied_main_all_four_native_adapters_and_shutdown(self):
        import asyncio
        from tests.test_isolated_native_launcher import offline_software_approval
        from tests.test_provider_clock_domain import identity
        with Scratch() as scope,patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()):
            result=asyncio.run(validation._exercise(scope.path,offline_software_approval(),
                launcher=copied_seccomp_fixture))
            print(json.dumps(result,sort_keys=True))
            self.assertIs(result['kernel_applied'],False)
            self.assertFalse(validation.verified(result))
            self.assertEqual(result['status'],'BLOCKED')
            self.assertTrue(result['owned_process_reaped'] and result['parent_cleanup_joined'],result)
            self.assertEqual(result['child']['status'],'COMPLETED',result)
            self.assertTrue(result['child']['observation']['all_workers_joined'],result)
            self.assertTrue(all(result['native_outputs']['regimes'].values()),result)
            self.assertGreater(result['native_outputs']['canonical_full_ack'],0,result)
            self.assertGreater(result['native_outputs']['candidate_references'],0,result)
            self.assertTrue(result['native_outputs']['financial_tables_absent'],result)
            self.assertEqual(result['fixture_counters']['external_provider_calls'],0)
            self.assertFalse(result['financial_authority'])
            scope.check();scope.success=True


if __name__=='__main__':unittest.main()
