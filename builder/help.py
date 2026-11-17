"""Hilfe: zeigt das Handbuch in der Oberfläche an."""
from functools import lru_cache
from pathlib import Path

import markdown
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.translation import get_language
from django.utils.safestring import mark_safe
from markdown.extensions.toc import slugify_unicode

HANDBOOK = Path(settings.BASE_DIR) / "docs" / "HANDBUCH.md"
HANDBOOK_EN = Path(settings.BASE_DIR) / "docs" / "HANDBOOK.en.md"


@lru_cache(maxsize=8)
def _render(path, mtime):
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": slugify_unicode, "toc_depth": "2-3"}},
    )
    text = path.read_text(encoding="utf-8")
    # Erste Überschrift steht schon im Seitenkopf.
    if text.startswith("# "):
        text = text.split("\n", 1)[1]
    html = md.convert(text)
    return html, md.toc_tokens


def handbook(language=None):
    """Gibt (html, toc_tokens, language) zurück; neu gerendert bei Dateiänderung."""
    language = (language or get_language() or "de").split("-", 1)[0]
    path = HANDBOOK_EN if language == "en" else HANDBOOK
    if not path.exists():
        path = HANDBOOK
        language = "de"
    if not path.exists():
        return "", [], language
    html, toc = _render(path, path.stat().st_mtime_ns)
    return html, toc, language


@login_required
def help_page(request):
    html, toc, language = handbook()
    return render(request, "builder/help.html", {
        "handbook": mark_safe(html), "toc": toc, "handbook_language": language,
    })
