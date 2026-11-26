#!/usr/bin/env bash
# Hält einen DuckDNS-Namen (z. B. meinname.duckdns.org) auf der aktuellen IPv4- und IPv6-Adresse des Pi.
# Läuft per systemd-Timer alle 5 Minuten, wenn DUCKDNS_TOKEN in /etc/baukasten/pi.env steht
# (eingerichtet von einrichten.sh). Von Hand: sudo systemctl start baukasten-dyndns
#
# IPv4: öffentliche Adresse des Anschlusses (DuckDNS sieht sie an der Anfrage; der Router leitet weiter).
# IPv6: globale Adresse des Pi selbst (jedes Gerät hat eine eigene, der Router gibt sie nur frei).
set -euo pipefail
# shellcheck source=/dev/null
source /etc/baukasten/pi.env
: "${DUCKDNS_TOKEN:?DUCKDNS_TOKEN fehlt in /etc/baukasten/pi.env}"
: "${DOMAIN:?DOMAIN fehlt in /etc/baukasten/pi.env}"
NAME=${DOMAIN%.duckdns.org}
[ "$NAME" != "$DOMAIN" ] || { echo "DOMAIN muss auf .duckdns.org enden." >&2; exit 1; }

# Stabile globale IPv6-Adresse (nicht die wechselnden Datenschutz-Adressen).
V6=$(ip -6 addr show scope global 2>/dev/null | grep inet6 | grep -vE 'temporary|deprecated' \
    | awk '{print $2}' | cut -d/ -f1 | grep -v '^f[cd]' | head -n1 || true)

URL="https://www.duckdns.org/update?domains=$NAME&token=$DUCKDNS_TOKEN&ip=${V6:+&ipv6=$V6}"
# Über IPv4 anfragen, damit DuckDNS die öffentliche IPv4 übernimmt; ohne IPv4 (DS-Lite) nur IPv6.
ANTWORT=$(curl -4 -fsS -m 20 "$URL" 2>/dev/null || curl -fsS -m 20 "$URL")
if [ "$ANTWORT" = OK ]; then
    echo "DuckDNS $DOMAIN aktualisiert${V6:+ (IPv6 $V6)}"
else
    echo "DuckDNS meldet: $ANTWORT (Token und Name prüfen)" >&2
    exit 1
fi
