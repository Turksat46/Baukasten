"""Einstellungen für gunicorn im Container. Alle Werte lassen sich per Umgebungsvariable ändern.

Threads statt nur Prozesse: Wartet eine Anfrage auf eine langsame Datenquelle, bedienen
die anderen Threads desselben Prozesses weiter Seiten. Gleichzeitige Anfragen je Pod:
GUNICORN_WORKERS × GUNICORN_THREADS (Standard 3 × 4 = 12).

Jeder Thread hält eine eigene Datenbankverbindung (DB_CONN_MAX_AGE). Für PostgreSQL gilt also
grob: Pods × Workers × Threads + Hintergrund-Job < max_connections (Standard 100).
"""
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
# Muss über QUERY_TIMEOUT liegen, sonst bricht gunicorn wartende Abfragen vorher ab.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
# Prozesse regelmäßig erneuern: hält den Speicherverbrauch über Wochen stabil.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "2000"))
max_requests_jitter = 200
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
