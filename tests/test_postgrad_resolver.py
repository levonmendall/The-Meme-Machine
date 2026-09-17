import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.legacy_raydium import LegacyRaydiumProvenance
from meme_machine.postgrad import GraduationHandoff
from meme_machine.postgrad_resolver import (
    VerifiedPostGraduationResolver, load_legacy_raydium_registry,
)
from meme_machine.provider import Unavailable
from tests.test_postgrad import MINT, CREATOR


class Adapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0
    def pumpswap_snapshot(self, handoff, now, priority=True):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.result)


class VerifiedResolver(unittest.TestCase):
    def handoff(self):
        return GraduationHandoff(MINT, CREATOR, 'source', 1, 1, False)

    def provenance(self):
        return LegacyRaydiumProvenance(
            mint=MINT, pool='Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw',
            current_pair_identity_verified=True,
            direct_pump_withdraw_lineage_verified=False,
            source_label='test',
        )

    def test_canonical_pumpswap_wins_without_touching_legacy_fallback(self):
        adapter = Adapter(result={'surface':'pumpswap', 'source':{}})
        resolver = VerifiedPostGraduationResolver(adapter, {MINT:self.provenance()})
        with patch('meme_machine.postgrad_resolver.read_explicit_pool') as legacy:
            result = resolver.resolve(self.handoff(), 100)
        self.assertEqual(result['surface'], 'pumpswap')
        self.assertEqual(result['source']['resolution_path'], 'canonical_pumpswap')
        self.assertFalse(result['source']['allocation_eligible'])
        legacy.assert_not_called()

    def test_only_explicit_missing_pumpswap_permits_legacy_fallback(self):
        adapter = Adapter(error=Unavailable('pumpswap_pool_missing'))
        resolver = VerifiedPostGraduationResolver(adapter, {MINT:self.provenance()})
        legacy_result = {'surface':'raydium-v4', 'source':{}}
        with patch('meme_machine.postgrad_resolver.read_explicit_pool', return_value=legacy_result) as legacy:
            result = resolver.resolve(self.handoff(), 100)
        self.assertEqual(result['surface'], 'raydium-v4')
        self.assertEqual(result['source']['resolution_path'], 'explicit_legacy_raydium')
        self.assertFalse(result['source']['allocation_eligible'])
        legacy.assert_called_once()

    def test_provider_or_identity_failure_never_silently_falls_through(self):
        adapter = Adapter(error=Unavailable('provider_request_failed'))
        resolver = VerifiedPostGraduationResolver(adapter, {MINT:self.provenance()})
        with patch('meme_machine.postgrad_resolver.read_explicit_pool') as legacy:
            with self.assertRaisesRegex(Unavailable, 'provider_request_failed'):
                resolver.resolve(self.handoff(), 100)
        legacy.assert_not_called()

    def test_missing_legacy_provenance_fails_closed(self):
        adapter = Adapter(error=Unavailable('pumpswap_pool_missing'))
        resolver = VerifiedPostGraduationResolver(adapter)
        with self.assertRaisesRegex(Unavailable, 'legacy_raydium_provenance_missing'):
            resolver.resolve(self.handoff(), 100)

    def test_registry_is_bounded_verified_and_never_allocation_authority(self):
        record = {
            'schema':'legacy-raydium-pool-provenance-v1',
            'authority':'read-only research only; never selects or authorizes a trade',
            'records':[{
                'mint':MINT,
                'pool':'Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw',
                'surface':'raydium-v4',
                'current_pair_identity_verified':True,
                'direct_pump_withdraw_lineage_verified':False,
                'allocation_eligible':False,
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'registry.json'
            path.write_text(json.dumps(record))
            loaded = load_legacy_raydium_registry(path)
            self.assertIn(MINT, loaded)
            self.assertFalse(loaded[MINT].allocation_eligible)
            record['records'][0]['allocation_eligible'] = True
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'registry_allocation'):
                load_legacy_raydium_registry(path)


if __name__ == '__main__':
    unittest.main()
