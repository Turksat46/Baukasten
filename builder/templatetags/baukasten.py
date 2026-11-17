import functools
import hashlib
import time
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django import template
from django.utils.html import format_html, json_script

from ..tours import TOURS

register = template.Library()


@register.filter
def tr(text, app=None):
    """Text einer App in der Sprache der Person: {{ entity.name|tr }} oder {{ app.name|tr:app }}."""
    from ..app_i18n import t

    return t(text, app)


@functools.lru_cache(maxsize=64)
def _asset_version(path, _debug_tick):
    found = finders.find(path)
    if not found:
        return ""
    return hashlib.md5(Path(found).read_bytes()).hexdigest()[:10]


@register.simple_tag
def asset(path):
    """Statische Datei mit Versionsnummer, damit Browser nach Updates neu laden."""
    tick = int(time.time() // 5) if settings.DEBUG else 0
    version = _asset_version(path, tick)
    url = static(path)
    return f"{url}?v={version}" if version else url


@register.simple_tag
def tour(tour_id):
    """Gibt die Schritte einer Führung als JSON aus; tour.js liest sie von dort."""
    script = json_script(TOURS[tour_id], "tour-steps")
    return format_html('<span id="tour-id" data-tour-id="{}" hidden></span>{}', tour_id, script)


@register.simple_tag
def admin_app_overview():
    """Apps mit Zahlen für die Startseite der Verwaltung."""
    from django.db.models import Count

    from ..models import App

    return App.objects.annotate(
        n_tables=Count("entities", distinct=True), n_records=Count("entities__records", distinct=True),
        n_pages=Count("pages", distinct=True), n_scripts=Count("scripts", distinct=True),
    ).order_by("name")
