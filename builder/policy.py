"""Wer darf was: alle Rechte-Entscheidungen des Baukastens an einer Stelle (ADR 0012).

Ansichten, Bausteine, Skript-Brücke und Tabellen-Zugriff fragen nur noch hier:

    from .policy import darf, pruefe, LESEN
    if not darf(request.user, LESEN, entity): ...
    pruefe(request.user, AENDERN, entity)        # sonst PermissionDenied

Die Modelle liefern nur Fakten (Gruppen der App, der Seite, der Tabelle; Designer-Recht). Was eine
Aktion daraus macht – Schalter der Tabelle, Gäste auf öffentlichen Seiten, Bearbeiter dürfen
immer – steht ausschließlich in diesem Modul. Neue Zugriffswege bekommen eine Aktion hier und eine
Zeile im Matrix-Test (tests/test_policy.py), keine eigene Prüfung.

Begriffe:
- Mitglied: angemeldet und darf die App benutzen (App-Gruppen oder Bearbeiter).
- Gast: alle anderen. Gäste erreichen nur öffentliche Seiten veröffentlichter Apps und was dort
  steht (Formulare, Buttons; siehe App.public_reach).
"""
from django.core.exceptions import PermissionDenied

from .models import App, Entity, Page, Script, can_automate, can_design

# ---------- Aktionen ----------

# ohne Objekt (obj=None)
DESIGNEN = "designen"              # Designer öffnen, Apps anlegen
AUTOMATISIEREN = "automatisieren"  # Automatisierungen mit echtem Python

# App
BENUTZEN = "benutzen"              # Seiten der App öffnen (ohne Gäste-Zugang)
BEARBEITEN = "bearbeiten"          # im Designer ändern; sieht und darf in der App alles
VERWALTEN = "verwalten"            # Mitbearbeiter verwalten, App löschen

# Seite
SEHEN = "sehen"

# Tabelle
LESEN = "lesen"                    # Einträge sehen: Listen, Kennzahlen, Diagramme, Bearbeiten-Formular
SCHREIBEN = "schreiben"            # Gruppenrecht „Ändern dürfen“, ohne die Schalter der Tabelle
ANLEGEN = "anlegen"                # neuer Eintrag (Formular, API, Skript-Brücke); auch Gäste über öffentliche Formulare
AENDERN = "aendern"                # bestehenden Eintrag bearbeiten
LOESCHEN = "loeschen"
EXPORTIEREN = "exportieren"        # CSV-Export
IMPORTIEREN = "importieren"        # CSV-Import

# Skript (Button)
AUSFUEHREN = "ausfuehren"


# ---------- Fakten ----------

def _angemeldet(user):
    return user is not None and getattr(user, "is_authenticated", False)


def mitglied(user, app):
    """Darf die App regulär benutzen (kein Gast)."""
    return _angemeldet(user) and app.user_can_use(user)


def _gemerkt(app, key, compute):
    """Je App-Objekt (also je Anfrage) nur einmal ausrechnen: Seiten fragen oft viele Bausteine ab."""
    cache = app.__dict__.setdefault("_policy_cache", {})
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def _gast_erreicht(app):
    """Gäste nur bei veröffentlichten Apps mit öffentlichen Seiten (siehe views.runtime_access)."""
    return _gemerkt(app, "gast", lambda: app.kind == App.APP and app.published
                    and app.pages.filter(public=True).exists())


def _oeffentlich(app):
    """(Skript-Kurznamen, Tabellen-Kurznamen), die Gäste über öffentliche Seiten auslösen dürfen."""
    return _gemerkt(app, "reach", app.public_reach)


# ---------- Entscheidungen ----------

def _app(user, action, app):
    if action == BENUTZEN:
        return mitglied(user, app)
    if action == BEARBEITEN:
        return _angemeldet(user) and app.user_can_edit(user)
    if action == VERWALTEN:
        return _angemeldet(user) and app.user_can_manage(user)
    raise ValueError(f"Unbekannte Aktion {action!r} für eine App")


def _seite(user, action, page):
    if action != SEHEN:
        raise ValueError(f"Unbekannte Aktion {action!r} für eine Seite")
    if page.public and (_gast_erreicht(page.app) or mitglied(user, page.app)):
        return True
    return mitglied(user, page.app) and page.user_can_view(user)


def _tabelle(user, action, entity):
    app = entity.app
    member = mitglied(user, app)
    lesen = entity.user_can_read(user)
    schreiben = entity.user_can_write(user)
    if action == LESEN:
        return lesen and (member or _gast_erreicht(app))
    if action == SCHREIBEN:
        return schreiben and (member or _gast_erreicht(app))
    if action == ANLEGEN:
        if not (entity.allow_create and schreiben):
            return False
        return member or entity.slug in _oeffentlich(app)[1]
    if action == AENDERN:
        return member and entity.allow_edit and lesen and schreiben
    if action == LOESCHEN:
        return member and entity.allow_delete and lesen and schreiben
    if action == EXPORTIEREN:
        return member and lesen
    if action == IMPORTIEREN:
        return member and entity.allow_create and schreiben
    raise ValueError(f"Unbekannte Aktion {action!r} für eine Tabelle")


def _skript(user, action, script):
    if action != AUSFUEHREN:
        raise ValueError(f"Unbekannte Aktion {action!r} für ein Skript")
    app = script.app
    if mitglied(user, app):
        return True
    return _gast_erreicht(app) and script.slug in _oeffentlich(app)[0]


def darf(user, action, obj=None):
    """True, wenn user die Aktion an obj ausführen darf. Unbekannte Kombinationen sind ein
    Programmierfehler (ValueError), kein stilles Nein."""
    if obj is None:
        if action == DESIGNEN:
            return _angemeldet(user) and can_design(user)
        if action == AUTOMATISIEREN:
            return _angemeldet(user) and can_automate(user)
        raise ValueError(f"Aktion {action!r} braucht ein Objekt")
    if isinstance(obj, Entity):
        return _tabelle(user, action, obj)
    if isinstance(obj, Page):
        return _seite(user, action, obj)
    if isinstance(obj, App):
        return _app(user, action, obj)
    if isinstance(obj, Script):
        return _skript(user, action, obj)
    raise ValueError(f"Für {type(obj).__name__} gibt es keine Rechte")


def pruefe(user, action, obj=None):
    """Wie darf, aber ohne Recht PermissionDenied (Fehlerseite 403)."""
    if not darf(user, action, obj):
        raise PermissionDenied


def sichtbare_seiten(user, app, queryset=None):
    """Seiten der App, die user sehen darf, als QuerySet (Menü, Seitenlinks, Startseite).
    Gleiche Regel wie darf(user, SEHEN, seite), nur für viele Seiten auf einmal."""
    pages = app.pages.all() if queryset is None else queryset
    if not mitglied(user, app):
        return pages.filter(public=True) if _gast_erreicht(app) else pages.none()
    return Page.visible_to(app, user, pages)
