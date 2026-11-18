// Service Worker des Baukastens (aus builder/templates/builder/sw.js, Version {{ version }}).
// Speichert nur statische Dateien und die Offline-Seite. Seiten mit Daten gehen immer ans Netz;
// ohne Verbindung erscheint stattdessen die Offline-Seite.
"use strict";

const CACHE = "baukasten-{{ version }}";
const OFFLINE = "/offline/";
const PRECACHE = [OFFLINE{% for url in precache %}, "{{ url|escapejs }}"{% endfor %}];
const STATIC = "{{ static_url|escapejs }}";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  // Alte Fassungen aufräumen
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("baukasten-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Seiten: immer aus dem Netz, ohne Verbindung die Offline-Seite
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)));
    return;
  }

  // Statische Dateien: aus dem Speicher, im Hintergrund auffrischen
  if (url.pathname.startsWith(STATIC)) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const fresh = fetch(request).then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          }).catch(() => cached);
          return cached || fresh;
        })
      )
    );
  }
  // Alles andere (API, MCP, nachladende Bausteine …) bleibt unberührt.
});
