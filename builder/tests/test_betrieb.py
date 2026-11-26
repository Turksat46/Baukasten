"""Verwaltung, Hilfe, Kennzahlen, Änderungsprotokoll, Einstellungen, Release Notes, Alarme."""

import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from ..blocks import make_block
from ..models import App, Entity, Field, Page, Record
from .base import Base


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
        from ..models import ApiKey
        ApiKey.issue(self.app, "k")
        from ..versions import create_version
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


class AdminLinkTests(Base):
    def test_admin_link_only_for_staff(self):
        self.client.force_login(self.designer)  # is_staff
        self.assertContains(self.client.get(reverse("home")), 'href="/admin/"')
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), 'href="/admin/"')


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
        from ..models import Script, ScriptRun
        from ..scripting.worker import alive
        cache.clear()
        auto = App.objects.create(name="Nacht", kind=App.AUTOMATION)
        script = Script.objects.create(app=auto, name="Lauf", trigger="manual", code="pass",
                                       running_since=timezone.now(), heartbeat_at=timezone.now())
        ScriptRun.objects.create(script=script, trigger="manual", status="error", ok=False)
        def get():
            return self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer geheim").content.decode()
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
        from ..models import AuditEntry
        return list(AuditEntry.objects.filter(**filters).order_by("id"))

    def test_records_via_form_with_person_and_changes(self):
        from ..models import AuditEntry
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
        from ..models import ApiKey
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
        from .. import versions
        from ..models import AuditEntry
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
        from ..models import AuditEntry, DesignerToken
        from ..mcp_designer import EXAMPLE
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
        from .. import audit
        from ..admin import AuditEntryAdmin
        from ..models import AuditEntry
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
        from ..models import AuditEntry
        self.assertFalse(AuditEntry.objects.filter(app=self.app).exists())  # Base.setUp ruft demo auf


class PlatformSettingsTests(TestCase):
    """Fachliche Einstellungen unter /admin/ (builder/platform.py)."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = User.objects.create_superuser("chef", password="x")

    @override_settings(BAUKASTEN_PUBLIC_RATE=120)
    def test_database_value_wins_and_takes_effect_without_restart(self):
        from .. import platform
        from ..models import AuditEntry, PlatformSettings
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
        from ..models import ReleaseNote
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

    def test_notes_from_changelog_and_login_required(self):
        """migrate gleicht die Release Notes mit CHANGELOG.md ab (post_migrate)."""
        from ..models import ReleaseNote
        from ..release_notes import OLD_SEED_TITLE, UNRELEASED

        note = ReleaseNote.objects.get(version="1.0.0")
        self.assertTrue(note.published)
        self.assertEqual(note.title, "Erste Version: Apps bauen, automatisieren und mit KI erweitern")
        self.assertIn("Fachabteilungen bauen ihre internen Apps", note.body)
        self.assertFalse(ReleaseNote.objects.get(version=UNRELEASED).published)  # Entwurf für Verwalter
        self.assertFalse(ReleaseNote.objects.filter(title=OLD_SEED_TITLE).exists())  # alter Entwurf aufgeräumt
        self.assertEqual(self.client.get(reverse("about")).status_code, 302)

    def test_changelog_matches_running_version(self):
        """Fällt um, wenn BAUKASTEN_VERSION erhöht wird, ohne den CHANGELOG-Abschnitt anzulegen (oder umgekehrt)."""
        from django.conf import settings

        from ..release_notes import check, read

        self.assertEqual(check(read(), settings.BAUKASTEN_VERSION), [])


class ReleaseNotesFromChangelogTests(TestCase):
    """Eine Quelle für Release Notes: CHANGELOG.md → /ueber/, Prüfung und GitHub-Release."""

    CHANGELOG = """# Änderungen

Einleitung.

## Unveröffentlicht

**Kurz gesagt:** Bald kommt mehr

### Neu
- etwas Technisches

## 1.1.0 – 2026-11-25

**Kurz gesagt:** Berichte aus n8n und Teams.

### Für Nutzer
- **Berichte-Feed** für alle 📰

### Neu
- `api.inbox` mit `raw=True`

## 1.0.0 – 2026-11-17

Erste Version.

### Apps bauen
- Tabellen
"""

    def write(self, text):

        folder = tempfile.mkdtemp(prefix="changelog-")
        path = Path(folder) / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_parse_title_user_part_and_fallback(self):
        from datetime import date

        from ..release_notes import UNRELEASED, parse

        drafts, new, first = parse(self.CHANGELOG)
        self.assertEqual((drafts.version, drafts.released_on, drafts.title), (UNRELEASED, None, "Bald kommt mehr"))
        self.assertEqual((new.version, new.released_on), ("1.1.0", date(2026, 11, 25)))
        self.assertEqual(new.title, "Berichte aus n8n und Teams")
        self.assertEqual(new.body, "- **Berichte-Feed** für alle 📰")  # nur „Für Nutzer“
        self.assertIn("api.inbox", new.section)  # GitHub-Release: ganzer Abschnitt
        self.assertEqual(first.title, "Erste Version")  # ohne „Kurz gesagt“: erster Satz
        self.assertIn("### Apps bauen", first.body)  # ohne „Für Nutzer“: alle Unterabschnitte

    def test_check_finds_mismatches(self):
        from ..release_notes import check, parse

        releases = parse(self.CHANGELOG)
        self.assertEqual(check(releases, "1.1.0"), [])
        self.assertIn("BAUKASTEN_VERSION ist 1.2.0", check(releases, "1.2.0")[0])
        swapped = self.CHANGELOG.replace("## 1.1.0 – 2026-11-25", "## 0.9.0 – 2026-11-25")
        self.assertTrue(any("Reihenfolge" in p for p in check(parse(swapped), "0.9.0")))
        broken = self.CHANGELOG.replace("## 1.0.0 – 2026-11-17", "## Version eins")
        self.assertTrue(any("Überschrift" in p for p in check(parse(broken), "1.1.0")))
        untitled = self.CHANGELOG.replace("**Kurz gesagt:** Berichte aus n8n und Teams.\n", "")
        self.assertTrue(any("Kurz gesagt" in p for p in check(parse(untitled), "1.1.0")))

    def test_sync_publishes_up_to_running_version_and_keeps_own_notes(self):
        from ..models import ReleaseNote
        from ..release_notes import UNRELEASED, sync

        ReleaseNote.objects.all().delete()
        own = ReleaseNote.objects.create(version="Wartung", title="Samstag Wartung", published=True)
        path = self.write(self.CHANGELOG)
        self.assertEqual(sync("1.0.0", path), (3, 0))
        self.assertTrue(ReleaseNote.objects.get(version="1.0.0").published)
        self.assertFalse(ReleaseNote.objects.get(version="1.1.0").published)  # noch nicht ausgerollt
        self.assertFalse(ReleaseNote.objects.get(version=UNRELEASED).published)
        self.assertEqual(sync("1.1.0", path), (0, 1))  # neue Version ausgerollt: jetzt veröffentlicht
        self.assertTrue(ReleaseNote.objects.get(version="1.1.0").published)
        self.assertEqual(sync("1.1.0", path), (0, 0))
        own.refresh_from_db()
        self.assertEqual(own.title, "Samstag Wartung")
        ReleaseNote.objects.filter(version="1.1.0").update(title="von Hand geändert")
        sync("1.1.0", path)
        self.assertEqual(ReleaseNote.objects.get(version="1.1.0").title, "Berichte aus n8n und Teams")
        self.assertEqual(sync("1.1.0", self.write("") .parent / "fehlt.md"), (0, 0))  # ohne Datei: nichts tun

    def test_admin_shows_changelog_notes_read_only(self):
        from ..models import ReleaseNote

        boss = User.objects.create_superuser("chef2", password="x")
        self.client.force_login(boss)
        note = ReleaseNote.objects.get(version="1.0.0")
        page = self.client.get(reverse("admin:builder_releasenote_change", args=[note.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="title"')
        listing = self.client.get(reverse("admin:builder_releasenote_changelist"))
        self.assertContains(listing, "CHANGELOG.md")

    def test_command_and_standalone_script(self):
        import subprocess
        import sys
        from io import StringIO

        from django.conf import settings

        out = StringIO()
        call_command("release_notes", "pruefen", stdout=out)
        self.assertIn("passen zusammen", out.getvalue())
        out = StringIO()
        call_command("release_notes", "abschnitt", "1.0.0", stdout=out)
        self.assertIn("Für Nutzer", out.getvalue())
        result = subprocess.run([sys.executable, "-m", "builder.release_notes", "titel", settings.BAUKASTEN_VERSION],
                                capture_output=True, text=True, encoding="utf-8", cwd=settings.BASE_DIR)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


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
        from .. import versions

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
        from ..models import Script

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
        from .. import alerts, platform
        from ..models import PlatformSettings

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
