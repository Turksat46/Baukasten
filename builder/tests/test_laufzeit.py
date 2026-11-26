"""Laufzeit der Apps: Seiten, Bausteine, Startseite, Darstellung, PWA."""

import json
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .. import hooks
from ..blocks import REGISTRY, clean_layout, make_block
from ..management.commands.demo import months_ago
from ..models import App, Entity, Field, Page, Record
from .base import BUILDER_DIR, Base


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


class SanitizerTests(TestCase):
    def test_dangerous_markup_is_removed(self):
        from ..sanitize import fill_placeholders, sanitize_html
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


class BrandTests(TestCase):
    def test_logo_slot(self):
        from .. import context
        with mock.patch.object(context, "brand_logo", return_value=""):  # unabhängig von einer echten Logodatei
            self.assertNotContains(self.client.get(reverse("login")), "brand-logo")
        with mock.patch.object(context, "brand_logo", return_value="builder/logo.svg"):
            self.assertContains(self.client.get(reverse("login")), 'class="brand-logo"')


# ---------- Skripte ----------


class TransitionTests(TestCase):
    def test_pages_opt_into_transitions(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, "builder/transitions.js")
        from django.contrib.staticfiles import finders
        css = open(finders.find("builder/style.css"), encoding="utf-8").read()
        self.assertIn("@view-transition { navigation: auto; }", css)
        self.assertIn("prefers-reduced-motion", css)


class ThemeTests(Base):
    def test_toggle_on_every_page_and_login(self):
        login = self.client.get("/login/")
        self.assertContains(login, "data-theme-toggle")
        self.assertContains(login, "builder/theme.js")
        self.client.force_login(self.designer)
        for url in ("/", "/profil/", "/hilfe/", "/designer/"):
            self.assertContains(self.client.get(url), "data-theme-toggle", msg_prefix=url)
        self.assertContains(self.client.get("/profil/"), 'data-theme-choice="dark"')


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


class LineChartTests(Base):
    """Baustein „Liniendiagramm“."""

    def render(self, **props):
        from ..blocks import prep_line
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
        from .. import versions
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
        from ..models import Script
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
        from ..scripting.python import run
        result = run("a = token()\nb = token(32)\nprint(len(a) >= 20, len(b) >= 40, a != b)", self.app)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.log[0], "True True True")


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
            self.assertTrue((BUILDER_DIR / "static" / "builder" / "app" / name).exists(), name)


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
        from ..ai_designer import Invalid, normalize
        from ..management.commands.beispiel_einsatzplanung import DEFINITION

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

        from ..blocks import render_block

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
        from ..models import AuditEntry

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
        from ..models import Script

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
        from ..models import HomeWidget

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
        # Die Filterleiste der Beispiel-App ist richtig eingestellt (kein Hinweis statt Filter).
        self.assertNotContains(analyse, "Wähle mindestens ein Feld")
        self.assertContains(analyse, 'name="chargen.werk"')

        sim =self.client.get(reverse("page", args=[app.slug, "simulator"]))
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
        from ..models import DataQuery, Record

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


class ReportInboxTests(TestCase):
    """Berichte-Eingang: Formate aus n8n, Teams-Workflows, Graph und Copilot; Feldtyp HTML; Bilder; Feed."""

    def setUp(self):
        import base64

        from ..management.commands.beispiel_berichte import bar_chart_png
        from ..models import ApiKey

        call_command("beispiel_berichte", "--ohne-daten", verbosity=0)
        self.app = App.objects.get(slug="berichte")
        self.entity = self.app.entities.get(slug="berichte")
        self.write_key = ApiKey.issue(self.app, "n8n", can_write=True)[1]
        self.read_key = ApiKey.issue(self.app, "lesen", can_write=False)[1]
        self.png = bar_chart_png([1, 2, 3], width=30, height=20)
        self.png64 = base64.b64encode(self.png).decode()
        self.url = reverse("api_inbox", args=["berichte", "berichte"])

    def post(self, body, content_type="application/json", key=None, query=""):
        data = json.dumps(body) if not isinstance(body, (str, bytes)) else body
        return self.client.post(self.url + query, data, content_type=content_type,
                                HTTP_AUTHORIZATION=f"Bearer {key or self.write_key}")

    def last(self):
        return self.entity.records.order_by("-id").first().data

    def test_html_body_with_embedded_chart_and_query_values(self):
        from ..models import Attachment

        html = (f'<h2>Wochenbericht 📈</h2><p><b>71</b> Aufträge</p><img src="data:image/png;base64,{self.png64}" alt="Diagramm">'
                '<script>alert(1)</script><p onclick="x()">ok</p>')
        response = self.post(html, content_type="text/html", query="?agent=Vertrieb")
        self.assertEqual(response.status_code, 201, response.content)
        data = self.last()
        self.assertEqual(data["titel"], "Wochenbericht 📈")  # erste Überschrift wird Titel …
        self.assertNotIn("<h2>", data["inhalt"])  # … und steht nicht doppelt im Inhalt
        self.assertEqual(data["agent"], "Vertrieb")
        self.assertNotIn("script", data["inhalt"])
        self.assertNotIn("onclick", data["inhalt"])
        self.assertNotIn("data:image", data["inhalt"])
        stored = Attachment.objects.get(app=self.app)
        self.assertIn(f"/a/berichte/bild/{stored.sha256}.png", data["inhalt"])
        self.assertEqual(bytes(stored.data), self.png)
        self.assertEqual(response.json()["id"], self.entity.records.order_by("-id").first().pk)

    def test_teams_webhook_markdown_message_card_and_adaptive_card(self):
        self.assertEqual(self.post({"title": "Kurz", "text": "**Fett** und ✅\n\n- eins\n- zwei", "agent": "IT"}).status_code, 201)
        data = self.last()
        self.assertEqual((data["titel"], data["agent"]), ("Kurz", "IT"))
        self.assertIn("<strong>Fett</strong>", data["inhalt"])
        self.assertIn("<li>eins</li>", data["inhalt"])

        self.post({"@type": "MessageCard", "summary": "Alarm", "sections": [
            {"activityTitle": "Linie 2", "facts": [{"name": "Ausschuss", "value": "4,8 %"}],
             "images": [{"image": "https://example.com/chart.png"}]}],
            "potentialAction": [{"@type": "OpenUri", "name": "Öffnen", "targets": [{"uri": "https://example.com"}]}]})
        data = self.last()
        self.assertEqual(data["titel"], "Alarm")
        self.assertIn("<th>Ausschuss</th><td>4,8 %</td>", data["inhalt"])
        self.assertIn('src="https://example.com/chart.png"', data["inhalt"])
        self.assertIn('href="https://example.com"', data["inhalt"])

        self.post({"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
            "type": "AdaptiveCard", "body": [
                {"type": "TextBlock", "text": "Qualität ⚠️", "size": "large"},
                {"type": "FactSet", "facts": [{"title": "Werk", "value": "Hamburg"}]},
                {"type": "Image", "url": f"data:image/png;base64,{self.png64}", "altText": "Verlauf"},
                {"type": "Image", "url": "javascript:alert(1)"}]}}]})
        data = self.last()
        self.assertEqual(data["titel"], "Qualität ⚠️")
        self.assertIn("<th>Werk</th><td>Hamburg</td>", data["inhalt"])
        self.assertIn("/a/berichte/bild/", data["inhalt"])
        self.assertNotIn("javascript", data["inhalt"])

    def test_graph_message_with_hosted_contents(self):
        response = self.post({"subject": "Teams-Kanal", "body": {
            "contentType": "html", "content": '<p>Bild:</p><img src="../hostedContents/1/$value">'},
            "hostedContents": [{"@microsoft.graph.temporaryId": "1", "contentBytes": self.png64,
                                "contentType": "image/png"}]})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn("/a/berichte/bild/", self.last()["inhalt"])
        self.assertEqual(self.last()["titel"], "Teams-Kanal")

    def test_rejections(self):
        from .. import api

        self.assertEqual(self.post({"text": "x"}, key="falsch").status_code, 401)
        self.assertEqual(self.post({"text": "x"}, key=self.read_key).status_code, 403)
        self.assertEqual(self.post({"text": "   "}).status_code, 400)
        self.assertEqual(self.post("kein json").status_code, 400)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {self.write_key}").status_code, 405)
        with mock.patch.object(api, "MAX_INBOX_BYTES", 50):
            self.assertEqual(self.post({"text": "x" * 100}).status_code, 413)
        Field.objects.filter(entity=self.entity, type=Field.HTML).update(type=Field.LONGTEXT)
        self.assertEqual(self.post({"text": "x"}).status_code, 400)
        self.assertEqual(self.entity.records.count(), 0)

    def test_fake_image_and_svg_are_not_stored(self):
        import base64

        from ..models import Attachment

        svg = base64.b64encode(b'<svg onload="alert(1)"></svg>').decode()
        self.post({"title": "t", "text": f'<p>x</p><img src="data:image/png;base64,{svg}"><img src="data:image/svg+xml;base64,{svg}">'})
        self.assertFalse(Attachment.objects.exists())
        self.assertNotIn("data:", self.last()["inhalt"])

    def test_attachment_access_and_headers(self):
        from ..models import Attachment

        self.post({"title": "t", "text": f'<img src="data:image/png;base64,{self.png64}">'})
        url = reverse("attachment", args=["berichte", Attachment.objects.get().sha256 + ".png"])
        self.assertEqual(self.client.get(url).status_code, 302)  # nicht angemeldet
        self.client.force_login(User.objects.create_user("leser", password="x"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(response.content, self.png)
        other = App.objects.create(name="Andere", slug="andere", published=True)
        self.assertEqual(self.client.get(reverse("attachment", args=[other.slug, url.rsplit("/", 1)[1]])).status_code, 404)

    def test_html_field_in_api_form_list_and_detail(self):
        from ..blocks import display_value
        from ..scripting.ops import OpsError, save_record

        record = save_record(self.entity, {"titel": "Per API", "inhalt": "Nur **Markdown** 🙂"})
        self.assertIn("<strong>Markdown</strong>", record.data["inhalt"])
        field = self.entity.fields.get(key="inhalt")
        self.assertEqual(display_value(field, "<p>Hallo <b>Welt</b></p><ul><li>eins</li></ul>"), "Hallo Welt eins")
        with self.assertRaises(OpsError):
            save_record(self.entity, {"titel": "leer", "inhalt": "<script>x</script>"})  # Pflichtfeld bleibt leer

    def test_report_feed_block_with_source_filter(self):
        call_command("beispiel_berichte", "--neu", verbosity=0)
        self.client.force_login(User.objects.create_user("leser2", password="x"))
        response = self.client.get(reverse("page", args=["berichte", "feed"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "report-feed")
        self.assertContains(response, "Wochenbericht Vertrieb KW 48")
        self.assertContains(response, "<strong>12 Systeme</strong>")
        self.assertContains(response, "/a/berichte/bild/")
        self.assertContains(response, "berichte.agent=Copilot")
        self.assertNotContains(response, "Ausschuss über Grenzwert</h3>")  # Überschrift nicht doppelt
        filtered = self.client.get(reverse("page", args=["berichte", "feed"]), {"berichte.agent": "IT-Monitoring"})
        self.assertContains(filtered, "Nächtliche Prüfung")
        self.assertNotContains(filtered, "Wochenbericht Vertrieb")

    def test_openapi_describes_html_fields(self):
        spec = self.client.get(reverse("api_openapi", args=["berichte"]), HTTP_AUTHORIZATION=f"Bearer {self.read_key}").json()
        self.assertIn('"format": "html"', json.dumps(spec))
        inbox = spec["paths"]["/api/v1/berichte/berichte/eingang/"]["post"]
        self.assertEqual(inbox["operationId"], "berichte_bericht_ablegen")
        self.assertIn("text/html", inbox["requestBody"]["content"])

    def test_mcp_create_tool_converts_markdown(self):
        response = self.client.post(reverse("mcp", args=["berichte"]), json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_berichte", "arguments": {
                "titel": "Von Copilot", "agent": "Copilot", "inhalt": "**Fertig** 🎉"}}}),
            content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.write_key}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"].get("isError"), response.content)
        self.assertIn("<strong>Fertig</strong> 🎉", self.last()["inhalt"])


class WhatIfLiveTests(TestCase):
    """Data-Science-Beispiel: Der Simulator rechnet nach jedem gespeicherten Reglerwert neu."""

    def setUp(self):
        self.user = User.objects.create_user("analyst", password="x", is_staff=True)
        self.client.force_login(self.user)
        call_command("beispiel_datascience", verbosity=0)
        self.app = App.objects.get(slug="datascience")
        self.page = self.app.pages.get(slug="simulator")
        self.sliders = next(b for b in self.page.layout if b["type"] == "sliders")
        self.chart = next(b for b in self.page.layout if b["type"] == "spec_chart")
        self.temp = self.app.entities.get(slug="parameter").records.get(data__name="Temperatur (°C)")

    def block(self, block_id):
        return self.client.get(reverse("page_block", args=[self.app.slug, self.page.slug, block_id]))

    def test_page_has_live_slider_and_chart(self):
        response = self.client.get(reverse("page", args=[self.app.slug, self.page.slug]))
        self.assertContains(response, 'data-widget="sliders"')
        self.assertContains(response, 'data-reload-url="%s"' % reverse(
            "page_block", args=[self.app.slug, self.page.slug, self.sliders["id"]]))
        self.assertContains(response, "builder/widgets.js")
        self.assertContains(response, "spec-chart-block")

    def test_saved_slider_value_changes_prognosis_and_chart(self):
        before = self.block("bsimout").content.decode()
        response = self.client.post(
            reverse("block_action", args=[self.app.slug, self.page.slug, self.sliders["id"]]),
            data=json.dumps({"op": "set", "record": self.temp.pk, "value": "200"}),
            content_type="application/json")
        self.assertEqual(response.json(), {"ok": True, "value": 200})
        # Genau diese Bausteine lädt widgets.js nach jedem Speichern während des Ziehens nach.
        after = self.block("bsimout").content.decode()
        self.assertNotEqual(before, after)
        self.assertRegex(after, r"2[.,]46")
        self.assertContains(self.block(self.chart["id"]), "200")

    def test_widgets_script_saves_while_dragging(self):
        from django.contrib.staticfiles import finders

        source = Path(finders.find("builder/widgets.js")).read_text(encoding="utf-8")
        handler = source[source.index('document.addEventListener("input"'):]
        handler = handler[:handler.index("});")]
        self.assertIn("setTimeout", handler)  # mit Verzögerung, nicht bei jedem Pixel
        self.assertIn("refreshDependents", source)


class ProgressFeedbackTests(Base):
    """Ladebalken und Wartezustand: progress.js auf jeder Seite, Übersetzung vorhanden."""

    def test_progress_script_on_pages_and_login(self):
        self.assertContains(self.client.get(reverse("login")), "builder/progress")
        self.client.force_login(self.user)
        page = self.client.get(reverse("page", args=["inventar"]))
        self.assertContains(page, "builder/progress")
        html = page.content.decode()
        self.assertLess(html.index("builder/confirm"), html.index("builder/progress"))  # nach confirm.js

    def test_splash_markup_script_and_offline_cache(self):
        """Startbildschirm: Markup und Skript auf jeder Seite, Skript im Head vor dem Inhalt."""
        page = self.client.get(reverse("login")).content.decode()
        self.assertIn('class="bk-splash"', page)
        self.assertLess(page.index("builder/splash"), page.index("</head>"))
        self.assertNotIn("brand-logo", page[page.index('class="bk-splash"'):page.index("</svg>")])
        self.assertContains(self.client.get("/sw.js"), "builder/splash")
