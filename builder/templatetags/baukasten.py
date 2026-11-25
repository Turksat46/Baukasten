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


@register.simple_tag(takes_context=True)
def tour(context, tour_id):
    """Gibt die Schritte einer Führung als JSON aus; tour.js liest sie von dort.

    Für Angemeldete steht dabei, ob sie die Führung schon gesehen haben, und wohin
    tour.js das meldet. Gäste merken es sich nur im Browser."""
    script = json_script(TOURS[tour_id], "tour-steps")
    request = context.get("request")
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return format_html('<span id="tour-id" data-tour-id="{}" hidden></span>{}', tour_id, script)
    from django.middleware.csrf import get_token
    from django.urls import reverse

    from ..models import TourSeen

    seen = TourSeen.objects.filter(user=user, tour_id=tour_id).exists()
    return format_html(
        '<span id="tour-id" data-tour-id="{}" data-seen="{}" data-save-url="{}" data-csrf="{}" hidden></span>{}',
        tour_id, "1" if seen else "0", reverse("tour_seen", args=[tour_id]), get_token(request), script)


@register.simple_tag
def admin_app_overview():
    """Apps mit Zahlen für die Startseite der Verwaltung."""
    from django.db.models import Count

    from ..models import App

    return App.objects.annotate(
        n_tables=Count("entities", distinct=True), n_records=Count("entities__records", distinct=True),
        n_pages=Count("pages", distinct=True), n_scripts=Count("scripts", distinct=True),
    ).order_by("name")


@register.filter
def duration_ms(value):
    """Laufdauer lesbar: 850 ms, 12 s, 3 min 20 s, 1 h 5 min."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return ""
    if ms < 1000:
        return f"{ms} ms"
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s" if seconds else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"
