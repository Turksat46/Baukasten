"""Legt die Beispiel-App „Aufnahme-Einwilligung“ an: python manage.py beispiel_einwilligung

Ablauf in der App:
1. Auf der Startseite legt die verantwortliche Person eine Veranstaltung an
   (Titel, Datum, Ort, Art der Aufnahmen, Zweck).
2. Ein Skript erzeugt dafür den Teilnahme-Link, z. B. /a/einwilligung/p/teilnahme/?event=3.
3. Teilnehmende öffnen den Link, sehen, was aufgenommen wird und wofür, und stimmen zu
   oder lehnen ab. Gespeichert wird die Antwort der angemeldeten Person; sie lässt sich
   jederzeit ändern.
4. Für Gäste ohne Konto erzeugt dasselbe Skript einen Gast-Link mit geheimem Code,
   z. B. /a/einwilligung/p/gast/?code=Xy3…. Die Seite „Gast“ ist im Seiten-Designer als
   „Ohne Anmeldung erreichbar“ markiert; Gäste geben dort ihren Namen in Eingabefelder ein
   und klicken Zustimmen oder Ablehnen. Alles mit Bausteinen und Skripten, ohne eigenen Code.
5. Auf der Startseite und unter „Antworten“ sieht man, wer zugestimmt oder abgelehnt hat.
"""
import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from builder.blocks import make_block
from builder.models import App, Entity, Field, Page, Record, Script

SLUG = "einwilligung"

LINK_SKRIPT = """# Nach dem Speichern einer Veranstaltung: Teilnahme-Link und verantwortliche Person ergänzen.
link = "/a/" + app.slug + "/p/teilnahme/?event=" + str(event["id"])
if record.get("teilnahme_link") != link:
    record["teilnahme_link"] = link
if not record.get("verantwortlich") and user:
    record["verantwortlich"] = user["name"]
# Gast-Link für Personen ohne Konto: geheimer Code, damit niemand Veranstaltungen durchprobieren kann.
if not record.get("gast_code"):
    record["gast_code"] = token()
gast_link = "/a/" + app.slug + "/p/gast/?code=" + record["gast_code"]
if record.get("gast_link") != gast_link:
    record["gast_link"] = gast_link
"""

GAST_SEITE_SKRIPT = """# Füllt die öffentliche Gast-Seite für die Veranstaltung aus der Adresse (?code=…).
import datetime

code = str(params.get("code", ""))
veranstaltung = app.table("veranstaltungen").first(gast_code=code) if code else None
if veranstaltung is None:
    ui.set("titel", text="Veranstaltung nicht gefunden", subtitle="Bitte den Link aus der Einladung verwenden.")
    for name in ("details", "status", "name", "email", "zustimmen", "ablehnen", "hinweis"):
        ui.hide(name)
else:
    datum = datetime.date.fromisoformat(veranstaltung["datum"]).strftime("%d.%m.%Y")
    ort = veranstaltung.get("ort") or ""
    ui.set("titel", text=veranstaltung["titel"], subtitle=datum + (", " + ort if ort else ""))
    ui.set("details", title="Geplante Aufnahmen: " + veranstaltung["aufnahmeart"],
           text=veranstaltung["zweck"] + "\\n\\nVerantwortlich: " + (veranstaltung.get("verantwortlich") or "–"))
    # Hat dieser Besucher (Browser) schon geantwortet? Die Nummer der Antwort steht in session.
    antwort_id = session.get("antwort_" + code)
    antwort = app.table("antworten").get(antwort_id) if antwort_id else None
    if antwort is None or antwort["veranstaltung"] != veranstaltung["id"]:
        ui.hide("status")
    else:
        zugestimmt = antwort["entscheidung"] == "Zustimmung"
        ui.set("status", title=("Du hast zugestimmt" if zugestimmt else "Du hast abgelehnt"),
               text="Gespeichert am " + antwort["zeitpunkt"] + " für " + antwort["name"]
                    + ". Mit den Buttons unten kannst du deine Antwort ändern.",
               tone=("success" if zugestimmt else "warning"))
        ui.hide("name")
        ui.hide("email")
        ui.set("zustimmen", label="Zustimmung bestätigen" if zugestimmt else "Doch zustimmen")
        ui.set("ablehnen", label="Doch ablehnen" if zugestimmt else "Ablehnung bestätigen")
"""

GAST_ANTWORT_SKRIPT = """# Speichert die Antwort eines Gastes (ohne Konto) für die Veranstaltung aus dem Gast-Link.
import datetime

ENTSCHEIDUNG = "{entscheidung}"

code = str(params.get("code", ""))
veranstaltung = app.table("veranstaltungen").first(gast_code=code) if code else None
name = str(params.get("name", "")).strip()
email = str(params.get("email", "")).strip()
antworten = app.table("antworten")
jetzt = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
# Schon geantwortet (gleicher Browser)? Dann die Antwort ändern statt eine zweite anzulegen.
antwort_id = session.get("antwort_" + code)
vorhanden = antworten.get(antwort_id) if antwort_id else None
if veranstaltung is None:
    message("Die Veranstaltung wurde nicht gefunden. Bitte den Link aus der Einladung verwenden.")
elif vorhanden is not None and vorhanden["veranstaltung"] == veranstaltung["id"]:
    antworten.update(vorhanden["id"], entscheidung=ENTSCHEIDUNG, zeitpunkt=jetzt)
    message("{danke}")
elif not name:
    message("Bitte gib deinen Namen an.")
else:
    try:
        neu = antworten.create(
            veranstaltung=veranstaltung["id"], name=name[:200], email=email or None, benutzer=None,
            entscheidung=ENTSCHEIDUNG, herkunft="Gast", zeitpunkt=jetzt,
        )
    except ScriptError:
        message("Bitte prüfe deine Angaben, z. B. die E-Mail-Adresse.")
    else:
        session["antwort_" + code] = neu["id"]
        message("{danke}")
"""

TEILNAHME_SKRIPT = """# Füllt die Teilnahme-Seite für die Veranstaltung aus der Adresse (?event=…).
import datetime

veranstaltung = None
if str(params.get("event", "")).isdigit():
    veranstaltung = app.table("veranstaltungen").get(int(params["event"]))

if veranstaltung is None:
    ui.set("titel", text="Veranstaltung nicht gefunden",
           subtitle="Bitte den Link aus der Einladung verwenden.")
    for name in ("details", "status", "zustimmen", "ablehnen", "hinweis"):
        ui.hide(name)
else:
    datum = datetime.date.fromisoformat(veranstaltung["datum"]).strftime("%d.%m.%Y")
    ort = veranstaltung.get("ort") or ""
    ui.set("titel", text=veranstaltung["titel"], subtitle=datum + (", " + ort if ort else ""))
    ui.set("details", title="Geplante Aufnahmen: " + veranstaltung["aufnahmeart"],
           text=veranstaltung["zweck"] + "\\n\\nVerantwortlich: " + (veranstaltung.get("verantwortlich") or "–"))
    antwort = app.table("antworten").first(veranstaltung=veranstaltung["id"], benutzer=user["username"])
    if antwort is None:
        ui.set("status", text="Du hast noch nicht geantwortet.", tone="info")
    elif antwort["entscheidung"] == "Zustimmung":
        ui.set("status", text="Du hast am " + antwort["zeitpunkt"] + " zugestimmt. Du kannst deine Antwort hier jederzeit ändern.",
               tone="success")
    else:
        ui.set("status", text="Du hast am " + antwort["zeitpunkt"] + " abgelehnt. Du kannst deine Antwort hier jederzeit ändern.",
               tone="warning")
"""

ANTWORT_SKRIPT = """# Speichert die Antwort der angemeldeten Person für die Veranstaltung aus der Adresse.
import datetime

ENTSCHEIDUNG = "{entscheidung}"

veranstaltung = None
if str(params.get("event", "")).isdigit():
    veranstaltung = app.table("veranstaltungen").get(int(params["event"]))

if veranstaltung is None:
    message("Die Veranstaltung wurde nicht gefunden. Bitte den Link aus der Einladung verwenden.")
else:
    antworten = app.table("antworten")
    werte = {{
        "entscheidung": ENTSCHEIDUNG,
        "zeitpunkt": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "name": user["name"],
        "email": user["email"] or None,
        "herkunft": "Konto",
    }}
    vorhanden = antworten.first(veranstaltung=veranstaltung["id"], benutzer=user["username"])
    if vorhanden:
        antworten.update(vorhanden["id"], **werte)
    else:
        antworten.create(veranstaltung=veranstaltung["id"], benutzer=user["username"], **werte)
    message("{danke}")
"""

AUSWERTUNG_SKRIPT = """# Zählt auf der Startseite die Antworten je Veranstaltung.
import datetime

antworten = app.table("antworten").all()
ja = [a for a in antworten if a["entscheidung"] == "Zustimmung"]
ui.set("zustimmungen", value=len(ja))
ui.set("ablehnungen", value=len(antworten) - len(ja))
zeilen = []
for v in app.table("veranstaltungen").all():
    eigene = [a for a in antworten if a["veranstaltung"] == v["id"]]
    zustimmungen = len([a for a in eigene if a["entscheidung"] == "Zustimmung"])
    zeilen.append((v["datum"], {"Veranstaltung": v["titel"],
                                "Datum": datetime.date.fromisoformat(v["datum"]).strftime("%d.%m.%Y"),
                                "Zustimmungen": zustimmungen, "Ablehnungen": len(eigene) - zustimmungen}))
ui.set("je_veranstaltung", rows=[zeile for datum, zeile in sorted(zeilen, key=lambda z: z[0], reverse=True)])
"""


class Command(BaseCommand):
    help = "Legt die Beispiel-App „Aufnahme-Einwilligung“ an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true",
                            help="Vorhandene Beispiel-App samt ihren Daten löschen und neu anlegen.")

    def handle(self, *args, **options):
        from builder import audit

        with audit.quiet():  # Beispieldaten anlegen gehört nicht ins Änderungsprotokoll
            return self._handle(*args, **options)

    def _handle(self, *args, **options):
        existing = App.objects.filter(slug=SLUG)
        if existing.exists():
            if not options["neu"]:
                self.stdout.write("Die Beispiel-App „Aufnahme-Einwilligung“ gibt es schon. Mit --neu wird sie neu angelegt.")
                return
            existing.delete()

        app = App.objects.create(
            name="Aufnahme-Einwilligung", slug=SLUG, icon="🎥", published=True,
            description="Beispiel: Einwilligung zu Foto-, Video- und Tonaufnahmen bei Veranstaltungen",
        )

        # ---------- Daten ----------
        events = Entity.objects.create(app=app, name="Veranstaltungen", slug="veranstaltungen")
        Field.objects.create(entity=events, label="Titel", key="titel", required=True)
        Field.objects.create(entity=events, label="Datum", key="datum", type=Field.DATE, required=True)
        Field.objects.create(entity=events, label="Ort", key="ort")
        Field.objects.create(entity=events, label="Aufnahmeart", key="aufnahmeart", type=Field.CHOICE, required=True,
                             choices="Foto\nVideo\nTon\nFoto und Video")
        Field.objects.create(entity=events, label="Zweck", key="zweck", type=Field.LONGTEXT, required=True,
                             show_in_list=False)
        Field.objects.create(entity=events, label="Verantwortlich", key="verantwortlich", show_in_form=False)
        Field.objects.create(entity=events, label="Teilnahme-Link", key="teilnahme_link", type=Field.URL,
                             show_in_form=False)
        # Code und Gast-Link ergänzt das Skript „Teilnahme-Link erzeugen“.
        Field.objects.create(entity=events, label="Gast-Link (ohne Anmeldung)", key="gast_link", type=Field.URL,
                             show_in_form=False)
        Field.objects.create(entity=events, label="Gast-Code", key="gast_code", show_in_form=False,
                             show_in_list=False)

        # Antworten entstehen nur über die Teilnahme-Seite, nicht über Formulare oder die Liste.
        answers = Entity.objects.create(app=app, name="Antworten", slug="antworten",
                                        allow_create=False, allow_edit=False, allow_delete=False)
        Field.objects.create(entity=answers, label="Veranstaltung", key="veranstaltung", type=Field.REFERENCE,
                             reference=events, required=True)
        Field.objects.create(entity=answers, label="Name", key="name", required=True)
        Field.objects.create(entity=answers, label="E-Mail", key="email", type=Field.EMAIL)
        Field.objects.create(entity=answers, label="Benutzer", key="benutzer", show_in_list=False)
        Field.objects.create(entity=answers, label="Entscheidung", key="entscheidung", type=Field.CHOICE,
                             required=True, choices="Zustimmung\nAblehnung")
        Field.objects.create(entity=answers, label="Zeitpunkt", key="zeitpunkt")
        Field.objects.create(entity=answers, label="Herkunft", key="herkunft", type=Field.CHOICE,
                             choices="Konto\nGast")

        # ---------- Beispieldaten ----------
        today = timezone.localdate()
        beispiele = [
            ("Betriebsversammlung Werk 2", today + timedelta(days=14), "Kantine Werk 2", "Foto und Video",
             "Fotos und ein kurzer Videozusammenschnitt für das Intranet. Aufnahmen werden nach 12 Monaten gelöscht."),
            ("Workshop Prozessautomatisierung", today + timedelta(days=5), "Raum 4.12", "Ton",
             "Tonaufnahme für das Protokoll. Nur für die Teilnehmenden, Löschung nach Freigabe des Protokolls."),
        ]
        created = []
        for titel, datum, ort, art, zweck in beispiele:
            record = Record.objects.create(entity=events, data={
                "titel": titel, "datum": datum.isoformat(), "ort": ort, "aufnahmeart": art, "zweck": zweck,
                "verantwortlich": "Kommunikation",
            })
            record.data["teilnahme_link"] = f"/a/{SLUG}/p/teilnahme/?event={record.pk}"
            code = secrets.token_urlsafe(16)
            record.data.update(gast_code=code, gast_link=f"/a/{SLUG}/p/gast/?code={code}")
            record.save(update_fields=["data"])
            created.append(record)
        stamp = timezone.localtime().strftime("%d.%m.%Y %H:%M")
        for name, benutzer, entscheidung in [("Anna Beispiel", "anna.beispiel", "Zustimmung"),
                                             ("Ben Muster", "ben.muster", "Ablehnung"),
                                             ("Cem Probe", "cem.probe", "Zustimmung")]:
            Record.objects.create(entity=answers, data={
                "veranstaltung": created[0].pk, "name": name, "benutzer": benutzer, "email": None,
                "entscheidung": entscheidung, "zeitpunkt": stamp, "herkunft": "Konto",
            })

        # ---------- Skripte ----------
        Script.objects.create(app=app, name="Teilnahme-Link erzeugen", slug="teilnahme-link",
                              trigger=Script.SAVE, entity=events, code=LINK_SKRIPT)
        Script.objects.create(app=app, name="Zustimmen", slug="zustimmen", trigger=Script.BUTTON,
                              code=ANTWORT_SKRIPT.format(
                                  entscheidung="Zustimmung",
                                  danke="Danke! Deine Zustimmung ist gespeichert."))
        Script.objects.create(app=app, name="Ablehnen", slug="ablehnen", trigger=Script.BUTTON,
                              code=ANTWORT_SKRIPT.format(
                                  entscheidung="Ablehnung",
                                  danke="Deine Ablehnung ist gespeichert. Du wirst nicht aufgenommen."))

        # ---------- Seiten ----------
        start = Page.objects.create(app=app, title="Veranstaltungen", slug="veranstaltungen", layout=[
            make_block("heading", text="Aufnahme-Einwilligungen", level="1",
                       subtitle="Veranstaltung anlegen, Link an die Teilnehmenden schicken, Antworten verfolgen."),
            make_block("stat", width=4, label="Veranstaltungen", entity=events.slug),
            {**make_block("output", width=4, label="Zustimmungen"), "name": "zustimmungen"},
            {**make_block("output", width=4, label="Ablehnungen"), "name": "ablehnungen"},
            make_block("form", width=6, entity=events.slug, submit_label="Veranstaltung anlegen"),
            make_block("notice", width=6, tone="info", title="So funktioniert es",
                       text="1. Links eine Veranstaltung anlegen: was wird aufgenommen und wofür?\n"
                            "2. Den Teilnahme-Link aus der Liste kopieren und mit der Einladung verschicken. "
                            "Für Gäste ohne Konto den Gast-Link verschicken: Dort geben sie nur ihren Namen ein.\n"
                            "3. Teilnehmende öffnen den Link und stimmen zu oder lehnen ab. "
                            "Mit Konto können sie ihre Antwort jederzeit ändern.\n"
                            "4. Wer wie geantwortet hat, steht unter „Antworten“."),
            make_block("table", entity=events.slug, title="Veranstaltungen", searchable=True),
            {**make_block("output", label="Antworten je Veranstaltung"), "name": "je_veranstaltung"},
        ])
        Page.objects.create(app=app, title="Antworten", slug="antworten", layout=[
            make_block("heading", text="Antworten", level="1",
                       subtitle="Jede Person hat je Veranstaltung genau eine Antwort; die letzte gilt."),
            make_block("donut", width=4, label="Entscheidungen", entity=answers.slug, field="entscheidung"),
            make_block("table", width=8, entity=answers.slug, title="Alle Antworten", searchable=True),
            make_block("export", entity=answers.slug, label="Antworten als CSV herunterladen"),
        ])
        teilnahme = Page.objects.create(app=app, title="Teilnahme", slug="teilnahme", show_in_nav=False, layout=[
            {**make_block("heading", text="Einwilligung zu Aufnahmen", level="1"), "name": "titel"},
            {**make_block("notice", tone="info", title="Geplante Aufnahmen", text=""), "name": "details"},
            {**make_block("notice", tone="info", text=""), "name": "status"},
            {**make_block("button", width=6, label="Ich stimme den Aufnahmen zu", target="script",
                          script="zustimmen"), "name": "zustimmen"},
            {**make_block("button", width=6, label="Ich lehne ab", target="script", script="ablehnen",
                          style="secondary", align="right"), "name": "ablehnen"},
            {**make_block("text", text="Wenn du ablehnst, wirst du nicht fotografiert oder gefilmt. "
                                       "Deine Antwort kannst du bis zur Veranstaltung jederzeit ändern."),
             "name": "hinweis"},
        ])
        Script.objects.create(app=app, name="Teilnahme-Seite füllen", slug="teilnahme-seite",
                              trigger=Script.PAGE, page=teilnahme, code=TEILNAHME_SKRIPT)
        Script.objects.create(app=app, name="Auswertung", slug="auswertung",
                              trigger=Script.PAGE, page=start, code=AUSWERTUNG_SKRIPT)
        add_guest_page(app)
        self.stdout.write(self.style.SUCCESS(
            f"Beispiel-App „Aufnahme-Einwilligung“ angelegt: /a/{SLUG}/ – Teilnahme-Seite z. B. "
            f"/a/{SLUG}/p/teilnahme/?event={created[0].pk}, Gast-Seite: {created[0].data['gast_link']}"))


def add_guest_page(app):
    """Öffentliche Seite „Gast“ mit Eingabefeldern und zwei Skript-Buttons. Gibt die Seite zurück.
    Auch für bestehende Apps nutzbar, die noch keine Gast-Seite haben."""
    gast = Page.objects.create(app=app, title="Gast", slug="gast", show_in_nav=False, public=True, layout=[
        {**make_block("heading", text="Einwilligung zu Aufnahmen", level="1"), "name": "titel"},
        {**make_block("notice", tone="info", title="Geplante Aufnahmen", text=""), "name": "details"},
        {**make_block("notice", tone="success", title="", text=""), "name": "status"},
        {**make_block("input", width=6, label="Dein Name", param="name", required=True), "name": "name"},
        {**make_block("input", width=6, label="E-Mail (freiwillig)", param="email", kind="email"), "name": "email"},
        {**make_block("button", width=6, label="Ich stimme den Aufnahmen zu", target="script",
                      script="gast-zustimmen"), "name": "zustimmen"},
        {**make_block("button", width=6, label="Ich lehne ab", target="script", script="gast-ablehnen",
                      style="secondary", align="right"), "name": "ablehnen"},
        {**make_block("text", text="Wenn du ablehnst, wirst du nicht fotografiert oder gefilmt. Gespeichert werden "
                                   "Name, E-Mail (falls angegeben), deine Entscheidung und der Zeitpunkt. Auf diesem "
                                   "Gerät kannst du deine Antwort hier ändern, sonst über die verantwortliche Person."),
         "name": "hinweis"},
    ])
    Script.objects.create(app=app, name="Gast-Seite füllen", slug="gast-seite",
                          trigger=Script.PAGE, page=gast, code=GAST_SEITE_SKRIPT)
    Script.objects.create(app=app, name="Gast stimmt zu", slug="gast-zustimmen", trigger=Script.BUTTON,
                          code=GAST_ANTWORT_SKRIPT.format(entscheidung="Zustimmung",
                                                          danke="Danke! Deine Zustimmung ist gespeichert."))
    Script.objects.create(app=app, name="Gast lehnt ab", slug="gast-ablehnen", trigger=Script.BUTTON,
                          code=GAST_ANTWORT_SKRIPT.format(
                              entscheidung="Ablehnung",
                              danke="Deine Ablehnung ist gespeichert. Du wirst nicht aufgenommen."))
    return gast
