"""Werks-Apps aus dem Produkttest, Werks-Bausteine, Datumsformeln, Achsenbeschriftung, Fragment-Links."""

from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ..blocks import make_block
from ..models import App, Entity, Field, Page, Record


class WerkBausteinTests(TestCase):
    """Bausteine, die beim Produkttest mit den Werks-Apps gefehlt haben: Bedingung, Ampel, Trend, Pareto."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        self.user = User.objects.create_user("werker", password="x")
        self.app = App.objects.create(name="Werk", slug="werk", published=True)
        self.entity = Entity.objects.create(app=self.app, name="Störungen", slug="stoerungen")
        Field.objects.create(entity=self.entity, label="Titel", key="titel", order=1)
        Field.objects.create(entity=self.entity, label="Status", key="status", type=Field.CHOICE,
                             choices="Offen\nIn Arbeit\nBehoben", order=2)
        Field.objects.create(entity=self.entity, label="Kategorie", key="kategorie", type=Field.CHOICE,
                             choices="Mechanik\nElektrik\nMaterial", order=3)
        Field.objects.create(entity=self.entity, label="Stillstand (min)", key="minuten", type=Field.NUMBER, order=4)
        Field.objects.create(entity=self.entity, label="Fällig", key="faellig", type=Field.DATE, order=5)
        Field.objects.create(entity=self.entity, label="Bestand", key="bestand", type=Field.NUMBER, order=6)
        Field.objects.create(entity=self.entity, label="Mindestbestand", key="mindest", type=Field.NUMBER, order=7)
        Field.objects.create(entity=self.entity, label="Erledigt", key="erledigt", type=Field.BOOL, order=8)
        today = timezone.localdate()
        self.today = today
        rows = [
            ("A", "Offen", "Mechanik", 120, -3, 5, 10, False),
            ("B", "In Arbeit", "Elektrik", 30, 2, 50, 10, False),
            ("C", "Behoben", "Mechanik", 60, -1, 0, 0, True),
            ("D", "Offen", "Material", 10, -10, 8, 8, False),
            ("E", "Behoben", "Elektrik", 5, 5, 1, 2, True),
        ]
        for titel, status, kat, minuten, tage, bestand, mindest, erledigt in rows:
            Record.objects.create(entity=self.entity, data={
                "titel": titel, "status": status, "kategorie": kat, "minuten": minuten,
                "faellig": (today + timedelta(days=tage)).isoformat(), "bestand": bestand, "mindest": mindest,
                "erledigt": erledigt})

    def _page(self, *blocks):
        Page.objects.filter(app=self.app).delete()
        Page.objects.create(app=self.app, title="Tafel", slug="tafel", layout=list(blocks))
        self.client.force_login(self.user)
        return self.client.get(reverse("page", args=["werk", "tafel"]))

    def _titles(self, text):
        from ..conditions import matches, parse

        conditions = parse(text, self.entity)
        return sorted(r.data["titel"] for r in self.entity.records.all() if matches(conditions, r.data, self.today))

    def test_conditions(self):
        from ..conditions import ConditionError, parse

        self.assertEqual(self._titles("Status != Behoben"), ["A", "B", "D"])
        self.assertEqual(self._titles("status = Offen, In Arbeit"), ["A", "B", "D"])
        self.assertEqual(self._titles("Fällig < heute\nStatus != Behoben"), ["A", "D"])
        self.assertEqual(self._titles("Fällig >= heute-1"), ["B", "C", "E"])
        self.assertEqual(self._titles("Fällig < today"), ["A", "C", "D"])
        self.assertEqual(self._titles("Bestand < Mindestbestand"), ["A", "E"])  # zwei Felder vergleichen
        self.assertEqual(self._titles("Stillstand (min) >= 30"), ["A", "B", "C"])
        self.assertEqual(self._titles("Erledigt = nein"), ["A", "B", "D"])
        self.assertEqual(self._titles("Titel enthält a"), ["A"])  # Groß-/Kleinschreibung egal
        self.assertEqual(self._titles("# Kommentar\n\nKategorie = Mechanik"), ["A", "C"])
        with self.assertRaises(ConditionError):
            parse("Farbe = rot", self.entity)
        with self.assertRaises(ConditionError):
            parse("Status Offen", self.entity)

    def test_where_applies_to_stat_and_table(self):
        response = self._page(
            make_block("stat", label="Offen", entity="stoerungen", where="Status != Behoben"),
            make_block("table", entity="stoerungen", where="Fällig < heute\nStatus != Behoben"),
            make_block("stat", label="Alle", entity="stoerungen"),
        )
        html = response.content.decode()
        self.assertIn('<span data-slot="value">3</span>', html)
        self.assertIn('<span data-slot="value">5</span>', html)  # die Bedingung gilt nur für ihren Baustein
        table = html[html.index("<table"):html.index("</table>")]
        self.assertIn(">A<", table)
        self.assertIn(">D<", table)
        self.assertNotIn(">B<", table)  # noch nicht fällig
        self.assertNotIn(">C<", table)  # behoben

    def test_where_error_is_shown_in_block(self):
        response = self._page(make_block("stat", label="Offen", entity="stoerungen", where="Farbe = rot"))
        self.assertContains(response, "Ein Feld „Farbe“ gibt es in „Störungen“ nicht.")

    def test_stat_traffic_light(self):
        from ..blocks import stat_tone

        self.assertEqual(stat_tone(5, {}), "")
        self.assertEqual(stat_tone(5, {"warn_at": "3", "alarm_at": "8"}), "warning")
        self.assertEqual(stat_tone(9, {"warn_at": "3", "alarm_at": "8"}), "danger")
        self.assertEqual(stat_tone(1, {"warn_at": "3", "alarm_at": "8"}), "success")
        self.assertEqual(stat_tone(80, {"direction": "lower_worse", "warn_at": "85", "alarm_at": "75"}), "warning")
        self.assertEqual(stat_tone(70.5, {"direction": "lower_worse", "warn_at": "85", "alarm_at": "75,5"}), "danger")
        response = self._page(make_block("stat", label="Offen", entity="stoerungen", where="Status = Offen",
                                         warn_at="1", alarm_at="3"))
        self.assertContains(response, 'class="stat stat-warning"')

    def test_stat_compare_with_previous_period(self):
        response = self._page(make_block("stat", label="Minuten", entity="stoerungen", aggregate="sum", field="minuten",
                                         compare_field="faellig", compare_days=7))
        # letzte 7 Tage (heute−6 … heute): A (−3) und C (−1) = 180; davor (−13 … −7): D = 10
        self.assertContains(response, '<span data-slot="value">180</span>')
        self.assertContains(response, "▲ +170")
        self.assertContains(response, "stat-delta-up is-bad")

    def test_chart_sum_and_pareto(self):
        response = self._page(make_block("chart", label="Stillstand", entity="stoerungen", field="kategorie",
                                         agg="sum", value_field="minuten", pareto=True))
        html = response.content.decode()
        self.assertLess(html.index(">Mechanik<"), html.index(">Elektrik<"))  # 180 vor 35 vor 10
        self.assertLess(html.index(">Elektrik<"), html.index(">Material<"))
        self.assertIn(">180<", html)
        self.assertIn("Σ 80 %", html)  # 180 von 225
        self.assertIn("Σ 100 %", html)
        missing = self._page(make_block("chart", label="X", entity="stoerungen", field="kategorie", agg="sum"))
        self.assertContains(missing, "Summe und Durchschnitt brauchen ein Zahlenfeld.")

    def test_small_ranges_keep_their_decimals(self):
        from ..blocks import decimals_for

        self.assertEqual(decimals_for(0), 2)
        self.assertEqual(decimals_for(250), 2)
        self.assertEqual(decimals_for(0.024), 3)
        self.assertEqual(decimals_for(0.002), 4)
        messwerte = Entity.objects.create(app=self.app, name="Messungen", slug="messungen")
        Field.objects.create(entity=messwerte, label="Wert", key="wert", type=Field.DECIMAL, order=1)
        for wert in (24.001, 24.004, 24.006, 24.011, 24.012):
            Record.objects.create(entity=messwerte, data={"wert": wert})
        response = self._page(make_block("histogram", entity="messungen", field="wert", bins=4))
        self.assertContains(response, "24,0010–24,0038")
        self.assertNotContains(response, "24,00–24,00")

    def test_stat_days_since_and_until(self):
        import re

        response = self._page(
            make_block("stat", label="Seit", entity="stoerungen", aggregate="days_since", field="faellig"),
            make_block("stat", label="Bis", entity="stoerungen", aggregate="days_until", field="faellig"),
            make_block("stat", label="Offen seit", entity="stoerungen", aggregate="days_since", field="faellig",
                       where="Status = Offen", direction="lower_worse", warn_at="5", alarm_at="2"),
            make_block("stat", label="Offen bis", entity="stoerungen", aggregate="days_until", field="faellig",
                       where="Status = Offen"),
        )
        html = response.content.decode()
        values = re.findall(r'<span data-slot="value">([^<]*)</span>', html)
        self.assertEqual(values, ["1", "2", "3", "–"])  # C vor 1 Tag, B in 2 Tagen; offen: A vor 3, nichts kommt
        self.assertIn("stat-warning", html)
        wrong = self._page(make_block("stat", label="X", entity="stoerungen", aggregate="days_since", field="minuten"))
        self.assertContains(wrong, "brauchen ein Datumsfeld")

    def test_control_chart_with_lower_limit_and_precise_mean(self):
        from datetime import timedelta

        messwerte = Entity.objects.create(app=self.app, name="Messungen", slug="messungen")
        Field.objects.create(entity=messwerte, label="Datum", key="datum", type=Field.DATE, order=1)
        Field.objects.create(entity=messwerte, label="Wert", key="wert", type=Field.DECIMAL, order=2)
        for tage, wert in [(-3, 24.001), (-2, 23.990), (-1, 24.004), (0, 24.012)]:
            Record.objects.create(entity=messwerte, data={"datum": (self.today + timedelta(days=tage)).isoformat(),
                                                          "wert": wert})
        response = self._page(
            make_block("line", entity="messungen", date_field="datum", aggregate="avg", field="wert", period="day",
                       count=5, threshold="24,008", threshold_low="23,992"),
            make_block("stat", label="Mittelwert", entity="messungen", aggregate="avg", field="wert"),
        )
        html = response.content.decode()
        self.assertEqual(html.count('class="line-threshold"'), 2)
        self.assertEqual(html.count('class="line-anomaly"'), 2)  # 23,990 unter UEG, 24,012 über OEG
        self.assertIn('<span data-slot="value">24,002</span>', html)  # nicht „24,00“

    def test_pivot_uses_german_number_format(self):
        Record.objects.create(entity=self.entity, data={"titel": "F", "status": "Offen", "minuten": 1234.5})
        response = self._page(make_block("pivot", entity="stoerungen", row_field="status", agg="sum",
                                         value_field="minuten"))
        self.assertContains(response, "1.364,5")  # A 120 + D 10 + F 1234,5


class WerkAppsTests(TestCase):
    """Die Werks-Apps aus beispiele/werk/ lassen sich laden, und jede Seite rendert ohne Fehler."""

    def test_all_apps_load_and_render(self):
        import re

        from ..scripting import python, triggers

        with mock.patch.object(triggers, "on_save"):  # Skripte beim Speichern laufen hier nicht, das dauert
            call_command("beispiel_werk", verbosity=0)
        apps = App.objects.filter(slug__startswith="gmd-")
        self.assertGreaterEqual(apps.count(), 20)
        self.assertFalse(Record.objects.filter(entity__app__in=apps, data__has_key="datum",
                                               data__datum__startswith="@").exists())  # „@-3“ aufgelöst
        self.client.force_login(User.objects.create_user("pruefer", password="x"))
        empty = mock.Mock(ok=True, ui={}, messages=[], log=[], error="", record=None)
        for app in apps:
            self.assertFalse(app.scripts.filter(enabled=False).exists(), app.slug)
            for page in app.pages.all():
                url = reverse("page", args=[app.slug, page.slug])
                if not page.show_in_nav:  # Detailseite: Eintrag der Tabelle ihres Detail-Bausteins
                    slug = next(b["props"]["entity"] for b in page.layout if b["type"] in ("detail", "stepper"))
                    url += f"?id={Record.objects.filter(entity__app=app, entity__slug=slug).first().pk}"
                with mock.patch.object(python, "run", return_value=empty):  # Seitenskripte nicht ausführen
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                errors = re.findall(r'class="block-error">([^<]+)', response.content.decode())
                # Kennzahlen ohne Tabelle füllt das (hier nicht ausgeführte) Seitenskript
                self.assertFalse([e for e in errors if "keine Tabelle" not in e], f"{url}: {errors}")


class DatumsFormelTests(TestCase):
    """Formeln rechnen mit Datumsfeldern: Tage zwischen zwei Daten, Datum plus Tage oder Monate."""

    def test_date_formulas(self):
        from ..forms import FieldForm
        from ..models import apply_formulas

        app = App.objects.create(name="Prüfmittel", slug="pm")
        entity = Entity.objects.create(app=app, name="Lehren", slug="lehren")
        Field.objects.create(entity=entity, label="Zuletzt", key="zuletzt", type=Field.DATE, order=1)
        Field.objects.create(entity=entity, label="Intervall", key="intervall", type=Field.NUMBER, order=2)
        Field.objects.create(entity=entity, label="Fällig", key="faellig", type=Field.DATE, order=3,
                             formula="zuletzt + intervall", show_in_form=False)
        Field.objects.create(entity=entity, label="Kalibrierung", key="kalib", type=Field.DATE, order=4,
                             formula="add_months(zuletzt, 12)", show_in_form=False)
        Field.objects.create(entity=entity, label="Puffer", key="puffer", type=Field.NUMBER, order=5,
                             formula="faellig - zuletzt", show_in_form=False)
        record = Record.objects.create(entity=entity, data={"zuletzt": "2026-01-31", "intervall": 30})
        self.assertEqual(record.data["faellig"], "2026-03-02")
        self.assertEqual(record.data["kalib"], "2027-01-31")
        self.assertEqual(record.data["puffer"], 30)
        data = {"zuletzt": "2028-01-31", "intervall": 30}
        apply_formulas(entity, data)
        self.assertEqual(data["kalib"], "2029-01-31")
        monat = {"zuletzt": "2026-01-31"}
        Field.objects.filter(key="kalib").update(formula="add_months(zuletzt, 1)")
        apply_formulas(entity, monat)
        self.assertEqual(monat["kalib"], "2026-02-28")  # kein 31. Februar
        leer = {"zuletzt": "", "intervall": 30}
        apply_formulas(entity, leer)
        self.assertIsNone(leer.get("faellig"))
        form = FieldForm(data={"label": "Nächste", "type": Field.DATE, "formula": "zuletzt + intervall * 2",
                               "show_in_list": True}, app=app, entity=entity)
        self.assertTrue(form.is_valid(), form.errors)
        form = FieldForm(data={"label": "Text", "type": Field.TEXT, "formula": "zuletzt + 1"}, app=app, entity=entity)
        self.assertIn("formula", form.errors)


class AchsenBeschriftungTests(TestCase):
    """Beschriftungen in Gantt und Liniendiagramm überlappen nicht („30.11.1.12.“, „25.11.26.11.“)."""

    def test_gantt_month_start_replaces_neighbouring_week_label(self):
        from datetime import date, timedelta

        from ..widgets import _gantt_labelled

        start = date(2026, 11, 23)  # Montag
        shown = [(start + timedelta(days=i)).strftime("%d.%m.") for i in range(28)
                 if _gantt_labelled(i, start + timedelta(days=i))]
        self.assertEqual(shown, ["23.11.", "01.12.", "07.12.", "14.12."])  # 30.11. fällt weg


class FragmentLinkTests(TestCase):
    """Einzeln geladene Bausteine (Startseiten-Widgets, Neuladen) verlinken auf ihre Seite, nicht auf /b/."""

    def setUp(self):
        call_command("beispiel_datascience", verbosity=0)
        self.app = App.objects.get(slug="datascience")
        User.objects.create_superuser("chef", password="x")
        self.client.login(username="chef", password="x")

    def test_click_filters_point_to_page(self):
        page = Page.objects.create(app=self.app, title="Extra", slug="extra", layout=[
            {"id": "bch", "type": "chart", "width": 6, "props": {"label": "Nach Werk", "entity": "chargen", "field": "werk"}},
            {"id": "bdo", "type": "donut", "width": 6, "props": {"label": "Anteil", "entity": "chargen", "field": "werk"}},
        ])
        page_url = reverse("page", args=[self.app.slug, page.slug])
        for block in ("bch", "bdo"):
            html = self.client.get(reverse("page_block", args=[self.app.slug, page.slug, block])).content.decode()
            self.assertIn(f'href="{page_url}?chargen.werk=', html)
            self.assertNotIn("/b/", html)
        # Mit Filter: derselbe Link nimmt ihn wieder heraus und bleibt auf der Seite
        html = self.client.get(reverse("page_block", args=[self.app.slug, page.slug, "bch"]),
                               {"chargen.werk": "München"}).content.decode()
        self.assertIn(f'href="{page_url}"', html)

    def test_scatter_widget_links_to_page(self):
        page = next(p for p in self.app.pages.all() if any(b.get("type") == "scatter" for b in p.layout))
        block = next(b for b in page.layout if b.get("type") == "scatter")
        html = self.client.get(reverse("page_block", args=[self.app.slug, page.slug, block["id"]])).content.decode()
        self.assertIn(f'href="{reverse("page", args=[self.app.slug, page.slug])}?', html)
        self.assertNotIn(f"/b/{block['id']}/", html)

    def test_next_links_point_to_page(self):
        app = App.objects.get(slug="datascience")
        entity = app.entities.get(slug="chargen")
        page = Page.objects.create(app=app, title="Liste", slug="liste", layout=[
            {"id": "tab", "type": "table", "width": 12, "props": {"entity": entity.slug}},
        ])
        html = self.client.get(reverse("page_block", args=[app.slug, page.slug, "tab"])).content.decode()
        self.assertNotIn("/b/tab/", html)
