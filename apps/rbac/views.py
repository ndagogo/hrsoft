from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.core.paginator import Paginator
from itertools import groupby
from operator import attrgetter

from apps.core.permissions import permission_required, role_required
from .models import Role, Permission, AuditLog
from .forms import RoleForm, PermissionForm


@login_required
@role_required("Admin")
def role_list(request):
    roles = Role.objects.all().prefetch_related("permissions", "users")
    form = RoleForm()
    return render(request, "rbac/roles.html", {"roles": roles, "form": form})


@login_required
@role_required("Admin")
def role_create(request):
    if request.method == "POST":
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save()
            messages.success(request, f"Role '{role.name}' created. Now assign its permissions.")
            return redirect("rbac:role_builder", pk=role.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    return redirect("rbac:roles")


@login_required
@role_required("Admin")
def role_builder(request, pk):
    """The core 'admin assigns roles, privileges and permissions' screen: a checkbox matrix grouped by category."""
    role = get_object_or_404(Role, pk=pk)
    permissions = Permission.objects.all().order_by("category", "name")
    grouped = {
        category: list(perms)
        for category, perms in groupby(permissions, key=attrgetter("category"))
    }
    assigned_ids = set(role.permissions.values_list("id", flat=True))
    confirm_required = False

    if request.method == "POST":
        selected_raw = request.POST.getlist("permissions")
        selected_ids = [int(pid) for pid in selected_raw if str(pid).isdigit()]
        # Keep the user's toggles visible if confirmation fails
        assigned_ids = set(selected_ids)

        if role.is_system_role and request.POST.get("confirm_system_edit") != "yes":
            confirm_required = True
            messages.warning(
                request,
                f"Changes to '{role.name}' were not saved. Confirm the system-role dialog, then click Save again.",
            )
        else:
            role.permissions.set(selected_ids)
            messages.success(request, f"Permissions updated for '{role.name}'.")
            return redirect("rbac:roles")

    return render(request, "rbac/role_builder.html", {
        "role": role,
        "grouped_permissions": grouped,
        "assigned_ids": assigned_ids,
        "confirm_required": confirm_required,
    })


@login_required
@role_required("Admin")
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if request.method == "POST":
        if role.is_system_role:
            messages.error(request, "System roles can't be deleted.")
        elif role.member_count > 0:
            messages.error(request, f"Can't delete '{role.name}' - {role.member_count} user(s) still assigned to it. Reassign them first.")
        else:
            role.delete()
            messages.success(request, "Role deleted.")
    return redirect("rbac:roles")


@login_required
@role_required("Admin")
def permission_list(request):
    permissions = Permission.objects.all().order_by("category", "name")
    form = PermissionForm()
    if request.method == "POST":
        form = PermissionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Custom permission created. Assign it to roles in the role builder.")
            return redirect("rbac:permissions")
        else:
            messages.error(request, "Please fix the errors below.")
    return render(request, "rbac/permissions.html", {"permissions": permissions, "form": form})


@login_required
@role_required("Admin")
def audit_log(request):
    logs = AuditLog.objects.select_related("user").all()
    paginator = Paginator(logs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "rbac/audit_log.html", {"page_obj": page_obj})
