# Baukasten – Technische Dokumentation

> Zielgruppe: Entwickler/innen und Betrieb. Für die Bedienung siehe
> [HANDBUCH.md](HANDBUCH.md). Alle Diagramme sind in Mermaid geschrieben und werden
> auf GitHub/GitLab und in den meisten Markdown-Viewern direkt gerendert.

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
ergänzen Logik in Python oder JavaScript.

| Eigenschaft | Umsetzung |
|---|---|
| Sprache / Framework | Python ≥ 3.10, Django ≥ 5.2 |
| Datenbank | SQLite (lokal), PostgreSQL 16 (produktiv) via `DATABASE_URL` |
| Cache | Redis, Datenbank-Tabelle oder Arbeitsspeicher |
| Anwendungsserver | gunicorn (`gunicorn.conf.py`), statische Dateien über WhiteNoise |
| Anmeldung | lokale Konten oder Keycloak (OpenID Connect, `mozilla-django-oidc`) |
| Skript-Sandbox | eigener Prozess + RestrictedPython (Python), iframe-Sandbox (JavaScript) |
| Betrieb | Docker-Image, Kubernetes-Manifeste in `k8s/` |
| Sprachen | Deutsch (Quelle), Englisch (`builder/locale/en`) |

**Kernidee:** Datensätze aller App-Tabellen liegen als JSON in einer gemeinsamen
Tabelle (`Record.data`). Änderungen im Designer erfordern daher **keine
Datenbank-Migration**.

---

## 2. Systemarchitektur

```mermaid
flowchart LR
    subgraph Clients
        U["Browser<br/>(Nutzer & Designer)"]
        G["Gäste<br/>(öffentliche Seiten)"]
        X["Externe Systeme<br/>(REST-API)"]
        K["KI-Agenten<br/>(n8n, Claude, Cursor)"]
    end

    subgraph Cluster["Kubernetes / lokal"]
        ING["Ingress (TLS)"]
        subgraph Web["Deployment baukasten (2–6 Pods)"]
            GU["gunicorn + Django"]
            SB["Skript-Kindprozesse<br/>(RestrictedPython)"]
        end
        subgraph Worker["Deployment baukasten-worker (1 Pod)"]
            WK["Hintergrunddienst<br/>manage.py hintergrund"]
            AU["Automatisierungs-<br/>Kindprozesse"]
        end
        PG[("PostgreSQL")]
        RD[("Redis (optional)")]
    end

    subgraph Extern["Externe Dienste"]
        KC["Keycloak (OIDC)"]
        DS[("Datenquellen<br/>Databricks, SQL-DBs")]
        TB["Tableau Server/Cloud"]
        HT["Freigegebene HTTP-Hosts"]
    end

    U & G & X & K --> ING --> GU
    GU <--> SB
    GU --> PG
    GU --> RD
    WK <--> AU
    WK --> PG
    GU -. Login .-> KC
    GU & WK --> DS
    U -. Einbettung .-> TB
    SB & AU -. über Elternprozess .-> HT
```

**Zwei Prozessarten aus demselben Image:**

- **Web** (`gunicorn config.wsgi`): Laufzeit der Apps, Designer, API, MCP, Admin.
- **Worker** (`python manage.py hintergrund --dauerhaft`): Automatisierungen,
  zeitgesteuerte Skripte normaler Apps, Abgleich von Datenquellen.

---

## 3. Projektstruktur und Module

```
baukasten/
├── config/                 Django-Projekt (settings, urls, wsgi)
├── builder/                die eigentliche Anwendung
│   ├── models.py           Datenmodell
│   ├── urls.py             alle Routen
│   ├── views.py            Laufzeit: Seiten, Formulare, Export, Skript-Aufrufe
│   ├── designer.py         Designer-Oberfläche (Apps, Tabellen, Seiten, Skripte …)
│   ├── blocks.py           Registry und Rendering der Seiten-Bausteine
│   ├── forms.py            dynamische Formulare aus Field-Definitionen
│   ├── api.py / openapi.py REST-API und OpenAPI-Spezifikation
│   ├── mcp.py              MCP-Server je App
│   ├── mcp_designer.py     MCP-Server für den Designer (KI baut Apps)
│   ├── ai_designer.py      Werkzeuge für den Designer-MCP
│   ├── datasources.py      externe Datenbanken, Cache, Parallelitätsgrenzen
│   ├── versions.py         Snapshots, Export/Import von Apps
│   ├── app_i18n.py         Übersetzung von App-Inhalten
│   ├── auth.py             Keycloak-Backend (Gruppen, Designer-Rolle)
│   ├── hooks.py            Erweiterungspunkte für extensions/
│   ├── services.py         HTTP-Zugriffe mit Host-Freigabeliste
│   ├── sanitize.py         HTML-Bereinigung eigener Bausteine
│   ├── tableau.py          Tableau-Einbettung (Connected App, JWT)
│   ├── middleware.py       /healthz, App-Übersetzungen
│   ├── tutorial.py, tours.py  Einführung und Touren
│   ├── scripting/
│   │   ├── python.py       Start/Steuerung der Python-Sandbox
│   │   ├── child.py        Kindprozess (ohne Django-Import)
│   │   ├── ops.py          Tabellenzugriff für Skripte und API
│   │   ├── triggers.py     Auslöser normaler Apps
│   │   ├── automation.py   Ausführung von Automatisierungen
│   │   ├── worker.py       Hintergrunddienst („Aufseher“)
│   │   └── schedule.py     Zeitpläne
│   ├── management/commands/  demo, beispiel_einwilligung, hintergrund, lokal_einrichten
│   ├── templates/, static/   Oberfläche (Vanilla JS/CSS)
│   └── tests.py            automatische Tests
├── extensions/             eigene Python-Erweiterungen (beispiel.py)
├── clients/python/         Bibliothek baukasten-client
├── k8s/                    Kubernetes-Manifeste (+ lokal/ für Docker Desktop)
└── docs/                   Dokumentation
```

### Modulabhängigkeiten

```mermaid
flowchart TD
    urls["urls.py"] --> views & designer & api & mcp & mcp_designer & profile & help
    views --> blocks & forms & triggers
    designer --> versions & app_i18n & blocks & forms
    blocks --> datasources & tableau & sanitize & hooks
    api --> ops & openapi & hooks
    mcp --> ops
    mcp_designer --> ai_designer --> versions
    triggers --> python
    python --> child
    python --> ops & datasources & services
    worker --> automation --> child
    worker --> triggers & datasources & schedule
    ops & versions & datasources --> models[("models.py")]
```

---

## 4. Datenmodell

```mermaid
erDiagram
    USER ||--o{ APP : "created_by (Eigentümer/in)"
    USER }o--o{ APP : "editors"
    GROUP }o--o{ APP : "groups (Nutzung)"
    GROUP }o--o{ APP : "editor_groups"

    APP ||--o{ ENTITY : "entities"
    APP ||--o{ PAGE : "pages"
    APP ||--o{ SCRIPT : "scripts"
    APP ||--o{ DATAQUERY : "queries"
    APP ||--o{ APIKEY : "api_keys"
    APP ||--o{ APPVERSION : "versions"

    ENTITY ||--o{ FIELD : "fields"
    ENTITY ||--o{ RECORD : "records"
    FIELD }o--o| ENTITY : "reference"
    DATAQUERY }o--o| ENTITY : "sync_entity"
    SCRIPT }o--o| PAGE : "page"
    SCRIPT }o--o| ENTITY : "entity"
    SCRIPT ||--o{ SCRIPTRUN : "runs"

    USER ||--o{ DESIGNERTOKEN : "designer_tokens"
    USER ||--o| TUTORIAL : "tutorial"

    APP {
        string name
        slug slug UK
        string kind "app | automation"
        bool published
        json translations
    }
    ENTITY {
        string name
        slug slug "unique je App"
        bool allow_create
        bool allow_edit
        bool allow_delete
        bool api_enabled
    }
    FIELD {
        string label
        slug key "unique je Tabelle"
        string type "text, number, date, choice, reference ..."
        bool required
        text choices
        int order
    }
    RECORD {
        json data "Feldwerte nach key"
        datetime created_at
        datetime updated_at
    }
    PAGE {
        string title
        slug slug
        bool public
        json layout "Liste von Bausteinen"
    }
    SCRIPT {
        string language "python | javascript"
        string trigger
        text code
        datetime next_run_at
        datetime running_since "Sperre"
        datetime heartbeat_at
        bool run_requested
        bool stop_requested
    }
    SCRIPTRUN {
        string status
        text log
        text error
        int duration_ms
    }
    DATAQUERY {
        string source
        text sql
        int cache_seconds
        int sync_interval
        string key_column
    }
    APIKEY {
        string prefix
        string key_hash "SHA-256"
        bool can_write
    }
    APPVERSION {
        int number
        json snapshot
        bool automatic
    }
```

Außerdem: `CustomBlock` (eigene HTML-Bausteine und Vorlagen, global) sowie die
Django-Standardmodelle `User`, `Group`, `Session`.

### Wichtige Designentscheidungen

| Entscheidung | Begründung |
|---|---|
| `Record.data` als JSON | Schemaänderungen im Designer ohne Migration |
| `UnicodeJSONEncoder` (`ensure_ascii=False`) | Textsuche findet Umlaute auf jeder Datenbank |
| Slugs automatisch, eindeutig je App | stabile, lesbare URLs und Skript-Namen |
| `Page.layout` als JSON-Liste | Seiten-Designer speichert Bausteine + Props direkt |
| API-Schlüssel nur als SHA-256-Hash | Klartext wird nur einmal bei `issue()` ausgegeben |
| Sperre über `Script.running_since` | kein paralleles Ausführen, auch über Pods hinweg |

### Feldtypen

`text`, `longtext`, `number`, `decimal`, `date`, `bool`, `choice`, `email`, `url`,
`reference` (Verweis auf eine andere Tabelle der App).

---

## 5. Anfrageverarbeitung und Routing

### Middleware-Kette

```mermaid
flowchart LR
    R["Request"] --> H["HealthCheck<br/>/healthz"] --> S["Security"] --> W["WhiteNoise<br/>static"] --> SE["Session"] --> L["Locale"] --> AT["AppTranslation"] --> C["Common"] --> CS["CSRF"] --> A["Auth"] --> M["Messages"] --> XF["XFrame"] --> V["View"]
```

`/healthz` wird vor der Host-Prüfung beantwortet, damit Kubernetes-Probes immer
funktionieren.

### URL-Bereiche

| Präfix | Modul | Zweck |
|---|---|---|
| `/` , `/a/<app>/…` | `views.py` | Laufzeit: Seiten, Einträge, Export, Skripte, Bausteine |
| `/designer/…` | `designer.py` | Apps, Tabellen, Felder, Seiten, Skripte, Abfragen, Versionen |
| `/api/v1/<app>/…` | `api.py` | REST-API, OpenAPI, eigene Endpunkte, Webhooks (`ausloesen/`) |
| `/a/<app>/api-doku/…` | `views.py` | Doku und Swagger-UI je App |
| `/mcp/<app>/` | `mcp.py` | MCP-Server je App |
| `/mcp/designer/` | `mcp_designer.py` | MCP-Server für den Designer |
| `/profil/`, `/hilfe/` | `profile.py`, `help.py` | Profil, Schlüssel, Handbuch |
| `/admin/` | Django Admin | Verwaltung, Daten je App |

### Seitenaufruf (Laufzeit)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant V as views.page
    participant P as App/Page
    participant T as triggers
    participant BL as blocks
    participant DS as datasources

    B->>V: GET /a/inventar/p/uebersicht/
    V->>P: App laden, user_can_use() / page.public prüfen
    V->>T: Skripte mit Auslöser "page" ausführen
    T-->>V: ui-Werte, Meldungen
    loop je Baustein in page.layout
        V->>BL: render(block, context)
        alt Baustein mit Abfrage und LAZY_QUERIES
            BL-->>V: Platzhalter (wird nachgeladen)
        else
            BL->>DS: Daten (Cache, Parallelitätsgrenze)
            DS-->>BL: Zeilen
        end
    end
    V-->>B: HTML
    B->>V: GET /a/inventar/p/uebersicht/b/<block>/ (nachgeladen)
```

---

## 6. Berechtigungskonzept

```mermaid
flowchart TD
    A["Angemeldete Person"] --> D{"is_staff oder<br/>design_apps?"}
    D -- nein --> N["Nutzer/in"]
    D -- ja --> DES["Designer/in"]
    DES --> AU{"Superuser oder<br/>automate_apps?"}
    AU -- ja --> AUT["Automatisierer/in"]
    AU -- nein --> DES2["Designer ohne<br/>Automatisierungen"]

    N --> USE{"App veröffentlicht<br/>und Gruppe passt<br/>(oder keine Gruppen)?"}
    USE -- ja --> OK1["App benutzen"]

    DES --> ED{"Eigentümer/in, Mitbearbeiter/in,<br/>Mitbearbeiter-Gruppe,<br/>Superuser oder App ohne Eigentümer?"}
    ED -- ja --> OK2["App im Designer bearbeiten"]
    ED -- "nur Eigentümer/in / Admin" --> OK3["Mitbearbeiter verwalten, löschen"]

    G["Gast (nicht angemeldet)"] --> PUB{"Seite public und<br/>App veröffentlicht?"}
    PUB -- ja --> OK4["Nur Formulare und Skript-Buttons<br/>dieser Seite (App.public_reach)<br/>+ Rate-Limit PUBLIC_RATE"]
```

| Rolle | Herkunft | Rechte |
|---|---|---|
| Viewer | Standardgruppe (`DEFAULT_USER_GROUPS`) | veröffentlichte Apps benutzen |
| Designer | Recht `builder.design_apps` / Keycloak-Rolle `baukasten-designer` | eigene + geteilte Apps bauen |
| Automatisierer | Recht `builder.automate_apps` | zusätzlich Automatisierungen (echtes Python) |
| Superuser | Django | alles |
| API-Schlüssel | `ApiKey` je App | lesen, optional schreiben; nur Tabellen mit `api_enabled` |
| Designer-Token | `DesignerToken` je Person | MCP-Designer mit den Rechten dieser Person |

Bei Keycloak werden Gruppen aus dem Claim `OIDC_GROUPS_CLAIM` übernommen
(`builder/auth.py`).

---

## 7. Skript-Engine

### Übersicht der Skriptarten

| | Python (normale App) | JavaScript | Python (Automatisierung) |
|---|---|---|---|
| Ausführungsort | Server, Kindprozess | Browser, sandboxed iframe | Worker, Kindprozess |
| Einschränkung | RestrictedPython | iframe-Sandbox | echtes Python |
| Auslöser | page, button, save, schedule | page, button | schedule, daily, continuous, manual |
| Zeitlimit | `SCRIPT_TIMEOUT` (10 s) | – | je Skript, max. `AUTOMATION_MAX_TIMEOUT_MINUTES` |
| Speicher | `SCRIPT_MEMORY_MB` | Browser | `AUTOMATION_MEMORY_MB` |
| Tabellenrechte | alle Tabellen der App | wie angemeldete Person | alle Tabellen der App |
| Geheimnisse | – | – | `secret("NAME")` |

### Python-Sandbox: Prozessmodell

Der Kindprozess (`child.py`) importiert **kein Django**, hat **keine Zugangsdaten**
und **keine Datenbankverbindung**. Er kommuniziert ausschließlich über JSON-Zeilen
auf stdin/stdout; der Elternprozess prüft jede Anfrage.

```mermaid
sequenceDiagram
    autonumber
    participant V as View / triggers.execute
    participant P as python.run (Elternprozess)
    participant H as Handler
    participant C as child.py (Kindprozess)

    V->>P: run(code, app, user, event, record)
    P->>C: Popen(python -I child.py)<br/>leere Umgebung, rlimits (Linux)
    P->>C: {"code", "app", "user", "event", "record", "session", "max_calls"}
    C->>C: compile_restricted(code)
    loop während das Skript läuft
        C->>P: {"call": "table.filter", "args": {...}}
        P->>H: handler(op, args)
        H-->>P: Ergebnis oder OpsError
        P->>C: {"result": ...} / {"error": ...}
    end
    C->>P: {"done": true, "ok", "log", "ui", "messages", "record", "session"}
    P->>P: Prozess beenden, Ressourcen schließen
    P-->>V: Result
```

**Erlaubte Operationen** (`Handler.__call__`): `table.filter|get|count|aggregate|create|update|delete`,
`http.get_json`, `http.post_json` (nur `HTTP_ALLOWED_HOSTS`), `db.query`, `db.saved`
und – nur bei Automatisierungen – `secret`.

**Schutzmaßnahmen:**

- eigener Prozess, `python -I`, leere Umgebung (nur `PATH`, `TZ`)
- Linux: `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE=0`, `RLIMIT_NOFILE=32`, eigene Session
- Zeitlimit mit hartem `kill()`
- Obergrenze an Aufrufen (`SCRIPT_MAX_CALLS`)

### Auslöser normaler Apps

```mermaid
flowchart LR
    PG["Seite geöffnet"] -->|page| EX["triggers.execute"]
    BT["Button geklickt<br/>/a/app/skript/name/"] -->|button| EX
    SV["Eintrag gespeichert"] -->|save| EX
    WK["Worker alle 30 s<br/>run_due()"] -->|schedule| EX
    EX --> PR["python.run"] --> RUN[("ScriptRun<br/>(max. 20 je Skript)")]
```

Bei Seitenaufrufen werden nur Fehlläufe protokolliert (`store="errors"`).

---

## 8. Hintergrunddienst (Worker)

Der Worker (`builder/scripting/worker.py`) läuft als genau ein Pod und prüft alle
**2 Sekunden** (`TICK`) den Zustand.

```mermaid
flowchart TD
    S["serve()"] --> T["tick()"]
    T --> HB["Heartbeat für laufende Jobs<br/>Stopp-Anforderungen prüfen"]
    HB --> RC["recover(): verwaiste Läufe<br/>(kein Heartbeat > 90 s) freigeben"]
    RC --> PL["plan(): ersten Termin für<br/>neue zeitgesteuerte Skripte"]
    PL --> DU["due(): fällige Skripte"]
    DU --> CL{"claim():<br/>atomares UPDATE<br/>running_since IS NULL"}
    CL -- gewonnen --> JOB["Job-Thread → automation.run<br/>(Kindprozess, Live-Log)"]
    CL -- verloren --> T
    T --> AL["alive(): Datei für livenessProbe"]
    AL --> LG{"30 s vergangen?"}
    LG -- ja --> LEG["background_once():<br/>Skripte normaler Apps,<br/>Abgleiche der Datenquellen"]
    LG --> W["2 s warten"] --> T
```

### Lebenszyklus eines Automatisierungslaufs

```mermaid
stateDiagram-v2
    [*] --> Wartend
    Wartend --> Angefordert: Knopf / Webhook / MCP<br/>(run_requested)
    Wartend --> Läuft: Termin fällig / Dauerläufer
    Angefordert --> Läuft: claim()
    Läuft --> ok: Skript beendet
    Läuft --> Fehler: Ausnahme
    Läuft --> gestoppt: stop_requested / deaktiviert
    Läuft --> abgebrochen: Zeitlimit / SIGTERM / kein Heartbeat
    ok --> Wartend: next_run_at berechnen
    Fehler --> Wartend: Dauerläufer: Backoff 10s…600s
    gestoppt --> Wartend
    abgebrochen --> Wartend
    note right of Läuft
        Sperre: running_since + heartbeat_at
        Live-Log alle 2 s in ScriptRun.log
        (max. 50.000 Zeichen)
    end note
```

**Garantien:**

- **Kein Überholen:** Ein Skript läuft nie doppelt (DB-Sperre per bedingtem `UPDATE`).
- **Kein Nachholen:** Verpasste Termine werden als `skipped` vermerkt.
- **Dauerläufer** starten nach Ende neu; nach Fehlern mit Backoff `10, 30, 120, 300, 600` s.
  Nach 10 min gesunder Laufzeit wird der Fehlerzähler zurückgesetzt.
- **Graceful Shutdown:** SIGTERM → laufende Jobs `aborted`, 20 s Wartezeit,
  `terminationGracePeriodSeconds: 45`.
- **Parallelität:** `AUTOMATION_PARALLEL` (Dauerläufer zählen nicht mit).
- Es werden die letzten 30 Läufe je Skript aufbewahrt.

---

## 9. Externe Datenquellen

Datenquellen werden **nur über Umgebungsvariablen** konfiguriert:
`DATASOURCE_<NAME>=<verbindungs-url>` (z. B. `DATASOURCE_DWH=databricks://…`).
Im Designer wird nur der Name ausgewählt; Zugangsdaten sind dort nie sichtbar.

```mermaid
sequenceDiagram
    autonumber
    participant B as Baustein / Skript
    participant D as datasources.run
    participant C as Cache (Redis/DB/Memory)
    participant DB as Externe DB

    B->>D: Abfrage (nur SELECT/WITH, Parameter :name)
    D->>C: Ergebnis im Cache?
    alt Treffer (cache_seconds)
        C-->>D: Zeilen
    else kein Treffer
        D->>C: Sperre gegen Mehrfachabfrage +<br/>Slot (QUERY_PARALLEL je Quelle, clusterweit)
        alt Slot innerhalb QUERY_WAIT frei
            D->>DB: Abfrage (QUERY_TIMEOUT)
            DB-->>D: Zeilen
            D->>C: speichern
        else
            D-->>B: "wird geladen" – Browser fragt nach
        end
    end
    D-->>B: Zeilen
```

**Spiegeln:** Eine `DataQuery` mit `sync_entity` schreibt ihr Ergebnis in eine
App-Tabelle – per Knopf oder alle `sync_interval` Minuten durch den Worker
(`SYNC_TIMEOUT`). Mit `key_column` wird abgeglichen, sonst neu befüllt.

---

## 10. API, OpenAPI und MCP

### REST-API

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/v1/<app>/` | Beschreibung der App |
| GET | `/api/v1/<app>/openapi.json` | OpenAPI-Spezifikation |
| GET/POST | `/api/v1/<app>/<tabelle>/` | Liste (Filter, Paging) / Anlegen |
| GET/PATCH/PUT/DELETE | `/api/v1/<app>/<tabelle>/<id>/` | Einzelner Eintrag |
| * | `/api/v1/<app>/x/<name>/` | eigene Endpunkte aus `extensions/` |
| POST | `/api/v1/<app>/ausloesen/<skript>/` | Webhook für Automatisierungen |

Authentifizierung über einen API-Schlüssel (`bk_…`) der App. Schlüssel ohne
`can_write` dürfen nur lesen; nur Tabellen mit `api_enabled` sind erreichbar.
Der Tabellenzugriff läuft über dieselbe Schicht wie Skripte (`scripting/ops.py`).

### MCP-Server

```mermaid
flowchart LR
    AG["KI-Agent"] -->|"JSON-RPC, API-Schlüssel bk_…"| M["/mcp/&lt;app&gt;/"]
    M --> TL["Tools automatisch je Tabelle<br/>(lesend; schreibend nur mit can_write)"]
    TL --> OPS["scripting/ops.py"]

    AG2["KI-Agent"] -->|"Designer-Token bkd_…"| MD["/mcp/designer/"]
    MD --> AI["ai_designer.py<br/>Apps, Tabellen, Seiten bauen"]
    AI --> RL["Rate-Limit AI_WRITES<br/>je 10 min"]
```

### Python-Client

`clients/python/baukasten_client` bietet dieselben Befehle wie Skripte
(`filter`, `get`, `create`, …) gegen die REST-API.

---

## 11. Versionierung und Übersetzungen

### Versionen (`versions.py`)

```mermaid
flowchart LR
    APP["App<br/>(Einstellungen, Tabellen,<br/>Felder, Seiten, Skripte)"] -->|snapshot| V[("AppVersion.snapshot<br/>JSON, ohne Daten")]
    V -->|wiederherstellen| APP
    V -->|herunterladen| F["Datei (.json)"]
    F -->|/designer/import/| APP2["App in anderer Umgebung"]
```

Vor riskanten Änderungen entstehen automatische Versionen (`automatic=True`).

### Übersetzungen (`app_i18n.py`)

- Oberflächentexte: Django-gettext (`builder/locale/en`).
- App-Inhalte: `App.translations = {"en": {"Quelltext": "Übersetzung"}}`,
  angewendet über `AppTranslationMiddleware`. Export/Import als CSV.
- Gespeicherte Daten, API und Skripte bleiben unübersetzt (stabile Schlüssel).

---

## 12. Deployment auf Kubernetes

```mermaid
flowchart TB
    subgraph NS["Namespace baukasten"]
        ING["Ingress<br/>baukasten.example.com (TLS)"] --> SVC["Service baukasten :80"]
        SVC --> D1["Deployment baukasten<br/>RollingUpdate, maxUnavailable 0<br/>Pods: web :8000"]
        HPA["HPA 2–6 Pods<br/>CPU 70 %"] -.-> D1
        PDB["PodDisruptionBudget<br/>minAvailable 1"] -.-> D1
        D2["Deployment baukasten-worker<br/>1 Pod, Recreate<br/>kein ServiceAccount-Token"]
        J["Job migrate<br/>manage.py migrate"]
        CM[["ConfigMap baukasten-config"]]
        SEC[["Secret baukasten-secret<br/>SECRET_KEY, DATABASE_URL,<br/>DATASOURCE_*, OIDC_CLIENT_SECRET"]]
        SSEC[["Secret baukasten-skript-geheimnisse<br/>SCRIPT_SECRET_*"]]
        R[("Redis (optional)")]
    end
    PG[("PostgreSQL")]

    CM & SEC --> D1 & D2 & J
    SSEC --> D2
    D1 & D2 & J --> PG
    D1 --> R
```

### Ausrollen

```mermaid
sequenceDiagram
    participant Dev as Entwickler/in
    participant Reg as Registry
    participant K as Kubernetes
    Dev->>Reg: docker build & push (python:3.13-slim, collectstatic)
    Dev->>K: kubectl apply -f k8s/migrate-job.yaml
    K->>K: manage.py migrate
    Dev->>K: kubectl apply -f k8s/app.yaml -f k8s/worker.yaml
    K->>K: neue Web-Pods (readiness /healthz), dann alte beenden
    K->>K: Worker: SIGTERM → Läufe "abgebrochen" → neuer Pod
```

Lokal mit Docker Desktop: `k8s\lokal\deploy.ps1 -OhneBeispiele` (Kustomize,
eigene PostgreSQL), erreichbar unter http://localhost:8080.

### Kapazitätsplanung

Datenbankverbindungen ≈ `Pods × GUNICORN_WORKERS × GUNICORN_THREADS` (+ Worker).
Bei `maxReplicas 6 × 3 × 4 = 72` Verbindungen muss `max_connections` von PostgreSQL
ausreichend groß sein.

---

## 13. Konfiguration (Umgebungsvariablen)

| Variable | Standard | Bedeutung |
|---|---|---|
| `DEBUG` | `0` | Entwicklungsmodus |
| `SECRET_KEY` | – (Pflicht produktiv) | Django-Schlüssel |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | `localhost,127.0.0.1` | Hostnamen |
| `DATABASE_URL` | SQLite | z. B. `postgres://user:pass@host:5432/db` |
| `DB_CONN_MAX_AGE` | `60` | persistente DB-Verbindungen (s) |
| `REDIS_URL` / `CACHE_BACKEND` | – / auto | `redis`, `database`, `memory` |
| `DEFAULT_USER_GROUPS` | `Viewer` | Standardgruppen |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | – | Keycloak |
| `OIDC_ONLY`, `OIDC_GROUPS_CLAIM`, `OIDC_DESIGNER_ROLE` | `0`, `groups`, `baukasten-designer` | Keycloak-Details |
| `SCRIPT_TIMEOUT`, `SCRIPT_MEMORY_MB`, `SCRIPT_MAX_CALLS` | `10`, `512`, `1000` | Sandbox-Grenzen |
| `AUTOMATION_PARALLEL`, `AUTOMATION_MEMORY_MB` | `4`, `2048` | Worker |
| `AUTOMATION_MAX_TIMEOUT_MINUTES`, `AUTOMATION_MAX_CALLS` | `240`, `0` | Worker |
| `SCRIPT_SECRET_<NAME>` | – | Geheimnisse für Automatisierungen (nur Worker) |
| `AI_WRITES` | `30` | Änderungen je Designer-Token / 10 min |
| `PUBLIC_RATE` | `120` | Gast-Anfragen je IP / Minute |
| `DATASOURCE_<NAME>` | – | externe Datenquelle |
| `QUERY_TIMEOUT`, `SYNC_TIMEOUT` | `25`, `300` | Abfrage-Zeitlimits (s) |
| `QUERY_PARALLEL`, `QUERY_PARALLEL_<NAME>`, `QUERY_WAIT` | `4`, –, `2` | Lastbegrenzung |
| `LAZY_QUERIES` | `true` | Abfrage-Bausteine nachladen |
| `HTTP_ALLOWED_HOSTS`, `HTTP_TIMEOUT` | –, `10` | ausgehende HTTP-Requests |
| `TABLEAU_HOSTS`, `TABLEAU_CONNECTED_APP_*`, `TABLEAU_USER_ATTRIBUTE` | – | Tableau |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | `3`, `4`, `60` | Webserver |
| `COOKIE_SECURE`, `LOG_LEVEL` | `true`, `INFO` | Sonstiges |

---

## 14. Sicherheit

```mermaid
flowchart LR
    subgraph Schichten
        A["Netz<br/>Ingress/TLS, ALLOWED_HOSTS,<br/>CSRF, Secure Cookies"]
        B["Identität<br/>lokale Konten / Keycloak,<br/>gehashte Schlüssel"]
        C["Autorisierung<br/>Rollen, Eigentümer,<br/>Gruppen, public_reach"]
        D["Ausführung<br/>Prozess-Isolation,<br/>RestrictedPython, rlimits"]
        E["Ausgang<br/>HTTP-Allowlist,<br/>nur lesende SQL"]
        F["Betrieb<br/>non-root, drop ALL caps,<br/>kein SA-Token im Worker"]
    end
    A --> B --> C --> D --> E --> F
```

- **HTML eigener Bausteine** wird über `sanitize.py` bereinigt.
- **SQL** von Abfragen: nur `SELECT` / `WITH`, Parameterbindung `:name`.
- **Worker-Härtung:** `PR_SET_DUMPABLE=0` → Skripte können `/proc/<pid>/environ`
  des Dienstes nicht lesen; Kindprozesse starten mit leerer Umgebung.
- **Geheimnisse** für Automatisierungen liegen in einem eigenen Secret, das nur der
  Worker-Pod erhält.
- **Öffentliche Seiten:** Gäste erreichen nur die auf der Seite platzierten
  Formulare/Buttons; Rate-Limit je Adresse.

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

Änderungen an `builder/models.py` (nicht an App-Tabellen!) erfordern
`python manage.py makemigrations builder` und eine neue Datei in
`builder/migrations/`.

---

*Siehe auch:* [HANDBUCH.md](HANDBUCH.md) · [HANDBOOK.en.md](HANDBOOK.en.md) ·
[README](../README.md)
