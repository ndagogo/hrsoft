from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.employees.models import Employee
from apps.documents.models import Document
from apps.attendance.models import AttendanceRecord


@require_GET
def healthz(request):
    """Lightweight liveness/readiness probe for load balancers and Docker HEALTHCHECK."""
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


@login_required
def global_search(request):
    q = request.GET.get("q", "").strip()
    results = {"employees": [], "documents": [], "attendance": []}
    if len(q) >= 2:
        from apps.core.permissions import user_has_permission
        from apps.employees.scoping import scoped_employee_queryset

        emp_qs = Employee.objects.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
            | Q(employee_id__icontains=q) | Q(user__email__icontains=q)
        ).select_related("user", "department")
        if user_has_permission(request.user, "view_employees"):
            emp_qs = scoped_employee_queryset(request.user, emp_qs)
        else:
            emp_qs = emp_qs.none()
        results["employees"] = list(
            emp_qs[:8].values(
                "id", "employee_id", "user__first_name", "user__last_name", "department__name"
            )
        )
        if request.user.is_authenticated:
            if user_has_permission(request.user, "view_documents"):
                results["documents"] = list(
                    Document.objects.filter(title__icontains=q)[:5].values("id", "title", "category")
                )
            if user_has_permission(request.user, "view_attendance"):
                from apps.employees.scoping import can_view_all_employees, managed_department_ids
                att_qs = AttendanceRecord.objects.filter(
                    Q(employee__user__first_name__icontains=q)
                    | Q(employee__user__last_name__icontains=q)
                    | Q(employee__employee_id__icontains=q)
                ).select_related("employee__user")
                if not can_view_all_employees(request.user):
                    dept_ids = managed_department_ids(request.user)
                    att_qs = att_qs.filter(employee__department_id__in=dept_ids) if dept_ids else att_qs.none()
                results["attendance"] = list(
                    att_qs[:5].values(
                        "id", "date", "employee__user__first_name", "employee__user__last_name", "status"
                    )
                )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(results)
    return render(request, "core/search.html", {"q": q, "results": results})
