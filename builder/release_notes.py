"""Release Notes aus CHANGELOG.md: eine Quelle für Entwickler, Nutzer und GitHub.

Aufbau eines Abschnitts in CHANGELOG.md:

    ## 1.1.0 – 2026-11-25

    **Kurz gesagt:** Berichte aus n8n und Teams, Fehler-Alarme und neue Diagramme.

    ### Für Nutzer
    - in einfacher Sprache, wird unter /ueber/ angezeigt

    ### Neu
    - technische Einzelheiten für Entwickler und Betrieb

„Kurz gesagt“ wird zum Titel der Release Note, „Für Nutzer“ zu ihrem Text (fehlt der Teil,
zeigt /ueber/ alle Unterabschnitte). Der Abschnitt „## Unveröffentlicht“ wird zum Entwurf, den
nur Verwalter sehen. Versionen bis zur laufenden BAUKASTEN_VERSION gelten als veröffentlicht.

Abgeglichen wird nach jedem migrate (also bei jedem Ausrollen im Migrations-Job) und mit
python manage.py release_notes. Ohne Django nutzbar, z. B. im GitHub-Workflow:

    python -m builder.release_notes pruefen 1.1.0
    python -m builder.release_notes abschnitt 1.1.0 > notes.md
"""
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
UNRELEASED = "Unveröffentlicht"
HEADING = re.compile(r"^## +(?P<name>.+?)\s*$")
DATED = re.compile(r"^(?P<version>\d+\.\d+\.\d+)\s*[–—-]\s*(?P<date>\d{4}-\d{2}-\d{2})$")
SUMMARY = re.compile(r"^\*\*Kurz gesagt:?\*\*:?\s*(?P<text>.+)$")
USER_PART = "für nutzer"
TITLE_MAX = 120
# Entwurf aus Migration 0016, bevor es den Abgleich gab; steht jetzt unter „Unveröffentlicht“.
OLD_SEED_TITLE = "Änderungsprotokoll, Einstellungen und ältere Versionen einspielen"


@dataclass
class Release:
    version: str
    released_on: date | None
    title: str
    body: str
    section: str
    problems: list = field(default_factory=list)

    @property
    def unreleased(self):
        return self.released_on is None


def version_key(version):
    try:
        return tuple(int(part) for part in str(version).split("."))
    except ValueError:
        return ()


def _subsections(lines):
    """[(überschrift, zeilen)] der ###-Abschnitte; Text davor unter überschrift None."""
    parts, title, current = [], None, []
    for line in lines:
        if line.startswith("### "):
            parts.append((title, current))
            title, current = line[4:].strip(), []
        else:
            current.append(line)
    parts.append((title, current))
    return parts


def _clean(lines):
    return "\n".join(lines).strip()


def parse(text):
    """Alle Abschnitte des CHANGELOG, neueste zuerst, wie sie in der Datei stehen."""
    releases, name, lines = [], None, []

    def finish():
        if name is not None:
            releases.append(_release(name, lines))

    for line in (text or "").splitlines():
        match = HEADING.match(line)
        if match:
            finish()
            name, lines = match.group("name"), []
        elif name is not None:
            lines.append(line.rstrip())
    finish()
    return releases


def _release(name, lines):
    problems = []
    dated = DATED.match(name)
    if dated:
        version, released_on = dated.group("version"), date.fromisoformat(dated.group("date"))
    elif name.strip().lower() == UNRELEASED.lower():
        version, released_on = UNRELEASED, None
    else:
        version, released_on = name, None
        problems.append(f"Überschrift „## {name}“: erwartet „## 1.2.3 – JJJJ-MM-TT“ oder „## {UNRELEASED}“.")

    title, rest = "", []
    for line in lines:
        match = SUMMARY.match(line.strip())
        if match and not title:
            title = match.group("text").strip().rstrip(".")
        else:
            rest.append(line)
    parts = _subsections(rest)
    intro = _clean(parts[0][1])
    if not title:
        first = next((line.strip() for line in parts[0][1] if line.strip()), "")
        title = first.rstrip(".") if first and not first.startswith(("-", "*", "|", ">")) else ""
        if released_on and not title:
            problems.append(f"{version}: Es fehlt die Zeile „**Kurz gesagt:** …“ (Titel für /ueber/).")
    if len(title) > TITLE_MAX:
        problems.append(f"{version}: „Kurz gesagt“ ist länger als {TITLE_MAX} Zeichen.")
        title = title[: TITLE_MAX - 1].rstrip() + "…"

    user = next((body for heading, body in parts[1:] if heading and heading.lower() == USER_PART), None)
    if user is not None:
        body = _clean(user)
    else:
        body = "\n\n".join(f"### {heading}\n{_clean(content)}" for heading, content in parts[1:] if heading)
        if intro and intro.rstrip(".") != title:
            body = f"{intro}\n\n{body}".strip()
    section = _clean(lines)
    return Release(version, released_on, title or f"Version {version}", body, section, problems)


def read(path=CHANGELOG):
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def check(releases, running_version):
    """Fehler als Liste von Texten; leer, wenn CHANGELOG und Version zusammenpassen."""
    problems = [p for r in releases for p in r.problems]
    dated = [r for r in releases if not r.unreleased and version_key(r.version)]
    if not dated:
        return problems + ["Im CHANGELOG steht keine Version mit Datum („## 1.2.3 – JJJJ-MM-TT“)."]
    if dated[0].version != running_version:
        problems.append(f"BAUKASTEN_VERSION ist {running_version}, die neueste Version im CHANGELOG aber "
                        f"{dated[0].version}. Beides beim Release gemeinsam ändern.")
    for newer, older in zip(dated, dated[1:]):
        if version_key(newer.version) <= version_key(older.version):
            problems.append(f"Reihenfolge: {newer.version} steht über {older.version}; die neueste Version gehört nach oben.")
        if newer.released_on < older.released_on:
            problems.append(f"Datum: {newer.version} ({newer.released_on}) ist älter als {older.version}.")
    versions = [r.version for r in releases]
    for version in sorted({v for v in versions if versions.count(v) > 1}):
        problems.append(f"Version {version} steht mehrfach im CHANGELOG.")
    if versions.count(UNRELEASED) and versions.index(UNRELEASED) != 0:
        problems.append(f"„## {UNRELEASED}“ gehört ganz nach oben.")
    return problems


def sync(running_version, path=CHANGELOG):
    """Gleicht die Release Notes in der Datenbank mit dem CHANGELOG ab. Gibt (angelegt, geändert) zurück.

    Einträge zu Versionen aus dem CHANGELOG werden überschrieben; eigene Einträge unter /admin/
    (andere Versionen) bleiben, wie sie sind."""
    from django.db import transaction

    from .models import ReleaseNote

    releases = read(path)
    if not releases:
        return 0, 0
    created = changed = 0
    running = version_key(running_version)
    with transaction.atomic():
        for release in releases:
            values = {
                "title": release.title[:TITLE_MAX], "body": release.body,
                "published": bool(release.released_on) and version_key(release.version) <= running,
            }
            if release.released_on:
                values["released_on"] = release.released_on
            note = ReleaseNote.objects.filter(version=release.version).order_by("id").first()
            if note is None:
                ReleaseNote.objects.create(version=release.version, **values)
                created += 1
            elif any(getattr(note, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(note, key, value)
                note.save()
                changed += 1
        if any(r.unreleased for r in releases):
            ReleaseNote.objects.filter(published=False, title=OLD_SEED_TITLE).exclude(
                version__in=[r.version for r in releases]).delete()
    return created, changed


def managed_versions(path=CHANGELOG):
    return {r.version for r in read(path)}


def on_post_migrate(sender, **kwargs):
    """Nach jedem migrate abgleichen. Ein Fehler hier darf das Ausrollen nicht aufhalten."""
    import logging

    from django.conf import settings
    from django.db import DatabaseError

    try:
        sync(settings.BAUKASTEN_VERSION)
    except (DatabaseError, OSError, ValueError):
        logging.getLogger(__name__).exception("Release Notes aus CHANGELOG.md nicht abgeglichen")


def main(argv):
    """Ohne Django: pruefen <version> | abschnitt <version> | titel <version>."""
    if len(argv) != 2 or argv[0] not in ("pruefen", "abschnitt", "titel"):
        print("Aufruf: python -m builder.release_notes pruefen|abschnitt|titel <version>", file=sys.stderr)
        return 2
    action, version = argv
    version = version.removeprefix("v")
    releases = read()
    if action == "pruefen":
        problems = check(releases, version)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    release = next((r for r in releases if r.version == version), None)
    if release is None:
        print(f"Version {version} steht nicht im CHANGELOG.", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(release.title if action == "titel" else release.section)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
