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
| Befehle von `manage.py` ausführen | `sudo /opt/baukasten/app/pi-zero/manage.sh <befehl>` |

## Beispiel-Apps

Jede Beispiel-App ist ein eigener Befehl und darf mehrmals laufen (vorhandene bleibt, `--neu` ersetzt sie):

| App | Befehl |
|---|---|
| Inventar (mit Beispiel-Datenquelle) | `sudo /opt/baukasten/app/pi-zero/manage.sh demo` |
| Aufnahme-Einwilligung | `sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_einwilligung` |
| Personaleinsatz (Planung, Kanban) | `sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_einsatzplanung` |
| Agenten-Berichte | `sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_berichte` |
| Data Science & Model Monitoring | `sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_datascience` |
| Werks-Apps (20 Stück, auf dem Pi Zero langsam) | `sudo /opt/baukasten/app/pi-zero/manage.sh beispiel_werk` |

Die Inventar-Demo braucht in `/etc/baukasten/baukasten.env` diese zwei Zeilen (bei neuen Installationen
schon drin), danach `sudo systemctl restart baukasten-web baukasten-worker`:

```
DEMO_DATASOURCE_FILE=/var/lib/baukasten/demo-datenquelle.sqlite3
DATASOURCE_DEMO=sqlite:////var/lib/baukasten/demo-datenquelle.sqlite3
```

## HTTPS und Zugriff aus dem Internet

Mit einem öffentlichen Namen in `DOMAIN` setzt `einrichten.sh` **Caddy** vor den Baukasten. Caddy holt ein
kostenloses Zertifikat von Let's Encrypt, erneuert es selbst und leitet `http://` auf `https://` um. Die App
verlangt dann ebenfalls HTTPS (sichere Cookies, Umleitung, HSTS für 30 Tage). gunicorn lauscht nur noch intern.

1. **Name, der auf deinen Anschluss zeigt** (deine IP ändert sich, daher DynDNS), z. B.
   - FRITZ!Box: *Internet → MyFRITZ!-Konto* → Adresse wie `abc123.myfritz.net`, oder
   - kostenlos bei DuckDNS: `meinname.duckdns.org` (Router bzw. Pi aktualisiert die IP).
2. **Portfreigabe im Router:** TCP **80** und **443** auf den Pi (`hellgir`). Port 80 braucht Let's Encrypt
   zum Prüfen und für die Umleitung. SSH (22) nicht freigeben.
3. **Auf dem Pi** den Namen in `/etc/baukasten/pi.env` eintragen (`DOMAIN=meinname.duckdns.org`) und
   `sudo /opt/baukasten/app/pi-zero/einrichten.sh` noch einmal ausführen. Danach
   `sudo systemctl start baukasten-aktualisieren` (übernimmt den Namen in `ALLOWED_HOSTS`).

Prüfen: `journalctl -u caddy -n 30` sollte „certificate obtained successfully“ zeigen.
Im Heimnetz leitet `http://hellgir.local/` auf die HTTPS-Adresse um (der Router muss Aufrufe der eigenen
öffentlichen Adresse von innen zulassen, die FRITZ!Box kann das).

Geht es nicht: Viele Kabel- und Glasfaseranschlüsse haben **DS-Lite** (keine eigene öffentliche IPv4-Adresse).
Dann lassen sich Ports nicht von außen über IPv4 erreichen; Abhilfe sind IPv6 oder ein Tunnel wie Cloudflare Tunnel.

Wieder ausschalten: `DOMAIN=` leeren und `einrichten.sh` erneut ausführen.

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
