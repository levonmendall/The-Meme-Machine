"""Supplemental offline allocation race using independent SQLite authorities."""
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
import tempfile

from meme_machine.shared_capital import CapitalAuthority, REGIMES
from meme_machine.shared_capital.model import money
from tests.shared_capital_support import Harness
from tests.test_shared_capital_concurrency import cash_scarcity, unrestricted_test_policy


def main():
    count = 0
    for pair in combinations(REGIMES, 2):
        with tempfile.TemporaryDirectory() as root:
            h = Harness(root, unrestricted_test_policy())
            peers = []
            try:
                cash_scarcity(h)
                requests = [h.prepare(r, round_id="independent-race", requested="6") for r in pair]
                h.authority.open_round(operation_id="open-race", round_id="independent-race", at=0, cutoff=0)
                for q in requests:
                    h.authority.submit(q, at=0)
                h.finish_round("independent-race", requests)
                peers = [CapitalAuthority(h.path), CapitalAuthority(h.path)]
                assert all(money(p.snapshot()["capital"]["free_cash"]) == 6 for p in peers)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(lambda p: p.allocate(round_id="independent-race", at=0), peers))
                assert outcomes[0] == outcomes[1]
                assert sum(v["status"] == "RESERVED" for v in outcomes[0]["decisions"].values()) == 1
                assert money(h.check()["capital"]["free_cash"]) == 0
                h.restart()
                count += 1
            finally:
                for peer in peers:
                    peer.close()
                h.close()
    print(f"PASS: {count} lane pairs; two independent SQLite connections, identical allocation receipts, one grant, restart conservation.")


if __name__ == "__main__":
    main()
