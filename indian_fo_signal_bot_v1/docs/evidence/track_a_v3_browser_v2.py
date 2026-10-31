"""Actual terminal assets, bounded headless CDP, authored loopback HTTP fixtures.

No application/config imports, environment reads, databases or market calls.
Four selected screenshots per run; overflow probes are not WCAG certification.
"""
import argparse
import base64
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
STAMP = '2026-10-16T10:00:00+05:30'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(symbol):
    return dict(provider='authored-fixture', symbol=symbol, identifier='SYNTHETIC-'+symbol,
                exchange='NSE', segment='NSE_EQUITY_INTRADAY', instrument_type='EQ')


def ranking(mode):
    now = datetime.now(timezone.utc)
    symbols = ['INFY', 'TCS', 'ORBIT-DEMO'] if mode['reverse'] else ['TCS', 'INFY', 'ORBIT-DEMO']
    rows = [dict(rank=i+1, previous_rank=(2-i if i<2 else 3), symbol=s,
        opportunity_key='synthetic-'+s, candidate_id='synthetic-'+s,
        strategy_id='strat_4_orb_filtered', position_type='LONG_EQUITY_INTRADAY', direction='LONG',
        instrument_identity=identity(s), actionable=False, source_data_watermark=STAMP,
        score_components=dict(rule_quality=80-i*5, actual_target1_rr=1.8+i*.1),
        rank_change_reason='RELATIVE_ORDER_CHANGED' if mode['reverse'] else 'NEWLY_QUALIFIED',
        missing_components=['OBSERVED_SPREAD', 'NET_EXECUTABLE_REWARD', 'EMPIRICAL_EDGE']) for i,s in enumerate(symbols)]
    if mode['source'] != 'demo':
        return dict(status='UNAVAILABLE', actionable=False, current_rows=[], historical_rows=[], snapshot=None)
    return dict(status='CURRENT_CANDIDATE_PRIORITY', actionable=False, evidence_scope=SCOPE,
        as_of=now.isoformat(), current_rows=rows, historical_rows=rows,
        pagination=dict(total=3, limit=20, offset=0), snapshot=dict(run_id='synthetic-run',
            reference=now.isoformat(), valid_until=(now+timedelta(seconds=mode['lifetime'])).isoformat(),
            scope=dict(provider='authored-fixture'), evidence_scope=SCOPE, removals=[]))


def candles(symbol):
    start=datetime.fromisoformat(STAMP)-timedelta(minutes=5*9)
    return [dict(timestamp=(start+timedelta(minutes=5*i)).isoformat(), open=100+i*.1,
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
    mode=dict(source='none',reverse=False,lifetime=30)
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
            status=200;mime='application/json';payload={}
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
                elif path=='/api/opportunity-rankings':payload=ranking(mode)
                elif path=='/api/paper-portfolio':
                    payload=dict(status='OK',reconciliation=dict(status='OK'),as_of_ist=STAMP,
                        accounting=dict(open_positions=0,closed_positions=0,fees_paid_inr=0),
                        positions=[],events=[],candidate_decisions=[],total_positions=0,total_events=0,total_candidate_decisions=0,
                        evidence_scope=SCOPE,financial_mutations=False)
                elif path=='/api/signals':
                    symbol=query.get('symbol',[''])[0]
                    payload=dict(items=[dict(symbol=symbol,strategy_id='strat_4_orb_filtered',position_type='LONG_EQUITY_INTRADAY',
                        instrument_identity=identity(symbol),timestamp=STAMP,entry_price=101.1,invalidation_level=99.5,stop_loss=99,
                        target_1=105,target_2=107,rationale='SYNTHETIC TEST INPUT <img src=x onerror="window.__xss=1">',
                        evidence_scope=SCOPE)],total_count=1)
                elif path=='/api/scan-lineage':
                    payload=dict(run_id='synthetic-run',status='COMMITTED',source_authenticity='NOT_ESTABLISHED',
                        batches=[dict(batch_id='synthetic-'+s,identity=identity(s),interval_min=5,candle_count=10,last_timestamp=STAMP)
                                 for s in ('TCS','INFY','ORBIT-DEMO')])
                elif path=='/api/cash-candles':
                    batch=query.get('batch_id',[''])[0];symbol=batch.removeprefix('synthetic-')
                    payload=dict(run_id='synthetic-run',batch_id=batch,total_count=10,items=candles(symbol))
                elif path=='/api/backtest-eligibility':payload=dict(strategies={})
                elif path in ('/api/scans','/api/oi-snapshots'):payload=dict(items=[],total_count=0)
                elif path=='/api/config':payload=dict(config=dict(telegram_dry_run=True,enable_background_scheduler=False))
                elif path=='/favicon.ico':status=204
                else:status=404;failures.append('UNDEFINED_ROUTE '+path)
                body=json.dumps(payload,allow_nan=False).encode()
            requests.append(dict(method=self.command,path=path,query=query,status=status))
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
                fixture_scope=SCOPE,route='#/pulse',viewport=cdp.evaluate('({width:innerWidth,height:innerHeight})')))
        for label,width,height,mobile in [('desktop',1440,900,False),('mobile',390,844,True)]:
            metrics(width,height,mobile);mode.update(source='none',reverse=False,lifetime=30)
            cdp.command('Page.navigate',dict(url=origin+'/#/pulse'))
            check(label+'.no_source',cdp.wait("document.querySelector('#view')?.textContent.includes('clear signal starts') && document.querySelector('#source-status')?.dataset.state!=='LOADING'"))
            check(label+'.no_source_no_cards',cdp.evaluate("document.querySelectorAll('.candidate').length===0"))
            capture(label+'_no_source')
            mode['source']='error';cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.error_distinct',cdp.wait("document.querySelector('#source-status')?.dataset.state==='ERROR'"))
            mode['source']='demo';cdp.evaluate("document.querySelector('#refresh-data').click()")
            check(label+'.demo_three',cdp.wait("document.querySelectorAll('.candidate').length===3 && document.querySelector('#notice').textContent.includes('SYNTHETIC TEST DATA')"))
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
        check('external_blocked',cdp.evaluate("fetch('https://blocked.example/v3-probe').then(()=>false).catch(()=>true)") is True and any(r['host']=='blocked.example' for r in cdp.blocked))
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
    prefix='track_a_v3_browser_v2_'+args.stage;output=E/(prefix+'.json');log=E/(prefix+'.txt')
    if output.exists() or log.exists() or list(IMAGES.glob(prefix+'*.png')):parser.error('Immutable stage already exists')
    receipt=dict(schema='tradepulse.v3-browser-fixture.v1',status='FAIL',browser=args.browser,checks=[],screenshots=[],
        recorded_at=datetime.now(timezone.utc).isoformat(),helper_sha256=sha(Path(__file__)),source_before={n:sha(APP/n) for n in SOURCES},
        application_imports=False,environment_read=False,operational_database_accessed=False,provider_requests=0,
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
