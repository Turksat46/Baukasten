# Baukasten im lokalen Kubernetes von Docker Desktop installieren oder aktualisieren.
#
# Voraussetzung: Docker Desktop mit eingeschaltetem Kubernetes (Einstellungen > Kubernetes).
# Aufruf im Baukasten-Ordner:
#     powershell -ExecutionPolicy Bypass -File k8s\lokal\deploy.ps1
# Danach läuft der Baukasten unter http://localhost:8080.
#
# Was passiert:
#   1. Prüfen, ob Kubernetes läuft (Kontext docker-desktop)
#   2. Beim ersten Mal Zugangsdaten mit Zufallswerten in k8s\lokal\geheim.env anlegen
#   3. Image baukasten:lokal bauen
#   4. PostgreSQL, Baukasten und Hintergrunddienst einspielen (Namespace "baukasten")
#   5. Datenbank migrieren, neue Version ausrollen
#   6. Verwalter-Konto und Beispiel-Apps anlegen, falls sie fehlen
# Ein Protokoll des letzten Laufs steht in k8s\lokal\letzter-lauf.log.
#
# Vom Handy oder einem anderen Gerät im selben Netz testen:
#     powershell -ExecutionPolicy Bypass -File k8s\lokal\deploy.ps1 -OhneBeispiele -ImNetzwerk
# erlaubt zusätzlich die aktuelle Adresse dieses PCs im lokalen Netz (z. B. http://192.168.2.10:8080).
# Ohne -ImNetzwerk gilt beim nächsten Lauf wieder: nur dieser PC (localhost).
#
# Wieder entfernen:  kubectl delete namespace baukasten
param([switch]$OhneBeispiele, [switch]$ImNetzwerk)

$ErrorActionPreference = "Continue"
$hier = $PSScriptRoot
Set-Location (Resolve-Path (Join-Path $hier "..\.."))
Start-Transcript -Path (Join-Path $hier "letzter-lauf.log") -Force | Out-Null

function Schritt([string]$text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Pruefe([string]$was) { if ($LASTEXITCODE -ne 0) { throw "$was ist fehlgeschlagen (Exit-Code $LASTEXITCODE)." } }
# Ausgaben externer Programme (kubectl, docker) landen nur über Out-Host im Protokoll.
function K { & kubectl @args 2>&1 | Out-Host }
function Diagnose {
    Write-Host ""
    Write-Host "==> Diagnose" -ForegroundColor Yellow
    K -n baukasten get 'pods,pvc' -o wide
    K -n baukasten get events --sort-by=.lastTimestamp
    foreach ($app in "baukasten-db", "baukasten", "baukasten-worker") {
        K -n baukasten describe pods -l app=$app
        K -n baukasten logs -l app=$app --tail=40 --all-containers
    }
}
function Zufall([int]$bytes) {
    $puffer = New-Object byte[] $bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($puffer)
    ($puffer | ForEach-Object { $_.ToString("x2") }) -join ""
}

$ok = $false
try {
    Schritt "Kubernetes pruefen"
    K config use-context docker-desktop; Pruefe "Kontext docker-desktop (ist Kubernetes in Docker Desktop eingeschaltet?)"
    K get nodes; Pruefe "Kubernetes ist nicht erreichbar"

    $geheim = Join-Path $hier "geheim.env"
    if (-not (Test-Path $geheim)) {
        Schritt "Zugangsdaten anlegen (k8s\lokal\geheim.env)"
        $db = Zufall 16
        $zeilen = @(
            "SECRET_KEY=$(Zufall 32)",
            "POSTGRES_PASSWORD=$db",
            "DATABASE_URL=postgres://baukasten:$db@baukasten-db:5432/baukasten",
            "ADMIN_USERNAME=admin",
            "ADMIN_PASSWORD=$(Zufall 8)"
        )
        [IO.File]::WriteAllText($geheim, (($zeilen -join "`n") + "`n"))
    }
    # Geheimnisse für Automatisierungen: anfangs leer, Einträge als SCRIPT_SECRET_<NAME>=Wert.
    $skriptGeheim = Join-Path $hier "skript-geheim.env"
    if (-not (Test-Path $skriptGeheim)) {
        [IO.File]::WriteAllText($skriptGeheim, "# Geheimnisse fuer Automatisierungen, z. B.`n# SCRIPT_SECRET_ERP_TOKEN=abc`n")
    }
    # Nur Unix-Zeilenenden: sonst hängt an jedem Wert ein unsichtbares Wagenrücklauf-Zeichen.
    foreach ($datei in $geheim, $skriptGeheim) {
        $inhalt = [IO.File]::ReadAllText($datei)
        if ($inhalt.Contains("`r")) { [IO.File]::WriteAllText($datei, $inhalt.Replace("`r", "")) }
    }

    Schritt "Image bauen (baukasten:lokal)"
    docker build -t baukasten:lokal . 2>&1 | Out-Host; Pruefe "docker build"

    Schritt "Manifeste einspielen"
    # Die Manifeste der Produktion liegen im Elternordner; das muss kustomize ausdrücklich erlaubt werden.
    kubectl kustomize k8s/lokal --load-restrictor LoadRestrictionsNone | kubectl apply -f - 2>&1 | Out-Host
    Pruefe "kubectl apply"
    # Früherer CronJob; seine Arbeit macht jetzt der Hintergrunddienst baukasten-worker.
    K -n baukasten delete cronjob baukasten-hintergrund --ignore-not-found

    $netzAdresse = $null
    if ($ImNetzwerk) {
        Schritt "Zugriff aus dem lokalen Netz erlauben"
        # Die Schnittstelle der Standardroute ist die, über die der PC im WLAN/LAN hängt
        # (nicht die virtuellen Adapter von WSL und Docker).
        $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1
        if ($route) {
            $netzAdresse = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
        }
        if (-not $netzAdresse) { throw "Keine Adresse im lokalen Netz gefunden (ist der PC mit WLAN oder LAN verbunden?)." }
        $hosts = "localhost,127.0.0.1,host.docker.internal,$netzAdresse"
        $origins = "http://localhost:8080,http://127.0.0.1:8080,http://${netzAdresse}:8080"
        # Über eine Datei: PowerShell 5.1 verschluckt Anführungszeichen in JSON-Argumenten.
        $patch = Join-Path $env:TEMP "baukasten-netz.json"
        $json = '{"data":{"ALLOWED_HOSTS":"' + $hosts + '","CSRF_TRUSTED_ORIGINS":"' + $origins + '"}}'
        [IO.File]::WriteAllText($patch, $json)
        K -n baukasten patch configmap baukasten-config --type merge --patch-file $patch
        Pruefe "Freigabe im lokalen Netz"
        Remove-Item $patch -ErrorAction SilentlyContinue
        Write-Host "Erlaubt: $netzAdresse (gilt bis zum nächsten Lauf ohne -ImNetzwerk)"
    }

    Schritt "Auf die Datenbank warten"
    # Neu starten, damit der Pod die aktuellen Zugangsdaten bekommt.
    K -n baukasten rollout restart deploy/baukasten-db
    K -n baukasten rollout status deploy/baukasten-db --timeout=240s; Pruefe "Start der Datenbank"

    Schritt "Datenbank migrieren"
    kubectl -n baukasten delete job baukasten-migrate --ignore-not-found | Out-Null
    # Derselbe Job wie in der Produktion, nur mit dem lokal gebauten Image.
    (Get-Content k8s/migrate-job.yaml -Raw) -replace 'image: \S+', 'image: baukasten:lokal' |
        kubectl -n baukasten apply -f - 2>&1 | Out-Host
    Pruefe "Migrations-Job anlegen"
    K -n baukasten wait --for=condition=complete job/baukasten-migrate --timeout=300s
    if ($LASTEXITCODE -ne 0) {
        K -n baukasten logs job/baukasten-migrate
        throw "Die Migration ist fehlgeschlagen (Ausgabe siehe oben)."
    }

    Schritt "Neue Version ausrollen"
    K -n baukasten rollout restart deploy/baukasten; Pruefe "rollout restart"
    K -n baukasten rollout status deploy/baukasten --timeout=300s; Pruefe "Ausrollen"
    K -n baukasten rollout restart deploy/baukasten-worker; Pruefe "rollout restart (Hintergrunddienst)"
    K -n baukasten rollout status deploy/baukasten-worker --timeout=300s; Pruefe "Ausrollen (Hintergrunddienst)"

    Schritt "Verwalter-Konto und Beispiel-Apps"
    # '--' in Anführungszeichen: unquotiert verschluckt PowerShell es beim Aufruf von K.
    if ($OhneBeispiele) {
        K -n baukasten exec deploy/baukasten '--' python manage.py lokal_einrichten --ohne-beispiele
    } else {
        K -n baukasten exec deploy/baukasten '--' python manage.py lokal_einrichten
    }
    Pruefe "Einrichten"

    Schritt "Fertig"
    K -n baukasten get 'pods,svc'
    Write-Host ""
    Write-Host "Baukasten laeuft unter http://localhost:8080" -ForegroundColor Green
    if ($netzAdresse) {
        Write-Host "Im lokalen Netz (Handy im selben WLAN): http://${netzAdresse}:8080" -ForegroundColor Green
        Write-Host "Nur im eigenen Netz verwenden. Ohne -ImNetzwerk ist der Zugriff beim nächsten Lauf wieder zu."
    }
    Write-Host "Anmelden mit 'admin', das Passwort steht in k8s\lokal\geheim.env (ADMIN_PASSWORD)."
    $ok = $true
    Start-Process "http://localhost:8080"
} catch {
    Write-Host ""
    Write-Host "FEHLER: $_" -ForegroundColor Red
    Diagnose
} finally {
    Stop-Transcript | Out-Null
}
if (-not $ok) { exit 1 }
