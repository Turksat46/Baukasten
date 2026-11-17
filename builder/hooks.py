"""Erweiterungspunkte für Entwickler.

Eigene Logik kommt als Python-Datei in den Ordner „extensions“ und meldet sich
über diese Dekoratoren an. Beispiele stehen in extensions/beispiel.py.
"""
import logging

log = logging.getLogger(__name__)

ACTIONS = {}        # name -> {"label": str, "fn": callable}
SAVE_HOOKS = []     # (app_slug | None, entity_slug | None, callable)
CUSTOM_BLOCKS = {}  # key -> {"label": str, "icon": str, "fn": callable}
API_ENDPOINTS = {}  # name -> {"methods": tuple, "write": bool, "fn": callable}


def action(name, label=None):
    """Registriert eine Aktion, die ein Button im Designer auslösen kann.

    Die Funktion bekommt (request, app) und gibt einen Meldungstext oder eine
    fertige HttpResponse zurück.
    """

    def decorator(fn):
        ACTIONS[name] = {"label": label or name, "fn": fn}
        return fn

    return decorator


def on_save(entity=None, app=None):
    """Ruft die Funktion nach jedem Speichern eines Datensatzes auf: fn(record, created, user).

    entity und app sind optionale Kurznamen (Slugs), um den Hook einzuschränken.
    """

    def decorator(fn):
        SAVE_HOOKS.append((app, entity, fn))
        return fn

    return decorator


def block(key, label, icon="🧩"):
    """Registriert einen eigenen Baustein für den Seiten-Designer.

    Die Funktion bekommt (request, app) und gibt Text oder mit format_html
    erzeugtes HTML zurück. Normaler Text wird automatisch maskiert.
    """

    def decorator(fn):
        CUSTOM_BLOCKS[key] = {"label": label, "icon": icon, "fn": fn}
        return fn

    return decorator


def api(name, methods=("GET",), write=False):
    """Registriert einen eigenen API-Endpunkt: /api/v1/<app>/x/<name>/

    Die Funktion bekommt (request, app, daten) und gibt ein Dictionary oder eine
    Liste zurück. „daten“ ist der JSON-Inhalt der Anfrage (bei GET die
    Abfrageparameter). Mit write=True braucht der Aufrufer einen Schlüssel mit
    Schreibrecht.
    """

    def decorator(fn):
        API_ENDPOINTS[name] = {"methods": tuple(m.upper() for m in methods), "write": write, "fn": fn}
        return fn

    return decorator


def fire_save(record, created, user):
    for app_slug, entity_slug, fn in SAVE_HOOKS:
        if app_slug and app_slug != record.entity.app.slug:
            continue
        if entity_slug and entity_slug != record.entity.slug:
            continue
        try:
            fn(record, created, user)
        except Exception:  # ein fehlerhafter Hook darf das Speichern nicht abbrechen
            log.exception("Fehler im Speichern-Hook %s", getattr(fn, "__name__", fn))
