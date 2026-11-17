"""Tableau-Dashboards in Seiten einbetten (Baustein „Tableau-Ansicht“).

Eingebettet wird mit der offiziellen Embedding API v3 von Tableau. Das Skript
kommt vom selben Tableau-Server wie das Dashboard.

Einstellungen (Umgebungsvariablen, siehe Handbuch „Tableau“):

    TABLEAU_HOSTS                  erlaubte Tableau-Server, kommagetrennt (z. B. tableau.firma.de)
    TABLEAU_CONNECTED_APP_CLIENT_ID, TABLEAU_CONNECTED_APP_SECRET_ID, TABLEAU_CONNECTED_APP_SECRET_VALUE
                                   optional: Anmeldung über eine Connected App (Direct Trust).
                                   Ohne diese Werte melden sich Nutzer selbst bei Tableau an.
    TABLEAU_USER_ATTRIBUTE         "email" (Standard) oder "username": womit Personen in Tableau heißen

Mit Connected App stellt der Baukasten für jede angemeldete Person ein kurzlebiges
Token (JWT, 5 Minuten, nur zum Einbetten) aus. Gäste auf öffentlichen Seiten
bekommen nie ein Token und sehen keine Tableau-Ansichten.
"""
import base64
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlparse

from django.conf import settings

TOKEN_SECONDS = 300
SCOPES = ["tableau:views:embed"]


def host_of(url):
    """Host einer erlaubten https-Adresse, sonst None."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return parsed.hostname if parsed.hostname in settings.BAUKASTEN_TABLEAU_HOSTS else None


def script_url(host):
    return f"https://{host}/javascripts/api/tableau.embedding.3.latest.min.js"


def connected_app_configured():
    return all((settings.BAUKASTEN_TABLEAU_CLIENT_ID, settings.BAUKASTEN_TABLEAU_SECRET_ID,
                settings.BAUKASTEN_TABLEAU_SECRET_VALUE))


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def user_name(user):
    """Name der Person in Tableau: E-Mail oder Benutzername (TABLEAU_USER_ATTRIBUTE)."""
    if settings.BAUKASTEN_TABLEAU_USER_ATTRIBUTE == "username":
        return user.get_username()
    return user.email or ""


def connected_app_token(user, now=None):
    """JWT für Tableau Connected Apps (Direct Trust, HS256) oder None."""
    if not connected_app_configured() or user is None or not user.is_authenticated:
        return None
    subject = user_name(user)
    if not subject:
        return None
    now = int(now or time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": settings.BAUKASTEN_TABLEAU_SECRET_ID,
              "iss": settings.BAUKASTEN_TABLEAU_CLIENT_ID}
    payload = {"iss": settings.BAUKASTEN_TABLEAU_CLIENT_ID, "aud": "tableau", "sub": subject,
               "jti": str(uuid.uuid4()), "iat": now, "exp": now + TOKEN_SECONDS, "scp": SCOPES}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(settings.BAUKASTEN_TABLEAU_SECRET_VALUE.encode(), signing_input.encode(), hashlib.sha256)
    return f"{signing_input}.{_b64(signature.digest())}"
