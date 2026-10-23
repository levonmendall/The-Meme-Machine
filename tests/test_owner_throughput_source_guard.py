"""Unfrozen source-proof scaffold; root generates it after combined runtime freeze.

This placeholder deliberately grants no PASS and must not be used for promotion.
The reviewed builder/template replace it with exact committed identities.
"""
import unittest


class OwnerThroughputSourceProofNotFrozen(unittest.TestCase):
    def test_combined_runtime_cut_requires_root_freeze_and_generation(self):
        self.fail('owner-throughput proof is not frozen; root must generate the exact combined runtime proof')
