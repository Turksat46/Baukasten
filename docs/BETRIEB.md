# Baukasten – Betriebshandbuch

> Für alle, die den Baukasten betreiben oder übernehmen: wer wofür zuständig ist, was
> regelmäßig zu tun ist, wie man sichert und wiederherstellt und was bei Störungen hilft.
> Wie der Baukasten aufgebaut ist, steht in [TECHNISCHE_DOKUMENTATION.md](TECHNISCHE_DOKUMENTATION.md),
> warum er so gebaut ist in [adr/](adr/README.md).

Alle Befehle gehen davon aus, dass der Namespace `baukasten` heißt. Lokal mit Docker
Desktop ist das so; in der Produktion ggf. anpassen.

## Inhalt

1. [Zuständigkeiten](#1-zuständigkeiten)
2. [Regelmäßige Aufgaben](#2-regelmäßige-aufgaben)
3. [Neue Version einspielen](#3-neue-version-einspielen)
4. [Sicherung und Wiederherstellung](#4-sicherung-und-wiederherstellung)
5. [Überwachung und Alarme](#5-überwachung-und-alarme)
6. [Störfälle](#6-störfälle)
7. [Erste Diagnose in fünf Befehlen](#7-erste-diagnose-in-fünf-befehlen)

---

## 1. Zuständigkeiten

| Ebene | Was | Wer | Vertretung |
|---|---|---|---|
| Betrieb | Kubernetes, PostgreSQL, Sicherungen, Zertifikate, Überwachung | _Team eintragen_ | _eintragen_ |
| Plattform-Code | Fehler, Sicherheitsupdates, neue Funktionen, Pull Requests von Dependabot | _Person eintragen_ | _zweite Person eintragen_ |
| Apps | Inhalt, Rechte und Skripte der einzelnen Apps | Eigentümer/in der App (steht im Designer) | Mitbearbeiter der App |
| Automatisierungen | Skripte mit echtem Python, Geheimnisse dafür | Gruppe „Automatisierer“ | – |

Fällt der Plattform-Code für eine Weile aus, laufen alle Apps weiter. Es kommt nur nichts
Neues dazu. Kritisch sind allein Betrieb und Sicherungen.

## 2. Regelmäßige Aufgaben

| Wann | Aufgabe | Wie |
|---|---|---|
| bei jedem Pull Request | Tests müssen grün sein | GitHub → Actions; nichts mergen, was rot ist |
| wöchentlich | Pull Requests von Dependabot prüfen und mergen | Sicherheitsupdates sofort, andere gebündelt; danach neue Version einspielen (Abschnitt 3) |
| täglich, automatisch | Sicherung der Datenbank | Abschnitt 4; prüfen, dass sie wirklich entsteht |
| monatlich | Image neu bauen, auch ohne Codeänderung | holt Sicherheitsupdates des Basis-Images `python:3.13-slim` |
| vierteljährlich | Wiederherstellung üben | Abschnitt 4.3, Ergebnis kurz notieren |
| vierteljährlich | Rechte prüfen | Wer ist Superuser, Designer, Automatisierer? `/admin/` → Gruppen; alte KI-Zugänge und API-Schlüssel löschen |
| alle zwei Jahre | Django-Hauptversion | Django-LTS-Plan beachten (5.2 bis April 2028); Versionshinweise lesen, Tests, einspielen |

## 3. Neue Version einspielen

1. Tests auf `main` sind grün (GitHub Actions).
2. `CHANGELOG.md` ergänzen, Version in `config/settings.py` (`BAUKASTEN_VERSION`) erhöhen,
   Tag setzen: `git tag v1.1.0 && git push --tags`. Für die Nutzer unter `/admin/` →
   Release Notes einen Eintrag in einfacher Sprache schreiben (oder den vorbereiteten Entwurf
   anpassen) und nach dem Ausrollen „veröffentlicht“ anhaken; er erscheint dann unter `/ueber/`.
3. Image bauen und hochladen: `docker build -t registry.example.com/baukasten:1.1.0 .`
   und `docker push …`.
4. **Erst migrieren, dann ausrollen:**
   ```
   kubectl -n baukasten delete job baukasten-migrate --ignore-not-found
   kubectl -n baukasten apply -f k8s/migrate-job.yaml     (Image-Tag vorher anpassen)
   kubectl -n baukasten wait --for=condition=complete job/baukasten-migrate --timeout=300s
   kubectl -n baukasten set image deploy/baukasten web=registry.example.com/baukasten:1.1.0
   kubectl -n baukasten set image deploy/baukasten-worker worker=registry.example.com/baukasten:1.1.0
   kubectl -n baukasten rollout status deploy/baukasten
   ```
5. Prüfen: Startseite lädt, `/metrics` zeigt die neue Version und `baukasten_worker_up 1`.

Lokal erledigt das alles `k8s\lokal\deploy.ps1 -OhneBeispiele`.

**Zurück auf die alte Version:** `kubectl -n baukasten rollout undo deploy/baukasten` und
dasselbe für `deploy/baukasten-worker`. Hat die neue Version Migrationen mitgebracht,
die Daten verändern, vorher die Sicherung von vor dem Einspielen bereithalten
(Abschnitt 4.2).

**Wer gerade eine Seite bearbeitet,** verliert beim Ausrollen nichts. Der Designer speichert
weiter, bittet danach ums Neuladen und hält ungespeicherte Änderungen als Entwurf im Browser.
Seiten mit Bausteinen, die die laufende Version nicht kennt (auch nach einem Zurückrollen),
behalten diese Bausteine. Regeln für Entwickler: TECHNISCHE_DOKUMENTATION.md,
„Rückwärtskompatibilität bei Updates“.

## 4. Sicherung und Wiederherstellung

Gesichert werden muss **nur die Datenbank**. Sie enthält alles: Apps, Einträge, Nutzer,
Versionen, Skripte. Das Image lässt sich jederzeit neu bauen; Geheimnisse liegen in der
Secret-Verwaltung.

### 4.1 Sichern

**Produktion** (betriebene PostgreSQL, z. B. täglich per CronJob der Datenbank-Plattform):

```
pg_dump --format=custom --file=baukasten-$(date +%F).dump "$DATABASE_URL"
```

Aufbewahren: mindestens 14 tägliche und 3 monatliche Sicherungen, außerhalb des Clusters.
Die Dateien enthalten personenbezogene Daten: verschlüsselt und mit beschränktem Zugriff
ablegen.

**Lokal** (Docker Desktop):

```
powershell -ExecutionPolicy Bypass -File k8s\lokal\sicherung.ps1
```

Das Skript legt die Sicherung unter `k8s\lokal\sicherungen\` ab und macht sofort eine
Probe (siehe 4.3).

### 4.2 Zurückspielen (überschreibt die Datenbank)

1. Alles anhalten, damit niemand schreibt:
   ```
   kubectl -n baukasten scale deploy/baukasten deploy/baukasten-worker --replicas=0
   ```
2. Sicherung einspielen:
   ```
   pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" baukasten-2026-11-17.dump
   ```
   Lokal liegt die Datenbank im Pod: Datei mit `kubectl cp` nach `/tmp/` im Pod
   `baukasten-db-…` kopieren und dort `pg_restore -U baukasten -d baukasten --clean --if-exists --no-owner /tmp/…dump`.
3. Migrationen nachziehen (falls die Sicherung älter als die Version ist):
   `kubectl -n baukasten apply -f k8s/migrate-job.yaml` (vorher alten Job löschen).
4. Wieder starten:
   ```
   kubectl -n baukasten scale deploy/baukasten --replicas=2
   kubectl -n baukasten scale deploy/baukasten-worker --replicas=1
   ```

**Nur eine App ist kaputt** (z. B. Seiten versehentlich gelöscht)? Dafür braucht es
keine Sicherung: Im Designer unter „Versionen“ den alten Stand wiederherstellen. Versionen
enthalten aber **keine Einträge**. Gelöschte Einträge kommen nur aus der Sicherung zurück:
Sicherung in eine Test-Datenbank einspielen (4.3) und die Einträge von dort über die API
oder `/admin/` zurückholen.

### 4.3 Wiederherstellung üben

`k8s\lokal\sicherung.ps1` spielt jede Sicherung in eine Test-Datenbank `baukasten_probe`
ein, vergleicht die Zeilen der wichtigsten Tabellen mit dem Original und löscht die
Test-Datenbank wieder. Das Original wird nur gelesen. Ausgabe bei Erfolg:

```
builder_app: Original 4, wiederhergestellt 4
…
Probe bestanden: Die Sicherung lässt sich vollständig wiederherstellen.
```

In der Produktion dasselbe vierteljährlich gegen eine Kopie: Sicherung in eine leere
Datenbank einspielen, Zeilen von `builder_app`, `builder_record` und `auth_user`
vergleichen, einmal einen Baukasten dagegen starten und anmelden.

_Zuletzt geübt: 2026-11-17, lokal, bestanden._

## 5. Überwachung und Alarme

**Health- & Readiness-Check:** `/healthz` antwortet `ok`, solange der Web-Prozess läuft;
`/readyz` prüft zusätzlich die Datenbankverbindung (Probes in `k8s/app.yaml`). Der Worker
hat eine eigene `livenessProbe` über eine Lebenszeichen-Datei.

**Direkte Fehler-Alarmierung (Teams, E-Mail oder API-Call):** Schlägt im Hintergrunddienst
(`baukasten-worker`) eine Automatisierung, ein zeitgesteuertes Skript oder ein
Datenquellen-Abgleich fehl, kann der Baukasten sofort selbst alarmieren (`builder/alerts.py`).
Einrichtbar ohne Neustart unter `/admin/` → **Einstellungen** oder über Umgebungsvariablen:

| Einstellung / Variable | Werte |
|---|---|
| `ALERT_CHANNEL` | `off` (Standard), `teams` (Microsoft-Teams-MessageCard-Webhook), `email` (komma-/semikolongetrennte Empfänger) oder `api` (HTTP-POST mit JSON-Payload `event: "baukasten.failure"`) |
| `ALERT_TARGET` | Teams-Webhook-URL, E-Mail-Adresse(n) oder API-Endpunkt-URL |
| `ALERT_AUTH_HEADER` | optionaler `Authorization`-Header für `ALERT_CHANNEL=api` (z. B. `Bearer <Token>`) |
| `ALERT_REPEAT_MINUTES` | derselbe Fehler (Quelle, Titel, App) höchstens einmal in dieser Zeit; Standard `60`, `0` = jedes Mal |

**Kennzahlen:** `METRICS_TOKEN` im Secret setzen, dann liefert `/metrics` Werte im Format
von Prometheus (Abruf mit `Authorization: Bearer <METRICS_TOKEN>`):

| Kennzahl | Bedeutung |
|---|---|
| `baukasten_info{version}` | eingespielte Version |
| `baukasten_worker_up` | 1, wenn der Hintergrunddienst in den letzten 120 s lebte |
| `baukasten_worker_heartbeat_age_seconds` | Sekunden seit dem letzten Lebenszeichen, -1 = keins |
| `baukasten_automation_running` | laufende Skripte von Automatisierungen |
| `baukasten_automation_stale_locks` | Läufe ohne Lebenszeichen |
| `baukasten_automation_waiting_requests` | angeforderte Starts, die seit über 60 s warten |
| `baukasten_automation_continuous_failing` | Dauerläufer, die nach Fehlern auf den Neustart warten |
| `baukasten_script_runs_failed_24h{kind}` | fehlgeschlagene Skriptläufe der letzten 24 Stunden |
| `baukasten_datasource_sync_failed` | Abfragen, deren letzter Abgleich fehlschlug |
| `baukasten_apps{kind}`, `baukasten_records` | Umfang |

`baukasten_worker_up` braucht einen gemeinsamen Cache (Redis oder Datenbank, Standard in
der Produktion). Mit `CACHE_BACKEND=memory` bleibt der Wert 0.

**Empfohlene Alarme** (Prometheus-Regeln, Schwellen nach Erfahrung anpassen):

```yaml
groups:
  - name: baukasten
    rules:
      - alert: BaukastenWorkerAusgefallen
        expr: max(baukasten_worker_up) == 0
        for: 5m
        annotations: {summary: "Hintergrunddienst ohne Lebenszeichen – Störfall 6.4"}
      - alert: BaukastenAutomatisierungenStauen
        expr: max(baukasten_automation_waiting_requests) > 0
        for: 10m
        annotations: {summary: "Starts warten seit über 10 Minuten – Störfall 6.4"}
      - alert: BaukastenVieleSkriptfehler
        expr: max(baukasten_script_runs_failed_24h) > 20
        annotations: {summary: "Viele fehlgeschlagene Skriptläufe – Störfall 6.5"}
      - alert: BaukastenAbgleichFehlgeschlagen
        expr: max(baukasten_datasource_sync_failed) > 0
        for: 30m
        annotations: {summary: "Abgleich mit einer Datenquelle schlägt fehl – Störfall 6.7"}
      - alert: BaukastenNichtErreichbar
        expr: probe_success{job="baukasten-healthz"} == 0   # Blackbox-Exporter auf /healthz
        for: 3m
```

Ohne Prometheus genügt für den Anfang ein externer Uptime-Check auf `/healthz` und ein Blick
auf die Profilseite (fehlgeschlagene Skripte der eigenen Apps).

## 6. Störfälle

Jeder Störfall: woran man ihn erkennt, wie man die Ursache findet, was hilft.

### 6.1 Die Seite zeigt „Fehler 500“

- **Ursache finden:** `kubectl -n baukasten logs deploy/baukasten --tail=100` zeigt den
  Python-Fehler mit Datei und Zeile.
- **Häufig:** Migration fehlt nach einem Update (`relation … does not exist`) →
  Migrations-Job laufen lassen (Abschnitt 3). Ein Baustein oder eine Erweiterung wirft einen
  Fehler → betroffene Seite im Designer prüfen bzw. die Erweiterung in `extensions/`.
- **Nur eine App betroffen:** Im Designer eine ältere Version wiederherstellen.

### 6.2 Pods starten nicht (CrashLoopBackOff, Pending)

- `kubectl -n baukasten get pods` und `kubectl -n baukasten describe pod <name>`, Abschnitt „Events“.
- `CreateContainerConfigError` → ein Secret oder Schlüssel fehlt (`baukasten-secret`).
- `ImagePullBackOff` → Image-Tag oder Registry-Zugang falsch.
- `Pending` → zu wenig CPU oder Speicher im Cluster (`kubectl describe` nennt den Grund).
- Startet und stirbt sofort → `kubectl logs <pod> --previous`; meist fehlt `SECRET_KEY`
  oder die Datenbank ist nicht erreichbar (6.3).

### 6.3 Datenbank nicht erreichbar oder voll

- Erkennbar an `OperationalError` / `could not connect` in den Logs aller Pods.
- Datenbank-Betrieb prüfen; lokal: `kubectl -n baukasten get pods -l app=baukasten-db`
  und `kubectl -n baukasten logs deploy/baukasten-db`.
- **Zu viele Verbindungen** (`too many clients`): Pods × `GUNICORN_WORKERS` ×
  `GUNICORN_THREADS` übersteigt `max_connections`. Workers/Threads senken oder
  `max_connections` erhöhen (Handbuch, „Skalierung und Last“).
- **Platte voll:** Speicher der Datenbank erweitern. Die Skriptläufe wachsen nicht
  unbegrenzt (je Skript bleiben die letzten 20 bzw. 30); Platz brauchen eher viele Einträge
  oder alte Sitzungen: `python manage.py clearsessions` im Web-Pod.

### 6.4 Automatisierungen starten nicht („startet gleich“ bleibt stehen)

- Läuft der Worker? `kubectl -n baukasten get pods -l app=baukasten-worker`
- Was macht er? `kubectl -n baukasten logs deploy/baukasten-worker --tail=50`;
  normal sind Zeilen „Start: …“ und „Ende: …“.
- Worker läuft, aber nichts startet: Alle Plätze belegt (`AUTOMATION_PARALLEL`, Standard 4)
  durch lange Läufe. Im Designer die Übersicht der Automatisierung ansehen, ggf. einen
  Lauf stoppen oder `AUTOMATION_PARALLEL` erhöhen (mehr Speicher einplanen).
- Worker neu starten ist gefahrlos: `kubectl -n baukasten rollout restart deploy/baukasten-worker`.
  Laufende Skripte werden als „abgebrochen“ vermerkt, Dauerläufer starten von selbst wieder.

### 6.5 Eine Automatisierung hängt oder scheitert immer wieder

- Im Designer das Skript öffnen: Live-Protokoll und „Letzte Läufe“ zeigen Ausgabe und Fehler
  mit Zeile.
- „Zeitlimit überschritten“ → Zeitlimit des Skripts erhöhen (höchstens
  `AUTOMATION_MAX_TIMEOUT_MINUTES`) oder die Arbeit aufteilen.
- „abgebrochen (… Speichergrenze …)“ → `AUTOMATION_MEMORY_MB` erhöhen oder weniger Daten auf
  einmal laden.
- „Das Geheimnis … ist nicht eingerichtet“ → Eintrag `SCRIPT_SECRET_<NAME>` im Secret
  `baukasten-skript-geheimnisse` ergänzen, Worker neu starten.
- „Stoppen“ hilft nicht: Der Worker beendet den Prozess spätestens nach 10 Sekunden hart.
  Bleibt der Zustand „läuft“, gibt der Worker die Sperre nach 90 Sekunden ohne Lebenszeichen
  frei; notfalls Worker neu starten (6.4).
- Dauerläufer startet ständig neu → nach Fehlern wartet er 10 s bis 10 min. Im Designer
  ausschalten, Fehler beheben, wieder einschalten.

### 6.6 Worker wird beendet (OOMKilled)

- `kubectl -n baukasten describe pod -l app=baukasten-worker` zeigt `OOMKilled`.
- Die Läufe brauchen zusammen mehr als das Limit des Pods (4 GiB). Rechnung:
  `AUTOMATION_PARALLEL` × `AUTOMATION_MEMORY_MB` + Dauerläufer + ca. 300 MB.
  Limit in `k8s/worker.yaml` erhöhen oder `AUTOMATION_PARALLEL` senken.

### 6.7 Abfragen sind langsam oder melden „ausgelastet“

- „ausgelastet“ heißt: Mehr als `QUERY_PARALLEL` Abfragen an dieselbe Quelle gleichzeitig.
  Das schützt die Datenquelle. Abhilfe: `cache_seconds` der Abfrage erhöhen, Daten
  spiegeln statt live abfragen, oder für diese Quelle `QUERY_PARALLEL_<NAME>` erhöhen.
- Abgleich schlägt fehl: Im Designer unter „Datenquellen“ steht die Meldung beim letzten
  Abgleich. Häufig: Passwort der Quelle abgelaufen (`DATASOURCE_<NAME>` im Secret erneuern,
  Pods neu starten) oder Databricks-Warehouse schläft (wacht nach der ersten Abfrage auf).

### 6.8 Anmeldung über Keycloak geht nicht

- Fehler nach der Rückkehr von Keycloak: `OIDC_CLIENT_SECRET` falsch oder die
  Weiterleitungs-Adresse `https://<host>/oidc/callback/` fehlt im Keycloak-Client.
- Angemeldet, aber kein Designer: Die Rolle `OIDC_DESIGNER_ROLE` (Standard
  `baukasten-designer`) fehlt der Person in Keycloak. Gruppen werden bei jeder Anmeldung
  abgeglichen.
- Keycloak ganz weg: Verwalter melden sich lokal an, sofern `OIDC_ONLY` nicht gesetzt ist.

### 6.9 Verwalter-Passwort vergessen, niemand kommt mehr hinein

```
kubectl -n baukasten exec -it deploy/baukasten -- python manage.py changepassword admin
kubectl -n baukasten exec -it deploy/baukasten -- python manage.py createsuperuser
```

### 6.10 Ein Skript oder eine KI hat Daten kaputt gemacht

- Was genau passiert ist, wer und womit: Designer der App → „Änderungsprotokoll“, mit dem
  alten Wert jedes geänderten Feldes. Gelöschte Einträge stehen dort mit ihren Werten und
  lassen sich daraus von Hand wiederherstellen.
- Aufbau der App (Tabellen, Seiten, Skripte): im Designer unter „Versionen“ zurück. Jede
  Änderung über einen KI-Zugang hat vorher automatisch eine Version angelegt.
- Einträge: nur aus der Sicherung (4.2, Abschnitt „Nur eine App ist kaputt“).
- Ursache abstellen: Skript ausschalten bzw. den KI-Zugang auf der Profilseite löschen.
  Ein verdächtiger API-Schlüssel wird im Designer der App gelöscht.

### 6.11 Verdacht auf Missbrauch (Sicherheitsvorfall)

1. Betroffene Zugänge sofort löschen: API-Schlüssel (Designer der App), KI-Zugänge
   (Profilseite oder `/admin/` → KI-Zugänge zum Designer), Konten deaktivieren.
2. Bei Automatisierungen: Skripte ausschalten, Geheimnisse im Secret
   `baukasten-skript-geheimnisse` an der Quelle (ERP, SFTP …) erneuern.
3. `SECRET_KEY` erneuern meldet alle Personen ab.
4. Spuren sichern: `/admin/` → Änderungsprotokoll (filtern nach Weg „API“, „KI-Zugang“ bzw.
   nach dem Schlüssel), als CSV aus dem Designer herunterladen; dazu `kubectl logs` aller Pods,
   „Letzte Läufe“ der betroffenen Skripte, Versionen der betroffenen Apps. Bei Bedarf
   `AUDIT_RETENTION_DAYS` vorübergehend hochsetzen, damit nichts automatisch gelöscht wird.

### 6.12 Lokal: Docker Desktop startet ständig neu

Meist ist der WSL-VM der Speicher zu knapp oder zu großzügig bemessen. In
`%USERPROFILE%\.wslconfig` `memory=` so wählen, dass Windows genug übrig bleibt
(z. B. 6 GB bei 16 GB RAM), danach `wsl --shutdown` und Docker Desktop neu starten.

## 7. Erste Diagnose in fünf Befehlen

```
kubectl -n baukasten get pods                                   # läuft alles? Neustarts?
kubectl -n baukasten get events --sort-by=.lastTimestamp | tail -20
kubectl -n baukasten logs deploy/baukasten --tail=50            # Web
kubectl -n baukasten logs deploy/baukasten-worker --tail=50     # Hintergrunddienst
kubectl -n baukasten top pods                                   # CPU und Speicher (mit metrics-server)
```

Notfallkontakte und Zugänge (Registry, Datenbank, Keycloak, Secret-Verwaltung) gehören
nicht in dieses Repository, sondern in die Dokumentation des Betriebsteams. Dort auf
dieses Handbuch verweisen.
