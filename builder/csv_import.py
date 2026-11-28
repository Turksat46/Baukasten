"""CSV-Import für Tabellendaten: Einlesen, Spalten zuordnen, Typen prüfen und speichern."""
import csv
import io
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import validate_email, URLValidator
from django.db import transaction
from django.utils.translation import gettext

from . import audit
from .models import Field, Record, apply_formulas, label_key, record_label

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


class CsvImportError(Exception):
    """Verständlicher Fehler beim Einlesen oder Prüfen einer CSV-Datei."""


def parse_csv(raw_bytes):
    """Liest UTF-8-CSV-Daten ein und gibt (headers, rows) zurück."""
    if not raw_bytes:
        raise CsvImportError(gettext("Die Datei ist leer."))
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise CsvImportError(gettext("Die CSV-Datei ist größer als 2 MB."))
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError(gettext("Die Datei muss als UTF-8 gespeichert sein.")) from exc

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise CsvImportError(gettext("Die CSV-Datei braucht eine Kopfzeile und mindestens eine Datenzeile."))

    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=";,\t")
    except csv.Error:
        # Eigene Ableitung statt csv.excel zu ändern: das wäre eine globale Vorgabe des
        # ganzen Prozesses und träfe jedes andere CSV, das danach gelesen oder geschrieben wird.
        class dialect(csv.excel):
            delimiter = ";"

    reader = list(csv.reader(io.StringIO("\n".join(lines)), dialect))
    headers = [h.strip() for h in reader[0]]
    if not any(headers):
        raise CsvImportError(gettext("Die Kopfzeile der CSV-Datei enthält keine Spaltennamen."))
    data_rows = reader[1:]
    if len(data_rows) > MAX_ROWS:
        raise CsvImportError(gettext("Höchstens %(max)s Zeilen pro Import erlaubt.") % {"max": MAX_ROWS})
    return headers, data_rows


def guess_mapping(headers, fields):
    """Ordnet CSV-Spaltennamen automatisch passenden Tabellenfeldern zu."""
    by_name = {}
    for f in fields:
        by_name[f.key.casefold()] = f.key
        by_name[f.label.casefold()] = f.key
    return [by_name.get(h.casefold(), "") for h in headers]


def _build_ref_lookup(fields):
    """Erstellt für Verweisfelder ein Nachschlage-Dict (id / Anzeigetext -> Record.pk)."""
    lookups = {}
    for f in fields:
        if f.type == Field.REFERENCE and f.reference_id:
            by_pk, by_label = {}, {}
            name_key = label_key(f.reference)
            for r in f.reference.records.order_by("id")[:5000]:
                by_pk[str(r.pk)] = r.pk
                by_label[record_label(r, name_key).casefold()] = r.pk
            lookups[f.key] = (by_pk, by_label)
    return lookups


def _parse_date_value(text):
    for fmt in ("iso", "de"):
        if fmt == "iso":
            try:
                return date.fromisoformat(text[:10]).isoformat()
            except ValueError:
                pass
        else:
            parts = text.split(".")
            if len(parts) == 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    return date(y, m, d).isoformat()
                except ValueError:
                    pass
    raise ValueError("date")


def coerce_value(field, raw, ref_lookups):
    """Wandelt einen CSV-Zellwert in den passenden Feldtyp um."""
    text = (raw or "").strip()
    if text == "":
        if field.type == Field.BOOL:
            return False
        if field.required:
            raise CsvImportError(gettext("Pflichtfeld „%(field)s“ ist leer.") % {"field": field.label})
        return None

    t = field.type
    if t == Field.NUMBER:
        try:
            return int(text)
        except ValueError as exc:
            raise CsvImportError(gettext("„%(val)s“ ist keine ganze Zahl.") % {"val": text}) from exc

    if t == Field.DECIMAL:
        try:
            return float(text.replace(",", "."))
        except ValueError as exc:
            raise CsvImportError(gettext("„%(val)s“ ist keine Zahl.") % {"val": text}) from exc

    if t == Field.DATE:
        try:
            return _parse_date_value(text)
        except ValueError as exc:
            raise CsvImportError(gettext("„%(val)s“ ist kein gültiges Datum (JJJJ-MM-TT oder TT.MM.JJJJ).") % {"val": text}) from exc

    if t == Field.BOOL:
        low = text.casefold()
        if low in ("1", "true", "ja", "yes", "x", "wahr"):
            return True
        if low in ("0", "false", "nein", "no", "falsch"):
            return False
        raise CsvImportError(gettext("„%(val)s“ ist kein Ja/Nein-Wert.") % {"val": text})

    if t == Field.CHOICE:
        choices = field.choice_list()
        by_low = {c.casefold(): c for c in choices}
        if text.casefold() in by_low:
            return by_low[text.casefold()]
        raise CsvImportError(gettext("„%(val)s“ ist keine gültige Auswahl für „%(field)s“.") % {"val": text, "field": field.label})

    if t == Field.EMAIL:
        try:
            validate_email(text)
        except ValidationError as exc:
            raise CsvImportError(gettext("„%(val)s“ ist keine gültige E-Mail-Adresse.") % {"val": text}) from exc
        return text

    if t == Field.URL:
        candidate = text if "://" in text else f"https://{text}"
        try:
            _URL_VALIDATOR(candidate)
        except ValidationError as exc:
            raise CsvImportError(gettext("„%(val)s“ ist keine gültige Webadresse.") % {"val": text}) from exc
        return candidate

    if t == Field.REFERENCE:
        by_pk, by_label = ref_lookups.get(field.key, ({}, {}))
        if text in by_pk:
            return by_pk[text]
        if text.casefold() in by_label:
            return by_label[text.casefold()]
        raise CsvImportError(gettext("Verweis „%(val)s“ in „%(field)s“ nicht gefunden.") % {"val": text, "field": field.label})

    return text[:500] if t == Field.TEXT else text


def run_import(app, entity, rows, mapping, user, skip_errors=False):
    """Prüft und importiert die CSV-Zeilen in die Tabelle.

    mapping ist eine Liste von Feld-Keys (oder "" für ignorieren) je Spaltenindex.
    Gibt (created_count, errors) zurück.
    """
    all_fields = list(entity.fields.all())
    fields_by_key = {f.key: f for f in all_fields}
    mapped = [(idx, fields_by_key[key]) for idx, key in enumerate(mapping) if key in fields_by_key]
    if not mapped:
        raise CsvImportError(gettext("Bitte mindestens eine Spalte einem Tabellenfeld zuordnen."))

    mapped_keys = {f.key for _, f in mapped}
    missing_required = [f.label for f in fields_by_key.values() if f.required and f.show_in_form and not f.formula and f.key not in mapped_keys]
    if missing_required:
        raise CsvImportError(gettext("Pflichtfelder nicht zugeordnet: %(fields)s") % {"fields": ", ".join(missing_required)})

    ref_lookups = _build_ref_lookup([f for _, f in mapped])
    prepared, errors = [], []

    for line_no, row in enumerate(rows, start=2):
        data = {}
        row_errors = []
        for idx, field in mapped:
            raw = row[idx] if idx < len(row) else ""
            try:
                data[field.key] = coerce_value(field, raw, ref_lookups)
            except CsvImportError as exc:
                row_errors.append(str(exc))
        if row_errors:
            errors.append(gettext("Zeile %(line)s: %(msg)s") % {"line": line_no, "msg": "; ".join(row_errors)})
        else:
            # bulk_create umgeht Record.save(): Formelfelder deshalb hier berechnen.
            apply_formulas(entity, data, all_fields)
            prepared.append(Record(entity=entity, data=data, created_by=user if user and user.is_authenticated else None))

    if errors and not skip_errors:
        return 0, errors

    if prepared:
        with transaction.atomic(), audit.quiet():
            Record.objects.bulk_create(prepared, batch_size=500)
        audit.log(
            "create", "record", app=app, scope=entity.name,
            label=gettext("%(n)s Einträge") % {"n": len(prepared)},
            note=gettext("CSV-Import: %(n)s Einträge angelegt") % {"n": len(prepared)},
            user=user,
        )
    return len(prepared), errors
