# 0007: KI über MCP statt eingebautem Assistenten

Status: angenommen · Datum: 2026-11-17

## Kontext

Apps sollen sich mit KI bauen und benutzen lassen. Ein eingebauter Assistent bräuchte
Anbieter-Schlüssel, Kosten im Baukasten und eine Entscheidung für ein Modell.

## Entscheidung

Der Baukasten stellt MCP-Server bereit: je App (`/mcp/<app>/`, Tabellen als Werkzeuge) und für
den Designer (`/mcp/designer/`, Apps anlegen und ändern). Welche KI daran arbeitet, entscheidet
das Team. Der Designer-Server handelt mit den Rechten der Person (persönlicher KI-Zugang),
legt nur Entwürfe an, kann nichts veröffentlichen oder einschalten und sichert vor jeder
Änderung eine Version.

## Folgen

- Kein Anbieter fest eingebaut, keine KI-Kosten im Baukasten.
- Die Qualität hängt von der gewählten KI ab; deshalb verständliche Prüfmeldungen
  (`ai_designer.py`) und die Werkzeuge `guide` und `validate_app`.
