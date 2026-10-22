'use strict';

// Offline renderer regression tests. This DOM double is not browser acceptance.
// The actual inline dashboard script runs without its DOMContentLoaded callback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this._text = '';
    this.value = '';
    this.className = '';
    this.classList = { add() {}, remove() {} };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  get firstChild() { return this.children[0]; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  setAttribute() {}
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
    createElement() { return new Element(); }
  };
  const context = vm.createContext({
    document,
    window: { location: { protocol: 'http:', port: '8080', pathname: '/', origin: 'http://127.0.0.1:8080' }, addEventListener() {} },
    localStorage: { getItem() { return null; } },
    Chart: function() { this.destroy = function() {}; },
    URLSearchParams,
    fetch() { throw new Error('External transport forbidden in renderer test'); }
  });
  const html = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  const script = scripts.map(match => match[1]).find(text => text.includes('function renderSignalCards()'));
  assert.ok(script, 'actual dashboard inline script must exist');
  const end = script.lastIndexOf('})();');
  assert.ok(end > 0, 'dashboard closure must exist');
  const hooks = '\n globalThis.hooks = { state, apiClient, renderSignalCards, renderSelectedSignalInspector, renderHeaderHealth, loadHealthAndConfig, loadSignals, loadStoredReports, renderStoredReports };\n';
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
