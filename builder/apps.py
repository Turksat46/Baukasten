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

        from . import accounts

        post_save.connect(accounts.on_user_saved, sender=get_user_model(), dispatch_uid="baukasten-standardgruppen")
        user_logged_in.connect(accounts.on_login, dispatch_uid="baukasten-standardgruppen-login")

        try:
            import extensions
        except ImportError:
            return
        for module in pkgutil.iter_modules(extensions.__path__):
            try:
                importlib.import_module(f"extensions.{module.name}")
            except Exception:  # eine kaputte Erweiterung darf den Start nicht verhindern
                log.exception("Erweiterung %s konnte nicht geladen werden", module.name)
