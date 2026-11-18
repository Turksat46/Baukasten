# 0010: Änderungsprotokoll über Signale mit Kontext je Eingang

Status: angenommen · Datum: 2026-11-18

## Kontext

Für Apps mit Personendaten muss nachvollziehbar sein, wer wann was geändert hat. Daten und
Aufbau ändern sich auf vielen Wegen: Formulare, Designer, API, MCP, KI-Zugang, Skripte,
Automatisierungen, Abgleiche, `/admin/`. Ein Protokoll, das an jeder Stelle einzeln
aufgerufen werden muss, bekommt früher oder später Lücken.

## Entscheidung

- **Erfassung zentral über Django-Signale** (`pre_save`, `post_save`, `post_delete`) auf
  `Record` und den Modellen des Aufbaus (`builder/audit.py`). Neue Schreibwege sind damit
  automatisch abgedeckt.
- **Wer und worüber** kommt aus einem `ContextVar`, den jeder Eingang setzt: Middleware
  (Person, Weg nach Adresse), API und MCP (Schlüssel), KI-Zugang, Skripte, Worker.
- **Massenvorgänge** (Version wiederherstellen, Import, KI-Änderung, Abgleich, Löschen einer
  App oder Tabelle) schalten die Einzelerfassung ab (`quiet()`) bzw. erkennen das Löschen der
  Eltern und schreiben einen zusammenfassenden Eintrag.
- **Eigene Tabelle `AuditEntry`**, die Namen von App und Person mitspeichert, damit Einträge
  das Löschen überleben. Nur lesbar; gelöscht wird nur nach `AUDIT_RETENTION_DAYS`.
- Gespeichert werden alte und neue Werte geänderter Felder; bei Code und Seiten-Layout nur
  eine Zusammenfassung.

## Folgen

- Jede Änderung kostet eine zusätzliche Abfrage (alter Stand) und einen Schreibvorgang.
- Nicht erfasst: `QuerySet.update()`, `bulk_create`/`bulk_update` außerhalb der Abgleiche und
  Änderungen direkt in der Datenbank. Wer neuen Code mit diesen Methoden schreibt, muss selbst
  `audit.log()` aufrufen.
- Das Protokoll enthält personenbezogene Daten; die Aufbewahrungsfrist ist eine
  Datenschutz-Entscheidung, keine technische.
- Verworfen: ein Paket wie django-simple-history (Kopie jeder Tabelle, passt nicht zu einem
  JSON-Modell mit vielen Apps in einer Tabelle) und Trigger in der Datenbank (kennen weder
  Person noch Weg).
