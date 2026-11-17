# 0001: Einträge als JSON in einer gemeinsamen Tabelle

Status: angenommen · Datum: 2026-11-17

## Kontext

Fachabteilungen legen im Designer Tabellen und Felder an und ändern sie laufend. Würde jede
App-Tabelle eine echte Datenbanktabelle, bräuchte jede Änderung eine Migration, und der
Designer müsste zur Laufzeit das Datenbankschema ändern.

## Entscheidung

Alle Einträge aller Apps liegen in einer Tabelle (`Record`), die Werte als JSON in
`Record.data`, geschlüsselt nach dem `key` des Feldes. Felder beschreibt das Modell `Field`.
Gespeichert wird mit `UnicodeJSONEncoder` (`ensure_ascii=False`), damit die Textsuche
Umlaute auf jeder Datenbank findet.

## Folgen

- Tabellen und Felder ändern sich ohne Migration und ohne Ausfall.
- Prüfung der Werte (Typ, Pflichtfeld, Auswahl) macht die Anwendung, nicht die Datenbank
  (`scripting/ops.py`, Formulare).
- Filtern und Sortieren nach Feldern ist langsamer als mit echten Spalten. Für interne Apps
  mit bis zu einigen zehntausend Einträgen je Tabelle reicht das; sehr große Datenmengen
  gehören in eine Datenquelle (ADR 0006).
- **Nicht zurückdrehen**, ohne einen Ersatz für das Ändern von Tabellen zur Laufzeit zu haben.
