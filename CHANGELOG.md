# Änderungen

Alle nennenswerten Änderungen am Baukasten. Versionen nach [Semantic Versioning](https://semver.org/lang/de/):
**Major** bei Änderungen, die Apps, API oder Betrieb brechen; **Minor** bei neuen Funktionen;
**Patch** bei Fehlerbehebungen. Die laufende Version steht in `config/settings.py`
(`BAUKASTEN_VERSION`) und unter `/metrics` (`baukasten_info`).

Neue Einträge oben unter „Unveröffentlicht“ sammeln und beim Release zur Version machen
(Ablauf: docs/BETRIEB.md, „Neue Version einspielen“).

## Unveröffentlicht

### Neu
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
