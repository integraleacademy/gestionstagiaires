self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = {};
  }

  const title = (data.title || 'Intégrale Connect').trim() || 'Intégrale Connect';
  const body = (data.body || 'Nouvelle notification admin').trim() || 'Nouvelle notification admin';
  const icon = data.icon || '/static/logo-integrale.png';
  const badge = data.badge || icon;
  const image = data.image || icon;

  const options = {
    body,
    icon,
    badge,
    image,
    tag: data.notification_id || 'admin-notification',
    renotify: false,
    timestamp: Date.now(),
    data: {
      url: data.url || '/admin/sessions',
      notification_id: data.notification_id || '',
    },
    actions: [
      {
        action: 'open',
        title: 'Ouvrir',
      },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/admin/sessions';
  event.waitUntil(clients.openWindow(targetUrl));
});


// Cache only this public maintenance document: never user pages or API data.
const MAINTENANCE_CACHE = 'integrale-maintenance-20261106-v1';
const MAINTENANCE_URL = '/static/maintenance.html';

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const response = await fetch(MAINTENANCE_URL, {
      cache: 'no-store', credentials: 'omit', redirect: 'error',
    });
    if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) {
      throw new Error('Maintenance page unavailable');
    }
    const html = await response.text();
    if (!html.includes('name="integrale-maintenance-page" content="1"')) {
      throw new Error('Unexpected maintenance document');
    }
    const cache = await caches.open(MAINTENANCE_CACHE);
    await cache.put(MAINTENANCE_URL, new Response(html, {
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name =>
      name.startsWith('integrale-maintenance-') && name !== MAINTENANCE_CACHE
    ).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

function maintenanceNavigation(request) {
  if (request.method !== 'GET' || request.mode !== 'navigate') return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  return !/^\/(healthz(?:\/|$)|api(?:\/|$)|internal(?:\/|$)|webhooks(?:\/|$)|static(?:\/|$)|\.well-known(?:\/|$)|service-worker\.js$)/.test(url.pathname);
}

async function maintenanceResponse(originalResponse, networkError) {
  const cache = await caches.open(MAINTENANCE_CACHE);
  const fallback = await cache.match(MAINTENANCE_URL);
  if (!fallback) {
    if (originalResponse) return originalResponse;
    throw networkError;
  }
  return new Response(await fallback.text(), {
    status: 503,
    statusText: 'Service Unavailable',
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store, max-age=0',
      'Retry-After': '12',
      'Referrer-Policy': 'no-referrer',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}

self.addEventListener('fetch', (event) => {
  if (!maintenanceNavigation(event.request)) return;
  event.respondWith((async () => {
    let response;
    try {
      response = await fetch(event.request);
    } catch (error) {
      return maintenanceResponse(null, error);
    }
    if ([502, 503, 504].includes(response.status)) {
      return maintenanceResponse(response);
    }
    return response;
  })());
});
