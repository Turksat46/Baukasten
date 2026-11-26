# Falls bei euch ein internes Basis-Image vorgeschrieben ist, hier austauschen.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

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
