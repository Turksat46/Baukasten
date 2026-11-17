"""Zeitpläne der Automatisierungen: wann ein Skript als Nächstes läuft.

- „alle N Minuten“: Termine im Abstand N. Läuft ein Lauf über einen oder mehrere Termine
  hinaus, entfallen diese (kein Überholen, kein Nachholen); der nächste Lauf startet zum
  nächsten Termin nach dem Ende.
- „täglich um HH:MM“ (wahlweise nur Mo–Fr), in der Zeitzone des Baukastens.
- „läuft ständig“ und „nur von Hand“ haben keine Termine.
"""
from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from ..models import Script

TIMED = (Script.SCHEDULE, Script.DAILY)


def _step(script):
    return timedelta(minutes=max(script.interval_minutes or 1, 1))


def _daily_slots(script, after, until=None, limit=400):
    """Tägliche Termine nach „after“ (ausschließlich): bis „until“ (einschließlich) oder nur der erste."""
    tz = timezone.get_current_timezone()
    day = timezone.localtime(after, tz).date()
    for _i in range(limit):
        slot = timezone.make_aware(datetime.combine(day, script.daily_time), tz)
        day += timedelta(days=1)
        if slot <= after or (script.weekdays_only and slot.weekday() >= 5):
            continue
        if until is not None and slot > until:
            return
        yield slot
        if until is None:
            return


def following(script, moment):
    """Termin nach „moment“ (ausschließlich), oder None ohne Zeitplan."""
    if script.trigger == Script.SCHEDULE:
        return moment + _step(script)
    if script.trigger == Script.DAILY and script.daily_time:
        return next(_daily_slots(script, moment), None)
    return None


def first_run(script, now=None):
    """Erster Termin nach dem Speichern im Designer."""
    now = now or timezone.now()
    if script.trigger == Script.SCHEDULE:
        if script.last_run_at:
            return max(script.last_run_at + _step(script), now)
        return now
    return following(script, now)


def next_after_start(script, planned, now):
    """Nächster Termin, wenn ein geplanter Lauf (Termin „planned“) jetzt startet. Lag der Dienst
    länger still, wird nichts nachgeholt: dann zählt der nächste Termin ab jetzt."""
    nxt = following(script, planned or now)
    return nxt if nxt and nxt > now else following(script, now)


def catch_up(script, due, finished):
    """Ein Lauf endet um „finished“; „due“ ist der nächste geplante Termin. Lag der Termin während
    des Laufs, entfällt er. Gibt (nächster Termin, Zahl entfallener Termine) zurück."""
    if script.trigger not in TIMED or due is None or due > finished:
        return due, 0
    if script.trigger == Script.SCHEDULE:
        step = _step(script)
        missed = int((finished - due) / step) + 1
        return due + missed * step, missed
    if not script.daily_time:
        return None, 0
    missed = 1 + len(list(_daily_slots(script, due, until=finished)))
    return next(_daily_slots(script, finished), None), missed


def describe(script):
    """Kurze Beschreibung des Zeitplans für die Oberfläche."""
    if script.trigger == Script.SCHEDULE:
        n = script.interval_minutes
        return ngettext("jede Minute", "alle %(n)s Minuten", n) % {"n": n}
    if script.trigger == Script.DAILY:
        time = script.daily_time.strftime("%H:%M") if script.daily_time else "–"
        return (_("werktags um %(time)s") if script.weekdays_only else _("täglich um %(time)s")) % {"time": time}
    if script.trigger == Script.CONTINUOUS:
        return _("läuft ständig")
    return _("nur von Hand oder per Webhook")
