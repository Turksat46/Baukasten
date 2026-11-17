"""Python-Bibliothek für die API des Baukastens.

Ohne weitere Abhängigkeiten (nur Standardbibliothek). Die Befehle heißen wie
in den Skripten des Baukastens, damit man Code leicht übertragen kann.

    from baukasten_client import Client

    bk = Client("https://baukasten.example.com", app="inventar", key="bk_…")
    geraete = bk.table("gerate")
    for g in geraete.filter(kategorie="IT"):
        print(g["bezeichnung"], g["preis"])
    neu = geraete.create(bezeichnung="Kamera", kategorie="IT", preis=499.5)
    geraete.update(neu["id"], standort="Lager")
"""
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

__all__ = ["Client", "Table", "BaukastenError"]
__version__ = "0.1.0"


class BaukastenError(Exception):
    """Fehler der API. status: HTTP-Status, fields: Fehler je Feld (bei ungültigen Daten)."""

    def __init__(self, message, status=None, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}

    def __str__(self):
        text = super().__str__()
        if self.fields:
            details = "; ".join(f"{key}: {' '.join(e.get('message', '') for e in errors)}"
                                for key, errors in self.fields.items())
            text = f"{text} ({details})"
        return f"[{self.status}] {text}" if self.status else text


def _param(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class Client:
    """Verbindung zu einer App. key: API-Schlüssel aus dem Designer (Abschnitt „Schnittstelle“)."""

    def __init__(self, url, app, key, timeout=30, cafile=None):
        """cafile: eigene Zertifizierungsstelle (z. B. die interne CA des Unternehmens) als PEM-Datei."""
        self.base = url.rstrip("/") + f"/api/v1/{quote(app)}/"
        self.key = key
        self.timeout = timeout
        self._context = ssl.create_default_context(cafile=cafile) if cafile else None

    def __repr__(self):
        return f"<Baukasten {self.base}>"

    def request(self, method, path="", params=None, data=None):
        url = self.base + path
        if params:
            url += "?" + urlencode({k: _param(v) for k, v in params.items() if v is not None})
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        })
        try:
            with urlopen(req, timeout=self.timeout, context=self._context) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read() or b"{}")
            except ValueError:
                payload = {}
            raise BaukastenError(payload.get("error") or exc.reason, exc.code, payload.get("fields")) from None
        except URLError as exc:
            raise BaukastenError(f"Keine Verbindung: {exc.reason}") from None

    def describe(self):
        """Tabellen, Felder und eigene Endpunkte der App."""
        return self.request("GET")

    def table(self, slug):
        return Table(self, slug)

    def call(self, name, data=None, method=None, **params):
        """Eigener Endpunkt aus einer Erweiterung (hooks.api)."""
        method = method or ("POST" if data is not None else "GET")
        return self.request(method, f"x/{quote(name)}/", params=params or None, data=data)


class Table:
    """Eine Tabelle der App. Kurzname wie im Designer angezeigt."""

    def __init__(self, client, slug):
        self.client = client
        self.slug = slug
        self.path = f"{quote(slug)}/"

    def __repr__(self):
        return f"<Tabelle {self.slug}>"

    def iter(self, page_size=200, **where):
        """Alle passenden Einträge, seitenweise geladen."""
        page = 1
        while True:
            data = self.client.request("GET", self.path, params={**where, "page": page, "page_size": page_size})
            yield from data["results"]
            if page >= data["pages"]:
                return
            page += 1

    def all(self, limit=None):
        return self.filter(limit=limit)

    def filter(self, limit=None, **where):
        rows = []
        for row in self.iter(**where):
            rows.append(row)
            if limit and len(rows) >= limit:
                break
        return rows

    def first(self, **where):
        data = self.client.request("GET", self.path, params={**where, "page_size": 1})
        return data["results"][0] if data["results"] else None

    def count(self, **where):
        return self.client.request("GET", self.path, params={**where, "page_size": 1})["count"]

    def get(self, id):
        try:
            return self.client.request("GET", f"{self.path}{int(id)}/")
        except BaukastenError as exc:
            if exc.status == 404:
                return None
            raise

    def create(self, data=None, **fields):
        return self.client.request("POST", self.path, data={**(data or {}), **fields})

    def update(self, id, data=None, **fields):
        """Ändert nur die angegebenen Felder."""
        return self.client.request("PATCH", f"{self.path}{int(id)}/", data={**(data or {}), **fields})

    def replace(self, id, data):
        """Ersetzt den ganzen Eintrag; fehlende Felder werden leer."""
        return self.client.request("PUT", f"{self.path}{int(id)}/", data=data)

    def delete(self, id):
        self.client.request("DELETE", f"{self.path}{int(id)}/")
        return True
