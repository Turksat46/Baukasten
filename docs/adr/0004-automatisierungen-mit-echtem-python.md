# 0004: Automatisierungen: echtes Python, nur im Worker, nur für Automatisierer

Status: angenommen · Datum: 2026-11-17

## Kontext

Abgleiche mit anderen Systemen brauchen Bibliotheken (`requests`, `openpyxl` …), dauern
10–20 Minuten oder laufen ständig. Das passt weder zu RestrictedPython noch zum Zeitlimit von
Sekunden.

## Entscheidung

Eine zweite App-Art „Automatisierung“ ohne Seiten. Ihre Skripte laufen mit echtem Python,
aber **nur im Worker-Pod**, nie im Web-Pod, und anlegen dürfen sie nur Mitglieder der Gruppe
„Automatisierer“ (Recht `automate_apps`). Alle teilen sich eine Umgebung
(`requirements-automation.in`), keine eigenen Pakete je Skript. Geheimnisse kommen über
`secret("NAME")` aus einem eigenen Secret, das nur der Worker bekommt. Der Worker macht sich
„nicht auslesbar“ (`PR_SET_DUMPABLE`), damit Skripte nicht an seine Zugangsdaten kommen.

## Folgen

- Wer Automatisierungen bauen darf, kann beliebigen Code im Worker ausführen. Das ist
  bewusst so und durch das eigene Recht begrenzt.
- Das Netz des Workers ist nicht abgeschottet; NetworkPolicies sind die nächste Stufe.
- Neue Bibliotheken brauchen einen Image-Bau: gewollt, damit klar bleibt, was installiert ist.
