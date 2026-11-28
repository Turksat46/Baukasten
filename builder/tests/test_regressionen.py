"""Querschnittliche Regressionstests aus Reviews und Fehlersuchen."""

import json
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import App, Entity, Field, Page, Record
from ..services import HttpNotAllowed, http_request
from .base import _DEMO_DIR


class ReviewHardeningTests(TestCase):
    """Tests für Review-Härtungen: Probes, OIDC-Claims, SSRF, SQLite-Guard, API-Key-Aktivstatus, Slugs."""

    def test_healthz_readyz_and_redirect_exempt(self):
        from django.conf import settings

        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        self.assertTrue(any("healthz" in pat for pat in settings.SECURE_REDIRECT_EXEMPT))
        self.assertTrue(any("readyz" in pat for pat in settings.SECURE_REDIRECT_EXEMPT))

    def test_oidc_claim_names_and_username_fallback(self):
        from ..auth import _username_from_claims, claim_names

        claims = {"groups": ["/Automatisierer/", " /Team/Labor ", "/extern"]}
        self.assertEqual(claim_names(claims, "groups"), {"Automatisierer", "Labor", "extern"})
        self.assertEqual(claim_names(claims, "groups", prefix="Auto"), {"Automatisierer"})

        self.assertEqual(_username_from_claims({"preferred_username": "alice"}), "alice")
        self.assertEqual(_username_from_claims({"sub": "uuid-1234"}), "uuid-1234")
        self.assertEqual(_username_from_claims({"email": "bob@example.com"}), "")

    def test_ssrf_forbidden_hosts_and_internal_sqlite_guard(self):
        from django.conf import settings
        from ..datasources import QueryError, _connect

        with override_settings(BAUKASTEN_HTTP_ALLOWED_HOSTS=["127.0.0.1", "169.254.169.254", "localhost"]):
            for bad in ("http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/", "http://localhost/x"):
                with self.assertRaises(HttpNotAllowed):
                    http_request("GET", bad)

        fake_db = str(Path(_DEMO_DIR) / "internal-test.sqlite3")
        with override_settings(DATABASES={"default": {**settings.DATABASES["default"], "NAME": fake_db}}):
            with self.assertRaises(QueryError):
                _connect(f"sqlite:///{fake_db}", 5)

    def test_deactivated_user_api_key_rejected_and_reserved_slugs(self):
        from ..models import ApiKey, unique_slug

        owner = User.objects.create_user("apiuser", password="x", is_active=True)
        app = App.objects.create(name="Test", slug="test-api", created_by=owner, published=True)
        entity = Entity.objects.create(app=app, name="Items", slug="items", api_enabled=True)
        _key_obj, raw = ApiKey.issue(app, "Key", can_write=False, user=owner)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
        self.assertEqual(self.client.get(f"/api/v1/{app.slug}/{entity.slug}/", **auth).status_code, 200)

        owner.is_active = False
        owner.save()
        self.assertEqual(self.client.get(f"/api/v1/{app.slug}/{entity.slug}/", **auth).status_code, 401)

        self.assertEqual(unique_slug(app.entities, "neu"), "neu-2")


class ReviewFindingsTests(TestCase):
    """Befunde aus dem Code-Review: jeder Test schlägt mit dem alten Code fehl."""

    ROWS = [  # so liefert datasources.run_saved die Zeilen: Dictionaries {Spalte: Wert}
        {"temp": 180.0, "scrap": 1.5, "plant": "Stuttgart"},
        {"temp": 185.0, "scrap": 2.1, "plant": "Stuttgart"},
        {"temp": 195.0, "scrap": 3.8, "plant": "München"},
        {"temp": 200.0, "scrap": 4.4, "plant": "München"},
    ]

    def setUp(self):
        from ..models import DataQuery

        self.app = App.objects.create(name="Review", slug="review", published=True)
        self.query = DataQuery.objects.create(app=self.app, name="Chargen", slug="chargen", source="dwh",
                                              sql="SELECT * FROM c WHERE werk = :werk")
        self.user = User.objects.create_user("pruefer", password="x")

    def result(self):
        return {"columns": ["temp", "scrap", "plant"], "rows": [dict(r) for r in self.ROWS],
                "fetched_at": "2026-11-22T10:00:00+00:00", "truncated": False}

    def test_query_export_requires_login_and_writes_values(self):
        from unittest.mock import patch

        url = reverse("query_export", args=[self.app.slug, self.query.slug])
        with patch("builder.datasources.run_saved", return_value=self.result()) as run:
            self.assertEqual(self.client.get(url).status_code, 302)  # ohne Anmeldung: zur Anmeldung
            run.assert_not_called()
            self.client.force_login(self.user)
            body = b"".join(self.client.get(url + "?werk=S&fremd=1").streaming_content).decode("utf-8")
        self.assertIn("180.0;1.5;Stuttgart", body)
        self.assertNotIn("temp;scrap;plant\r\ntemp", body)
        self.assertEqual(run.call_args.args[1], {"werk": "S"})  # nur Parameter aus dem SQL

    def test_datascience_blocks_read_query_rows(self):
        from unittest.mock import patch

        from ..blocks import render_block
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        blocks = [
            {"id": "s", "type": "scatter", "props": {"query": "chargen", "x_field": "temp", "y_field": "scrap"}},
            {"id": "b", "type": "boxplot", "props": {"query": "chargen", "field": "scrap", "group_field": "plant"}},
            {"id": "h", "type": "histogram", "props": {"query": "chargen", "field": "temp", "bins": 4}},
            {"id": "m", "type": "heatmap", "props": {"query": "chargen", "mode": "correlation"}},
            {"id": "c", "type": "spec_chart", "props": {"query": "chargen", "spec": json.dumps(
                {"mark": "bar", "encoding": {"x": {"field": "plant"}, "y": {"field": "scrap", "aggregate": "sum"}}})}},
        ]
        with patch("builder.datasources.run_saved", return_value=self.result()):
            for block in blocks:
                html = render_block(request, self.app, block)
                self.assertNotIn("block-error", html, block["type"])
        with patch("builder.datasources.run_saved", return_value=self.result()):
            scatter = render_block(request, self.app, blocks[0])
            boxplot = render_block(request, self.app, blocks[1])
        self.assertEqual(scatter.count("<circle"), 4)  # vier Messpunkte
        self.assertIn("Stuttgart", boxplot)
        self.assertIn("München", boxplot)

    def test_datascience_block_with_query_loads_later(self):
        from unittest.mock import patch

        from .. import datasources

        page = Page.objects.create(app=self.app, title="DS", slug="ds", layout=[
            {"id": "s", "type": "scatter", "props": {"title": "Live", "query": "chargen", "x_field": "temp", "y_field": "scrap"}},
        ])
        self.client.force_login(self.user)
        with self.settings(BAUKASTEN_LAZY_QUERIES=True), \
                patch("builder.datasources.run_saved", side_effect=datasources.QueryBusy("läuft")) as run:
            html = self.client.get(reverse("page", args=[self.app.slug, page.slug])).content.decode()
            run.assert_not_called()  # die Seite wartet nicht auf die Abfrage
            self.assertIn("data-lazy", html)
            block = self.client.get(reverse("page_block", args=[self.app.slug, page.slug, "s"])).content.decode()
        self.assertIn('data-pending="2"', block)

    def test_formula_overflow_does_not_break_saving(self):
        from ..models import evaluate_formula

        entity = Entity.objects.create(app=self.app, name="Posten", slug="posten")
        Field.objects.create(entity=entity, label="Preis", key="preis", type=Field.DECIMAL)
        Field.objects.create(entity=entity, label="Riesig", key="riesig", type=Field.NUMBER, formula="preis * 1e308 * 10")
        self.assertIsNone(evaluate_formula("preis * 1e308 * 10", {"preis": 5}))
        record = Record.objects.create(entity=entity, data={"preis": 5})  # früher: OverflowError
        self.assertNotIn("riesig", record.data)

    def test_formula_may_use_later_formula_fields(self):
        entity = Entity.objects.create(app=self.app, name="Posten", slug="posten")
        Field.objects.create(entity=entity, label="Brutto", key="brutto", type=Field.DECIMAL, formula="netto * 1.19")
        Field.objects.create(entity=entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=entity, label="Preis", key="preis", type=Field.DECIMAL)
        Field.objects.create(entity=entity, label="Netto", key="netto", type=Field.DECIMAL, formula="menge * preis")
        record = Record.objects.create(entity=entity, data={"menge": 2, "preis": 10})
        self.assertEqual(record.data["netto"], 20)
        self.assertEqual(record.data["brutto"], 23.8)

    def test_csv_import_keeps_global_dialect_and_computes_formulas(self):
        import csv

        from .. import csv_import

        before = csv.excel.delimiter
        headers, rows = csv_import.parse_csv("kopf\nwert\n".encode())  # Sniffer scheitert bei einer Spalte
        self.assertEqual(csv.excel.delimiter, before)

        entity = Entity.objects.create(app=self.app, name="Posten", slug="posten")
        Field.objects.create(entity=entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=entity, label="Preis", key="preis", type=Field.DECIMAL)
        Field.objects.create(entity=entity, label="Summe", key="summe", type=Field.DECIMAL, formula="menge * preis",
                             show_in_form=False)
        headers, rows = csv_import.parse_csv("menge;preis\n3;2,5\n".encode())
        created, errors = csv_import.run_import(self.app, entity, rows, ["menge", "preis"], self.user)
        self.assertEqual((created, errors), (1, []))
        self.assertEqual(entity.records.get().data["summe"], 7.5)

    def test_related_list_finds_children_beyond_500_entries(self):
        from django.test import RequestFactory

        from ..blocks import render_block

        parent_entity = Entity.objects.create(app=self.app, name="Aufträge", slug="auftraege")
        Field.objects.create(entity=parent_entity, label="Name", key="name")
        child_entity = Entity.objects.create(app=self.app, name="Positionen", slug="positionen")
        Field.objects.create(entity=child_entity, label="Text", key="text")
        Field.objects.create(entity=child_entity, label="Auftrag", key="auftrag", type=Field.REFERENCE,
                             reference=parent_entity)
        parent = Record.objects.create(entity=parent_entity, data={"name": "A"})
        other = Record.objects.create(entity=parent_entity, data={"name": "B"})
        Record.objects.bulk_create([Record(entity=child_entity, data={"text": f"x{i}", "auftrag": other.pk})
                                    for i in range(520)])
        Record.objects.create(entity=child_entity, data={"text": "Gesuchte Position", "auftrag": parent.pk})
        request = RequestFactory().get(f"/?id={parent.pk}")
        request.user = self.user
        html = render_block(request, self.app, {"id": "r", "type": "related_list",
                                                "props": {"entity": "positionen", "ref_field": "auftrag"}})
        self.assertIn("Gesuchte Position", html)
        self.assertNotIn("x0<", html)

    def test_alerts_are_throttled(self):
        from unittest.mock import patch

        from django.core.cache import cache

        from .. import alerts

        cache.clear()
        with patch("builder.platform.value", side_effect=lambda key: {
                "alert_channel": "api", "alert_target": "https://alarm.example.com/hook",
                "alert_auth_header": ""}.get(key)), \
                patch("builder.alerts.requests.post") as post, self.settings(BAUKASTEN_ALERT_REPEAT_MINUTES=60):
            self.assertTrue(alerts.notify_failure("schedule_script", "Skript X fehlgeschlagen", "Fehler", app=self.app))
            self.assertFalse(alerts.notify_failure("schedule_script", "Skript X fehlgeschlagen", "Fehler", app=self.app))
            self.assertTrue(alerts.notify_failure("schedule_script", "Skript Y fehlgeschlagen", "Fehler", app=self.app))
        self.assertEqual(post.call_count, 2)


class BugHuntTests(TestCase):
    """Befunde aus dem Bug-Test vom 24.11.2026: jeder Test schlägt mit dem alten Code fehl."""

    def setUp(self):
        self.app = App.objects.create(name="Fehlersuche", slug="fehlersuche", published=True)
        self.user = User.objects.create_user("suchende", password="x")
        self.entity = Entity.objects.create(app=self.app, name="Posten", slug="posten")

    def request(self, path="/"):
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = self.user
        return request

    def test_chart_click_filters_by_stored_value(self):
        from django.utils import translation

        from ..blocks import filtered, prep_chart, prep_donut

        Field.objects.create(entity=self.entity, label="Aktiv", key="aktiv", type=Field.BOOL)
        Field.objects.create(entity=self.entity, label="Preis", key="preis", type=Field.DECIMAL)
        for aktiv, preis in ((True, 1234.5), (True, 1234.5), (False, 7.0)):
            Record.objects.create(entity=self.entity, data={"aktiv": aktiv, "preis": preis})
        for prep in (prep_chart, prep_donut):
            for key, expected in (("aktiv", {"Ja": [True, True], "Nein": [False]}),
                                  ("preis", {"1.234,50": [1234.5, 1234.5], "7,00": [7.0]})):
                with translation.override("de"):
                    result = prep(self.request(), self.app, {"id": "b", "props": {"entity": "posten", "field": key}})
                items = result.get("bars") or result.get("segments")
                self.assertEqual({i["label"] for i in items}, set(expected))
                for item in items:
                    values = [r.data[key] for r in filtered(self.request(item["href"]), self.entity)]
                    self.assertEqual(sorted(values), sorted(expected[item["label"]]), (prep.__name__, item))

    def test_reference_chart_click_filters(self):
        from ..blocks import filtered, prep_chart

        other = Entity.objects.create(app=self.app, name="Kunden", slug="kunden")
        Field.objects.create(entity=other, label="Name", key="name")
        kunde = Record.objects.create(entity=other, data={"name": "Müller"})
        andere = Record.objects.create(entity=other, data={"name": "Schmidt"})
        Field.objects.create(entity=self.entity, label="Kunde", key="kunde", type=Field.REFERENCE, reference=other)
        Record.objects.create(entity=self.entity, data={"kunde": kunde.pk})
        Record.objects.create(entity=self.entity, data={"kunde": andere.pk})
        bars = prep_chart(self.request(), self.app, {"id": "b", "props": {"entity": "posten", "field": "kunde"}})["bars"]
        bar = next(b for b in bars if b["label"] == "Müller")
        self.assertEqual([r.data["kunde"] for r in filtered(self.request(bar["href"]), self.entity)], [kunde.pk])

    def test_sql_percent_in_strings_survives_parameters(self):
        from .. import datasources

        sql, params = datasources.convert_params("SELECT * FROM t WHERE n LIKE 'A%' AND id = :id -- 5%", {"id": 1},
                                                 "pyformat")
        self.assertEqual(sql, "SELECT * FROM t WHERE n LIKE 'A%%' AND id = %(id)s -- 5%%")
        self.assertEqual(sql % {"id": 1}, "SELECT * FROM t WHERE n LIKE 'A%' AND id = 1 -- 5%")

    def test_read_only_check_handles_backslash_escapes(self):
        from .. import datasources

        for sql in (r"SELECT 'a\'' AS x, 1; DELETE FROM t; SELECT ''",
                    r"SELECT E'\'' AS x, (DELETE FROM t) AS y --'",
                    r"SELECT 'C:\' AS p, 1; DELETE FROM t; SELECT ''"):
            with self.assertRaises(datasources.QueryError, msg=sql):
                datasources.check_read_only(sql)
        for sql in (r"SELECT 'C:\' AS p FROM t WHERE x = 'it''s'", r"SELECT E'\'' AS x", "SELECT 'a;b' AS x"):
            datasources.check_read_only(sql)

    def test_formula_clears_value_when_inputs_are_missing(self):
        Field.objects.create(entity=self.entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Preis", key="preis", type=Field.DECIMAL)
        Field.objects.create(entity=self.entity, label="Summe", key="summe", type=Field.DECIMAL, formula="menge * preis")
        Field.objects.create(entity=self.entity, label="Je Stück", key="stueck", type=Field.DECIMAL,
                             formula="preis / menge")
        record = Record.objects.create(entity=self.entity, data={"menge": 2, "preis": 10})
        self.assertEqual((record.data["summe"], record.data["stueck"]), (20, 5))
        record.data["menge"] = 0
        record.save()
        self.assertEqual((record.data["summe"], record.data["stueck"]), (0, None))  # Division durch 0
        record.data["menge"] = None
        record.save()
        self.assertIsNone(record.data["summe"])

    def test_formula_fields_are_not_form_inputs(self):
        from ..forms import RecordForm

        Field.objects.create(entity=self.entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Doppelt", key="doppelt", type=Field.NUMBER,
                             formula="menge * 2", required=True)
        form = RecordForm(self.entity, {"menge": "3"})
        self.assertNotIn("doppelt", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save(self.user).data["doppelt"], 6)

    def test_field_form_checks_formulas(self):
        from ..forms import FieldForm

        Field.objects.create(entity=self.entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Notiz", key="notiz", type=Field.TEXT)

        def errors(formula, type_=Field.DECIMAL):
            form = FieldForm({"label": "Summe", "type": type_, "formula": formula}, app=self.app, entity=self.entity)
            form.is_valid()
            return form.errors.get("formula")

        self.assertIsNone(errors("round(menge * 1.19, 2)"))
        self.assertIn("mange", errors("mange * 2")[0])
        self.assertIn("notiz", errors("notiz * 2")[0])  # Textfelder rechnen nicht
        self.assertTrue(errors("menge ** 2"))
        self.assertTrue(errors("menge *"))
        self.assertTrue(errors("menge * 2", type_=Field.TEXT))

    def test_spec_chart_understands_vega_lite_aggregates(self):
        from django.utils import translation

        from ..datascience import prep_spec_chart

        Field.objects.create(entity=self.entity, label="Werk", key="werk")
        Field.objects.create(entity=self.entity, label="Wert", key="wert", type=Field.DECIMAL)
        for wert in (1, 2, 9):
            Record.objects.create(entity=self.entity, data={"werk": "A", "wert": wert})
        expected = {"mean": "4", "average": "4", "median": "2", "min": "1", "max": "9", "sum": "12", "count": "3"}
        for agg, value in expected.items():
            spec = {"mark": "bar", "encoding": {"x": {"field": "werk"}, "y": {"field": "wert", "aggregate": agg}}}
            with translation.override("de"):
                result = prep_spec_chart(self.request(), self.app, {"id": "s", "props": {
                    "entity": "posten", "spec": json.dumps(spec)}})
            self.assertEqual(result["items"][0]["value"].split(",")[0], value, agg)
        spec = {"mark": "bar", "encoding": {"x": {"field": "werk"}, "y": {"field": "wert", "aggregate": "stdev"}}}
        result = prep_spec_chart(self.request(), self.app, {"id": "s", "props": {"entity": "posten",
                                                                                "spec": json.dumps(spec)}})
        self.assertIn("error", result)

    def test_zero_is_its_own_group(self):
        from django.utils import translation

        from ..datascience import prep_boxplot

        Field.objects.create(entity=self.entity, label="Stufe", key="stufe", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Wert", key="wert", type=Field.DECIMAL)
        for stufe, wert in ((0, 1), (0, 2), (None, 3), (1, 4)):
            Record.objects.create(entity=self.entity, data={"stufe": stufe, "wert": wert})
        with translation.override("de"):
            rows = prep_boxplot(self.request(), self.app, {"id": "x", "props": {
                "entity": "posten", "field": "wert", "group_field": "stufe"}})["rows"]
        self.assertEqual({r["label"]: r["count"] for r in rows}, {"0": 2, "1": 1, "Ohne": 1})

    def test_csv_export_keeps_negative_numbers(self):
        from ..views import _csv_cell

        self.assertEqual(_csv_cell("-5"), "-5")
        self.assertEqual(_csv_cell("-1.234,50"), "-1.234,50")
        self.assertEqual(_csv_cell("-1+2"), "'-1+2")
        self.assertEqual(_csv_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_csv_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(_csv_cell("\tx"), "'\tx")

    def test_designer_new_table_keeps_permissions(self):
        """Das Formular „Tabelle anlegen“ schickt nur den Namen; die Schalter dürfen nicht „aus“ werden."""
        self.client.force_login(User.objects.create_superuser("chefin", password="x"))
        self.client.post(reverse("designer_app", args=["fehlersuche"]), {"kind": "entity", "entity-name": "Anträge"})
        entity = self.app.entities.get(name="Anträge")
        self.assertEqual((entity.allow_create, entity.allow_edit, entity.allow_delete), (True, True, True))

    def test_decimals_are_rounded_not_cut(self):
        from django.utils import translation

        from ..blocks import _format_number, display_value

        field = Field(key="x", type=Field.DECIMAL)
        with translation.override("de"):
            self.assertEqual(display_value(field, -4.1667), "-4,17")
            self.assertEqual(display_value(field, 2.999), "3,00")
            self.assertEqual(display_value(field, 19.995), "20,00")
            self.assertEqual(_format_number(0.625), "0,63")
            self.assertEqual(_format_number(1234), "1.234")

    def test_spec_chart_shows_display_values(self):
        from django.utils import translation

        from ..datascience import prep_spec_chart

        Field.objects.create(entity=self.entity, label="Aktiv", key="aktiv", type=Field.BOOL)
        Record.objects.create(entity=self.entity, data={"aktiv": True})
        Record.objects.create(entity=self.entity, data={"aktiv": False})
        spec = {"mark": "bar", "encoding": {"x": {"field": "aktiv"}, "y": {"aggregate": "count"}}}
        with translation.override("de"):
            result = prep_spec_chart(self.request(), self.app, {"id": "s", "props": {
                "entity": "posten", "spec": json.dumps(spec)}})
        self.assertEqual(sorted(i["label"] for i in result["items"]), ["Ja", "Nein"])

    def test_csv_import_does_not_offer_formula_fields(self):
        Field.objects.create(entity=self.entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Doppelt", key="doppelt", type=Field.NUMBER, formula="menge * 2")
        self.client.force_login(User.objects.create_superuser("importeur", password="x"))
        url = reverse("entity_import", args=["fehlersuche", "posten"])
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(url, {"step": "upload", "file": SimpleUploadedFile("p.csv", "menge;doppelt\n3;99\n".encode())})
        self.assertNotContains(response, 'value="doppelt"')
        self.client.post(url, {"step": "import", "col_0": "menge", "col_1": ""})
        self.assertEqual(self.entity.records.get().data["doppelt"], 6)


class RecordLabelQueryTests(TestCase):
    """Anzeigetexte von Einträgen dürfen nicht je Eintrag Abfragen kosten (früher 2–3 je Zeile)."""

    def setUp(self):
        self.app = App.objects.create(name="Werk", slug="werk", published=True)
        self.user = User.objects.create_user("leser", password="x")
        self.anlagen = Entity.objects.create(app=self.app, name="Anlagen", slug="anlagen")
        Field.objects.create(entity=self.anlagen, label="Name", key="name")
        self.entity = Entity.objects.create(app=self.app, name="Verluste", slug="verluste")
        Field.objects.create(entity=self.entity, label="Grund", key="grund")
        Field.objects.create(entity=self.entity, label="Minuten", key="minuten", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Ausschuss", key="ausschuss", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Status", key="status", type=Field.CHOICE, choices="offen\nerledigt")
        Field.objects.create(entity=self.entity, label="Anlage", key="anlage", type=Field.REFERENCE,
                             reference=self.anlagen)
        Field.objects.create(entity=self.entity, label="Geprüft", key="geprueft", type=Field.BOOL)
        self.machines = [Record.objects.create(entity=self.anlagen, data={"name": f"Presse {i}"}).pk for i in range(5)]

    def add_records(self, count):
        Record.objects.bulk_create([Record(entity=self.entity, data={
            "grund": f"Stillstand {i}", "minuten": i % 17, "ausschuss": i % 5,
            "status": "offen" if i % 2 else "erledigt", "anlage": self.machines[i % 5],
            "geprueft": bool(i % 3),
        }) for i in range(count)])

    def queries(self):
        from django.db import connection
        from django.test import RequestFactory
        from django.test.utils import CaptureQueriesContext

        from ..blocks import render_block

        request = RequestFactory().get("/")
        request.user = self.user
        blocks = [
            {"id": "s", "type": "scatter", "props": {"entity": "verluste", "x_field": "minuten", "y_field": "ausschuss"}},
            {"id": "b", "type": "boxplot", "props": {"entity": "verluste", "field": "minuten", "group_field": "status"}},
            {"id": "c", "type": "spec_chart", "props": {"entity": "verluste", "spec": json.dumps(
                {"mark": "bar", "encoding": {"x": {"field": "anlage"}, "y": {"field": "minuten", "aggregate": "sum"}}})}},
            {"id": "k", "type": "kanban", "props": {"entity": "verluste", "field": "status", "detail": "anlage"}},
            {"id": "l", "type": "checklist", "props": {"entity": "verluste", "field": "geprueft"}},
        ]
        with CaptureQueriesContext(connection) as ctx:
            for block in blocks:
                html = render_block(request, self.app, block)
                self.assertNotIn("block-error", html, block["type"])
        return len(ctx.captured_queries), html

    def test_query_count_does_not_grow_with_records(self):
        self.add_records(20)
        self.queries()  # einmal vorweg, damit Zwischenspeicher (Übersetzungen, Einstellungen) gefüllt sind
        few, _html = self.queries()
        self.add_records(180)
        many, _html = self.queries()
        self.assertEqual(few, many)
        self.assertLess(many, 100)  # früher über 1000 bei 200 Einträgen

    def test_labels_still_use_first_field(self):
        from ..models import label_key, record_label, record_labels

        self.add_records(3)
        record = self.entity.records.order_by("id").first()
        self.assertEqual(str(record), "Stillstand 0")
        self.assertEqual(label_key(self.entity), "grund")
        self.assertEqual(record_label(record, None), f"#{record.pk}")
        machine = Record.objects.get(pk=self.machines[0])
        self.assertEqual(record_labels([record, machine]), {record.pk: "Stillstand 0", machine.pk: "Presse 0"})
