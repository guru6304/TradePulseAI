'use strict';

// Actual terminal functions with a small DOM double and authored GET readers.
// This verifies renderer contracts; the CDP helper supplies browser evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const STAMP = '2026-10-16T10:00:00+05:30';
const NAIVE = '2026-10-16 10:00:00';
const SCOPE = {provider:'authored-fixture',data_mode:'SIMULATED',segment:'NSE_EQUITY_INTRADAY',profile_digest:'a'.repeat(64)};
const identity = symbol => ({provider:SCOPE.provider,symbol,identifier:'SYNTHETIC-'+symbol,
  exchange:'NSE',segment:SCOPE.segment,instrument_type:'EQ',is_index:false});
const rows = count => Array.from({length:count}, (_, i) => ({rank:i+1,previous_rank:i+1,
  symbol:'STOCK'+String(i).padStart(3,'0'),opportunity_key:'opportunity-'+i,candidate_id:'signal-'+i,
  strategy_id:'strat_4_orb_filtered',position_type:'LONG_EQUITY_INTRADAY',direction:'LONG',
  instrument_identity:identity('STOCK'+String(i).padStart(3,'0')),actionable:false,
  source_data_watermark:STAMP,source_digest:'b'.repeat(64),
  score_components:{rule_quality:80,actual_target1_rr:1.8},missing_components:['EMPIRICAL_EDGE'],
  rank_change_reason:'UNCHANGED_PRIORITY'}));

function fixture(count=125) {
  const data={rows:rows(count),version:'c'.repeat(64),run:'synthetic-run',calls:[]};
  data.page = params => ({status:'CURRENT_CANDIDATE_PRIORITY',actionable:false,scope:SCOPE,
    as_of:'2026-10-16T04:30:00Z',current_rows:JSON.parse(JSON.stringify(data.rows.slice(params.offset, params.offset+params.limit))),
    historical_rows:JSON.parse(JSON.stringify(data.rows.slice(params.offset, params.offset+params.limit))),
    pagination:{total:data.rows.length,limit:params.limit,offset:params.offset},
    snapshot:{run_id:data.run,work_id:'synthetic-work',rank_version:data.version,scope:SCOPE,
      reference:STAMP,valid_until:'2026-10-16T10:00:30+05:30',source_authenticity:'NOT_ESTABLISHED'}});
  data.read = async (route, params={}) => {
    data.calls.push({route,params:{...params}});
    if(route==='/api/health') return {evidence_scope:'DETERMINISTIC_OFFLINE_DEMO',
      broker:{data_mode:'SIMULATED',is_simulated:true,last_candle_timestamp_ist:NAIVE},
      scheduler:{session_state:'SYNTHETIC_TEST_SESSION'}};
    if(route==='/api/opportunity-rankings') return data.page(params);
    const selected=data.rows.find(row=>row.symbol===params.symbol)||data.rows[0];
    if(route==='/api/signals') return {items:[signal(selected)],total_count:1};
    if(route==='/api/scan-lineage') return {run_id:data.run,status:'COMMITTED',batches:data.rows.map(row=>({
      batch_id:'synthetic-'+row.symbol,identity:row.instrument_identity,interval_min:5,
      candle_count:2,last_timestamp:NAIVE}))};
    if(route==='/api/cash-candles') {
      const row=data.rows.find(item=>'synthetic-'+item.symbol===params.batch_id)||selected;
      return {run_id:data.run,batch_id:params.batch_id,total_count:2,items:[
        {timestamp:'2026-10-16 09:55:00',open:100,high:103,low:99,close:102},
        {timestamp:NAIVE,open:102,high:104,low:101,close:103},
      ].map(bar=>({...bar,instrument_identity:row.instrument_identity,interval_min:5,is_complete:true}))};
    }
    throw new Error('Undeclared authored route '+route);
  };
  return data;
}

function signal(row) {
  return {...row,dedup_key:row.candidate_id,scan_run_id:'synthetic-run',timestamp:NAIVE,
    provider:SCOPE.provider,segment:SCOPE.segment,direction:'BULLISH',actionable:false,
    entry_price:101,entry_zone_low:100.5,entry_zone_high:101.5,invalidation_level:99.5,
    stop_loss:99,target_1:105,target_2:107,rationale:'Authored signal <img src=x onerror=bad()>',
    candidate_evaluation:{candidate_id:row.candidate_id,explanation:{rule_evaluation:{
      summary:'Retained qualification',rule_checks:[{rule_id:'volume.surge',status:'PASS',reason:'Observed volume'}]}},
      warnings:['LIQUIDITY_NOT_ESTABLISHED']},
    strategy_evidence:{maturity_state:'MECHANICS_VERIFIED',empirical_status:'NOT_ESTABLISHED'},
    context:{candidate_id:row.candidate_id,status:'MISSING',actionable:false,affects_ranking:false,
      reason_codes:['CONTEXT_NOT_EVALUATED'],records:[],evaluation_mode:'DECISION_TIME',as_of:STAMP},
    paper_decision:{status:'PENDING',reason_code:'WAITING_FOR_LATER_TRIGGER',trigger_contract:{rule_id:'orb.close_cross.v1'}}};
}

class Element {
  constructor(document, tag='div') {
    this.document=document; this.tagName=tag.toUpperCase(); this.children=[];
    this.attributes={}; this.dataset={}; this.style={}; this._text=''; this.value='';
    this.className=''; this.open=false; this.disabled=false;
    this.listeners={}; this.parentNode=null;
    this.classList={add:value=>{this.className+=' '+value;},toggle:()=>false};
  }
  append(...nodes) { for(const node of nodes){node.parentNode=this;this.children.push(node);} }
  replaceChildren(...nodes) {
    if(this.contains(this.document.activeElement))this.document.activeElement=this.document.body;
    for(const node of this.children)node.parentNode=null;
    this.children=[];this._text='';this.append(...nodes);
  }
  set textContent(value) { this.replaceChildren();this._text=String(value); }
  get textContent() { return this._text+this.children.map(node=>node.textContent).join(' '); }
  set innerHTML(_) { throw new Error('Use textContent for retained source text'); }
  setAttribute(key,value) { this.attributes[key]=String(value); }
  getAttribute(key) { return this.attributes[key]??null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name,fn) { (this.listeners[name]??=[]).push(fn); }
  dispatch(name) { for(const fn of this.listeners[name]||[])fn({target:this}); }
  click() { if(!this.disabled)this.dispatch('click'); }
  contains(node) { return this===node||this.children.some(child=>child.contains(node)); }
  get isConnected() { return this.document.body.contains(this); }
  focus() { if(this.isConnected)this.document.activeElement=this; }
  showModal() { this.open=true;this.document.getElementById('close-detail').focus(); }
  close() { this.open=false;this.dispatch('close'); }
  matches(selector) {
    if(selector[0]==='#')return this.id===selector.slice(1);
    if(selector[0]==='.')return this.className.split(/\s+/).includes(selector.slice(1));
    const attribute=/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/.exec(selector);
    if(attribute){const key=attribute[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
      return Object.hasOwn(this.dataset,key)&&(attribute[2]===undefined||this.dataset[key]===attribute[2]);}
    return this.tagName===selector.toUpperCase();
  }
  querySelectorAll(selector) { return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
  closest(selector) { return this.matches(selector)?this:this.parentNode?.closest(selector)||null; }
}

function terminal(data=fixture()) {
  const document={}; document.body=new Element(document,'body');document.activeElement=document.body;
  document.createElement=tag=>new Element(document,tag);
  document.createElementNS=(_ns,tag)=>new Element(document,tag);
  document.getElementById=id=>document.body.querySelectorAll('#'+id)[0]||null;
  document.querySelectorAll=selector=>document.body.querySelectorAll(selector);
  for(const id of ['view','detail','notice','source-mode','source-time','source-status','session','search','refresh-data','page-content']) {
    const node=document.createElement(id==='detail'?'dialog':'div');node.id=id;document.body.append(node);
  }
  for(const id of ['detail-title','detail-body','close-detail']) {
    const node=document.createElement(id==='close-detail'?'button':'div');node.id=id;document.getElementById('detail').append(node);
  }
  const timers=[];let elapsed=0;
  const context=vm.createContext({document,Intl,performance:{now:()=>elapsed},
    setTimeout(callback,delay){const timer={callback,delay};timers.push(timer);return timer;},
    clearTimeout(timer){if(timer)timer.cancelled=true;}});
  const source=fs.readFileSync(path.join(__dirname,'public/terminal.js'),'utf8');
  const marker='\n  navigation();';assert.equal(source.split(marker).length,2);
  const hook=`\n globalThis.hooks={state,refresh,render,detail,filtered,
    closeDetail:typeof closeDetail==='function'?closeDetail:undefined,
    readWith(reader){get=reader;}};\n return;`;
  vm.runInContext(source.replace(marker,hook+marker),context,{filename:'public/terminal.js'});
  const h={...context.hooks,document,timers,advance:ms=>{elapsed+=ms;},node:id=>document.getElementById(id),
    buttons:()=>document.getElementById('view').querySelectorAll('button').filter(node=>node.dataset.candidateKey)};
  h.state.route='opportunities';h.readWith(data.read);return h;
}

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

test('collects more than100 ranked rows with API limit100 and snapshot-pinned later pages',async()=>{
  const data=fixture(),h=terminal(data);await h.refresh();
  assert.equal(h.state.rows.length,125);
  const calls=data.calls.filter(call=>call.route==='/api/opportunity-rankings');
  assert.deepEqual(calls.map(call=>call.params.limit),[100,100]);
  assert.deepEqual(calls.map(call=>call.params.offset),[0,100]);
  assert.equal(calls[1].params.run_id,'synthetic-run');
});

test('full-snapshot search reaches a candidate beyond the first API page',async()=>{
  const h=terminal();await h.refresh();h.state.query='stock124';h.render();
  assert.equal(h.buttons().length,1);assert.equal(h.buttons()[0].textContent,'STOCK124');
  assert.match(h.node('opportunity-page').textContent,/1.*125/);
});

test('zero matches keep reset and paging recovery; a shortened last page clamps locally',async()=>{
  const data=fixture(),h=terminal(data);await h.refresh();h.state.page=6;h.render();
  assert.equal(h.buttons().length,5);
  h.state.query='absent';h.render();assert.ok(h.node('opportunity-reset'));
  assert.ok(h.node('opportunity-prev'));assert.ok(h.node('opportunity-next'));
  h.node('opportunity-reset').click();assert.equal(h.state.query,'');
  data.rows=data.rows.slice(0,3);await h.refresh();assert.equal(h.state.page,0);
  assert.equal(h.buttons().length,3);
});

test('mixed rank versions and malformed page/duplicate identities withhold the entire collection',async()=>{
  for(const corrupt of [page=>{page.snapshot.rank_version='d'.repeat(64);},
    page=>{page.pagination.offset=0;},page=>{page.scope={...SCOPE,provider:'wrong'};},
    page=>{page.current_rows[0]={...page.current_rows[0],opportunity_key:'opportunity-0'};},
    page=>{page.current_rows=page.current_rows.slice(1);}]) {
    const data=fixture(),page=data.page;data.page=params=>{const value=page(params);if(params.offset)corrupt(value);return value;};
    const h=terminal(data);await h.refresh();assert.equal(h.state.rows.length,0);
    assert.match(h.node('view').textContent,/could not be verified|invalid|inconsistent/i);
  }
});

test('rejects rank collection larger than512 rather than reading an unbounded list',async()=>{
  const data=fixture(513),h=terminal(data);await h.refresh();assert.equal(h.state.rows.length,0);
  assert.equal(data.calls.filter(call=>call.route==='/api/opportunity-rankings').length,1);
});

test('local filter rerender preserves the focused filter and resets page',async()=>{
  const h=terminal();await h.refresh();h.state.page=5;h.render();
  const select=h.node('opportunity-direction');assert.ok(select);select.focus();select.value='SHORT';select.dispatch('change');
  assert.equal(h.document.activeElement,h.node('opportunity-direction'));assert.equal(h.state.page,0);
});

test('reordered refresh preserves a focused candidate without moving a user-owned search focus',async()=>{
  const data=fixture(3),h=terminal(data);await h.refresh();
  const key=h.buttons()[1].dataset.candidateKey;h.buttons()[1].focus();
  data.rows.reverse();data.rows.forEach((row,index)=>{row.rank=index+1;});await h.refresh();
  assert.equal(h.document.activeElement.dataset.candidateKey,key);
  const hold=deferred(),read=data.read;h.readWith(async(route,params)=>route==='/api/health'?hold.promise:read(route,params));
  const pending=h.refresh();h.node('search').focus();hold.resolve(await read('/api/health'));await pending;
  assert.equal(h.document.activeElement,h.node('search'));
});

test('selected X-Ray withholds old prices while refreshing then rebinds the same source identity',async()=>{
  const data=fixture(3),h=terminal(data);await h.refresh();const selected=data.rows[1];
  await h.detail(selected);assert.match(h.node('detail-body').textContent,/Decision reference/);
  const hold=deferred(),read=data.read;h.readWith(async(route,params)=>route==='/api/health'?hold.promise:read(route,params));
  const pending=h.refresh();assert.equal(h.node('detail').open,true);
  assert.ok(!h.node('detail-body').textContent.includes('Decision reference'));
  data.rows.reverse();data.rows.forEach((row,index)=>{row.rank=index+1;});
  hold.resolve(await read('/api/health'));await pending;
  assert.match(h.node('detail-title').textContent,new RegExp(selected.symbol));
  assert.match(h.node('detail-body').textContent,/Decision reference/);
});

test('removed or source-revised selected candidates cannot retain old price evidence',async()=>{
  for(const change of [data=>{data.rows=[];},data=>{data.rows[0]={...data.rows[0],source_digest:'d'.repeat(64)};}]) {
    const data=fixture(1),h=terminal(data);await h.refresh();await h.detail(data.rows[0]);change(data);await h.refresh();
    assert.ok(!h.node('detail-body').textContent.includes('Decision reference'));
    assert.match(h.node('detail-body').textContent,/no longer|changed|expired|unavailable/i);
  }
});

test('expiry invalidates selected X-Ray and late signal completion cannot restore it',async()=>{
  const data=fixture(1),h=terminal(data);await h.refresh();const hold=deferred(),read=data.read;
  h.readWith(async(route,params)=>route==='/api/signals'?hold.promise:read(route,params));
  const pending=h.detail(data.rows[0]);const expiry=h.timers.find(timer=>!timer.cancelled&&timer.delay>1000);assert.ok(expiry);
  expiry.callback();hold.resolve({items:[signal(data.rows[0])],total_count:1});await pending;
  assert.equal(h.state.rows.length,0);assert.ok(!h.node('detail-body').textContent.includes('Decision reference'));
});

test('a late older ranking read cannot replace the later accepted snapshot',async()=>{
  const data=fixture(2),h=terminal(data),hold=deferred(),read=data.read;let first=true;
  h.readWith(async(route,params)=>{if(route==='/api/opportunity-rankings'&&first){first=false;return hold.promise;}return read(route,params);});
  const older=h.refresh();await h.refresh();const accepted=h.state.rows.map(row=>row.candidate_id).join();
  hold.resolve({...data.page({limit:100,offset:0}),current_rows:[]});await older;
  assert.equal(h.state.rows.map(row=>row.candidate_id).join(),accepted);
});

test('closing a popup cancels a pending detail and returns focus to its exact surviving candidate',async()=>{
  const data=fixture(2),h=terminal(data);await h.refresh();const origin=h.buttons()[1];origin.focus();
  const hold=deferred(),read=data.read;h.readWith(async(route,params)=>route==='/api/signals'?hold.promise:read(route,params));
  const pending=h.detail(data.rows[1]);assert.equal(typeof h.closeDetail,'function');h.closeDetail();
  hold.resolve({items:[signal(data.rows[1])],total_count:1});await pending;
  assert.equal(h.node('detail').open,false);assert.equal(h.document.activeElement.dataset.candidateKey,origin.dataset.candidateKey);
  assert.ok(!h.node('detail-body').textContent.includes('Decision reference'));
});

test('signal lookup narrows supported source/time fields and never sends LONG as stored direction',async()=>{
  const data=fixture(1),h=terminal(data);await h.refresh();await h.detail(data.rows[0]);
  const query=data.calls.find(call=>call.route==='/api/signals').params;
  assert.equal(query.provider,SCOPE.provider);assert.equal(query.segment,SCOPE.segment);
  assert.equal(query.start_time,STAMP);assert.equal(query.end_time,STAMP);assert.ok(!Object.hasOwn(query,'direction'));
});

test('X-Ray exposes retained zones, checks, warnings, maturity, context and paper trigger safely',async()=>{
  const data=fixture(1),h=terminal(data);await h.refresh();await h.detail(data.rows[0]);
  const content=h.node('detail-body').textContent;
  for(const expected of ['Entry zone','100.5','101.5','volume.surge','Observed volume','LIQUIDITY_NOT_ESTABLISHED',
    'MECHANICS_VERIFIED','NOT_ESTABLISHED','CONTEXT_NOT_EVALUATED','informational','WAITING_FOR_LATER_TRIGGER','orb.close_cross.v1','<img src=x']) {
    assert.ok(content.includes(expected),expected+' must be visible');
  }
  assert.equal(h.node('detail-body').querySelectorAll('img').length,0);
});

test('health refresh clears the old session label on loading and error',async()=>{
  const data=fixture(1),h=terminal(data);await h.refresh();assert.match(h.node('session').textContent,/Synthetic/);
  const hold=deferred();h.readWith(async(route,params)=>{if(route==='/api/health')return hold.promise;return data.read(route,params);});
  const pending=h.refresh();assert.ok(!h.node('session').textContent.includes('Synthetic'));
  await tick();h.advance(31000);
  hold.resolve(Promise.reject(new Error('authored offline')));await pending;
  assert.ok(!h.node('session').textContent.includes('Synthetic'));assert.equal(h.node('source-status').dataset.state,'ERROR');
  assert.equal(h.state.rows.length,0,'a slow health read cannot extend the server ranking lifetime');
});
