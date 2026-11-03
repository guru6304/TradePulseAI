import http from 'http';
import { spawn, execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = __dirname;
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const FRONTEND_DIST = path.join(FRONTEND_DIR, 'dist');
const BACKEND_DIR = path.join(REPO_ROOT, 'indian_fo_signal_bot_v1');
const BACKEND_SCRIPT = path.join(BACKEND_DIR, 'offline_backend_server.py');
const EVIDENCE_DIR = path.join(BACKEND_DIR, 'docs', 'project', 'ui-evidence');

const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 8000;
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT) || 5173;
const CHROME_DEBUG_PORT = Number(process.env.CHROME_DEBUG_PORT) || 9222;

// Detect Chrome / Chromium executable
function findChromeExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'Google\\Chrome\\Application\\chrome.exe') : null,
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);

  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return null;
}

const CHROME_PATH = findChromeExecutable();
if (!CHROME_PATH) {
  console.error('ERROR: No Chrome or Chromium executable found on this system.');
  console.error('Please install Chrome or set the CHROME_PATH environment variable.');
  process.exit(1);
}

const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 1. Ensure production build exists in frontend/dist
console.log('Ensuring frontend production build is current in frontend/dist...');
execSync('npm.cmd run build', { cwd: FRONTEND_DIR, stdio: 'inherit' });

// 2. Start offline backend server
console.log(`Starting offline Python backend server on port ${BACKEND_PORT}...`);
const backendProc = spawn('python', ['-u', BACKEND_SCRIPT, String(BACKEND_PORT)], {
  cwd: BACKEND_DIR,
  stdio: ['ignore', 'pipe', 'inherit'],
});

let backendReady = false;
backendProc.stdout.on('data', (d) => {
  const str = d.toString();
  if (str.includes('READY')) backendReady = true;
});

for (let i = 0; i < 30; i++) {
  if (backendReady) break;
  try {
    const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/health`, {
      headers: { Origin: `http://127.0.0.1:${BACKEND_PORT}` },
    });
    if (res.ok) {
      backendReady = true;
      break;
    }
  } catch {}
  await sleep(200);
}

if (!backendReady) {
  backendProc.kill('SIGKILL');
  throw new Error('Offline Python backend server failed to start in time');
}
console.log(`Backend is running and responding to /api/health on port ${BACKEND_PORT}!`);

// 3. Start Frontend HTTP static & proxy server on port 5173
console.log(`Starting HTTP frontend static & proxy server on port ${FRONTEND_PORT}...`);
const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname.startsWith('/api/')) {
    // Proxy to backend
    const proxyReq = http.request(
      {
        hostname: '127.0.0.1',
        port: BACKEND_PORT,
        path: url.pathname + url.search,
        method: req.method,
        headers: {
          ...req.headers,
          host: `127.0.0.1:${BACKEND_PORT}`,
          origin: `http://127.0.0.1:${BACKEND_PORT}`,
          'sec-fetch-site': 'same-origin',
        },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );
    proxyReq.on('error', (err) => {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    });
    req.pipe(proxyReq);
    return;
  }

  // Serve static dist
  let filePath = path.join(FRONTEND_DIST, url.pathname);
  if (url.pathname === '/' || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(FRONTEND_DIST, 'index.html');
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(500);
      res.end('Error loading file');
    } else {
      res.writeHead(200, {
        'Content-Type': contentType,
        'Cache-Control': 'no-cache',
      });
      res.end(content);
    }
  });
});

await new Promise((resolve) => server.listen(FRONTEND_PORT, '127.0.0.1', resolve));
console.log(`Frontend HTTP server running at http://127.0.0.1:${FRONTEND_PORT}`);

// Ensure evidence directory exists
if (!fs.existsSync(EVIDENCE_DIR)) {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
}

// 4. Launch headless Chrome with DevTools Protocol port
const userDataDir = path.join(process.env.TEMP || 'C:\\temp', 'cdp_acceptance_' + Date.now());
console.log(`Launching Headless Chrome on port ${CHROME_DEBUG_PORT} (${CHROME_PATH})...`);
const chromeProc = spawn(
  CHROME_PATH,
  [
    '--headless=new',
    `--remote-debugging-port=${CHROME_DEBUG_PORT}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    `--user-data-dir=${userDataDir}`,
  ],
  { stdio: 'ignore' }
);

async function getVersion() {
  for (let i = 0; i < 25; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${CHROME_DEBUG_PORT}/json/version`);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome did not start in time on debug port');
}

const version = await getVersion();
console.log(`Connected to Chrome: ${version.Browser}`);

const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.onopen = resolve;
  ws.onerror = reject;
});

let msgId = 1;
function sendCommand(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    const handler = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.id === id) {
        ws.removeEventListener('message', handler);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

const target = await sendCommand('Target.createTarget', { url: 'about:blank' });
const attached = await sendCommand('Target.attachToTarget', { targetId: target.targetId, flatten: true });

function sendSession(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    const handler = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.id === id) {
        ws.removeEventListener('message', handler);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, sessionId: attached.sessionId, method, params }));
  });
}

await sendSession('Page.enable');
await sendSession('Runtime.enable');
await sendSession('DOM.enable');

const results = [];

async function setViewport(width, height, isMobile = false) {
  await sendSession('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 2,
    mobile: isMobile,
  });
  await sendSession('Emulation.setVisibleSize', { width, height });
}

async function evalInPage(expression) {
  const res = await sendSession('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (res.exceptionDetails) {
    throw new Error('Eval error: ' + JSON.stringify(res.exceptionDetails));
  }
  return res.result?.value;
}

async function capture(filename) {
  const screenshot = await sendSession('Page.captureScreenshot', { format: 'png' });
  const outPath = path.join(EVIDENCE_DIR, filename);
  fs.writeFileSync(outPath, Buffer.from(screenshot.data, 'base64'));
  console.log(`Saved screenshot: ${filename} (${Math.round((screenshot.data.length * 0.75) / 1024)} KB)`);
}

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900, isMobile: false },
  { name: 'tablet', width: 768, height: 1024, isMobile: false },
  { name: 'mobile', width: 390, height: 844, isMobile: true },
];

const VIEWS = [
  { name: 'pulse', route: '#/pulse', expectedText: 'The Opportunity Shortlist' },
  { name: 'opportunities', route: '#/opportunities', expectedText: 'RELIANCE' },
  { name: 'options', route: '#/options', expectedText: 'Options Lab' },
  { name: 'strategies', route: '#/strategies', expectedText: 'Strategies & Research' },
  { name: 'paper', route: '#/paper', expectedText: 'Paper Portfolio' },
  { name: 'health', route: '#/health', expectedText: 'Health & Diagnostics' },
  { name: 'admin-research', route: '#/admin-research', expectedText: 'Admin Research' },
];

try {
  // Loop over viewports and views
  for (const vp of VIEWPORTS) {
    console.log(`\n======================================================`);
    console.log(`TESTING VIEWPORT: ${vp.name.toUpperCase()} (${vp.width}x${vp.height})`);
    console.log(`======================================================`);
    await setViewport(vp.width, vp.height, vp.isMobile);

    for (const v of VIEWS) {
      console.log(`\n--- Validating View: ${v.name} (${v.route}) at ${vp.name} ---`);
      await sendSession('Page.navigate', { url: `http://127.0.0.1:${FRONTEND_PORT}/${v.route}` });
      await sleep(800);

      // Verify DOM content
      const bodyText = await evalInPage('document.body.innerText');
      const hasExpected = bodyText.includes(v.expectedText);
      console.log(`Content check ("${v.expectedText}"): ${hasExpected ? 'PASS' : 'FAIL'}`);

      // Check overflow on root / body
      const overflow = await evalInPage(`({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
      })`);
      const hasHorizontalOverflow = overflow.scrollWidth > vp.width || overflow.bodyScrollWidth > vp.width;
      console.log(
        `Horizontal overflow check: ${hasHorizontalOverflow ? 'WARN (overflow detected)' : 'PASS (no page clipping)'}`
      );

      // Capture screenshot
      const filename = `tradepulse_u2b_${v.name}_${vp.name}.png`;
      await capture(filename);

      results.push({
        viewport: vp.name,
        view: v.name,
        route: v.route,
        contentCheck: hasExpected ? 'PASS' : 'FAIL',
        horizontalOverflow: hasHorizontalOverflow ? 'FAIL' : 'PASS',
        screenshot: filename,
      });

      // Special interaction testing on Opportunities view
      if (v.name === 'opportunities') {
        console.log(`-> Testing Opportunities interaction on ${vp.name}...`);

        // 1. Check predecessor rank display
        const rankChangeText = await evalInPage(
          `Array.from(document.querySelectorAll('tr')).map(r => r.innerText).find(t => t.includes('RELIANCE'))`
        );
        console.log(`RELIANCE rank row text: "${rankChangeText?.replace(/\\n/g, ' ')}"`);
        const showsPrior = rankChangeText && (rankChangeText.includes('(prior #3)') || rankChangeText.includes('#1'));
        console.log(`Predecessor rank display check: ${showsPrior ? 'PASS' : 'FAIL'}`);

        // 2. Open X-Ray Drawer by focusing and clicking inspect on RELIANCE
        console.log(`-> Clicking Inspect on candidate RELIANCE...`);
        const inspectClicked = await evalInPage(`(() => {
          const btn = Array.from(document.querySelectorAll('button')).find(b => b.getAttribute('aria-label') === 'Inspect RELIANCE');
          if (btn) { btn.focus(); btn.click(); return true; }
          return false;
        })()`);
        console.log(`Inspect clicked: ${inspectClicked}`);
        await sleep(1000);

        // Capture X-Ray open screenshot
        const xrayFilename = `tradepulse_u2b_xray_open_${vp.name}.png`;
        await capture(xrayFilename);

        // Check focus and X-Ray content
        const xrayContent = await evalInPage(`(() => {
          const dialog = document.querySelector('[role="dialog"]');
          return {
            hasDialog: !!dialog,
            ariaModal: dialog?.getAttribute('aria-modal'),
            focusedButton: document.activeElement?.getAttribute('aria-label'),
            hasCandles: document.body.innerText.includes('Retained 5-Minute Candles'),
            hasDiagnosticsTab: document.body.innerText.includes('Paper & Lineage'),
          };
        })()`);
        console.log(
          `X-Ray Dialog check: hasDialog=${xrayContent.hasDialog}, ariaModal=${xrayContent.ariaModal}, focusedButton=${xrayContent.focusedButton}`
        );

        // Switch to Diagnostics tab in X-Ray
        await evalInPage(`(() => {
          const tab = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Paper & Lineage'));
          if (tab) tab.click();
        })()`);
        await sleep(500);

        const diagText = await evalInPage('document.body.innerText');
        const hasRejectionReason = diagText.includes('CONFLICTING_OPEN_POSITION');
        console.log(`X-Ray CONFLICTING_OPEN_POSITION reason check: ${hasRejectionReason ? 'PASS' : 'FAIL'}`);

        const xrayDiagFilename = `tradepulse_u2b_xray_diagnostics_${vp.name}.png`;
        await capture(xrayDiagFilename);

        // Test Escape key dismissal
        console.log(`-> Pressing Escape key to dismiss X-Ray drawer...`);
        await sendSession('Input.dispatchKeyEvent', {
          type: 'rawKeyDown',
          key: 'Escape',
          code: 'Escape',
          windowsVirtualKeyCode: 27,
        });
        await sendSession('Input.dispatchKeyEvent', {
          type: 'keyUp',
          key: 'Escape',
          code: 'Escape',
          windowsVirtualKeyCode: 27,
        });
        await sleep(500);

        const dialogClosed = await evalInPage(`!document.querySelector('[role="dialog"]')`);
        console.log(`X-Ray Escape key dismissal check: ${dialogClosed ? 'PASS' : 'FAIL'}`);

        const restoredFocus = await evalInPage(`document.activeElement?.getAttribute('aria-label')`);
        console.log(
          `X-Ray Focus restoration check: activeElement aria-label="${restoredFocus}" -> ${
            restoredFocus === 'Inspect RELIANCE' ? 'PASS' : 'FAIL'
          }`
        );

        // Test pagination controls (25 candidates)
        console.log(`-> Testing 20-row client pagination controls...`);
        const paginationInfo1 = await evalInPage(
          `document.querySelector('[data-testid="pagination-info"]')?.innerText`
        );
        const prevDisabled1 = await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Previous'))?.disabled`
        );
        const nextDisabled1 = await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Next'))?.disabled`
        );
        console.log(`Page 1: "${paginationInfo1}" | Prev disabled: ${prevDisabled1} | Next disabled: ${nextDisabled1}`);

        // Click Next
        await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Next'))?.click()`
        );
        await sleep(400);

        const paginationInfo2 = await evalInPage(
          `document.querySelector('[data-testid="pagination-info"]')?.innerText`
        );
        const prevDisabled2 = await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Previous'))?.disabled`
        );
        const nextDisabled2 = await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Next'))?.disabled`
        );
        console.log(`Page 2: "${paginationInfo2}" | Prev disabled: ${prevDisabled2} | Next disabled: ${nextDisabled2}`);

        const page2Filename = `tradepulse_u2b_opportunities_page2_${vp.name}.png`;
        await capture(page2Filename);

        // Click Previous back to page 1
        await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Previous'))?.click()`
        );
        await sleep(300);
      }

      // Special mobile navigation test
      if (vp.name === 'mobile' && v.name === 'pulse') {
        console.log(`-> Testing Mobile 'More' popover sheet...`);
        await evalInPage(
          `Array.from(document.querySelectorAll('button')).find(b => b.getAttribute('aria-label') === 'More destinations')?.click()`
        );
        await sleep(400);

        const moreOpen = await evalInPage(`!!document.querySelector('[role="menu"]')`);
        console.log(`Mobile More sheet open check: ${moreOpen ? 'PASS' : 'FAIL'}`);

        const mobileMoreFilename = `tradepulse_u2b_mobile_more_sheet.png`;
        await capture(mobileMoreFilename);

        // Close More sheet
        await evalInPage(`document.querySelector('button[aria-label="Close menu"]')?.click()`);
        await sleep(300);
      }
    }
  }

  console.log('\n======================================================');
  console.log('ALL VIEWPORT AND INTERACTION CHECKS COMPLETED!');
  console.log('======================================================');
  console.log(JSON.stringify(results, null, 2));
} finally {
  console.log('\nCleaning up processes...');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }
  chromeProc.kill('SIGKILL');
  server.close();
  backendProc.kill('SIGKILL');
  try {
    fs.rmSync(userDataDir, { recursive: true, force: true });
  } catch {}
}
