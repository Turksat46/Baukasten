"""Release Notes aus CHANGELOG.md pflegen:

    python manage.py release_notes                 # Release Notes in der Datenbank abgleichen
    python manage.py release_notes pruefen         # passt CHANGELOG zu BAUKASTEN_VERSION? (Exit-Code 1 bei Fehlern)
    python manage.py release_notes abschnitt 1.1.0 # Abschnitt als Markdown, z. B. für ein GitHub-Release

Der Abgleich läuft auch nach jedem migrate von selbst (siehe builder/release_notes.py).
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from builder import release_notes


class Command(BaseCommand):
    help = "Release Notes aus CHANGELOG.md abgleichen, prüfen oder ausgeben."

    def add_arguments(self, parser):
        parser.add_argument("aktion", nargs="?", default="abgleichen", choices=["abgleichen", "pruefen", "abschnitt"])
        parser.add_argument("version", nargs="?", default="")

    def handle(self, *args, aktion, version, **options):
        if aktion == "pruefen":
            problems = release_notes.check(release_notes.read(), version or settings.BAUKASTEN_VERSION)
            if problems:
                raise CommandError("\n".join(problems))
            self.stdout.write(self.style.SUCCESS("CHANGELOG und Version passen zusammen."))
        elif aktion == "abschnitt":
            release = next((r for r in release_notes.read() if r.version == (version or settings.BAUKASTEN_VERSION)), None)
            if release is None:
                raise CommandError(f"Version {version} steht nicht im CHANGELOG.")
            self.stdout.write(release.section)
        else:
            created, changed = release_notes.sync(settings.BAUKASTEN_VERSION)
            self.stdout.write(f"Release Notes abgeglichen: {created} neu, {changed} geändert.")
