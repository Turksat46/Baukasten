"""REST-API, OpenAPI, MCP-Server, KI-Designer und Python-Client."""

import json
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import LiveServerTestCase, TestCase, override_settings
from django.urls import reverse

from ..models import App, Record
from .base import BUILDER_DIR, _DEMO_DIR, Base


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        from ..models import ApiKey
        self.entity.api_enabled = True
        self.entity.save()
        _obj, self.read_key = ApiKey.issue(self.app, "Lesen")
        _obj, self.write_key = ApiKey.issue(self.app, "Schreiben", can_write=True)
        self.url = reverse("api_collection", args=["inventar", self.entity.slug])

    def auth(self, key):
        return {"HTTP_AUTHORIZATION": f"Bearer {key}"}

    def test_requires_key_of_this_app(self):
        from ..models import ApiKey
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, **self.auth("bk_falsch")).status_code, 401)
        other = App.objects.create(name="Andere")
        _obj, foreign = ApiKey.issue(other, "fremd", can_write=True)
        self.assertEqual(self.client.get(self.url, **self.auth(foreign)).status_code, 401)
        self.assertFalse(ApiKey.objects.filter(key_hash=self.read_key).exists())  # Klartext wird nicht gespeichert

    def test_list_filter_search_and_describe(self):
        data = self.client.get(self.url, **self.auth(self.read_key)).json()
        self.assertEqual((data["count"], len(data["results"])), (6, 6))
        self.assertEqual(set(data["results"][0]) - {"id", "created_at", "updated_at"},
                         {"bezeichnung", "kategorie", "standort", "anschaffung", "preis", "aktiv"})
        self.assertEqual(self.client.get(self.url, {"kategorie": "IT"}, **self.auth(self.read_key)).json()["count"], 3)
        self.assertEqual(self.client.get(self.url, {"aktiv": "false"}, **self.auth(self.read_key)).json()["count"], 1)
        self.assertEqual(self.client.get(self.url, {"preis": "640"}, **self.auth(self.read_key)).json()["count"], 1)
        self.assertEqual(self.client.get(self.url, {"q": "labor"}, **self.auth(self.read_key)).json()["count"], 2)
        paged = self.client.get(self.url, {"page_size": 4, "page": 2}, **self.auth(self.read_key)).json()
        self.assertEqual((paged["pages"], len(paged["results"])), (2, 2))
        info = self.client.get(reverse("api_describe", args=["inventar"]), **self.auth(self.read_key)).json()
        self.assertEqual(info["tables"][0]["slug"], self.entity.slug)
        self.assertEqual(info["tables"][0]["fields"][1]["choices"], ["IT", "Messtechnik", "Werkstatt"])
        self.assertIn("statistik", [e["name"] for e in info["endpoints"]])

    def test_write_needs_write_key_and_validates(self):
        body = json.dumps({"bezeichnung": "Kamera", "kategorie": "IT", "preis": 499.5, "aktiv": True})
        denied = self.client.post(self.url, body, content_type="application/json", **self.auth(self.read_key))
        self.assertEqual(denied.status_code, 403)
        created = self.client.post(self.url, body, content_type="application/json", **self.auth(self.write_key))
        self.assertEqual(created.status_code, 201)
        pk = created.json()["id"]
        self.assertEqual(Record.objects.get(pk=pk).data["preis"], 499.5)
        invalid = self.client.post(self.url, json.dumps({"kategorie": "Unbekannt"}), content_type="application/json", **self.auth(self.write_key))
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(set(invalid.json()["fields"]), {"bezeichnung", "kategorie"})
        self.assertEqual(self.client.post(self.url, "kein json", content_type="application/json", **self.auth(self.write_key)).status_code, 400)

        item = reverse("api_item", args=["inventar", self.entity.slug, pk])
        patched = self.client.patch(item, json.dumps({"standort": "Lager"}), content_type="application/json", **self.auth(self.write_key))
        self.assertEqual((patched.json()["standort"], patched.json()["bezeichnung"]), ("Lager", "Kamera"))
        replaced = self.client.put(item, json.dumps({"bezeichnung": "Kamera 2", "kategorie": "IT"}), content_type="application/json", **self.auth(self.write_key))
        # PUT leert den Standort; das Skript „Standort ergänzen“ der Beispiel-App setzt ihn wieder.
        self.assertEqual((replaced.json()["bezeichnung"], replaced.json()["standort"]), ("Kamera 2", "Lager"))
        self.assertEqual(self.client.get(item, **self.auth(self.read_key)).json()["id"], pk)
        self.assertEqual(self.client.delete(item, **self.auth(self.write_key)).status_code, 204)
        self.assertEqual(self.client.get(item, **self.auth(self.read_key)).status_code, 404)

    def test_table_must_be_enabled_and_flags_hold(self):
        self.entity.api_enabled = False
        self.entity.save()
        self.assertEqual(self.client.get(self.url, **self.auth(self.read_key)).status_code, 404)
        self.entity.api_enabled, self.entity.allow_delete = True, False
        self.entity.save()
        item = reverse("api_item", args=["inventar", self.entity.slug, Record.objects.first().pk])
        self.assertEqual(self.client.delete(item, **self.auth(self.write_key)).status_code, 403)

    def test_custom_endpoint(self):
        url = reverse("api_custom", args=["inventar", "statistik"])
        self.assertEqual(self.client.get(url, **self.auth(self.read_key)).json()["tabellen"], {"Geräte": 6})
        self.assertEqual(self.client.post(url, "{}", content_type="application/json", **self.auth(self.write_key)).status_code, 405)
        self.assertEqual(self.client.get(reverse("api_custom", args=["inventar", "nix"]), **self.auth(self.read_key)).status_code, 404)

    def test_designer_manages_access_and_keys(self):
        from ..models import ApiKey
        self.client.force_login(self.designer)
        url = reverse("designer_app", args=["inventar"])
        page = self.client.post(url, {"kind": "key", "key-name": "Excel", "key-can_write": "on"})
        key = page.context["new_key"]
        self.assertContains(page, key)
        self.assertEqual(self.client.get(self.url, **self.auth(key)).status_code, 200)
        self.assertNotContains(self.client.get(url), key)   # danach nie wieder im Klartext
        self.client.post(url, {"kind": "api"})              # keine Tabelle angehakt
        self.assertEqual(self.client.get(self.url, **self.auth(key)).status_code, 404)
        self.client.post(reverse("designer_key_delete", args=["inventar", ApiKey.objects.get(name="Excel").pk]))
        self.assertEqual(self.client.get(self.url, **self.auth(key)).status_code, 401)


@override_settings(DEMO_DATASOURCE_FILE=Path(_DEMO_DIR) / "demo-datenquelle.sqlite3")
class ClientLibraryTests(LiveServerTestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(BUILDER_DIR.parent / "clients" / "python"))
        self.addCleanup(sys.path.pop, 0)
        from ..models import ApiKey
        call_command("demo", verbosity=0)
        self.app = App.objects.get(slug="inventar")
        entity = self.app.entities.get(slug="gerate")
        entity.api_enabled = True
        entity.save()
        _obj, self.write_key = ApiKey.issue(self.app, "Test", can_write=True)
        _obj, self.read_key = ApiKey.issue(self.app, "Lesen")

    def test_client_crud(self):
        from baukasten_client import BaukastenError, Client
        bk = Client(self.live_server_url, app="inventar", key=self.write_key)
        geraete = bk.table("gerate")
        self.assertEqual(geraete.count(), 6)
        self.assertEqual(geraete.count(kategorie="IT"), 3)
        self.assertEqual(geraete.count(aktiv=False), 1)
        self.assertEqual(len(list(geraete.iter(page_size=2))), 6)
        self.assertEqual(len(geraete.filter(limit=4)), 4)
        self.assertEqual(geraete.first(bezeichnung="Beamer")["kategorie"], "IT")
        neu = geraete.create(bezeichnung="Kamera", kategorie="IT", preis=499.5)
        self.assertEqual(neu["standort"], "Lager")     # Skript „Standort ergänzen“ läuft auch über die API
        self.assertEqual(geraete.update(neu["id"], standort="Büro")["standort"], "Büro")
        self.assertEqual(geraete.get(neu["id"])["preis"], 499.5)
        self.assertTrue(geraete.delete(neu["id"]))
        self.assertIsNone(geraete.get(neu["id"]))
        with self.assertRaises(BaukastenError) as caught:
            geraete.create(kategorie="Unbekannt")
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("bezeichnung", caught.exception.fields)
        self.assertEqual(bk.call("statistik")["tabellen"]["Geräte"], 6)
        self.assertEqual(bk.describe()["tables"][0]["slug"], "gerate")
        reader = Client(self.live_server_url, app="inventar", key=self.read_key).table("gerate")
        with self.assertRaises(BaukastenError) as denied:
            reader.create(bezeichnung="X", kategorie="IT")
        self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(BaukastenError) as wrong:
            Client(self.live_server_url, app="inventar", key="bk_falsch").table("gerate").count()
        self.assertEqual(wrong.exception.status, 401)


class ApiDocsTests(Base):
    def setUp(self):
        super().setUp()
        self.entity.api_enabled = True
        self.entity.allow_delete = False
        self.entity.save()

    def test_spec_describes_tables_and_flags(self):
        self.client.force_login(self.user)
        spec = self.client.get(reverse("api_docs_spec", args=["inventar"])).json()
        self.assertEqual(spec["openapi"], "3.0.3")
        base = reverse("api_describe", args=["inventar"])
        item = spec["paths"][f"{base}{self.entity.slug}/{{id}}/"]
        self.assertEqual(sorted(k for k in item if k != "parameters"), ["get", "patch", "put"])  # Löschen ist aus
        schema = spec["components"]["schemas"]["GerateEingabe"]
        self.assertEqual(schema["properties"]["kategorie"]["enum"], ["IT", "Messtechnik", "Werkstatt"])
        self.assertEqual(schema["properties"]["anschaffung"]["format"], "date")
        self.assertEqual(sorted(schema["required"]), ["bezeichnung", "kategorie"])
        params = [p["name"] for p in spec["paths"][f"{base}{self.entity.slug}/"]["get"]["parameters"]]
        self.assertIn("standort", params)
        self.assertIn(f"{base}x/statistik/", spec["paths"])

    def test_spec_validates_with_openapi_structure(self):
        """Jede Referenz in der Beschreibung muss auf ein vorhandenes Schema zeigen."""
        self.client.force_login(self.user)
        text = self.client.get(reverse("api_docs_spec", args=["inventar"])).content.decode()
        spec = json.loads(text)
        import re
        for ref in set(re.findall(r'"#/components/schemas/([^"]+)"', text)):
            self.assertIn(ref, spec["components"]["schemas"])

    def test_docs_pages(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("api_docs", args=["inventar"]))
        self.assertContains(page, "Alle Anfragen auf einen Blick")
        self.assertContains(page, "/api/v1/inventar/gerate/{id}/")
        ui = self.client.get(reverse("api_docs_ui", args=["inventar"]))
        self.assertContains(ui, "swagger-ui-bundle.js")
        self.assertContains(ui, "request.loadSpec")  # Beschreibung lädt mit Anmeldung
        self.assertEqual(ui["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(self.client.get(reverse("api_index")), reverse("api_docs", args=["inventar"]))

    def test_access_follows_app_rights(self):
        self.app.published = False
        self.app.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("api_docs_spec", args=["inventar"])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("api_index")), "Inventar")

    def test_spec_with_key(self):
        from ..models import ApiKey
        _obj, key = ApiKey.issue(self.app, "Werkzeug")
        url = reverse("api_openapi", args=["inventar"])
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {key}").json()["info"]["version"], "v1")

    def test_english_spec(self):
        self.client.force_login(self.user)
        spec = self.client.get(reverse("api_docs_spec", args=["inventar"]), HTTP_ACCEPT_LANGUAGE="en").json()
        base = reverse("api_describe", args=["inventar"])
        self.assertEqual(spec["paths"][f"{base}{self.entity.slug}/"]["get"]["summary"], "List entries")


class McpTests(Base):
    """MCP-Server je App (builder/mcp.py): Tools aus den freigeschalteten Tabellen."""

    def setUp(self):
        super().setUp()
        from ..models import ApiKey
        self.entity.api_enabled = True
        self.entity.save()
        _obj, self.read_key = ApiKey.issue(self.app, "Lesen")
        _obj, self.write_key = ApiKey.issue(self.app, "Schreiben", can_write=True)
        self.url = reverse("mcp", args=["inventar"])
        self.slug = self.entity.slug

    def rpc(self, method, params=None, key=None, msg_id=1, **extra):
        body = {"jsonrpc": "2.0", "method": method, **({"id": msg_id} if msg_id is not None else {}),
                **({"params": params} if params is not None else {})}
        return self.client.post(self.url, json.dumps(body), content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {key or self.read_key}", **extra)

    def call(self, name, arguments, key=None):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments}, key=key)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def tool_names(self, key):
        return {t["name"] for t in self.rpc("tools/list", key=key).json()["result"]["tools"]}

    def test_needs_key_of_this_app_and_post(self):
        from ..models import ApiKey
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json").status_code, 401)
        other = App.objects.create(name="Andere", slug="andere")
        _obj, foreign = ApiKey.issue(other, "fremd", can_write=True)
        self.assertEqual(self.rpc("tools/list", key=foreign).status_code, 401)
        get = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {self.read_key}")
        self.assertEqual(get.status_code, 405)
        self.assertEqual(get["Allow"], "POST")
        evil = self.rpc("tools/list", HTTP_ORIGIN="https://boese.example")
        self.assertEqual(evil.status_code, 403)

    def test_initialize_and_notifications(self):
        result = self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                         "clientInfo": {"name": "n8n", "version": "1"}}).json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertEqual(result["serverInfo"]["name"], "baukasten-inventar")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("nur lesen", result["instructions"])
        unknown = self.rpc("initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
        self.assertEqual(unknown["protocolVersion"], "2025-06-18")
        self.assertEqual(self.rpc("notifications/initialized", msg_id=None).status_code, 202)
        self.assertEqual(self.rpc("ping").json()["result"], {})
        self.assertEqual(self.rpc("gibt/es/nicht").json()["error"]["code"], -32601)
        bad = self.client.post(self.url, "kein json", content_type="application/json",
                               HTTP_AUTHORIZATION=f"Bearer {self.read_key}")
        self.assertEqual(bad.json()["error"]["code"], -32700)

    def test_tools_follow_key_and_table_settings(self):
        read = self.tool_names(self.read_key)
        self.assertIn(f"list_{self.slug}", read)
        self.assertIn(f"get_{self.slug}", read)
        self.assertIn("x_statistik", read)  # eigener Endpunkt aus extensions/beispiel.py
        self.assertFalse({n for n in read if n.startswith(("create_", "update_", "delete_"))})
        write = self.tool_names(self.write_key)
        self.assertTrue({f"create_{self.slug}", f"update_{self.slug}", f"delete_{self.slug}"} <= write)
        self.entity.allow_delete = False
        self.entity.save()
        self.assertNotIn(f"delete_{self.slug}", self.tool_names(self.write_key))
        self.entity.api_enabled = False
        self.entity.save()
        self.assertFalse({n for n in self.tool_names(self.write_key) if self.slug in n})

    def test_tool_schemas_describe_fields(self):
        tools = {t["name"]: t for t in self.rpc("tools/list", key=self.write_key).json()["result"]["tools"]}
        create = tools[f"create_{self.slug}"]
        required = list(self.entity.fields.filter(required=True).values_list("key", flat=True))
        self.assertIn("bezeichnung", required)
        self.assertEqual(create["inputSchema"]["required"], required)
        props = create["inputSchema"]["properties"]
        self.assertEqual(props["preis"]["type"], "number")
        self.assertEqual(props["aktiv"]["type"], "boolean")
        self.assertIn("IT", props["kategorie"]["enum"])
        self.assertTrue(tools[f"delete_{self.slug}"]["annotations"]["destructiveHint"])
        self.assertTrue(tools[f"list_{self.slug}"]["annotations"]["readOnlyHint"])

    def test_list_and_get(self):
        result = self.call(f"list_{self.slug}", {"kategorie": "IT", "page_size": 2})["result"]
        self.assertFalse(result["isError"])
        data = result["structuredContent"]
        self.assertEqual(data["count"], self.entity.records.filter(data__kategorie="IT").count())
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(json.loads(result["content"][0]["text"]), data)
        first = data["results"][0]
        one = self.call(f"get_{self.slug}", {"id": first["id"]})["result"]["structuredContent"]
        self.assertEqual(one["bezeichnung"], first["bezeichnung"])
        missing = self.call(f"get_{self.slug}", {"id": 999999})["result"]
        self.assertTrue(missing["isError"])

    def test_write_tools(self):
        created = self.call(f"create_{self.slug}", {"bezeichnung": "Kamera", "kategorie": "IT", "preis": 499.5},
                            key=self.write_key)["result"]
        self.assertFalse(created["isError"])
        pk = created["structuredContent"]["id"]
        self.assertEqual(self.entity.records.get(pk=pk).data["preis"], 499.5)
        invalid = self.call(f"create_{self.slug}", {"kategorie": "IT"}, key=self.write_key)["result"]
        self.assertTrue(invalid["isError"])
        self.assertIn("bezeichnung", invalid["content"][0]["text"])
        self.call(f"update_{self.slug}", {"id": pk, "standort": "Lager"}, key=self.write_key)
        record = self.entity.records.get(pk=pk)
        self.assertEqual((record.data["standort"], record.data["bezeichnung"]), ("Lager", "Kamera"))
        self.assertFalse(self.call(f"delete_{self.slug}", {"id": pk}, key=self.write_key)["result"]["isError"])
        self.assertFalse(self.entity.records.filter(pk=pk).exists())
        # Lese-Schlüssel kennt die schreibenden Tools gar nicht.
        denied = self.call(f"create_{self.slug}", {"bezeichnung": "X"})
        self.assertEqual(denied["error"]["code"], -32602)
        self.assertFalse(self.entity.records.filter(data__bezeichnung="X").exists())

    def test_batch(self):
        body = [{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        response = self.client.post(self.url, json.dumps(body), content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Bearer {self.read_key}")
        self.assertEqual([a["id"] for a in response.json()], [1, 2])


class AiDesignerTests(TestCase):
    """Apps mit einer KI nach Wahl bauen: MCP-Server /mcp/designer/ (builder/mcp_designer.py)."""

    def setUp(self):
        from ..models import DesignerToken
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.other = User.objects.create_user("andere", password="x", is_staff=True)
        _obj, self.key = DesignerToken.issue(self.designer, "Claude")
        self.url = reverse("mcp_designer")

    def rpc(self, method, params=None, key=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return self.client.post(self.url, json.dumps(body), content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {key or self.key}")

    def call(self, name, arguments=None, key=None):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}}, key=key).json()["result"]
        text = result["content"][0]["text"]
        return result.get("isError"), (json.loads(text) if not result.get("isError") else text)

    def test_needs_personal_token_and_designer_right(self):
        from ..models import ApiKey, DesignerToken
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json").status_code, 401)
        app = App.objects.create(name="X")
        _obj, app_key = ApiKey.issue(app, "app", can_write=True)
        self.assertEqual(self.rpc("tools/list", key=app_key).status_code, 401)  # App-Schlüssel gelten hier nicht
        plain = User.objects.create_user("plain", password="x")
        _obj, plain_key = DesignerToken.issue(plain, "x")
        self.assertEqual(self.rpc("tools/list", key=plain_key).status_code, 403)
        info = self.rpc("initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
        self.assertEqual(info["serverInfo"]["name"], "baukasten-designer")
        names = {t["name"] for t in self.rpc("tools/list").json()["result"]["tools"]}
        self.assertEqual(names, {"guide", "list_apps", "get_app", "validate_app", "create_app", "update_app",
                                 "list_versions", "restore_version",
                                 "list_custom_blocks", "save_custom_block", "delete_custom_block"})

    def test_guide_example_is_valid_and_lists_blocks(self):
        error, guide = self.call("guide")
        self.assertFalse(error)
        self.assertIn("table", {b["type"] for b in guide["blocks"]})
        self.assertIn("choice", {f["type"] for f in guide["field_types"]})
        error, result = self.call("validate_app", {"definition": guide["example"]})
        self.assertEqual(result, {"valid": True, "errors": [], "warnings": []})

    def test_create_app_as_safe_draft(self):
        from ..mcp_designer import EXAMPLE
        definition = json.loads(json.dumps(EXAMPLE))
        definition["pages"][0]["public"] = True
        definition["entities"][0]["api_enabled"] = True
        definition["scripts"] = [{"name": "Zählen", "trigger": "page", "code": "print(1)", "enabled": True}]
        error, result = self.call("create_app", {"definition": definition})
        self.assertFalse(error, result)
        app = App.objects.get(slug=result["app"]["slug"])
        self.assertEqual(app.created_by, self.designer)
        self.assertFalse(app.published)
        self.assertFalse(app.pages.filter(public=True).exists())
        self.assertFalse(app.entities.filter(api_enabled=True).exists())
        self.assertFalse(app.scripts.get().enabled)
        self.assertEqual(app.entities.get(slug="ausleihen").fields.get(key="geraet").reference.slug, "geraete")
        self.assertEqual(app.entities.get(slug="geraete").fields.get(key="kategorie").choice_list(),
                         ["Werkzeug", "Messgerät", "IT"])
        self.assertEqual(app.pages.get(slug="uebersicht").layout[1]["props"]["entity"], "geraete")
        self.assertTrue(app.versions.exists())
        # Sie gehört der Person mit dem Schlüssel; andere Designer sehen sie nicht
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("designer_app", args=[app.slug])).status_code, 403)

    def test_errors_name_path_and_fix(self):
        bad = {"name": "Kaputt", "entities": [
            {"name": "A", "fields": [{"label": "X", "type": "string"},
                                     {"label": "Y", "type": "choice"},
                                     {"label": "Z", "type": "reference", "reference": "gibtsnicht"}]}],
            "pages": [{"title": "S", "layout": [{"type": "tabelle"},
                                                 {"type": "table", "props": {"entity": "b"}},
                                                 {"type": "stat", "props": {"entity": "a", "field": "q", "aggregate": "max"}},
                                                 {"type": "heading", "props": {"farbe": "rot"}}]}]}
        error, result = self.call("validate_app", {"definition": bad})
        self.assertFalse(result["valid"])
        text = "\n".join(result["errors"])
        for expected in ("entities[0].fields[0].type", "entities[0].fields[1].choices",
                         "entities[0].fields[2].reference", "pages[0].layout[0].type",
                         "pages[0].layout[1].props.entity", "pages[0].layout[2].props.field",
                         "pages[0].layout[2].props.aggregate"):
            self.assertIn(expected, text)
        self.assertIn("pages[0].layout[3].props.farbe", "\n".join(result["warnings"]))
        error, message = self.call("create_app", {"definition": bad})
        self.assertTrue(error)
        self.assertIn("entities[0].fields[0].type", message)
        self.assertFalse(App.objects.filter(name="Kaputt").exists())

    def test_update_keeps_human_settings_and_can_be_undone(self):
        from ..mcp_designer import EXAMPLE
        _e, created = self.call("create_app", {"definition": EXAMPLE})
        app = App.objects.get(slug=created["app"]["slug"])
        # Ein Mensch gibt frei
        app.pages.filter(slug="uebersicht").update(public=True)
        app.entities.filter(slug="geraete").update(api_enabled=True)
        from ..models import Script
        Script.objects.create(app=app, name="Prüfen", slug="pruefen", trigger="page", code="print(1)", enabled=True)
        _e, current = self.call("get_app", {"app": app.slug})
        geraete = next(e for e in current["entities"] if e["slug"] == "geraete")
        self.assertEqual(geraete["fields"][1]["choices"], ["Werkzeug", "Messgerät", "IT"])
        geraete["fields"].append({"label": "Seriennummer", "type": "text"})
        current["pages"][0]["title"] = "Start"
        current["scripts"].append({"name": "Neu", "trigger": "page", "code": "print(2)"})
        error, result = self.call("update_app", {"app": app.slug, "definition": current})
        self.assertFalse(error, result)
        self.assertTrue(app.entities.get(slug="geraete").fields.filter(key="seriennummer").exists())
        self.assertTrue(app.pages.get(slug="uebersicht").public)
        self.assertTrue(app.entities.get(slug="geraete").api_enabled)
        self.assertTrue(app.scripts.get(slug="pruefen").enabled)   # unverändert: bleibt an
        self.assertFalse(app.scripts.get(slug="neu").enabled)      # neu: aus
        # Nur Seiten mitgeschickt: Tabellen bleiben
        error, result = self.call("update_app", {"app": app.slug, "definition": {"pages": current["pages"]}})
        self.assertFalse(error, result)
        self.assertEqual(app.entities.count(), 2)
        # Rückgängig
        error, undone = self.call("restore_version", {"app": app.slug, "number": result["backup_version"] - 1})
        self.assertFalse(error, undone)
        self.assertFalse(app.entities.get(slug="geraete").fields.filter(key="seriennummer").exists())
        error, listing = self.call("list_versions", {"app": app.slug})
        self.assertGreaterEqual(len(listing["versions"]), 4)

    def test_only_own_apps_and_automations_need_group(self):
        foreign = App.objects.create(name="Fremd", created_by=self.other)
        error, message = self.call("get_app", {"app": foreign.slug})
        self.assertTrue(error)
        _e, listing = self.call("list_apps")
        self.assertNotIn("fremd", [a["slug"] for a in listing["apps"]])
        self.assertFalse(listing["may_create_automations"])
        error, message = self.call("create_app", {"definition": {"name": "Nacht", "kind": "automation"}})
        self.assertTrue(error)
        self.assertIn("Automatisierer", message)
        self.designer.groups.add(Group.objects.get(name="Automatisierer"))
        self.designer = User.objects.get(pk=self.designer.pk)
        error, result = self.call("create_app", {"definition": {
            "name": "Nacht", "kind": "automation",
            "scripts": [{"name": "Takt", "trigger": "schedule", "interval_minutes": 15, "code": "import requests"}]}})
        self.assertFalse(error, result)
        app = App.objects.get(slug=result["app"]["slug"])
        self.assertTrue(app.is_automation)
        self.assertFalse(app.scripts.get().enabled)

    @override_settings(BAUKASTEN_AI_WRITES=2)
    def test_write_limit(self):
        from django.core.cache import cache
        cache.clear()
        for i in range(2):
            error, _result = self.call("create_app", {"definition": {"name": f"A{i}", "entities": []}})
            self.assertFalse(error)
        error, message = self.call("create_app", {"definition": {"name": "A3"}})
        self.assertTrue(error)
        self.assertIn("Zu viele", message)

    def test_profile_issues_shows_once_and_deletes_tokens(self):
        from ..models import DesignerToken
        self.client.force_login(self.designer)
        self.client.post(reverse("profile_ai_token_create"), {"name": "Cursor"})
        page = self.client.get(reverse("profile"))
        new = page.context["new_ai_token"]
        self.assertTrue(new.startswith("bkd_"))
        self.assertContains(page, new)
        self.assertNotContains(self.client.get(reverse("profile")), new)  # nur einmal
        token = DesignerToken.objects.get(name="Cursor")
        self.assertEqual(DesignerToken.find(new), token)
        self.client.force_login(self.other)
        self.client.post(reverse("profile_ai_token_delete", args=[token.pk]))
        self.assertTrue(DesignerToken.objects.filter(pk=token.pk).exists())  # fremde nicht
        self.client.force_login(self.designer)
        self.client.post(reverse("profile_ai_token_delete", args=[token.pk]))
        self.assertFalse(DesignerToken.objects.filter(pk=token.pk).exists())
