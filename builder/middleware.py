from django.http import HttpResponse

from . import app_i18n


class AppTranslationMiddleware:
    """Setzt die Übersetzungen der App je Anfrage zurück (Threads werden wiederverwendet)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        app_i18n.reset()
        try:
            return self.get_response(request)
        finally:
            app_i18n.reset()


class HealthCheckMiddleware:
    """Beantwortet /healthz vor der Host-Prüfung, damit Kubernetes-Probes immer durchkommen."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        if request.path == "/readyz":
            from django.db import connection

            try:
                connection.ensure_connection()
            except Exception:
                return HttpResponse("error", status=503, content_type="text/plain")
            return HttpResponse("ok", content_type="text/plain")
        if request.path == "/metrics":  # Prometheus fragt Pods direkt ab, ohne bekannten Hostnamen
            from .metrics import response

            return response(request)
        return self.get_response(request)
