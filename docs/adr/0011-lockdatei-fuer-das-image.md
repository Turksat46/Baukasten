# 0011: Lockdatei mit Prüfsummen für das Image, Versionsgrenzen in .in-Dateien

Status: angenommen · Datum: 2026-11-25

## Kontext

`requirements.txt` nannte nur Versionsbereiche (z. B. `Django>=5.2,<7.0`). Jeder Image-Build holte
die gerade neueste passende Version. Zwei Builds desselben Commits konnten sich also unterscheiden,
und ein Update einer Bibliothek kam unbemerkt mit dem nächsten Build in Produktion.

## Entscheidung

- `requirements.in` und `requirements-automation.in` nennen die Bereiche, gepflegt von Hand.
- `requirements.txt` ist die daraus mit `pip-compile --generate-hashes` erzeugte **Lockdatei**
  (Linux, Python 3.13 wie das Image). Das Image installiert nur sie, mit `--require-hashes`.
- Die CI testet die Lockdatei (Python 3.13) und zusätzlich die neuesten Versionen innerhalb der
  Bereiche (Python 3.10). `tools/lockdatei_pruefen.py` stellt sicher, dass beide zusammenpassen.
- Dependabot hebt Versionen in der Lockdatei per Pull Request an, auch Sicherheitsupdates.

Verworfen: Poetry oder uv als Projektwerkzeug. Beide hätten den Aufbau des Projekts geändert;
pip-tools braucht nichts außer pip, und Dependabot versteht das Format.

## Folgen

- Derselbe Commit baut dasselbe Image; jede Versionsänderung ist ein sichtbarer Pull Request.
- Prüfsummen schützen vor manipulierten Paketen auf dem Weg ins Image.
- Wer eine `.in`-Datei ändert, muss die Lockdatei neu erzeugen (Befehl in CONTRIBUTING.md);
  die CI meldet es, wenn das vergessen wurde.
- Lokal installieren Entwickler aus den `.in`-Dateien, weil die Lockdatei nur für Linux/3.13 gilt.
