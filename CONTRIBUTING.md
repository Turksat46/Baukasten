# Am Baukasten mitarbeiten

Kurzanleitung für alle, die den Baukasten weiterentwickeln oder betreuen. Wie das System
aufgebaut ist, steht in [docs/TECHNISCHE_DOKUMENTATION.md](docs/TECHNISCHE_DOKUMENTATION.md),
warum es so gebaut ist, in den [Architekturentscheidungen](docs/adr/README.md), der Betrieb in
[docs/BETRIEB.md](docs/BETRIEB.md).

## Einrichten

```powershell
python -m venv .venv
.venv\Scripts\activate                     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.in -r requirements-automation.in
pip install "ruff==0.17.6" "packaging>=24"   # Werkzeuge, dieselben Versionen wie in der CI
$env:DEBUG=1                               # Linux/macOS: export DEBUG=1
python manage.py migrate
python manage.py demo
python manage.py runserver
```

## Vor jedem Pull Request

```powershell
ruff check .                               # Codeprüfung (Regeln in pyproject.toml)
python manage.py test builder              # alle Tests
python manage.py makemigrations --check --dry-run
```

Die CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) prüft dasselbe, zusätzlich
mit PostgreSQL, mit Python 3.10 und ob das Docker-Image baut und startet.

- **Tests** liegen in [builder/tests/](builder/tests/), eine Datei je Bereich (Laufzeit, Designer,
  API, Skripte, …). Gemeinsame Testdaten: `Base` in [builder/tests/base.py](builder/tests/base.py).
  Einzelne Bereiche: `python manage.py test builder.tests.test_designer`.
- **Formatierung:** `ruff format` ist bewusst nicht eingeschaltet, damit die Historie
  (`git blame`) lesbar bleibt. Neuer Code orientiert sich am umgebenden Stil, Zeilen bis 120 Zeichen.
- **Updates ohne Bruch:** Beim Ausrollen laufen alte und neue Pods kurz nebeneinander. Die Regeln
  dafür stehen in der technischen Dokumentation unter „Rückwärtskompatibilität bei Updates“.
- **Texte** sind auf Deutsch, Englisch ist Übersetzung:
  `python manage.py uebersetzungen ergaenzen`, Übersetzungen eintragen, dann `… kompilieren`.
- **CHANGELOG.md** bekommt zu jeder sichtbaren Änderung einen Eintrag unter „Unveröffentlicht“.
  Daraus entstehen die Release Notes in der App (`python -m builder.release_notes pruefen <version>`).
- **Größere Entscheidungen** als neue Datei in [docs/adr/](docs/adr/README.md) festhalten.

## Abhängigkeiten

| Datei | Inhalt | Wer ändert sie |
|---|---|---|
| `requirements.in` | Bibliotheken des Baukastens mit Versionsgrenzen | Entwickler |
| `requirements-automation.in` | zusätzliche Bibliotheken für Automatisierungen | Betrieb, Entwickler |
| `requirements.txt` | **Lockdatei**: genaue Versionen mit Prüfsummen, daraus baut das Image | wird erzeugt, nie von Hand |

Nach jeder Änderung an einer `.in`-Datei die Lockdatei neu erzeugen. Der Befehl läuft im selben
Python wie das Image (Linux, 3.13) und braucht nur Docker:

```powershell
docker run --rm -v "${PWD}:/src" -w /src python:3.13-slim sh -c "pip install -q pip-tools && pip-compile -q --generate-hashes --strip-extras --allow-unsafe --no-emit-index-url --output-file=requirements.txt requirements.in requirements-automation.in"
```

Ohne `--upgrade` bleiben alle übrigen Versionen, wie sie sind. Alles neu auflösen:
`--upgrade` anhängen; ein einzelnes Paket: `--upgrade-package django`.

`python tools/lockdatei_pruefen.py` meldet, wenn Lockdatei und `.in`-Dateien nicht zusammenpassen
(läuft auch in der CI). Dependabot hält die Lockdatei wöchentlich aktuell
([.github/dependabot.yml](.github/dependabot.yml)); neue Django-Hauptversionen plant ihr von Hand.

## Commits und Pull Requests

- Ein Thema je Pull Request, Branch von `main` (`feat/…`, `fix/…`, `chore/…`).
- Pull Requests brauchen grüne CI. Gemergt wird über GitHub.
- Ein Release entsteht über den Tag `v<version>`; siehe [.github/workflows/release.yml](.github/workflows/release.yml).
