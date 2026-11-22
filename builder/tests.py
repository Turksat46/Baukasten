import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import LiveServerTestCase, TestCase, override_settings
from django.urls import reverse

from . import hooks
from .blocks import REGISTRY, clean_layout, make_block
from .management.commands.demo import months_ago
from .models import App, Entity, Field, Page, Record
from .services import HttpNotAllowed, http_request


import tempfile
from pathlib import Path

_DEMO_DIR = tempfile.mkdtemp(prefix="baukasten-test-")


@override_settings(DEMO_DATASOURCE_FILE=Path(_DEMO_DIR) / "demo-datenquelle.sqlite3")
class Base(TestCase):
    def setUp(self):
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.user = User.objects.create_user("nutzer", password="x")
        call_command("demo", verbosity=0)
        self.app = App.objects.get(slug="inventar")
        self.entity = self.app.entities.get()


class RuntimeTests(Base):
    def test_login_required(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_health_ignores_host_check(self):
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="10.1.2.3").content, b"ok")

    def test_pages_render_with_data(self):
        self.client.force_login(self.user)
        overview = self.client.get(reverse("page", args=["inventar"]))
        self.assertContains(overview, "Geräte im Bestand")
        self.assertContains(overview, "10.188,40")  # Summe der Preise, deutsch formatiert
        self.assertContains(overview, "Messtechnik")
        table = self.client.get(reverse("page", args=["inventar", "gerate"]))
        self.assertContains(table, "Oszilloskop")
        year, month, day = months_ago(2, 20).split("-")
        self.assertContains(table, f"{day}.{month}.{year}")
        self.assertContains(table, "3.420,50")

    def test_search_finds_umlauts(self):
        self.client.force_login(self.user)
        page = self.app.pages.get(slug="gerate")
        bid = page.layout[1]["id"]
        self.assertEqual(self.app.home_page.title, "Übersicht")
        response = self.client.get(reverse("page", args=["inventar", "gerate"]), {f"q_{bid}": "büro"})
        self.assertContains(response, "Laptop 14 Zoll")
        self.assertNotContains(response, "Oszilloskop")

    def test_create_edit_delete_record(self):
        self.client.force_login(self.user)
        url = reverse("record_create", args=["inventar", self.entity.slug])
        bad = self.client.post(url, {"bezeichnung": ""})
        self.assertEqual(bad.status_code, 200)  # Pflichtfelder fehlen: Formular erneut
        count = Record.objects.count()
        ok = self.client.post(url, {
            "bezeichnung": "Lötstation", "kategorie": "Werkstatt", "anschaffung": "2026-01-05",
            "preis": "129.5", "aktiv": "on",
        })
        self.assertEqual(ok.status_code, 302)
        record = Record.objects.first()
        self.assertEqual(Record.objects.count(), count + 1)
        self.assertEqual(record.data["preis"], 129.5)
        self.assertEqual(record.data["anschaffung"], "2026-01-05")
        self.assertIs(record.data["aktiv"], True)

        edit = reverse("record_edit", args=["inventar", self.entity.slug, record.pk])
        self.assertContains(self.client.get(edit), "Lötstation")
        self.client.post(edit, {"bezeichnung": "Lötstation 2", "kategorie": "Werkstatt"})
        record.refresh_from_db()
        self.assertEqual(record.data["bezeichnung"], "Lötstation 2")

        self.client.post(reverse("record_delete", args=["inventar", self.entity.slug, record.pk]))
        self.assertEqual(Record.objects.count(), count)

    def test_form_block_posts_with_prefix(self):
        self.client.force_login(self.user)
        page = self.app.pages.get(slug="gerat-erfassen")
        bid = page.layout[1]["id"]
        response = self.client.post(reverse("record_create", args=["inventar", self.entity.slug]), {
            "form_prefix": bid, f"{bid}-bezeichnung": "Stativ", f"{bid}-kategorie": "IT",
            "next": reverse("page", args=["inventar", "gerat-erfassen"]),
        })
        self.assertRedirects(response, reverse("page", args=["inventar", "gerat-erfassen"]))
        self.assertTrue(Record.objects.filter(data__bezeichnung="Stativ").exists())

    def test_entity_flags_are_enforced(self):
        self.client.force_login(self.user)
        self.entity.allow_create = self.entity.allow_delete = False
        self.entity.save()
        record = Record.objects.first()
        self.assertEqual(self.client.get(reverse("record_create", args=["inventar", self.entity.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse("record_delete", args=["inventar", self.entity.slug, record.pk])).status_code, 403)

    def test_access_by_publication_and_group(self):
        self.client.force_login(self.user)
        self.app.published = False
        self.app.save()
        self.assertEqual(self.client.get(reverse("page", args=["inventar"])).status_code, 403)
        self.app.published = True
        self.app.save()
        group = Group.objects.create(name="Labor")
        self.app.groups.add(group)
        self.assertEqual(self.client.get(reverse("page", args=["inventar"])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("home")), "Inventar")
        self.user.groups.add(group)
        self.assertEqual(self.client.get(reverse("page", args=["inventar"])).status_code, 200)

    def test_reference_field(self):
        orte = Entity.objects.create(app=self.app, name="Orte")
        Field.objects.create(entity=orte, label="Name", required=True)
        ort = Record.objects.create(entity=orte, data={"name": "Halle 7"})
        Field.objects.create(entity=self.entity, label="Ort", type=Field.REFERENCE, reference=orte)
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]), {
            "bezeichnung": "Kran", "kategorie": "Werkstatt", "ort": ort.pk,
        })
        self.assertEqual(Record.objects.get(data__bezeichnung="Kran").data["ort"], ort.pk)
        self.assertContains(self.client.get(reverse("page", args=["inventar", "gerate"])), "Halle 7")

    def test_action_hook_and_save_hook(self):
        calls = []
        hooks.SAVE_HOOKS.append((None, None, lambda record, created, user: calls.append(created)))
        self.addCleanup(hooks.SAVE_HOOKS.pop)
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Zange", "kategorie": "Werkstatt"})
        self.assertEqual(calls, [True])
        response = self.client.post(reverse("run_action", args=["inventar", "begruessung"]), follow=True)
        self.assertContains(response, "das kam aus Python")
        self.assertEqual(self.client.post(reverse("run_action", args=["inventar", "gibtsnicht"])).status_code, 403)

    def test_broken_block_does_not_break_page(self):
        page = self.app.pages.get(slug="gerate")
        page.layout.append(make_block("table", entity="geloescht"))
        page.layout.append(make_block("x-uhrzeit"))
        page.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", "gerate"]))
        self.assertContains(response, "keine Tabelle ausgewählt")
        self.assertContains(response, "Aktuelle Uhrzeit")


class BlockTests(Base):
    def test_every_block_type_renders(self):
        """Jeder Baustein muss sich mit Standardwerten und mit Tabelle fehlerfrei anzeigen lassen."""
        layout = []
        for key in REGISTRY:
            layout.append(make_block(key))
            layout.append(make_block(key, entity=self.entity.slug, field="kategorie", page="gerate",
                                     url="/static/builder/logo.svg", target=10))
        page = Page.objects.create(app=self.app, title="Alle", layout=clean_layout(layout))
        self.client.force_login(self.user)
        with self.assertNoLogs("builder.blocks", level="ERROR"):
            response = self.client.get(reverse("page", args=["inventar", page.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "konnte nicht geladen werden")

    def test_overview_blocks_show_computed_values(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar"]))
        self.assertContains(response, "Budget ausgeschöpft")
        self.assertContains(response, "10.188,40 von 15.000")   # Fortschritt: 68 %
        self.assertContains(response, 'aria-valuenow="68"')
        self.assertContains(response, 'stroke-dasharray="50.00 50.00"')  # Kreis: IT = 3 von 6
        self.assertContains(response, "Anschaffungen pro Monat")
        self.assertEqual(response.content.decode().count('class="column-count">1<'), 4)
        self.assertEqual(response.content.decode().count('class="column-count">2<'), 1)

    def test_timeline_without_date_field_uses_created(self):
        page = Page.objects.create(app=self.app, title="V", layout=[make_block("timeline", entity=self.entity.slug)])
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", page.slug]))
        self.assertContains(response, "nach Erfassungsdatum")
        self.assertContains(response, 'class="column-count">6<')

    def test_csv_export(self):
        Record.objects.create(entity=self.entity, data={"bezeichnung": "=SUMME(A1)", "preis": 1.5})
        self.client.force_login(self.user)
        response = self.client.get(reverse("entity_export", args=["inventar", self.entity.slug]))
        text = b"".join(response.streaming_content).decode("utf-8")
        lines = text.splitlines()
        self.assertTrue(text.startswith("\ufeffBezeichnung;Kategorie;Standort;Anschaffung;Preis;Aktiv"))
        self.assertEqual(len(lines), 8)
        self.assertIn("Oszilloskop;Messtechnik;Labor 1;", text)
        self.assertIn("3.420,50;Ja", text)
        self.assertIn("'=SUMME(A1)", text)  # keine Formel für Excel

    def test_export_respects_app_access(self):
        self.client.force_login(self.user)
        self.app.published = False
        self.app.save()
        self.assertEqual(self.client.get(reverse("entity_export", args=["inventar", self.entity.slug])).status_code, 403)


class LoginTests(TestCase):
    def test_login_page_and_local_login(self):
        User.objects.create_user("anna", password="sehr-geheim-1")
        page = self.client.get(reverse("login"))
        self.assertContains(page, "Anmelden")
        self.assertNotContains(page, "Mit Firmenkonto anmelden")
        wrong = self.client.post(reverse("login"), {"username": "anna", "password": "falsch"})
        self.assertContains(wrong, "Benutzername oder Passwort stimmen nicht")
        right = self.client.post(reverse("login"), {"username": "anna", "password": "sehr-geheim-1"})
        self.assertRedirects(right, "/")


@override_settings(OIDC_GROUPS_CLAIM="groups", OIDC_DESIGNER_ROLE="baukasten-designer",
                   OIDC_OP_TOKEN_ENDPOINT="x", OIDC_OP_USER_ENDPOINT="x", OIDC_RP_CLIENT_ID="x",
                   OIDC_RP_CLIENT_SECRET="x", OIDC_RP_SIGN_ALGO="RS256", OIDC_OP_JWKS_ENDPOINT="x")
class KeycloakTests(TestCase):
    """Prüft die Zuordnung der Keycloak-Angaben. Der Login-Ablauf selbst braucht einen echten Keycloak."""

    def backend(self):
        from .auth import KeycloakBackend
        return KeycloakBackend()

    def claims(self, **extra):
        return {"preferred_username": "mmuster", "email": "m@example.com", "given_name": "Max",
                "family_name": "Muster", "groups": ["/Labor", "Einkauf"], **extra}

    def test_user_is_created_with_groups(self):
        backend = self.backend()
        self.assertFalse(backend.filter_users_by_claims(self.claims()).exists())
        user = backend.create_user(self.claims())
        self.assertEqual((user.username, user.first_name, user.email), ("mmuster", "Max", "m@example.com"))
        self.assertFalse(user.has_usable_password())
        self.assertEqual(sorted(g.name for g in user.groups.all()), ["Einkauf", "Labor", "Viewer"])
        self.assertFalse(user.has_perm("builder.design_apps"))

    def test_designer_role_grants_and_revokes(self):
        from .models import can_design
        backend = self.backend()
        user = backend.create_user(self.claims(realm_access={"roles": ["baukasten-designer"]}))
        user = User.objects.get(pk=user.pk)
        self.assertTrue(can_design(user))
        backend.update_user(user, self.claims(groups=["Einkauf"]))
        user = User.objects.get(pk=user.pk)
        self.assertFalse(can_design(user))
        self.assertEqual(sorted(g.name for g in user.groups.all()), ["Einkauf", "Viewer"])

    def test_local_account_is_never_taken_over(self):
        from django.core.exceptions import SuspiciousOperation
        User.objects.create_superuser("mmuster", password="lokal-geheim-1")
        with self.assertRaises(SuspiciousOperation):
            self.backend().filter_users_by_claims(self.claims())

    def test_missing_username_is_rejected(self):
        self.assertFalse(self.backend().verify_claims({"email": "x@example.com"}))


class HttpTests(Base):
    def test_host_must_be_allowed(self):
        with self.assertRaises(HttpNotAllowed):
            http_request("GET", "https://intern.example/api")
        with self.assertRaises(HttpNotAllowed):
            http_request("GET", "file:///etc/passwd")

    @override_settings(BAUKASTEN_HTTP_ALLOWED_HOSTS=["api.example.com"])
    def test_http_block_renders_json_list(self):
        page = Page.objects.create(app=self.app, title="Extern", layout=[
            make_block("http", label="Tickets", url="https://api.example.com/tickets", path="items"),
        ])
        payload = {"items": [{"nr": 1, "titel": "Drucker <defekt>"}, {"nr": 2, "titel": "VPN"}]}
        self.client.force_login(self.user)
        with mock.patch("builder.blocks.http_json", return_value=payload) as fake:
            response = self.client.get(reverse("page", args=["inventar", page.slug]))
        fake.assert_called_once()
        self.assertContains(response, "Drucker &lt;defekt&gt;")
        self.assertContains(response, "VPN")


class DesignerTests(Base):
    def test_designer_needs_permission(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("designer_home")).status_code, 403)

    def test_build_app_from_data_model(self):
        self.client.force_login(self.designer)
        self.client.post(reverse("designer_home"), {"name": "Urlaub", "description": "", "icon": "🌴"})
        app = App.objects.get(slug="urlaub")
        self.assertEqual(app.pages.count(), 1)

        self.client.post(reverse("designer_app", args=["urlaub"]), {"kind": "entity", "entity-name": "Anträge",
                         "entity-allow_create": "on", "entity-allow_edit": "on", "entity-allow_delete": "on"})
        entity = app.entities.get()
        url = reverse("designer_entity", args=["urlaub", entity.pk])
        self.client.post(url, {"kind": "field", "field-label": "Tage", "field-type": "number", "field-show_in_list": "on"})
        bad = self.client.post(url, {"kind": "field", "field-label": "Art", "field-type": "choice"})
        self.assertContains(bad, "mindestens einen Auswahlwert")
        self.assertEqual([f.key for f in entity.fields.all()], ["bezeichnung", "tage"])

        first, second = entity.fields.all()
        self.client.post(reverse("designer_field_move", args=["urlaub", second.pk, "auf"]))
        self.assertEqual([f.key for f in entity.fields.all()], ["tage", "bezeichnung"])

        self.client.post(reverse("designer_entity_page", args=["urlaub", entity.pk]))
        page = app.pages.get(title="Anträge")
        self.assertEqual(page.layout[1]["props"]["entity"], entity.slug)
        for name, args in [("designer_app", ["urlaub"]), ("designer_entity", ["urlaub", entity.pk]),
                           ("designer_field", ["urlaub", first.pk]), ("designer_page", ["urlaub", page.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)

    def test_page_designer_saves_cleaned_layout(self):
        self.client.force_login(self.designer)
        page = self.app.pages.get(slug="gerate")
        url = reverse("designer_page", args=["inventar", page.pk])
        self.assertContains(self.client.get(url), "designer-config")
        layout = [
            {"id": "abc", "type": "heading", "width": 6, "props": {"text": "Hallo", "level": "1", "boese": "<script>"}},
            {"type": "unbekannt", "props": {}},
            {"id": "abc", "type": "table", "width": 99, "props": {"entity": self.entity.slug, "page_size": "abc"}},
        ]
        response = self.client.post(url, json.dumps({"title": "Neu", "show_in_nav": False, "layout": layout}),
                                    content_type="application/json")
        self.assertTrue(response.json()["ok"])
        page.refresh_from_db()
        self.assertEqual((page.title, page.show_in_nav, len(page.layout)), ("Neu", False, 2))
        self.assertNotIn("boese", page.layout[0]["props"])
        self.assertEqual(page.layout[1]["width"], 12)
        self.assertEqual(page.layout[1]["props"]["page_size"], 20)
        self.assertNotEqual(page.layout[0]["id"], page.layout[1]["id"])
        self.assertEqual(self.client.post(url, "kaputt", content_type="application/json").status_code, 400)

    def test_page_designer_optimistic_locking_and_conflict(self):
        import re

        self.client.force_login(self.designer)
        page = self.app.pages.get(slug="gerate")
        url = reverse("designer_page", args=["inventar", page.pk])
        html = self.client.get(url).content.decode()
        match = re.search(r'<script id="designer-config" type="application/json">(.*?)</script>', html)
        self.assertIsNotNone(match)
        cfg = json.loads(match.group(1))
        v1 = cfg["version"]
        self.assertEqual(v1, page.version)

        layout_1 = [{"id": "b1", "type": "heading", "width": 12, "props": {"text": "Erste Fassung", "level": "2"}}]
        res1 = self.client.post(
            url,
            json.dumps({"title": "Geräte v2", "show_in_nav": True, "public": False, "layout": layout_1, "version": v1}),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertTrue(data1["ok"])
        self.assertEqual(data1["version"], v1 + 1)
        page.refresh_from_db()
        self.assertEqual((page.title, page.version), ("Geräte v2", v1 + 1))

        # Zweiter Tab speichert mit veralteter Version v1 -> 409 Conflict, ohne zu überschreiben
        layout_2 = [{"id": "b2", "type": "heading", "width": 12, "props": {"text": "Veraltet", "level": "2"}}]
        res2 = self.client.post(
            url,
            json.dumps({"title": "Überschrieben", "show_in_nav": False, "public": True, "layout": layout_2, "version": v1}),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 409)
        data2 = res2.json()
        self.assertFalse(data2["ok"])
        self.assertTrue(data2["conflict"])
        self.assertEqual(data2["version"], v1 + 1)
        self.assertTrue(data2["error"])
        page.refresh_from_db()
        self.assertEqual(page.title, "Geräte v2")
        self.assertEqual(page.show_in_nav, True)
        self.assertEqual(page.public, False)
        self.assertEqual(page.layout, data1["layout"])
        self.assertEqual(page.version, v1 + 1)

        # Erneutes Speichern mit aktueller Version v1 + 1 funktioniert und erhöht weiter
        res3 = self.client.post(
            url,
            json.dumps({"title": "Geräte v3", "show_in_nav": True, "public": False, "layout": layout_1, "version": v1 + 1}),
            content_type="application/json",
        )
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.json()["version"], v1 + 2)

        # Ungültige Versionsangaben werden mit 400 abgewiesen
        for bad_version in (None, True, "1", 0):
            bad_res = self.client.post(
                url,
                json.dumps({"title": "Ungültig", "layout": layout_1, "version": bad_version}),
                content_type="application/json",
            )
            self.assertEqual(bad_res.status_code, 400)

    def test_page_designer_keyboard_hint_and_save_shortcut(self):
        self.client.force_login(self.designer)
        page = self.app.pages.get(slug="gerate")
        response = self.client.get(reverse("designer_page", args=["inventar", page.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="conflict-note"', html)
        self.assertIn('aria-keyshortcuts="Control+S Meta+S"', html)
        self.assertIn("Alt+Pfeil", html)
        self.assertIn("Entf", html)
        self.assertIn("Strg+S", html)

        js = (Path(__file__).resolve().parent / "static" / "builder" / "designer.js").read_text(encoding="utf-8")
        self.assertIn("e.ctrlKey || e.metaKey", js)
        self.assertIn('e.key.toLowerCase() === "s"', js)
        self.assertIn("e.preventDefault()", js)
        self.assertIn("save()", js)

    def test_live_preview_renders_unsaved_layout(self):
        self.client.force_login(self.designer)
        page = self.app.pages.get(slug="gerate")
        url = reverse("designer_page_preview", args=["inventar", page.pk])
        layout = [{"id": "neu1", "type": "notice", "width": 12, "props": {"text": "Wartung <b>heute</b>", "tone": "warning"}},
                  {"id": "neu2", "type": "stat", "width": 4, "props": {"label": "Anzahl", "entity": self.entity.slug}}]
        data = self.client.post(url, json.dumps({"layout": layout}), content_type="application/json").json()
        self.assertIn("notice-warning", data["blocks"]["neu1"])
        self.assertIn("Wartung &lt;b&gt;heute&lt;/b&gt;", data["blocks"]["neu1"])
        self.assertIn(">6<", data["blocks"]["neu2"])
        page.refresh_from_db()
        self.assertEqual(len(page.layout), 2)  # Vorschau speichert nichts
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, "{}", content_type="application/json").status_code, 403)

    def test_clean_layout_rejects_non_list(self):
        with self.assertRaises(ValueError):
            clean_layout({"a": 1})


class SanitizerTests(TestCase):
    def test_dangerous_markup_is_removed(self):
        from .sanitize import fill_placeholders, sanitize_html
        dirty = ('<div class="card" onclick="x()"><script>alert(1)</script><h3>Titel</h3>'
                 '<a href="javascript:alert(1)">a</a><a href="https://example.com">b</a>'
                 '<img src="//evil.example/x.png" onerror="x()"><iframe src="https://x"></iframe>'
                 '<p style="background:url(https://x)">p</p><p style="color:red">q</p><b>offen')
        clean = sanitize_html(dirty)
        for bad in ("script", "onclick", "onerror", "javascript:", "iframe", "url(", "evil.example", "alert"):
            self.assertNotIn(bad, clean)
        self.assertIn('<div class="card">', clean)
        self.assertIn('<a href="https://example.com" rel="noopener">b</a>', clean)
        self.assertIn('<p style="color:red">q</p>', clean)
        self.assertTrue(clean.endswith("<b>offen</b></div>"))
        filled = fill_placeholders('<p title="{{ t }}">{{ t }} {{ fehlt }}</p>', {"t": '"><script>x</script>'})
        self.assertNotIn("<script>", sanitize_html(filled))
        self.assertIn("&lt;script&gt;", sanitize_html(filled))


class CustomBlockTests(Base):
    def test_html_block_lifecycle(self):
        from .models import CustomBlock
        self.client.force_login(self.designer)
        response = self.client.post(reverse("designer_block_new"), {
            "name": "Wartungshinweis", "description": "Kasten mit Titel",
            "settings": "Titel = Wartung\nText = Heute ab 16 Uhr",
            "html": '<div class="card"><h3>{{ titel }}</h3><p onclick="x()">{{ text }}</p><script>x</script><small>{{ nutzer }}</small></div>',
        })
        block = CustomBlock.objects.get()
        self.assertRedirects(response, reverse("designer_block_edit", args=[block.pk]))
        self.assertNotIn("script", block.html)
        self.assertEqual([s["key"] for s in block.setting_specs()], ["titel", "text"])
        edit = self.client.get(reverse("designer_block_edit", args=[block.pk]))
        self.assertContains(edit, "<h3>Wartung</h3>", html=True)   # Vorschau mit Standardwerten
        self.assertContains(self.client.get(reverse("designer_blocks")), "Wartungshinweis")

        page = self.app.pages.get(slug="gerate")
        config = self.client.get(reverse("designer_page", args=["inventar", page.pk])).context["config"]
        entry = next(b for b in config["blocks"] if b["key"] == f"c-{block.slug}")
        self.assertEqual((entry["category"], [f["key"] for f in entry["fields"]]), ("Eigene", ["titel", "text"]))
        page.layout = clean_layout([{"type": f"c-{block.slug}", "props": {"titel": "Achtung <b>", "text": "Kran gesperrt"}}])
        page.save()
        self.client.force_login(self.user)
        shown = self.client.get(reverse("page", args=["inventar", "gerate"]))
        self.assertContains(shown, "<h3>Achtung &lt;b&gt;</h3>")
        self.assertContains(shown, "<p>Kran gesperrt</p>")
        self.assertContains(shown, "<small>nutzer</small>")

        self.client.force_login(self.designer)
        self.client.post(reverse("designer_block_delete", args=[block.pk]))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("page", args=["inventar", "gerate"])).status_code, 200)

    def test_preset_is_saved_and_offered(self):
        from .models import CustomBlock
        self.client.force_login(self.designer)
        block = make_block("stat", width=4, label="Bestand", entity=self.entity.slug)
        response = self.client.post(reverse("designer_preset_save"), json.dumps({"name": "Bestandszahl", "block": block}),
                                    content_type="application/json")
        self.assertTrue(response.json()["ok"])
        preset = CustomBlock.objects.get(kind="preset")
        self.assertEqual((preset.preset["type"], preset.preset["width"], preset.preset["props"]["label"]), ("stat", 4, "Bestand"))
        page = self.app.pages.first()
        config = self.client.get(reverse("designer_page", args=["inventar", page.pk])).context["config"]
        self.assertEqual(config["presets"][0]["name"], "Bestandszahl")
        bad = self.client.post(reverse("designer_preset_save"), json.dumps({"name": "", "block": block}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("designer_blocks")).status_code, 403)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        from .models import ApiKey
        self.entity.api_enabled = True
        self.entity.save()
        _obj, self.read_key = ApiKey.issue(self.app, "Lesen")
        _obj, self.write_key = ApiKey.issue(self.app, "Schreiben", can_write=True)
        self.url = reverse("api_collection", args=["inventar", self.entity.slug])

    def auth(self, key):
        return {"HTTP_AUTHORIZATION": f"Bearer {key}"}

    def test_requires_key_of_this_app(self):
        from .models import ApiKey
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
        from .models import ApiKey
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


class VersionTests(Base):
    def test_save_change_restore(self):
        from .models import AppVersion
        self.client.force_login(self.designer)
        url = reverse("designer_app", args=["inventar"])
        self.client.post(url, {"kind": "version", "note": "Ausgangsstand"})
        version = AppVersion.objects.get()
        self.assertEqual((version.number, version.note, len(version.snapshot["pages"])), (1, "Ausgangsstand", 4))

        # Umbauen: Seite löschen, Feld löschen, Feld und Tabelle ergänzen, Namen ändern
        self.app.pages.get(slug="gerate").delete()
        self.entity.fields.get(key="standort").delete()
        Field.objects.create(entity=self.entity, label="Seriennummer")
        extra = Entity.objects.create(app=self.app, name="Räume")
        Record.objects.create(entity=extra, data={})
        self.app.name = "Umbenannt"
        self.app.save()

        response = self.client.post(reverse("designer_version_restore", args=["inventar", version.pk]), follow=True)
        self.assertContains(response, "Version 1 wiederhergestellt")
        self.assertContains(response, "Räume")   # Hinweis: Tabelle bleibt wegen ihrer Daten
        self.app.refresh_from_db()
        self.assertEqual(self.app.name, "Inventar")
        self.assertEqual(sorted(p.slug for p in self.app.pages.all()), ["gerat-erfassen", "gerate", "live-daten", "ubersicht"])
        self.assertEqual([f.key for f in self.entity.fields.all()],
                         ["bezeichnung", "kategorie", "standort", "anschaffung", "preis", "aktiv"])
        self.assertEqual(self.entity.records.count(), 6)            # Daten unberührt
        self.assertTrue(self.app.entities.filter(name="Räume").exists())
        self.assertEqual(AppVersion.objects.count(), 2)             # Stand vor der Rückkehr automatisch gesichert
        self.assertTrue(AppVersion.objects.first().automatic)
        self.assertEqual(self.client.get(reverse("page", args=["inventar"])).status_code, 200)

    def test_download_and_import_as_new_app(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import AppVersion
        self.client.force_login(self.designer)
        self.client.post(reverse("designer_app", args=["inventar"]), {"kind": "version"})
        download = self.client.get(reverse("designer_version_download", args=["inventar", AppVersion.objects.get().pk]))
        self.assertIn("inventar-v1.json", download["Content-Disposition"])
        upload = SimpleUploadedFile("app.json", download.content, content_type="application/json")
        response = self.client.post(reverse("designer_app_import"), {"file": upload})
        copy = App.objects.exclude(pk=self.app.pk).get()
        self.assertRedirects(response, reverse("designer_app", args=[copy.slug]))
        self.assertEqual((copy.name, copy.published, copy.pages.count(), copy.entities.get().fields.count()), ("Inventar", False, 4, 6))
        self.assertEqual(sorted(copy.scripts.values_list("slug", flat=True)),
                         ["durchschnitt-berechnen", "live-kennzahlen", "standort-erganzen"])
        self.assertEqual(copy.queries.count(), 2)
        self.assertEqual(copy.scripts.get(slug="live-kennzahlen").page.slug, "live-daten")
        self.assertEqual(copy.entities.get().records.count(), 0)
        self.assertEqual(self.client.get(reverse("page", args=[copy.slug])).status_code, 200)
        broken = SimpleUploadedFile("x.json", b'{"format": "baukasten-app/1", "app": {"name": "X"}}')
        self.assertContains(self.client.post(reverse("designer_app_import"), {"file": broken}, follow=True), "keine gültige App-Datei")
        self.assertEqual(App.objects.count(), 2)   # fehlgeschlagener Import hinterlässt nichts

    def test_delete_app_from_list(self):
        self.client.force_login(self.designer)
        self.assertContains(self.client.get(reverse("designer_home")), reverse("designer_app_delete", args=["inventar"]))
        self.client.post(reverse("designer_app_delete", args=["inventar"]))
        self.assertEqual((App.objects.count(), Record.objects.count()), (0, 0))

    def test_reserved_slugs(self):
        self.assertEqual(App.objects.create(name="Bausteine").slug, "bausteine-app")


class LanguageTests(Base):
    def test_english_interface(self):
        self.client.force_login(self.designer)
        english = {"HTTP_ACCEPT_LANGUAGE": "en"}
        home = self.client.get(reverse("home"), **english)
        self.assertContains(home, "Your apps. Pick one to get started.")
        self.assertContains(home, '<html lang="en">')
        self.assertContains(home, "Welcome to Baukasten")           # Führung
        overview = self.client.get(reverse("page", args=["inventar"]), **english)
        self.assertContains(overview, "10,188.40 of 15,000")          # Zahlen im englischen Format
        self.assertContains(overview, ">total<")
        self.assertContains(overview, '">No</td>')                    # Ja/Nein-Feld
        self.assertNotContains(overview, '">Nein</td>')
        broken = Page.objects.create(app=self.app, title="Leer", layout=[make_block("table")])
        self.assertContains(self.client.get(reverse("page", args=["inventar", broken.slug]), **english),
                            "No table is selected for this list.")
        page = self.app.pages.first()
        config = self.client.get(reverse("designer_page", args=["inventar", page.pk]), **english).context["config"]
        labels = {b["key"]: b["label"] for b in config["blocks"]}
        self.assertEqual((labels["heading"], labels["donut"], config["categories"][0]["label"]), ("Heading", "Donut chart", "Content"))
        self.assertContains(self.client.get(reverse("designer_app", args=["inventar"]), **english), "Save version")
        js = self.client.get(reverse("javascript-catalog"), **english)
        self.assertContains(js, "Save as template")
        self.assertContains(self.client.get(reverse("login"), **english), "Sign in")

    def test_switch_is_remembered(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("home")), "Deine Apps")
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.assertContains(self.client.get(reverse("home")), "Your apps")
        self.client.post(reverse("set_language"), {"language": "de", "next": "/"})
        self.assertContains(self.client.get(reverse("home")), "Deine Apps")


class BrandTests(TestCase):
    def test_logo_slot(self):
        from . import context
        with mock.patch.object(context, "brand_logo", return_value=""):  # unabhängig von einer echten Logodatei
            self.assertNotContains(self.client.get(reverse("login")), "brand-logo")
        with mock.patch.object(context, "brand_logo", return_value="builder/logo.svg"):
            self.assertContains(self.client.get(reverse("login")), 'class="brand-logo"')


# ---------- Skripte ----------

class PythonScriptTests(Base):
    def run_code(self, code, **kwargs):
        from .scripting import python
        return python.run(code, self.app, **kwargs)

    def test_table_access_and_ui(self):
        result = self.run_code(
            't = app.table("gerate")\n'
            'neu = t.create(bezeichnung="Skriptgerät", kategorie="IT", preis=10)\n'
            't.update(neu["id"], standort="Lager")\n'
            'print(t.count(), t.count(kategorie="IT"), round(t.sum("preis"), 2), t.get(neu["id"])["standort"])\n'
            't.delete(neu["id"])\n'
            'ui.set("anzahl", value=t.count(), label="Geräte")\n'
            'message("fertig")\n')
        self.assertTrue(result.ok, result.error_text())
        self.assertEqual(result.log, ["7 4 10198.4 Lager"])
        self.assertEqual(result.ui, {"anzahl": {"value": 6, "label": "Geräte"}})
        self.assertEqual(result.messages, ["fertig"])
        self.assertEqual(Record.objects.filter(entity=self.entity).count(), 6)

    def test_errors_and_limits(self):
        cases = {
            "import os": "nicht verfügbar",
            'open("/etc/passwd")': "open",
            "().__class__": "invalid attribute",
            'x = "{0}".format(1)': "format",
            "x = 1 / 0": "ZeroDivisionError",
            "x = (": "never closed",
            'app.table("gibtsnicht").count()': "gibtsnicht",
            'app.table("gerate").create(kategorie="falsch")': "bezeichnung",
            'http.get_json("https://intern.example/x")': "nicht freigegeben",
            'db.query("lager", "SELECT 1")': "nicht eingerichtet",
            # Grenze im Test klein, damit das Zeitlimit auch bei langsamer Datenbank nicht zuerst greift
            "for i in range(200):\n    app.table(\"gerate\").count()": "Zu viele Zugriffe",
        }
        for code, expected in cases.items():
            with override_settings(BAUKASTEN_SCRIPT_MAX_CALLS=50):
                result = self.run_code(code)
            self.assertFalse(result.ok, code)
            self.assertIn(expected, result.error_text(), code)
        timed = self.run_code("while True:\n    pass", timeout=1.5)
        self.assertIn("Zeitlimit", timed.error_text())
        line = self.run_code("a = 1\nb = 2\nc = a / 0\n")
        self.assertEqual(line.line, 3)

    def test_child_has_no_secrets(self):
        from .scripting.python import _environment
        # Nur Pfad, Kodierung und Zeitzone – keine Umgebungsvariablen mit Zugangsdaten.
        self.assertEqual(set(_environment()) - {"SYSTEMROOT", "TZ"}, {"PATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"})

    def test_page_script_fills_blocks(self):
        from .models import Script
        page = Page.objects.create(app=self.app, title="Skriptseite", layout=[
            {**make_block("output", label="Ergebnis"), "name": "ergebnis"},
            {**make_block("heading", text="Alt"), "name": "kopf"},
            {**make_block("notice", text="x"), "name": "weg"},
            {**make_block("stat", label="Zahl"), "name": "zahl"},
            {**make_block("form", entity=self.entity.slug), "name": "formular"},
        ])
        Script.objects.create(app=self.app, name="Füllen", page=page, code=(
            'ui.set("ergebnis", value=1234.5, rows=[{"a": 1, "b": "<x>"}])\n'
            'ui.set("kopf", text="Neu", subtitle="Unterzeile")\n'
            'ui.hide("weg")\n'
            'ui.set("zahl", value=42)\n'
            'ui.set("formular", values={"standort": "Halle 9"})\n'
            'message("Hallo " + user["name"])\n'))
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", page.slug]))
        content = response.content.decode()
        self.assertIn('<span data-slot="value">1.234,50</span>', content)
        self.assertIn("<td>&lt;x&gt;</td>", content)
        self.assertIn(">Neu</h2>", content)
        self.assertIn(">Unterzeile</p>", content)
        self.assertNotIn("notice-info\" role=\"note\" data-tone>", content.split("script-note")[-1])
        self.assertIn('<span data-slot="value">42</span>', content)
        self.assertIn('value="Halle 9"', content)
        self.assertIn("Hallo nutzer", content)
        self.assertNotIn("bk-runtime", content)   # kein JavaScript nötig

    def test_failing_page_script_is_shown_to_designers_only(self):
        from .models import Script, ScriptRun
        page = self.app.pages.get(slug="gerate")
        Script.objects.create(app=self.app, name="Kaputt", page=page, code="x = 1 / 0")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("page", args=["inventar", "gerate"])), "Kaputt")
        self.client.force_login(self.designer)
        self.assertContains(self.client.get(reverse("page", args=["inventar", "gerate"])), "ZeroDivisionError")
        self.assertEqual(ScriptRun.objects.filter(ok=False).count(), 2)

    def test_button_script(self):
        from .models import Script
        script = Script.objects.create(app=self.app, name="Zählen", trigger=Script.BUTTON,
                                       code='message(str(app.table("gerate").count()) + " Geräte")')
        page = Page.objects.create(app=self.app, title="Knopf", layout=[
            make_block("button", label="Los", target="script", script=script.slug)])
        self.client.force_login(self.user)
        html = self.client.get(reverse("page", args=["inventar", page.slug])).content.decode()
        url = reverse("run_script", args=["inventar", script.slug])
        self.assertIn(url, html)
        response = self.client.post(url, {"next": reverse("page", args=["inventar", page.slug])}, follow=True)
        self.assertContains(response, "6 Geräte")

    def test_on_save_script_changes_record_without_loop(self):
        # Die Beispiel-App ergänzt den Standort, wenn er fehlt.
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Leiter", "kategorie": "Werkstatt"})
        self.assertEqual(Record.objects.get(data__bezeichnung="Leiter").data["standort"], "Lager")
        from .models import Script
        Script.objects.create(app=self.app, name="Schleife", trigger=Script.SAVE, entity=self.entity,
                              code='app.table("gerate").create(bezeichnung="Kopie", kategorie="IT")')
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Start", "kategorie": "IT", "standort": "A"})
        self.assertEqual(Record.objects.filter(data__bezeichnung="Kopie").count(), 1)

    def test_scheduled_script_and_background_command(self):
        from io import StringIO

        from .models import Script
        script = Script.objects.create(app=self.app, name="Nachts", trigger=Script.SCHEDULE, interval_minutes=60,
                                       code='app.table("gerate").create(bezeichnung="Zeitplan", kategorie="IT")')
        out = StringIO()
        call_command("hintergrund", stdout=out)
        call_command("hintergrund", stdout=out)   # Intervall noch nicht abgelaufen
        self.assertEqual(Record.objects.filter(data__bezeichnung="Zeitplan").count(), 1)
        script.refresh_from_db()
        self.assertEqual(script.runs.count(), 1)
        self.assertIn("1 Skripte ausgeführt", out.getvalue())

    def test_designer_editor_and_test_run(self):
        from .models import Script
        self.client.force_login(self.designer)
        new = self.client.get(reverse("designer_script_new", args=["inventar"]) + "?sprache=python")
        self.assertContains(new, 'app.table(&quot;gerate&quot;)')
        response = self.client.post(reverse("designer_script_new", args=["inventar"]), {
            "name": "Test", "language": "python", "trigger": "page", "interval_minutes": 60, "enabled": "on",
            "code": 'print("hallo", app.table("gerate").count())', "action": "test"})
        self.assertContains(response, "hallo 6")
        self.assertContains(response, "erfolgreich")
        bad = self.client.post(reverse("designer_script_new", args=["inventar"]), {
            "name": "JS", "language": "javascript", "trigger": "save", "interval_minutes": 60, "code": ""})
        self.assertContains(bad, "nur beim Öffnen einer Seite oder per Button")
        self.assertEqual(Script.objects.filter(name="JS").count(), 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("designer_script_new", args=["inventar"])).status_code, 403)


class JavaScriptBridgeTests(Base):
    def post(self, op, **args):
        return self.client.post(reverse("script_bridge", args=["inventar"]), json.dumps({"op": op, "args": args}),
                                content_type="application/json")

    def test_bridge_uses_user_rights(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post("table.count", table=self.entity.slug, where={"kategorie": "IT"}).json()["result"], 3)
        created = self.post("table.create", table=self.entity.slug, data={"bezeichnung": "JS", "kategorie": "IT"})
        self.assertEqual(created.status_code, 200)
        self.entity.allow_delete = False
        self.entity.save()
        denied = self.post("table.delete", table=self.entity.slug, id=created.json()["result"]["id"])
        self.assertEqual(denied.status_code, 400)
        self.assertIn("nicht erlaubt", denied.json()["error"])
        self.assertEqual(self.post("os.system", cmd="x").status_code, 400)
        self.app.published = False
        self.app.save()
        self.assertEqual(self.post("table.count", table=self.entity.slug).status_code, 403)

    def test_bridge_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("script_bridge", args=["inventar"]), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_sandbox_page_is_locked_down(self):
        response = self.client.get(reverse("script_sandbox"))
        csp = response["Content-Security-Policy"]
        for part in ("default-src 'none'", "connect-src 'none'", "worker-src blob:"):
            self.assertIn(part, csp)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        nonce = csp.split("'nonce-")[1].split("'")[0]
        self.assertContains(response, f'nonce="{nonce}"')

    def test_page_with_js_script_gets_runtime(self):
        from .models import Script
        page = self.app.pages.get(slug="gerate")
        Script.objects.create(app=self.app, name="Im Browser", language=Script.JAVASCRIPT, page=page,
                              code='ui.set("x", {value: 1});')
        self.client.force_login(self.user)
        content = self.client.get(reverse("page", args=["inventar", "gerate"])).content.decode()
        self.assertIn('id="bk-runtime"', content)
        self.assertIn('ui.set(\\"x\\", {value: 1});', content)


# ---------- Datenquellen ----------

class DataSourceBase(Base):
    """Legt eine kleine SQLite-Datenquelle „lager“ an."""

    def setUp(self):
        super().setUp()
        import sqlite3
        import tempfile
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.addCleanup(lambda: __import__("os").unlink(handle.name))
        conn = sqlite3.connect(handle.name)
        conn.execute("CREATE TABLE teile (nr TEXT, name TEXT, bestand INTEGER, preis REAL, datum TEXT, aktiv BOOLEAN)")
        conn.executemany("INSERT INTO teile VALUES (?, ?, ?, ?, ?, ?)", [
            ("A1", "Schraube", 120, 0.15, "2026-01-02", 1), ("A2", "Mutter", 80, 0.1, "2026-02-03", 1),
            ("B7", "Welle", 4, 31.5, "2026-03-04", 0)])
        conn.commit()
        conn.close()
        self.settings_override = override_settings(BAUKASTEN_DATASOURCES={"lager": f"sqlite:///{handle.name}"})
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)


class DataSourceTests(DataSourceBase):
    def test_read_only_check(self):
        from .datasources import QueryError, check_read_only
        check_read_only("SELECT * FROM teile WHERE name = 'delete' -- update\n")
        check_read_only("with x as (select 1) select * from x;")
        for sql in ("DELETE FROM teile", "SELECT 1; DROP TABLE teile", "WITH x AS (DELETE FROM teile RETURNING *) SELECT * FROM x",
                    "UPDATE teile SET bestand = 0", "PRAGMA table_info(teile)", "", "INSERT INTO teile VALUES (1)"):
            with self.assertRaises(QueryError, msg=sql):
                check_read_only(sql)

    def test_param_conversion(self):
        from .datasources import convert_params
        sql = "SELECT * FROM t WHERE a = :a AND b::text = ':nicht' AND c LIKE '%x' -- :kommentar\nAND d = :d"
        self.assertEqual(convert_params(sql, {"a": 1, "d": 2}, "qmark"),
                         ("SELECT * FROM t WHERE a = ? AND b::text = ':nicht' AND c LIKE '%x' -- :kommentar\nAND d = ?", [1, 2]))
        converted, params = convert_params(sql, {"a": 1, "d": 2}, "pyformat")
        self.assertIn("a = %(a)s", converted)
        self.assertIn("LIKE '%x'", converted)          # in Zeichenketten unverändert
        self.assertNotIn("%%(", converted)
        self.assertEqual(convert_params("SELECT :a", {"a": 1}, "named"), ("SELECT :a", {"a": 1}))

    def test_query_and_script_access(self):
        from . import datasources
        result = datasources.run("lager", "SELECT nr, bestand FROM teile WHERE bestand > :min ORDER BY nr", {"min": 50})
        self.assertEqual(result["rows"], [{"nr": "A1", "bestand": 120}, {"nr": "A2", "bestand": 80}])
        with self.assertRaises(datasources.QueryError):
            datasources.run("lager", "SELECT * FROM gibtsnicht")
        from .scripting import python
        script = python.run('rows = db.query("lager", "SELECT name FROM teile WHERE nr = :nr", {"nr": "B7"})\nprint(rows[0]["name"])', self.app)
        self.assertEqual(script.log, ["Welle"])

    def test_live_block_and_refresh(self):
        from .models import DataQuery
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
        from .models import DataQuery
        query = DataQuery.objects.create(app=self.app, name="Teile", source="lager", sql="SELECT nr, name FROM teile ORDER BY nr")
        page = Page.objects.create(app=self.app, title="Direkt", layout=[make_block("query", query=query.slug)])
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("page", args=["inventar", page.slug])), "<td>Welle</td>")

    def test_sync_into_table(self):
        import sqlite3

        from . import datasources
        from .models import DataQuery
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
        from .models import DataQuery
        query = DataQuery.objects.get(name="Teile")
        synced = self.client.post(reverse("designer_query", args=["inventar", query.pk]), {
            "name": "Teile", "source": "lager", "sql": "SELECT nr, name FROM teile", "cache_seconds": 60,
            "sync_interval": 0, "key_column": "nr", "action": "sync"}, follow=True)
        self.assertContains(synced, "3 Zeilen übernommen")
        self.assertNotContains(self.client.get(reverse("designer_query", args=["inventar", query.pk])), "sqlite:///")


# ---------- Python-Bibliothek ----------

@override_settings(DEMO_DATASOURCE_FILE=Path(_DEMO_DIR) / "demo-datenquelle.sqlite3")
class ClientLibraryTests(LiveServerTestCase):
    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clients" / "python"))
        self.addCleanup(sys.path.pop, 0)
        from .models import ApiKey
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


class DatabricksTests(TestCase):
    """Ohne echten Databricks-Zugang: prüft, wie die Adresse an den Treiber übergeben wird."""

    def test_connection_parameters(self):
        from . import datasources
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
        from . import datasources
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


class TransitionTests(TestCase):
    def test_pages_opt_into_transitions(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, "builder/transitions.js")
        from django.contrib.staticfiles import finders
        css = open(finders.find("builder/style.css"), encoding="utf-8").read()
        self.assertIn("@view-transition { navigation: auto; }", css)
        self.assertIn("prefers-reduced-motion", css)


class DefaultGroupTests(TestCase):
    def test_new_users_join_viewer(self):
        user = User.objects.create_user("neu", password="x")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Viewer"])

    def test_existing_user_joins_on_login(self):
        user = User.objects.create_user("alt", password="sehr-geheim-1")
        user.groups.clear()
        self.client.post(reverse("login"), {"username": "alt", "password": "sehr-geheim-1"})
        self.assertTrue(user.groups.filter(name="Viewer").exists())

    def test_permissions_of_existing_group_are_kept(self):
        from django.contrib.auth.models import Permission
        group = Group.objects.get_or_create(name="Viewer")[0]  # legt die Migration an
        group.permissions.add(Permission.objects.get(codename="view_app"))
        user = User.objects.create_user("mit", password="x")
        self.assertTrue(user.has_perm("builder.view_app"))
        self.assertEqual(Group.objects.filter(name="Viewer").count(), 1)

    @override_settings(DEFAULT_USER_GROUPS=[])
    def test_can_be_switched_off(self):
        self.assertFalse(User.objects.create_user("ohne", password="x").groups.exists())

    @override_settings(OIDC_GROUPS_CLAIM="groups", OIDC_DESIGNER_ROLE="baukasten-designer",
                       OIDC_OP_TOKEN_ENDPOINT="x", OIDC_OP_USER_ENDPOINT="x", OIDC_RP_CLIENT_ID="x",
                       OIDC_RP_CLIENT_SECRET="x", OIDC_RP_SIGN_ALGO="RS256", OIDC_OP_JWKS_ENDPOINT="x")
    def test_keycloak_sync_keeps_viewer(self):
        from .auth import KeycloakBackend
        user = KeycloakBackend().create_user({"preferred_username": "kc", "groups": ["/Labor"]})
        self.assertEqual(sorted(user.groups.values_list("name", flat=True)), ["Labor", "Viewer"])

    def test_app_restricted_to_viewer_is_open_to_everyone(self):
        app = App.objects.create(name="Für alle", published=True)
        app.groups.add(Group.objects.get_or_create(name="Viewer")[0])
        user = User.objects.create_user("jeder", password="x")
        self.assertTrue(app.user_can_use(user))


class ProfileTests(Base):
    def test_profile_shows_own_things(self):
        from .models import ApiKey, Script
        own, _key = ApiKey.issue(self.app, "Mein Export", user=self.designer)
        ApiKey.issue(self.app, "Fremd", user=self.user)
        Script.objects.create(app=self.app, name="Mein Skript", code="1/0", created_by=self.designer)
        self.client.force_login(self.designer)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "Mein Export")
        self.assertNotContains(page, "Fremd")
        self.assertContains(page, "Mein Skript")
        self.assertContains(page, "Viewer")
        self.assertContains(page, reverse("api_docs", args=["inventar"]))

    def test_only_own_keys_can_be_deleted(self):
        from .models import ApiKey
        mine, _k = ApiKey.issue(self.app, "meins", user=self.user)
        theirs, _k = ApiKey.issue(self.app, "fremd", user=self.designer)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("profile_key_delete", args=[theirs.pk])).status_code, 404)
        self.client.post(reverse("profile_key_delete", args=[mine.pk]))
        self.assertEqual(list(ApiKey.objects.values_list("name", flat=True)), ["fremd"])

    def test_simple_user_profile(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("profile"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Meine API-Schlüssel")
        self.assertContains(page, "Passwort ändern")
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)


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
        from .models import ApiKey
        _obj, key = ApiKey.issue(self.app, "Werkzeug")
        url = reverse("api_openapi", args=["inventar"])
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {key}").json()["info"]["version"], "v1")

    def test_english_spec(self):
        self.client.force_login(self.user)
        spec = self.client.get(reverse("api_docs_spec", args=["inventar"]), HTTP_ACCEPT_LANGUAGE="en").json()
        base = reverse("api_describe", args=["inventar"])
        self.assertEqual(spec["paths"][f"{base}{self.entity.slug}/"]["get"]["summary"], "List entries")


class AdminTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("chef", password="x")
        self.client.force_login(self.admin)

    def test_index_lists_apps(self):
        page = self.client.get(reverse("admin:index"))
        self.assertContains(page, "Apps im Baukasten")
        self.assertContains(page, reverse("admin:builder_app_data", args=[self.app.pk]))

    def test_data_view_shows_columns(self):
        page = self.client.get(reverse("admin:builder_app_data", args=[self.app.pk]))
        self.assertContains(page, "<th>Kategorie</th>", html=True)
        self.assertContains(page, "Oszilloskop")
        self.assertContains(page, "3.420,50")

    def test_record_list_filters_by_app_and_searches(self):
        other = App.objects.create(name="Andere")
        table = Entity.objects.create(app=other, name="Dinge")
        Field.objects.create(entity=table, label="Name")
        Record.objects.create(entity=table, data={"name": "Oszilloskop-Kopie"})
        url = reverse("admin:builder_record_changelist")
        everything = self.client.get(url, {"q": "Oszilloskop"})
        self.assertEqual(everything.context["cl"].result_count, 2)
        only_one = self.client.get(url, {"q": "Oszilloskop", "app": other.pk})
        self.assertEqual(only_one.context["cl"].result_count, 1)
        by_table = self.client.get(url, {"app": self.app.pk, "tabelle": self.entity.pk})
        self.assertEqual(by_table.context["cl"].result_count, 6)

    def test_all_admin_pages_open(self):
        from .models import ApiKey, AppVersion, Script
        ApiKey.issue(self.app, "k")
        from .versions import create_version
        create_version(self.app, self.admin)
        record = Record.objects.filter(entity=self.entity).first()
        urls = [reverse("admin:builder_app_change", args=[self.app.pk]),
                reverse("admin:builder_record_change", args=[record.pk])]
        for model in ("app", "entity", "field", "record", "page", "script", "scriptrun", "dataquery", "apikey",
                      "appversion", "customblock"):
            urls.append(reverse(f"admin:builder_{model}_changelist") + f"?app={self.app.pk}" * (model not in ("app", "customblock")))
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(urls[1]), f"<td>{record.data['kategorie']}</td>", html=True)

    def test_record_edit_keeps_umlauts(self):
        record = Record.objects.filter(entity=self.entity, data__bezeichnung="Beamer").first()
        data = dict(record.data, standort="Büro 3")
        self.client.post(reverse("admin:builder_record_change", args=[record.pk]),
                         {"entity": self.entity.pk, "data": json.dumps(data, ensure_ascii=False)})
        record.refresh_from_db()
        self.assertEqual(record.data["standort"], "Büro 3")

    def test_viewer_staff_can_look_but_not_change(self):
        from django.contrib.auth.models import Permission
        viewer = Group.objects.get(name="Viewer")
        viewer.permissions.add(*Permission.objects.filter(codename__in=["view_app", "view_record"]))
        user = User.objects.create_user("schauer", password="x", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:builder_app_data", args=[self.app.pk])).status_code, 200)
        record = Record.objects.filter(entity=self.entity).first()
        page = self.client.get(reverse("admin:builder_app_data", args=[self.app.pk]))
        self.assertNotContains(page, reverse("admin:builder_record_change", args=[record.pk]))


class HelpTests(Base):
    def test_help_renders_handbook(self):
        self.client.force_login(self.designer)
        response = self.client.get("/hilfe/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="schnellstart-deine-erste-app-in-15-minuten"')
        self.assertContains(response, 'href="#häufige-fragen"')
        self.assertContains(response, "<table>")

    def test_help_renders_english_handbook(self):
        self.client.force_login(self.designer)
        response = self.client.get("/hilfe/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, "Where to start")

    def test_help_needs_login(self):
        self.assertEqual(self.client.get("/hilfe/").status_code, 302)


class ThemeTests(Base):
    def test_toggle_on_every_page_and_login(self):
        login = self.client.get("/login/")
        self.assertContains(login, "data-theme-toggle")
        self.assertContains(login, "builder/theme.js")
        self.client.force_login(self.designer)
        for url in ("/", "/profil/", "/hilfe/", "/designer/"):
            self.assertContains(self.client.get(url), "data-theme-toggle", msg_prefix=url)
        self.assertContains(self.client.get("/profil/"), 'data-theme-choice="dark"')



@override_settings(BAUKASTEN_QUERY_PARALLEL=1, BAUKASTEN_QUERY_WAIT=0.3)
class LoadProtectionTests(DataSourceBase):
    """Schutz unter Last: Limit je Quelle, Sperre gegen Mehrfachabfragen, letzter Stand bei Fehlern."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def _query(self, **extra):
        from .models import DataQuery
        return DataQuery.objects.create(app=self.app, name="Teile", source="lager",
                                        sql="SELECT nr, name FROM teile ORDER BY nr", **extra)

    def test_limit_per_source_answers_busy_instead_of_blocking(self):
        import time

        from . import datasources
        with datasources.slot("lager", hold_seconds=30):
            started = time.monotonic()
            with self.assertRaises(datasources.QueryBusy):
                datasources.run("lager", "SELECT 1")
            self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(datasources.run("lager", "SELECT 1 AS x")["rows"], [{"x": 1}])

    @override_settings(BAUKASTEN_QUERY_PARALLEL_BY_SOURCE={"lager": 2})
    def test_limit_per_source_can_be_set_individually(self):
        from . import datasources
        self.assertEqual(datasources.parallel_limit("lager"), 2)
        self.assertEqual(datasources.parallel_limit("andere"), 1)

    def test_identical_query_runs_only_once(self):
        from unittest import mock

        from . import datasources
        query = self._query(cache_seconds=60)
        with mock.patch.object(datasources, "_run", wraps=datasources._run) as spy:
            for _ in range(5):
                datasources.run_saved(query)
        self.assertEqual(spy.call_count, 1)

    def test_running_query_is_not_sent_twice(self):
        from django.core.cache import cache

        from . import datasources
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

        from . import datasources
        query = self._query(cache_seconds=0)
        datasources.run_saved(query)
        with mock.patch.object(datasources, "_run", side_effect=datasources.QueryError("weg")):
            result = datasources.run_saved(query)
        self.assertTrue(result["stale"])
        self.assertEqual(result["rows"][0]["name"], "Schraube")

    def test_busy_block_asks_browser_to_retry(self):
        from unittest import mock

        from . import datasources
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

        from . import datasources
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

        from . import datasources
        query = self._query()
        with mock.patch.object(datasources, "_run", wraps=datasources._run) as spy:
            datasources.sync(query)
        self.assertEqual(spy.call_args.args[4], datasources.sync_timeout())



class MobileTests(Base):
    """Handy: Menü-Knopf in der Kopfzeile, Listen mit Spaltennamen je Zelle (werden zu Karten)."""

    def test_menu_button_and_script(self):
        self.client.force_login(self.designer)
        page = self.client.get(reverse("page", args=["inventar"]))
        self.assertContains(page, 'class="icon-btn menu-toggle"')
        self.assertContains(page, 'aria-controls="topbar-menu"')
        self.assertContains(page, 'id="topbar-menu"')
        self.assertContains(page, "builder/menu.js")

    def test_list_cells_carry_column_label(self):
        self.client.force_login(self.designer)
        content = self.client.get(reverse("page", args=["inventar", "gerate"])).content.decode()
        self.assertIn('<table class="stack">', content)
        self.assertIn('<td data-label="Bezeichnung">', content)

    def test_viewport_meta(self):
        self.assertContains(self.client.get("/login/"), 'name="viewport" content="width=device-width, initial-scale=1"')


class McpTests(Base):
    """MCP-Server je App (builder/mcp.py): Tools aus den freigeschalteten Tabellen."""

    def setUp(self):
        super().setUp()
        from .models import ApiKey
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
        from .models import ApiKey
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


class CollaborationTests(Base):
    """Eigentümerin und Mitbearbeiter je App im Designer."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        self.kollegin = User.objects.create_user("kollegin", password="x")
        self.kollegin.user_permissions.add(Permission.objects.get(codename="design_apps"))
        self.client.force_login(self.designer)
        self.client.post(reverse("designer_home"), {"name": "Urlaub", "description": "", "icon": "🌴"})
        self.urlaub = App.objects.get(slug="urlaub")
        self.client.force_login(self.kollegin)

    def share(self, action, as_user=None, **data):
        self.client.force_login(as_user or self.designer)
        return self.client.post(reverse("designer_app", args=["urlaub"]), {"kind": "share", "action": action, **data})

    def can_open(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("designer_app", args=["urlaub"])).status_code == 200

    def test_creator_is_owner_and_others_are_locked_out(self):
        self.assertEqual(self.urlaub.created_by, self.designer)
        self.assertFalse(self.can_open(self.kollegin))
        self.assertNotContains(self.client.get(reverse("designer_home")), reverse("designer_app", args=["urlaub"]))
        page = self.urlaub.pages.get()
        for url in (reverse("designer_page", args=["urlaub", page.pk]),
                    reverse("designer_script_new", args=["urlaub"]),
                    reverse("designer_query_new", args=["urlaub"])):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("designer_app_delete", args=["urlaub"])).status_code, 403)
        self.assertTrue(App.objects.filter(slug="urlaub").exists())
        # Alte Apps ohne Eigentümerin bleiben für alle Designer offen.
        self.assertIsNone(self.app.created_by)
        self.assertEqual(self.client.get(reverse("designer_app", args=["inventar"])).status_code, 200)

    def test_owner_invites_and_removes_a_designer(self):
        self.share("add_user", username="Kollegin")
        self.assertTrue(self.can_open(self.kollegin))
        self.assertContains(self.client.get(reverse("designer_home")), "Urlaub")
        # Mitbearbeiter dürfen bearbeiten, aber nicht verwalten oder löschen.
        self.assertEqual(self.share("add_user", as_user=self.kollegin, username="designer").status_code, 403)
        self.assertEqual(self.client.post(reverse("designer_app_delete", args=["urlaub"])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("designer_app", args=["urlaub"])),
                               reverse("designer_app_delete", args=["urlaub"]))
        self.assertNotContains(self.client.get(reverse("designer_home")), reverse("designer_app_delete", args=["urlaub"]))
        self.share("remove_user", user=self.kollegin.pk)
        self.assertFalse(self.can_open(self.kollegin))

    def test_only_designers_and_existing_accounts_can_be_invited(self):
        response = self.share("add_user", username="nutzer")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.urlaub.editors.exists())
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertIn("kein Designer-Recht", " ".join(messages))
        self.share("add_user", username="gibt-es-nicht")
        self.assertFalse(self.urlaub.editors.exists())

    def test_group_of_designers(self):
        from django.contrib.auth.models import Group
        team = Group.objects.create(name="Team Personal")
        self.kollegin.groups.add(team)
        self.share("add_group", group=team.pk)
        self.assertTrue(self.can_open(self.kollegin))
        self.share("remove_group", group=team.pk)
        self.assertFalse(self.can_open(self.kollegin))

    def test_claim_ownerless_app(self):
        self.client.force_login(self.kollegin)
        self.client.post(reverse("designer_app", args=["inventar"]), {"kind": "share", "action": "claim"})
        self.app.refresh_from_db()
        self.assertEqual(self.app.created_by, self.kollegin)
        self.client.force_login(self.designer)
        self.assertEqual(self.client.get(reverse("designer_app", args=["inventar"])).status_code, 403)
        # Übernehmen geht nur bei Apps ohne Eigentümerin.
        self.client.force_login(self.kollegin)
        self.assertEqual(self.share("claim", as_user=self.kollegin).status_code, 403)

    def test_superuser_sees_everything(self):
        chef = User.objects.create_superuser("chef", password="x")
        self.assertTrue(self.can_open(chef))
        self.assertEqual(self.share("add_user", as_user=chef, username="kollegin").status_code, 302)
        self.assertTrue(self.urlaub.editors.filter(pk=self.kollegin.pk).exists())

    def test_runtime_access_follows_normal_rules_for_other_designers(self):
        url = reverse("page", args=["urlaub"])
        self.client.force_login(self.kollegin)
        self.assertEqual(self.client.get(url).status_code, 403)  # Entwurf, nicht ihre App
        self.urlaub.published = True
        self.urlaub.save()
        self.assertEqual(self.client.get(url).status_code, 200)


class AppTranslationTests(Base):
    """Übersetzungen der App-Inhalte (builder/app_i18n.py)."""

    EN = {"Inventar": "Inventory", "Geräte": "Devices", "Bezeichnung": "Name",
          "Messtechnik": "Measurement", "Übersicht": "Overview"}

    def setUp(self):
        super().setUp()
        self.app.translations = {"en": dict(self.EN)}
        self.app.save()
        self.client.force_login(self.user)

    def test_collect_finds_texts_of_the_app(self):
        from . import app_i18n
        texts = dict(app_i18n.collect(self.app))
        for text in ("Inventar", "Geräte", "Bezeichnung", "Messtechnik", "Übersicht"):
            self.assertIn(text, texts)
        self.assertIn("Auswahlwert", texts["Messtechnik"])
        heading = next(b for b in self.app.home_page.layout if b["type"] == "heading")
        self.assertIn(heading["props"]["text"], texts)

    def test_pages_show_translation_but_data_stays(self):
        gerate = self.app.pages.get(slug="gerate")
        english = self.client.get(reverse("page", args=["inventar", gerate.slug]), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(english, "Measurement")
        self.assertContains(english, "<th>Name</th>", html=False)
        self.assertContains(english, "Overview")  # Navigation
        self.assertContains(english, "Inventory")
        self.assertNotContains(english, "<th>Bezeichnung</th>")
        german = self.client.get(reverse("page", args=["inventar", gerate.slug]), HTTP_ACCEPT_LANGUAGE="de")
        self.assertContains(german, "Messtechnik")
        self.assertNotContains(german, "Measurement")
        self.assertTrue(self.entity.records.filter(data__kategorie="Messtechnik").exists())
        home = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(home, "Inventory")

    def test_form_translates_labels_and_keeps_choice_values(self):
        response = self.client.get(reverse("record_create", args=["inventar", self.entity.slug]),
                                   HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, '<option value="Messtechnik">Measurement</option>', html=True)
        self.assertContains(response, '<label for="id_bezeichnung">Name:</label>', html=True)

    def test_no_leak_into_other_requests_or_designer(self):
        self.client.get(reverse("page", args=["inventar"]), HTTP_ACCEPT_LANGUAGE="en")
        self.client.force_login(self.designer)
        designer = self.client.get(reverse("designer_entity", args=["inventar", self.entity.pk]),
                                   HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(designer, "Bezeichnung")  # der Designer zeigt immer die Quelltexte

    def test_designer_page_saves_and_merges(self):
        self.client.force_login(self.designer)
        url = reverse("designer_translations", args=["inventar"])
        page = self.client.get(url)
        self.assertContains(page, "Messtechnik")
        self.assertContains(page, 'value="Measurement"')
        missing = self.client.get(url + "?fehlend=1")
        self.assertNotContains(missing, 'value="Messtechnik"')  # schon übersetzt, daher ausgeblendet
        # Nur den einen Text „Standort“ schicken: Die übrigen Übersetzungen bleiben.
        self.client.post(url, {"src_1": "Standort", "tr_en_1": "Location", "src_2": "Geräte", "tr_en_2": ""})
        self.app.refresh_from_db()
        en = self.app.translations["en"]
        self.assertEqual(en["Standort"], "Location")
        self.assertEqual(en["Messtechnik"], "Measurement")
        self.assertNotIn("Geräte", en)  # geleert = gelöscht
        # Unbekannte Texte werden nicht gespeichert.
        self.client.post(url, {"src_1": "Gibt es nicht", "tr_en_1": "Nope"})
        self.app.refresh_from_db()
        self.assertNotIn("Gibt es nicht", self.app.translations["en"])

    def test_csv_roundtrip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.designer)
        csv_text = self.client.get(reverse("designer_translations_export", args=["inventar"])).content.decode("utf-8-sig")
        self.assertTrue(csv_text.startswith("de;ort;en"))
        self.assertIn("Messtechnik;", csv_text)
        edited = csv_text.replace("Standort;Feld in „Geräte“;", "Standort;Feld in „Geräte“;Location")
        self.client.post(reverse("designer_translations", args=["inventar"]),
                         {"kind": "import", "file": SimpleUploadedFile("t.csv", edited.encode("utf-8-sig"))})
        self.app.refresh_from_db()
        self.assertEqual(self.app.translations["en"]["Standort"], "Location")
        self.assertEqual(self.app.translations["en"]["Messtechnik"], "Measurement")  # Rest bleibt

    def test_other_designers_cannot_open_translations(self):
        from django.contrib.auth.models import Permission
        self.app.created_by = self.designer
        self.app.save()
        other = User.objects.create_user("andere", password="x")
        other.user_permissions.add(Permission.objects.get(codename="design_apps"))
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("designer_translations", args=["inventar"])).status_code, 403)

    def test_versions_keep_translations(self):
        from . import versions
        version = versions.create_version(self.app, self.designer, "mit Übersetzung")
        self.app.translations = {}
        self.app.save()
        versions.restore(version, self.designer)
        self.app.refresh_from_db()
        self.assertEqual(self.app.translations["en"]["Geräte"], "Devices")

    def test_scripts_get_language_and_translations(self):
        from django.utils import translation

        from .scripting.python import run
        code = 'print(user["language"], app.t("Geräte"), app.t("unbekannt"))'
        with translation.override("en"):
            result = run(code, self.app, user=self.user)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.log[0], "en Devices unbekannt")
        with translation.override("de"):
            self.assertEqual(run(code, self.app, user=self.user).log[0], "de Geräte unbekannt")


class LineChartTests(Base):
    """Baustein „Liniendiagramm“."""

    def render(self, **props):
        from .blocks import prep_line
        from django.test import RequestFactory
        return prep_line(RequestFactory().get("/"), self.app, make_block("line", entity=self.entity.slug, **props))

    def test_count_by_created_date_per_month(self):
        ctx = self.render()
        self.assertEqual(len(ctx["entries"]), 12)
        # Alle Demo-Einträge sind gerade erst angelegt: Sie zählen im aktuellen Monat.
        self.assertEqual(ctx["entries"][-1]["value"], str(self.entity.records.count()))
        self.assertEqual(ctx["basis"], "Erfassungsdatum")
        self.assertTrue(ctx["line"])
        self.assertFalse(ctx["empty"])

    def test_sum_and_avg_by_date_field(self):
        from datetime import date

        from django.utils.formats import date_format, number_format
        total = sum(r.data["preis"] for r in self.entity.records.all() if r.data.get("anschaffung") == months_ago(1))
        ctx = self.render(date_field="anschaffung", aggregate="sum", field="preis", unit="€")
        month = date_format(date.fromisoformat(months_ago(1)), "F Y")
        entry = next(e for e in ctx["entries"] if e["full"] == month)
        self.assertEqual(entry["value"], number_format(total, decimal_pos=2, use_l10n=True, force_grouping=True))
        self.assertIn("€", entry["title"])
        avg = self.render(date_field="anschaffung", aggregate="avg", field="preis")
        self.assertIn("–", [e["value"] for e in avg["entries"]])  # Monate ohne Einträge haben keinen Durchschnitt

    def test_periods_and_limits(self):
        days = self.render(period="day", count=500)
        self.assertEqual(len(days["entries"]), 90)
        weeks = self.render(period="week", count=8)
        self.assertEqual(len(weeks["entries"]), 8)
        self.assertTrue(weeks["entries"][-1]["full"].startswith("KW"))

    def test_errors_and_page_render(self):
        self.assertIn("Zahlenfeld", self.render(aggregate="sum", field="bezeichnung")["error"])
        page = Page.objects.create(app=self.app, title="Linie", layout=[make_block("line", entity=self.entity.slug)])
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", page.slug]))
        self.assertContains(response, 'class="line-path"')
        self.assertContains(response, "<caption>")


@override_settings(BAUKASTEN_TABLEAU_HOSTS=["tableau.example.com"], BAUKASTEN_TABLEAU_CLIENT_ID="",
                   BAUKASTEN_TABLEAU_SECRET_ID="", BAUKASTEN_TABLEAU_SECRET_VALUE="")
class TableauTests(Base):
    """Baustein „Tableau-Ansicht“ (builder/tableau.py)."""

    URL = "https://tableau.example.com/views/Werke/Uebersicht"

    def render(self, user=None, query="", **props):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from .blocks import prep_tableau
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
        from .blocks import prep_tableau
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

        from . import tableau
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


class TutorialTests(Base):
    """Einführung „Deine erste App“ (builder/tutorial.py): einmal komplett durchspielen."""

    def coach(self):
        return self.client.get(reverse("designer_home")).context["coach"]

    def test_walkthrough_from_start_to_finish(self):
        from .models import Script
        from . import tutorial, versions
        self.client.force_login(self.designer)
        self.assertIsNone(self.coach())
        self.assertContains(self.client.get(reverse("designer_home")), "Einführung starten")
        self.client.post(reverse("tutorial_start"))

        # 1: App anlegen – das Formular ist vorausgefüllt.
        page = self.client.get(reverse("designer_home"))
        self.assertEqual(page.context["coach"]["number"], 1)
        self.assertEqual(page.context["form"].initial, {"name": "Urlaub", "icon": "🌴"})
        self.assertContains(page, 'id="coach"')
        self.client.post(reverse("designer_home"), {"name": "Urlaub", "description": "", "icon": "🌴"})
        app = App.objects.get(slug="urlaub")
        # 2: Tabelle
        self.assertEqual(self.coach()["number"], 2)
        self.client.post(reverse("designer_app", args=["urlaub"]), {
            "kind": "entity", "entity-name": "Anträge", "entity-allow_create": "on", "entity-allow_edit": "on",
            "entity-allow_delete": "on"})
        entity = app.entities.get()
        # 3: Felder
        coach = self.coach()
        self.assertEqual((coach["number"], coach["url"]), (3, reverse("designer_entity", args=["urlaub", entity.pk])))
        Field.objects.create(entity=entity, label="Von", type=Field.DATE, required=True)
        Field.objects.create(entity=entity, label="Bis", type=Field.DATE, required=True)
        Field.objects.create(entity=entity, label="Tage", type=Field.NUMBER)
        Field.objects.create(entity=entity, label="Status", type=Field.CHOICE, choices="offen\ngenehmigt\nabgelehnt")
        # 4: Seite aus der Tabelle
        self.assertEqual(self.coach()["number"], 4)
        self.client.post(reverse("designer_entity_page", args=["urlaub", entity.pk]))
        # 5: zwei Einträge in der App – der Begleiter zeigt auf die Liste
        coach = self.coach()
        self.assertEqual(coach["number"], 5)
        self.assertContains(self.client.get(coach["url"]), 'data-tour="new-record"')
        # 7 vorgezogen: Das Beispielskript rechnet Tage aus und setzt den Status.
        Script.objects.create(app=app, name="Tage", slug="tage", trigger=Script.SAVE, entity=entity,
                              code=tutorial.SCRIPT_EXAMPLE)
        for von, bis in (("2026-08-04", "2026-08-15"), ("2026-12-23", "2026-12-23")):
            self.client.post(reverse("record_create", args=["urlaub", entity.slug]),
                             {"bezeichnung": "Urlaub", "von": von, "bis": bis})
        first = entity.records.order_by("id").first()
        self.assertEqual((first.data["tage"], first.data["status"]), (12, "offen"))
        # 6: Startseite mit Kennzahl und Diagramm (Schritt 7 ist schon erledigt)
        coach = self.coach()
        self.assertEqual(coach["number"], 6)
        self.assertTrue(coach["steps"][6]["done"])
        home = app.home_page
        home.layout = [make_block("stat", entity=entity.slug), make_block("donut", entity=entity.slug, field="status")]
        home.save()
        # 8: veröffentlichen, 9: Version
        self.assertEqual(self.coach()["number"], 8)
        app.published = True
        app.save()
        self.assertEqual(self.coach()["number"], 9)
        versions.create_version(app, self.designer, "erste Fassung")
        coach = self.coach()
        self.assertTrue(coach["finished"])
        self.assertEqual(coach["done_count"], 9)
        self.assertContains(self.client.get(reverse("designer_home")), "Geschafft")
        self.client.post(reverse("tutorial_stop"))
        self.assertIsNone(self.coach())

    def test_only_apps_after_start_count_and_users_without_design_see_nothing(self):
        self.client.force_login(self.designer)
        self.client.post(reverse("tutorial_start"))
        self.assertIsNone(self.coach()["app"])  # die Demo-App von vorher zählt nicht
        self.client.force_login(self.user)
        self.assertIsNone(self.client.get(reverse("home")).context["coach"])
        self.assertEqual(self.client.post(reverse("tutorial_start")).status_code, 403)

    def test_coach_shows_link_or_highlight(self):
        self.client.force_login(self.designer)
        self.client.post(reverse("tutorial_start"))
        self.assertContains(self.client.get(reverse("home")), "Hierhin")
        here = self.client.get(reverse("designer_home"))
        self.assertContains(here, "data-coach-show")
        self.assertContains(here, 'data-target="[data-tour=new-app-form]"')


class HomePageTests(Base):
    def test_home_shows_greeting_tiles_and_quick_links(self):
        self.app.published = True
        self.app.save()
        self.client.force_login(self.user)
        home = self.client.get(reverse("home"))
        self.assertContains(home, "home-hero")
        self.assertRegex(home.content.decode(), r"Guten (Morgen|Tag|Abend), nutzer")
        self.assertContains(home, 'class="tile-icon tone-')
        self.assertContains(home, reverse("help"))
        self.assertNotContains(home, reverse("designer_blocks"))  # nur für Designer
        self.assertNotContains(home, 'id="app-search"')  # Suche erst ab sieben Apps
        for i in range(7):
            App.objects.create(name=f"App {i}", slug=f"app-{i}", published=True)
        self.assertContains(self.client.get(reverse("home")), 'id="app-search"')
        self.client.force_login(self.designer)
        self.assertContains(self.client.get(reverse("home")), reverse("designer_blocks"))


class AdminLinkTests(Base):
    def test_admin_link_only_for_staff(self):
        self.client.force_login(self.designer)  # is_staff
        self.assertContains(self.client.get(reverse("home")), 'href="/admin/"')
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), 'href="/admin/"')


class ConsentExampleTests(Base):
    """Beispiel-App „Aufnahme-Einwilligung“ und die Funktionen, die sie nutzt."""

    def setUp(self):
        super().setUp()
        call_command("beispiel_einwilligung", verbosity=0)
        self.consent = App.objects.get(slug="einwilligung")
        self.events = self.consent.entities.get(slug="veranstaltungen")
        self.answers = self.consent.entities.get(slug="antworten")

    def _create_event(self):
        self.client.force_login(self.designer)
        response = self.client.post(reverse("record_create", args=["einwilligung", "veranstaltungen"]), {
            "titel": "Sommerfest", "datum": "2026-12-04", "ort": "Innenhof", "aufnahmeart": "Foto",
            "zweck": "Newsletter",
        })
        self.assertEqual(response.status_code, 302)
        return self.events.records.order_by("-id").first()

    def test_script_filled_fields_are_not_in_form_and_survive_editing(self):
        event = self._create_event()
        self.assertEqual(event.data["teilnahme_link"], f"/a/einwilligung/p/teilnahme/?event={event.pk}")
        self.assertEqual(event.data["verantwortlich"], "designer")
        form_page = self.client.get(reverse("record_edit", args=["einwilligung", "veranstaltungen", event.pk]))
        self.assertNotContains(form_page, 'name="teilnahme_link"')
        self.client.post(reverse("record_edit", args=["einwilligung", "veranstaltungen", event.pk]), {
            "titel": "Sommerfest 2026", "datum": "2026-12-04", "aufnahmeart": "Foto", "zweck": "Newsletter",
        })
        event.refresh_from_db()
        self.assertEqual(event.data["titel"], "Sommerfest 2026")
        self.assertEqual(event.data["teilnahme_link"], f"/a/einwilligung/p/teilnahme/?event={event.pk}")

    def test_link_fields_are_clickable_but_only_safe_targets(self):
        event = self._create_event()
        page = self.client.get(reverse("page", args=["einwilligung"]))
        self.assertContains(page, f'<a href="/a/einwilligung/p/teilnahme/?event={event.pk}">')
        event.data["teilnahme_link"] = "javascript:alert(1)"
        event.save()
        page = self.client.get(reverse("page", args=["einwilligung"]))
        self.assertNotContains(page, 'href="javascript:')

    def test_participant_agrees_then_changes_mind(self):
        event = self._create_event()
        self.client.force_login(self.user)
        url = f"/a/einwilligung/p/teilnahme/?event={event.pk}"
        page = self.client.get(url)
        self.assertContains(page, "Sommerfest")
        self.assertContains(page, "Du hast noch nicht geantwortet.")
        # Der Button trägt die Parameter der Seite weiter.
        self.assertContains(page, f'action="/a/einwilligung/skript/zustimmen/?event={event.pk}"')
        agree = self.client.post(f"/a/einwilligung/skript/zustimmen/?event={event.pk}", {"next": url})
        self.assertRedirects(agree, url, fetch_redirect_response=False)
        answers = self.answers.records.filter(data__benutzer="nutzer")
        self.assertEqual([a.data["entscheidung"] for a in answers], ["Zustimmung"])
        self.assertEqual(answers[0].data["veranstaltung"], event.pk)
        self.assertContains(self.client.get(url), "zugestimmt")
        self.client.post(f"/a/einwilligung/skript/ablehnen/?event={event.pk}", {"next": url})
        answers = self.answers.records.filter(data__benutzer="nutzer")
        self.assertEqual([a.data["entscheidung"] for a in answers], ["Ablehnung"])

    def test_unknown_event(self):
        self.client.force_login(self.user)
        page = self.client.get("/a/einwilligung/p/teilnahme/?event=999999")
        self.assertContains(page, "Veranstaltung nicht gefunden")
        self.assertNotContains(page, "Ich stimme den Aufnahmen zu")
        self.client.post("/a/einwilligung/skript/zustimmen/?event=999999", {"next": "/"})
        self.assertFalse(self.answers.records.filter(data__benutzer="nutzer").exists())

    def test_answers_cannot_be_created_through_forms(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("record_create", args=["einwilligung", "antworten"]))
        self.assertEqual(response.status_code, 403)

    def test_command_is_idempotent_and_setup_command_creates_admin(self):
        import os
        from unittest import mock
        call_command("beispiel_einwilligung", verbosity=0)
        self.assertEqual(App.objects.filter(slug="einwilligung").count(), 1)
        with mock.patch.dict(os.environ, {"ADMIN_USERNAME": "chefin", "ADMIN_PASSWORD": "geheim-123"}):
            call_command("lokal_einrichten", "--ohne-beispiele", stdout=__import__("io").StringIO())
            call_command("lokal_einrichten", "--ohne-beispiele", stdout=__import__("io").StringIO())
        chefin = User.objects.get(username="chefin")
        self.assertTrue(chefin.is_superuser and chefin.check_password("geheim-123"))


class GuestConsentTests(ConsentExampleTests):
    """Gast-Teilnahme der Aufnahme-Einwilligung: gebaut nur mit Baukasten-Funktionen
    (öffentliche Seite, Eingabefelder, Skript-Buttons, token())."""

    def _guest_url(self, event):
        event.refresh_from_db()
        return event.data["gast_link"]

    def _answer(self, url, script, **data):
        code = url.split("code=", 1)[1]
        return self.client.post(f"/a/einwilligung/skript/{script}/?code={code}", {"next": url, **data})

    def test_guest_page_is_an_ordinary_public_page(self):
        gast = self.consent.pages.get(slug="gast")
        self.assertTrue(gast.public)
        self.assertFalse(gast.show_in_nav)
        self.assertEqual({b["type"] for b in gast.layout} & {"input", "button"}, {"input", "button"})
        self.assertEqual(self.consent.public_reach(), ({"gast-zustimmen", "gast-ablehnen"}, set()))

    def test_new_and_sample_events_get_secret_guest_link(self):
        event = self._create_event()
        code = event.data["gast_code"]
        self.assertGreaterEqual(len(code), 20)
        self.assertEqual(event.data["gast_link"], f"/a/einwilligung/p/gast/?code={code}")
        codes = [r.data["gast_code"] for r in self.events.records.all()]
        self.assertTrue(all(codes))
        self.assertEqual(len(set(codes)), len(codes))
        self.client.post(reverse("record_edit", args=["einwilligung", "veranstaltungen", event.pk]), {
            "titel": "Sommerfest 2026", "datum": "2026-12-04", "aufnahmeart": "Foto", "zweck": "Newsletter",
        })
        event.refresh_from_db()
        self.assertEqual(event.data["gast_code"], code)  # Bearbeiten behält den Code

    def test_guest_agrees_without_login(self):
        event = self._create_event()
        url = self._guest_url(event)
        self.client.logout()
        page = self.client.get(url)
        self.assertContains(page, "Sommerfest")
        self.assertContains(page, "Newsletter")
        self.assertContains(page, 'name="name"')
        self.assertContains(page, "Ich stimme den Aufnahmen zu")
        self.assertNotContains(page, ">Veranstaltungen<")  # keine Navigation zu internen Seiten
        response = self._answer(url, "gast-zustimmen", name="Gisela Gast", email="gisela@example.org")
        self.assertRedirects(response, url, fetch_redirect_response=False)
        answer = self.answers.records.get(data__name="Gisela Gast")
        self.assertEqual((answer.data["veranstaltung"], answer.data["entscheidung"], answer.data["herkunft"]),
                         (event.pk, "Zustimmung", "Gast"))
        self.assertEqual(answer.data["email"], "gisela@example.org")
        self.assertIsNone(answer.data["benutzer"])
        self.assertContains(self.client.get(url), "Deine Zustimmung ist gespeichert")

    def test_guest_declines(self):
        event = self._create_event()
        url = self._guest_url(event)
        self.client.logout()
        self._answer(url, "gast-ablehnen", name="Otto Ohne")
        answer = self.answers.records.get(data__name="Otto Ohne")
        self.assertEqual(answer.data["entscheidung"], "Ablehnung")
        self.assertIsNone(answer.data["email"])

    def test_guest_input_is_checked(self):
        event = self._create_event()
        url = self._guest_url(event)
        self.client.logout()
        before = self.answers.records.count()
        self._answer(url, "gast-zustimmen", name="")
        self._answer(url, "gast-zustimmen", name="Ina", email="kein-mail")
        self.client.post("/a/einwilligung/skript/gast-zustimmen/?code=falsch", {"name": "Ina"})
        self.assertEqual(self.answers.records.count(), before)

    def test_wrong_code_and_internal_pages_stay_closed(self):
        event = self._create_event()
        url = self._guest_url(event)
        self.client.logout()
        wrong = self.client.get("/a/einwilligung/p/gast/?code=falsch")
        self.assertContains(wrong, "Veranstaltung nicht gefunden")
        self.assertNotContains(wrong, "Ich stimme den Aufnahmen zu")
        for blocked in (reverse("page", args=["einwilligung"]), f"/a/einwilligung/p/teilnahme/?event={event.pk}",
                        reverse("page", args=["einwilligung", "antworten"])):
            self.assertEqual(self.client.get(blocked).status_code, 302, blocked)
        # Skripte, die nicht auf einer öffentlichen Seite stehen, bleiben gesperrt.
        self.assertEqual(self.client.post(f"/a/einwilligung/skript/zustimmen/?event={event.pk}").status_code, 302)
        self.consent.published = False
        self.consent.save()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_account_answers_are_marked(self):
        event = self._create_event()
        self.client.force_login(self.user)
        self.client.post(f"/a/einwilligung/skript/zustimmen/?event={event.pk}", {"next": "/"})
        self.assertEqual(self.answers.records.get(data__benutzer="nutzer").data["herkunft"], "Konto")

    def test_guest_sees_answer_after_reload_and_changes_instead_of_duplicating(self):
        event = self._create_event()
        url = self._guest_url(event)
        self.client.logout()
        self.assertNotContains(self.client.get(url), "Du hast zugestimmt")
        self._answer(url, "gast-zustimmen", name="Gisela Gast")
        reloaded = self.client.get(url)
        self.assertContains(reloaded, "Du hast zugestimmt")
        self.assertContains(reloaded, "Gisela Gast")
        self.assertNotContains(reloaded, 'name="name"')  # Name wird nicht noch einmal abgefragt
        self.assertContains(reloaded, "Doch ablehnen")
        # Zweimal klicken legt keine zweite Antwort an.
        self._answer(url, "gast-zustimmen")
        self._answer(url, "gast-ablehnen")
        answers = self.answers.records.filter(data__veranstaltung=event.pk, data__herkunft="Gast")
        self.assertEqual(answers.count(), 1)
        self.assertEqual(answers.get().data["entscheidung"], "Ablehnung")
        self.assertContains(self.client.get(url), "Du hast abgelehnt")
        # Ein anderer Browser (neue Sitzung) ist eine neue Person.
        self.client.cookies.clear()
        self.assertNotContains(self.client.get(url), "Du hast abgelehnt")
        self._answer(url, "gast-zustimmen", name="Zweite Person")
        self.assertEqual(self.answers.records.filter(data__veranstaltung=event.pk, data__herkunft="Gast").count(), 2)

    def test_session_is_per_event(self):
        first, second = self._create_event(), self._create_event()
        url1, url2 = self._guest_url(first), self._guest_url(second)
        self.client.logout()
        self._answer(url1, "gast-zustimmen", name="Gisela Gast")
        self.assertNotContains(self.client.get(url2), "Du hast zugestimmt")
        self._answer(url2, "gast-ablehnen", name="Gisela Gast")
        self.assertEqual(self.answers.records.filter(data__name="Gisela Gast").count(), 2)


class ScriptSessionTests(Base):
    """session in Skripten: Merkzettel je Besucher (Browser) und App."""

    def test_button_and_page_scripts_share_session_per_visitor_and_app(self):
        from .models import Script
        self.app.published = True
        self.app.save()
        Script.objects.create(app=self.app, name="Zählen", slug="zaehlen", trigger=Script.BUTTON,
                              code='session["klicks"] = session.get("klicks", 0) + 1')
        page = Page.objects.create(app=self.app, title="Zähler", slug="zaehler", public=True, layout=[
            {**make_block("output", label="Klicks"), "name": "klicks"},
            make_block("button", label="+1", target="script", script="zaehlen"),
        ])
        Script.objects.create(app=self.app, name="Anzeigen", slug="anzeigen", trigger=Script.PAGE, page=page,
                              code='ui.set("klicks", value=session.get("klicks", 0))')
        url = reverse("page", args=["inventar", "zaehler"])
        for _ in range(3):
            self.client.post("/a/inventar/skript/zaehlen/", {"next": url})
        self.assertContains(self.client.get(url), ">3<")
        self.client.cookies.clear()
        self.assertContains(self.client.get(url), ">0<")

    def test_session_limits(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        from .scripting.triggers import load_session, save_session
        request = RequestFactory().get("/")
        request.session = SessionStore()
        save_session(request, self.app, {"x": "a" * 5000})  # zu groß: wird nicht gespeichert
        self.assertEqual(load_session(request, self.app), {})
        save_session(request, self.app, {"x": 1})
        other = App.objects.create(name="Andere", slug="andere")
        self.assertEqual(load_session(request, self.app), {"x": 1})
        self.assertEqual(load_session(request, other), {})


class PublicPageTests(Base):
    """Öffentliche Seiten als Funktion des Baukastens."""

    def setUp(self):
        super().setUp()
        self.app.published = True
        self.app.save()
        self.form_page = Page.objects.create(app=self.app, title="Anmeldung", slug="anmeldung", public=True, layout=[
            make_block("heading", text="Anmeldung"),
            make_block("form", entity=self.entity.slug),
        ])

    def test_public_page_without_login_but_others_closed(self):
        self.assertEqual(self.client.get(reverse("page", args=["inventar", "anmeldung"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("page", args=["inventar", "gerate"])).status_code, 302)
        self.assertEqual(self.client.get(reverse("page", args=["inventar"])).status_code, 302)
        first = self.entity.records.first().pk
        self.assertEqual(self.client.get(reverse("record_edit", args=["inventar", self.entity.slug, first])).status_code, 302)
        self.assertEqual(self.client.get(reverse("entity_export", args=["inventar", self.entity.slug])).status_code, 302)

    def test_guest_can_submit_form_of_public_page(self):
        bid = self.form_page.layout[1]["id"]
        response = self.client.post(reverse("record_create", args=["inventar", self.entity.slug]), {
            "form_prefix": bid, f"{bid}-bezeichnung": "Gastgerät", f"{bid}-kategorie": "IT",
            "next": reverse("page", args=["inventar", "anmeldung"])})
        self.assertEqual(response.status_code, 302)
        record = self.entity.records.get(data__bezeichnung="Gastgerät")
        self.assertIsNone(record.created_by)

    def test_guest_cannot_use_tables_without_public_form(self):
        self.form_page.public = False
        self.form_page.save()
        Page.objects.create(app=self.app, title="Info", slug="info", public=True, layout=[make_block("text", text="Hallo")])
        response = self.client.post(reverse("record_create", args=["inventar", self.entity.slug]), {"bezeichnung": "X"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
        self.assertFalse(self.entity.records.filter(data__bezeichnung="X").exists())

    def test_logged_in_user_without_app_rights_sees_public_page(self):
        from django.contrib.auth.models import Group
        self.app.groups.add(Group.objects.create(name="Nur Labor"))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("page", args=["inventar", "anmeldung"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("page", args=["inventar", "gerate"])).status_code, 403)

    def test_rate_limit_for_guests(self):
        from django.core.cache import cache
        cache.clear()
        with override_settings(BAUKASTEN_PUBLIC_RATE=2):
            codes = [self.client.get(reverse("page", args=["inventar", "anmeldung"])).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_designer_toggle_and_versions(self):
        from . import versions
        self.client.force_login(self.designer)
        url = reverse("designer_page", args=["inventar", self.form_page.pk])
        self.assertContains(self.client.get(url), 'id="page-public" type="checkbox" checked')
        self.form_page.refresh_from_db()
        self.client.post(url, json.dumps({"title": "Anmeldung", "show_in_nav": True, "public": False,
                                          "layout": self.form_page.layout}), content_type="application/json")
        self.form_page.refresh_from_db()
        self.assertFalse(self.form_page.public)
        self.form_page.public = True
        self.form_page.save()
        version = versions.create_version(self.app, self.designer)
        versions.restore(version, self.designer)
        self.assertTrue(self.app.pages.get(slug="anmeldung").public)

    def test_input_block_values_reach_button_script(self):
        from .models import Script
        Script.objects.create(app=self.app, name="Gruß", slug="gruss", trigger=Script.BUTTON,
                              code='message("Hallo " + params.get("vorname", "?"))')
        Page.objects.create(app=self.app, title="Gruß", slug="gruss", public=True, layout=[
            make_block("input", label="Vorname", param="vorname", required=True),
            make_block("button", label="Grüßen", target="script", script="gruss"),
        ])
        page = self.client.get(reverse("page", args=["inventar", "gruss"]))
        self.assertContains(page, 'name="vorname"')
        self.assertContains(page, "data-page-input")
        self.assertContains(page, "inputs.js")
        response = self.client.post("/a/inventar/skript/gruss/", {"vorname": "Ada", "next": "/a/inventar/p/gruss/"})
        self.assertContains(self.client.get(response["Location"]), "Hallo Ada")
        bad = Page.objects.create(app=self.app, title="Falsch", slug="falsch", public=True,
                                  layout=[make_block("input", label="X", param="next")])
        self.assertContains(self.client.get(reverse("page", args=["inventar", bad.slug])), "braucht einen Namen")

    def test_token_in_scripts(self):
        from .scripting.python import run
        result = run("a = token()\nb = token(32)\nprint(len(a) >= 20, len(b) >= 40, a != b)", self.app)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.log[0], "True True True")


class ScriptTimeTests(TestCase):
    def test_scripts_use_the_configured_time_zone(self):
        from django.utils import timezone

        from .scripting.python import posix_timezone, run
        self.assertTrue(posix_timezone("Europe/Berlin").startswith("CET-1CEST"))
        app = App.objects.create(name="Zeit", slug="zeit")
        result = run('import datetime\nprint(datetime.datetime.now().strftime("%H"))', app)
        self.assertTrue(result.ok, result.error)
        self.assertIn(result.log[0], {timezone.localtime().strftime("%H"),
                                      (timezone.localtime() - __import__("datetime").timedelta(minutes=1)).strftime("%H")})


class AutomationTests(TestCase):
    """Automatisierungen: zweite App-Art mit echtem Python im Hintergrunddienst (scripting/worker.py)."""

    def setUp(self):
        from .models import Script
        self.automator = User.objects.create_user("auto", password="x", is_staff=True)
        self.automator.groups.add(Group.objects.get(name="Automatisierer"))
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.user = User.objects.create_user("nutzer", password="x")
        self.app = App.objects.create(name="Abgleich", kind=App.AUTOMATION, created_by=self.automator)
        self.table = Entity.objects.create(app=self.app, name="Protokoll", slug="protokoll")
        Field.objects.create(entity=self.table, label="Text", key="text")
        self.Script = Script

    def script(self, code, trigger="manual", **extra):
        return self.Script.objects.create(app=self.app, name=extra.pop("name", "Lauf"), trigger=trigger,
                                          code=code, **extra)

    def run_now(self, script, event=None, control=None):
        """Ein Lauf wie im Dienst, aber im Test-Thread."""
        from django.utils import timezone
        from .scripting import automation, worker
        self.Script.objects.filter(pk=script.pk).update(running_since=timezone.now())
        script.refresh_from_db()
        outcome = worker.execute(script, script.trigger, event or {"trigger": "manual"},
                                 control or automation.Control())
        return outcome, script.runs.exclude(status="skipped").first()

    # ---- Rechte und Oberfläche ----

    def test_only_automators_create_and_see_automations(self):
        self.client.force_login(self.designer)
        page = self.client.get(reverse("designer_home"))
        self.assertNotContains(page, 'id="neue-automatisierung"')
        self.assertNotContains(page, 'id="automatisierungen"')
        self.assertNotContains(page, "Abgleich")
        denied = self.client.post(reverse("designer_home"), {"auto-name": "X", "auto-icon": "⚙️"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get(reverse("designer_app", args=["abgleich"])).status_code, 403)
        # Auch als Mitbearbeiter nicht ohne die Gruppe
        self.app.editors.add(self.designer)
        self.assertEqual(self.client.get(reverse("designer_app", args=["abgleich"])).status_code, 403)

        self.client.force_login(self.automator)
        self.assertContains(self.client.get(reverse("designer_home")), 'id="neue-automatisierung"')
        response = self.client.post(reverse("designer_home"), {"auto-name": "Nachtlauf", "auto-icon": "🌙"})
        app = App.objects.get(slug="nachtlauf")
        self.assertRedirects(response, reverse("designer_app", args=["nachtlauf"]))
        self.assertTrue(app.is_automation)
        self.assertFalse(app.pages.exists())
        overview = self.client.get(reverse("designer_app", args=["nachtlauf"]))
        self.assertTemplateUsed(overview, "designer/automation.html")
        # Normale Apps legt dieselbe Seite weiter wie bisher an
        self.client.post(reverse("designer_home"), {"name": "Normal", "icon": "📦"})
        self.assertEqual(App.objects.get(slug="normal").kind, App.APP)

    def test_designer_home_lists_automations_below_apps_with_state(self):
        from django.utils import timezone
        from .models import ScriptRun
        App.objects.create(name="Normale App", created_by=self.automator)
        running = self.script("pass", name="Laeuft")
        broken = self.script("pass", name="Kaputt")
        self.Script.objects.filter(pk=running.pk).update(running_since=timezone.now())
        ScriptRun.objects.create(script=broken, trigger="manual", status="error", ok=False)
        self.client.force_login(self.automator)
        page = self.client.get(reverse("designer_home"))
        self.assertEqual([a.name for a in page.context["apps"]], ["Normale App"])
        summary = page.context["automations"][0]
        self.assertEqual((summary.script_count, summary.running, summary.errors), (2, 1, 1))
        html = page.content.decode()
        self.assertLess(html.index('data-tour="app-list"'), html.index('id="automatisierungen"'))
        self.assertContains(page, "1 läuft")
        self.assertEqual(page.context["tab"], "app")
        # Fehler im Formular der Automatisierung: deren Reiter bleibt offen
        page = self.client.post(reverse("designer_home"), {"auto-name": "", "auto-icon": "⚙️"})
        self.assertEqual(page.context["tab"], "automation")
        self.assertEqual(self.client.get(reverse("designer_home") + "?neu=datei").context["tab"], "datei")

    def test_automation_has_no_runtime_pages(self):
        self.client.force_login(self.automator)
        self.assertEqual(self.client.get(reverse("page", args=["abgleich"])).status_code, 404)
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), "Abgleich")

    def test_invite_requires_automation_group(self):
        self.client.force_login(self.automator)
        self.client.post(reverse("designer_app", args=["abgleich"]),
                         {"kind": "share", "action": "add_user", "username": "designer"})
        self.assertFalse(self.app.editors.exists())

    def test_script_editor_saves_plan_and_starts(self):
        from django.utils import timezone
        self.client.force_login(self.automator)
        new = self.client.get(reverse("designer_script_new", args=["abgleich"]))
        triggers = [value for value, _label in new.context["form"].fields["trigger"].choices]
        self.assertEqual(triggers, ["schedule", "daily", "continuous", "manual"])
        self.assertIn("import requests", new.context["form"].initial["code"])
        response = self.client.post(reverse("designer_script_new", args=["abgleich"]), {
            "name": "Viertelstunde", "trigger": "schedule", "interval_minutes": 15, "timeout_minutes": 20,
            "enabled": "on", "code": "print('hallo')", "action": "save"})
        script = self.app.scripts.get(slug="viertelstunde")
        self.assertRedirects(response, reverse("designer_script", args=["abgleich", script.pk]))
        self.assertEqual(script.language, "python")
        self.assertIsNotNone(script.next_run_at)
        # Zustand des Dienstes wird beim Speichern nicht überschrieben
        self.Script.objects.filter(pk=script.pk).update(running_since=timezone.now())
        self.client.post(reverse("designer_script", args=["abgleich", script.pk]), {
            "name": "Viertelstunde", "trigger": "schedule", "interval_minutes": 15, "timeout_minutes": 20,
            "enabled": "on", "code": "print('neu')", "action": "run"})
        script.refresh_from_db()
        self.assertIsNotNone(script.running_since)
        self.assertEqual(script.code, "print('neu')")
        self.assertTrue(script.run_requested)
        self.assertEqual(script.request_event["trigger"], "manual")
        page = self.client.get(reverse("designer_script", args=["abgleich", script.pk]))
        self.assertContains(page, "Live-Protokoll")
        live = self.client.get(reverse("designer_script_live", args=["abgleich", script.pk])).json()
        self.assertEqual(live["state"], "running")
        status = self.client.get(reverse("designer_automation_status", args=["abgleich"])).json()
        self.assertEqual(status["scripts"][0]["id"], script.pk)
        # Stoppen setzt nur die Bitte, den Rest erledigt der Dienst
        self.client.post(reverse("designer_script_stop", args=["abgleich", script.pk]))
        script.refresh_from_db()
        self.assertTrue(script.stop_requested)
        self.assertFalse(script.run_requested)

    def test_daily_needs_time_and_timeout_is_limited(self):
        self.client.force_login(self.automator)
        response = self.client.post(reverse("designer_script_new", args=["abgleich"]), {
            "name": "Morgens", "trigger": "daily", "interval_minutes": 60, "timeout_minutes": 99999, "code": "pass"})
        form = response.context["form"]
        self.assertIn("daily_time", form.errors)
        self.assertIn("timeout_minutes", form.errors)

    def test_normal_app_script_form_rejects_automation_triggers(self):
        from .forms import ScriptForm
        normal = App.objects.create(name="Normal")
        form = ScriptForm({"name": "x", "language": "python", "trigger": "continuous", "interval_minutes": 60,
                           "code": "pass"}, app=normal)
        self.assertFalse(form.is_valid())

    # ---- Zeitpläne ----

    def test_schedule_skips_slots_instead_of_overtaking(self):
        from datetime import datetime, timezone as dt_tz
        from .scripting import schedule
        script = self.script("pass", trigger="schedule", interval_minutes=15)
        due = datetime(2026, 11, 17, 10, 15, tzinfo=dt_tz.utc)
        self.assertEqual(schedule.catch_up(script, due, due.replace(minute=10)), (due, 0))
        nxt, missed = schedule.catch_up(script, due, due.replace(minute=20))
        self.assertEqual((nxt.minute, missed), (30, 1))
        nxt, missed = schedule.catch_up(script, due, due.replace(minute=50))
        self.assertEqual((nxt.hour, nxt.minute, missed), (11, 0, 3))
        # Nach langem Stillstand nichts nachholen
        later = due.replace(hour=18)
        self.assertGreater(schedule.next_after_start(script, due, later), later)

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_daily_weekdays_only(self):
        from datetime import datetime, time
        from django.utils import timezone
        from .scripting import schedule
        script = self.script("pass", trigger="daily", daily_time=time(7, 0), weekdays_only=True)
        friday_evening = timezone.make_aware(datetime(2026, 11, 20, 18, 0))
        nxt = timezone.localtime(schedule.following(script, friday_evening))
        self.assertEqual((nxt.weekday(), nxt.hour), (0, 7))  # Montag 7 Uhr
        self.assertEqual(schedule.describe(script), "werktags um 07:00")

    # ---- Läufe (echte Kindprozesse) ----

    def test_full_python_run_with_libraries_tables_and_live_log(self):
        script = self.script(
            "import requests, dateutil, os, sys, threading\n"
            "print('requests', bool(requests.get))\n"
            "app.table('protokoll').create(text='von ' + event['trigger'])\n"
            "open('datei.txt', 'w').write('ok')\n"
            "print('datei', open('datei.txt').read())\n"
            "print('fehlerkanal', file=sys.stderr)\n"
            "print('daten', event.get('daten'))\n")
        outcome, run = self.run_now(script, {"trigger": "webhook", "daten": {"x": 1}})
        self.assertEqual(outcome.status, "ok", run.log + run.error)
        self.assertEqual(run.status, "ok")
        self.assertIn("requests True", run.log)
        self.assertIn("datei ok", run.log)
        self.assertIn("fehlerkanal", run.log)
        self.assertIn("daten {'x': 1}", run.log)
        self.assertEqual(self.table.records.get().data["text"], "von webhook")
        script.refresh_from_db()
        self.assertIsNone(script.running_since)

    def test_child_sees_no_credentials_but_secrets_on_request(self):
        import os
        script = self.script("import os\nprint('env', os.environ.get('DATABASE_URL'), os.environ.get('SECRET_KEY'))\n"
                             "print('geheim', secret('erp_token'))\n"
                             "try:\n    secret('fehlt')\nexcept ScriptError as e:\n    print('fehlt:', e)\n")
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://geheim", "SECRET_KEY": "s3cr3t",
                                          "SCRIPT_SECRET_ERP_TOKEN": "abc123"}):
            outcome, run = self.run_now(script)
        self.assertEqual(outcome.status, "ok", run.error)
        self.assertIn("env None None", run.log)
        self.assertIn("geheim abc123", run.log)
        self.assertIn("SCRIPT_SECRET_FEHLT", run.log)

    def test_restricted_scripts_cannot_read_secrets(self):
        import os
        from .scripting import python
        normal = App.objects.create(name="Normal")
        with mock.patch.dict(os.environ, {"SCRIPT_SECRET_ERP_TOKEN": "abc123"}):
            result = python.run("print(secret('erp_token'))", normal)
        self.assertFalse(result.ok)
        self.assertIn("secret", result.error)

    def test_error_line_and_traceback(self):
        _outcome, run = self.run_now(self.script("x = 1\nraise ValueError('kaputt')\n"))
        self.assertEqual(run.status, "error")
        self.assertIn("Zeile 2", run.error)
        self.assertIn("ValueError: kaputt", run.error)

    def test_timeout_and_stop(self):
        import threading
        from .scripting import automation
        with mock.patch.object(automation, "timeout_seconds", return_value=1):
            _outcome, run = self.run_now(self.script("import time\ntime.sleep(30)\n", trigger="schedule"))
        self.assertEqual(run.status, "error")
        self.assertIn("Zeitlimit", run.error)

        control = automation.Control()
        threading.Timer(1.0, control.request, args=["stopped"]).start()
        script = self.script("import time\nprint('los')\ntime.sleep(30)\n", name="Stopp")
        _outcome, run = self.run_now(script, control=control)
        self.assertEqual(run.status, "stopped")
        self.assertLess(run.duration_ms, 15000)

    def test_continuous_restarts_with_growing_delay(self):
        from django.utils import timezone
        script = self.script("raise RuntimeError('weg')", trigger="continuous")
        before = timezone.now()
        self.run_now(script)
        script.refresh_from_db()
        self.assertEqual(script.failures, 1)
        self.assertAlmostEqual((script.next_run_at - before).total_seconds(), 10, delta=5)
        self.run_now(script)
        script.refresh_from_db()
        self.assertEqual(script.failures, 2)
        self.assertGreater((script.next_run_at - timezone.now()).total_seconds(), 20)

    def test_finished_run_records_skipped_slots(self):
        from datetime import timedelta
        from django.utils import timezone
        script = self.script("print('fertig')", trigger="schedule", interval_minutes=15)
        self.Script.objects.filter(pk=script.pk).update(next_run_at=timezone.now() - timedelta(minutes=20))
        self.run_now(script)
        script.refresh_from_db()
        self.assertGreater(script.next_run_at, timezone.now())
        self.assertTrue(script.runs.filter(status="skipped", log__contains="2 Termine").exists())

    # ---- Dienst ----

    def worker(self):
        import io as _io
        from .scripting import worker

        class SyncJob(worker.Job):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.thread = mock.Mock(start=self._run, is_alive=lambda: False)

        for patch in (mock.patch.object(worker, "Job", SyncJob), mock.patch.object(worker, "connection")):
            patch.start()
            self.addCleanup(patch.stop)
        return worker.Worker(out=_io.StringIO())

    def test_worker_runs_due_and_requested_scripts_once(self):
        from django.utils import timezone
        from .scripting import worker as worker_module
        w = self.worker()
        timed = self.script("print('takt')", trigger="schedule", interval_minutes=15, name="Takt")
        manual = self.script("print('knopf')", name="Knopf")
        off = self.script("print('nie')", trigger="schedule", enabled=False, name="Aus")
        w.tick()  # plant den ersten Termin (jetzt) und startet ihn
        self.assertEqual(timed.runs.get().status, "ok")
        timed.refresh_from_db()
        self.assertGreater(timed.next_run_at, timezone.now())
        self.assertFalse(manual.runs.exists())
        self.assertFalse(off.runs.exists())
        self.assertTrue(worker_module.request_run(manual, "manual", user="auto"))
        self.assertFalse(worker_module.request_run(manual, "manual", user="auto"))  # wartet schon
        w.tick()
        self.assertEqual(manual.runs.get().trigger, "manual")
        w.tick()
        self.assertEqual(timed.runs.count(), 1)  # nicht doppelt

    def test_worker_never_starts_a_running_script_and_frees_stale_locks(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import ScriptRun
        w = self.worker()
        script = self.script("print('x')")
        now = timezone.now()
        self.Script.objects.filter(pk=script.pk).update(running_since=now, heartbeat_at=now, run_requested=True)
        self.assertEqual(w.tick(), [])
        # Dienst abgestürzt: kein Lebenszeichen mehr -> freigeben, Lauf als abgebrochen vermerken
        ScriptRun.objects.create(script=script, trigger="manual", status="running")
        self.Script.objects.filter(pk=script.pk).update(heartbeat_at=now - timedelta(minutes=5))
        w.tick()
        self.assertEqual(script.runs.filter(status="aborted").count(), 1)
        self.assertEqual(script.runs.filter(status="ok").count(), 1)  # danach regulär gelaufen

    def test_legacy_schedule_ignores_automations(self):
        from .scripting.triggers import run_due
        self.script("print('x')", trigger="schedule")
        self.assertEqual(run_due(), 0)

    # ---- Von außen: Webhook, MCP, Versionen ----

    def test_webhook(self):
        from .models import ApiKey
        script = self.script("pass")
        _obj, write = ApiKey.issue(self.app, "n8n", can_write=True)
        _obj, read = ApiKey.issue(self.app, "lesen")

        def post(slug, key, body='{"auftrag": 42}'):
            return self.client.post(reverse("api_trigger", args=["abgleich", slug]), body,
                                    content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}")

        self.assertEqual(post(script.slug, read).status_code, 403)
        response = post(script.slug, write)
        self.assertEqual(response.status_code, 202, response.content)
        script.refresh_from_db()
        self.assertEqual(script.request_event["daten"], {"auftrag": 42})
        self.assertEqual(script.request_event["trigger"], "webhook")
        self.assertEqual(post(script.slug, write).status_code, 409)
        self.assertEqual(post("gibtsnicht", write).status_code, 404)
        forever = self.script("pass", trigger="continuous", name="Immer")
        self.assertEqual(post(forever.slug, write).status_code, 409)
        describe = self.client.get(reverse("api_describe", args=["abgleich"]), HTTP_AUTHORIZATION=f"Bearer {read}")
        self.assertEqual([s["slug"] for s in describe.json()["scripts"]], [script.slug])

    def test_mcp_tools(self):
        from .models import ApiKey
        script = self.script("pass", name="Export")
        _obj, write = ApiKey.issue(self.app, "agent", can_write=True)
        _obj, read = ApiKey.issue(self.app, "lesen")
        url = reverse("mcp", args=["abgleich"])

        def rpc(method, params, key):
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            return self.client.post(url, json.dumps(body), content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Bearer {key}").json()

        names = {t["name"] for t in rpc("tools/list", {}, read)["result"]["tools"]}
        self.assertIn("automation_status", names)
        self.assertNotIn("start_export", names)
        result = rpc("tools/call", {"name": "start_export", "arguments": {"daten": {"a": 1}}}, write)["result"]
        self.assertFalse(result.get("isError"), result)
        script.refresh_from_db()
        self.assertEqual((script.request_event["trigger"], script.request_event["daten"]), ("mcp", {"a": 1}))
        status = rpc("tools/call", {"name": "automation_status", "arguments": {}}, read)["result"]
        self.assertIn("requested", json.dumps(status))

    def test_versions_keep_kind_and_import_needs_group(self):
        from datetime import time
        from . import versions
        self.script("print(1)", trigger="daily", daily_time=time(6, 30), timeout_minutes=45)
        data = versions.snapshot(self.app)
        self.assertEqual(data["app"]["kind"], "automation")
        with self.assertRaises(versions.InvalidSnapshot):
            versions.import_app(data, self.designer)
        copy = versions.import_app(data, self.automator)
        self.assertTrue(copy.is_automation)
        imported = copy.scripts.get()
        self.assertEqual((imported.daily_time, imported.timeout_minutes), (time(6, 30), 45))
        # In eine normale App passen die Skripte nicht
        normal = App.objects.create(name="Normal")
        with self.assertRaises(versions.InvalidSnapshot):
            versions.apply(normal, data)


class AiDesignerTests(TestCase):
    """Apps mit einer KI nach Wahl bauen: MCP-Server /mcp/designer/ (builder/mcp_designer.py)."""

    def setUp(self):
        from .models import DesignerToken
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
        from .models import ApiKey, DesignerToken
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
        from .mcp_designer import EXAMPLE
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
        from .mcp_designer import EXAMPLE
        _e, created = self.call("create_app", {"definition": EXAMPLE})
        app = App.objects.get(slug=created["app"]["slug"])
        # Ein Mensch gibt frei
        app.pages.filter(slug="uebersicht").update(public=True)
        app.entities.filter(slug="geraete").update(api_enabled=True)
        from .models import Script
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
        from .models import DesignerToken
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


class MetricsTests(TestCase):
    """Überwachung: /metrics im Prometheus-Format (builder/metrics.py)."""

    def test_hidden_without_token_and_needs_bearer(self):
        with override_settings(BAUKASTEN_METRICS_TOKEN=""):
            self.assertEqual(self.client.get("/metrics").status_code, 404)
        with override_settings(BAUKASTEN_METRICS_TOKEN="geheim"):
            self.assertEqual(self.client.get("/metrics").status_code, 401)
            self.assertEqual(self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer falsch").status_code, 401)
            # Antwortet auch ohne bekannten Hostnamen (Prometheus fragt Pods direkt ab)
            ok = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer geheim", HTTP_HOST="10.1.2.3:8000")
            self.assertEqual(ok.status_code, 200)
            self.assertIn("text/plain", ok["Content-Type"])

    @override_settings(BAUKASTEN_METRICS_TOKEN="geheim")
    def test_values(self):
        from django.core.cache import cache
        from django.utils import timezone
        from .models import Script, ScriptRun
        from .scripting.worker import alive
        cache.clear()
        auto = App.objects.create(name="Nacht", kind=App.AUTOMATION)
        script = Script.objects.create(app=auto, name="Lauf", trigger="manual", code="pass",
                                       running_since=timezone.now(), heartbeat_at=timezone.now())
        ScriptRun.objects.create(script=script, trigger="manual", status="error", ok=False)
        get = lambda: self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer geheim").content.decode()
        text = get()
        self.assertIn('baukasten_info{version="', text)
        self.assertIn('baukasten_apps{kind="automation"} 1', text)
        self.assertIn("baukasten_automation_running 1", text)
        self.assertIn('baukasten_script_runs_failed_24h{kind="automation"} 1', text)
        self.assertIn("baukasten_worker_up 0", text)          # noch kein Lebenszeichen
        self.assertIn("baukasten_worker_heartbeat_age_seconds -1", text)
        alive()
        self.assertIn("baukasten_worker_up 1", get())
        self.assertEqual(text.count("# TYPE baukasten_apps gauge"), 1)


class AuditTests(Base):
    """Änderungsprotokoll (builder/audit.py): wer hat wann was geändert, auf welchem Weg."""

    def entries(self, **filters):
        from .models import AuditEntry
        return list(AuditEntry.objects.filter(**filters).order_by("id"))

    def test_records_via_form_with_person_and_changes(self):
        from .models import AuditEntry
        AuditEntry.objects.all().delete()
        self.client.force_login(self.user)
        url = reverse("record_create", args=["inventar", self.entity.slug])
        self.client.post(url, {"bezeichnung": "Lötstation", "kategorie": "Werkstatt"})
        record = Record.objects.get(data__bezeichnung="Lötstation")
        created = self.entries(target_type="record", action="create")[-1]
        self.assertEqual((created.action, created.username, created.via), ("create", "nutzer", "ui"))
        self.assertEqual(created.changes["bezeichnung"], [None, "Lötstation"])
        self.assertEqual(created.scope, self.entity.slug)
        self.client.post(reverse("record_edit", args=["inventar", self.entity.slug, record.pk]),
                         {"bezeichnung": "Lötstation XL", "kategorie": "Werkstatt", "standort": "Lager"})
        updated =self.entries(target_type="record", action="update", via="ui")[-1]
        self.assertEqual(updated.changes, {"bezeichnung": ["Lötstation", "Lötstation XL"]})
        # Speichern ohne Änderung erzeugt keinen Eintrag
        count = len(self.entries(target_type="record", action="update"))
        self.client.post(reverse("record_edit", args=["inventar", self.entity.slug, record.pk]),
                         {"bezeichnung": "Lötstation XL", "kategorie": "Werkstatt", "standort": "Lager"})
        self.assertEqual(len(self.entries(target_type="record", action="update")), count)
        self.client.post(reverse("record_delete", args=["inventar", self.entity.slug, record.pk]))
        deleted = self.entries(target_type="record", action="delete")[-1]
        self.assertEqual(deleted.changes["bezeichnung"], ["Lötstation XL", None])

    def test_api_and_scripts_name_the_actor(self):
        from .models import ApiKey
        self.entity.api_enabled = True
        self.entity.save()
        _obj, key = ApiKey.issue(self.app, "Excel-Abgleich", can_write=True)
        self.client.post(reverse("api_collection", args=["inventar", self.entity.slug]),
                         json.dumps({"bezeichnung": "Beamer", "kategorie": "IT"}), content_type="application/json",
                         HTTP_AUTHORIZATION=f"Bearer {key}")
        entry = self.entries(target_type="record", action="create")[-1]
        self.assertEqual((entry.via, entry.actor, entry.username), ("api", "API-Schlüssel Excel-Abgleich", ""))
        # Das Skript „Standort ergänzen“ der Demo ändert den Eintrag nach dem Speichern:
        # das steht als Skript im Protokoll, ausgelöst von der Person
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Kabel", "kategorie": "IT"})
        by_script = self.entries(target_type="record", action="update")[-1]
        self.assertEqual((by_script.via, by_script.actor, by_script.username),
                         ("script", "Skript Standort ergänzen", "nutzer"))
        self.assertEqual(by_script.changes, {"standort": [None, "Lager"]})

    def test_structure_changes_and_sharing(self):
        self.client.force_login(self.designer)
        field = self.entity.fields.get(key="standort")
        self.client.post(reverse("designer_field", args=["inventar", field.pk]), {
            "label": "Lagerort", "type": "text", "show_in_list": "on", "show_in_form": "on"})
        entry = self.entries(target_type="field")[-1]
        self.assertEqual((entry.action, entry.via, entry.username), ("update", "designer", "designer"))
        self.assertEqual(entry.changes["label"], ["Standort", "Lagerort"])
        page = self.app.pages.first()
        page.layout = page.layout + [make_block("text", text="Neu")]
        page.save()
        self.assertIn("Bausteine", self.entries(target_type="page")[-1].changes["layout"][1])
        self.app.published = False
        self.app.save()
        self.assertEqual(self.entries(target_type="app")[-1].changes["published"], [True, False])
        self.client.post(reverse("designer_app", args=["inventar"]),
                         {"kind": "share", "action": "claim"})
        self.assertIn("übernommen", self.entries(action="share")[-1].note)

    def test_mass_operations_are_summarized(self):
        from . import versions
        from .models import AuditEntry
        version = versions.create_version(self.app, self.designer, "vorher")
        before = AuditEntry.objects.count()
        versions.restore(version, self.designer)
        new = self.entries(id__gt=0)[before:]
        self.assertEqual([(e.action, e.target_type) for e in new], [("restore", "version")])
        # Tabelle löschen: ein Eintrag mit Anzahl, nicht einer je Eintrag
        records = self.entity.records.count()
        before = AuditEntry.objects.count()
        self.entity.delete()
        new = self.entries()[before:]
        self.assertEqual([(e.action, e.target_type) for e in new], [("delete", "entity")])
        self.assertIn(str(records), new[0].note)
        # App löschen: ein Eintrag, Name bleibt erhalten
        before = AuditEntry.objects.count()
        self.app.delete()
        new = self.entries()[before:]
        self.assertEqual([(e.action, e.target_type, e.app_name) for e in new], [("delete", "app", "Inventar")])
        self.assertTrue(AuditEntry.objects.filter(app_name="Inventar", app__isnull=True).exists())

    def test_ai_access_is_named(self):
        from .models import AuditEntry, DesignerToken
        from .mcp_designer import EXAMPLE
        _obj, key = DesignerToken.issue(self.designer, "Claude")
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "create_app", "arguments": {"definition": EXAMPLE}}}
        before = AuditEntry.objects.count()
        self.client.post(reverse("mcp_designer"), json.dumps(body), content_type="application/json",
                         HTTP_AUTHORIZATION=f"Bearer {key}")
        new = self.entries()[before:]
        self.assertEqual([(e.action, e.target_type, e.via, e.actor, e.username) for e in new],
                         [("create", "app", "ki", "KI-Zugang Claude", "designer")])

    def test_protocol_page_csv_and_record_history(self):
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Monitor", "kategorie": "IT"})
        record = Record.objects.get(data__bezeichnung="Monitor")
        self.client.force_login(self.designer)
        page = self.client.get(reverse("designer_audit", args=["inventar"]))
        self.assertContains(page, "Monitor")
        self.assertContains(page, "nutzer")
        only = self.client.get(reverse("designer_audit", args=["inventar"]) + f"?eintrag={record.pk}")
        self.assertEqual({e.target_id for e in only.context["page_obj"]}, {str(record.pk)})
        csv_text = b"".join(self.client.get(reverse("designer_audit", args=["inventar"]) + "?format=csv")
                            .streaming_content).decode("utf-8")
        self.assertIn("Zeit;Person", csv_text)
        self.assertIn("Monitor", csv_text)
        form = self.client.get(reverse("record_edit", args=["inventar", self.entity.slug, record.pk]))
        self.assertContains(form, "Verlauf")
        self.assertContains(self.client.get(reverse("designer_app", args=["inventar"])), 'id="protokoll"')
        # Nutzer ohne Designer-Recht sehen weder Protokoll noch Verlauf
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("record_edit", args=["inventar", self.entity.slug, record.pk])),
                               "Verlauf")
        self.assertEqual(self.client.get(reverse("designer_audit", args=["inventar"])).status_code, 403)

    def test_retention_and_read_only_admin(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import audit
        from .admin import AuditEntryAdmin
        from .models import AuditEntry
        old = audit.log("update", "app", app=self.app, label="alt")
        AuditEntry.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        fresh = audit.log("update", "app", app=self.app, label="neu")
        with override_settings(BAUKASTEN_AUDIT_RETENTION_DAYS=0):
            self.assertEqual(audit.cleanup(), 0)
        with override_settings(BAUKASTEN_AUDIT_RETENTION_DAYS=365):
            self.assertEqual(audit.cleanup(), 1)
        self.assertFalse(AuditEntry.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditEntry.objects.filter(pk=fresh.pk).exists())
        admin_view = AuditEntryAdmin(AuditEntry, None)
        self.assertFalse(admin_view.has_change_permission(None))
        self.assertFalse(admin_view.has_delete_permission(None))

    def test_demo_setup_is_not_logged(self):
        from .models import AuditEntry
        self.assertFalse(AuditEntry.objects.filter(app=self.app).exists())  # Base.setUp ruft demo auf


class FormatUpgradeTests(Base):
    """Alte Versionsdateien einspielen (versions.upgrade) und Datei in bestehende App einspielen."""

    OLD_FILE = {  # so sah eine heruntergeladene Version im Format 1 aus (vor Automatisierungen)
        "format": "baukasten-app/1",
        "app": {"name": "Alt", "description": "", "icon": "📦"},
        "entities": [{"slug": "dinge", "name": "Dinge", "allow_create": True, "allow_edit": True,
                      "allow_delete": True, "api_enabled": False,
                      "fields": [{"key": "name", "label": "Name", "type": "text", "required": True, "choices": "",
                                  "reference": None, "show_in_list": True, "show_in_form": True, "order": 1}]}],
        "pages": [{"slug": "start", "title": "Start", "show_in_nav": True, "order": 1,
                   "layout": [{"id": "b1", "type": "table", "width": 12, "props": {"entity": "dinge"}},
                              {"id": "b2", "type": "gibtsnichtmehr", "width": 12, "props": {}}]}],
        "scripts": [{"slug": "s", "name": "S", "language": "python", "trigger": "page", "page": None,
                     "entity": None, "interval_minutes": 60, "enabled": True, "code": "print(1)"}],
    }

    def test_old_format_is_upgraded_with_notes(self):
        from . import versions
        data, notes = versions.upgrade(self.OLD_FILE)
        self.assertEqual(data["format"], versions.FORMAT)
        self.assertEqual(data["app"]["kind"], "app")
        self.assertEqual(data["scripts"][0]["timeout_minutes"], 30)
        self.assertIn("älteres Format", notes[0])
        self.assertIn("gibtsnichtmehr", notes[1])
        self.assertEqual(self.OLD_FILE["format"], "baukasten-app/1")  # Eingabe bleibt unverändert
        app = versions.import_app(self.OLD_FILE, self.designer)
        self.assertEqual(app.entities.get().fields.get().key, "name")
        self.assertEqual([b["type"] for b in app.pages.get().layout], ["table"])
        self.assertEqual(len(app.import_notes), 2)
        # Neue Dateien tragen Format und Baukasten-Version
        snapshot = versions.snapshot(app)
        self.assertEqual(snapshot["format"], "baukasten-app/2")
        self.assertIn("baukasten_version", snapshot)

    def test_newer_or_foreign_files_are_rejected_clearly(self):
        from . import versions
        with self.assertRaisesMessage(versions.InvalidSnapshot, "neueren Version des Baukastens"):
            versions.upgrade({**self.OLD_FILE, "format": "baukasten-app/99"})
        with self.assertRaisesMessage(versions.InvalidSnapshot, "keine exportierte App"):
            versions.upgrade({"format": "etwas-anderes/1", "app": {}})

    def test_old_stored_version_still_restores(self):
        from .models import AppVersion
        old = AppVersion.objects.create(app=self.app, number=99, snapshot=self.OLD_FILE)
        self.client.force_login(self.designer)
        response = self.client.post(reverse("designer_version_restore", args=["inventar", old.pk]), follow=True)
        self.assertContains(response, "älteres Format")
        self.assertTrue(self.app.entities.filter(slug="dinge").exists())

    def test_upload_into_existing_app(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import AuditEntry
        self.client.force_login(self.designer)
        upload = SimpleUploadedFile("alt.json", json.dumps(self.OLD_FILE).encode(), content_type="application/json")
        before = self.app.versions.count()
        response = self.client.post(reverse("designer_version_upload", args=["inventar"]), {"file": upload}, follow=True)
        self.assertContains(response, "Datei eingespielt")
        self.assertContains(response, "älteres Format")
        self.assertEqual(self.app.versions.count(), before + 1)  # vorher gesichert
        self.assertTrue(self.app.entities.filter(slug="dinge").exists())
        self.assertTrue(self.app.entities.filter(slug=self.entity.slug).exists())  # Tabelle mit Daten bleibt
        entry = AuditEntry.objects.filter(app=self.app, action="restore").latest("id")
        self.assertIn("alt.json", entry.target_label)
        # Automatisierung passt nicht in eine normale App
        auto = {**self.OLD_FILE, "format": "baukasten-app/2", "app": {**self.OLD_FILE["app"], "kind": "automation"},
                "pages": [], "scripts": []}
        upload = SimpleUploadedFile("auto.json", json.dumps(auto).encode(), content_type="application/json")
        response = self.client.post(reverse("designer_version_upload", args=["inventar"]), {"file": upload}, follow=True)
        self.assertContains(response, "enthält eine Automatisierung")
        broken = SimpleUploadedFile("x.json", b"kein json", content_type="application/json")
        response = self.client.post(reverse("designer_version_upload", args=["inventar"]), {"file": broken}, follow=True)
        self.assertContains(response, "keine gültige App-Datei")


class PlatformSettingsTests(TestCase):
    """Fachliche Einstellungen unter /admin/ (builder/platform.py)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = User.objects.create_superuser("chef", password="x")

    @override_settings(BAUKASTEN_PUBLIC_RATE=120)
    def test_database_value_wins_and_takes_effect_without_restart(self):
        from . import platform
        from .models import AuditEntry, PlatformSettings
        self.assertEqual(platform.value("public_rate"), 120)
        PlatformSettings.objects.create(public_rate=5)
        self.assertEqual(platform.value("public_rate"), 5)  # Cache wurde beim Speichern geleert
        settings_row = PlatformSettings.objects.get()
        settings_row.public_rate = None
        settings_row.save()
        self.assertEqual(platform.value("public_rate"), 120)  # leer = Umgebung
        self.assertTrue(AuditEntry.objects.filter(target_type="settings").exists())

    def test_admin_shows_single_record_with_defaults(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:builder_platformsettings_changelist"))
        self.assertRedirects(response, reverse("admin:builder_platformsettings_change", args=[1]))
        page = self.client.get(reverse("admin:builder_platformsettings_change", args=[1]))
        self.assertContains(page, "Standard aus der Umgebung")
        response = self.client.post(reverse("admin:builder_platformsettings_change", args=[1]),
                                    {"script_timeout": "99"})
        self.assertContains(response, "50")  # Obergrenze greift
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:builder_platformsettings_change", args=[1])).status_code, 403)


class AboutTests(TestCase):
    """Über den Baukasten: Version und Release Notes."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("nutzer", password="x")

    def test_version_and_published_notes(self):
        from django.conf import settings
        from .models import ReleaseNote
        ReleaseNote.objects.create(version="9.9.9", title="Geheim", body="noch nicht", published=False)
        ReleaseNote.objects.create(version="9.9.8", title="Sicher", body="<script>alert(1)</script>**fett**",
                                   published=True)
        self.client.force_login(self.user)
        page = self.client.get(reverse("about"))
        self.assertContains(page, settings.BAUKASTEN_VERSION)
        self.assertContains(page, "Sicher")
        self.assertContains(page, "<strong>fett</strong>")
        self.assertNotContains(page, "<script>alert")
        self.assertNotContains(page, "Geheim")
        self.assertContains(page, 'data-news="9.9.8"')  # Fuß: neueste veröffentlichte Version
        boss = User.objects.create_superuser("chef", password="x")
        self.client.force_login(boss)
        self.assertContains(self.client.get(reverse("about")), "Entwurf")

    def test_seeded_notes_and_login_required(self):
        from .models import ReleaseNote
        self.assertTrue(ReleaseNote.objects.filter(version="1.0.0", published=True).exists())
        self.assertTrue(ReleaseNote.objects.filter(version="1.1.0", published=False).exists())
        self.assertEqual(self.client.get(reverse("about")).status_code, 302)


class PwaTests(TestCase):
    """Als App installieren: Manifest, Service Worker, Offline-Seite (builder/pwa.py)."""

    def test_manifest_without_login(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual((data["name"], data["start_url"], data["display"]), ("Baukasten", "/", "standalone"))
        purposes = {(i["sizes"], i["purpose"]) for i in data["icons"]}
        self.assertIn(("512x512", "maskable"), purposes)
        self.assertIn(("192x192", "any"), purposes)
        for icon in data["icons"]:
            self.assertTrue(icon["src"].endswith(".png"))

    def test_service_worker_scope_and_privacy(self):
        from django.conf import settings
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", response["Cache-Control"])
        body = response.content.decode()
        self.assertIn(f'baukasten-{settings.BAUKASTEN_VERSION}', body)
        self.assertIn('"/offline/"', body)
        self.assertIn('request.mode === "navigate"', body)  # Seiten gehen immer ans Netz

    def test_offline_page_is_public_and_personal_data_free(self):
        response = self.client.get("/offline/")
        self.assertContains(response, "Keine Verbindung")
        self.assertNotContains(response, "data-user")

    def test_pages_link_manifest_and_offer_install(self):
        self.assertContains(self.client.get(reverse("login")), 'rel="manifest"')
        user = User.objects.create_user("nutzer", password="x")
        self.client.force_login(user)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "apple-touch-icon")
        self.assertContains(page, "data-install")
        self.assertContains(page, "builder/pwa.js")
        for name in ("icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png"):
            self.assertTrue((Path(__file__).parent / "static" / "builder" / "app" / name).exists(), name)


class PlanningTests(TestCase):
    """Planungs-Bausteine: Einsatzplanung, Wochenübersicht, Kanban (builder/planning.py)."""

    def setUp(self):
        from django.utils import timezone

        call_command("beispiel_einsatzplanung", "--ohne-daten", verbosity=0)
        self.app = App.objects.get(slug="personaleinsatz")
        self.user = User.objects.create_user("planer", password="x")
        self.client.force_login(self.user)
        t = {e.slug: e for e in self.app.entities.all()}
        self.t = t
        self.l1 = Record.objects.create(entity=t["linien"], data={"name": "Linie A", "prioritaet": 1})
        self.l2 = Record.objects.create(entity=t["linien"], data={"name": "Linie B", "prioritaet": 2})
        # Die weniger wichtige Linie zuerst anlegen: sortiert wird trotzdem nach Priorität.
        self.s2 = Record.objects.create(entity=t["schichten"], data={"bezeichnung": "Früh B", "linie": self.l2.pk, "bedarf": 2})
        self.s1 = Record.objects.create(entity=t["schichten"], data={"bezeichnung": "Früh A", "linie": self.l1.pk, "bedarf": 1})
        self.anna = Record.objects.create(entity=t["mitarbeitende"], data={"name": "Anna", "aktiv": True})
        self.ben = Record.objects.create(entity=t["mitarbeitende"], data={"name": "Ben", "aktiv": True})
        self.alt = Record.objects.create(entity=t["mitarbeitende"], data={"name": "Ruheständler", "aktiv": False})
        self.today = timezone.localdate()
        self.day = self.today.isoformat()
        self.page = self.app.pages.get(slug="planung")
        self.url = reverse("block_action", args=[self.app.slug, "planung", self.page.layout[0]["id"]])

    def act(self, **payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def links(self):
        return list(self.t["einsaetze"].records.values_list("data", flat=True))

    def test_board_sorted_by_priority_and_only_active_sources(self):
        html = self.client.get(reverse("page", args=[self.app.slug, "planung"])).content.decode()
        self.assertLess(html.index("Linie A"), html.index("Linie B"))
        self.assertIn("Priorität 1", html)
        self.assertNotIn("Ruheständler", html)
        self.assertIn('data-plan="assign"', html)
        self.assertIn("planning.js", html)

    def test_assign_move_and_unassign(self):
        response = self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        self.assertEqual(response.json(), {"ok": True})
        link = self.t["einsaetze"].records.get()
        self.assertEqual((link.data["mitarbeiter"], link.data["schicht"], link.data["datum"]),
                         (self.anna.pk, self.s1.pk, self.day))
        self.assertEqual(link.created_by, self.user)
        # Schon in derselben Schicht: immer abgelehnt, auch mit force
        response = self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day, force=True)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["confirm"])
        self.assertEqual(self.act(op="move", link=link.pk, target=self.s2.pk, force=True).status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.data["schicht"], self.s2.pk)
        self.assertEqual(self.act(op="unassign", link=link.pk).json(), {"ok": True})
        self.assertEqual(self.links(), [])

    def test_overbooking_asks_and_force_saves(self):
        self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        response = self.act(op="assign", source=self.ben.pk, target=self.s1.pk, day=self.day)
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertTrue(data["confirm"])
        self.assertEqual(data["error"], "Überplanung")
        self.assertIn("1 von 1", data["problems"][0])
        self.assertEqual(len(self.links()), 1)
        forced = self.act(op="assign", source=self.ben.pk, target=self.s1.pk, day=self.day, force=True)
        self.assertEqual(forced.status_code, 200)
        self.assertEqual(len(self.links()), 2)
        html = self.client.get(reverse("page", args=[self.app.slug, "planung"])).content.decode()
        self.assertIn("state-over", html)

    def test_overbooking_blocked_when_configured(self):
        self.page.layout[0]["props"]["overbook"] = "block"
        self.page.save()
        self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        response = self.act(op="assign", source=self.ben.pk, target=self.s1.pk, day=self.day, force=True)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["confirm"])
        self.assertEqual(len(self.links()), 1)

    def test_priority_and_double_booking_warnings(self):
        # Linie B (Priorität 2) füllen, solange Linie A (Priorität 1) noch frei ist
        response = self.act(op="assign", source=self.anna.pk, target=self.s2.pk, day=self.day)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Linie A hat Priorität 1 und noch 1 offenen Platz.", response.json()["problems"])
        self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        # Anna ist jetzt in Linie A; ein zweiter Einsatz am selben Tag fragt nach
        problems = self.act(op="assign", source=self.anna.pk, target=self.s2.pk, day=self.day).json()["problems"]
        self.assertTrue(any("schon in „Früh A“ (Linie A)" in p for p in problems), problems)
        # An einem anderen Tag gibt es keine Rückfrage
        from datetime import timedelta
        other = (self.today + timedelta(days=1)).isoformat()
        self.assertEqual(self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=other).status_code, 200)

    def test_actions_respect_table_switches_and_login(self):
        self.t["einsaetze"].allow_create = False
        self.t["einsaetze"].save()
        response = self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        self.assertEqual(response.status_code, 400)
        self.assertIn("nicht erlaubt", response.json()["error"])
        self.client.logout()
        self.assertEqual(self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day).status_code, 302)

    def test_targets_from_other_tables_are_rejected(self):
        response = self.act(op="assign", source=self.anna.pk, target=self.l1.pk, day=self.day)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.links(), [])

    def test_week_overview_counts_capacity(self):
        self.act(op="assign", source=self.anna.pk, target=self.s1.pk, day=self.day)
        self.act(op="assign", source=self.ben.pk, target=self.s1.pk, day=self.day, force=True)
        html = self.client.get(reverse("page", args=[self.app.slug, "woche"])).content.decode()
        self.assertIn('2<span class="muted">/1</span>', html)
        self.assertIn("Anna, Ben", html)
        self.assertIn(f"/a/personaleinsatz/p/planung/?datum={self.day}", html)
        self.assertIn("überplant", html)

    def test_kanban_move_with_limit(self):
        t = self.t["tauschwuensche"]
        card = Record.objects.create(entity=t, data={"wunsch": "A", "status": "Neu"})
        Record.objects.create(entity=t, data={"wunsch": "B", "status": "Genehmigt"})
        page = self.app.pages.get(slug="tausch")
        page.layout[0]["props"]["limit"] = 1
        page.save()
        url = reverse("block_action", args=[self.app.slug, "tausch", page.layout[0]["id"]])

        def move(**extra):
            return self.client.post(url, json.dumps({"op": "move", "record": card.pk, **extra}),
                                    content_type="application/json")

        self.assertEqual(move(value="Gibt es nicht").status_code, 400)
        response = move(value="Genehmigt")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["confirm"])
        self.assertEqual(move(value="Genehmigt", force=True).status_code, 200)
        card.refresh_from_db()
        self.assertEqual(card.data["status"], "Genehmigt")

    def test_ai_designer_checks_fields_of_linked_tables(self):
        from .ai_designer import Invalid, normalize
        from .management.commands.beispiel_einsatzplanung import DEFINITION

        normalize(DEFINITION)  # gültig
        broken = json.loads(json.dumps(DEFINITION))
        broken["pages"][0]["layout"][0]["props"]["priority_field"] = "gibts_nicht"
        broken["pages"][0]["layout"][0]["props"]["capacity_field"] = "auch_nicht"
        with self.assertRaises(Invalid) as ctx:
            normalize(broken)
        text = " ".join(ctx.exception.errors)
        self.assertIn("Die Tabelle „linien“ hat kein Feld „gibts_nicht“", text)
        self.assertIn("Die Tabelle „schichten“ hat kein Feld „auch_nicht“", text)

    def test_preview_in_designer_is_read_only(self):
        from django.test import RequestFactory

        from .blocks import render_block

        request = RequestFactory().get("/designer/x/seite/1/vorschau/")
        request.user = self.user
        html = render_block(request, self.app, self.page.layout[0])
        self.assertIn("Schichtplanung", html)
        self.assertNotIn("data-action-url", html)

    def test_example_data_command(self):
        call_command("beispiel_einsatzplanung", "--app", self.app.slug, verbosity=0)
        # Tabellen mit Daten bleiben unverändert, leere bekommen Beispiele
        self.assertEqual(self.t["linien"].records.count(), 2)
        self.assertEqual(self.t["mitarbeitende"].records.count(), 3)
        self.assertEqual(self.t["aufgaben"].records.count(), 0)  # braucht drei Linien
        self.assertEqual(self.t["tauschwuensche"].records.count(), 0)  # braucht zwölf Personen
        self.assertGreater(self.t["einsaetze"].records.count(), 0)
        before = self.t["einsaetze"].records.count()
        call_command("beispiel_einsatzplanung", "--app", self.app.slug, verbosity=0)
        self.assertEqual(self.t["einsaetze"].records.count(), before)


class WidgetTests(TestCase):
    """Allgemeine Bausteine: Filterleiste, Kalender, Checkliste, Schieberegler, Aufklappbereich,
    Eingabefeld-Arten (builder/widgets.py)."""

    def setUp(self):
        from django.utils import timezone

        self.user = User.objects.create_user("macher", password="x")
        self.client.force_login(self.user)
        self.app = App.objects.create(name="Aufgaben", slug="aufgaben-test", published=True)
        self.entity = Entity.objects.create(app=self.app, name="Aufgaben", slug="aufgaben")
        Field.objects.create(entity=self.entity, label="Aufgabe", key="aufgabe", required=True)
        Field.objects.create(entity=self.entity, label="Status", key="status", type=Field.CHOICE, choices="Offen\nZu")
        Field.objects.create(entity=self.entity, label="Erledigt", key="erledigt", type=Field.BOOL)
        Field.objects.create(entity=self.entity, label="Fortschritt", key="fortschritt", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Fällig", key="faellig", type=Field.DATE)
        Field.objects.create(entity=self.entity, label="Bis", key="bis", type=Field.DATE)
        self.today = timezone.localdate()
        day = self.today.replace(day=10).isoformat()
        self.a = Record.objects.create(entity=self.entity, data={
            "aufgabe": "Alpha", "status": "Offen", "erledigt": False, "fortschritt": 20, "faellig": day,
            "bis": self.today.replace(day=12).isoformat()})
        self.b = Record.objects.create(entity=self.entity, data={
            "aufgabe": "Beta", "status": "Zu", "erledigt": True, "fortschritt": 90, "faellig": day})
        self.page = Page.objects.create(app=self.app, title="Start", slug="start", layout=clean_layout([
            make_block("filter", entity="aufgaben", field="status", field2="erledigt", field3="faellig"),
            make_block("table", entity="aufgaben"),
            make_block("stat", entity="aufgaben", label="Anzahl"),
            make_block("checklist", entity="aufgaben", field="erledigt"),
            make_block("sliders", entity="aufgaben", field="fortschritt", min=0, max=100, step=10),
            make_block("calendar", entity="aufgaben", date_field="faellig", end_field="bis", color_field="status"),
            make_block("details", title="Fragen", text="Antwort"),
        ]))
        self.ids = {b["type"]: b["id"] for b in self.page.layout}

    def url(self, block):
        return reverse("block_action", args=[self.app.slug, "start", self.ids[block]])

    def post(self, block, **payload):
        return self.client.post(self.url(block), json.dumps(payload), content_type="application/json")

    def get(self, query=""):
        return self.client.get(reverse("page", args=[self.app.slug, "start"]) + query).content.decode()

    def test_page_renders_all_widgets(self):
        html = self.get()
        for marker in ('class="card filter-block"', 'data-widget="checklist"', 'data-widget="sliders"',
                       'class="calendar"', "<summary", "widgets.js"):
            self.assertIn(marker, html)
        self.assertIn("1 von 2 erledigt", html)

    def test_filter_applies_to_all_blocks_of_the_table(self):
        html = self.get("?aufgaben.status=Zu")
        self.assertIn("1 von 2 Einträgen", html)
        self.assertIn("Beta", html)
        self.assertNotIn("Alpha", html)
        self.assertNotIn("Alpha", self.get("?aufgaben.erledigt=1"))
        self.assertNotIn("Beta", self.get("?aufgaben.erledigt=0"))
        later = (self.today.replace(day=10)).isoformat()
        self.assertIn("Alpha", self.get(f"?aufgaben.faellig.von={later}"))
        self.assertNotIn("Alpha", self.get("?aufgaben.faellig.bis=2000-01-01"))

    def test_filter_on_text_and_reset_keeps_other_params(self):
        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("filter", entity="aufgaben", field="aufgabe"), make_block("table", entity="aufgaben")]))
        html = self.get("?aufgaben.aufgabe=alp&monat=2026-01")
        self.assertIn("Alpha", html)
        self.assertNotIn("Beta", html)
        self.assertIn('name="monat" value="2026-01"', html)
        self.assertIn('href="?monat=2026-01"', html)

    def test_checklist_toggle(self):
        self.assertEqual(self.post("checklist", op="toggle", record=self.a.pk, value=True).status_code, 200)
        self.a.refresh_from_db()
        self.assertIs(self.a.data["erledigt"], True)
        self.post("checklist", op="toggle", record=self.a.pk, value=False)
        self.a.refresh_from_db()
        self.assertIs(self.a.data["erledigt"], False)
        self.assertEqual(self.post("checklist", op="toggle", record=999999, value=True).status_code, 400)

    def test_sliders_validate_range_and_step(self):
        response = self.post("sliders", op="set", record=self.a.pk, value="57")
        self.assertEqual(response.json(), {"ok": True, "value": 60})
        self.a.refresh_from_db()
        self.assertEqual(self.a.data["fortschritt"], 60)
        self.assertEqual(self.post("sliders", op="set", record=self.a.pk, value="150").status_code, 400)
        self.assertEqual(self.post("sliders", op="set", record=self.a.pk, value="viel").status_code, 400)

    def test_actions_respect_table_switches(self):
        self.entity.allow_edit = False
        self.entity.save()
        self.assertEqual(self.post("sliders", op="set", record=self.a.pk, value="30").status_code, 400)
        self.assertEqual(self.post("checklist", op="toggle", record=self.a.pk, value=True).status_code, 400)
        self.assertNotIn('data-widget="checklist"', self.get())  # nur zum Ansehen
        self.assertEqual(self.post("details").status_code, 400)  # Baustein ohne Aktionen

    def test_calendar_month_multi_day_and_create_link(self):
        html = self.get(f"?monat={self.today:%Y-%m}")
        self.assertEqual(html.count('title="Alpha">Alpha<'), 3)  # im Kalender am 10., 11. und 12.
        self.assertIn("tone-2", html)  # Beta hat Status „Zu“, zweiter Auswahlwert
        self.assertIn(f"/a/{self.app.slug}/t/aufgaben/neu/?faellig=", html)
        self.assertNotIn('title="Alpha">Alpha<', self.get("?monat=2000-01"))

    def test_new_record_prefilled_from_address(self):
        url = reverse("record_create", args=[self.app.slug, "aufgaben"])
        html = self.client.get(url + "?faellig=2026-12-24&aufgabe=Geschenke&unbekannt=x").content.decode()
        self.assertIn('value="2026-12-24"', html)
        self.assertIn('value="Geschenke"', html)

    def test_input_kinds(self):
        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("input", param="menge", kind="range", min=1, max=10, step=1),
            make_block("input", param="farbe", kind="select", options="Rot\nGrün"),
            make_block("input", param="ok", kind="checkbox"),
            make_block("input", param="tag", kind="date"),
        ]))
        html = self.get("?menge=99&farbe=Grün&ok=1")
        self.assertIn('type="range" name="menge" min="1" max="10" step="1" value="10"', html)
        self.assertIn("<option selected>Grün</option>", html)
        self.assertIn('type="checkbox" name="ok" value="1" data-page-input checked', html)
        self.assertIn('type="date" name="tag"', html)

    def test_pivot_count_sum_and_filter(self):
        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("filter", entity="aufgaben", field="status"),
            make_block("pivot", entity="aufgaben", row_field="status", col_field="erledigt", agg="count"),
            make_block("pivot", entity="aufgaben", row_field="status", agg="sum", value_field="fortschritt"),
        ]))
        html = self.get()
        self.assertIn('class="pivot-table"', html)
        self.assertIn("Offen", html)
        self.assertIn("Zu", html)
        self.assertIn("110", html)  # Gesamtsumme 20 + 90
        filtered_html = self.get("?aufgaben.status=Zu")
        self.assertIn("90", filtered_html)
        self.assertNotIn("Offen", filtered_html.split('class="pivot-table"')[1])

    def test_gantt_timeline_and_grouping(self):
        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("gantt", entity="aufgaben", start_field="faellig", end_field="bis",
                       group_field="status", color_field="status"),
        ]))
        win = self.today.replace(day=1).isoformat()
        html = self.get(f"?zeitraum={win}")
        self.assertIn('class="card gantt-block"', html)
        self.assertIn('class="gantt-group">Offen</div>', html)
        self.assertIn('class="gantt-bar', html)
        self.assertIn("Alpha", html)
        self.assertIn("Keine Einträge in diesem Zeitraum.", self.get("?zeitraum=2000-01-03"))

    def test_detail_related_list_search_and_stepper(self):
        notizen = Entity.objects.create(app=self.app, name="Notizen", slug="notizen")
        Field.objects.create(entity=notizen, label="Aufgabe", key="aufgabe", type=Field.REFERENCE, reference=self.entity)
        Field.objects.create(entity=notizen, label="Text", key="text")
        Record.objects.create(entity=notizen, data={"aufgabe": self.a.pk, "text": "Erste Notiz"})
        Record.objects.create(entity=notizen, data={"aufgabe": self.b.pk, "text": "Andere Notiz"})

        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("search", entity="aufgaben", field="aufgabe", target_page="start"),
            make_block("detail", entity="aufgaben"),
            make_block("stepper", entity="aufgaben", field="status"),
            make_block("related_list", entity="notizen", ref_field="aufgabe"),
        ]))
        self.ids = {b["type"]: b["id"] for b in Page.objects.get(pk=self.page.pk).layout}

        html = self.get(f"?id={self.a.pk}")
        self.assertIn('class="card detail-block"', html)
        self.assertIn("Alpha", html)
        self.assertIn("Erste Notiz", html)
        self.assertNotIn("Andere Notiz", html)
        self.assertIn(f"/a/{self.app.slug}/t/notizen/neu/?aufgabe={self.a.pk}", html)
        self.assertIn('data-widget="stepper"', html)
        self.assertIn('name="aufgaben.aufgabe"', html)

        self.assertEqual(self.post("stepper", op="step", record=self.a.pk, value="Zu").status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.data["status"], "Zu")
        self.assertEqual(self.post("stepper", op="step", record=self.a.pk, value="Ungueltig").status_code, 400)

    def test_stepper_missing_param_uses_field_label_and_title_override(self):
        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("stepper", entity="aufgaben", field="status"),
        ]))
        html = self.get()
        self.assertIn('<h3 data-slot="title">Status</h3>', html)
        self.assertIn("Wähle einen Eintrag über ?id=… aus.", html)
        self.assertNotIn('data-widget="stepper"', html)

        Page.objects.filter(pk=self.page.pk).update(layout=clean_layout([
            make_block("stepper", entity="aufgaben", field="status", title="Mein Fortschritt"),
        ]))
        html_titled = self.get()
        self.assertIn('<h3 data-slot="title">Mein Fortschritt</h3>', html_titled)
        self.assertIn("Wähle einen Eintrag über ?id=… aus.", html_titled)


class CsvImportTests(TestCase):
    """Zweistufiger CSV-Import für Tabellendaten."""

    def setUp(self):
        self.user = User.objects.create_user("importer", password="x")
        self.client.force_login(self.user)
        self.app = App.objects.create(name="Lager", slug="lager-import", published=True)
        self.kategorien = Entity.objects.create(app=self.app, name="Kategorien", slug="kategorien")
        Field.objects.create(entity=self.kategorien, label="Name", key="name", required=True)
        self.kat = Record.objects.create(entity=self.kategorien, data={"name": "Elektronik"})
        self.entity = Entity.objects.create(app=self.app, name="Artikel", slug="artikel")
        Field.objects.create(entity=self.entity, label="Bezeichnung", key="bezeichnung", required=True)
        Field.objects.create(entity=self.entity, label="Menge", key="menge", type=Field.NUMBER)
        Field.objects.create(entity=self.entity, label="Aktiv", key="aktiv", type=Field.BOOL)
        Field.objects.create(entity=self.entity, label="Datum", key="datum", type=Field.DATE)
        Field.objects.create(entity=self.entity, label="Kategorie", key="kategorie", type=Field.REFERENCE, reference=self.kategorien)
        self.url = reverse("entity_import", args=[self.app.slug, self.entity.slug])

    def test_two_step_csv_import_and_audit(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_bytes = "Bezeichnung;Menge;Aktiv;Datum;Kategorie\nMonitor;5;ja;19.11.2026;Elektronik\nMaus;12;nein;2026-11-20;Elektronik\n".encode("utf-8")
        res = self.client.post(self.url, {"step": "upload", "file": SimpleUploadedFile("daten.csv", csv_bytes, content_type="text/csv")})
        self.assertEqual(res.status_code, 200)
        self.assertIn("2 Datenzeilen erkannt", res.content.decode())

        res = self.client.post(self.url, {"step": "import", "col_0": "bezeichnung", "col_1": "menge", "col_2": "aktiv", "col_3": "datum", "col_4": "kategorie"})
        self.assertEqual(res.status_code, 302)
        records = list(self.entity.records.order_by("id"))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].data["bezeichnung"], "Monitor")
        self.assertEqual(records[0].data["menge"], 5)
        self.assertIs(records[0].data["aktiv"], True)
        self.assertEqual(records[0].data["datum"], "2026-11-19")
        self.assertEqual(records[0].data["kategorie"], self.kat.pk)
        from .models import AuditEntry

        self.assertTrue(AuditEntry.objects.filter(app=self.app, action="create", target_type="record").exists())

    def test_csv_import_validation_abort_and_skip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        csv_bytes = "Bezeichnung,Menge\nMonitor,5\nKaputt,keinezahl\n".encode("utf-8")
        self.client.post(self.url, {"step": "upload", "file": SimpleUploadedFile("bad.csv", csv_bytes, content_type="text/csv")})
        res = self.client.post(self.url, {"step": "import", "col_0": "bezeichnung", "col_1": "menge"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.entity.records.count(), 0)  # bei Fehler abgebrochen

        res = self.client.post(self.url, {"step": "import", "col_0": "bezeichnung", "col_1": "menge", "skip_errors": "1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.entity.records.count(), 1)  # gültige Zeile importiert

    def test_csv_import_respects_allow_create(self):
        self.entity.allow_create = False
        self.entity.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)


class InterfaceTranslationTests(TestCase):
    """Englische Oberfläche: jeder Text hat eine Übersetzung (manage.py uebersetzungen)."""

    def test_every_text_is_translated(self):
        from .management.commands.uebersetzungen import missing

        gaps = {domain: [f"{where[0]}: {msgid}" for _c, msgid, _p, where, _k in items]
                for domain, items in missing("en").items() if items}
        self.assertEqual(gaps, {}, "Fehlende Übersetzungen: python manage.py uebersetzungen ergaenzen, "
                                   "übersetzen, dann kompilieren.")

    def test_compiled_files_match_po(self):
        import gettext
        import tempfile
        from pathlib import Path

        from .management.commands.uebersetzungen import BUILDER, compile_mo

        folder = BUILDER / "locale" / "en" / "LC_MESSAGES"
        for domain in ("django", "djangojs"):
            with tempfile.TemporaryDirectory() as tmp:
                fresh = Path(tmp) / "x.mo"
                compile_mo(folder / f"{domain}.po", fresh)
                with open(folder / f"{domain}.mo", "rb") as a, open(fresh, "rb") as b:
                    shipped, built = gettext.GNUTranslations(a)._catalog, gettext.GNUTranslations(b)._catalog
            self.assertEqual(shipped, built, f"{domain}.mo ist nicht aktuell: python manage.py uebersetzungen kompilieren")

    def test_planning_page_in_english(self):
        from django.utils import timezone

        call_command("beispiel_einsatzplanung", "--ohne-daten", verbosity=0)
        app = App.objects.get(slug="personaleinsatz")
        user = User.objects.create_user("english", password="x")
        self.client.force_login(user)
        self.client.cookies["django_language"] = "en"
        html = self.client.get(reverse("page", args=[app.slug, "planung"]), HTTP_ACCEPT_LANGUAGE="en").content.decode()
        self.assertIn("Available", html)
        self.assertNotIn("Verfügbar", html)
        today = timezone.localdate()
        self.assertIn(f"{today:%B} {today.day}, {today.year}", html)  # z. B. „Thursday, November 19, 2026“


class CustomBlockEnhancementTests(TestCase):
    """Eigene Bausteine: typisierte Einstellungen, Live-Vorschau, Sanitizer-Report, Hooks & MCP."""

    def setUp(self):
        from .models import DesignerToken

        self.designer = User.objects.create_user("bauherr", password="x", is_staff=True)
        self.token, self.raw_token = DesignerToken.issue(self.designer, "KI-Test")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"}

    def test_typed_and_json_setting_specs(self):
        from .models import CustomBlock

        cb = CustomBlock(
            name="KPI",
            settings="Anzahl : number = 5\nAktiv : checkbox = true\nStufe : select(info, warnung) = warnung",
            html="<p>{{ anzahl }}</p>",
        )
        specs = cb.setting_specs()
        self.assertEqual([s["type"] for s in specs], ["number", "checkbox", "select"])
        self.assertEqual(specs[1]["default"], True)
        self.assertEqual(specs[2]["options"], [["info", "info"], ["warnung", "warnung"]])

        cb_json = CustomBlock(
            name="JSON",
            settings='[{"key": "limit", "label": "Limit", "type": "number", "default": 10}]',
            html="<p>{{ limit }}</p>",
        )
        self.assertEqual(cb_json.setting_specs(), [{"key": "limit", "label": "Limit", "default": "10", "type": "number"}])

    def test_sanitize_report_and_live_preview(self):
        from .sanitize import sanitize_html_report

        clean, warnings = sanitize_html_report('<div onclick="x()">Hi</div><script>alert(1)</script>')
        self.assertEqual(clean, "<div>Hi</div>")
        self.assertEqual(len(warnings), 2)

        self.client.force_login(self.designer)
        resp = self.client.post(
            reverse("designer_block_preview"),
            data=json.dumps({
                "name": "Test",
                "settings": "Titel = Hallo",
                "html": '<div class="card"><h3>{{ titel }}</h3><script>bad()</script></div>',
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("<h3>Hallo</h3>", data["html"])
        self.assertNotIn("<script>", data["html"])
        self.assertIn("titel", data["placeholders"])
        self.assertIn("nutzer", data["placeholders"])
        self.assertTrue(data["warnings"])

    def test_hook_block_with_fields_and_props(self):
        from . import hooks
        from .blocks import all_types

        @hooks.block("test_props_block", label="Props-Test", fields=[{"key": "titel", "label": "Titel", "type": "text"}])
        def _test_block(request, app, props):
            return f"Hallo {props.get('titel', '')}"

        try:
            btype = all_types()["x-test_props_block"]
            self.assertEqual(len(btype.fields), 1)
            res = btype.prepare(None, None, {"props": {"titel": "Welt"}})
            self.assertEqual(res["custom_html"], "Hallo Welt")
        finally:
            hooks.CUSTOM_BLOCKS.pop("test_props_block", None)

    def test_mcp_custom_block_tools_and_guide(self):
        def call_mcp(method, params=None):
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            return self.client.post(
                reverse("mcp_designer"), data=json.dumps(body), content_type="application/json", **self.auth
            ).json()

        guide_res = call_mcp("tools/call", {"name": "guide", "arguments": {}})
        guide_data = json.loads(guide_res["result"]["content"][0]["text"])
        self.assertIn("design_system", guide_data)
        self.assertIn("custom_block_html_rules", guide_data)

        save_res = call_mcp("tools/call", {
            "name": "save_custom_block",
            "arguments": {
                "name": "Status-Karte",
                "description": "Zeigt Status",
                "settings": [{"key": "titel", "label": "Titel", "type": "text", "default": "OK"}],
                "html": '<div class="card"><h3>{{ titel }}</h3><script>x()</script></div>',
            },
        })
        saved = json.loads(save_res["result"]["content"][0]["text"])
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["type"], "c-status-karte")
        self.assertTrue(saved["warnings"])

        listed = json.loads(call_mcp("tools/call", {"name": "list_custom_blocks", "arguments": {}})["result"]["content"][0]["text"])
        self.assertEqual(len(listed["custom_blocks"]), 1)

        deleted = json.loads(call_mcp("tools/call", {"name": "delete_custom_block", "arguments": {"slug": "status-karte"}})["result"]["content"][0]["text"])
        self.assertTrue(deleted["deleted"])


class HomePageEnhancementTests(TestCase):
    """Startseite: unterschiedliche Designer-Links, Seiten-Meldungen, Fehler-Badge und Widgets."""

    def setUp(self):
        self.designer = User.objects.create_user("chef", password="x", is_staff=True)
        self.viewer = User.objects.create_user("leser", password="x")
        self.app = App.objects.create(name="Werk", slug="werk", created_by=self.designer, published=True)
        self.entity = Entity.objects.create(app=self.app, name="Geräte", slug="geraete")
        self.page = Page.objects.create(
            app=self.app,
            title="Start",
            slug="start",
            layout=[
                {"id": "bnotice1", "type": "notice", "width": 12, "props": {"title": "Wartung", "text": "Freitag 16 Uhr"}},
                {"id": "bstat1", "type": "stat", "width": 4, "props": {"label": "Geräte", "entity": "geraete"}},
            ],
        )

    def test_hero_links_notices_and_error_badges(self):
        from .models import Script

        Script.objects.create(app=self.app, name="Kaputt", language=Script.PYTHON, trigger=Script.PAGE, failures=2)
        self.client.force_login(self.designer)
        res = self.client.get(reverse("home"))
        self.assertContains(res, '?neu=app#neu-anlegen"')
        self.assertContains(res, "Freitag 16 Uhr")
        self.assertContains(res, "1 Fehler")

        self.client.force_login(self.viewer)
        res_viewer = self.client.get(reverse("home"))
        self.assertContains(res_viewer, "Freitag 16 Uhr")
        self.assertNotContains(res_viewer, "1 Fehler")

    def test_home_widgets_add_render_and_remove(self):
        from .models import HomeWidget

        self.client.force_login(self.viewer)
        sheet = self.client.get(reverse("home"))
        self.assertContains(sheet, 'id="widget-sheet"')
        self.assertContains(sheet, 'data-widget-app')
        self.assertContains(sheet, f'value="{self.page.pk}:bstat1"')
        self.assertNotContains(sheet, "<select name=\"target\"")
        add_res = self.client.post(reverse("home_widget_add"), {"target": f"{self.page.pk}:bstat1"})
        self.assertEqual(add_res.status_code, 302)
        widget = HomeWidget.objects.get(user=self.viewer, page=self.page, block_id="bstat1")

        home_res = self.client.get(reverse("home"))
        self.assertContains(home_res, reverse("page_block", args=["werk", "start", "bstat1"]))

        rem_res = self.client.post(reverse("home_widget_remove", args=[widget.pk]))
        self.assertEqual(rem_res.status_code, 302)
        self.assertFalse(HomeWidget.objects.filter(pk=widget.pk).exists())


class ReviewHardeningTests(TestCase):
    """Tests für Review-Härtungen: Probes, OIDC-Claims, SSRF, SQLite-Guard, API-Key-Aktivstatus, Slugs."""

    def test_healthz_readyz_and_redirect_exempt(self):
        from django.conf import settings

        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        self.assertTrue(any("healthz" in pat for pat in settings.SECURE_REDIRECT_EXEMPT))
        self.assertTrue(any("readyz" in pat for pat in settings.SECURE_REDIRECT_EXEMPT))

    def test_oidc_claim_names_and_username_fallback(self):
        from .auth import _username_from_claims, claim_names

        claims = {"groups": ["/Automatisierer/", " /Team/Labor ", "/extern"]}
        self.assertEqual(claim_names(claims, "groups"), {"Automatisierer", "Labor", "extern"})
        self.assertEqual(claim_names(claims, "groups", prefix="Auto"), {"Automatisierer"})

        self.assertEqual(_username_from_claims({"preferred_username": "alice"}), "alice")
        self.assertEqual(_username_from_claims({"sub": "uuid-1234"}), "uuid-1234")
        self.assertEqual(_username_from_claims({"email": "bob@example.com"}), "")

    def test_ssrf_forbidden_hosts_and_internal_sqlite_guard(self):
        from django.conf import settings
        from django.test import override_settings
        from .datasources import QueryError, _connect
        from .services import HttpNotAllowed, http_request

        with override_settings(BAUKASTEN_HTTP_ALLOWED_HOSTS=["127.0.0.1", "169.254.169.254", "localhost"]):
            for bad in ("http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/", "http://localhost/x"):
                with self.assertRaises(HttpNotAllowed):
                    http_request("GET", bad)

        fake_db = str(Path(_DEMO_DIR) / "internal-test.sqlite3")
        with override_settings(DATABASES={"default": {**settings.DATABASES["default"], "NAME": fake_db}}):
            with self.assertRaises(QueryError):
                _connect(f"sqlite:///{fake_db}", 5)

    def test_deactivated_user_api_key_rejected_and_reserved_slugs(self):
        from .models import ApiKey, unique_slug

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


class DataScienceBlocksTests(TestCase):
    """Tests für Data-Science-Visualisierungen: Scatter, Boxplot, Heatmap, Spec-Chart, Band/Anomalien, Tableau-Selection & Demo."""

    def setUp(self):
        self.user = User.objects.create_user("dsuser", password="x", is_staff=True)
        self.client.force_login(self.user)

    def test_beispiel_datascience_and_all_ds_blocks(self):
        call_command("beispiel_datascience", verbosity=0)
        app = App.objects.get(slug="datascience")

        analyse = self.client.get(reverse("page", args=[app.slug, "analyse"]))
        self.assertEqual(analyse.status_code, 200)
        self.assertContains(analyse, "scatter-block")
        self.assertContains(analyse, 'cx="24.0"')
        self.assertNotContains(analyse, 'cx="24,0"')
        self.assertContains(analyse, "R² =")
        self.assertContains(analyse, "boxplot-block")
        self.assertContains(analyse, "heatmap-block")
        self.assertContains(analyse, "line-band")
        self.assertContains(analyse, "line-threshold")
        self.assertContains(analyse, "line-anomaly")
        self.assertContains(analyse, "chargen.werk=Stuttgart")

        sim = self.client.get(reverse("page", args=[app.slug, "simulator"]))
        self.assertEqual(sim.status_code, 200)
        self.assertContains(sim, "What-If-Simulator")

    def test_heatmap_crosstab_spec_chart_and_tableau_selection_map(self):
        from django.test import override_settings

        call_command("beispiel_datascience", verbosity=0)
        app = App.objects.get(slug="datascience")
        page = Page.objects.create(app=app, title="Extra", slug="extra", layout=[
            {"id": "bhm", "type": "heatmap", "width": 6, "props": {
                "title": "Werk × Status", "entity": "chargen", "mode": "crosstab",
                "row_field": "werk", "col_field": "status", "agg": "avg", "value_field": "ausschuss",
            }},
            {"id": "bsp", "type": "spec_chart", "width": 6, "props": {
                "title": "Vega-Spec", "entity": "chargen",
                "spec": json.dumps({"mark": "line", "encoding": {"x": {"field": "werk"}, "y": {"field": "ausschuss", "aggregate": "avg"}}}),
            }},
            {"id": "bch", "type": "chart", "width": 6, "props": {
                "label": "Nach Werk", "entity": "chargen", "field": "werk",
            }},
            {"id": "btb", "type": "tableau", "width": 12, "props": {
                "label": "Tableau", "url": "https://tableau.example.com/views/Werk/Dashboard",
                "selection_map": "Werk = chargen.werk\nCharge = id",
            }},
        ])
        with override_settings(BAUKASTEN_TABLEAU_HOSTS=["tableau.example.com"]):
            res = self.client.get(reverse("page", args=[app.slug, page.slug]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "heat-cell")
        self.assertContains(res, "spec-chart-block")
        self.assertContains(res, "chart-filter-link")
        self.assertContains(res, "data-selection-map=")

    def test_histogram_psi_formula_query_visuals_and_exports(self):
        from unittest.mock import patch
        from .models import DataQuery, Record

        call_command("beispiel_datascience", verbosity=0)
        app = App.objects.get(slug="datascience")
        chargen = app.entities.get(slug="chargen")

        # 1c. Formelspalte wird beim Speichern automatisch berechnet
        rec = Record.objects.create(entity=chargen, data={
            "charge": "CH-999", "werk": "Stuttgart", "temperatur": 190.0,
            "druck": 40.0, "durchsatz": 100, "prognose": 2.0, "ausschuss": 3.25, "status": "OK",
        })
        self.assertEqual(rec.data.get("abweichung"), 1.25)

        # 1b. Histogramm & PSI-Drift auf der Analyse-Seite
        analyse = self.client.get(reverse("page", args=[app.slug, "analyse"]))
        self.assertEqual(analyse.status_code, 200)
        self.assertContains(analyse, "histogram-block")
        self.assertContains(analyse, "PSI ")

        # 1a & 1d. Live-DataQuery direkt in Scatter/Boxplot/Histogramm + CSV-Export für Query & gefilterte Tabelle
        q = DataQuery.objects.create(app=app, name="Live-Chargen", slug="live-chargen", source="dwh", sql="SELECT * FROM c")
        # Wie datasources.run_saved wirklich liefert: Zeilen als Dictionaries {Spalte: Wert}.
        fake_rows = [
            {"temp": 180.0, "scrap": 1.5, "plant": "Stuttgart"},
            {"temp": 185.0, "scrap": 2.1, "plant": "Stuttgart"},
            {"temp": 195.0, "scrap": 3.8, "plant": "München"},
            {"temp": 200.0, "scrap": 4.4, "plant": "München"},
        ]
        q_page = Page.objects.create(app=app, title="Live-DS", slug="live-ds", layout=[
            {"id": "bqsc", "type": "scatter", "width": 6, "props": {
                "title": "Live-Scatter", "query": "live-chargen", "x_field": "temp", "y_field": "scrap", "trendline": True,
            }},
            {"id": "bqbx", "type": "boxplot", "width": 6, "props": {
                "title": "Live-Boxplot", "query": "live-chargen", "field": "scrap", "group_field": "plant",
            }},
            {"id": "bqhi", "type": "histogram", "width": 6, "props": {
                "title": "Live-Histogramm", "query": "live-chargen", "field": "temp", "group_field": "plant", "bins": 4,
            }},
        ])
        with patch("builder.datasources.run_saved", return_value={"columns": ["temp", "scrap", "plant"], "rows": fake_rows}):
            res_q = self.client.get(reverse("page", args=[app.slug, q_page.slug]))
            self.assertEqual(res_q.status_code, 200)
            self.assertContains(res_q, "Live-Scatter")
            self.assertContains(res_q, "Live-Boxplot")
            self.assertContains(res_q, "Live-Histogramm")

            csv_q = self.client.get(reverse("query_export", args=[app.slug, q.slug]))
            self.assertEqual(csv_q.status_code, 200)
            self.assertIn("Stuttgart", b"".join(csv_q.streaming_content).decode("utf-8"))

        # Gefilterter Tabellen-CSV-Export
        csv_all = b"".join(self.client.get(reverse("entity_export", args=[app.slug, "chargen"])).streaming_content).decode("utf-8")
        csv_stuttgart = b"".join(self.client.get(
            reverse("entity_export", args=[app.slug, "chargen"]) + "?chargen.werk=Stuttgart"
        ).streaming_content).decode("utf-8")
        self.assertIn("München", csv_all)
        self.assertNotIn("München", csv_stuttgart)
        self.assertIn("Stuttgart", csv_stuttgart)


class ComfortAndAlertingTests(TestCase):
    """Tests für Punkt 3: Versions-Diff, Optimistic Locking für Skripte, App-Klonen und Fehler-Alarmierung."""

    def setUp(self):
        self.user = User.objects.create_user("opsuser", password="x", is_staff=True)
        self.client.force_login(self.user)
        self.app = App.objects.create(name="Produktion", slug="produktion", created_by=self.user, published=True)
        self.entity = Entity.objects.create(app=self.app, name="Aufträge", slug="auftraege")
        Field.objects.create(entity=self.entity, label="Nummer", key="nummer", type=Field.TEXT)
        self.page = Page.objects.create(app=self.app, title="Übersicht", slug="uebersicht")

    def test_version_diff_and_app_clone(self):
        from . import versions

        v1 = versions.create_version(self.app, self.user, "Basis")
        Field.objects.create(entity=self.entity, label="Betrag", key="betrag", type=Field.DECIMAL, formula="preis * 2")
        Page.objects.create(app=self.app, title="Neu", slug="neu-seite")

        changes = versions.diff(versions.snapshot(self.app), v1.snapshot)
        self.assertTrue(any("Aufträge" in c for c in changes))
        self.assertTrue(any("Neu" in c for c in changes))

        detail = self.client.get(reverse("designer_app", args=[self.app.slug]))
        self.assertContains(detail, "Unterschiede zum aktuellen Stand")

        clone_res = self.client.post(reverse("designer_app_clone", args=[self.app.slug]))
        self.assertEqual(clone_res.status_code, 302)
        cloned = App.objects.exclude(pk=self.app.pk).get()
        self.assertIn("(Kopie)", cloned.name)
        self.assertFalse(cloned.published)
        self.assertEqual(cloned.entities.count(), 1)
        self.assertEqual(cloned.entities.first().fields.get(key="betrag").formula, "preis * 2")

    def test_script_optimistic_locking_409(self):
        from .models import Script

        sc = Script.objects.create(
            app=self.app, name="Rechner", slug="rechner",
            language=Script.PYTHON, trigger=Script.PAGE, code="print(1)",
        )
        stale_token = "2020-01-01T00:00:00+00:00"
        conflict = self.client.post(reverse("designer_script", args=[self.app.slug, sc.pk]), {
            "name": "Rechner", "language": Script.PYTHON, "trigger": Script.PAGE,
            "interval_minutes": 60, "enabled": "on", "code": "print(2)",
            "expected_version": stale_token, "action": "save",
        })
        self.assertEqual(conflict.status_code, 409)
        sc.refresh_from_db()
        self.assertEqual(sc.code, "print(1)")

        ok = self.client.post(reverse("designer_script", args=[self.app.slug, sc.pk]), {
            "name": "Rechner", "language": Script.PYTHON, "trigger": Script.PAGE,
            "interval_minutes": 60, "enabled": "on", "code": "print(2)",
            "expected_version": sc.updated_at.isoformat(), "action": "save",
        })
        self.assertEqual(ok.status_code, 302)
        sc.refresh_from_db()
        self.assertEqual(sc.code, "print(2)")

    def test_alert_channels_teams_email_and_api(self):
        from unittest.mock import MagicMock, patch
        from django.core import mail
        from . import alerts, platform
        from .models import PlatformSettings

        settings_row, _ = PlatformSettings.objects.get_or_create(pk=1)

        # 1. Teams Webhook
        settings_row.alert_channel = "teams"
        settings_row.alert_target = "https://outlook.office.com/webhook/test"
        settings_row.save()
        platform.forget()
        with patch("builder.alerts.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            self.assertTrue(alerts.notify_failure("automation", "Job X kaputt", "ZeroDivisionError", app=self.app))
            self.assertEqual(mock_post.call_count, 1)
            payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(payload["@type"], "MessageCard")
            self.assertIn("Job X kaputt", payload["title"])

        # 2. E-Mail
        settings_row.alert_channel = "email"
        settings_row.alert_target = "ops@example.com, team@example.com"
        settings_row.save()
        platform.forget()
        mail.outbox.clear()
        self.assertTrue(alerts.notify_failure("datasource_sync", "DWH Timeout", "Timeout nach 300s", app=self.app))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("DWH Timeout", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["ops@example.com", "team@example.com"])

        # 3. API-Call mit Authorization-Header
        settings_row.alert_channel = "api"
        settings_row.alert_target = "https://monitoring.example.com/events"
        settings_row.alert_auth_header = "Bearer geheim-123"
        settings_row.save()
        platform.forget()
        with patch("builder.alerts.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            self.assertTrue(alerts.notify_failure("schedule_script", "Skript Y", "Fehler in Zeile 3", app=self.app))
            self.assertEqual(mock_post.call_count, 1)
            self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer geheim-123")
            self.assertEqual(mock_post.call_args.kwargs["json"]["event"], "baukasten.failure")
            self.assertEqual(mock_post.call_args.kwargs["json"]["app"], "produktion")



class ReviewFindingsTests(TestCase):
    """Befunde aus dem Code-Review: jeder Test schlägt mit dem alten Code fehl."""

    ROWS = [  # so liefert datasources.run_saved die Zeilen: Dictionaries {Spalte: Wert}
        {"temp": 180.0, "scrap": 1.5, "plant": "Stuttgart"},
        {"temp": 185.0, "scrap": 2.1, "plant": "Stuttgart"},
        {"temp": 195.0, "scrap": 3.8, "plant": "München"},
        {"temp": 200.0, "scrap": 4.4, "plant": "München"},
    ]

    def setUp(self):
        from .models import DataQuery

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

        from .blocks import render_block
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

        from . import datasources

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
        from .models import evaluate_formula

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

        from . import csv_import

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

        from .blocks import render_block

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

        from . import alerts

        cache.clear()
        with patch("builder.platform.value", side_effect=lambda key: {
                "alert_channel": "api", "alert_target": "https://alarm.example.com/hook",
                "alert_auth_header": ""}.get(key)), \
                patch("builder.alerts.requests.post") as post, self.settings(BAUKASTEN_ALERT_REPEAT_MINUTES=60):
            self.assertTrue(alerts.notify_failure("schedule_script", "Skript X fehlgeschlagen", "Fehler", app=self.app))
            self.assertFalse(alerts.notify_failure("schedule_script", "Skript X fehlgeschlagen", "Fehler", app=self.app))
            self.assertTrue(alerts.notify_failure("schedule_script", "Skript Y fehlgeschlagen", "Fehler", app=self.app))
        self.assertEqual(post.call_count, 2)
