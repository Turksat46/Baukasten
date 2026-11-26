#!/usr/bin/env bash
# Richtet einen Raspberry Pi (Zero 2 W oder größer, 64-Bit-Raspberry-Pi-OS Lite) einmalig ein:
# Auslagerungsspeicher, k3s (schlankes Kubernetes), Zugangsdaten und automatisches Ausrollen.
# Danach genügt ein Push auf GitHub – der Pi holt sich die neue Version selbst (aktualisieren.sh).
#
# Aufruf auf dem Pi (Anleitung: k8s/pi/LIESMICH.md):
#   sudo apt-get install -y git
#   sudo git clone https://github.com/Turksat46/Baukasten /opt/baukasten
#   sudo /opt/baukasten/k8s/pi/einrichten.sh
#
# Ist das Image auf ghcr.io privat, Zugang mitgeben (Token mit read:packages):
#   sudo GHCR_USER=<github-name> GHCR_TOKEN=<token> /opt/baukasten/k8s/pi/einrichten.sh
#
# Darf beliebig oft laufen; Vorhandenes (Passwörter, Einstellungen) bleibt erhalten.
set -euo pipefail

REPO=/opt/baukasten
KONF=/etc/baukasten
HIER=$(cd "$(dirname "$0")" && pwd)

schritt() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
fehler() { printf '\n\033[31mFEHLER: %s\033[0m\n' "$*" >&2; exit 1; }

# ---- Voraussetzungen ----
[ "$(id -u)" = 0 ] || fehler "Bitte mit sudo starten."
[ "$HIER" = "$REPO/k8s/pi" ] || fehler "Das Repository muss unter $REPO liegen (git clone … $REPO)."
case "$(uname -m)" in
    aarch64) ;;
    armv6l) fehler "Dies ist ein Raspberry Pi Zero/Zero W der ersten Generation (ARMv6). Kubernetes (k3s) läuft darauf nicht – es braucht mindestens einen Pi Zero 2 W." ;;
    armv7l) fehler "32-Bit-System erkannt. Bitte Raspberry Pi OS Lite (64-bit) installieren (Raspberry Pi Imager)." ;;
    *) fehler "Unerwartete Architektur $(uname -m); erwartet wird aarch64 (64-Bit-Raspberry-Pi-OS)." ;;
esac

schritt "Pakete"
apt-get update -qq
apt-get install -y -qq git curl ca-certificates openssl >/dev/null

# ---- Auslagerungsspeicher: 512 MB reichen für k3s + PostgreSQL + Baukasten nicht ganz ----
SWAP_KB=$(awk '/SwapTotal/ {print $2}' /proc/meminfo)
if [ "$SWAP_KB" -lt 900000 ] && [ ! -f /var/swap-baukasten ]; then
    schritt "Auslagerungsdatei anlegen (1 GB)"
    fallocate -l 1G /var/swap-baukasten 2>/dev/null || dd if=/dev/zero of=/var/swap-baukasten bs=1M count=1024 status=none
    chmod 600 /var/swap-baukasten
    mkswap /var/swap-baukasten >/dev/null
    swapon /var/swap-baukasten
    grep -q swap-baukasten /etc/fstab || echo "/var/swap-baukasten none swap sw 0 0" >>/etc/fstab
fi

# ---- Speicher-cgroup: auf dem Raspberry Pi standardmäßig aus, k3s braucht sie ----
if ! grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null; then
    CMDLINE=/boot/firmware/cmdline.txt
    [ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
    if ! grep -q "cgroup_enable=memory" "$CMDLINE"; then
        schritt "Speicher-cgroup in $CMDLINE einschalten"
        sed -i '1 s/$/ cgroup_memory=1 cgroup_enable=memory/' "$CMDLINE"
    fi
    printf '\n\033[33mBitte neu starten und das Skript danach noch einmal ausführen:\033[0m\n'
    echo "  sudo reboot"
    echo "  sudo $REPO/k8s/pi/einrichten.sh"
    exit 0
fi

# ---- Einstellungen und Zugangsdaten ----
schritt "Einstellungen in $KONF"
install -d -m 700 "$KONF"
if [ ! -f "$KONF/pi.env" ]; then
    # Image-Name aus dem GitHub-Repository ableiten (ghcr.io verlangt Kleinbuchstaben).
    PFAD=$(git -C "$REPO" remote get-url origin | sed -E 's#^.*github\.com[:/]##; s#\.git$##' | tr '[:upper:]' '[:lower:]')
    BRANCH=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)
    [ "$BRANCH" = HEAD ] && BRANCH=main
    cat >"$KONF/pi.env" <<EOF
# Einstellungen für das automatische Ausrollen (aktualisieren.sh)
# Image, das GitHub Actions baut (Workflow .github/workflows/pi.yml)
IMAGE=ghcr.io/$PFAD
# Zweig, dem der Pi folgt
BRANCH=$BRANCH
# Beim ersten Start Beispiel-Apps anlegen (ja/nein). Die Inventar-Demo kann im Cluster nicht
# schreiben (siehe README); einzelne Beispiele lieber von Hand anlegen.
BEISPIELE=nein
# Weitere Hostnamen, unter denen der Baukasten erreichbar sein soll (kommagetrennt), z. B. baukasten.fritz.box
EXTRA_HOSTS=
EOF
fi
if [ ! -f "$KONF/geheim.env" ]; then
    DB=$(openssl rand -hex 16)
    cat >"$KONF/geheim.env" <<EOF
SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$DB
DATABASE_URL=postgres://baukasten:$DB@baukasten-db:5432/baukasten
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$(openssl rand -hex 8)
EOF
fi
[ -f "$KONF/skript-geheim.env" ] || printf '# Geheimnisse für Automatisierungen, z. B.\n# SCRIPT_SECRET_ERP_TOKEN=abc\n' >"$KONF/skript-geheim.env"
[ -f "$KONF/einstellungen.env" ] || printf '# Eigene Einstellungen für den Baukasten (KEY=Wert), überschreiben k8s/app.yaml und k8s/pi/.\n# Beispiel: LOG_LEVEL=DEBUG\n' >"$KONF/einstellungen.env"
chmod 600 "$KONF"/*.env

# ---- Zugang zu ghcr.io (nur für private Images nötig) ----
K3S_NEUSTART=
if [ -n "${GHCR_TOKEN:-}" ]; then
    schritt "Zugang zu ghcr.io hinterlegen"
    : "${GHCR_USER:?GHCR_USER fehlt (GitHub-Benutzername)}"
    install -d -m 755 /etc/rancher/k3s
    umask 077
    cat >/etc/rancher/k3s/registries.yaml <<EOF
configs:
  "ghcr.io":
    auth:
      username: "$GHCR_USER"
      password: "$GHCR_TOKEN"
EOF
    umask 022
    K3S_NEUSTART=1
fi

# ---- k3s ----
if ! command -v k3s >/dev/null; then
    schritt "k3s installieren (dauert auf dem Pi Zero einige Minuten)"
    # Ohne Traefik und Metrics-Server: spart rund 100 MB Arbeitsspeicher. Der Baukasten ist über
    # den eingebauten ServiceLB direkt auf Port 80 erreichbar.
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable traefik --disable metrics-server --write-kubeconfig-mode 600" sh -
elif [ -n "$K3S_NEUSTART" ]; then
    systemctl restart k3s
fi

schritt "Warte auf Kubernetes"
for _ in $(seq 1 90); do
    k3s kubectl get nodes 2>/dev/null | grep -qw Ready && break
    sleep 5
done
k3s kubectl get nodes | grep -qw Ready || fehler "k3s ist nicht bereit (journalctl -u k3s)."
k3s kubectl get nodes

# ---- Automatisches Ausrollen und Sicherung ----
schritt "Automatisches Ausrollen und tägliche Sicherung einrichten"
chmod +x "$REPO/k8s/pi/"*.sh
cat >/etc/systemd/system/baukasten-aktualisieren.service <<EOF
[Unit]
Description=Baukasten: neuesten Stand von GitHub ausrollen
After=k3s.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$REPO/k8s/pi/aktualisieren.sh
TimeoutStartSec=1h
EOF
cat >/etc/systemd/system/baukasten-aktualisieren.timer <<EOF
[Unit]
Description=Baukasten: alle zwei Minuten auf neue Version prüfen

[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min

[Install]
WantedBy=timers.target
EOF
cat >/etc/systemd/system/baukasten-sichern.service <<EOF
[Unit]
Description=Baukasten: Datenbank sichern
After=k3s.service

[Service]
Type=oneshot
ExecStart=$REPO/k8s/pi/sichern.sh
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
systemctl enable --now baukasten-aktualisieren.timer baukasten-sichern.timer >/dev/null
systemctl start --no-block baukasten-aktualisieren.service

# shellcheck source=/dev/null
source "$KONF/geheim.env"
schritt "Fertig eingerichtet"
cat <<EOF
Der erste Start läuft jetzt im Hintergrund (Image laden, Datenbank anlegen: 10–20 Minuten).
Zuschauen:   journalctl -fu baukasten-aktualisieren

Danach:      http://$(hostname).local/   (oder http://$(hostname -I | awk '{print $1}')/)
Anmelden:    $ADMIN_USERNAME / $ADMIN_PASSWORD   (steht auch in $KONF/geheim.env)

Ab jetzt:    git push auf '$(. "$KONF/pi.env"; echo "$BRANCH")' → GitHub testet und baut das Image → der Pi rollt es
             innerhalb von ein paar Minuten selbst aus.
EOF
