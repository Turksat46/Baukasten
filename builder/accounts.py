"""Standardgruppen für alle Nutzer.

Jede Person gehört automatisch zu den Gruppen aus der Einstellung DEFAULT_USER_GROUPS
(Standard: „Viewer“): beim Anlegen, bei jeder Anmeldung und beim Abgleich mit
Keycloak. Gibt es eine Gruppe noch nicht, wird sie leer angelegt; ihre Rechte
vergibt man unter /admin/ → Gruppen.
"""
from django.conf import settings
from django.contrib.auth.models import Group


def default_groups():
    return [Group.objects.get_or_create(name=name[:150])[0] for name in settings.DEFAULT_USER_GROUPS]


def add_default_groups(user):
    groups = default_groups()
    if groups:
        user.groups.add(*groups)


def on_user_saved(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        add_default_groups(instance)


def on_login(sender, request, user, **kwargs):
    add_default_groups(user)
