"""Über den Baukasten: Version, Umgebung und Release Notes (/ueber/)."""
import platform as python_platform

import django
import markdown
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render

from .sanitize import sanitize_html

LATEST_KEY = "baukasten-latest-release"


def render_markdown(text):
    """Markdown der Release Notes als sicheres HTML (kein eigenes HTML, keine Skripte)."""
    html = markdown.markdown(text or "", extensions=["sane_lists"])
    return sanitize_html(html)


def latest_release():
    """Neueste veröffentlichte Release Note (Version), 60 Sekunden zwischengespeichert. Für den Hinweis „neu“."""
    value = cache.get(LATEST_KEY)
    if value is None:
        from .models import ReleaseNote

        note = ReleaseNote.objects.filter(published=True).values_list("version", flat=True).first()
        value = note or ""
        cache.set(LATEST_KEY, value, 60)
    return value


def forget(**kwargs):
    cache.delete(LATEST_KEY)


@login_required
def about(request):
    from .models import ReleaseNote
    from .versions import FORMAT_VERSION

    notes = ReleaseNote.objects.all() if request.user.is_superuser else ReleaseNote.objects.filter(published=True)
    notes = list(notes[:30])
    for note in notes:
        note.html = render_markdown(note.body)
    return render(request, "builder/about.html", {
        "version": settings.BAUKASTEN_VERSION,
        "notes": notes,
        "facts": [
            ("Django", django.get_version()),
            ("Python", python_platform.python_version()),
            ("Format der App-Dateien", FORMAT_VERSION),
        ],
        "latest": latest_release(),
    })
