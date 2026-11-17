"""Anmeldung über Keycloak (OpenID Connect).

Aktiv, sobald die Umgebungsvariablen OIDC_ISSUER, OIDC_CLIENT_ID und
OIDC_CLIENT_SECRET gesetzt sind (siehe README). Nutzer werden beim ersten
Login angelegt; Name, E-Mail, Gruppen und die Designer-Rolle kommen bei jedem
Login aus Keycloak.
"""
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import SuspiciousOperation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

DESIGNER_GROUP = "Baukasten-Designer"


def provider_logout(request):
    """Meldet nach dem Abmelden hier auch bei Keycloak ab."""
    from urllib.parse import urlencode

    params = {
        "client_id": settings.OIDC_RP_CLIENT_ID,
        "post_logout_redirect_uri": request.build_absolute_uri("/"),
    }
    id_token = request.session.get("oidc_id_token")
    if id_token:
        params["id_token_hint"] = id_token
    return f"{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}"


def claim_names(claims, key):
    """Liest Gruppen- oder Rollennamen; Keycloak liefert Gruppen oft als Pfad („/Labor“)."""
    values = claims.get(key) or []
    if isinstance(values, str):
        values = [values]
    return {str(v).rsplit("/", 1)[-1] for v in values if v}


class KeycloakBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        username = claims.get("preferred_username")
        if not username:
            return self.UserModel.objects.none()
        users = self.UserModel.objects.filter(username__iexact=username)
        # Ein lokales Konto mit Passwort wird nie von einem gleichnamigen Keycloak-Konto übernommen.
        if any(user.has_usable_password() for user in users):
            raise SuspiciousOperation("Der Benutzername gehört zu einem lokalen Konto.")
        return users

    def create_user(self, claims):
        user = self.UserModel(username=claims["preferred_username"])
        user.set_unusable_password()
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        user.email = claims.get("email") or ""
        user.first_name = (claims.get("given_name") or "")[:150]
        user.last_name = (claims.get("family_name") or "")[:150]
        user.save()
        self.sync_groups(user, claims)
        return user

    def verify_claims(self, claims):
        return bool(claims.get("preferred_username"))

    def sync_groups(self, user, claims):
        names = claim_names(claims, settings.OIDC_GROUPS_CLAIM)
        roles = claim_names(claims, "roles") | claim_names(claims.get("realm_access") or {}, "roles")
        if settings.OIDC_DESIGNER_ROLE in names | roles:
            names.add(DESIGNER_GROUP)
        else:
            names.discard(DESIGNER_GROUP)
        names |= set(settings.DEFAULT_USER_GROUPS)  # Standardgruppen bleiben immer erhalten
        groups = [Group.objects.get_or_create(name=name[:150])[0] for name in sorted(names)]
        user.groups.set(groups)
        designer = Group.objects.filter(name=DESIGNER_GROUP).first()
        if designer:
            designer.permissions.add(Permission.objects.get(codename="design_apps"))
