# Sicherung der Baukasten-Datenbank im lokalen Kubernetes, mit Probe-Wiederherstellung.
#
# Aufruf im Baukasten-Ordner:
#     powershell -ExecutionPolicy Bypass -File k8s\lokal\sicherung.ps1
#
# Was passiert:
#   1. pg_dump im Datenbank-Pod (Format „custom“), Datei nach k8s\lokal\sicherungen\
#   2. Probe: dieselbe Sicherung in eine Test-Datenbank einspielen, Zeilen der wichtigsten
#      Tabellen mit dem Original vergleichen, Test-Datenbank wieder löschen
# Die echte Datenbank wird nur gelesen. Sicherungen enthalten echte Daten: Der Ordner
# sicherungen\ steht in .gitignore und gehört nicht ins Repository.
#
# Zurückspielen (überschreibt die Datenbank!) steht im Betriebshandbuch, docs\BETRIEB.md.
param([switch]$OhneProbe)

# Continue: Hinweise externer Programme auf stderr sind keine Fehler; geprüft wird $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$ns = "baukasten"
$hier = $PSScriptRoot
$ordner = Join-Path $hier "sicherungen"
New-Item -ItemType Directory -Force $ordner | Out-Null

$pod = kubectl -n $ns get pod -l app=baukasten-db -o jsonpath="{.items[0].metadata.name}"
if (-not $pod) { throw "Kein Datenbank-Pod gefunden (läuft Kubernetes, ist der Baukasten eingespielt?)." }
$name = "baukasten-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".dump"

Write-Host "==> Sicherung erstellen ($name)" -ForegroundColor Cyan
kubectl -n $ns exec $pod '--' sh -c "pg_dump -U baukasten -Fc baukasten > /tmp/sicherung.dump"
if ($LASTEXITCODE -ne 0) { throw "pg_dump ist fehlgeschlagen." }
# kubectl cp mag keine Laufwerksbuchstaben: relativ zum Skriptordner kopieren
Push-Location $hier
try {
    kubectl -n $ns cp "${pod}:/tmp/sicherung.dump" "sicherungen/$name" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Kopieren der Sicherung ist fehlgeschlagen." }
} finally { Pop-Location }
$groesse = [math]::Round((Get-Item (Join-Path $ordner $name)).Length / 1KB)
Write-Host "Gespeichert: k8s\lokal\sicherungen\$name ($groesse KB)"

if (-not $OhneProbe) {
    Write-Host "==> Probe: in eine Test-Datenbank wiederherstellen und vergleichen" -ForegroundColor Cyan
    $pruefung = @'
set -e
dropdb -U baukasten --if-exists baukasten_probe 2>/dev/null
createdb -U baukasten baukasten_probe
pg_restore -U baukasten -d baukasten_probe --no-owner /tmp/sicherung.dump
fehler=0
for t in builder_app builder_entity builder_field builder_record builder_page builder_script auth_user; do
  a=$(psql -U baukasten -d baukasten -tAc "select count(*) from $t")
  b=$(psql -U baukasten -d baukasten_probe -tAc "select count(*) from $t")
  echo "$t: Original $a, wiederhergestellt $b"
  [ "$a" = "$b" ] || fehler=1
done
dropdb -U baukasten baukasten_probe
rm -f /tmp/sicherung.dump
exit $fehler
'@
    # Base64-kodiert übergeben: PowerShell 5.1 verschluckt Anführungszeichen in Argumenten
    # und setzt beim Weiterleiten über stdin ein unsichtbares BOM vor die erste Zeile.
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pruefung.Replace("`r", "")))
    kubectl -n $ns exec $pod '--' sh -c "echo $b64 | base64 -d | sh"
    if ($LASTEXITCODE -ne 0) { throw "Die Probe-Wiederherstellung weicht vom Original ab oder ist fehlgeschlagen." }
    Write-Host "Probe bestanden: Die Sicherung lässt sich vollständig wiederherstellen." -ForegroundColor Green
} else {
    kubectl -n $ns exec $pod '--' rm -f /tmp/sicherung.dump | Out-Null
}
