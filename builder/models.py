"""Datenmodell des Baukastens.

Eine App besteht aus Tabellen (Entity) mit Feldern (Field) und aus Seiten (Page).
Datensätze (Record) liegen als JSON in einer gemeinsamen Tabelle. Dadurch braucht
eine im Designer geänderte Tabelle keine Datenbank-Migration.
"""
import hashlib
import secrets

from django.conf import settings
from django.conf import settings as settings_module
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class UnicodeJSONEncoder(DjangoJSONEncoder):
    """Speichert Umlaute lesbar, damit die Textsuche sie auf jeder Datenbank findet."""

    def __init__(self, *args, **kwargs):
        kwargs["ensure_ascii"] = False
        super().__init__(*args, **kwargs)


RESERVED_APP_SLUGS = {
    "bausteine", "import", "designer", "admin", "oidc", "api", "mcp",
    "healthz", "readyz", "metrics", "login", "logout", "profil", "hilfe", "ueber", "offline",
}  # Adressen, die keine App belegen darf
RESERVED_RESOURCE_SLUGS = {"neu"}


def unique_slug(queryset, base, field="slug", sep="-", reserved=RESERVED_RESOURCE_SLUGS):
    base = base or "x"
    slug, i = base, 2
    while slug in reserved or queryset.filter(**{field: slug}).exists():
        slug = f"{base}{sep}{i}"
        i += 1
    return slug


def can_design(user):
    return user.is_authenticated and (user.is_staff or user.has_perm("builder.design_apps"))


def can_automate(user):
    """Automatisierungen bauen: Skripte mit uneingeschränktem Python. Nur Superuser und die Gruppe
    „Automatisierer“ (Recht automate_apps), immer zusammen mit dem Designer-Recht."""
    return can_design(user) and (user.is_superuser or user.has_perm("builder.automate_apps"))


class App(models.Model):
    # Art: normale App mit Seiten oder Automatisierung (nur Python-Skripte im Hintergrund).
    APP, AUTOMATION = "app", "automation"
    KINDS = [(APP, _("App")), (AUTOMATION, _("Automatisierung"))]

    name = models.CharField(_("Name"), max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    description = models.CharField(_("Beschreibung"), max_length=200, blank=True)
    icon = models.CharField(_("Symbol"), max_length=8, blank=True, default="📦")
    published = models.BooleanField(
        _("Veröffentlicht"), default=False, help_text=_("Erst dann sehen Nutzer die App.")
    )
    groups = models.ManyToManyField(
        Group,
        blank=True,
        verbose_name=_("Gruppen"),
        help_text=_("Leer lassen: alle angemeldeten Nutzer dürfen die App verwenden."),
    )
    # Eigentümerin: wer die App angelegt hat. Ohne Eigentümerin (alte Apps, gelöschtes Konto)
    # dürfen alle Designer die App bearbeiten.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name=_("Eigentümer/in"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    editors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="edited_apps", verbose_name=_("Mitbearbeiter"),
        help_text=_("Designer, die diese App zusätzlich zur Eigentümerin bearbeiten dürfen."),
    )
    editor_groups = models.ManyToManyField(
        Group, blank=True, related_name="edited_apps", verbose_name=_("Mitbearbeiter-Gruppen"),
        help_text=_("Designer in diesen Gruppen dürfen die App bearbeiten."),
    )
    # Übersetzungen der Inhalte: {"en": {"Quelltext": "Übersetzung"}}, siehe builder/app_i18n.py
    translations = models.JSONField(default=dict, blank=True, encoder=UnicodeJSONEncoder)
    kind = models.CharField(_("Art"), max_length=12, choices=KINDS, default=APP)

    class Meta:
        verbose_name = _("App")
        verbose_name_plural = _("Apps")
        ordering = ["name"]
        permissions = [("design_apps", _("Darf Apps im Designer bearbeiten")),
                       ("automate_apps", _("Darf Automatisierungen mit uneingeschränktem Python bauen"))]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "app"
            if base in RESERVED_APP_SLUGS:
                base += "-app"
            self.slug = unique_slug(App.objects, base)
        super().save(*args, **kwargs)

    @classmethod
    def editable_by(cls, user):
        """Apps, die diese Person im Designer bearbeiten darf."""
        if not can_design(user):
            return cls.objects.none()
        if user.is_superuser:
            return cls.objects.all()
        apps = cls.objects.filter(
            models.Q(created_by__isnull=True) | models.Q(created_by=user) | models.Q(editors=user)
            | models.Q(editor_groups__in=user.groups.all())
        ).distinct()
        return apps if can_automate(user) else apps.exclude(kind=cls.AUTOMATION)

    @property
    def is_automation(self):
        return self.kind == self.AUTOMATION

    def user_can_edit(self, user):
        """Im Designer bearbeiten: Eigentümerin, Mitbearbeiter (einzeln oder per Gruppe), Admins.
        Immer nur mit Designer-Recht."""
        if not can_design(user) or (self.is_automation and not can_automate(user)):
            return False
        if user.is_superuser or self.created_by_id is None or self.created_by_id == user.pk:
            return True
        return (self.editors.filter(pk=user.pk).exists()
                or self.editor_groups.filter(pk__in=user.groups.values("pk")).exists())

    def user_can_manage(self, user):
        """Mitbearbeiter verwalten und die App löschen: Eigentümerin und Admins.
        Apps ohne Eigentümerin bleiben wie bisher für alle Designer offen."""
        return (can_design(user) and (not self.is_automation or can_automate(user))
                and (user.is_superuser or self.created_by_id in (None, user.pk)))

    def user_can_use(self, user):
        if self.is_automation:  # hat keine Seiten; bedient wird sie nur im Designer
            return False
        if self.user_can_edit(user):
            return True
        if not self.published:
            return False
        group_ids = list(self.groups.values_list("id", flat=True))
        return not group_ids or user.groups.filter(id__in=group_ids).exists()

    @property
    def home_page(self):
        return self.pages.order_by("order", "id").first()

    def public_reach(self):
        """Was Gäste ohne Anmeldung auslösen dürfen: Skripte der Buttons und Tabellen der
        Formulare auf öffentlichen Seiten. Gibt (Skript-Kurznamen, Tabellen-Kurznamen) zurück."""
        scripts, entities = set(), set()
        if not self.published:
            return scripts, entities
        for page in self.pages.filter(public=True):
            for block in page.layout or []:
                props = block.get("props") or {}
                if block.get("type") == "button" and props.get("target") == "script" and props.get("script"):
                    scripts.add(props["script"])
                elif block.get("type") == "form" and props.get("entity"):
                    entities.add(props["entity"])
        return scripts, entities


class Entity(models.Model):
    app = models.ForeignKey(App, related_name="entities", on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=80)
    slug = models.SlugField(blank=True)
    allow_create = models.BooleanField(_("Anlegen erlaubt"), default=True)
    allow_edit = models.BooleanField(_("Bearbeiten erlaubt"), default=True)
    allow_delete = models.BooleanField(_("Löschen erlaubt"), default=True)
    api_enabled = models.BooleanField(_("Über die API erreichbar"), default=False)

    class Meta:
        verbose_name = _("Tabelle")
        verbose_name_plural = _("Tabellen")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["app", "slug"], name="entity_slug_per_app")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self.app.entities, slugify(self.name) or "tabelle")
        super().save(*args, **kwargs)


class Field(models.Model):
    TEXT, LONGTEXT, NUMBER, DECIMAL, DATE = "text", "longtext", "number", "decimal", "date"
    BOOL, CHOICE, EMAIL, URL, REFERENCE = "bool", "choice", "email", "url", "reference"
    TYPES = [
        (TEXT, _("Text")),
        (LONGTEXT, _("Langer Text")),
        (NUMBER, _("Ganze Zahl")),
        (DECIMAL, _("Kommazahl")),
        (DATE, _("Datum")),
        (BOOL, _("Ja/Nein")),
        (CHOICE, _("Auswahl")),
        (EMAIL, _("E-Mail")),
        (URL, _("Link")),
        (REFERENCE, _("Verweis auf Tabelle")),
    ]

    entity = models.ForeignKey(Entity, related_name="fields", on_delete=models.CASCADE)
    label = models.CharField(_("Bezeichnung"), max_length=80)
    key = models.SlugField(blank=True, editable=False)
    type = models.CharField(_("Typ"), max_length=12, choices=TYPES, default=TEXT)
    required = models.BooleanField(_("Pflichtfeld"), default=False)
    choices = models.TextField(
        _("Auswahlwerte"), blank=True, help_text=_("Nur für Typ „Auswahl“: ein Wert pro Zeile.")
    )
    reference = models.ForeignKey(
        Entity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referenced_by",
        verbose_name=_("Verweist auf"),
        help_text=_("Nur für Typ „Verweis auf Tabelle“."),
    )
    show_in_list = models.BooleanField(_("In Listen anzeigen"), default=True)
    show_in_form = models.BooleanField(
        _("Im Formular anzeigen"), default=True,
        help_text=_("Aus für Felder, die ein Skript füllt (z. B. ein erzeugter Link). Der Wert bleibt beim Bearbeiten erhalten."),
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Feld")
        verbose_name_plural = _("Felder")
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["entity", "key"], name="field_key_per_entity")]

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if not self.key:
            base = slugify(self.label).replace("-", "_") or "feld"
            self.key = unique_slug(self.entity.fields, base, field="key", sep="_")
        if not self.pk and not self.order:
            last = self.entity.fields.order_by("-order").first()
            self.order = (last.order + 1) if last else 1
        super().save(*args, **kwargs)

    def choice_list(self):
        return [c.strip() for c in self.choices.splitlines() if c.strip()]


class Record(models.Model):
    entity = models.ForeignKey(Entity, related_name="records", on_delete=models.CASCADE)
    data = models.JSONField(default=dict, encoder=UnicodeJSONEncoder)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Eintrag")
        verbose_name_plural = _("Einträge")
        ordering = ["-id"]

    def __str__(self):
        first = self.entity.fields.first()
        value = self.data.get(first.key) if first else None
        return str(value) if value not in (None, "") else f"#{self.pk}"


class Page(models.Model):
    app = models.ForeignKey(App, related_name="pages", on_delete=models.CASCADE)
    title = models.CharField(_("Titel"), max_length=80)
    slug = models.SlugField(blank=True)
    show_in_nav = models.BooleanField(_("Im Menü anzeigen"), default=True)
    public = models.BooleanField(
        _("Ohne Anmeldung erreichbar"), default=False,
        help_text=_("Jeder mit dem Link kann die Seite öffnen, ihre Formulare absenden und ihre Buttons auslösen."),
    )
    order = models.PositiveIntegerField(default=0)
    layout = models.JSONField(default=list, encoder=UnicodeJSONEncoder)
    version = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = _("Seite")
        verbose_name_plural = _("Seiten")
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["app", "slug"], name="page_slug_per_app")]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self.app.pages, slugify(self.title) or "seite")
        if not self.pk and not self.order:
            last = self.app.pages.order_by("-order").first()
            self.order = (last.order + 1) if last else 1
        if self.pk and not self._state.adding:
            self.version = (self.version or 1) + 1
            if kwargs.get("update_fields") is not None:
                fields = list(kwargs["update_fields"])
                if "version" not in fields:
                    fields.append("version")
                kwargs["update_fields"] = fields
        super().save(*args, **kwargs)


class CustomBlock(models.Model):
    """Eigener Baustein, im Designer ohne Programmierung angelegt.

    „html“: eigenes Markup mit Platzhaltern für selbst definierte Einstellungen.
    „preset“: ein fertig eingestellter Standard-Baustein als wiederverwendbare Vorlage.
    """

    HTML, PRESET = "html", "preset"
    KINDS = [(HTML, _("HTML-Baustein")), (PRESET, _("Vorlage"))]

    name = models.CharField(_("Name"), max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    description = models.CharField(_("Kurzbeschreibung"), max_length=120, blank=True)
    kind = models.CharField(max_length=10, choices=KINDS, default=HTML)
    html = models.TextField(_("HTML"), blank=True)
    settings = models.TextField(_("Einstellungen"), blank=True)
    preset = models.JSONField(default=dict, blank=True, encoder=UnicodeJSONEncoder)
    created_by = models.ForeignKey(
        settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Eigener Baustein")
        verbose_name_plural = _("Eigene Bausteine")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(CustomBlock.objects, slugify(self.name) or "baustein")
        super().save(*args, **kwargs)

    def setting_specs(self):
        """Liest Einstellungen: JSON-Liste oder Zeilen „Bezeichnung [: typ] = Standardwert“."""
        import json as _json
        import re as _re

        text = (self.settings or "").strip()
        if text.startswith("["):
            try:
                raw = _json.loads(text)
            except ValueError:
                raw = None
            if isinstance(raw, list):
                specs, seen = [], set()
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    label = str(item.get("label") or item.get("key") or "").strip()
                    key = slugify(str(item.get("key") or label)).replace("-", "_")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    ftype = str(item.get("type") or "text").strip().lower()
                    if ftype not in ("text", "textarea", "number", "checkbox", "select"):
                        ftype = "text"
                    default = item.get("default", "")
                    if ftype == "checkbox":
                        default = bool(default) if isinstance(default, bool) else str(default).lower() in ("1", "true", "ja", "yes")
                    else:
                        default = str(default) if default is not None else ""
                    spec = {"key": key, "label": label or key, "default": default, "type": ftype}
                    if ftype == "select":
                        opts = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
                        spec["options"] = [[o, o] for o in opts]
                    specs.append(spec)
                return specs

        specs, seen = [], set()
        for line in self.settings.splitlines():
            left, _sep, default = line.partition("=")
            left, default = left.strip(), default.strip()
            if not left:
                continue
            label, sep_type, type_expr = left.partition(":")
            label = label.strip()
            key = slugify(label).replace("-", "_")
            if not key or key in seen:
                continue
            seen.add(key)
            ftype = "textarea" if len(default) > 60 else "text"
            options = None
            if sep_type:
                expr = type_expr.strip()
                m = _re.match(r"^select\((.+)\)$", expr, _re.IGNORECASE)
                if m:
                    ftype = "select"
                    options = [[o.strip(), o.strip()] for o in m.group(1).split(",") if o.strip()]
                elif expr.lower() in ("text", "textarea", "number", "checkbox"):
                    ftype = expr.lower()
            if ftype == "checkbox":
                default = default.lower() in ("1", "true", "ja", "yes")
            spec = {"key": key, "label": label, "default": default, "type": ftype}
            if options is not None:
                spec["options"] = options
            specs.append(spec)
        return specs


class ApiKey(models.Model):
    """Zugangsschlüssel für die API einer App. Gespeichert wird nur der Hash."""

    app = models.ForeignKey(App, related_name="api_keys", on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=80, help_text=_("Wofür der Schlüssel gedacht ist, z. B. „Auswertung Excel“."))
    prefix = models.CharField(max_length=12, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    can_write = models.BooleanField(_("Darf schreiben"), default=False,
                                    help_text=_("Ohne Haken kann der Schlüssel nur lesen."))
    created_by = models.ForeignKey(
        settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("API-Schlüssel")
        verbose_name_plural = _("API-Schlüssel")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash(key):
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, app, name, can_write=False, user=None):
        """Erzeugt einen Schlüssel. Der Klartext wird nur hier zurückgegeben."""
        key = "bk_" + secrets.token_urlsafe(32)
        obj = cls.objects.create(app=app, name=name, can_write=can_write, created_by=user,
                                 prefix=key[:9], key_hash=cls.hash(key))
        return obj, key


class DesignerToken(models.Model):
    """Persönlicher Schlüssel für den Designer-MCP-Server (/mcp/designer/): Eine KI nach Wahl
    baut damit Apps mit den Rechten dieser Person. Gespeichert wird nur der Hash."""

    user = models.ForeignKey(settings_module.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="designer_tokens")
    name = models.CharField(_("Name"), max_length=80,
                            help_text=_("Wofür der Schlüssel gedacht ist, z. B. „Claude Desktop“ oder „Cursor“."))
    prefix = models.CharField(max_length=12, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("KI-Zugang zum Designer")
        verbose_name_plural = _("KI-Zugänge zum Designer")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @classmethod
    def issue(cls, user, name):
        """Erzeugt einen Schlüssel. Der Klartext wird nur hier zurückgegeben."""
        key = "bkd_" + secrets.token_urlsafe(32)
        obj = cls.objects.create(user=user, name=name[:80], prefix=key[:10], key_hash=ApiKey.hash(key))
        return obj, key

    @classmethod
    def find(cls, key):
        if not key or not key.startswith("bkd_"):
            return None
        return cls.objects.filter(key_hash=ApiKey.hash(key)).select_related("user").first()


class Tutorial(models.Model):
    """Geführte Einführung „Deine erste App“ einer Person (siehe builder/tutorial.py).

    Der Fortschritt wird nicht gespeichert, sondern bei jedem Aufruf aus dem Zustand
    der App abgeleitet: Ein Schritt ist erledigt, sobald die App ihn enthält."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tutorial")
    app = models.ForeignKey(App, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Einführung")
        verbose_name_plural = _("Einführungen")

    def __str__(self):
        return f"{self.user} – {self.app or '…'}"


class AppVersion(models.Model):
    """Gespeicherter Stand einer App: Einstellungen, Tabellen, Felder und Seiten, ohne die Daten."""

    app = models.ForeignKey(App, related_name="versions", on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    note = models.CharField(_("Notiz"), max_length=200, blank=True,
                            help_text=_("Was sich geändert hat, z. B. „Auswertung ergänzt“."))
    automatic = models.BooleanField(default=False)
    snapshot = models.JSONField(encoder=UnicodeJSONEncoder)
    created_by = models.ForeignKey(
        settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Version")
        verbose_name_plural = _("Versionen")
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["app", "number"], name="version_number_per_app")]

    def __str__(self):
        return f"{self.app.name} v{self.number}"


class Script(models.Model):
    """Skript in Python (läuft auf dem Server) oder JavaScript (läuft im Browser)."""

    PYTHON, JAVASCRIPT = "python", "javascript"
    LANGUAGES = [(PYTHON, "Python"), (JAVASCRIPT, "JavaScript")]
    PAGE, BUTTON, SAVE, SCHEDULE = "page", "button", "save", "schedule"
    DAILY, CONTINUOUS, MANUAL = "daily", "continuous", "manual"
    TRIGGERS = [
        (PAGE, _("Beim Öffnen einer Seite")),
        (BUTTON, _("Per Button")),
        (SAVE, _("Nach dem Speichern eines Eintrags")),
        (SCHEDULE, _("Zeitgesteuert im Hintergrund")),
        (DAILY, _("Täglich zu einer Uhrzeit")),
        (CONTINUOUS, _("Läuft ständig")),
        (MANUAL, _("Nur von Hand oder per Webhook")),
    ]
    PYTHON_ONLY = {SAVE, SCHEDULE}
    APP_TRIGGERS = (PAGE, BUTTON, SAVE, SCHEDULE)
    AUTOMATION_TRIGGERS = (SCHEDULE, DAILY, CONTINUOUS, MANUAL)

    app = models.ForeignKey(App, related_name="scripts", on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=80)
    slug = models.SlugField(blank=True)
    language = models.CharField(_("Sprache"), max_length=12, choices=LANGUAGES, default=PYTHON)
    trigger = models.CharField(_("Auslöser"), max_length=10, choices=TRIGGERS, default=PAGE)
    page = models.ForeignKey(Page, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Seite"),
                             help_text=_("Leer lassen: auf allen Seiten der App."))
    entity = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.CASCADE, verbose_name=_("Tabelle"),
                               help_text=_("Leer lassen: nach dem Speichern in jeder Tabelle der App."))
    interval_minutes = models.PositiveIntegerField(_("Alle … Minuten"), default=60)
    # Nur Automatisierungen:
    daily_time = models.TimeField(_("Uhrzeit"), null=True, blank=True)
    weekdays_only = models.BooleanField(_("Nur werktags (Mo–Fr)"), default=False)
    timeout_minutes = models.PositiveIntegerField(
        _("Zeitlimit in Minuten"), default=30,
        help_text=_("Dauert ein Lauf länger, wird er abgebrochen. Gilt nicht für „Läuft ständig“."))
    enabled = models.BooleanField(_("Aktiv"), default=True)
    code = models.TextField(_("Code"), blank=True)
    created_by = models.ForeignKey(
        settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    # Zustand im Hintergrunddienst (nur Automatisierungen, siehe scripting/worker.py)
    next_run_at = models.DateTimeField(null=True, blank=True)
    running_since = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    run_requested = models.BooleanField(default=False)
    request_event = models.JSONField(null=True, blank=True, encoder=UnicodeJSONEncoder)
    stop_requested = models.BooleanField(default=False)
    failures = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Skript")
        verbose_name_plural = _("Skripte")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["app", "slug"], name="script_slug_per_app")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self.app.scripts, slugify(self.name) or "skript")
        super().save(*args, **kwargs)


class ScriptRun(models.Model):
    RUNNING, OK, ERROR, SKIPPED, ABORTED, STOPPED = "running", "ok", "error", "skipped", "aborted", "stopped"
    STATUSES = [(RUNNING, _("läuft")), (OK, _("ok")), (ERROR, _("Fehler")), (SKIPPED, _("übersprungen")),
                (ABORTED, _("abgebrochen")), (STOPPED, _("gestoppt"))]

    script = models.ForeignKey(Script, related_name="runs", on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    trigger = models.CharField(max_length=10)
    duration_ms = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    log = models.TextField(blank=True)
    error = models.TextField(blank=True)
    # Nur Automatisierungen; ältere Läufe haben keinen Status (dann zählt „ok“).
    status = models.CharField(max_length=10, choices=STATUSES, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Skriptlauf")
        verbose_name_plural = _("Skriptläufe")
        ordering = ["-id"]

    @property
    def state(self):
        return self.status or (self.OK if self.ok else self.ERROR)


class DataQuery(models.Model):
    """Lesende Abfrage an eine externe Datenbank (z. B. Databricks); live anzeigen oder in eine Tabelle spiegeln."""

    app = models.ForeignKey(App, related_name="queries", on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=80)
    slug = models.SlugField(blank=True)
    source = models.CharField(_("Datenquelle"), max_length=40)
    sql = models.TextField(_("SQL-Abfrage"), help_text=_("Nur lesende Abfragen (SELECT oder WITH). Parameter als :name."))
    cache_seconds = models.PositiveIntegerField(
        _("Ergebnis zwischenspeichern (Sekunden)"), default=60,
        help_text=_("Wie lange ein Ergebnis wiederverwendet wird, bevor die Datenbank erneut gefragt wird."))
    sync_entity = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="synced_by", verbose_name=_("In Tabelle spiegeln"))
    key_column = models.CharField(
        _("Schlüsselspalte"), max_length=80, blank=True,
        help_text=_("Spalte, die einen Datensatz eindeutig kennzeichnet. Leer: Tabelle wird bei jedem Abgleich neu befüllt."))
    created_by = models.ForeignKey(
        settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    sync_interval = models.PositiveIntegerField(
        _("Automatisch abgleichen alle … Minuten"), default=0, help_text=_("0 = nur auf Knopfdruck."))
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_ok = models.BooleanField(default=True)
    last_sync_message = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("Abfrage")
        verbose_name_plural = _("Abfragen")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["app", "slug"], name="query_slug_per_app")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self.app.queries, slugify(self.name) or "abfrage")
        super().save(*args, **kwargs)


class AuditEntry(models.Model):
    """Änderungsprotokoll: wer hat wann was geändert, auf welchem Weg (builder/audit.py).

    Bleibt erhalten, wenn App oder Konto gelöscht werden (Namen werden mitgespeichert).
    Wird nie bearbeitet; gelöscht wird nur nach Ablauf von AUDIT_RETENTION_DAYS.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    app = models.ForeignKey(App, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    app_slug = models.CharField(max_length=50, blank=True)
    app_name = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(settings_module.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    username = models.CharField(max_length=150, blank=True)
    actor = models.CharField(max_length=120, blank=True,
                             help_text=_("Womit: API-Schlüssel, KI-Zugang, Skript …"))
    via = models.CharField(max_length=12)
    action = models.CharField(max_length=12)
    target_type = models.CharField(max_length=12)
    target_id = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    scope = models.CharField(max_length=50, blank=True, help_text=_("Kurzname der Tabelle bei Einträgen und Feldern"))
    changes = models.JSONField(default=dict, blank=True, encoder=UnicodeJSONEncoder)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = _("Protokolleintrag")
        verbose_name_plural = _("Änderungsprotokoll")
        ordering = ["-id"]
        indexes = [models.Index(fields=["app", "-id"], name="audit_app_newest"),
                   models.Index(fields=["target_type", "target_id"], name="audit_target")]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.username or self.actor} {self.action} {self.target_label}"


class PlatformSettings(models.Model):
    """Fachliche Einstellungen, unter /admin/ änderbar ohne Neustart (builder/platform.py).

    Es gibt genau einen Datensatz. Ein leeres Feld heißt: Es gilt der Wert aus der Umgebung
    (settings.py). Zugangsdaten und Technisches (Datenbank, Hosts, Keycloak) gehören nicht hierher.
    """

    public_rate = models.PositiveIntegerField(
        _("Anfragen von Gästen je Adresse und Minute"), null=True, blank=True,
        help_text=_("Öffentliche Seiten. 0 = keine Grenze."))
    ai_writes = models.PositiveIntegerField(
        _("Änderungen je KI-Zugang in 10 Minuten"), null=True, blank=True, help_text=_("0 = keine Grenze."))
    audit_retention_days = models.PositiveIntegerField(
        _("Änderungsprotokoll aufbewahren (Tage)"), null=True, blank=True,
        help_text=_("Danach werden Einträge gelöscht. 0 = nie. Mit dem Datenschutz abstimmen."))
    script_timeout = models.PositiveIntegerField(
        _("Zeitlimit für Skripte normaler Apps (Sekunden)"), null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text=_("1 bis 50. Seiten warten so lange auf ihre Skripte."))
    script_max_calls = models.PositiveIntegerField(
        _("Zugriffe je Skriptlauf (normale Apps)"), null=True, blank=True,
        validators=[MinValueValidator(10)])
    automation_max_timeout_minutes = models.PositiveIntegerField(
        _("Längstes Zeitlimit für Automatisierungen (Minuten)"), null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1440)])
    updated_at = models.DateTimeField(_("Zuletzt geändert"), auto_now=True)
    updated_by = models.ForeignKey(settings_module.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+", editable=False,
                                   verbose_name=_("Geändert von"))

    class Meta:
        verbose_name = _("Einstellungen")
        verbose_name_plural = _("Einstellungen")

    def __str__(self):
        return str(_("Einstellungen des Baukastens"))

    def save(self, *args, **kwargs):
        self.pk = 1  # genau ein Datensatz
        super().save(*args, **kwargs)


class ReleaseNote(models.Model):
    """Was ist neu: Release Notes für alle Nutzer, auf der Seite „Über den Baukasten“ (/ueber/).

    Gepflegt unter /admin/. Sichtbar erst, wenn „veröffentlicht“ angehakt ist.
    """

    version = models.CharField(_("Version"), max_length=20, help_text=_("z. B. 1.1.0"))
    title = models.CharField(_("Titel"), max_length=120, help_text=_("In einem Satz: was bringt diese Version?"))
    body = models.TextField(_("Text"), blank=True,
                            help_text=_("Markdown: Absätze, **fett**, Listen mit „- “, Überschriften mit „### “."))
    released_on = models.DateField(_("Datum"), default=timezone.localdate)
    published = models.BooleanField(_("Veröffentlicht"), default=False,
                                    help_text=_("Erst dann sehen alle Nutzer diesen Eintrag."))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Release Note")
        verbose_name_plural = _("Release Notes")
        ordering = ["-released_on", "-id"]

    def __str__(self):
        return f"{self.version}: {self.title}"


class HomeWidget(models.Model):
    """Persönliches Widget auf der Startseite: verweist auf einen Baustein einer App-Seite."""

    user = models.ForeignKey(settings_module.AUTH_USER_MODEL, related_name="home_widgets", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="home_widgets", on_delete=models.CASCADE)
    block_id = models.CharField(max_length=40)
    title = models.CharField(max_length=80, blank=True)
    width = models.PositiveSmallIntegerField(default=4)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["user", "page", "block_id"], name="home_widget_per_user")]

    def __str__(self):
        return f"{self.user} -> {self.page}:{self.block_id}"
