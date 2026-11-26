# 0012: Alle Rechte-Entscheidungen in einer Policy (`builder/policy.py`)

Status: angenommen · Datum: 2026-11-26

## Kontext

Mit Seiten- und Tabellenrechten wurde an rund 40 Stellen geprüft, wer was darf: in den Ansichten,
in `render_block`, in `TableOps`, im Designer, bei Berichten und in der Gäste-Logik
(`public_reach`). Jede Stelle kombinierte die Fakten selbst (App-Gruppen, Seitengruppen,
Tabellengruppen, Schalter der Tabelle, Gast oder nicht). Ein neuer Zugriffsweg musste an alle
Regeln denken; vergaß er eine, entstand eine Rechte-Lücke, die kein Test bemerkte.

## Entscheidung

- `builder/policy.py` trifft alle Entscheidungen: `darf(user, aktion, objekt)` und
  `pruefe(...)` (wirft `PermissionDenied`), dazu `sichtbare_seiten()` für Listen.
- Aktionen sind Konstanten: `BENUTZEN`, `BEARBEITEN`, `VERWALTEN` (App), `SEHEN` (Seite),
  `LESEN`, `SCHREIBEN`, `ANLEGEN`, `AENDERN`, `LOESCHEN`, `EXPORTIEREN`, `IMPORTIEREN` (Tabelle),
  `AUSFUEHREN` (Skript), `DESIGNEN`, `AUTOMATISIEREN` (ohne Objekt).
- Die Modelle liefern nur **Fakten** (`App.user_can_use`, `Page.user_can_view`,
  `Entity.user_can_read` …). Was eine Aktion daraus macht, steht nur in der Policy.
- Unbekannte Kombinationen sind ein Programmierfehler (`ValueError`), kein stilles Nein.
- `tests/test_policy.py` prüft eine **Matrix** aus Rollen (Gast, Fremde, Werker, Controlling,
  Werksleitung, Designer) und Zugriffswegen. Jede Zelle muss dreimal übereinstimmen: erwartete
  Antwort, `darf()` und der echte HTTP-Aufruf.

Verworfen: `django-guardian` oder `django-rules`. Beide bringen eigene Tabellen oder eine eigene
Sprache für Regeln mit, und die Regeln hier hängen an Baukasten-Begriffen (öffentliche Seiten,
Schalter der Tabelle, Gäste über Formulare), die man ohnehin selbst ausdrücken müsste.

## Folgen

- Ein neuer Zugriffsweg ruft `darf()` mit der passenden Aktion auf und bekommt eine Zeile in der
  Matrix. Eine eigene Prüfung in der Ansicht ist ein Fehler im Review.
- Regeländerungen (z. B. später „nur eigene Einträge“) passieren an einer Stelle und werden von der
  Matrix gegen alle Zugriffswege geprüft.
- Bewusst nicht in der Policy: API-Schlüssel (eigene Prüfung in `api.py`, der Schlüssel steht für
  einen Bearbeiter), Python-Skripte und gespeicherte SQL-Abfragen (laufen mit Bearbeiter-Rechten),
  der Admin-Bereich (`/admin/`, Django-Rechte).
