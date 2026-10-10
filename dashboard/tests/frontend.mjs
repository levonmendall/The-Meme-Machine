// No dependencies or browser installation. Exercises the shipped renderer against
// the real loopback fixture API. This is NOT a substitute for browser layout QA.
import assert from 'node:assert/strict';
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
    fetch:(url,options)=>{assert.ok(url.startsWith('/api/dashboard/'));return fetch(base+url,{...options,headers:{Authorization:auth}});},
    AbortController,URLSearchParams,setTimeout,clearTimeout,setInterval(){},console,FormData,
  });
  const source = await readFile('dashboard/static/app.js','utf8');
  vm.runInContext(source,context);
  const snapshots={};
  for(const route of ['overview','lanes','lane/pump','lane/pons','lane/ramses','lane/meteora','positions','trades','analytics','system']) {
    context.location.hash='#'+route;
    await vm.runInContext('render()',context);
    const html=element('#main').innerHTML;
    assert.ok(!html.includes('Dashboard unavailable'),route);
    assert.ok(html.includes('DEVELOPMENT FIXTURE'),route);
    assert.ok(!html.includes('NaN'),route);
    assert.ok(!html.includes('[object Object]'),route);
    snapshots[route]=html;
  }
  assert.ok(snapshots.overview.includes('$512.34'));
  assert.ok(snapshots.overview.includes('+2.47%'));
  assert.ok(snapshots['lane/pons'].includes('+$4.40'));
  assert.ok(snapshots.system.includes('progress_stalled'));
  assert.ok(snapshots.analytics.includes('Completed P&L by settlement day'));
  assert.ok(snapshots.positions.includes('fixture-open-pons'));
  assert.equal(vm.runInContext('fixed("0.005")',context),'0.00');
  assert.equal(vm.runInContext('fixed("0.015")',context),'0.02');
  assert.equal(vm.runInContext('fixed("123456789123456789.995")',context),'123,456,789,123,456,790.00');
  assert.equal(vm.runInContext('esc("<script>bad</script>")',context),'&lt;script&gt;bad&lt;/script&gt;');
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
from tests.test_shared_portfolio_epoch import SharedEpochTests
from dashboard.api import Dashboard
import json
t=SharedEpochTests()
try:
 h=t.harness()
 def responses():
  reader,_,_=t.view(h);app=Dashboard(reader)
  paths=['portfolio','lanes','positions','trades','equity','system','analytics','regimes']
  paths+=['lanes/'+f for f in ('pump','pons','meteora','ramses')]
  paths+=['equity?series='+f for f in ('pump','pons','meteora','ramses')]
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
 print(json.dumps(dict(initial=initial,ongoing=responses())))
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
  assert.ok(startHtml.includes('$1,000.00')&&startHtml.includes('Total realized equity'));
  assert.equal((startHtml.match(/New-position target/g)||[]).length,4);
  assert.equal((startHtml.match(/Staged-add equity ceiling/g)||[]).length,4);
  assert.ok(startHtml.includes('$50.00')&&startHtml.includes('$25.00'));
  assert.ok(startHtml.includes('total portfolio realized equity'));
  assert.ok(!startHtml.includes('family-equivalent')&&!startHtml.includes('$500'));
  assert.ok(startHtml.includes('Meteora: PAUSED')&&startHtml.includes('Ramses: PAUSED'));
  assert.ok(startHtml.includes('$1,000.00 inception reference'));
  context.fetch=serveSnapshot(newEpoch.ongoing);
  await vm.runInContext('render()',context);
  assert.ok(element('#main').innerHTML.includes('$50.88')); // 5% of $1,017.50, presentation only
  assert.ok(element('#main').innerHTML.includes('+2.00%')); // includes $2.50 open unrealized
  assert.ok(element('#main').innerHTML.includes('Pons Survivor')&&element('#main').innerHTML.includes('Realized P&amp;L'));
  const openPosition=newEpoch.ongoing.positions.data[0].id;
  await vm.runInContext('showPosition('+JSON.stringify(openPosition)+')',context);
  assert.ok(element('#detail-content').innerHTML.includes('Partial exits'));
  assert.ok(element('#detail-content').innerHTML.includes('Remaining staged-add financial ceiling'));
  const stopped={operations:{snapshot_state:'CURRENT',paper_state:'STOPPED',observer_state:'CURRENT',
    monitor_state:'CURRENT',portfolio_state:'UNAVAILABLE',captured_at:'2026-10-08T00:00:00Z',
    source:{},observer:{},acceptance:Object.fromEntries(['CAPACITY','RECOVERY','AUTONOMY'].map(p=>[p,{status:'NOT_STARTED',elapsed_seconds:0}])),alerts:['paper_stopped']}};
  const connected=vm.runInContext('operationsPanel',context)(stopped,true);
  assert.ok(connected.includes('PAPER STOPPED'));
  assert.ok(connected.includes('NOT STARTED'));
  assert.ok(connected.includes('Pump Current')&&connected.includes('Pons Survivor'));
  assert.ok(connected.includes('PAUSED (PAPER stopped)'));
  assert.ok(connected.includes('No authentic measurements available'));
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
  console.log('PASS: 10 rendered routes, exact presentation rounding, fixture labeling, lifecycle details, API integration, mutating-method rejection, CSP, responsive rules. Browser geometry not tested.');
} finally {
  server.kill('SIGTERM');
  await once(server,'exit');
  await rm(root,{recursive:true,force:true});
}
