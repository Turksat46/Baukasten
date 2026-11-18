"""Als App installieren (Progressive Web App): Manifest, Service Worker, Offline-Seite.

- /manifest.webmanifest beschreibt die App: Name, Symbole, Farben, Start-Adresse.
- /sw.js ist der Service Worker. Er liegt bewusst unter / statt /static/, weil er nur Seiten
  unterhalb seiner eigenen Adresse betreuen darf.
- Zwischengespeichert werden nur statische Dateien (Stil, Skripte, Symbole) und die
  Offline-Seite. Seiten mit Daten der Apps werden nie zwischengespeichert: Sie enthalten
  persönliche Daten und sollen immer aktuell sein.

Installieren lässt sich die App nur über HTTPS (oder localhost); über http://192.168… legt der
Browser höchstens eine Verknüpfung auf dem Startbildschirm an.
"""
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control

THEME = "#006c7a"
BACKGROUND = "#eef0f2"
ICONS = [
    {"src": "builder/app/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "builder/app/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "builder/app/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
]


@cache_control(max_age=3600)
def manifest(request):
    data = {
        "id": "/",
        "name": "Baukasten",
        "short_name": "Baukasten",
        "description": _("Interne Apps aus Tabellen, Seiten und Bausteinen."),
        "lang": getattr(request, "LANGUAGE_CODE", "de"),
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": THEME,
        "background_color": BACKGROUND,
        "icons": [{**icon, "src": static(icon["src"])} for icon in ICONS],
        "shortcuts": [
            {"name": _("Meine Apps"), "url": "/"},
            {"name": _("Designer"), "url": "/designer/"},
            {"name": _("Hilfe"), "url": "/hilfe/"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json",
                        json_dumps_params={"ensure_ascii": False})


@cache_control(no_cache=True)  # Browser prüfen bei jedem Start, ob es eine neue Fassung gibt
def service_worker(request):
    from .templatetags.baukasten import asset

    precache = [asset("builder/theme.css"), asset("builder/style.css"), asset("builder/theme.js"),
                asset("builder/menu.js"), asset("builder/transitions.js"), static("builder/logo.svg"),
                static("builder/app/icon-192.png")]
    response = render(request, "builder/sw.js", {
        "version": settings.BAUKASTEN_VERSION, "precache": precache, "static_url": settings.STATIC_URL,
    }, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    """Wird vom Service Worker gezeigt, wenn keine Verbindung besteht. Ohne persönliche Daten,
    damit sie gefahrlos zwischengespeichert werden kann."""
    return render(request, "builder/offline.html")
