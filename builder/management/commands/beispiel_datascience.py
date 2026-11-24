"""Beispiel-App für Data Science & Model Monitoring: python manage.py beispiel_datascience"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from builder import audit
from builder.blocks import make_block
from builder.models import App, Entity, Field, Page, Record, Script

SIMULATOR_SKRIPT = """# What-If-Simulator: berechnet Ausschuss-Prognose aus den Reglern der Tabelle „parameter“.
params_rows = app.table("parameter").filter()
werte = {r["name"]: float(r["wert"] or 0) for r in params_rows}
temp = werte.get("Temperatur (°C)", 185.0)
druck = werte.get("Druck (bar)", 42.0)
speed = werte.get("Bandgeschwindigkeit", 100.0)
prognose = round(max(0.2, 1.4 + 0.045 * (temp - 180) + 0.08 * abs(druck - 40) + 0.015 * (speed - 100)), 2)
risiko = "Kritisch (Drift)" if prognose > 4.0 else ("Erhöht" if prognose > 2.5 else "Optimal")
ui.set("sim_prognose", value=prognose, unit="% (" + risiko + ")")
"""


class Command(BaseCommand):
    help = "Legt die Data-Science-Beispiel-App „Qualitäts- & Modell-Cockpit“ an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="Vorhandene App löschen und neu anlegen.")

    def handle(self, *args, **options):
        with audit.quiet():
            existing = App.objects.filter(slug="datascience")
            if existing.exists():
                if not options["neu"]:
                    self.stdout.write("Die Beispiel-App „datascience“ gibt es schon (mit --neu ersetzen).")
                    return
                existing.delete()

            app = App.objects.create(
                name="Qualitäts- & Modell-Cockpit",
                slug="datascience",
                icon="🧪",
                description="Korrelationen, Verteilungen, Anomalie-Erkennung, What-If-Simulation & Write-Back",
                published=True,
            )

            chargen = Entity.objects.create(app=app, name="Chargen", slug="chargen", api_enabled=True)
            for idx, (label, key, ftype, choices, formula) in enumerate([
                ("Charge", "charge", Field.TEXT, "", ""),
                ("Werk", "werk", Field.CHOICE, "Stuttgart\nMünchen\nHamburg", ""),
                ("Datum", "datum", Field.DATE, "", ""),
                ("Temperatur (°C)", "temperatur", Field.DECIMAL, "", ""),
                ("Druck (bar)", "druck", Field.DECIMAL, "", ""),
                ("Durchsatz", "durchsatz", Field.NUMBER, "", ""),
                ("Prognose Ausschuss (%)", "prognose", Field.DECIMAL, "", ""),
                ("Ist Ausschuss (%)", "ausschuss", Field.DECIMAL, "", ""),
                ("Prognose-Abweichung (%)", "abweichung", Field.DECIMAL, "", "round(ausschuss - prognose, 2)"),
                ("Status", "status", Field.CHOICE, "OK\nDrift-Warnung\nAnomalie", ""),
                ("Kommentar (Write-Back)", "kommentar", Field.TEXT, "", ""),
            ], start=1):
                Field.objects.create(
                    entity=chargen, label=label, key=key, type=ftype,
                    choices=choices, formula=formula, show_in_form=not bool(formula), order=idx,
                )

            today = timezone.localdate()
            sample = [
                ("CH-101", "Stuttgart", 11, 178.0, 39.5, 95, 1.5, 1.4, "OK", ""),
                ("CH-102", "Stuttgart", 10, 182.0, 41.0, 102, 1.8, 1.9, "OK", ""),
                ("CH-103", "München", 9, 188.5, 43.2, 110, 2.6, 2.8, "OK", ""),
                ("CH-104", "München", 7, 194.0, 46.0, 118, 3.5, 3.9, "Drift-Warnung", "Sensorik Linie 2 prüfen"),
                ("CH-105", "Hamburg", 5, 176.0, 38.8, 90, 1.3, 1.2, "OK", ""),
                ("CH-106", "Hamburg", 4, 181.0, 40.2, 98, 1.7, 1.6, "OK", ""),
                ("CH-107", "Stuttgart", 3, 201.0, 49.5, 125, 4.8, 5.4, "Anomalie", "Kühlung ausgefallen"),
                ("CH-108", "München", 2, 185.0, 41.8, 105, 2.1, 2.0, "OK", ""),
                ("CH-109", "Hamburg", 1, 191.0, 44.5, 114, 3.1, 3.3, "Drift-Warnung", ""),
                ("CH-110", "Stuttgart", 0, 180.0, 40.0, 100, 1.6, 1.5, "OK", ""),
            ]
            for code, werk, days_ago, temp, druck, durch, prog, ist, status, komm in sample:
                Record.objects.create(entity=chargen, data={
                    "charge": code, "werk": werk, "datum": (today - timedelta(days=days_ago)).isoformat(),
                    "temperatur": temp, "druck": druck, "durchsatz": durch,
                    "prognose": prog, "ausschuss": ist, "status": status, "kommentar": komm,
                })

            params = Entity.objects.create(app=app, name="Simulations-Parameter", slug="parameter")
            Field.objects.create(entity=params, label="Parameter", key="name", type=Field.TEXT, order=1)
            Field.objects.create(entity=params, label="Wert", key="wert", type=Field.NUMBER, order=2)
            for pname, pval in [("Temperatur (°C)", 185), ("Druck (bar)", 42), ("Bandgeschwindigkeit", 100)]:
                Record.objects.create(entity=params, data={"name": pname, "wert": pval})

            Page.objects.create(app=app, title="Analyse & Drift", slug="analyse", order=1, layout=[
                make_block("heading", text="Qualitäts- & Modell-Cockpit", subtitle="Klick auf Werk oder Status filtert alle Diagramme", level="1"),
                make_block("filter", entity="chargen", field="werk", field2="status"),
                make_block("scatter", width=6, title="Temperatur vs. Ist-Ausschuss (mit Trend & R²)",
                           entity="chargen", x_field="temperatur", y_field="ausschuss",
                           color_field="werk", size_field="durchsatz", label_field="charge", trendline=True),
                make_block("boxplot", width=6, title="Ausschuss-Verteilung nach Werk",
                           entity="chargen", field="ausschuss", group_field="werk", show_outliers=True),
                make_block("heatmap", width=6, title="Feature-Korrelationsmatrix (Pearson r)",
                           entity="chargen", mode="correlation"),
                make_block("histogram", width=6, title="Temperatur-Verteilung & Drift (PSI nach Werk)",
                           entity="chargen", field="temperatur", group_field="werk", bins=6),
                make_block("line", width=12, label="Ausschuss-Verlauf mit ±1σ-Band & Anomalien",
                           entity="chargen", date_field="datum", aggregate="avg", field="ausschuss",
                           period="day", count=14, unit="%", show_band=True, threshold="4.0"),
            ])

            sim_page = Page.objects.create(app=app, title="What-If & Write-Back", slug="simulator", order=2, layout=[
                make_block("heading", text="What-If-Simulator & Write-Back",
                           subtitle="Regler verstellen für Live-Prognose · Kommentare und Freigaben direkt zurückschreiben", level="1"),
                make_block("sliders", width=6, title="Modell-Parameter verstellen",
                           entity="parameter", field="wert", label_field="name", min=30, max=220, step=1),
                {"id": "bsimout", "type": "output", "width": 6, "name": "sim_prognose",
                 "props": {"label": "Modell-Vorhersage (Ausschuss)", "unit": "%", "text": "Wird berechnet …"}},
                make_block("table", width=8, entity="chargen", title="Chargen & Write-Back-Kommentare"),
                make_block("form", width=4, entity="chargen", submit_label="Charge / Kommentar speichern"),
            ])
            Script.objects.create(
                app=app, name="Simulator", slug="simulator",
                language=Script.PYTHON, trigger=Script.PAGE, page=sim_page,
                enabled=True, code=SIMULATOR_SKRIPT.strip(),
            )
            self.stdout.write(self.style.SUCCESS("Beispiel-App „Qualitäts- & Modell-Cockpit“ (/a/datascience/) angelegt."))
