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
