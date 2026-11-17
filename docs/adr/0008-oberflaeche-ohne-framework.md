# 0008: Oberfläche ohne Frontend-Framework und ohne Build-Schritt

Status: angenommen · Datum: 2026-11-17

## Kontext

Die Oberfläche soll viele Jahre wartbar bleiben, auch wenn das Team wechselt.

## Entscheidung

Django-Templates, eigenes CSS mit Variablen (`theme.css`) und kleines Vanilla-JavaScript je
Funktion (`static/builder/*.js`). Kein React/Vue, kein npm, kein Bundler.

## Folgen

- Keine Abhängigkeitskette im Frontend, die veraltet; Änderungen ohne Build sichtbar.
- Interaktive Teile (Seiten-Designer) sind mehr Handarbeit. Wird die Oberfläche deutlich
  interaktiver, diese Entscheidung neu bewerten.
