#!/usr/bin/env bash
# manage.py auf dem Pi ausführen – als Benutzer baukasten, mit derselben Umgebung wie die Dienste.
#   sudo /opt/baukasten/app/pi-zero/manage.sh demo
#   sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_einsatzplanung
#   sudo /opt/baukasten/app/pi-zero/manage.sh help
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten." >&2; exit 1; }
exec runuser -u baukasten -- bash -c 'set -a; . /etc/baukasten/baukasten.env; . /var/lib/baukasten/netz.env; set +a
    cd /opt/baukasten/app && exec /opt/baukasten/venv/bin/python manage.py "$@"' _ "$@"
