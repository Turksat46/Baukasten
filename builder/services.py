"""Web-Requests für Bausteine und Erweiterungen.

Aufrufe gehen nur an Hosts aus der Einstellung HTTP_ALLOWED_HOSTS. So kann
niemand über den Designer beliebige interne Adressen abfragen.
"""
import ipaddress
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils.translation import gettext as _


class HttpNotAllowed(Exception):
    pass


def _is_forbidden_host(hostname):
    host = (hostname or "").strip().lower()
    if host in ("localhost", "metadata.google.internal"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_loopback or ip.is_link_local or ip.is_unspecified
    except ValueError:
        return False


def http_request(method, url, **kwargs):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HttpNotAllowed(_("Nur http- und https-Adressen sind erlaubt."))
    if _is_forbidden_host(parsed.hostname) or parsed.hostname not in settings.BAUKASTEN_HTTP_ALLOWED_HOSTS:
        raise HttpNotAllowed(
            _("Der Host „%(host)s“ ist nicht freigegeben (Einstellung HTTP_ALLOWED_HOSTS).") % {"host": parsed.hostname}
        )
    kwargs.setdefault("timeout", settings.BAUKASTEN_HTTP_TIMEOUT)
    kwargs.setdefault("allow_redirects", False)
    return requests.request(method, url, **kwargs)


def http_json(url, method="GET", **kwargs):
    response = http_request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()
