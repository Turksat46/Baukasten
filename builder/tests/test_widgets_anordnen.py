"""Startseiten-Widgets anordnen: Reihenfolge und Breite je Person speichern."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ..blocks import make_block
from ..models import App, HomeWidget, Page


class WidgetsAnordnenTests(TestCase):
    def setUp(self):
        self.app = App.objects.create(name="Werk", slug="werk", published=True)
        self.blocks = [make_block("stat", label=f"Kennzahl {i}") for i in range(3)]
        self.page = Page.objects.create(app=self.app, title="Start", slug="start", order=1, layout=self.blocks)
        self.user = User.objects.create_user("werker", password="x")
        self.other = User.objects.create_user("andere", password="x")
        self.client.force_login(self.user)
        for block in self.blocks:
            self.client.post(reverse("home_widget_add"), {"target": f"{self.page.pk}:{block['id']}"})
        self.widgets = list(HomeWidget.objects.filter(user=self.user).order_by("order", "id"))

    def _save(self, items):
        return self.client.post(reverse("home_widgets_arrange"), json.dumps({"widgets": items}),
                                content_type="application/json")

    def test_new_widgets_are_appended(self):
        self.assertEqual([w.block_id for w in self.widgets], [b["id"] for b in self.blocks])
        self.assertEqual([w.order for w in self.widgets], [0, 1, 2])

    def test_order_and_width_are_saved(self):
        a, b, c = self.widgets
        response = self._save([{"id": c.pk, "width": 12}, {"id": a.pk, "width": 8}, {"id": b.pk, "width": 5}])
        self.assertEqual(response.status_code, 200)
        saved = list(HomeWidget.objects.filter(user=self.user).order_by("order"))
        self.assertEqual([w.pk for w in saved], [c.pk, a.pk, b.pk])
        self.assertEqual([w.width for w in saved], [12, 8, b.width])  # ungültige Breite bleibt unverändert
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn(f'data-widget-id="{c.pk}" data-width="12"', html)
        self.assertLess(html.index(f'data-widget-id="{c.pk}"'), html.index(f'data-widget-id="{a.pk}"'))

    def test_missing_widgets_move_to_the_end(self):
        a, b, c = self.widgets
        self._save([{"id": c.pk}])
        self.assertEqual(list(HomeWidget.objects.filter(user=self.user).order_by("order", "id")
                              .values_list("pk", flat=True))[0], c.pk)

    def test_foreign_widgets_and_bad_data_are_ignored(self):
        foreign = HomeWidget.objects.create(user=self.other, page=self.page, block_id=self.blocks[0]["id"],
                                            width=4, order=7)
        self.assertEqual(self._save([{"id": foreign.pk, "width": 12}, "x", {"id": "1"}]).status_code, 200)
        foreign.refresh_from_db()
        self.assertEqual((foreign.width, foreign.order), (4, 7))
        self.assertEqual(self.client.post(reverse("home_widgets_arrange"), "kein json",
                                          content_type="application/json").status_code, 400)
        self.assertEqual(self._save("x").status_code, 400)
        self.assertEqual(self.client.get(reverse("home_widgets_arrange")).status_code, 405)

    def test_home_shows_arrange_controls(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("data-widget-arrange", html)
        self.assertIn('data-size="8"', html)
