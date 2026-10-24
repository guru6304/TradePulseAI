'use strict';

// Offline renderer regression tests. This DOM double is not browser acceptance.
// The actual inline dashboard script runs without its DOMContentLoaded callback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.attributes = {};
    this.children = [];
    this._text = '';
    this.value = '';
    this.className = '';
    this.classList = { add() {}, remove() {} };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  set innerHTML(_) { throw new Error('Renderer must use textContent for source text'); }
  get firstChild() { return this.children[0]; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener() {}
  getContext() { return {}; }
}

function dashboard() {
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id);
    },
    createElement(tagName) { return new Element(tagName); }
  };
  const context = vm.createContext({
    document,
    window: { location: { protocol: 'http:', port: '8080', pathname: '/', origin: 'http://127.0.0.1:8080' }, addEventListener() {} },
    localStorage: { getItem() { return null; } },
    Chart: function() { this.destroy = function() {}; },
    URLSearchParams, URL,
    fetch() { throw new Error('External transport forbidden in renderer test'); }
  });
  const html = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  const script = scripts.map(match => match[1]).find(text => text.includes('function renderSignalCards()'));
  assert.ok(script, 'actual dashboard inline script must exist');
  const end = script.lastIndexOf('})();');
  assert.ok(end > 0, 'dashboard closure must exist');
  const hooks = '\n globalThis.hooks = { state, apiClient, renderSignalCards, renderSelectedSignalInspector, renderHeaderHealth, renderSystemHealthTab, loadHealthAndConfig, loadSignals, loadStoredReports, renderStoredReports, renderScanRunsTable };\n';
  vm.runInContext(script.slice(0, end) + hooks + script.slice(end), context, { timeout: 1000 });
  return { ...context.hooks, node: id => document.getElementById(id) };
}

function storedSignal(overrides = {}) {
  return {
    id: 1, symbol: 'RELIANCE', segment: 'NSE_EQUITY_INTRADAY', direction: 'BULLISH',
    timestamp: '2026-10-16 10:30:00', entry_price: 100, stop_loss: 98,
    target_1: 104, target_2: 106, data_mode: 'LIVE', is_simulated: false,
    provider: 'angelone', state_context: 'SCANNER', broker: 'Angel One SmartAPI',
    ...overrides
  };
}

function renderSignal(view, record) {
  view.state.signals = [record];
  view.state.signalsTotal = 1;
  view.renderSignalCards();
}

test('candidate cards and inspector use supported numeric gross RR and visited rule explanations', () => {
  const view = dashboard();
  const record = storedSignal({risk_reward: '1:999', candidate_evaluation: {
    actionable: false, risk_reward: {allowed: true, target1_ratio: 2.125, target2_ratio: 3.25},
    explanation: {rule_evaluation: {summary: 'Existing setup detected', rule_checks: [
      {rule_id: 'volume.surge', status: 'PASS', reason: 'Volume requirement met'}]}},
    warnings: ['LIQUIDITY_NOT_ESTABLISHED', 'EMPIRICAL_PERFORMANCE_UNAVAILABLE']
  }});
  renderSignal(view, record);
  const cards = view.node('signalCardsContainer').textContent;
  assert.match(cards, /Gross R:R T1 2.13 \/ T2 3.25/);
  assert.match(cards, /Net R:R unavailable/);
  assert.ok(!cards.includes('1:999'));
  view.renderSelectedSignalInspector(record);
  assert.match(view.node('detailRationale').textContent, /volume.surge: PASS/);
  assert.match(view.node('detailRationale').textContent, /LIQUIDITY_NOT_ESTABLISHED/);
});

test('empty scan renders warm-up and rejected-rule reasons from retained evaluation', () => {
  const view = dashboard();
  view.state.scans = [{status: 'COMPLETED_EMPTY', total_signals: 0, evaluation: {
    strategy_evaluations: [{symbol: 'RELIANCE', strategy_id: 'strat_5_supertrend_pullback',
      status: 'UNAVAILABLE', warmup: {observed: 199, required: 200},
      reason_codes: ['INSUFFICIENT_COMPLETED_CANDLES']},
    {symbol: 'RELIANCE', strategy_id: 'strat_4_orb_filtered', status: 'REJECTED',
      reason_codes: ['CLOSE_NOT_ABOVE_RANGE']}]
  }}];
  view.renderScanRunsTable();
  const text = view.node('scanRunsTableBody').textContent;
  assert.match(text, /199\/200 bars/);
  assert.match(text, /UNAVAILABLE/);
  assert.match(text, /CLOSE_NOT_ABOVE_RANGE/);
});

test('scan history exposes downstream risk rejection when a detected setup has no stored signal', () => {
  const view = dashboard();
  view.state.scans = [{status: 'COMPLETED_EMPTY', total_signals: 0, evaluation: {
    strategy_evaluations: [{symbol: 'RELIANCE', strategy_id: 'strat_1_order_block',
      status: 'DETECTED', reason_codes: ['SETUP_DETECTED']}],
    candidate_evaluations: [{symbol: 'RELIANCE', strategy_id: 'strat_1_order_block',
      status: 'REJECTED', actionable: false, reason_codes: ['INVALID_SIGNAL_LEVELS']}]
  }}];
  view.renderScanRunsTable();
  const text = view.node('scanRunsTableBody').textContent;
  assert.match(text, /Candidate REJECTED INVALID_SIGNAL_LEVELS/);
  assert.match(text, /COMPLETED_EMPTY/);
});

const untrusted = [
  { data_mode: 'UNKNOWN' },
  { provider: 'unknown', state_context: 'UNKNOWN' },
  { provider: undefined },
  { data_mode: undefined },
  { is_simulated: undefined },
  { is_simulated: 'false' },
  { is_simulated: true },
  { data_mode: 'SIMULATED', is_simulated: false }
];

test('signal cards never promote missing, unknown or conflicting provenance to LIVE', () => {
  for (const fields of untrusted) {
    const view = dashboard();
    renderSignal(view, storedSignal(fields));
    const text = view.node('signalCardsContainer').textContent;
    assert.ok(text.includes('UNKNOWN SOURCE'), JSON.stringify(fields) + ': ' + text);
    assert.ok(!text.includes('LIVE'), JSON.stringify(fields));
  }
});

test('selected inspector never promotes untrusted provenance to LIVE', () => {
  for (const fields of untrusted) {
    const view = dashboard();
    view.renderSelectedSignalInspector(storedSignal(fields));
    assert.equal(view.node('detailDataModeBadge').textContent, 'UNKNOWN SOURCE');
  }
});

test('explicit source labels distinguish stored LIVE records from simulated records', () => {
  const view = dashboard();
  renderSignal(view, storedSignal());
  assert.ok(view.node('signalCardsContainer').textContent.includes('LIVE SOURCE (STORED)'));
  assert.equal(view.node('detailDataModeBadge').textContent, 'LIVE SOURCE (STORED)');
  assert.ok(view.node('detailTimestampAndBroker').textContent.includes('2026-10-16 10:30:00'));
  renderSignal(view, storedSignal({ data_mode: 'SIMULATED', is_simulated: true, provider: 'paper_sim' }));
  assert.ok(view.node('signalCardsContainer').textContent.includes('SIMULATED'));
  assert.equal(view.node('detailDataModeBadge').textContent, 'SIMULATED');
});

test('backend health failure clears a previously accepted header', async () => {
  const view = dashboard();
  view.renderHeaderHealth({ broker: { connection_state: 'CONNECTED_VERIFIED', data_mode: 'LIVE' }, live_acceptance: { accepted: true } });
  assert.equal(view.node('headerDataModeBadge').textContent, 'LIVE ACCEPTANCE EVIDENCE VALID');
  view.apiClient.getHealth = async () => { throw new Error('OFFLINE unavailable fixture'); };
  view.apiClient.getConfig = async () => ({});
  await view.loadHealthAndConfig();
  assert.equal(view.state.health, null);
  assert.equal(view.node('brokerStateBadge').textContent, 'OFFLINE');
  assert.equal(view.node('headerDataModeBadge').textContent, 'API DISCONNECTED');
});

test('continuous feed status exposes stale and fixture observations with signals blocked', () => {
  const view = dashboard();
  for (const status of ['STALE', 'FIXTURE', 'UNAVAILABLE']) {
    view.renderSystemHealthTab({ broker: {stream: {status, live_signal_allowed: false}} }, {});
    const text = view.node('healthDetailsContainer').textContent;
    assert.ok(text.includes('Continuous feed'));
    assert.ok(text.includes(status + ' | signals blocked'));
  }
});

test('a failed signals API request removes cached cards and inspector prices', async () => {
  const view = dashboard();
  renderSignal(view, storedSignal());
  view.apiClient.getSignals = async () => { throw new Error('OFFLINE signals unavailable'); };
  await view.loadSignals();
  assert.equal(view.state.signals.length, 0);
  assert.equal(view.node('signalCountBadge').textContent, 'Error');
  assert.ok(!view.node('signalCardsContainer').textContent.includes('RELIANCE'));
  assert.equal(view.node('detailDataModeBadge').textContent, '--');
  assert.equal(view.node('detailEntryPrice').textContent, '--');
});

test('late successful health response cannot replace a newer unavailable state', async () => {
  const view = dashboard();
  let resolveOld;
  view.apiClient.getHealth = () => new Promise(resolve => { resolveOld = resolve; });
  view.apiClient.getConfig = async () => ({});
  const older = view.loadHealthAndConfig();
  view.apiClient.getHealth = async () => { throw new Error('OFFLINE newer failure'); };
  await view.loadHealthAndConfig();
  resolveOld({ broker: { connection_state: 'CONNECTED_VERIFIED' }, live_acceptance: { accepted: true } });
  await older;
  assert.equal(view.state.health, null);
  assert.equal(view.node('brokerStateBadge').textContent, 'OFFLINE');
  assert.equal(view.node('headerDataModeBadge').textContent, 'API DISCONNECTED');
});

test('fixture scope overrides live-shaped source and acceptance flags', () => {
  const view = dashboard();
  const evidence_scope = 'OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE';
  renderSignal(view, storedSignal({ evidence_scope }));
  assert.equal(view.node('detailDataModeBadge').textContent, 'OFFLINE FIXTURE');
  view.renderHeaderHealth({ evidence_scope, live_acceptance: { accepted: true }, broker: { data_mode: 'LIVE' } });
  assert.equal(view.node('headerDataModeBadge').textContent, 'OFFLINE FIXTURE');
});

test('risk-rejected stored candidates show rejection and exact source batch', () => {
  const view = dashboard();
  renderSignal(view, storedSignal({ actionable: false, recommendation_status: 'PAPER_REJECTED',
    paper_decision: { status: 'REJECTED', reason_code: 'POSITION_EXPOSURE_LIMIT' },
    lineage: { batch_ids: ['fixture-batch'] }, scan_run_id: 'fixture-run' }));
  const cards = view.node('signalCardsContainer').textContent;
  assert.ok(cards.includes('PAPER_REJECTED') && cards.includes('POSITION_EXPOSURE_LIMIT'));
  assert.ok(cards.includes('fixture-batch') && cards.includes('fixture-run'));
  assert.ok(view.node('detailRationale').textContent.includes('fixture-batch'));
});

const workflowFlag = process.argv.indexOf('--workflow-payload');
test('stored report failures clear prior accounting and never turn reconciliation failure into accepted equity', async () => {
  const view = dashboard();
  view.state.health = {paper_account_id: 'offline'};
  view.apiClient.getNotificationOutbox = async () => ({counts: {ACKNOWLEDGED: 1}});
  view.apiClient.getBacktestRuns = async () => ({total_count: 0, items: []});
  view.apiClient.getPaperReport = async () => ({reconciliation: {status: 'OK'}, accounting: {
    equity_inr: 12345, open_positions: 1, closed_positions: 0, fees_paid_inr: 0}});
  await view.loadStoredReports();
  assert.ok(view.node('storedReportsContainer').textContent.includes('12,345'));
  view.apiClient.getPaperReport = async () => { throw new Error('OFFLINE unavailable'); };
  await view.loadStoredReports();
  const failed = view.node('storedReportsContainer').textContent;
  assert.ok(failed.includes('UNAVAILABLE') && !failed.includes('12,345'));
  view.apiClient.getPaperReport = async () => ({reconciliation: {status: 'RECONCILIATION_REQUIRED'}, accounting: {equity_inr: 12345}});
  await view.loadStoredReports();
  const corrupt = view.node('storedReportsContainer').textContent;
  assert.ok(corrupt.includes('RECONCILIATION REQUIRED') && !corrupt.includes('12,345'));
});

test('late stored report response cannot restore accounting after current health fails', async () => {
  const view = dashboard();
  view.state.health = {paper_account_id: 'offline'};
  let resolveOld;
  view.apiClient.getPaperReport = () => new Promise(resolve => { resolveOld = resolve; });
  view.apiClient.getNotificationOutbox = async () => ({counts: {}});
  view.apiClient.getBacktestRuns = async () => ({items: [], total_count: 0});
  const pending = view.loadStoredReports();
  view.apiClient.getHealth = async () => { throw new Error('OFFLINE'); };
  view.apiClient.getConfig = async () => ({});
  await view.loadHealthAndConfig();
  resolveOld({reconciliation: {status: 'OK'}, accounting: {equity_inr: 99999}});
  await pending;
  const text = view.node('storedReportsContainer').textContent;
  assert.ok(text.includes('unavailable') && !text.includes('99,999'));
});

function contextSignal(overrides = {}) {
  const identity = {provider: 'angelone', symbol: 'RELIANCE', identifier: '2885', exchange: 'NSE',
    segment: 'NSE_EQ', instrument_type: 'EQ', is_index: false, source: 'pinned-master', source_revision: 'fixture-v1'};
  return storedSignal({candidate_evaluation: {candidate_id: 'candidate-context-1', status: 'QUALIFIED', actionable: false,
    source_reference: {instrument_identity: identity}},
  context: {candidate_id: 'candidate-context-1', status: 'QUALIFIED', reason_codes: ['CONTEXT_QUALIFIED'],
    actionable: false, affects_ranking: false, evaluation_mode: 'DECISION_TIME',
    as_of: '2026-10-16T10:30:00+05:30', decision_at: '2026-10-16T10:30:00+05:30', snapshot_id: 'snapshot-1',
    records: [{record_id: 'record-1', content_id: 'content-1', title: '<script>source text</script>',
      summary: 'Authored offline fixture summary', source_id: 'fixture-issuer', source_name: 'Authored issuer fixture',
      source_url: 'https://issuer.example/notice/123', original_ref: 'source-original-123',
      published_at: '2026-10-16T09:40:00+05:30', event_at: '2026-10-16T09:45:00+05:30',
      collected_at: '2026-10-16T10:00:00+05:30', instrument_identity: {...identity},
      verification: {allowed: true, status: 'QUALIFIED_UNDER_LOCAL_POLICY'}, freshness: {status: 'FRESH'},
      reason_codes: [], retracted: false, conflict: false, correction: false,
      interpretation: {text: 'Source supplied interpretation', rule_id: 'source-rule-1'}}]}, ...overrides});
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

test('actual inspector renders source identity, times, safe links and local qualification without HTML injection', () => {
  const view = dashboard();
  const signal = contextSignal();
  renderSignal(view, signal);
  const content = view.node('detailContext');
  assert.match(content.textContent, /Context QUALIFIED/);
  assert.match(content.textContent, /Original decision 2026-10-16T10:30:00/);
  assert.match(content.textContent, /Published: 2026-10-16T09:40:00/);
  assert.match(content.textContent, /Event: 2026-10-16T09:45:00/);
  assert.match(content.textContent, /Collected: 2026-10-16T10:00:00/);
  assert.match(content.textContent, /independent authority\/rights not established/);
  assert.match(content.textContent, /Source-supplied interpretation \(unvalidated\)/);
  assert.match(content.textContent, /<script>source text<\/script>/);
  assert.equal(descendants(content).filter(node => node.tagName === 'SCRIPT').length, 0);
  const links = descendants(content).filter(node => node.tagName === 'A');
  assert.equal(links.length, 1);
  assert.equal(links[0].href, 'https://issuer.example/notice/123');
  assert.equal(links[0].rel, 'noopener noreferrer');
  assert.match(view.node('signalCardsContainer').textContent, /Context QUALIFIED/);
});

test('source hyperlinks reject executable, credentialed and local addresses without hiding the qualified facts', () => {
  for (const source_url of ['javascript:alert(1)', 'data:text/html,unsafe', 'file:///private', '//issuer.example/a',
    'http://issuer.example/a', 'https://user:password@issuer.example/a', 'https://127.0.0.1/a',
    'https://10.0.0.1/a', 'https://169.254.169.254/a', 'https://localhost/a', 'https://host.local/a',
    'https://[::1]/a', 'https://2130706433/a', 'https://issuer.example.:443/a', 'https://issuer.example:9443/a',
    'https://issuer.example/\\unsafe', 'https://issuer.example/\nunsafe']) {
    const view = dashboard();
    const signal = contextSignal();
    signal.context.records[0].source_url = source_url;
    view.renderSelectedSignalInspector(signal);
    const content = view.node('detailContext');
    assert.equal(descendants(content).filter(node => node.tagName === 'A').length, 0, source_url);
    assert.match(content.textContent, /Source link unavailable or unsafe/, source_url);
  }
});

test('missing and failed context never inherit neutral or previously qualified facts', async () => {
  const view = dashboard();
  renderSignal(view, contextSignal());
  view.renderSelectedSignalInspector(storedSignal());
  assert.match(view.node('detailContext').textContent, /Context UNAVAILABLE; no neutral assessment/);
  assert.ok(!view.node('detailContext').textContent.includes('source-original-123'));
  const missing = contextSignal();
  missing.context.status = 'MISSING';
  missing.context.records = [];
  missing.context.reason_codes = ['CONTEXT_IDENTITY_NOT_AVAILABLE'];
  view.renderSelectedSignalInspector(missing);
  assert.match(view.node('detailContext').textContent, /Context MISSING/);
  assert.match(view.node('detailContext').textContent, /No context record available/);
  renderSignal(view, contextSignal());
  view.apiClient.getSignals = async () => { throw new Error('OFFLINE context API unavailable'); };
  await view.loadSignals();
  assert.ok(!view.node('detailContext').textContent.includes('source-original-123'));
  assert.ok(!view.node('detailContext').textContent.includes('Context QUALIFIED'));
});

test('warning records expose stale, unverified, retracted and conflicting source state without changing candidate risk', () => {
  const view = dashboard();
  const signal = contextSignal();
  const original = JSON.stringify(signal.candidate_evaluation);
  Object.assign(signal.context, {status: 'WARNING_ONLY', reason_codes: ['CONTEXT_STALE', 'CONTEXT_CONFLICTING']});
  Object.assign(signal.context.records[0], {verification: {allowed: false, status: 'NOT_ESTABLISHED'},
    freshness: {status: 'STALE'}, retracted: true, conflict: true, correction: true,
    reason_codes: ['CONTEXT_SOURCE_NOT_QUALIFIED']});
  view.renderSelectedSignalInspector(signal);
  const text = view.node('detailContext').textContent;
  assert.match(text, /Context WARNING_ONLY/);
  assert.match(text, /UNVERIFIED \/ WARNING ONLY/);
  assert.match(text, /Freshness STALE/);
  assert.match(text, /Retracted YES \| Conflict YES \| Correction YES/);
  assert.ok(!text.includes('QUALIFIED UNDER LOCAL POLICY'));
  assert.equal(JSON.stringify(signal.candidate_evaluation), original);
});

test('inconsistent qualified context and exact instrument or candidate mismatches withhold facts', () => {
  for (const mutate of [
    signal => { signal.context.candidate_id = 'other-candidate'; },
    signal => { signal.context.records[0].instrument_identity.identifier = 'wrong-token'; },
    signal => { signal.context.records[0].instrument_identity.provider = 'upstox'; },
    signal => { signal.context.records[0].verification.allowed = false; },
    signal => { signal.context.records[0].freshness.status = 'STALE'; },
    signal => { signal.context.actionable = true; }
  ]) {
    const view = dashboard();
    const signal = contextSignal();
    mutate(signal);
    view.renderSelectedSignalInspector(signal);
    const text = view.node('detailContext').textContent;
    assert.match(text, /Context UNAVAILABLE/);
    assert.ok(!text.includes('source-original-123'));
  }
});

test('current-information context remains labeled as a later informational update to a stored decision', () => {
  const view = dashboard();
  const signal = contextSignal();
  signal.context.evaluation_mode = 'CURRENT_INFORMATION';
  signal.context.as_of = '2026-10-17T10:30:00+05:30';
  signal.context_alert_decision = {status: 'ELIGIBLE', reason_code: 'QUALIFIED_CONTEXT_FOR_STORED_CANDIDATE'};
  view.renderSelectedSignalInspector(signal);
  const text = view.node('detailContext').textContent;
  assert.match(text, /CURRENT_INFORMATION \| As of 2026-10-17/);
  assert.match(text, /Original decision 2026-10-16/);
  assert.match(text, /no current recommendation/);
  assert.match(text, /Context alert ELIGIBLE/);
  assert.match(text, /no real delivery/);
});

test('scan-only rejected candidates expose retained context and suppression even with no stored signal', () => {
  const view = dashboard();
  const signal = contextSignal();
  signal.candidate_evaluation.status = 'REJECTED';
  signal.candidate_evaluation.symbol = 'RELIANCE';
  signal.candidate_evaluation.reason_codes = ['INVALID_SIGNAL_LEVELS'];
  signal.context.status = 'WARNING_ONLY';
  signal.context.reason_codes = ['CONTEXT_SOURCE_NOT_QUALIFIED'];
  signal.context.records[0].verification = {allowed: false, status: 'NOT_ESTABLISHED'};
  view.state.scans = [{status: 'COMPLETED_EMPTY', total_signals: 0,
    evaluation: {strategy_evaluations: [], candidate_evaluations: [signal.candidate_evaluation]},
    context: {snapshot_id: 'snapshot-1', as_of: signal.context.as_of, decision_at: signal.context.decision_at,
      evaluation_mode: 'DECISION_TIME', candidate_contexts: [signal.context]},
    context_alert_decisions: [{snapshot_id: 'snapshot-1', candidate_id: signal.context.candidate_id,
      status: 'SUPPRESSED', reason_code: 'CANDIDATE_NOT_QUALIFIED'}]}];
  view.renderScanRunsTable();
  const text = view.node('scanRunsTableBody').textContent;
  assert.match(text, /Candidate REJECTED INVALID_SIGNAL_LEVELS/);
  assert.match(text, /Context WARNING_ONLY/);
  assert.match(text, /Context alert SUPPRESSED: CANDIDATE_NOT_QUALIFIED/);
  assert.match(text, /Source-supplied interpretation \(unvalidated\)/);
});

test('notification view distinguishes local preview acknowledgement, retry and suppressed context without delivery claims', () => {
  const view = dashboard();
  view.renderStoredReports([{label: 'Notification previews', data: {counts: {ACKNOWLEDGED: 1, RETRY: 1},
    items: [{kind: 'CONTEXT_UPDATE', delivery_state: 'DRY_RUN_RECORDED', candidate_id: 'c1', context_snapshot_id: 's1'},
      {kind: 'CONTEXT_UPDATE', status: 'RETRY', candidate_id: 'c2', context_snapshot_id: 's2'}],
    context_alert_decisions: [{status: 'SUPPRESSED', reason_code: 'CONTEXT_NOT_QUALIFIED'}]}}], null);
  const text = view.node('storedReportsContainer').textContent;
  assert.match(text, /LOCAL PREVIEW ONLY; real delivery disabled/);
  assert.match(text, /CONTEXT_UPDATE DRY_RUN_RECORDED/);
  assert.match(text, /CONTEXT_UPDATE RETRY/);
  assert.match(text, /Context alert SUPPRESSED: CONTEXT_NOT_QUALIFIED/);
  assert.ok(!text.includes('DELIVERED'));
});

test('phase 6 paper ledger report renders open positions, closed positions, fees, and equity with simulation disclaimer', () => {
  const view = dashboard();
  view.renderStoredReports([{
    label: 'Paper ledger',
    data: {
      reconciliation: {status: 'OK'},
      accounting: {
        open_positions: 2,
        closed_positions: 3,
        equity_inr: 205000.5,
        fees_paid_inr: 45.25
      }
    }
  }], 'phase6-account');
  const text = view.node('storedReportsContainer').textContent;
  assert.match(text, /LOCAL STORED EVIDENCE\. Paper fills and research execution are simulations/);
  assert.match(text, /Reconciliation OK \| Open 2 \| Closed 3/);
  assert.match(text, /Equity ₹2,05,000\.50/);
  assert.match(text, /Fees ₹45\.25/);
});

test('phase 6 EOD statement renders reconciled statement hash or unresolved status truthfully', () => {
  const view = dashboard();
  view.renderStoredReports([{
    label: 'EOD statement',
    data: {
      status: 'OK',
      eod_status: 'RECONCILED',
      session_date: '2026-10-16',
      statement_sha256: 'abc123def4567890fedcba0987654321'
    }
  }], 'phase6-account');
  const text = view.node('storedReportsContainer').textContent;
  assert.match(text, /OK \| RECONCILED \| 2026-10-16 \| Statement abc123def4567890fedcba0987654321/);
});

if (workflowFlag !== -1) {
  test('actual HTTP workflow payload renders matching source, timestamp, prices and paper decision', () => {
    const payload = JSON.parse(fs.readFileSync(process.argv[workflowFlag+1], 'utf8'));
    assert.equal(payload.evidence_scope, 'OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE');
    const signal = payload.items[0];
    const view = dashboard();
    renderSignal(view, signal);
    assert.equal(signal.actionable, false);
    assert.equal(view.node('detailDataModeBadge').textContent, 'OFFLINE FIXTURE');
    assert.ok(view.node('detailTimestampAndBroker').textContent.includes(signal.timestamp));
    assert.ok(view.node('detailRationale').textContent.includes(signal.lineage.batch_ids[0]));
    assert.ok(view.node('signalCardsContainer').textContent.includes('PAPER_FILLED'));
    assert.ok(view.node('detailEntryPrice').textContent.includes(Number(signal.entry_price).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })));
    view.renderStoredReports(payload.stored_reports, 'offline-cash');
    const reports = view.node('storedReportsContainer').textContent;
    assert.ok(reports.includes('Reconciliation OK | Open 1'));
    assert.ok(reports.includes('real delivery disabled'));
  });
}
