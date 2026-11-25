# Baukasten – Technische Dokumentation

> Zielgruppe: Entwickler/innen und Betrieb. Für die Bedienung siehe
> [HANDBUCH.md](HANDBUCH.md). Die Diagramme sind in Mermaid geschrieben und werden
> auf GitHub, GitLab und in den meisten Markdown-Viewern direkt gerendert.
>
> Farben in allen Diagrammen: **türkis** = Web-Pods, **orange** = Hintergrunddienst,
> **blau** = Daten, **grau** = außerhalb des Baukastens.

## Inhalt

1. [Überblick](#1-überblick)
2. [Systemarchitektur](#2-systemarchitektur)
3. [Projektstruktur und Module](#3-projektstruktur-und-module)
4. [Datenmodell](#4-datenmodell)
5. [Anfrageverarbeitung und Routing](#5-anfrageverarbeitung-und-routing)
6. [Berechtigungskonzept](#6-berechtigungskonzept)
7. [Skript-Engine](#7-skript-engine)
8. [Hintergrunddienst (Worker)](#8-hintergrunddienst-worker)
9. [Externe Datenquellen](#9-externe-datenquellen)
10. [API, OpenAPI und MCP](#10-api-openapi-und-mcp)
11. [Versionierung und Übersetzungen](#11-versionierung-und-übersetzungen)
12. [Deployment auf Kubernetes](#12-deployment-auf-kubernetes)
13. [Konfiguration (Umgebungsvariablen)](#13-konfiguration-umgebungsvariablen)
14. [Sicherheit](#14-sicherheit)
15. [Entwicklung und Tests](#15-entwicklung-und-tests)

---

## 1. Überblick

Der Baukasten ist eine **Low-Code-Plattform auf Basis von Django 5.2**. Fachabteilungen
bauen im Browser interne Apps aus Tabellen, Seiten und Bausteinen; Entwickler/innen
ergänzen Logik in Python oder JavaScript. Eine zweite App-Art, die **Automatisierung**,
hat keine Seiten und führt nur Python-Skripte im Hintergrund aus.

| Eigenschaft | Umsetzung |
|---|---|
| Sprache / Framework | Python ≥ 3.10, Django 5.2 |
| Datenbank | SQLite (lokal), PostgreSQL 16 (produktiv) über `DATABASE_URL` |
| Cache | Redis, Datenbank-Tabelle oder Arbeitsspeicher (`CACHE_BACKEND`) |
| Anwendungsserver | gunicorn (`gunicorn.conf.py`), statische Dateien über WhiteNoise |
| Anmeldung | lokale Konten oder Keycloak (OpenID Connect, `mozilla-django-oidc`) |
| Skripte | Python: Kindprozess mit RestrictedPython; JavaScript: iframe-Sandbox; Automatisierungen: echtes Python im Worker |
| Betrieb | ein Docker-Image für Web und Worker, Kubernetes-Manifeste in `k8s/` |
| Sprachen der Oberfläche | Deutsch (Quelle), Englisch (`builder/locale/en`) |

**Kernidee:** Die Datensätze aller App-Tabellen liegen als JSON in einer gemeinsamen
Tabelle (`Record.data`). Änderungen im Designer brauchen daher **keine
Datenbank-Migration**.

---

## 2. Systemarchitektur

```mermaid
flowchart LR
    subgraph Zugriff["Zugriff"]
        direction TB
        U["Nutzer und Designer"] ~~~ G["Gäste"] ~~~ X["Programme · API"] ~~~ K["KI-Agenten · MCP"]
    end

    ING["Ingress<br/>TLS"]

    subgraph Pods["Kubernetes"]
        direction TB
        subgraph Web["baukasten · 2–6 Pods"]
            direction TB
            GU["gunicorn + Django"] -. startet .-> SB["Skripte normaler Apps<br/>RestrictedPython"]
        end
        subgraph Worker["baukasten-worker · 1 Pod"]
            direction TB
            WK["Hintergrunddienst"] -. startet .-> AU["Automatisierungen<br/>echtes Python"]
        end
        Web ~~~ Worker
    end

    subgraph Daten["Daten"]
        direction TB
        PG[("PostgreSQL")] ~~~ RD[("Redis · optional")]
    end

    subgraph Extern["Außerhalb"]
        direction TB
        KC["Keycloak"] ~~~ DS[("Datenquellen<br/>SQL, Databricks")] ~~~ NET["HTTP-Dienste"]
    end

    Zugriff --> ING --> Web
    Pods --> Daten
    Pods --> Extern

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef worker fill:#fff4e6,stroke:#d9480f,color:#5c2400
    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    classDef ext fill:#f1f3f5,stroke:#868e96,color:#212529
    class ING,GU,SB web
    class WK,AU worker
    class PG,RD,DS data
    class U,G,X,K,KC,NET ext
```

**Zwei Prozessarten aus demselben Image:**

- **Web** (`gunicorn config.wsgi`): Laufzeit der Apps, Designer, API, MCP, Verwaltung.
  Skripte normaler Apps laufen hier als kurzlebige Kindprozesse; ihre HTTP-Aufrufe
  macht der Elternprozess, und nur an `HTTP_ALLOWED_HOSTS`.
- **Worker** (`python manage.py hintergrund --dauerhaft`): Automatisierungen,
  zeitgesteuerte Skripte normaler Apps, Abgleich mit Datenquellen. Automatisierungen
  sind echtes Python und erreichen das Netz direkt.

Tableau-Dashboards lädt der Browser selbst (Einbettung); der Server erzeugt nur das
Token einer Connected App.

---

## 3. Projektstruktur und Module

```
baukasten/
├── config/                 Django-Projekt (settings, urls, wsgi)
├── builder/                die eigentliche Anwendung
│   ├── models.py           Datenmodell
│   ├── urls.py             alle Routen
│   ├── views.py            Laufzeit: Seiten, Formulare, Export, Skript-Aufrufe, Startseiten-Widgets
│   ├── designer.py         Designer-Oberfläche (Apps, Klonen, Tabellen, Seiten, Skripte …)
│   ├── blocks.py           Registry und Rendering der Seiten-Bausteine
│   ├── datascience.py      Data-Science-Bausteine (Scatter, Boxplot, Heatmap, Histogramm/PSI, Spec-Chart)
│   ├── alerts.py           Fehler-Alarmierung für Hintergrundarbeiten (Teams, E-Mail, API-Call)
│   ├── forms.py            Formulare, auch dynamisch aus Feld-Definitionen
│   ├── api.py, openapi.py  REST-API und OpenAPI-Spezifikation
│   ├── mcp.py              MCP-Protokoll und Server je App
│   ├── mcp_designer.py     MCP-Server für den Designer (KI baut Apps)
│   ├── ai_designer.py      Prüfen, Schützen und Anwenden von KI-Definitionen
│   ├── datasources.py      externe Datenbanken, Cache, Parallelitätsgrenzen
│   ├── versions.py         Snapshots, Export und Import von Apps
│   ├── audit.py            Änderungsprotokoll (Signale, Kontext je Eingang, Aufbewahrung)
│   ├── platform.py         fachliche Einstellungen: Datenbank vor Umgebung, 30 s Cache
│   ├── about.py            Seite „Über den Baukasten“, Release Notes
│   ├── pwa.py              als App installieren: Manifest, Service Worker (/sw.js), Offline-Seite
│   ├── app_i18n.py         Übersetzung von App-Inhalten
│   ├── auth.py, accounts.py  Keycloak-Backend, Standardgruppen
│   ├── profile.py, help.py Profilseite, Handbuch in der Oberfläche
│   ├── hooks.py            Erweiterungspunkte für extensions/
│   ├── services.py         HTTP-Zugriffe mit Freigabeliste
│   ├── sanitize.py         HTML-Bereinigung eigener Bausteine
│   ├── tableau.py          Tableau-Einbettung (Connected App, JWT)
│   ├── middleware.py       /healthz, Zurücksetzen der App-Übersetzungen
│   ├── context.py          Template-Kontext (u. a. Begleiter der Einführung)
│   ├── tutorial.py, tours.py  Einführung „Deine erste App“ und Führungen
│   ├── admin.py            Verwaltung unter /admin/
│   ├── scripting/
│   │   ├── python.py       Start und Steuerung der Python-Sandbox
│   │   ├── child.py        Kindprozess (importiert kein Django)
│   │   ├── ops.py          Tabellenzugriff für Skripte und API
│   │   ├── triggers.py     Auslöser normaler Apps
│   │   ├── automation.py   ein Lauf einer Automatisierung
│   │   ├── worker.py       Hintergrunddienst („Aufseher“)
│   │   └── schedule.py     Zeitpläne
│   ├── management/commands/  demo, beispiel_einwilligung, hintergrund, lokal_einrichten
│   ├── templates/, static/   Oberfläche (Vanilla JS und CSS)
│   └── tests.py            automatische Tests
├── extensions/             eigene Python-Erweiterungen (beispiel.py)
├── clients/python/         Bibliothek baukasten-client
├── k8s/                    Kubernetes-Manifeste (lokal/ für Docker Desktop)
└── docs/                   Dokumentation
```

### Wie die Module zusammenhängen

Vereinfacht, nur die wichtigen Abhängigkeiten. Alle Module greifen auf `models.py` zu;
gestrichelt heißt „startet als eigenen Prozess“.

```mermaid
flowchart LR
    subgraph E["Eingänge"]
        direction TB
        mcp_designer
        designer
        views
        worker
        api
        mcp
    end

    subgraph F["Seiten und Aufbau"]
        direction TB
        ai_designer
        versions
        blocks
    end

    subgraph S["scripting/"]
        direction TB
        triggers
        automation
        python
    end

    subgraph B["Grundlagen"]
        direction TB
        datasources
        ops
        child[["child.py<br/>Kindprozess"]]
    end

    mcp_designer --> ai_designer --> versions
    designer --> versions
    designer --> blocks
    views --> blocks
    views --> triggers
    worker --> triggers
    worker --> automation
    triggers --> python
    automation --> python
    blocks --> datasources
    python --> datasources
    python --> ops
    api --> ops
    mcp --> ops
    python -.-> child
    automation -.-> child

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef worker fill:#fff4e6,stroke:#d9480f,color:#5c2400
    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    classDef ext fill:#f1f3f5,stroke:#868e96,color:#212529
    class views,designer,api,mcp,mcp_designer web
    class worker,automation worker
    class ops,datasources,child data
```

`automation.py` nutzt den `Handler` aus `python.py`: Beide Skriptarten beantworten die
Anfragen ihres Kindprozesses gleich (Tabellen, Abfragen, Geheimnisse).

---

## 4. Datenmodell

Das Modell ist auf zwei Diagramme verteilt: der Aufbau einer App und alles, was um sie
herum gespeichert wird.

### Aufbau einer App

```mermaid
erDiagram
    APP ||--o{ ENTITY : "Tabellen"
    APP ||--o{ PAGE : "Seiten"
    ENTITY ||--o{ FIELD : "Felder"
    ENTITY ||--o{ RECORD : "Einträge"
    FIELD }o--o| ENTITY : "Verweis (reference)"

    APP {
        string name
        slug slug UK
        string kind "app oder automation"
        bool published
        json translations
    }
    ENTITY {
        string name
        slug slug "eindeutig je App"
        bool allow_create
        bool allow_edit
        bool allow_delete
        bool api_enabled
    }
    FIELD {
        string label
        slug key "eindeutig je Tabelle"
        string type "text, number, date, choice, reference …"
        bool required
        text choices
        string formula "optionaler AST-Formelausdruck"
        int order
    }
    RECORD {
        json data "Werte nach Feld-key"
        datetime created_at
        datetime updated_at
    }
    PAGE {
        string title
        slug slug "eindeutig je App"
        bool public
        int version "Optimistic Locking (409)"
        json layout "Liste von Bausteinen"
    }
```

### Logik, Zugänge und Verlauf

```mermaid
erDiagram
    APP ||--o{ SCRIPT : "Skripte"
    APP ||--o{ DATAQUERY : "Abfragen"
    APP ||--o{ APIKEY : "API-Schlüssel"
    APP ||--o{ APPVERSION : "Versionen"
    SCRIPT ||--o{ SCRIPTRUN : "Läufe"
    USER ||--o{ APP : "Eigentümer/in"
    USER }o--o{ APP : "Mitbearbeiter"
    GROUP }o--o{ APP : "Nutzung, Mitbearbeiter-Gruppen"
    USER ||--o{ DESIGNERTOKEN : "KI-Zugänge"
    USER ||--o| TUTORIAL : "Einführung"

    SCRIPT {
        string language "python oder javascript"
        string trigger
        text code
        datetime next_run_at
        datetime running_since "Sperre"
        datetime heartbeat_at
        bool run_requested
        bool stop_requested
    }
    SCRIPTRUN {
        string status "running, ok, error, skipped, aborted, stopped"
        text log
        text error
        int duration_ms
    }
    DATAQUERY {
        string source
        text sql
        int cache_seconds
        int sync_interval
    }
    APIKEY {
        string prefix "bk_…"
        string key_hash "SHA-256"
        bool can_write
    }
    DESIGNERTOKEN {
        string prefix "bkd_…"
        string key_hash "SHA-256"
    }
    APPVERSION {
        int number
        json snapshot "Aufbau ohne Daten"
        bool automatic
    }
```

Außerdem gibt es `CustomBlock` (eigene HTML-Bausteine und Vorlagen, für alle Apps) und
die Django-Standardmodelle `User`, `Group` und `Session`. Skripte können an eine Seite
oder Tabelle gebunden sein, Abfragen an eine Tabelle, in die sie spiegeln; diese
Verweise fehlen im Diagramm der Übersicht halber.

### Wichtige Designentscheidungen

| Entscheidung | Begründung |
|---|---|
| `Record.data` als JSON | Schemaänderungen im Designer ohne Migration |
| `UnicodeJSONEncoder` (`ensure_ascii=False`) | die Textsuche findet Umlaute auf jeder Datenbank |
| Kurznamen automatisch, eindeutig je App bzw. Tabelle | stabile, lesbare Adressen und Namen für Skripte |
| `Page.layout` als JSON-Liste | der Seiten-Designer speichert Bausteine und Einstellungen direkt |
| Schlüssel nur als SHA-256-Hash | der Klartext erscheint nur einmal beim Erzeugen |
| Sperre über `Script.running_since` | ein Skript läuft nie doppelt, auch nicht über Pods hinweg |

### Feldtypen

`text`, `longtext`, `number`, `decimal`, `date`, `bool`, `choice`, `email`, `url`,
`reference` (Verweis auf eine andere Tabelle der App).

---

## 5. Anfrageverarbeitung und Routing

### Middleware (in dieser Reihenfolge)

| # | Middleware | Aufgabe |
|---|---|---|
| 1 | `HealthCheckMiddleware` | beantwortet `/healthz` vor der Host-Prüfung, damit Kubernetes-Probes immer durchkommen |
| 2 | `SecurityMiddleware` | HTTPS-Weiterleitung, Sicherheits-Header |
| 3 | `WhiteNoiseMiddleware` | statische Dateien |
| 4 | `SessionMiddleware` | Sitzungen (in der Datenbank) |
| 5 | `LocaleMiddleware` | Sprache der Oberfläche |
| 6 | `AppTranslationMiddleware` | setzt die Übersetzungen der App je Anfrage zurück |
| 7 | `CommonMiddleware` | Host-Prüfung, Schrägstriche |
| 8 | `CsrfViewMiddleware` | CSRF-Schutz (API und MCP sind ausgenommen, sie nutzen Schlüssel) |
| 9 | `AuthenticationMiddleware` | angemeldete Person |
| 10 | `MessageMiddleware` | Meldungen nach Aktionen |
| 11 | `XFrameOptionsMiddleware` | kein Einbetten in fremde Seiten |

Welche Übersetzungen einer App gelten, setzen die Views selbst (`app_i18n.activate`),
sobald klar ist, um welche App es geht.

### URL-Bereiche

| Präfix | Modul | Zweck |
|---|---|---|
| `/`, `/a/<app>/…` | `views.py` | Laufzeit: Seiten, Einträge, Export, Skripte, nachladende Bausteine |
| `/designer/…` | `designer.py` | Apps, Tabellen, Felder, Seiten, Skripte, Abfragen, Versionen |
| `/api/v1/<app>/…` | `api.py` | REST-API, OpenAPI, eigene Endpunkte, Webhooks (`ausloesen/`) |
| `/a/<app>/api-doku/…` | `views.py` | Dokumentation und Swagger je App |
| `/mcp/<app>/` | `mcp.py` | MCP-Server je App |
| `/mcp/designer/` | `mcp_designer.py` | MCP-Server für den Designer |
| `/profil/`, `/hilfe/` | `profile.py`, `help.py` | Profil, Schlüssel, KI-Zugänge, Handbuch |
| `/admin/` | Django Admin | Verwaltung, Daten je App |

### Seitenaufruf

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant V as views.page
    participant T as triggers
    participant BL as blocks
    participant DS as datasources

    B->>V: GET /a/inventar/p/uebersicht/
    V->>V: runtime_access(): benutzen oder Gast auf öffentlicher Seite?
    V->>T: Python-Skripte mit Auslöser „page“
    T-->>V: Werte für Bausteine, Meldungen
    loop je Baustein im Layout
        V->>BL: render_block()
        alt Abfrage-Baustein (LAZY_QUERIES)
            BL-->>V: Platzhalter
        else alle anderen
            BL->>DS: Daten (Cache, Parallelitätsgrenze)
            DS-->>BL: Zeilen
            BL-->>V: HTML des Bausteins
        end
    end
    V-->>B: Seite
    B->>V: GET …/b/‹baustein›/ (Platzhalter nachladen)
    V-->>B: HTML des Bausteins
```

JavaScript-Skripte mit Auslöser „page“ startet der Browser nach dem Laden in seiner
Sandbox.

---

## 6. Berechtigungskonzept

```mermaid
flowchart LR
    A(["Anfrage an<br/>eine App"]) --> L{{"angemeldet?"}}
    L -- ja --> E{{"darf sie<br/>bearbeiten? ¹"}}
    E -- ja --> FULL["Designer und Laufzeit,<br/>auch als Entwurf"]
    E -- nein --> U{{"veröffentlicht,<br/>Gruppe passt? ²"}}
    U -- ja --> USE["App benutzen"]
    U -- nein --> P
    L -- nein --> P{{"öffentliche<br/>Seite?"}}
    P -- ja --> GAST["Gast: Formulare und<br/>Buttons dieser Seite"]
    P -- nein --> NO["Anmeldung<br/>bzw. 403"]

    classDef ok fill:#ebfbee,stroke:#2b8a3e,color:#1b4d2a
    classDef limited fill:#fff4e6,stroke:#d9480f,color:#5c2400
    classDef no fill:#fff5f5,stroke:#c92a2a,color:#5c1111
    class FULL,USE ok
    class GAST limited
    class NO no
```

¹ Designer-Recht **und** Eigentümer/in, Mitbearbeiter/in (einzeln oder über eine
Gruppe), Superuser oder App ohne Eigentümer/in. Bei Automatisierungen zusätzlich das
Recht `automate_apps`. Mitbearbeiter verwalten und die App löschen dürfen nur
Eigentümer/in und Superuser.
² Die App hat keine Nutzergruppen, oder die Person ist in einer davon.
Gäste sind auf `PUBLIC_RATE` Anfragen je Adresse und Minute begrenzt.
Automatisierungen haben keine Laufzeit; sie werden nur im Designer bedient.

| Rolle | Herkunft | Rechte |
|---|---|---|
| Gast | nicht angemeldet | nur öffentliche Seiten, deren Formulare und Skript-Buttons |
| Nutzer/in | jedes Konto, Standardgruppe `Viewer` (`DEFAULT_USER_GROUPS`) | veröffentlichte Apps benutzen, die für alle oder eine eigene Gruppe frei sind |
| Designer/in | Recht `design_apps`, Mitarbeiter-Status oder Keycloak-Rolle `baukasten-designer` | eigene und geteilte Apps bauen |
| Automatisierer/in | Gruppe „Automatisierer“ (Recht `automate_apps`) zusätzlich zum Designer-Recht | Automatisierungen mit echtem Python |
| Superuser | Django | alles, auch `/admin/` |
| API-Schlüssel | `ApiKey` je App | lesen, optional schreiben; nur Tabellen mit `api_enabled` |
| KI-Zugang | `DesignerToken` je Person | MCP-Designer mit den Rechten dieser Person |

Bei Keycloak kommen die Gruppen aus dem Claim `OIDC_GROUPS_CLAIM` (`builder/auth.py`).

---

## 7. Skript-Engine

### Die drei Skriptarten

| | Python (normale App) | JavaScript | Python (Automatisierung) |
|---|---|---|---|
| Läuft | Web-Pod, Kindprozess | Browser, iframe-Sandbox | Worker-Pod, Kindprozess |
| Einschränkung | RestrictedPython, Modul-Liste | Sandbox ohne Seite, Cookies und Netz | keine (echtes Python) |
| Auslöser | page, button, save, schedule | page, button | schedule, daily, continuous, manual |
| Zeitlimit | `SCRIPT_TIMEOUT` (10 s) | `SCRIPT_TIMEOUT` | je Skript, höchstens `AUTOMATION_MAX_TIMEOUT_MINUTES` |
| Speicher | `SCRIPT_MEMORY_MB` | Browser | `AUTOMATION_MEMORY_MB` |
| Tabellen | alle der App | mit den Rechten der Person | alle der App |
| Netz | `http.get_json` über den Elternprozess, Freigabeliste | – | direkt (z. B. `requests`) |
| Geheimnisse | – | – | `secret("NAME")` |

### Python: Kindprozess und Elternprozess

Der Kindprozess (`child.py`) importiert **kein Django**, hat **keine Zugangsdaten**
und **keine Datenbankverbindung**. Er spricht nur über JSON-Zeilen auf stdin/stdout
mit dem Elternprozess, und der prüft jede Anfrage.

```mermaid
sequenceDiagram
    autonumber
    participant A as Aufrufer<br/>triggers.execute
    participant P as python.run<br/>Elternprozess
    participant C as child.py<br/>Kindprozess

    A->>P: run(code, app, user, event, …)
    P->>C: starten: python -I, fast leere Umgebung, rlimits
    P->>C: Kontext: code, app, user, event, record, params, session
    C->>C: compile_restricted(code)
    loop solange das Skript läuft
        C->>P: {"call": "table.filter", "args": …}
        P->>P: Handler prüft und führt aus
        P-->>C: {"result": …} oder {"error": …}
    end
    C->>P: {"done": true, ok, log, ui, messages, record, session}
    P->>C: Prozess beenden
    P-->>A: Result
```

**Anfragen, die der Handler beantwortet:** `table.filter|get|count|aggregate|create|update|delete`,
`http.get_json`, `http.post_json` (nur `HTTP_ALLOWED_HOSTS`), `db.query`, `db.saved`,
bei Automatisierungen zusätzlich `secret`.

**Schutz:**

- eigener Prozess, `python -I`; die Umgebung enthält nur `PATH`, `TZ` und zwei
  Python-Schalter (unter Windows zusätzlich `SYSTEMROOT`)
- Linux: `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE=0`, `RLIMIT_NOFILE=32`, eigene Sitzung
- Zeitlimit mit hartem Beenden, höchstens `SCRIPT_MAX_CALLS` Anfragen je Lauf

Automatisierungen nutzen denselben Kindprozess im Modus „full“: echtes `exec`,
Ausgaben gehen laufend als Protokollzeilen an den Elternprozess, Stoppen per SIGTERM.

### Auslöser normaler Apps

```mermaid
flowchart LR
    PG["Seite geöffnet"] -- page --> EX
    BT["Button geklickt"] -- button --> EX
    SV["Eintrag gespeichert"] -- save --> EX
    WK["Worker, alle 30 s"] -- schedule --> EX
    EX["triggers.execute"] --> PR["python.run"] --> RUN[("ScriptRun<br/>letzte 20 je Skript")]

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef worker fill:#fff4e6,stroke:#d9480f,color:#5c2400
    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    class PG,BT,SV,EX,PR web
    class WK worker
    class RUN data
```

Bei Seitenaufrufen werden nur Fehlläufe protokolliert (`store="errors"`), sonst entstünde
für jeden Aufruf ein Eintrag. Was ein Skript selbst speichert, löst keine weiteren
„save“-Skripte aus.

---

## 8. Hintergrunddienst (Worker)

Der Worker (`builder/scripting/worker.py`) läuft als genau ein Pod und prüft alle
**2 Sekunden** (`TICK`) den Zustand.

```mermaid
flowchart TB
    S(["serve()"]) --> Tick
    S -. SIGTERM .-> END(["shutdown()<br/>Läufe stoppen"])

    subgraph Tick["tick() · alle 2 Sekunden"]
        direction LR
        HB["Lebenszeichen,<br/>Stopp-Wünsche"] --> RC["recover()<br/>verwaiste Läufe"] --> PL["plan()<br/>erste Termine"] --> DU["due()<br/>fällige Skripte"] --> CL{{"Platz frei und<br/>claim() gewonnen?"}} -- ja --> JOB["Job-Thread<br/>automation.run"]
    end

    subgraph Danach["nach jedem tick()"]
        direction LR
        AL["alive()<br/>livenessProbe"] ~~~ BG["alle 30 s: background_once()<br/>normale Apps, Abgleiche"]
    end

    Tick --> Danach

    classDef worker fill:#fff4e6,stroke:#d9480f,color:#5c2400
    class HB,RC,PL,DU,JOB,AL,BG worker
```

`claim()` ist ein bedingtes `UPDATE … WHERE running_since IS NULL`. Nur wer die Zeile
ändert, darf das Skript starten; so läuft es nie doppelt, auch nicht über Pods hinweg.

### Zustände eines Skripts

```mermaid
stateDiagram-v2
    direction LR
    state "wartet" as waiting
    state "angefordert" as requested
    state "läuft" as running
    state "Ergebnis (ScriptRun.status)" as result {
        direction TB
        state "ok" as ok
        state "Fehler" as error
        state "gestoppt" as stopped
        state "abgebrochen" as aborted
    }

    [*] --> waiting
    waiting --> requested: Knopf, Webhook, MCP
    requested --> running: claim()
    waiting --> running: Termin fällig, Dauerläufer
    running --> ok: Skript endet
    running --> error: Ausnahme, Zeitlimit
    running --> stopped: Stoppen, ausgeschaltet
    running --> aborted: Dienst endet
    result --> waiting: nächster Termin
```

Während eines Laufs hält `running_since` die Sperre, `heartbeat_at` zeigt, dass der
Dienst lebt, und das Protokoll landet alle 2 Sekunden in `ScriptRun.log` (höchstens
50.000 Zeichen, das Ende bleibt).

**Garantien:**

- **Kein Überholen:** Ein Skript läuft nie doppelt (Sperre per bedingtem `UPDATE`).
- **Kein Nachholen:** Fällt ein Termin in einen laufenden Lauf, entfällt er und steht als
  `skipped` im Protokoll. Lag der Dienst länger still, startet der nächste Lauf zum
  nächsten Termin ab jetzt, ohne Vermerk.
- **Dauerläufer** starten nach dem Ende neu, nach Fehlern mit 10, 30, 120, 300 und 600 s
  Wartezeit. Nach 10 Minuten fehlerfreier Laufzeit beginnt die Zählung von vorn.
- **Sauberes Beenden:** SIGTERM an den Dienst stoppt laufende Skripte (SIGTERM, nach
  10 s SIGKILL), wartet bis zu 20 s und vermerkt sie als `aborted`;
  `terminationGracePeriodSeconds: 45`.
- **Parallelität:** höchstens `AUTOMATION_PARALLEL` Läufe, Dauerläufer zählen nicht mit.
- Aufbewahrt werden die letzten 30 Läufe je Skript.

---

## 9. Externe Datenquellen

Datenquellen richtet nur der Betrieb ein, über Umgebungsvariablen:
`DATASOURCE_<NAME>=<verbindungs-url>` (z. B. `DATASOURCE_DWH=databricks://…`).
Im Designer wird nur der Name gewählt; Zugangsdaten sind dort nie sichtbar.

### Gespeicherte Abfrage unter Last

```mermaid
flowchart LR
    A(["Abfrage<br/>angefragt"]) --> B{{"frisch im<br/>Cache?"}}
    B -- ja --> R(["Zeilen"])
    B -- nein --> C{{"läuft sie<br/>gerade schon?"}}
    C -- ja --> D{{"letzter Stand<br/>da?"}}
    D -- ja --> R
    D -- nein --> WAIT(["„wird geladen“,<br/>Browser fragt nach"])
    C -- nein --> F{{"Platz frei?<br/>QUERY_PARALLEL"}}
    F -- nein --> BUSY(["„ausgelastet“"])
    F -- ja --> Q["Abfrage an die<br/>Datenbank"]
    Q -- ok --> SAVE["in den Cache"] --> R
    Q -- Fehler --> STALE(["letzter Stand<br/>oder Fehler"])

    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    classDef warn fill:#fff4e6,stroke:#d9480f,color:#5c2400
    class Q,SAVE,R data
    class WAIT,BUSY,STALE warn
```

- **Frisch** heißt: jünger als `cache_seconds` der Abfrage. Der Cache ist für alle Pods
  gemeinsam (Redis oder Datenbank).
- **Läuft gerade** erkennt eine Sperre im Cache, auch in einem anderen Pod. Wer keinen
  letzten Stand hat, wartet bis zu `QUERY_WAIT` Sekunden; nachladende Bausteine warten gar
  nicht, sondern fragen nach 2 Sekunden erneut.
- **Platz frei** zählt die Abfragen je Quelle im ganzen Cluster (`QUERY_PARALLEL`,
  einzeln `QUERY_PARALLEL_<NAME>`).
- Die Abfrage selbst darf `QUERY_TIMEOUT` Sekunden dauern, beim Spiegeln im Hintergrund
  `SYNC_TIMEOUT`. Schlägt sie fehl, kommt der letzte Stand mit `stale: true` zurück.

Erlaubt sind nur Abfragen, die mit `SELECT` oder `WITH` beginnen, mit Parametern als
`:name`. Die eigentliche Sicherheit ist ein Datenbank-Benutzer, der nur lesen darf.

**Spiegeln:** Eine `DataQuery` mit `sync_entity` schreibt ihr Ergebnis in eine
App-Tabelle, per Knopf oder alle `sync_interval` Minuten durch den Worker
(`SYNC_TIMEOUT`). Mit `key_column` wird abgeglichen, sonst neu befüllt.

---

## 10. API, OpenAPI und MCP

### REST-API

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/v1/<app>/` | Beschreibung der App |
| GET | `/api/v1/<app>/openapi.json` | OpenAPI-Spezifikation |
| GET, POST | `/api/v1/<app>/<tabelle>/` | Liste (Filter, Seiten) oder anlegen |
| GET, PATCH, PUT, DELETE | `/api/v1/<app>/<tabelle>/<id>/` | einzelner Eintrag |
| beliebig | `/api/v1/<app>/x/<name>/` | eigene Endpunkte aus `extensions/` |
| POST | `/api/v1/<app>/ausloesen/<skript>/` | Webhook für Automatisierungen |

Angemeldet wird mit einem API-Schlüssel der App (`bk_…`). Schlüssel ohne `can_write`
dürfen nur lesen; erreichbar sind nur Tabellen mit `api_enabled`. Der Tabellenzugriff
läuft über dieselbe Schicht wie bei Skripten (`scripting/ops.py`).

### Die zwei MCP-Server

Beide sprechen MCP über „Streamable HTTP“ ohne Streaming: jede Anfrage ein POST mit
einer JSON-RPC-Nachricht. Den Protokollteil teilen sie sich (`mcp.dispatch`, `mcp.serve`).

```mermaid
flowchart LR
    subgraph App["MCP je App · /mcp/‹app›/"]
        direction TB
        A1["API-Schlüssel der App<br/>bk_…"] --> A2["Tools je freigegebener Tabelle<br/>lesen; schreiben nur mit can_write"]
        A2 --> A3["bei Automatisierungen:<br/>start_‹skript›, automation_status"]
    end
    subgraph Des["MCP für den Designer · /mcp/designer/"]
        direction TB
        D1["persönlicher KI-Zugang<br/>bkd_…"] --> D2["guide, list_apps, get_app,<br/>validate_app, create_app,<br/>update_app, restore_version"]
        D2 --> D3["ai_designer.py: prüfen, schützen,<br/>Version vor jeder Änderung,<br/>höchstens AI_WRITES je 10 min"]
    end
    AG(["KI-Agent<br/>n8n, Claude, Cursor"]) --> A1
    AG --> D1

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef ext fill:#f1f3f5,stroke:#868e96,color:#212529
    class A1,A2,A3,D1,D2,D3 web
    class AG ext
```

Der Designer-Server handelt mit den Rechten der Person, der der Schlüssel gehört. Er
legt Apps nur als Entwurf an und kann nicht veröffentlichen, nichts öffentlich machen,
keine Tabelle für die API freigeben und keine Skripte einschalten.

### Python-Client

`clients/python/baukasten_client` bietet gegen die REST-API dieselben Befehle wie
Skripte (`filter`, `get`, `create`, …).

---

## 11. Versionierung und Übersetzungen

### Versionen (`versions.py`)

```mermaid
flowchart LR
    APP["App<br/>Einstellungen, Tabellen,<br/>Felder, Seiten, Skripte"] -- snapshot --> V[("AppVersion<br/>JSON ohne Daten")]
    V -- wiederherstellen --> APP
    V -- herunterladen --> F["Datei .json"]
    F -- "/designer/import/" --> APP2["App in einer<br/>anderen Umgebung"]
    KI(["KI-Zugang"]) -- "update_app sichert vorher" --> V

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    classDef ext fill:#f1f3f5,stroke:#868e96,color:#212529
    class APP,APP2 web
    class V,F data
    class KI ext
```

Automatische Versionen (`automatic=True`) entstehen vor dem Wiederherstellen, vor dem
Einspielen einer Datei und bei jeder Änderung über den KI-Zugang.

**Format-Versionen:** Jeder Stand trägt `format` (`baukasten-app/2`) und `baukasten_version`.
`versions.upgrade()` hebt ältere Stände Schritt für Schritt an (`UPGRADES`: 1 → 2 → …), bevor
sie eingespielt werden; das gilt für Dateien und für alte, gespeicherte Versionen. Stände aus
einem neueren Format werden abgelehnt. Bei einer inkompatiblen Änderung: `FORMAT_VERSION`
erhöhen, eine Funktion in `UPGRADES` ergänzen, eine alte Beispieldatei in die Tests
(`FormatUpgradeTests`). Tabellen werden beim Wiederherstellen nie gelöscht;
ihre Einträge bleiben erhalten.

### Übersetzungen (`app_i18n.py`)

- Oberflächentexte: Django-gettext (`builder/locale/en`).
- App-Inhalte: `App.translations = {"en": {"Quelltext": "Übersetzung"}}`, aktiviert in
  den Views; `AppTranslationMiddleware` setzt sie nach jeder Anfrage zurück. Export und
  Import als CSV.
- Gespeicherte Daten, API und Skripte bleiben unübersetzt (stabile Schlüssel).

---

## 12. Deployment auf Kubernetes

```mermaid
flowchart LR
    USR(["Nutzer, Programme,<br/>KI-Agenten"]) --> ING["Ingress<br/>TLS"] --> SVC["Service<br/>:80"] --> WL

    subgraph NS["Namespace baukasten"]
        direction LR
        subgraph CFGS["Konfiguration"]
            direction TB
            CFG[["ConfigMap und Secret<br/>baukasten-config, -secret"]] ~~~ SSEC[["Secret<br/>baukasten-skript-geheimnisse"]]
        end
        subgraph WL["Workloads"]
            direction TB
            WEB["Deployment baukasten<br/>2–6 Pods · HPA · PDB"] ~~~ WRK["Deployment baukasten-worker<br/>1 Pod · Recreate · kein SA-Token"] ~~~ JOB["Job baukasten-migrate"]
        end
        RD[("Redis<br/>optional")]
    end
    PG[("PostgreSQL")]

    CFGS -. Umgebung .-> WL
    WL --> PG
    WL -.-> RD

    classDef web fill:#e3f4f6,stroke:#0b7285,color:#0b3d47
    classDef worker fill:#fff4e6,stroke:#d9480f,color:#5c2400
    classDef data fill:#e7f0ff,stroke:#364fc7,color:#1b2a6b
    classDef ext fill:#f1f3f5,stroke:#868e96,color:#212529
    class ING,SVC,WEB,JOB web
    class WRK,SSEC worker
    class PG,RD,CFG data
    class USR ext
```

Die Konfiguration bekommen alle drei Workloads; das Secret mit den Geheimnissen für
Skripte nur der Worker. Der Service leitet nur auf die Web-Pods. Lokal mit Docker
Desktop läuft PostgreSQL mit im Namespace; Ingress und HPA entfallen dort.

### Ausrollen

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Entwickler/in
    participant Reg as Registry
    participant K as Kubernetes
    Dev->>Reg: docker build und push (python:3.13-slim, collectstatic)
    Dev->>K: alten Job löschen, k8s/migrate-job.yaml anwenden
    K->>K: manage.py migrate
    Dev->>K: kubectl apply -f k8s/app.yaml -f k8s/worker.yaml
    K->>K: Web: neue Pods (readiness /healthz), dann alte beenden
    K->>K: Worker: SIGTERM, Läufe „abgebrochen“, neuer Pod
```

Lokal mit Docker Desktop erledigt das `k8s\lokal\deploy.ps1 -OhneBeispiele` (Kustomize,
eigene PostgreSQL); danach unter http://localhost:8080 erreichbar.

### Kapazität

Datenbankverbindungen ≈ `Pods × GUNICORN_WORKERS × GUNICORN_THREADS` plus Worker. Bei
6 Pods × 3 × 4 sind das 72; `max_connections` von PostgreSQL muss reichen.

---

## 13. Konfiguration (Umgebungsvariablen)

| Variable | Standard | Bedeutung |
|---|---|---|
| `DEBUG` | `0` | Entwicklungsmodus |
| `SECRET_KEY` | – (produktiv Pflicht) | Django-Schlüssel |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | `localhost,127.0.0.1` | Hostnamen |
| `DATABASE_URL` | SQLite | z. B. `postgres://user:pass@host:5432/db` |
| `DB_CONN_MAX_AGE` | `60` | Datenbankverbindungen offen halten (s) |
| `REDIS_URL`, `CACHE_BACKEND` | –, automatisch | `redis`, `database` oder `memory` |
| `DEFAULT_USER_GROUPS` | `Viewer` | Standardgruppen |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | – | Keycloak |
| `OIDC_ONLY`, `OIDC_GROUPS_CLAIM`, `OIDC_DESIGNER_ROLE` | `0`, `groups`, `baukasten-designer` | Keycloak im Detail |
| `SCRIPT_TIMEOUT`, `SCRIPT_MEMORY_MB`, `SCRIPT_MAX_CALLS` | `10`, `512`, `1000` | Grenzen der Python-Sandbox |
| `AUTOMATION_PARALLEL`, `AUTOMATION_MEMORY_MB` | `4`, `2048` | Worker |
| `AUTOMATION_MAX_TIMEOUT_MINUTES`, `AUTOMATION_MAX_CALLS` | `240`, `0` | Worker |
| `SCRIPT_SECRET_<NAME>` | – | Geheimnis für Automatisierungen (nur Worker) |
| `AUDIT_RETENTION_DAYS` | `365` | Änderungsprotokoll aufbewahren (Tage, 0 = nie) |
| `METRICS_TOKEN` | – | Schlüssel für `/metrics`; leer = abgeschaltet |
| `AI_WRITES` | `30` | Änderungen je KI-Zugang in 10 Minuten |
| `PUBLIC_RATE` | `120` | Anfragen von Gästen je Adresse und Minute |
| `DATASOURCE_<NAME>` | – | externe Datenquelle |
| `QUERY_TIMEOUT`, `SYNC_TIMEOUT` | `25`, `300` | Zeitlimits für Abfragen (s) |
| `QUERY_PARALLEL`, `QUERY_PARALLEL_<NAME>`, `QUERY_WAIT` | `4`, –, `2` | Lastbegrenzung |
| `LAZY_QUERIES` | `true` | Abfrage-Bausteine nachladen |
| `HTTP_ALLOWED_HOSTS`, `HTTP_TIMEOUT` | –, `10` | ausgehende HTTP-Aufrufe |
| `TABLEAU_HOSTS`, `TABLEAU_CONNECTED_APP_*`, `TABLEAU_USER_ATTRIBUTE` | – | Tableau |
| `ALERT_CHANNEL`, `ALERT_TARGET`, `ALERT_AUTH_HEADER` | `off`, –, – | Fehler-Alarmierung (`teams`, `email`, `api`) |
| `ALERT_REPEAT_MINUTES` | `60` | derselbe Fehler höchstens einmal je Zeitraum (0 = jedes Mal) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | `3`, `4`, `60` | Webserver |
| `REDIS_PASSWORD` | – | Passwort für Redis aus `k8s/redis.yaml` |
| `COOKIE_SECURE`, `LOG_LEVEL` | `true`, `INFO` | Sonstiges |

---

## 14. Sicherheit

Die Schutzmaßnahmen wirken auf mehreren Ebenen nebeneinander:

| Ebene | Maßnahmen |
|---|---|
| Netz | Ingress mit TLS, `ALLOWED_HOSTS`, CSRF-Schutz, sichere Cookies, kein Einbetten in fremde Seiten |
| Identität | lokale Konten oder Keycloak; API-Schlüssel und KI-Zugänge nur als SHA-256-Hash |
| Rechte | Designer-Recht je App (Eigentümer/in, Mitbearbeiter), Tabellenrechte, Schreibrecht des Schlüssels, `public_reach` für Gäste, `automate_apps` für Automatisierungen |
| Ausführung | Kindprozesse mit fast leerer Umgebung; RestrictedPython und rlimits für normale Skripte; Sandbox im Browser für JavaScript |
| Ausgang | HTTP nur an `HTTP_ALLOWED_HOSTS` (normale Skripte, Bausteine), Abfragen nur lesend |
| Betrieb | Container ohne root, alle Capabilities entfernt, kein ServiceAccount-Token im Worker |

Im Einzelnen:

- **HTML eigener Bausteine** wird über `sanitize.py` bereinigt.
- **Worker-Härtung:** `PR_SET_DUMPABLE=0`, damit Skripte `/proc/<pid>/environ` des
  Dienstes nicht lesen können; Kindprozesse starten ohne Zugangsdaten. Läuft der Dienst
  als root, laufen Skripte als `nobody`.
- **Geheimnisse** für Automatisierungen liegen in einem eigenen Secret, das nur der
  Worker-Pod bekommt.
- **Nicht abgeschottet** ist das Netz der Automatisierungen: Sie erreichen alles, was
  der Worker-Pod erreicht. Deshalb dürfen nur Automatisierer sie bauen, Redis verlangt
  ein Passwort, und NetworkPolicies können den Worker weiter einschränken.
- **Öffentliche Seiten:** Gäste erreichen nur die Formulare und Buttons dieser Seite,
  mit Anfragebegrenzung je Adresse.

---

## 15. Entwicklung und Tests

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-automation.txt
$env:DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py demo                    # Beispiel-App „Inventar“
python manage.py runserver
python manage.py hintergrund --dauerhaft # zweites Terminal: Worker
python manage.py test builder            # automatische Tests
```

### Erweiterungen (`extensions/`)

Module in `extensions/` registrieren über `builder/hooks.py` eigene **Aktionen**,
**Hooks** (z. B. nach dem Speichern), **Bausteine** und **API-Endpunkte**
(`/api/v1/<app>/x/<name>/`). Siehe [beispiel.py](../extensions/beispiel.py).

### Neue Migration

Änderungen an `builder/models.py` (nicht an App-Tabellen!) brauchen
`python manage.py makemigrations builder` und eine neue Datei in `builder/migrations/`.

### Rückwärtskompatibilität bei Updates

Beim Ausrollen laufen kurz alte und neue Pods nebeneinander auf derselben Datenbank, und
offene Designer-Tabs haben noch den alten Stand. Damit dabei nichts bricht:

- **Migrationen nur erweitern** (expand/contract): Spalten und Tabellen hinzufügen, neue Felder
  mit Standardwert oder `null=True`. Entfernen oder Umbenennen frühestens eine Version später,
  wenn kein alter Pod mehr läuft. Die Migration läuft vor dem Ausrollen (Migrations-Job).
- **Bausteine und Einstellungen nie entfernen oder umbenennen**, ohne die gespeicherten Seiten
  per Datenmigration umzustellen. `builder/bausteinvertrag.json` hält alle ausgelieferten
  Namen fest. Ein Test schlägt fehl, wenn einer fehlt. Neue trägt
  `python manage.py bausteinvertrag` ein.
- **Neue Einstellungen brauchen einen Standardwert** (`default`): Alte Seiten und alte Tabs
  speichern ohne sie.
- **Unbekanntes bleibt erhalten:** `clean_layout(raw, previous=…)` übernimmt Bausteine und
  Einstellungen, die diese Version nicht kennt, unverändert aus dem gespeicherten Stand der
  Seite. Beispiele sind ein entfernter Baustein, eine abgeschaltete Erweiterung oder eine Seite
  aus einer neueren Version. App-Dateien und Versionen (`keep_unknown=True`) behalten sie in
  begrenzter Größe. Der Designer zeigt dafür einen Platzhalter, die Seite lässt sie aus.
- **Designer nach einem Update:** Die Antwort aufs Speichern enthält `baukasten_version`. Weicht
  sie vom Stand beim Öffnen ab, bittet der Designer ums Neuladen. Ungespeicherte Änderungen
  liegen bis zum Speichern als Entwurf im Browser (localStorage) und werden nach dem Neuladen
  angeboten. Die Versionsnummer der Seite (409 bei Konflikt) verhindert gegenseitiges
  Überschreiben.

---

*Siehe auch:* [HANDBUCH.md](HANDBUCH.md) · [HANDBOOK.en.md](HANDBOOK.en.md) ·
[README](../README.md)
