"""Erzeugt die Werks-Apps (Produkttest) als JSON-Dateien in diesem Ordner.

    python beispiele/werk/erzeugen.py

Jede Datei ist eine App-Definition im selben Format, das der KI-Designer (MCP-Server
/mcp/designer/) annimmt, plus Beispieldaten unter „beispieldaten“. Laden mit:

    python manage.py beispiel_werk            (mit --neu vorhandene ersetzen)

Konventionen in den Beispieldaten:
- Datumswerte „@-3“ / „@+10“ heißen „heute minus 3 Tage“ / „heute plus 10 Tage“.
- Verweise „#4“ zeigen auf den 4. Beispieleintrag der Zieltabelle.

Szenarien und Daten sind erfunden. Jede App nennt unter „nachbauten“, welche Bausteine
gefehlt haben und wie sie ersatzweise gebaut wurden (Skript, Hinweis-Baustein, …).
"""
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent
R = random.Random(4711)

LINIEN = ["ZS-1 Zahnstange", "LG-2 Lenkgetriebe", "EPS-3 Servoeinheit", "PR-4 Endprüfung", "HT-5 Härterei",
          "VM-6 Ventilmontage"]
SCHICHTEN = ["Früh", "Spät", "Nacht"]
VORNAMEN = ["Ayşe", "Bernd", "Chiara", "Dragan", "Elif", "Frank", "Gül", "Heike", "Ivan", "Jana", "Kemal", "Lena",
            "Marco", "Nadine", "Oleksandr", "Petra", "Rüdiger", "Selin", "Thomas", "Uwe", "Vesna", "Wolfgang",
            "Yusuf", "Zoe"]
NACHNAMEN = ["Abele", "Bauer", "Celik", "Dietrich", "Engel", "Fuchs", "Gruber", "Hahn", "Ilić", "Jäger", "Kaya",
             "Lutz", "Maier", "Nowak", "Ott", "Pfeiffer", "Rapp", "Schäfer", "Traub", "Ulrich", "Vogel", "Wolf"]


def person():
    return f"{R.choice(VORNAMEN)} {R.choice(NACHNAMEN)}"


def f(label, key, type="text", choices=None, ref=None, required=False, formula="", liste=True, formular=True):
    out = {"label": label, "key": key, "type": type}
    if choices:
        out["choices"] = choices
    if ref:
        out["reference"] = ref
    if required:
        out["required"] = True
    if formula:
        out["formula"] = formula
    if not liste:
        out["show_in_list"] = False
    if not formular:
        out["show_in_form"] = False
    return out


def b(type, width=12, name=None, **props):
    out = {"type": type, "width": width, "props": props}
    if name:
        out["name"] = name
    return out


def t(name, slug, *fields):
    return {"name": name, "slug": slug, "fields": list(fields)}


def page(title, slug, *layout, nav=True, public=False):
    out = {"title": title, "slug": slug, "layout": list(layout)}
    if not nav:
        out["show_in_nav"] = False
    if public:
        out["public"] = True
    return out


def script(name, code, trigger="page", page=None, entity=None, interval=None):
    out = {"name": name, "language": "python", "trigger": trigger, "code": code.strip() + "\n"}
    if page:
        out["page"] = page
    if entity:
        out["entity"] = entity
    if interval:
        out["interval_minutes"] = interval
    return out


def gap(key, ersatz, jetzt=""):
    """Ein fehlender Baustein, wie er zuerst ersatzweise gebaut wurde und – falls inzwischen eingebaut – wie jetzt."""
    out = {"baustein": key, "ersatz": ersatz, "geloest": bool(jetzt)}
    if jetzt:
        out["jetzt"] = jetzt
    return out


APPS = []


def app(slug, name, icon, rolle, komplexitaet, description, entities, pages, data, scripts=(), nachbauten=()):
    APPS.append({
        "slug": slug, "name": name, "icon": icon, "description": description,
        "rolle": rolle, "komplexitaet": komplexitaet,
        "entities": entities, "pages": pages, "scripts": list(scripts),
        "beispieldaten": data, "nachbauten": list(nachbauten),
    })


def days(lo, hi):
    return f"@{R.randint(lo, hi):+d}"


# ---------------------------------------------------------------- 1 Kantine (Werker, sehr einfach)
gerichte = [("Linsen mit Spätzle und Saitenwürstle", "Fleisch", 5.9), ("Gemüse-Maultaschen in Brühe", "Vegetarisch", 4.8),
            ("Seelachs mit Kartoffelsalat", "Fisch", 6.4), ("Kichererbsen-Curry", "Vegan", 4.9),
            ("Schweinebraten mit Knödel", "Fleisch", 6.9), ("Käsespätzle mit Röstzwiebeln", "Vegetarisch", 5.2),
            ("Ofengemüse mit Hummus", "Vegan", 4.6), ("Rostbraten mit Spätzle", "Fleisch", 8.5)]
speiseplan = []
for d in range(-2, 8):
    for name, kat, preis in R.sample(gerichte, 3):
        speiseplan.append({"datum": f"@{d:+d}", "gericht": name, "kategorie": kat, "preis": preis})
app("gmd-kantine", "Kantine & Schichtessen", "🍽️", "Werker", "einfach",
    "Speiseplan der Woche und Essensbestellung für die Spät- und Nachtschicht",
    [t("Speiseplan", "speiseplan",
       f("Datum", "datum", "date", required=True), f("Gericht", "gericht", required=True),
       f("Kategorie", "kategorie", "choice", ["Vegetarisch", "Vegan", "Fleisch", "Fisch"]),
       f("Preis (€)", "preis", "decimal")),
     t("Bestellungen", "bestellungen",
       f("Name", "name", required=True), f("Personalnummer", "persnr"),
       f("Gericht", "gericht", "reference", ref="speiseplan", required=True),
       f("Schicht", "schicht", "choice", SCHICHTEN), f("Abholung", "datum", "date"))],
    [page("Speiseplan", "plan",
          b("heading", text="Speiseplan", subtitle="Kantine Werk Gmünd · Bau 3", level="1"),
          b("filter", entity="speiseplan", field="kategorie"),
          b("calendar", title="Diese und nächste Woche", entity="speiseplan", date_field="datum",
            label_field="gericht", color_field="kategorie", create_links=False),
          b("cards", title="Alle Gerichte", entity="speiseplan", page_size=12)),
     page("Bestellen", "bestellen",
          b("heading", text="Schichtessen bestellen", subtitle="Bis 11 Uhr für die Spätschicht, bis 18 Uhr für die Nacht", level="2"),
          b("form", width=6, entity="bestellungen", submit_label="Bestellen"),
          b("stat", width=6, label="Bestellungen für heute", entity="bestellungen", where="Abholung = heute"),
          b("table", entity="bestellungen", title="Bestellungen", searchable=True))],
    {"speiseplan": speiseplan,
     "bestellungen": [{"name": person(), "persnr": str(R.randint(100000, 999999)),
                       "gericht": f"#{R.randint(7, 12)}", "schicht": R.choice(["Spät", "Nacht"]), "datum": "@+0"}
                      for _ in range(14)]},
    [],
    [gap("kennzahl_bedingung", "„Bestellungen für heute“: Kennzahl zählt nur gefiltert über die Adresse, "
                               "darum Seitenskript mit count(datum=heute) und ui.set.",
         jetzt="Kennzahl mit Bedingung „Abholung = heute“, kein Skript mehr.")])

# ---------------------------------------------------------------- 2 Schichtbuch (Werker, einfach)
schichtbuch = []
for d in range(-13, 1):
    for s in SCHICHTEN:
        for linie in LINIEN[:4]:
            soll = {"ZS-1 Zahnstange": 620, "LG-2 Lenkgetriebe": 480, "EPS-3 Servoeinheit": 410, "PR-4 Endprüfung": 900}[linie]
            ist = int(soll * R.uniform(0.78, 1.04))
            schichtbuch.append({"datum": f"@{d:+d}", "schicht": s, "linie": linie, "soll": soll, "ist": ist,
                                "ausschuss": R.randint(0, 14), "personal": R.randint(6, 11),
                                "besonderheiten": R.choice(["", "", "", "Werkzeugwechsel Räumnadel", "Materialengpass Ritzel",
                                                            "Prüfstand 2 kalibriert", "Störung Schrauber Station 40"])})
app("gmd-schichtbuch", "Schichtbuch & Übergabe", "📒", "Werker / Schichtführer", "einfach",
    "Stückzahlen, Ausschuss und Besonderheiten je Schicht und Linie, mit Übergabe-Checkliste",
    [t("Schichtbuch", "schichtbuch",
       f("Datum", "datum", "date", required=True), f("Schicht", "schicht", "choice", SCHICHTEN, required=True),
       f("Linie", "linie", "choice", LINIEN, required=True), f("Soll (Stück)", "soll", "number"),
       f("Ist (Stück)", "ist", "number"), f("Ausschuss (Stück)", "ausschuss", "number"),
       f("Personal anwesend", "personal", "number"),
       f("Erfüllung (%)", "erfuellung", "decimal", formula="round(ist / soll * 100, 1)", formular=False),
       f("Besonderheiten", "besonderheiten", "longtext", liste=False)),
     t("Übergabepunkte", "uebergabe",
       f("Punkt", "punkt", required=True), f("Linie", "linie", "choice", LINIEN),
       f("Erledigt", "erledigt", "bool"), f("Hinweis", "hinweis"))],
    [page("Übergabe", "uebergabe",
          b("heading", text="Schichtübergabe", level="1"),
          b("notice", name="ampel", title="Erfüllung letzte Schicht", text="wird berechnet …", tone="info"),
          b("checklist", width=6, title="Übergabe-Checkliste", entity="uebergabe", field="erledigt",
            label_field="punkt", detail="linie"),
          b("form", width=6, entity="schichtbuch", submit_label="Schicht eintragen")),
     page("Auswertung", "auswertung",
          b("filter", entity="schichtbuch", field="linie", field2="schicht", field3="datum"),
          b("stat", width=4, label="Ist-Stück gesamt", entity="schichtbuch", aggregate="sum", field="ist"),
          b("stat", width=4, label="Ausschuss gesamt", entity="schichtbuch", aggregate="sum", field="ausschuss"),
          b("stat", width=4, label="Ø Erfüllung", entity="schichtbuch", aggregate="avg", field="erfuellung", unit="%"),
          b("line", label="Ist-Stück pro Tag", entity="schichtbuch", date_field="datum", aggregate="sum", field="ist",
            period="day", count=14),
          b("pivot", title="Erfüllung (%) Linie × Schicht", entity="schichtbuch", row_field="linie", col_field="schicht",
            agg="avg", value_field="erfuellung"),
          b("table", entity="schichtbuch", page_size=20, searchable=True))],
    {"schichtbuch": schichtbuch,
     "uebergabe": [{"punkt": p, "linie": li, "erledigt": R.random() < 0.4} for p, li in [
         ("Werkzeugstandzeiten eingetragen", "ZS-1 Zahnstange"), ("Prüfprotokolle abgelegt", "PR-4 Endprüfung"),
         ("Leergut abgeholt", "LG-2 Lenkgetriebe"), ("Nacharbeitsplatz leer", "EPS-3 Servoeinheit"),
         ("Sperrlager-Teile gekennzeichnet", "PR-4 Endprüfung"), ("Kühlschmierstoff-Konzentration gemessen", "ZS-1 Zahnstange"),
         ("5S-Rundgang Arbeitsplatz", "LG-2 Lenkgetriebe")]]},
    [script("Ampel letzte Schicht", """
rows = app.table("schichtbuch").all()
if rows:
    letzte = max(rows, key=lambda r: (r["datum"] or "", ["Früh", "Spät", "Nacht"].index(r["schicht"]) if r["schicht"] in ["Früh", "Spät", "Nacht"] else 0))
    gleiche = [r for r in rows if r["datum"] == letzte["datum"] and r["schicht"] == letzte["schicht"]]
    soll = sum(r["soll"] or 0 for r in gleiche); ist = sum(r["ist"] or 0 for r in gleiche)
    quote = round(100 * ist / soll, 1) if soll else 0
    ton = "success" if quote >= 95 else ("warning" if quote >= 85 else "danger")
    ui.set("ampel", tone=ton, title=f"Erfüllung {letzte['schicht']}schicht {letzte['datum']}: {quote} %",
           text=f"{ist} von {soll} Stück über {len(gleiche)} Linien.")
""", page="uebergabe")],
    [gap("ampel", "Soll/Ist-Ampel der letzten Schicht: Hinweis-Baustein, dessen Farbe (tone) ein Seitenskript setzt.")])

# ---------------------------------------------------------------- 3 Andon / Störungen (Werker+IH, mittel)
KATEGORIEN = ["Mechanik", "Elektrik", "Hydraulik", "Steuerung/Software", "Material fehlt", "Qualität"]
stoerungen = []
for _n in range(60):
    status = R.choices(["Behoben", "Offen", "In Arbeit", "Wartet auf Teil"], [7, 1, 1, 0.5])[0]
    stoerungen.append({"titel": R.choice(["Schrauber NOK", "Greifer klemmt", "Lichtschranke verschmutzt", "Hydraulikdruck niedrig",
                                          "Ritzel fehlen am Band", "Prüfstand Fehlercode 217", "Roboter Kollision",
                                          "Presse Kraft außer Toleranz", "SPS-Kommunikation gestört"]),
                       "linie": R.choice(LINIEN), "kategorie": R.choices(KATEGORIEN, [5, 4, 2, 3, 3, 2])[0],
                       "prioritaet": R.choices(["Hoch", "Mittel", "Niedrig"], [2, 3, 2])[0], "status": status,
                       "gemeldet": days(-20, 0), "dauer_min": R.choice([5, 10, 15, 20, 30, 45, 60, 90, 120, 240]),
                       "gemeldet_von": person()})
ANDON_CODE = """
rows = app.table("stoerungen").all()
offen = [r for r in rows if r["status"] != "Behoben"]
linien = __LISTE__
for i, linie in enumerate(linien, start=1):
    l_offen = [r for r in offen if r["linie"] == linie]
    hoch = [r for r in l_offen if r["prioritaet"] == "Hoch"]
    ton = "danger" if hoch else ("warning" if l_offen else "success")
    ui.set(f"linie{i}", tone=ton, title=linie,
           text=("Steht: " + hoch[0]["titel"]) if hoch else (f"{len(l_offen)} offene Meldung(en)" if l_offen else "Läuft"))
""".replace("__LISTE__", json.dumps(LINIEN, ensure_ascii=False))
app("gmd-andon", "Andon & Störungsmeldung", "🚨", "Werker / Instandhaltung", "mittel",
    "Störungen an der Linie melden, Andon-Tafel mit Linienstatus, Stillstands-Pareto",
    [t("Störungen", "stoerungen",
       f("Störung", "titel", required=True), f("Linie", "linie", "choice", LINIEN, required=True),
       f("Kategorie", "kategorie", "choice", KATEGORIEN),
       f("Priorität", "prioritaet", "choice", ["Hoch", "Mittel", "Niedrig"]),
       f("Status", "status", "choice", ["Offen", "In Arbeit", "Wartet auf Teil", "Behoben"]),
       f("Gemeldet am", "gemeldet", "date"), f("Stillstand (min)", "dauer_min", "number"),
       f("Gemeldet von", "gemeldet_von"), f("Beschreibung", "beschreibung", "longtext", liste=False))],
    [page("Andon-Tafel", "tafel",
          b("heading", text="Andon-Tafel", subtitle="Werk Gmünd · Halle 2", level="1"),
          b("stat", width=4, label="Offene Störungen", entity="stoerungen", where="Status != Behoben",
            warn_at="5", alarm_at="10"),
          b("stat", width=4, label="davon Priorität hoch", entity="stoerungen",
            where="Status != Behoben\nPriorität = Hoch", warn_at="1", alarm_at="3"),
          b("stat", width=4, label="Stillstand heute", entity="stoerungen", aggregate="sum", field="dauer_min",
            unit="min", where="Gemeldet am = heute", warn_at="60", alarm_at="120"),
          *[b("notice", width=4, name=f"linie{i}", title=li, text="…", tone="info") for i, li in enumerate(LINIEN, 1)],
          b("table", width=8, title="Offene Störungen", entity="stoerungen", where="Status != Behoben"),
          b("chart", width=4, label="Pareto: Stillstand nach Ursache (min)", entity="stoerungen", field="kategorie",
            agg="sum", value_field="dauer_min", pareto=True)),
     page("Melden", "melden",
          b("heading", text="Störung melden", level="2"),
          b("form", entity="stoerungen", submit_label="Störung melden")),
     page("Bearbeitung", "bearbeitung",
          b("filter", entity="stoerungen", field="linie", field2="kategorie", field3="prioritaet"),
          b("kanban", title="Störungen nach Status", entity="stoerungen", field="status", detail="linie", limit=8),
          b("chart", width=6, label="Anzahl nach Kategorie", entity="stoerungen", field="kategorie"),
          b("donut", width=6, label="Nach Linie", entity="stoerungen", field="linie"),
          b("table", entity="stoerungen", searchable=True))],
    {"stoerungen": stoerungen},
    [script("Andon berechnen", ANDON_CODE, page="tafel")],
    [gap("kennzahl_bedingung", "3 Kennzahlen (offen, Prio hoch, Stillstand heute) per Skript statt Kennzahl-Baustein.",
         jetzt="Kennzahlen mit Bedingung und Ampel-Schwellen."),
     gap("ampel", "6 Linien-Ampeln als Hinweis-Bausteine mit tone aus dem Skript.",
         jetzt="Die 3 Kennzahlen färben sich selbst. Die Linien-Ampeln bleiben Skript: Sie zeigen den Text der Störung."),
     gap("liste_bedingung", "Liste nur der offenen Störungen als Ausgabe-Baustein mit rows aus dem Skript – "
                            "ohne Klick zum Bearbeiten.", jetzt="Liste mit Bedingung „Status != Behoben“, mit Bearbeiten."),
     gap("diagramm_summe", "Pareto Stillstand nach Ursache: Balkendiagramm kann nur zählen, nicht Minuten summieren "
                           "und absteigend sortieren – Tabelle aus dem Skript.",
         jetzt="Balkendiagramm mit Summe der Minuten und Pareto-Anteil.")])

# ---------------------------------------------------------------- 4 5S-Audit (Meister, mittel)
BEREICHE = ["Halle 1 Zerspanung", "Halle 2 Montage", "Halle 3 Prüffeld", "Logistik Wareneingang", "Werkstatt IH", "Härterei"]
audits = []
for w in range(12):
    for ber in BEREICHE:
        if R.random() < 0.7:
            vals = [R.randint(2, 5) for _ in range(5)]
            audits.append({"bereich": ber, "datum": f"@{-7 * w - R.randint(0, 4):+d}", "auditor": person(),
                           "s1": vals[0], "s2": vals[1], "s3": vals[2], "s4": vals[3], "s5": vals[4]})
app("gmd-5s", "5S-Audit", "🧹", "Meister / Werker", "mittel",
    "5S-Audits je Bereich erfassen, Entwicklung verfolgen, Maßnahmen abhaken",
    [t("Audits", "audits",
       f("Bereich", "bereich", "choice", BEREICHE, required=True), f("Datum", "datum", "date", required=True),
       f("Auditor/in", "auditor"),
       f("Sortieren (0–5)", "s1", "number"), f("Systematisieren (0–5)", "s2", "number"),
       f("Säubern (0–5)", "s3", "number"), f("Standardisieren (0–5)", "s4", "number"),
       f("Selbstdisziplin (0–5)", "s5", "number"),
       f("Punkte gesamt", "gesamt", "number", formula="s1 + s2 + s3 + s4 + s5", formular=False),
       f("Bemerkung", "bemerkung", "longtext", liste=False)),
     t("Maßnahmen", "massnahmen",
       f("Maßnahme", "massnahme", required=True), f("Bereich", "bereich", "choice", BEREICHE),
       f("Verantwortlich", "verantwortlich"), f("Fällig", "faellig", "date"), f("Erledigt", "erledigt", "bool"))],
    [page("Audit erfassen", "erfassen",
          b("heading", text="5S-Audit erfassen", subtitle="Je Kriterium 0 (nicht erfüllt) bis 5 (vorbildlich)", level="1"),
          b("form", entity="audits", submit_label="Audit speichern")),
     page("Auswertung", "auswertung",
          b("filter", entity="audits", field="bereich", field2="datum"),
          b("stat", width=4, label="Ø Punkte (max. 25)", entity="audits", aggregate="avg", field="gesamt"),
          b("stat", width=4, label="Audits", entity="audits"),
          b("output", width=4, name="schwaechstes", label="Schwächstes S"),
          b("line", label="Ø Punkte je Woche", entity="audits", date_field="datum", aggregate="avg", field="gesamt",
            period="week", count=12, threshold="18"),
          b("heatmap", title="Ø Punkte Bereich × Woche", entity="audits", mode="crosstab", row_field="bereich",
            col_field="auditor", value_field="gesamt", agg="avg"),
          b("boxplot", width=6, title="Streuung je Bereich", entity="audits", field="gesamt", group_field="bereich"),
          b("output", width=6, name="netz", label="Profil der 5 S (Ø)")),
     page("Maßnahmen", "massnahmen",
          b("checklist", title="Offene 5S-Maßnahmen", entity="massnahmen", field="erledigt", label_field="massnahme",
            detail="bereich"),
          b("calendar", entity="massnahmen", date_field="faellig", label_field="massnahme", color_field="bereich"),
          b("form", entity="massnahmen", submit_label="Maßnahme anlegen"))],
    {"audits": audits,
     "massnahmen": [{"massnahme": m, "bereich": R.choice(BEREICHE), "verantwortlich": person(), "faellig": days(-5, 20),
                     "erledigt": R.random() < 0.3} for m in [
         "Schattenbrett Werkzeugwagen 3 erneuern", "Bodenmarkierung Gang B nachziehen", "Kabelkanal Station 20 schließen",
         "Ablage Prüfmittel beschriften", "Ölwanne Presse 4 reinigen", "Rote-Karte-Bereich auflösen",
         "Standard Reinigungsplan aushängen", "Leergutplatz kennzeichnen"]]},
    [script("5S-Profil", """
rows = app.table("audits").all()
namen = ["Sortieren", "Systematisieren", "Säubern", "Standardisieren", "Selbstdisziplin"]
mittel = []
for i, n in enumerate(namen, start=1):
    werte = [r[f"s{i}"] for r in rows if r[f"s{i}"] is not None]
    mittel.append((n, round(sum(werte) / len(werte), 2) if werte else 0))
ui.set("netz", rows=[{"S": n, "Ø": m, "Balken": "█" * int(round(m * 4))} for n, m in mittel])
schwach = min(mittel, key=lambda x: x[1]) if mittel else ("–", 0)
ui.set("schwaechstes", value=schwach[0], unit=f"Ø {schwach[1]}")
""", page="auswertung")],
    [gap("netzdiagramm", "Profil der 5 Kriterien: kein Netz-/Radardiagramm, darum Tabelle mit Textbalken aus dem Skript."),
     gap("diagramm_mehrere_felder", "Durchschnitt über 5 Zahlenfelder nebeneinander geht mit keinem Diagramm."),
     gap("kennzahl_bedingung", "„Schwächstes S“ per Skript.")])

# ---------------------------------------------------------------- 5 TPM-Wartungsplan (Instandhaltung, mittel)
ANLAGEN = [("Räummaschine RM-01", "ZS-1 Zahnstange", "A"), ("Induktionshärteanlage IH-02", "HT-5 Härterei", "A"),
           ("Verzahnungsfräse VF-03", "ZS-1 Zahnstange", "A"), ("Schraubstation SS-40", "LG-2 Lenkgetriebe", "B"),
           ("Fügepresse FP-12", "LG-2 Lenkgetriebe", "A"), ("Roboterzelle RZ-07", "EPS-3 Servoeinheit", "B"),
           ("Funktionsprüfstand PS-02", "PR-4 Endprüfung", "A"), ("Dichtheitsprüfung DP-05", "PR-4 Endprüfung", "B"),
           ("Waschanlage WA-01", "VM-6 Ventilmontage", "C"), ("Kompressor K-3", "Infrastruktur", "B")]
wartungen = []
for i, _anlage in enumerate(ANLAGEN, start=1):
    for aufgabe, intervall in R.sample([("Ölwechsel Hydraulik", 180), ("Filter tauschen", 30), ("Sichtprüfung Schutzeinrichtung", 7),
                                        ("Spindel-Schwingungsmessung", 90), ("Kalibrierung Kraftsensor", 365),
                                        ("Schmierung Führungen", 14), ("Kühlmittel prüfen", 7), ("Bremsentest Roboter", 30)], 3):
        letzte = -R.randint(0, intervall + 15)
        wartungen.append({"anlage": f"#{i}", "aufgabe": aufgabe, "intervall": intervall, "letzte": f"@{letzte:+d}",
                          "verantwortlich": person(),
                          "art": R.choice(["Autonome IH (Werker)", "Geplante IH"])})
app("gmd-tpm", "TPM-Wartungsplan", "🛠️", "Instandhaltung", "mittel",
    "Anlagen, Wartungsintervalle, Fälligkeiten und Rückmeldung der Wartung",
    [t("Anlagen", "anlagen",
       f("Anlage", "name", required=True), f("Linie", "linie", "choice", LINIEN + ["Infrastruktur"]),
       f("Kritikalität", "krit", "choice", ["A", "B", "C"]), f("Baujahr", "baujahr", "number")),
     t("Wartungen", "wartungen",
       f("Anlage", "anlage", "reference", ref="anlagen", required=True), f("Aufgabe", "aufgabe", required=True),
       f("Intervall (Tage)", "intervall", "number"), f("Zuletzt", "letzte", "date"),
       f("Nächste Fälligkeit", "naechste", "date", formula="letzte + intervall", formular=False),
       f("Art", "art", "choice", ["Autonome IH (Werker)", "Geplante IH"]), f("Verantwortlich", "verantwortlich"))],
    [page("Fällig", "faellig",
          b("heading", text="Wartungen", subtitle="Überfällig, diese Woche, demnächst", level="1"),
          b("stat", width=4, label="Überfällig", entity="wartungen", where="Nächste Fälligkeit < heute",
            warn_at="1", alarm_at="5"),
          b("stat", width=4, label="Fällig in 7 Tagen", entity="wartungen",
            where="Nächste Fälligkeit >= heute\nNächste Fälligkeit <= heute+7"),
          b("stat", width=4, name="k_a", label="Überfällig an A-Anlagen"),
          b("table", title="Überfällige Wartungen", entity="wartungen", where="Nächste Fälligkeit < heute"),
          b("calendar", title="Fälligkeiten", entity="wartungen", date_field="naechste", label_field="aufgabe",
            color_field="art")),
     page("Anlagen", "anlagen",
          b("search", entity="anlagen", field="name", target_page="anlage"),
          b("table", entity="anlagen")),
     page("Anlage", "anlage",
          b("detail", entity="anlagen"),
          b("related_list", title="Wartungsaufgaben", entity="wartungen", ref_field="anlage"), nav=False),
     page("Plan", "plan",
          b("filter", entity="wartungen", field="art", field2="anlage"),
          b("gantt", title="Nächste 4 Wochen", entity="wartungen", start_field="naechste", label_field="aufgabe",
            group_field="anlage", color_field="art"),
          b("table", entity="wartungen", searchable=True, page_size=30))],
    {"anlagen": [{"name": n, "linie": li, "krit": k, "baujahr": R.randint(2008, 2023)} for n, li, k in ANLAGEN],
     "wartungen": wartungen},
    [script("Fälligkeiten", """
import datetime
heute = datetime.date.today()
anlagen = {a["id"]: a for a in app.table("anlagen").all()}
rows = app.table("wartungen").all()
def tage(r):
    return (datetime.date.fromisoformat(r["naechste"]) - heute).days if r["naechste"] else 9999
ueber = [r for r in rows if tage(r) < 0]
n = len([r for r in ueber if anlagen.get(int(r["anlage"] or 0), {}).get("krit") == "A"])
ui.set("k_a", value=n, tone="danger" if n else "success")
""", page="faellig")],
    [gap("datumsformel", "„Nächste Fälligkeit = Zuletzt + Intervall“: Formeln rechnen nur mit Zahlen, darum Skript nach dem Speichern.",
         jetzt="Formel „letzte + intervall“ im Datumsfeld, kein Skript mehr."),
     gap("kennzahl_bedingung", "3 Kennzahlen mit Datumsbedingung (überfällig, 7 Tage, A-Anlagen) per Skript.",
         jetzt="2 von 3 als Kennzahl mit Bedingung. „A-Anlagen“ braucht ein Feld der verknüpften Anlage – bleibt Skript."),
     gap("liste_bedingung", "Liste der überfälligen Wartungen als Ausgabe-Baustein; Verweis auf Anlage im Skript aufgelöst.",
         jetzt="Liste mit Bedingung „Nächste Fälligkeit < heute“.")])

# ---------------------------------------------------------------- 6 8D-Reklamationen (Qualität, komplex)
KUNDEN = ["OEM Nord", "OEM Süd", "OEM Premium", "Nutzfahrzeug AG", "Ersatzteilgeschäft"]
D_STUFEN = ["D1 Team", "D2 Problem", "D3 Sofortmaßnahme", "D4 Ursache", "D5 Abstellmaßnahme", "D6 Umsetzung",
            "D7 Vorbeugung", "D8 Abschluss"]
rekla = []
for i in range(24):
    rekla.append({"nr": f"Q-{2026}-{100 + i}", "kunde": R.choice(KUNDEN),
                  "teil": R.choice(["Zahnstange 7.8", "Lenkgetriebe EPSapa", "Servoeinheit Gen4", "Ventilkolben", "Ritzelwelle"]),
                  "fehlerbild": R.choice(["Geräusch beim Lenken", "Undichtigkeit", "Lenkmoment zu hoch", "Gratbildung Verzahnung",
                                          "Falsche Variante verbaut", "Korrosion", "Fehlercode Steuergerät"]),
                  "eingang": days(-90, -1), "status": R.choice(D_STUFEN), "verantwortlich": person(),
                  "kosten": round(R.uniform(300, 48000), 2), "anzahl": R.randint(1, 400)})
app("gmd-8d", "8D-Reklamationen", "🧾", "Qualitätsingenieur", "komplex",
    "Kundenreklamationen nach 8D: Status je Disziplin, Maßnahmen, Kosten, Alter",
    [t("Reklamationen", "reklamationen",
       f("Nummer", "nr", required=True), f("Kunde", "kunde", "choice", KUNDEN), f("Teil", "teil"),
       f("Fehlerbild", "fehlerbild"), f("Eingang", "eingang", "date"),
       f("8D-Status", "status", "choice", D_STUFEN), f("Verantwortlich", "verantwortlich"),
       f("Kosten (€)", "kosten", "decimal"), f("Betroffene Teile", "anzahl", "number"),
       f("Alter (Tage)", "alter", "number", formular=False)),
     t("Maßnahmen", "massnahmen",
       f("Reklamation", "reklamation", "reference", ref="reklamationen", required=True),
       f("Maßnahme", "massnahme", required=True),
       f("Typ", "typ", "choice", ["Sofortmaßnahme", "Abstellmaßnahme", "Vorbeugemaßnahme"]),
       f("Verantwortlich", "verantwortlich"), f("Fällig", "faellig", "date"), f("Erledigt", "erledigt", "bool"))],
    [page("Übersicht", "uebersicht",
          b("heading", text="8D-Reklamationen", level="1"),
          b("filter", entity="reklamationen", field="kunde", field2="status", field3="teil"),
          b("stat", width=3, label="Reklamationen", entity="reklamationen"),
          b("stat", width=3, label="Kosten gesamt", entity="reklamationen", aggregate="sum", field="kosten", unit="€"),
          b("stat", width=3, label="Offen (vor D8)", entity="reklamationen", where="8D-Status != D8 Abschluss"),
          b("stat", width=3, label="Älter als 60 Tage, offen", entity="reklamationen",
            where="8D-Status != D8 Abschluss\nEingang < heute-60", warn_at="1", alarm_at="4"),
          b("kanban", title="Nach 8D-Status", entity="reklamationen", field="status", detail="kunde", limit=6),
          b("table", entity="reklamationen", searchable=True)),
     page("Reklamation", "reklamation",
          b("stepper", title="8D-Fortschritt", entity="reklamationen", field="status"),
          b("detail", width=6, entity="reklamationen"),
          b("related_list", width=6, title="Maßnahmen", entity="massnahmen", ref_field="reklamation"), nav=False),
     page("Auswertung", "auswertung",
          b("donut", width=6, label="Nach Kunde", entity="reklamationen", field="kunde"),
          b("chart", width=6, label="Nach Teil (Anzahl)", entity="reklamationen", field="teil"),
          b("chart", width=6, label="Kosten je Kunde (€)", entity="reklamationen", field="kunde", agg="sum",
            value_field="kosten", pareto=True),
          b("pivot", width=6, title="Kosten Kunde × Teil", entity="reklamationen", row_field="kunde", col_field="teil",
            agg="sum", value_field="kosten"),
          b("line", label="Eingänge pro Woche", entity="reklamationen", date_field="eingang", period="week", count=13)),
     page("Maßnahmen", "massnahmen",
          b("filter", entity="massnahmen", field="typ", field2="erledigt"),
          b("checklist", entity="massnahmen", field="erledigt", label_field="massnahme", detail="reklamation"),
          b("form", entity="massnahmen", submit_label="Maßnahme anlegen"))],
    {"reklamationen": rekla,
     "massnahmen": [{"reklamation": f"#{R.randint(1, 24)}", "massnahme": m,
                     "typ": R.choice(["Sofortmaßnahme", "Abstellmaßnahme", "Vorbeugemaßnahme"]),
                     "verantwortlich": person(), "faellig": days(-10, 30), "erledigt": R.random() < 0.4}
                    for m in ["100%-Prüfung Lager", "Sortieraktion beim Kunden", "Poka-Yoke Variantenabfrage",
                              "Werkzeugwechselintervall verkürzen", "FMEA aktualisieren", "Lieferant auditieren",
                              "Prüfplan Merkmal 12 ergänzen", "Schulung Werker Station 30", "Korrosionsschutz erhöhen",
                              "Ishikawa-Workshop", "Bauteilanalyse Labor", "Lessons Learned verteilen"] * 2]},
    [
     script("Alter berechnen", """
import datetime
if record.get("eingang"):
    alter = (datetime.date.today() - datetime.date.fromisoformat(record["eingang"])).days
    record["alter"] = alter
""", trigger="save", entity="reklamationen")],
    [gap("kennzahl_bedingung", "„Offen“ und „älter als 60 Tage“ per Skript.",
         jetzt="Kennzahlen mit Bedingung, „älter als 60 Tage“ mit Ampel."),
     gap("diagramm_summe", "Kosten je Kunde absteigend: Balkendiagramm summiert nicht – Tabelle aus dem Skript.",
         jetzt="Balkendiagramm mit Summe der Kosten und Pareto-Anteil."),
     gap("datumsformel", "„Alter (Tage)“ = heute − Eingang: per Skript beim Speichern (veraltet ohne erneutes Speichern).")])

# ---------------------------------------------------------------- 7 SPC Zahnstange (Qualitätsingenieur, komplex)
MASCHINEN = ["Schleifmaschine S1", "Schleifmaschine S2", "Schleifmaschine S3"]
messungen = []
for d in range(-29, 1):
    for m in MASCHINEN:
        mu = {"Schleifmaschine S1": 24.000, "Schleifmaschine S2": 24.004, "Schleifmaschine S3": 23.998}[m]
        drift = 0.0004 * (d + 29) if m == "Schleifmaschine S2" else 0
        for _ in range(2):
            messungen.append({"datum": f"@{d:+d}", "maschine": m, "merkmal": "Ø Zahnstange 24 h7",
                              "wert": round(R.gauss(mu + drift, 0.0035), 4), "pruefer": person()})
app("gmd-spc", "SPC Zahnstangen-Durchmesser", "📐", "Qualitätsingenieur", "komplex",
    "Messwerte erfassen, Regelkarte, Verteilung, Prozessfähigkeit Cp/Cpk mit verstellbaren Toleranzen",
    [t("Messungen", "messungen",
       f("Datum", "datum", "date", required=True), f("Maschine", "maschine", "choice", MASCHINEN, required=True),
       f("Merkmal", "merkmal", "choice", ["Ø Zahnstange 24 h7", "Rundlauf", "Oberflächenhärte HRC"]),
       f("Messwert (mm)", "wert", "decimal", required=True), f("Prüfer/in", "pruefer")),
     t("Toleranzen", "toleranzen",
       f("Grenze", "name", required=True), f("Wert (µm Abweichung von 24,000)", "wert", "number"))],
    [page("Regelkarte", "regelkarte",
          b("heading", text="SPC · Ø Zahnstange 24 h7", subtitle="Nennmaß 24,000 mm · h7: 0 / −21 µm (hier zur Übung symmetrisch einstellbar)", level="1"),
          b("filter", entity="messungen", field="maschine"),
          b("notice", name="ampel", title="Prozessfähigkeit", text="wird berechnet …"),
          b("stat", width=3, name="k_cp", label="Cp"),
          b("stat", width=3, name="k_cpk", label="Cpk"),
          b("stat", width=3, label="Mittelwert", entity="messungen", aggregate="avg", field="wert", unit="mm"),
          b("stat", width=3, name="k_aus", label="Außerhalb Toleranz"),
          b("line", label="Mittelwert je Tag (Regelkarte mit OEG und UEG)", entity="messungen", date_field="datum",
            aggregate="avg", field="wert", period="day", count=30, show_band=True, threshold="24,008",
            threshold_low="23,992"),
          b("histogram", width=6, title="Verteilung je Maschine", entity="messungen", field="wert", group_field="maschine", bins=12),
          b("boxplot", width=6, title="Streuung je Maschine", entity="messungen", field="wert", group_field="maschine")),
     page("Toleranzen", "toleranzen",
          b("heading", text="Was wäre, wenn … die Toleranz anders wäre?", level="2"),
          b("sliders", width=6, title="Toleranzgrenzen in µm", entity="toleranzen", field="wert", label_field="name",
            min=-30, max=30, step=1, unit="µm"),
          b("output", width=6, name="was_waere", label="Cpk je Maschine")),
     page("Erfassen", "erfassen",
          b("form", width=6, entity="messungen", submit_label="Messwert speichern"),
          b("csv_import", width=6, entity="messungen", label="Messprotokoll (CSV) laden"),
          b("table", entity="messungen", page_size=20))],
    {"messungen": messungen, "toleranzen": [{"name": "UGW", "wert": -12}, {"name": "OGW", "wert": 12}]},
    [script("Prozessfähigkeit", """
import statistics
tol = {r["name"]: (r["wert"] or 0) for r in app.table("toleranzen").all()}
ugw = 24 + tol.get("UGW", -12) / 1000
ogw = 24 + tol.get("OGW", 12) / 1000
filt = {}
if params.get("messungen.maschine"):
    filt["maschine"] = params.get("messungen.maschine")
werte = [r["wert"] for r in app.table("messungen").filter(**filt) if r["wert"] is not None]
def kennwerte(w):
    if len(w) < 3:
        return None, None
    mu, s = statistics.mean(w), statistics.stdev(w)
    return round((ogw - ugw) / (6 * s), 2), round(min(ogw - mu, mu - ugw) / (3 * s), 2)
cp, cpk = kennwerte(werte)
ui.set("k_cp", value=cp if cp is not None else "–")
ui.set("k_cpk", value=cpk if cpk is not None else "–")
ui.set("k_aus", value=len([w for w in werte if w < ugw or w > ogw]))
if cpk is not None:
    ton = "success" if cpk >= 1.33 else ("warning" if cpk >= 1.0 else "danger")
    de = lambda x, n=2: f"{x:.{n}f}".replace(".", ",")
    ui.set("ampel", tone=ton, title=f"Cpk {de(cpk)} – " + ("fähig" if cpk >= 1.33 else ("bedingt fähig" if cpk >= 1 else "nicht fähig")),
           text=f"Grenzen {de(ugw, 3)} … {de(ogw, 3)} mm, n = {len(werte)}")
zeilen = []
for m in ["Schleifmaschine S1", "Schleifmaschine S2", "Schleifmaschine S3"]:
    w = [r["wert"] for r in app.table("messungen").filter(maschine=m) if r["wert"] is not None]
    a, k = kennwerte(w)
    zeilen.append({"Maschine": m, "n": len(w), "Cp": a, "Cpk": k, "Bewertung": "fähig" if (k or 0) >= 1.33 else "prüfen"})
ui.set("was_waere", rows=zeilen)
""")],
    [gap("regelkarte", "Regelkarte mit OEG und UEG: Liniendiagramm hat nur einen Schwellwert, UEG fehlt.",
         jetzt="Liniendiagramm mit oberer und unterer Grenze; Punkte außerhalb werden rot markiert."),
     gap("kennzahl_berechnet", "Cp/Cpk/außerhalb Toleranz: Statistik per Skript (statistics.stdev)."),
     gap("ampel", "Fähigkeits-Ampel als Hinweis mit tone.")])

# ---------------------------------------------------------------- 8 Rüstzeit-Analyse SMED (Prozessingenieur, mittel)
URSACHEN = ["Werkzeug nicht vorbereitet", "Warten auf Erstmusterfreigabe", "Programm suchen", "Spannmittel fehlt",
            "Kran belegt", "Keine Verzögerung"]
ruesten = []
for _n in range(80):
    intern = R.randint(12, 55)
    extern = R.randint(5, 30)
    ursache = R.choices(URSACHEN, [5, 4, 2, 3, 1, 6])[0]
    verz = 0 if ursache == "Keine Verzögerung" else R.randint(5, 40)
    ruesten.append({"datum": days(-60, 0), "linie": R.choice(LINIEN[:3]), "von": R.choice(["7.8", "8.1", "8.4", "Gen4-L", "Gen4-R"]),
                    "nach": R.choice(["7.8", "8.1", "8.4", "Gen4-L", "Gen4-R"]), "intern": intern, "extern": extern,
                    "verzoegerung": verz, "ursache": ursache})
app("gmd-smed", "Rüstzeit-Analyse (SMED)", "⏱️", "Prozessingenieur", "mittel",
    "Rüstvorgänge erfassen, intern/extern trennen, Verzögerungen nach Ursache auswerten",
    [t("Rüstvorgänge", "ruesten",
       f("Datum", "datum", "date", required=True), f("Linie", "linie", "choice", LINIEN[:3]),
       f("Von Typ", "von"), f("Nach Typ", "nach"),
       f("Intern (min)", "intern", "number"), f("Extern (min)", "extern", "number"),
       f("Verzögerung (min)", "verzoegerung", "number"),
       f("Rüstzeit gesamt (min)", "gesamt", "number", formula="intern + verzoegerung", formular=False),
       f("Ursache Verzögerung", "ursache", "choice", URSACHEN))],
    [page("Analyse", "analyse",
          b("heading", text="Rüstzeit-Analyse", subtitle="Ziel: Rüstzeit < 30 min (Single Minute Exchange of Die)", level="1"),
          b("filter", entity="ruesten", field="linie", field2="ursache", field3="datum"),
          b("stat", width=4, label="Ø Rüstzeit", entity="ruesten", aggregate="avg", field="gesamt", unit="min"),
          b("stat", width=4, label="Verlorene Minuten (Verzögerung)", entity="ruesten", aggregate="sum", field="verzoegerung", unit="min"),
          b("progress", width=4, label="Rüstvorgänge im Monat (Ziel 100)", entity="ruesten", target=100,
            where="Datum >= monatsanfang"),
          b("chart", width=6, label="Pareto: Verzögerung nach Ursache (Summe min)", entity="ruesten", field="ursache",
            agg="sum", value_field="verzoegerung", pareto=True, where="Ursache != Keine Verzögerung"),
          b("scatter", width=6, title="Intern vs. Extern", entity="ruesten", x_field="intern", y_field="extern",
            color_field="linie", trendline=True),
          b("line", label="Ø Rüstzeit je Woche", entity="ruesten", date_field="datum", aggregate="avg", field="gesamt",
            period="week", count=9, threshold="30"),
          b("pivot", title="Ø Rüstzeit Linie × Zieltyp", entity="ruesten", row_field="linie", col_field="nach", agg="avg",
            value_field="gesamt")),
     page("Erfassen", "erfassen",
          b("form", entity="ruesten", submit_label="Rüstvorgang speichern"),
          b("table", entity="ruesten", page_size=15))],
    {"ruesten": ruesten}, [],
    [gap("diagramm_summe", "Pareto über Summe der Minuten nur mit Spec-Chart (Vega-Lite-JSON von Hand) – "
                           "für Fachanwender kaum machbar.", jetzt="Balkendiagramm mit Summe und Pareto-Anteil."),
     gap("fortschritt_zeitraum", "„Rüstvorgänge im Monat“: Fortschritt zählt alle Einträge, nicht nur den laufenden Monat.",
         jetzt="Fortschritt mit Bedingung „Datum >= monatsanfang“.")])

# ---------------------------------------------------------------- 9 Materialnachschub (Logistik, mittel)
MATERIAL = [("1 345 678 901", "Ritzelwelle 7.8", "Supermarkt A-01", 480, 300), ("1 345 678 902", "Zahnstangenrohling", "Supermarkt A-02", 120, 200),
            ("1 345 678 903", "Dichtring 32x2", "Supermarkt B-04", 4000, 2500), ("1 345 678 904", "Gehäuse LG Alu", "Hochregal 12", 90, 150),
            ("1 345 678 905", "Steuergerät Gen4", "Sperrbereich C", 260, 200), ("1 345 678 906", "Kugelumlaufmutter", "Supermarkt A-05", 310, 250),
            ("1 345 678 907", "Elektromotor 80 W", "Hochregal 07", 75, 120), ("1 345 678 908", "Schrauben M8x25", "Kanban-Regal 1", 9000, 5000)]
app("gmd-nachschub", "Materialnachschub (Routenzug)", "🚚", "Logistik", "mittel",
    "Nachschub an die Linie anfordern, Routenzug-Aufträge abarbeiten, Unterdeckungen erkennen",
    [t("Material", "material",
       f("Sachnummer", "sachnr", required=True), f("Bezeichnung", "bezeichnung"), f("Lagerort", "lagerort"),
       f("Bestand", "bestand", "number"), f("Mindestbestand", "mindest", "number"),
       f("Reichweite über Minimum", "puffer", "number", formula="bestand - mindest", formular=False)),
     t("Anforderungen", "anforderungen",
       f("Material", "material", "reference", ref="material", required=True),
       f("Linie", "linie", "choice", LINIEN, required=True), f("Behälter", "behaelter", "number"),
       f("Status", "status", "choice", ["Angefordert", "Kommissioniert", "Auf Routenzug", "Geliefert"]),
       f("Angefordert am", "datum", "date"), f("Dringend", "dringend", "bool"))],
    [page("Anfordern", "anfordern",
          b("heading", text="Nachschub anfordern", subtitle="Kanban-Karte scannen oder Material auswählen", level="1"),
          b("form", width=6, entity="anforderungen", submit_label="Anfordern"),
          b("stat", width=6, label="Material unter Mindestbestand", entity="material",
            where="Bestand < Mindestbestand", warn_at="1", alarm_at="3")),
     page("Routenzug", "routenzug",
          b("filter", entity="anforderungen", field="linie", field2="dringend"),
          b("kanban", title="Aufträge", entity="anforderungen", field="status", detail="material", limit=10),
          b("donut", width=6, label="Anforderungen je Linie", entity="anforderungen", field="linie"),
          b("stat", width=6, label="Nicht geliefert", entity="anforderungen", where="Status != Geliefert")),
     page("Bestand", "bestand",
          b("table", title="Material unter Mindestbestand", entity="material", where="Bestand < Mindestbestand"),
          b("table", entity="material", searchable=True),
          b("csv_import", entity="material", label="Bestand aus SAP-Export (CSV) laden"))],
    {"material": [{"sachnr": s, "bezeichnung": bz, "lagerort": lo, "bestand": be, "mindest": mi} for s, bz, lo, be, mi in MATERIAL],
     "anforderungen": [{"material": f"#{R.randint(1, 8)}", "linie": R.choice(LINIEN), "behaelter": R.randint(1, 6),
                        "status": R.choice(["Angefordert", "Kommissioniert", "Auf Routenzug", "Geliefert", "Geliefert"]),
                        "datum": days(-3, 0), "dringend": R.random() < 0.2} for _ in range(30)]},
    [],
    [gap("liste_bedingung", "Material unter Mindestbestand (Bedingung zwischen zwei Feldern) nur per Skript.",
         jetzt="Liste mit Bedingung „Bestand < Mindestbestand“ (Feld gegen Feld)."),
     gap("ampel", "Unterdeckung als Hinweis mit tone.", jetzt="Kennzahl mit Ampel."),
     gap("kennzahl_bedingung", "„Nicht geliefert“ per Skript.", jetzt="Kennzahl mit Bedingung, kein Skript mehr.")])

# ---------------------------------------------------------------- 10 Qualifikationsmatrix (Meister/HR, mittel)
STATIONEN = ["ST10 Rohr einlegen", "ST20 Verzahnen", "ST30 Härten", "ST40 Schrauben", "ST50 Fügen", "ST60 Prüfstand"]
leute = [person() for _ in range(14)]
qualis = []
for pi in range(1, 15):
    for si in range(1, 7):
        if R.random() < 0.75:
            qualis.append({"mitarbeiter": f"#{pi}", "station": f"#{si}", "stufe": R.choices([1, 2, 3, 4], [2, 3, 4, 1])[0],
                           "gueltig": days(-20, 400)})
app("gmd-quali", "Qualifikationsmatrix", "🎓", "Meister / Personal", "mittel",
    "Wer kann welche Station? ILUO-Stufen, ablaufende Qualifikationen, Springer-Planung",
    [t("Mitarbeitende", "mitarbeitende",
       f("Name", "name", required=True), f("Schicht", "schicht", "choice", SCHICHTEN),
       f("Kostenstelle", "kst", "choice", ["4711 Montage", "4712 Zerspanung", "4713 Prüffeld"])),
     t("Stationen", "stationen", f("Station", "name", required=True), f("Linie", "linie", "choice", LINIEN)),
     t("Qualifikationen", "qualifikationen",
       f("Mitarbeiter/in", "mitarbeiter", "reference", ref="mitarbeitende", required=True),
       f("Station", "station", "reference", ref="stationen", required=True),
       f("Stufe (1=I angelernt … 4=O Trainer)", "stufe", "number"), f("Gültig bis", "gueltig", "date"))],
    [page("Matrix", "matrix",
          b("heading", text="Qualifikationsmatrix", subtitle="1 = I (in Ausbildung) · 2 = L (unter Aufsicht) · 3 = U (selbstständig) · 4 = O (Trainer)", level="1"),
          b("filter", entity="qualifikationen", field="station"),
          b("heatmap", title="Stufe je Person und Station", entity="qualifikationen", mode="crosstab",
            row_field="mitarbeiter", col_field="station", value_field="stufe", agg="avg"),
          b("output", width=6, name="engpass", label="Stationen mit weniger als 3 selbstständigen Personen"),
          b("table", width=6, title="Läuft in den nächsten 60 Tagen ab", entity="qualifikationen",
            where="Gültig bis <= heute+60")),
     page("Pflegen", "pflegen",
          b("form", width=6, entity="qualifikationen", submit_label="Qualifikation speichern"),
          b("table", width=6, entity="mitarbeitende"),
          b("table", entity="qualifikationen", searchable=True))],
    {"mitarbeitende": [{"name": n, "schicht": R.choice(SCHICHTEN), "kst": R.choice(["4711 Montage", "4712 Zerspanung", "4713 Prüffeld"])}
                       for n in leute],
     "stationen": [{"name": s, "linie": "ZS-1 Zahnstange" if i < 3 else "LG-2 Lenkgetriebe"} for i, s in enumerate(STATIONEN)],
     "qualifikationen": qualis},
    [script("Engpässe", """
import datetime
heute = datetime.date.today()
leute = {p["id"]: p["name"] for p in app.table("mitarbeitende").all()}
stationen = {s["id"]: s["name"] for s in app.table("stationen").all()}
q = app.table("qualifikationen").all()
zeilen = []
for sid, name in stationen.items():
    n = len([x for x in q if int(x["station"] or 0) == sid and (x["stufe"] or 0) >= 3])
    if n < 3:
        zeilen.append({"Station": name, "selbstständig": n, "fehlen": 3 - n})
ui.set("engpass", rows=zeilen)
""", page="matrix")],
    [gap("matrix_symbole", "ILUO-Matrix: Heatmap zeigt Zahlen statt Symbole (Viertelkreis I/L/U/O)."),
     gap("liste_bedingung", "„Läuft in 60 Tagen ab“ und Engpass-Stationen per Skript.",
         jetzt="„Läuft ab“ als Liste mit Bedingung. Engpässe (zählen je Station mit Schwelle) bleiben Skript.")])

# ---------------------------------------------------------------- 11 Arbeitssicherheit (EHS, mittel)
ARTEN = ["Unsichere Situation", "Beinahe-Unfall", "Erste-Hilfe-Fall", "Unfall ohne Ausfall", "Unfall mit Ausfall"]
meldungen = [{"datum": days(-60, 0), "bereich": R.choice(BEREICHE), "art": R.choices(ARTEN, [8, 5, 2, 1, 0.3])[0],
              "beschreibung": R.choice(["Ölspur im Gang", "Stapler zu schnell", "Schutztür überbrückt", "Stolperstelle Kabel",
                                        "Schnittverletzung am Grat", "Last ungesichert", "Fluchtweg zugestellt"]),
              "status": R.choice(["Neu", "In Bearbeitung", "Erledigt", "Erledigt"])} for _ in range(45)]
app("gmd-sicherheit", "Arbeitssicherheit & Sicherheitskreuz", "🦺", "Arbeitssicherheit / alle", "mittel",
    "Beinahe-Unfälle anonym melden, Sicherheitskreuz, Schwerpunkte nach Bereich",
    [t("Meldungen", "meldungen",
       f("Datum", "datum", "date", required=True), f("Bereich", "bereich", "choice", BEREICHE, required=True),
       f("Art", "art", "choice", ARTEN, required=True), f("Was ist passiert?", "beschreibung", "longtext"),
       f("Sofortmaßnahme", "massnahme"), f("Status", "status", "choice", ["Neu", "In Bearbeitung", "Erledigt"]))],
    [page("Melden", "melden",
          b("heading", text="Gefahr gesehen? Melden!", subtitle="Anonym – auch ohne Anmeldung über den QR-Code am Infoboard", level="1"),
          b("form", entity="meldungen", submit_label="Meldung absenden"), public=True),
     page("Sicherheitskreuz", "kreuz",
          b("stat", width=4, label="Tage ohne Unfall mit Ausfall", entity="meldungen", aggregate="days_since",
            field="datum", where="Art = Unfall mit Ausfall", direction="lower_worse", warn_at="30", alarm_at="7"),
          b("stat", width=4, label="Meldungen diesen Monat", entity="meldungen", where="Datum >= monatsanfang"),
          b("progress", width=4, label="Meldungen (Ziel 40 im Quartal)", entity="meldungen", target=40,
            where="Datum >= quartalsanfang"),
          b("output", name="kreuz", label="Sicherheitskreuz (aktueller Monat)"),
          b("calendar", title="Meldungen im Kalender", entity="meldungen", date_field="datum", label_field="art",
            color_field="art", create_links=False)),
     page("Auswertung", "auswertung",
          b("filter", entity="meldungen", field="bereich", field2="art", field3="status"),
          b("heatmap", title="Bereich × Art", entity="meldungen", mode="crosstab", row_field="bereich", col_field="art"),
          b("donut", width=6, label="Nach Art", entity="meldungen", field="art"),
          b("chart", width=6, label="Nach Bereich", entity="meldungen", field="bereich"),
          b("kanban", entity="meldungen", field="status", detail="bereich"))],
    {"meldungen": meldungen},
    [script("Sicherheitskreuz", """
import datetime
heute = datetime.date.today()
rows = app.table("meldungen").all()
rang = {"Unfall mit Ausfall": "🟥", "Unfall ohne Ausfall": "🟧", "Erste-Hilfe-Fall": "🟨", "Beinahe-Unfall": "🟦", "Unsichere Situation": "🟦"}
woche = []
zeilen = []
for tag in range(1, heute.day + 1):
    d = heute.replace(day=tag).isoformat()
    an = [r["art"] for r in rows if r["datum"] == d]
    farbe = "🟩"
    for art in ["Unfall mit Ausfall", "Unfall ohne Ausfall", "Erste-Hilfe-Fall"]:
        if art in an:
            farbe = rang[art]
            break
    woche.append(f"{tag:02d} {farbe}")
    if len(woche) == 7:
        zeilen.append({"Tage": "  ".join(woche)}); woche = []
if woche:
    zeilen.append({"Tage": "  ".join(woche)})
ui.set("kreuz", rows=zeilen)
""", page="kreuz")],
    [gap("sicherheitskreuz", "Grünes Kreuz (Tag je Feld, Farbe nach schwerstem Ereignis): Emoji-Tabelle aus dem Skript."),
     gap("datumsformel", "„Tage ohne Unfall“ per Skript.",
         jetzt="Kennzahl „Tage seit dem letzten Datum“ mit Bedingung „Art = Unfall mit Ausfall“ und Ampel."),
     gap("kennzahl_bedingung", "„Meldungen diesen Monat“ per Skript.", jetzt="Kennzahl mit „Datum >= monatsanfang“."),
     gap("fortschritt_zeitraum", "Fortschritt „im Quartal“ zählt alle Meldungen.",
         jetzt="Fortschritt mit „Datum >= quartalsanfang“.")])

# ---------------------------------------------------------------- 12 Kostenstellen-Controlling (Controller, mittel)
KST = ["4711 Montage", "4712 Zerspanung", "4713 Prüffeld", "4720 Instandhaltung", "4730 Logistik"]
KOSTENARTEN = ["Personal", "Hilfs- & Betriebsstoffe", "Werkzeuge", "Fremdleistung", "Energie", "Reparatur"]
buchungen = [{"datum": days(-150, 0), "kst": R.choice(KST), "kostenart": R.choice(KOSTENARTEN),
              "betrag": round(R.uniform(200, 18000), 2), "text": R.choice(["Rahmenvertrag", "Einzelbestellung", "Umbuchung", "Monatsabgrenzung"])}
             for _ in range(220)]
app("gmd-controlling", "Kostenstellen-Controlling", "💶", "Controller / Kostenstellenverantwortliche", "mittel",
    "Ist-Kosten gegen Budget je Kostenstelle, Kostenarten-Pivot, Hochrechnung",
    [t("Buchungen", "buchungen",
       f("Datum", "datum", "date", required=True), f("Kostenstelle", "kst", "choice", KST, required=True),
       f("Kostenart", "kostenart", "choice", KOSTENARTEN), f("Betrag (€)", "betrag", "decimal", required=True),
       f("Text", "text")),
     t("Budgets", "budgets", f("Kostenstelle", "kst", "choice", KST, required=True), f("Budget Jahr (€)", "budget", "decimal"))],
    [page("Cockpit", "cockpit",
          b("heading", text="Kostenstellen-Cockpit", subtitle="Geschäftsjahr laufend", level="1"),
          b("filter", entity="buchungen", field="kst", field2="kostenart", field3="datum"),
          b("stat", width=4, label="Ist-Kosten", entity="buchungen", aggregate="sum", field="betrag", unit="€"),
          b("progress", width=8, name="budget", label="Ausschöpfung Gesamtbudget", entity="buchungen", aggregate="sum",
            field="betrag", target=1000000, unit="€"),
          *[b("notice", width=4, name=f"kst{i}", title=k, text="…") for i, k in enumerate(KST, 1)],
          b("pivot", title="Kostenstelle × Kostenart (Summe €)", entity="buchungen", row_field="kst", col_field="kostenart",
            agg="sum", value_field="betrag"),
          b("line", label="Kosten je Monat", entity="buchungen", date_field="datum", aggregate="sum", field="betrag",
            period="month", count=6, unit="€")),
     page("Buchungen", "buchungen",
          b("table", entity="buchungen", searchable=True, page_size=25),
          b("export", entity="buchungen", label="Als CSV für Excel"),
          b("csv_import", entity="buchungen", label="SAP-Export (CSV) laden")),
     page("Budgets", "budgets", b("table", entity="budgets"), b("form", entity="budgets"))],
    {"buchungen": buchungen, "budgets": [{"kst": k, "budget": v} for k, v in zip(KST, [420000, 380000, 160000, 210000, 140000])]},
    [script("Budget-Ampeln", """
import datetime
heute = datetime.date.today()
anteil_jahr = (heute.timetuple().tm_yday) / 365
budgets = {b["kst"]: b["budget"] or 0 for b in app.table("budgets").all()}
ist = {}
for r in app.table("buchungen").all():
    ist[r["kst"]] = ist.get(r["kst"], 0) + (r["betrag"] or 0)
kst = __LISTE__
for i, k in enumerate(kst, start=1):
    b = budgets.get(k, 0); x = ist.get(k, 0)
    quote = 100 * x / b if b else 0
    hoch = x / anteil_jahr if anteil_jahr else 0
    ton = "danger" if hoch > b * 1.05 else ("warning" if hoch > b * 0.95 else "success")
    ui.set(f"kst{i}", tone=ton, text=f"Ist {x:,.0f} € von {b:,.0f} € ({quote:.0f} %) · Hochrechnung {hoch:,.0f} €".replace(",", "."))
ui.set("budget", label=f"Ausschöpfung Gesamtbudget ({sum(budgets.values()):,.0f} €)".replace(",", "."))
""".replace("__LISTE__", json.dumps(KST, ensure_ascii=False)), page="cockpit")],
    [gap("ziel_aus_tabelle", "Fortschritt: Zielwert ist eine feste Zahl, das Budget steht aber in einer Tabelle – nur die Beschriftung lässt sich per Skript ändern, der Zielwert nicht."),
     gap("ampel", "5 Budget-Ampeln mit Hochrechnung als Hinweis-Bausteine.")])

# ---------------------------------------------------------------- 13 OEE-Cockpit (Werksleiter, komplex)
oee = []
for d in range(-41, 1):
    for linie in LINIEN[:5]:
        for s in SCHICHTEN[:2] if linie != "HT-5 Härterei" else SCHICHTEN:
            plan = 450
            still = R.choice([0, 5, 10, 15, 20, 30, 45, 60, 90]) + (25 if linie == "EPS-3 Servoeinheit" and d > -14 else 0)
            takt = {"ZS-1 Zahnstange": 0.7, "LG-2 Lenkgetriebe": 0.9, "EPS-3 Servoeinheit": 1.1, "PR-4 Endprüfung": 0.5, "HT-5 Härterei": 0.8}[linie]
            soll = int((plan - still) / takt)
            ist = int(soll * R.uniform(0.82, 0.99))
            gut = ist - R.randint(0, max(1, ist // 40))
            oee.append({"datum": f"@{d:+d}", "linie": linie, "schicht": s, "planzeit": plan, "stillstand": still,
                        "soll": soll, "ist": ist, "gut": gut})
app("gmd-oee", "OEE-Cockpit", "🏭", "Werksleiter / Fertigungsleiter", "komplex",
    "Verfügbarkeit × Leistung × Qualität je Linie und Schicht, Trends, Ampeln und Verlustanalyse",
    [t("Schichtdaten", "schichtdaten",
       f("Datum", "datum", "date", required=True), f("Linie", "linie", "choice", LINIEN, required=True),
       f("Schicht", "schicht", "choice", SCHICHTEN), f("Planzeit (min)", "planzeit", "number"),
       f("Stillstand (min)", "stillstand", "number"), f("Soll bei Laufzeit (Stück)", "soll", "number"),
       f("Ist (Stück)", "ist", "number"), f("Gut (Stück)", "gut", "number"),
       f("Verfügbarkeit (%)", "vf", "decimal", formula="round((planzeit - stillstand) / planzeit * 100, 1)", formular=False),
       f("Leistung (%)", "lg", "decimal", formula="round(ist / soll * 100, 1)", formular=False),
       f("Qualität (%)", "ql", "decimal", formula="round(gut / ist * 100, 1)", formular=False),
       f("OEE (%)", "oee", "decimal",
         formula="round((planzeit - stillstand) / planzeit * ist / soll * gut / ist * 100, 1)", formular=False))],
    [page("Cockpit", "cockpit",
          b("heading", text="OEE-Cockpit Werk Gmünd", subtitle="Ziel 75 % · Weltklasse 85 %", level="1"),
          b("filter", entity="schichtdaten", field="linie", field2="schicht", field3="datum"),
          b("stat", width=3, label="OEE", entity="schichtdaten", aggregate="avg", field="oee", unit="%"),
          b("stat", width=3, label="Verfügbarkeit", entity="schichtdaten", aggregate="avg", field="vf", unit="%"),
          b("stat", width=3, label="Leistung", entity="schichtdaten", aggregate="avg", field="lg", unit="%"),
          b("stat", width=3, label="Qualität", entity="schichtdaten", aggregate="avg", field="ql", unit="%"),
          *[b("stat", width=4, label=li, entity="schichtdaten", aggregate="avg", field="oee", unit="%",
              where=f"Linie = {li}", direction="lower_worse", warn_at="75", alarm_at="65",
              compare_field="datum", compare_days=7) for li in LINIEN[:5]],
          b("notice", width=4, title="So liest man die Ampeln",
            text="OEE der letzten 7 Tage je Linie. Grün ab 75 %, rot unter 65 %. Der Pfeil vergleicht mit den 7 Tagen davor."),
          b("line", label="OEE je Tag", entity="schichtdaten", date_field="datum", aggregate="avg", field="oee",
            period="day", count=42, unit="%", show_band=True, threshold="75"),
          b("chart", width=6, label="Ø OEE je Linie (%)", entity="schichtdaten", field="linie", agg="avg",
            value_field="oee"),
          b("pivot", width=6, title="OEE Linie × Schicht", entity="schichtdaten", row_field="linie", col_field="schicht",
            agg="avg", value_field="oee")),
     page("Verluste", "verluste",
          b("filter", entity="schichtdaten", field="linie", field2="datum"),
          b("chart", label="Stillstand je Linie (Summe min)", entity="schichtdaten", field="linie", agg="sum",
            value_field="stillstand", pareto=True),
          b("boxplot", width=6, title="OEE-Streuung je Linie", entity="schichtdaten", field="oee", group_field="linie"),
          b("scatter", width=6, title="Stillstand vs. OEE", entity="schichtdaten", x_field="stillstand", y_field="oee",
            color_field="linie", trendline=True),
          b("heatmap", title="Korrelationen", entity="schichtdaten", mode="correlation")),
     page("Erfassung", "erfassung",
          b("form", width=6, entity="schichtdaten", submit_label="Schicht melden"),
          b("csv_import", width=6, entity="schichtdaten", label="MES-Export laden"),
          b("table", entity="schichtdaten", page_size=20))],
    {"schichtdaten": oee},
    [],
    [gap("ampel", "5 Linien-Ampeln mit Trendpfeil (7 Tage gegen Vorwoche) als Hinweis-Bausteine.",
         jetzt="5 Kennzahlen mit Bedingung „Linie = …“, Ampel (niedrig ist schlecht) und 7-Tage-Vergleich – kein Skript mehr."),
     gap("diagramm_summe", "OEE je Linie (Durchschnitt, sortiert) nur als Skript-Tabelle; Stillstand-Summe nur per Spec-Chart.",
         jetzt="Balkendiagramm mit Durchschnitt bzw. Summe."),
     gap("kennzahl_vergleich", "Kennzahl mit Vergleich zum Vorzeitraum (Trendpfeil) fehlt.",
         jetzt="Kennzahl-Einstellung „Vergleich: Zeitraum in Tagen“.")])

# ---------------------------------------------------------------- 14 Projekt Anlauf (Projektingenieur, komplex)
pakete = []
GEWERKE = ["Konstruktion", "Betriebsmittel", "Qualität", "Logistik", "Einkauf", "Produktion"]
start = -60
for name, gew, dauer in ([
        ("Lastenheft Linie", "Konstruktion", 20), ("Anlagenbeschaffung", "Einkauf", 60), ("Vorabnahme Lieferant", "Betriebsmittel", 10),
        ("Aufbau Linie Halle 2", "Betriebsmittel", 25), ("Prüfmittelfähigkeit MSA", "Qualität", 15), ("Logistikkonzept Supermarkt", "Logistik", 20),
        ("Run@Rate 1", "Produktion", 3), ("PPAP Einreichung", "Qualität", 12), ("Mitarbeiterschulung", "Produktion", 18),
        ("Run@Rate 2", "Produktion", 3), ("SOP", "Produktion", 1)]):
    pakete.append({"name": name, "gewerk": gew, "start": f"@{start:+d}", "ende": f"@{start + dauer:+d}",
                   "status": "Erledigt" if start + dauer < 0 else ("In Arbeit" if start < 0 else "Geplant"),
                   "fortschritt": 100 if start + dauer < 0 else (R.randint(20, 80) if start < 0 else 0), "verantwortlich": person()})
    start += max(3, dauer // 2)
app("gmd-anlauf", "Projekt Anlauf EPS Gen 5", "🚀", "Projektingenieur / Projektleiter", "komplex",
    "Arbeitspakete, Meilensteine, Risiken und offene Punkte bis SOP",
    [t("Arbeitspakete", "pakete",
       f("Arbeitspaket", "name", required=True), f("Gewerk", "gewerk", "choice", GEWERKE),
       f("Start", "start", "date"), f("Ende", "ende", "date"),
       f("Status", "status", "choice", ["Geplant", "In Arbeit", "Blockiert", "Erledigt"]),
       f("Fortschritt (%)", "fortschritt", "number"), f("Verantwortlich", "verantwortlich")),
     t("Risiken", "risiken",
       f("Risiko", "titel", required=True), f("Wahrscheinlichkeit (1–5)", "w", "number"),
       f("Auswirkung (1–5)", "a", "number"), f("Risikozahl", "rz", "number", formula="w * a", formular=False),
       f("Maßnahme", "massnahme"), f("Status", "status", "choice", ["Offen", "Mitigiert", "Eingetreten", "Geschlossen"])),
     t("Offene Punkte", "ops",
       f("Punkt", "punkt", required=True), f("Gewerk", "gewerk", "choice", GEWERKE),
       f("Fällig", "faellig", "date"), f("Erledigt", "erledigt", "bool"), f("Verantwortlich", "verantwortlich"))],
    [page("Status", "status",
          b("heading", text="Projekt EPS Gen 5 · Anlauf Halle 2", level="1"),
          b("stat", width=3, label="Tage bis SOP", entity="pakete", aggregate="days_until", field="start", where="Arbeitspaket = SOP"),
          b("stat", width=3, label="Ø Fortschritt", entity="pakete", aggregate="avg", field="fortschritt", unit="%"),
          b("stat", width=3, label="Blockierte Pakete", entity="pakete", where="Status = Blockiert", warn_at="1", alarm_at="2"),
          b("stat", width=3, label="Risiken mit RZ ≥ 12", entity="risiken", where="Risikozahl >= 12\nStatus = Offen",
            warn_at="1", alarm_at="3"),
          b("notice", name="ampel", title="Projektampel", text="…"),
          b("gantt", title="Arbeitspakete", entity="pakete", start_field="start", end_field="ende", label_field="name",
            group_field="gewerk", color_field="status"),
          b("sliders", width=6, title="Fortschritt melden", entity="pakete", field="fortschritt", label_field="name", step=10, unit="%"),
          b("kanban", width=6, entity="pakete", field="status", detail="gewerk")),
     page("Risiken", "risiken",
          b("heatmap", width=6, title="Risikomatrix (Anzahl)", entity="risiken", mode="crosstab", row_field="w", col_field="a"),
          b("scatter", width=6, title="Risiken", entity="risiken", x_field="w", y_field="a", label_field="titel", size_field="rz"),
          b("table", entity="risiken"), b("form", entity="risiken")),
     page("Offene Punkte", "ops",
          b("filter", entity="ops", field="gewerk", field2="erledigt"),
          b("checklist", entity="ops", field="erledigt", label_field="punkt", detail="gewerk"),
          b("calendar", entity="ops", date_field="faellig", label_field="punkt", color_field="gewerk"),
          b("form", entity="ops"))],
    {"pakete": pakete,
     "risiken": [{"titel": tl, "w": R.randint(1, 5), "a": R.randint(1, 5), "massnahme": m, "status": R.choice(["Offen", "Mitigiert", "Offen"])}
                 for tl, m in [("Lieferverzug Roboterzelle", "Zweitlieferant anfragen"), ("Cpk Verzahnung < 1,33", "Prozessparameter-DoE"),
                               ("Fachkräfte Prüfstand fehlen", "Schulung vorziehen"), ("Software-Freigabe Steuergerät spät", "Wöchentliche Abstimmung OEM"),
                               ("Platz Supermarkt reicht nicht", "Layout-Variante B"), ("Energieanschluss Halle 2", "Elektroplanung beauftragen")]],
     "ops": [{"punkt": p, "gewerk": R.choice(GEWERKE), "faellig": days(-10, 40), "erledigt": R.random() < 0.3, "verantwortlich": person()}
             for p in ["Schutzzaun-Abnahme", "Prüfanweisung ST60", "Behälterkonzept final", "Rüstwagen bestellen", "Ersatzteilliste",
                       "Wartungsplan anlegen", "Arbeitsplatzgestaltung Ergonomie", "Kennzeichnung Sperrlager"]]},
    [script("Projektstatus", """
import datetime
heute = datetime.date.today()
pakete = app.table("pakete").all()
block = [p for p in pakete if p["status"] == "Blockiert"]
verzug = [p for p in pakete if p["ende"] and p["status"] != "Erledigt" and datetime.date.fromisoformat(p["ende"]) < heute]
hoch = [r for r in app.table("risiken").all() if (r["rz"] or 0) >= 12 and r["status"] == "Offen"]
ton = "danger" if block or len(verzug) > 1 else ("warning" if verzug or hoch else "success")
ui.set("ampel", tone=ton, text=f"{len(verzug)} Paket(e) im Verzug, {len(block)} blockiert, {len(hoch)} hohe Risiken offen.")
""", page="status")],
    [gap("datumsformel", "„Tage bis SOP“ per Skript.", jetzt="Kennzahl „Tage bis zum nächsten Datum“ mit Bedingung „Arbeitspaket = SOP“."),
     gap("kennzahl_bedingung", "Blockierte Pakete und hohe Risiken per Skript.", jetzt="Kennzahlen mit Bedingung und Ampel."),
     gap("ampel", "Projektampel als Hinweis mit tone."),
     gap("meilensteine", "Meilensteine als Raute im Zeitstrahl fehlen; SOP ist ein 1-Tages-Balken.")])

# ---------------------------------------------------------------- 15 Ideenmanagement (alle, einfach)
ideen = [{"titel": tl, "bereich": R.choice(BEREICHE), "einreicher": person(), "kategorie": R.choice(["Arbeitssicherheit", "Qualität", "Kosten", "Ergonomie", "Umwelt"]),
          "ersparnis": R.choice([0, 0, 500, 1200, 3500, 8000, 15000]), "status": R.choice(["Eingereicht", "In Prüfung", "Umgesetzt", "Umgesetzt", "Abgelehnt"]),
          "datum": days(-120, 0)} for tl in ["Rutschmatte vor Presse 4", "Schraubenbehälter näher an Station", "LED statt Leuchtstoff Halle 3",
                                            "Druckluft-Leck an Verteiler B suchen", "Einlegehilfe Ritzel", "Mehrweg statt Einweg-Folie",
                                            "Prüfprogramm schneller starten", "Kühlwasser-Kreislauf schließen", "Kabelbinder-Farben je Variante",
                                            "Hubtisch für Gehäuse", "Prüfprotokoll digital", "Werkzeugvoreinstellung extern"]]
app("gmd-ideen", "Ideenmanagement", "💡", "Alle Mitarbeitenden", "einfach",
    "Verbesserungsvorschläge einreichen, Status verfolgen, umgesetzte Einsparungen",
    [t("Ideen", "ideen",
       f("Idee", "titel", required=True), f("Bereich", "bereich", "choice", BEREICHE),
       f("Eingereicht von", "einreicher"), f("Kategorie", "kategorie", "choice", ["Arbeitssicherheit", "Qualität", "Kosten", "Ergonomie", "Umwelt"]),
       f("Einsparung pro Jahr (€)", "ersparnis", "number"),
       f("Status", "status", "choice", ["Eingereicht", "In Prüfung", "Umgesetzt", "Abgelehnt"]),
       f("Datum", "datum", "date"), f("Beschreibung", "beschreibung", "longtext", liste=False))],
    [page("Einreichen", "einreichen",
          b("heading", text="Deine Idee zählt", level="1"),
          b("form", width=8, entity="ideen", submit_label="Idee einreichen"),
          b("stat", width=4, label="Umgesetzte Einsparung", entity="ideen", aggregate="sum", field="ersparnis",
            unit="€/Jahr", where="Status = Umgesetzt")),
     page("Board", "board",
          b("filter", entity="ideen", field="bereich", field2="kategorie"),
          b("kanban", entity="ideen", field="status", detail="einreicher"),
          b("donut", width=6, label="Nach Kategorie", entity="ideen", field="kategorie"),
          b("chart", width=6, label="Nach Bereich", entity="ideen", field="bereich"))],
    {"ideen": ideen},
    [],
    [gap("kennzahl_bedingung", "Summe nur der umgesetzten Ideen per Skript.",
         jetzt="Kennzahl Summe mit Bedingung „Status = Umgesetzt“, kein Skript mehr.")])

# ---------------------------------------------------------------- 16 Fremdfirmen & Besucher (Pforte, mittel)
besuche = [{"name": person(), "firma": R.choice(["Elektro Kurz GmbH", "Gerüstbau Ostalb", "Roboter-Service Süd", "Kältetechnik Rems", "Auditor OEM Nord"]),
            "ansprechpartner": person(), "datum": days(-3, 5), "bereich": R.choice(BEREICHE),
            "unterweisung": R.random() < 0.8, "status": R.choice(["Angemeldet", "Vor Ort", "Abgemeldet"]),
            "ausweis": f"G-{R.randint(100, 199)}"} for _ in range(26)]
app("gmd-besucher", "Fremdfirmen & Besucher", "🪪", "Pforte / Ansprechpartner", "mittel",
    "Voranmeldung, Sicherheitsunterweisung, wer ist gerade im Werk (Evakuierungsliste)",
    [t("Besuche", "besuche",
       f("Name", "name", required=True), f("Firma", "firma", required=True), f("Ansprechpartner/in", "ansprechpartner"),
       f("Datum", "datum", "date", required=True), f("Bereich", "bereich", "choice", BEREICHE),
       f("Sicherheitsunterweisung erhalten", "unterweisung", "bool"),
       f("Status", "status", "choice", ["Angemeldet", "Vor Ort", "Abgemeldet"]), f("Besucherausweis", "ausweis"))],
    [page("Voranmeldung", "anmeldung",
          b("heading", text="Besuch voranmelden", level="1"),
          b("form", entity="besuche", submit_label="Anmelden")),
     page("Pforte", "pforte",
          b("stat", width=4, label="Jetzt im Werk", entity="besuche", where="Status = Vor Ort"),
          b("stat", width=4, label="Heute angemeldet", entity="besuche", where="Datum = heute"),
          b("stat", width=4, label="Vor Ort ohne Unterweisung", entity="besuche",
            where="Status = Vor Ort\nSicherheitsunterweisung erhalten = nein", alarm_at="1"),
          b("search", entity="besuche", field="name"),
          b("table", title="Evakuierungsliste (Status „Vor Ort“)", entity="besuche", where="Status = Vor Ort", page_size=100),
          b("kanban", entity="besuche", field="status", detail="firma")),
     page("Kalender", "kalender",
          b("calendar", entity="besuche", date_field="datum", label_field="firma", color_field="status"))],
    {"besuche": besuche},
    [],
    [gap("kennzahl_bedingung", "3 Kennzahlen mit Bedingung per Skript.", jetzt="3 Kennzahlen mit Bedingung, kein Skript mehr."),
     gap("liste_bedingung", "Evakuierungsliste (nur „Vor Ort“) als Ausgabe-Baustein – druckbar, aber ohne Abmelde-Klick.",
         jetzt="Liste mit Bedingung „Status = Vor Ort“, mit Bearbeiten.")])

# ---------------------------------------------------------------- 17 Energiemonitoring (Facility, komplex)
HALLEN = ["Halle 1", "Halle 2", "Halle 3", "Härterei", "Verwaltung"]
MEDIEN = {"Strom": ("kWh", 0.21), "Druckluft": ("Nm³", 0.025), "Erdgas": ("kWh", 0.08), "Wasser": ("m³", 3.2)}
verbrauch = []
for d in range(-59, 1):
    for h in HALLEN:
        for m, (_e, preis) in MEDIEN.items():
            if h == "Verwaltung" and m == "Druckluft":
                continue
            basis = {"Strom": 8000, "Druckluft": 30000, "Erdgas": 4000, "Wasser": 40}[m] * (2.5 if h == "Härterei" else 1)
            wochenende = 0.35 if ((d + 70) % 7) in (5, 6) else 1
            verbrauch.append({"datum": f"@{d:+d}", "halle": h, "medium": m, "menge": round(basis * wochenende * R.uniform(0.85, 1.15), 1),
                              "preis": preis})
app("gmd-energie", "Energiemonitoring", "⚡", "Facility Management / Werksleitung", "komplex",
    "Verbrauch je Halle und Medium, Kosten, Grundlast am Wochenende, Einspar-Simulation",
    [t("Verbrauch", "verbrauch",
       f("Datum", "datum", "date", required=True), f("Halle", "halle", "choice", HALLEN, required=True),
       f("Medium", "medium", "choice", list(MEDIEN), required=True), f("Menge", "menge", "decimal"),
       f("Preis je Einheit (€)", "preis", "decimal"),
       f("Kosten (€)", "kosten", "decimal", formula="round(menge * preis, 2)", formular=False)),
     t("Maßnahmen", "massnahmen",
       f("Maßnahme", "name", required=True), f("Einsparung (%)", "prozent", "number"),
       f("Medium", "medium", "choice", list(MEDIEN)))],
    [page("Übersicht", "uebersicht",
          b("heading", text="Energiemonitoring", level="1"),
          b("filter", entity="verbrauch", field="halle", field2="medium", field3="datum"),
          b("stat", width=4, label="Energiekosten", entity="verbrauch", aggregate="sum", field="kosten", unit="€"),
          b("stat", width=4, name="k_wochenende", label="Grundlast Wochenende (Strom)"),
          b("stat", width=4, name="k_co2", label="CO₂ (Strom + Gas)"),
          b("line", label="Kosten je Tag", entity="verbrauch", date_field="datum", aggregate="sum", field="kosten",
            period="day", count=60, unit="€"),
          b("pivot", title="Kosten Halle × Medium (€)", entity="verbrauch", row_field="halle", col_field="medium",
            agg="sum", value_field="kosten"),
          b("spec_chart", title="Kosten je Halle und Medium", entity="verbrauch",
            spec=json.dumps({"mark": "bar", "encoding": {"x": {"field": "halle", "type": "nominal"},
                                                          "y": {"field": "kosten", "aggregate": "sum", "type": "quantitative"},
                                                          "color": {"field": "medium", "type": "nominal"}}}, ensure_ascii=False))),
     page("Einsparung", "einsparung",
          b("heading", text="Was bringt welche Maßnahme?", level="2"),
          b("sliders", width=6, title="Einsparung je Maßnahme", entity="massnahmen", field="prozent", label_field="name",
            min=0, max=40, step=1, unit="%"),
          b("output", width=6, name="ergebnis", label="Hochgerechnete Einsparung pro Jahr")),
     page("Daten", "daten",
          b("csv_import", entity="verbrauch", label="Zählerdaten (CSV) laden"),
          b("table", entity="verbrauch", page_size=30, searchable=True))],
    {"verbrauch": verbrauch,
     "massnahmen": [{"name": "Druckluft-Leckagen beheben", "prozent": 15, "medium": "Druckluft"},
                    {"name": "Grundlast Wochenende abschalten", "prozent": 8, "medium": "Strom"},
                    {"name": "Wärmerückgewinnung Härterei", "prozent": 12, "medium": "Erdgas"},
                    {"name": "Kühlwasser im Kreislauf", "prozent": 20, "medium": "Wasser"}]},
    [script("Energie-Kennzahlen", """
import datetime
rows = app.table("verbrauch").all(limit=10000)
strom_we = [r["menge"] for r in rows if r["medium"] == "Strom" and r["datum"] and datetime.date.fromisoformat(r["datum"]).weekday() >= 5]
strom_wt = [r["menge"] for r in rows if r["medium"] == "Strom" and r["datum"] and datetime.date.fromisoformat(r["datum"]).weekday() < 5]
if strom_we and strom_wt:
    ui.set("k_wochenende", value=round(100 * (sum(strom_we) / len(strom_we)) / (sum(strom_wt) / len(strom_wt))), unit="% der Werktagslast")
co2 = sum((r["menge"] or 0) * (0.38 if r["medium"] == "Strom" else 0.2) for r in rows if r["medium"] in ("Strom", "Erdgas"))
ui.set("k_co2", value=round(co2 / 1000, 1), unit="t (Zeitraum)")
""", page="uebersicht"),
     script("Einspar-Simulation", """
rows = app.table("verbrauch").all(limit=10000)
tage = len({r["datum"] for r in rows}) or 1
kosten = {}
for r in rows:
    kosten[r["medium"]] = kosten.get(r["medium"], 0) + (r["kosten"] or 0)
zeilen, summe = [], 0
for m in app.table("massnahmen").all():
    jahr = kosten.get(m["medium"], 0) / tage * 365 * (m["prozent"] or 0) / 100
    summe += jahr
    zeilen.append({"Maßnahme": m["name"], "Medium": m["medium"], "Einsparung": f"{m['prozent']} %", "€ / Jahr": f"{jahr:,.0f}".replace(",", ".")})
zeilen.append({"Maßnahme": "Summe", "Medium": "", "Einsparung": "", "€ / Jahr": f"{summe:,.0f}".replace(",", ".")})
ui.set("ergebnis", rows=zeilen)
""", page="einsparung")],
    [gap("kennzahl_berechnet", "Grundlast Wochenende und CO₂ per Skript (Wochentag-Bedingung, Umrechnungsfaktor)."),
     gap("diagramm_summe", "Gestapelte Kosten je Halle nur per Spec-Chart.")])

# ---------------------------------------------------------------- 18 Prüfmittelverwaltung (Prüfmittelbeauftragter, mittel)
pm = [{"inv": f"PM-{1000 + i}", "bezeichnung": R.choice(["Bügelmessschraube 0–25", "Grenzlehrdorn Ø24 h7", "Drehmomentschlüssel 5–25 Nm",
                                                         "Härteprüfer HRC", "Rauheitsmessgerät", "Koordinatenmessgerät", "Messuhr 0,01"]),
       "standort": R.choice(BEREICHE), "letzte": days(-400, -1), "intervall": R.choice([6, 12, 12, 24]),
       "status": R.choices(["Freigegeben", "Gesperrt", "In Kalibrierung"], [10, 1, 1])[0]} for i in range(40)]
app("gmd-pruefmittel", "Prüfmittelverwaltung", "🔬", "Prüfmittelbeauftragter / Qualität", "mittel",
    "Prüfmittel mit Kalibrierintervall, Fälligkeiten, Sperren und Ausleihe",
    [t("Prüfmittel", "pruefmittel",
       f("Inventarnummer", "inv", required=True), f("Bezeichnung", "bezeichnung"), f("Standort", "standort", "choice", BEREICHE),
       f("Letzte Kalibrierung", "letzte", "date"), f("Intervall (Monate)", "intervall", "number"),
       f("Nächste Kalibrierung", "naechste", "date", formula="add_months(letzte, intervall)", formular=False),
       f("Status", "status", "choice", ["Freigegeben", "Gesperrt", "In Kalibrierung"])),
     t("Ausleihen", "ausleihen",
       f("Prüfmittel", "pruefmittel", "reference", ref="pruefmittel", required=True), f("Person", "person"),
       f("Von", "von", "date"), f("Zurück", "zurueck", "bool"))],
    [page("Fällig", "faellig",
          b("heading", text="Kalibrierung", level="1"),
          b("stat", width=4, label="Überfällig (müsste gesperrt sein)", entity="pruefmittel",
            where="Nächste Kalibrierung < heute\nStatus = Freigegeben", alarm_at="1"),
          b("stat", width=4, label="Fällig in 30 Tagen", entity="pruefmittel",
            where="Nächste Kalibrierung >= heute\nNächste Kalibrierung <= heute+30", warn_at="5"),
          b("stat", width=4, label="Ausgeliehen", entity="ausleihen", where="Zurück = nein"),
          b("table", title="Überfällig oder in 30 Tagen fällig", entity="pruefmittel", where="Nächste Kalibrierung <= heute+30"),
          b("calendar", entity="pruefmittel", date_field="naechste", label_field="inv", color_field="status")),
     page("Bestand", "bestand",
          b("search", entity="pruefmittel", field="inv", target_page="pruefmittel"),
          b("filter", entity="pruefmittel", field="standort", field2="status"),
          b("table", entity="pruefmittel", searchable=True)),
     page("Prüfmittel", "pruefmittel",
          b("detail", entity="pruefmittel"),
          b("related_list", title="Ausleihen", entity="ausleihen", ref_field="pruefmittel"), nav=False)],
    {"pruefmittel": pm,
     "ausleihen": [{"pruefmittel": f"#{R.randint(1, 40)}", "person": person(), "von": days(-10, 0), "zurueck": R.random() < 0.5} for _ in range(15)]},
    [],
    [gap("datumsformel", "„Nächste = Letzte + Intervall (Monate)“ per Skript nach dem Speichern.",
         jetzt="Formel „add_months(letzte, intervall)“, kein Skript mehr (der 31. wird zum Monatsletzten)."),
     gap("kennzahl_bedingung", "3 Kennzahlen per Skript.", jetzt="3 Kennzahlen mit Bedingung und Ampel."),
     gap("liste_bedingung", "Fällige Prüfmittel als Ausgabe-Baustein.", jetzt="Liste mit Bedingung „Nächste Kalibrierung <= heute+30“.")])

# ---------------------------------------------------------------- 19 Layered Process Audit (Meister bis Werksleiter, mittel)
EBENEN = ["Meister (täglich)", "Abteilungsleiter (wöchentlich)", "Werksleiter (monatlich)"]
lpa = []
for _n in range(70):
    nok = R.choices([0, 1, 2, 3], [6, 3, 1, 0.5])[0]
    lpa.append({"datum": days(-60, 0), "ebene": R.choices(EBENEN, [6, 2, 1])[0], "linie": R.choice(LINIEN), "auditor": person(),
                "ok": 10 - nok, "nok": nok})
app("gmd-lpa", "Layered Process Audit", "🧅", "Meister · Abteilungsleiter · Werksleiter", "mittel",
    "Prozessaudits auf drei Ebenen, Erfüllungsquote, Abweichungen mit Maßnahmen",
    [t("Audits", "audits",
       f("Datum", "datum", "date", required=True), f("Ebene", "ebene", "choice", EBENEN, required=True),
       f("Linie", "linie", "choice", LINIEN), f("Auditor/in", "auditor"),
       f("Fragen i. O.", "ok", "number"), f("Fragen n. i. O.", "nok", "number"),
       f("Erfüllung (%)", "quote", "decimal", formula="round(ok / (ok + nok) * 100, 1)", formular=False)),
     t("Abweichungen", "abweichungen",
       f("Audit", "audit", "reference", ref="audits"), f("Abweichung", "text", required=True),
       f("Maßnahme", "massnahme"), f("Erledigt", "erledigt", "bool"))],
    [page("Durchführen", "durchfuehren",
          b("heading", text="LPA durchführen", subtitle="10 Fragen · Abweichungen sofort mit Maßnahme anlegen", level="1"),
          b("form", width=6, entity="audits", submit_label="Audit speichern"),
          b("form", width=6, entity="abweichungen", submit_label="Abweichung anlegen")),
     page("Auswertung", "auswertung",
          b("filter", entity="audits", field="ebene", field2="linie", field3="datum"),
          b("stat", width=4, label="Ø Erfüllung", entity="audits", aggregate="avg", field="quote", unit="%"),
          b("stat", width=4, label="Audits", entity="audits"),
          b("output", width=4, name="plan", label="Soll/Ist Audits diesen Monat"),
          b("pivot", title="Erfüllung Linie × Ebene", entity="audits", row_field="linie", col_field="ebene", agg="avg", value_field="quote"),
          b("line", label="Ø Erfüllung je Woche", entity="audits", date_field="datum", aggregate="avg", field="quote",
            period="week", count=9, threshold="90"),
          b("checklist", title="Abweichungen", entity="abweichungen", field="erledigt", label_field="text", detail="massnahme"))],
    {"audits": lpa,
     "abweichungen": [{"audit": f"#{R.randint(1, 70)}", "text": t_, "massnahme": m, "erledigt": R.random() < 0.5} for t_, m in [
         ("Arbeitsanweisung nicht aktuell", "Neue Version aushängen"), ("Werker kennt Reaktionsplan nicht", "Unterweisung"),
         ("Prüfmittel ohne Plakette", "Sperren und kalibrieren"), ("Ausschussbehälter nicht gekennzeichnet", "Rote Kiste beschaffen"),
         ("Erstteilfreigabe fehlt", "Freigabe nachholen"), ("Drehmoment-Protokoll lückenhaft", "Schrauber-Datenexport prüfen")]]},
    [script("Plan-Erfüllung", """
import datetime
heute = datetime.date.today()
monat = heute.isoformat()[:7]
rows = [r for r in app.table("audits").all() if (r["datum"] or "").startswith(monat)]
soll = {"Meister (täglich)": 22 * 6, "Abteilungsleiter (wöchentlich)": 4 * 6, "Werksleiter (monatlich)": 1}
anteil = heute.day / 30
ui.set("plan", rows=[{"Ebene": e, "Ist": len([r for r in rows if r["ebene"] == e]), "Soll bis heute": round(s * anteil)}
                     for e, s in soll.items()])
""", page="auswertung")],
    [gap("kennzahl_bedingung", "Soll/Ist je Ebene im laufenden Monat per Skript."),
     gap("checkliste_im_formular", "Die 10 Auditfragen als Checkliste im Formular fehlen – nur Zähler i. O./n. i. O.")])

# ---------------------------------------------------------------- 20 Shopfloor-Management (Werksleiter, extrem komplex)
SFM_BEREICHE = ["Zerspanung", "Montage LG", "Montage EPS", "Prüffeld", "Logistik"]
kennz = []
for d in range(-29, 1):
    for ber in SFM_BEREICHE:
        kennz.append({"datum": f"@{d:+d}", "bereich": ber, "s": R.choices([0, 1, 2], [20, 2, 0.3])[0],
                      "q": R.randint(20, 140) + (60 if ber == "Montage EPS" and d > -7 else 0),
                      "d": round(R.uniform(93, 100), 1), "c": round(R.uniform(80, 104), 1), "p": round(R.uniform(86, 99), 1)})
themen = []
for _n in range(36):
    stufe = R.choices(["1 Linie", "2 Meister", "3 Abteilung", "4 Werksleitung"], [5, 4, 2, 1])[0]
    themen.append({"thema": R.choice(["Ausschuss Dichtheit EPS steigt", "Personalmangel Spätschicht", "Leergut fehlt Linie 2",
                                      "Prüfstand 2 instabil", "Liefertreue OEM Süd < 95 %", "Ergonomie Station 40", "Kran Halle 1 defekt",
                                      "Lieferant Gehäuse in Verzug", "Werkzeugstandzeit Räumnadel sinkt"]),
                   "bereich": R.choice(SFM_BEREICHE), "kategorie": R.choice(["S Sicherheit", "Q Qualität", "D Lieferung", "C Kosten", "P Personal"]),
                   "stufe": stufe, "verantwortlich": person(), "faellig": days(-12, 14),
                   "status": R.choice(["Offen", "In Arbeit", "In Arbeit", "Erledigt"]), "eskaliert_am": ""})
SFM_TAFEL = """
import datetime
heute = datetime.date.today()
bereich = params.get("kennzahlen.bereich") or ""
rows = app.table("kennzahlen").all(limit=5000)
if bereich:
    rows = [r for r in rows if r["bereich"] == bereich]
tage = sorted({r["datum"] for r in rows if r["datum"]})
letzter = tage[-1] if tage else None
akt = [r for r in rows if r["datum"] == letzter]
def avg(rs, k):
    w = [r[k] for r in rs if r[k] is not None]
    return round(sum(w) / len(w), 1) if w else 0
s = sum(r["s"] or 0 for r in akt)
q = avg(akt, "q"); d = avg(akt, "d"); c = avg(akt, "c"); p = avg(akt, "p")
ziele = {"s": 0, "q": 80, "d": 97, "c": 95, "p": 92}
ui.set("ampel_s", tone="success" if s == 0 else "danger", title=f"S · Sicherheit: {s} Ereignis(se)", text=f"Stand {letzter}")
ui.set("ampel_q", tone="success" if q <= ziele["q"] else ("warning" if q <= ziele["q"] * 1.25 else "danger"), title=f"Q · Qualität: {q} ppm", text=f"Ziel ≤ {ziele['q']} ppm")
ui.set("ampel_d", tone="success" if d >= ziele["d"] else ("warning" if d >= ziele["d"] - 2 else "danger"), title=f"D · Liefertreue: {d} %", text=f"Ziel ≥ {ziele['d']} %")
ui.set("ampel_c", tone="success" if c >= ziele["c"] else ("warning" if c >= ziele["c"] - 5 else "danger"), title=f"C · Produktivität: {c} %", text=f"Ziel ≥ {ziele['c']} %")
ui.set("ampel_p", tone="success" if p >= ziele["p"] else ("warning" if p >= ziele["p"] - 3 else "danger"), title=f"P · Anwesenheit: {p} %", text=f"Ziel ≥ {ziele['p']} %")
themen = app.table("themen").all()
offen = [t for t in themen if t["status"] != "Erledigt" and (not bereich or t["bereich"] == bereich)]
ueber = [t for t in offen if t["faellig"] and datetime.date.fromisoformat(t["faellig"]) < heute]
ui.set("k_offen", value=len(offen))
ui.set("k_ueber", value=len(ueber))
ui.set("k_wl", value=len([t for t in offen if t["stufe"] == "4 Werksleitung"]))
ui.set("ueberfaellig", rows=[{"Thema": t["thema"], "Bereich": t["bereich"], "Stufe": t["stufe"], "Verantwortlich": t["verantwortlich"],
                              "fällig": t["faellig"]} for t in sorted(ueber, key=lambda t: t["faellig"])])
"""
SFM_ESKALATION = """
import datetime
heute = datetime.date.today()
stufen = ["1 Linie", "2 Meister", "3 Abteilung", "4 Werksleitung"]
n = 0
for t in app.table("themen").all():
    if t["status"] == "Erledigt" or not t["faellig"] or t["stufe"] not in stufen:
        continue
    verzug = (heute - datetime.date.fromisoformat(t["faellig"])).days
    if verzug > 3 and t["stufe"] != stufen[-1] and t.get("eskaliert_am") != heute.isoformat():
        neu = stufen[stufen.index(t["stufe"]) + 1]
        app.table("themen").update(t["id"], stufe=neu, eskaliert_am=heute.isoformat())
        app.table("eskalationen").create(thema=t["id"], von=t["stufe"], nach=neu, datum=heute.isoformat(),
                                         grund=f"{verzug} Tage überfällig")
        n += 1
message(f"{n} Thema/Themen eskaliert" if n else "Nichts zu eskalieren – kein Thema länger als 3 Tage überfällig.")
"""
app("gmd-sfm", "Shopfloor-Management (SQDCP)", "📋", "Werksleiter · Abteilungsleiter · Meister", "extrem komplex",
    "Tägliche Runde: SQDCP-Ampeln je Bereich, Themenspeicher mit automatischer Eskalation über 4 Stufen, Trends",
    [t("Kennzahlen", "kennzahlen",
       f("Datum", "datum", "date", required=True), f("Bereich", "bereich", "choice", SFM_BEREICHE, required=True),
       f("S Sicherheitsereignisse", "s", "number"), f("Q Ausschuss (ppm)", "q", "number"),
       f("D Liefertreue (%)", "d", "decimal"), f("C Produktivität (%)", "c", "decimal"),
       f("P Anwesenheit (%)", "p", "decimal")),
     t("Themen", "themen",
       f("Thema", "thema", required=True), f("Bereich", "bereich", "choice", SFM_BEREICHE),
       f("Kategorie", "kategorie", "choice", ["S Sicherheit", "Q Qualität", "D Lieferung", "C Kosten", "P Personal"]),
       f("Eskalationsstufe", "stufe", "choice", ["1 Linie", "2 Meister", "3 Abteilung", "4 Werksleitung"]),
       f("Verantwortlich", "verantwortlich"), f("Fällig", "faellig", "date"),
       f("Status", "status", "choice", ["Offen", "In Arbeit", "Erledigt"]),
       f("Zuletzt eskaliert", "eskaliert_am", "date", formular=False),
       f("Beschreibung", "beschreibung", "longtext", liste=False)),
     t("Eskalationen", "eskalationen",
       f("Thema", "thema", "reference", ref="themen"), f("Von Stufe", "von"), f("Nach Stufe", "nach"),
       f("Datum", "datum", "date"), f("Grund", "grund"))],
    [page("Tafel", "tafel",
          b("heading", text="Shopfloor-Tafel", subtitle="Tägliche Runde 8:30 · Filter = Bereich", level="1"),
          b("filter", entity="kennzahlen", field="bereich"),
          b("stat", width=4, label="S · Sicherheitsereignisse heute", entity="kennzahlen", aggregate="sum", field="s",
            where="Datum = heute", alarm_at="1", compare_field="datum", compare_days=7),
          b("stat", width=4, label="Q · Ausschuss heute (ppm, Ziel ≤ 80)", entity="kennzahlen", aggregate="avg", field="q",
            where="Datum = heute", warn_at="80", alarm_at="100"),
          b("stat", width=4, label="D · Liefertreue heute (%, Ziel ≥ 97)", entity="kennzahlen", aggregate="avg", field="d",
            where="Datum = heute", direction="lower_worse", warn_at="97", alarm_at="95"),
          b("stat", width=6, label="C · Produktivität heute (%, Ziel ≥ 95)", entity="kennzahlen", aggregate="avg", field="c",
            where="Datum = heute", direction="lower_worse", warn_at="95", alarm_at="90"),
          b("stat", width=6, label="P · Anwesenheit heute (%, Ziel ≥ 92)", entity="kennzahlen", aggregate="avg", field="p",
            where="Datum = heute", direction="lower_worse", warn_at="92", alarm_at="89"),
          b("stat", width=4, label="Offene Themen", entity="themen", where="Status != Erledigt"),
          b("stat", width=4, label="Überfällig", entity="themen", where="Status != Erledigt\nFällig < heute",
            warn_at="1", alarm_at="10"),
          b("stat", width=4, label="Bei der Werksleitung", entity="themen",
            where="Status != Erledigt\nEskalationsstufe = 4 Werksleitung", warn_at="1", alarm_at="3"),
          b("table", title="Überfällige Themen", entity="themen", where="Status != Erledigt\nFällig < heute"),
          b("button", label="Eskalation jetzt prüfen", target="script", script="eskalation", style="secondary")),
     page("Themenspeicher", "themen",
          b("filter", entity="themen", field="bereich", field2="kategorie", field3="stufe"),
          b("kanban", title="Nach Eskalationsstufe", entity="themen", field="stufe", detail="verantwortlich", limit=6),
          b("kanban", title="Nach Status", entity="themen", field="status", detail="bereich", limit=6),
          b("table", entity="themen", searchable=True),
          b("form", entity="themen", submit_label="Thema aufnehmen")),
     page("Thema", "thema",
          b("stepper", title="Status", entity="themen", field="status"),
          b("stepper", title="Eskalationsstufe", entity="themen", field="stufe"),
          b("detail", width=6, entity="themen"),
          b("related_list", width=6, title="Eskalationsverlauf", entity="eskalationen", ref_field="thema", show_add=False), nav=False),
     page("Trends", "trends",
          b("filter", entity="kennzahlen", field="bereich", field2="datum"),
          b("line", width=6, label="Q · Ausschuss (ppm)", entity="kennzahlen", date_field="datum", aggregate="avg", field="q",
            period="day", count=30, threshold="80"),
          b("line", width=6, label="D · Liefertreue (%)", entity="kennzahlen", date_field="datum", aggregate="avg", field="d",
            period="day", count=30, threshold="97"),
          b("line", width=6, label="C · Produktivität (%)", entity="kennzahlen", date_field="datum", aggregate="avg", field="c",
            period="day", count=30, threshold="95"),
          b("line", width=6, label="P · Anwesenheit (%)", entity="kennzahlen", date_field="datum", aggregate="avg", field="p",
            period="day", count=30, threshold="92"),
          b("heatmap", title="Ø Ausschuss Bereich × Tag", entity="kennzahlen", mode="crosstab", row_field="bereich",
            col_field="datum", value_field="q", agg="avg")),
     page("Kennzahlen melden", "melden",
          b("form", width=6, entity="kennzahlen", submit_label="Tageswerte speichern"),
          b("csv_import", width=6, entity="kennzahlen"),
          b("table", entity="kennzahlen", page_size=15)),
     page("Eskalationen", "eskalationen",
          b("table", entity="eskalationen", title="Protokoll"),
          b("chart", width=6, label="Eskalationen nach Zielstufe", entity="eskalationen", field="nach"))],
    {"kennzahlen": kennz, "themen": themen, "eskalationen": []},
    [script("Eskalation", SFM_ESKALATION, trigger="button"),
     script("Eskalation stündlich", SFM_ESKALATION, trigger="schedule", interval=60)],
    [gap("ampel", "5 SQDCP-Ampeln mit Zielwert je Kennzahl als Hinweis-Bausteine, Farbe per Skript.",
         jetzt="5 Kennzahlen mit „Datum = heute“ und Ampel-Schwellen; die Filterleiste „Bereich“ wirkt auf sie."),
     gap("kennzahl_bedingung", "3 Kennzahlen (offen, überfällig, Werksleitung) per Skript.",
         jetzt="Kennzahlen mit Bedingung und Ampel – das ganze Tafel-Skript ist weg."),
     gap("liste_bedingung", "Überfällige Themen als Ausgabe-Baustein – kein Klick ins Thema.",
         jetzt="Liste mit Bedingung, mit Bearbeiten."),
     gap("buchstabentafel", "Die klassische SQDCP-Buchstabentafel (S/Q/D/C/P als Monatsraster) fehlt.")])


BAUSTEIN_NAMEN = {
    "kennzahl_bedingung": "Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)",
    "ampel": "Ampel-Farbe nach Schwellwerten",
    "liste_bedingung": "Liste mit fester Bedingung (z. B. nur überfällige)",
    "diagramm_summe": "Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto",
    "datumsformel": "Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)",
    "kennzahl_berechnet": "Statistische Kennzahl (Cp/Cpk, Anteil am Wochenende)",
    "fortschritt_zeitraum": "Fortschritt nur für einen Zeitraum (Monat, Quartal)",
    "kennzahl_vergleich": "Kennzahl mit Vergleich zum Vorzeitraum (Trendpfeil)",
    "netzdiagramm": "Netz-/Radardiagramm",
    "diagramm_mehrere_felder": "Diagramm über mehrere Zahlenfelder nebeneinander",
    "regelkarte": "SPC-Regelkarte mit oberer und unterer Eingriffsgrenze",
    "matrix_symbole": "Qualifikationsmatrix mit ILUO-Symbolen",
    "sicherheitskreuz": "Sicherheitskreuz (Tag je Feld, Farbe nach Ereignis)",
    "ziel_aus_tabelle": "Fortschritt mit Zielwert aus einer Tabelle",
    "meilensteine": "Meilensteine im Zeitstrahl",
    "checkliste_im_formular": "Checkliste als Teil eines Formulars (Auditfragen)",
    "buchstabentafel": "SQDCP-Buchstabentafel als Monatsraster",
}


def bericht():
    """Schreibt README.md: welche Apps es gibt und welche Bausteine gefehlt haben."""
    zeilen = ["# Werks-Apps (Produkttest)", "",
              "Erfundene, aber realistische Apps für ein Lenkungswerk – vom Werker bis zur Werksleitung. Sie",
              "dienen als Produkttest für den Baukasten: Was sich nur mit Umwegen (Skript, Hinweis-Baustein als",
              "Ampel, Ausgabe-Tabelle) bauen ließ, steht unter „Nachbauten“. Die häufigsten fehlenden Bausteine",
              "sind inzwischen eingebaut; die Apps nutzen sie.", "",
              "Diese Datei wird von `erzeugen.py` geschrieben – nicht von Hand ändern.", "",
              "## Laden", "", "```", "python beispiele/werk/erzeugen.py          # JSON-Dateien neu erzeugen (optional)",
              "python manage.py beispiel_werk --neu       # alle Apps mit Beispieldaten anlegen bzw. ersetzen",
              "python manage.py beispiel_werk --nur gmd-oee,gmd-sfm", "```", "",
              "## Fertige Datenbank", "",
              "`beispiele/werk/datenbank/werk.sqlite3` (nur lokal, steht in `.gitignore`) enthält alle 20 Apps mit",
              "Beispieldaten und einen Verwalter `pruefer` ohne Passwort. Ansehen in PowerShell:", "",
              "```powershell", "$env:DEBUG = \"1\"",
              "$env:DATABASE_URL = \"sqlite:///$PWD/beispiele/werk/datenbank/werk.sqlite3\"",
              "python manage.py changepassword pruefer     # einmal ein Passwort setzen",
              "python manage.py runserver", "```", "",
              "Datumswerte der Beispieldaten sind relativ zum Tag des Ladens; mit `beispiel_werk --neu` sind sie",
              "wieder aktuell.", "",
              "Jede `gmd-*.json` ist eine App-Definition im Format des KI-Designers (MCP-Server `/mcp/designer/`)",
              "plus Beispieldaten. Im Designer lässt sie sich auch über „App importieren“ einlesen (ohne Daten).", "",
              "## Apps", "", "| App | Rolle | Komplexität | Seiten | Tabellen | Skripte | Nachbauten (gelöst) |",
              "|---|---|---|---|---|---|---|"]
    for a in sorted(APPS, key=lambda a: ["einfach", "mittel", "komplex", "extrem komplex"].index(a["komplexitaet"])):
        geloest = sum(1 for g in a["nachbauten"] if g.get("geloest"))
        zeilen.append(f"| {a['icon']} **{a['name']}** (`{a['slug']}`) – {a['description']} | {a['rolle']} | "
                      f"{a['komplexitaet']} | {len(a['pages'])} | {len(a['entities'])} | {len(a['scripts'])} | "
                      f"{len(a['nachbauten'])} ({geloest}) |")
    tally = {}
    for a in APPS:
        for g in a["nachbauten"]:
            tally.setdefault(g["baustein"], []).append((a, g))
    zeilen += ["", "## Fehlende Bausteine nach Häufigkeit", "",
               "| Baustein | Apps | gelöst | Wo |", "|---|---|---|---|"]
    for key, items in sorted(tally.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        geloest = sum(1 for _a, g in items if g.get("geloest"))
        wo = ", ".join(f"`{a['slug']}`" for a, _g in items)
        zeilen.append(f"| {BAUSTEIN_NAMEN.get(key, key)} | {len(items)} | {geloest} von {len(items)} | {wo} |")
    zeilen += ["", "## Nachbauten im Einzelnen", ""]
    for a in APPS:
        if not a["nachbauten"]:
            continue
        zeilen.append(f"### {a['icon']} {a['name']}")
        zeilen.append("")
        for g in a["nachbauten"]:
            mark = "✅" if g.get("geloest") else "⏳"
            text = f"- {mark} **{BAUSTEIN_NAMEN.get(g['baustein'], g['baustein'])}** – vorher: {g['ersatz']}"
            if g.get("jetzt"):
                text += f" **Jetzt:** {g['jetzt']}"
            zeilen.append(text)
        zeilen.append("")
    (OUT / "README.md").write_text("\n".join(zeilen).rstrip() + "\n", encoding="utf-8", newline="\n")


def main():
    for f_ in OUT.glob("gmd-*.json"):
        f_.unlink()
    for a in APPS:
        path = OUT / f"{a['slug']}.json"
        path.write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    bericht()
    tally = {}
    for a in APPS:
        for g in a["nachbauten"]:
            tally.setdefault(g["baustein"], []).append(a["slug"] + ("+" if g.get("geloest") else ""))
    print(f"{len(APPS)} Apps geschrieben, README.md aktualisiert.")
    for key, apps in sorted(tally.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(apps):3d}  {key:28s} {', '.join(apps)}")


if __name__ == "__main__":
    main()
