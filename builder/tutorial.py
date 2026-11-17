"""Geführte Einführung „Deine erste App“: eine Urlaubsantrag-App Schritt für Schritt selbst bauen.

Ein Begleiter unten rechts zeigt auf jeder Seite den aktuellen Schritt, einen Link
zur passenden Seite und auf Wunsch die Stelle, an der es weitergeht. Ob ein
Schritt erledigt ist, prüft der Baukasten am Zustand der App (nicht an Klicks):
Wer Schritte in anderer Reihenfolge oder ohne Begleiter macht, kommt trotzdem
weiter. Die Einführung ist für Designer gedacht.
"""
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import App, Field, Script, Tutorial

CHART_TYPES = {"chart", "donut", "line", "timeline"}

SCRIPT_EXAMPLE = '''import datetime

# Tage aus „Von“ und „Bis“ ausrechnen (beide Tage zählen mit).
if record.get("von") and record.get("bis"):
    von = datetime.date.fromisoformat(record["von"])
    bis = datetime.date.fromisoformat(record["bis"])
    record["tage"] = (bis - von).days + 1

# Neue Anträge sind erst einmal offen.
if not record.get("status"):
    record["status"] = "offen"
'''


def _entity(app):
    return app.entities.order_by("id").first()


def _layouts(app):
    return [(page, page.layout or []) for page in app.pages.all()]


def _has_fields(app):
    """Datum, Zahl (ganz oder Komma) und Auswahl in derselben Tabelle."""
    for entity in app.entities.all():
        types = set(entity.fields.values_list("type", flat=True))
        if {Field.DATE, Field.CHOICE} <= types and types & {Field.NUMBER, Field.DECIMAL}:
            return True
    return False


def _table_page(app):
    slugs = set(app.entities.values_list("slug", flat=True))
    for page, layout in _layouts(app):
        if any(b.get("type") == "table" and (b.get("props") or {}).get("entity") in slugs for b in layout):
            return page
    return None


def _has_dashboard(app):
    for _page, layout in _layouts(app):
        types = {b.get("type") for b in layout}
        if "stat" in types and types & CHART_TYPES:
            return True
    return False


def _entity_url(app):
    entity = _entity(app)
    return reverse("designer_entity", args=[app.slug, entity.pk]) if entity else reverse("designer_app", args=[app.slug])


def _records_url(app):
    page = _table_page(app)
    return reverse("page", args=[app.slug, page.slug]) if page else reverse("page", args=[app.slug])


def _dashboard_url(app):
    page = app.home_page
    return reverse("designer_page", args=[app.slug, page.pk]) if page else reverse("designer_app", args=[app.slug])


# Jeder Schritt: Titel, Anleitung, erledigt(app), Adresse(app), Ziel auf der Seite, optional Code.
STEPS = [
    {"key": "app", "title": _("App anlegen"),
     "text": _("Im Designer unter „Neue App“: Name „Urlaub“, Symbol 🌴, dann „Anlegen“."),
     "done": lambda app: app is not None,
     "url": lambda app: reverse("designer_home"), "target": "[data-tour=new-app-form]"},
    {"key": "table", "title": _("Tabelle anlegen"),
     "text": _("Im Kasten „1 Daten: Tabellen“ die Tabelle „Anträge“ anlegen. Sie bekommt automatisch das Feld „Bezeichnung“ – trag dort später z. B. „Sommerurlaub“ ein."),
     "done": lambda app: app.entities.exists(),
     "url": lambda app: reverse("designer_app", args=[app.slug]), "target": "[data-tour=entities]"},
    {"key": "fields", "title": _("Felder hinzufügen"),
     "text": _("Unter „Feld hinzufügen“ nacheinander: „Von“ (Datum, Pflichtfeld), „Bis“ (Datum, Pflichtfeld), „Tage“ (Ganze Zahl) und „Status“ (Auswahl, Werte je Zeile: offen, genehmigt, abgelehnt)."),
     "done": _has_fields,
     "url": _entity_url, "target": "[data-tour=add-field]"},
    {"key": "page", "title": _("Seite erzeugen"),
     "text": _("Oben auf „Seite aus dieser Tabelle erzeugen“ klicken. Daraus entsteht eine Liste mit Suche, Anlegen, Bearbeiten und Löschen."),
     "done": lambda app: _table_page(app) is not None,
     "url": _entity_url, "target": "[data-tour=make-page]"},
    {"key": "records", "title": _("Zwei Anträge erfassen"),
     "text": _("So sieht die App für Nutzer aus. Mit „Neu“ zwei Anträge anlegen, z. B. „Sommerurlaub“ vom 4. bis 15. August. Tage und Status darfst du leer lassen – das übernimmt gleich ein Skript."),
     "done": lambda app: any(e.records.count() >= 2 for e in app.entities.all()),
     "url": _records_url, "target": "[data-tour=new-record]"},
    {"key": "dashboard", "title": _("Startseite gestalten"),
     "text": _("Im Seiten-Designer der Startseite: den Text-Baustein entfernen, eine „Kennzahl“ (Anträge gesamt) und ein „Kreisdiagramm“ nach „Status“ hinzufügen – oder ein „Liniendiagramm“. Dann „Speichern“."),
     "done": _has_dashboard,
     "url": _dashboard_url, "target": "#palette-panel"},
    {"key": "script", "title": _("Skript: Tage ausrechnen"),
     "text": _("Neues Python-Skript, Auslöser „Nach dem Speichern“, Tabelle „Anträge“. Den Code unten einfügen und speichern. Ab jetzt rechnet der Baukasten die Tage selbst aus und setzt neue Anträge auf „offen“."),
     "done": lambda app: app.scripts.filter(trigger=Script.SAVE).exists(),
     "url": lambda app: reverse("designer_script_new", args=[app.slug]), "target": "[data-tour=script-trigger]",
     "code": SCRIPT_EXAMPLE},
    {"key": "publish", "title": _("Veröffentlichen"),
     "text": _("Unter „3 Einstellungen und Freigabe“ den Haken „Veröffentlicht“ setzen und speichern. Ohne Gruppen sehen jetzt alle angemeldeten Personen die App."),
     "done": lambda app: app.published,
     "url": lambda app: reverse("designer_app", args=[app.slug]), "target": "[data-tour=settings]"},
    {"key": "version", "title": _("Stand sichern"),
     "text": _("Unter „Versionen“ eine Version mit der Notiz „erste Fassung“ speichern. Geht später ein Umbau schief, holst du diesen Stand mit einem Klick zurück."),
     "done": lambda app: app.versions.exists(),
     "url": lambda app: reverse("designer_app", args=[app.slug]), "target": "[data-tour=versions]"},
]

NEXT_IDEAS = [
    (_("Übersetzungen"), _("die App auf Englisch anbieten"), "designer_translations"),
    (_("Mitbearbeiter"), _("Kolleginnen und Kollegen zum Mitbauen einladen"), "designer_app"),
    (_("Schnittstelle (API) und MCP"), _("Excel, n8n oder KI-Agenten anbinden"), "designer_app"),
]


def _link_app(tutorial):
    """Ordnet der Einführung die App zu, die die Person nach dem Start angelegt hat."""
    if tutorial.app_id:
        return tutorial.app
    app = (App.objects.filter(created_by=tutorial.user, created_at__gte=tutorial.started_at)
           .order_by("created_at").first())
    if app:
        tutorial.app = app
        tutorial.save(update_fields=["app"])
    return app


def state(user):
    """Was der Begleiter zeigt, oder None. Schließt die Einführung ab, wenn alles erledigt ist."""
    tutorial = getattr(user, "tutorial", None) if user.is_authenticated else None
    if tutorial is None or not tutorial.active:
        return None
    app = _link_app(tutorial)
    done = [bool(step["done"](app)) if (app or step["key"] == "app") else False for step in STEPS]
    current = next((i for i, ok in enumerate(done) if not ok), None)
    if current is None:
        if not tutorial.finished_at:
            tutorial.finished_at = timezone.now()
            tutorial.save(update_fields=["finished_at"])
        return {"finished": True, "app": app, "total": len(STEPS), "done_count": len(STEPS),
                "steps": [{"title": s["title"], "done": True} for s in STEPS],
                "ideas": [{"title": t, "text": x, "url": reverse(name, args=[app.slug])} for t, x, name in NEXT_IDEAS],
                "app_url": reverse("page", args=[app.slug])}
    step = STEPS[current]
    return {
        "finished": False, "app": app, "number": current + 1, "total": len(STEPS),
        "done_count": sum(done), "title": step["title"], "text": step["text"],
        "url": step["url"](app), "target": step["target"], "code": step.get("code", ""),
        "steps": [{"title": s["title"], "done": ok, "current": i == current} for i, (s, ok) in enumerate(zip(STEPS, done))],
    }


def start(user):
    """Startet die Einführung (neu): Danach angelegte Apps werden zur Übungs-App."""
    Tutorial.objects.update_or_create(user=user, defaults={
        "app": None, "started_at": timezone.now(), "finished_at": None, "active": True})


def stop(user):
    Tutorial.objects.filter(user=user).update(active=False)
