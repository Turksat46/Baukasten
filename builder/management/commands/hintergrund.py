"""Führt fällige Hintergrundarbeiten aus: zeitgesteuerte Skripte und Abgleiche mit Datenquellen.

Im Betrieb regelmäßig aufrufen, z. B. jede Minute als Kubernetes-CronJob (k8s/cronjob.yaml):
    python manage.py hintergrund

Beim Entwickeln in einem zweiten Terminal dauerhaft laufen lassen:
    python manage.py hintergrund --dauerhaft
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from builder.datasources import sync_and_record
from builder.models import DataQuery
from builder.scripting.triggers import run_due


class Command(BaseCommand):
    help = "Führt fällige zeitgesteuerte Skripte und Abgleiche mit Datenquellen aus."

    def add_arguments(self, parser):
        parser.add_argument("--dauerhaft", action="store_true",
                            help="Nicht beenden, sondern alle 30 Sekunden erneut prüfen (für die Entwicklung).")
        parser.add_argument("--pause", type=int, default=30, help="Sekunden zwischen zwei Durchläufen.")

    def handle(self, *args, **options):
        if not options["dauerhaft"]:
            self.run_once()
            return
        self.stdout.write("Läuft dauerhaft. Beenden mit Strg+C.")
        try:
            while True:
                close_old_connections()
                self.run_once()
                time.sleep(max(options["pause"], 5))
        except KeyboardInterrupt:
            self.stdout.write("Beendet.")

    def run_once(self):
        now = timezone.now()
        scripts = run_due(now)
        syncs = failed = 0
        for query in DataQuery.objects.filter(sync_interval__gt=0).select_related("app", "sync_entity"):
            if query.last_sync_at and query.last_sync_at + timedelta(minutes=query.sync_interval) > now:
                continue
            syncs += 1
            if not sync_and_record(query):
                failed += 1
                self.stderr.write(f"Abgleich {query.app.slug}/{query.slug}: {query.last_sync_message}")
        stamp = timezone.localtime(now).strftime("%H:%M:%S")
        self.stdout.write(f"{stamp} {scripts} Skripte ausgeführt, {syncs} Abgleiche ({failed} fehlgeschlagen).")
