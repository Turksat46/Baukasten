#!/usr/bin/env bash
# Rollt auf dem Pi den neuesten Stand von GitHub aus. Läuft per systemd-Timer alle zwei Minuten
# (eingerichtet von einrichten.sh) und tut nichts, solange sich nichts geändert hat.
#
# Ablauf:
#   1. Neuesten Commit des Zweigs holen (BRANCH in /etc/baukasten/pi.env, Standard: main)
#   2. Warten, bis GitHub Actions das Image ghcr.io/<besitzer>/baukasten:sha-<commit> gebaut hat
#      (das passiert nur, wenn die Tests grün sind; vorher läuft die alte Version einfach weiter)
#   3. Image vorab laden (kurze Unterbrechung beim Umschalten), Manifeste einspielen
#   4. Auf den Start warten; beim ersten Mal Verwalter-Konto (und Beispiel-Apps) anlegen
#
# Von Hand anstoßen:         sudo systemctl start baukasten-aktualisieren
# Zuschauen:                 journalctl -fu baukasten-aktualisieren
# Erneut versuchen erzwingen: sudo ERZWINGEN=1 /opt/baukasten/k8s/pi/aktualisieren.sh
set -euo pipefail

KONF=/etc/baukasten
ZUSTAND=/var/lib/baukasten
REPO=/opt/baukasten
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# shellcheck source=/dev/null
source "$KONF/pi.env"
BRANCH="${BRANCH:-main}"
BEISPIELE="${BEISPIELE:-nein}"
: "${IMAGE:?IMAGE fehlt in $KONF/pi.env}"

mkdir -p "$ZUSTAND"
exec 9>"$ZUSTAND/lauf.lock"
flock -n 9 || { echo "Läuft schon."; exit 0; }

kc() { k3s kubectl "$@"; }
ns() { kc -n baukasten "$@"; }

diagnose() {
    echo "==> Diagnose"
    ns get pods -o wide || true
    ns get events --sort-by=.lastTimestamp 2>/dev/null | tail -n 25 || true
    for app in baukasten-db baukasten baukasten-worker; do
        ns logs -l "app=$app" --tail=30 --all-containers --prefix 2>/dev/null || true
    done
    free -m || true
}

# ---- 1. Neuesten Stand holen ----
cd "$REPO"
git fetch --quiet origin "$BRANCH"
ZIEL=$(git rev-parse FETCH_HEAD)

# Adressen, unter denen der Pi erreichbar ist (DHCP kann die IP ändern, darum bei jedem Lauf).
NAME=$(hostname)
IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -vE '^10\.4[23]\.' | paste -sd, - || true)
HOSTS="localhost,127.0.0.1,$NAME,$NAME.local${IPS:+,$IPS}${EXTRA_HOSTS:+,$EXTRA_HOSTS}"

PI_CM=$(mktemp)
trap 'rm -f "$PI_CM"' EXIT
{
    echo "ALLOWED_HOSTS=$HOSTS"
    # Eigene Einstellungen (KEY=Wert), überschreiben alles aus k8s/app.yaml und k8s/pi/.
    if [ -f "$KONF/einstellungen.env" ]; then grep -vE '^\s*(#|$)' "$KONF/einstellungen.env" || true; fi
} >"$PI_CM"

# Ein Wert über alles, was einen Neustart der Pods verlangt: Commit, Einstellungen, Geheimnisse.
STAND=$(cat <(echo "$ZIEL") "$PI_CM" "$KONF/geheim.env" "$KONF/skript-geheim.env" | sha256sum | cut -c1-16)

if [ -z "${ERZWINGEN:-}" ]; then
    [ "$(cat "$ZUSTAND/ausgerollt" 2>/dev/null)" = "$STAND" ] && exit 0
    if [ "$(cat "$ZUSTAND/fehlgeschlagen" 2>/dev/null)" = "$STAND" ]; then
        echo "Stand ${ZIEL:0:7} ist schon einmal fehlgeschlagen; warte auf den nächsten Push (oder ERZWINGEN=1)."
        exit 0
    fi
fi

# ---- 2./3. Image holen ----
IMAGE_REF="$IMAGE:sha-$ZIEL"
echo "==> Neuer Stand ${ZIEL:0:7} – lade $IMAGE_REF"
if ! k3s crictl pull "$IMAGE_REF" >/dev/null 2>"$ZUSTAND/pull.log"; then
    echo "Image noch nicht verfügbar (GitHub baut noch, oder Tests/Build sind fehlgeschlagen). Nächster Versuch in zwei Minuten."
    tail -n 3 "$ZUSTAND/pull.log" || true
    exit 0
fi

# Arbeitskopie auf genau diesen Commit (reine Ausroll-Kopie, lokale Änderungen gehen verloren).
git checkout --quiet --force --detach "$ZIEL"

echo "==> Manifeste einspielen"
kc create namespace baukasten --dry-run=client -o yaml | kc apply -f - >/dev/null
ns create secret generic baukasten-secret --from-env-file="$KONF/geheim.env" --dry-run=client -o yaml | kc apply -f -
ns create secret generic baukasten-skript-geheimnisse --from-env-file="$KONF/skript-geheim.env" --dry-run=client -o yaml | kc apply -f -
ns create configmap baukasten-pi --from-env-file="$PI_CM" --dry-run=client -o yaml | kc apply -f -

MANIFEST=$(kc kustomize k8s/pi --load-restrictor LoadRestrictionsNone \
    | sed -e "s#baukasten-pi-image:aktuell#$IMAGE_REF#g" -e "s#PI_STAND#$STAND#g")
if grep -q 'registry.example.com' <<<"$MANIFEST"; then
    echo "FEHLER: Im gerenderten Manifest steht noch das Beispiel-Image." >&2
    exit 1
fi
kc apply -f - <<<"$MANIFEST"

# ---- 4. Auf den Start warten ----
echo "==> Warte auf den Start (auf dem Pi Zero dauert das ein paar Minuten)"
if ! ns rollout status deploy/baukasten-db --timeout=10m \
    || ! ns rollout status deploy/baukasten --timeout=20m \
    || ! ns rollout status deploy/baukasten-worker --timeout=15m; then
    echo "FEHLER: Stand ${ZIEL:0:7} ist nicht hochgekommen." >&2
    diagnose
    echo "$STAND" >"$ZUSTAND/fehlgeschlagen"
    exit 1
fi

if [ ! -f "$ZUSTAND/eingerichtet" ]; then
    echo "==> Erstes Einrichten: Verwalter-Konto (Beispiel-Apps: $BEISPIELE)"
    ARGS=()
    [ "$BEISPIELE" = "ja" ] || ARGS+=(--ohne-beispiele)
    # Einmalig; schlägt es fehl (z. B. eine Beispiel-App), läuft der Baukasten trotzdem.
    ns exec deploy/baukasten -c web -- python manage.py lokal_einrichten "${ARGS[@]}" \
        || echo "WARNUNG: Einrichten unvollständig – von Hand: sudo k3s kubectl -n baukasten exec deploy/baukasten -- python manage.py lokal_einrichten --ohne-beispiele"
    touch "$ZUSTAND/eingerichtet"
fi

echo "$STAND" >"$ZUSTAND/ausgerollt"
rm -f "$ZUSTAND/fehlgeschlagen"
# Alte Images löschen, die SD-Karte ist klein.
k3s crictl rmi --prune >/dev/null 2>&1 || true
echo "==> Fertig: ${ZIEL:0:7} läuft unter http://$NAME.local/"
