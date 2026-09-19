import copy
import json
from pathlib import Path
import unittest

from robinhood_research import BoundaryError
from robinhood_research.abi import decode_event
from robinhood_research.identity import load
from robinhood_research.pons import (
    factory_record,
    prove_v1_v3_lineage,
    prove_v4_lineage,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pons_lineage_35378762520.json"


def normalized(role, raw):
    return dict(
        decoded=decode_event(load(role)["abi"], raw),
        protocol_address=raw["address"].lower(),
        transaction_hash=raw["transactionHash"],
    )


class CapturedPonsLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = json.loads(FIXTURE.read_text())

    def test_capture_was_bounded_and_provider_clean(self):
        self.assertEqual(self.capture["source_run"], 35378762520)
        self.assertEqual(self.capture["source_artifact"], 10561890805)
        self.assertEqual(
            self.capture["source_artifact_sha256"],
            "97582b1ce347cd3e13650cc8c4c74571ad4d6406bdbc5cf9acb2ecbc41041353",
        )
        self.assertEqual(self.capture["provider"]["failures"], {})
        self.assertEqual(self.capture["provider"]["requests"], 44)
        self.assertEqual(self.capture["provider"]["retries"], 0)

    def test_captured_v2_graduation_reconstructs_exact_v4_lineage(self):
        row = self.capture["v2"]
        record = factory_record(row["factory_record_raw"], "pons_v2_factory")
        graduation = normalized("pons_v2_factory", row["graduation"])
        registration = normalized("pons_v2_hook", row["registration"])
        initialization = normalized("uniswap_v4_manager", row["initialization"])
        proof = prove_v4_lineage(
            record=record,
            registration=registration,
            initialization=initialization,
            graduation=graduation,
            hook=load("pons_v2_hook")["address"].lower(),
            manager=load("uniswap_v4_manager")["address"].lower(),
        )
        self.assertEqual(proof, row["expected"])
        self.assertEqual(
            graduation["transaction_hash"],
            "0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9",
        )

    def test_captured_v2_unrelated_v4_initialization_is_rejected(self):
        row = self.capture["v2"]
        record = factory_record(row["factory_record_raw"], "pons_v2_factory")
        graduation = normalized("pons_v2_factory", row["graduation"])
        registration = normalized("pons_v2_hook", row["registration"])
        initialization = normalized("uniswap_v4_manager", row["initialization"])
        initialization = copy.deepcopy(initialization)
        initialization["decoded"]["args"]["hooks"] = "0x" + "11" * 20
        with self.assertRaisesRegex(BoundaryError, "lineage|unrelated"):
            prove_v4_lineage(
                record=record,
                registration=registration,
                initialization=initialization,
                graduation=graduation,
                hook=load("pons_v2_hook")["address"].lower(),
                manager=load("uniswap_v4_manager")["address"].lower(),
            )

    def test_captured_v1_launch_reconstructs_exact_v3_provenance(self):
        row = self.capture["v1"]
        record = factory_record(row["factory_record_raw"], "pons_v1_factory")
        launch = normalized("pons_v1_factory", row["launch"])
        pool_created = normalized("uniswap_v3_factory", row["pool_created"])
        proof = prove_v1_v3_lineage(
            record=record,
            launch=launch,
            pool_created=pool_created,
            factory=load("pons_v1_factory")["address"].lower(),
            v3_factory=load("uniswap_v3_factory")["address"].lower(),
        )
        self.assertEqual(proof, row["expected"])
        self.assertEqual(row["creation_block"], 17661055)

    def test_captured_v1_pool_substitution_is_rejected(self):
        row = self.capture["v1"]
        record = factory_record(row["factory_record_raw"], "pons_v1_factory")
        launch = normalized("pons_v1_factory", row["launch"])
        pool_created = normalized("uniswap_v3_factory", row["pool_created"])
        pool_created = copy.deepcopy(pool_created)
        pool_created["decoded"]["args"]["pool"] = "0x" + "22" * 20
        with self.assertRaisesRegex(BoundaryError, "pool"):
            prove_v1_v3_lineage(
                record=record,
                launch=launch,
                pool_created=pool_created,
                factory=load("pons_v1_factory")["address"].lower(),
                v3_factory=load("uniswap_v3_factory")["address"].lower(),
            )


if __name__ == "__main__":
    unittest.main()
