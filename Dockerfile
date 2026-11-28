# Braucht BuildKit (Standard seit Docker 23 und in Docker Desktop).

# ---- Firmenproxy mit eigener Zertifizierungsstelle (optional) ----
# Prüft ein Proxy TLS-Verbindungen (TLS-Inspection), scheitert sonst schon `pip install` mit
# CERTIFICATE_VERIFY_FAILED. Dann die Zertifikate der Firmen-CA (PEM, *.crt oder *.pem) in einen
# Ordner legen und so bauen:
#   docker build --build-arg FIRMEN_CA=an --build-context firmen-ca=./zertifikate \
#     --build-arg HTTPS_PROXY=http://proxy.example.com:3128 .
# Die CA landet im System-Speicher des Images, und PIP_CERT, REQUESTS_CA_BUNDLE und SSL_CERT_FILE
# zeigen auf /etc/ssl/certs/ca-certificates.crt – auch zur Laufzeit (Keycloak, Teams, Databricks …).
# Ohne FIRMEN_CA baut das Image genau wie bisher. Details: Handbuch, „Firmenproxy und eigene
# Zertifizierungsstelle“.
ARG FIRMEN_CA=aus

# Leerer Platzhalter; --build-context firmen-ca=<ordner> ersetzt ihn.
FROM scratch AS firmen-ca

# Falls bei euch ein internes Basis-Image vorgeschrieben ist, hier austauschen.
FROM python:3.13-slim AS basis

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM basis AS ca-aus

FROM basis AS ca-an
COPY --from=firmen-ca / /tmp/firmen-ca/
RUN set -eu; \
    ziel=/usr/local/share/ca-certificates/firmen-ca; \
    mkdir -p "$ziel"; \
    find /tmp/firmen-ca -type f \( -name '*.crt' -o -name '*.pem' \) > /tmp/firmen-ca.liste; \
    if [ ! -s /tmp/firmen-ca.liste ]; then \
      echo "FIRMEN_CA=an, aber keine *.crt/*.pem in --build-context firmen-ca=<ordner> gefunden." >&2; \
      exit 1; \
    fi; \
    while read -r datei; do \
      name=$(basename "$datei"); \
      cp "$datei" "$ziel/${name%.*}.crt"; \
    done < /tmp/firmen-ca.liste; \
    update-ca-certificates; \
    rm -rf /tmp/firmen-ca /tmp/firmen-ca.liste
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

FROM ca-${FIRMEN_CA}

# requirements.txt ist die Lockdatei: genaue Versionen mit Prüfsummen, erzeugt aus requirements*.in
# (siehe CONTRIBUTING.md). So baut dasselbe Commit immer dasselbe Image.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# PostgreSQL und Databricks sind in requirements.in enthalten. Weitere Treiber, z. B. für MySQL:
#   docker build --build-arg EXTRA_PACKAGES="pymysql" .
# SQL Server braucht zusätzlich den ODBC-Treiber 18 von Microsoft im Image (siehe Handbuch).
ARG EXTRA_PACKAGES=""
RUN if [ -n "$EXTRA_PACKAGES" ]; then pip install --no-cache-dir $EXTRA_PACKAGES; fi

COPY . .
RUN SECRET_KEY=nur-fuer-den-build python manage.py collectstatic --noinput

RUN useradd --uid 10001 --no-create-home app
USER 10001

EXPOSE 8000
# Worker, Threads und Zeitlimits: gunicorn.conf.py (per Umgebungsvariable einstellbar)
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
