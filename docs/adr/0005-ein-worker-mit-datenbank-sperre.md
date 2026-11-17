# 0005: Ein Worker-Pod mit Sperre in der Datenbank statt einer Warteschlange

Status: angenommen · Datum: 2026-11-17

## Kontext

Automatisierungen und zeitgesteuerte Skripte brauchen einen Dienst, der sie startet. Übliche
Lösungen sind Celery mit Redis/RabbitMQ oder ein Pod je Skript.

## Entscheidung

Ein einziger Pod `baukasten-worker` (Recreate) startet jeden Lauf als Kindprozess. Dass ein
Skript nie doppelt läuft, sichert ein bedingtes `UPDATE … WHERE running_since IS NULL`
plus Lebenszeichen (`heartbeat_at`); fehlt das Lebenszeichen 90 s, gibt der nächste Worker die
Sperre frei. Termine stehen in `Script.next_run_at`.

## Folgen

- Keine zusätzliche Infrastruktur (kein Broker), keine Rechte für den Worker im Cluster.
- Ein Pod pro Skript wurde verworfen: 100–150 MB je Pod und RBAC-Rechte für den Baukasten.
- Grenze: Alle Läufe teilen sich CPU und Speicher eines Pods. Bei sehr vielen Skripten
  wären mehrere Worker möglich, weil die Sperre in der Datenbank liegt.
