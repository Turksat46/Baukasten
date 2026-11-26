# Baukasten auf dem Raspberry Pi (k3s)

Push auf `main` → GitHub testet → GitHub baut ein arm64-Image → der Pi holt es sich selbst und rollt es aus.
Am Router muss nichts freigegeben werden: Der Pi fragt alle zwei Minuten bei GitHub nach.

```
git push ──► Tests (tests.yml) ──grün──► Pi-Image (pi.yml) ──► ghcr.io/<besitzer>/baukasten:sha-<commit>
                                                                         │
Pi: systemd-Timer alle 2 min ──► aktualisieren.sh ──► neuer Commit? Image da? ──► k3s rollt aus
```

## Voraussetzungen

- **Raspberry Pi Zero 2 W** oder größer. Der erste Pi Zero / Zero W (ARMv6) kann kein Kubernetes.
- **Raspberry Pi OS Lite (64-bit)**, z. B. mit dem Raspberry Pi Imager installiert, SSH eingeschaltet.
- SD-Karte mit mindestens 16 GB (besser 32 GB, „A1“/„A2“).

Ehrlich gesagt: 512 MB Arbeitsspeicher sind für Kubernetes + PostgreSQL + Baukasten knapp. Es läuft
mit Auslagerungsdatei, aber Seiten laden langsamer als auf einem PC und ein Update dauert einige Minuten.
Für ein paar Nutzer im Heimnetz reicht das.

## Einmal einrichten

Auf dem Pi (`ssh okumus@hellgir.local`):

```bash
sudo apt-get install -y git
```

```bash
sudo git clone https://github.com/Turksat46/Baukasten /opt/baukasten
```

```bash
sudo /opt/baukasten/k8s/pi/einrichten.sh
```

Beim ersten Lauf schaltet das Skript die Speicher-cgroup ein und bittet um einen Neustart –
danach `sudo reboot` und den letzten Befehl noch einmal ausführen. Am Ende stehen Adresse und
Verwalter-Passwort auf dem Bildschirm (auch in `/etc/baukasten/geheim.env`).

Der Baukasten läuft dann unter **http://hellgir.local/**.

### Image auf ghcr.io öffentlich machen (einmalig)

Nach dem ersten Lauf von „Pi-Image“ liegt das Image unter *GitHub → Profil → Packages → baukasten*.
Neue Pakete sind privat. Entweder dort unter *Package settings* auf **Public** stellen, oder dem Pi
einen Zugang geben (klassisches Token mit `read:packages`):

```bash
sudo GHCR_USER=<github-name> GHCR_TOKEN=<token> /opt/baukasten/k8s/pi/einrichten.sh
```

## Im Alltag

| Was | Befehl auf dem Pi |
|---|---|
| Zuschauen, was beim Ausrollen passiert | `journalctl -fu baukasten-aktualisieren` |
| Sofort prüfen statt nach 2 Minuten | `sudo systemctl start baukasten-aktualisieren` |
| Fehlgeschlagenen Stand noch mal versuchen | `sudo ERZWINGEN=1 /opt/baukasten/k8s/pi/aktualisieren.sh` |
| Pods ansehen | `sudo k3s kubectl -n baukasten get pods` |
| Logs | `sudo k3s kubectl -n baukasten logs deploy/baukasten` |
| Sicherung jetzt | `sudo systemctl start baukasten-sichern` (täglich 3:30, in `/var/backups/baukasten`) |

## Einstellungen

Alles liegt in `/etc/baukasten/` und bleibt bei Updates erhalten:

- `pi.env` – Image, Zweig (`BRANCH`), Beispiel-Apps, weitere Hostnamen (`EXTRA_HOSTS`)
- `einstellungen.env` – eigene Werte für den Baukasten (`KEY=Wert`), z. B. `OIDC_ISSUER=…`
- `geheim.env` – `SECRET_KEY`, Datenbank, Verwalter
- `skript-geheim.env` – Geheimnisse für Automatisierungen (`SCRIPT_SECRET_<NAME>=…`)

Nach einer Änderung übernimmt der nächste Lauf sie automatisch (die Pods starten neu).
`POSTGRES_PASSWORD` danach nicht mehr ändern – die Datenbank ist schon damit angelegt.

## Was angepasst ist (`kustomization.yaml`)

Dieselben Manifeste wie in der Produktion (`k8s/app.yaml`, `k8s/worker.yaml`), dazu PostgreSQL aus
`k8s/lokal/`. Auf dem Pi anders: ein Pod, ein gunicorn-Prozess, `Recreate` statt Rolling Update
(für zwei Pods reicht der Speicher nicht), Migration als Init-Container, längere Startzeiten,
kleine Speichergrenzen, kein Ingress/HPA/PDB, Zugriff über den ServiceLB von k3s auf Port 80, Cookies
ohne TLS (nur im Heimnetz verwenden).

## Entfernen

```bash
sudo systemctl disable --now baukasten-aktualisieren.timer baukasten-sichern.timer
```

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```
