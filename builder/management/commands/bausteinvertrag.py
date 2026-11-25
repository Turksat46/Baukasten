"""Hält fest, welche Bausteine und Einstellungen ausgeliefert wurden (builder/bausteinvertrag.json).

Gespeicherte Seiten verweisen auf diese Namen. Ein Test schlägt fehl, wenn einer davon
verschwindet. Dieses Kommando trägt nur Neues nach und entfernt nie etwas: Wer einen Baustein
oder eine Einstellung wirklich umbenennen oder streichen will, schreibt eine Datenmigration für
die gespeicherten Seiten und nimmt den Eintrag dann bewusst von Hand aus der Datei.

    python manage.py bausteinvertrag
"""
import json

from django.core.management.base import BaseCommand

from builder.blocks import CONTRACT_FILE, block_contract


class Command(BaseCommand):
    help = "Trägt neue Bausteine und Einstellungen in builder/bausteinvertrag.json ein (entfernt nie etwas)."

    def handle(self, *args, **options):
        try:
            saved = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = {}
        current = block_contract()
        merged = {key: sorted(set(saved.get(key, [])) | set(current.get(key, [])))
                  for key in sorted(set(saved) | set(current))}
        added = sum(len(set(merged[k]) - set(saved.get(k, []))) + (k not in saved) for k in merged)
        CONTRACT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8", newline="\n")
        self.stdout.write(f"{CONTRACT_FILE.name}: {len(merged)} Bausteine, {added} Einträge neu.")
