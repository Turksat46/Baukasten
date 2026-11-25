"""Gemeinsame Grundlagen der Tests: Testdaten (Base) und Datenquellen (DataSourceBase)."""

import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from ..models import App

BUILDER_DIR = Path(__file__).resolve().parent.parent
_DEMO_DIR = tempfile.mkdtemp(prefix="baukasten-test-")


@override_settings(DEMO_DATASOURCE_FILE=Path(_DEMO_DIR) / "demo-datenquelle.sqlite3")
class Base(TestCase):
    def setUp(self):
        self.designer = User.objects.create_user("designer", password="x", is_staff=True)
        self.user = User.objects.create_user("nutzer", password="x")
        call_command("demo", verbosity=0)
        self.app = App.objects.get(slug="inventar")
        self.entity = self.app.entities.get()


class DataSourceBase(Base):
    """Legt eine kleine SQLite-Datenquelle „lager“ an."""

    def setUp(self):
        super().setUp()
        import sqlite3
        import tempfile
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.addCleanup(lambda: __import__("os").unlink(handle.name))
        conn = sqlite3.connect(handle.name)
        conn.execute("CREATE TABLE teile (nr TEXT, name TEXT, bestand INTEGER, preis REAL, datum TEXT, aktiv BOOLEAN)")
        conn.executemany("INSERT INTO teile VALUES (?, ?, ?, ?, ?, ?)", [
            ("A1", "Schraube", 120, 0.15, "2026-01-02", 1), ("A2", "Mutter", 80, 0.1, "2026-02-03", 1),
            ("B7", "Welle", 4, 31.5, "2026-03-04", 0)])
        conn.commit()
        conn.close()
        self.settings_override = override_settings(BAUKASTEN_DATASOURCES={"lager": f"sqlite:///{handle.name}"})
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
