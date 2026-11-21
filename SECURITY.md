# Sicherheit (Security Policy)

## Sicherheitslücken melden

Bitte melde Sicherheitslücken **nicht** über öffentliche GitHub-Issues, sondern vertraulich an das Entwickler-/Betriebsteam (bzw. über GitHub Private Vulnerability Reporting).

## Sicherheitsgrenzen (Trust Boundaries)

1. **Skripte normaler Apps (`builder/scripting/python.py`, `child.py`):**
   - Laufen in einem kurzlebigen Kindprozess mit leerer Umgebung (keine Secrets, keine DB-Verbindung) unter `RestrictedPython`.
   - Unter Linux gelten `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE` und eine eigene Prozessgruppe (`os.setsid()`).
   - Web-Requests laufen ausschließlich über den Elternprozess und nur an Hosts aus `HTTP_ALLOWED_HOSTS` (Loopback- und Link-Local-/Metadaten-IPs werden blockiert, `allow_redirects=False`).

2. **Automatisierungen (`builder/scripting/automation.py`, `worker.py`):**
   - Laufen nur im Hintergrunddienst (`baukasten-worker`) und dürfen nur von Mitgliedern der Gruppe **Automatisierer** (`automate_apps`) bearbeitet werden.
   - Sie führen echtes Python in einer eigenen Prozessgruppe (`os.setsid()` / `os.killpg`) aus.
   - Unter Linux setzt der Worker `prctl(PR_SET_DUMPABLE, 0)`, damit Kindprozesse derselben UID nicht `/proc/<ppid>/environ` oder `/proc/<ppid>/mem` auslesen können. Im Kubernetes-Deployment ist `automountServiceAccountToken: false` empfohlen.

3. **Externe Datenquellen (`builder/datasources.py`):**
   - Werden ausschließlich über Umgebungsvariablen (`DATASOURCE_<NAME>`) durch den Betrieb eingerichtet.
   - Abfragen werden vorab geprüft (`SELECT` / `WITH`), auf Treiber-/Session-Ebene read-only geöffnet (`conn.read_only = True`, `mode=ro`, `SET SESSION TRANSACTION READ ONLY`), zeitlich begrenzt (`statement_timeout`) und per `fetchmany(limit + 1)` geladen. Die interne SQLite-Datenbank des Baukastens wird als Datenquelle blockiert.

4. **HTML-Bereinigung & MCP (`builder/sanitize.py`, `builder/mcp.py`, `builder/mcp_designer.py`):**
   - Eigene HTML-Bausteine und Markdown-Release-Notes werden über einen Whitelist-HTML-Parser (`sanitize_html`) bereinigt.
   - MCP-Endpunkte prüfen den `Origin`-Header gegen DNS-Rebinding, verlangen `Authorization: Bearer`-Tokens aktiver Nutzer und unterliegen für Schreibzugriffe im Designer-MCP einem Rate-Limit (`AI_WRITES`).
