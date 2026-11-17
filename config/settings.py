"""Einstellungen. Alles Umgebungsabhängige kommt aus Umgebungsvariablen (siehe README)."""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY") or ("nur-fuer-lokale-entwicklung" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY fehlt. Lokal: DEBUG=1 setzen. Produktiv: SECRET_KEY setzen.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "builder",  # vor admin, damit eigene Vorlagen (Anmeldung, Admin-Startseite) Vorrang haben
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "builder.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "builder.middleware.AppTranslationMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "builder.context.shell",
            ],
        },
    },
]

# Lokal SQLite, produktiv PostgreSQL über DATABASE_URL=postgres://user:pass@host:5432/db
# Jeder gunicorn-Thread hält eine eigene Verbindung offen. Pro Pod also bis zu
# GUNICORN_WORKERS × GUNICORN_THREADS Verbindungen – bei der Größe von PostgreSQL
# (max_connections) mitrechnen, siehe Handbuch „Skalierung“.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}

# Zwischenspeicher, gemeinsam für alle Pods: Ergebnisse von Abfragen, Sperren gegen
# Mehrfachabfragen und das Limit je Datenquelle hängen daran.
#   REDIS_URL gesetzt  -> Redis (empfohlen ab mehreren Pods mit viel Last)
#   sonst produktiv    -> Tabelle in der eigenen Datenbank (kein zusätzlicher Dienst nötig)
#   lokal mit DEBUG    -> Arbeitsspeicher des Prozesses
REDIS_URL = os.environ.get("REDIS_URL", "")
CACHE_BACKEND = os.environ.get("CACHE_BACKEND", "redis" if REDIS_URL else ("memory" if DEBUG else "database"))
if CACHE_BACKEND == "redis":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                          "LOCATION": REDIS_URL, "KEY_PREFIX": "baukasten", "TIMEOUT": 300}}
elif CACHE_BACKEND == "database":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache",
                          "LOCATION": "baukasten_cache", "TIMEOUT": 300,
                          "OPTIONS": {"MAX_ENTRIES": 20000, "CULL_FREQUENCY": 4}}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                          "LOCATION": "baukasten", "TIMEOUT": 300}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"

# Deutsch ist die Ausgangssprache der Texte, Englisch liegt als Übersetzung bei
# (builder/locale/en). Die Sprache folgt der Wahl des Nutzers, sonst dem Browser.
LANGUAGE_CODE = "de"
LANGUAGES = [("de", "Deutsch"), ("en", "English")]
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

if not DEBUG:
    # Hinter dem Ingress: TLS endet dort, die App sieht den Header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("COOKIE_SECURE", True)

# Gruppen, zu denen jede Person automatisch gehört (kommagetrennt). Leer lassen: keine.
DEFAULT_USER_GROUPS = env_list("DEFAULT_USER_GROUPS", "Viewer")

# Anmeldung über Keycloak (OpenID Connect). Ohne diese Variablen gilt die lokale Anmeldung.
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "").rstrip("/")  # z. B. https://keycloak.example.com/realms/firma
OIDC_ENABLED = bool(OIDC_ISSUER and os.environ.get("OIDC_CLIENT_ID"))
OIDC_ONLY = OIDC_ENABLED and env_bool("OIDC_ONLY", False)  # lokale Anmeldung ausblenden
OIDC_GROUPS_CLAIM = os.environ.get("OIDC_GROUPS_CLAIM", "groups")
OIDC_DESIGNER_ROLE = os.environ.get("OIDC_DESIGNER_ROLE", "baukasten-designer")
if OIDC_ENABLED:
    INSTALLED_APPS.append("mozilla_django_oidc")
    AUTHENTICATION_BACKENDS = [
        "builder.auth.KeycloakBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
    _oidc = f"{OIDC_ISSUER}/protocol/openid-connect"
    OIDC_RP_CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
    OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc}/auth"
    OIDC_OP_TOKEN_ENDPOINT = f"{_oidc}/token"
    OIDC_OP_USER_ENDPOINT = f"{_oidc}/userinfo"
    OIDC_OP_JWKS_ENDPOINT = f"{_oidc}/certs"
    OIDC_OP_LOGOUT_ENDPOINT = f"{_oidc}/logout"
    OIDC_RP_SIGN_ALGO = "RS256"
    OIDC_RP_SCOPES = os.environ.get("OIDC_SCOPES", "openid email profile")
    OIDC_STORE_ID_TOKEN = True
    OIDC_OP_LOGOUT_URL_METHOD = "builder.auth.provider_logout"
    OIDC_TIMEOUT = 10

# Skripte (siehe Handbuch, Abschnitt „Skripte“)
BAUKASTEN_SCRIPT_TIMEOUT = float(os.environ.get("SCRIPT_TIMEOUT", "10"))
BAUKASTEN_SCRIPT_MEMORY_MB = int(os.environ.get("SCRIPT_MEMORY_MB", "512"))
BAUKASTEN_SCRIPT_MAX_CALLS = int(os.environ.get("SCRIPT_MAX_CALLS", "1000"))

# Öffentliche Seiten: höchstens so viele Anfragen von Gästen je Adresse und Minute (0 = keine Grenze).
# Hinter einem Ingress teilen sich Gäste oft eine Adresse – dann großzügig wählen.
BAUKASTEN_PUBLIC_RATE = int(os.environ.get("PUBLIC_RATE", "120"))

# Externe Datenquellen unter Last (siehe builder/datasources.py und Handbuch „Skalierung“):
# Zeitlimit für Abfragen, auf die eine Seite wartet. Muss unter GUNICORN_TIMEOUT liegen.
BAUKASTEN_QUERY_TIMEOUT = int(os.environ.get("QUERY_TIMEOUT", "25"))
# Zeitlimit für das Spiegeln im Hintergrund (darf ein schlafendes Warehouse wecken).
BAUKASTEN_SYNC_TIMEOUT = int(os.environ.get("SYNC_TIMEOUT", "300"))
# Höchstens so viele Abfragen laufen gleichzeitig je Datenquelle – im ganzen Cluster,
# nicht pro Pod. Je Quelle überschreibbar: QUERY_PARALLEL_<NAME>=… (z. B. QUERY_PARALLEL_DWH=2)
BAUKASTEN_QUERY_PARALLEL = int(os.environ.get("QUERY_PARALLEL", "4"))
BAUKASTEN_QUERY_PARALLEL_BY_SOURCE = {
    key[len("QUERY_PARALLEL_"):].lower(): int(value)
    for key, value in os.environ.items() if key.startswith("QUERY_PARALLEL_") and value.strip().isdigit()
}
# So lange wartet eine Anfrage auf einen freien Platz oder auf dieselbe, gerade laufende
# Abfrage, bevor sie „wird geladen“ meldet und den Thread freigibt (der Browser fragt nach).
BAUKASTEN_QUERY_WAIT = float(os.environ.get("QUERY_WAIT", "2"))
# Bausteine mit Datenbank-Abfragen erst nach dem Seitenaufbau laden.
BAUKASTEN_LAZY_QUERIES = env_bool("LAZY_QUERIES", True)

# Externe Datenquellen: DATASOURCE_<NAME>=<adresse>, siehe builder/datasources.py
BAUKASTEN_DATASOURCES = {
    key[len("DATASOURCE_"):].lower(): value
    for key, value in os.environ.items()
    if key.startswith("DATASOURCE_") and value
}
# Beispiel-Datenquelle für „python manage.py demo“, nur beim Entwickeln.
DEMO_DATASOURCE_FILE = Path(os.environ.get("DEMO_DATASOURCE_FILE", BASE_DIR / "demo-datenquelle.sqlite3"))
if DEBUG and DEMO_DATASOURCE_FILE.exists():
    BAUKASTEN_DATASOURCES.setdefault("demo", f"sqlite:///{DEMO_DATASOURCE_FILE.as_posix()}")

# Web-Requests aus Bausteinen und Erweiterungen dürfen nur diese Hosts erreichen.
BAUKASTEN_HTTP_ALLOWED_HOSTS = env_list("HTTP_ALLOWED_HOSTS")

# Tableau einbetten (Baustein „Tableau-Ansicht“, siehe builder/tableau.py und Handbuch „Tableau“)
BAUKASTEN_TABLEAU_HOSTS = env_list("TABLEAU_HOSTS")
BAUKASTEN_TABLEAU_CLIENT_ID = os.environ.get("TABLEAU_CONNECTED_APP_CLIENT_ID", "")
BAUKASTEN_TABLEAU_SECRET_ID = os.environ.get("TABLEAU_CONNECTED_APP_SECRET_ID", "")
BAUKASTEN_TABLEAU_SECRET_VALUE = os.environ.get("TABLEAU_CONNECTED_APP_SECRET_VALUE", "")
BAUKASTEN_TABLEAU_USER_ATTRIBUTE = os.environ.get("TABLEAU_USER_ATTRIBUTE", "email")
BAUKASTEN_HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "10"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
