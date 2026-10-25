"""Original UI with operational evidence only; all payloads are disposable."""
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'static' / 'app.js'


class LiveOperationsFrontendTests(unittest.TestCase):
    def test_retired_financial_interface_is_not_requested_or_linked(self):
        code = SOURCE.read_text()
        self.assertIn("api('live')", code)
        self.assertIn("pons-live-operations-v1", code)
        self.assertNotIn('/api/pons-simulator/state', code)
        self.assertNotIn('/dashboard/pons-simulator', code)
        self.assertNotIn('ponsFocusedOverview', code)
        self.assertNotIn('ponsAccountPanel', code)
        self.assertNotIn('ponsAccountMetric', code)
        live = code.split('// Live operations are reporting only.', 1)[1].split('function canonicalHistoryIdentity(', 1)[0]
        self.assertNotIn("metric('financial'", live)
        self.assertNotIn('feed.lifecycles', live)
        self.assertNotIn('feed.history', live)
        self.assertIn("livePonsPanel(live,p)", code)
        self.assertIn("livePonsPanel(live,p,true)", code)

    def test_actual_renderer_preserves_finance_and_truthful_live_boundaries(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required for the shipped renderer')
        program = textwrap.dedent(r"""
        const assert=require('assert'),fs=require('fs'),vm=require('vm');
        const source=fs.readFileSync(process.argv[1],'utf8');
        const end=source.indexOf("document.querySelector('#close-detail')");
        assert(end>0);
        const now=Date.parse('2026-10-25T16:00:00Z');
        class Clock extends Date {static now(){return now;}}
        const stamp=delta=>new Date(now+delta*1000).toISOString();
        const original={paper_state:'STOPPED',epoch:{epoch_id:'original-canonical-epoch'}};
        const identity={source_commit:'a'.repeat(40),epoch_id:'different-live-owner',inception_sha256:'b'.repeat(64)};
        const metric=value=>({value,quality:'MEASURED',state:'CURRENT',unit:'COUNT',as_of:stamp(-5)});
        const feed={schema:'pons-live-operations-v1',financial_authority:false,
          financial_source:'ORIGINAL_CANONICAL_PORTFOLIO_ONLY',source_ledger_authoritative:false,
          state:'CURRENT',captured_at:stamp(-2),identity,
          account_cutover:{state:'NOT_ESTABLISHED',reason:'NO_AUTHENTICATED_ORIGINAL_EXECUTION_BINDING'},
          strategy_version:{policy_sha256:'c'.repeat(64)},
          observer:{source_commit:identity.source_commit,status:'RUNNING',heartbeat_at:stamp(-3),
            market_as_of:stamp(-6),restart_count:4,history_coverage:'INCOMPLETE',
            current:{completed:8,eligible:7,wait:10,incomplete:10,rejected:1},
            survivor:{completed:0,eligible:0,wait:3,incomplete:3,rejected:0},
            decisions:[{id:'d'.repeat(64),at:stamp(-3600),strategy:'SURVIVOR',
              action:'WAIT',qualification:'INCOMPLETE',reason:'native_survivor_history_incomplete'}]},
          paper:{schema:'pons-current-paper-report-v1',...identity,policy_sha256:'c'.repeat(64),
            state:'DISABLED',permission_enabled:false,new_risk_enabled:false,authority_sha256:null,heartbeat_at:stamp(-2)},
          metrics:{activity:{events_processed:metric('1234'),sampled_block_debt:metric('0'),queue_depth:metric('500')},
            operational:{provider_failures:metric('2'),provider_requests:metric('45')},
            financial:{cash:{...metric('999999'),unit:'USD'}}},
          lifecycles:[{id:'UNRELATED_FINANCIAL_LIFECYCLE'}],history:{equity:{rows:['UNRELATED_EQUITY']}}};
        let requested=[];
        const context=vm.createContext({document:{querySelector:()=>({})},Date:Clock,AbortController,
          URLSearchParams,setTimeout,clearTimeout,fetch:async url=>{
            requested.push(url);return {ok:true,json:async()=>feed};}});
        vm.runInContext(source.slice(0,end),context);
        context.FEED=feed;context.ORIGINAL=original;
        const render=expression=>vm.runInContext(expression,context);
        const html=render('livePonsPanel(FEED,ORIGINAL,true)');
        assert(html.includes('MARKET CURRENT'));
        assert(html.includes('Original financial cutover pending'));
        assert(html.includes('original portfolio reports STOPPED'));
        assert(html.includes('Reported owner permission DISABLED'));
        assert(html.includes('Native new-risk gate CLOSED'));
        assert(html.includes('separate account identities'));
        assert(html.includes('Reference complete')&&html.includes('Reference eligible'));
        assert(html.includes('not financial Current qualifications'));
        assert(html.includes('HISTORICAL')&&html.includes('WAIT · SHADOW'));
        assert(html.includes('Pending candidates: 500')&&html.includes('Sampled block debt'));
        assert(html.includes('Position-protection acceptance: UNAVAILABLE'));
        assert(!html.includes('999999')&&!html.includes('UNRELATED_'));
        context.FEED={...feed,paper:{...feed.paper,state:'READY',permission_enabled:true,authority_sha256:'e'.repeat(64)}};
        const armed=render('livePonsPanel(FEED,ORIGINAL)');
        assert(armed.includes('ARMED · AWAITING QUALIFICATION'));
        assert(armed.includes('Original financial cutover pending'));
        assert(armed.includes('not original-account authority'));
        context.FEED={...feed,observer:{...feed.observer,market_as_of:stamp(-61)}};
        const stale=render('livePonsPanel(FEED,ORIGINAL)');
        assert(stale.includes('STALE')&&!stale.includes('MARKET CURRENT'));
        context.FEED={...feed,observer:{...feed.observer,heartbeat_at:stamp(1)}};
        assert(!render('livePonsPanel(FEED,ORIGINAL)').includes('MARKET CURRENT'));
        context.FEED={...feed,observer:{...feed.observer,source_commit:'f'.repeat(40)}};
        const mismatch=render('livePonsPanel(FEED,ORIGINAL,true)');
        assert(mismatch.includes('UNAVAILABLE')&&!mismatch.includes('1234'));
        context.FEED={...feed,metrics:{...feed.metrics,activity:{...feed.metrics.activity,
          events_processed:{...metric('<script>unsafe</script>')}}}};
        assert(!render('livePonsPanel(FEED,ORIGINAL)').includes('<script>unsafe'));
        context.FEED={...feed,paper:{...feed.paper,permission_enabled:1}};
        assert(render('livePonsPanel(FEED,ORIGINAL)').includes('permission UNKNOWN'));
        context.FEED=null;
        assert(render('livePonsPanel(FEED,ORIGINAL)').includes('UNAVAILABLE'));
        (async()=>{await render('livePonsFeed()');
          assert.deepEqual(requested,['/api/dashboard/live']);
          process.stdout.write('LIVE_OPERATIONS_ORIGINAL_UI_PASS');
        })().catch(error=>{console.error(error);process.exitCode=1;});
        """)
        result = subprocess.run([node, '-e', program, str(SOURCE)], check=True,
                                capture_output=True, text=True, timeout=10)
        self.assertIn('LIVE_OPERATIONS_ORIGINAL_UI_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
