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
  const hooks = '\n globalThis.hooks = { state, apiClient, renderSignalCards, renderSelectedSignalInspector, renderHeaderHealth, loadHealthAndConfig, loadSignals };\n';
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
