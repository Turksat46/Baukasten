"""Richtet eine frische Installation ein: Verwalter-Konto und Beispiel-Apps.

Wird von k8s/lokal/deploy.ps1 nach jedem Ausrollen aufgerufen und darf beliebig oft laufen:
Vorhandenes bleibt unverändert. Name und Passwort des Verwalters kommen aus den
Umgebungsvariablen ADMIN_USERNAME und ADMIN_PASSWORD (lokal aus k8s/lokal/geheim.env).
"""
import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Legt Verwalter-Konto und Beispiel-Apps an, falls sie fehlen."

    def add_arguments(self, parser):
        parser.add_argument("--ohne-beispiele", action="store_true", help="Keine Beispiel-Apps anlegen.")

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Verwalter „{username}“ gibt es schon; Passwort bleibt unverändert.")
        else:
            if not password:
                raise CommandError("ADMIN_PASSWORD ist nicht gesetzt.")
            User.objects.create_superuser(username=username, email="", password=password)
            self.stdout.write(self.style.SUCCESS(f"Verwalter „{username}“ angelegt."))
        if not options["ohne_beispiele"]:
            call_command("demo", stdout=self.stdout)
            call_command("beispiel_einwilligung", stdout=self.stdout)
