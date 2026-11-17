"""Legt die Tabelle für den gemeinsamen Zwischenspeicher an, falls CACHE_BACKEND=database.

Ohne Redis teilen sich alle Pods darüber Abfrage-Ergebnisse, Sperren und das Limit je
Datenquelle. Der Befehl ist idempotent; bei Redis oder lokal (Arbeitsspeicher) tut er nichts.
"""
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [("builder", "0005_deutsche_namen")]
    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
