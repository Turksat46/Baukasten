"""Lädt die Werks-Apps aus beispiele/werk/*.json: python manage.py beispiel_werk [--neu] [--nur gmd-oee,…]

Die Dateien erzeugt beispiele/werk/erzeugen.py. Jede Datei ist eine Definition im Format des
KI-Designers (ai_designer.normalize) plus Beispieldaten:
- „@-3“ in einem Datumsfeld heißt „heute minus 3 Tage“,
- „#4“ in einem Verweisfeld zeigt auf den 4. Beispieleintrag der Zieltabelle.
Nach dem Anlegen eines Eintrags laufen die Skripte „Nach dem Speichern“ wie beim Speichern im Formular.
"""
import json
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from builder import ai_designer, audit, versions
from builder.models import App, Field, Record, Script
from builder.scripting import triggers

ORDNER = Path(settings.BASE_DIR) / "beispiele" / "werk"
DATUM = re.compile(r"^@([+-]?\d+)$")
VERWEIS = re.compile(r"^#(\d+)$")


class Command(BaseCommand):
    help = "Legt die Werks-Apps (Produkttest) mit Beispieldaten an."

    def add_arguments(self, parser):
        parser.add_argument("--neu", action="store_true", help="Vorhandene Werks-Apps ersetzen.")
        parser.add_argument("--nur", default="", help="Nur diese Apps (Kurznamen, durch Komma getrennt).")
        parser.add_argument("--ordner", default=str(ORDNER), help="Ordner mit den JSON-Dateien.")

    def handle(self, *args, **options):
        files = sorted(Path(options["ordner"]).glob("*.json"))
        if not files:
            raise CommandError(f"Keine App-Dateien in {options['ordner']} – zuerst beispiele/werk/erzeugen.py ausführen.")
        nur = {s.strip() for s in options["nur"].split(",") if s.strip()}
        self.verbosity = options["verbosity"]
        owner = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
        with audit.quiet():
            for path in files:
                data = json.loads(path.read_text(encoding="utf-8"))
                if nur and data["slug"] not in nur:
                    continue
                self._load(data, options["neu"], owner)

    def _load(self, data, replace, owner):
        slug = data["slug"]
        existing = App.objects.filter(slug=slug)
        if existing.exists():
            if not replace:
                self.stdout.write(f"{slug}: gibt es schon (mit --neu ersetzen).")
                return
            existing.delete()
        definition = {k: data[k] for k in ("name", "icon", "description", "entities", "pages", "scripts") if k in data}
        try:
            snapshot, warnings = ai_designer.normalize(definition)
        except ai_designer.Invalid as exc:
            raise CommandError(f"{slug}: " + "; ".join(exc.errors)) from exc
        app = App.objects.create(name=data["name"], slug=slug, published=True, created_by=owner)
        versions.apply(app, snapshot)
        for page in data.get("pages", []):
            if page.get("public"):
                app.pages.filter(slug=page["slug"]).update(public=True)
        # Der KI-Designer legt Skripte ausgeschaltet an (ein Mensch prüft sie erst). Diese Beispiele
        # stammen aus dem Repository und sind geprüft, darum hier gleich einschalten.
        app.scripts.update(enabled=True)
        count = self._data(app, data.get("beispieldaten") or {})
        if self.verbosity:
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"  {slug}: {w}"))
            self.stdout.write(self.style.SUCCESS(f"{slug}: {app.name} – {count} Einträge (/a/{slug}/)"))

    def _data(self, app, rows_by_table):
        today = timezone.localdate()
        entities = {e.slug: e for e in app.entities.all()}
        created = {}  # slug -> [pk, …] in Reihenfolge der Beispieldaten
        count = 0
        # Tabellen ohne Verweise zuerst, damit „#n“ aufgelöst werden kann
        order = sorted(rows_by_table, key=lambda s: entities[s].fields.filter(type=Field.REFERENCE).exists())
        save_scripts = {s.entity_id for s in Script.objects.filter(app=app, trigger=Script.SAVE, enabled=True)}
        has_global_save = Script.objects.filter(app=app, trigger=Script.SAVE, enabled=True, entity__isnull=True).exists()
        for slug in order:
            entity = entities[slug]
            fields = {f.key: f for f in entity.fields.all()}
            created[slug] = []
            run_scripts = has_global_save or entity.pk in save_scripts
            for row in rows_by_table[slug]:
                values = {}
                for key, value in row.items():
                    f = fields.get(key)
                    if f is None:
                        continue
                    if f.type == Field.DATE and isinstance(value, str) and DATUM.match(value):
                        value = (today + timedelta(days=int(DATUM.match(value).group(1)))).isoformat()
                    elif f.type == Field.REFERENCE and isinstance(value, str) and VERWEIS.match(value):
                        target = created.get(f.reference.slug if f.reference else "", [])
                        index = int(VERWEIS.match(value).group(1)) - 1
                        value = str(target[index]) if 0 <= index < len(target) else ""
                    values[key] = value
                record = Record.objects.create(entity=entity, data=values)
                if run_scripts:
                    triggers.on_save(record, True, None)
                created[slug].append(record.pk)
                count += 1
        return count
