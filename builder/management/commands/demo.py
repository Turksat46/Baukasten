"""Legt eine Beispiel-App „Inventar“ an: python manage.py demo"""
import random
from pathlib import Path
import sqlite3
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from builder import datasources
from builder.blocks import make_block
from builder.models import App, DataQuery, Entity, Field, Page, Record, Script

def months_ago(count, day=10):
    """Datum vor einigen Monaten, damit die Beispieldaten im Verlauf aktuell wirken."""
    today = timezone.localdate()
    index = today.year * 12 + today.month - 1 - count
    return date(index // 12, index % 12 + 1, day).isoformat()


def geraete():
    return [
        ("Laptop 14 Zoll", "IT", "Büro 2.14", months_ago(1), 1249.0, True),
        ("Laptop 16 Zoll", "IT", "Büro 2.15", months_ago(2), 1899.0, True),
        ("Oszilloskop", "Messtechnik", "Labor 1", months_ago(2, 20), 3420.5, True),
        ("Multimeter", "Messtechnik", "Labor 1", months_ago(4), 189.9, True),
        ("3D-Drucker", "Werkstatt", "Werkstatt", months_ago(7), 2790.0, False),
        ("Beamer", "IT", "Besprechung A", months_ago(9), 640.0, True),
    ]


MASCHINEN = ["Fräse 1", "Fräse 2", "Presse", "Lackieranlage"]

LIVE_SKRIPT = """# Füllt die Ausgabe-Bausteine der Seite „Live-Daten“ beim Öffnen.
maschinen = db.saved("maschinenstatus")
warnungen = [m for m in maschinen if m["status"] != "OK"]
ui.set("warnungen", value=len(warnungen), unit="von " + str(len(maschinen)))
if warnungen:
    ui.set("hinweis", text="Bitte prüfen: " + ", ".join(m["maschine"] for m in warnungen), tone="warning")
else:
    ui.set("hinweis", text="Alle Maschinen laufen normal.", tone="success")
ui.set("letzte_messung", value=max(m["zeitpunkt"] for m in maschinen)[11:16], unit="Uhr")
"""

JS_SKRIPT = """// Berechnet im Browser die Durchschnittstemperatur und zeigt sie als Tabelle.
const maschinen = await db.saved("maschinenstatus");
const schnitt = maschinen.reduce((summe, m) => summe + m.temperatur, 0) / maschinen.length;
ui.set("durchschnitt", {
  value: Math.round(schnitt * 10) / 10,
  rows: maschinen.map(m => ({Maschine: m.maschine, "°C": m.temperatur, Abweichung: Math.round((m.temperatur - schnitt) * 10) / 10})),
});
message("Durchschnitt berechnet.");
"""

SPEICHERN_SKRIPT = """# Nach dem Speichern eines Geräts: fehlenden Standort ergänzen.
if not record.get("standort"):
    record["standort"] = "Lager"
    print("Standort ergänzt für", record["bezeichnung"])
"""


def demo_source_file():
    import tempfile

    path = Path(settings.DEMO_DATASOURCE_FILE)
    try:
        return _fill_demo_source(path)
    except (sqlite3.OperationalError, PermissionError, OSError):
        fallback = Path(tempfile.gettempdir()) / "demo-datenquelle.sqlite3"
        return _fill_demo_source(fallback)
    except sqlite3.DatabaseError:
        # Datei beschädigt, z. B. nach einem abgebrochenen Lauf: neu anlegen.
        for leftover in (path, path.with_name(path.name + "-journal")):
            leftover.unlink(missing_ok=True)
        return _fill_demo_source(path)


def _fill_demo_source(path):
    conn = sqlite3.connect(path)
    # Inhalt ersetzen statt die Datei zu löschen, und ohne Journal-Datei: Manche Umgebungen
    # erlauben im Projektordner kein Löschen von Dateien.
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("DROP TABLE IF EXISTS messwerte")
    conn.execute("CREATE TABLE messwerte (id INTEGER PRIMARY KEY, maschine TEXT, zeitpunkt TEXT, temperatur REAL, status TEXT)")
    now = timezone.localtime().replace(second=0, microsecond=0)
    rng = random.Random(7)
    rows = []
    for step in range(48):
        moment = (now - timedelta(minutes=15 * (47 - step))).strftime("%Y-%m-%d %H:%M:%S")
        for name in MASCHINEN:
            temp = round(rng.uniform(38, 62) + (14 if name == "Presse" and step > 40 else 0), 1)
            if name == "Presse" and step == 47:
                temp = 74.3  # damit die Beispielseite eine Warnung zeigt
            rows.append((name, moment, temp, "Warnung" if temp > 70 else "OK"))
    conn.executemany("INSERT INTO messwerte (maschine, zeitpunkt, temperatur, status) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


class Command(BaseCommand):
    help = "Legt die Beispiel-App „Inventar“ an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true",
                            help="Vorhandene Beispiel-App samt ihren Daten löschen und neu anlegen.")

    def handle(self, *args, **options):
        from builder import audit

        with audit.quiet():  # Beispieldaten anlegen gehört nicht ins Änderungsprotokoll
            return self._handle(*args, **options)

    def _handle(self, *args, **options):
        existing = App.objects.filter(slug="inventar")
        if existing.exists():
            if not options["neu"]:
                self.stdout.write("Die Beispiel-App gibt es schon. Mit --neu wird sie neu angelegt.")
                return
            existing.delete()
        app = App.objects.create(
            name="Inventar", slug="inventar", icon="🗄️",
            description="Beispiel: Geräte erfassen und auswerten", published=True,
        )
        entity = Entity.objects.create(app=app, name="Geräte")
        Field.objects.create(entity=entity, label="Bezeichnung", required=True)
        Field.objects.create(
            entity=entity, label="Kategorie", type=Field.CHOICE, required=True,
            choices="IT\nMesstechnik\nWerkstatt",
        )
        Field.objects.create(entity=entity, label="Standort")
        Field.objects.create(entity=entity, label="Anschaffung", type=Field.DATE)
        Field.objects.create(entity=entity, label="Preis", type=Field.DECIMAL)
        Field.objects.create(entity=entity, label="Aktiv", type=Field.BOOL)
        keys = ["bezeichnung", "kategorie", "standort", "anschaffung", "preis", "aktiv"]
        for row in geraete():
            Record.objects.create(entity=entity, data=dict(zip(keys, row)))

        # Reihenfolge: erst die Seiten anlegen, auf die der Button der Übersicht verweist.
        overview = Page.objects.create(app=app, title="Übersicht")
        Page.objects.create(app=app, title="Geräte", layout=[
            make_block("heading", text="Geräte", level="1"),
            make_block("table", entity=entity.slug),
        ])
        Page.objects.create(app=app, title="Gerät erfassen", layout=[
            make_block("heading", text="Neues Gerät erfassen", level="1"),
            make_block("form", width=6, entity=entity.slug, submit_label="Gerät speichern"),
            make_block("text", width=6, text="Dieses Formular entsteht automatisch aus den Feldern der Tabelle „Geräte“."),
        ])
        overview.layout = [
            make_block("heading", width=8, text="Inventar", level="1",
                       subtitle="Bestand, Wert und Verteilung aller erfassten Geräte"),
            make_block("button", width=4, label="Gerät erfassen", page="gerat-erfassen", align="right"),
            make_block("stat", width=3, label="Geräte im Bestand", entity=entity.slug),
            make_block("stat", width=3, label="Gesamtwert", entity=entity.slug, aggregate="sum", field="preis", unit="€"),
            make_block("stat", width=3, label="Durchschnittspreis", entity=entity.slug, aggregate="avg", field="preis", unit="€"),
            make_block("progress", width=3, label="Budget ausgeschöpft", entity=entity.slug, aggregate="sum",
                       field="preis", target=15000, unit="€"),
            make_block("donut", width=6, label="Geräte je Kategorie", entity=entity.slug, field="kategorie"),
            make_block("chart", width=6, label="Geräte je Standort", entity=entity.slug, field="standort"),
            make_block("timeline", label="Anschaffungen pro Monat", entity=entity.slug, field="anschaffung", months=12),
            make_block("table", entity=entity.slug, title="Zuletzt erfasst", page_size=5, searchable=False),
        ]
        overview.save()
        Script.objects.create(app=app, name="Standort ergänzen", trigger=Script.SAVE, entity=entity,
                              code=SPEICHERN_SKRIPT)
        self.live_data(app)
        self.stdout.write(self.style.SUCCESS("Beispiel-App „Inventar“ angelegt."))

    def live_data(self, app):
        """Datenquelle, Abfragen und Skripte. Die Datenquelle „demo“ gibt es nur mit DEBUG=1."""
        path = demo_source_file()
        if not settings.DEBUG:
            self.stdout.write("Hinweis: Die Datenquelle „demo“ gibt es nur mit DEBUG=1; die Seite „Live-Daten“ zeigt sonst Fehler.")
        settings.BAUKASTEN_DATASOURCES.setdefault("demo", f"sqlite:///{path.as_posix()}")
        status = DataQuery.objects.create(
            app=app, name="Maschinenstatus", slug="maschinenstatus", source="demo", cache_seconds=10,
            sql="SELECT m.maschine, m.zeitpunkt, m.temperatur, m.status\nFROM messwerte m\n"
                "WHERE m.zeitpunkt = (SELECT MAX(zeitpunkt) FROM messwerte WHERE maschine = m.maschine)\n"
                "ORDER BY m.maschine",
        )
        verlauf = DataQuery.objects.create(
            app=app, name="Messwerte", slug="messwerte", source="demo", cache_seconds=60,
            sql="SELECT id, maschine, zeitpunkt, temperatur, status FROM messwerte", key_column="id", sync_interval=15,
        )
        if settings.DEBUG:
            datasources.sync_and_record(verlauf)
        Script.objects.create(app=app, name="Live-Kennzahlen", code=LIVE_SKRIPT, trigger=Script.PAGE)
        Script.objects.create(app=app, name="Durchschnitt berechnen", code=JS_SKRIPT,
                              language=Script.JAVASCRIPT, trigger=Script.BUTTON)
        page = Page.objects.create(app=app, title="Live-Daten", layout=[
            make_block("heading", width=8, text="Live-Daten aus der Fertigung", level="1",
                       subtitle="Beispiel für eine Datenquelle, ein Python- und ein JavaScript-Skript"),
            make_block("button", width=4, label="Durchschnitt berechnen", target="script",
                       script="durchschnitt-berechnen", align="right"),
            {**make_block("notice", text="Wird beim Öffnen von einem Skript gefüllt."), "name": "hinweis"},
            {**make_block("output", width=4, label="Maschinen mit Warnung"), "name": "warnungen"},
            {**make_block("output", width=4, label="Letzte Messung"), "name": "letzte_messung"},
            {**make_block("output", width=4, label="Durchschnittstemperatur", unit="°C",
                          text="Auf „Durchschnitt berechnen“ klicken."), "name": "durchschnitt"},
            {**make_block("query", query=status.slug, title="Aktueller Stand je Maschine"), "refresh": 10},
        ])
        Script.objects.filter(app=app, slug="live-kennzahlen").update(page=page)
