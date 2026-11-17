# 0006: Datenquellen nur über Umgebungsvariablen und nur lesend

Status: angenommen · Datum: 2026-11-17

## Kontext

Apps sollen Daten aus Datenbanken und Databricks anzeigen. Zugangsdaten dürfen nicht im
Designer landen, und eine langsame Quelle darf den Baukasten nicht lahmlegen.

## Entscheidung

Quellen richtet nur der Betrieb ein (`DATASOURCE_<NAME>`); der Designer wählt nur den Namen.
Erlaubt sind Abfragen mit `SELECT`/`WITH`, die eigentliche Sicherheit ist ein Benutzer mit
reinen Leserechten. Gegen Last: gemeinsamer Cache, eine laufende Abfrage wird nicht doppelt
geschickt, höchstens `QUERY_PARALLEL` Abfragen je Quelle im Cluster, kurze Zeitlimits für
Seiten.

## Folgen

- Keine Zugangsdaten im Designer oder in Versionen.
- Neue Quelle = Secret ändern und neu starten; Designer können sie nicht selbst anlegen.
