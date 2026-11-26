#!/usr/bin/env bash
# Rollt auf dem Pi Zero den neuesten Stand von GitHub aus (ohne Kubernetes/Docker).
# Läuft per systemd-Timer alle drei Minuten (eingerichtet von einrichten.sh) und tut nichts,
# solange sich nichts geändert hat.
#
# Ablauf bei einem neuen Commit auf BRANCH (Standard: main):
#   1. Auf GitHub nachsehen, ob der Workflow „Tests“ für diesen Commit grün ist
#      (läuft er noch: später wieder; rot: diesen Commit überspringen)
#   2. Datenbank sichern, Code auschecken, Pakete (nur wenn geändert), statische Dateien, Migration
#   3. Dienste neu starten und warten, bis /readyz antwortet
#   4. Kommt die neue Version nicht hoch: alter Code und Datenbank-Stand von vorher zurück
#
# Von Hand anstoßen:          sudo systemctl start baukasten-aktualisieren
# Zuschauen:                  journalctl -fu baukasten-aktualisieren
# Erneut versuchen erzwingen: sudo ERZWINGEN=1 /opt/baukasten/app/pi-zero/aktualisieren.sh
set -euo pipefail

KONF=/etc/baukasten
ZUSTAND=/var/lib/baukasten
APP=/opt/baukasten/app
VENV=/opt/baukasten/venv
DB="$ZUSTAND/baukasten.sqlite3"

# shellcheck source=/dev/null
source "$KONF/pi.env"
BRANCH="${BRANCH:-main}"
TESTS_ABWARTEN="${TESTS_ABWARTEN:-ja}"
BEISPIELE="${BEISPIELE:-nein}"
DOMAIN="${DOMAIN:-}"
# Mit DOMAIN steht Caddy (HTTPS) davor und gunicorn lauscht nur intern auf 8000 (siehe einrichten.sh).
if [ -n "$DOMAIN" ]; then PORT=8000; else PORT=80; fi
: "${REPO_SLUG:?REPO_SLUG fehlt in $KONF/pi.env}"

exec 9>"$ZUSTAND/lauf.lock"
flock -n 9 || { echo "Läuft schon."; exit 0; }
# Von einrichten.sh beim ersten Mal gesetzt: den geklonten Stand ohne Warten auf GitHub installieren.
if [ -f "$ZUSTAND/erzwingen" ]; then ERZWINGEN=1; rm -f "$ZUSTAND/erzwingen"; fi

# manage.py mit denselben Umgebungsvariablen wie die Dienste ausführen.
manage() {
    local nutzer="$1"; shift
    runuser -u "$nutzer" -- bash -c 'set -a; . /etc/baukasten/baukasten.env; [ -f /etc/baukasten/https.env ] && . /etc/baukasten/https.env; . /var/lib/baukasten/netz.env; set +a
        cd /opt/baukasten/app && exec /opt/baukasten/venv/bin/python manage.py "$@"' _ "$@"
}

pakete_installieren() {
    local stand tmp
    stand=$(cat "$APP/requirements.in" "$APP/requirements-automation.in" "$APP/requirements.txt" | sha256sum | cut -c1-16)
    [ "$(cat "$ZUSTAND/pakete" 2>/dev/null)" = "$stand" ] && return 0
    echo "==> Python-Pakete installieren (dauert auf dem Pi Zero eine Weile)"
    tmp=$(mktemp -d)
    # Ohne Databricks (zieht pandas/numpy/pyarrow nach, gibt es für ARMv6 nicht fertig) und ohne
    # PostgreSQL-Treiber (der Pi nimmt SQLite). cryptography kommt aus Debian (python3-cryptography).
    grep -hvE '^\s*(#|$)' "$APP/requirements.in" "$APP/requirements-automation.in" \
        | grep -viE '^(databricks|psycopg)' >"$tmp/pakete.txt"
    # Dieselben Versionen wie im getesteten Image, soweit vorhanden.
    grep -oE '^[A-Za-z0-9_.-]+==[^ ;\\]+' "$APP/requirements.txt" \
        | grep -viE '^(cryptography|cffi|pycparser)==' >"$tmp/versionen.txt"
    if ! "$VENV/bin/pip" install --quiet --disable-pip-version-check --prefer-binary \
        -r "$tmp/pakete.txt" -c "$tmp/versionen.txt"; then
        rm -rf "$tmp"
        return 1
    fi
    rm -rf "$tmp"
    echo "$stand" >"$ZUSTAND/pakete"
}

db_sichern() {  # $1: Zieldatei
    [ -f "$DB" ] || return 0
    python3 -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' "$DB" "$1"
}

# Läuft als Bedingung („if ausrollen“), dort greift set -e nicht: jeden Schritt selbst prüfen.
ausrollen() {
    pakete_installieren || { echo "FEHLER: Python-Pakete" >&2; return 1; }
    echo "==> Statische Dateien"
    manage root collectstatic --noinput >/dev/null || { echo "FEHLER: collectstatic" >&2; return 1; }
    echo "==> Datenbank migrieren"
    manage baukasten migrate --noinput || { echo "FEHLER: Migration" >&2; return 1; }
    manage baukasten createcachetable || { echo "FEHLER: Cache-Tabelle" >&2; return 1; }
    echo "==> Dienste neu starten"
    systemctl restart baukasten-web baukasten-worker || { echo "FEHLER: Neustart der Dienste" >&2; return 1; }
    echo "==> Warte auf den Start (auf dem Pi Zero bis zu ein paar Minuten)"
    for _ in $(seq 1 60); do
        curl -fsS -o /dev/null "http://127.0.0.1:$PORT/readyz" 2>/dev/null && return 0
        sleep 5
    done
    return 1
}

# ---- Adressen, unter denen der Pi erreichbar ist (DHCP kann die IP ändern) ----
NAME=$(hostname)
IPS4=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | paste -sd, - || true)
# IPv6-Adressen in eckigen Klammern (so steht der Host im Browser: http://[2003:…]/)
IPS6=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep ':' | sed 's/.*/[&]/' | paste -sd, - || true)
IPS="$IPS4${IPS6:+${IPS4:+,}$IPS6}"
NETZ="ALLOWED_HOSTS=${DOMAIN:+$DOMAIN,}localhost,127.0.0.1,$NAME,$NAME.local${IPS:+,$IPS}${EXTRA_HOSTS:+,$EXTRA_HOSTS}"
if [ "$(cat "$ZUSTAND/netz.env" 2>/dev/null)" != "$NETZ" ]; then
    echo "$NETZ" >"$ZUSTAND/netz.env"
    if [ -f "$ZUSTAND/ausgerollt" ]; then
        echo "==> Adresse geändert, Dienste neu starten"
        systemctl restart baukasten-web baukasten-worker
    fi
fi

# ---- 1. Neuen Stand holen und prüfen ----
cd "$APP"
git fetch --quiet origin "$BRANCH"
ZIEL=$(git rev-parse FETCH_HEAD)
KURZ=${ZIEL:0:7}

if [ -z "${ERZWINGEN:-}" ]; then
    [ "$(cat "$ZUSTAND/ausgerollt" 2>/dev/null)" = "$ZIEL" ] && exit 0
    [ "$(cat "$ZUSTAND/uebersprungen" 2>/dev/null)" = "$ZIEL" ] && exit 0
fi

if [ "$TESTS_ABWARTEN" = "ja" ] && [ -z "${ERZWINGEN:-}" ]; then
    ERGEBNIS=$(python3 - "$REPO_SLUG" "$ZIEL" "${GITHUB_TOKEN:-}" <<'EOF'
import json, sys, urllib.request
slug, sha, token = sys.argv[1:4]
req = urllib.request.Request(f"https://api.github.com/repos/{slug}/actions/runs?head_sha={sha}&event=push&per_page=50",
                             headers={"Accept": "application/vnd.github+json", "User-Agent": "baukasten-pi"})
if token:
    req.add_header("Authorization", f"Bearer {token}")
try:
    runs = json.load(urllib.request.urlopen(req, timeout=20))["workflow_runs"]
except Exception as exc:
    print(f"fehler {exc}")
    sys.exit()
tests = [r for r in runs if r["name"] == "Tests"]
if not tests:
    print("ausstehend")
elif tests[0]["status"] != "completed":
    print("ausstehend")
else:
    print(tests[0]["conclusion"])
EOF
)
    case "$ERGEBNIS" in
        success) ;;
        ausstehend) echo "Commit $KURZ: Tests laufen noch auf GitHub, später wieder."; exit 0 ;;
        fehler*) echo "GitHub nicht erreichbar (${ERGEBNIS#fehler }), später wieder."; exit 0 ;;
        *) echo "Commit $KURZ: Tests sind '$ERGEBNIS' – wird übersprungen, die bisherige Version läuft weiter."
           echo "$ZIEL" >"$ZUSTAND/uebersprungen"; exit 0 ;;
    esac
fi

# ---- 2./3. Ausrollen ----
VORHER=$(cat "$ZUSTAND/ausgerollt" 2>/dev/null || true)
echo "==> Rolle $KURZ aus${VORHER:+ (bisher ${VORHER:0:7})}"
db_sichern "$ZUSTAND/vor-update.sqlite3"
git checkout --quiet --force --detach "$ZIEL"

if ausrollen; then
    if [ ! -f "$ZUSTAND/eingerichtet" ]; then
        echo "==> Erstes Einrichten: Verwalter-Konto (Beispiel-Apps: $BEISPIELE)"
        ARGS=()
        [ "$BEISPIELE" = "ja" ] || ARGS+=(--ohne-beispiele)
        manage baukasten lokal_einrichten "${ARGS[@]}" \
            || echo "WARNUNG: Einrichten unvollständig – von Hand wiederholen, siehe LIESMICH.md."
        touch "$ZUSTAND/eingerichtet"
    fi
    echo "$ZIEL" >"$ZUSTAND/ausgerollt"
    rm -f "$ZUSTAND/uebersprungen"
    echo "==> Fertig: $KURZ läuft unter ${DOMAIN:+https://$DOMAIN/}${DOMAIN:-http://$NAME.local/}"
    exit 0
fi

# ---- 4. Zurück zur vorherigen Version ----
echo "FEHLER: $KURZ ist nicht hochgekommen." >&2
journalctl -u baukasten-web -u baukasten-worker -n 40 --no-pager || true
echo "$ZIEL" >"$ZUSTAND/uebersprungen"
if [ -n "$VORHER" ]; then
    echo "==> Zurück auf ${VORHER:0:7}"
    systemctl stop baukasten-web baukasten-worker
    if [ -f "$ZUSTAND/vor-update.sqlite3" ]; then
        rm -f "$DB-wal" "$DB-shm"
        install -o baukasten -g baukasten -m 600 "$ZUSTAND/vor-update.sqlite3" "$DB"
    fi
    git checkout --quiet --force --detach "$VORHER"
    ausrollen || echo "FEHLER: Auch die vorherige Version startet nicht." >&2
fi
exit 1
