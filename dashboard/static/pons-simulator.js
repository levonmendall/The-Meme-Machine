(() => {
  'use strict';

  const LABEL = 'EXPERIMENTAL PONS CURRENT — SIMULATED TRADING — NO REAL MONEY';
  const CURRENT_SECONDS = 60;
  const POLL_MS = 30000;
  const UNAVAILABLE = 'UNAVAILABLE';
  const baselineStrategy = {
    version: 'baseline-909738760e6f722b',
    policy_revision: 'paper-postgrad-rally-v1',
    policy_sha256: '909738760e6f722b8668a99493f698c3a415867f77f08199a61b0fb047381be7',
    adaptation_state: 'BASELINE_UNCHANGED'
  };
  const qualityNames = {MEASURED: 'Measured', ESTIMATED: 'Estimated', UNAVAILABLE: 'Unavailable'};
  const units = new Set(['USD', 'COUNT', 'PERCENT', 'SECONDS', 'MILLISECONDS', 'BYTES', 'TOKENS', 'PER_HOUR']);
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
  const metricGroups = {
    financial: [
      ['financial', 'starting_capital', 'Starting simulated capital'],
      ['financial', 'cash', 'Available simulated cash'],
      ['financial', 'equity', 'Marked simulated equity'],
      ['financial', 'reserved', 'Reserved capital'],
      ['financial', 'deployed', 'Deployed capital'],
      ['financial', 'realized_pnl', 'Realized P&L'],
      ['financial', 'unrealized_pnl', 'Unrealized P&L'],
      ['financial', 'gross_pnl', 'Gross P&L'],
      ['financial', 'net_pnl', 'Net P&L'],
      ['financial', 'net_return_pct', 'Net return'],
      ['financial', 'fees', 'Simulated trading fees'],
      ['financial', 'slippage', 'Simulated slippage cost'],
      ['financial', 'drawdown_pct', 'Drawdown'],
      ['financial', 'open_exposure', 'Open exposure']
    ],
    activity: [
      ['strategy', 'eligible', 'Qualifying opportunities'],
      ['activity', 'entries', 'Simulated entries'],
      ['activity', 'partial_exits', 'Partial exits'],
      ['activity', 'exits', 'Complete exits'],
      ['activity', 'round_trips', 'Completed round trips'],
      ['activity', 'open_positions', 'Open positions'],
      ['activity', 'winners', 'Winners'],
      ['activity', 'losers', 'Losers'],
      ['strategy', 'rejected', 'Rejected opportunities']
    ],
    strategy: [
      ['strategy', 'manager_decisions', 'Codex candidate reviews'],
      ['strategy', 'manager_rejections', 'Codex safety rejections'],
      ['strategy', 'evaluated', 'Complete native strategy evaluations'],
      ['strategy', 'volume_quality_passes', 'Volume-quality passes'],
      ['financial', 'win_rate_pct', 'Realized win rate'],
      ['financial', 'average_profit', 'Average realized profit'],
      ['financial', 'average_loss', 'Average realized loss'],
      ['activity', 'average_hold_seconds', 'Average holding duration'],
      ['activity', 'trade_frequency_per_hour', 'Trading frequency']
    ],
    operational: [
      ['operational', 'connected', 'Provider connectivity'],
      ['activity', 'pairs_seen', 'Market pairs observed'],
      ['activity', 'events_seen', 'Received curve-topic events (lineage may be unverified)'],
      ['activity', 'launch_events', 'Received launch events'],
      ['activity', 'events_processed', 'Durable economic events'],
      ['activity', 'queue_depth', 'Pending native candidates'],
      ['activity', 'sampled_block_debt', 'Sampled block debt (event backlog unknown)'],
      ['operational', 'range_processing_ms', 'Last completed range processing time'],
      ['operational', 'processing_latency_ms', 'Processing latency'],
      ['operational', 'heartbeat_age_seconds', 'Source heartbeat age'],
      ['activity', 'duplicates', 'Duplicate events'],
      ['activity', 'gaps', 'Evidence gaps'],
      ['activity', 'dropped_events', 'Dropped evidence'],
      ['activity', 'recovered_events', 'Recovered evidence'],
      ['activity', 'unrecovered_events', 'Unrecovered evidence'],
      ['operational', 'provider_requests', 'Provider requests'],
      ['operational', 'provider_failures', 'Provider failures'],
      ['operational', 'cpu_seconds', 'Runtime CPU'],
      ['operational', 'memory_bytes', 'Runtime memory']
    ]
  };
  let snapshot = null;
  let fetchedAt = null;
  let requestFailed = false;
  let failureReason = '';
  let inflight = false;
  const metricNodes = [];
  const byId = id => document.getElementById(id);
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const validTime = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
  const timestamp = value => validTime(value) ? new Date(value).toISOString().replace('T', ' ').replace('.000Z', 'Z').replace('Z', ' UTC') : UNAVAILABLE;
  const age = value => validTime(value) ? (Date.now() - Date.parse(value)) / 1000 : null;
  const ageText = seconds => seconds === null ? UNAVAILABLE : seconds < 0 ? 'Future timestamp' : `${Math.floor(seconds).toLocaleString()} s`;
  const boundedText = (value, limit = 200) => typeof value === 'string' ? value.slice(0, limit) : UNAVAILABLE;
  const reasonText = reasons => Array.isArray(reasons) && reasons.length ? reasons.slice(0, 40).map(value => boundedText(value, 100)).join(' · ') : 'No reason codes reported.';

  function numberText(value) {
    const parts = value.replace(/^\+/, '').split('.');
    const negative = parts[0].startsWith('-');
    const integer = (parts[0].replace('-', '') || '0').replace(/^0+(?=\d)/, '');
    const fraction = (parts[1] || '').replace(/0+$/, '');
    return `${negative ? '−' : ''}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`;
  }

  function metricValid(metric) {
    return metric && typeof metric === 'object' && metric.quality !== UNAVAILABLE &&
      Object.hasOwn(qualityNames, metric.quality) && typeof metric.value === 'string' &&
      metric.value.length <= 100 && decimal.test(metric.value) && units.has(metric.unit);
  }

  function metricText(metric, connected = false) {
    if (!metricValid(metric)) return UNAVAILABLE;
    if (connected) {
      if (metric.value === '1') return 'CONNECTED';
      if (metric.value === '0') return 'DISCONNECTED';
      return UNAVAILABLE;
    }
    const value = numberText(metric.value);
    const suffix = {COUNT: '', PERCENT: '%', SECONDS: ' s', MILLISECONDS: ' ms', BYTES: ' bytes', TOKENS: ' tokens', PER_HOUR: '/hour'};
    return metric.unit === 'USD' ? value.startsWith('−') ? `−$${value.slice(1)}` : `$${value}` : `${value}${suffix[metric.unit]}`;
  }

  function metricState(metric) {
    if (!metricValid(metric) || !validTime(metric.as_of)) return UNAVAILABLE;
    const seconds = age(metric.as_of);
    if (metric.state === 'STALE' || metric.state === UNAVAILABLE || seconds < 0 || seconds > CURRENT_SECONDS || feedState() !== 'CURRENT') return 'STALE';
    return 'CURRENT';
  }

  function metricCard(label, metric, connected = false) {
    const card = element('div', 'sim-metric');
    const title = element('div', 'sim-metric-label', label);
    const value = element('div', 'sim-metric-value', metricText(metric, connected));
    const quality = element('div', 'sim-metric-quality');
    const asof = element('div', 'sim-metric-asof');
    card.append(title, value, quality, asof);
    metricNodes.push({metric, value, quality, asof});
    return card;
  }

  function renderMetrics() {
    metricNodes.length = 0;
    for (const [group, fields] of Object.entries(metricGroups)) {
      byId(`sim-${group}`).replaceChildren(...fields.map(([source, key, label]) => metricCard(label, snapshot?.metrics?.[source]?.[key], key === 'connected')));
    }
  }

  function feedState() {
    if (!snapshot || snapshot.state === UNAVAILABLE) return UNAVAILABLE;
    const seconds = age(snapshot.captured_at);
    if (requestFailed || snapshot.state !== 'CURRENT' || seconds === null || seconds < 0 || seconds > CURRENT_SECONDS) return 'STALE';
    return 'CURRENT';
  }

  function updateFreshness() {
    const state = feedState();
    byId('sim-main').dataset.feedState = state;
    byId('sim-feed-state').dataset.state = state;
    byId('sim-feed-state').textContent = state;
    byId('sim-age').textContent = ageText(age(snapshot?.captured_at));
    let message = 'Waiting for an authenticated experiment snapshot.';
    if (snapshot && state === UNAVAILABLE) message = 'Experiment data is unavailable. No current operation is established.';
    if (snapshot && state === 'CURRENT') message = snapshot.execution_state === 'RUNNING' ? 'Fresh report; the experiment reports RUNNING.' : `Fresh report; reported execution is ${snapshot.execution_state}.`;
    if (state === 'STALE') message = 'Last reported values are stale. Current operation and protection are unverified.';
    if (requestFailed) message = `${snapshot ? 'Last reported values are stale. ' : ''}${failureReason} Current operation is unverified.`;
    byId('sim-feed-detail').textContent = message;
    updateObserverFreshness();
    for (const item of metricNodes) {
      const metric = item.metric;
      const quality = metricValid(metric) ? metric.quality : UNAVAILABLE;
      const metricFreshness = metricState(metric);
      item.value.dataset.quality = quality;
      item.value.dataset.state = metricFreshness;
      item.quality.dataset.quality = quality;
      item.quality.dataset.state = metricFreshness;
      item.quality.textContent = `${metricFreshness === 'STALE' ? 'STALE · ' : ''}${qualityNames[quality]}${quality === 'ESTIMATED' ? ' · not a confirmed observation' : ''}`;
      item.asof.textContent = validTime(metric?.as_of) ? `As of ${timestamp(metric.as_of)}` : 'Measurement time unavailable';
    }
  }

  function addDefinition(list, label, value) {
    const row = element('div');
    row.append(element('dt', '', label), element('dd', '', value));
    list.append(row);
  }

  function renderLifecycles() {
    const container = byId('sim-lifecycles');
    if (!snapshot || snapshot.state === UNAVAILABLE || !Array.isArray(snapshot.lifecycles)) {
      container.replaceChildren(element('p', 'sim-empty', 'Lifecycle history unavailable.'));
      byId('sim-lifecycle-count').textContent = UNAVAILABLE;
      return;
    }
    const rows = snapshot.lifecycles.filter(row => row && typeof row === 'object').slice(0, 100);
    byId('sim-lifecycle-count').textContent = `${rows.length.toLocaleString()} reported lifecycle${rows.length === 1 ? '' : 's'}`;
    if (!rows.length) {
      container.replaceChildren(element('p', 'sim-empty', 'No position lifecycles recorded in this snapshot. No trades are inferred.'));
      return;
    }
    container.replaceChildren(...rows.map(row => {
      const card = element('article', 'sim-lifecycle');
      const header = element('div', 'sim-lifecycle-header');
      header.append(element('h3', '', `Asset ${boundedText(row.asset_id, 64)}`), element('span', 'sim-badge', boundedText(row.state, 20)));
      const timeline = element('div', 'sim-timeline');
      for (const [label, field] of [['Entry', 'entered_at'], ['Updated', 'updated_at'], ['Settled', 'settled_at']]) timeline.append(element('span', '', `${label}: ${timestamp(row[field])}`));
      const metrics = element('div', 'sim-metric-grid');
      for (const [key, label] of [['entry_price', 'Entry price'], ['mark_price', 'Mark price'], ['quantity', 'Entry quantity'], ['remaining_quantity', 'Remaining quantity'], ['realized_pnl', 'Realized P&L'], ['unrealized_pnl', 'Unrealized P&L'], ['fees', 'Trading fees'], ['slippage', 'Slippage cost']]) metrics.append(metricCard(label, row.metrics?.[key]));
      const details = element('details');
      details.append(element('summary', '', 'Evidence and simulated execution assumptions'));
      const definitions = element('dl');
      addDefinition(definitions, 'Lifecycle identity', boundedText(row.lifecycle_id, 64));
      addDefinition(definitions, 'Entry market evidence', 'UNAVAILABLE in this dashboard payload.');
      addDefinition(definitions, 'Liquidity, price impact, and fill assumptions', 'UNAVAILABLE in this dashboard payload. Simulated prices are not guaranteed fills.');
      addDefinition(definitions, 'Fee breakdown', 'Only the reported aggregate fee metric is available; individual fee components are UNAVAILABLE.');
      addDefinition(definitions, 'Reported decision / exit reasons', reasonText(row.reason_codes));
      details.append(definitions);
      card.append(header, timeline, metrics, details);
      return card;
    }));
  }

  function historyCoverage(history) {
    if (!history || !Array.isArray(history.rows)) return 'History coverage unavailable.';
    const total = Number.isSafeInteger(history.total) && history.total >= 0 ? history.total.toLocaleString() : 'unknown total';
    const shown = Math.min(history.rows.length, 100);
    return `Showing ${shown.toLocaleString()} of ${history.rows.length.toLocaleString()} reported rows · ${total} total · ${history.complete === true ? 'source reports complete coverage' : 'INCOMPLETE or unverified coverage'}.`;
  }

  function table(headers, caption) {
    const tableNode = element('table');
    tableNode.append(element('caption', '', caption));
    const head = element('thead');
    const row = element('tr');
    for (const label of headers) {
      const cell = element('th', '', label);
      cell.scope = 'col';
      row.append(cell);
    }
    head.append(row);
    const body = element('tbody');
    tableNode.append(head, body);
    return {tableNode, body};
  }

  function updateObserverFreshness() {
    const observer = snapshot?.observer;
    const heartbeatAge = age(observer?.heartbeat_at);
    const marketAge = age(observer?.market_as_of);
    const fresh = feedState() === 'CURRENT' && heartbeatAge !== null && heartbeatAge >= 0 &&
      heartbeatAge <= CURRENT_SECONDS && marketAge !== null && marketAge >= 0 && marketAge <= CURRENT_SECONDS;
    byId('sim-observer-status').textContent = !observer ? UNAVAILABLE :
      !fresh ? 'STALE / MARKET UNAVAILABLE' : `${boundedText(observer.status, 20)} — READ ONLY`;
    byId('sim-observer-detail').textContent = !observer ? 'No resident observer evidence received.' :
      `Heartbeat ${timestamp(observer.heartbeat_at)} · market evidence ${timestamp(observer.market_as_of)} · ` +
      `reported process restarts ${Number.isSafeInteger(observer.restart_count) ? observer.restart_count : UNAVAILABLE} · ` +
      `history coverage ${boundedText(observer.history_coverage, 20)}. Source ${boundedText(observer.source_commit, 40)}.`;
  }

  function renderObserver() {
    const observer = snapshot?.observer;
    if (!observer) {
      byId('sim-observer-counts').replaceChildren(element('p', 'sim-empty', 'Current and Survivor evaluation counts unavailable.'));
      byId('sim-observer-decisions').replaceChildren(element('p', 'sim-empty', 'No verified shadow decisions received.'));
      return;
    }
    const counts = table(['Strategy', 'Completed native evaluations', 'Eligible', 'WAIT', 'REJECT', 'Incomplete'], 'Read-only strategy evaluations; unknown counts remain unavailable');
    for (const [key, name] of [['current', 'Pons Current'], ['survivor', 'Pons Survivor']]) {
      const row = element('tr');
      row.append(element('th', '', name));
      for (const field of ['completed', 'eligible', 'wait', 'rejected', 'incomplete']) {
        const count = observer[key]?.[field];
        row.append(element('td', '', Number.isSafeInteger(count) && count >= 0 ? count.toLocaleString() : UNAVAILABLE));
      }
      counts.body.append(row);
    }
    byId('sim-observer-counts').replaceChildren(counts.tableNode);
    if (!Array.isArray(observer.decisions) || !observer.decisions.length) {
      byId('sim-observer-decisions').replaceChildren(element('p', 'sim-empty', 'No shadow decision records reported. No trades are inferred.'));
      return;
    }
    const decisions = table(['Time (UTC)', 'Strategy', 'Shadow action', 'Qualification', 'Reason / evidence'], 'Latest read-only shadow decisions; never PAPER fills');
    for (const decision of observer.decisions.slice(-64).reverse()) {
      const row = element('tr');
      const reason = element('td', '', boundedText(decision.reason, 128));
      reason.append(element('span', 'sim-cell-detail', `Evidence ${boundedText(decision.evidence_sha256, 64)}`));
      row.append(element('td', '', timestamp(decision.at)), element('td', '', boundedText(decision.strategy, 20)),
        element('td', '', boundedText(decision.action, 20)), element('td', '', boundedText(decision.qualification, 20)), reason);
      decisions.body.append(row);
    }
    byId('sim-observer-decisions').replaceChildren(decisions.tableNode);
  }

  function renderHistory() {
    const events = snapshot?.state === UNAVAILABLE ? null : snapshot?.history?.events;
    const equity = snapshot?.state === UNAVAILABLE ? null : snapshot?.history?.equity;
    byId('sim-events-coverage').textContent = historyCoverage(events);
    byId('sim-equity-coverage').textContent = historyCoverage(equity);
    if (!events || !Array.isArray(events.rows)) byId('sim-events').replaceChildren(element('p', 'sim-empty', 'Decision history unavailable.'));
    else if (!events.rows.length) byId('sim-events').replaceChildren(element('p', 'sim-empty', 'No decision or execution events reported.'));
    else {
      const {tableNode, body} = table(['Time (UTC)', 'Event', 'Decision / reason'], 'Reported simulator decision and execution events');
      for (const item of events.rows.filter(row => row && typeof row === 'object').slice(-100).reverse()) {
        const row = element('tr');
        const kind = element('td', '', boundedText(item.kind, 30));
        kind.append(element('span', 'sim-cell-detail', `Event ${boundedText(item.event_id, 64)}`));
        const reason = element('td', '', boundedText(item.reason_code, 100));
        if (item.lifecycle_id) reason.append(element('span', 'sim-cell-detail', `Lifecycle ${boundedText(item.lifecycle_id, 64)}`));
        row.append(element('td', '', timestamp(item.at)), kind, reason);
        body.append(row);
      }
      byId('sim-events').replaceChildren(tableNode);
    }
    if (!equity || !Array.isArray(equity.rows)) byId('sim-equity').replaceChildren(element('p', 'sim-empty', 'Equity history unavailable.'));
    else if (!equity.rows.length) byId('sim-equity').replaceChildren(element('p', 'sim-empty', 'No equity history reported.'));
    else {
      const {tableNode, body} = table(['Time (UTC)', 'Simulated equity', 'Evidence quality'], 'Reported historical simulated equity');
      for (const item of equity.rows.filter(row => row && typeof row === 'object').slice(-100).reverse()) {
        const row = element('tr');
        row.append(element('td', '', timestamp(item.at)), element('td', '', metricText(item.equity)), element('td', '', qualityNames[item.equity?.quality] || 'Unavailable'));
        body.append(row);
      }
      byId('sim-equity').replaceChildren(tableNode);
    }
  }

  function render() {
    byId('sim-execution').textContent = snapshot?.execution_state || 'UNKNOWN';
    byId('sim-captured').textContent = timestamp(snapshot?.captured_at);
    byId('sim-sequence').textContent = snapshot && Number.isSafeInteger(snapshot.sequence) ? snapshot.sequence.toLocaleString() : UNAVAILABLE;
    byId('sim-fetched').textContent = timestamp(fetchedAt);
    byId('sim-reasons').textContent = snapshot ? reasonText(snapshot.reason_codes) : 'No experiment data received.';
    byId('sim-experiment').textContent = boundedText(snapshot?.identity?.experiment_id, 128);
    byId('sim-epoch').textContent = boundedText(snapshot?.identity?.epoch_id, 128);
    byId('sim-source').textContent = boundedText(snapshot?.identity?.source_commit, 40);
    byId('sim-inception').textContent = boundedText(snapshot?.identity?.inception_sha256, 64);
    const strategy = snapshot?.strategy_version;
    byId('sim-strategy-version').textContent = boundedText(strategy?.version, 64);
    byId('sim-policy-revision').textContent = boundedText(strategy?.policy_revision, 96);
    byId('sim-policy-hash').textContent = boundedText(strategy?.policy_sha256, 64);
    byId('sim-adaptation-state').textContent = {
      BASELINE_UNCHANGED: 'BASELINE UNCHANGED — no strategy changes reported',
      EXPERIMENTAL: 'EXPERIMENTAL — strategy changes reported',
      REVERTED: 'REVERTED — reported strategy version restored'
    }[strategy?.adaptation_state] || UNAVAILABLE;
    byId('sim-persistence').textContent = boundedText(snapshot?.persistence, 50);
    byId('sim-persistence-detail').textContent = snapshot?.source_ledger_authoritative === false
      ? 'This read-only observer has no financial ledger access or execution authority. Any retained financial statement keeps its original verification timestamp. Observer history is maintained at the source; this dashboard is not its durable archive.'
      : snapshot?.persistence === 'EPHEMERAL_UNVERIFIED'
      ? 'Dashboard storage is ephemeral or unverified. Do not rely on this service as the historical archive. The experimental source ledger, not this dashboard, owns financial records; durable recovery must be verified separately.'
      : 'Historical persistence has not been independently verified by this view. The dashboard never owns trading or financial authority.';
    renderMetrics();
    renderLifecycles();
    renderHistory();
    renderObserver();
    updateFreshness();
  }

  function validate(payload) {
    if (!payload || payload.schema !== 'pons-simulator-view-v1' || payload.label !== LABEL ||
        !['CURRENT', 'STALE', UNAVAILABLE].includes(payload.state) ||
        !['RUNNING', 'STOPPED', 'FAILED', 'UNKNOWN'].includes(payload.execution_state)) throw new Error('Invalid simulator response');
    if (payload.strategy_version !== undefined && payload.strategy_version !== null) {
      const strategy = payload.strategy_version;
      if (typeof strategy !== 'object' || Array.isArray(strategy) || Object.keys(strategy).length !== 4 ||
          !Object.keys(baselineStrategy).every(key => Object.hasOwn(strategy, key)) ||
          typeof strategy.version !== 'string' || strategy.version.match(/^[a-z0-9][a-z0-9._-]{0,63}$/)?.[0] !== strategy.version ||
          typeof strategy.policy_revision !== 'string' || strategy.policy_revision.match(/^[a-z0-9][a-z0-9._-]{0,95}$/)?.[0] !== strategy.policy_revision ||
          typeof strategy.policy_sha256 !== 'string' || strategy.policy_sha256.match(/^[a-f0-9]{64}$/)?.[0] !== strategy.policy_sha256 ||
          !['BASELINE_UNCHANGED', 'EXPERIMENTAL', 'REVERTED'].includes(strategy.adaptation_state) ||
          (strategy.adaptation_state === 'BASELINE_UNCHANGED' &&
            !Object.entries(baselineStrategy).every(([key, value]) => strategy[key] === value))) throw new Error('Invalid simulator strategy version');
    }
    if (payload.state !== UNAVAILABLE && (!validTime(payload.captured_at) || !Number.isSafeInteger(payload.sequence) || payload.sequence < 1 ||
        typeof payload.identity?.experiment_id !== 'string' || !payload.identity.experiment_id || payload.identity.experiment_id.length > 128 ||
        !/^paper-pons-simulator-1000-[0-9]{8}$/.test(payload.identity.epoch_id || '') ||
        !/^[a-f0-9]{40}$/.test(payload.identity.source_commit || '') || !/^[a-f0-9]{64}$/.test(payload.identity.inception_sha256 || ''))) throw new Error('Invalid simulator identity');
    if (snapshot?.identity && payload.identity && snapshot.identity.experiment_id === payload.identity.experiment_id) {
      if (payload.identity.epoch_id !== snapshot.identity.epoch_id || payload.identity.source_commit !== snapshot.identity.source_commit || payload.identity.inception_sha256 !== snapshot.identity.inception_sha256 || payload.sequence < snapshot.sequence ||
          (payload.sequence === snapshot.sequence && payload.snapshot_sha256 !== snapshot.snapshot_sha256)) throw new Error('Simulator identity or sequence changed unexpectedly');
    } else if (snapshot?.identity && payload.identity) {
      throw new Error('Simulator experiment changed unexpectedly');
    }
    return payload;
  }

  async function refresh() {
    if (inflight) return;
    inflight = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let requestFailure = '';
    try {
      const response = await fetch('/api/pons-simulator/state', {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}, signal: controller.signal});
      if (!response.ok) {
        requestFailure = response.status === 401 || response.status === 403 ? 'Simulator access is unavailable; use the existing owner authentication.' : `Simulator request failed (HTTP ${response.status}).`;
        throw new Error('Simulator request failed');
      }
      snapshot = validate(await response.json());
      fetchedAt = new Date().toISOString();
      requestFailed = false;
      failureReason = '';
      render();
    } catch (error) {
      requestFailed = true;
      failureReason = requestFailure || (error.name === 'AbortError' ? 'Simulator request timed out.' : 'Simulator response unavailable or invalid.');
      updateFreshness();
    } finally {
      clearTimeout(timeout);
      inflight = false;
    }
  }

  render();
  refresh();
  setInterval(refresh, POLL_MS);
  setInterval(updateFreshness, 1000);
  document.addEventListener('visibilitychange', () => {
    updateFreshness();
    if (!document.hidden) refresh();
  });
})();
