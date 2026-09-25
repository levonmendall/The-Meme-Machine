from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH_REL = "certification/patches/counterfactual-replay-pump-v1.patch"
PATCH_PATH = ROOT / PATCH_REL


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def git_diff(root: Path) -> bytes:
    return subprocess.check_output([
        "git", "diff", "--binary", "--full-index", "--no-ext-diff",
        "--no-textconv", "--no-renames"
    ], cwd=root)


def git_head_diff(root: Path) -> bytes:
    return subprocess.check_output([
        "git", "diff", "--binary", "--full-index", "--no-ext-diff",
        "--no-textconv", "--no-renames", "HEAD"
    ], cwd=root)


def run(cmd, *, cwd: Path):
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    sys.path.insert(0, str(ROOT))
    from certification.run import prepare

    baseline_root = Path(tempfile.mkdtemp(prefix="mm-counterfactual-baseline-"))
    baseline = baseline_root / "lanes"
    fresh_root = None
    fresh = None
    try:
        prepare(baseline)
        pump = baseline / "pump"

        strategy_path = pump / "meme_machine/pump_acceleration_strategy.py"
        strategy = strategy_path.read_text()
        strategy = replace_once(
            strategy,
            'version: str = STRATEGY_ID + "-profitability-v1-profit-protection-v2"',
            'version: str = STRATEGY_ID + "-profitability-v1-profit-protection-v2-counterfactual-replay-v1"',
            "pump policy version",
        )
        strategy = replace_once(
            strategy,
            '    min_postgrad_price_vs_graduation_bps: int = 1\n',
            '    min_postgrad_price_vs_graduation_bps: int = 1\n'
            '    # Counterfactual replay across runs 36043064083 and 36077647211 found\n'
            '    # price retention on 100% of both resolved winners and losers. Keep it\n'
            '    # as point-in-time ranking/confirmation evidence, not a binary veto.\n'
            '    postgrad_price_retention_hard_gate: bool = False\n',
            "pump retention policy field",
        )
        strategy = replace_once(
            strategy,
            '        if int(_value_or(signal.price_vs_graduation_bps,0)) < policy.min_postgrad_price_vs_graduation_bps:\n'
            '            reasons.append("price_retention")\n',
            '        price_retained=(\n'
            '            int(_value_or(signal.price_vs_graduation_bps,0))\n'
            '            >= policy.min_postgrad_price_vs_graduation_bps\n'
            '        )\n'
            '        if price_retained:\n'
            '            confirmations.append("price_retention")\n'
            '        elif policy.postgrad_price_retention_hard_gate:\n'
            '            reasons.append("price_retention")\n',
            "pump price retention gate",
        )
        strategy_path.write_text(strategy)

        new_policy_hash = subprocess.check_output([
            sys.executable, "-c",
            "from meme_machine.pump_acceleration_strategy import policy_hash; print(policy_hash())",
        ], cwd=pump, text=True).strip()
        if len(new_policy_hash) != 64:
            raise RuntimeError("invalid derived Pump policy hash")

        identity_path = pump / "tests/test_pump_acceleration_policy_identity.py"
        identity = identity_path.read_text()
        import re
        identity, n = re.subn(r'FROZEN="[0-9a-f]{64}"', f'FROZEN="{new_policy_hash}"', identity, count=1)
        if n != 1:
            raise RuntimeError("Pump policy identity test anchor")
        identity_path.write_text(identity)

        test_path = pump / "tests/test_pump_acceleration_strategy.py"
        tests = test_path.read_text()
        anchor = '    def test_second_leg_requires_pullback_consolidation_and_breakout(self):\n'
        new_test = '''    def test_postgrad_price_retention_is_confirmation_not_binary_veto(self):
        strong=SignalVector(
            mint="M-retention",observed_at=1000,surface="pumpswap",phase=MODE_POSTGRAD,
            graduated=True,seconds_since_graduation=25,independent_buyer_clusters=10,
            buyer_growth=3,net_buy_share_bps=8500,concentration_bps=1600,
            price_vs_graduation_bps=-200,volume_acceleration_bps=3000,
            early_holder_sell_share_bps=1200,recovery_bps=1000,
            skilled_wallet_clusters=2,quote_relative_return_bps=500,
        )
        result=qualify(strong)
        self.assertTrue(result.qualified,result.reasons)
        self.assertNotIn("price_retention",result.reasons)
        self.assertNotIn("price_retention",result.confirmations)
        retained=qualify(SignalVector(**{**strong.__dict__,"price_vs_graduation_bps":200}))
        self.assertTrue(retained.qualified,retained.reasons)
        self.assertIn("price_retention",retained.confirmations)

'''
        tests = replace_once(tests, anchor, new_test + anchor, "Pump counterfactual test insertion")
        test_path.write_text(tests)

        run([
            sys.executable, "-m", "unittest",
            "tests.test_pump_acceleration_strategy",
            "tests.test_pump_acceleration_policy_identity", "-v",
        ], cwd=pump)

        patch_bytes = git_diff(pump)
        if not patch_bytes or b"pump_acceleration_strategy.py" not in patch_bytes:
            raise RuntimeError("counterfactual Pump patch missing strategy mutation")
        PATCH_PATH.write_bytes(patch_bytes)

        sources_path = ROOT / "certification/sources.json"
        spec = json.loads(sources_path.read_text())
        row = spec["lanes"]["pump"]
        if PATCH_REL in row["overlay_patches"]:
            raise RuntimeError("counterfactual Pump patch already declared")
        row["overlay_patches"].append(PATCH_REL)
        row["strategy_version"] = (
            "pump-acceleration-independent-v1/"
            "profitability-v1-profit-protection-v2-counterfactual-replay-v1"
        )
        row["policy_hash"] = new_policy_hash
        row["execution_certification"]["revision"] = (
            "profitability-v1-profit-protection-v2-counterfactual-replay-v1"
        )
        row["execution_certification"]["counterfactual_replay_v1"] = {
            "basis_runs": [36043064083, 36077647211],
            "resolved_first_rejections": 56,
            "winner_rejections": 26,
            "loser_rejections": 30,
            "price_retention_winner_presence_bps": 10000,
            "price_retention_loser_presence_bps": 10000,
            "change": "postgraduation_price_retention_from_binary_veto_to_ranking_confirmation",
            "early_holder_distribution_gate_unchanged": True,
            "net_demand_gate_unchanged": True,
            "buyer_growth_gate_unchanged": True,
            "execution_downside_gate_unchanged": True,
            "fill_time_persistence_unchanged": True,
            "paper_only_unchanged": True,
        }
        admission = row["prospect_admission"]
        admission["investment_evaluation_scope"] = (
            admission["investment_evaluation_scope"]
            + "; post-graduation price retention remains ranking/confirmation evidence "
              "but no longer has independent binary veto authority"
        )
        admission["counterfactual_replay_revision"] = "pump-price-retention-soft-v1"
        spec["verified_at"] = "2026-09-24-counterfactual-replay-strategy-v1"
        sources_path.write_text(json.dumps(spec, indent=2) + "\n")

        fresh = Path(tempfile.mkdtemp(prefix="mm-counterfactual-fresh-"))
        prepare(fresh)
        fresh_pump = fresh / "pump"
        observed = hashlib.sha256(git_head_diff(fresh_pump)).hexdigest()
        spec = json.loads(sources_path.read_text())
        spec["lanes"]["pump"]["source_diff_sha256"] = observed
        sources_path.write_text(json.dumps(spec, indent=2) + "\n")

        run([
            sys.executable, "-m", "unittest",
            "tests.test_pump_acceleration_strategy",
            "tests.test_pump_acceleration_policy_identity", "-v",
        ], cwd=fresh_pump)

        docs = ROOT / "docs/COUNTERFACTUAL_STRATEGY_REVISION_V1_20260924.md"
        docs.write_text(
            "# Counterfactual strategy revision v1 — 2026-09-24\n\n"
            "Evidence basis: hourly runs 36043064083 and 36077647211.\n\n"
            "## Activated change\n\n"
            "Pump post-graduation price retention is no longer an independent binary entry veto. "
            "It remains point-in-time ranking/confirmation evidence. The counterfactual replay found "
            "the old veto present in 100% of resolved winner rejects and 100% of resolved loser rejects, "
            "so it supplied no discrimination in this sample.\n\n"
            "All stronger Pump risk and demand protections remain unchanged, including early-holder "
            "distribution, net demand, buyer growth, concentration, executable downside, and fill-time persistence.\n\n"
            "## Pons decision\n\n"
            "No Pons economic threshold is changed in this revision. The replay showed that age and ETA "
            "behave primarily as timing eligibility conditions, but the sample does not identify a defensible "
            "replacement window. The existing age/ETA boundaries therefore remain unchanged rather than "
            "introducing an outcome-fitted threshold.\n\n"
            f"Derived Pump policy hash: `{new_policy_hash}`.\n"
            f"Derived Pump prepared-tree diff SHA-256: `{observed}`.\n"
        )

        print(json.dumps({
            "pump_policy_hash": new_policy_hash,
            "pump_source_diff_sha256": observed,
            "patch": PATCH_REL,
            "pons_economics_changed": False,
        }, sort_keys=True))
    finally:
        shutil.rmtree(baseline, ignore_errors=True)
        if fresh is not None:
            shutil.rmtree(fresh, ignore_errors=True)


if __name__ == "__main__":
    main()
