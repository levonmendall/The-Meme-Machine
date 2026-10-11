"""Conditional package economics preserve retained charges and billing uncertainty."""
from decimal import Decimal
import unittest

from engineering.proven_efficiency.provider_packages import pons_rpc_hybrid


class ProviderPackageSensitivityTests(unittest.TestCase):
    def test_included_ru_threshold_counts_full_plan_and_archive_overage(self):
        full=pons_rpc_hybrid(monthly_rpc_elements=20_000_000,
            alchemy_cu_per_element=20,archive_fraction=0)
        archive=pons_rpc_hybrid(monthly_rpc_elements=20_000_000,
            alchemy_cu_per_element=20,archive_fraction=1)
        self.assertEqual(Decimal(full['chainstack_growth_total_usd']),Decimal(49))
        self.assertEqual(Decimal(archive['chainstack_growth_total_usd']),Decimal(349))
        self.assertGreater(Decimal(full['conditional_net_saving_usd']),0)
        self.assertLess(Decimal(archive['conditional_net_saving_usd']),0)

    def test_unused_alchemy_allowance_prevents_invented_replaced_spending(self):
        value=pons_rpc_hybrid(monthly_rpc_elements=1_000_000,
            alchemy_cu_per_element=20,archive_fraction=0,
            existing_alchemy_unused_cu=20_000_000,existing_alchemy_plan_usd=100,
            unchanged_solana_and_stream_usd=200)
        self.assertEqual(Decimal(value['original_total_usd']),Decimal(300))
        self.assertEqual(Decimal(value['hybrid_total_usd']),Decimal(349))
        self.assertEqual(Decimal(value['conditional_net_saving_usd']),Decimal(-49))

    def test_actual_fallback_storage_and_operations_are_added_without_a_multiplier(self):
        value=pons_rpc_hybrid(monthly_rpc_elements=5_000_000,
            alchemy_cu_per_element=20,archive_fraction=0,fallback_fraction='.1',
            existing_alchemy_plan_usd=100,unchanged_solana_and_stream_usd=200,
            added_storage_usd=2,added_operations_usd=3)
        self.assertEqual(Decimal(value['original_total_usd']),Decimal('352.5'))
        self.assertEqual(Decimal(value['hybrid_total_usd']),Decimal('359.25'))
        self.assertEqual(Decimal(value['conditional_net_saving_usd']),Decimal('-6.75'))

    def test_invalid_or_unknown_economic_inputs_are_not_cost_forecasts(self):
        for args in ({'monthly_rpc_elements':-1},{'archive_fraction':2},
                {'existing_alchemy_plan_usd':-1},{'added_operations_usd':'NaN'}):
            values=dict(monthly_rpc_elements=1,alchemy_cu_per_element=20,archive_fraction=0)
            with self.assertRaises(ValueError):pons_rpc_hybrid(**dict(values,**args))
