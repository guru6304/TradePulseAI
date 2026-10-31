/* TradePulse's read-only intelligence workspace. No data acquisition or order calls. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const routes = {
    pulse: ['Pulse', '◈', 'YOUR MARKET, IN FOCUS', 'A clear view of what qualifies. And what needs to wait.'],
    opportunities: ['Opportunities', '≋', 'EVIDENCE BEFORE ACTION', 'Qualified setups, ranked transparently. Every condition in view.'],
    options: ['Options Lab', '⌘', 'UNDERLYING ≠ CONTRACT', 'Exact instruments. Observable premiums. Honest availability.'],
    strategies: ['Strategies & Research', '◇', 'KNOW THE RULES', 'Understand the setup, its trigger and the limits of its evidence.'],
    paper: ['Paper Portfolio', '▤', 'SIMULATION WITH A MEMORY', 'From pending setup to outcome. A retained, auditable record.'],
    health: ['Health & Settings', '⊙', 'SOURCE & SYSTEM', 'Operational detail, kept separate from your market decisions.']
  };
  const names = {
    strat_1_order_block:'Order Block / BOS / FVG',strat_2_vwap_pullback:'VWAP Pullback',strat_3_option_apex_oi:'Option Apex',strat_4_orb_filtered:'Opening Range Breakout',strat_5_supertrend_pullback:'Supertrend Pullback'};
  const state = {
    route:'pulse', routeGeneration:0, health:null, ranks:null, paper:null, rows:[], generation:0, controllers:new Set(), expiry:null, page:0, query:'', direction:'', strategy:'', detailGeneration:0, paperCursor:null,
    rankState:'LOADING', rankMessage:'Reading retained priority…', selected:null, detailReturnKey:null};
  const text = value => typeof value === 'string' && value.trim() ? value : 'Unavailable';
  const num = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-IN',{
    maximumFractionDigits:2}
  ) : '—';
  function sourceTime(value, {requireOffset=false}={}) {
    if(typeof value!=='string')return NaN;
    // Stored application timestamps use this exact naive IST format. Feed/rank
    // timestamps remain offset-qualified; the browser's local zone is irrelevant.
    let fields=/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/.exec(value);
    let zone='+05:30';
    if(fields){
      if(requireOffset)return NaN;
    }else{
      fields=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
      if(!fields)return NaN;
      zone=fields[8];
    }
    const [year,month,day,hour,minute,second]=fields.slice(1,7).map(Number);
    const leap=year%4===0&&(year%100!==0||year%400===0);
    const days=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
    if(year<1||month<1||month>12||day<1||day>days[month-1]||hour>23||minute>59||second>59)return NaN;
    let offset=0;
    if(zone!=='Z'){
      const hours=Number(zone.slice(1,3)),minutes=Number(zone.slice(4,6));
      if(hours>23||minutes>59)return NaN;
      offset=(zone[0]==='+'?1:-1)*(hours*60+minutes);
    }
    const date=new Date(0);
    date.setUTCFullYear(year,month-1,day);
    date.setUTCHours(hour,minute,second,Number((fields[7]||'').padEnd(3,'0').slice(0,3)));
    return date.getTime()-offset*60000;
  }
  const time = value => {
    const parsed=sourceTime(value);
    return Number.isFinite(parsed)?new Intl.DateTimeFormat('en-IN',{
      timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',day:'2-digit',month:'short',hour12:false}
    ).format(parsed)+' IST':'Time unavailable';
  };
  function el(tag, cls, content) {
    const node=document.createElement(tag);
    if(cls)node.className=cls;
    if(content!==undefined)node.textContent=String(content);
    return node;
  }
  function append(parent,...nodes){
    nodes.forEach(n=>parent.append(n));
    return parent;
  }
  function link(label,route,cls=''){
    const a=el('a',cls,label);
    a.href='#/'+route;
    return a;
  }
  function button(label,action,cls='button secondary'){
    const b=el('button',cls,label);
    b.type='button';
    b.addEventListener('click',action);
    return b;
  }
  function badge(label,cls=''){
    return el('span','badge '+cls,label);
  }
  function heading(title,sub,route){
    const h=el('div','section-heading');
    const d=append(el('div'),el('h2','',title));
    if(sub)d.append(el('p','',sub));
    h.append(d);
    if(route)h.append(link('View all →',route));
    return h;
  }
  function panel(title,description){
    return append(el('div','panel'),el('h3','',title),el('p','',description));
  }
  function availability(title,description){
    return append(el('div','availability'),el('h2','',title),el('p','',description));
  }
  function fact(label,value){
    return append(el('div','fact'),el('small','',label),el('strong','',value));
  }
  function row(label,value,sub){
    const r=el('div','mini-row');
    const d=el('div','',label);
    if(sub)d.append(el('small','',sub));
    return append(r,d,el('span','',value));
  }
  async function get(path,params={
  }
  ) {
    const controller=new AbortController();
    state.controllers.add(controller);
    const timer=setTimeout(()=>controller.abort(),8000);
    try{
      const url=new URL(path,location.origin);
      Object.entries(params).forEach(([k,v])=>{
        if(v!==undefined&&v!==null&&v!=='')url.searchParams.set(k,String(v));
      }
      );
      const response=await fetch(url,{
        method:'GET',headers:{
          Accept:'application/json'}
        ,cache:'no-store',credentials:'same-origin',signal:controller.signal}
      );
      if(!response.ok)throw new Error('Stored evidence unavailable');
      const payload=await response.json();
      if(!payload||typeof payload!=='object'||Array.isArray(payload))throw new Error('Malformed stored evidence');
      return payload;
    }
    finally{
      clearTimeout(timer);
      state.controllers.delete(controller);
    }
  }
  function current(){
    return state.ranks&&state.ranks.actionable===false&&state.ranks.status==='CURRENT_CANDIDATE_PRIORITY';
  }
  function filtered(){
    return state.rows.filter(r=>(!state.query||String(r.symbol).toLowerCase().includes(state.query))&&(!state.direction||r.direction===state.direction)&&(!state.strategy||r.strategy_id===state.strategy));
  }
  function focusedKey(){
    const active=document.activeElement;
    return active&&$('view').contains(active)?active.dataset.restoreFocusKey||active.dataset.focusKey:null;
  }
  function restoreViewFocus(key){
    if(!key)return;
    const target=[...$('view').querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===key);
    if(target&&!target.disabled){target.focus({preventScroll:true});return;}
    const status=$('ranking-status');
    if(status){status.dataset.restoreFocusKey=key;status.focus({preventScroll:true});}
  }
  function candidateButton(label,candidate,cls=''){
    const node=button(label,()=>detail(candidate),cls);
    node.dataset.candidateKey=candidate.opportunity_key;
    node.dataset.focusKey='candidate:'+candidate.opportunity_key;
    node.setAttribute('aria-label','Inspect '+candidate.symbol+' · '+(names[candidate.strategy_id]||candidate.strategy_id));
    node.setAttribute('aria-pressed',String(state.selected?.key===candidate.opportunity_key));
    return node;
  }
  function selectedSource(candidate){
    return {key:candidate.opportunity_key,candidate:candidate.candidate_id,
      identity:stable(candidate.instrument_identity),watermark:sourceTime(candidate.source_data_watermark,{requireOffset:true}),
      digest:candidate.source_digest};
  }
  function sameSelectedSource(candidate,selected){
    return stable(selectedSource(candidate))===stable(selected);
  }
  function invalidateSelection(message){
    state.detailGeneration++;
    state.selected=null;
    $('detail-body').dataset.state='UNAVAILABLE';
    $('detail-body').replaceChildren(availability('Selected evidence unavailable',message));
  }
  function closeDetail(returnFocus=true){
    const key=state.detailReturnKey;
    state.detailReturnKey=null;
    state.selected=null;
    state.detailGeneration++;
    if($('detail').open)$('detail').close();
    $('detail-body').replaceChildren();
    $('detail-body').dataset.state='CLOSED';
    if(returnFocus&&key&&state.route==='opportunities'){
      const index=filtered().findIndex(row=>'candidate:'+row.opportunity_key===key);
      if(index>=0)state.page=Math.floor(index/20);
    }
    if(['pulse','opportunities'].includes(state.route))render();
    if(returnFocus&&key){
      const target=[...$('view').querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===key);
      (target||$('refresh-data')).focus({preventScroll:true});
    }
  }
  async function collectRankings(generation){
    const rows=[],keys=new Set(),candidates=new Set(),identities=new Set(),symbols=new Set();
    let first,binding,total,deadline=Infinity;
    for(let offset=0;offset===0||offset<total;offset+=100){
      const sent=performance.now();
      const data=await get('/api/opportunity-rankings',{limit:100,offset,...(first?{run_id:first.snapshot.run_id}:{})});
      if(generation!==state.generation)return null;
      if(offset===0&&data.status!=='CURRENT_CANDIDATE_PRIORITY')return {data,rows:[],lifetime:null};
      const page=data.pagination||{},snapshot=data.snapshot||{},scope=data.scope||{};
      const until=sourceTime(snapshot.valid_until,{requireOffset:true}),asOf=sourceTime(data.as_of,{requireOffset:true});
      const stamp=sourceTime(snapshot.reference,{requireOffset:true});
      const hex=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
      const named=value=>typeof value==='string'&&value.length>0&&value.length<=160&&value.trim()===value;
      if(data.status!=='CURRENT_CANDIDATE_PRIORITY'||data.actionable!==false||!named(snapshot.run_id)||!named(snapshot.work_id)||!hex(snapshot.rank_version)||
        !Number.isFinite(until)||!Number.isFinite(asOf)||!Number.isFinite(stamp)||until<asOf||
        !named(scope.provider)||!['LIVE','SIMULATED'].includes(scope.data_mode)||scope.segment!=='NSE_EQUITY_INTRADAY'||!hex(scope.profile_digest)||
        stable(scope)!==stable(snapshot.scope)||page.limit!==100||page.offset!==offset||!Number.isInteger(page.total)||page.total<0||page.total>512||
        !Array.isArray(data.current_rows)||data.current_rows.length!==Math.min(100,page.total-offset))throw new Error('Invalid ranking page');
      const currentBinding=stable({run:snapshot.run_id,work:snapshot.work_id,version:snapshot.rank_version,
        scope,reference:snapshot.reference,until:snapshot.valid_until,policy:snapshot.policy});
      if(first&&(binding!==currentBinding||total!==page.total))throw new Error('Inconsistent ranking pages');
      if(!first){first=data;binding=currentBinding;total=page.total;}
      deadline=Math.min(deadline,sent+until-asOf);
      for(const [index,row]of data.current_rows.entries()){
        const id=row&&row.instrument_identity;
        if(!row||row.actionable!==false||!named(row.symbol)||!named(row.opportunity_key)||!named(row.candidate_id)||
          row.rank!==offset+index+1||!hex(row.source_digest)||!Number.isFinite(sourceTime(row.source_data_watermark,{requireOffset:true}))||
          !['LONG','SHORT'].includes(row.direction)||row.position_type!==(row.direction==='LONG'?'LONG_EQUITY_INTRADAY':'SHORT_EQUITY_INTRADAY')||
          !id||!named(id.identifier)||id.symbol!==row.symbol||id.provider!==scope.provider||id.segment!==scope.segment||id.exchange!=='NSE'||id.instrument_type!=='EQ'||id.is_index!==false||
          !named(row.strategy_id)||keys.has(row.opportunity_key)||candidates.has(row.candidate_id)||symbols.has(row.symbol)||
          identities.has(stable([id.provider,id.identifier,id.exchange,id.segment,id.instrument_type])))throw new Error('Invalid ranking identity');
        keys.add(row.opportunity_key);candidates.add(row.candidate_id);symbols.add(row.symbol);
        identities.add(stable([id.provider,id.identifier,id.exchange,id.segment,id.instrument_type]));rows.push(row);
      }
    }
    const lifetime=deadline-performance.now();
    if(!Number.isFinite(lifetime)||lifetime<0)throw new Error('Ranking expired during collection');
    return {data:first,rows,deadline};
  }
  function mode(health){
    if(health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO')return 'DEMO · SYNTHETIC TEST DATA · NOT LIVE';
    if(health.evidence_scope==='OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE')return 'Offline fixture · not live';
    const b=health.broker||{
    };
    if(health.evidence_scope==='NO_SOURCE'||b.data_mode==='UNAVAILABLE')return 'No source available';
    if(b.is_simulated||b.data_mode==='SIMULATED')return 'Simulated source';
    if(b.data_mode==='LIVE')return 'Live source unverified';
    return 'Source unverified';
  }
  function sourceState(health) {
    if(health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO')return 'DETERMINISTIC_OFFLINE_DEMO';
    const broker=health.broker||{};
    if(health.evidence_scope==='NO_SOURCE'||broker.data_mode==='UNAVAILABLE')return 'NO_SOURCE';
    if(broker.is_simulated||broker.data_mode==='SIMULATED')return 'SIMULATED';
    return 'UNVERIFIED';
  }
  function sessionLabel(health) {
    if(health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO')return 'Synthetic demo / IST';
    const known={OPEN:'Market open',MARKET_OPEN:'Market open',CLOSED:'Market closed',MARKET_CLOSED:'Market closed',
      PRE_OPEN:'Before market',POST_CLOSE:'After market',WEEKEND:'Weekend',HOLIDAY:'Market holiday'};
    return (known[(health.scheduler||{}).session_state]||'Session unverified')+' / IST';
  }
  function navigation(){
    for(const [key,value]of Object.entries(routes)){
      const a=link('',key,key==='health'?'utility':'');
      a.setAttribute('aria-label',value[0]);
      append(a,el('span','nav-icon',value[1]),el('span','nav-label',value[0]));
      $('desktop-nav').append(a);
    }
    for(const key of ['pulse','opportunities','options','paper']){
      const a=link('',key);
      a.setAttribute('aria-label',routes[key][0]);
      append(a,el('span','nav-icon',routes[key][1]),el('span','',key==='opportunities'?'Discover':routes[key][0]));
      $('mobile-nav').append(a);
    }
    const more=button('',()=>{
      const open=$('more-menu').hidden;
      $('more-menu').hidden=!open;
      more.setAttribute('aria-expanded',String(open));
    }
    ,'');
    more.id='more-button';
    more.setAttribute('aria-label','More destinations');
    more.setAttribute('aria-expanded','false');
    more.setAttribute('aria-controls','more-menu');
    append(more,el('span','nav-icon','•••'),el('span','','More'));
    $('mobile-nav').append(more);
    for(const key of ['strategies','health'])$('more-menu').append(link(routes[key][0],key));
  }
  function navigate() {
    state.routeGeneration++;
    const key = location.hash.slice(1).replace(/^\//, '').split('?')[0] || 'pulse';
    state.route = routes[key] ? key : 'pulse';
    const route = routes[state.route];
    document.title = route[0] + ' / TradePulse AI';
    $('page-title').textContent = route[0];
    $('eyebrow').textContent = route[2];
    $('page-description').textContent = route[3];
    $('view').setAttribute('aria-label', route[0] + ' content');
    $('more-menu').hidden = true;
    $('more-button').setAttribute('aria-expanded', 'false');
    document.querySelectorAll('nav a').forEach(anchor => {
      if (anchor.hash === '#/' + state.route) anchor.setAttribute('aria-current', 'page');
      else anchor.removeAttribute('aria-current');
    });
    if ($('detail').open) closeDetail(false);
    else state.detailGeneration++;
    render();
    if (!['pulse', 'opportunities'].includes(state.route)) loadRoute();
  }
  function candidateCard(candidate){
    const card=el('article','candidate');
    card.dataset.candidateKey=candidate.opportunity_key||candidate.candidate_id;
    card.dataset.symbol=candidate.symbol;
    append(card,append(el('div','candidate-top'),el('span','rank','#'+num(candidate.rank)+' priority'),badge(text(candidate.direction),candidate.direction==='LONG'?'positive':'negative')),el('h3','',text(candidate.symbol)),el('p','strategy',names[candidate.strategy_id]||text(candidate.strategy_id)),el('p','why',reason(candidate)));
    const m=el('div','metrics');
    for(const [label,value]of [['Rule quality',num((candidate.score_components||{
    }
    ).rule_quality)],['Gross T1 R:R',num((candidate.score_components||{
    }
    ).actual_target1_rr)]])append(m,append(el('div'),el('small','',label),el('strong','',value)));
    card.append(m,el('p','chart-note','Source candle: '+time(candidate.source_data_watermark)),candidateButton('Explore evidence ↗',candidate,'button secondary'));
    return card;
  }
  function reason(r){
    return {
      NEWLY_QUALIFIED:'Newly qualified in the latest retained scan.',SCORE_COMPONENT_CHANGED:'Its measured setup inputs changed.',RELATIVE_ORDER_CHANGED:'Other qualified candidates changed order.',UNCHANGED_PRIORITY:'Priority is unchanged from the previous snapshot.'}
    [r.rank_change_reason]||'Priority follows retained rule quality and gross reward/risk.';
  }
  function pulse(){
    const view=$('view');
    const rows=filtered();
    view.append(heading('The opportunity shortlist','Qualified candidate evidence · never an automatic entry instruction','opportunities'));
    if(current()&&rows.length){
      const cards=el('div','cards');
      rows.slice(0,3).forEach(r=>cards.append(candidateCard(r)));
      view.append(cards);
    }
    else{
      const hero=el('div','hero');
      const copy=el('div');
      const hasSource=!!state.health;
      append(copy,badge(state.query?'SEARCH RESULTS':current()?'NO QUALIFIED SETUPS':hasSource?'WAITING FOR QUALIFIED EVIDENCE':'NO SOURCE', 'caution'),el('h2','',state.query?'No qualified match for this instrument.':current()?'Patience is a position, too.':hasSource?'A clear signal starts with clear evidence.':'Your market view is waiting for a source.'),el('p','',state.query?'Search applies only to the retained ranked candidates. It does not acquire a new instrument or broaden the watchlist.':current()?'The latest stored scan has no qualifying candidate. Nothing is promoted just to fill this space. Review the strategy rules or inspect source coverage.':'Current candidate priority is unavailable. Read the source status and latest completed observations before interpreting an opportunity.'));
      append(copy,append(el('div','actions'),link('Inspect source →','health','button'),link('Explore the rules','strategies','button secondary')));
      append(hero,copy,el('div','hero-symbol','⌁'));
      view.append(hero);
    }
    const split=el('div','split');
    const movers=el('div');
    movers.append(heading('What changed','Rank movement, with a reason'));
    const movePanel=el('div','panel');
    if(current()&&rows.length)rows.slice(0,3).forEach(r=>movePanel.append(row(text(r.symbol),'#'+num(r.rank),reason(r)+' Previous rank '+num(r.previous_rank))));
    else movePanel.append(el('p','','No current rank transitions to interpret. Historical results remain separate from current opportunities.'));
    movers.append(movePanel);
    const paper=el('div');
    paper.append(heading('Paper, with perspective','Simulation status · no real brokerage orders','paper'));
    const pp=el('div','panel');
    if(state.paper&&state.paper.reconciliation&&state.paper.reconciliation.status==='OK'){
      const a=state.paper.accounting||{
      };
      append(pp,row('Open positions',num(a.open_positions)),row('Closed positions',num(a.closed_positions)),el('p','','Marks and retained financial evidence are available in Paper Portfolio.'));
    }
    else append(pp,el('h3','',state.paper?'Reconciliation needs attention':'No paper summary available'),el('p','','A missing report is not a zero balance. No account or position is created by this view.'));
    paper.append(pp);
    append(split,movers,paper);
    view.append(split,heading('Market radar','Movement context is separate from strategy qualification'),panel('No verified radar feed','Breadth, sector participation and raw movers are not inferred from the ranked shortlist. This area remains unavailable until an admissible source supplies them.'));
  }
  function opportunities(){
    const view=$('view');
    const toolbar=el('div','toolbar');
    for(const [key,label,values]of [['direction','All directions',['LONG','SHORT']],['strategy','All strategies',Object.keys(names)]]){
      const s=el('select');
      s.id='opportunity-'+key;
      s.dataset.focusKey='filter:'+key;
      s.setAttribute('aria-label',label);
      const any=el('option','',label);
      any.value='';
      s.append(any);
      values.forEach(v=>{
        const o=el('option','',names[v]||v);
        o.value=v;
        s.append(o);
      }
      );
      s.value=state[key];
      s.addEventListener('change',()=>{
        state[key]=s.value;
        state.page=0;
        render();
      }
      );
      toolbar.append(s);
    }
    const reset=button('Reset filters',()=>{
      state.query='';state.direction='';state.strategy='';state.page=0;$('search').value='';render();
    },'quiet');
    reset.id='opportunity-reset';reset.dataset.focusKey='filter:reset';toolbar.append(reset);
    view.append(toolbar);
    const status=el('p','chart-note',state.rankMessage);
    status.id='ranking-status';status.dataset.state=state.rankState;
    status.setAttribute('role','status');status.setAttribute('tabindex','-1');
    view.append(status);
    if(!current()){
      const labels={LOADING:'Reading retained priority',ERROR:'Priority could not be verified',ARCHIVED:'Historical evidence only',UNAVAILABLE:'Current priority is unavailable'};
      view.append(availability(labels[state.rankState]||'Current priority is unavailable',state.rankMessage));
      const retry=button('Retry stored evidence',refresh,'quiet');retry.dataset.focusKey='ranking:retry';view.append(retry);
      opportunityPager(0);
      return;
    }
    const rows=filtered();
    if(!rows.length){
      view.append(availability(state.rows.length?'No candidates match':'No qualified setups retained',state.rows.length?'Try another instrument, direction or strategy. Filters inspect the entire retained snapshot.':'This current snapshot has no qualifying candidate. Refresh only reads stored evidence.'));
      opportunityPager(0);
      return;
    }
    const table=el('table');
    const tr=el('tr');
    ['Rank / change','Instrument','Strategy','Direction','Quality','Gross T1 R:R'].forEach(t=>tr.append(el('th','',t)));
    table.append(append(el('thead'),tr));
    const body=el('tbody');
    state.page=Math.min(Math.max(0,state.page),Math.ceil(rows.length/20)-1);
    rows.slice(state.page*20,state.page*20+20).forEach(r=>{
      const line=el('tr');
      line.dataset.candidateKey=r.opportunity_key||r.candidate_id;
      append(line,el('td','','#'+num(r.rank)+' · prior '+num(r.previous_rank)),append(el('td'),candidateButton(text(r.symbol),r),el('small','',time(r.source_data_watermark))),el('td','',names[r.strategy_id]||text(r.strategy_id)),el('td','',text(r.direction)),el('td','',num((r.score_components||{
      }
      ).rule_quality)),el('td','',num((r.score_components||{
      }
      ).actual_target1_rr)));
      body.append(line);
    }
    );
    table.append(body);
    view.append(append(el('div','table-wrap'),table));
    opportunityPager(rows.length);
    view.append(el('p','chart-note','Quality measures detector rules, not a win probability. Net executable reward is unavailable when spread and other inputs are missing.'));
  }
  function opportunityPager(count){
    state.page=Math.min(Math.max(0,state.page),Math.max(0,Math.ceil(count/20)-1));
    const nav=el('div','pagination');
    const prev=button('← Previous',()=>{
      state.page=Math.max(0,state.page-1);
      render();
    }
    ,'quiet');
    prev.disabled=state.page===0;
    prev.id='opportunity-prev';prev.dataset.focusKey='page:previous';
    const next=button('Next →',()=>{
      state.page++;
      render();
    }
    ,'quiet');
    next.disabled=(state.page+1)*20>=count;
    next.id='opportunity-next';next.dataset.focusKey='page:next';
    const info=el('span','','Page '+(state.page+1)+' / '+Math.max(1,Math.ceil(count/20))+' · '+num(count)+' matching / '+num(state.rows.length)+' retained candidates');
    info.id='opportunity-page';
    append(nav,prev,info,next);$('view').append(nav);
  }
  function render(){
    const focus=focusedKey();
    const view=$('view');
    view.replaceChildren();
    if(state.route==='pulse')pulse();
    else if(state.route==='opportunities')opportunities();
    else view.append(availability('Reading retained evidence…','This view only inspects existing records.'));
    restoreViewFocus(focus);
  }
  async function refresh(){
    const generation=++state.generation;
    state.detailGeneration++;
    if($('detail').open){
      const owned=$('detail-body').contains(document.activeElement);
      $('detail-body').dataset.state='REQUALIFYING';
      $('detail-body').replaceChildren(el('p','muted','Requalifying selected evidence… Previous prices are withheld.'));
      if(owned)$('close-detail').focus({preventScroll:true});
    }
    state.controllers.forEach(c=>c.abort());
    clearTimeout(state.expiry);
    state.health=null;
    state.ranks=null;
    state.rows=[];
    state.paper=null;
    state.rankState='LOADING';
    state.rankMessage='Reading the complete retained ranking snapshot…';
    $('notice').textContent='Reading stored evidence...';
    $('source-mode').textContent='Checking source';
    $('source-time').textContent='Awaiting evidence';
    $('source-status').dataset.state='LOADING';
    $('session').textContent='Session unverified / IST';
    render();
    const results=await Promise.allSettled([get('/api/health'),collectRankings(generation)]);
    if(generation!==state.generation)return;
    if(results[0].status==='fulfilled'){
      const health=results[0].value;
      state.health=health;
      $('source-mode').textContent=mode(health);
      $('source-status').dataset.state=sourceState(health);
      $('source-time').textContent=time((health.broker||{
      }
      ).last_candle_timestamp_ist);
      $('session').textContent=sessionLabel(health);
      $('notice').textContent=health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO'?'DEMO - SYNTHETIC TEST DATA - NOT LIVE':'';
    }
    else{
      $('source-mode').textContent='Source unavailable';
      $('source-status').dataset.state='ERROR';
      $('source-time').textContent='No cached health retained';
      $('session').textContent='Session unverified / IST';
      $('notice').textContent='Source health could not be read. Independent retained results are not live acceptance.';
    }
    if(results[1].status==='fulfilled'&&results[1].value){
      const {data,rows,deadline}=results[1].value;
      const lifetime=deadline-performance.now();
      state.ranks=data;
      if(data.status==='CURRENT_CANDIDATE_PRIORITY'&&Number.isFinite(lifetime)&&lifetime>=0){
        state.rows=rows;
        state.rankState=rows.length?'CURRENT':'EMPTY';
        state.rankMessage=rows.length+' retained candidates · complete snapshot · filters do not acquire data.';
        state.expiry=setTimeout(()=>{
          if(generation===state.generation){
            state.rows=[];
            state.ranks={
              ...data,status:'ARCHIVED_EXPIRED'};
            state.rankState='ARCHIVED';
            state.rankMessage='Candidate evidence has expired. Refresh reads stored evidence.';
            invalidateSelection('This selected candidate has expired. No previous prices are retained.');
            $('notice').textContent='Candidate evidence has expired. Refresh reads stored evidence; it does not acquire new data.';
            if(['pulse','opportunities'].includes(state.route))render();
          }
        }
        ,lifetime+1);
      }
      else{
        if(data.status==='CURRENT_CANDIDATE_PRIORITY')state.ranks={...data,status:'ARCHIVED_EXPIRED'};
        state.rankState=['RANKING_UNAVAILABLE_NO_DURABLE_SCAN','UNAVAILABLE'].includes(data.status)?'UNAVAILABLE':'ARCHIVED';
        state.rankMessage=state.rankState==='UNAVAILABLE'?'No durable ranking snapshot is available for this source. Refresh only reads existing evidence.':
          'No current priority: '+text(state.ranks.status)+'. Historical evidence does not establish a current opportunity.';
      }
    }else{
      state.rankState='ERROR';
      state.rankMessage='The complete ranking snapshot could not be verified. No cached or partial ranks are retained. Retry the stored read.';
    }
    if(['pulse','opportunities'].includes(state.route))render();
    else loadRoute();
    if(state.selected&&$('detail').open){
      const selected=state.selected;
      const match=state.rows.find(row=>row.opportunity_key===selected.key&&sameSelectedSource(row,selected));
      if(current()&&match)await detail(match);
      else invalidateSelection('The selected candidate is no longer current or its source changed. Select a qualified row to inspect new evidence.');
    }
    if(generation!==state.generation)return;
    if(state.health&&state.health.paper_account_id){
      try{
        const paper=await get('/api/paper-portfolio',{
          account_id:state.health.paper_account_id}
        );
        if(generation!==state.generation)return;
        state.paper=paper;
        if(state.route==='pulse')render();
        else if(state.route==='paper')loadRoute();
      }
      catch(error){
        /* Missing financial evidence stays unavailable. */}
    }
  }
  async function loadRoute(){
    const route=state.route,generation=state.generation,routeGeneration=++state.routeGeneration;
    const valid=()=>route===state.route&&generation===state.generation&&routeGeneration===state.routeGeneration;
    const view=$('view');
    try{
      if(route==='options'){
        const data=await get('/api/oi-snapshots',{
          limit:10}
        );
        if(!valid())return;
        view.replaceChildren(availability('Contract viability comes first','A directional underlying signal does not establish a tradable option. Exact expiry, strike, CE/PE, observed premium and liquidity must qualify separately.'));
        const items=Array.isArray(data.items)?data.items:[];
        view.append(heading('Retained option observations',items.length+' snapshots · historical context, not an executable chain'));
        if(!items.length)view.append(panel('No admissible option snapshot','Premium, OI, IV, Greeks and spread remain unavailable. No synthetic chain is substituted.'));
        items.forEach(s=>view.append(panel(text(s.symbol||s.underlying), 'Observed '+time(s.snapshot_timestamp||s.timestamp)+' · Contract execution authority is not established by a stored snapshot.')));
      }
      else if(route==='strategies'){
        const data=await get('/api/backtest-eligibility');
        if(!valid())return;
        view.replaceChildren();
        view.append(availability('Rules are inspectable. Edge must be earned.','A completed detection is not a future entry. Each strategy needs its own later trigger, source lineage and paper evidence. No win rate is inferred from passing software tests.'));
        const contracts=[['strat_1_order_block','Retest of a qualified order block with BOS/FVG context. Future lifecycle acceptance remains strategy-specific.'],['strat_2_vwap_pullback','Completed VWAP touch and directional reclaim/rejection with EMA, volume and RSI conditions. Later paper triggering uses an explicitly versioned policy.'],['strat_3_option_apex_oi','Underlying/OI context and long CE/PE selection. Exact qualified contracts and premium observations remain mandatory.'],['strat_4_orb_filtered','Completed opening-range breakout with VWAP, RSI and relative-volume confirmation. Later close-cross paper evidence is separate.'],['strat_5_supertrend_pullback','Trend-aligned pullback with Supertrend, EMA, VWAP and volume conditions. No universal next-close rule.']];
        contracts.forEach(([key,description])=>{
          const block=panel(names[key],description);
          block.append(badge('MECHANICS ≠ EMPIRICAL EDGE','caution'));
          const meta=(data.strategies||{
          }
          )[key];
          if(meta)block.append(el('p','','Research eligibility: '+text(meta.status||meta.reason_code||meta.reason)));
          block.style.marginTop='16px';
          view.append(block);
        }
        );
      }
      else if(route==='paper'){
        view.replaceChildren();
        if(!state.health||!state.health.paper_account_id){
          view.append(availability('No paper account is configured','An account is not created by visiting this page. Source and account configuration can be inspected in Health.'));
          return;
        }
        const p=state.paper;
        if(!p){
          view.append(availability('Paper evidence unavailable','The latest report could not be verified. No cached financial values are shown.'));
          return;
        }
        const safe=(p.reconciliation||{
        }
        ).status==='OK';
        view.append(badge(safe?'RECONCILED RETAINED EVIDENCE':'RECONCILIATION REQUIRED',safe?'positive':'caution'));
        if(!safe){
          view.append(availability('Accounting is withheld','Retained paper evidence requires inspection before balances or outcomes can be interpreted.'));
          return;
        }
        view.append(el('p','chart-note','Snapshot '+time(p.as_of_ist)+' · retained observations do not establish current quotes.'));
        const a=p.accounting||{
        };
        const facts=el('div','facts');
        append(facts,fact('Open positions',num(a.open_positions)),fact('Closed positions',num(a.closed_positions)),fact('Fees paid · INR',num(a.fees_paid_inr)));
        view.append(facts);
        for(const [title,key,total]of [['Positions','positions',p.total_positions],['Setups & decisions','candidate_decisions',p.total_candidate_decisions],['Event timeline','events',p.total_events]]){
          view.append(heading(title,'Preview '+Math.min(40,(p[key]||[]).length)+' / '+num(total)+' retained records'));
          (p[key]||[]).slice(0,40).forEach(item=>{
            const candidate=item.candidate||{
            };
            const d=el('article','evidence');
            append(d,el('h3','',text(item.symbol||candidate.symbol||item.kind)+' · '+text(item.status||(item.result||{
            }
            ).status)),el('p','',text(item.reason_code||item.exit_reason||(item.result||{
            }
            ).reason_code)),el('p','','Trigger: '+text((item.trigger_contract||{
            }
            ).rule_id)+' · '+time(item.trigger_timestamp_ist||item.fill_timestamp_ist||item.timestamp_ist)));
            view.append(d);
          }
          );
          if(!(p[key]||[]).length)view.append(el('p','muted','No rows in this preview.'));
        }
        view.append(el('p','chart-note','Current unrealized P&L is not summarized here: mark freshness and position-level evidence must be inspected before interpreting it.'));
      }
      else if(route==='health'){
        const results=await Promise.allSettled([get('/api/config'),get('/api/scans',{
          limit:10}
        )]);
        if(!valid())return;
        view.replaceChildren(availability(state.health?'Read-only system inspection':'The evidence service is unavailable','No provider authentication, scan, account creation or brokerage operation is performed by this workspace.'));
        if(state.health){
          const h=state.health;
          view.append(append(el('div','facts'),fact('Source',mode(h)),fact('Database',text((h.database||{
          }
          ).status)),fact('Scheduler',(h.scheduler||{
          }
          ).running?'Running':'Not running')));
        }
        view.append(heading('Recent retained scans','A scan record does not establish current live acceptance'));
        const scans=results[1].status==='fulfilled'?results[1].value.items:[];
        (Array.isArray(scans)?scans:[]).forEach(s=>view.append(row(text(s.status||s.scan_status),time(s.completed_at_ist||s.completed_at),text(s.provider||s.broker))));
        if(!scans||!scans.length)view.append(panel('No scan history available','Existing records may be absent or the read service unavailable.'));
        view.append(el('p','chart-note','Bounded read-only preview. Extended diagnostics and paper-ledger pagination remain separate acceptance work.'));
      }
    }
    catch(error){
      if(valid())view.replaceChildren(availability('This evidence is unavailable','The latest read failed. Previous values have been cleared. Refresh to retry; no background acquisition is triggered.'));
    }
  }
  function stable(value){
    if(Array.isArray(value))return '['+value.map(stable).join(',')+']';
    if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(', ')+'}';
    return JSON.stringify(value);
  }
  function retainedDetails(body,signal,candidate){
    const evaluation=signal.candidate_evaluation||{};
    const rules=(evaluation.explanation||{}).rule_evaluation||{};
    const checks=el('section','evidence');
    checks.append(el('h3','','Retained rule checks'),el('p','',text(rules.summary)));
    const items=Array.isArray(rules.rule_checks)?rules.rule_checks:[];
    items.slice(0,60).forEach(rule=>checks.append(el('p','',text(rule.rule_id)+' · '+text(rule.status)+' · '+text(rule.reason))));
    if(!items.length)checks.append(el('p','','Rule checks unavailable for this retained signal.'));
    const warnings=Array.isArray(evaluation.warnings)?evaluation.warnings:[];
    checks.append(el('p','','Warnings: '+(warnings.length?warnings.map(text).join(', '):'None retained.')));
    body.append(checks);
    const maturity=signal.strategy_evidence||evaluation.strategy_evidence||{};
    body.append(panel('Strategy evidence','Maturity: '+text(maturity.maturity_state)+' · Empirical evidence: '+text(maturity.empirical_status)+
      (maturity.explanation?' · '+text(maturity.explanation):'')+' · Software checks do not establish a win probability.'));
    const block=el('section','evidence');
    block.append(el('h3','','Informational context'),el('p','','Context is informational only. It cannot change strategy qualification, ranking or actionability. Missing context is not neutral.'));
    const context=signal.context,records=context&&Array.isArray(context.records)?context.records:[];
    const bound=context&&['QUALIFIED','WARNING_ONLY','UNAVAILABLE','MISSING'].includes(context.status)&&
      context.candidate_id===candidate.candidate_id&&context.actionable===false&&context.affects_ranking===false;
    const qualified=bound&&(context.status!=='QUALIFIED'||records.length>0&&records.every(record=>
      stable(record.instrument_identity)===stable(candidate.instrument_identity)&&record.verification?.allowed===true&&
      record.verification?.status==='QUALIFIED_UNDER_LOCAL_POLICY'&&record.freshness?.status==='FRESH'&&!record.retracted&&!record.conflict));
    if(!qualified)block.append(el('p','','Context unavailable: qualification or candidate mapping could not be verified.'));
    else{
      block.append(el('p','',context.status+' · '+(Array.isArray(context.reason_codes)?context.reason_codes.map(text).join(', '):'No reason retained')),
        el('p','',text(context.evaluation_mode)+' · As of '+time(context.as_of)+' · Original decision '+time(context.decision_at)));
      records.slice(0,8).forEach(record=>{
        if(stable(record.instrument_identity)!==stable(candidate.instrument_identity)){
          block.append(el('p','','Context record withheld: instrument mapping conflict.'));return;
        }
        block.append(el('p','',text(record.title||record.headline||record.record_id)+' · '+text(record.source_name||record.source)+
          ' · Published '+time(record.published_at)+' · Freshness '+text(record.freshness?.status)+
          ' · '+(Array.isArray(record.reason_codes)?record.reason_codes.map(text).join(', '):'')));
      });
      if(signal.context_alert_decision)block.append(el('p','','Context alert: '+text(signal.context_alert_decision.status)+' · '+text(signal.context_alert_decision.reason_code)+' · No delivery is performed here.'));
    }
    body.append(block);
    const paper=signal.paper_decision||{},trigger=paper.trigger_contract||{};
    body.append(panel('Paper trigger evidence',text(paper.status)+' · '+text(paper.reason_code)+' · Rule '+text(trigger.rule_id)+
      ' · Trigger '+time(paper.trigger_timestamp_ist)+' · '+text(signal.recommendation_status||'CANDIDATE_ONLY')+
      ' · Displayed decision levels are a retained reference. A later paper trigger needs its own versioned rule.'));
  }
  async function detail(candidate){
    const generation=++state.detailGeneration;
    state.selected=selectedSource(candidate);
    state.detailReturnKey='candidate:'+candidate.opportunity_key;
    if(['pulse','opportunities'].includes(state.route))render();
    const dialog=$('detail');
    $('detail-title').textContent=text(candidate.symbol)+' · '+text(candidate.direction);
    const body=$('detail-body');
    body.dataset.state='LOADING';
    body.replaceChildren(el('p','muted','Reading exact retained setup and source…'));
    if(!dialog.open)dialog.showModal();
    const valid=()=>generation===state.detailGeneration&&dialog.open;
    let verified=false;
    try{
      const data=await get('/api/signals',{
        symbol:candidate.symbol,strategy_id:candidate.strategy_id,provider:candidate.instrument_identity.provider,
        segment:candidate.instrument_identity.segment,start_time:candidate.source_data_watermark,end_time:candidate.source_data_watermark,limit:200,offset:0}
      );
      if(!valid())return;
      const signals=(Array.isArray(data.items)?data.items:[]).filter(s=>s.actionable===false&&s.dedup_key===candidate.candidate_id&&
        (!s.candidate_evaluation||s.candidate_evaluation.candidate_id===candidate.candidate_id)&&s.strategy_id===candidate.strategy_id&&
        s.position_type===candidate.position_type&&stable(s.instrument_identity)===stable(candidate.instrument_identity)&&
        sourceTime(s.timestamp)===sourceTime(candidate.source_data_watermark,{requireOffset:true}));
      body.replaceChildren(el('p','',reason(candidate)));
      if(signals.length!==1){
        body.dataset.state='UNAVAILABLE';
        body.append(availability('Exact setup link unavailable','The selected rank could not be uniquely matched to retained signal identity and timestamp. No replacement price or chart is shown.'));
        return;
      }
      const s=signals[0];
      verified=true;
      body.dataset.state='CURRENT';
      body.append(el('p','chart-note',names[s.strategy_id]+' · '+time(s.timestamp)),append(el('div','facts'),fact('Decision reference',num(s.entry_price)),fact('Invalidation',num(s.invalidation_level)),fact('Stop',num(s.stop_loss)),fact('Target 1',num(s.target_1)),fact('Target 2',num(s.target_2)),fact('Gross T1 R:R',num((candidate.score_components||{
      }
      ).actual_target1_rr))),panel('Why this setup qualified',text(s.rationale)),el('p','chart-note','Decision levels are retained evidence, not an executable quote. Missing inputs: '+(candidate.missing_components||[]).join(', ')));
      body.append(fact('Entry zone',num(s.entry_zone_low)+' – '+num(s.entry_zone_high)));
      retainedDetails(body,s,candidate);
      const run=(state.ranks&&state.ranks.snapshot||{
      }
      ).run_id;
      if(!run){
        body.append(el('p','chart-note','Candle source locator unavailable.'));
        return;
      }
      const lineage=await get('/api/scan-lineage',{
        run_id:run}
      );
      if(!valid())return;
      const batches=(lineage.batches||[]).filter(b=>stable(b.identity)===stable(candidate.instrument_identity)&&b.interval_min===5);
      if(lineage.run_id!==run||lineage.status!=='COMMITTED'||batches.length!==1)throw new Error('Exact candle identity unavailable');
      const batch=batches[0];
      if(!Number.isInteger(batch.candle_count)||batch.candle_count<1||!Number.isFinite(sourceTime(batch.last_timestamp)))throw new Error('Invalid candle locator');
      const candles=await get('/api/cash-candles',{
        run_id:run,batch_id:batch.batch_id,limit:100,offset:Math.max(0,batch.candle_count-100)}
      );
      if(!valid())return;
      const watermark=sourceTime(candidate.source_data_watermark,{requireOffset:true});
      if(!Number.isFinite(watermark)||candles.run_id!==run||candles.batch_id!==batch.batch_id||!Array.isArray(candles.items)||!candles.items.length||candles.total_count!==batch.candle_count)throw new Error('Invalid candle page');
      let previous=-Infinity;
      const istDay=stamp=>new Date(stamp+330*60000).toISOString().slice(0,10);
      for(const b of candles.items){
        const stamp=sourceTime(b.timestamp);
        if(!Number.isFinite(stamp)||stamp<=previous||stamp>watermark||stable(b.instrument_identity)!==stable(candidate.instrument_identity)||b.is_complete!==true||b.interval_min!==5||![b.open,b.high,b.low,b.close].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>0)||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close,b.high))throw new Error('Invalid candle input');
        if(Number.isFinite(previous)&&istDay(stamp)===istDay(previous)&&stamp-previous!==300000)throw new Error('Candle session gap');
        previous=stamp;
      }
      if(previous!==watermark||previous!==sourceTime(batch.last_timestamp))throw new Error('Candle watermark mismatch');
      drawCandles(body,candles.items);
      body.append(el('p','chart-note','Actual retained completed 5-minute bars · '+time(candles.items[0].timestamp)+' — '+time(candles.items.at(-1).timestamp)+' · Source authenticity not established.'));
    }
    catch(error){
      if(valid()){
        if(!verified){
          body.dataset.state='UNAVAILABLE';
          body.replaceChildren(availability('Exact setup evidence unavailable','The selected signal could not be verified. Retry the stored read; no previous prices are retained.'));
        }else body.append(availability('Retained chart unavailable','An exact, validated candle source could not be read. No illustrative candle history is substituted.'));
      }
    }
  }
  function drawCandles(parent,bars){
    const ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 760 240');
    svg.setAttribute('role','img');
    svg.setAttribute('aria-label','Retained completed five-minute OHLC candle chart; '+bars.length+' bars. Prices and times are available in the table below.');
    svg.classList.add('candle-chart');
    const low=Math.min(...bars.map(b=>b.low)),high=Math.max(...bars.map(b=>b.high));
    const y=v=>220-(v-low)/(high-low||1)*195;
    const step=720/bars.length;
    bars.forEach((b,i)=>{
      const color=b.close>=b.open?'#55d6b1':'#f59ca7';
      const x=25+i*step;
      const wick=document.createElementNS(ns,'line');
      Object.entries({
        x1:x,x2:x,y1:y(b.high),y2:y(b.low),stroke:color}
      ).forEach(([k,v])=>wick.setAttribute(k,String(v)));
      svg.append(wick);
      const rect=document.createElementNS(ns,'rect');
      Object.entries({
        x:x-step*.29,y:Math.min(y(b.open),y(b.close)),width:Math.max(1,step*.58),height:Math.max(1,Math.abs(y(b.open)-y(b.close))),fill:color}
      ).forEach(([k,v])=>rect.setAttribute(k,String(v)));
      svg.append(rect);
    }
    );
    parent.append(svg);
    const disclosure=el('details');
    disclosure.append(el('summary','','Read candle values'));
    const table=el('table');
    const head=el('tr');
    ['Time · IST','Open','High','Low','Close'].forEach(t=>head.append(el('th','',t)));
    table.append(append(el('thead'),head));
    const tbody=el('tbody');
    bars.forEach(b=>{
      const r=el('tr');
      [time(b.timestamp),num(b.open),num(b.high),num(b.low),num(b.close)].forEach(v=>r.append(el('td','',v)));
      tbody.append(r);
    }
    );
    table.append(tbody);
    disclosure.append(append(el('div','table-wrap'),table));
    parent.append(disclosure);
  }
  navigation();
  $('collapse').addEventListener('click',()=>{
    const collapsed=document.body.classList.toggle('collapsed');
    $('collapse').setAttribute('aria-expanded',String(!collapsed));
    $('collapse').setAttribute('aria-label',collapsed?'Expand sidebar':'Collapse sidebar');
  }
  );
  $('refresh-data').addEventListener('click',refresh);
  $('search').addEventListener('input',event=>{
    state.query=event.target.value.trim().toLowerCase();
    state.page=0;
    if(!['pulse','opportunities'].includes(state.route))location.hash='/opportunities';
    else render();
  }
  );
  $('close-detail').addEventListener('click',()=>closeDetail());
  $('detail').addEventListener('close',()=>{
    if(!$('detail').open)closeDetail();
  }
  );
  window.addEventListener('hashchange',()=>{
    navigate();
    $('page-content').focus();
  }
  );
  document.addEventListener('keydown',e=>{
    if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){
      e.preventDefault();
      $('search').focus();
    }
    if(e.key==='Escape'){
      $('more-menu').hidden=true;
      $('more-button').setAttribute('aria-expanded','false');
    }
  }
  );
  window.addEventListener('pagehide',()=>{
    state.controllers.forEach(c=>c.abort());
    clearTimeout(state.expiry);
  }
  );
  navigate();
  refresh();
}
)();
