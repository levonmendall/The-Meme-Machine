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
const generated = spawnSync('python',['-m','dashboard.fixtures',fixture],{encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
const server = spawn('python',['-m','dashboard','--fixture-dir',fixture,'--port','0'],{stdio:['ignore','pipe','pipe']});
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
    fetch:(url,options)=>{assert.ok(url.startsWith('/api/dashboard/'));return fetch(base+url,options);},
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
    const r=await fetch(base+'/api/dashboard/portfolio',{method});assert.equal(r.status,405);
  }
  const response=await fetch(base+'/dashboard');
  assert.equal(response.status,200);
  assert.ok(response.headers.get('content-security-policy').includes("connect-src 'self'"));
  const css=await readFile('dashboard/static/style.css','utf8');
  assert.ok(css.includes('@media(max-width:760px)'));
  assert.ok(css.includes('env(safe-area-inset-bottom)'));
  assert.ok(css.includes('prefers-reduced-motion'));
  const unavailable = spawnSync('python',['-c',
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
