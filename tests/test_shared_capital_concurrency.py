"""Thread/process TOCTOU, all regime combinations, sealed priority and replay."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import combinations
import multiprocessing
import tempfile
import unittest

from meme_machine.shared_capital import CapitalAuthority, CapitalError, REGIMES, RiskPolicy
from meme_machine.shared_capital.model import money
from tests.shared_capital_support import Harness


def unrestricted_test_policy():
    # Isolate the cash race with explicit 100% risk ceilings in this fixture.
    # This policy is never the feature's recommended or default configuration.
    return RiskPolicy(portfolio_bps=10000, asset_bps=10000,
        regime_base_bps={r: 10000 for r in REGIMES}, regime_max_bps={r: 10000 for r in REGIMES},
        family_max_bps={r: 10000 for r in ("pump", "pons", "meteora", "ramses")},
        group_bps={g: 10000 for g in ("crypto_beta", "solana", "robinhood", "directional", "lp")})


def cash_scarcity(h):
    requests, _ = h.allocate([("ramses", dict(requested="494"))])
    h.fill(requests[0])


def _deliver(path, request, barrier, output):
    authority = CapitalAuthority(path)
    try:
        observed = authority.snapshot()["capital"]["free_cash"]
        barrier.wait(timeout=20)
        result = authority.submit(request, at=0)
        output.put((observed, result, None))
    except BaseException as error:
        output.put((None, None, repr(error)))
    finally:
        authority.close()


class ConcurrentCapitalTests(unittest.TestCase):
    def harness(self, policy=RiskPolicy()):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        h = Harness(temp.name, policy); self.addCleanup(h.close)
        return h

    def test_every_pair_of_six_regimes_observes_same_cash_and_only_one_gets_it(self):
        for left, right in combinations(REGIMES, 2):
            with self.subTest(left=left, right=right):
                h = self.harness(unrestricted_test_policy())
                cash_scarcity(h)
                requests = [h.prepare(r, round_id="race", requested="6") for r in (left, right)]
                h.authority.open_round(operation_id="open-race", round_id="race", at=0, cutoff=0)
                readers = [CapitalAuthority(h.path) for _ in requests]
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        snapshots = list(pool.map(lambda a: a.snapshot()["capital"]["free_cash"], readers))
                        self.assertTrue(all(money(v) == 6 for v in snapshots))
                        submitted = list(pool.map(lambda pair: pair[0].submit(pair[1], at=0), zip(readers, requests)))
                    self.assertTrue(all(s["status"] == "SUBMITTED" for s in submitted))
                finally:
                    for a in readers: a.close()
                h.finish_round("race", requests)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(lambda _: h.authority.allocate(round_id="race", at=0), range(2)))
                self.assertEqual(outcomes[0], outcomes[1])
                decisions = outcomes[0]["decisions"]
                self.assertEqual(sum(d["status"] == "RESERVED" for d in decisions.values()), 1)
                self.assertEqual(money(h.check()["capital"]["free_cash"]), 0)

    def test_six_processes_cannot_spend_the_same_observed_cash(self):
        h = self.harness(unrestricted_test_policy())
        cash_scarcity(h)
        requests = [h.prepare(r, round_id="process-race", requested="6") for r in REGIMES]
        h.authority.open_round(operation_id="open-process", round_id="process-race", at=0, cutoff=0)
        context = multiprocessing.get_context("spawn")
        barrier, output = context.Barrier(6), context.Queue()
        processes = [context.Process(target=_deliver, args=(h.path, q, barrier, output)) for q in requests]
        for process in processes: process.start()
        reports = [output.get(timeout=40) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
        output.close(); output.join_thread()
        self.assertTrue(all(error is None and money(cash) == 6 for cash, _, error in reports))
        h.finish_round("process-race", requests)
        result = h.authority.allocate(round_id="process-race", at=0)
        self.assertEqual(sum(d["status"] == "RESERVED" for d in result["decisions"].values()), 1)
        h.restart(); h.authority.verify_replay()

    def test_every_nonempty_regime_subset_is_sealed_and_conserves_capital(self):
        for size in range(1, 7):
            for subset in combinations(REGIMES, size):
                with self.subTest(regimes=subset):
                    h = self.harness()
                    requests = [h.prepare(r, round_id="subset", requested="1") for r in subset]
                    h.authority.open_round(operation_id="open-subset", round_id="subset", at=0, cutoff=0)
                    readers = [CapitalAuthority(h.path) for _ in subset]
                    try:
                        with ThreadPoolExecutor(max_workers=size) as pool:
                            list(pool.map(lambda pair: pair[0].submit(pair[1], at=0), zip(readers, requests)))
                    finally:
                        for a in readers: a.close()
                    h.finish_round("subset", requests)
                    result = h.authority.allocate(round_id="subset", at=0)
                    self.assertEqual(sum(d["status"] == "RESERVED" for d in result["decisions"].values()), size)
                    self.assertEqual(money(h.check()["capital"]["active_reservations"]), size)

    def test_incomplete_manifest_never_awards_capital_and_late_delivery_rejected(self):
        h = self.harness()
        q = h.prepare("pump_current", round_id="sealed")
        h.authority.open_round(operation_id="open-sealed", round_id="sealed", at=0, cutoff=0)
        h.authority.submit(q, at=0)
        with self.assertRaisesRegex(CapitalError, "six_lane_watermarks"):
            h.authority.allocate(round_id="sealed", at=0)
        with self.assertRaisesRegex(CapitalError, "incomplete_or_conflicting_lane_manifest"):
            h.authority.seal(operation_id="bad-seal", round_id="sealed", regime_name="pump_current", request_ids=[], at=0)
        h.finish_round("sealed", [q])
        late = h.prepare("pump_current", round_id="sealed", request_id="late")
        with self.assertRaisesRegex(CapitalError, "late_or_unsealed"):
            h.authority.submit(late, at=0)
        self.assertEqual(money(h.check()["capital"]["active_reservations"]), 0)

    def test_reversed_arrival_order_has_identical_priority_and_capital_results(self):
        results = []
        for reverse in (False, True):
            h = self.harness(unrestricted_test_policy())
            cash_scarcity(h)
            requests = [h.prepare(r, round_id="replay", request_id="fixed-" + r, requested="6") for r in REGIMES]
            h.authority.open_round(operation_id="open-replay", round_id="replay", at=0, cutoff=0)
            for q in reversed(requests) if reverse else requests:
                h.authority.submit(q, at=0)
            h.finish_round("replay", requests)
            results.append(h.authority.allocate(round_id="replay", at=0))
            h.authority.verify_replay()
        self.assertEqual(results[0], results[1])

    def test_required_management_precedes_continuation_and_new_opportunity(self):
        h = self.harness(unrestricted_test_policy())
        requests, _ = h.allocate([("ramses", {}), ("meteora", {})])
        lives = {q.regime: h.fill(q)[0] for q in requests}
        h.allocate([("ramses", dict(requested="444"))])
        specs = [("ramses", dict(asset=requests[0].candidate_id, candidate="safety", requested="6", kind="safety", lifecycle_id=lives["ramses"])),
                 ("meteora", dict(asset=requests[1].candidate_id, candidate="continuation", requested="6", kind="continuation", lifecycle_id=lives["meteora"])),
                 ("pump_current", dict(requested="6"))]
        requests, result = h.allocate(specs)
        self.assertEqual(result["order"][0], requests[0].request_id)
        self.assertEqual(result["decisions"][requests[0].request_id]["status"], "RESERVED")
        self.assertEqual(sum(d["status"] == "RESERVED" for d in result["decisions"].values()), 1)
