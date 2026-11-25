#!/usr/bin/env bash
# Startet Baukasten im Codespace (oder Dev Container): Datenbank, Beispiel-Apps,
# Demo-Konto und Server. Läuft bei jedem Start des Codespaces; Einrichtung nur einmal.
set -euo pipefail
cd "$(dirname "$0")/.."

export DEBUG=1
ALLOWED_HOSTS="localhost,127.0.0.1"
if [ -n "${CODESPACE_NAME:-}" ]; then
  HOST="${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  ALLOWED_HOSTS="${ALLOWED_HOSTS},${HOST}"
  export CSRF_TRUSTED_ORIGINS="https://${HOST}"
fi
export ALLOWED_HOSTS

python manage.py migrate --noinput

if [ ! -f .devcontainer/.eingerichtet ]; then
  python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
if not U.objects.filter(username='demo').exists():
    U.objects.create_superuser('demo', 'demo@example.com', 'demo')
"
  python manage.py demo
  python manage.py beispiel_einwilligung
  python manage.py beispiel_einsatzplanung
  python manage.py beispiel_datascience
  touch .devcontainer/.eingerichtet
fi

# Server und Hintergrund-Worker in eigener Sitzung (setsid) starten: Codespaces beendet
# sonst Prozesse, die der Start-Befehl im Hintergrund hinterlässt.
if ! pgrep -f "manage.py runserver" > /dev/null; then
  setsid nohup python manage.py runserver 0.0.0.0:8000 > /tmp/baukasten.log 2>&1 < /dev/null &
fi
if ! pgrep -f "manage.py hintergrund" > /dev/null; then
  setsid nohup python manage.py hintergrund --dauerhaft > /tmp/baukasten-hintergrund.log 2>&1 < /dev/null &
fi
sleep 3
if ! pgrep -f "manage.py runserver" > /dev/null; then
  echo "Baukasten konnte nicht starten:" >&2
  tail -20 /tmp/baukasten.log >&2
  exit 1
fi
echo "Baukasten läuft auf Port 8000 (Anmeldung: demo / demo). Log: /tmp/baukasten.log"
