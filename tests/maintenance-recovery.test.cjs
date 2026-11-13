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
let healthStatus = null;
let transportDown = false;
let transientNavigationFailures = 0;
let navigationDown = false;
let probeContent = null;
let probeType = 'text/html; charset=utf-8';
let probeRedirect = null;
let loginRequired = false;
let navigationRequests = 0;
let probeRequests = 0;
let probeCookie = '';
let posts = 0;
let lastPost = '';
function maintenanceHTML() {
  let html = fs.readFileSync(path.join(root, 'static/maintenance.html'), 'utf8');
  assert.ok(html.includes("'gestionstagiaires-r5no.onrender.com'"));
  // Accelerate only the polling clock. All real fetch/navigation/SW behavior
  // remains exercised, and neither fixture nor browser contacts production.
  return html.replace("'gestionstagiaires-r5no.onrender.com'", `'${hostname}'`)
    .replace('const interval = 12000;', 'const interval = 100;')
    .replace('const maxInterval = 30000;', 'const maxInterval = 300;');
}
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
      contents = maintenanceHTML();
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
    if (pathname === '/healthz' && healthStatus !== null) res.statusCode = healthStatus;
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({ ok: res.statusCode === 200 }));
  }
  const navigation = req.headers['sec-fetch-mode'] === 'navigate';
  if (req.headers['sec-fetch-dest'] === 'document') {
    assert.ok(navigation, 'service worker must preserve navigation metadata');
  }
  if (navigation) {
    navigationRequests += 1;
    if (navigationDown || transientNavigationFailures > 0) {
      transientNavigationFailures = Math.max(0, transientNavigationFailures - 1);
      res.statusCode = 502;
    }
  } else {
    probeRequests += 1;
    probeCookie = req.headers.cookie || '';
    if (probeRedirect && pathname !== '/login') {
      res.writeHead(302, { Location: probeRedirect });
      return res.end();
    }
  }
  if (loginRequired && pathname !== '/login') {
    res.writeHead(302, { Location: '/login' });
    return res.end();
  }
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  if (res.statusCode !== 200) return res.end('<body>Raw origin error</body>');
  if (!navigation && probeContent !== null) {
    res.setHeader('Content-Type', probeType);
    return res.end(probeContent);
  }
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
      await page.getByText('Reconnexion en cours…', { exact: true }).waitFor();
      assert.equal(await page.locator('#resume-note').isVisible(), true);
      assert.equal(page.url(), originalURL);
      assert.equal(await page.getByRole('button', { name: 'Réessayer' }).isVisible(), false);
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
    assert.ok(probeCookie.includes('integrale_admin=local-test-session'), 'probe must use the existing login');
    await page.waitForFunction(() => sessionStorage.getItem('integrale-maintenance-return') === null);

    // A one-off 502 is retried once without ever displaying the fallback.
    transientNavigationFailures = 1;
    const recovered = await page.reload();
    assert.equal(recovered.status(), 200);
    await page.getByRole('heading', { name: 'Original page' }).waitFor();

    // Existing pages remain untouched when the origin becomes unavailable.
    const beforeIdle = navigationRequests;
    status = 503;
    await page.waitForTimeout(500);
    assert.equal(navigationRequests, beforeIdle);
    await page.getByRole('heading', { name: 'Original page' }).waitFor();

    // Regression: a healthy /healthz must not reload a failing actual page.
    healthStatus = 200;
    await page.reload();
    const afterFailure = navigationRequests;
    const firstProbe = probeRequests;
    await page.waitForTimeout(1000);
    assert.ok(probeRequests >= firstProbe + 2);
    assert.equal(navigationRequests, afterFailure, 'no navigation while actual page is unavailable');
    await page.getByText('Connexion interrompue', { exact: true }).waitFor();

    // Even a 200 response must be a full application page, not a proxy
    // maintenance document, partial HTML, or an unrelated JSON response.
    status = 200;
    probeContent = maintenanceHTML();
    await page.waitForTimeout(650);
    assert.equal(navigationRequests, afterFailure);
    probeContent = '<p>Partial HTML</p>';
    await page.waitForTimeout(650);
    assert.equal(navigationRequests, afterFailure);
    probeContent = '{"ok":true}';
    probeType = 'application/json';
    await page.waitForTimeout(650);
    assert.equal(navigationRequests, afterFailure);
    probeContent = null;
    probeType = 'text/html; charset=utf-8';
    await page.getByRole('heading', { name: 'Original page' }).waitFor();
    assert.equal(page.url(), originalURL);

    // Race: the probe succeeds but the subsequent navigation fails. A guard
    // survives that failed return and stops the reloading cycle in this tab.
    status = 503;
    healthStatus = 503;
    await page.reload();
    navigationDown = true;
    status = 200;
    healthStatus = 200;
    await page.getByText('Le retour automatique est en pause.', { exact: true }).waitFor();
    const afterPausedReturn = navigationRequests;
    await page.waitForTimeout(1000);
    assert.equal(navigationRequests, afterPausedReturn);
    navigationDown = false;
    await page.getByRole('button', { name: 'Réessayer' }).click();
    await page.getByRole('heading', { name: 'Original page' }).waitFor();
    assert.equal(page.url(), originalURL);
    await page.waitForFunction(() => sessionStorage.getItem('integrale-maintenance-return') === null);

    // A login redirect on the same origin is a usable recovery, while a
    // cross-origin redirect must not receive the private recovery request.
    status = 503;
    healthStatus = 503;
    await page.reload();
    probeRedirect = 'https://example.invalid/login';
    status = 200;
    healthStatus = 200;
    const beforeRedirect = navigationRequests;
    await page.waitForTimeout(650);
    assert.equal(navigationRequests, beforeRedirect);
    probeRedirect = '/login';
    loginRequired = true;
    await page.getByRole('heading', { name: 'Original page' }).waitFor();
    assert.equal(new URL(page.url()).pathname, '/login');
    probeRedirect = null;
    loginRequired = false;
    healthStatus = null;
    await page.goto(originalURL);

    // Break the actual connection: browser offline emulation can leave a
    // service worker's independent network connection online in Chromium.
    transportDown = true;
    const offline = await page.reload();
    assert.equal(offline.status(), 503);
    await page.getByText('Reconnexion en cours…', { exact: true }).waitFor();
    transportDown = false;
    await page.getByRole('heading', { name: 'Original page' }).waitFor({ timeout: 20000 });
    assert.equal(page.url(), originalURL);
    // Browsers that refuse sessionStorage use a manual recovery instead of
    // navigating without a working loop guard.
    const noStorage = await context.newPage();
    await noStorage.addInitScript(() => {
      Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('Storage disabled'); } });
    });
    status = 503;
    await noStorage.goto(originalURL);
    await noStorage.getByText('Le retour automatique est en pause.', { exact: true }).waitFor();
    status = 200;
    const beforeManual = navigationRequests;
    await noStorage.waitForTimeout(650);
    assert.equal(navigationRequests, beforeManual);
    await noStorage.getByRole('button', { name: 'Réessayer' }).click();
    await noStorage.getByRole('heading', { name: 'Original page' }).waitFor();
    await noStorage.close();

    assert.equal(posts, 1, 'no POST replay during any recovery');
    const finalCacheContents = await page.evaluate(async () => {
      const names = await caches.keys();
      return Promise.all(names.map(async name => (await (await caches.open(name)).keys()).map(r => new URL(r.url).pathname)));
    });
    assert.deepEqual(finalCacheContents.flat(), ['/static/maintenance.html']);
    console.log('PASS real Chromium: transient/persistent failures, healthy healthz with failed page, complete authenticated HTML, no reload loop, manual recovery, storage denied, redirects, offline, path/query/hash, cookies, APIs unchanged, POST once, public cache only');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
