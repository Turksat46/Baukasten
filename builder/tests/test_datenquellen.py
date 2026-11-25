"""Externe Datenquellen, Databricks, Lastschutz und Tableau."""

import json
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from ..blocks import make_block
from ..models import Page
from .base import Base, DataSourceBase


class DataSourceTests(DataSourceBase):
    def test_read_only_check(self):
        from ..datasources import QueryError, check_read_only
        check_read_only("SELECT * FROM teile WHERE name = 'delete' -- update\n")
        check_read_only("with x as (select 1) select * from x;")
        for sql in ("DELETE FROM teile", "SELECT 1; DROP TABLE teile", "WITH x AS (DELETE FROM teile RETURNING *) SELECT * FROM x",
                    "UPDATE teile SET bestand = 0", "PRAGMA table_info(teile)", "", "INSERT INTO teile VALUES (1)"):
            with self.assertRaises(QueryError, msg=sql):
                check_read_only(sql)

    def test_param_conversion(self):
        from ..datasources import convert_params
        sql = "SELECT * FROM t WHERE a = :a AND b::text = ':nicht' AND c LIKE '%x' -- :kommentar\nAND d = :d"
        self.assertEqual(convert_params(sql, {"a": 1, "d": 2}, "qmark"),
                         ("SELECT * FROM t WHERE a = ? AND b::text = ':nicht' AND c LIKE '%x' -- :kommentar\nAND d = ?", [1, 2]))
        converted, params = convert_params(sql, {"a": 1, "d": 2}, "pyformat")
        self.assertIn("a = %(a)s", converted)
        self.assertIn("LIKE '%%x'", converted)         # der Treiber liest % auch in Zeichenketten
        self.assertIn("LIKE '%x'", converted % {"a": 1, "d": 2})
        self.assertNotIn("%%(", converted)
        self.assertEqual(convert_params("SELECT :a", {"a": 1}, "named"), ("SELECT :a", {"a": 1}))

    def test_query_and_script_access(self):
        from .. import datasources
        result = datasources.run("lager", "SELECT nr, bestand FROM teile WHERE bestand > :min ORDER BY nr", {"min": 50})
        self.assertEqual(result["rows"], [{"nr": "A1", "bestand": 120}, {"nr": "A2", "bestand": 80}])
        with self.assertRaises(datasources.QueryError):
            datasources.run("lager", "SELECT * FROM gibtsnicht")
        from ..scripting import python
        script = python.run('rows = db.query("lager", "SELECT name FROM teile WHERE nr = :nr", {"nr": "B7"})\nprint(rows[0]["name"])', self.app)
        self.assertEqual(script.log, ["Welle"])

    def test_live_block_and_refresh(self):
        from ..models import DataQuery
        query = DataQuery.objects.create(app=self.app, name="Teile", source="lager", sql="SELECT nr, name FROM teile ORDER BY nr")
        page = Page.objects.create(app=self.app, title="Live", layout=[
            {**make_block("query", query=query.slug), "refresh": 30}])
        self.client.force_login(self.user)
        content = self.client.get(reverse("page", args=["inventar", page.slug])).content.decode()
        # Die Seite kommt sofort, der Baustein mit der Abfrage wird nachgeladen.
        self.assertNotIn("<td>Welle</td>", content)
        self.assertIn("data-lazy", content)
        self.assertIn("block-loading", content)
        self.assertIn('data-refresh="30"', content)
        self.assertIn('id="bk-runtime"', content)
        block = page.layout[0]["id"]
        fragment = self.client.get(reverse("page_block", args=["inventar", page.slug, block]))
        self.assertContains(fragment, "<td>Schraube</td>")
        self.assertEqual(self.client.get(reverse("page_block", args=["inventar", page.slug, "fremd"])).status_code, 404)

    @override_settings(BAUKASTEN_LAZY_QUERIES=False)
    def test_live_block_inline_when_lazy_off(self):
        from ..models import DataQuery
        query = DataQuery.objects.create(app=self.app, name="Teile", source="lager", sql="SELECT nr, name FROM teile ORDER BY nr")
        page = Page.objects.create(app=self.app, title="Direkt", layout=[make_block("query", query=query.slug)])
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("page", args=["inventar", page.slug])), "<td>Welle</td>")

    def test_sync_into_table(self):
        import sqlite3

        from .. import datasources
        from ..models import DataQuery
        query = DataQuery.objects.create(app=self.app, name="Lagerteile", source="lager",
                                         sql="SELECT * FROM teile", key_column="nr")
        self.assertTrue(datasources.sync_and_record(query), query.last_sync_message)
        entity = query.sync_entity
        self.assertEqual({f.key: f.type for f in entity.fields.all()},
                         {"nr": "text", "name": "text", "bestand": "number", "preis": "decimal", "datum": "date", "aktiv": "number"})
        self.assertFalse(entity.allow_create)
        first_ids = {r.data["nr"]: r.pk for r in entity.records.all()}
        self.assertEqual(len(first_ids), 3)
        path = datasources.sources()["lager"].split("sqlite:///", 1)[1]
        conn = sqlite3.connect(path)
        conn.execute("UPDATE teile SET bestand = 99 WHERE nr = 'A1'")
        conn.execute("DELETE FROM teile WHERE nr = 'A2'")
        conn.execute("INSERT INTO teile VALUES ('C1', 'Feder', 10, 1.0, '2026-04-01', 1)")
        conn.commit()
        conn.close()
        datasources.sync_and_record(query)
        after = {r.data["nr"]: r for r in entity.records.all()}
        self.assertEqual(sorted(after), ["A1", "B7", "C1"])
        self.assertEqual(after["A1"].pk, first_ids["A1"])          # Schlüssel: Einträge behalten ihre Nummer
        self.assertEqual(after["A1"].data["bestand"], 99)
        query.key_column = "gibtsnicht"
        query.save()
        self.assertFalse(datasources.sync_and_record(query))
        self.assertIn("gibtsnicht", query.last_sync_message)

    def test_designer_query_editor(self):
        self.client.force_login(self.designer)
        url = reverse("designer_query_new", args=["inventar"])
        bad = self.client.post(url, {"name": "X", "source": "lager", "sql": "DELETE FROM teile", "cache_seconds": 60,
                                     "sync_interval": 0, "action": "save"})
        self.assertContains(bad, "nur lesende Abfragen")
        response = self.client.post(url, {"name": "Teile", "source": "lager", "sql": "SELECT nr, name FROM teile",
                                          "cache_seconds": 60, "sync_interval": 0, "action": "test"})
        self.assertContains(response, "<td>Mutter</td>")
        from ..models import DataQuery
        query = DataQuery.objects.get(name="Teile")
        synced = self.client.post(reverse("designer_query", args=["inventar", query.pk]), {
            "name": "Teile", "source": "lager", "sql": "SELECT nr, name FROM teile", "cache_seconds": 60,
            "sync_interval": 0, "key_column": "nr", "action": "sync"}, follow=True)
        self.assertContains(synced, "3 Zeilen übernommen")
        self.assertNotContains(self.client.get(reverse("designer_query", args=["inventar", query.pk])), "sqlite:///")


# ---------- Python-Bibliothek ----------


class DatabricksTests(TestCase):
    """Ohne echten Databricks-Zugang: prüft, wie die Adresse an den Treiber übergeben wird."""

    def test_connection_parameters(self):
        from .. import datasources
        url = "databricks://token:dapi%2Fgeheim@adb-123.azuredatabricks.net/sql/1.0/warehouses/abc?catalog=main&schema=werk"
        cursor = mock.MagicMock(description=[("linie",), ("stueck",)])
        cursor.fetchmany.return_value = [("L1", 120), ("L2", 95)]
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor
        with override_settings(BAUKASTEN_DATASOURCES={"dwh": url}), \
                mock.patch("databricks.sql.connect", return_value=connection) as connect:
            result = datasources.run("dwh", "SELECT linie, stueck FROM werk.ausstoss WHERE tag = :tag", {"tag": "2026-11-16"})
        kwargs = connect.call_args.kwargs
        self.assertEqual((kwargs["server_hostname"], kwargs["http_path"], kwargs["access_token"]),
                         ("adb-123.azuredatabricks.net", "/sql/1.0/warehouses/abc", "dapi/geheim"))
        self.assertEqual((kwargs["catalog"], kwargs["schema"]), ("main", "werk"))
        statement, params = cursor.execute.call_args.args
        self.assertEqual((statement, params), ("SELECT linie, stueck FROM werk.ausstoss WHERE tag = :tag", {"tag": "2026-11-16"}))
        self.assertEqual(result["rows"], [{"linie": "L1", "stueck": 120}, {"linie": "L2", "stueck": 95}])
        connection.close.assert_called_once()

    def test_driver_error_is_readable_and_hides_token(self):
        from .. import datasources
        url = "databricks://token:dapiGEHEIM@adb-1.azuredatabricks.net/sql/1.0/warehouses/x"
        with override_settings(BAUKASTEN_DATASOURCES={"dwh": url}), \
                mock.patch("databricks.sql.connect", side_effect=RuntimeError("403 Forbidden for token dapiGEHEIM\nDetails")):
            with self.assertRaises(datasources.QueryError) as caught:
                datasources.run("dwh", "SELECT 1")
        self.assertEqual(str(caught.exception), "Keine Verbindung zur Datenquelle: 403 Forbidden for token ***")

    def test_background_command_once(self):
        from io import StringIO
        out = StringIO()
        call_command("hintergrund", stdout=out)
        self.assertIn("0 Skripte ausgeführt, 0 Abgleiche", out.getvalue())


@override_settings(BAUKASTEN_QUERY_PARALLEL=1, BAUKASTEN_QUERY_WAIT=0.3)
class LoadProtectionTests(DataSourceBase):
    """Schutz unter Last: Limit je Quelle, Sperre gegen Mehrfachabfragen, letzter Stand bei Fehlern."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def _query(self, **extra):
        from ..models import DataQuery
        return DataQuery.objects.create(app=self.app, name="Teile", source="lager",
                                        sql="SELECT nr, name FROM teile ORDER BY nr", **extra)

    def test_limit_per_source_answers_busy_instead_of_blocking(self):
        import time

        from .. import datasources
        with datasources.slot("lager", hold_seconds=30):
            started = time.monotonic()
            with self.assertRaises(datasources.QueryBusy):
                datasources.run("lager", "SELECT 1")
            self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(datasources.run("lager", "SELECT 1 AS x")["rows"], [{"x": 1}])

    @override_settings(BAUKASTEN_QUERY_PARALLEL_BY_SOURCE={"lager": 2})
    def test_limit_per_source_can_be_set_individually(self):
        from .. import datasources
        self.assertEqual(datasources.parallel_limit("lager"), 2)
        self.assertEqual(datasources.parallel_limit("andere"), 1)

    def test_identical_query_runs_only_once(self):
        from unittest import mock

        from .. import datasources
        query = self._query(cache_seconds=60)
        with mock.patch.object(datasources, "_run", wraps=datasources._run) as spy:
            for _ in range(5):
                datasources.run_saved(query)
        self.assertEqual(spy.call_count, 1)

    def test_running_query_is_not_sent_twice(self):
        from django.core.cache import cache

        from .. import datasources
        query = self._query(cache_seconds=0)
        first = datasources.run_saved(query)
        # Jemand anderes lädt gerade: der letzte Stand kommt sofort, ohne neue Abfrage.
        cache.add(datasources.query_cache_key(query) + "-lock", 1, 60)
        from unittest import mock
        with mock.patch.object(datasources, "_run") as spy:
            again = datasources.run_saved(query)
        spy.assert_not_called()
        self.assertEqual(again["rows"], first["rows"])

    def test_last_result_shown_when_source_fails(self):
        from unittest import mock

        from .. import datasources
        query = self._query(cache_seconds=0)
        datasources.run_saved(query)
        with mock.patch.object(datasources, "_run", side_effect=datasources.QueryError("weg")):
            result = datasources.run_saved(query)
        self.assertTrue(result["stale"])
        self.assertEqual(result["rows"][0]["name"], "Schraube")

    def test_busy_block_asks_browser_to_retry(self):
        from unittest import mock

        from .. import datasources
        query = self._query()
        page = Page.objects.create(app=self.app, title="Live", layout=[make_block("query", query=query.slug)])
        self.client.force_login(self.user)
        with mock.patch.object(datasources, "run_saved", side_effect=datasources.QueryBusy("ausgelastet")):
            fragment = self.client.get(reverse("page_block", args=["inventar", page.slug, page.layout[0]["id"]]))
        self.assertContains(fragment, 'data-pending="2"')
        self.assertContains(fragment, "ausgelastet")
        self.assertNotContains(fragment, "block-error")

    def test_bridge_reports_busy_with_retry_after(self):
        from unittest import mock

        from .. import datasources
        query = self._query()
        self.client.force_login(self.user)
        with mock.patch.object(datasources, "run_saved", side_effect=datasources.QueryBusy("ausgelastet")):
            response = self.client.post(reverse("script_bridge", args=["inventar"]),
                                        data=json.dumps({"op": "query.run", "args": {"slug": query.slug}}),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "3")

    def test_sync_uses_long_timeout(self):
        from unittest import mock

        from .. import datasources
        query = self._query()
        with mock.patch.object(datasources, "_run", wraps=datasources._run) as spy:
            datasources.sync(query)
        self.assertEqual(spy.call_args.args[4], datasources.sync_timeout())


@override_settings(BAUKASTEN_TABLEAU_HOSTS=["tableau.example.com"], BAUKASTEN_TABLEAU_CLIENT_ID="",
                   BAUKASTEN_TABLEAU_SECRET_ID="", BAUKASTEN_TABLEAU_SECRET_VALUE="")
class TableauTests(Base):
    """Baustein „Tableau-Ansicht“ (builder/tableau.py)."""

    URL = "https://tableau.example.com/views/Werke/Uebersicht"

    def render(self, user=None, query="", **props):
        from django.test import RequestFactory

        from ..blocks import prep_tableau
        request = RequestFactory().get("/" + query)
        request.user = user or self.user
        return prep_tableau(request, self.app, make_block("tableau", url=self.URL, **props))

    def test_embeds_allowed_host_with_filters_from_address(self):
        ctx = self.render(query="?werk=Stuttgart", filters="Werk = {werk}\nJahr = 2026\nLeer = {fehlt}\nkein Filter")
        self.assertEqual(ctx["script_url"], "https://tableau.example.com/javascripts/api/tableau.embedding.3.latest.min.js")
        self.assertEqual(ctx["filters"], [{"field": "Werk", "value": "Stuttgart"}, {"field": "Jahr", "value": "2026"}])
        self.assertIsNone(ctx["token"])  # ohne Connected App melden sich Nutzer selbst bei Tableau an
        self.assertEqual((ctx["height"], ctx["toolbar"]), (600, "bottom"))

    def test_rejects_other_hosts_http_and_guests(self):
        from django.contrib.auth.models import AnonymousUser
        from ..blocks import prep_tableau
        from django.test import RequestFactory
        for url in ("https://boese.example.com/views/x", "http://tableau.example.com/views/x", "javascript:alert(1)"):
            request = RequestFactory().get("/")
            request.user = self.user
            self.assertIn("nicht freigegeben", prep_tableau(request, self.app, make_block("tableau", url=url))["error"])
        self.assertIn("angemeldete", self.render(user=AnonymousUser())["error"])

    def test_connected_app_token(self):
        import base64
        import hashlib
        import hmac

        from .. import tableau
        self.user.email = "max@example.com"
        self.user.save()
        with override_settings(BAUKASTEN_TABLEAU_CLIENT_ID="client-1", BAUKASTEN_TABLEAU_SECRET_ID="secret-1",
                               BAUKASTEN_TABLEAU_SECRET_VALUE="geheim"):
            token = tableau.connected_app_token(self.user, now=1_800_000_000)
            ctx = self.render()
        head, body, signature = token.split(".")
        decode = lambda part: json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))  # noqa: E731
        self.assertEqual(decode(head), {"alg": "HS256", "typ": "JWT", "kid": "secret-1", "iss": "client-1"})
        claims = decode(body)
        self.assertEqual((claims["sub"], claims["aud"], claims["scp"]), ("max@example.com", "tableau", ["tableau:views:embed"]))
        self.assertEqual(claims["exp"] - claims["iat"], 300)
        expected = base64.urlsafe_b64encode(hmac.new(b"geheim", f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertEqual(signature, expected)
        self.assertTrue(ctx["token"])

    def test_page_renders_tableau_viz(self):
        page = Page.objects.create(app=self.app, title="BI", layout=[
            make_block("tableau", url=self.URL, label="Werke", hide_tabs=True, filters="Werk = <b>{werk}</b>")])
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", page.slug]), {"werk": '"><script>x</script>'})
        self.assertContains(response, f'<tableau-viz src="{self.URL}"')
        self.assertContains(response, " hide-tabs")
        self.assertNotContains(response, "<script>x</script>")  # Werte aus der Adresse werden maskiert
        self.assertNotContains(response, 'token="')
