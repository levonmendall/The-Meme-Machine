// No dependencies or browser installation. Exercises the shipped renderer against
// the real loopback fixture API. This is NOT a substitute for browser layout QA.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawn, spawnSync} from 'node:child_process';
import {readFile, mkdtemp, rm, writeFile, mkdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {once} from 'node:events';

const root = await mkdtemp(path.join(os.tmpdir(),'mm-dashboard-ui-'));
const fixture = path.join(root,'fixtures');
const generated = spawnSync(process.env.MM_TEST_PYTHON||'python3',['-m','dashboard.fixtures',fixture],{encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
const auth = 'Basic '+Buffer.from('owner:synthetic-frontend-password').toString('base64');
const server = spawn(process.env.MM_TEST_PYTHON||'python3',['-m','dashboard','--fixture-dir',fixture,'--port','0'],{
  stdio:['ignore','pipe','pipe'], env:{...process.env,MM_DASHBOARD_OWNER_USER:'owner',MM_DASHBOARD_OWNER_PASSWORD:'synthetic-frontend-password'}});
let stderr='';server.stderr.on('data',b=>{stderr+=b;});
try {
  const [out] = await Promise.race([once(server.stdout,'data'),new Promise((_,reject)=>setTimeout(()=>reject(Error('preview startup timeout '+stderr)),8000))]);
  const base = /http:\/\/127\.0\.0\.1:\d+/.exec(out.toString())?.[0];
  assert.ok(base,'Server must publish its actual loopback port');
  const elements = new Map();
  const element = key => {
    if(!elements.has(key)) elements.set(key,{innerHTML:'',textContent:'',open:false,addEventListener(){},showModal(){this.open=true;},close(){this.open=false;}});
    return elements.get(key);
  };
  const context = vm.createContext({
    document:{hidden:true,activeElement:{tagName:'BODY'},querySelector:element,querySelectorAll:()=>[]},
    window:{addEventListener(){}},location:{hash:'#overview'},
    fetch:(url,options)=>{assert.ok(url.startsWith('/api/dashboard/')||url==='/dashboard/pons-research-v1.json');return fetch(base+url,{...options,headers:{Authorization:auth}});},
    AbortController,URLSearchParams,setTimeout,clearTimeout,setInterval(){},console,FormData,
  });
  const source = await readFile('dashboard/static/app.js','utf8');
  vm.runInContext(source,context);
  const snapshots={};
  for(const route of ['overview','lanes','lane/pump','lane/pons','positions','trades','analytics','system']) {
    context.location.hash='#'+route;
    await vm.runInContext('render()',context);
    const html=element('#main').innerHTML;
    assert.ok(!html.includes('Dashboard unavailable'),route);
    assert.ok(html.includes('DEVELOPMENT FIXTURE'),route);
    assert.ok(!html.includes('NaN'),route);
    assert.ok(!html.includes('[object Object]'),route);
    assert.ok(!/ramses|meteora/i.test(html),route);
    snapshots[route]=html;
  }
  assert.ok(snapshots.overview.includes('$512.34'));
  assert.ok(snapshots.overview.includes('+2.47%'));
  assert.ok(snapshots['lane/pons'].includes('+$4.40'));
  assert.ok(snapshots.system.includes('Native accounting reconciliation'));
  assert.ok(!snapshots.system.includes('progress_stalled')); // belongs to the hidden historical maker fixture
  assert.ok(snapshots.analytics.includes('Completed P&L by settlement day'));
  assert.ok(snapshots.positions.includes('fixture-open-pons'));
  assert.equal(vm.runInContext('fixed("0.005")',context),'0.00');
  assert.equal(vm.runInContext('fixed("0.015")',context),'0.02');
  assert.equal(vm.runInContext('fixed("123456789123456789.995")',context),'123,456,789,123,456,790.00');
  assert.equal(vm.runInContext('esc("<script>bad</script>")',context),'&lt;script&gt;bad&lt;/script&gt;');
  const research = {
    schema:'pons-historical-research-v1', status:'HISTORICAL',
    actual_market_asof:'2026-09-01T00:00:00Z', captured_at:'2026-09-01T00:01:00Z',
    source_app_commit:'a'.repeat(40), run_id:'123456789', report_sha256:'b'.repeat(64),
    report_url:'https://github.com/levonmendall/meme-machine-admin/actions/runs/123456789',
    confidence:'LIMITED — synthetic test fixture', coverage:'Two retained observations; incomplete historical coverage.',
    observations:['<img src=x onerror=alert(1)>'], shadow_hypotheses:['<script>unvalidated</script>']
  };
  const researchPanel = vm.runInContext('ponsResearchPanel',context);
  const publishedResearch=JSON.parse(await readFile('dashboard/static/pons-research-v1.json','utf8'));
  if(publishedResearch.status==='HISTORICAL') {
    const publishedPanel=researchPanel(publishedResearch);
    assert.ok(publishedPanel.includes(publishedResearch.report_sha256));
    assert.ok(publishedPanel.includes(publishedResearch.actual_market_asof));
    assert.ok(!publishedPanel.includes('RESEARCH UNAVAILABLE'));
  }
  const historical = researchPanel(research);
  for(const expected of ['HISTORICAL RESEARCH',research.actual_market_asof,research.captured_at,research.report_sha256,
    research.source_app_commit,research.report_url,'Unvalidated shadow hypotheses','No fills, P&amp;L, live quotes or strategy promotion'])
    assert.ok(historical.includes(expected),expected);
  assert.ok(historical.includes('&lt;img')&&historical.includes('&lt;script&gt;'));
  assert.ok(!historical.includes('<img')&&!historical.includes('<script>')&&!historical.includes('CURRENT'));
  for(const bad of [null,{}, {...research,status:'UNAVAILABLE'}, {...research,schema:'other'},
    {...research,actual_market_asof:null}, {...research,actual_market_asof:'2026-02-30T00:00:00Z'},
    {...research,actual_market_asof:'2026-09-01T00:02:00Z'}, {...research,captured_at:'2999-01-01T00:00:00Z'},
    {...research,source_app_commit:['a'.repeat(40)]}, {...research,report_sha256:'bad'},
    {...research,run_id:'123456788'}, {...research,report_url:'javascript:alert(1)'},
    {...research,report_url:research.report_url+'?secret=bad'}, {...research,confidence:'x'.repeat(161)},
    {...research,coverage:'x'.repeat(1001)}, {...research,observations:[]},
    {...research,observations:['a','b','c','d']}, {...research,observations:['x'.repeat(601)]},
    {...research,shadow_hypotheses:['a','b','c']}])
    assert.ok(researchPanel(bad).includes('RESEARCH UNAVAILABLE'));
  const initialFetch=context.fetch;
  for(const unavailable of [async()=>{throw Error('missing static snapshot');},
    async()=>({ok:true,json:async()=>{throw SyntaxError('malformed static snapshot');}})]) {
    context.fetch=(url,options)=>url==='/dashboard/pons-research-v1.json'?unavailable():initialFetch(url,options);
    context.location.hash='#overview';
    await vm.runInContext('render()',context);
    assert.ok(element('#main').innerHTML.includes('RESEARCH UNAVAILABLE'));
    assert.ok(element('#main').innerHTML.includes('$512.34')&&!element('#main').innerHTML.includes('Dashboard UNAVAILABLE'));
  }
  context.fetch=(url,options)=>url==='/dashboard/pons-research-v1.json'?Promise.resolve({ok:true,json:async()=>research}):initialFetch(url,options);
  await vm.runInContext('render()',context);
  assert.ok(element('#main').innerHTML.includes(research.report_sha256)&&element('#main').innerHTML.includes('$512.34'));
  context.fetch=initialFetch;
  await vm.runInContext('showPosition("fixture-open-pons")',context);
  assert.ok(element('#detail-content').innerHTML.includes('partial realization'));
  assert.ok(element('#detail-content').innerHTML.includes('Remaining basis'));
  for(const method of ['POST','PUT','DELETE']) {
    const r=await fetch(base+'/api/dashboard/portfolio',{method,headers:{Authorization:auth}});assert.equal(r.status,405);
  }
  const response=await fetch(base+'/dashboard',{headers:{Authorization:auth}});
  assert.equal(response.status,200);
  assert.ok(response.headers.get('content-security-policy').includes("connect-src 'self'"));
  const css=await readFile('dashboard/static/style.css','utf8');
  // Exact deployed baseline16594add; CSS hash independently matched live Render before this change.
  assert.equal(createHash('sha256').update(css).digest('hex'),'59a6464d096bc62d7fd3fe5fbe283d7b66e77ab215ac25d41399ce2b06e33a79');
  assert.equal(createHash('sha256').update(await readFile('dashboard/static/index.html')).digest('hex'),'a08aedcacc16a0a72396175ccd184930ad4a0690bc52d79a4c9c9144414e8454');
  assert.equal((snapshots.overview.match(/class="panel lane-card /g)||[]).length,2);
  assert.equal((snapshots.overview.match(/class="stat /g)||[]).length,14); // six portfolio, four per family
  assert.ok(css.includes('@media(max-width:760px)'));
  assert.ok(css.includes('env(safe-area-inset-bottom)'));
  assert.ok(css.includes('prefers-reduced-motion'));
  const unavailable = spawnSync(process.env.MM_TEST_PYTHON||'python3',['-c',
    'from dashboard.api import Dashboard; import json; app=Dashboard(); print(json.dumps({p:json.loads(app.response("GET","/api/dashboard/"+p)[2]) for p in ("portfolio","lanes","positions","trades","equity","system")}))'],{encoding:'utf8'});
  assert.equal(unavailable.status,0,unavailable.stderr);
  const emptyResponses = JSON.parse(unavailable.stdout);
  context.fetch=async url=>({ok:true,json:async()=>emptyResponses[url.split('/api/dashboard/')[1].split('?')[0]]});
  context.location.hash='#overview';
  await vm.runInContext('render()',context);
  assert.ok(element('#main').innerHTML.includes('Portfolio not initialized'));
  assert.ok(element('#main').innerHTML.includes('Planned starting capital'));
  assert.ok(!element('#main').innerHTML.includes('$512.34'));
  assert.ok(!element('#main').innerHTML.includes('LIVE PAPER'));
  assert.ok(element('#main').innerHTML.includes('$1,000.00'));
  const shared = spawnSync(process.env.MM_TEST_PYTHON||'python3',['-c',`
from tests.test_shared_portfolio_epoch import SharedEpochTests,shared_risk_candidate
from dashboard.api import Dashboard
import json
t=SharedEpochTests()
try:
 h=t.harness(policy=shared_risk_candidate())
 def responses():
  reader,_,_=t.view(h);app=Dashboard(reader)
  paths=['portfolio','lanes','positions','trades','equity','system','analytics','regimes']
  paths+=['lanes/'+f for f in ('pump','pons')]
  paths+=['equity?series='+f for f in ('pump','pons')]
  out={p:json.loads(app.response('GET','/api/dashboard/'+p)[2]) for p in paths}
  for row in out['positions']['data']:
   p='positions/'+row['id'];out[p]=json.loads(app.response('GET','/api/dashboard/'+p)[2])
  return out
 initial=responses()
 q,_=h.allocate([('pump_current',dict(requested='50')),('pons_survivor',dict(requested='50'))])
 pump,_=h.fill(q[0]);pons,_=h.fill(q[1]);h.at=1
 h.realize('pump_current',pump,'60')
 h.realize('pons_survivor',pons,'20',released='12.5',terminal=False)
 h.mark('pons_survivor',pons,'40')
 ongoing=responses()
 h=t.harness(policy=shared_risk_candidate())
 q,_=h.allocate([('pump_current',dict(requested='50',minimum_basis='1',execution_capacity='20'))])
 h.fill(q[0])
 print(json.dumps(dict(initial=initial,ongoing=ongoing,reduced=responses())))
finally:t.doCleanups()
`],{encoding:'utf8'});
  assert.equal(shared.status,0,shared.stderr);
  const newEpoch = JSON.parse(shared.stdout);
  const serveSnapshot = responses => async url => {
    const parsed=new URL(url,'http://offline.test');const route=decodeURIComponent(parsed.pathname.split('/api/dashboard/')[1]);
    const key=route==='equity'&&parsed.searchParams.has('series')&&parsed.searchParams.get('series')!=='portfolio'?route+'?series='+parsed.searchParams.get('series'):route;
    assert.ok(responses[key],'No synthetic response for '+key);
    return {ok:true,json:async()=>responses[key]};
  };
  context.fetch=serveSnapshot(newEpoch.initial);
  await vm.runInContext('render()',context);
  const startHtml=element('#main').innerHTML;
  assert.ok(startHtml.includes('$1,000.00')&&startHtml.includes('Starting capital'));
  assert.equal((startHtml.match(/class="stat /g)||[]).length,14);
  assert.equal((startHtml.match(/class="panel lane-card /g)||[]).length,2);
  assert.ok(!startHtml.includes('Shared capital')&&!startHtml.includes('Directional strategy performance'));
  // Financial evidence stays available in the existing System source disclosure.
  context.location.hash='#system';
  await vm.runInContext('render()',context);
  const allocationHtml=element('#main').innerHTML;
  assert.ok(allocationHtml.includes('<details><summary>Portfolio inception and source</summary>'));
  assert.ok(allocationHtml.includes('$50.00')&&allocationHtml.includes('$25.00'));
  assert.ok(allocationHtml.includes('total portfolio realized equity'));
  assert.ok(allocationHtml.includes('Asset invested-basis limit: 7.50%'));
  assert.ok(allocationHtml.includes('Marked asset limit: 10.00%'));
  assert.ok(!startHtml.includes('family-equivalent')&&!startHtml.includes('$500'));
  assert.ok(!/ramses|meteora/i.test(startHtml+allocationHtml));
  assert.ok(startHtml.includes('$1,000.00 inception reference'));
  context.fetch=serveSnapshot(newEpoch.ongoing);
  await vm.runInContext('render()',context);
  assert.ok(element('#main').innerHTML.includes('$50.88')); // 5% of $1,017.50, presentation only
  context.location.hash='#overview';
  await vm.runInContext('render()',context);
  assert.ok(element('#main').innerHTML.includes('+2.00%')); // includes $2.50 open unrealized
  assert.ok(element('#main').innerHTML.includes('Pons Survivor'));
  const openPosition=newEpoch.ongoing.positions.data[0].id;
  await vm.runInContext('showPosition('+JSON.stringify(openPosition)+')',context);
  assert.ok(element('#detail-content').innerHTML.includes('Partial exits'));
  assert.ok(element('#detail-content').innerHTML.includes('Remaining staged-add financial ceiling'));
  assert.ok(element('#detail-content').innerHTML.includes('Original plus added investment'));
  assert.ok(element('#detail-content').innerHTML.includes('Marked position exposure'));
  context.fetch=serveSnapshot(newEpoch.reduced);
  await vm.runInContext('render()',context);
  await vm.runInContext('showPosition('+JSON.stringify(newEpoch.reduced.positions.data[0].id)+')',context);
  const reducedHtml=element('#detail-content').innerHTML;
  assert.ok(reducedHtml.includes('EXECUTION_CAPACITY'));
  assert.ok(reducedHtml.includes('$50.00')&&reducedHtml.includes('$20.00'));
  assert.ok(reducedHtml.includes('neither mandates a sale'));
  const detail=vm.runInContext('positionProtectionDetails',context);
  const longHeld={...newEpoch.ongoing.positions.data[0],age_seconds:30*86400,
    protection:{state:'MONITORING',evidence_current:true,pending_exit:false,
      observed_at:'2026-10-10T16:00:00Z',high_water_bps:40000,remaining_quantity:300,
      trail:{kind:'tail_gain_giveback',return_floor_bps:24000},last_action:'hold'}};
  const healthy=detail(longHeld);
  assert.ok(healthy.includes('Holding age 30d 0h'));
  assert.ok(healthy.includes('Holding age does not require a sale'));
  assert.ok(healthy.includes('MONITORING')&&healthy.includes('400.00%'));
  assert.ok(healthy.includes('240.00%')&&healthy.includes('300'));
  const protective=detail({...longHeld,protection:{...longHeld.protection,
    stop_signal_bps:-1000,observed_return_bps:-6000,executed_return_bps:-7300,
    actionable_at:'2026-10-10T16:00:00Z',execution_at:'2026-10-10T16:00:03Z'}});
  assert.ok(protective.includes('-10.00%')&&protective.includes('-60.00%')&&protective.includes('-73.00%'));
  assert.ok(protective.includes('not guaranteed fill prices'));
  assert.ok(protective.includes('Hypothetical outcomes never enter portfolio equity'));
  assert.ok(healthy.includes('Executed native return Unavailable'));
  for(const state of ['DEGRADED_PROTECTION','OPERATIONAL_FAULT','EXIT_PENDING']) {
    const h=detail({...longHeld,protection:{...longHeld.protection,state,evidence_current:false,
      pending_exit:state==='EXIT_PENDING',last_reason:'<script>bad</script>'}});
    assert.ok(h.includes(state)&&h.includes('unavailable or stale'));
    assert.ok(!h.includes('<script>bad</script>')&&h.includes('&lt;script&gt;'));
  }
  assert.ok(detail({...longHeld,protection:undefined}).includes('Protective monitoring unavailable'));
  const stopped={operations:{snapshot_state:'CURRENT',paper_state:'STOPPED',observer_state:'CURRENT',
    monitor_state:'CURRENT',portfolio_state:'UNAVAILABLE',captured_at:'2026-10-08T00:00:00Z',
    source:{},observer:{},acceptance:Object.fromEntries(['CAPACITY','RECOVERY','AUTONOMY'].map(p=>[p,{status:'NOT_STARTED',elapsed_seconds:0}])),alerts:['paper_stopped']}};
  const connected=vm.runInContext('operationsPanel',context)(stopped,true);
  assert.ok(connected.includes('PAPER STOPPED'));
  assert.ok(connected.includes('NOT STARTED'));
  assert.ok(connected.includes('Pump Current')&&connected.includes('Pons Survivor'));
  assert.ok(connected.includes('STOPPED')&&!connected.includes('PAUSED (PAPER stopped)'));
  assert.ok(connected.includes('No authentic measurements available'));
  // Accounting freshness alone must not claim a running trading service.
  vm.runInContext('syncTopbar({state:"CURRENT",mode:"canonical",snapshot_state:"CURRENT"})',context);
  assert.equal(element('#live-indicator').textContent,'PAPER · UNAVAILABLE');
  vm.runInContext('syncTopbar({state:"CURRENT",mode:"canonical",snapshot_state:"CURRENT",paper_state:"STOPPED"})',context);
  assert.equal(element('#live-indicator').textContent,'PAPER · STOPPED');
  assert.ok(!element('#live-indicator').className.includes('is-live'));
  if(process.env.MM_ACTUAL_DASHBOARD_RESPONSES) {
    // This optional input is an authenticated, validated host snapshot, never a fixture.
    const actual=JSON.parse(await readFile(process.env.MM_ACTUAL_DASHBOARD_RESPONSES,'utf8'));
    assert.equal(actual.portfolio.mode,'canonical');
    assert.equal(actual.portfolio.data.epoch.epoch_id,'paper-shared-1000-20261011T071207Z');
    assert.equal(actual.portfolio.data.starting_capital.value,'1000.00');
    assert.equal(actual.equity.reference,'1000.00');
    context.fetch=serveSnapshot(actual);
    for(const route of ['overview','lanes','lane/pump','lane/pons','positions','trades','analytics','system']) {
      context.location.hash='#'+route;
      await vm.runInContext('render()',context);
      const html=element('#main').innerHTML;
      assert.ok(!/ramses|meteora|DEVELOPMENT FIXTURE|NaN|\[object Object\]/i.test(html),route);
      assert.ok(html.includes('PAPER STOPPED'),route);
      if(route==='overview') {
        assert.ok(html.includes('$1,000.00')&&html.includes('$0.00'));
        assert.ok(html.includes('$1,000.00 inception reference'));
        assert.equal((html.match(/class="panel lane-card /g)||[]).length,2);
        assert.equal((html.match(/class="stat /g)||[]).length,14);
        assert.ok(!html.includes('Shared capital')&&!html.includes('Directional strategy performance'));
      }
    }
    console.log('PASS: authoritative host $1,000 epoch rendered on all eight routes; correct chart reference, two families, zero balances/P&L and stopped service labeling.');
  }
  if(process.argv[2]) {
    // Static captures contain the exact renderer output and stylesheet. They
    // deliberately have no scripts/API access and are always synthetic.
    await mkdir(process.argv[2],{recursive:true});
    const shell=await readFile('dashboard/static/index.html','utf8');
    for(const [name,route] of [['desktop','overview'],['lane','lane/pons'],['mobile','overview']]) {
      let html=shell.replace('<link rel="stylesheet" href="/dashboard/style.css">',`<style>${css}</style>`)
        .replace('<script src="/dashboard/app.js" defer></script>','')
        .replace(/<main id="main" tabindex="-1">[\s\S]*?<\/main>/,`<main id="main" tabindex="-1">${snapshots[route]}</main>`);
      await writeFile(path.join(process.argv[2],name+'.html'),html);
    }
  }
  console.log('PASS: eight rendered routes, prior Render shell/CSS identity and component proportions, exact presentation rounding, fixture labeling, shared financial/protection details, API integration, mutating-method rejection, CSP, responsive rules. Browser geometry not tested.');
} finally {
  server.kill('SIGTERM');
  await once(server,'exit');
  await rm(root,{recursive:true,force:true});
}
