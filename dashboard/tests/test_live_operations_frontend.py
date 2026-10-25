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
        assert(html.includes('Financial account selection pending'));
        assert(html.includes('original portfolio reports STOPPED'));
        assert(html.includes('Reported owner permission DISABLED'));
        assert(html.includes('Native new-risk gate CLOSED'));
        assert(html.includes('not verified as the same account'));
        assert(html.includes('Reference complete')&&html.includes('Reference eligible'));
        assert(html.includes('not financial Current qualifications'));
        assert(html.includes('HISTORICAL')&&html.includes('WAIT · SHADOW'));
        assert(html.includes('Pending candidates: 500')&&html.includes('Sampled block debt'));
        assert(html.includes('Position-protection acceptance: UNAVAILABLE'));
        assert(!html.includes('999999')&&!html.includes('UNRELATED_'));
        context.FEED={...feed,paper:{...feed.paper,state:'READY',permission_enabled:true,authority_sha256:'e'.repeat(64)}};
        const armed=render('livePonsPanel(FEED,ORIGINAL)');
        assert(armed.includes('ARMED · AWAITING QUALIFICATION'));
        assert(armed.includes('Financial account selection pending'));
        assert(armed.includes('authority for the displayed account is not established'));
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
        const selectedIdentity={...identity,epoch_id:'paper-pons-simulator-1000-20261024',
          inception_sha256:'0098b5790dee06e6b540a1e02fad0db562d115006f10b3575b36ba4e0f221474'};
        const selected={mode:'canonical',financial_source:'pons_experiment',state:'CURRENT',snapshot_state:'CURRENT',
          as_of:stamp(-3),paper_state:'DISABLED',epoch:{epoch_id:selectedIdentity.epoch_id},
          financial_identity:{epoch_id:selectedIdentity.epoch_id,inception_sha256:selectedIdentity.inception_sha256},
          selected_financial_identity:selectedIdentity};
        const selectedFeed={...feed,financial_source:'pons_experiment',identity:selectedIdentity,
          paper:{...feed.paper,...selectedIdentity},account_cutover:{state:'VERIFIED',
            current_owner_epoch:selectedIdentity.epoch_id,inception_sha256:selectedIdentity.inception_sha256,
            reason:'AUTHENTICATED_SELECTED_CANONICAL_BINDING'}};
        context.ACCOUNT=selected;context.FEED=selectedFeed;
        assert(render('selectedFinancialBinding(ACCOUNT,FEED,livePonsEvidence(FEED))'));
        context.ACCOUNT={...selected,as_of:selected.as_of.replace('Z','+00:00')};
        assert(render('selectedFinancialBinding(ACCOUNT,FEED,livePonsEvidence(FEED))'));
        context.ACCOUNT=selected;
        const boundHtml=render('livePonsPanel(FEED,ACCOUNT,true)');
        assert(!boundHtml.includes('selection pending')&&!boundHtml.includes('binding unavailable'));
        assert(boundHtml.includes('selected canonical PAPER account identity'));
        assert(boundHtml.includes('Reported owner permission DISABLED'));
        assert(boundHtml.includes('dashboard grants no execution authority'));
        assert(boundHtml.includes('WAIT · SHADOW')&&!boundHtml.includes('999999'));
        const refusedBindings=[
          [{...selected,financial_identity:null},selectedFeed],
          [{...selected,financial_identity:{...selected.financial_identity,inception_sha256:'f'.repeat(64)}},selectedFeed],
          [{...selected,selected_financial_identity:{...selectedIdentity,source_commit:'f'.repeat(40)}},selectedFeed],
          [{...selected,selected_financial_identity:{...selectedIdentity,source_commit:1}},selectedFeed],
          [{...selected,selected_financial_identity:{...selectedIdentity,epoch_id:'another-1000-account'}},selectedFeed],
          [{...selected,epoch:{epoch_id:'another-1000-account'}},selectedFeed],
          [{...selected,as_of:stamp(-61)},selectedFeed],
          [{...selected,state:'STALE'},selectedFeed],
          [{...selected,snapshot_state:'STALE'},selectedFeed],
          [{...selected,mode:'fixture'},selectedFeed],
          [selected,{...selectedFeed,captured_at:stamp(-61)}],
          [selected,{...selectedFeed,state:'STALE'}],
          [selected,{...selectedFeed,identity:{...selectedIdentity,inception_sha256:'f'.repeat(64)}}],
          [selected,{...selectedFeed,identity:{...selectedIdentity,source_commit:'f'.repeat(40)}}],
          [selected,{...selectedFeed,account_cutover:{...selectedFeed.account_cutover,state:'NOT_ESTABLISHED'}}],
          [selected,{...selectedFeed,account_cutover:{...selectedFeed.account_cutover,current_owner_epoch:'other'}}],
          [selected,{...selectedFeed,account_cutover:{...selectedFeed.account_cutover,inception_sha256:'f'.repeat(64)}}],
          [selected,{...selectedFeed,account_cutover:{...selectedFeed.account_cutover,reason:'OTHER'}}]
        ];
        for(const [account,operations] of refusedBindings){
          context.ACCOUNT=account;context.FEED=operations;
          assert(!render('selectedFinancialBinding(ACCOUNT,FEED,livePonsEvidence(FEED))'));
          assert(render('livePonsPanel(FEED,ACCOUNT)').includes('Live account binding unavailable'));
        }
        context.ACCOUNT=selected;context.FEED={...selectedFeed,paper:{...selectedFeed.paper,permission_enabled:1}};
        assert(render('livePonsPanel(FEED,ACCOUNT)').includes('permission UNKNOWN'));
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
