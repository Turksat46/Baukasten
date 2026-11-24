"""Alarmierung bei Fehlern im Hintergrunddienst (Teams, E-Mail oder API-Call).

Konfigurierbar ohne Neustart über PlatformSettings (/admin/) oder über die Umgebung:
  ALERT_CHANNEL=off | teams | email | api
  ALERT_TARGET=<Teams-Webhook-URL, E-Mail-Adresse oder API-Endpunkt>
  ALERT_AUTH_HEADER=<optionaler Authorization-Header für API-Call>
  ALERT_REPEAT_MINUTES=<derselbe Fehler höchstens einmal in dieser Zeit, Standard 60, 0 = immer>
"""
import hashlib
import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext as _

from . import platform

log = logging.getLogger(__name__)


def notify_failure(source, title, details, app=None):
    """Sendet eine Fehlermeldung an den eingestellten Kanal. Darf den Aufrufer nie zum Absturz bringen."""
    try:
        channel = str(platform.value("alert_channel") or "off").strip().lower()
        target = str(platform.value("alert_target") or "").strip()
        auth_header = str(platform.value("alert_auth_header") or "").strip()
    except Exception:  # noqa: BLE001
        return False

    if channel in ("", "off") or not target:
        return False

    app_name = app.name if app else ""
    app_slug = app.slug if app else ""

    # Derselbe Fehler (Quelle, Titel, App) nur einmal je Zeitraum: Ein minütlich laufendes Skript,
    # das dauerhaft scheitert, würde sonst jede Minute eine Nachricht schicken.
    repeat = int(getattr(settings, "BAUKASTEN_ALERT_REPEAT_MINUTES", 60) or 0)
    if repeat > 0:
        digest = hashlib.sha256(f"{source}|{title}|{app_slug}".encode()).hexdigest()[:32]
        if not cache.add(f"baukasten-alarm-{digest}", 1, timeout=repeat * 60):
            return False
    full_title = f"[{app_name}] {title}" if app_name else title

    try:
        if channel == "teams":
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "themeColor": "D9480F",
                "summary": full_title,
                "title": _("Baukasten-Alarm: %(title)s") % {"title": full_title},
                "sections": [
                    {
                        "facts": [
                            {"name": _("Quelle"), "value": source},
                            *([{"name": _("App"), "value": f"{app_name} ({app_slug})"}] if app_slug else []),
                            {"name": _("Zeitpunkt"), "value": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")},
                        ],
                        "text": str(details or "")[:4000],
                    }
                ],
            }
            resp = requests.post(target, json=payload, timeout=5)
            resp.raise_for_status()
            return True

        if channel == "email":
            recipients = [addr.strip() for addr in target.replace(";", ",").split(",") if addr.strip()]
            if not recipients:
                return False
            body = (
                f"{full_title}\n"
                f"Quelle: {source}\n"
                f"Zeitpunkt: {timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{str(details or '')[:10000]}"
            )
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "baukasten@localhost")
            send_mail(f"[Baukasten] {full_title}", body, from_email, recipients, fail_silently=False)
            return True

        if channel == "api":
            headers = {"Content-Type": "application/json"}
            if auth_header:
                headers["Authorization"] = auth_header
            payload = {
                "event": "baukasten.failure",
                "source": source,
                "app": app_slug or None,
                "app_name": app_name or None,
                "title": title,
                "details": str(details or "")[:10000],
                "timestamp": timezone.now().isoformat(),
            }
            resp = requests.post(target, json=payload, headers=headers, timeout=5)
            resp.raise_for_status()
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Alarmierung (%s -> %s) fehlgeschlagen: %s", channel, target, exc)
    return False
