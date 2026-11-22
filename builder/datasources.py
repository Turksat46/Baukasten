"""Externe Datenquellen: Datenbanken und Databricks, nur lesend.

Verbindungen richtet der Betrieb über Umgebungsvariablen ein, nicht der
Designer. So liegen Zugangsdaten nur in Kubernetes-Secrets und Designer können
nur die Quellen nutzen, die freigegeben sind:

    DATASOURCE_LAGER=postgresql://leser:geheim@db.example.com:5432/lager
    DATASOURCE_DWH=databricks://token:dapi…@adb-123.azuredatabricks.net/sql/1.0/warehouses/abc?catalog=main&schema=werk
    DATASOURCE_ALT=mssql://leser:geheim@sql.example.com:1433/alt?driver=ODBC+Driver+18+for+SQL+Server
    DATASOURCE_SHOP=mysql://leser:geheim@mysql.example.com:3306/shop
    DATASOURCE_TEST=sqlite:////pfad/zur/datei.sqlite3

Der Name nach DATASOURCE_ wird in Kleinbuchstaben zum Namen der Quelle
(„lager“, „dwh“ …). Abfragen müssen mit SELECT oder WITH beginnen und dürfen
nichts verändern. Die eigentliche Sicherheit ist ein Datenbank-Benutzer, der
nur lesen darf: Bitte immer so einrichten.

Unter Last (viele Apps, viele Nutzer, langsames Databricks) schützen drei Dinge
den Rest des Baukastens:

1. Zwischenspeicher: Ergebnisse gespeicherter Abfragen liegen im gemeinsamen
   Cache aller Pods. Läuft eine Abfrage gerade, warten weitere Anfragen auf
   deren Ergebnis, statt dieselbe Abfrage noch einmal zu schicken. Schlägt eine
   Aktualisierung fehl, wird der letzte Stand gezeigt.
2. Limit je Datenquelle: höchstens QUERY_PARALLEL Abfragen gleichzeitig, im
   ganzen Cluster. Wer keinen Platz bekommt, erhält nach kurzer Wartezeit
   „ausgelastet“ statt einen Worker minutenlang zu blockieren.
3. Kurze Zeitlimits für Seiten (QUERY_TIMEOUT), lange nur im Hintergrund
   beim Spiegeln (SYNC_TIMEOUT).
"""
import contextlib
import secrets
import hashlib
import json
import re
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

LIVE_LIMIT = 2000
SYNC_LIMIT = 50000
STALE_SECONDS = 24 * 3600   # so lange bleibt der letzte Stand als Ersatz bei Fehlern
KINDS = {
    "sqlite": "SQLite", "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "mysql": "MySQL",
    "mssql": "SQL Server", "databricks": "Databricks",
}
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|"
    r"call|exec|execute|copy|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)


class QueryError(Exception):
    pass


class QueryBusy(QueryError):
    """Die Datenquelle ist gerade ausgelastet oder die Abfrage läuft schon; gleich noch einmal versuchen."""


def live_timeout():
    return int(getattr(settings, "BAUKASTEN_QUERY_TIMEOUT", 25))


def sync_timeout():
    return int(getattr(settings, "BAUKASTEN_SYNC_TIMEOUT", 300))


def parallel_limit(source):
    by_source = getattr(settings, "BAUKASTEN_QUERY_PARALLEL_BY_SOURCE", {}) or {}
    return max(int(by_source.get(str(source), getattr(settings, "BAUKASTEN_QUERY_PARALLEL", 4))), 1)


def wait_seconds(wait=None):
    return float(getattr(settings, "BAUKASTEN_QUERY_WAIT", 2)) if wait is None else float(wait)


@contextlib.contextmanager
def slot(source, hold_seconds, wait=None):
    """Belegt einen von parallel_limit(source) Plätzen, gemeinsam über den Cache für alle Pods.

    Ein Platz verfällt nach hold_seconds von selbst, falls ein Pod mitten in der Abfrage stirbt.
    """
    token = secrets.token_hex(8)
    limit = parallel_limit(source)
    deadline = time.monotonic() + wait_seconds(wait)
    key = None
    while key is None:
        for i in range(limit):
            candidate = f"baukasten-slot-{source}-{i}"
            if cache.add(candidate, token, timeout=hold_seconds):
                key = candidate
                break
        if key is None:
            if time.monotonic() >= deadline:
                raise QueryBusy(_("Die Datenquelle „%(name)s“ ist gerade ausgelastet. Bitte gleich noch einmal versuchen.")
                                % {"name": source})
            time.sleep(0.2)
    try:
        yield
    finally:
        if cache.get(key) == token:
            cache.delete(key)


def sources():
    """Eingerichtete Quellen: Name -> Adresse (ohne Zugangsdaten nach außen geben!)."""
    return dict(getattr(settings, "BAUKASTEN_DATASOURCES", {}))


def describe_sources():
    return [{"name": name, "kind": KINDS.get(urlparse(url).scheme, urlparse(url).scheme)}
            for name, url in sorted(sources().items())]


# ---------- SQL prüfen und Parameter umsetzen ----------

def _tokens(sql):
    """Zerlegt SQL in (art, text): Zeichenketten, Kommentare, Parameter (:name) und übrigen Text."""
    i, n = 0, len(sql)
    plain = []
    while i < n:
        ch = sql[i]
        if ch in "'\"`":
            if plain:
                yield "sql", "".join(plain)
                plain = []
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # verdoppeltes Anführungszeichen
                        j += 2
                        continue
                    break
                j += 1
            yield "string", sql[i:j + 1]
            i = j + 1
        elif sql.startswith("--", i):
            if plain:
                yield "sql", "".join(plain)
                plain = []
            j = sql.find("\n", i)
            j = n if j == -1 else j
            yield "comment", sql[i:j]
            i = j
        elif sql.startswith("/*", i):
            if plain:
                yield "sql", "".join(plain)
                plain = []
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            yield "comment", sql[i:j]
            i = j
        elif ch == ":" and sql.startswith("::", i):
            plain.append("::")
            i += 2
        elif ch == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
            if plain:
                yield "sql", "".join(plain)
                plain = []
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            yield "param", sql[i + 1:j]
            i = j
        else:
            plain.append(ch)
            i += 1
    if plain:
        yield "sql", "".join(plain)


def check_read_only(sql):
    """Lässt nur eine einzelne lesende Abfrage zu. Ersetzt keinen Nur-Lese-Benutzer in der Datenbank."""
    code = "".join(text if kind == "sql" else " ? " if kind == "param" else " ''" if kind == "string" else " "
                   for kind, text in _tokens(sql)).strip()
    code = code.rstrip(";").strip()
    if not code:
        raise QueryError(_("Die Abfrage ist leer."))
    if ";" in code:
        raise QueryError(_("Bitte nur eine einzelne Abfrage eintragen (kein Semikolon dazwischen)."))
    if not re.match(r"^\(?\s*(select|with)\b", code, re.IGNORECASE):
        raise QueryError(_("Erlaubt sind nur lesende Abfragen, die mit SELECT oder WITH beginnen."))
    found = FORBIDDEN.search(code)
    if found:
        raise QueryError(_("Das Wort „%(word)s“ ist in Abfragen nicht erlaubt, weil es Daten verändern könnte.")
                         % {"word": found.group(0).upper()})


def param_names(sql):
    """Namen der :name-Parameter einer Abfrage (ohne Treffer in Zeichenketten und Kommentaren)."""
    return {text for kind, text in _tokens(sql or "") if kind == "param"}


def convert_params(sql, params, paramstyle):
    """Setzt :name-Parameter in die Schreibweise des Treibers um."""
    params = params or {}
    if paramstyle == "named":
        missing = {text for kind, text in _tokens(sql) if kind == "param"} - set(params)
        if missing:
            raise QueryError(_("Für diese Parameter fehlt ein Wert: %(names)s") % {"names": ", ".join(sorted(missing))})
        return sql.rstrip().rstrip(";"), params
    out, values = [], []
    for kind, text in _tokens(sql):
        if kind == "param":
            if text not in params:
                raise QueryError(_("Für diese Parameter fehlt ein Wert: %(names)s") % {"names": text})
            if paramstyle == "qmark":
                out.append("?")
                values.append(params[text])
            else:  # pyformat
                out.append(f"%({text})s")
        elif kind == "sql" and paramstyle == "pyformat" and params:
            out.append(text.replace("%", "%%"))
        else:
            out.append(text)
    converted = "".join(out).rstrip().rstrip(";")
    if paramstyle == "qmark":
        return converted, values
    return converted, (params or None)


# ---------- Verbindungen ----------

def _connect(url, timeout):
    """Öffnet eine Verbindung mit Zeitlimit timeout (Sekunden). Gibt (Verbindung, paramstyle) zurück."""
    parsed = urlparse(url)
    scheme = parsed.scheme
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    if scheme == "sqlite":
        from pathlib import Path

        path = unquote(url.split("sqlite:///", 1)[1]) if "sqlite:///" in url else ""
        default_db = settings.DATABASES.get("default", {}).get("NAME")
        if path and default_db:
            try:
                if Path(path).resolve() == Path(str(default_db)).resolve():
                    raise QueryError(_("Die interne Datenbank des Baukastens darf nicht als Datenquelle abgefragt werden."))
            except OSError:
                pass
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        return conn, "qmark"
    if scheme in ("postgresql", "postgres"):
        import psycopg

        conn = psycopg.connect(url.replace("postgres://", "postgresql://", 1), connect_timeout=10,
                               options=f"-c statement_timeout={int(timeout * 1000)}")
        conn.read_only = True
        return conn, "pyformat"
    if scheme == "mysql":
        try:
            import pymysql
        except ImportError as exc:
            raise QueryError(_("Für MySQL fehlt das Paket „pymysql“ (pip install pymysql).")) from exc
        conn = pymysql.connect(host=parsed.hostname, port=parsed.port or 3306, user=unquote(parsed.username or ""),
                               password=unquote(parsed.password or ""), database=parsed.path.lstrip("/"),
                               connect_timeout=10, read_timeout=timeout)
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
        return conn, "pyformat"
    if scheme == "mssql":
        try:
            import pyodbc
        except ImportError as exc:
            raise QueryError(_("Für SQL Server fehlt das Paket „pyodbc“ samt ODBC-Treiber.")) from exc
        driver = query.get("driver", "ODBC Driver 18 for SQL Server")
        conn = pyodbc.connect(
            f"DRIVER={{{driver}}};SERVER={parsed.hostname},{parsed.port or 1433};DATABASE={parsed.path.lstrip('/')};"
            f"UID={unquote(parsed.username or '')};PWD={unquote(parsed.password or '')};"
            f"Encrypt={query.get('encrypt', 'yes')};TrustServerCertificate={query.get('trust', 'no')};"
            "ApplicationIntent=ReadOnly", timeout=10)
        conn.timeout = int(timeout)
        return conn, "qmark"
    if scheme == "databricks":
        try:
            from databricks import sql as databricks_sql
        except ImportError as exc:
            raise QueryError(_("Für Databricks fehlt das Paket „databricks-sql-connector“.")) from exc
        conn = databricks_sql.connect(
            server_hostname=parsed.hostname, http_path=parsed.path,
            access_token=unquote(parsed.password or ""),
            catalog=query.get("catalog") or None, schema=query.get("schema") or None,
            # Ein schlafendes SQL-Warehouse braucht zum Starten oft einige Minuten. Seiten warten
            # höchstens QUERY_TIMEOUT; wer länger braucht, gehört gespiegelt (SYNC_TIMEOUT).
            # &timeout= in der Adresse begrenzt zusätzlich.
            _socket_timeout=int(min(timeout, float(query.get("timeout", timeout)))),
            _retry_stop_after_attempts_duration=float(min(timeout, float(query.get("timeout", timeout)))),
        )
        return conn, "named"
    raise QueryError(_("Unbekannte Art von Datenquelle: %(kind)s") % {"kind": scheme})


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _clean_message(exc, url):
    """Erste Zeile der Fehlermeldung, ohne Passwort oder Token aus der Adresse."""
    message = str(exc).splitlines()[0][:300] if str(exc).strip() else type(exc).__name__
    secret = urlparse(url).password
    for variant in {secret, unquote(secret or "")} - {None, ""}:
        message = message.replace(variant, "***")
    return message


def run(source, sql, params=None, limit=LIVE_LIMIT, timeout=None, wait=None):
    """Führt eine lesende Abfrage aus. Gibt {"columns", "rows", "truncated"} zurück.

    timeout: Sekunden, Standard QUERY_TIMEOUT. Belegt für die Dauer einen Platz der Datenquelle.
    wait: so lange auf einen freien Platz warten (Standard QUERY_WAIT); 0 = sofort QueryBusy.
    """
    url = sources().get(str(source))
    if not url:
        raise QueryError(_("Die Datenquelle „%(name)s“ ist nicht eingerichtet.") % {"name": source})
    check_read_only(sql)
    limit = min(max(int(limit or LIVE_LIMIT), 1), SYNC_LIMIT)
    timeout = timeout or live_timeout()
    with slot(source, hold_seconds=int(timeout) + 30, wait=wait):
        return _run(url, sql, params, limit, timeout)


def _run(url, sql, params, limit, timeout):
    try:
        conn, paramstyle = _connect(url, timeout)
    except QueryError:
        raise
    except Exception as exc:  # Verbindungsfehler: Host, Zugang, Netzwerk
        raise QueryError(_("Keine Verbindung zur Datenquelle: %(message)s")
                         % {"message": _clean_message(exc, url)}) from exc
    try:
        statement, values = convert_params(sql, params, paramstyle)
        cur = conn.cursor()
        try:
            if values:
                cur.execute(statement, values)
            else:
                cur.execute(statement)
            columns = [d[0] for d in (cur.description or [])]
            raw = cur.fetchmany(limit + 1)
        finally:
            cur.close()
    except QueryError:
        raise
    except Exception as exc:  # Treiberfehler verständlich weitergeben, ohne Zugangsdaten
        raise QueryError(_("Die Datenbank meldet: %(message)s") % {"message": _clean_message(exc, url)}) from exc
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    rows = [{col: _value(val) for col, val in zip(columns, row)} for row in raw[:limit]]
    return {"columns": columns, "rows": rows, "truncated": len(raw) > limit}


def query_cache_key(query, params=None):
    """Ändert sich, sobald SQL oder Quelle geändert werden: alte Ergebnisse gelten dann nicht mehr."""
    return "baukasten-query-" + hashlib.sha256(
        json.dumps([query.pk, query.source, query.sql, params or {}], sort_keys=True, default=str).encode()
    ).hexdigest()


def run_saved(query, params=None, wait=None):
    """Ergebnis einer im Designer angelegten Abfrage.

    - frisch aus dem Cache, solange query.cache_seconds nicht abgelaufen sind;
    - läuft dieselbe Abfrage gerade (in irgendeinem Pod), wird auf ihr Ergebnis gewartet
      bzw. der letzte Stand gezeigt, statt sie ein zweites Mal zu schicken;
    - schlägt eine Aktualisierung fehl, kommt der letzte Stand mit "stale": True zurück.

    wait=0 für Aufrufer, die selbst später nachfragen (nachladende Bausteine): dann blockiert
    kein Thread, sondern es kommt sofort QueryBusy.
    """
    key = query_cache_key(query, params)
    fresh_seconds = int(query.cache_seconds or 0)
    if fresh_seconds:
        cached = cache.get(key)
        if cached is not None:
            return cached
    last = cache.get(key + "-last")
    timeout = live_timeout()
    lock = key + "-lock"
    if not cache.add(lock, 1, timeout=timeout + 30):
        # Läuft gerade woanders: den letzten Stand zeigen oder kurz auf das Ergebnis warten.
        if last is not None:
            return last
        # Nur kurz warten: Ein wartender Thread fehlt allen anderen Seiten. Danach meldet der
        # Baukasten „wird geladen“, und der Browser fragt selbst in ein paar Sekunden wieder.
        deadline = time.monotonic() + wait_seconds(wait)
        while time.monotonic() < deadline:
            time.sleep(0.25)
            done = cache.get(key + "-last")
            if done is not None:
                return done
            if cache.get(lock) is None:
                break
        raise QueryBusy(_("Die Abfrage „%(name)s“ wird gerade geladen. Bitte gleich noch einmal versuchen.")
                        % {"name": query.name})
    try:
        result = run(query.source, query.sql, params, timeout=timeout, wait=wait)
    except QueryError:
        if last is not None:
            return dict(last, stale=True)
        raise
    finally:
        cache.delete(lock)
    result["fetched_at"] = timezone.now().isoformat()
    if fresh_seconds:
        cache.set(key, result, fresh_seconds)
    cache.set(key + "-last", result, max(STALE_SECONDS, fresh_seconds))
    return result


# ---------- In eine Tabelle spiegeln ----------

def _field_type(values):
    from .models import Field

    sample = [v for v in values if v is not None][:200]
    if not sample:
        return Field.TEXT
    if all(isinstance(v, bool) for v in sample):
        return Field.BOOL
    if all(isinstance(v, int) and not isinstance(v, bool) for v in sample):
        return Field.NUMBER
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sample):
        return Field.DECIMAL
    if all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in sample):
        return Field.DATE
    if all(isinstance(v, str) and len(v) <= 500 for v in sample):
        return Field.TEXT
    return Field.LONGTEXT


def column_key(column):
    return slugify(str(column)).replace("-", "_")[:50] or "spalte"


@transaction.atomic
def sync(query):
    """Spiegelt das Ergebnis in eine Tabelle der App. Gibt die Anzahl der Zeilen zurück."""
    from .models import Entity, Field, Record

    result = run(query.source, query.sql, limit=SYNC_LIMIT, timeout=sync_timeout())
    if result["truncated"]:
        raise QueryError(_("Die Abfrage liefert mehr als %(limit)s Zeilen. Bitte im SQL eingrenzen.")
                         % {"limit": SYNC_LIMIT})
    entity = query.sync_entity
    if entity is None:
        # Gespiegelte Tabellen sind zum Lesen gedacht: Änderungen würden beim nächsten Abgleich überschrieben.
        entity = Entity.objects.create(app=query.app, name=query.name,
                                       allow_create=False, allow_edit=False, allow_delete=False)
        query.sync_entity = entity
        query.save(update_fields=["sync_entity"])
    keys, used = {}, set()
    for column in result["columns"]:
        key, n = column_key(column), 2
        while key in used:
            key, n = f"{column_key(column)}_{n}", n + 1
        keys[column] = key
        used.add(key)
    existing = {f.key for f in entity.fields.all()}
    for column, key in keys.items():
        if key not in existing:
            Field.objects.create(entity=entity, label=str(column)[:80], key=key,
                                 type=_field_type([row[column] for row in result["rows"]]))
            existing.add(key)
    rows = [{keys[c]: v for c, v in row.items()} for row in result["rows"]]

    key_field = column_key(query.key_column) if query.key_column else ""
    if key_field and key_field not in keys.values():
        raise QueryError(_("Die Schlüsselspalte „%(name)s“ kommt in der Abfrage nicht vor.") % {"name": query.key_column})
    from . import audit

    with audit.quiet():
        counts = _sync_rows(entity, rows, key_field)
    audit.log("sync", "entity", app=query.app, target_id=entity.pk, label=entity.name, scope=entity.slug,
              note=f"Abfrage „{query.name}“: {counts[0]} neu, {counts[1]} geändert, {counts[2]} entfernt")
    return len(rows)


def _sync_rows(entity, rows, key_field):
    """Gibt (neu, geändert, entfernt) zurück."""
    from .models import Record

    if not key_field:
        removed, _detail = entity.records.all().delete()
        Record.objects.bulk_create([Record(entity=entity, data=row) for row in rows], batch_size=1000)
        return len(rows), 0, removed
    else:
        current = {}
        for record in entity.records.all():
            current.setdefault(json.dumps(record.data.get(key_field), default=str), record)
        seen, changed, new = set(), [], []
        for row in rows:
            marker = json.dumps(row.get(key_field), default=str)
            if marker in seen:
                continue
            seen.add(marker)
            record = current.get(marker)
            if record is None:
                new.append(Record(entity=entity, data=row))
            elif record.data != row:
                record.data = row
                record.updated_at = timezone.now()
                changed.append(record)
        Record.objects.bulk_create(new, batch_size=1000)
        Record.objects.bulk_update(changed, ["data", "updated_at"], batch_size=1000)
        stale = [r.pk for marker, r in current.items() if marker not in seen]
        Record.objects.filter(pk__in=stale).delete()
        return len(new), len(changed), len(stale)


def sync_and_record(query):
    """Abgleich mit Protokoll am Objekt; Fehler werden vermerkt, nicht geworfen."""
    try:
        count = sync(query)
        query.last_sync_ok = True
        query.last_sync_message = _("%(count)s Zeilen übernommen.") % {"count": count}
    except QueryError as exc:
        query.last_sync_ok = False
        query.last_sync_message = str(exc)[:500]
    query.last_sync_at = timezone.now()
    query.save(update_fields=["last_sync_at", "last_sync_ok", "last_sync_message"])
    return query.last_sync_ok
