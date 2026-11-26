"""Anmeldung, Keycloak, Gruppen, Profil und Einwilligungen."""

from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import App
from .base import Base


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
        from ..auth import KeycloakBackend
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
        from ..models import can_design
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
        from ..auth import KeycloakBackend
        user = KeycloakBackend().create_user({"preferred_username": "kc", "groups": ["/Labor"]})
        self.assertEqual(sorted(user.groups.values_list("name", flat=True)), ["Labor", "Viewer"])

    def test_app_restricted_to_viewer_is_open_to_everyone(self):
        app = App.objects.create(name="Für alle", published=True)
        app.groups.add(Group.objects.get_or_create(name="Viewer")[0])
        user = User.objects.create_user("jeder", password="x")
        self.assertTrue(app.user_can_use(user))


class ProfileTests(Base):
    def test_profile_shows_own_things(self):
        from ..models import ApiKey, Script
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
        from ..models import ApiKey
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
