"""Formulare. RecordForm entsteht zur Laufzeit aus den Feldern einer Tabelle."""
from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from . import app_i18n, hooks
from .models import ApiKey, App, CustomBlock, DataQuery, Entity, Field, Page, Record, Script
from .sanitize import sanitize_html


def _form_field(field):
    # Beschriftungen in der Sprache der Person; die Werte (z. B. Auswahlwerte) bleiben in der Quellsprache.
    kw = {"label": app_i18n.t(field.label), "required": field.required}
    t = field.type
    if t == Field.LONGTEXT:
        return forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), **kw)
    if t == Field.NUMBER:
        return forms.IntegerField(**kw)
    if t == Field.DECIMAL:
        return forms.FloatField(**kw)
    if t == Field.DATE:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **kw)
    if t == Field.BOOL:
        return forms.BooleanField(label=kw["label"], required=False)
    if t == Field.CHOICE:
        options = [("", _("– bitte wählen –"))] + [(c, app_i18n.t(c)) for c in field.choice_list()]
        return forms.ChoiceField(choices=options, **kw)
    if t == Field.EMAIL:
        return forms.EmailField(**kw)
    if t == Field.URL:
        return forms.URLField(assume_scheme="https", **kw)
    if t == Field.REFERENCE and field.reference_id:
        queryset = Record.objects.filter(entity_id=field.reference_id).prefetch_related("entity__fields")
        return forms.ModelChoiceField(queryset=queryset, empty_label=_("– bitte wählen –"), **kw)
    return forms.CharField(max_length=500, **kw)


class RecordForm(forms.Form):
    def __init__(self, entity, *args, record=None, **kwargs):
        self.entity = entity
        self.record = record
        # Felder, die ein Skript füllt (show_in_form aus), erscheinen nicht im Formular,
        # Formelfelder auch nicht: Ihr Wert wird beim Speichern berechnet.
        self.entity_fields = [f for f in entity.fields.all() if f.show_in_form and not f.formula]
        if record is not None and "initial" not in kwargs:
            kwargs["initial"] = self._initial(record)
        super().__init__(*args, **kwargs)
        for f in self.entity_fields:
            self.fields[f.key] = _form_field(f)

    def _initial(self, record):
        initial = dict(record.data)
        for f in self.entity_fields:
            value = initial.get(f.key)
            if f.type == Field.DATE and value:
                try:
                    initial[f.key] = date.fromisoformat(value)
                except (TypeError, ValueError):
                    initial[f.key] = None
        return initial

    def json_data(self):
        data = {}
        for f in self.entity_fields:
            value = self.cleaned_data.get(f.key)
            if isinstance(value, date):
                value = value.isoformat()
            elif isinstance(value, Record):
                value = value.pk
            elif value == "":
                value = None
            data[f.key] = value
        return data

    def save(self, user=None):
        created = self.record is None
        record = self.record or Record(entity=self.entity, created_by=user if user and user.is_authenticated else None)
        # Zusammenführen statt ersetzen: Werte von Feldern, die nicht im Formular stehen
        # (gelöschte Felder, von Skripten gefüllte Felder), bleiben erhalten.
        record.data = {**(record.data or {}), **self.json_data()}
        record.save()
        hooks.fire_save(record, created, user)
        from .scripting.triggers import on_save

        on_save(record, created, user)
        record.refresh_from_db()
        return record


class AppForm(forms.ModelForm):
    class Meta:
        model = App
        fields = ["name", "description", "icon", "published", "groups"]
        widgets = {"groups": forms.CheckboxSelectMultiple}


class NewAppForm(forms.ModelForm):
    class Meta:
        model = App
        fields = ["name", "description", "icon"]


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ["name", "allow_create", "allow_edit", "allow_delete"]


class NewEntityForm(forms.ModelForm):
    """Neue Tabelle nur mit Namen: Die Schalter fehlen im Formular und dürfen nicht als „aus“ gelten."""

    class Meta:
        model = Entity
        fields = ["name"]


class FieldForm(forms.ModelForm):
    class Meta:
        model = Field
        fields = ["label", "type", "required", "show_in_list", "show_in_form", "formula", "choices", "reference"]
        widgets = {"choices": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, app, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = entity or (self.instance.entity if self.instance.entity_id else None)
        self.fields["reference"].queryset = app.entities.all()
        self.fields["reference"].empty_label = "–"

    def clean(self):
        from .models import formula_problem

        cleaned = super().clean()
        formula = (cleaned.get("formula") or "").strip()
        if formula:
            if cleaned.get("type") not in (Field.NUMBER, Field.DECIMAL):
                self.add_error("formula", _("Formeln gibt es nur für die Typen „Ganze Zahl“ und „Kommazahl“."))
            elif self.entity is not None:
                keys = [f.key for f in self.entity.fields.filter(type__in=[Field.NUMBER, Field.DECIMAL])
                        if f.pk != self.instance.pk]
                problem = formula_problem(formula, keys)
                if problem:
                    self.add_error("formula", problem)
        if cleaned.get("type") == Field.CHOICE and not cleaned.get("choices", "").strip():
            self.add_error("choices", _("Bitte mindestens einen Auswahlwert eintragen."))
        if cleaned.get("type") == Field.REFERENCE and not cleaned.get("reference"):
            self.add_error("reference", _("Bitte die Tabelle wählen, auf die verwiesen wird."))
        return cleaned


class NewPageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ["title"]


class ApiKeyForm(forms.ModelForm):
    class Meta:
        model = ApiKey
        fields = ["name", "can_write"]


class CustomBlockForm(forms.ModelForm):
    class Meta:
        model = CustomBlock
        fields = ["name", "description", "settings", "html"]
        widgets = {
            "settings": forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
            "html": forms.Textarea(attrs={"rows": 12, "spellcheck": "false", "class": "code"}),
        }
        help_texts = {
            "settings": _("Was man am Baustein einstellen kann. Eine Einstellung pro Zeile: Bezeichnung = Standardwert"),
            "html": _("Erlaubt sind übliche Tags wie div, p, h3, strong, a, img, ul, table. Skripte werden entfernt."),
        }

    def clean_html(self):
        html = sanitize_html(self.cleaned_data["html"])
        if not html.strip():
            raise forms.ValidationError(_("Nach dem Bereinigen ist kein Inhalt übrig. Bitte HTML eintragen."))
        return html


class ScriptForm(forms.ModelForm):
    class Meta:
        model = Script
        fields = ["name", "language", "trigger", "page", "entity", "interval_minutes", "enabled", "code"]
        widgets = {"code": forms.Textarea(attrs={"rows": 22, "spellcheck": "false", "class": "code",
                                                 "autocapitalize": "off", "autocomplete": "off"})}

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["page"].queryset = app.pages.all()
        self.fields["page"].empty_label = _("Alle Seiten")
        self.fields["entity"].queryset = app.entities.all()
        self.fields["entity"].empty_label = _("Alle Tabellen")
        labels = dict(Script.TRIGGERS)
        self.fields["trigger"].choices = [(key, labels[key]) for key in Script.APP_TRIGGERS]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("language") == Script.JAVASCRIPT and cleaned.get("trigger") in Script.PYTHON_ONLY:
            self.add_error("trigger", _("JavaScript läuft im Browser und kann nur beim Öffnen einer Seite oder per Button starten."))
        if cleaned.get("trigger") == Script.SCHEDULE and not cleaned.get("interval_minutes"):
            self.add_error("interval_minutes", _("Bitte ein Intervall von mindestens einer Minute angeben."))
        return cleaned


class AutomationForm(forms.ModelForm):
    """Einstellungen einer Automatisierung: keine Veröffentlichung, keine Nutzergruppen."""

    class Meta:
        model = App
        fields = ["name", "description", "icon"]


class AutomationScriptForm(forms.ModelForm):
    """Skript einer Automatisierung: immer Python, eigene Auslöser."""

    class Meta:
        model = Script
        fields = ["name", "trigger", "interval_minutes", "daily_time", "weekdays_only", "timeout_minutes",
                  "enabled", "code"]
        widgets = {"code": forms.Textarea(attrs={"rows": 26, "spellcheck": "false", "class": "code",
                                                 "autocapitalize": "off", "autocomplete": "off"}),
                   "daily_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, **kwargs):
        from . import platform

        super().__init__(*args, **kwargs)
        labels = dict(Script.TRIGGERS)
        self.fields["trigger"].choices = [(key, labels[key]) for key in Script.AUTOMATION_TRIGGERS]
        self.fields["trigger"].label = _("Wann läuft das Skript?")
        self.fields["timeout_minutes"].min_value = 1
        self.fields["timeout_minutes"].widget.attrs.update(
            min=1, max=platform.value("automation_max_timeout_minutes"))
        self.limit = platform.value("automation_max_timeout_minutes")

    def clean(self):
        cleaned = super().clean()
        trigger = cleaned.get("trigger")
        if trigger == Script.SCHEDULE and not cleaned.get("interval_minutes"):
            self.add_error("interval_minutes", _("Bitte ein Intervall von mindestens einer Minute angeben."))
        if trigger == Script.DAILY and not cleaned.get("daily_time"):
            self.add_error("daily_time", _("Bitte eine Uhrzeit angeben."))
        minutes = cleaned.get("timeout_minutes")
        if minutes is not None and not 1 <= minutes <= self.limit:
            self.add_error("timeout_minutes", _("Erlaubt sind 1 bis %(max)s Minuten.") % {"max": self.limit})
        return cleaned


class QueryForm(forms.ModelForm):
    source = forms.ChoiceField(label=_("Datenquelle"))

    class Meta:
        model = DataQuery
        fields = ["name", "source", "sql", "cache_seconds", "sync_entity", "key_column", "sync_interval"]
        widgets = {"sql": forms.Textarea(attrs={"rows": 12, "spellcheck": "false", "class": "code"})}

    def __init__(self, *args, app, **kwargs):
        from .datasources import describe_sources

        super().__init__(*args, **kwargs)
        choices = [(s["name"], f"{s['name']} ({s['kind']})") for s in describe_sources()]
        current = self.instance.source if self.instance and self.instance.pk else ""
        if current and current not in dict(choices):
            choices.append((current, _("%(name)s (nicht eingerichtet)") % {"name": current}))
        self.fields["source"].choices = choices
        self.fields["sync_entity"].queryset = app.entities.all()
        self.fields["sync_entity"].empty_label = _("– nicht spiegeln oder neue Tabelle anlegen –")

    def clean_sql(self):
        from .datasources import QueryError, check_read_only

        sql = self.cleaned_data["sql"]
        try:
            check_read_only(sql)
        except QueryError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return sql
