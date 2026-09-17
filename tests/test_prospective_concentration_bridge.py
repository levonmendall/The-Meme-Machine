import base64
import unittest

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader, ProgramScanRPC
from meme_machine.provider import PumpAdapter, RPC
from tests.support import snapshot


class ProspectiveConcentrationBridge(unittest.TestCase):
    def test_pump_adapter_uses_shared_compact_reader_not_direct_largest_call(self):
        snap = snapshot(slot=100)
        primary_methods = []
        program_methods = []
        amount = 100_000_000_000_000

        def primary_transport(request):
            primary_methods.append(request['method'])
            if request['method'] == 'getGenesisHash':
                return {'result': pump.MAINNET}
            if request['method'] == 'getTokenLargestAccounts':
                raise AssertionError('prospective adapter must use shared compact reader first')
            raise AssertionError(request['method'])

        def program_transport(request):
            program_methods.append(request['method'])
            if request['method'] == 'getGenesisHash':
                return {'result': pump.MAINNET}
            if request['method'] == 'getProgramAccounts':
                return {'result': {
                    'context': {'slot': 100},
                    'value': [{
                        'pubkey': pump.b58(bytes([31]) * 32),
                        'account': {
                            'data': [
                                base64.b64encode(amount.to_bytes(8, 'little')).decode(),
                                'base64',
                            ]
                        },
                    }],
                }}
            raise AssertionError(request['method'])

        primary = RPC('https://primary.example', limit=120, transport=primary_transport)
        adapter = PumpAdapter(primary)
        program = ProgramScanRPC('https://primary.example', limit=40, transport=program_transport)
        adapter._concentration_reader = ConcentrationReader(primary, program_rpc=program)

        value = adapter.concentration(snap['mint'], snap)

        self.assertEqual(value, 1000)
        self.assertEqual(primary_methods, ['getGenesisHash'])
        self.assertEqual(program_methods, ['getGenesisHash', 'getProgramAccounts'])
        status = adapter.concentration_status()
        self.assertTrue(status['initialized'])
        self.assertEqual(status['source_counts']['program_scan'], 1)
        self.assertEqual(status['source_counts']['primary_largest'], 0)

    def test_pump_adapter_concentration_keeps_fail_closed_fallback(self):
        snap = snapshot(slot=100)

        def primary_transport(request):
            if request['method'] == 'getGenesisHash':
                return {'result': pump.MAINNET}
            if request['method'] == 'getTokenLargestAccounts':
                return {'result': {
                    'context': {'slot': 100},
                    'value': [{
                        'address': pump.b58(bytes([31]) * 32),
                        'amount': '100000000000000',
                        'decimals': 6,
                        'uiAmount': None,
                        'uiAmountString': '0',
                    }],
                }}
            raise AssertionError(request['method'])

        def unavailable_program(request):
            if request['method'] == 'getGenesisHash':
                return {'result': pump.MAINNET}
            raise TimeoutError('program scan unavailable')

        primary = RPC('https://primary.example', limit=120, transport=primary_transport)
        adapter = PumpAdapter(primary)
        program = ProgramScanRPC('https://primary.example', limit=40, transport=unavailable_program)
        adapter._concentration_reader = ConcentrationReader(primary, program_rpc=program)

        self.assertEqual(adapter.concentration(snap['mint'], snap), 1000)
        status = adapter.concentration_status()
        self.assertGreaterEqual(status['retrieval_failures'], 1)
        self.assertEqual(status['source_counts']['primary_largest'], 1)


if __name__ == '__main__':
    unittest.main()
