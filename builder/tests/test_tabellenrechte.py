"""Tabellenrechte: Gruppen je Tabelle schränken ein, wer Einträge lesen und ändern darf."""

import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .. import versions
from ..blocks import make_block
from ..models import App, AuditEntry, Entity, Field, Page, Record
from ..scripting.ops import OpsError, TableOps


class TabellenrechteTests(TestCase):
    def setUp(self):
        self.controlling = Group.objects.create(name="Controlling")
        self.werk = Group.objects.create(name="Werk")
        self.app = App.objects.create(name="Werk", slug="werk", published=True)
        self.kosten = Entity.objects.create(app=self.app, name="Kosten", slug="kosten")
        Field.objects.create(entity=self.kosten, label="Betrag", key="betrag", type=Field.NUMBER, order=1)
        self.record = Record.objects.create(entity=self.kosten, data={"betrag": 4711})
        self.kosten.read_groups.add(self.controlling)
        self.page = Page.objects.create(app=self.app, title="Start", slug="start", order=1, layout=[
            make_block("table", entity="kosten"), make_block("form", entity="kosten")])
        self.werker = User.objects.create_user("werker", password="x")
        self.werker.groups.add(self.werk)
        self.controller = User.objects.create_user("controller", password="x")
        self.controller.groups.add(self.controlling)
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.app.created_by = self.designer
        self.app.save()

    def _entity(self):
        return Entity.objects.get(pk=self.kosten.pk)  # frisch geladen, ohne zwischengespeicherte Rechte

    def test_rights(self):
        entity = self._entity()
        self.assertFalse(entity.user_can_read(self.werker))
        self.assertTrue(entity.user_can_read(self.controller))
        self.assertTrue(entity.user_can_read(self.designer))  # Bearbeiter dürfen immer
        self.assertTrue(entity.user_can_write(self.werker))  # ohne Schreibgruppen: alle

    def test_blocks_hide_data_without_read_right(self):
        self.client.force_login(self.werker)
        html = self.client.get(reverse("page", args=["werk", "start"])).content.decode()
        self.assertNotIn("4711", html)
        self.assertIn("fehlt dir die Berechtigung", html)
        self.assertIn(reverse("record_create", args=["werk", "kosten"]), html)  # Formular: nur Schreibrecht nötig
        self.client.force_login(self.controller)
        self.assertContains(self.client.get(reverse("page", args=["werk", "start"])), "4711")

    def test_read_only_hides_change_links(self):
        self.kosten.write_groups.add(self.werk)
        self.client.force_login(self.controller)
        html = self.client.get(reverse("page", args=["werk", "start"])).content.decode()
        self.assertIn("4711", html)
        self.assertNotIn(reverse("record_edit", args=["werk", "kosten", self.record.pk]), html)
        self.assertNotIn(reverse("record_create", args=["werk", "kosten"]), html)
        self.assertEqual(self.client.get(reverse("record_create", args=["werk", "kosten"])).status_code, 403)

    def test_record_views_and_export(self):
        self.client.force_login(self.werker)
        edit = reverse("record_edit", args=["werk", "kosten", self.record.pk])
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.post(reverse("record_delete", args=["werk", "kosten", self.record.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("entity_export", args=["werk", "kosten"])).status_code, 403)
        # Anlegen ohne Leserecht geht (z. B. Meldungen, die nur das Controlling liest)
        response = self.client.post(reverse("record_create", args=["werk", "kosten"]), {"betrag": "5"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Record.objects.filter(entity=self.kosten).count(), 2)
        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(edit).status_code, 200)
        self.assertContains(self.client.get(reverse("entity_export", args=["werk", "kosten"])), "4711")

    def test_guests_cannot_read_restricted_tables(self):
        self.page.public = True
        self.page.save()
        html = self.client.get(reverse("page", args=["werk", "start"])).content.decode()
        self.assertNotIn("4711", html)

    def test_table_ops_and_script_bridge(self):
        ops = TableOps(self.app, user=self.werker, enforce_flags=True)
        with self.assertRaises(OpsError):
            ops.filter("kosten")
        self.assertEqual(ops.create("kosten", {"betrag": 1})["betrag"], 1)
        with self.assertRaises(OpsError):
            ops.update("kosten", self.record.pk, {"betrag": 1})
        # Python-Skripte (enforce_flags=False) schreiben Bearbeiter; sie bleiben uneingeschränkt
        self.assertEqual(len(TableOps(self.app, user=self.werker).filter("kosten")), 2)
        self.client.force_login(self.werker)
        response = self.client.post(reverse("script_bridge", args=["werk"]),
                                    json.dumps({"op": "table.filter", "args": {"table": "kosten"}}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("4711", response.content.decode())

    def test_designer_saves_rights_and_logs_change(self):
        self.client.force_login(self.designer)
        url = reverse("designer_entity", args=["werk", self.kosten.pk])
        self.assertContains(self.client.get(url), "read_groups")
        response = self.client.post(url, {
            "kind": "entity", "entity-name": "Kosten", "entity-allow_create": "on", "entity-allow_edit": "on",
            "entity-allow_delete": "on", "entity-read_groups": [self.controlling.pk],
            "entity-write_groups": [self.controlling.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self._entity().write_groups.values_list("name", flat=True)), ["Controlling"])
        entry = AuditEntry.objects.filter(target_type="entity", target_id=str(self.kosten.pk)).latest("pk")
        self.assertEqual(entry.changes["write_groups"], ["alle", "Controlling"])
        self.assertNotIn("read_groups", entry.changes)

    def test_versions_keep_table_rights(self):
        snapshot = versions.snapshot(self.app)
        entity = next(e for e in snapshot["entities"] if e["slug"] == "kosten")
        self.assertEqual(entity["read_groups"], ["Controlling"])
        changed = json.loads(json.dumps(snapshot))
        next(e for e in changed["entities"] if e["slug"] == "kosten")["read_groups"] = []
        self.assertTrue(versions.diff(snapshot, changed))
        versions.apply(self.app, changed)
        self.assertFalse(self._entity().read_groups.exists())
        versions.apply(self.app, snapshot)
        self.assertEqual(list(self._entity().read_groups.values_list("name", flat=True)), ["Controlling"])
        # Ältere Versionen ohne Tabellenrechte lassen die Rechte unverändert
        old = json.loads(json.dumps(snapshot))
        for item in old["entities"]:
            item.pop("read_groups"), item.pop("write_groups")
        versions.apply(self.app, old)
        self.assertTrue(self._entity().read_groups.exists())
