"""Beispiele für eigene Logik in Python.

Jede Datei in diesem Ordner wird beim Start geladen. Alles, was sich hier
anmeldet, steht danach im Designer zur Auswahl.
"""
import logging

from django.utils import timezone
from django.utils.html import format_html

from builder import hooks

log = logging.getLogger(__name__)


@hooks.action("begruessung", label="Beispiel: Begrüßung anzeigen")
def begruessung(request, app):
    """Eine Aktion: im Designer einem Button zuweisen („Python-Aktion ausführen“)."""
    return f"Hallo {request.user.get_username()}, das kam aus Python (App „{app.name}“)."


@hooks.on_save()
def protokoll(record, created, user):
    """Läuft nach jedem Speichern. Mit on_save(entity="gerate") nur für eine Tabelle."""
    log.info("%s %s in %s", "Neu:" if created else "Geändert:", record, record.entity.name)


@hooks.block("uhrzeit", label="Uhrzeit (Beispiel)", icon="🕒")
def uhrzeit(request, app):
    """Ein eigener Baustein für den Seiten-Designer."""
    now = timezone.localtime()
    return format_html("<h3>Aktuelle Uhrzeit</h3><p>{}</p>", now.strftime("%d.%m.%Y, %H:%M Uhr"))


# Web-Requests an andere Systeme:
#
#   from builder.services import http_json
#
#   @hooks.action("wetter", label="Wetter abrufen")
#   def wetter(request, app):
#       daten = http_json("https://api.example.com/wetter")   # Host muss in HTTP_ALLOWED_HOSTS stehen
#       return f"Temperatur: {daten['temperatur']} °C"


@hooks.api("statistik")
def statistik(request, app, daten):
    """Ein eigener API-Endpunkt: GET /api/v1/<app>/x/statistik/"""
    return {"app": app.name, "tabellen": {e.name: e.records.count() for e in app.entities.all()}}
