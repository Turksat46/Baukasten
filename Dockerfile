# Falls bei euch ein internes Basis-Image vorgeschrieben ist, hier austauschen.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-automation.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-automation.txt

# PostgreSQL und Databricks sind in requirements.txt enthalten. Weitere Treiber, z. B. für MySQL:
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
