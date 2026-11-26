# Entscheidungsprotokoll (Architecture Decision Records)

Warum der Baukasten so gebaut ist, wie er ist. Jede Entscheidung mit Kontext und Folgen,
damit Nachfolger gute Gründe nicht versehentlich zurückdrehen. Neue Entscheidungen als
nächste Nummer anlegen; überholte nicht löschen, sondern mit „Status: ersetzt durch …“ markieren.

| Nr. | Entscheidung | Status |
|---|---|---|
| 0001 | [Einträge als JSON in einer gemeinsamen Tabelle](0001-eintraege-als-json.md) | angenommen |
| 0002 | [Python-Skripte normaler Apps in einem eigenen Prozess mit RestrictedPython](0002-python-skripte-im-kindprozess.md) | angenommen |
| 0003 | [JavaScript-Skripte im Browser in einer iframe-Sandbox](0003-javascript-in-iframe-sandbox.md) | angenommen |
| 0004 | [Automatisierungen: echtes Python, nur im Worker, nur für Automatisierer](0004-automatisierungen-mit-echtem-python.md) | angenommen |
| 0005 | [Ein Worker-Pod mit Sperre in der Datenbank statt einer Warteschlange](0005-ein-worker-mit-datenbank-sperre.md) | angenommen |
| 0006 | [Datenquellen nur über Umgebungsvariablen und nur lesend](0006-datenquellen-nur-ueber-umgebung.md) | angenommen |
| 0007 | [KI über MCP statt eingebautem Assistenten](0007-ki-ueber-mcp-statt-eingebaut.md) | angenommen |
| 0008 | [Oberfläche ohne Frontend-Framework und ohne Build-Schritt](0008-oberflaeche-ohne-framework.md) | angenommen |
| 0009 | [Versionen halten den Aufbau fest, nicht die Daten](0009-versionen-ohne-daten.md) | angenommen |
| 0010 | [Änderungsprotokoll über Signale mit Kontext je Eingang](0010-aenderungsprotokoll-ueber-signale.md) | angenommen |
| 0011 | [Lockdatei mit Prüfsummen für das Image, Versionsgrenzen in .in-Dateien](0011-lockdatei-fuer-das-image.md) | angenommen |
| 0012 | [Alle Rechte-Entscheidungen in einer Policy](0012-rechte-in-einer-policy.md) | angenommen |
