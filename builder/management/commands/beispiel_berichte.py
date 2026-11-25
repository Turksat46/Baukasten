"""Legt die Beispiel-App „Agenten-Berichte“ an: python manage.py beispiel_berichte

Zeigt den Berichte-Eingang für n8n, Teams-Workflows und Copilot:
- Tabelle „Berichte“ mit einem Feld vom Typ „Formatierter Text (HTML)“, für die API freigeschaltet.
- Seite „Feed“ mit dem Baustein „Berichte-Feed“ und Schnellfilter je Agent.
- Beispielberichte in den Formen, die der Eingang versteht (HTML mit eingebettetem Diagramm,
  Markdown mit Emojis, Adaptive Card), abgelegt über denselben Weg wie ein echter Aufruf.

Mit --neu wird die App ersetzt. Mit --schluessel bekommt die App einen API-Schlüssel mit
Schreibrecht; er wird einmal ausgegeben (für n8n: Kopfzeile „Authorization: Bearer …“).
"""
import base64
import struct
import zlib

from django.core.management.base import BaseCommand

from builder import ai_designer, versions
from builder.models import ApiKey, App

SLUG = "berichte"

DEFINITION = {
    "name": "Agenten-Berichte", "icon": "📰",
    "description": "Berichte von n8n-Agenten, Teams-Workflows und Copilot an einem Ort",
    "entities": [
        {"name": "Berichte", "slug": "berichte", "fields": [
            {"label": "Titel", "key": "titel", "type": "text", "required": True},
            {"label": "Agent", "key": "agent", "type": "text"},
            {"label": "Inhalt", "key": "inhalt", "type": "html", "required": True, "show_in_list": False},
        ]},
    ],
    "pages": [
        {"title": "Feed", "slug": "feed", "layout": [
            {"type": "heading", "props": {"text": "Agenten-Berichte", "level": "1",
                                          "subtitle": "Was die Agenten in n8n und Copilot melden, neueste zuerst"}},
            {"type": "report_feed", "props": {"title": "Neueste Berichte", "entity": "berichte",
                                              "field": "inhalt", "title_field": "titel", "source_field": "agent",
                                              "page_size": 10}},
        ]},
        {"title": "Alle Berichte", "slug": "alle", "layout": [
            {"type": "table", "props": {"entity": "berichte"}},
        ]},
    ],
}


def bar_chart_png(values, width=480, height=200):
    """Kleines Balkendiagramm als PNG, ohne Bibliotheken (steht für ein Diagramm aus n8n)."""
    background, bar, accent, grid = (255, 255, 255), (0, 108, 122), (217, 138, 31), (214, 219, 226)
    rows = [[background] * width for _ in range(height)]
    for y in (height // 4, height // 2, 3 * height // 4):
        rows[y] = [grid] * width
    slot = width // len(values)
    top = max(values)
    for i, value in enumerate(values):
        bar_height = int((height - 20) * value / top)
        color = accent if i == len(values) - 1 else bar
        for y in range(height - bar_height, height):
            for x in range(i * slot + slot // 5, (i + 1) * slot - slot // 5):
                rows[y][x] = color
    raw = b"".join(b"\x00" + bytes(c for pixel in row for c in pixel) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def examples():
    chart = base64.b64encode(bar_chart_png([42, 51, 47, 58, 63, 71])).decode()
    return [
        {"agent": "Vertriebs-Agent", "title": "📈 Wochenbericht Vertrieb KW 48", "text": (
            "<p>Guten Morgen! ☀️ Hier die Zahlen der Woche:</p>"
            "<ul><li><b>Aufträge:</b> 71 (+13 % zur Vorwoche) 🚀</li>"
            "<li><b>Angebote offen:</b> 24</li><li><b>Größter Abschluss:</b> Rahmenvertrag Nord</li></ul>"
            f'<p><img src="data:image/png;base64,{chart}" alt="Aufträge der letzten sechs Wochen"></p>'
            "<p><i>Automatisch erstellt von n8n.</i></p>")},
        {"agent": "IT-Monitoring", "title": "✅ Nächtliche Prüfung ohne Befund", "text": (
            "Alle **12 Systeme** erreichbar, Sicherungen vollständig.\n\n"
            "| System | Status | Antwortzeit |\n|---|---|---|\n"
            "| ERP | 🟢 läuft | 180 ms |\n| Intranet | 🟢 läuft | 95 ms |\n| Druckserver | 🟡 langsam | 1,4 s |\n\n"
            "> Hinweis: Wartung am Samstag 22–23 Uhr.")},
        {"agent": "Qualitäts-Agent", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"type": "AdaptiveCard", "version": "1.5", "body": [
                {"type": "TextBlock", "text": "⚠️ Ausschuss über Grenzwert", "size": "large", "weight": "bolder"},
                {"type": "TextBlock", "text": "Linie 2 meldet seit 6 Uhr erhöhten Ausschuss.", "wrap": True},
                {"type": "FactSet", "facts": [
                    {"title": "Linie", "value": "Linie 2 – Lackierung"},
                    {"title": "Ausschuss", "value": "4,8 % (Grenze 3 %)"},
                    {"title": "Seit", "value": "06:00 Uhr"},
                ]},
            ], "actions": [{"type": "Action.OpenUrl", "title": "Zum Qualitäts-Cockpit",
                            "url": "https://example.com/a/datascience/"}]},
        }]},
        {"agent": "Copilot", "title": "🤖 Zusammenfassung der Woche", "text": (
            "Die Agenten haben diese Woche **3 Berichte** abgelegt.\n\n"
            "- Vertrieb wächst weiter 📈\n- IT ohne Störungen ✅\n- Qualität: eine Grenzwertverletzung auf Linie 2 ⚠️\n\n"
            "_Vorschlag:_ Ursache auf Linie 2 im Qualitäts-Cockpit prüfen.")},
    ]


class Command(BaseCommand):
    help = "Legt die Beispiel-App „Agenten-Berichte“ mit Berichte-Feed und Eingang an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="Vorhandene Beispiel-App ersetzen")
        parser.add_argument("--ohne-daten", action="store_true", help="Nur die App, keine Beispielberichte")
        parser.add_argument("--schluessel", action="store_true", help="API-Schlüssel mit Schreibrecht ausgeben")

    def handle(self, *args, **options):
        from builder import audit

        existing = App.objects.filter(slug=SLUG)
        if existing.exists():
            if not options["neu"]:
                self.stdout.write("Die Beispiel-App „Agenten-Berichte“ gibt es schon. Mit --neu wird sie neu angelegt.")
                return
            existing.delete()
        with audit.quiet():
            snapshot, _warnings = ai_designer.normalize(DEFINITION)
            app = App.objects.create(name=DEFINITION["name"], slug=SLUG, published=True)
            versions.apply(app, snapshot)
            entity = app.entities.get(slug="berichte")
            entity.api_enabled = True
            entity.save(update_fields=["api_enabled"])
            if not options["ohne_daten"]:
                self._examples(app, entity)
        if options["verbosity"]:
            self.stdout.write(self.style.SUCCESS(f"Beispiel-App „Agenten-Berichte“ (/a/{SLUG}/) angelegt."))
            self.stdout.write(f"Eingang für n8n: POST /api/v1/{SLUG}/berichte/eingang/")
        if options["schluessel"]:
            _key, plain = ApiKey.issue(app, "n8n-Berichte", can_write=True)
            self.stdout.write(f"API-Schlüssel (wird nur jetzt angezeigt): {plain}")

    def _examples(self, app, entity):
        """Legt die Beispiele über denselben Weg ab wie der Eingang (Umwandlung, Bilder, Prüfung)."""
        from builder.rich import split_report
        from builder.scripting.ops import save_record

        for payload in examples():
            title, html = split_report(payload)
            save_record(entity, {"titel": title, "agent": payload["agent"], "inhalt": html})
