"""Seitenrechte: Gruppen je Seite schränken ein, wer eine Seite innerhalb einer App sieht."""

import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .. import versions
from ..blocks import make_block
from ..models import App, AuditEntry, Entity, Field, HomeWidget, Page, Record


class SeitenrechteTests(TestCase):
    def setUp(self):
        self.controlling = Group.objects.create(name="Controlling")
        self.app = App.objects.create(name="Werk", slug="werk", published=True)
        entity = Entity.objects.create(app=self.app, name="Kosten", slug="kosten")
        Field.objects.create(entity=entity, label="Betrag", key="betrag", type=Field.NUMBER, order=1)
        Record.objects.create(entity=entity, data={"betrag": 42})
        self.start = Page.objects.create(app=self.app, title="Start", slug="start", order=1, layout=[
            make_block("text", text="Willkommen"), make_block("pagelinks")])
        stat = make_block("stat", label="Kosten", entity="kosten")
        self.stat_id = stat["id"]
        self.kosten = Page.objects.create(app=self.app, title="Kosten", slug="kosten", order=2, layout=[stat])
        self.kosten.groups.add(self.controlling)
        self.werker = User.objects.create_user("werker", password="x")
        self.controller = User.objects.create_user("controller", password="x")
        self.controller.groups.add(self.controlling)
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.app.created_by = self.designer
        self.app.save()

    def _get(self, user, *args):
        self.client.force_login(user)
        return self.client.get(reverse("page", args=["werk", *args]))

    def test_page_is_only_visible_to_its_groups(self):
        self.assertEqual(self._get(self.werker, "kosten").status_code, 403)
        self.assertEqual(self._get(self.controller, "kosten").status_code, 200)
        self.assertEqual(self._get(self.designer, "kosten").status_code, 200)  # Bearbeiter sehen alles
        self.assertTrue(self.start.user_can_view(self.werker))  # ohne Gruppen: alle mit App-Zugriff

    def test_menu_and_page_links_hide_forbidden_pages(self):
        url = reverse("page", args=["werk", "kosten"])
        self.assertNotContains(self._get(self.werker, "start"), url)
        self.assertContains(self._get(self.controller, "start"), url)

    def test_home_page_is_first_visible_page(self):
        self.start.groups.add(self.controlling)
        response = self._get(self.werker)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Willkommen")
        self.assertContains(self._get(self.controller), "Willkommen")

    def test_single_block_and_widgets_respect_page_rights(self):
        self.client.force_login(self.werker)
        block_url = reverse("page_block", args=["werk", "kosten", self.stat_id])
        self.assertEqual(self.client.get(block_url).status_code, 403)
        response = self.client.post(reverse("home_widget_add"), {"target": f"{self.kosten.pk}:{self.stat_id}"})
        self.assertEqual(response.status_code, 403)
        # Ein schon angepinntes Widget verschwindet, wenn die Seite gesperrt wird
        HomeWidget.objects.create(user=self.werker, page=self.kosten, block_id=self.stat_id, title="Kosten")
        home = self.client.get(reverse("home")).content.decode()
        self.assertNotIn(block_url, home)
        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(block_url).status_code, 200)

    def test_public_page_ignores_groups(self):
        self.kosten.public = True
        self.kosten.save()
        self.assertEqual(self._get(self.werker, "kosten").status_code, 200)

    def test_designer_saves_groups_and_logs_change(self):
        self.client.force_login(self.designer)
        url = reverse("designer_page", args=["werk", self.start.pk])
        response = self.client.post(url, json.dumps({
            "title": "Start", "layout": self.start.layout, "groups": [str(self.controlling.pk), "x", 99999]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(self.start.groups.values_list("name", flat=True)), ["Controlling"])
        entry = AuditEntry.objects.filter(target_type="page", target_id=str(self.start.pk)).latest("pk")
        self.assertEqual(entry.changes["groups"], ["alle", "Controlling"])
        # Ohne „groups“ (ältere Designer-Stände) bleibt die Auswahl erhalten
        self.client.post(url, json.dumps({"title": "Start", "layout": self.start.layout}),
                         content_type="application/json")
        self.assertTrue(self.start.groups.exists())
        self.assertContains(self.client.get(url), 'name="page-group"')

    def test_versions_keep_page_groups(self):
        snapshot = versions.snapshot(self.app)
        self.assertEqual(next(p for p in snapshot["pages"] if p["slug"] == "kosten")["groups"], ["Controlling"])
        changed = json.loads(json.dumps(snapshot))
        next(p for p in changed["pages"] if p["slug"] == "kosten")["groups"] = []
        self.assertTrue(versions.diff(snapshot, changed))
        versions.apply(self.app, snapshot)
        restored = self.app.pages.get(slug="kosten")
        self.assertEqual(list(restored.groups.values_list("name", flat=True)), ["Controlling"])
