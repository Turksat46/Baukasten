"""Adresse der Seite, zu der ein Baustein gehört.

Bausteine werden nicht nur mit ihrer Seite gerendert, sondern auch einzeln über
`/a/<app>/p/<seite>/b/<baustein>/` (Widgets auf der Startseite, Neuladen nach Schiebereglern
und automatischer Aktualisierung). Links und Rücksprünge (Filter per Klick, `next=`) müssen
trotzdem auf die Seite zeigen, nicht auf diese Einzeladresse: Dort gibt es nur das nackte HTML
des Bausteins ohne Layout und CSS.

Darum nie `request.path` oder `request.get_full_path()` für Links in Bausteinen verwenden,
sondern `page_path()` und `page_url()`.
"""

_ATTR = "baukasten_page_path"


def set_page_path(request, path):
    """Vom Einzel-Endpunkt aufgerufen: Links des Bausteins zeigen danach auf `path`."""
    setattr(request, _ATTR, path)


def page_path(request):
    """Pfad der Seite ohne Parameter."""
    return getattr(request, _ATTR, None) or getattr(request, "path", "") or ""


def page_url(request):
    """Pfad der Seite mit den aktuellen Parametern (Filter, Seite der Tabelle, …)."""
    path = page_path(request)
    get = getattr(request, "GET", None)
    query = get.urlencode() if get is not None else ""
    return f"{path}?{query}" if query else path
