import importlib
import logging
import pkgutil

from django.apps import AppConfig

log = logging.getLogger(__name__)


class BuilderConfig(AppConfig):
    name = "builder"
    verbose_name = "Baukasten"

    def ready(self):
        """Verbindet die Standardgruppen und lädt die Python-Dateien aus dem Ordner „extensions“."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.signals import user_logged_in
        from django.db.models.signals import post_save

        from . import accounts, audit

        post_save.connect(accounts.on_user_saved, sender=get_user_model(), dispatch_uid="baukasten-standardgruppen")
        user_logged_in.connect(accounts.on_login, dispatch_uid="baukasten-standardgruppen-login")
        audit.connect()  # Änderungsprotokoll

        from . import platform
        from .models import PlatformSettings

        post_save.connect(platform.forget, sender=PlatformSettings, dispatch_uid="baukasten-einstellungen")

        from django.db.models.signals import post_delete

        from . import about
        from .models import ReleaseNote

        post_save.connect(about.forget, sender=ReleaseNote, dispatch_uid="baukasten-release-notes")
        post_delete.connect(about.forget, sender=ReleaseNote, dispatch_uid="baukasten-release-notes-del")

        from django.db.models.signals import post_migrate

        from . import release_notes

        # Release Notes aus CHANGELOG.md: läuft beim Ausrollen im Migrations-Job mit.
        post_migrate.connect(release_notes.on_post_migrate, sender=self, dispatch_uid="baukasten-release-notes-sync")
        _register_checks()

        try:
            import extensions
        except ImportError:
            return
        for module in pkgutil.iter_modules(extensions.__path__):
            try:
                importlib.import_module(f"extensions.{module.name}")
            except Exception:  # eine kaputte Erweiterung darf den Start nicht verhindern
                log.exception("Erweiterung %s konnte nicht geladen werden", module.name)


def _register_checks():
    import os
    from django.conf import settings
    from django.core.checks import Tags, Warning, register

    @register(Tags.security, deploy=True)
    def check_production_database(app_configs, **kwargs):
        warnings = []
        engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
        allow_sqlite = os.environ.get("ALLOW_SQLITE_IN_PROD", "").strip().lower() in ("1", "true", "yes", "on")
        if not settings.DEBUG and engine.endswith("sqlite3") and not allow_sqlite:
            warnings.append(Warning(
                "SQLite ist im Produktivbetrieb (DEBUG=0) aktiv.",
                hint="DATABASE_URL für PostgreSQL setzen oder ALLOW_SQLITE_IN_PROD=1 angeben.",
                id="builder.W001",
            ))
        return warnings
