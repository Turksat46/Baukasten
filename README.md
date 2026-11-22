<p align="center">
  <img src="builder/static/builder/logo.svg" alt="Baukasten-Logo" width="96" height="96">
</p>

<h1 align="center">Baukasten</h1>

Ein App-Baukasten auf Basis von Django. Fachabteilungen bauen interne Apps im
Browser zusammen, Entwickler ergänzen bei Bedarf Logik in Python. Läuft auf
Kubernetes.

[![Tests](https://github.com/Turksat46/Baukasten/actions/workflows/tests.yml/badge.svg)](https://github.com/Turksat46/Baukasten/actions/workflows/tests.yml)

**Die vollständige Dokumentation steht in [docs/HANDBUCH.md](docs/HANDBUCH.md)**
(englische Kurzfassung: [docs/HANDBOOK.en.md](docs/HANDBOOK.en.md)).

## Was er kann

- **Daten → fertige App:** Tabellen und Felder festlegen (inklusive **berechneter Formelspalten** wie `preis * menge`), daraus entsteht per
  Klick eine Seite mit Liste, Suche, Anlegen, Bearbeiten und Löschen.
- **Seiten-Designer:** 42 Bausteine per Drag-and-drop, Tastatursteuerung und Überschreib-Schutz (`409 Conflict`), mit Vorschau auf echten
  Daten (Listen, Karten, Formulare, Kennzahlen, Diagramme, Liniendiagramme mit $\pm 1\,\sigma$-Band & Anomalien, **Streudiagramm mit Trendlinie & $R^2$**, **Boxplot & Ausreißer**, **Heatmap & Korrelationsmatrix**, **Histogramm & Data-Drift/PSI**, **Vega-Lite Spec-Chart**, Verlauf, Export,
  Eingabefelder mit Schiebereglern, Filterleiste, Cross-Filtering per Klick, Kalender, Checkliste, Einsatzplanung per
  Drag-and-drop, Wochenübersicht, Kanban …).
- **Startseite mit persönlichen Widgets:** Kennzahlen, Diagramme, Abfragen und eigene Bausteine aus beliebigen Apps auf der eigenen Startseite anpinnen („Meine Widgets“).
- **Öffentliche Seiten:** einzelne Seiten „ohne Anmeldung erreichbar“ machen, etwa
  für Anmeldeformulare oder Einwilligungen von Externen. Gäste dürfen nur
  Formulare und Skript-Buttons dieser Seite benutzen; mit Anfragebegrenzung.
- **Eigene Bausteine:** HTML-Bausteine mit eigenen Einstellungen und
  wiederverwendbare Vorlagen, ohne Programmierung.
- **API:** JSON-Schnittstelle je Tabelle mit Schlüsseln; eigene Endpunkte in Python.
  Dokumentation je App mit Swagger zum Ausprobieren und OpenAPI-Datei.
- **MCP-Server je App** (`/mcp/<app>/`): KI-Agenten wie n8n, Claude oder Cursor
  nutzen die freigeschalteten Tabellen als Werkzeuge. Die Tools entstehen
  automatisch aus den Tabellen; ein Schlüssel ohne Schreibrecht bekommt nur die
  lesenden.
- **Apps mit KI bauen:** Eine KI deiner Wahl (Claude, Cursor, n8n …) legt über
  den MCP-Server `/mcp/designer/` Apps an und ändert sie, mit einem persönlichen
  KI-Zugang aus der Profilseite und genau deinen Rechten. Verständliche
  Prüfmeldungen, Version vor jeder Änderung; veröffentlichen und Skripte
  einschalten bleibt Sache eines Menschen.
- **Änderungsprotokoll:** wer wann was geändert hat, je App und je Eintrag, über alle Wege
  (Oberfläche, API, KI, Skripte, Automatisierungen); mit Suche, CSV-Export und
  Aufbewahrungsfrist.
- **Mitbearbeiter:** Wer eine App anlegt, ist Eigentümer/in und lädt weitere
  Designer oder Gruppen ein. Andere Designer sehen fremde Apps im Designer nicht.
- **Versionen & App-Klonen:** Stand einer App speichern, **Unterschiede zum aktuellen Stand (Versions-Diff)** vor dem Wiederherstellen prüfen, als Datei
  exportieren, importieren oder eine bestehende App per Klick als neuen Entwurf **duplizieren**.
- **Skripte in Python und JavaScript:** Bausteine füllen, rechnen, Einträge
  prüfen, zeitgesteuert im Hintergrund arbeiten (mit Überschreib-Schutz bei gleichzeitiger Bearbeitung). Python läuft abgeschottet auf
  dem Server, JavaScript in einer Sandbox im Browser. Python-Skripte haben
  außerdem `session` (Merkzettel je Besucher, auch ohne Konto) und `token()`
  für geheime Links.
- **Automatisierungen & Fehler-Alarmierung:** Zweite App-Art ohne Seiten, nur Python-Skripte im
  Hintergrund, mit echtem Python und allen Bibliotheken einer gemeinsamen
  Umgebung. Zeitgesteuert, täglich, ständig laufend (mit Neustart) oder per
  Webhook/MCP; nie zwei Läufe eines Skripts gleichzeitig, Zeitlimit bis 4 Stunden,
  Live-Protokoll und Stoppen im Designer, Geheimnisse über `secret("NAME")`. Bei Fehlern in Automatisierungen, Zeitplan-Skripten oder Datenquellen-Abgleichen optionale **Alarmierung über Microsoft Teams (Webhook), E-Mail oder API-Call (HTTP POST)**.
- **Tableau (bidirektional):** Dashboards von Tableau Server oder Tableau Cloud einbetten, mit
  Filtern aus der Seite, Rückfilterung aus Tableau-Auswahlen (`selection_map` → Baukasten-Seite/Write-Back) und optionaler Anmeldung über eine Connected App.
- **Datenbanken und Databricks:** lesende Abfragen live in Tabellen oder direkt in Data-Science-Diagrammen anzeigen (mit
  automatischer Aktualisierung und CSV-Export) oder regelmäßig in eine Tabelle spiegeln.
- **Python-Bibliothek** `baukasten-client` für die API, mit denselben Befehlen
  wie in Skripten (`clients/python/`).
- **Python-Erweiterungen:** Aktionen, Hooks, Bausteine und Endpunkte im Ordner
  `extensions/`.
- **Anmeldung:** lokale Konten oder Keycloak (OpenID Connect) mit Gruppen und
  Designer-Rolle.
- **Zweisprachig:** Deutsch und Englisch, umschaltbar.
- **Übersetzbare Apps:** alle Texte einer App (Namen, Felder, Auswahlwerte,
  Seiten, Bausteine) im Designer übersetzen, auch per CSV für Übersetzer.
  Gespeicherte Daten, API und Skripte bleiben unverändert.
- **Führung für neue Nutzer**, Platz für das Firmenlogo, Design über Variablen.
- **Profilseite** mit eigenen Apps, API-Schlüsseln, Skripten und deren Fehlern.
- **Verwaltung nach Apps:** in `/admin/` alle Daten je App mit echten Spalten;
  Admins erreichen sie direkt über „Admin“ in der Kopfzeile.
- **Standardgruppe „Viewer“** für jede Person (einstellbar über `DEFAULT_USER_GROUPS`).
- **Handbuch in der Oberfläche** unter „Hilfe“ (Quelle: `docs/HANDBUCH.md`).

**Neu im Baukasten?** Im Designer startet „Einführung“ einen Begleiter, mit dem du
in etwa 20 Minuten deine erste App selbst baust.

## In fünf Minuten starten

Voraussetzung: Python 3.10 oder neuer.

```
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-automation.txt

$env:DEBUG=1                      # cmd: set DEBUG=1, Linux/macOS: export DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py demo             # Beispiel-App „Inventar“; mit --neu wird sie ersetzt
python manage.py beispiel_einwilligung   # Beispiel-App „Aufnahme-Einwilligung“
python manage.py beispiel_einsatzplanung # Beispiel-App „Personaleinsatz“ mit Schichtplanung
python manage.py beispiel_datascience    # Beispiel-App „Qualitäts- & Modell-Cockpit“ (Data Science)
python manage.py runserver
```

Danach http://127.0.0.1:8000 öffnen und anmelden. Mit `DEBUG=1` legt `demo`
auch die Seite „Live-Daten“ mit einer Beispiel-Datenquelle und Skripten an.

Für Automatisierungen, zeitgesteuerte Skripte und das Spiegeln von Abfragen in
einem zweiten Terminal: `python manage.py hintergrund --dauerhaft`.

Nach einem Update des Baukastens: `pip install -r requirements.txt -r requirements-automation.txt`
und `python manage.py migrate` erneut ausführen.

**Lokal in Kubernetes** (Docker Desktop mit eingeschaltetem Kubernetes):
`powershell -ExecutionPolicy Bypass -File k8s\lokal\deploy.ps1 -OhneBeispiele`,
danach http://localhost:8080. Ohne `-OhneBeispiele` bricht das Skript am Ende ab,
weil die Inventar-Demo im Cluster nicht schreiben darf; die Einwilligungs-App
legt man danach mit
`kubectl -n baukasten exec deploy/baukasten -- python manage.py beispiel_einwilligung`
an. Einzelheiten im Handbuch unter „Lokal mit Kubernetes“.

## Wo was steht

| Thema | Ort |
|---|---|
| Benutzen, Apps bauen, Bausteine, Versionen | Handbuch Teil 1 und 2 |
| Datenquellen und Skripte anwenden | Handbuch Teil 2 |
| Öffentliche Seiten, Übersetzungen, Mitbearbeiter, Automatisierungen | Handbuch Teil 2 und „Rechte“ |
| Hintergrunddienst, Geheimnisse und Bibliotheken für Automatisierungen | Handbuch „Hintergrundarbeiten“, `requirements-automation.txt` |
| Skript-Referenz, Python-Bibliothek, API, MCP-Server, Aufbau des Codes | Handbuch Teil 3 |
| Kubernetes, Datenquellen einrichten, Keycloak, Sicherheit | Handbuch Teil 4 |
| Firmenlogo einbinden | `builder/static/builder/brand/LIESMICH.txt` |
| Farben und Schrift | `builder/static/builder/theme.css` |
| Beispiele für Erweiterungen | `extensions/beispiel.py` |
| Kubernetes-Manifeste | `k8s/` |
| Aufbau, Abläufe, Diagramme | `docs/TECHNISCHE_DOKUMENTATION.md` |
| Betrieb: Zuständigkeiten, Updates, Sicherung, Störfälle, Alarme | `docs/BETRIEB.md` |
| Warum etwas so gebaut ist | `docs/adr/` |
| Was sich geändert hat | `CHANGELOG.md` |

## Stand

Version 1.0.0 (siehe `CHANGELOG.md`). 282 automatische Tests laufen bei jeder Änderung
in GitHub Actions gegen SQLite und PostgreSQL, dazu Durchläufe im Browser. Docker-Build und die lokalen Manifeste laufen auf Kubernetes in Docker
Desktop mit PostgreSQL 16. Nicht getestet: ein echter Produktions-Cluster (Ingress,
TLS), der vollständige Login gegen einen echten Keycloak und Verbindungen zu
echten Datenbanken außer SQLite und PostgreSQL, auch nicht zu Databricks. Alle
bekannten Grenzen stehen im Handbuch unter „Grenzen des jetzigen Stands“.
