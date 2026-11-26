#!/usr/bin/env bash
# Tägliche Sicherung der SQLite-Datenbank nach /var/backups/baukasten (die letzten 7 bleiben).
# Läuft per systemd-Timer (eingerichtet von einrichten.sh). Von Hand: sudo systemctl start baukasten-sichern
#
# Zurückspielen (überschreibt die aktuellen Daten!):
#   sudo systemctl stop baukasten-web baukasten-worker
#   sudo rm -f /var/lib/baukasten/baukasten.sqlite3-wal /var/lib/baukasten/baukasten.sqlite3-shm
#   sudo install -o baukasten -g baukasten -m 600 /var/backups/baukasten/baukasten-JJJJ-MM-TT.sqlite3 /var/lib/baukasten/baukasten.sqlite3
#   sudo systemctl start baukasten-web baukasten-worker
#
# Tipp: SD-Karten fallen gern aus. Den Ordner ab und zu woanders hin kopieren (scp, rsync).
set -euo pipefail
DB=/var/lib/baukasten/baukasten.sqlite3
ZIEL=/var/backups/baukasten
BEHALTEN=7

[ -f "$DB" ] || { echo "Noch keine Datenbank."; exit 0; }
install -d -m 700 "$ZIEL"
DATEI="$ZIEL/baukasten-$(date +%F).sqlite3"
# Über die Backup-Schnittstelle von SQLite: konsistent, auch während der Baukasten schreibt.
python3 -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' "$DB" "$DATEI.tmp"
mv "$DATEI.tmp" "$DATEI"
echo "Gesichert: $DATEI ($(du -h "$DATEI" | cut -f1))"
# shellcheck disable=SC2012
ls -1t "$ZIEL"/baukasten-*.sqlite3 | tail -n +$((BEHALTEN + 1)) | xargs -r rm -f
