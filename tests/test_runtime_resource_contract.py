import importlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from operational import dependencies
from operational.tests import network_guard

class RuntimeResourceContractTests(unittest.TestCase):
    def test_deleting_each_required_resource_fails_inventory(self):
        # A copied contract with a missing target cannot shrink its own inventory.
        contract=json.loads((dependencies.ROOT/'operational/runtime-resource-contract.json').read_text())
        self.assertIn('meme_machine/runtime/alchemy-cu-schedule.json',contract['required_packaged_resources'])
        original=Path.is_file
        for relative in contract['required_packaged_resources']:
            missing=dependencies.ROOT/relative
            with self.subTest(resource=relative),patch.object(dependencies,'closure',return_value=([],[])),patch.object(Path,'is_file',lambda p:False if p==missing else original(p)):
                with self.assertRaisesRegex(AssertionError,'resource missing'):dependencies.inventory()

    def test_each_removed_runtime_module_fails_the_fixed_contract(self):
        mapping=dependencies.modules()
        contract=json.loads((dependencies.ROOT/'operational/runtime-resource-contract.json').read_text())
        for name in contract['required_runtime_modules']:
            missing=dict(mapping);missing.pop(name)
            with self.subTest(module=name),patch.object(dependencies,'modules',return_value=missing):
                with self.assertRaisesRegex(AssertionError,'runtime modules missing'):dependencies.inventory()

    def test_verified_role_resources_exercise_real_consumers(self):
        for lane in ('pons','ramses'):
            module=importlib.import_module('meme_machine.lanes.'+lane+'.identity')
            for path in sorted(module.ROOT.glob('*.json')):
                with self.subTest(lane=lane,role=path.stem):
                    pin=module.load(path.stem)
                    self.assertEqual(module.verify_compilation(pin),pin)
        from meme_machine.lanes.pons.pons import curve_abi
        self.assertTrue(curve_abi())
        from meme_machine.lanes.meteora.runner import load_policy
        self.assertTrue(load_policy())
        from meme_machine.runtime.cu import estimate
        self.assertIsNotNone(estimate({'eth_call':1})['estimated_cu'])

    def test_dynamic_process_entrypoints_and_provider_modules_exist(self):
        from importlib.util import find_spec
        contract=json.loads((dependencies.ROOT/'operational/runtime-resource-contract.json').read_text())
        for name in contract['dynamic_modules']['entrypoints']+contract['dynamic_modules']['request_scheduler_provider_classes']:
            self.assertIsNotNone(find_spec(name),name)
        from meme_machine.solana_evidence_service import source_decoder_probe
        self.assertIsNotNone(source_decoder_probe())
        service=(dependencies.ROOT/'deployment/meme-machine-paper.service').read_text()
        self.assertIn('-m meme_machine.operational',service)

    def test_governor_timeout_selects_each_native_solana_provider_exception(self):
        import os
        from unittest.mock import MagicMock
        names=['meme_machine.provider','meme_machine.lanes.pump.provider','meme_machine.lanes.meteora.provider']
        contract=json.loads((dependencies.ROOT/'operational/runtime-resource-contract.json').read_text())
        self.assertEqual(set(contract['dynamic_modules']['request_scheduler_provider_classes']),set(names))
        governor=MagicMock()
        governor.acquire.side_effect=TimeoutError('offline_admission_timeout')
        with patch.dict(os.environ,{'MM_PROVIDER_GOVERNOR_DB':'offline-mocked-governor'},clear=True),patch('meme_machine.runtime.governor.Governor',return_value=governor):
            for name in names:
                topology=importlib.import_module(name.rsplit('.',1)[0]+'.solana_read_rpc')
                native=importlib.import_module(name).Unavailable
                for factory in (topology.new_rpc,topology.new_pool_scan_rpc):
                    with self.subTest(provider=name,factory=factory.__name__):
                        rpc=factory(limit=40,environ={topology.ALCHEMY_ENV_NAME:'https://solana-mainnet.g.alchemy.com/v2/offline-test'})
                        with self.assertRaises(native) as caught:
                            rpc._http({'id':1,'method':'getGenesisHash','params':[]})
                        self.assertIs(type(caught.exception),native)
                        self.assertEqual(caught.exception.args,('offline_admission_timeout',))
                        self.assertEqual(rpc.http_requests,0)
