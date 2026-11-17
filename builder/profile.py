"""Profilseite: alles, was zur angemeldeten Person gehört, auf einen Blick."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, OuterRef, Subquery
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import ApiKey, App, CustomBlock, DataQuery, DesignerToken, Script, ScriptRun, can_design


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
        "ai_tokens": DesignerToken.objects.filter(user=user) if designer else [],
        # Der neue Schlüssel steht nur in dieser einen Antwort im Klartext.
        "new_ai_token": request.session.pop("new_ai_token", None) if designer else None,
        "ai_url": request.build_absolute_uri(reverse("mcp_designer")),
    })


@login_required
@require_POST
def delete_key(request, pk):
    """Eigene API-Schlüssel lassen sich hier löschen, fremde nicht."""
    key = get_object_or_404(ApiKey, pk=pk, created_by=request.user)
    key.delete()
    messages.success(request, _("Schlüssel gelöscht. Er funktioniert ab sofort nicht mehr."))
    return redirect("profile")


@login_required
@require_POST
def create_designer_token(request):
    """Persönlicher KI-Zugang zum Designer (MCP-Server /mcp/designer/)."""
    if not can_design(request.user):
        raise PermissionDenied
    name = request.POST.get("name", "").strip() or _("KI-Zugang")
    _token, key = DesignerToken.issue(request.user, name)
    request.session["new_ai_token"] = key
    return redirect(reverse("profile") + "#ki-zugang")


@login_required
@require_POST
def delete_designer_token(request, pk):
    get_object_or_404(DesignerToken, pk=pk, user=request.user).delete()
    messages.success(request, _("KI-Zugang gelöscht. Er funktioniert ab sofort nicht mehr."))
    return redirect(reverse("profile") + "#ki-zugang")
