# 0003: JavaScript-Skripte im Browser in einer iframe-Sandbox

Status: angenommen · Datum: 2026-11-17

## Kontext

Manche Logik soll sofort auf der Seite passieren (Knopfdruck ohne Neuladen) und braucht
keinen Server.

## Entscheidung

JavaScript-Skripte laufen im Browser der Person in einem `<iframe sandbox>` ohne Zugriff auf
die Seite, Cookies und das Netz. Daten bekommen sie nur über eine Brücke
(`/a/<app>/skript-bruecke/`), die mit den Rechten der angemeldeten Person arbeitet.

## Folgen

- Keine Last auf dem Server, keine Gefahr für ihn.
- Skripte sehen nur, was die Person ohnehin sehen darf.
- Nicht für Hintergrundarbeit oder „nach dem Speichern“ geeignet; dafür Python.
