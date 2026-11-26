"""Rechte-Matrix: jede Rolle gegen jeden Zugriffsweg (ADR 0012).

Für jede Zelle gilt dreierlei zugleich: die erwartete Antwort aus der Tabelle unten, die Antwort von
policy.darf() und das, was der echte Zugriffsweg (HTTP) tut. So fällt auf, wenn eine Ansicht an der
Policy vorbei prüft oder die Policy etwas anderes sagt als die Oberfläche.

Neue Zugriffswege: Aktion in builder/policy.py, Zeile in ERWARTET und ein Eintrag in _http().
"""
import json

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import TestCase
from django.urls import reverse

from .. import policy
from ..blocks import make_block
from ..models import App, Entity, Field, Page, Record, Script

ROLLEN = ["gast", "fremd", "werker", "controller", "leitung", "designer"]

# (Aktion, Objekt): erlaubte Rollen
ERWARTET = {
    (policy.SEHEN, "seite_start"): {"werker", "controller", "leitung", "designer"},
    (policy.SEHEN, "seite_kosten"): {"controller", "designer"},
    (policy.SEHEN, "seite_oeffentlich"): set(ROLLEN),
    (policy.LESEN, "kosten"): {"controller", "leitung", "designer"},
    (policy.ANLEGEN, "kosten"): {"controller", "designer"},
    (policy.AENDERN, "kosten"): {"controller", "designer"},
    (policy.LOESCHEN, "kosten"): {"controller", "designer"},
    (policy.EXPORTIEREN, "kosten"): {"controller", "leitung", "designer"},
    (policy.IMPORTIEREN, "kosten"): {"controller", "designer"},
    (policy.LESEN, "meldungen"): {"controller", "designer"},
    (policy.ANLEGEN, "meldungen"): set(ROLLEN),  # Formular auf öffentlicher Seite: auch Gäste
    (policy.AENDERN, "meldungen"): {"controller", "designer"},
    (policy.EXPORTIEREN, "meldungen"): {"controller", "designer"},
    (policy.BENUTZEN, "app"): {"werker", "controller", "leitung", "designer"},
    (policy.BEARBEITEN, "app"): {"designer"},
    (policy.AUSFUEHREN, "skript_oeffentlich"): set(ROLLEN),
    (policy.AUSFUEHREN, "skript_intern"): {"werker", "controller", "leitung", "designer"},
}


class RechteMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        werk = Group.objects.create(name="Werk")
        controlling = Group.objects.create(name="Controlling")
        leitung = Group.objects.create(name="Werksleitung")
        cls.users = {"gast": AnonymousUser()}
        for name, groups in (("fremd", []), ("werker", [werk]), ("controller", [werk, controlling]),
                             ("leitung", [werk, leitung])):
            user = User.objects.create_user(name, password="x")
            user.groups.set(groups)
            cls.users[name] = user
        cls.users["designer"] = User.objects.create_user("designer", password="x", is_staff=True)

        app = App.objects.create(name="Werk", slug="werk", published=True, created_by=cls.users["designer"])
        app.groups.add(werk)
        kosten = Entity.objects.create(app=app, name="Kosten", slug="kosten")
        meldungen = Entity.objects.create(app=app, name="Meldungen", slug="meldungen")
        for entity in (kosten, meldungen):
            Field.objects.create(entity=entity, label="Text", key="text", type=Field.TEXT, order=1)
        kosten.read_groups.set([controlling, leitung])
        kosten.write_groups.set([controlling])
        meldungen.read_groups.set([controlling])
        start = Page.objects.create(app=app, title="Start", slug="start", order=1, layout=[make_block("text", text="Hallo")])
        seite_kosten = Page.objects.create(app=app, title="Kosten", slug="kosten", order=2,
                                           layout=[make_block("table", entity="kosten")])
        seite_kosten.groups.add(controlling)
        oeffentlich = Page.objects.create(app=app, title="Melden", slug="melden", order=3, public=True, layout=[
            make_block("form", entity="meldungen"),
            make_block("button", label="Danke", target="script", script="danke")])
        cls.objects = {
            "app": app, "kosten": kosten, "meldungen": meldungen, "seite_start": start,
            "seite_kosten": seite_kosten, "seite_oeffentlich": oeffentlich,
            "skript_oeffentlich": Script.objects.create(app=app, name="Danke", slug="danke", language=Script.PYTHON,
                                                       trigger=Script.BUTTON, code="pass"),
            "skript_intern": Script.objects.create(app=app, name="Intern", slug="intern", language=Script.PYTHON,
                                                  trigger=Script.BUTTON, code="pass"),
        }

    def _login(self, rolle):
        self.client.logout()
        if rolle != "gast":
            self.client.force_login(self.users[rolle])

    def _obj(self, key):
        # frisch laden: Rechte werden je Objekt zwischengespeichert
        obj = self.objects[key]
        return type(obj).objects.get(pk=obj.pk)

    def _http(self, action, key):
        """Ergebnis des echten Zugriffswegs: True (erlaubt), False (abgelehnt) oder None (kein Weg)."""
        obj = self.objects[key]
        if action == policy.SEHEN:
            return self._ok(self.client.get(reverse("page", args=["werk", obj.slug])))
        if isinstance(obj, Entity):
            if action == policy.LESEN:
                if self.client.session.get("_auth_user_id") is None:
                    return None  # Skript-Brücke nur für Angemeldete; Gäste lesen nur über Bausteine
                response = self.client.post(reverse("script_bridge", args=["werk"]), json.dumps(
                    {"op": "table.filter", "args": {"table": obj.slug}}), content_type="application/json")
                return response.status_code == 200 if response.status_code in (200, 400) else self._ok(response)
            if action == policy.ANLEGEN:
                return self._ok(self.client.get(reverse("record_create", args=["werk", obj.slug])))
            if action == policy.AENDERN:
                record = Record.objects.create(entity=obj, data={"text": "a"})
                return self._ok(self.client.get(reverse("record_edit", args=["werk", obj.slug, record.pk])))
            if action == policy.LOESCHEN:
                record = Record.objects.create(entity=obj, data={"text": "a"})
                self.client.post(reverse("record_delete", args=["werk", obj.slug, record.pk]))
                return not Record.objects.filter(pk=record.pk).exists()
            if action == policy.EXPORTIEREN:
                return self._ok(self.client.get(reverse("entity_export", args=["werk", obj.slug])))
            if action == policy.IMPORTIEREN:
                return self._ok(self.client.get(reverse("entity_import", args=["werk", obj.slug])))
        if action == policy.BENUTZEN:
            return self._ok(self.client.get(reverse("api_docs", args=["werk"])))
        if action == policy.BEARBEITEN:
            return self._ok(self.client.get(reverse("designer_app", args=["werk"])))
        return None  # Skripte: Ausführen startet einen Kindprozess, hier nur die Policy

    @staticmethod
    def _ok(response):
        if response.status_code == 200:
            return True
        if response.status_code == 403 or (response.status_code == 302 and "/login/" in response["Location"]):
            return False
        raise AssertionError(f"Unerwartete Antwort {response.status_code}")

    def test_matrix(self):
        for (action, key), allowed in ERWARTET.items():
            for rolle in ROLLEN:
                with self.subTest(rolle=rolle, aktion=action, objekt=key):
                    expected = rolle in allowed
                    self.assertEqual(policy.darf(self.users[rolle], action, self._obj(key)), expected, "policy")
                    self._login(rolle)
                    http = self._http(action, key)
                    if http is not None:
                        self.assertEqual(http, expected, "HTTP")

    def test_page_lists_follow_policy(self):
        app = self.objects["app"]
        for rolle in ROLLEN:
            with self.subTest(rolle=rolle):
                listed = set(policy.sichtbare_seiten(self.users[rolle], self._obj("app")).values_list("slug", flat=True))
                visible = {p.slug for p in app.pages.all() if policy.darf(self.users[rolle], policy.SEHEN, p)}
                self.assertEqual(listed, visible)

    def test_unknown_combinations_are_errors(self):
        with self.assertRaises(ValueError):
            policy.darf(self.users["werker"], policy.LESEN, self.objects["app"])
        with self.assertRaises(ValueError):
            policy.darf(self.users["werker"], policy.LESEN)
        with self.assertRaises(ValueError):
            policy.darf(self.users["werker"], policy.LESEN, object())

    def test_flags_override_groups(self):
        kosten = self._obj("kosten")
        kosten.allow_create = kosten.allow_edit = kosten.allow_delete = False
        kosten.save()
        for action in (policy.ANLEGEN, policy.AENDERN, policy.LOESCHEN, policy.IMPORTIEREN):
            with self.subTest(aktion=action):
                self.assertFalse(policy.darf(self.users["controller"], action, self._obj("kosten")))
        self.assertTrue(policy.darf(self.users["controller"], policy.SCHREIBEN, self._obj("kosten")))
