'use strict';
const LANES = ['pump', 'pons', 'ramses', 'meteora'];
const names = {pump:'Pump', pons:'Pons', ramses:'Ramses', meteora:'Meteora'};
const main = document.querySelector('#main');
const state = {period:'ALL', series:'portfolio', offset:0, filters:{}, generation:0, busy:false, lastPortfolio:null};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const title = word => word.replaceAll('_',' ');
const badge = (value, label) => `<span class="badge ${esc(value)}">${esc(label || title(value))}</span>`;
const date = value => value ? new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Unavailable';
const empty = text => `<div class="empty"><span class="symbol">⌁</span>${esc(text)}</div>`;

// Formatting only. Currency totals and percentages are calculated by Python.
function fixed(value, places=2) {
  const match = /^(-?)(\d+)(?:\.(\d*))?$/.exec(String(value));
  if (!match) return 'Unavailable';
  const [, sign, whole, tail=''] = match;
  const padded = tail.padEnd(places+1,'0');
  let n = BigInt(whole + padded.slice(0,places));
  const next = Number(padded[places]);
  if (next>5 || (next===5 && (/[1-9]/.test(padded.slice(places+1)) || n%2n===1n))) n += 1n;
  const digits = n.toString().padStart(places+1,'0');
  const integer = (places ? digits.slice(0,-places) : digits).replace(/\B(?=(\d{3})+(?!\d))/g,',');
  return (n===0n?'':sign)+integer+(places?'.'+digits.slice(-places):'');
}
function value(m, kind='money', signed=false) {
  if (!m || m.value===null || m.value===undefined) return `<span class="missing">${esc(title(m?.state || 'UNAVAILABLE'))}</span>`;
  const negative = String(m.value).startsWith('-');
  const nonzero = /[1-9]/.test(String(m.value));
  const cls = signed && nonzero ? (negative?'negative':'positive') : '';
  let formatted = kind==='count' ? esc(m.value) : fixed(m.value);
  if (kind==='money') formatted = negative ? '-$'+formatted.slice(1) : '$'+formatted;
  if (kind==='percent') formatted += '%';
  if (kind==='seconds') formatted += ' s';
  if (signed && nonzero && !negative) formatted='+'+formatted;
  return `<span class="${cls}">${formatted}</span>`;
}
function stat(label,m,kind='money',signed=false,cls='') {
  return `<div class="stat ${cls}"><label>${esc(label)}</label><strong>${value(m,kind,signed)}</strong>${m?.value!=null&&m.state!=='CURRENT'?`<small>${esc(title(m.state))}</small>`:''}</div>`;
}
async function api(path, params={}) {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),7000);
  try {
    const query = new URLSearchParams(Object.entries(params).filter(([,v])=>v!==''&&v!=null));
    const response = await fetch('/api/dashboard/'+path+(query.size?'?'+query:''), {signal:controller.signal,cache:'no-store',credentials:'same-origin'});
    if (!response.ok) throw new Error('Local observations unavailable');
    return await response.json();
  } finally { clearTimeout(timer); }
}
function header(name,p) {
  const demo = p.mode==='fixture';
  return `<div class="pagehead"><div><p class="eyebrow">Portfolio intelligence / Paper only</p><h1>${esc(name)}</h1></div><div class="head-right">${badge(demo?'UNKNOWN':p.state,demo?'DETERMINISTIC FIXTURE':p.state==='CURRENT'?'LIVE PAPER':title(p.state))}<small class="muted">Accounting ${date(p.as_of)}</small></div></div>`+
    (demo?'<div class="banner fixture"><strong>DEVELOPMENT FIXTURE</strong> · Synthetic balances and trades. Fixed demo clock. These results are not market performance.</div>':'')+
    (p.state==='NOT_INITIALIZED'?'<div class="banner"><strong>Portfolio not initialized.</strong> The intended inception is $500.00. No canonical inception is connected; historical campaigns are excluded.</div>':'')+
    (p.state==='FAIL_CLOSED'?'<div class="banner error"><strong>Accounting fail-closed.</strong> Source validation or reconciliation failed. Values are not trusted current balances.</div>':'')+
    (p.state==='STALE'?'<div class="banner"><strong>Accounting stale.</strong> Last persisted balances are labeled stale; expired valuations are unavailable.</div>':'');
}
function hero(p,chart) {
  const m=p.metrics;
  const capitalLabel=p.epoch?'Starting capital':'Planned starting capital';
  const spark=plot(chart?.data||[],chart?.reference||'500','portfolio',true);
  return `<section class="panel hero portfolio-summary">
    <div class="portfolio-primary">
      <p class="summary-label">Portfolio value</p>
      <div class="portfolio-primary-row">
        <div>
          <div class="equity ${m.equity.value==null?'unavailable':''}">${value(m.equity)}</div>
          <div class="pnl-line">${value(m.net_pnl,'money',true)} <span class="muted">(${value(m.return_pct,'percent',true)})</span></div>
        </div>
        <div class="hero-spark">${spark}</div>
      </div>
    </div>
    <div class="summary-stats">
      ${stat(capitalLabel,{value:'500.00',state:p.state})}
      ${stat('Total P&L',m.net_pnl,'money',true)}
      ${stat('Total trades',m.trades_taken,'count')}
      ${stat('Open positions',m.open_positions,'count')}
      ${stat('Closed positions',m.completed_trades,'count')}
      ${stat('Win rate',m.win_rate,'percent')}
    </div>
  </section>`;
}
function sharedCapital(p) {
  const c=p.shared_capital;
  if (!c) return '';
  const amount = key => ({value:c[key],state:p.state});
  const labels = {inception_equity:'Portfolio inception',realized_equity:'Realized portfolio equity',
    marked_equity:'Marked portfolio equity',free_cash:'Available shared cash',actual_cash:'Actual shared cash',
    deployed_basis:'Deployed basis',active_reservations:'Reserved cash',
    pending_authoritative_commitments:'Pending commitments',required_funding_obligations:'Funding obligations'};
  const regimes=['pump_current','pump_survivor','pons_current','pons_survivor'];
  const limits=c.risk_limits,base=Number(c.risk.risk_base);
  const riskRows=limits ? [['Portfolio',c.risk.exposure.portfolio,limits.portfolio_bps],
    ...['pump','pons'].map(f=>[names[f],c.risk.exposure.family[f],limits.family_max_bps[f]]),
    ['Most exposed asset / lineage',Math.max(0,...Object.values(c.risk.exposure.asset).map(Number)),limits.asset_bps],
    ...['solana','robinhood','directional','crypto_beta'].map(g=>[title(g),c.risk.exposure.group[g],limits.group_bps[g]])] : [];
  const riskUse=(exposure,bps)=>{const ceiling=base*Number(bps)/10000;return ceiling>0 ? `${(Number(exposure)/ceiling*100).toFixed(1)}% of ${ceiling.toFixed(2)} USD` : 'Unavailable'};
  const latency=Object.values(c.allocation_latency||{}).flatMap(row=>Object.entries(row.regimes||{})).map(([r,v])=>`${title(r)}: median ${(v.median_us/1000).toFixed(1)} ms, p95 ${(v.p95_us/1000).toFixed(1)} ms, p99 ${(v.p99_us/1000).toFixed(1)} ms (${v.samples} requests)`).join(' · ') || 'Unmeasured';
  return `<section class="panel"><h2>Shared capital</h2><p>Authority ${esc(c.authority_health)} · Cutover ${esc(c.cutover_status)}</p>
    <div class="summary-stats">${Object.entries(labels).map(([key,label])=>stat(label,amount(key))).join('')}</div>
    <p>Individual targets use 5% of realized family-equivalent equity.</p>
    <p>${['pump','pons'].map(f=>`${esc(names[f])} sizing equity: ${value({value:c.family_equivalent_equity[f],state:p.state})}`).join(' · ')}</p>
    <table><thead><tr><th>Regime</th><th>Deployed basis</th><th>Risk utilization</th><th>Qualified, unfunded</th><th>Funding constraints</th></tr></thead>
    <tbody>${regimes.map(r=>{const row=c.regimes[r];return `<tr><td>${esc(title(r))}</td><td>${value({value:row.deployed_basis,state:p.state})}</td><td>${esc(limits ? riskUse(row.aggregate_exposure,limits.regime_max_bps[r]) : 'Unavailable')}</td><td>${esc(row.qualified_but_unfunded)}</td><td>${esc(Object.entries(row.denials).map(([reason,n])=>`${reason}: ${n}`).join(', ')||'None')}</td></tr>`}).join('')}</tbody></table>
    <p>${riskRows.map(([label,exposure,bps])=>`${esc(label)} risk: ${esc(riskUse(exposure,bps))}`).join(' · ')}</p>
    <p>Meteora: PAUSED · Ramses: PAUSED. Historical attribution remains in the portfolio.</p>
    <p>Portfolio exposure: ${value({value:c.risk.exposure.portfolio,state:p.state})} · Drawdown: ${esc(c.risk.drawdown_bps)} bps · Allocation latency: ${esc(latency)}</p>
    </section>`;
}
function plot(points,reference,series='portfolio',small=false) {
  const valid=points.filter(p=>p.value!==null);
  if (!valid.length) return small?'<div class="spark muted">History unavailable</div>':empty('No equity samples for this portfolio epoch');
  // Number is used only for presentation coordinates, never for accounting.
  const values=valid.map(p=>Number(p.value));
  const ref=Number(reference);
  const low=Math.min(...values,Number.isFinite(ref)?ref:Math.min(...values));
  const high=Math.max(...values,Number.isFinite(ref)?ref:Math.max(...values));
  const pad=Math.max((high-low)*.18,small?.1:1), min=low-pad,max=high+pad;
  const width=small?320:600,height=small?58:220,left=small?2:52,right=small?318:585,top=small?4:18,bottom=small?54:185;
  const times=valid.map(p=>new Date(p.at).getTime()), start=Math.min(...times),end=Math.max(...times);
  const x=at=>left+(new Date(at).getTime()-start)/Math.max(end-start,1)*(right-left);
  const y=v=>bottom-(Number(v)-min)/(max-min)*(bottom-top);
  const coords=valid.map(p=>[x(p.at),y(p.value)]);
  const poly=coords.map(([px,py])=>`${px.toFixed(2)},${py.toFixed(2)}`).join(' ');
  const line=`<polyline class="series" points="${poly}"/>`;
  const area=small?'':`<polygon class="area" points="${left},${bottom} ${poly} ${right},${bottom}"/>`;
  const circles=small?'':valid.map(p=>`<circle class="sample" cx="${x(p.at)}" cy="${y(p.value)}" r="2.5"><title>${esc(date(p.at))}: ${esc(p.value)} USD</title></circle>`).join('');
  let labels='';
  if (!small) {
    for(let i=0;i<4;i++) {
      const v=min+(max-min)*i/3;
      labels+=`<line class="grid" x1="${left}" x2="${right}" y1="${y(v)}" y2="${y(v)}"/><text x="0" y="${y(v)+4}">$${v.toFixed(0)}</text>`;
    }
    if(Number.isFinite(ref)) labels+=`<line class="reference" x1="${left}" x2="${right}" y1="${y(ref)}" y2="${y(ref)}"/>`;
    for(let i=0;i<5;i++) {
      const t=start+(end-start)*i/4;
      const px=left+(right-left)*i/4;
      labels+=`<text x="${px}" y="211" text-anchor="${i===0?'start':i===4?'end':'middle'}">${esc(new Date(t).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}))}</text>`;
    }
  }
  return `<svg class="${small?'spark':'chart'} ${series==='portfolio'?'':series}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(series)} actual observed samples">${labels}${area}${line}${circles}</svg>`;
}
function chartPanel(c, options=true) {
  return `<section class="panel chart-main"><div class="panelhead"><h2>${c.series==='portfolio'?'Portfolio performance':names[c.series]+' cumulative P&L'}</h2>${options?`<div class="chart-tools"><select id="series" aria-label="Chart series">${['portfolio',...LANES].map(k=>`<option value="${k}" ${k===state.series?'selected':''}>${k==='portfolio'?'Portfolio':names[k]}</option>`).join('')}</select><div class="periods" aria-label="Chart period">${['1H','6H','24H','7D','30D','ALL'].map(p=>`<button data-period="${p}" class="${p===state.period?'selected':''}" ${c.periods.includes(p)?'':'disabled'}>${p}</button>`).join('')}</div></div>`:''}</div><div class="panelbody">${plot(c.data,c.reference,c.series)}<div class="chart-note"><span>${c.displayed_count} observed samples${c.truncated?' · bounded recent slice':''} · no interpolation</span><span>${c.series==='portfolio'?'$500 inception reference':'$0 P&L reference'}</span></div></div></section>`;
}
function laneIcon(lane) {
  const icons={
    pump:'<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10"/><path d="M8 22 23 7M21 7h4v4"/></svg>',
    pons:'<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 16c4-7 8-7 11 0s7 7 11 0"/><path d="M5 11c4-5 8-5 11 0s7 5 11 0"/></svg>',
    ramses:'<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M7 21c2-8 5-12 9-12s7 4 9 12"/><path d="M10 10 6 7M22 10l4-3M12 17c1 5 3 8 4 8s3-3 4-8"/></svg>',
    meteora:'<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M8 24c10-2 15-8 16-17-8 2-14 7-16 17Z"/><path d="m8 24 13-13M8 18l-4 2M12 12l-3-3"/></svg>'
  };
  return icons[lane]||'';
}
function laneCards(lanes,charts={}) {
  return `<div class="lane-grid">${lanes.map(l=>{const m=l.metrics;return `<a href="#lane/${l.lane}" class="panel lane-card ${l.lane}" aria-label="${names[l.lane]} lane details">
    <div class="lane-title"><span class="lane-name"><span class="lane-icon">${laneIcon(l.lane)}</span>${names[l.lane].toUpperCase()} LANE</span><span class="lane-arrow">›</span></div>
    <div class="lane-kpis"><div><span class="summary-label">P&L</span><div class="lane-money">${value(m.net_pnl,'money',true)}</div><div class="lane-return">${value(m.contribution_pct,'percent',true)}</div></div></div>
    <div class="mini-stats">${stat('Trades',m.trades_taken,'count')}${stat('Open',m.open_positions,'count')}${stat('Closed',m.completed_trades,'count')}${stat('Win rate',m.win_rate,'percent')}</div>
    ${plot(charts[l.lane]?.data||[],'0',l.lane,true)}
  </a>`;}).join('')}</div>`;
}
function laneBars(lanes,outcomes=false) {
  const known=lanes.filter(l=>outcomes?(l.metrics.wins.value!=null&&l.metrics.losses.value!=null):l.metrics.net_pnl.value!=null);
  if (!known.length) return empty('Canonical performance unavailable');
  const max=Math.max(1,...known.map(l=>Math.abs(Number(l.metrics.net_pnl.value))));
  return `<div class="legend">${outcomes?'<span><i></i>Wins</span><span><i class="loss"></i>Losses</span>':'Net P&L · USD · shared costs shown separately'}</div><div class="bars">${lanes.map(l=>{
    const m=l.metrics;
    if (outcomes?(m.wins.value==null||m.losses.value==null):m.net_pnl.value==null) return `<div class="bar-row"><span>${names[l.lane]}</span><span class="muted">Unavailable</span></div>`;
    const w=Number(m.wins.value),loss=Number(m.losses.value),n=Number(m.completed_trades.value);
    const a=outcomes?(n?w/n*100:0):Math.abs(Number(m.net_pnl.value))/max*100;
    const b=outcomes?(n?loss/n*100:0):0;
    return `<div class="bar-row ${l.lane}"><span>${names[l.lane]}</span><div class="bar-track"><svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true"><rect class="${outcomes?'bar-positive':Number(m.net_pnl.value)<0?'bar-negative':'bar-lane'}" width="${a}" height="10"/><rect class="bar-negative" x="${a}" width="${b}" height="10"/></svg></div><span>${outcomes?`${w} / ${loss}`:value(m.net_pnl,'money',true)}</span></div>`;
  }).join('')}</div><p class="sample-count">${outcomes?'Completed sample: '+lanes.map(l=>names[l.lane]+' '+(l.metrics.completed_trades.value??'unknown')).join(' · '):'Contribution denominator: total $500 inception. No strategy ranking.'}</p>`;
}
function laneDonut(lanes,p) {
  const usable=lanes.map(l=>({lane:l.lane,value:Number(l.metrics.net_pnl.value)})).filter(x=>Number.isFinite(x.value));
  const total=usable.reduce((sum,x)=>sum+Math.abs(x.value),0);
  if(!total) return empty('Canonical lane P&L unavailable');
  let offset=0;
  const segments=usable.map(x=>{
    const pct=Math.abs(x.value)/total*100;
    const circle=`<circle class="donut-segment ${x.lane}" cx="50" cy="50" r="38" pathLength="100" stroke-dasharray="${pct.toFixed(3)} ${(100-pct).toFixed(3)}" stroke-dashoffset="${(-offset).toFixed(3)}"/>`;
    offset+=pct; return circle;
  }).join('');
  const legend=usable.map(x=>{
    const pct=Math.abs(x.value)/total*100;
    return `<div class="donut-legend-row ${x.lane}"><span><i></i>${names[x.lane]}</span><strong>${pct.toFixed(0)}%</strong></div>`;
  }).join('');
  return `<div class="donut-layout"><div class="donut-wrap"><svg viewBox="0 0 100 100" role="img" aria-label="Absolute lane contribution to observed net P&L"><circle class="donut-track" cx="50" cy="50" r="38"/>${segments}</svg><div class="donut-center"><strong>${value(p.metrics.return_pct,'percent',true)}</strong><span>Total P&L</span></div></div><div class="donut-legend">${legend}</div></div>`;
}
function positionsTable(rows,completed=false) {
  if (!rows.length) return empty(completed?'No completed trades in the available epoch records':'No open positions in the available epoch records');
  const columns=completed?['Asset / pool','Lane','Settled','Net realized','Outcome']:['Asset / pool','Lane','Capital / basis','Current value','Unrealized'];
  return `<div class="table-wrap"><table class="position-table"><thead><tr>${columns.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.map(p=>`<tr><td data-label="${columns[0]}"><button class="row-button" data-position="${esc(p.id)}">${esc(p.asset)}</button><small>${esc(p.id)}</small></td><td data-label="Lane"><span class="lane-label ${p.lane}">${names[p.lane]}</span><small>${esc(p.runner_state||p.lp_state||p.state)}</small></td>${completed?`<td data-label="Settled">${date(p.settled_at)}</td><td data-label="Net realized">${value({value:p.realized_pnl,state:'CURRENT'},'money',true)}</td><td data-label="Outcome">${esc(p.outcome)}</td>`:`<td data-label="Capital / remaining basis">${value({value:p.capital,state:'CURRENT'})}<small>Basis ${value({value:p.remaining_basis,state:'CURRENT'})}</small></td><td data-label="Current value">${value(p.current_value)}<small>Age ${Math.floor(p.age_seconds/60)}m</small></td><td data-label="Unrealized">${value(p.unrealized_pnl,'money',true)}<small>${value(p.unrealized_pct,'percent',true)}</small></td>`}</tr>`).join('')}</tbody></table></div>`;
}
function tablePanel(name,res,completed,link) {
  return `<section class="panel"><div class="panelhead"><h2>${name}</h2>${link?`<a class="link" href="#${link}">View all →</a>`:''}</div>${res.total===null?empty('Position state unavailable'):positionsTable(res.data,completed)}</section>`;
}
function systemStrip(s) {
  return `<section class="panel system-strip"><div><h3>Portfolio accounting</h3>${badge(s.accounting.state)}</div><div><h3>Read model</h3>${badge(s.read_model.state)}</div><div><h3>Persisted telemetry</h3>${badge(s.telemetry.state)}</div><div><h3>Lane state</h3><a href="#system" class="link">Inspect all four lanes →</a></div></section>`;
}
function overviewAlerts(p) {
  const demo=p.mode==='fixture';
  return (demo?'<div class="banner fixture"><strong>DEVELOPMENT FIXTURE</strong> · Synthetic balances and trades. Fixed demo clock. These results are not market performance.</div>':'')+
    (p.state==='NOT_INITIALIZED'?'<div class="banner"><strong>Portfolio not initialized.</strong> The intended inception is $500.00. No canonical inception is connected; historical campaigns are excluded.</div>':'')+
    (p.state==='FAIL_CLOSED'?'<div class="banner error"><strong>Accounting fail-closed.</strong> Source validation or reconciliation failed. Values are not trusted current balances.</div>':'')+
    (p.state==='STALE'?'<div class="banner"><strong>Accounting stale.</strong> Last persisted balances are labeled stale; expired valuations are unavailable.</div>':'');
}
function overviewStatus(s,p) {
  const laneStates=LANES.map(l=>s.lanes?.[l]?.operational?.state||'UNKNOWN');
  const coreStates=[s.accounting.state,s.read_model.state,s.telemetry.state];
  const allHealthy=[...laneStates,...coreStates].every(x=>x==='CURRENT')&&(!p.paper_state||p.paper_state==='RUNNING');
  const headline=p.mode==='fixture'?'Development fixture active':p.paper_state==='STOPPED'?'PAPER STOPPED':allHealthy&&p.state==='CURRENT'?'All systems operational':p.state==='NOT_INITIALIZED'?'Awaiting portfolio initialization':'System attention required';
  const headlineState=allHealthy&&p.state==='CURRENT'?'positive':p.state==='FAIL_CLOSED'?'negative':'caution';
  const notification=p.mode==='fixture'?'Fixture mode is clearly separated from genuine portfolio performance.':p.state==='CURRENT'&&allHealthy?'No critical alerts. Read-only paper telemetry is current.':p.state==='NOT_INITIALIZED'?'The genuine $500 paper portfolio has not been initialized.':'One or more persisted states are stale, unavailable, or fail-closed.';
  return `<div class="overview-bottom">
    <section class="panel system-summary-card">
      <div class="status-heading"><h2>System status</h2><span class="${headlineState} status-headline">● ${esc(headline)}</span></div>
      <div class="status-kpis">
        <div><span>Accounting</span>${badge(s.accounting.state)}</div>
        <div><span>Read model</span>${badge(s.read_model.state)}</div>
        <div><span>Telemetry</span>${badge(s.telemetry.state)}</div>
        <div><span>Lane health</span><strong>${laneStates.filter(x=>x==='CURRENT').length}/4 current</strong></div>
      </div>
    </section>
    <section class="panel notification-card">
      <div class="notification-icon" aria-hidden="true">◆</div>
      <div><h2>Notifications</h2><p>${esc(notification)}</p></div>
      <a class="link" href="#system">View all →</a>
    </section>
  </div>`;
}
function seconds(v) {
  if(v===null||v===undefined) return 'Unmeasured';
  return `${Math.floor(v/3600)}h ${Math.floor(v%3600/60)}m ${Math.floor(v%60)}s`;
}
function measuredRows(obj,prefix='',depth=0) {
  if(!obj||depth>4) return [];
  return Object.entries(obj).flatMap(([k,v])=>{
    const key=prefix?prefix+' · '+title(k):title(k);
    return typeof v==='number'?[[key,v]]:v&&typeof v==='object'?measuredRows(v,key,depth+1):[];
  }).slice(0,100);
}
function observationsTable(rows) {
  return rows.length?`<div class="table-wrap"><table><thead><tr><th>Recorded measure</th><th>Value</th></tr></thead><tbody>${rows.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table></div>`:empty('No authentic measurements available');
}
function operationsPanel(s,detailed=false) {
  const o=s.operations;
  if(!o) return '';
  const observed=o.observer||{}, src=o.source||{}, phases=o.acceptance||{};
  const regimes=observed.six_regimes||{}, sol=observed.solana||{}, rh=observed.robinhood_provider||{};
  const phaseRows=['CAPACITY','RECOVERY','AUTONOMY'].map(name=>{
    const r=phases[name]||{status:'UNAVAILABLE'}, previous=r.previous_attempt;
    return `<tr><td>${name}</td><td>${badge(r.status)}${previous?`<small>Previous source: ${esc(previous.status)} · ${seconds(previous.elapsed_seconds)} · ${esc(previous.commit)}</small>`:''}</td><td>${seconds(r.elapsed_seconds)}${r.required_seconds?` / ${seconds(r.required_seconds)}`:''}</td><td>${r.status==='PASS'&&r.verified_result?'PASS':r.status==='NOT_STARTED'?'No current-candidate result':esc(r.status)}</td></tr>`;
  }).join('');
  const statusRows=['Pump Current','Pump Survivor','Pons Current','Pons Survivor','Meteora','Ramses'].map(name=>{
    const r=regimes[name]||{}, paused=['Meteora','Ramses'].includes(name);
    const phase=o.paper_state==='STOPPED'?(paused?'PAUSED (PAPER stopped)':'STOPPED'):(r.phase||'UNAVAILABLE');
    const evidence=o.observer_state==='CURRENT'?(r.report_state||'UNAVAILABLE'):o.observer_state;
    return `<tr><td>${name}</td><td>${badge(phase)}</td><td>${badge(evidence)}${r.report_age_seconds!=null?`<small>Report age ${seconds(r.report_age_seconds)}</small>`:''}</td></tr>`;
  }).join('');
  const candidates=Object.entries(regimes).flatMap(([name,r])=>measuredRows(r.machinery).filter(([k])=>/candidate|qualif|evidence|completed steps|successful steps|processed events|completed windows/.test(k)).map(([k,v])=>[name+' · '+k,v]));
  const errors=(rh.usage||[]).filter(r=>r.metric.startsWith('failure:')||['responses_429','retries'].includes(r.metric));
  const usage=(rh.usage||[]).filter(r=>['physical_http_requests','logical_rpc_calls','completed_transport_attempts'].includes(r.metric));
  const providers=[
    ['Solana queue depth',observed.solana_provider?.queue_depth], ['Robinhood queue depth',rh.queue_depth],
    ['Solana rate errors',observed.solana_provider?.pressure?(observed.solana_provider.pressure).reduce((a,r)=>a+(r.rate_errors||0),0):undefined],
    ['Open evidence gaps',sol.repair_backlog?.open_gaps], ['Required evidence gaps',sol.repair_backlog?.required_gaps],
    ['Retained stream bytes',sol.counters?.stream_bytes],
    ...usage.map(r=>[`${r.lane} · ${title(r.metric)}`,r.value]), ...errors.map(r=>[`${r.lane} · ${title(r.metric)}`,r.value])
  ].filter(([,v])=>v!==undefined);
  const estimate=sol.repair_http?.estimated_alchemy;
  return `<section class="panel"><div class="panelhead"><h2>Operational reporting</h2>${badge(o.snapshot_state)}</div><div class="panelbody">
    <p>PAPER ${esc(o.paper_state)} · Snapshot ${esc(o.captured_at||'UNAVAILABLE')} · Observer ${esc(observed.at||'UNAVAILABLE')}</p>
    <p class="identity">Deployed PAPER: ${esc(src.deployed_commit||'UNAVAILABLE')}<br>Acceptance candidate: ${esc(src.candidate_commit||'UNAVAILABLE')}<br>Dashboard: ${esc(o.dashboard_commit||'UNAVAILABLE')}<br>Epoch: ${esc(src.epoch_id||'UNAVAILABLE')}</p>
    <p>Observer ${badge(o.observer_state)} · Monitor ${badge(o.monitor_state)} · Portfolio replay ${badge(o.portfolio_state)}</p>
    <div class="table-wrap"><table><thead><tr><th>Acceptance</th><th>Status</th><th>Elapsed / required</th><th>Result</th></tr></thead><tbody>${phaseRows}</tbody></table></div>
    <div class="table-wrap"><table><thead><tr><th>Strategy</th><th>Service status</th><th>Persisted evidence</th></tr></thead><tbody>${statusRows}</tbody></table></div>
    <p>${(o.alerts||[]).length?'Current alerts: '+o.alerts.map(a=>esc(title(typeof a==='string'?a:JSON.stringify(a)))).join(' · '):o.monitor_state==='CURRENT'?'No recorded health alerts':'Health alerts unavailable'}</p>
    <details ${detailed?'open':''}><summary>Discovery, qualification and evidence progress</summary><p>Recorded measures retain their original report age above. Missing measures are unavailable.</p>${observationsTable(candidates)}<p>Evidence heartbeat: ${sol.heartbeat?esc(new Date(sol.heartbeat*1000).toISOString()):'UNAVAILABLE'} · Coverage read: ${esc(sol.state||'UNAVAILABLE')}</p>${observationsTable(measuredRows(sol.all_frontiers))}</details>
    <details ${detailed?'open':''}><summary>Provider queues, errors, coverage and local usage</summary><p>Cumulative local counters, including historical activity; queue ${esc(observed.solana_provider?.state||'UNAVAILABLE')} / ${esc(rh.state||'UNAVAILABLE')}. They do not prove current market coverage.</p>${observationsTable(providers)}${estimate?`<p>Recorded Alchemy repair usage estimate: ${esc(estimate.known_estimated_cu)} known CU. Billing estimate only; unpriced methods remain unpriced.</p>${observationsTable(measuredRows(estimate.unpriced_methods))}`:'<p>Local CU estimate unavailable.</p>'}${observationsTable(measuredRows(sol.repair_http?.counters))}</details>
    ${detailed?Object.entries(phases).filter(([,r])=>r.results).map(([name,r])=>`<details><summary>${name} recorded results</summary>${observationsTable(measuredRows(r.results))}</details>`).join(''):''}
    </div></section>`;
}
async function overview(p) {
  const [lanes,chart,positions,trades,system,...laneCharts] = await Promise.all([
    api('lanes'),api('equity',{period:state.period,series:state.series}),api('positions',{limit:5}),api('trades',{limit:5}),api('system'),...LANES.map(l=>api('equity',{series:l,limit:60}))]);
  const charts=Object.fromEntries(LANES.map((l,i)=>[l,laneCharts[i]]));
  return `<div class="overview-page">${overviewAlerts(p)}${hero(p,chart)}${sharedCapital(p)}
    ${operationsPanel(system.data)}${laneCards(lanes.data,charts)}
    <div class="chart-row overview-charts">
      ${chartPanel(chart)}
      <section class="panel"><div class="panelhead"><h2>P&L by lane</h2></div><div class="panelbody">${laneDonut(lanes.data,p)}</div></section>
      <section class="panel"><div class="panelhead"><h2>Trade outcomes</h2></div><div class="panelbody">${laneBars(lanes.data,true)}</div></section>
    </div>
    <div class="tables overview-tables">${tablePanel('Recent trades',trades,true,'trades')}${tablePanel('Open positions',positions,false,'positions')}</div>
    ${overviewStatus(system.data,p)}
  </div>`;
}
async function lanePage(lane,p) {
  const [r,chart,positions,trades]=await Promise.all([api('lanes/'+lane),api('equity',{series:lane,period:state.period}),api('positions',{lane,limit:25}),api('trades',{lane,limit:10})]);
  const l=r.data,m=l.metrics;
  const metrics=[['Portfolio contribution','contribution_pct','percent'],['Realized net P&L','realized_pnl','money'],['Unrealized net P&L','unrealized_pnl','money'],['Trades taken','trades_taken','count'],['Completed trades','completed_trades','count'],['Open positions','open_positions','count'],['Winners','wins','count'],['Losses','losses','count'],['Breakevens','breakevens','count'],['Win rate','win_rate','percent'],['Deployed capital','deployed_capital','money'],['Fees / costs','fees','money'],['Average completed result','average_result','money'],['Largest winner','largest_winner','money'],['Largest loss','largest_loser','money'],['Average holding time','average_holding_seconds','seconds'],['Max drawdown','max_drawdown_pct','percent'],['Standalone lane return','lane_return_pct','percent']];
  return header(names[lane]+' lane',p)+`<section class="panel lane-hero ${lane}"><div class="panelhead"><div><p class="eyebrow">Net P&L / ${names[lane]}</p><div class="equity">${value(m.net_pnl,'money',true)}</div><p class="sample-count">${m.completed_trades.value??'Unknown'} completed trades · ${m.open_positions.value??'Unknown'} open · ${m.wins.value??'?'} wins / ${m.losses.value??'?'} losses / ${m.breakevens.value??'?'} breakevens</p></div>${badge(l.health.operational.state,l.health.operational.value)}</div><div class="metric-grid">${metrics.map(([label,key,kind])=>stat(label,m[key],kind,['realized_pnl','unrealized_pnl','contribution_pct'].includes(key))).join('')}</div></section><div class="detail-chart">${chartPanel(chart,false)}</div><div class="tables">${tablePanel('Open exposure',positions,false,'positions')}${tablePanel('Recent completed trades',trades,true,'trades')}</div>${healthPanel(lane,l.health)}`;
}
function healthPanel(lane,h) {
  return `<section class="panel ${lane}"><div class="panelhead"><h2 class="lane-label">${names[lane]}</h2>${badge(h.operational.state,h.operational.value)}</div><div class="panelbody"><div class="health-row"><span>Native accounting reconciliation</span>${badge(h.accounting.state,h.accounting.value===true?'RECONCILED':h.accounting.value===false?'MISMATCH':undefined)}</div><div class="health-row"><span>Evidence freshness</span>${badge(h.evidence.state)}</div><div class="health-row"><span>Progress age</span><span>${value(h.progress_age_seconds,'seconds')}</span></div><div class="health-row"><span>Persisted provider request count</span><span>${value(h.provider_requests,'count')}</span></div><p class="status-notice">A responsive process does not prove fresh evidence. Native campaign telemetry is separate from the new USD portfolio.</p>${nativePanel(h.native_accounting)}<details><summary>Source / policy / configuration identities</summary><p class="status-notice">Runtime-observed identities</p>${identityRows(h.runtime_identities)}<p class="status-notice">Configured source map (not proof of execution)</p>${identityRows(h.configured_identities)}</details></div></section>`;
}
function nativePanel(data) {
  if(!data) return '<p class="status-notice">Native book balances unavailable.</p>';
  const rows=Object.entries(data).filter(([,v])=>typeof v==='string').map(([k,v])=>`<div class="identity"><span class="muted">${esc(title(k))}</span> ${esc(v)}</div>`).join('');
  const sleeves=Object.entries(data.by_quote_asset||{}).map(([asset,values])=>`<div class="identity">${esc(asset)}</div>${Object.entries(values).map(([k,v])=>`<div class="identity">${esc(title(k))}: ${esc(v)}</div>`).join('')}`).join('');
  return `<details><summary>Persisted native book (not USD portfolio)</summary><p class="status-notice">Integer native quote units. Historical campaign balances are excluded from portfolio equity.</p>${rows}${sleeves}</details>`;
}
function identityRows(ids) {return Object.entries(ids).map(([k,v])=>`<div class="identity"><span class="muted">${esc(title(k))}</span><br>${esc(v||'Unavailable')}</div>`).join('');}
async function historyPage(completed,p) {
  const route=completed?'trades':'positions';
  const res=await api(route,{...state.filters,offset:state.offset,limit:25});
  const f=state.filters;
  return header(completed?'Trade history':'Open positions',p)+`<form class="filters" id="filters"><input type="search" name="q" aria-label="Search asset, pool or position" placeholder="Search asset, pool, position…" value="${esc(f.q||'')}"><select name="lane" aria-label="Filter lane"><option value="">All lanes</option>${LANES.map(l=>`<option value="${l}" ${f.lane===l?'selected':''}>${names[l]}</option>`).join('')}</select>${completed?`<select name="outcome" aria-label="Filter outcome"><option value="">All outcomes</option>${['winner','loser','breakeven'].map(o=>`<option ${f.outcome===o?'selected':''}>${o}</option>`).join('')}</select><input name="strategy" aria-label="Strategy or source identity" placeholder="Strategy / source SHA" value="${esc(f.strategy||'')}"><label>From <input type="date" name="from" value="${esc((f.from||'').slice(0,10))}"></label><label>To <input type="date" name="to" value="${esc((f.to||'').slice(0,10))}"></label>`:''}<button type="submit">Apply filters</button></form><section class="panel">${res.total===null?empty('Canonical position state unavailable'):positionsTable(res.data,completed)}<div class="pagination"><span>${res.total===null?'Unknown total':`${res.total} matching lifecycles · ${res.total?res.offset+1:0}–${res.offset+res.data.length}`} · snapshot ${date(res.as_of)}</span><span><button data-page="${Math.max(0,state.offset-25)}" ${state.offset===0?'disabled':''}>Previous</button> <button data-page="${res.next_offset??0}" ${res.next_offset===null?'disabled':''}>Next</button></span></div></section>`;
}
async function analytics(p) {
  const [lanes,chart,daily]=await Promise.all([api('lanes'),api('equity',{series:state.series,period:state.period}),api('analytics')]);
  const dailyTable=(pnl)=>daily.data.length?`<div class="table-wrap"><table><thead><tr><th>UTC day</th><th>${pnl?'Completed net P&L':'Entries'}</th><th>Settlements</th></tr></thead><tbody>${daily.data.map(d=>`<tr><td>${esc(d.day)}</td><td>${pnl?value({value:d.completed_net_pnl,state:p.state},'money',true):d.entries}</td><td>${d.settlements}</td></tr>`).join('')}</tbody></table></div>`:empty('Recorded daily lifecycle data unavailable');
  return header('Portfolio analytics',p)+`<p class="status-notice">Coverage: ${p.metrics.completed_trades.value??'unknown'} completed lifecycles. No statistical significance, ranking or strategy selection is inferred.</p><div class="chart-row">${chartPanel(chart)}<section class="panel"><div class="panelhead"><h2>Cumulative lane contribution</h2></div><div class="panelbody">${laneBars(lanes.data)}${stat('Unallocated / shared costs',p.metrics.shared_costs)}</div></section><section class="panel"><div class="panelhead"><h2>Wins / losses</h2></div><div class="panelbody">${laneBars(lanes.data,true)}</div></section></div><div class="panel metric-grid">${stat('Realized net P&L',p.metrics.realized_pnl,'money',true)}${stat('Unrealized net P&L',p.metrics.unrealized_pnl,'money',true)}${stat('Portfolio drawdown',p.metrics.max_drawdown_pct,'percent')}${stat('Completed sample',p.metrics.completed_trades,'count')}${stat('Breakevens',p.metrics.breakevens,'count')}${stat('Win rate',p.metrics.win_rate,'percent')}</div><div class="daily"><section class="panel"><div class="panelhead"><h2>Completed P&L by settlement day</h2></div>${dailyTable(true)}<div class="panelbody"><p class="status-notice">Full lifecycle net outcomes on terminal settlement day. Excludes open partial realizations and shared costs. Daily equity change is unavailable.</p></div></section><section class="panel"><div class="panelhead"><h2>Daily trade frequency</h2></div>${dailyTable(false)}<div class="panelbody"><p class="status-notice">${esc(daily.coverage)}. Showing up to 31 observed days.</p></div></section></div>`;
}
async function systemPage(p) {
  const s=(await api('system')).data;
  return header('System & evidence',p)+operationsPanel(s,true)+systemStrip(s)+`<p class="status-notice">Telemetry snapshot: ${date(s.observed_at)}. Polling reads local persisted state only. Each lane retains its own operational and evidence status.</p><div class="system-grid">${LANES.map(l=>healthPanel(l,s.lanes[l])).join('')}</div><section class="panel detail-chart"><div class="panelhead"><h2>Portfolio reconciliation</h2>${badge(p.reconciliation.state)}</div><div class="panelbody">${p.reconciliation.value?Object.entries(p.reconciliation.value).map(([k,v])=>`<div class="health-row"><span>${esc(title(k))}</span>${badge(v?'CURRENT':'FAIL_CLOSED',v?'MATCH':'MISMATCH')}</div>`).join(''):empty('No canonical USD account connected')}<details><summary>Portfolio inception and source</summary><div class="identity">${p.epoch?esc(p.epoch.epoch_id)+'<br>'+esc(p.epoch.inception_at)+'<br>'+esc(p.epoch.canonical_event_id):'NOT INITIALIZED'}</div>${p.identities?identityRows(p.identities):''}</details></div></section>`;
}
async function showPosition(id) {
  try {
    const p=(await api('positions/'+encodeURIComponent(id))).data;
    document.querySelector('#detail-content').innerHTML=`<p class="eyebrow">Canonical paper position / ${names[p.lane]}</p><h1>${esc(p.asset)}</h1><div class="identity">${esc(p.id)}</div><p class="sample-count">One lifecycle · ${esc(p.state)} · ${esc(p.outcome||'remaining active exposure')}</p><div class="detail-metrics">${stat('Entry reference',{value:p.entry_value,state:'CURRENT'})}${stat('Exit reference',{value:p.exit_value,state:'CURRENT'})}${stat('Current value',p.current_value)}${stat('Capital used',{value:p.capital,state:'CURRENT'})}${stat('Remaining basis',{value:p.remaining_basis,state:'CURRENT'})}${stat('Realized net P&L',{value:p.realized_pnl,state:'CURRENT'},'money',true)}${stat('Gross realized result',{value:p.gross_result,state:'CURRENT'},'money',true)}${stat('Fees / costs',{value:p.fees,state:'CURRENT'})}${stat('Unrealized P&L',p.unrealized_pnl,'money',true)}</div><p class="status-notice">Entry ${date(p.entered_at)} · Settlement ${date(p.settled_at)}<br>Exit reason: ${esc(p.exit_reason||'Unavailable')}</p>${['harvest_state','runner_state','remaining_runner_exposure','range_id','lp_state','in_range','rebalance_state','rebalance_count'].filter(k=>p[k]!=null).map(k=>`<div class="health-row"><span>${esc(title(k))}</span><span>${esc(p[k])}</span></div>`).join('')}<h2>Recorded lifecycle</h2>${p.lifecycle.length?`<ol class="timeline">${p.lifecycle.map(e=>`<li>${esc(title(e.stage))}<time>${date(e.at)}</time></li>`).join('')}</ol>`:empty('No lifecycle stages supplied')}<h2>Source identity</h2><p class="status-notice">${esc(p.strategy_id||'Strategy unavailable')}</p>${identityRows(p.identities)}`;
    document.querySelector('#detail').showModal();
  } catch { document.querySelector('#detail-content').textContent='Position details unavailable.'; document.querySelector('#detail').showModal(); }
}
function syncTopbar(p) {
  const indicator=document.querySelector('#live-indicator');
  const updated=document.querySelector('#last-update');
  if(indicator) {
    const label=p.mode==='fixture'?'FIXTURE (Paper)':p.snapshot_state&&p.snapshot_state!=='CURRENT'?`PAPER · ${title(p.snapshot_state)}`:p.paper_state==='STOPPED'?'PAPER · STOPPED':p.paper_state==='UNAVAILABLE'?'PAPER · UNAVAILABLE':p.state==='CURRENT'?'LIVE (Paper)':`PAPER · ${title(p.state)}`;
    indicator.textContent=label;
    indicator.className='live-indicator '+(p.state==='CURRENT'&&p.mode!=='fixture'&&(!p.paper_state||p.paper_state==='RUNNING')&&(!p.snapshot_state||p.snapshot_state==='CURRENT')?'is-live':p.state==='FAIL_CLOSED'?'is-error':'is-caution');
  }
  const at=p.snapshot_at||p.as_of;
  if(updated) updated.textContent=at?new Date(at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Unavailable';
}
function bind() {
  document.querySelectorAll('[data-period]').forEach(b=>b.addEventListener('click',()=>{state.period=b.dataset.period;render();}));
  document.querySelector('#series')?.addEventListener('change',e=>{state.series=e.target.value;render();});
  document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>{state.offset=Number(b.dataset.page);render();}));
  document.querySelectorAll('[data-position]').forEach(b=>b.addEventListener('click',()=>showPosition(b.dataset.position)));
  document.querySelector('#filters')?.addEventListener('submit',event=>{
    event.preventDefault(); state.filters=Object.fromEntries(new FormData(event.target));
    for(const key of ['from','to']) if(state.filters[key]) state.filters[key]+=(key==='from'?'T00:00:00Z':'T23:59:59Z');
    state.offset=0;render();
  });
}
async function render() {
  const generation=++state.generation;
  state.busy=true;
  const route=location.hash.slice(1)||'overview';
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.hash==='#'+(route.startsWith('lane/')?'lanes':route)));
  try {
    const p=(await api('portfolio')).data;
    syncTopbar(p);
    let html;
    if(route==='overview') html=await overview(p);
    else if(route==='lanes') html=header('Four paper lanes',p)+laneCards((await api('lanes')).data)+`<a class="link" href="#analytics">Portfolio analytics →</a>`;
    else if(route.startsWith('lane/')&&LANES.includes(route.slice(5))) html=await lanePage(route.slice(5),p);
    else if(route==='positions'||route==='trades') html=await historyPage(route==='trades',p);
    else if(route==='analytics') html=await analytics(p);
    else if(route==='system') html=await systemPage(p);
    else html=empty('Page not found');
    if(generation===state.generation){main.innerHTML=html;state.lastPortfolio=p;bind();}
  } catch {
    if(generation===state.generation) {
      syncTopbar({...state.lastPortfolio,state:'STALE',snapshot_state:'UNAVAILABLE'});
      const warning='<div id="unavailable-banner" class="banner error"><strong>Dashboard UNAVAILABLE.</strong> Last displayed observations are STALE.</div>';
      if(state.lastPortfolio) { if(!document.querySelector('#unavailable-banner'))main.insertAdjacentHTML('afterbegin',warning); }
      else main.innerHTML=warning+'<button id="retry">Retry read</button>';
    }
    document.querySelector('#retry')?.addEventListener('click',render);
  } finally { if(generation===state.generation) state.busy=false; }
}
document.querySelector('#close-detail').addEventListener('click',()=>document.querySelector('#detail').close());
window.addEventListener('hashchange',()=>{state.offset=0;state.filters={};state.period='ALL';render();});
setInterval(()=>{if(!document.hidden&&!state.busy&&!document.querySelector('#detail').open&&!['INPUT','SELECT'].includes(document.activeElement.tagName))render();},15000);
render();
