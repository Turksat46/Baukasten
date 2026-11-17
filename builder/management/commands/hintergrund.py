"""Hintergrunddienst des Baukastens.

Dauerhaft (empfohlen, Kubernetes: Deployment baukasten-worker in k8s/worker.yaml; lokal in einem
zweiten Terminal):
    python manage.py hintergrund --dauerhaft
Startet den Aufseher für Automatisierungen (lange und ständig laufende Python-Skripte) und
erledigt alle 30 Sekunden die übrigen Hintergrundarbeiten: zeitgesteuerte Skripte normaler Apps
und Abgleiche mit Datenquellen.

Einmal (z. B. als CronJob, wie bis Version 1): nur die übrigen Hintergrundarbeiten, keine
Automatisierungen.
    python manage.py hintergrund
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from builder.scripting.worker import Worker, background_once


class Command(BaseCommand):
    help = "Hintergrunddienst: Automatisierungen, zeitgesteuerte Skripte und Abgleiche mit Datenquellen."

    def add_arguments(self, parser):
        parser.add_argument("--dauerhaft", action="store_true",
                            help="Als Dienst laufen (mit Automatisierungen). Beenden mit Strg+C oder SIGTERM.")
        parser.add_argument("--parallel", type=int, default=0,
                            help="Gleichzeitige Läufe von Automatisierungen (Standard: AUTOMATION_PARALLEL).")

    def handle(self, *args, **options):
        if options["dauerhaft"]:
            Worker(parallel=options["parallel"] or None, out=self.stdout).serve()
            return
        scripts, syncs, failed = background_once()
        stamp = timezone.localtime().strftime("%H:%M:%S")
        self.stdout.write(f"{stamp} {scripts} Skripte ausgeführt, {syncs} Abgleiche ({failed} fehlgeschlagen). "
                          "Automatisierungen laufen nur mit --dauerhaft.")
