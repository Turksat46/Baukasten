#!/usr/bin/env bash
# Tägliche Sicherung der Datenbank nach /var/backups/baukasten (die letzten 7 bleiben).
# Läuft per systemd-Timer (eingerichtet von einrichten.sh). Von Hand: sudo systemctl start baukasten-sichern
#
# Zurückspielen (überschreibt die aktuellen Daten!):
#   sudo k3s kubectl -n baukasten exec -i deploy/baukasten-db -- \
#     pg_restore -U baukasten -d baukasten --clean --if-exists < /var/backups/baukasten/baukasten-JJJJ-MM-TT.dump
#
# Tipp: Die SD-Karte kann ausfallen. Den Ordner ab und zu woanders hin kopieren (z. B. per scp oder rsync).
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
ZIEL=/var/backups/baukasten
BEHALTEN=7

mkdir -p "$ZIEL"
chmod 700 "$ZIEL"
DATEI="$ZIEL/baukasten-$(date +%F).dump"
k3s kubectl -n baukasten exec deploy/baukasten-db -- pg_dump -U baukasten -Fc baukasten >"$DATEI.tmp"
mv "$DATEI.tmp" "$DATEI"
echo "Gesichert: $DATEI ($(du -h "$DATEI" | cut -f1))"
# shellcheck disable=SC2012
ls -1t "$ZIEL"/baukasten-*.dump | tail -n +$((BEHALTEN + 1)) | xargs -r rm -f
