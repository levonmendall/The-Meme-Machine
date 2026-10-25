"""UI-only verification for the Pons-first dashboard Overview.

Uses no provider, trading executor, wallet, or financial-state mutation.
"""
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "static" / "app.js"


class PonsFocusedOverviewTests(unittest.TestCase):
    def test_overview_hides_pump_and_legacy_reporting_without_deleting_source(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("const LANES = ['pons'];", source)
        self.assertIn("function ponsFocusedOverview(feed)", source)
        overview = source.split("async function overview(p,feed) {", 1)[1].split(
            "async function lanePage(", 1
        )[0]
        self.assertIn("ponsFocusedOverview(feed)", overview)
        for clutter in ("hero(", "laneCards(", "chartPanel(", "operationsPanel(",
                        "ponsResearchPanel(", "Pump"):
            self.assertNotIn(clutter, overview)
        self.assertIn("Historical Pons market research", source)
        self.assertIn("Original stopped PAPER", source)

    def test_actual_javascript_parses_and_live_vs_missing_render(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for frontend execution coverage")
        subprocess.run([node, "--check", str(APP)], check=True, capture_output=True, text=True)
        script = textwrap.dedent(r"""
            const fs=require('fs'),vm=require('vm'),assert=require('assert');
            const source=fs.readFileSync(process.argv[1],'utf8');
            const stoppedAt=source.indexOf("document.querySelector('#close-detail')");
            assert(stoppedAt>0);
            const suffix=`
              const now=new Date().toISOString(), sha='a'.repeat(40), inception='b'.repeat(64);
              const measure=(value,unit)=>({value:String(value),unit,state:'CURRENT',quality:'MEASURED',as_of:now});
              const feed={
                schema:'pons-simulator-view-v1',state:'CURRENT',
                identity:{source_commit:sha,epoch_id:'test-epoch',inception_sha256:inception},
                observer:{source_commit:sha,status:'RUNNING',heartbeat_at:now,market_as_of:now,restart_count:3},
                metrics:{
                  financial:{equity:measure('1000.00','USD'),cash:measure('1000.00','USD'),
                    net_return_pct:measure('0','PERCENT'),realized_pnl:measure('0','USD'),
                    unrealized_pnl:measure('0','USD')},
                  activity:{entries:measure('0','COUNT'),exits:measure('0','COUNT'),
                    open_positions:measure('0','COUNT'),events_processed:measure('125','COUNT')}
                },
                paper:{schema:'pons-current-paper-report-v1',source_commit:sha,epoch_id:'test-epoch',
                  inception_sha256:inception,
                  policy_sha256:'909738760e6f722b8668a99493f698c3a415867f77f08199a61b0fb047381be7',
                  authority_sha256:'e'.repeat(64),permission_enabled:true,new_risk_enabled:false,
                  state:'READY',heartbeat_at:now}
              };
              const html=ponsFocusedOverview(feed);
              assert(html.includes('$1,000.00'));
              assert(html.includes('Standing permission ENABLED'));
              assert(html.includes('ARMED'));
              assert(html.includes('FRESH · READ ONLY'));
              assert(!html.includes('Pump'));
              const missing=ponsFocusedOverview(null);
              assert(missing.includes('UNAVAILABLE'));
              assert(!missing.includes('CURRENT MARKET FEED'));
              assert(!missing.includes('$1,000.00'));
              process.stdout.write('PONS_OVERVIEW_RENDER_PASS');
            `;
            const sandbox={document:{querySelector:()=>({})},Date,AbortController,
              URLSearchParams,setTimeout,clearTimeout,fetch(){throw Error('No fetch permitted')}};
            vm.runInNewContext(source.slice(0,stoppedAt)+suffix,sandbox,{timeout:2000});
        """)
        done = subprocess.run([node, "-e", script, str(APP)], check=True,
                              capture_output=True, text=True, timeout=10)
        self.assertIn("PONS_OVERVIEW_RENDER_PASS", done.stdout)


if __name__ == "__main__":
    unittest.main()
