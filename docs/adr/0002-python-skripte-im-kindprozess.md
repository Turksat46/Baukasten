# 0002: Python-Skripte normaler Apps in einem eigenen Prozess mit RestrictedPython

Status: angenommen · Datum: 2026-11-17

## Kontext

Designer schreiben Python-Skripte, die beim Seitenaufruf, per Button oder nach dem Speichern
laufen, auch auf öffentlichen Seiten. Der Code stammt also nicht von Entwicklern und kann
von Gästen ausgelöst werden.

## Entscheidung

Jeder Lauf ist ein eigener Prozess (`scripting/child.py`), gestartet mit `python -I` und
fast leerer Umgebung: keine Zugangsdaten, keine Datenbankverbindung, kein Django. Der Code
wird mit RestrictedPython übersetzt (kein `import` außer einer Liste, kein Dateizugriff,
keine Namen mit Unterstrich). Unter Linux begrenzen rlimits Rechenzeit, Speicher, Dateien.
Alles, was das Skript braucht (Tabellen, Abfragen, HTTP), erfragt es über JSON-Zeilen beim
Elternprozess, der jede Anfrage prüft und auf die eigene App begrenzt.

## Folgen

- Ein Fehler im Skript kann den Web-Prozess nicht beschädigen und kommt nicht an Geheimnisse.
- Jeder Lauf kostet 0,1 bis 0,3 Sekunden für den Prozessstart.
- Restrisiko: eine Lücke in RestrictedPython. Änderungen an `child.py` und `python.py`
  brauchen eine zweite Prüfung.
- Wer mehr braucht (Bibliotheken, lange Läufe), nimmt eine Automatisierung (ADR 0004).
