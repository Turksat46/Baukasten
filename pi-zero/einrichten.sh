#!/usr/bin/env bash
# Richtet den Baukasten auf einem Raspberry Pi Zero (erste Generation, ARMv6) ohne Kubernetes ein:
# Python direkt auf dem Pi, SQLite als Datenbank, zwei systemd-Dienste (Webserver, Hintergrund)
# und automatisches Ausrollen: Nach jedem Push mit grünen Tests holt der Pi sich die neue Version.
#
# Voraussetzung: Raspberry Pi OS Lite (32-bit) auf Basis von Debian 13 „Trixie“ (Python 3.13).
#
# Aufruf auf dem Pi (Anleitung: pi-zero/LIESMICH.md):
#   sudo apt-get install -y git
#   sudo git clone https://github.com/Turksat46/Baukasten /opt/baukasten/app
#   sudo /opt/baukasten/app/pi-zero/einrichten.sh
#
# Darf beliebig oft laufen; Vorhandenes (Passwörter, Einstellungen, Daten) bleibt erhalten.
set -euo pipefail

BASIS=/opt/baukasten
APP=$BASIS/app
VENV=$BASIS/venv
KONF=/etc/baukasten
ZUSTAND=/var/lib/baukasten
HIER=$(cd "$(dirname "$0")" && pwd)

schritt() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
fehler() { printf '\n\033[31mFEHLER: %s\033[0m\n' "$*" >&2; exit 1; }

# ---- Voraussetzungen ----
[ "$(id -u)" = 0 ] || fehler "Bitte mit sudo starten."
[ "$HIER" = "$APP/pi-zero" ] || fehler "Das Repository muss unter $APP liegen (git clone … $APP)."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
    || fehler "Python $(python3 -V 2>&1 | cut -d' ' -f2) ist zu alt (Django braucht 3.12+). Bitte Raspberry Pi OS Lite auf Basis von Debian 13 „Trixie“ installieren (Raspberry Pi Imager)."

schritt "Pakete (Debian)"
apt-get update -qq
# python3-cryptography aus Debian: als pip-Paket müsste es auf dem Pi Zero mit Rust kompiliert werden.
apt-get install -y -qq git curl ca-certificates openssl python3-venv python3-pip python3-cryptography sqlite3 >/dev/null

# ---- Auslagerungsspeicher: Pakete installieren und zwei Django-Prozesse brauchen mehr als 512 MB ----
SWAP_KB=$(awk '/SwapTotal/ {print $2}' /proc/meminfo)
if [ "$SWAP_KB" -lt 500000 ] && [ ! -f /var/swap-baukasten ]; then
    schritt "Auslagerungsdatei anlegen (512 MB)"
    fallocate -l 512M /var/swap-baukasten 2>/dev/null || dd if=/dev/zero of=/var/swap-baukasten bs=1M count=512 status=none
    chmod 600 /var/swap-baukasten
    mkswap /var/swap-baukasten >/dev/null
    swapon /var/swap-baukasten
    grep -q swap-baukasten /etc/fstab || echo "/var/swap-baukasten none swap sw 0 0" >>/etc/fstab
fi

# ---- Benutzer und Ordner ----
schritt "Benutzer und Ordner"
id baukasten >/dev/null 2>&1 || useradd --system --home-dir "$ZUSTAND" --shell /usr/sbin/nologin baukasten
install -d -o baukasten -g baukasten -m 750 "$ZUSTAND"
install -d -o root -g baukasten -m 750 "$KONF"
[ -d "$VENV" ] || python3 -m venv --system-site-packages "$VENV"

# ---- Einstellungen und Zugangsdaten ----
schritt "Einstellungen in $KONF"
if [ ! -f "$KONF/pi.env" ]; then
    SLUG=$(git -C "$APP" remote get-url origin | sed -E 's#^.*github\.com[:/]##; s#\.git$##')
    BRANCH=$(git -C "$APP" rev-parse --abbrev-ref HEAD)
    [ "$BRANCH" = HEAD ] && BRANCH=main
    cat >"$KONF/pi.env" <<EOF
# Einstellungen für das automatische Ausrollen (aktualisieren.sh)
# GitHub-Repository und Zweig, dem der Pi folgt
REPO_SLUG=$SLUG
BRANCH=$BRANCH
# Nur ausrollen, wenn der Workflow „Tests“ für den Commit grün ist (ja/nein)
TESTS_ABWARTEN=ja
# Nur für private Repositories: Token mit Lesezugriff auf Actions (fine-grained: „Actions: read“)
GITHUB_TOKEN=
# Beim ersten Start Beispiel-Apps anlegen (ja/nein)
BEISPIELE=nein
# Weitere Hostnamen, unter denen der Baukasten erreichbar sein soll (kommagetrennt), z. B. baukasten.fritz.box
EXTRA_HOSTS=
EOF
    chmod 600 "$KONF/pi.env"
fi
if [ ! -f "$KONF/baukasten.env" ]; then
    cat >"$KONF/baukasten.env" <<EOF
# Umgebung für den Baukasten (Webserver, Hintergrunddienst). Werte ohne Leerzeichen und Anführungszeichen.
# Nach einer Änderung: sudo systemctl restart baukasten-web baukasten-worker
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=sqlite:///$ZUSTAND/baukasten.sqlite3
SQLITE_WAL=1
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$(openssl rand -hex 8)
# Nur im Heimnetz über http: Cookies ohne TLS erlauben
COOKIE_SECURE=false
# Wenig Speicher, langsamer Prozessor
GUNICORN_WORKERS=1
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=180
GUNICORN_MAX_REQUESTS=500
AUTOMATION_PARALLEL=1
AUTOMATION_MEMORY_MB=256
AUTOMATION_MAX_TIMEOUT_MINUTES=30
SCRIPT_TIMEOUT=20
QUERY_TIMEOUT=60
QUERY_PARALLEL=1
LOG_LEVEL=INFO
# Beispiel-Datenquelle der Inventar-Demo (python manage.py demo)
DEMO_DATASOURCE_FILE=$ZUSTAND/demo-datenquelle.sqlite3
DATASOURCE_DEMO=sqlite:///$ZUSTAND/demo-datenquelle.sqlite3
EOF
fi
chown root:baukasten "$KONF/baukasten.env"
chmod 640 "$KONF/baukasten.env"
touch "$ZUSTAND/netz.env"

# ---- Dienste ----
schritt "Dienste einrichten"
chmod +x "$APP/pi-zero/"*.sh
cat >/etc/systemd/system/baukasten-web.service <<EOF
[Unit]
Description=Baukasten (Webserver)
After=network-online.target
Wants=network-online.target

[Service]
User=baukasten
Group=baukasten
WorkingDirectory=$APP
EnvironmentFile=$KONF/baukasten.env
EnvironmentFile=-$ZUSTAND/netz.env
# Port 80 ohne root
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=$VENV/bin/gunicorn config.wsgi:application --config gunicorn.conf.py --bind 0.0.0.0:80
Restart=always
RestartSec=10
TimeoutStartSec=5min
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/baukasten-worker.service <<EOF
[Unit]
Description=Baukasten (Hintergrunddienst: Automatisierungen, Zeitpläne)
After=baukasten-web.service

[Service]
User=baukasten
Group=baukasten
WorkingDirectory=$APP
EnvironmentFile=$KONF/baukasten.env
EnvironmentFile=-$ZUSTAND/netz.env
ExecStart=$VENV/bin/python manage.py hintergrund --dauerhaft
Restart=always
RestartSec=30
TimeoutStopSec=45
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
cat >/etc/systemd/system/baukasten-aktualisieren.service <<EOF
[Unit]
Description=Baukasten: neuesten Stand von GitHub ausrollen
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$APP/pi-zero/aktualisieren.sh
TimeoutStartSec=2h
EOF
cat >/etc/systemd/system/baukasten-aktualisieren.timer <<EOF
[Unit]
Description=Baukasten: alle drei Minuten auf neue Version prüfen

[Timer]
OnBootSec=3min
OnUnitInactiveSec=3min

[Install]
WantedBy=timers.target
EOF
cat >/etc/systemd/system/baukasten-sichern.service <<EOF
[Unit]
Description=Baukasten: Datenbank sichern

[Service]
Type=oneshot
ExecStart=$APP/pi-zero/sichern.sh
EOF
cat >/etc/systemd/system/baukasten-sichern.timer <<EOF
[Unit]
Description=Baukasten: tägliche Sicherung

[Timer]
OnCalendar=*-*-* 03:30
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable baukasten-web baukasten-worker >/dev/null
systemctl enable --now baukasten-aktualisieren.timer baukasten-sichern.timer >/dev/null

schritt "Erste Installation starten"
# Beim ersten Mal nicht auf GitHub-Tests warten: Der geklonte Stand wird direkt installiert.
[ -f "$ZUSTAND/ausgerollt" ] || touch "$ZUSTAND/erzwingen"
systemctl start --no-block baukasten-aktualisieren.service

# shellcheck source=/dev/null
source "$KONF/baukasten.env"
schritt "Fertig eingerichtet"
cat <<EOF
Die erste Installation läuft jetzt im Hintergrund (Python-Pakete, Datenbank: 20–40 Minuten
auf dem Pi Zero). Zuschauen:   journalctl -fu baukasten-aktualisieren

Danach:      http://$(hostname).local/   (oder http://$(hostname -I | awk '{print $1}')/)
Anmelden:    $ADMIN_USERNAME / $ADMIN_PASSWORD   (steht auch in $KONF/baukasten.env)

Ab jetzt:    git push auf '$(. "$KONF/pi.env"; echo "$BRANCH")' → GitHub testet → bei grünen Tests
             installiert der Pi die neue Version innerhalb weniger Minuten selbst.
EOF
