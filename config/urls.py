from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.core.views import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("rbac/", include("apps.rbac.urls")),
    path("organization/", include("apps.organization.urls")),
    path("employees/", include("apps.employees.urls")),
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
    path("settings/", include("apps.system_settings.urls")),
    path("reports/", include("apps.reports.urls")),
    path("selfservice/", include("apps.selfservice.urls")),
    path("core/", include("apps.core.urls")),
    path("api/", include("apps.attendance.api_urls")),
]

if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
