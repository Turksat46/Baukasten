"""Eigene Fehlerseite 403: sagt, was fehlt, wer helfen kann, und führt zurück."""

from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ..models import App, Page
from ..views import permission_denied


class FehlerseiteTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("eigentuemer", password="x", first_name="Petra", last_name="Planer",
                                              is_staff=True)
        self.app = App.objects.create(name="Werk", slug="werk", published=True, created_by=self.owner)
        Page.objects.create(app=self.app, title="Start", slug="start", order=1)
        kosten = Page.objects.create(app=self.app, title="Kosten", slug="kosten", order=2)
        kosten.groups.add(Group.objects.create(name="Controlling"))
        self.werker = User.objects.create_user("werker", password="x")

    def test_page_names_app_owner_and_way_back(self):
        self.client.force_login(self.werker)
        response = self.client.get(reverse("page", args=["werk", "kosten"]))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, "Dafür fehlt dir die Berechtigung", status_code=403)
        self.assertContains(response, "Petra Planer", status_code=403)
        self.assertContains(response, f'href="{reverse("page", args=["werk"])}"', status_code=403)

    def test_no_link_to_app_without_app_access(self):
        self.app.groups.add(Group.objects.create(name="Werksleitung"))
        self.client.force_login(self.werker)
        response = self.client.get(reverse("page", args=["werk", "start"]))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, f'href="{reverse("page", args=["werk"])}"', status_code=403)
        self.assertContains(response, reverse("home"), status_code=403)

    def test_without_app(self):
        request = RequestFactory().get("/irgendwo/")
        request.user = self.werker
        response = permission_denied(request)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Frag deine Verwaltung", response.content.decode())
