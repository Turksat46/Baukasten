"""Designer, eigene Bausteine, Mitbearbeitung, Versionen und Rückwärtskompatibilität."""

import json
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .. import hooks
from ..blocks import clean_layout, make_block
from ..models import App, Entity, Field, Record
from .base import BUILDER_DIR, Base


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

        js = (BUILDER_DIR / "static" / "builder" / "designer.js").read_text(encoding="utf-8")
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


class CustomBlockTests(Base):
    def test_html_block_lifecycle(self):
        from ..models import CustomBlock
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
        from ..models import CustomBlock
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


class VersionTests(Base):
    def test_save_change_restore(self):
        from ..models import AppVersion
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
        from ..models import AppVersion
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


class TutorialTests(Base):
    """Einführung „Deine erste App“ (builder/tutorial.py): einmal komplett durchspielen."""

    def coach(self):
        return self.client.get(reverse("designer_home")).context["coach"]

    def test_walkthrough_from_start_to_finish(self):
        from ..models import Script
        from .. import tutorial, versions
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
        from .. import versions
        data, notes = versions.upgrade(self.OLD_FILE)
        self.assertEqual(data["format"], versions.FORMAT)
        self.assertEqual(data["app"]["kind"], "app")
        self.assertEqual(data["scripts"][0]["timeout_minutes"], 30)
        self.assertIn("älteres Format", notes[0])
        self.assertIn("gibtsnichtmehr", notes[1])
        self.assertEqual(self.OLD_FILE["format"], "baukasten-app/1")  # Eingabe bleibt unverändert
        app = versions.import_app(self.OLD_FILE, self.designer)
        self.assertEqual(app.entities.get().fields.get().key, "name")
        # Unbekannte Bausteine bleiben gespeichert (Rückwärtskompatibilität), angezeigt wird nur „table“
        self.assertEqual([b["type"] for b in app.pages.get().layout], ["table", "gibtsnichtmehr"])
        self.assertEqual(len(app.import_notes), 2)
        # Neue Dateien tragen Format und Baukasten-Version
        snapshot = versions.snapshot(app)
        self.assertEqual(snapshot["format"], "baukasten-app/2")
        self.assertIn("baukasten_version", snapshot)

    def test_newer_or_foreign_files_are_rejected_clearly(self):
        from .. import versions
        with self.assertRaisesMessage(versions.InvalidSnapshot, "neueren Version des Baukastens"):
            versions.upgrade({**self.OLD_FILE, "format": "baukasten-app/99"})
        with self.assertRaisesMessage(versions.InvalidSnapshot, "keine exportierte App"):
            versions.upgrade({"format": "etwas-anderes/1", "app": {}})

    def test_old_stored_version_still_restores(self):
        from ..models import AppVersion
        old = AppVersion.objects.create(app=self.app, number=99, snapshot=self.OLD_FILE)
        self.client.force_login(self.designer)
        response = self.client.post(reverse("designer_version_restore", args=["inventar", old.pk]), follow=True)
        self.assertContains(response, "älteres Format")
        self.assertTrue(self.app.entities.filter(slug="dinge").exists())

    def test_upload_into_existing_app(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from ..models import AuditEntry
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


class CustomBlockEnhancementTests(TestCase):
    """Eigene Bausteine: typisierte Einstellungen, Live-Vorschau, Sanitizer-Report, Hooks & MCP."""

    def setUp(self):
        from ..models import DesignerToken

        self.designer = User.objects.create_user("bauherr", password="x", is_staff=True)
        self.token, self.raw_token = DesignerToken.issue(self.designer, "KI-Test")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"}

    def test_typed_and_json_setting_specs(self):
        from ..models import CustomBlock

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
        from ..sanitize import sanitize_html_report

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
        from ..blocks import all_types

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


class BackwardCompatibilityTests(Base):
    """Updates im laufenden Betrieb: Seiten aus älteren oder neueren Versionen verlieren nichts."""

    def stored_page(self):
        page = self.app.pages.get(slug="gerate")
        page.layout = [
            {"id": "h1", "type": "heading", "width": 12,
             "props": {"text": "Hallo", "level": "2", "farbe_aus_v2": "blau"}},
            {"id": "alt1", "type": "weg_baustein", "width": 6, "name": "alt",
             "props": {"geheim": 1, "liste": [1, 2]}},
        ]
        page.save()
        return page

    def post(self, url, layout, **extra):
        return self.client.post(url, json.dumps({"title": "Geräte", "layout": layout, **extra}),
                                content_type="application/json")

    def test_unknown_blocks_and_props_survive_save(self):
        """Ein Designer-Tab, der Baustein oder Einstellung nicht kennt, darf sie nicht löschen."""
        page = self.stored_page()
        self.client.force_login(self.designer)
        url = reverse("designer_page", args=["inventar", page.pk])
        sent = [
            {"id": "h1", "type": "heading", "width": 6, "props": {"text": "Neu", "level": "1"}},
            {"id": "alt1", "type": "weg_baustein", "width": 12, "props": {"geheim": 999}},  # Browser manipuliert
            {"id": "fremd", "type": "erfunden", "width": 12, "props": {"x": 1}},  # nie gespeichert gewesen
        ]
        data = self.post(url, sent).json()
        self.assertTrue(data["ok"])
        from django.conf import settings
        self.assertEqual(data["baukasten_version"], settings.BAUKASTEN_VERSION)
        page.refresh_from_db()
        heading, old = page.layout
        self.assertEqual(heading["props"], {"text": "Neu", "subtitle": "", "level": "1", "farbe_aus_v2": "blau"})
        self.assertEqual(old, {"id": "alt1", "type": "weg_baustein", "width": 12, "name": "alt",
                               "props": {"geheim": 1, "liste": [1, 2]}})  # gespeicherter Stand, neue Breite
        self.assertEqual(self.post(url, sent[:1]).status_code, 200)  # im Designer bewusst entfernt
        page.refresh_from_db()
        self.assertEqual([b["id"] for b in page.layout], ["h1"])

    def test_designer_and_preview_show_placeholder_page_skips_it(self):
        page = self.stored_page()
        self.client.force_login(self.designer)
        config = self.client.get(reverse("designer_page", args=["inventar", page.pk])).context["config"]
        self.assertIn("weg_baustein", [b["type"] for b in config["layout"]])
        self.assertTrue(config["baukasten_version"])
        preview = self.client.post(reverse("designer_page_preview", args=["inventar", page.pk]),
                                   json.dumps({"layout": page.layout}), content_type="application/json").json()
        self.assertIn("block-unknown", preview["blocks"]["alt1"])
        self.assertIn("weg_baustein", preview["blocks"]["alt1"])
        live = self.client.get(reverse("page", args=["inventar", page.slug]))
        self.assertEqual(live.status_code, 200)
        self.assertNotContains(live, "block-unknown")

    def test_app_file_keeps_unknown_blocks_with_limits(self):
        from ..versions import import_app, snapshot

        page = self.stored_page()
        data = snapshot(self.app)
        imported = import_app(data, self.designer, name_override="Kopie")
        layout = imported.pages.get(slug=page.slug).layout
        self.assertEqual([b["type"] for b in layout], ["heading", "weg_baustein"])
        self.assertEqual(layout[0]["props"]["farbe_aus_v2"], "blau")
        self.assertTrue(any("weg_baustein" in note for note in imported.import_notes))
        huge = clean_layout([{"id": "a", "type": "neu", "props": {"x": "y" * 30000}},
                             {"id": "b", "type": "<script>", "props": {}}], keep_unknown=True)
        self.assertEqual(huge, [{"id": "a", "type": "neu", "props": {}, "width": 12}])

    def test_shipped_blocks_and_props_stay_registered(self):
        """Gespeicherte Seiten verweisen auf diese Namen. Neu: python manage.py bausteinvertrag.
        Entfernen oder Umbenennen nur mit Datenmigration für die Seiten und bewusst in der Datei."""
        from ..blocks import CONTRACT_FILE, block_contract

        shipped = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
        current = block_contract()
        missing = sorted(f"{key}.{prop}" if prop else key for key, props in shipped.items()
                         for prop in ([None] if key not in current else sorted(set(props) - set(current[key]))))
        self.assertEqual(missing, [], "Diese Bausteine/Einstellungen stecken in gespeicherten Seiten und fehlen jetzt.")
        new = sorted(f"{key}.{prop}" for key, props in current.items() for prop in set(props) - set(shipped.get(key, [])))
        new += sorted(key for key in current if key not in shipped)
        self.assertEqual(new, [], "Neue Bausteine/Einstellungen eintragen: python manage.py bausteinvertrag")


class TourSeenTests(TestCase):
    """Die Führung merkt sich „gesehen“ pro Person auf dem Server, Gäste weiter nur im Browser."""

    def setUp(self):
        self.user = User.objects.create_user("tourist", password="x")
        self.client.force_login(self.user)

    def tour_span(self, response):
        html = response.content.decode()
        start = html.index('<span id="tour-id"')
        return html[start:html.index("</span>", start)]

    def test_state_comes_from_server_and_is_saved_per_user(self):
        from ..models import TourSeen

        span = self.tour_span(self.client.get(reverse("home")))
        self.assertIn('data-tour-id="start"', span)
        self.assertIn('data-seen="0"', span)
        self.assertIn('data-save-url="%s"' % reverse("tour_seen", args=["start"]), span)
        self.assertIn("data-csrf=", span)

        response = self.client.post(reverse("tour_seen", args=["start"]))
        self.assertEqual(response.status_code, 204)
        # Zweimal melden schadet nicht (z. B. Übernahme aus dem Browser und Ende der Führung).
        self.assertEqual(self.client.post(reverse("tour_seen", args=["start"])).status_code, 204)
        self.assertEqual(TourSeen.objects.filter(user=self.user, tour_id="start").count(), 1)
        self.assertIn('data-seen="1"', self.tour_span(self.client.get(reverse("home"))))

        # Andere Person: eigener Zustand.
        other = User.objects.create_user("neu", password="x")
        self.client.force_login(other)
        self.assertIn('data-seen="0"', self.tour_span(self.client.get(reverse("home"))))

    def test_endpoint_needs_post_login_csrf_and_known_tour(self):
        from ..models import TourSeen

        self.assertEqual(self.client.get(reverse("tour_seen", args=["start"])).status_code, 405)
        self.assertEqual(self.client.post(reverse("tour_seen", args=["gibtsnicht"])).status_code, 404)

        strict = self.client_class(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse("tour_seen", args=["start"])).status_code, 403)

        self.client.logout()
        self.assertEqual(self.client.post(reverse("tour_seen", args=["start"])).status_code, 302)
        self.assertFalse(TourSeen.objects.exists())

    def test_guests_keep_browser_storage(self):
        from django.contrib.auth.models import AnonymousUser
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        html = Template('{% load baukasten %}{% tour "start" %}').render(Context({"request": request}))
        self.assertIn('data-tour-id="start"', html)
        self.assertNotIn("data-save-url", html)
        self.assertNotIn("data-seen", html)

    def test_script_syncs_browser_value_once_and_on_end(self):
        from django.contrib.staticfiles import finders

        source = Path(finders.find("builder/tour.js")).read_text(encoding="utf-8")
        self.assertIn("info.saveUrl", source)
        self.assertIn("X-CSRFToken", source)
        # Ein im Browser gemerkter Wert wird an den Server gemeldet.
        self.assertIn("if (seenInBrowser()) {", source)
