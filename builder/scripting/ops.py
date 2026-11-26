"""Zugriff auf die Tabellen einer App für Skripte (Python und JavaScript) und die API.

Python-Skripte schreiben Designer; sie dürfen alle Tabellen ihrer App lesen und
schreiben. JavaScript läuft im Browser mit den Rechten der angemeldeten Person
(enforce_flags=True): Anlegen, Bearbeiten und Löschen nur, wo die Tabelle es
erlaubt, und nur in Tabellen, die die Person lesen bzw. ändern darf (Tabellenrechte).
"""
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Avg, FloatField, Sum, TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils.translation import gettext as _

from .. import policy
from ..models import Field, Record

MAX_ROWS = 10000


class OpsError(Exception):
    def __init__(self, message, fields=None):
        super().__init__(message)
        self.fields = fields or {}


def serialize(record, fields):
    data = {"id": record.pk}
    data.update({f.key: record.data.get(f.key) for f in fields})
    data["created_at"] = record.created_at.isoformat()
    data["updated_at"] = record.updated_at.isoformat()
    return data


def coerce(field, raw):
    """Wandelt einen Text (z. B. aus einer Adresse) in den gespeicherten Typ um."""
    if not isinstance(raw, str):
        if isinstance(raw, (date, datetime)):
            return raw.isoformat()[:10] if field.type == Field.DATE else raw.isoformat()
        if isinstance(raw, Decimal):
            return float(raw)
        return raw
    try:
        if field.type in (Field.NUMBER, Field.REFERENCE):
            return int(raw)
        if field.type == Field.DECIMAL:
            return float(raw)
    except ValueError:
        return None
    if field.type == Field.BOOL:
        return raw.lower() in ("1", "true", "ja", "yes")
    return raw


def save_record(entity, payload, user=None, record=None, partial=False):
    """Prüft wie das Formular und speichert. Wirft OpsError mit den Fehlern je Feld."""
    from ..forms import RecordForm

    if not isinstance(payload, dict):
        raise OpsError(_("Erwartet wird ein JSON-Objekt."))
    fields = {f.key: f for f in entity.fields.all()}
    data = {key: coerce(fields[key], value) if key in fields and not isinstance(value, str) else value
            for key, value in payload.items()}
    if record and partial:
        data = {**record.data, **data}
    form = RecordForm(entity, data, record=record)
    if not form.is_valid():
        raise OpsError(_("Die Daten sind ungültig."), fields=form.errors.get_json_data())
    return form.save(user)


class TableOps:
    def __init__(self, app, user=None, enforce_flags=False):
        self.app = app
        self.user = user
        self.enforce_flags = enforce_flags

    def entity(self, slug, write=False):
        entity = self.app.entities.filter(slug=str(slug)).first()
        if entity is None:
            raise OpsError(_("Die Tabelle „%(name)s“ gibt es in dieser App nicht.") % {"name": slug})
        if self.enforce_flags:
            # Rechte der Person (policy); die Schalter der Tabelle prüfen create/update/delete selbst
            lesen = policy.darf(self.user, policy.LESEN, entity)
            schreiben = policy.darf(self.user, policy.SCHREIBEN, entity)
            if not lesen and not (write == "create" and schreiben):
                raise OpsError(_("Für die Tabelle „%(name)s“ fehlt dir die Berechtigung.") % {"name": entity.name})
            if write and not schreiben:
                raise OpsError(_("Die Tabelle „%(name)s“ darfst du nur lesen.") % {"name": entity.name})
        return entity

    def _where(self, entity, where):
        fields = {f.key: f for f in entity.fields.all()}
        records = entity.records.all()
        for key, value in (where or {}).items():
            if key == "id":
                records = records.filter(pk=value)
            elif key == "q":
                records = records.annotate(_text=Cast("data", TextField())).filter(_text__icontains=str(value))
            elif key in fields:
                records = records.filter(**{f"data__{key}": coerce(fields[key], value)})
            else:
                raise OpsError(_("Die Tabelle hat kein Feld „%(name)s“.") % {"name": key})
        return records, list(fields.values())

    def filter(self, table, where=None, limit=1000):
        entity = self.entity(table)
        records, fields = self._where(entity, where)
        limit = min(max(int(limit or 1000), 1), MAX_ROWS)
        return [serialize(r, fields) for r in records.order_by("id")[:limit]]

    def get(self, table, id):
        entity = self.entity(table)
        record = entity.records.filter(pk=id).first()
        return serialize(record, list(entity.fields.all())) if record else None

    def count(self, table, where=None):
        entity = self.entity(table)
        return self._where(entity, where)[0].count()

    def aggregate(self, table, func, field, where=None):
        entity = self.entity(table)
        if not entity.fields.filter(key=field, type__in=[Field.NUMBER, Field.DECIMAL]).exists():
            raise OpsError(_("Summe und Durchschnitt brauchen ein Zahlenfeld."))
        records = self._where(entity, where)[0]
        expr = Cast(KeyTextTransform(field, "data"), FloatField())
        value = records.aggregate(v=(Sum if func == "sum" else Avg)(expr))["v"]
        return value or 0

    def create(self, table, data):
        entity = self.entity(table, write="create")
        if self.enforce_flags and not entity.allow_create:
            raise OpsError(_("In dieser Tabelle ist das Anlegen nicht erlaubt."))
        record = save_record(entity, data, self.user)
        return serialize(record, list(entity.fields.all()))

    def update(self, table, id, data):
        entity = self.entity(table, write=True)
        if self.enforce_flags and not entity.allow_edit:
            raise OpsError(_("In dieser Tabelle ist das Bearbeiten nicht erlaubt."))
        record = Record.objects.filter(pk=id, entity=entity).first()
        if record is None:
            raise OpsError(_("Diesen Eintrag gibt es nicht."))
        record = save_record(entity, data, self.user, record, partial=True)
        return serialize(record, list(entity.fields.all()))

    def delete(self, table, id):
        entity = self.entity(table, write=True)
        if self.enforce_flags and not entity.allow_delete:
            raise OpsError(_("In dieser Tabelle ist das Löschen nicht erlaubt."))
        deleted, _detail = Record.objects.filter(pk=id, entity=entity).delete()
        return bool(deleted)
