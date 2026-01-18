// Service Worker para Happy Remesitas PWA
const CACHE_NAME = 'happy-remesitas-v2';
const urlsToCache = [
  '/static/css/style.css',
  '/static/manifest.json'
];

// Instalar Service Worker
self.addEventListener('install', event => {
  console.log('[SW] Instalando...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[SW] Cache abierto');
        // Cachear URLs de forma individual para no fallar si alguna no existe
        return Promise.allSettled(
          urlsToCache.map(url => cache.add(url).catch(e => console.log('[SW] No se pudo cachear:', url)))
        );
      })
      .then(() => {
        console.log('[SW] Instalacion completada');
      })
      .catch(err => {
        console.log('[SW] Error en cache:', err);
      })
  );
  self.skipWaiting();
});

// Activar Service Worker
self.addEventListener('activate', event => {
  console.log('[SW] Activando...');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Eliminando cache viejo:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
      console.log('[SW] Activacion completada');
    })
  );
  self.clients.claim();
});

// Interceptar peticiones
self.addEventListener('fetch', event => {
  // Solo cachear GET requests
  if (event.request.method !== 'GET') return;

  // No cachear APIs
  if (event.request.url.includes('/api/')) return;

  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Si está en cache, devolver
        if (response) {
          // Actualizar cache en background
          fetch(event.request).then(networkResponse => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then(cache => {
                cache.put(event.request, networkResponse);
              });
            }
          }).catch(() => {});
          return response;
        }

        // Si no está en cache, buscar en red
        return fetch(event.request).then(response => {
          if (!response || response.status !== 200) {
            return response;
          }

          // Clonar respuesta para cache
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
          });

          return response;
        });
      })
      .catch(() => {
        // Si falla todo, mostrar página offline
        if (event.request.mode === 'navigate') {
          return caches.match('/solicitar');
        }
      })
  );
});

// Notificaciones push
self.addEventListener('push', event => {
  console.log('[SW] Push recibido!');
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    console.log('[SW] Error parseando push data:', e);
    data = { title: 'Notificacion', body: event.data ? event.data.text() : 'Nueva notificacion' };
  }

  const options = {
    body: data.body || 'Nueva notificacion de Happy Remesitas',
    icon: '/static/images/icon-192.png',
    badge: '/static/images/icon-72.png',
    vibrate: [100, 50, 100],
    tag: 'remesitas-' + Date.now(),
    data: {
      url: data.url || '/'
    }
  };

  console.log('[SW] Mostrando notificacion:', data.title);
  event.waitUntil(
    self.registration.showNotification(data.title || 'Happy Remesitas', options)
  );
});

// Click en notificación
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});
