'use strict';

// Run the real terminal closure before its DOM startup, with authored reads only.
// Each child process has an actual non-IST host timezone; no parser is copied here.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const test = require('node:test');
const vm = require('node:vm');

const APP = __dirname;
const NAIVE = '2026-10-16 10:00:00';
const OFFSET = '2026-10-16T10:00:00+05:30';
const INSTANT = Date.UTC(2026, 9, 16, 4, 30);
const IDENTITY = {provider:'authored-fixture',symbol:'INFY',identifier:'SYNTHETIC-INFY',
  exchange:'NSE',segment:'NSE_EQUITY_INTRADAY',instrument_type:'EQ',is_index:false};

class Node {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.open = false;
    this.value = '';
    this._text = '';
    this.classList = {add: value => { this.className = value; }};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent || '').join(''); }
}

function harness() {
  const source = fs.readFileSync(path.join(APP, 'public', 'terminal.js'), 'utf8');
  const marker = '\n  navigation();';
  assert.equal(source.split(marker).length, 2, 'exactly one DOM startup boundary');
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new Node());
      return nodes.get(id);
    },
    createElement: tag => new Node(tag),
    createElementNS: (_namespace, tag) => new Node(tag),
  };
  const timers = [];
  const context = vm.createContext({
    document, Intl, performance:{now:() => 0},
    setTimeout(fn, ms) { const timer = {fn, ms}; timers.push(timer); return timer; },
    clearTimeout(timer) { if (timer) timer.cleared = true; },
  });
  const hook = `
  globalThis.__clock = {
    time, sourceTime: typeof sourceTime === 'function' ? sourceTime : undefined,
    detail, refresh, state,
    readWith(reader) { get = reader; },
    isolateView() { render = () => {}; loadRoute = () => {}; }
  };
  return;`;
  vm.runInContext(source.replace(marker, hook + marker), context, {filename:'public/terminal.js'});
  context.__clock.isolateView();
  return {clock:context.__clock, node:id => document.getElementById(id), timers};
}

function candidate(overrides = {}) {
  return {rank:1,symbol:'INFY',strategy_id:'strat_4_orb_filtered',
    opportunity_key:'synthetic-INFY',candidate_id:'synthetic-signal-INFY',source_digest:'b'.repeat(64),
    position_type:'LONG_EQUITY_INTRADAY',direction:'LONG',actionable:false,
    instrument_identity:IDENTITY,source_data_watermark:OFFSET,
    score_components:{rule_quality:80,actual_target1_rr:1.8},missing_components:[],...overrides};
}

function fixtures() {
  const row = candidate();
  const scope = {provider:'authored-fixture',data_mode:'SIMULATED',segment:'NSE_EQUITY_INTRADAY',profile_digest:'a'.repeat(64)};
  return {
    row,
    health:{evidence_scope:'DETERMINISTIC_OFFLINE_DEMO',
      broker:{is_simulated:true,data_mode:'SIMULATED',last_candle_timestamp_ist:NAIVE}},
    ranks:{status:'CURRENT_CANDIDATE_PRIORITY',actionable:false,current_rows:[row],scope,
      pagination:{total:1,limit:100,offset:0},as_of:'2026-10-16T04:30:00Z',
      snapshot:{run_id:'synthetic-run',work_id:'synthetic-work',rank_version:'c'.repeat(64),scope,
        reference:OFFSET,valid_until:'2026-10-16T10:00:30+05:30'}},
    signal:{...row,dedup_key:row.candidate_id,timestamp:NAIVE,entry_price:101,entry_zone_low:100.5,
      entry_zone_high:101.5,invalidation_level:99.5,stop_loss:99,target_1:105,target_2:107,rationale:'Authored retained signal',
      candidate_evaluation:{candidate_id:row.candidate_id,warnings:[],explanation:{rule_evaluation:{summary:'Retained rules',
        rule_checks:[{rule_id:'orb.close',status:'PASS',reason:'Completed close'}]}}},
      strategy_evidence:{maturity_state:'MECHANICS_VERIFIED',empirical_status:'NOT_ESTABLISHED'},
      context:{candidate_id:row.candidate_id,status:'QUALIFIED',actionable:false,affects_ranking:false,
        reason_codes:['AUTHORED_INFORMATION_ONLY'],evaluation_mode:'DECISION_TIME',as_of:OFFSET,decision_at:OFFSET,
        records:[{instrument_identity:IDENTITY,title:'Authored source',source_name:'Authored fixture',published_at:OFFSET,
          verification:{allowed:true,status:'QUALIFIED_UNDER_LOCAL_POLICY'},freshness:{status:'FRESH'},reason_codes:[]}]},
      paper_decision:{status:'PENDING',reason_code:'WAITING_FOR_LATER_TRIGGER',trigger_timestamp_ist:NAIVE,
        trigger_contract:{rule_id:'orb.close_cross.v1'}}},
    lineage:{run_id:'synthetic-run',status:'COMMITTED',batches:[{batch_id:'synthetic-INFY',
      identity:IDENTITY,interval_min:5,candle_count:2,last_timestamp:NAIVE}]},
    candles:{run_id:'synthetic-run',batch_id:'synthetic-INFY',total_count:2,items:[
      {timestamp:'2026-10-16 09:55:00',open:100,high:102,low:99,close:101,
        instrument_identity:IDENTITY,interval_min:5,is_complete:true},
      {timestamp:NAIVE,open:101,high:103,low:100,close:102,
        instrument_identity:IDENTITY,interval_min:5,is_complete:true},
    ]},
  };
}

function reader(data) {
  return async route => {
    const payloads = {'/api/health':data.health,'/api/opportunity-rankings':data.ranks,
      '/api/signals':{items:[data.signal]},'/api/scan-lineage':data.lineage,
      '/api/cash-candles':data.candles};
    assert.ok(Object.hasOwn(payloads, route), 'only a declared authored read is used: ' + route);
    return payloads[route];
  };
}

function charts(node) {
  return (node.className === 'candle-chart' ? 1 : 0) + node.children.reduce((n, child) => n + charts(child), 0);
}

if (!process.env.TERMINAL_CLOCK_TZ_CHILD) {
  for (const timezone of ['UTC', 'America/New_York']) {
    test('actual terminal clock and chart contract under TZ=' + timezone, t => {
      const childEnv = {...process.env,TZ:timezone,TERMINAL_CLOCK_TZ_CHILD:timezone};
      // A --test worker's inherited context can suppress its nested test runner.
      delete childEnv.NODE_TEST_CONTEXT;
      const child = spawnSync(process.execPath, ['--test', '--test-reporter=tap', __filename], {
        cwd:APP,encoding:'utf8',timeout:15000,
        env:childEnv,
      });
      t.diagnostic('Child TZ=' + timezone + '\n' + (child.stdout || '') + (child.stderr || ''));
      assert.ifError(child.error);
      assert.equal(child.status, 0, child.stdout + child.stderr);
      for (const [key, expected] of Object.entries({tests:9,pass:9,fail:0,cancelled:0,skipped:0,todo:0})) {
        assert.match(child.stdout, new RegExp('^# ' + key + ' ' + expected + '\\r?$', 'm'),
          'the timezone child must report ' + key + '=' + expected);
      }
    });
  }
} else {
  test('the child uses its requested host timezone', () => {
    assert.equal(Intl.DateTimeFormat().resolvedOptions().timeZone, process.env.TERMINAL_CLOCK_TZ_CHILD);
  });

  test('backend IST text and ISO offsets denote one instant', () => {
    const {clock} = harness();
    assert.equal(typeof clock.sourceTime, 'function', 'the terminal has one shared source-time parser');
    for (const value of [NAIVE, OFFSET, '2026-10-16T04:30:00Z', '2026-10-16T00:30:00-04:00']) {
      assert.equal(clock.sourceTime(value), INSTANT, value);
    }
    assert.equal(clock.sourceTime('2024-02-29 10:00:00'), Date.UTC(2024, 1, 29, 4, 30));
  });

  test('invalid, missing, non-string and rolled-over dates never become source instants', () => {
    const {clock} = harness();
    assert.equal(typeof clock.sourceTime, 'function');
    for (const value of [undefined,null,0,1,false,{},[],new Date(INSTANT),'',' ',
      '2026-02-29 10:00:00','2026-02-30 10:00:00','2026-04-31 10:00:00',
      '2026-13-16 10:00:00','2026-10-00 10:00:00','2026-10-16 24:00:00',
      '2026-10-16 10:60:00','2026-10-16 10:00:60','2026-10-16T10:00:00',
      '2026-02-30T10:00:00+05:30','2026-10-16T24:00:00Z',
      '2026-10-16T10:00:00+24:00','2026-10-16T10:00:00+05:60','10/16/2026 10:00:00']) {
      assert.ok(Number.isNaN(clock.sourceTime(value)), 'reject ' + String(value));
    }
  });

  test('expiry parser requires an explicit offset and accepts equivalent ISO instants', () => {
    const {clock} = harness();
    assert.equal(typeof clock.sourceTime, 'function');
    for (const value of [NAIVE,'2026-10-16T10:00:00','',0,null]) {
      assert.ok(Number.isNaN(clock.sourceTime(value, {requireOffset:true})), 'reject ambiguous expiry ' + value);
    }
    assert.equal(clock.sourceTime(OFFSET, {requireOffset:true}), INSTANT);
    assert.equal(clock.sourceTime('2026-10-16T04:30:00Z', {requireOffset:true}), INSTANT);
  });

  test('fresh health display is 10:00 IST for backend text in a non-IST host', async () => {
    const h = harness(), data = fixtures();
    h.clock.readWith(reader(data));
    await h.clock.refresh();
    assert.match(h.node('source-time').textContent, /10:00 IST$/);
    assert.equal(h.clock.state.rows.length, 1);
    assert.equal(h.timers.filter(timer => !timer.cleared).length, 1);
    assert.equal(h.timers.find(timer => !timer.cleared).ms, 30001);
    assert.equal(h.clock.time(NAIVE), h.clock.time(OFFSET));
    for (const value of [0,null,'2026-02-30 10:00:00']) assert.equal(h.clock.time(value), 'Time unavailable');
  });

  test('ranking refresh rejects naive as_of or valid_until instead of scheduling expiry', async () => {
    for (const field of ['as_of', 'valid_until']) {
      const h = harness(), data = fixtures();
      if (field === 'as_of') data.ranks.as_of = NAIVE;
      else data.ranks.snapshot.valid_until = '2026-10-16 10:00:30';
      h.clock.readWith(reader(data));
      await h.clock.refresh();
      assert.equal(h.clock.state.rows.length, 0, field + ' must include an offset');
      assert.equal(h.timers.filter(timer => !timer.cleared).length, 0);
    }
  });

  test('actual detail links naive signal and completed 5m bars to the ISO ranking watermark', async () => {
    const h = harness(), data = fixtures();
    h.clock.readWith(reader(data));
    h.clock.state.ranks = data.ranks;
    await h.clock.detail(data.row);
    assert.equal(charts(h.node('detail-body')), 1);
    assert.match(h.node('detail-body').textContent, /10:00 IST/);
    assert.ok(!h.node('detail-body').textContent.includes('unavailable'));
  });

  test('actual detail withholds the chart for wrong 5m lineage, bars, identity or watermark', async () => {
    const corruptions = {
      'non-5m lineage':data => { data.lineage.batches[0].interval_min = 1; },
      'non-5m bar':data => { data.candles.items[0].interval_min = 1; },
      'same-session cadence gap':data => { data.candles.items[0].timestamp = '2026-10-16 09:54:00'; },
      'wrong identity':data => { data.candles.items[0].instrument_identity = {...IDENTITY,symbol:'TCS'}; },
      'incomplete bar':data => { data.candles.items[1].is_complete = false; },
      'ranking watermark without offset':data => { data.row.source_data_watermark = NAIVE; },
      'wrong final watermark':data => { data.candles.items[1].timestamp = '2026-10-16 09:59:00'; },
      'invalid rollover bar':data => { data.candles.items[0].timestamp = '2026-02-30 09:55:00'; },
      'invalid rollover signal':data => { data.signal.timestamp = '2026-02-30 10:00:00'; },
      'wrong signal timestamp':data => { data.signal = {...data.signal,timestamp:'2026-10-16 10:00:01'}; },
    };
    for (const [name, corrupt] of Object.entries(corruptions)) {
      const h = harness(), data = fixtures();
      corrupt(data);
      h.clock.readWith(reader(data));
      h.clock.state.ranks = data.ranks;
      await h.clock.detail(data.row);
      assert.equal(charts(h.node('detail-body')), 0, name);
      assert.match(h.node('detail-body').textContent, /unavailable/, name);
    }
  });

  test('actual 5m chart allows a retained previous-session boundary', async () => {
    const h = harness(), data = fixtures();
    data.candles.items[0].timestamp = '2026-10-15 15:30:00';
    h.clock.readWith(reader(data));
    h.clock.state.ranks = data.ranks;
    await h.clock.detail(data.row);
    assert.equal(charts(h.node('detail-body')), 1);
  });
}
