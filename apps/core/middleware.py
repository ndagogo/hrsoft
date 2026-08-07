"""
Middleware for the HRMS platform.

LoginRequiredMiddleware
    Locks down every view by default unless it's in settings.PUBLIC_URLS
    or the path starts with /static or /media. This keeps individual view
    files free of repetitive @login_required decorators while making the
    "secure by default" posture explicit and auditable in one place.

AuditLogMiddleware
    Writes a lightweight audit trail row for state-changing requests
    (POST/PUT/PATCH/DELETE) so admins can see who-did-what-when across the
    system - a baseline enterprise compliance requirement.
"""
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.utils.deprecation import MiddlewareMixin


class LoginRequiredMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path

        if path.startswith(settings.STATIC_URL) or path.startswith(settings.MEDIA_URL):
            return None

        if any(path.startswith(p) for p in settings.PUBLIC_URLS):
            return None

        if request.user.is_authenticated:
            return None

        return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)


class AuditLogMiddleware(MiddlewareMixin):
    AUDITABLE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def process_response(self, request, response):
        try:
            if (
                request.method in self.AUDITABLE_METHODS
                and getattr(request, "user", None)
                and request.user.is_authenticated
                and not request.path.startswith("/static")
                and 200 <= response.status_code < 400
            ):
                from apps.rbac.models import AuditLog

                AuditLog.objects.create(
                    user=request.user,
                    action=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    ip_address=self._client_ip(request),
                )
        except Exception:
            # Audit logging must never break the request/response cycle.
            pass
        return response

    @staticmethod
    def _client_ip(request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
