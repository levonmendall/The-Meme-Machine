import unittest

from meme_machine import pump
from meme_machine.concentration import ConcentrationReader
from meme_machine.provider import RPC
from tests.support import snapshot


class ConcentrationReaderTests(unittest.TestCase):
    def _largest(self, snap, amount=100_000_000_000_000, slot=None):
        return {
            'context': {'slot': snap['slot'] if slot is None else slot},
            'value': [
                {'address': pump.b58(bytes([31]) * 32), 'amount': str(amount),
                 'decimals': 6, 'uiAmount': None, 'uiAmountString': '0'},
            ],
        }

    def test_verified_secondary_serves_concentration_without_primary_expensive_call(self):
        snap=snapshot()
        primary_calls=[]
        secondary_calls=[]
        def primary_transport(request):
            primary_calls.append(request['method'])
            if request['method']=='getTokenLargestAccounts':
                raise AssertionError('secondary should satisfy concentration')
            return {'result':pump.MAINNET}
        def secondary_transport(request):
            secondary_calls.append(request['method'])
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            if request['method']=='getTokenLargestAccounts':
                return {'result':self._largest(snap)}
            raise AssertionError(request['method'])
        primary=RPC('https://primary.example',limit=40,transport=primary_transport)
        secondary=RPC('https://secondary.example',limit=40,transport=secondary_transport)
        reader=ConcentrationReader(primary,secondary_url='https://secondary.example',secondary_rpc=secondary)
        value,meta=reader.read(snap['mint'],snap)
        self.assertEqual(value,1000)
        self.assertEqual(meta['source'],'secondary')
        self.assertEqual(primary_calls,[])
        self.assertEqual(secondary_calls,['getGenesisHash','getTokenLargestAccounts'])
        self.assertTrue(reader.status()['secondary_verified'])

    def test_stale_secondary_falls_back_to_fresh_primary(self):
        snap=snapshot(slot=100)
        def secondary_transport(request):
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            if request['method']=='getTokenLargestAccounts':
                return {'result':self._largest(snap,slot=1)}
            raise AssertionError(request['method'])
        def primary_transport(request):
            if request['method']=='getTokenLargestAccounts':
                return {'result':self._largest(snap,slot=100)}
            raise AssertionError(request['method'])
        primary=RPC('https://primary.example',limit=40,transport=primary_transport)
        secondary=RPC('https://secondary.example',limit=40,transport=secondary_transport)
        reader=ConcentrationReader(primary,secondary_url='https://secondary.example',secondary_rpc=secondary)
        value,meta=reader.read(snap['mint'],snap)
        self.assertEqual(value,1000)
        self.assertEqual(meta['source'],'primary')
        self.assertEqual(reader.status()['retrieval_failures'],1)

    def test_wrong_network_secondary_is_never_trusted(self):
        snap=snapshot()
        secondary_methods=[]
        def secondary_transport(request):
            secondary_methods.append(request['method'])
            if request['method']=='getGenesisHash':
                return {'result':'wrong-network'}
            raise AssertionError('wrong-network secondary must not be queried further')
        def primary_transport(request):
            if request['method']=='getTokenLargestAccounts':
                return {'result':self._largest(snap)}
            raise AssertionError(request['method'])
        primary=RPC('https://primary.example',limit=40,transport=primary_transport)
        secondary=RPC('https://secondary.example',limit=40,transport=secondary_transport)
        reader=ConcentrationReader(primary,secondary_url='https://secondary.example',secondary_rpc=secondary)
        value,meta=reader.read(snap['mint'],snap)
        self.assertEqual(value,1000)
        self.assertEqual(meta['source'],'primary')
        self.assertEqual(secondary_methods,['getGenesisHash'])
        self.assertEqual(reader.status()['secondary_disabled_reason'],'wrong_network')

    def test_both_sources_unavailable_fail_closed(self):
        snap=snapshot()
        def secondary_transport(request):
            if request['method']=='getGenesisHash':
                return {'result':pump.MAINNET}
            raise TimeoutError('unavailable')
        def primary_transport(request):
            raise TimeoutError('unavailable')
        primary=RPC('https://primary.example',limit=40,transport=primary_transport)
        secondary=RPC('https://secondary.example',limit=40,transport=secondary_transport)
        reader=ConcentrationReader(primary,secondary_url='https://secondary.example',secondary_rpc=secondary)
        with self.assertRaisesRegex(RuntimeError,'concentration_unavailable'):
            reader.read(snap['mint'],snap)


if __name__=='__main__':
    unittest.main()
