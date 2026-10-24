// Run with Playwright installed; optionally set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const origin = 'https://afc-documents.test';
const template = fs.readFileSync(path.join(root, 'templates/partials/afc_documents.html'), 'utf8')
  .replace(/{%[\s\S]*?%}/g, '')
  .replace(/{{ url_for\('static', filename='([^']+)'[^}]+}}/g, '/static/$1')
  .replace(/{{ url_for\('admin_afc_documents_preview'[^}]+}}/g, '/api/documents');

async function scenario(browser, mode, action = 'generate') {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const requests = [], effects = new Set(), completed = new Set(), counts = new Map(), errors = [];
  let token = 0, interrupted = mode === 'long-outage' || mode === 'auth', csrfExpired = false;
  page.on('pageerror', error => errors.push(error.message));
  if (mode === 'already-generated') for (let i = 1; i <= 5; i++) completed.add(`T${i}`);
  const respond = (route, status, data) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)});
  await page.route(origin + '/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/static/')) {
      return route.fulfill({contentType: url.pathname.endsWith('.js') ? 'application/javascript' : 'text/css',
        body: fs.readFileSync(path.join(root, url.pathname.slice(1)), 'utf8')});
    }
    if (url.pathname === '/api/documents') {
      token++;
      return respond(route, 200, {csrf: `csrf-${token}`, rows: Array.from({length: 12}, (_, i) => {
        const id = `T${i + 1}`;
        return {id, name: `Stagiaire ${i + 1}`, email: `stagiaire${i + 1}@example.test`, revision: `revision-${id}`,
          eligible: !completed.has(id), reason: 'Déjà générée', preview_url: '/preview/' + id, execute_url: '/api/documents/' + id};
      })});
    }
    if (url.pathname.startsWith('/api/documents/')) {
      const id = url.pathname.split('/').pop(), payload = request.postDataJSON();
      requests.push({id, ...payload});
      counts.set(id, (counts.get(id) || 0) + 1);
      if (mode === 'csrf' && !csrfExpired) {
        csrfExpired = true;
        return respond(route, 403, {code: 'csrf_expired', error: 'Actualisation de la session nécessaire.'});
      }
      if (mode === 'csrf') assert.equal(payload.csrf, `csrf-${token}`);
      if (id === 'T6') {
        if ((mode === 'restart' && counts.get(id) <= 2) || (mode === 'long-outage' && interrupted)) {
          return route.fulfill({status: 503, contentType: 'text/html', body: '<!DOCTYPE html><h1>Server restarting</h1>'});
        }
        if (mode === 'invalid-json' && counts.get(id) === 1) {
          return route.fulfill({status: 200, contentType: 'text/html', body: '<!DOCTYPE html><h1>Temporary proxy page</h1>'});
        }
        if (mode === 'pending' && counts.get(id) === 1) return respond(route, 202, {pending: true});
        if (mode === 'auth' && interrupted) return respond(route, 401, {error: 'Session expirée'});
      }
      if (!completed.has(id)) { completed.add(id); assert(!effects.has(id)); effects.add(id); }
      if (id === 'T6' && mode === 'lost-response' && counts.get(id) === 1) return route.abort('connectionreset');
      return respond(route, 200, {ok: true, message: action === 'send' ? 'Envoyée' : 'Générée'});
    }
    return route.fulfill({contentType: 'text/html', body: '<!doctype html><meta charset="utf-8">' + template});
  });
  if (mode === 'long-outage') await page.clock.install();
  await page.goto(origin + '/');
  await page.locator(`[data-afc-document="convention"][data-afc-action="${action}"]`).click();
  await page.locator('#afc-doc-run:enabled').waitFor();
  await page.locator('#afc-doc-run').click();
  if (mode === 'long-outage') {
    await page.waitForFunction(() => document.getElementById('afc-doc-feedback').textContent.includes('Nouvelle vérification'));
    await page.clock.fastForward(181000);
    await page.locator('#afc-doc-run:enabled').waitFor();
    assert.match(await page.locator('#afc-doc-feedback').textContent(), /5 générées.*7 en attente/);
    interrupted = false;
    await page.locator('#afc-doc-run').click();
  }
  if (mode === 'auth') {
    await page.locator('#afc-doc-run:enabled').waitFor();
    assert.equal(counts.get('T6'), 1, 'Authentication failures must not be retried automatically');
    interrupted = false;
    await page.locator('#afc-doc-run').click();
  }
  await page.locator('#afc-doc-run').waitFor({state: 'hidden', timeout: 30000});
  const feedback = await page.locator('#afc-doc-feedback').textContent();
  assert.match(feedback, mode === 'already-generated' ? /7 générées.*5 exclues.*terminé/ : new RegExp(`12 ${action === 'send' ? 'envoyées' : 'générées'}.*0 en erreur.*terminé`));
  assert.equal(effects.size, mode === 'already-generated' ? 7 : 12);
  for (const id of new Set(requests.map(request => request.id))) {
    const calls = requests.filter(request => request.id === id);
    assert.equal(new Set(calls.map(request => request.request_id)).size, 1, 'Retries and manual resume must keep the original request id');
    assert(calls.every(request => request.revision === `revision-${id}`), 'CSRF refresh must not silently adopt edited documents');
    if (id !== 'T6' && mode !== 'csrf') assert.equal(calls.length, 1, 'Finished dossiers must not run again');
  }
  assert.equal(errors.length, 0, errors.join('\n'));
  assert(!(await page.locator('#afc-doc-rows').textContent()).includes('Unexpected token'));
  console.log(JSON.stringify({scenario: mode, action, documents: effects.size, requests: requests.length, feedback}));
  await page.close();
}
(async () => {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || (fs.existsSync('/tmp/bts-chromium/chromium') ? '/tmp/bts-chromium/chromium' : undefined);
  const browser = await chromium.launch({headless: true, executablePath, args: ['--no-sandbox']});
  try {
    for (const mode of ['restart', 'invalid-json', 'pending', 'csrf', 'long-outage', 'auth', 'already-generated']) await scenario(browser, mode);
    await scenario(browser, 'lost-response', 'send');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode = 1;});
