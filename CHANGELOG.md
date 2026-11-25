# Änderungen

Alle nennenswerten Änderungen am Baukasten. Versionen nach [Semantic Versioning](https://semver.org/lang/de/):
**Major** bei Änderungen, die Apps, API oder Betrieb brechen; **Minor** bei neuen Funktionen;
**Patch** bei Fehlerbehebungen. Die laufende Version steht in `config/settings.py`
(`BAUKASTEN_VERSION`) und unter `/metrics` (`baukasten_info`).

Neue Einträge oben unter „Unveröffentlicht“ sammeln und beim Release zur Version machen
(Ablauf: docs/BETRIEB.md, „Neue Version einspielen“).

## Unveröffentlicht

### Neu
- **Berichte aus n8n, Teams und Copilot:** Eingang `POST /api/v1/<app>/<tabelle>/eingang/` nimmt
  dieselbe Nachricht an, die sonst an Teams geht (HTML, Text/Markdown, Teams-Webhook-JSON,
  Adaptive Card, MessageCard, Graph-Nachricht mit Bildern), und legt sie als Eintrag ab.
- Neuer Feldtyp **Formatierter Text (HTML)**: wird beim Speichern bereinigt, Markdown wird
  umgewandelt, eingebettete Bilder (PNG, JPEG, GIF, WebP) speichert der Baukasten in der Datenbank
  und liefert sie nur an Berechtigte aus. Detailansicht zeigt ihn formatiert, Listen als Text.
- Neuer Baustein **Berichte-Feed**: Zeitleiste der Berichte, neueste zuerst, mit Schnellfilter
  nach Quelle (z. B. Agent). Beispiel-App: `python manage.py beispiel_berichte`.
- OpenAPI und MCP-Server beschreiben das neue Feld; der Eingang steht in der OpenAPI-Datei
  (für Copilot-Connectoren und API-Plugins).
- **Führung pro Person:** Ob jemand eine Führung gesehen hat, merkt sich der Baukasten jetzt auf
  dem Server (neue Tabelle, Migration `0022`). Die Führung startet daher auf anderen Geräten und in
  anderen Browsern nicht erneut von selbst. Ein bisher nur im Browser gemerkter Wert wird beim
  nächsten Besuch einmalig übernommen. Gäste ohne Konto merken es sich weiter im Browser, und das
  Fragezeichen startet die Führung wie bisher erneut.

### Behoben
- Schieberegler (u. a. What-If-Simulator im „Qualitäts- & Modell-Cockpit“): Ergebnisse
  aktualisierten sich erst nach dem Neuladen der Seite. Ursache: Der Regler speicherte nur beim
  Loslassen (`change`) und lud danach nur sich selbst neu. Die Prognose kommt aber aus einem
  Seitenskript, das nur beim Aufbau der Seite lief. Jetzt speichert der Regler schon beim Ziehen,
  kurz verzögert (`input`, Debounce), und lädt danach die übrigen Bausteine der Seite neu, also
  Skript-Ausgaben und Diagramme. Bausteine mit Eingabefeldern lässt er aus. Die Beispiel-App
  zeigt das aktuelle Szenario zusätzlich als Diagramm.
- Beispiel-App „Qualitäts- & Modell-Cockpit“: Die Filterleiste zeigte nur den Hinweis
  „Wähle mindestens ein Feld …“, weil `beispiel_datascience` die Felder falsch übergab.
- Sicherheit: Der CSV-Export gespeicherter Abfragen (`/a/<app>/q/<abfrage>/export.csv`) war ohne
  Anmeldung erreichbar; er verlangt jetzt eine Anmeldung und nimmt nur Parameter aus dem SQL an.
- Abfrage-Export schrieb in jede Zeile die Spaltennamen statt der Werte.
- Data-Science-Bausteine mit Datenbank-Abfrage als Quelle stürzten ab (`KeyError`); sie lesen die
  Zeilen jetzt richtig und laden wie der Abfrage-Baustein nach, statt die Seite aufzuhalten.
  Startseiten-Widgets fragen bei „wird geladen“ selbst nach.
- Formeln mit unendlichem Ergebnis (z. B. sehr großen Werten) brachen das Speichern ab; Formeln
  dürfen jetzt auch weiter hinten stehende Formelfelder nutzen.
- CSV-Import: berechnet Formelfelder und verändert nicht mehr das globale CSV-Format des Prozesses.
- Unterliste: zeigte bei Tabellen mit mehr als 500 Einträgen nicht alle Untereinträge.
- Alarme: derselbe Fehler höchstens einmal je `ALERT_REPEAT_MINUTES` (Standard 60).
- Klick-Filter in Diagramm und Kreisdiagramm filterten nach dem angezeigten Text statt nach dem
  gespeicherten Wert: „Ja“ zeigte die Nein-Einträge, Verweise, Kommazahlen und übersetzte
  Auswahlwerte filterten gar nicht.
- Abfragen mit Parametern und `%` in Zeichenketten (`LIKE 'A%'`) scheiterten auf PostgreSQL und MySQL.
- Sicherheit: Die Nur-Lese-Prüfung von Abfragen ließ sich mit Backslash-maskierten Anführungszeichen
  (`'a\''`, MySQL bzw. PostgreSQL `E'…'`) umgehen.
- Formelfelder behielten den alten Wert, wenn ein Eingangsfeld geleert wurde oder durch 0 geteilt
  wurde; sie stehen nicht mehr als Eingabefeld im Formular. Der Designer prüft Formeln beim Speichern
  (unbekannte Felder, nicht erlaubte Zeichen, nur für Zahlenfelder).
- Spec-Chart: die Vega-Lite-Berechnungen `mean`, `average`, `median`, `min` und `max` wurden still
  als Summe gerechnet; unbekannte Berechnungen melden jetzt einen Fehler.
- Data-Science-Bausteine fassten den Wert 0 mit leeren Werten zu „Ohne“ bzw. „–“ zusammen.
- CSV-Export: negative Zahlen bekamen ein Apostroph vorangestellt.
- Im Designer neu angelegte Tabellen hatten „Anlegen/Bearbeiten/Löschen erlaubt“ ausgeschaltet,
  Nutzer konnten dort also nichts erfassen.
- Kommazahlen wurden auf zwei Stellen abgeschnitten statt gerundet (2,999 → 2,99; jetzt 3,00).
- Spec-Chart zeigt Werte wie in Listen („Ja/Nein“ statt „True/False“, Namen statt Nummern).
- CSV-Import bietet Formelfelder nicht mehr als Ziel an (ihr Wert wird ohnehin berechnet).
- Konsole: abgebrochene Seitenübergänge erzeugten „Uncaught (in promise)“-Fehler.

### Neu
- **Data-Science-Visualisierungen (Stufe 1 & 2) & Tableau-Bidirektionalität:**
  - Neue Bausteine unter „Auswertung“: **Streudiagramm (`scatter`)** (X/Y-Zahlenfelder, Bubble-Größe,
    Farbgruppen, lineare Regression mit Trendlinie, Pearson-$r$ und $R^2$), **Boxplot & Verteilung (`boxplot`)**
    (Quantile $Q_1$/Median/$Q_3$, Mittelwert, Whisker und $1{,}5\times\text{IQR}$-Ausreißer, optional gruppiert),
    **Heatmap & Korrelation (`heatmap`)** (Pearson-Korrelationsmatrix über alle Zahlenfelder oder
    farbcodierte Kreuztabelle), **Histogramm & Drift (`histogram`)** (Häufigkeitsverteilung in 3–20 Intervallen
    mit automatischer Berechnung des **Population Stability Index / PSI** zum Erkennen von Data Drift) und
    **Spec-Chart (`spec_chart`)** (deklarative Vega-Lite-JSON-Spezifikation).
  - **Live-Datenquellen in allen Data-Science-Bausteinen:** `scatter`, `boxplot`, `heatmap`, `histogram` und
    `spec_chart` arbeiten wahlweise auf einer Baukasten-Tabelle oder direkt auf einer Live-`DataQuery` (SQL / Databricks).
  - **Berechnete Felder (`Field.formula`):** Zahlenfelder berechnen ihren Wert beim Speichern automatisch per
    sicherem arithmetischem Ausdruck aus anderen Feldern des Datensatzes (z. B. `preis * menge`,
    `round(ausschuss - prognose, 2)`).
  - **CSV-Export für Abfragen & aktive Filter:** Der Baustein „Datenbank-Abfrage“ hat einen „CSV“-Button
    (`/a/<app>/q/<query>/export.csv`); der Tabellen-CSV-Export berücksichtigt aktive Seitenfilter (`?tabelle.feld=wert`).
  - **Liniendiagramm (`line`)** erweitert um optionales **Konfidenzband ($\pm 1\,\sigma$)**,
    **Schwellenwert-Linie** und automatische **Anomalie-Markierung**.
  - **Cross-Filtering per Klick:** Klick auf Balken (`chart`), Segmente (`donut`), Heatmap-Zellen,
    Boxplot-Gruppen oder Scatter-Cluster filtert alle Bausteine derselben Tabelle auf der Seite (`?tabelle.feld=wert`).
  - **Tableau-Ansicht (`tableau`):** Neue Zuordnung `selection_map` („Tableau-Feld = URL-Parameter“),
    die bei Klick im Tableau-Dashboard (`markselectionchanged`) die Baukasten-Seite und Write-Back-Formulare filtert.
  - **Beispiel-App:** `python manage.py beispiel_datascience` legt das „Qualitäts- & Modell-Cockpit“
    (`/a/datascience/`) mit Drift-Analyse, Histogramm/PSI, Formelspalte, What-If-Simulator und Write-Back an.
- **Designer- & Betriebskomfort + Fehler-Alarmierung:**
  - **Versions-Diff im Designer:** Jede gespeicherte `AppVersion` zeigt vor dem Wiederherstellen aufklappbar alle
    Unterschiede zum aktuellen Stand (hinzugefügte/entfernte/geänderte Tabellen, Seiten, Skripte und Abfragen).
  - **App duplizieren (`app_clone`):** Apps und Automatisierungen lassen sich im Designer per Klick samt Tabellen,
    Feldern, Formeln, Seiten, Skripten und Abfragen als neuer Entwurf (`„<Name> (Kopie)“`) klonen.
  - **Überschreib-Schutz für Skripte (`409 Conflict`):** Verhindert im Skript-Editor (Apps & Automatisierungen)
    stilles Überschreiben, wenn zwei Personen dasselbe Skript gleichzeitig bearbeiten.
  - **Fehler-Alarmierung (Microsoft Teams, E-Mail oder API-Call):** Schlägt im Hintergrunddienst eine Automatisierung,
    ein zeitgesteuertes Skript oder ein Datenquellen-Abgleich fehl, sendet der Baukasten auf Wunsch einen Alarm per
    **Microsoft Teams (MessageCard-Webhook)**, **E-Mail** oder **API-Call (HTTP POST mit optionalem Authorization-Header)**
    — einstellbar ohne Neustart unter `/admin/` → Einstellungen oder über `ALERT_CHANNEL`, `ALERT_TARGET` und `ALERT_AUTH_HEADER`.
- **Startseite:** Persönliche Widgets („Meine Widgets“) zum Anpinnen von Kennzahlen, Diagrammen, Hinweisen,
  Abfragen und eigenen Bausteinen mit asynchronem Nachladen (`HomeWidget`); Auswahl über ein
  Widget-Sheet wie unter Android (je App aufklappbar, mit Suche und Live-Vorschau); App-Kacheln zeigen
  Hinweise (`notice`-Bausteine) der Seiten sowie für Designer Fehler-Badges bei fehlgeschlagenen Skripten
  oder Abgleichen; „Neue App bauen“ springt direkt zum Anlege-Formular (`?neu=app#neu-anlegen`).
- **Seiten-Designer:** Drag-and-drop mit Vor-/Nach-Indikatoren je Blockhälfte, Quell-Markierung,
  Auto-Scroll und No-Op-Schutz; vollständige Tastaturbedienung auf Bausteinen (Pfeiltasten zur
  Navigation, `Alt+Pfeil` zum Verschieben, `Entf` zum Entfernen, `Strg+S`/`Cmd+S` zum Speichern,
  `Escape` zum Abwählen) samt Kürzel-Hinweis; Überschreib-Schutz (`Page.version` / HTTP `409 Conflict`
  mit Konflikt-Hinweis); Seiten-Footer im Designer ausgeblendet.
- **Eigene Bausteine (Mensch & KI):** Live-Vorschau beim Tippen, klickbare Platzhalter-Chips,
  Start-Vorlagen (Snippets) und Sanitizer-Hinweise (`sanitize_html_report`); typisierte Einstellungen
  (`Name : typ = Wert` mit `number`, `checkbox`, `textarea`, `select(...)` sowie JSON-Format);
  `@hooks.block` unterstützt `fields` und `hint` sowie `(request, app, props)`; MCP-Designer-Tools
  `list_custom_blocks`, `save_custom_block` und `delete_custom_block` samt `design_system`- und
  HTML-Regel-Referenz in `guide`.
- Englische Oberfläche vollständig: rund 530 fehlende Texte übersetzt (auch aus Änderungsprotokoll,
  Einstellungen, App-Installation, Automatisierungen, Übersetzungsseite), Datumsformate je Sprache.
- `python manage.py uebersetzungen pruefen|ergaenzen|kompilieren` pflegt Übersetzungen ohne GNU
  gettext; ein Test meldet fehlende Übersetzungen.
- Bausteingruppe **Planung**: „Einsatzplanung“ (Einträge per Drag-and-drop Zielen je Tag
  zuordnen, mit Kapazität, Gruppen mit Priorität und Rückfragen bei Überplanung,
  Doppelbelegung oder offenen Plätzen in wichtigeren Gruppen), „Wochenübersicht“ (Belegung
  und Kapazität je Tag) und „Kanban-Board“ (Status per Drag-and-drop, Höchstzahl je Spalte).
  Beispiel-App: `python manage.py beispiel_einsatzplanung`.
- Neue Bausteine: „Filterleiste“ (filtert alle Bausteine derselben Tabelle auf der Seite über
  `?tabelle.feld=wert`), „Kalender“ (Monatsansicht, mehrtägig, Farben, „+“ zum Anlegen),
  „Checkliste“ (Ja/Nein per Häkchen), „Schieberegler“ (Zahlenfelder direkt ändern) und
  „Aufklappbereich“. Das Eingabefeld kann jetzt auch Schieberegler, Datum, Auswahl und Ja/Nein.
- „Neu“-Links belegen Felder aus der Adresse vor (`…/neu/?feld=wert`).
- Dialog `BaukastenDialog` (modal.js) für alle Seiten; Rückfragen wie „Eintrag wirklich
  löschen?“ erscheinen jetzt darin statt im Fenster des Browsers.
- Wiederverwendbares Drag-and-drop `BaukastenDnD` (dnd.js), auch ohne Maus bedienbar.
- Feld-Einstellungen von Bausteinen können sich auf andere Tabellen beziehen (`"of"`),
  auch über ein Verweisfeld; Seiten-Designer und KI-Prüfung verstehen das.
- Änderungsprotokoll: wer hat wann was geändert und auf welchem Weg (Oberfläche, Designer, API,
  MCP, KI-Zugang, Skript, Automatisierung, Abgleich, Verwaltung). Je App im Designer mit Filter,
  Suche und CSV-Export, „Verlauf“ im Formular eines Eintrags, alle Apps unter `/admin/`.
  Massenvorgänge als ein zusammenfassender Eintrag. Aufbewahrung über `AUDIT_RETENTION_DAYS`
  (Standard 365 Tage).
- Heruntergeladene Versionen in eine bestehende App einspielen; ältere Dateien und gespeicherte
  Versionen werden automatisch auf das aktuelle Format gehoben (Format 2), weggefallene
  Bausteine werden genannt, Dateien aus neueren Baukasten-Versionen klar abgelehnt.
- Fachliche Einstellungen unter `/admin/` ohne Neustart (Gäste-Grenze, KI-Grenze,
  Aufbewahrung, Zeitlimits); leer = Wert aus der Umgebung.
- Als App installieren (Progressive Web App): Manifest, App-Symbole, Service Worker nur für
  statische Dateien und eine Offline-Seite; Knopf „Als App installieren“ unten auf jeder Seite.
- Seite „Über den Baukasten“ (`/ueber/`) mit Version und Release Notes, gepflegt unter `/admin/`;
  Hinweis „Was ist neu?“ unten auf jeder Seite.

### Behoben
- Status-Leiste (`stepper`): `field_label` wird auch dann bereitgestellt, wenn noch kein Eintrag über `?id=…` gewählt ist.
- Altlasten-Ordner `_to_delete/` entfernt.

## 1.0.0 – 2026-11-17

Erste Version für den produktiven Einsatz.

### Apps bauen
- Tabellen mit zehn Feldtypen, daraus per Klick fertige Seiten mit Liste, Suche, Anlegen, Bearbeiten
- Seiten-Designer mit 24 Bausteinen (Listen, Formulare, Kennzahlen, Diagramme, Liniendiagramm,
  Tableau-Einbettung, Eingabefelder …), eigene HTML-Bausteine und Vorlagen
- Öffentliche Seiten für Gäste ohne Konto, mit Anfragebegrenzung
- Versionen, Export und Import von Apps; Übersetzungen der App-Inhalte (auch per CSV)
- Mitbearbeiter je App (Personen und Gruppen), Eigentümer/in
- Geführte Einführung „Deine erste App“, Führungen durch die Oberfläche

### Logik und Anbindung
- Skripte in Python (abgeschottet, RestrictedPython) und JavaScript (Sandbox im Browser)
- Automatisierungen: zweite App-Art mit echtem Python im Hintergrunddienst, zeitgesteuert,
  täglich, ständig laufend oder per Webhook/MCP, mit Live-Protokoll und Stoppen
- REST-API je App mit OpenAPI und Swagger, Python-Bibliothek `baukasten-client`
- MCP-Server je App; MCP-Server für den Designer: Apps mit einer KI nach Wahl bauen
- Datenquellen (PostgreSQL, Databricks, SQL Server, MySQL, SQLite) live oder gespiegelt

### Betrieb
- Docker-Image, Kubernetes-Manifeste (Web mit Autoscaling, Worker, Migrations-Job, optional Redis)
- Anmeldung lokal oder über Keycloak (OpenID Connect) mit Gruppen und Designer-Rolle
- Überwachung über `/metrics` (Prometheus), Health-Check `/healthz`
- CI mit Tests gegen SQLite und PostgreSQL, automatische Abhängigkeits-Updates (Dependabot)
- Betriebshandbuch mit Störfällen, Sicherungsskript mit Probe-Wiederherstellung,
  Entscheidungsprotokoll (docs/adr/)
