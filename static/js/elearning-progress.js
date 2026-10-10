/* Refresh only the authenticated report, keeping the reader's DOM and position. */
(function () {
  'use strict';
  const INTERVAL = 15000;
  const TIMEOUT = 10000;
  const REGION = '[data-el-live-region]';
  const KEY = 'data-el-live-key';

  function key(node) {
    return node.nodeType === 1 ? node.getAttribute(KEY) : null;
  }
  function compatible(a, b) {
    return Boolean(a && b && a.nodeType === b.nodeType && a.nodeName === b.nodeName && key(a) === key(b));
  }
  function updateNode(target, source) {
    if (target.nodeType === 3 || target.nodeType === 8) {
      if (target.nodeValue !== source.nodeValue) target.nodeValue = source.nodeValue;
      return;
    }
    // Native details state belongs to the reader, never to the fetched page.
    const keep = name => target.nodeName === 'DETAILS' && name === 'open';
    for (const attr of Array.from(target.attributes)) {
      if (!keep(attr.name) && !source.hasAttribute(attr.name)) target.removeAttribute(attr.name);
    }
    for (const attr of Array.from(source.attributes)) {
      if (!keep(attr.name) && target.getAttribute(attr.name) !== attr.value) target.setAttribute(attr.name, attr.value);
    }
    updateChildren(target, source);
  }
  function updateChildren(target, source) {
    let cursor = target.firstChild;
    const keyed = new Map(Array.from(target.childNodes).filter(node => key(node)).map(node => [key(node), node]));
    for (const fresh of Array.from(source.childNodes)) {
      let current = key(fresh) ? keyed.get(key(fresh)) : cursor;
      if (!compatible(current, fresh)) current = null;
      if (!current) {
        target.insertBefore(fresh.cloneNode(true), cursor);
        continue;
      }
      if (current !== cursor) target.insertBefore(current, cursor);
      updateNode(current, fresh);
      cursor = current.nextSibling;
    }
    while (cursor) {
      const next = cursor.nextSibling;
      target.removeChild(cursor);
      cursor = next;
    }
  }
  function hasSelection(root, win) {
    const selection = win.getSelection && win.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    try { return selection.getRangeAt(0).intersectsNode(root); }
    catch (_) { return root.contains(selection.anchorNode) || root.contains(selection.focusNode); }
  }
  function safeFocus(region, fresh, active) {
    if (!active || !region.contains(active)) return true;
    if (active.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.nodeName)) return false;
    // Keep focus in place. If its ancestor structure disappeared or moved,
    // defer this region until the reader moves focus elsewhere.
    const path = [];
    let cursor = active;
    while (cursor !== region) {
      path.unshift(Array.from(cursor.parentNode.childNodes).indexOf(cursor));
      cursor = cursor.parentNode;
    }
    let next = fresh;
    cursor = region;
    for (const index of path) {
      cursor = cursor.childNodes[index];
      next = next && next.childNodes[index];
      if (!compatible(cursor, next)) return false;
    }
    return true;
  }

  function createLiveProgress(env) {
    const {root, document: doc, window: win, fetch: fetchPage, DOMParser: Parser, AbortController: Controller} = env;
    const status = root.querySelector('[data-el-live-status]');
    const message = root.querySelector('[data-el-live-message]');
    const reload = root.querySelector('[data-el-live-reload]');
    const identity = root.getAttribute('data-el-live-report');
    const url = root.getAttribute('data-el-live-url');
    let timer = null, timeout = null, deferredTimer = null, controller = null;
    let busy = false, stopped = false, paused = false, pointerDown = false, rerun = false;
    let latest = null, failures = 0;
    const listeners = [];
    const online = () => !win.navigator || win.navigator.onLine !== false;
    const visible = () => !doc.hidden && !paused;
    const say = (text, state = 'ready') => {
      if (status) { status.hidden = false; status.dataset.state = state; }
      if (message && message.textContent !== text) message.textContent = text;
    };
    const clearTimer = () => { if (timer !== null) win.clearTimeout(timer); timer = null; };
    const schedule = delay => {
      clearTimer();
      if (!stopped && visible() && online()) timer = win.setTimeout(refresh, delay);
    };
    const stop = text => {
      stopped = true; clearTimer();
      if (controller) controller.abort();
      if (reload) reload.hidden = false;
      say(text, 'error');
    };
    const applyLatest = () => {
      if (!latest || !visible() || pointerDown || hasSelection(root, win)) return false;
      const active = doc.activeElement;
      const anchor = doc.elementFromPoint ? doc.elementFromPoint(Math.max(20, (win.innerWidth || 800) / 2), Math.min(150, (win.innerHeight || 600) / 3)) : null;
      const anchorTop = anchor && root.contains(anchor) ? anchor.getBoundingClientRect().top : null;
      let deferred = false;
      for (const region of Array.from(root.querySelectorAll(REGION))) {
        const name = region.getAttribute('data-el-live-region');
        const fresh = Array.from(latest.querySelectorAll(REGION)).find(node => node.getAttribute('data-el-live-region') === name);
        // Future interactive forms must never be overwritten by this reader.
        if (!fresh || region.querySelector('form') || fresh.querySelector('form')) continue;
        if (!safeFocus(region, fresh, active)) { deferred = true; continue; }
        updateNode(region, fresh);
      }
      if (anchorTop !== null && root.contains(anchor)) {
        const delta = anchor.getBoundingClientRect().top - anchorTop;
        if (Math.abs(delta) > 1 && win.scrollBy) win.scrollBy(0, delta);
      }
      if (!deferred) latest = null;
      return true;
    };
    const applySoon = () => {
      if (deferredTimer !== null) win.clearTimeout(deferredTimer);
      deferredTimer = win.setTimeout(() => { deferredTimer = null; applyLatest(); }, 0);
    };
    async function refresh() {
      clearTimer();
      if (stopped || !visible()) return;
      if (!online()) { say('Hors connexion. Le suivi reprendra automatiquement au retour du réseau.', 'offline'); return; }
      if (busy) { rerun = true; return; }
      busy = true;
      let retryDelay = INTERVAL;
      const backoff = () => { failures += 1; return Math.min(60000, INTERVAL * (2 ** Math.min(failures - 1, 2))); };
      controller = new Controller();
      timeout = win.setTimeout(() => controller && controller.abort(), TIMEOUT);
      try {
        const response = await fetchPage(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'text/html'}, signal: controller.signal});
        if (stopped || !visible() || !online()) return;
        if (response.redirected || response.status === 401 || response.status === 403) {
          stop('Votre session a expiré ou cet accès a changé. Reconnectez-vous pour reprendre le suivi.'); return;
        }
        if (!response.ok) {
          if (response.status === 404 || response.status === 410) {
            stop('Ce suivi n’est plus disponible. Les dernières données restent affichées.');
          } else {
            retryDelay = backoff();
            say('Le serveur est momentanément indisponible. Nouvelle tentative automatique…', 'offline');
          }
          return;
        }
        const html = await response.text();
        if (stopped || !visible()) return;
        const page = new Parser().parseFromString(html, 'text/html');
        const report = page.querySelector('[data-el-live-report]');
        if (!report || report.getAttribute('data-el-live-report') !== identity) {
          stop('La mise à jour n’a pas pu être vérifiée. Rechargez la page pour reprendre le suivi.'); return;
        }
        failures = 0;
        latest = report;
        applyLatest();
        say('Suivi mis à jour automatiquement.');
      } catch (_) {
        if (!stopped && visible() && online()) retryDelay = backoff();
        if (!stopped && visible()) say(online() ? 'Connexion momentanément interrompue. Nouvelle tentative automatique…' : 'Hors connexion. Le suivi reprendra automatiquement au retour du réseau.', 'offline');
      } finally {
        if (timeout !== null) win.clearTimeout(timeout);
        timeout = null; controller = null; busy = false;
        const immediately = rerun; rerun = false;
        schedule(immediately ? 0 : retryDelay);
      }
    }
    const on = (target, event, callback) => { target.addEventListener(event, callback); listeners.push([target, event, callback]); };
    on(doc, 'visibilitychange', () => {
      if (!visible()) { clearTimer(); if (controller) controller.abort(); }
      else { applyLatest(); refresh(); }
    });
    on(win, 'offline', () => {
      clearTimer(); if (controller) controller.abort();
      if (!stopped) say('Hors connexion. Le suivi reprendra automatiquement au retour du réseau.', 'offline');
    });
    on(win, 'online', () => { if (!stopped) refresh(); });
    on(doc, 'selectionchange', applySoon);
    on(root, 'focusout', applySoon);
    on(root, 'pointerdown', () => { pointerDown = true; });
    on(doc, 'pointerup', () => { pointerDown = false; applySoon(); });
    on(doc, 'pointercancel', () => { pointerDown = false; applySoon(); });
    on(win, 'pagehide', () => { paused = true; clearTimer(); if (controller) controller.abort(); });
    on(win, 'pageshow', event => { if (event.persisted) { paused = false; refresh(); } });
    say(online() ? 'Actualisation automatique du suivi' : 'Hors connexion. Le suivi reprendra automatiquement au retour du réseau.', online() ? 'ready' : 'offline');
    schedule(INTERVAL);
    return {
      refresh, applyLatest,
      destroy() {
        stopped = true; clearTimer();
        if (timeout !== null) win.clearTimeout(timeout);
        if (deferredTimer !== null) win.clearTimeout(deferredTimer);
        if (controller) controller.abort();
        listeners.forEach(([target, event, callback]) => target.removeEventListener(event, callback));
      },
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {createLiveProgress, updateNode, hasSelection, safeFocus};
  if (typeof document !== 'undefined') {
    const root = document.querySelector('[data-el-live-report]');
    if (root) createLiveProgress({root, document, window, fetch: window.fetch.bind(window), DOMParser, AbortController});
  }
})();
