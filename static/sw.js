self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = {};
  }

  const title = data.title || 'Gestion stagiaires';
  const options = {
    body: data.body || 'Nouvelle notification admin',
    icon: '/static/logo-integrale.png',
    badge: '/static/logo-integrale.png',
    data: {
      url: data.url || '/admin/sessions',
    },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/admin/sessions';
  event.waitUntil(clients.openWindow(targetUrl));
});
