"""Fachliche Einstellungen: Wert aus der Datenbank (PlatformSettings, änderbar unter /admin/),
sonst aus der Umgebung (settings.py).

    from builder import platform
    platform.value("public_rate")

Der Datensatz wird 30 Sekunden im gemeinsamen Cache gehalten; Speichern leert den Cache, damit
eine Änderung in allen Pods schnell ankommt.
"""
from django.conf import settings
from django.core.cache import cache

CACHE_KEY = "baukasten-platform-settings"
CACHE_SECONDS = 30

# Feld in PlatformSettings -> Einstellung in settings.py (Standard aus der Umgebung)
FALLBACK = {
    "public_rate": "BAUKASTEN_PUBLIC_RATE",
    "ai_writes": "BAUKASTEN_AI_WRITES",
    "audit_retention_days": "BAUKASTEN_AUDIT_RETENTION_DAYS",
    "script_timeout": "BAUKASTEN_SCRIPT_TIMEOUT",
    "script_max_calls": "BAUKASTEN_SCRIPT_MAX_CALLS",
    "automation_max_timeout_minutes": "BAUKASTEN_AUTOMATION_MAX_TIMEOUT_MINUTES",
    "alert_channel": "BAUKASTEN_ALERT_CHANNEL",
    "alert_target": "BAUKASTEN_ALERT_TARGET",
    "alert_auth_header": "BAUKASTEN_ALERT_AUTH_HEADER",
}


def _overrides():
    """Nur die gesetzten Felder, z. B. {"public_rate": 60}."""
    values = cache.get(CACHE_KEY)
    if values is None:
        from .models import PlatformSettings

        row = PlatformSettings.objects.filter(pk=1).values(*FALLBACK).first() or {}
        values = {k: v for k, v in row.items() if v is not None and v != ""}
        cache.set(CACHE_KEY, values, CACHE_SECONDS)
    return values


def value(name):
    if name not in FALLBACK:
        raise KeyError(name)
    overrides = _overrides()
    return overrides[name] if name in overrides else getattr(settings, FALLBACK[name])


def default(name):
    """Wert aus der Umgebung, für die Anzeige unter /admin/."""
    return getattr(settings, FALLBACK[name])


def forget(**kwargs):
    cache.delete(CACHE_KEY)
