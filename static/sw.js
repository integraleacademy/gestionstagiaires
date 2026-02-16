self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = {};
  }

  const title = (data.title || 'Intégrale Academy').trim() || 'Intégrale Academy';
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
