"""Sprachwahl und Übersetzungen der Oberfläche und der Apps."""

import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from ..blocks import make_block
from ..models import App, Page
from .base import Base


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
        from .. import app_i18n
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
        from .. import versions
        version = versions.create_version(self.app, self.designer, "mit Übersetzung")
        self.app.translations = {}
        self.app.save()
        versions.restore(version, self.designer)
        self.app.refresh_from_db()
        self.assertEqual(self.app.translations["en"]["Geräte"], "Devices")

    def test_scripts_get_language_and_translations(self):
        from django.utils import translation

        from ..scripting.python import run
        code = 'print(user["language"], app.t("Geräte"), app.t("unbekannt"))'
        with translation.override("en"):
            result = run(code, self.app, user=self.user)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.log[0], "en Devices unbekannt")
        with translation.override("de"):
            self.assertEqual(run(code, self.app, user=self.user).log[0], "de Geräte unbekannt")


class InterfaceTranslationTests(TestCase):
    """Englische Oberfläche: jeder Text hat eine Übersetzung (manage.py uebersetzungen)."""

    def test_every_text_is_translated(self):
        from ..management.commands.uebersetzungen import missing

        gaps = {domain: [f"{where[0]}: {msgid}" for _c, msgid, _p, where, _k in items]
                for domain, items in missing("en").items() if items}
        self.assertEqual(gaps, {}, "Fehlende Übersetzungen: python manage.py uebersetzungen ergaenzen, "
                                   "übersetzen, dann kompilieren.")

    def test_compiled_files_match_po(self):
        import gettext

        from ..management.commands.uebersetzungen import BUILDER, compile_mo

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
