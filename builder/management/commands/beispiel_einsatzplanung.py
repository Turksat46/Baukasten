"""Legt die Beispiel-App „Personaleinsatz“ an: python manage.py beispiel_einsatzplanung

Zeigt die Planungs-Bausteine:
- „Einsatzplanung“: Mitarbeitende per Drag-and-drop in Schichten einplanen. Linien haben eine
  Priorität; wer eine Schicht überplant, eine Person doppelt einplant oder eine weniger wichtige
  Linie füllt, solange eine wichtigere noch Lücken hat, bekommt einen Dialog zum Bestätigen.
- „Wochenübersicht“: Belegung und Kapazität je Schicht und Tag, Klick führt zur Tagesplanung.
- „Kanban-Board“: Tauschwünsche nach Status.

Mit --neu wird die App ersetzt, mit --ohne-daten bleibt sie leer. Die Definition ist dieselbe,
die eine KI über den MCP-Server /mcp/designer/ anlegen würde (siehe DEFINITION).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from builder import ai_designer, versions
from builder.models import App, Record

SLUG = "personaleinsatz"

PLAN = {
    "target": "schichten", "capacity_field": "bedarf", "group_field": "linie", "priority_field": "prioritaet",
    "link": "einsaetze", "link_source": "mitarbeiter", "link_target": "schicht", "link_date": "datum",
}

DEFINITION = {
    "name": "Personaleinsatz", "icon": "🧑‍🏭",
    "description": "Schichten planen per Drag-and-drop, mit Linien-Prioritäten und Wochenübersicht",
    "entities": [
        {"name": "Linien", "slug": "linien", "fields": [
            {"label": "Name", "key": "name", "type": "text", "required": True},
            {"label": "Priorität", "key": "prioritaet", "type": "number", "required": True},
            {"label": "Bereich", "key": "bereich", "type": "text"},
        ]},
        {"name": "Schichten", "slug": "schichten", "fields": [
            {"label": "Schicht", "key": "bezeichnung", "type": "text", "required": True},
            {"label": "Linie", "key": "linie", "type": "reference", "reference": "linien", "required": True},
            {"label": "Zeit", "key": "zeit", "type": "text"},
            {"label": "Bedarf (Personen)", "key": "bedarf", "type": "number", "required": True},
        ]},
        {"name": "Mitarbeitende", "slug": "mitarbeitende", "fields": [
            {"label": "Name", "key": "name", "type": "text", "required": True},
            {"label": "Qualifikation", "key": "qualifikation", "type": "choice",
             "choices": ["Maschinenführung", "Bedienung", "Springer", "Instandhaltung"]},
            {"label": "Aktiv", "key": "aktiv", "type": "bool"},
        ]},
        {"name": "Einsätze", "slug": "einsaetze", "fields": [
            {"label": "Mitarbeiter/in", "key": "mitarbeiter", "type": "reference", "reference": "mitarbeitende",
             "required": True},
            {"label": "Schicht", "key": "schicht", "type": "reference", "reference": "schichten", "required": True},
            {"label": "Datum", "key": "datum", "type": "date", "required": True},
            {"label": "Bemerkung", "key": "bemerkung", "type": "text", "show_in_list": False},
        ]},
        {"name": "Tauschwünsche", "slug": "tauschwuensche", "fields": [
            {"label": "Wunsch", "key": "wunsch", "type": "text", "required": True},
            {"label": "Mitarbeiter/in", "key": "mitarbeiter", "type": "reference", "reference": "mitarbeitende"},
            {"label": "Status", "key": "status", "type": "choice",
             "choices": ["Neu", "In Prüfung", "Genehmigt", "Abgelehnt"]},
        ]},
    ],
    "pages": [
        {"title": "Planung", "slug": "planung", "layout": [
            {"type": "assign", "props": {
                "title": "Schichtplanung", "source": "mitarbeitende", "source_label": "name",
                "source_info": "qualifikation", "source_active": "aktiv", **PLAN,
                "overbook": "warn", "double_check": True, "priority_check": True}},
        ]},
        {"title": "Wochenübersicht", "slug": "woche", "layout": [
            {"type": "weekplan", "props": {
                "title": "Schichten und Kapazitäten", "source": "mitarbeitende", **PLAN,
                "show_names": True, "page": "planung"}},
        ]},
        {"title": "Tauschwünsche", "slug": "tausch", "layout": [
            {"type": "kanban", "props": {"title": "Tauschwünsche", "entity": "tauschwuensche", "field": "status",
                                         "detail": "mitarbeiter", "limit": 5}},
        ]},
        {"title": "Stammdaten", "slug": "stammdaten", "layout": [
            {"type": "table", "width": 6, "props": {"entity": "linien", "title": "Linien und Prioritäten"}},
            {"type": "table", "width": 6, "props": {"entity": "schichten"}},
            {"type": "table", "props": {"entity": "mitarbeitende"}},
            {"type": "table", "props": {"entity": "einsaetze", "title": "Alle Einsätze"}},
        ]},
    ],
}

LINIEN = [("Linie 1 – Montage", 1, "Endmontage"), ("Linie 2 – Lackierung", 2, "Oberfläche"),
          ("Linie 3 – Verpackung", 3, "Logistik")]
SCHICHTEN = {  # Linie -> [(Schicht, Zeit, Bedarf)]
    0: [("Früh", "06–14 Uhr", 3), ("Spät", "14–22 Uhr", 3), ("Nacht", "22–6 Uhr", 2)],
    1: [("Früh", "06–14 Uhr", 2), ("Spät", "14–22 Uhr", 2)],
    2: [("Früh", "06–14 Uhr", 2), ("Spät", "14–22 Uhr", 1)],
}
PERSONEN = [
    ("Anna Berger", "Maschinenführung"), ("Ben Schulte", "Bedienung"), ("Carla Weiß", "Bedienung"),
    ("Deniz Yılmaz", "Maschinenführung"), ("Elena Rossi", "Springer"), ("Finn Hoffmann", "Bedienung"),
    ("Greta Lange", "Instandhaltung"), ("Hakan Demir", "Bedienung"), ("Ida Krüger", "Maschinenführung"),
    ("Jonas Wagner", "Springer"), ("Kira Neumann", "Bedienung"), ("Lukas Braun", "Bedienung"),
    ("Mia Schröder", "Maschinenführung"), ("Noah Fischer", "Instandhaltung"), ("Olga Petrova", "Bedienung"),
    ("Paul Richter", "Springer"), ("Rosa Klein", "Bedienung"), ("Sami Haddad", "Bedienung"),
]


class Command(BaseCommand):
    help = "Legt die Beispiel-App „Personaleinsatz“ mit Schichtplanung an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="Vorhandene Beispiel-App ersetzen")
        parser.add_argument("--ohne-daten", action="store_true", help="Nur die App, keine Beispieldaten")
        parser.add_argument("--app", default="", help="Beispieldaten in eine schon angelegte App mit derselben "
                                                      "Struktur füllen (z. B. über den MCP-Server angelegt)")

    def handle(self, *args, **options):
        from builder import audit

        with audit.quiet():  # Beispieldaten gehören nicht ins Änderungsprotokoll
            if options["app"]:
                app = App.objects.get(slug=options["app"])
            else:
                app = self._app(options["neu"])
                if app is None:
                    return
            if not options["ohne_daten"]:
                self._data(app)
        self.stdout.write(self.style.SUCCESS(f"Fertig: /a/{app.slug}/"))

    def _app(self, replace):
        existing = App.objects.filter(slug=SLUG)
        if existing.exists():
            if not replace:
                self.stdout.write("Die Beispiel-App „Personaleinsatz“ gibt es schon. Mit --neu wird sie neu angelegt.")
                return None
            existing.delete()
        snapshot, _warnings = ai_designer.normalize(DEFINITION)
        app = App.objects.create(name=DEFINITION["name"], slug=SLUG, published=True)
        versions.apply(app, snapshot)
        return app

    def _data(self, app):
        tables = {e.slug: e for e in app.entities.all()}
        if tables["linien"].records.exists():
            self.stdout.write("Es gibt schon Daten; Beispieldaten werden nicht noch einmal angelegt.")
            return

        def add(table, **data):
            return Record.objects.create(entity=tables[table], data=data)

        linien = [add("linien", name=n, prioritaet=p, bereich=b) for n, p, b in LINIEN]
        schichten = []
        for index, items in SCHICHTEN.items():
            for name, zeit, bedarf in items:
                schichten.append(add("schichten", bezeichnung=name, linie=linien[index].pk, zeit=zeit, bedarf=bedarf))
        personen = [add("mitarbeitende", name=n, qualifikation=q, aktiv=n != "Rosa Klein") for n, q in PERSONEN]

        # Diese Woche teilweise verplant: Linie 1 fast voll, Linie 2 und 3 mit Lücken, ein Tag überplant.
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        for offset in range(5):
            day = (monday + timedelta(days=offset)).isoformat()
            pool = personen[offset:] + personen[:offset]
            nr = 0
            for s_index, shift in enumerate(schichten):
                need = shift.data["bedarf"] - (1 if (s_index + offset) % 3 == 0 else 0)
                if s_index >= 5 and offset >= 3:
                    need = 0  # zum Wochenende hin noch offen
                for _ in range(max(need, 0)):
                    if nr >= len(pool):
                        break
                    add("einsaetze", mitarbeiter=pool[nr].pk, schicht=shift.pk, datum=day)
                    nr += 1
            if offset == 1:  # ein überplanter Tag als Beispiel
                add("einsaetze", mitarbeiter=pool[-2].pk, schicht=schichten[0].pk, datum=day,
                    bemerkung="Einarbeitung")

        for wunsch, person, status in [
            ("Früh gegen Spät tauschen (Do)", 1, "Neu"), ("Freier Freitag wegen Arzttermin", 4, "Neu"),
            ("Nachtschicht abgeben", 8, "In Prüfung"), ("Linie 2 statt Linie 3", 11, "Genehmigt"),
            ("Samstag zusätzlich", 6, "Abgelehnt"),
        ]:
            add("tauschwuensche", wunsch=wunsch, mitarbeiter=personen[person].pk, status=status)
