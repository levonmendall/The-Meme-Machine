"""Validate the canonical original-portfolio Overview and line chart.

All cases run offline with supplied fixtures. Nothing touches live financial
sources, simulator ingestion, market providers or a trading service.
"""
import json
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "static" / "app.js"


class OriginalPortfolioPnlTests(unittest.TestCase):
    def test_original_only_source_boundaries(self):
        code = SOURCE.read_text()
        self.assertIn("const LANES = ['pons'];", code)  # Pump presentation remains hidden.
        self.assertIn("function canonicalPnlGraph(p,h)", code)
        overview = code.split("async function overview(p) {", 1)[1].split(
            "async function lanePage(", 1
        )[0]
        self.assertIn("api('equity',{period:state.period,series:'portfolio',limit:240})", overview)
        self.assertIn("canonicalPnlGraph(p,chart)", overview)
        self.assertIn("hero(p,chart)", overview)
        self.assertNotIn("ponsFocusedOverview", overview)
        self.assertNotIn("ponsObserverPanel", overview)
        self.assertIn("livePonsPanel(live,p)", overview)
        self.assertIn("livePonsFeed()", overview)
        self.assertLess(overview.index("livePonsPanel(live,p)"), overview.index("canonicalPnlGraph(p,chart)"))
        self.assertNotIn("/api/pons-simulator/state", code)
        self.assertNotIn("ponsAccountPanel", code)
        self.assertNotIn("ponsAccountMetric", code)
        renderer = code.split("async function render() {", 1)[1]
        self.assertNotIn("ponsObserverFeed()", renderer)
        self.assertIn("if(route==='overview') html=await overview(p);", renderer)
        self.assertIn("else if(route==='system') html=await systemPage(p);", renderer)

    def test_node_renders_original_graph_and_rejects_other_financial_accounts(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed to execute the actual frontend")
        subprocess.run([node, "--check", str(SOURCE)], check=True, capture_output=True, text=True)
        script = textwrap.dedent(r"""
        const assert=require('assert');
        const fs=require('fs'),vm=require('vm');
        const source=fs.readFileSync(process.argv[1],'utf8');
        const end=source.indexOf("document.querySelector('#close-detail')");
        assert(end>0);
        const execute=`
          const financialIdentity={epoch_id:'paper-shared-1000-original',inception_sha256:'a'.repeat(64)};
          const account={mode:'canonical',epoch:{epoch_id:'paper-shared-1000-original'},financial_identity:financialIdentity,
            paper_state:'STOPPED',starting_capital:{value:'1000.00'}};
          const at1='2026-10-25T10:00:00Z',at2='2026-10-25T10:05:00Z',
            at3='2026-10-25T10:10:00Z';
          const data={mode:'canonical',series:'portfolio',reference:'1000.00',financial_identity:financialIdentity,
            periods:['ALL','1H'],truncated:false,
            data:[{at:at1,value:'1000.00'},{at:at2,value:'1025.00'},
              {at:at3,value:'990.00'}]};
          const graph=canonicalPnlGraph(account,data);
          assert(graph.includes('Total portfolio P&amp;L'));
          assert(graph.includes('canonical-pnl-line'));
          assert(graph.includes('−$10.00'));
          assert(graph.includes('Original portfolio'));
          assert(!graph.includes('Pons experimental'));
          assert(!graph.includes('simulator equity'));
          const spoof=canonicalPnlGraph(account,{...data,mode:'experimental'});
          assert(spoof.includes('HISTORY UNAVAILABLE'));
          const wrongInception=canonicalPnlGraph(account,{...data,reference:'500.00'});
          assert(wrongInception.includes('HISTORY UNAVAILABLE'));
          const wrongEpoch=canonicalPnlGraph(account,{...data,financial_identity:{...financialIdentity,epoch_id:'different-1000-account'}});
          assert(wrongEpoch.includes('HISTORY UNAVAILABLE'));
          const wrongHash=canonicalPnlGraph(account,{...data,financial_identity:{...financialIdentity,inception_sha256:'b'.repeat(64)}});
          assert(wrongHash.includes('HISTORY UNAVAILABLE'));
          const missingIdentity=canonicalPnlGraph(account,{...data,financial_identity:null});
          assert(missingIdentity.includes('HISTORY UNAVAILABLE'));
          const noHistory=canonicalPnlGraph({...account,epoch:null},data);
          assert(noHistory.includes('HISTORY UNAVAILABLE'));
          const unknown=canonicalPnlGraph(account,{...data,data:[]});
          assert(unknown.includes('No original-portfolio equity observations'));
          const gap=canonicalPnlGraph(account,{...data,
            data:[{at:at1,value:'1000.00'},{at:at2,value:null},{at:at3,value:'1010.00'}]});
          assert(!gap.includes('class="canonical-pnl-line"'));
          const emptyStatus={textContent:'',className:''},update={textContent:''};
          document.querySelector=selector=>selector==='#live-indicator'?emptyStatus:
            selector==='#last-update'?update:null;
          syncTopbar({...account,state:'CURRENT',as_of:at3});
          assert(emptyStatus.textContent.includes('STOPPED'));
          assert(!emptyStatus.className.includes('is-live'));
          process.stdout.write('ORIGINAL_CANONICAL_PNL_PASS');
        `;
        const sandbox={document:{querySelector:()=>({})},Date,AbortController,
          URLSearchParams,setTimeout,clearTimeout,assert,process};
        vm.runInNewContext(source.slice(0,end)+execute,sandbox,{timeout:3000});
        """)
        result = subprocess.run([node, "-e", script, str(SOURCE)], check=True,
                                capture_output=True, text=True, timeout=10)
        self.assertIn("ORIGINAL_CANONICAL_PNL_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
