"""
Permission enforcement helpers built on top of apps.rbac models.

Usage:
    @permission_required("manage_payroll")
    def run_payroll(request): ...

    class PayrollListView(PermissionRequiredMixin, ListView):
        permission_codename = "view_payroll"
"""
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def user_has_permission(user, codename: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, "role", None)
    if not role:
        return False
    return role.permissions.filter(codename=codename).exists()


def permission_required(codename, raise_exception=False):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if user_has_permission(request.user, codename):
                return view_func(request, *args, **kwargs)
            if raise_exception:
                raise PermissionDenied
            messages.error(request, "You don't have permission to access that.")
            return redirect("dashboard:router")
        return _wrapped
    return decorator


def role_required(*role_names):
    """Restrict a view to specific role names (e.g. role_required('Admin', 'HR Manager'))."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            role = getattr(user, "role", None)
            if role and role.name in role_names:
                return view_func(request, *args, **kwargs)
            messages.error(request, "Your role doesn't have access to that page.")
            return redirect("dashboard:router")
        return _wrapped
    return decorator


class PermissionRequiredMixin:
    """CBV mixin: set `permission_codename = "..."` on the view class."""
    permission_codename = None

    def dispatch(self, request, *args, **kwargs):
        if self.permission_codename and not user_has_permission(request.user, self.permission_codename):
            messages.error(request, "You don't have permission to access that.")
            return redirect("dashboard:router")
        return super().dispatch(request, *args, **kwargs)


class RoleRequiredMixin:
    """CBV mixin: set `allowed_roles = ["Admin", "HR Manager"]` on the view class."""
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        role = getattr(user, "role", None)
        if not role or (self.allowed_roles and role.name not in self.allowed_roles):
            messages.error(request, "Your role doesn't have access to that page.")
            return redirect("dashboard:router")
        return super().dispatch(request, *args, **kwargs)
