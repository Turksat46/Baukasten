from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

handler403 = "builder.views.permission_denied"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("passwort/", auth_views.PasswordChangeView.as_view(success_url="/profil/"), name="password_change"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("builder.urls")),
]

if settings.OIDC_ENABLED:
    from mozilla_django_oidc.views import OIDCLogoutView

    urlpatterns += [
        path("oidc/", include("mozilla_django_oidc.urls")),
        path("logout/", OIDCLogoutView.as_view(), name="logout"),
    ]
else:
    urlpatterns.append(path("logout/", auth_views.LogoutView.as_view(), name="logout"))
