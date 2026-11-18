from functools import lru_cache
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.staticfiles import finders

from .models import can_design

BRAND_LOGO_CANDIDATES = ["builder/brand/logo.svg", "builder/brand/logo.png"]


@lru_cache(maxsize=1)
def _brand_logo_cached():
    return next((path for path in BRAND_LOGO_CANDIDATES if finders.find(path)), "")


def brand_logo():
    """Firmenlogo, falls eine Datei unter static/builder/brand/ liegt (siehe LIESMICH dort)."""
    if settings.DEBUG:  # beim Entwickeln ohne Neustart sichtbar
        _brand_logo_cached.cache_clear()
    return _brand_logo_cached()


def shell(request):
    """Werte, die jede Seite für Kopfzeile und Anmeldung braucht."""
    user = getattr(request, "user", None)
    name = ""
    if user is not None and user.is_authenticated:
        name = user.get_full_name() or user.get_username()
    parts = name.replace(".", " ").replace("_", " ").split()
    initials = "".join(p[0] for p in parts[:2]).upper() or "?"
    designer = can_design(user) if user is not None else False
    coach = None
    if designer and not request.path.startswith(("/admin/", "/api/", "/mcp/", "/skript-sandbox/")):
        # Einmal je Anfrage: Bausteine werden einzeln mit diesem Kontext gerendert.
        if not hasattr(request, "_baukasten_coach"):
            from .tutorial import state

            coach = state(user)
            if coach and not coach["finished"]:
                # Schon auf der Seite des Schritts? Dann „Zeig mir wo“ statt „Hierhin“.
                coach["here"] = request.path == urlparse(coach["url"]).path
            request._baukasten_coach = coach
        coach = request._baukasten_coach
    return {
        "can_design": designer,
        "coach": coach,
        "display_name": name,
        "first_name": (user.first_name if user is not None and user.is_authenticated else "") or name,
        "initials": initials,
        "oidc_enabled": settings.OIDC_ENABLED,
        "oidc_only": settings.OIDC_ONLY,
        "brand_logo": brand_logo(),
        "baukasten_version": settings.BAUKASTEN_VERSION,
        "latest_release": _latest_release(user),
    }


def _latest_release(user):
    if user is None or not user.is_authenticated:
        return ""
    from .about import latest_release

    return latest_release()
