"""Übersetzungen für die Inhalte einer App (nicht für die Oberfläche des Baukastens).

Gebaut wird eine App in der Quellsprache (LANGUAGE_CODE, meist Deutsch). Für jede
weitere Sprache aus LANGUAGES kann man im Designer zu jedem Text der App eine
Übersetzung eintragen. Gespeichert wird das in App.translations:

    {"en": {"Veranstaltungen": "Events", "Zustimmung": "Consent", …}}

Schlüssel ist der Text in der Quellsprache, wie bei gettext. Derselbe Text wird
überall gleich übersetzt; ändert sich der Quelltext, fehlt die Übersetzung, bis
jemand sie neu einträgt. Fehlt eine Übersetzung, erscheint der Quelltext.

Gespeicherte Daten bleiben unverändert: Ein Auswahlwert „Zustimmung“ steht so in
der Datenbank, in der API und in Skripten und wird nur in der Anzeige übersetzt.
"""
import contextvars
import csv
import io

from django.conf import settings
from django.utils.translation import get_language

_current = contextvars.ContextVar("baukasten_app_translations", default={})

# Einstellungen von Bausteinen, die Adressen oder Pfade enthalten, nie Text für Menschen.
NOT_TEXT = {"url", "path", "param", "filters"}
MAX_TEXT = 5000


def source_language():
    return settings.LANGUAGE_CODE.split("-", 1)[0]


def target_languages():
    """[(Code, Name)] aller Sprachen außer der Quellsprache."""
    return [(code, name) for code, name in settings.LANGUAGES if code != source_language()]


def current_language():
    return (get_language() or source_language()).split("-", 1)[0]


def mapping(app, language=None):
    language = language or current_language()
    if app is None or language == source_language():
        return {}
    return (app.translations or {}).get(language) or {}


def activate(app):
    """Übersetzungen dieser App für die aktuelle Sprache für den Rest der Anfrage."""
    _current.set(mapping(app))


def reset():
    _current.set({})


def t(text, app=None):
    """Übersetzung eines Textes aus der App; ohne Übersetzung der Text selbst."""
    if not isinstance(text, str) or not text:
        return text
    table = mapping(app) if app is not None else _current.get()
    return table.get(text) or text


def translate_props(props, block_type):
    """Kopie der Einstellungen eines Bausteins mit übersetzten Texten."""
    if not _current.get() or block_type is None:
        return props
    keys = text_keys(block_type)
    return {k: t(v) if k in keys else v for k, v in props.items()}


def text_keys(block_type):
    return {f["key"] for f in block_type.fields if f.get("type") in ("text", "textarea") and f["key"] not in NOT_TEXT}


def collect(app):
    """Alle übersetzbaren Texte einer App in der Reihenfolge, in der man sie baut: [(Text, Fundort)]."""
    from .blocks import all_types

    found = {}

    def add(text, where):
        text = (text or "").strip() if isinstance(text, str) else ""
        if text and len(text) <= MAX_TEXT:
            found.setdefault(text, where)

    add(app.name, "App: Name")
    add(app.description, "App: Beschreibung")
    for entity in app.entities.prefetch_related("fields"):
        add(entity.name, f"Tabelle „{entity.name}“")
        for field in entity.fields.all():
            add(field.label, f"Feld in „{entity.name}“")
            for choice in field.choice_list() if field.type == field.CHOICE else []:
                add(choice, f"Auswahlwert von „{field.label}“")
    types = all_types()
    for page in app.pages.all():
        add(page.title, f"Seite „{page.title}“: Titel")
        for block in page.layout or []:
            block_type = types.get(block.get("type"))
            if block_type is None:
                continue
            keys = text_keys(block_type)
            for key, value in (block.get("props") or {}).items():
                if key in keys:
                    add(value, f"Seite „{page.title}“: {block_type.label}")
    return list(found.items())


def clean(raw, known=None):
    """Prüft eingereichte Übersetzungen: nur bekannte Sprachen, nur Text, leere Einträge fallen weg."""
    languages = {code for code, _name in target_languages()}
    result = {}
    for language, table in (raw or {}).items() if isinstance(raw, dict) else []:
        if language not in languages or not isinstance(table, dict):
            continue
        entries = {str(k)[:MAX_TEXT]: str(v).strip()[:MAX_TEXT] for k, v in table.items()
                   if isinstance(k, str) and isinstance(v, str) and v.strip() and (known is None or k in known)}
        if entries:
            result[language] = entries
    return result


def to_csv(app):
    """Alle Texte mit Fundort und Übersetzungen, zum Bearbeiten in Excel o. Ä."""
    languages = [code for code, _name in target_languages()]
    out = io.StringIO()
    out.write("﻿")  # damit Excel Umlaute richtig liest
    writer = csv.writer(out, delimiter=";")
    writer.writerow([source_language(), "ort", *languages])
    for text, where in collect(app):
        writer.writerow([text, where, *[mapping(app, code).get(text, "") for code in languages]])
    return out.getvalue()


def from_csv(app, content):
    """Übernimmt Übersetzungen aus einer CSV-Datei (wie to_csv). Gibt die Anzahl der Einträge zurück.
    Spalten anderer Sprachen und unbekannte Texte werden ignoriert; leere Zellen löschen nichts."""
    content = content.lstrip("﻿")
    dialect = csv.Sniffer().sniff(content.splitlines()[0] if content else ";", delimiters=";,\t")
    rows = list(csv.reader(io.StringIO(content), dialect))
    if not rows:
        return 0
    header = [h.strip() for h in rows[0]]
    languages = {code for code, _name in target_languages()}
    columns = {i: h for i, h in enumerate(header) if h in languages}
    known = {text for text, _where in collect(app)}
    merged = {code: dict(table) for code, table in (app.translations or {}).items()}
    count = 0
    for row in rows[1:]:
        if not row or row[0] not in known:
            continue
        for index, language in columns.items():
            value = row[index].strip() if index < len(row) else ""
            if value:
                merged.setdefault(language, {})[row[0]] = value
                count += 1
    app.translations = clean(merged)
    app.save(update_fields=["translations"])
    return count
