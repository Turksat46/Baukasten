"""Skripte normaler Apps, HTTP-Aufrufe und Automatisierungen."""

import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from ..blocks import make_block
from ..models import App, Entity, Field, Page, Record
from ..services import HttpNotAllowed, http_request
from .base import Base


class HttpTests(Base):
    def test_host_must_be_allowed(self):
        with self.assertRaises(HttpNotAllowed):
            http_request("GET", "https://intern.example/api")
        with self.assertRaises(HttpNotAllowed):
            http_request("GET", "file:///etc/passwd")

    @override_settings(BAUKASTEN_HTTP_ALLOWED_HOSTS=["api.example.com"])
    def test_http_block_renders_json_list(self):
        page = Page.objects.create(app=self.app, title="Extern", layout=[
            make_block("http", label="Tickets", url="https://api.example.com/tickets", path="items"),
        ])
        payload = {"items": [{"nr": 1, "titel": "Drucker <defekt>"}, {"nr": 2, "titel": "VPN"}]}
        self.client.force_login(self.user)
        with mock.patch("builder.blocks.http_json", return_value=payload) as fake:
            response = self.client.get(reverse("page", args=["inventar", page.slug]))
        fake.assert_called_once()
        self.assertContains(response, "Drucker &lt;defekt&gt;")
        self.assertContains(response, "VPN")


class PythonScriptTests(Base):
    def run_code(self, code, **kwargs):
        from ..scripting import python
        return python.run(code, self.app, **kwargs)

    def test_table_access_and_ui(self):
        result = self.run_code(
            't = app.table("gerate")\n'
            'neu = t.create(bezeichnung="Skriptgerät", kategorie="IT", preis=10)\n'
            't.update(neu["id"], standort="Lager")\n'
            'print(t.count(), t.count(kategorie="IT"), round(t.sum("preis"), 2), t.get(neu["id"])["standort"])\n'
            't.delete(neu["id"])\n'
            'ui.set("anzahl", value=t.count(), label="Geräte")\n'
            'message("fertig")\n')
        self.assertTrue(result.ok, result.error_text())
        self.assertEqual(result.log, ["7 4 10198.4 Lager"])
        self.assertEqual(result.ui, {"anzahl": {"value": 6, "label": "Geräte"}})
        self.assertEqual(result.messages, ["fertig"])
        self.assertEqual(Record.objects.filter(entity=self.entity).count(), 6)

    def test_errors_and_limits(self):
        cases = {
            "import os": "nicht verfügbar",
            'open("/etc/passwd")': "open",
            "().__class__": "invalid attribute",
            'x = "{0}".format(1)': "format",
            "x = 1 / 0": "ZeroDivisionError",
            "x = (": "never closed",
            'app.table("gibtsnicht").count()': "gibtsnicht",
            'app.table("gerate").create(kategorie="falsch")': "bezeichnung",
            'http.get_json("https://intern.example/x")': "nicht freigegeben",
            'db.query("lager", "SELECT 1")': "nicht eingerichtet",
            # Grenze im Test klein, damit das Zeitlimit auch bei langsamer Datenbank nicht zuerst greift
            "for i in range(200):\n    app.table(\"gerate\").count()": "Zu viele Zugriffe",
        }
        for code, expected in cases.items():
            with override_settings(BAUKASTEN_SCRIPT_MAX_CALLS=50):
                result = self.run_code(code)
            self.assertFalse(result.ok, code)
            self.assertIn(expected, result.error_text(), code)
        timed = self.run_code("while True:\n    pass", timeout=1.5)
        self.assertIn("Zeitlimit", timed.error_text())
        line = self.run_code("a = 1\nb = 2\nc = a / 0\n")
        self.assertEqual(line.line, 3)

    def test_child_has_no_secrets(self):
        from ..scripting.python import _environment
        # Nur Pfad, Kodierung und Zeitzone – keine Umgebungsvariablen mit Zugangsdaten.
        self.assertEqual(set(_environment()) - {"SYSTEMROOT", "TZ"}, {"PATH", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"})

    def test_page_script_fills_blocks(self):
        from ..models import Script
        page = Page.objects.create(app=self.app, title="Skriptseite", layout=[
            {**make_block("output", label="Ergebnis"), "name": "ergebnis"},
            {**make_block("heading", text="Alt"), "name": "kopf"},
            {**make_block("notice", text="x"), "name": "weg"},
            {**make_block("stat", label="Zahl"), "name": "zahl"},
            {**make_block("form", entity=self.entity.slug), "name": "formular"},
        ])
        Script.objects.create(app=self.app, name="Füllen", page=page, code=(
            'ui.set("ergebnis", value=1234.5, rows=[{"a": 1, "b": "<x>"}])\n'
            'ui.set("kopf", text="Neu", subtitle="Unterzeile")\n'
            'ui.hide("weg")\n'
            'ui.set("zahl", value=42)\n'
            'ui.set("formular", values={"standort": "Halle 9"})\n'
            'message("Hallo " + user["name"])\n'))
        self.client.force_login(self.user)
        response = self.client.get(reverse("page", args=["inventar", page.slug]))
        content = response.content.decode()
        self.assertIn('<span data-slot="value">1.234,50</span>', content)
        self.assertIn("<td>&lt;x&gt;</td>", content)
        self.assertIn(">Neu</h2>", content)
        self.assertIn(">Unterzeile</p>", content)
        self.assertNotIn("notice-info\" role=\"note\" data-tone>", content.split("script-note")[-1])
        self.assertIn('<span data-slot="value">42</span>', content)
        self.assertIn('value="Halle 9"', content)
        self.assertIn("Hallo nutzer", content)
        self.assertNotIn("bk-runtime", content)   # kein JavaScript nötig

    def test_failing_page_script_is_shown_to_designers_only(self):
        from ..models import Script, ScriptRun
        page = self.app.pages.get(slug="gerate")
        Script.objects.create(app=self.app, name="Kaputt", page=page, code="x = 1 / 0")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("page", args=["inventar", "gerate"])), "Kaputt")
        self.client.force_login(self.designer)
        self.assertContains(self.client.get(reverse("page", args=["inventar", "gerate"])), "ZeroDivisionError")
        self.assertEqual(ScriptRun.objects.filter(ok=False).count(), 2)

    def test_button_script(self):
        from ..models import Script
        script = Script.objects.create(app=self.app, name="Zählen", trigger=Script.BUTTON,
                                       code='message(str(app.table("gerate").count()) + " Geräte")')
        page = Page.objects.create(app=self.app, title="Knopf", layout=[
            make_block("button", label="Los", target="script", script=script.slug)])
        self.client.force_login(self.user)
        html = self.client.get(reverse("page", args=["inventar", page.slug])).content.decode()
        url = reverse("run_script", args=["inventar", script.slug])
        self.assertIn(url, html)
        response = self.client.post(url, {"next": reverse("page", args=["inventar", page.slug])}, follow=True)
        self.assertContains(response, "6 Geräte")

    def test_on_save_script_changes_record_without_loop(self):
        # Die Beispiel-App ergänzt den Standort, wenn er fehlt.
        self.client.force_login(self.user)
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Leiter", "kategorie": "Werkstatt"})
        self.assertEqual(Record.objects.get(data__bezeichnung="Leiter").data["standort"], "Lager")
        from ..models import Script
        Script.objects.create(app=self.app, name="Schleife", trigger=Script.SAVE, entity=self.entity,
                              code='app.table("gerate").create(bezeichnung="Kopie", kategorie="IT")')
        self.client.post(reverse("record_create", args=["inventar", self.entity.slug]),
                         {"bezeichnung": "Start", "kategorie": "IT", "standort": "A"})
        self.assertEqual(Record.objects.filter(data__bezeichnung="Kopie").count(), 1)

    def test_scheduled_script_and_background_command(self):
        from io import StringIO

        from ..models import Script
        script = Script.objects.create(app=self.app, name="Nachts", trigger=Script.SCHEDULE, interval_minutes=60,
                                       code='app.table("gerate").create(bezeichnung="Zeitplan", kategorie="IT")')
        out = StringIO()
        call_command("hintergrund", stdout=out)
        call_command("hintergrund", stdout=out)   # Intervall noch nicht abgelaufen
        self.assertEqual(Record.objects.filter(data__bezeichnung="Zeitplan").count(), 1)
        script.refresh_from_db()
        self.assertEqual(script.runs.count(), 1)
        self.assertIn("1 Skripte ausgeführt", out.getvalue())

    def test_designer_editor_and_test_run(self):
        from ..models import Script
        self.client.force_login(self.designer)
        new = self.client.get(reverse("designer_script_new", args=["inventar"]) + "?sprache=python")
        self.assertContains(new, 'app.table(&quot;gerate&quot;)')
        response = self.client.post(reverse("designer_script_new", args=["inventar"]), {
            "name": "Test", "language": "python", "trigger": "page", "interval_minutes": 60, "enabled": "on",
            "code": 'print("hallo", app.table("gerate").count())', "action": "test"})
        self.assertContains(response, "hallo 6")
        self.assertContains(response, "erfolgreich")
        bad = self.client.post(reverse("designer_script_new", args=["inventar"]), {
            "name": "JS", "language": "javascript", "trigger": "save", "interval_minutes": 60, "code": ""})
        self.assertContains(bad, "nur beim Öffnen einer Seite oder per Button")
        self.assertEqual(Script.objects.filter(name="JS").count(), 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("designer_script_new", args=["inventar"])).status_code, 403)


class JavaScriptBridgeTests(Base):
    def post(self, op, **args):
        return self.client.post(reverse("script_bridge", args=["inventar"]), json.dumps({"op": op, "args": args}),
                                content_type="application/json")

    def test_bridge_uses_user_rights(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post("table.count", table=self.entity.slug, where={"kategorie": "IT"}).json()["result"], 3)
        created = self.post("table.create", table=self.entity.slug, data={"bezeichnung": "JS", "kategorie": "IT"})
        self.assertEqual(created.status_code, 200)
        self.entity.allow_delete = False
        self.entity.save()
        denied = self.post("table.delete", table=self.entity.slug, id=created.json()["result"]["id"])
        self.assertEqual(denied.status_code, 400)
        self.assertIn("nicht erlaubt", denied.json()["error"])
        self.assertEqual(self.post("os.system", cmd="x").status_code, 400)
        self.app.published = False
        self.app.save()
        self.assertEqual(self.post("table.count", table=self.entity.slug).status_code, 403)

    def test_bridge_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("script_bridge", args=["inventar"]), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_sandbox_page_is_locked_down(self):
        response = self.client.get(reverse("script_sandbox"))
        csp = response["Content-Security-Policy"]
        for part in ("default-src 'none'", "connect-src 'none'", "worker-src blob:"):
            self.assertIn(part, csp)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        nonce = csp.split("'nonce-")[1].split("'")[0]
        self.assertContains(response, f'nonce="{nonce}"')

    def test_page_with_js_script_gets_runtime(self):
        from ..models import Script
        page = self.app.pages.get(slug="gerate")
        Script.objects.create(app=self.app, name="Im Browser", language=Script.JAVASCRIPT, page=page,
                              code='ui.set("x", {value: 1});')
        self.client.force_login(self.user)
        content = self.client.get(reverse("page", args=["inventar", "gerate"])).content.decode()
        self.assertIn('id="bk-runtime"', content)
        self.assertIn('ui.set(\\"x\\", {value: 1});', content)


# ---------- Datenquellen ----------


class ScriptSessionTests(Base):
    """session in Skripten: Merkzettel je Besucher (Browser) und App."""

    def test_button_and_page_scripts_share_session_per_visitor_and_app(self):
        from ..models import Script
        self.app.published = True
        self.app.save()
        Script.objects.create(app=self.app, name="Zählen", slug="zaehlen", trigger=Script.BUTTON,
                              code='session["klicks"] = session.get("klicks", 0) + 1')
        page = Page.objects.create(app=self.app, title="Zähler", slug="zaehler", public=True, layout=[
            {**make_block("output", label="Klicks"), "name": "klicks"},
            make_block("button", label="+1", target="script", script="zaehlen"),
        ])
        Script.objects.create(app=self.app, name="Anzeigen", slug="anzeigen", trigger=Script.PAGE, page=page,
                              code='ui.set("klicks", value=session.get("klicks", 0))')
        url = reverse("page", args=["inventar", "zaehler"])
        for _ in range(3):
            self.client.post("/a/inventar/skript/zaehlen/", {"next": url})
        self.assertContains(self.client.get(url), ">3<")
        self.client.cookies.clear()
        self.assertContains(self.client.get(url), ">0<")

    def test_session_limits(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        from ..scripting.triggers import load_session, save_session
        request = RequestFactory().get("/")
        request.session = SessionStore()
        save_session(request, self.app, {"x": "a" * 5000})  # zu groß: wird nicht gespeichert
        self.assertEqual(load_session(request, self.app), {})
        save_session(request, self.app, {"x": 1})
        other = App.objects.create(name="Andere", slug="andere")
        self.assertEqual(load_session(request, self.app), {"x": 1})
        self.assertEqual(load_session(request, other), {})


class ScriptTimeTests(TestCase):
    def test_scripts_use_the_configured_time_zone(self):
        from django.utils import timezone

        from ..scripting.python import posix_timezone, run
        self.assertTrue(posix_timezone("Europe/Berlin").startswith("CET-1CEST"))
        app = App.objects.create(name="Zeit", slug="zeit")
        result = run('import datetime\nprint(datetime.datetime.now().strftime("%H"))', app)
        self.assertTrue(result.ok, result.error)
        self.assertIn(result.log[0], {timezone.localtime().strftime("%H"),
                                      (timezone.localtime() - __import__("datetime").timedelta(minutes=1)).strftime("%H")})


class AutomationTests(TestCase):
    """Automatisierungen: zweite App-Art mit echtem Python im Hintergrunddienst (scripting/worker.py)."""

    def setUp(self):
        from ..models import Script
        self.automator = User.objects.create_user("auto", password="x", is_staff=True)
        self.automator.groups.add(Group.objects.get(name="Automatisierer"))
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.user = User.objects.create_user("nutzer", password="x")
        self.app = App.objects.create(name="Abgleich", kind=App.AUTOMATION, created_by=self.automator)
        self.table = Entity.objects.create(app=self.app, name="Protokoll", slug="protokoll")
        Field.objects.create(entity=self.table, label="Text", key="text")
        self.Script = Script

    def script(self, code, trigger="manual", **extra):
        return self.Script.objects.create(app=self.app, name=extra.pop("name", "Lauf"), trigger=trigger,
                                          code=code, **extra)

    def run_now(self, script, event=None, control=None):
        """Ein Lauf wie im Dienst, aber im Test-Thread."""
        from django.utils import timezone
        from ..scripting import automation, worker
        self.Script.objects.filter(pk=script.pk).update(running_since=timezone.now())
        script.refresh_from_db()
        outcome = worker.execute(script, script.trigger, event or {"trigger": "manual"},
                                 control or automation.Control())
        return outcome, script.runs.exclude(status="skipped").first()

    # ---- Rechte und Oberfläche ----

    def test_only_automators_create_and_see_automations(self):
        self.client.force_login(self.designer)
        page = self.client.get(reverse("designer_home"))
        self.assertNotContains(page, 'id="neue-automatisierung"')
        self.assertNotContains(page, 'id="automatisierungen"')
        self.assertNotContains(page, "Abgleich")
        denied = self.client.post(reverse("designer_home"), {"auto-name": "X", "auto-icon": "⚙️"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get(reverse("designer_app", args=["abgleich"])).status_code, 403)
        # Auch als Mitbearbeiter nicht ohne die Gruppe
        self.app.editors.add(self.designer)
        self.assertEqual(self.client.get(reverse("designer_app", args=["abgleich"])).status_code, 403)

        self.client.force_login(self.automator)
        self.assertContains(self.client.get(reverse("designer_home")), 'id="neue-automatisierung"')
        response = self.client.post(reverse("designer_home"), {"auto-name": "Nachtlauf", "auto-icon": "🌙"})
        app = App.objects.get(slug="nachtlauf")
        self.assertRedirects(response, reverse("designer_app", args=["nachtlauf"]))
        self.assertTrue(app.is_automation)
        self.assertFalse(app.pages.exists())
        overview = self.client.get(reverse("designer_app", args=["nachtlauf"]))
        self.assertTemplateUsed(overview, "designer/automation.html")
        # Normale Apps legt dieselbe Seite weiter wie bisher an
        self.client.post(reverse("designer_home"), {"name": "Normal", "icon": "📦"})
        self.assertEqual(App.objects.get(slug="normal").kind, App.APP)

    def test_designer_home_lists_automations_below_apps_with_state(self):
        from django.utils import timezone
        from ..models import ScriptRun
        App.objects.create(name="Normale App", created_by=self.automator)
        running = self.script("pass", name="Laeuft")
        broken = self.script("pass", name="Kaputt")
        self.Script.objects.filter(pk=running.pk).update(running_since=timezone.now())
        ScriptRun.objects.create(script=broken, trigger="manual", status="error", ok=False)
        self.client.force_login(self.automator)
        page = self.client.get(reverse("designer_home"))
        self.assertEqual([a.name for a in page.context["apps"]], ["Normale App"])
        summary = page.context["automations"][0]
        self.assertEqual((summary.script_count, summary.running, summary.errors), (2, 1, 1))
        html = page.content.decode()
        self.assertLess(html.index('data-tour="app-list"'), html.index('id="automatisierungen"'))
        self.assertContains(page, "1 läuft")
        self.assertEqual(page.context["tab"], "app")
        # Fehler im Formular der Automatisierung: deren Reiter bleibt offen
        page = self.client.post(reverse("designer_home"), {"auto-name": "", "auto-icon": "⚙️"})
        self.assertEqual(page.context["tab"], "automation")
        self.assertEqual(self.client.get(reverse("designer_home") + "?neu=datei").context["tab"], "datei")

    def test_automation_has_no_runtime_pages(self):
        self.client.force_login(self.automator)
        self.assertEqual(self.client.get(reverse("page", args=["abgleich"])).status_code, 404)
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("home")), "Abgleich")

    def test_invite_requires_automation_group(self):
        self.client.force_login(self.automator)
        self.client.post(reverse("designer_app", args=["abgleich"]),
                         {"kind": "share", "action": "add_user", "username": "designer"})
        self.assertFalse(self.app.editors.exists())

    def test_script_editor_saves_plan_and_starts(self):
        from django.utils import timezone
        self.client.force_login(self.automator)
        new = self.client.get(reverse("designer_script_new", args=["abgleich"]))
        triggers = [value for value, _label in new.context["form"].fields["trigger"].choices]
        self.assertEqual(triggers, ["schedule", "daily", "continuous", "manual"])
        self.assertIn("import requests", new.context["form"].initial["code"])
        response = self.client.post(reverse("designer_script_new", args=["abgleich"]), {
            "name": "Viertelstunde", "trigger": "schedule", "interval_minutes": 15, "timeout_minutes": 20,
            "enabled": "on", "code": "print('hallo')", "action": "save"})
        script = self.app.scripts.get(slug="viertelstunde")
        self.assertRedirects(response, reverse("designer_script", args=["abgleich", script.pk]))
        self.assertEqual(script.language, "python")
        self.assertIsNotNone(script.next_run_at)
        # Zustand des Dienstes wird beim Speichern nicht überschrieben
        self.Script.objects.filter(pk=script.pk).update(running_since=timezone.now())
        self.client.post(reverse("designer_script", args=["abgleich", script.pk]), {
            "name": "Viertelstunde", "trigger": "schedule", "interval_minutes": 15, "timeout_minutes": 20,
            "enabled": "on", "code": "print('neu')", "action": "run"})
        script.refresh_from_db()
        self.assertIsNotNone(script.running_since)
        self.assertEqual(script.code, "print('neu')")
        self.assertTrue(script.run_requested)
        self.assertEqual(script.request_event["trigger"], "manual")
        page = self.client.get(reverse("designer_script", args=["abgleich", script.pk]))
        self.assertContains(page, "Live-Protokoll")
        live = self.client.get(reverse("designer_script_live", args=["abgleich", script.pk])).json()
        self.assertEqual(live["state"], "running")
        status = self.client.get(reverse("designer_automation_status", args=["abgleich"])).json()
        self.assertEqual(status["scripts"][0]["id"], script.pk)
        # Stoppen setzt nur die Bitte, den Rest erledigt der Dienst
        self.client.post(reverse("designer_script_stop", args=["abgleich", script.pk]))
        script.refresh_from_db()
        self.assertTrue(script.stop_requested)
        self.assertFalse(script.run_requested)

    def test_daily_needs_time_and_timeout_is_limited(self):
        self.client.force_login(self.automator)
        response = self.client.post(reverse("designer_script_new", args=["abgleich"]), {
            "name": "Morgens", "trigger": "daily", "interval_minutes": 60, "timeout_minutes": 99999, "code": "pass"})
        form = response.context["form"]
        self.assertIn("daily_time", form.errors)
        self.assertIn("timeout_minutes", form.errors)

    def test_normal_app_script_form_rejects_automation_triggers(self):
        from ..forms import ScriptForm
        normal = App.objects.create(name="Normal")
        form = ScriptForm({"name": "x", "language": "python", "trigger": "continuous", "interval_minutes": 60,
                           "code": "pass"}, app=normal)
        self.assertFalse(form.is_valid())

    # ---- Zeitpläne ----

    def test_schedule_skips_slots_instead_of_overtaking(self):
        from datetime import datetime, timezone as dt_tz
        from ..scripting import schedule
        script = self.script("pass", trigger="schedule", interval_minutes=15)
        due = datetime(2026, 11, 17, 10, 15, tzinfo=dt_tz.utc)
        self.assertEqual(schedule.catch_up(script, due, due.replace(minute=10)), (due, 0))
        nxt, missed = schedule.catch_up(script, due, due.replace(minute=20))
        self.assertEqual((nxt.minute, missed), (30, 1))
        nxt, missed = schedule.catch_up(script, due, due.replace(minute=50))
        self.assertEqual((nxt.hour, nxt.minute, missed), (11, 0, 3))
        # Nach langem Stillstand nichts nachholen
        later = due.replace(hour=18)
        self.assertGreater(schedule.next_after_start(script, due, later), later)

    @override_settings(TIME_ZONE="Europe/Berlin")
    def test_daily_weekdays_only(self):
        from datetime import datetime, time
        from django.utils import timezone
        from ..scripting import schedule
        script = self.script("pass", trigger="daily", daily_time=time(7, 0), weekdays_only=True)
        friday_evening = timezone.make_aware(datetime(2026, 11, 20, 18, 0))
        nxt = timezone.localtime(schedule.following(script, friday_evening))
        self.assertEqual((nxt.weekday(), nxt.hour), (0, 7))  # Montag 7 Uhr
        self.assertEqual(schedule.describe(script), "werktags um 07:00")

    # ---- Läufe (echte Kindprozesse) ----

    def test_full_python_run_with_libraries_tables_and_live_log(self):
        script = self.script(
            "import requests, dateutil, os, sys, threading\n"
            "print('requests', bool(requests.get))\n"
            "app.table('protokoll').create(text='von ' + event['trigger'])\n"
            "open('datei.txt', 'w').write('ok')\n"
            "print('datei', open('datei.txt').read())\n"
            "print('fehlerkanal', file=sys.stderr)\n"
            "print('daten', event.get('daten'))\n")
        outcome, run = self.run_now(script, {"trigger": "webhook", "daten": {"x": 1}})
        self.assertEqual(outcome.status, "ok", run.log + run.error)
        self.assertEqual(run.status, "ok")
        self.assertIn("requests True", run.log)
        self.assertIn("datei ok", run.log)
        self.assertIn("fehlerkanal", run.log)
        self.assertIn("daten {'x': 1}", run.log)
        self.assertEqual(self.table.records.get().data["text"], "von webhook")
        script.refresh_from_db()
        self.assertIsNone(script.running_since)

    def test_child_sees_no_credentials_but_secrets_on_request(self):
        import os
        script = self.script("import os\nprint('env', os.environ.get('DATABASE_URL'), os.environ.get('SECRET_KEY'))\n"
                             "print('geheim', secret('erp_token'))\n"
                             "try:\n    secret('fehlt')\nexcept ScriptError as e:\n    print('fehlt:', e)\n")
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://geheim", "SECRET_KEY": "s3cr3t",
                                          "SCRIPT_SECRET_ERP_TOKEN": "abc123"}):
            outcome, run = self.run_now(script)
        self.assertEqual(outcome.status, "ok", run.error)
        self.assertIn("env None None", run.log)
        self.assertIn("geheim abc123", run.log)
        self.assertIn("SCRIPT_SECRET_FEHLT", run.log)

    def test_restricted_scripts_cannot_read_secrets(self):
        import os
        from ..scripting import python
        normal = App.objects.create(name="Normal")
        with mock.patch.dict(os.environ, {"SCRIPT_SECRET_ERP_TOKEN": "abc123"}):
            result = python.run("print(secret('erp_token'))", normal)
        self.assertFalse(result.ok)
        self.assertIn("secret", result.error)

    def test_error_line_and_traceback(self):
        _outcome, run = self.run_now(self.script("x = 1\nraise ValueError('kaputt')\n"))
        self.assertEqual(run.status, "error")
        self.assertIn("Zeile 2", run.error)
        self.assertIn("ValueError: kaputt", run.error)

    def test_timeout_and_stop(self):
        import threading
        from ..scripting import automation
        with mock.patch.object(automation, "timeout_seconds", return_value=1):
            _outcome, run = self.run_now(self.script("import time\ntime.sleep(30)\n", trigger="schedule"))
        self.assertEqual(run.status, "error")
        self.assertIn("Zeitlimit", run.error)

        control = automation.Control()
        threading.Timer(1.0, control.request, args=["stopped"]).start()
        script = self.script("import time\nprint('los')\ntime.sleep(30)\n", name="Stopp")
        _outcome, run = self.run_now(script, control=control)
        self.assertEqual(run.status, "stopped")
        self.assertLess(run.duration_ms, 15000)

    def test_continuous_restarts_with_growing_delay(self):
        from django.utils import timezone
        script = self.script("raise RuntimeError('weg')", trigger="continuous")
        before = timezone.now()
        self.run_now(script)
        script.refresh_from_db()
        self.assertEqual(script.failures, 1)
        self.assertAlmostEqual((script.next_run_at - before).total_seconds(), 10, delta=5)
        self.run_now(script)
        script.refresh_from_db()
        self.assertEqual(script.failures, 2)
        self.assertGreater((script.next_run_at - timezone.now()).total_seconds(), 20)

    def test_finished_run_records_skipped_slots(self):
        from datetime import timedelta
        from django.utils import timezone
        script = self.script("print('fertig')", trigger="schedule", interval_minutes=15)
        self.Script.objects.filter(pk=script.pk).update(next_run_at=timezone.now() - timedelta(minutes=20))
        self.run_now(script)
        script.refresh_from_db()
        self.assertGreater(script.next_run_at, timezone.now())
        self.assertTrue(script.runs.filter(status="skipped", log__contains="2 Termine").exists())

    # ---- Dienst ----

    def worker(self):
        import io as _io
        from ..scripting import worker

        class SyncJob(worker.Job):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.thread = mock.Mock(start=self._run, is_alive=lambda: False)

        for patch in (mock.patch.object(worker, "Job", SyncJob), mock.patch.object(worker, "connection")):
            patch.start()
            self.addCleanup(patch.stop)
        return worker.Worker(out=_io.StringIO())

    def test_worker_runs_due_and_requested_scripts_once(self):
        from django.utils import timezone
        from ..scripting import worker as worker_module
        w = self.worker()
        timed = self.script("print('takt')", trigger="schedule", interval_minutes=15, name="Takt")
        manual = self.script("print('knopf')", name="Knopf")
        off = self.script("print('nie')", trigger="schedule", enabled=False, name="Aus")
        w.tick()  # plant den ersten Termin (jetzt) und startet ihn
        self.assertEqual(timed.runs.get().status, "ok")
        timed.refresh_from_db()
        self.assertGreater(timed.next_run_at, timezone.now())
        self.assertFalse(manual.runs.exists())
        self.assertFalse(off.runs.exists())
        self.assertTrue(worker_module.request_run(manual, "manual", user="auto"))
        self.assertFalse(worker_module.request_run(manual, "manual", user="auto"))  # wartet schon
        w.tick()
        self.assertEqual(manual.runs.get().trigger, "manual")
        w.tick()
        self.assertEqual(timed.runs.count(), 1)  # nicht doppelt

    def test_worker_never_starts_a_running_script_and_frees_stale_locks(self):
        from datetime import timedelta
        from django.utils import timezone
        from ..models import ScriptRun
        w = self.worker()
        script = self.script("print('x')")
        now = timezone.now()
        self.Script.objects.filter(pk=script.pk).update(running_since=now, heartbeat_at=now, run_requested=True)
        self.assertEqual(w.tick(), [])
        # Dienst abgestürzt: kein Lebenszeichen mehr -> freigeben, Lauf als abgebrochen vermerken
        ScriptRun.objects.create(script=script, trigger="manual", status="running")
        self.Script.objects.filter(pk=script.pk).update(heartbeat_at=now - timedelta(minutes=5))
        w.tick()
        self.assertEqual(script.runs.filter(status="aborted").count(), 1)
        self.assertEqual(script.runs.filter(status="ok").count(), 1)  # danach regulär gelaufen

    def test_legacy_schedule_ignores_automations(self):
        from ..scripting.triggers import run_due
        self.script("print('x')", trigger="schedule")
        self.assertEqual(run_due(), 0)

    # ---- Von außen: Webhook, MCP, Versionen ----

    def test_webhook(self):
        from ..models import ApiKey
        script = self.script("pass")
        _obj, write = ApiKey.issue(self.app, "n8n", can_write=True)
        _obj, read = ApiKey.issue(self.app, "lesen")

        def post(slug, key, body='{"auftrag": 42}'):
            return self.client.post(reverse("api_trigger", args=["abgleich", slug]), body,
                                    content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}")

        self.assertEqual(post(script.slug, read).status_code, 403)
        response = post(script.slug, write)
        self.assertEqual(response.status_code, 202, response.content)
        script.refresh_from_db()
        self.assertEqual(script.request_event["daten"], {"auftrag": 42})
        self.assertEqual(script.request_event["trigger"], "webhook")
        self.assertEqual(post(script.slug, write).status_code, 409)
        self.assertEqual(post("gibtsnicht", write).status_code, 404)
        forever = self.script("pass", trigger="continuous", name="Immer")
        self.assertEqual(post(forever.slug, write).status_code, 409)
        describe = self.client.get(reverse("api_describe", args=["abgleich"]), HTTP_AUTHORIZATION=f"Bearer {read}")
        self.assertEqual([s["slug"] for s in describe.json()["scripts"]], [script.slug])

    def test_mcp_tools(self):
        from ..models import ApiKey
        script = self.script("pass", name="Export")
        _obj, write = ApiKey.issue(self.app, "agent", can_write=True)
        _obj, read = ApiKey.issue(self.app, "lesen")
        url = reverse("mcp", args=["abgleich"])

        def rpc(method, params, key):
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            return self.client.post(url, json.dumps(body), content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Bearer {key}").json()

        names = {t["name"] for t in rpc("tools/list", {}, read)["result"]["tools"]}
        self.assertIn("automation_status", names)
        self.assertNotIn("start_export", names)
        result = rpc("tools/call", {"name": "start_export", "arguments": {"daten": {"a": 1}}}, write)["result"]
        self.assertFalse(result.get("isError"), result)
        script.refresh_from_db()
        self.assertEqual((script.request_event["trigger"], script.request_event["daten"]), ("mcp", {"a": 1}))
        status = rpc("tools/call", {"name": "automation_status", "arguments": {}}, read)["result"]
        self.assertIn("requested", json.dumps(status))

    def test_versions_keep_kind_and_import_needs_group(self):
        from datetime import time
        from .. import versions
        self.script("print(1)", trigger="daily", daily_time=time(6, 30), timeout_minutes=45)
        data = versions.snapshot(self.app)
        self.assertEqual(data["app"]["kind"], "automation")
        with self.assertRaises(versions.InvalidSnapshot):
            versions.import_app(data, self.designer)
        copy = versions.import_app(data, self.automator)
        self.assertTrue(copy.is_automation)
        imported = copy.scripts.get()
        self.assertEqual((imported.daily_time, imported.timeout_minutes), (time(6, 30), 45))
        # In eine normale App passen die Skripte nicht
        normal = App.objects.create(name="Normal")
        with self.assertRaises(versions.InvalidSnapshot):
            versions.apply(normal, data)
