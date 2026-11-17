# 0009: Versionen halten den Aufbau fest, nicht die Daten

Status: angenommen · Datum: 2026-11-17

## Kontext

Designer (und KIs) ändern Apps; Fehler sollen sich rückgängig machen lassen, ohne
Einträge zu verlieren.

## Entscheidung

Eine Version (`AppVersion.snapshot`) enthält Einstellungen, Tabellen, Felder, Seiten, Skripte
und Abfragen, aber keine Einträge. Beim Wiederherstellen werden Tabellen nie gelöscht, damit
keine Daten verloren gehen. Dasselbe Format dient zum Export und Import zwischen Umgebungen
und für den KI-Designer.

## Folgen

- Zurückgehen ist gefahrlos für die Daten.
- Gelöschte oder falsch geänderte **Einträge** kommen nur aus der Datenbank-Sicherung zurück
  (docs/BETRIEB.md, Abschnitt 4).
