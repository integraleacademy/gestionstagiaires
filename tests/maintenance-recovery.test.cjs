// End-to-end browser test. Every request goes to this local HTTP fixture.
// Only the recovery page's hostname allowlist is adapted to the fixture origin.
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const hostname = '127.0.0.1';
let status = 200;
let transportDown = false;
let posts = 0;
let lastPost = '';
const server = http.createServer((req, res) => {
  if (transportDown) {
    req.socket.destroy();
    return;
  }
  res.setHeader('Cache-Control', 'no-store');
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const files = {
    '/service-worker.js': ['static/sw.js', 'application/javascript'],
    '/static/maintenance-register.js': ['static/maintenance-register.js', 'application/javascript'],
    '/static/maintenance.html': ['static/maintenance.html', 'text/html; charset=utf-8'],
  };
  if (files[pathname]) {
    const [file, type] = files[pathname];
    res.setHeader('Content-Type', type);
    let contents = fs.readFileSync(path.join(root, file), 'utf8');
    if (pathname === '/static/maintenance.html') {
      assert.ok(contents.includes("'gestionstagiaires-r5no.onrender.com'"));
      contents = contents.replace("'gestionstagiaires-r5no.onrender.com'", `'${hostname}'`);
    }
    return res.end(contents);
  }
  if (req.method === 'POST') {
    posts += 1;
    req.on('data', chunk => { lastPost += chunk; });
    req.on('end', () => { res.statusCode = 502; res.end('POST received once'); });
    return;
  }
  res.statusCode = status;
  if (pathname === '/healthz' || pathname.startsWith('/api/')) {
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({ ok: status === 200 }));
  }
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  if (status !== 200) return res.end('<body>Raw origin error</body>');
  res.end('<!doctype html><body><h1>Original page</h1><script defer src="/static/maintenance-register.js"></script></body>');
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://${hostname}:${server.address().port}`;
  const browser = await chromium.launch({
    ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
    args: ['--no-sandbox'],
  });
  try {
    const context = await browser.newContext();
    await context.addCookies([{ name: 'integrale_admin', value: 'local-test-session', url: origin, httpOnly: true }]);
    const page = await context.newPage();
    const originalURL = `${origin}/espace/test-only?tab=cours&value=a%2Fb#documents`;
    await page.goto(originalURL);
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) {
        await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
      }
    });
    const cacheContents = await page.evaluate(async () => {
      const names = await caches.keys();
      return Promise.all(names.map(async name => (await (await caches.open(name)).keys()).map(r => new URL(r.url).pathname)));
    });
    assert.deepEqual(cacheContents.flat(), ['/static/maintenance.html']);

    for (const code of [502, 503, 504]) {
      status = code;
      const response = await page.reload();
      assert.equal(response.status(), 503);
      await page.getByText('Veuillez patienter…', { exact: true }).waitFor();
      assert.equal(await page.locator('#resume-note').isVisible(), true);
      assert.equal(page.url(), originalURL);
      assert.equal(await page.getByRole('button').count(), 0);
    }
    const health = await page.evaluate(() => fetch('/healthz').then(async r => [r.status, await r.json()]));
    assert.deepEqual(health, [504, { ok: false }]);
    const api = await page.evaluate(() => fetch('/api/example').then(r => r.status));
    assert.equal(api, 504);
    const post = await page.evaluate(() => fetch('/form', { method: 'POST', body: 'test-payload' }).then(r => r.status));
    assert.equal(post, 502);
    assert.equal(posts, 1);
    assert.equal(lastPost, 'test-payload');

    status = 200;
    await page.getByRole('heading', { name: 'Original page' }).waitFor({ timeout: 20000 });
    assert.equal(page.url(), originalURL);
    assert.equal((await context.cookies()).find(c => c.name === 'integrale_admin').value, 'local-test-session');

    // Break the actual connection: browser offline emulation can leave a
    // service worker's independent network connection online in Chromium.
    transportDown = true;
    const offline = await page.reload();
    assert.equal(offline.status(), 503);
    await page.getByText('Veuillez patienter…', { exact: true }).waitFor();
    transportDown = false;
    await page.getByRole('heading', { name: 'Original page' }).waitFor({ timeout: 20000 });
    assert.equal(page.url(), originalURL);
    console.log('PASS real service worker: 502/503/504/offline, automatic return with path/query/hash and cookie, API/health unchanged, POST once, only public maintenance cached');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
