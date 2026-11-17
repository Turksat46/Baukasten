# baukasten-client

Python-Bibliothek für die API des Baukastens. Keine Abhängigkeiten außer der
Standardbibliothek, Python 3.9 oder neuer.

## Installieren

Aus dem Ordner des Baukastens:

```
pip install ./clients/python
```

## Verwenden

Den API-Schlüssel erzeugst du im Designer in der App unter „Schnittstelle (API)“.
Dort schaltest du auch frei, welche Tabellen erreichbar sind.

```python
from baukasten_client import Client, BaukastenError

bk = Client("https://baukasten.example.com", app="inventar", key="bk_…")

geraete = bk.table("gerate")
print(geraete.count(kategorie="IT"))

for g in geraete.filter(kategorie="IT"):
    print(g["bezeichnung"], g["preis"])

neu = geraete.create(bezeichnung="Kamera", kategorie="IT", preis=499.5)
geraete.update(neu["id"], standort="Lager")
geraete.delete(neu["id"])

try:
    geraete.create(kategorie="Unbekannt")
except BaukastenError as e:
    print(e.status, e.fields)
```

| Befehl | Wirkung |
|---|---|
| `bk.describe()` | Tabellen, Felder und eigene Endpunkte |
| `bk.table("kurzname")` | eine Tabelle |
| `.all(limit=None)` / `.filter(**feld=wert)` | Einträge als Liste von Dictionaries |
| `.iter(**feld=wert)` | dasselbe als Generator, lädt seitenweise |
| `.first(**…)` / `.get(id)` / `.count(**…)` | einzelner Eintrag bzw. Anzahl |
| `.create(**felder)` / `.update(id, **felder)` | anlegen bzw. einzelne Felder ändern |
| `.replace(id, daten)` / `.delete(id)` | ganz ersetzen bzw. löschen |
| `bk.call("name", data=None, **params)` | eigener Endpunkt aus einer Erweiterung |

Bei einem Server mit Zertifikat einer internen Zertifizierungsstelle:
`Client(…, cafile="firmen-ca.pem")`.

Filter vergleichen auf Gleichheit; `q="text"` sucht in allen Feldern. Fehler
der API kommen als `BaukastenError` mit `status` und, bei ungültigen Daten,
`fields`.

Die Befehle heißen wie in den Python-Skripten des Baukastens (`app.table(…)`),
damit sich Code zwischen beiden übertragen lässt.
