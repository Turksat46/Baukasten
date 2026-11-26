# Baukasten auf dem Raspberry Pi Zero (1. Generation)

Für den ersten Pi Zero / Zero W (ARMv6, 512 MB) gibt es kein Kubernetes. Diese Variante läuft deshalb
ohne Container: Python direkt auf dem Pi, SQLite als Datenbank, zwei systemd-Dienste.
Ab einem Pi Zero 2 W lieber die Kubernetes-Variante nehmen: [k8s/pi/LIESMICH.md](../k8s/pi/LIESMICH.md).

```
git push ──► GitHub: Tests (tests.yml) ──grün──┐
                                               ▼
Pi: systemd-Timer alle 3 min ──► aktualisieren.sh ──► neuer Commit + Tests grün?
      ──► DB sichern ──► git checkout ──► Pakete/Migration ──► Dienste neu starten
      ──► startet nicht? ──► alter Code + alte Datenbank zurück
```

Am Router muss nichts freigegeben werden: Der Pi fragt selbst bei GitHub nach.

## Was du erwarten kannst

- Die erste Installation dauert 20–40 Minuten, jedes Update ein paar Minuten (die App ist dabei kurz weg).
- Seiten brauchen oft ein bis mehrere Sekunden. Für dich und ein, zwei weitere Personen im Heimnetz reicht das.
- **Nicht dabei:** Databricks als Datenquelle (braucht pandas/numpy, die es für ARMv6 nicht fertig gibt)
  und PostgreSQL-Datenquellen. Alles andere – Apps bauen, Tabellen, Seiten, Skripte, Automatisierungen – ist dabei.

## Einmal einrichten

1. Mit dem **Raspberry Pi Imager** „Raspberry Pi OS Lite (32-bit)“ auf die SD-Karte schreiben. Es muss
   die aktuelle Version auf Basis von **Debian 13 „Trixie“** sein (Python 3.13), die ältere „Bookworm“ ist zu alt.
   Im Imager Hostname `hellgir`, Benutzer `okumus`, WLAN und SSH einstellen.
2. Auf dem Pi (`ssh okumus@hellgir.local`):

```bash
sudo apt-get install -y git
```

```bash
sudo git clone https://github.com/Turksat46/Baukasten /opt/baukasten/app
```

```bash
sudo /opt/baukasten/app/pi-zero/einrichten.sh
```

Am Ende stehen Adresse und Verwalter-Passwort auf dem Bildschirm (auch in `/etc/baukasten/baukasten.env`).
Die Installation läuft danach im Hintergrund weiter; zuschauen mit `journalctl -fu baukasten-aktualisieren`.
Fertig ist sie, wenn dort „Fertig: … läuft unter http://hellgir.local/“ steht.

Ist das Repository privat: beim `git clone` ein Token in die Adresse schreiben
(`https://<token>@github.com/…`) und dasselbe Token in `/etc/baukasten/pi.env` als `GITHUB_TOKEN` eintragen
(fine-grained, Lesezugriff auf „Contents“ und „Actions“).

## Im Alltag

| Was | Befehl auf dem Pi |
|---|---|
| Zuschauen, was beim Ausrollen passiert | `journalctl -fu baukasten-aktualisieren` |
| Sofort prüfen statt nach 3 Minuten | `sudo systemctl start baukasten-aktualisieren` |
| Übersprungenen/fehlgeschlagenen Stand trotzdem installieren | `sudo ERZWINGEN=1 /opt/baukasten/app/pi-zero/aktualisieren.sh` |
| Logs der App | `journalctl -u baukasten-web -u baukasten-worker -f` |
| Neu starten | `sudo systemctl restart baukasten-web baukasten-worker` |
| Sicherung jetzt | `sudo systemctl start baukasten-sichern` (täglich 3:30, in `/var/backups/baukasten`) |
| Verwalter/Beispiele nachträglich anlegen | `sudo -u baukasten bash -c 'set -a; . /etc/baukasten/baukasten.env; . /var/lib/baukasten/netz.env; cd /opt/baukasten/app; /opt/baukasten/venv/bin/python manage.py lokal_einrichten --ohne-beispiele'` |

## Einstellungen

- `/etc/baukasten/pi.env` – Repository, Zweig (`BRANCH`), `TESTS_ABWARTEN`, `GITHUB_TOKEN`, `EXTRA_HOSTS`
- `/etc/baukasten/baukasten.env` – Umgebung der App: `SECRET_KEY`, Verwalter, gunicorn, Zeitlimits, eigene
  Werte (z. B. `OIDC_ISSUER=…`). Ohne Leerzeichen und Anführungszeichen. Danach Dienste neu starten.
- Daten: `/var/lib/baukasten/baukasten.sqlite3`

Die Adresse (`ALLOWED_HOSTS`) setzt `aktualisieren.sh` selbst aus Hostname und IP, auch wenn sich die IP ändert.

## Entfernen

```bash
sudo systemctl disable --now baukasten-web baukasten-worker baukasten-aktualisieren.timer baukasten-sichern.timer
```

```bash
sudo rm -rf /opt/baukasten /etc/baukasten /var/lib/baukasten /etc/systemd/system/baukasten-*
```
