// The browser page against a live FreeRTOS stream (examples/freertos-posix):
// every view opens without a JavaScript error and draws something, the
// layouts and options switch cleanly, and no text meant for Ghazni shows up
// on a FreeRTOS stream.
//   node tests/test_ui.js [demo]       (npm i playwright; npx playwright install chromium)
// The tool: this checkout's package, or (SCOPE_INSTALLED=1) the installed command.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DEMO = process.argv[2] || path.join(ROOT, 'examples/freertos-posix/build/demo');
let fails = 0;
function check(name, ok, detail) {
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${ok ? '' : ': ' + JSON.stringify(detail).slice(0, 400)}`);
  if (!ok) fails++;
}
const freePort = () => new Promise(res => { const s = net.createServer().listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); });
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const port = await freePort();
  const installed = !!process.env.SCOPE_INSTALLED;
  const cmd = installed ? 'ghazni-scope' : 'python3';
  const args = (installed ? [] : ['-m', 'ghazni_scope']).concat(['--exec', DEMO, '--port', String(port), '--quiet']);
  const env = Object.assign({}, process.env, installed ? {} : { PYTHONPATH: ROOT });
  const tool = spawn(cmd, args, { env, stdio: 'ignore' });
  console.log('=== web page (FreeRTOS on Linux, live) ===');
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    for (let i = 0; i < 50; i++) { try { await page.goto(`http://127.0.0.1:${port}/`); break; } catch (e) { await sleep(200); } }
    await page.waitForFunction(() => typeof D !== "undefined" && D.events && D.events.length > 3000, null, { timeout: 30000 });
    check('page loads, live stream arrives, title shows FreeRTOS',
      await page.evaluate(() => document.getElementById('osName').textContent.includes('FreeRTOS')), null);

    // a canvas that drew something: more than one colour in it
    const inked = id => page.evaluate(id => {
      const c = document.getElementById(id), g = c.getContext('2d');
      if (!c.width || !c.height) return 0;
      const d = g.getImageData(0, 0, c.width, c.height).data, seen = new Set();
      for (let i = 0; i < d.length; i += 4 * 97) seen.add(d[i] << 16 | d[i + 1] << 8 | d[i + 2] | d[i + 3] << 24);
      return seen.size;
    }, id);
    const rows = sel => page.evaluate(sel => document.querySelectorAll(sel).length, sel);
    const views = [
      ['trace', () => inked('cTrace'), n => n > 5],
      ['log', () => rows('#logTab tr'), n => n > 10],
      ['load', () => inked('cLoad'), n => n > 3],
      ['inst', () => inked('cInst'), n => n > 3],
      ['user', () => inked('cUser'), n => n > 3],
      ['sm', () => inked('cSm'), n => n > 3],
      ['heap', () => inked('cHeap'), n => n > 3],
      ['deps', () => rows('#sDeps circle, #sDeps rect, #sDeps ellipse'), n => n >= 3],
      ['comm', () => rows('#sComm ellipse'), n => n >= 5],
      ['obj', () => rows('#objTab tr'), n => n > 5],
      ['stats', () => rows('#statTab tr'), n => n > 8],
      ['console', () => page.evaluate(() => document.getElementById('console').textContent.length), n => n > 10],
    ];
    await page.click('#bPause');
    for (const [v, measure, ok] of views) {
      await page.click(`nav a[data-v=${v}]`);
      await sleep(700);
      const n = await measure();
      check(`view ${v}: drawn (${n}), no error`, ok(n) && !errors.length, { n, errors });
    }
    // layouts and options
    await page.click('nav a[data-v=trace]');
    for (const [btn, what] of [['#bHorz', 'horizontal'], ['#bVert', 'vertical'], ['#bCpus', 'columns = CPUs'],
                               ['#bTasks', 'columns = tasks'], ['#bTheme', 'dark'], ['#bTheme', 'light'], ['#bFit', 'whole record']]) {
      await page.click(btn); await sleep(400);
      check(`trace: ${what}`, (await inked('cTrace')) > 5 && !errors.length, errors);
    }
    // the names above the columns fit in the header (none cut off at the top)
    const head = await page.evaluate(() => {
      const g = document.getElementById('cTrace').getContext('2d');
      g.font = "11px -apple-system, Segoe UI, Noto Sans KR, sans-serif";
      const { cw, HEAD } = traceGeom, names = Object.values(D.tasks).map(t => t.name)
        .concat((D.objects.notifications || []).map((n, i) => objLabel('nt', i)));
      const need = Math.max(...names.map(n => { const w = g.measureText(n).width; return w > cw - 4 ? w * 0.87 + 10 : 0; }));
      return { HEAD, need };
    });
    check('trace: column names at an angle fit in the header', head.need <= head.HEAD, head);
    await page.click('nav a[data-v=heap]');
    await page.click('#heapOut'); await sleep(400);
    check('heap: allocations outside tasks shown again', (await inked('cHeap')) > 3 && !errors.length, errors);
    await page.click('#heapOut');
    // trigger: added, hits counted, no error
    await page.fill('#trigIn', 'isr * >0us'); await page.click('#trigAdd');
    await page.click('#bLive'); await sleep(2500);
    const hits = await page.evaluate(() => D.triggers.map(t => t.hits));
    check('trigger added and hit', hits.length === 1 && hits[0] > 0 && !errors.length, { hits, errors });
    // nothing meant for Ghazni on a FreeRTOS stream
    const text = await page.evaluate(() => document.body.innerText + ' ' +
      [...document.querySelectorAll('input[placeholder]')].map(i => i.placeholder).join(' '));
    const ghazni = ['ghazni_trace', 'uart_drv', '셸:', 'ntfn ', 'notification '].filter(w => text.includes(w));
    check('no Ghazni-only text on a FreeRTOS stream', ghazni.length === 0, ghazni);
  } finally {
    await browser.close();
    tool.kill();
  }
  console.log(fails ? `${fails} FAILED` : 'ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
