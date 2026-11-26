# Werks-Apps (Produkttest)

Erfundene, aber realistische Apps für ein Lenkungswerk – vom Werker bis zur Werksleitung. Sie
dienen als Produkttest für den Baukasten: Was sich nur mit Umwegen (Skript, Hinweis-Baustein als
Ampel, Ausgabe-Tabelle) bauen ließ, steht unter „Nachbauten“. Die häufigsten fehlenden Bausteine
sind inzwischen eingebaut; die Apps nutzen sie.

Diese Datei wird von `erzeugen.py` geschrieben – nicht von Hand ändern.

## Laden

```
python beispiele/werk/erzeugen.py          # JSON-Dateien neu erzeugen (optional)
python manage.py beispiel_werk --neu       # alle Apps mit Beispieldaten anlegen bzw. ersetzen
python manage.py beispiel_werk --nur gmd-oee,gmd-sfm
```

## Fertige Datenbank

`beispiele/werk/datenbank/werk.sqlite3` (nur lokal, steht in `.gitignore`) enthält alle 20 Apps mit
Beispieldaten und einen Verwalter `pruefer` ohne Passwort. Ansehen in PowerShell:

```powershell
$env:DEBUG = "1"
$env:DATABASE_URL = "sqlite:///$PWD/beispiele/werk/datenbank/werk.sqlite3"
python manage.py changepassword pruefer     # einmal ein Passwort setzen
python manage.py runserver
```

Datumswerte der Beispieldaten sind relativ zum Tag des Ladens; mit `beispiel_werk --neu` sind sie
wieder aktuell.

Jede `gmd-*.json` ist eine App-Definition im Format des KI-Designers (MCP-Server `/mcp/designer/`)
plus Beispieldaten. Im Designer lässt sie sich auch über „App importieren“ einlesen (ohne Daten).

## Apps

| App | Rolle | Komplexität | Seiten | Tabellen | Skripte | Nachbauten (gelöst) |
|---|---|---|---|---|---|---|
| 🍽️ **Kantine & Schichtessen** (`gmd-kantine`) – Speiseplan der Woche und Essensbestellung für die Spät- und Nachtschicht | Werker | einfach | 2 | 2 | 0 | 1 (1) |
| 📒 **Schichtbuch & Übergabe** (`gmd-schichtbuch`) – Stückzahlen, Ausschuss und Besonderheiten je Schicht und Linie, mit Übergabe-Checkliste | Werker / Schichtführer | einfach | 2 | 2 | 1 | 1 (0) |
| 💡 **Ideenmanagement** (`gmd-ideen`) – Verbesserungsvorschläge einreichen, Status verfolgen, umgesetzte Einsparungen | Alle Mitarbeitenden | einfach | 2 | 1 | 0 | 1 (1) |
| 🚨 **Andon & Störungsmeldung** (`gmd-andon`) – Störungen an der Linie melden, Andon-Tafel mit Linienstatus, Stillstands-Pareto | Werker / Instandhaltung | mittel | 3 | 1 | 1 | 4 (4) |
| 🧹 **5S-Audit** (`gmd-5s`) – 5S-Audits je Bereich erfassen, Entwicklung verfolgen, Maßnahmen abhaken | Meister / Werker | mittel | 3 | 2 | 1 | 3 (0) |
| 🛠️ **TPM-Wartungsplan** (`gmd-tpm`) – Anlagen, Wartungsintervalle, Fälligkeiten und Rückmeldung der Wartung | Instandhaltung | mittel | 4 | 2 | 1 | 3 (3) |
| ⏱️ **Rüstzeit-Analyse (SMED)** (`gmd-smed`) – Rüstvorgänge erfassen, intern/extern trennen, Verzögerungen nach Ursache auswerten | Prozessingenieur | mittel | 2 | 1 | 0 | 2 (2) |
| 🚚 **Materialnachschub (Routenzug)** (`gmd-nachschub`) – Nachschub an die Linie anfordern, Routenzug-Aufträge abarbeiten, Unterdeckungen erkennen | Logistik | mittel | 3 | 2 | 0 | 3 (3) |
| 🎓 **Qualifikationsmatrix** (`gmd-quali`) – Wer kann welche Station? ILUO-Stufen, ablaufende Qualifikationen, Springer-Planung | Meister / Personal | mittel | 2 | 3 | 1 | 2 (1) |
| 🦺 **Arbeitssicherheit & Sicherheitskreuz** (`gmd-sicherheit`) – Beinahe-Unfälle anonym melden, Sicherheitskreuz, Schwerpunkte nach Bereich | Arbeitssicherheit / alle | mittel | 3 | 1 | 1 | 4 (3) |
| 💶 **Kostenstellen-Controlling** (`gmd-controlling`) – Ist-Kosten gegen Budget je Kostenstelle, Kostenarten-Pivot, Hochrechnung | Controller / Kostenstellenverantwortliche | mittel | 3 | 2 | 1 | 2 (0) |
| 🪪 **Fremdfirmen & Besucher** (`gmd-besucher`) – Voranmeldung, Sicherheitsunterweisung, wer ist gerade im Werk (Evakuierungsliste) | Pforte / Ansprechpartner | mittel | 3 | 1 | 0 | 2 (2) |
| 🔬 **Prüfmittelverwaltung** (`gmd-pruefmittel`) – Prüfmittel mit Kalibrierintervall, Fälligkeiten, Sperren und Ausleihe | Prüfmittelbeauftragter / Qualität | mittel | 3 | 2 | 0 | 3 (3) |
| 🧅 **Layered Process Audit** (`gmd-lpa`) – Prozessaudits auf drei Ebenen, Erfüllungsquote, Abweichungen mit Maßnahmen | Meister · Abteilungsleiter · Werksleiter | mittel | 2 | 2 | 1 | 2 (0) |
| 🧾 **8D-Reklamationen** (`gmd-8d`) – Kundenreklamationen nach 8D: Status je Disziplin, Maßnahmen, Kosten, Alter | Qualitätsingenieur | komplex | 4 | 2 | 1 | 3 (2) |
| 📐 **SPC Zahnstangen-Durchmesser** (`gmd-spc`) – Messwerte erfassen, Regelkarte, Verteilung, Prozessfähigkeit Cp/Cpk mit verstellbaren Toleranzen | Qualitätsingenieur | komplex | 3 | 2 | 1 | 3 (1) |
| 🏭 **OEE-Cockpit** (`gmd-oee`) – Verfügbarkeit × Leistung × Qualität je Linie und Schicht, Trends, Ampeln und Verlustanalyse | Werksleiter / Fertigungsleiter | komplex | 3 | 1 | 0 | 3 (3) |
| 🚀 **Projekt Anlauf EPS Gen 5** (`gmd-anlauf`) – Arbeitspakete, Meilensteine, Risiken und offene Punkte bis SOP | Projektingenieur / Projektleiter | komplex | 3 | 3 | 1 | 4 (2) |
| ⚡ **Energiemonitoring** (`gmd-energie`) – Verbrauch je Halle und Medium, Kosten, Grundlast am Wochenende, Einspar-Simulation | Facility Management / Werksleitung | komplex | 3 | 2 | 2 | 2 (0) |
| 📋 **Shopfloor-Management (SQDCP)** (`gmd-sfm`) – Tägliche Runde: SQDCP-Ampeln je Bereich, Themenspeicher mit automatischer Eskalation über 4 Stufen, Trends | Werksleiter · Abteilungsleiter · Meister | extrem komplex | 6 | 3 | 2 | 4 (3) |

## Fehlende Bausteine nach Häufigkeit

| Baustein | Apps | gelöst | Wo |
|---|---|---|---|
| Kennzahl mit fester Bedingung (z. B. nur offene, nur heute) | 13 | 11 von 13 | `gmd-kantine`, `gmd-andon`, `gmd-5s`, `gmd-tpm`, `gmd-8d`, `gmd-nachschub`, `gmd-sicherheit`, `gmd-anlauf`, `gmd-ideen`, `gmd-besucher`, `gmd-pruefmittel`, `gmd-lpa`, `gmd-sfm` |
| Ampel-Farbe nach Schwellwerten | 8 | 4 von 8 | `gmd-schichtbuch`, `gmd-andon`, `gmd-spc`, `gmd-nachschub`, `gmd-controlling`, `gmd-oee`, `gmd-anlauf`, `gmd-sfm` |
| Liste mit fester Bedingung (z. B. nur überfällige) | 7 | 7 von 7 | `gmd-andon`, `gmd-tpm`, `gmd-nachschub`, `gmd-quali`, `gmd-besucher`, `gmd-pruefmittel`, `gmd-sfm` |
| Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen) | 5 | 4 von 5 | `gmd-tpm`, `gmd-8d`, `gmd-sicherheit`, `gmd-anlauf`, `gmd-pruefmittel` |
| Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto | 5 | 4 von 5 | `gmd-andon`, `gmd-8d`, `gmd-smed`, `gmd-oee`, `gmd-energie` |
| Fortschritt nur für einen Zeitraum (Monat, Quartal) | 2 | 2 von 2 | `gmd-smed`, `gmd-sicherheit` |
| Statistische Kennzahl (Cp/Cpk, Anteil am Wochenende) | 2 | 0 von 2 | `gmd-spc`, `gmd-energie` |
| SQDCP-Buchstabentafel als Monatsraster | 1 | 0 von 1 | `gmd-sfm` |
| Checkliste als Teil eines Formulars (Auditfragen) | 1 | 0 von 1 | `gmd-lpa` |
| Diagramm über mehrere Zahlenfelder nebeneinander | 1 | 0 von 1 | `gmd-5s` |
| Kennzahl mit Vergleich zum Vorzeitraum (Trendpfeil) | 1 | 1 von 1 | `gmd-oee` |
| Qualifikationsmatrix mit ILUO-Symbolen | 1 | 0 von 1 | `gmd-quali` |
| Meilensteine im Zeitstrahl | 1 | 0 von 1 | `gmd-anlauf` |
| Netz-/Radardiagramm | 1 | 0 von 1 | `gmd-5s` |
| SPC-Regelkarte mit oberer und unterer Eingriffsgrenze | 1 | 1 von 1 | `gmd-spc` |
| Sicherheitskreuz (Tag je Feld, Farbe nach Ereignis) | 1 | 0 von 1 | `gmd-sicherheit` |
| Fortschritt mit Zielwert aus einer Tabelle | 1 | 0 von 1 | `gmd-controlling` |

## Nachbauten im Einzelnen

### 🍽️ Kantine & Schichtessen

- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: „Bestellungen für heute“: Kennzahl zählt nur gefiltert über die Adresse, darum Seitenskript mit count(datum=heute) und ui.set. **Jetzt:** Kennzahl mit Bedingung „Abholung = heute“, kein Skript mehr.

### 📒 Schichtbuch & Übergabe

- ⏳ **Ampel-Farbe nach Schwellwerten** – vorher: Soll/Ist-Ampel der letzten Schicht: Hinweis-Baustein, dessen Farbe (tone) ein Seitenskript setzt.

### 🚨 Andon & Störungsmeldung

- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: 3 Kennzahlen (offen, Prio hoch, Stillstand heute) per Skript statt Kennzahl-Baustein. **Jetzt:** Kennzahlen mit Bedingung und Ampel-Schwellen.
- ✅ **Ampel-Farbe nach Schwellwerten** – vorher: 6 Linien-Ampeln als Hinweis-Bausteine mit tone aus dem Skript. **Jetzt:** Die 3 Kennzahlen färben sich selbst. Die Linien-Ampeln bleiben Skript: Sie zeigen den Text der Störung.
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Liste nur der offenen Störungen als Ausgabe-Baustein mit rows aus dem Skript – ohne Klick zum Bearbeiten. **Jetzt:** Liste mit Bedingung „Status != Behoben“, mit Bearbeiten.
- ✅ **Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto** – vorher: Pareto Stillstand nach Ursache: Balkendiagramm kann nur zählen, nicht Minuten summieren und absteigend sortieren – Tabelle aus dem Skript. **Jetzt:** Balkendiagramm mit Summe der Minuten und Pareto-Anteil.

### 🧹 5S-Audit

- ⏳ **Netz-/Radardiagramm** – vorher: Profil der 5 Kriterien: kein Netz-/Radardiagramm, darum Tabelle mit Textbalken aus dem Skript.
- ⏳ **Diagramm über mehrere Zahlenfelder nebeneinander** – vorher: Durchschnitt über 5 Zahlenfelder nebeneinander geht mit keinem Diagramm.
- ⏳ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: „Schwächstes S“ per Skript.

### 🛠️ TPM-Wartungsplan

- ✅ **Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)** – vorher: „Nächste Fälligkeit = Zuletzt + Intervall“: Formeln rechnen nur mit Zahlen, darum Skript nach dem Speichern. **Jetzt:** Formel „letzte + intervall“ im Datumsfeld, kein Skript mehr.
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: 3 Kennzahlen mit Datumsbedingung (überfällig, 7 Tage, A-Anlagen) per Skript. **Jetzt:** 2 von 3 als Kennzahl mit Bedingung. „A-Anlagen“ braucht ein Feld der verknüpften Anlage – bleibt Skript.
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Liste der überfälligen Wartungen als Ausgabe-Baustein; Verweis auf Anlage im Skript aufgelöst. **Jetzt:** Liste mit Bedingung „Nächste Fälligkeit < heute“.

### 🧾 8D-Reklamationen

- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: „Offen“ und „älter als 60 Tage“ per Skript. **Jetzt:** Kennzahlen mit Bedingung, „älter als 60 Tage“ mit Ampel.
- ✅ **Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto** – vorher: Kosten je Kunde absteigend: Balkendiagramm summiert nicht – Tabelle aus dem Skript. **Jetzt:** Balkendiagramm mit Summe der Kosten und Pareto-Anteil.
- ⏳ **Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)** – vorher: „Alter (Tage)“ = heute − Eingang: per Skript beim Speichern (veraltet ohne erneutes Speichern).

### 📐 SPC Zahnstangen-Durchmesser

- ✅ **SPC-Regelkarte mit oberer und unterer Eingriffsgrenze** – vorher: Regelkarte mit OEG und UEG: Liniendiagramm hat nur einen Schwellwert, UEG fehlt. **Jetzt:** Liniendiagramm mit oberer und unterer Grenze; Punkte außerhalb werden rot markiert.
- ⏳ **Statistische Kennzahl (Cp/Cpk, Anteil am Wochenende)** – vorher: Cp/Cpk/außerhalb Toleranz: Statistik per Skript (statistics.stdev).
- ⏳ **Ampel-Farbe nach Schwellwerten** – vorher: Fähigkeits-Ampel als Hinweis mit tone.

### ⏱️ Rüstzeit-Analyse (SMED)

- ✅ **Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto** – vorher: Pareto über Summe der Minuten nur mit Spec-Chart (Vega-Lite-JSON von Hand) – für Fachanwender kaum machbar. **Jetzt:** Balkendiagramm mit Summe und Pareto-Anteil.
- ✅ **Fortschritt nur für einen Zeitraum (Monat, Quartal)** – vorher: „Rüstvorgänge im Monat“: Fortschritt zählt alle Einträge, nicht nur den laufenden Monat. **Jetzt:** Fortschritt mit Bedingung „Datum >= monatsanfang“.

### 🚚 Materialnachschub (Routenzug)

- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Material unter Mindestbestand (Bedingung zwischen zwei Feldern) nur per Skript. **Jetzt:** Liste mit Bedingung „Bestand < Mindestbestand“ (Feld gegen Feld).
- ✅ **Ampel-Farbe nach Schwellwerten** – vorher: Unterdeckung als Hinweis mit tone. **Jetzt:** Kennzahl mit Ampel.
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: „Nicht geliefert“ per Skript. **Jetzt:** Kennzahl mit Bedingung, kein Skript mehr.

### 🎓 Qualifikationsmatrix

- ⏳ **Qualifikationsmatrix mit ILUO-Symbolen** – vorher: ILUO-Matrix: Heatmap zeigt Zahlen statt Symbole (Viertelkreis I/L/U/O).
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: „Läuft in 60 Tagen ab“ und Engpass-Stationen per Skript. **Jetzt:** „Läuft ab“ als Liste mit Bedingung. Engpässe (zählen je Station mit Schwelle) bleiben Skript.

### 🦺 Arbeitssicherheit & Sicherheitskreuz

- ⏳ **Sicherheitskreuz (Tag je Feld, Farbe nach Ereignis)** – vorher: Grünes Kreuz (Tag je Feld, Farbe nach schwerstem Ereignis): Emoji-Tabelle aus dem Skript.
- ✅ **Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)** – vorher: „Tage ohne Unfall“ per Skript. **Jetzt:** Kennzahl „Tage seit dem letzten Datum“ mit Bedingung „Art = Unfall mit Ausfall“ und Ampel.
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: „Meldungen diesen Monat“ per Skript. **Jetzt:** Kennzahl mit „Datum >= monatsanfang“.
- ✅ **Fortschritt nur für einen Zeitraum (Monat, Quartal)** – vorher: Fortschritt „im Quartal“ zählt alle Meldungen. **Jetzt:** Fortschritt mit „Datum >= quartalsanfang“.

### 💶 Kostenstellen-Controlling

- ⏳ **Fortschritt mit Zielwert aus einer Tabelle** – vorher: Fortschritt: Zielwert ist eine feste Zahl, das Budget steht aber in einer Tabelle – nur die Beschriftung lässt sich per Skript ändern, der Zielwert nicht.
- ⏳ **Ampel-Farbe nach Schwellwerten** – vorher: 5 Budget-Ampeln mit Hochrechnung als Hinweis-Bausteine.

### 🏭 OEE-Cockpit

- ✅ **Ampel-Farbe nach Schwellwerten** – vorher: 5 Linien-Ampeln mit Trendpfeil (7 Tage gegen Vorwoche) als Hinweis-Bausteine. **Jetzt:** 5 Kennzahlen mit Bedingung „Linie = …“, Ampel (niedrig ist schlecht) und 7-Tage-Vergleich – kein Skript mehr.
- ✅ **Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto** – vorher: OEE je Linie (Durchschnitt, sortiert) nur als Skript-Tabelle; Stillstand-Summe nur per Spec-Chart. **Jetzt:** Balkendiagramm mit Durchschnitt bzw. Summe.
- ✅ **Kennzahl mit Vergleich zum Vorzeitraum (Trendpfeil)** – vorher: Kennzahl mit Vergleich zum Vorzeitraum (Trendpfeil) fehlt. **Jetzt:** Kennzahl-Einstellung „Vergleich: Zeitraum in Tagen“.

### 🚀 Projekt Anlauf EPS Gen 5

- ✅ **Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)** – vorher: „Tage bis SOP“ per Skript. **Jetzt:** Kennzahl „Tage bis zum nächsten Datum“ mit Bedingung „Arbeitspaket = SOP“.
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: Blockierte Pakete und hohe Risiken per Skript. **Jetzt:** Kennzahlen mit Bedingung und Ampel.
- ⏳ **Ampel-Farbe nach Schwellwerten** – vorher: Projektampel als Hinweis mit tone.
- ⏳ **Meilensteine im Zeitstrahl** – vorher: Meilensteine als Raute im Zeitstrahl fehlen; SOP ist ein 1-Tages-Balken.

### 💡 Ideenmanagement

- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: Summe nur der umgesetzten Ideen per Skript. **Jetzt:** Kennzahl Summe mit Bedingung „Status = Umgesetzt“, kein Skript mehr.

### 🪪 Fremdfirmen & Besucher

- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: 3 Kennzahlen mit Bedingung per Skript. **Jetzt:** 3 Kennzahlen mit Bedingung, kein Skript mehr.
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Evakuierungsliste (nur „Vor Ort“) als Ausgabe-Baustein – druckbar, aber ohne Abmelde-Klick. **Jetzt:** Liste mit Bedingung „Status = Vor Ort“, mit Bearbeiten.

### ⚡ Energiemonitoring

- ⏳ **Statistische Kennzahl (Cp/Cpk, Anteil am Wochenende)** – vorher: Grundlast Wochenende und CO₂ per Skript (Wochentag-Bedingung, Umrechnungsfaktor).
- ⏳ **Balkendiagramm mit Summe/Durchschnitt statt Anzahl, Pareto** – vorher: Gestapelte Kosten je Halle nur per Spec-Chart.

### 🔬 Prüfmittelverwaltung

- ✅ **Rechnen mit Datumsfeldern (Fälligkeit = letzte + Intervall, Alter in Tagen)** – vorher: „Nächste = Letzte + Intervall (Monate)“ per Skript nach dem Speichern. **Jetzt:** Formel „add_months(letzte, intervall)“, kein Skript mehr (der 31. wird zum Monatsletzten).
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: 3 Kennzahlen per Skript. **Jetzt:** 3 Kennzahlen mit Bedingung und Ampel.
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Fällige Prüfmittel als Ausgabe-Baustein. **Jetzt:** Liste mit Bedingung „Nächste Kalibrierung <= heute+30“.

### 🧅 Layered Process Audit

- ⏳ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: Soll/Ist je Ebene im laufenden Monat per Skript.
- ⏳ **Checkliste als Teil eines Formulars (Auditfragen)** – vorher: Die 10 Auditfragen als Checkliste im Formular fehlen – nur Zähler i. O./n. i. O.

### 📋 Shopfloor-Management (SQDCP)

- ✅ **Ampel-Farbe nach Schwellwerten** – vorher: 5 SQDCP-Ampeln mit Zielwert je Kennzahl als Hinweis-Bausteine, Farbe per Skript. **Jetzt:** 5 Kennzahlen mit „Datum = heute“ und Ampel-Schwellen; die Filterleiste „Bereich“ wirkt auf sie.
- ✅ **Kennzahl mit fester Bedingung (z. B. nur offene, nur heute)** – vorher: 3 Kennzahlen (offen, überfällig, Werksleitung) per Skript. **Jetzt:** Kennzahlen mit Bedingung und Ampel – das ganze Tafel-Skript ist weg.
- ✅ **Liste mit fester Bedingung (z. B. nur überfällige)** – vorher: Überfällige Themen als Ausgabe-Baustein – kein Klick ins Thema. **Jetzt:** Liste mit Bedingung, mit Bearbeiten.
- ⏳ **SQDCP-Buchstabentafel als Monatsraster** – vorher: Die klassische SQDCP-Buchstabentafel (S/Q/D/C/P als Monatsraster) fehlt.
