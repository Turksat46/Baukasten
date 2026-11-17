"""Profilseite: alles, was zur angemeldeten Person gehört, auf einen Blick."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import ApiKey, App, CustomBlock, DataQuery, Script, ScriptRun, can_design


@login_required
def profile(request):
    user = request.user
    last_run = ScriptRun.objects.filter(script=OuterRef("pk")).order_by("-id")
    scripts = (Script.objects.filter(created_by=user).select_related("app")
               .annotate(last_ok=Subquery(last_run.values("ok")[:1]),
                         last_error=Subquery(last_run.values("error")[:1])))
    usable = [app for app in App.objects.prefetch_related("groups") if app.user_can_use(user)]
    designer = can_design(user)
    return render(request, "builder/profile.html", {
        "designer": designer,
        "local_account": user.has_usable_password(),
        "groups": user.groups.order_by("name"),
        "default_groups": settings.DEFAULT_USER_GROUPS,
        "usable_apps": usable,
        "own_apps": App.objects.filter(created_by=user).annotate(
            n_tables=Count("entities", distinct=True), n_pages=Count("pages", distinct=True)),
        "keys": ApiKey.objects.filter(created_by=user).select_related("app").order_by("app__name", "name"),
        "scripts": scripts.order_by("app__name", "name"),
        "queries": DataQuery.objects.filter(created_by=user).select_related("app", "sync_entity"),
        "blocks": CustomBlock.objects.filter(created_by=user),
        "failures": ScriptRun.objects.filter(script__created_by=user, ok=False)
                    .select_related("script", "script__app")[:10],
    })


@login_required
@require_POST
def delete_key(request, pk):
    """Eigene API-Schlüssel lassen sich hier löschen, fremde nicht."""
    key = get_object_or_404(ApiKey, pk=pk, created_by=request.user)
    key.delete()
    messages.success(request, _("Schlüssel gelöscht. Er funktioniert ab sofort nicht mehr."))
    return redirect("profile")
