"""Actual terminal assets, bounded headless CDP, authored loopback HTTP fixtures.

No application/config imports, environment reads, databases or market calls.
Four selected screenshots per run; overflow probes are not WCAG certification.
Backend-format naive IST health/signal/bar timestamps deliberately meet ISO-offset
ranking timestamps in real UTC desktop and America/New_York mobile browser clocks.
Opportunities fixtures mirror the rank-history page contract, including stable
snapshot metadata, more than 100 rows, deliberately inconsistent pages and delays.
"""
import argparse
import base64
import copy
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
from websockets.sync.client import connect

APP = Path(__file__).resolve().parents[2]
E = APP / 'docs/evidence'
IMAGES = APP / 'docs/project/ui-evidence'
SOURCES = ('public/terminal.html', 'public/terminal.css', 'public/terminal.js')
BROWSERS = {'chrome': Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe'),
            'edge': Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')}
SCOPE = 'DETERMINISTIC_OFFLINE_DEMO'
STAMP = '2026-10-16 10:00:00'
WATERMARK = '2026-10-16T10:00:00+05:30'
RANK_SCOPE = dict(provider='authored-fixture',data_mode='SIMULATED',
    segment='NSE_EQUITY_INTRADAY',profile_digest=hashlib.sha256(b'authored-v5-profile').hexdigest())
POLICY = 'CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(symbol):
    return dict(provider='authored-fixture', symbol=symbol, identifier='SYNTHETIC-'+symbol,
                exchange='NSE', segment='NSE_EQUITY_INTRADAY', instrument_type='EQ',is_index=False)


def symbols(mode):
    rows=['INFY','TCS','ORBIT-DEMO'] if mode['reverse'] else ['TCS','INFY','ORBIT-DEMO']
    if mode['wide']:rows += ['SYNTH'+str(i).zfill(3) for i in range(1,123)]
    return [symbol for symbol in rows if symbol not in mode['removed']][:mode['count']]


def ranking(mode,query):
    now = datetime.now(timezone.utc)
    limit=int(query.get('limit',['20'])[0]);offset=int(query.get('offset',['0'])[0])
    if set(query)-{'run_id','limit','offset'} or not 1<=limit<=100 or not 0<=offset<=512:
        raise ValueError('INVALID_RANK_QUERY')
    if mode['source']!='demo':
        return dict(status='RANKING_UNAVAILABLE_NO_DURABLE_SCAN',actionable=False,scope=RANK_SCOPE,
            as_of=now.isoformat(),current_rows=[],historical_rows=[],
            pagination=dict(total=0,limit=limit,offset=offset),snapshot=None)
    requested=query.get('run_id',[None])[0]
    if requested:
        frozen=mode['snapshots'][requested]
    else:
        all_rows = [dict(rank=i+1, previous_rank=(2-i if i<2 else i+1), symbol=s,
        opportunity_key=digest('synthetic-opportunity-'+s), candidate_id=digest('synthetic-candidate-'+s),
        strategy_id='strat_4_orb_filtered', position_type='LONG_EQUITY_INTRADAY', direction='LONG',
        instrument_identity=identity(s), actionable=False, source_data_watermark=WATERMARK,source_digest=digest('synthetic-candles-'+s),
        score_components=dict(rule_quality=80-i*.1, actual_target1_rr=1.8),
        component_versions=dict(rule_quality='EXISTING_EVALUATOR_V1',actual_target1_rr='PRICE_LEVEL_GEOMETRY_V1'),
        rank_change_reason='RELATIVE_ORDER_CHANGED' if mode['reverse'] else 'NEWLY_QUALIFIED',
        component_changes={},priority_scope='QUALIFIED_SCANNER_CANDIDATE_ONLY',
        missing_components=['OBSERVED_SPREAD', 'NET_EXECUTABLE_REWARD', 'EMPIRICAL_EDGE']) for i,s in enumerate(symbols(mode))]
        mode['next_run']+=1;run='synthetic-run-'+str(mode['next_run'])
        snapshot=dict(run_id=run,work_id=digest('synthetic-work-'+run),policy=POLICY,
            rank_version=digest(json.dumps(all_rows,sort_keys=True)),previous_rank_version=None,
            reference=WATERMARK,valid_until=(now+timedelta(seconds=mode['lifetime'])).isoformat(),
            scope=RANK_SCOPE,evidence_scope=SCOPE,source_authenticity='NOT_ESTABLISHED',
            previous_snapshot=None,source_data_watermarks=[WATERMARK],source_data_watermark_count=1,
            exclusions=[],exclusion_count=0,removals=[],removal_count=0,metadata_preview_limit=100,
            exclusions_truncated=False,removals_truncated=False,source_data_watermarks_truncated=False)
        frozen=dict(rows=all_rows,snapshot=snapshot)
        mode['snapshots'][run]=frozen;mode['latest_run']=run
    rows=copy.deepcopy(frozen['rows'][offset:offset+limit]);snapshot=copy.deepcopy(frozen['snapshot'])
    if offset and mode['fault']=='mixed-version':snapshot['rank_version']=digest('deliberately-mixed-page')
    if offset and mode['fault']=='duplicate' and rows:rows[0]=copy.deepcopy(frozen['rows'][0])
    if offset and mode['fault']=='short-page':rows=[]
    status=mode['rank_status'] or 'CURRENT_CANDIDATE_PRIORITY'
    return dict(status=status, actionable=False, evidence_scope=SCOPE,
        scope=RANK_SCOPE,as_of=now.isoformat(),current_rows=rows if status=='CURRENT_CANDIDATE_PRIORITY' else [],historical_rows=rows,
        pagination=dict(total=len(frozen['rows']),limit=limit,offset=offset),snapshot=snapshot)


def signal(symbol,run,late_marker=''):
    key=digest('synthetic-candidate-'+symbol)
    return dict(dedup_key=key,scan_run_id=run,symbol=symbol,segment='NSE_EQUITY_INTRADAY',
        strategy_id='strat_4_orb_filtered',position_type='LONG_EQUITY_INTRADAY',direction='BULLISH',
        instrument_identity=identity(symbol),timestamp=STAMP,provider='authored-fixture',data_mode='SIMULATED',
        interval_min=5,actionable=False,entry_price=101.1,entry_zone_low=100.9,entry_zone_high=101.2,
        invalidation_level=99.5,stop_loss=99,target_1=105,target_2=107,
        rationale='SYNTHETIC TEST INPUT <img src=x onerror="window.__xss=1"> '+late_marker,evidence_scope=SCOPE,
        recommendation_status='CANDIDATE_ONLY',
        candidate_evaluation=dict(candidate_id=key,warnings=['SYNTHETIC WARNING - NOT LIVE'],
            source_reference=dict(instrument_identity=identity(symbol)),
            explanation=dict(rule_evaluation=dict(summary='Authored rule evidence only',rule_checks=[
                dict(rule_id='SYNTHETIC_COMPLETED_BAR',status='PASS',reason='Authored completed-bar check')]))),
        strategy_evidence=dict(maturity_state='MECHANICS_TESTED',empirical_status='NOT_ESTABLISHED',
            explanation='Synthetic mechanics provide no empirical edge.'),
        context=dict(candidate_id=key,status='WARNING_ONLY',reason_codes=['SYNTHETIC_INFORMATION_ONLY'],
            actionable=False,affects_ranking=False,evaluation_mode='DECISION_TIME',as_of=WATERMARK,
            decision_at=WATERMARK,records=[]),
        context_alert_decision=dict(status='SUPPRESSED',reason_code='SYNTHETIC_NO_DELIVERY'),
        paper_decision=dict(status='DEFERRED',reason_code='SYNTHETIC_TRIGGER_NOT_OBSERVED',
            trigger_contract=dict(rule_id='SYNTHETIC_FUTURE_TRIGGER_V1',version='1'),trigger_timestamp_ist=None))


def candles(symbol):
    start=datetime.strptime(STAMP,'%Y-%m-%d %H:%M:%S')-timedelta(minutes=5*9)
    return [dict(timestamp=(start+timedelta(minutes=5*i)).strftime('%Y-%m-%d %H:%M:%S'), open=100+i*.1,
        high=100.4+i*.1, low=99.8+i*.1, close=100.2+i*.1, volume=1000,
        instrument_identity=identity(symbol), interval_min=5, is_complete=True,
        is_simulated=True, data_mode='SIMULATED') for i in range(10)]


class CDP:
    """Prior journal CDP pattern, with NO external-asset fulfillment path."""
    def __init__(self, ws, origin, deadline):
        self.ws,self.origin,self.deadline=ws,origin,deadline
        self.seq=0
        self.allowed,self.blocked,self.exceptions,self.crashes=[],[],[],[]

    def send(self, method, params=None):
        self.seq+=1
        self.ws.send(json.dumps(dict(id=self.seq,method=method,params=params or {})))
        return self.seq

    def command(self, method, params=None, timeout=4):
        request=self.send(method,params)
        end=min(self.deadline,time.monotonic()+timeout)
        while time.monotonic()<end:
            msg=json.loads(self.ws.recv(timeout=max(.01,end-time.monotonic())))
            kind=msg.get('method')
            if kind=='Fetch.requestPaused':
                event=msg['params'];req=event['request'];parts=urlsplit(req['url'])
                allowed=parts.scheme=='http' and parts.scheme+'://'+parts.netloc==self.origin and req['method'] in ('GET','HEAD')
                record=dict(method=req['method'],host=parts.hostname,path=parts.path)
                (self.allowed if allowed else self.blocked).append(record)
                self.send('Fetch.continueRequest' if allowed else 'Fetch.failRequest',
                    dict(requestId=event['requestId']) if allowed else dict(requestId=event['requestId'],errorReason='BlockedByClient'))
            elif kind=='Runtime.exceptionThrown':self.exceptions.append(msg['params']['exceptionDetails'])
            elif kind in ('Inspector.targetCrashed','Target.targetCrashed'):self.crashes.append(msg)
            elif msg.get('id')==request:
                if 'error' in msg:raise RuntimeError('CDP '+method+': '+str(msg['error']))
                return msg.get('result',{})
        raise TimeoutError('CDP '+method)

    def evaluate(self, expression):
        result=self.command('Runtime.evaluate',dict(expression=expression,awaitPromise=True,returnByValue=True))
        if result.get('exceptionDetails'):raise RuntimeError(str(result['exceptionDetails']))
        return result.get('result',{}).get('value')

    def wait(self, expression, timeout=4):
        end=min(self.deadline,time.monotonic()+timeout)
        while time.monotonic()<end:
            if self.evaluate(expression) is True:return True
            time.sleep(.025)
        return False

    def key(self,key,code,virtual):
        for kind in ('keyDown','keyUp'):
            self.command('Input.dispatchKeyEvent',dict(type=kind,key=key,code=code,
                windowsVirtualKeyCode=virtual,nativeVirtualKeyCode=virtual))


def run(receipt, browser, prefix):
    started=time.monotonic();deadline=started+52
    mode=dict(source='none',reverse=False,lifetime=30,wide=False,count=512,removed=[],fault='',rank_status='',
        rank_delay=0,signal_delay=0,late_marker='',snapshots={},next_run=0,latest_run=None)
    requests=[];failures=[]
    raw={('/' if n.endswith('.html') else '/'+Path(n).name):(APP/n).read_bytes() for n in SOURCES}
    raw['/terminal.html']=raw['/']
    def check(name,result,details=None):
        receipt['checks'].append(dict(name=name,passed=result is True,details=details))
        print(name,'PASS' if result is True else 'FAIL', details if details is not None else '')
        if result is not True:
            raise AssertionError('BROWSER_CHECK_FAILED: '+name)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,head=False):
            parts=urlsplit(self.path);path=parts.path;query=parse_qs(parts.query)
            status=200;mime='application/json';payload={};delay=0
            if path in raw:
                body=raw[path];mime='text/html' if path in ('/','/terminal.html') else 'text/css' if path.endswith('.css') else 'application/javascript'
            else:
                if path=='/api/health':
                    if mode['source']=='error':status=503
                    payload=dict(evidence_scope=SCOPE if mode['source']=='demo' else 'NO_SOURCE',
                        broker=dict(is_simulated=mode['source']=='demo',data_mode='SIMULATED' if mode['source']=='demo' else 'UNAVAILABLE',
                            last_candle_timestamp_ist=STAMP if mode['source']=='demo' else None),
                        paper_account_id='synthetic-paper' if mode['source']=='demo' else None,
                        database=dict(status='AUTHORED_FIXTURE'),scheduler=dict(running=False,session_state='SYNTHETIC_TEST_SESSION'))
                elif path=='/api/opportunity-rankings':
                    payload=ranking(mode,query)
                    delay=mode['rank_delay'] if 'run_id' not in query else 0
                elif path=='/api/paper-portfolio':
                    payload=dict(status='OK',reconciliation=dict(status='OK'),as_of_ist=STAMP,
                        accounting=dict(open_positions=0,closed_positions=0,fees_paid_inr=0),
                        positions=[],events=[],candidate_decisions=[],total_positions=0,total_events=0,total_candidate_decisions=0,
                        evidence_scope=SCOPE,financial_mutations=False)
                elif path=='/api/signals':
                    symbol=query.get('symbol',[''])[0]
                    payload=dict(status='ok',items=[signal(symbol,mode['latest_run'],mode['late_marker'])],total_count=1,limit=200,offset=0)
                    delay=mode['signal_delay']
                elif path=='/api/scan-lineage':
                    run=query.get('run_id',[''])[0];frozen=mode['snapshots'][run]
                    payload=dict(run_id=run,status='COMMITTED',source_authenticity='NOT_ESTABLISHED',
                        batches=[dict(batch_id='synthetic-'+s,identity=identity(s),interval_min=5,candle_count=10,last_timestamp=STAMP)
                                 for s in (row['symbol'] for row in frozen['rows'])])
                elif path=='/api/cash-candles':
                    batch=query.get('batch_id',[''])[0];symbol=batch.removeprefix('synthetic-')
                    payload=dict(run_id=query.get('run_id',[''])[0],batch_id=batch,total_count=10,
                        limit=int(query.get('limit',['100'])[0]),offset=int(query.get('offset',['0'])[0]),items=candles(symbol))
                elif path=='/api/backtest-eligibility':payload=dict(strategies={})
                elif path in ('/api/scans','/api/oi-snapshots'):payload=dict(items=[],total_count=0)
                elif path=='/api/config':payload=dict(config=dict(telegram_dry_run=True,enable_background_scheduler=False))
                elif path=='/favicon.ico':status=204
                else:status=404;failures.append('UNDEFINED_ROUTE '+path)
                body=json.dumps(payload,allow_nan=False).encode()
            record=dict(method=self.command,path=path,query=query,status=status,fixture_mode=mode['source'],
                fixture_case=dict(wide=mode['wide'],count=mode['count'],fault=mode['fault'],rank_status=mode['rank_status'],removed=list(mode['removed'])),
                authored_delay_seconds=delay)
            if path=='/api/opportunity-rankings':
                record['rank_response']=dict(pagination=payload.get('pagination'),snapshot=payload.get('snapshot'),
                    row_count=len(payload.get('current_rows',[])))
            requests.append(record)
            if delay:time.sleep(delay)
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.end_headers()
            if not head:
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):self.respond()
        def do_HEAD(self):self.respond(True)
        def do_POST(self):
            failures.append('MUTATION_REACHED_SERVER');self.send_response(405);self.send_header('Content-Length','0');self.end_headers()

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    origin='http://127.0.0.1:'+str(server.server_address[1])
    worker=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.025),daemon=True);worker.start()
    profile_temp=tempfile.TemporaryDirectory(prefix='track-a-v3-browser-');profile=Path(profile_temp.name).resolve()
    process=ws=cdp=None
    try:
        assert profile.parent==Path(tempfile.gettempdir()).resolve() and profile.name.startswith('track-a-v3-browser-')
        flags=['--headless=new','--disable-gpu','--disable-background-networking','--disable-component-update',
            '--disable-default-apps','--disable-extensions','--disable-sync','--disable-domain-reliability',
            '--disable-client-side-phishing-detection','--disable-breakpad','--disable-crash-reporter','--disable-pings',
            '--safebrowsing-disable-auto-update','--metrics-recording-only','--no-first-run','--no-default-browser-check',
            '--password-store=basic','--use-mock-keychain','--disable-search-engine-choice-screen',
            '--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication,Translate,NetworkTimeServiceQuerying',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank']
        receipt['browser_arguments']=[f if not f.startswith('--user-data-dir=') else '--user-data-dir=<isolated-temporary-profile>' for f in flags]
        process=subprocess.Popen([str(BROWSERS[browser]),*flags],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        portfile=profile/'DevToolsActivePort';limit=time.monotonic()+10
        while not portfile.exists():
            if process.poll() is not None or time.monotonic()>limit:raise RuntimeError('BROWSER_START_FAILED')
            time.sleep(.025)
        port=int(portfile.read_text().splitlines()[0])
        with urlopen('http://127.0.0.1:'+str(port)+'/json/list',timeout=3) as response:targets=json.loads(response.read(1048576))
        target=next(t for t in targets if t.get('type')=='page');debug=urlsplit(target['webSocketDebuggerUrl'])
        assert debug.scheme=='ws' and debug.hostname=='127.0.0.1'
        ws=connect(target['webSocketDebuggerUrl'],open_timeout=3,close_timeout=2,max_size=8*1024*1024,proxy=None)
        cdp=CDP(ws,origin,deadline);receipt['browser_version']=cdp.command('Browser.getVersion')
        for domain in ('Runtime','Page','Inspector','Accessibility'):cdp.command(domain+'.enable')
        cdp.command('Fetch.enable',dict(patterns=[dict(urlPattern='*',requestStage='Request')]))
        IMAGES.mkdir(parents=True,exist_ok=True)
        def metrics(width,height=900,mobile=False):
            cdp.command('Emulation.setDeviceMetricsOverride',dict(width=width,height=height,deviceScaleFactor=1,mobile=mobile))
        def capture(label):
            name=prefix+'_'+label+'.png';path=IMAGES/name
            image=cdp.command('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
            with path.open('xb') as stream:stream.write(base64.b64decode(image['data']))
            receipt['screenshots'].append(dict(file=path.relative_to(APP).as_posix(),sha256=sha(path),mode=mode['source'],
                fixture_scope=SCOPE if mode['source']=='demo' else 'OFFLINE_AUTHORED_NO_SOURCE',route='#/pulse',
                host_timezone=cdp.evaluate('Intl.DateTimeFormat().resolvedOptions().timeZone'),
                viewport=cdp.evaluate('({width:innerWidth,height:innerHeight})')))
        def search(value):
            cdp.evaluate("document.querySelector('#search').value="+json.dumps(value)+";document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))")
        def candidate(symbol):
            return "[...document.querySelectorAll('#view button[data-candidate-key]')].find(b=>b.textContent.trim()==="+json.dumps(symbol)+")"
        def received(predicate,timeout=2):
            end=min(deadline,time.monotonic()+timeout)
            while time.monotonic()<end:
                cdp.evaluate('true')
                if any(predicate(record) for record in requests):return True
                time.sleep(.025)
            return False
        def w4(label):
            mode.update(source='demo',wide=True,count=512,reverse=False,lifetime=30,removed=[],fault='',rank_status='',
                rank_delay=0,signal_delay=0,late_marker='')
            beginning=len(requests)
            cdp.evaluate("location.hash='/opportunities';document.querySelector('#refresh-data').click()")
            check(label+'.w4.complete_snapshot',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && document.querySelector('#opportunity-page')?.textContent.includes('125 matching / 125 retained') && document.querySelectorAll('#view button[data-candidate-key]').length===20"))
            pages=[record for record in requests[beginning:] if record['path']=='/api/opportunity-rankings']
            check(label+'.w4.pinned_100_row_contract',len(pages)==2 and pages[0]['query']==dict(limit=['100'],offset=['0'])
                and pages[1]['query']==dict(limit=['100'],offset=['100'],run_id=[pages[0]['rank_response']['snapshot']['run_id']])
                and [page['rank_response']['row_count'] for page in pages]==[100,25]
                and pages[0]['rank_response']['snapshot']==pages[1]['rank_response']['snapshot'],
                [dict(query=page['query'],response=page['rank_response']) for page in pages])
            cdp.evaluate("document.querySelector('#search').focus()")
            search('SYNTH122')
            check(label+'.w4.cross_server_page_filter',cdp.wait("document.querySelectorAll('#view button[data-candidate-key]').length===1 && "+candidate('SYNTH122')+"!==undefined && document.querySelector('#opportunity-page').textContent.includes('1 matching / 125 retained') && document.activeElement.id==='search'"))
            cdp.evaluate("const filter=document.querySelector('#opportunity-direction');filter.focus();filter.value='SHORT';filter.dispatchEvent(new Event('change',{bubbles:true}))")
            check(label+'.w4.zero_match_controls_and_focus',cdp.wait("document.querySelectorAll('#view button[data-candidate-key]').length===0 && !!document.querySelector('#opportunity-reset') && !!document.querySelector('#opportunity-prev') && !!document.querySelector('#opportunity-next') && document.activeElement.id==='opportunity-direction' && document.querySelector('#opportunity-page').textContent.includes('0 matching / 125 retained')"))
            cdp.evaluate("document.querySelector('#opportunity-reset').click()")
            check(label+'.w4.reset_filters',cdp.wait("document.querySelector('#search').value==='' && document.querySelector('#opportunity-direction').value==='' && document.querySelectorAll('#view button[data-candidate-key]').length===20"))
            rank_reads=sum(record['path']=='/api/opportunity-rankings' for record in requests)
            for _ in range(6):cdp.evaluate("document.querySelector('#opportunity-next').click()")
            check(label+'.w4.local_last_page',cdp.wait("document.querySelector('#opportunity-page').textContent.includes('Page 7 / 7') && document.querySelectorAll('#view button[data-candidate-key]').length===5 && document.querySelector('#opportunity-next').disabled"))
            check(label+'.w4.paging_does_not_reread',sum(record['path']=='/api/opportunity-rankings' for record in requests)==rank_reads)
            mode['count']=20;cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.shrunk_last_page_recovers',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && document.querySelector('#opportunity-page').textContent.includes('Page 1 / 1') && document.querySelectorAll('#view button[data-candidate-key]').length===20 && document.querySelector('#opportunity-prev').disabled && document.querySelector('#opportunity-next').disabled"))
            mode['count']=512
            for fault in ('mixed-version','duplicate','short-page'):
                mode['fault']=fault;cdp.evaluate("document.querySelector('#refresh-data').click()")
                check(label+'.w4.reject_'+fault,cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='ERROR' && document.querySelectorAll('#view button[data-candidate-key]').length===0 && !!document.querySelector('#opportunity-reset')"))
            mode['fault']='';cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.recover_valid_snapshot',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && "+candidate('TCS')+"!==undefined"))
            cdp.evaluate(candidate('TCS')+".focus()")
            mode.update(reverse=True,rank_delay=.45)
            cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.reorder_keeps_owned_focus',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && document.activeElement.dataset.candidateKey==="+json.dumps(digest('synthetic-opportunity-TCS'))))
            mode['rank_delay']=0
            cdp.evaluate(candidate('TCS')+".click()")
            check(label+'.w4.selected_detail',cdp.wait("document.querySelector('#detail').open && document.querySelector('#detail-body').dataset.state==='CURRENT' && document.querySelectorAll('#detail .candle-chart').length===1"))
            details=cdp.evaluate("document.querySelector('#detail-body').textContent")
            check(label+'.w4.extended_retained_evidence',all(text in details for text in (
                'Entry zone','Retained rule checks','SYNTHETIC_COMPLETED_BAR','SYNTHETIC WARNING - NOT LIVE',
                'Strategy evidence','MECHANICS_TESTED','NOT_ESTABLISHED','Informational context',
                'SYNTHETIC_INFORMATION_ONLY','Paper trigger evidence','SYNTHETIC_FUTURE_TRIGGER_V1',
                'SYNTHETIC_TRIGGER_NOT_OBSERVED')) and cdp.evaluate("!window.__xss && !document.querySelector('#detail-body img')"))
            reads=[record for record in requests if record['path']=='/api/signals' and record['query'].get('symbol')==['TCS']]
            query=reads[-1]['query']
            def instant(value):
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                return parsed.replace(tzinfo=timezone(timedelta(hours=5,minutes=30))) if parsed.tzinfo is None else parsed
            check(label+'.w4.narrow_supported_signal_query',query.get('provider')==['authored-fixture']
                and query.get('segment')==['NSE_EQUITY_INTRADAY'] and 'direction' not in query
                and len(query.get('start_time',[]))==1 and len(query.get('end_time',[]))==1
                and instant(query['start_time'][0])==instant(WATERMARK)==instant(query['end_time'][0]),query)
            mode.update(reverse=False,rank_delay=.45)
            cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.immediate_price_withholding',cdp.evaluate("document.querySelector('#detail').open && document.querySelector('#detail-body').dataset.state==='REQUALIFYING' && document.querySelectorAll('#detail .fact,#detail .candle-chart').length===0"))
            check(label+'.w4.same_source_selection_requalified',cdp.wait("document.querySelector('#detail-body').dataset.state==='CURRENT' && document.querySelector('#detail-title').textContent.includes('TCS') && document.querySelectorAll('#detail .candle-chart').length===1"))
            mode['rank_delay']=0
            cdp.evaluate("document.querySelector('#close-detail').click()")
            check(label+'.w4.close_restores_exact_focus',cdp.wait("!document.querySelector('#detail').open && document.activeElement.dataset.candidateKey==="+json.dumps(digest('synthetic-opportunity-TCS'))))
            cdp.evaluate(candidate('TCS')+".click()")
            check(label+'.w4.selected_before_removal',cdp.wait("document.querySelector('#detail-body').dataset.state==='CURRENT'"))
            mode['removed']=['TCS'];cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.removed_selection_withheld',cdp.wait("document.querySelector('#detail-body').dataset.state==='UNAVAILABLE' && document.querySelectorAll('#detail .fact,#detail .candle-chart').length===0 && "+candidate('TCS')+"===undefined"))
            cdp.evaluate("document.querySelector('#close-detail').click()")
            check(label+'.w4.removed_close_recovery_focus',cdp.wait("!document.querySelector('#detail').open && document.activeElement.id==='refresh-data'"))
            mode['removed']=[];cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.restored_after_removal',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && "+candidate('INFY')+"!==undefined"))
            delayed_start=len(requests);mode.update(signal_delay=.55,late_marker='LATE-INFY-ONLY')
            cdp.evaluate(candidate('INFY')+".click()")
            check(label+'.w4.late_signal_was_requested',received(lambda record:record in requests[delayed_start:]
                and record['path']=='/api/signals' and record['query'].get('symbol')==['INFY'] and record['authored_delay_seconds']==.55))
            cdp.evaluate("document.querySelector('#close-detail').click()")
            mode.update(signal_delay=0,late_marker='')
            cdp.evaluate(candidate('TCS')+".click()")
            check(label+'.w4.new_selection_loaded',cdp.wait("document.querySelector('#detail-body').dataset.state==='CURRENT' && document.querySelector('#detail-title').textContent.includes('TCS')"))
            cdp.evaluate('new Promise(resolve=>setTimeout(()=>resolve(true),650))')
            check(label+'.w4.late_signal_cannot_replace_selection',cdp.evaluate("document.querySelector('#detail-title').textContent.includes('TCS') && !document.querySelector('#detail-body').textContent.includes('LATE-INFY-ONLY') && document.querySelectorAll('#detail .candle-chart').length===1"))
            mode['lifetime']=.45;cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.expired_selection_withheld',cdp.wait("document.querySelector('#notice').textContent.includes('expired') && document.querySelector('#detail-body').dataset.state==='UNAVAILABLE' && document.querySelectorAll('#detail .fact,#detail .candle-chart').length===0 && document.querySelectorAll('#view button[data-candidate-key]').length===0"))
            cdp.evaluate("document.querySelector('#close-detail').click()")
            mode.update(lifetime=30,reverse=False,rank_delay=.55)
            delayed_start=len(requests);cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.late_rank_was_requested',received(lambda record:record in requests[delayed_start:]
                and record['path']=='/api/opportunity-rankings' and record['authored_delay_seconds']==.55))
            mode.update(reverse=True,rank_delay=0)
            cdp.evaluate("document.querySelector('#refresh-data').click();document.querySelector('#search').focus()")
            check(label+'.w4.new_rank_wins',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='CURRENT' && document.querySelector('#view button[data-candidate-key]')?.textContent.trim()==='INFY' && document.activeElement.id==='search'"))
            cdp.evaluate('new Promise(resolve=>setTimeout(()=>resolve(true),650))')
            check(label+'.w4.late_rank_cannot_replace_or_steal_focus',cdp.evaluate("document.querySelector('#view button[data-candidate-key]')?.textContent.trim()==='INFY' && document.activeElement.id==='search'"))
            mode['count']=0;cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.empty_current_scan_distinct',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='EMPTY' && document.querySelectorAll('#view button[data-candidate-key]').length===0 && !!document.querySelector('#opportunity-reset')"))
            mode.update(count=512,rank_status='ARCHIVED_NON_CURRENT_SCAN')
            cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.archive_distinct',cdp.wait("document.querySelector('#ranking-status')?.dataset.state==='ARCHIVED' && document.querySelectorAll('#view button[data-candidate-key]').length===0"))
            mode['rank_status']=''
            mode.update(source='error',rank_delay=.45)
            cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.w4.loading_clears_old_session',cdp.evaluate("!document.querySelector('#session').textContent.includes('Synthetic demo')"))
            check(label+'.w4.health_error_clears_old_session',cdp.wait("document.querySelector('#source-status').dataset.state==='ERROR' && !document.querySelector('#session').textContent.includes('Synthetic demo')"))
            mode.update(source='demo',wide=False,count=512,reverse=False,lifetime=30,rank_delay=0)
            cdp.evaluate("location.hash='/pulse';document.querySelector('#refresh-data').click()")
            check(label+'.w4.return_to_small_pulse',cdp.wait("document.querySelector('#page-title').textContent==='Pulse' && document.querySelectorAll('.candidate').length===3"))
        for label,width,height,mobile,host_timezone in [('desktop',1440,900,False,'UTC'),('mobile',390,844,True,'America/New_York')]:
            metrics(width,height,mobile);mode.update(source='none',reverse=False,lifetime=30,wide=False,count=512,rank_status='',
                removed=[],fault='',rank_delay=0,signal_delay=0,late_marker='')
            cdp.command('Emulation.setTimezoneOverride',dict(timezoneId=host_timezone))
            health_before=sum(r['path']=='/api/health' for r in requests)
            cdp.command('Page.navigate',dict(url=origin+'/?viewport='+label+'&mode=no_source#/pulse'))
            check(label+'.no_source',cdp.wait("document.querySelector('#source-status')?.dataset.state==='NO_SOURCE' && document.querySelector('#source-mode')?.textContent==='No source available' && document.querySelector('#view')?.textContent.includes('clear signal starts') && !document.body.textContent.includes('SYNTHETIC TEST DATA') && !document.querySelector('#notice').textContent.includes('expired')"))
            check(label+'.real_browser_timezone',cdp.evaluate('Intl.DateTimeFormat().resolvedOptions().timeZone==='+json.dumps(host_timezone)),host_timezone)
            check(label+'.fresh_no_source_health_request',sum(r['path']=='/api/health' for r in requests)>health_before and [r for r in requests if r['path']=='/api/health'][-1]['fixture_mode']=='none')
            check(label+'.no_source_no_cards',cdp.evaluate("document.querySelectorAll('.candidate').length===0"))
            check(label+'.no_source_time_unavailable',cdp.evaluate("document.querySelector('#source-time').textContent==='Time unavailable'"))
            capture(label+'_no_source')
            mode['source']='error';cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.error_distinct',cdp.wait("document.querySelector('#source-status')?.dataset.state==='ERROR'"))
            mode['source']='demo';cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.demo_three',cdp.wait("document.querySelectorAll('.candidate').length===3 && document.querySelector('#source-status').dataset.state==='DETERMINISTIC_OFFLINE_DEMO' && document.querySelector('#source-mode').textContent==='DEMO \\u00b7 SYNTHETIC TEST DATA \\u00b7 NOT LIVE' && document.querySelector('#notice').textContent==='DEMO - SYNTHETIC TEST DATA - NOT LIVE' && document.querySelector('#session').textContent==='Synthetic demo / IST'"))
            check(label+'.naive_health_1000_ist',cdp.evaluate("document.querySelector('#source-time').textContent.endsWith('10:00 IST') && document.querySelector('#source-time').textContent.includes('16 Oct')"),cdp.evaluate("document.querySelector('#source-time').textContent"))
            check(label+'.visible_source_freshness',cdp.evaluate("(()=>{const e=document.querySelector('#source-time');return e.getBoundingClientRect().width>0 && e.getBoundingClientRect().height>0 && getComputedStyle(e).display!=='none'})()"))
            check(label+'.first_rank',cdp.evaluate("document.querySelector('.candidate')?.dataset.symbol==='TCS'"))
            capture(label+'_demo')
            mode['reverse']=True;cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.rank_reversal',cdp.wait("document.querySelector('.candidate')?.dataset.symbol==='INFY'"))
            cdp.key('/','Slash',191)
            check(label+'.keyboard_search',cdp.evaluate("document.activeElement.id==='search'"))
            cdp.evaluate("document.querySelector('#search').value='INFY';document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))")
            check(label+'.search_filter',cdp.wait("document.querySelectorAll('.candidate').length===1 && document.querySelector('.candidate').dataset.symbol==='INFY'"))
            cdp.evaluate("document.querySelector('.candidate button').click()")
            check(label+'.exact_identity_chart',cdp.wait("document.querySelector('#detail')?.open && document.querySelector('#detail-title').textContent.includes('INFY') && document.querySelectorAll('#detail .candle-chart').length===1"))
            clock=cdp.evaluate("({host_timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,host_offset_minutes:new Date('2026-10-16T04:30:00Z').getTimezoneOffset(),source_time:document.querySelector('#source-time').textContent,signal_time:document.querySelector('#detail-body > .chart-note')?.textContent,last_candle_time:document.querySelector('#detail tbody tr:last-child td')?.textContent,candle_rows:document.querySelectorAll('#detail tbody tr').length})")
            receipt['clock_observations'].append(dict(viewport=label,**clock))
            check(label+'.mixed_format_exact_1000_ist',clock['candle_rows']==10 and clock['source_time'].endswith('10:00 IST') and clock['signal_time'].endswith(clock['source_time']) and clock['last_candle_time']==clock['source_time'],clock)
            check(label+'.host_clock_is_non_ist',clock['host_offset_minutes']==(0 if host_timezone=='UTC' else 240),clock['host_offset_minutes'])
            check(label+'.text_safe',cdp.evaluate("!window.__xss && document.querySelector('#detail-body').textContent.includes('<img src=x') && !document.querySelector('#detail-body img')"))
            cdp.key('Escape','Escape',27)
            check(label+'.escape_dialog',cdp.wait("!document.querySelector('#detail').open"))
            cdp.evaluate("document.querySelector('#search').value='';document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))")
            if mobile:
                cdp.evaluate("document.querySelector('#more-button').click()")
                check(label+'.mobile_more',cdp.evaluate("!document.querySelector('#more-menu').hidden && document.querySelector('#more-button').getAttribute('aria-expanded')==='true'"))
                cdp.evaluate("document.querySelector('#more-menu a[href=\"#/strategies\"]').click()")
                check(label+'.mobile_more_navigation',cdp.wait("location.hash==='#/strategies' && document.querySelector('#more-menu').hidden"))
            for route,title in [('opportunities','Opportunities'),('options','Options Lab'),('strategies','Strategies & Research'),('paper','Paper Portfolio'),('health','Health & Settings'),('pulse','Pulse')]:
                cdp.evaluate('location.hash='+json.dumps('/'+route))
                check(label+'.route_'+route,cdp.wait('document.querySelector("#page-title").textContent==='+json.dumps(title)))
            cdp.evaluate("location.hash='/health'");cdp.wait("location.hash==='#/health'")
            cdp.evaluate('history.back()')
            check(label+'.browser_back',cdp.wait("location.hash==='#/pulse' && document.querySelector('#page-title').textContent==='Pulse'"))
            mode['lifetime']=.45;cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.expiry_clears',cdp.wait("document.querySelector('#notice').textContent.includes('expired') && document.querySelectorAll('.candidate').length===0"))
            w4(label)
        mode.update(source='demo',lifetime=30)
        for width in (360,390,768,1024,1366,1440,1920):
            metrics(width,900,width<800)
            check('overflow.'+str(width),cdp.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),
                cdp.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})'))
        cdp.command('Page.navigate',dict(url=origin+'/#/paper'))
        check('deep_link.paper',cdp.wait("document.querySelector('#page-title')?.textContent==='Paper Portfolio'"))
        tree=cdp.command('Accessibility.getFullAXTree')
        receipt['accessibility_sample']=[dict(role=n.get('role',{}).get('value'),name=n.get('name',{}).get('value')) for n in tree['nodes'] if n.get('role',{}).get('value') in ('button','link','main','navigation')][:70]
        check('semantic.skip_and_named_controls',cdp.evaluate("!!document.querySelector('a.skip[href=\"#page-content\"]') && [...document.querySelectorAll('button')].every(b=>b.textContent.trim()||b.getAttribute('aria-label'))"))
        receipt['computed_contrast_sample']=cdp.evaluate("({bodyText:getComputedStyle(document.body).color,bodyBackground:getComputedStyle(document.body).backgroundColor,focusToken:getComputedStyle(document.documentElement).getPropertyValue('--brand')})")
        def luminance(rgb):
            channels=[int(c)/255 for c in re.findall(r'\d+',rgb)[:3]]
            assert len(channels)==3
            linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels]
            return sum(c*w for c,w in zip(linear,(.2126,.7152,.0722)))
        sample=receipt['computed_contrast_sample']
        a,b=sorted((luminance(sample['bodyText']),luminance(sample['bodyBackground'])))
        sample['body_text_contrast_ratio']=(b+.05)/(a+.05)
        check('contrast.body_text_only',sample['body_text_contrast_ratio']>=4.5,sample['body_text_contrast_ratio'])
        check('external_blocked',cdp.evaluate("fetch('https://blocked.example/v5-probe').then(()=>false).catch(()=>true)") is True and any(r['host']=='blocked.example' for r in cdp.blocked))
        check('post_blocked',cdp.evaluate("fetch('/api/scan',{method:'POST'}).then(()=>false).catch(()=>true)") is True and any(r['method']=='POST' for r in cdp.blocked))
        check('get_head_only_origin',all(r['method'] in ('GET','HEAD') for r in requests) and all(r['path']!='/api/scan' for r in requests))
        check('no_fixture_failures',not failures,failures)
        check('no_js_exceptions_or_crashes',not cdp.exceptions and not cdp.crashes)
    finally:
        if cdp:
            receipt.update(cdp_allowed_requests=cdp.allowed,cdp_blocked_requests=cdp.blocked,javascript_exceptions=cdp.exceptions,browser_crashes=cdp.crashes)
            try:cdp.send('Browser.close')
            except Exception:pass
        if ws:ws.close()
        if process:
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate();process.wait(timeout=2)
            receipt['browser_exit_code']=process.returncode
        server.shutdown();server.server_close();worker.join(timeout=2)
        receipt['server_thread_stopped']=not worker.is_alive()
        profile_temp.cleanup();receipt['temporary_profile_removed']=not profile.exists()
        receipt.update(actual_fixture_requests=requests,fixture_failures=failures,browser_run_seconds=round(time.monotonic()-started,3))
        check('bounded_run_under_60_seconds',receipt['browser_run_seconds']<60,receipt['browser_run_seconds'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',required=True)
    parser.add_argument('--browser',choices=sorted(BROWSERS),default='chrome');args=parser.parse_args()
    if not re.fullmatch('[a-z0-9_]{2,60}',args.stage):parser.error('Use a unique simple stage')
    prefix='track_a_v3_browser_v5_'+args.stage;output=E/(prefix+'.json');log=E/(prefix+'.txt')
    if output.exists() or log.exists() or list(IMAGES.glob(prefix+'*.png')):parser.error('Immutable stage already exists')
    receipt=dict(schema='tradepulse.v3-browser-fixture.v3',status='FAIL',browser=args.browser,checks=[],screenshots=[],clock_observations=[],
        recorded_at=datetime.now(timezone.utc).isoformat(),helper_sha256=sha(Path(__file__)),source_before={n:sha(APP/n) for n in SOURCES},
        application_imports=False,environment_read=False,operational_database_accessed=False,provider_requests=0,
        timestamp_fixture_contract=dict(health=STAMP,signal=STAMP,cash_bar_last=STAMP,lineage_last=STAMP,
            rank_watermark=WATERMARK,ranking_lifetime='Explicit-offset ISO as_of and valid_until',
            stored_naive_timezone='Asia/Kolkata',desktop_host_timezone='UTC',mobile_host_timezone='America/New_York'),
        ranking_fixture_contract=dict(api_limit_max=100,client_candidate_bound=512,wide_candidate_count=125,
            immutable_pinned_pages=True,scope=RANK_SCOPE,policy=POLICY,
            intentional_page_faults=['mixed-version','duplicate','short-page']),
        evidence_scope=SCOPE,limitations=['Authored HTTP fixture, not actual backend or live acceptance.',
        'No market performance or fabricated realized profit; toy ranking reversal only.',
        'Limited semantic/overflow checks, no WCAG certification or usability study.',
        'Browser networking suppression plus CDP interception, not an OS packet capture.'])
    with output.open('x',encoding='utf-8') as stream:json.dump(dict(status='IN_PROGRESS'),stream)
    with log.open('x',encoding='utf-8') as stream,redirect_stdout(stream),redirect_stderr(stream):
        try:
            syntax=subprocess.run(['node','--check',str(APP/'public/terminal.js')],capture_output=True,text=True,timeout=10)
            receipt['syntax_preflight']=dict(command=['node','--check','public/terminal.js'],exit_code=syntax.returncode)
            print(syntax.stdout,syntax.stderr)
            if syntax.returncode!=0:raise RuntimeError('TERMINAL_JAVASCRIPT_SYNTAX_PREFLIGHT_FAILED')
            run(receipt,args.browser,prefix)
        except Exception as exc:receipt.update(error_type=type(exc).__name__,error=str(exc)[:600]);traceback.print_exc()
    receipt['source_after']={n:sha(APP/n) for n in SOURCES}
    passed=sum(c['passed'] for c in receipt['checks']);receipt['assertions']=dict(passed=passed,total=len(receipt['checks']))
    good=bool(passed) and passed==len(receipt['checks']) and 'error' not in receipt and receipt['source_before']==receipt['source_after'] and receipt.get('browser_exit_code')==0 and receipt.get('server_thread_stopped') and receipt.get('temporary_profile_removed') and len(receipt['screenshots'])==4
    receipt.update(status='PASS' if good else 'FAIL',exit_code=0 if good else 1,log=log.relative_to(APP).as_posix(),log_sha256=sha(log))
    output.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=receipt['status'],assertions=receipt['assertions'],receipt=output.relative_to(APP).as_posix())))
    return receipt['exit_code']


if __name__=='__main__':raise SystemExit(main())
