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
    route:'pulse', routeGeneration:0, health:null, ranks:null, paper:null, rows:[], generation:0, controllers:new Set(), expiry:null, page:0, query:'', direction:'', strategy:'', detailGeneration:0, paperCursor:null};
  const text = value => typeof value === 'string' && value.trim() ? value : 'Unavailable';
  const num = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-IN',{
    maximumFractionDigits:2}
  ) : '—';
  const time = value => {
    const parsed=Date.parse(value);
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
  function mode(health){
    if(health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO')return 'DEMO · SYNTHETIC TEST DATA · NOT LIVE';
    if(health.evidence_scope==='OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE')return 'Offline fixture · not live';
    const b=health.broker||{
    };
    if(b.is_simulated||b.data_mode==='SIMULATED')return 'Simulated source';
    return 'Live source unverified';
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
    state.detailGeneration++;
    if ($('detail').open) $('detail').close();
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
    card.append(m,button('Explore evidence ↗',()=>detail(candidate)));
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
      append(copy,badge(state.query?'SEARCH RESULTS':current()?'NO QUALIFIED SETUPS':hasSource?'WAITING FOR QUALIFIED EVIDENCE':'NO SOURCE', 'caution'),el('h2','',state.query?'No qualified match for this instrument.':current()?'Patience is a position,
         too.':hasSource?'A clear signal starts with clear evidence.':'Your market view is waiting for a source.'),el('p','',state.query?'Search applies only to the retained ranked candidates. It does not acquire a new instrument or broaden the watchlist.':current()?'The latest stored scan has no qualifying candidate. Nothing is promoted just to fill this space. Review the strategy rules or inspect source coverage.':'Current candidate priority is unavailable. Read the source status and latest completed observations before interpreting an opportunity.'));
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
    view.append(split,heading('Market radar','Movement context is separate from strategy qualification'),panel('No verified radar feed','Breadth,
         sector participation and raw movers are not inferred from the ranked shortlist. This area remains unavailable until an admissible source supplies them.'));
  }
  function opportunities(){
    const view=$('view');
    const toolbar=el('div','toolbar');
    for(const [key,label,values]of [['direction','All directions',['LONG','SHORT']],['strategy','All strategies',Object.keys(names)]]){
      const s=el('select');
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
        render();
      }
      );
      toolbar.append(s);
    }
    view.append(toolbar);
    if(!current()){
      view.append(availability('Current priority is unavailable','Archived signals are not current entry opportunities. Check the source watermark or return after qualified observations have been retained.'));
      return;
    }
    const rows=filtered();
    if(!rows.length){
      view.append(availability('No candidates match','Try another instrument, direction or strategy. No additional scan is triggered by these filters.'));
      return;
    }
    const table=el('table');
    const tr=el('tr');
    ['Rank / change','Instrument','Strategy','Direction','Quality','Gross T1 R:R'].forEach(t=>tr.append(el('th','',t)));
    table.append(append(el('thead'),tr));
    const body=el('tbody');
    rows.forEach(r=>{
      const line=el('tr');
      line.dataset.candidateKey=r.opportunity_key||r.candidate_id;
      append(line,el('td','','#'+num(r.rank)+' · prior '+num(r.previous_rank)),append(el('td'),button(text(r.symbol),()=>detail(r),''),el('small','',time(r.source_data_watermark))),el('td','',names[r.strategy_id]||text(r.strategy_id)),el('td','',text(r.direction)),el('td','',num((r.score_components||{
      }
      ).rule_quality)),el('td','',num((r.score_components||{
      }
      ).actual_target1_rr)));
      body.append(line);
    }
    );
    table.append(body);
    view.append(append(el('div','table-wrap'),table));
    const p=state.ranks.pagination||{
    };
    const nav=el('div','pagination');
    const prev=button('← Previous',()=>{
      state.page=Math.max(0,state.page-1);
      refresh();
    }
    ,'quiet');
    prev.disabled=state.page===0;
    const next=button('Next →',()=>{
      state.page++;
      refresh();
    }
    ,'quiet');
    next.disabled=(state.page+1)*20>=(p.total||0);
    append(nav,prev,el('span','','Page '+(state.page+1)+' · '+num(p.total)+' retained candidates'),next);
    view.append(nav,el('p','chart-note','Quality measures detector rules, not a win probability. Net executable reward is unavailable when spread and other inputs are missing.'));
  }
  function render(){
    const view=$('view');
    view.replaceChildren();
    if(state.route==='pulse')pulse();
    else if(state.route==='opportunities')opportunities();
    else view.append(availability('Reading retained evidence…','This view only inspects existing records.'));
  }
  async function refresh(){
    const generation=++state.generation;
    state.detailGeneration++;
    if($('detail').open)$('detail').close();
    state.controllers.forEach(c=>c.abort());
    clearTimeout(state.expiry);
    state.health=null;
    state.ranks=null;
    state.rows=[];
    state.paper=null;
    $('notice').textContent='Reading stored evidence...';
    $('source-mode').textContent='Checking source';
    $('source-time').textContent='Awaiting evidence';
    $('source-status').dataset.state='LOADING';
    render();
    const started=performance.now();
    const results=await Promise.allSettled([get('/api/health'),get('/api/opportunity-rankings',{
      limit:20,offset:state.page*20}
    )]);
    if(generation!==state.generation)return;
    if(results[0].status==='fulfilled'){
      const health=results[0].value;
      state.health=health;
      $('source-mode').textContent=mode(health);
      $('source-status').dataset.state=health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO'?'DETERMINISTIC_OFFLINE_DEMO':(health.broker||{
      }
      ).is_simulated||(health.broker||{
      }
      ).data_mode==='SIMULATED'?'SIMULATED':'UNVERIFIED';
      $('source-time').textContent=time((health.broker||{
      }
      ).last_candle_timestamp_ist);
      $('session').textContent=text((health.scheduler||{
      }
      ).session_state)+' / IST';
      $('notice').textContent=health.evidence_scope==='DETERMINISTIC_OFFLINE_DEMO'?'DEMO - SYNTHETIC TEST DATA - NOT LIVE':'';
    }
    else{
      $('source-mode').textContent='Source unavailable';
      $('source-status').dataset.state='ERROR';
      $('source-time').textContent='No cached health retained';
      $('notice').textContent='Source health could not be read. Independent retained results are not live acceptance.';
    }
    if(results[1].status==='fulfilled'){
      const data=results[1].value;
      const lifetime=Date.parse((data.snapshot||{
      }
      ).valid_until)-Date.parse(data.as_of)-(performance.now()-started);
      state.ranks=data;
      const validRows=Array.isArray(data.current_rows)&&data.current_rows.every(r=>r&&r.actionable===false&&typeof r.symbol==='string'&&Number.isInteger(r.rank)&&r.instrument_identity&&typeof r.instrument_identity==='object');
      if(data.actionable===false&&data.status==='CURRENT_CANDIDATE_PRIORITY'&&Number.isFinite(lifetime)&&lifetime>=0&&validRows){
        state.rows=data.current_rows;
        state.expiry=setTimeout(()=>{
          if(generation===state.generation){
            state.rows=[];
            state.ranks={
              ...data,status:'ARCHIVED_EXPIRED'};
            state.detailGeneration++;
            if($('detail').open)$('detail').close();
            $('notice').textContent='Candidate evidence has expired. Refresh reads stored evidence; it does not acquire new data.';
            if(['pulse','opportunities'].includes(state.route))render();
          }
        }
        ,lifetime+1);
      }
      else if(data.status==='CURRENT_CANDIDATE_PRIORITY')state.ranks={
        ...data,status:'ARCHIVED_OR_INVALID'};
    }
    if(['pulse','opportunities'].includes(state.route))render();
    else loadRoute();
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
        view.replaceChildren(availability('Contract viability comes first','A directional underlying signal does not establish a tradable option. Exact expiry,
         strike, CE/PE, observed premium and liquidity must qualify separately.'));
        const items=Array.isArray(data.items)?data.items:[];
        view.append(heading('Retained option observations',items.length+' snapshots · historical context, not an executable chain'));
        if(!items.length)view.append(panel('No admissible option snapshot','Premium, OI, IV, Greeks and spread remain unavailable. No synthetic chain is substituted.'));
        items.forEach(s=>view.append(panel(text(s.symbol||s.underlying), 'Observed '+time(s.snapshot_timestamp||s.timestamp)+' · Contract execution authority is not established by a stored snapshot.')));
      }
      else if(route==='strategies'){
        const data=await get('/api/backtest-eligibility');
        if(!valid())return;
        view.replaceChildren();
        view.append(availability('Rules are inspectable. Edge must be earned.','A completed detection is not a future entry. Each strategy needs its own later trigger,
         source lineage and paper evidence. No win rate is inferred from passing software tests.'));
        const contracts=[['strat_1_order_block','Retest of a qualified order block with BOS/FVG context. Future lifecycle acceptance remains strategy-specific.'],['strat_2_vwap_pullback','Completed VWAP touch and directional reclaim/rejection with EMA,
         volume and RSI conditions. Later paper triggering uses an explicitly versioned policy.'],['strat_3_option_apex_oi','Underlying/OI context and long CE/PE selection. Exact qualified contracts and premium observations remain mandatory.'],['strat_4_orb_filtered','Completed opening-range breakout with VWAP,
         RSI and relative-volume confirmation. Later close-cross paper evidence is separate.'],['strat_5_supertrend_pullback','Trend-aligned pullback with Supertrend,
         EMA, VWAP and volume conditions. No universal next-close rule.']];
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
        view.replaceChildren(availability(state.health?'Read-only system inspection':'The evidence service is unavailable','No provider authentication,
         scan, account creation or brokerage operation is performed by this workspace.'));
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
    if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',
        ')+'}';
    return JSON.stringify(value);
  }
  async function detail(candidate){
    const generation=++state.detailGeneration;
    const dialog=$('detail');
    $('detail-title').textContent=text(candidate.symbol)+' · '+text(candidate.direction);
    const body=$('detail-body');
    body.replaceChildren(el('p','muted','Reading exact retained setup and source…'));
    if(!dialog.open)dialog.showModal();
    const valid=()=>generation===state.detailGeneration&&dialog.open;
    try{
      const data=await get('/api/signals',{
        symbol:candidate.symbol,strategy_id:candidate.strategy_id,limit:200}
      );
      if(!valid())return;
      const signals=(data.items||[]).filter(s=>s.strategy_id===candidate.strategy_id&&s.position_type===candidate.position_type&&stable(s.instrument_identity)===stable(candidate.instrument_identity)&&Date.parse(s.timestamp)===Date.parse(candidate.source_data_watermark));
      body.replaceChildren(el('p','',reason(candidate)));
      if(signals.length!==1){
        body.append(availability('Exact setup link unavailable','The selected rank could not be uniquely matched to retained signal identity and timestamp. No replacement price or chart is shown.'));
        return;
      }
      const s=signals[0];
      body.append(el('p','chart-note',names[s.strategy_id]+' · '+time(s.timestamp)),append(el('div','facts'),fact('Decision reference',num(s.entry_price)),fact('Invalidation',num(s.invalidation_level)),fact('Stop',num(s.stop_loss)),fact('Target 1',num(s.target_1)),fact('Target 2',num(s.target_2)),fact('Gross T1 R:R',num((candidate.score_components||{
      }
      ).actual_target1_rr))),panel('Why this setup qualified',text(s.rationale)),el('p','chart-note','Decision levels are retained evidence,
         not an executable quote. Missing inputs: '+(candidate.missing_components||[]).join(', ')));
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
      if(!Number.isInteger(batch.candle_count)||batch.candle_count<1||!Number.isFinite(Date.parse(batch.last_timestamp)))throw new Error('Invalid candle locator');
      const candles=await get('/api/cash-candles',{
        run_id:run,batch_id:batch.batch_id,limit:100,offset:Math.max(0,batch.candle_count-100)}
      );
      if(!valid())return;
      const watermark=Date.parse(candidate.source_data_watermark);
      if(!Number.isFinite(watermark)||candles.run_id!==run||candles.batch_id!==batch.batch_id||!Array.isArray(candles.items)||!candles.items.length||candles.total_count!==batch.candle_count)throw new Error('Invalid candle page');
      let previous=-Infinity;
      for(const b of candles.items){
        const stamp=Date.parse(b.timestamp);
        if(!Number.isFinite(stamp)||stamp<=previous||stamp>watermark||stable(b.instrument_identity)!==stable(candidate.instrument_identity)||b.is_complete!==true||b.interval_min!==5||![b.open,b.high,b.low,b.close].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>0)||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close,b.high))throw new Error('Invalid candle input');
        previous=stamp;
      }
      if(previous!==watermark||previous!==Date.parse(batch.last_timestamp))throw new Error('Candle watermark mismatch');
      drawCandles(body,candles.items);
      body.append(el('p','chart-note','Actual retained completed 5-minute bars · '+time(candles.items[0].timestamp)+' — '+time(candles.items.at(-1).timestamp)+' · Source authenticity not established.'));
    }
    catch(error){
      if(valid())body.append(availability('Retained chart unavailable','An exact, validated candle source could not be read. No illustrative candle history is substituted.'));
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
    if(!['pulse','opportunities'].includes(state.route))location.hash='/opportunities';
    else render();
  }
  );
  $('close-detail').addEventListener('click',()=>{
    $('detail').close();
    state.detailGeneration++;
  }
  );
  $('detail').addEventListener('close',()=>{
    state.detailGeneration++;
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
