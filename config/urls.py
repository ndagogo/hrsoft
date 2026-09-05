import re
from urllib.parse import urlsplit

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

from apps.core.views import healthz
from apps.employees.views import invite_onboard

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("rbac/", include("apps.rbac.urls")),
    path("organization/", include("apps.organization.urls")),
    path("employees/", include("apps.employees.urls")),
    path("onboarding/invite/<str:token>/", invite_onboard, name="invite_onboard"),
    path("attendance/", include("apps.attendance.urls")),
    path("leave/", include("apps.leave.urls")),
    path("payroll/", include("apps.payroll.urls")),
    path("recruitment/", include("apps.recruitment.urls")),
    path("performance/", include("apps.performance.urls")),
    path("training/", include("apps.training.urls")),
    path("assets/", include("apps.assets.urls")),
    path("documents/", include("apps.documents.urls")),
    path("visitors/", include("apps.visitors.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("announcements/", include("apps.announcements.urls")),
    path("transport/", include("apps.transport.urls")),
    path("settings/", include("apps.system_settings.urls")),
    path("reports/", include("apps.reports.urls")),
    path("selfservice/", include("apps.selfservice.urls")),
    path("core/", include("apps.core.urls")),
    path("api/", include("apps.attendance.api_urls")),
]


def _serve_media_urlpatterns():
    """Register MEDIA_URL → MEDIA_ROOT even when DEBUG=False.

    django.conf.urls.static.static() intentionally returns [] when DEBUG is
    False, so production (Railway/Gunicorn, no nginx) must wire
    django.views.static.serve explicitly when SERVE_MEDIA is enabled.
    Without this, /media/... falls through to templates/404.html.
    """
    if not (settings.DEBUG or getattr(settings, "SERVE_MEDIA", True)):
        return []
    prefix = settings.MEDIA_URL or ""
    if not prefix or urlsplit(prefix).netloc:
        return []
    return [
        re_path(
            r"^%s(?P<path>.*)$" % re.escape(prefix.lstrip("/")),
            serve,
            {"document_root": str(settings.MEDIA_ROOT)},
        ),
    ]


urlpatterns += _serve_media_urlpatterns()

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
