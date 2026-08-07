import io

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.permissions import permission_required, user_has_permission
from apps.employees.models import Employee

from .forms import (
    AssetForm,
    AssetRequestForm,
    AssignAssetForm,
    DisposeAssetForm,
    MaintenanceForm,
    ReturnAssetForm,
    TransferAssetForm,
)
from .models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetMaintenance,
    AssetRequest,
    AssetRequestStatus,
    AssetStatus,
    MaintenanceStatus,
)
from .services import (
    advance_asset_request,
    approve_asset,
    assign_asset,
    complete_maintenance,
    dashboard_metrics,
    dispose_asset,
    employee_active_assignments,
    employee_offboarding_ready,
    issue_from_request,
    log_history,
    open_maintenance,
    register_asset,
    return_asset,
    transfer_asset,
)
from .models import AssetHistory


def _can_manage(user):
    return user_has_permission(user, "manage_assets")


def _employee_for_user(user):
    return getattr(user, "employee_profile", None)


@login_required
@permission_required("view_assets")
def asset_dashboard(request):
    metrics = dashboard_metrics()
    by_category = (
        Asset.objects.filter(is_active=True)
        .values("category__name", "category__group")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    by_branch = (
        Asset.objects.filter(is_active=True)
        .values("branch__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:8]
    )
    open_maint = AssetMaintenance.objects.filter(status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS])[:8]
    from .models import AssetHistory
    history = AssetHistory.objects.select_related("asset", "actor", "employee__user")[:15]
    pending = Asset.objects.filter(status=AssetStatus.PENDING_APPROVAL, is_active=True)[:10]
    open_maint = AssetMaintenance.objects.filter(status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS])[:8]
    return render(request, "assets/dashboard.html", {
        "metrics": metrics,
        "by_category": by_category,
        "by_branch": by_branch,
        "history": history,
        "pending": pending,
        "open_maint": open_maint,
        "can_manage": _can_manage(request.user),
    })


@login_required
@permission_required("view_assets")
def asset_list(request):
    qs = Asset.objects.filter(is_active=True).select_related("category", "branch", "department")
    status = request.GET.get("status")
    category = request.GET.get("category")
    branch = request.GET.get("branch")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if category:
        qs = qs.filter(category_id=category)
    if branch:
        qs = qs.filter(branch_id=branch)
    if q:
        qs = qs.filter(
            Q(asset_number__icontains=q) | Q(name__icontains=q) |
            Q(serial_number__icontains=q) | Q(barcode__icontains=q)
        )
    return render(request, "assets/list.html", {
        "assets": qs,
        "categories": AssetCategory.objects.filter(is_active=True),
        "status_choices": AssetStatus.choices,
        "can_manage": _can_manage(request.user),
    })


@login_required
@permission_required("view_assets")
def asset_detail(request, pk):
    asset = get_object_or_404(
        Asset.objects.select_related("category", "branch", "department", "approved_by"),
        pk=pk,
    )
    return render(request, "assets/detail.html", {
        "asset": asset,
        "history": asset.history.select_related("actor", "employee__user")[:50],
        "assignments": asset.assignments.select_related("employee__user", "assigned_by").all()[:20],
        "maintenance": asset.maintenance_records.all()[:10],
        "can_manage": _can_manage(request.user),
    })


@login_required
@permission_required("manage_assets")
def asset_create(request):
    if request.method == "POST":
        form = AssetForm(request.POST)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.registered_by = request.user
            asset.status = AssetStatus.PENDING_APPROVAL
            asset.save()
            register_asset(asset, request.user)
            messages.success(request, f"Asset {asset.asset_number} registered — pending approval.")
            return redirect("assets:detail", pk=asset.pk)
    else:
        form = AssetForm()
    return render(request, "assets/form.html", {"form": form, "mode": "create"})


@login_required
@permission_required("manage_assets")
def asset_edit(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = AssetForm(request.POST, instance=asset)
        if form.is_valid():
            form.save()
            messages.success(request, "Asset updated.")
            return redirect("assets:detail", pk=pk)
    else:
        form = AssetForm(instance=asset)
    return render(request, "assets/form.html", {"form": form, "mode": "edit", "asset": asset})


@login_required
@permission_required("manage_assets")
def asset_approve(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        if approve_asset(asset, request.user):
            messages.success(request, f"{asset.asset_number} approved and available.")
        else:
            messages.error(request, "Asset cannot be approved in its current state.")
    return redirect("assets:detail", pk=pk)


@login_required
@permission_required("manage_assets")
def asset_assign(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = AssignAssetForm(request.POST)
        if form.is_valid():
            try:
                assign_asset(
                    asset, form.cleaned_data["employee"], user=request.user,
                    condition=form.cleaned_data["condition"],
                    accessories=form.cleaned_data["accessories_issued"],
                    expected_return=form.cleaned_data.get("expected_return_date"),
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(request, "Asset assigned successfully.")
                return redirect("assets:detail", pk=pk)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = AssignAssetForm()
    return render(request, "assets/assign.html", {"form": form, "asset": asset})


@login_required
@permission_required("manage_assets")
def assignment_return(request, pk):
    assignment = get_object_or_404(
        AssetAssignment.objects.select_related("asset", "employee__user"), pk=pk, is_active=True,
    )
    if request.method == "POST":
        form = ReturnAssetForm(request.POST)
        if form.is_valid():
            return_asset(
                assignment, user=request.user,
                condition_on_return=form.cleaned_data["condition_on_return"],
                inspection_notes=form.cleaned_data.get("inspection_notes", ""),
                accessories_returned=form.cleaned_data.get("accessories_returned", True),
            )
            messages.success(request, "Asset returned and inspected.")
            return redirect("assets:detail", pk=assignment.asset_id)
    else:
        form = ReturnAssetForm()
    return render(request, "assets/return.html", {"form": form, "assignment": assignment})


@login_required
@permission_required("manage_assets")
def asset_transfer(request, pk):
    assignment = get_object_or_404(
        AssetAssignment.objects.select_related("asset", "employee__user", "department"),
        pk=pk, is_active=True,
    )
    if request.method == "POST":
        form = TransferAssetForm(request.POST)
        if form.is_valid():
            ttype = form.cleaned_data["transfer_type"]
            try:
                if ttype == "employee" and form.cleaned_data["to_employee"]:
                    transfer_asset(
                        assignment, user=request.user,
                        to_employee=form.cleaned_data["to_employee"],
                        notes=form.cleaned_data.get("notes", ""),
                    )
                elif ttype == "department" and form.cleaned_data["to_department"]:
                    transfer_asset(
                        assignment, user=request.user,
                        to_department=form.cleaned_data["to_department"],
                        notes=form.cleaned_data.get("notes", ""),
                    )
                else:
                    raise ValueError("Select a valid transfer target.")
                messages.success(request, "Transfer recorded.")
                return redirect("assets:detail", pk=assignment.asset_id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = TransferAssetForm()
    return render(request, "assets/transfer.html", {"form": form, "assignment": assignment})


@login_required
@permission_required("manage_assets")
def asset_maintenance_create(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = MaintenanceForm(request.POST)
        if form.is_valid():
            open_maintenance(
                asset, user=request.user,
                problem=form.cleaned_data["problem"],
                technician=form.cleaned_data.get("technician", ""),
                vendor=form.cleaned_data.get("vendor", ""),
            )
            messages.success(request, "Maintenance request opened.")
            return redirect("assets:detail", pk=pk)
    else:
        form = MaintenanceForm()
    return render(request, "assets/maintenance_form.html", {"form": form, "asset": asset})


@login_required
@permission_required("manage_assets")
def maintenance_complete(request, pk):
    record = get_object_or_404(AssetMaintenance, pk=pk)
    if request.method == "POST":
        complete_maintenance(
            record, user=request.user,
            repair_cost=request.POST.get("repair_cost") or 0,
            notes=request.POST.get("notes", ""),
            next_date=request.POST.get("next_maintenance_date") or None,
        )
        messages.success(request, "Maintenance marked complete.")
    return redirect("assets:detail", pk=record.asset_id)


@login_required
@permission_required("manage_assets")
def asset_dispose(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == "POST":
        form = DisposeAssetForm(request.POST)
        if form.is_valid():
            dispose_asset(
                asset, user=request.user,
                reason=form.cleaned_data["reason"],
                method=form.cleaned_data.get("method", ""),
                salvage_value=form.cleaned_data.get("salvage_value") or 0,
            )
            messages.success(request, "Asset disposed.")
            return redirect("assets:list")
    else:
        form = DisposeAssetForm()
    return render(request, "assets/dispose.html", {"form": form, "asset": asset})


@login_required
def asset_qr(request, pk):
    asset = get_object_or_404(
        Asset.objects.select_related("category", "branch", "department"),
        pk=pk,
    )
    if not user_has_permission(request.user, "view_assets"):
        emp = _employee_for_user(request.user)
        assigned = asset.assigned_employee
        if not emp or not assigned or assigned.pk != emp.pk:
            return redirect("dashboard:router")
    if request.GET.get("format") == "png":
        url = request.build_absolute_uri(reverse("assets:qr", kwargs={"pk": pk}))
        img = qrcode.make(url, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return HttpResponse(buf.getvalue(), content_type="image/png")
    assignment = asset.current_assignment
    return render(request, "assets/qr.html", {"asset": asset, "assignment": assignment})


@login_required
def my_assets(request):
    emp = _employee_for_user(request.user)
    if not emp:
        messages.info(request, "No employee profile linked to your account.")
        return redirect("dashboard:router")
    assignments = employee_active_assignments(emp)
    return render(request, "assets/my_assets.html", {
        "assignments": assignments,
        "employee": emp,
    })


@login_required
def asset_request_list(request):
    emp = _employee_for_user(request.user)
    can_manage = _can_manage(request.user)
    if can_manage:
        requests_qs = AssetRequest.objects.select_related("employee__user", "category").all()
    elif emp:
        requests_qs = AssetRequest.objects.filter(employee=emp).select_related("category")
    else:
        return redirect("dashboard:router")
    return render(request, "assets/requests.html", {
        "requests": requests_qs[:100],
        "can_manage": can_manage,
        "can_approve": can_manage or user_has_permission(request.user, "approve_leave"),
    })


@login_required
def asset_request_create(request):
    emp = _employee_for_user(request.user)
    if not emp:
        messages.error(request, "Employee profile required to request assets.")
        return redirect("dashboard:router")
    if request.method == "POST":
        form = AssetRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = emp
            req.save()
            messages.success(request, "Asset request submitted.")
            return redirect("assets:requests")
    else:
        form = AssetRequestForm()
    return render(request, "assets/request_form.html", {"form": form})


@login_required
@permission_required("manage_assets")
def asset_request_approve(request, pk):
    req = get_object_or_404(AssetRequest.objects.select_related("employee__user", "category"), pk=pk)
    stage = request.POST.get("stage")
    if request.method == "POST" and stage:
        if advance_asset_request(req, user=request.user, stage=stage):
            messages.success(request, f"Request updated: {req.get_status_display()}")
        else:
            messages.error(request, "Could not advance request at this stage.")
    return redirect("assets:requests")


@login_required
@permission_required("manage_assets")
def asset_request_issue(request, pk):
    req = get_object_or_404(AssetRequest, pk=pk)
    asset = get_object_or_404(Asset, pk=request.POST.get("asset_id"), status=AssetStatus.AVAILABLE)
    if request.method == "POST":
        try:
            issue_from_request(req, asset, request.user)
            messages.success(request, "Asset issued from request.")
        except ValueError as e:
            messages.error(request, str(e))
    return redirect("assets:requests")


@login_required
@permission_required("view_employees")
def employee_assets(request, emp_pk):
    employee = get_object_or_404(Employee, pk=emp_pk)
    active = employee_active_assignments(employee)
    history = AssetAssignment.objects.filter(employee=employee).select_related("asset").order_by("-assigned_date")[:30]
    return render(request, "assets/employee_assets.html", {
        "employee": employee,
        "active": active,
        "history": history,
        "offboarding_ready": employee_offboarding_ready(employee),
    })


@login_required
@permission_required("manage_employees")
def offboarding_checklist(request, emp_pk):
    employee = get_object_or_404(Employee, pk=emp_pk)
    active = employee_active_assignments(employee)
    ready = employee_offboarding_ready(employee)
    if request.method == "POST" and ready:
        employee.status = "terminated"
        employee.user.is_active = False
        employee.user.is_active_employee = False
        employee.user.save()
        employee.save()
        messages.success(request, f"{employee.full_name} offboarded — all assets returned.")
        return redirect("employees:list")
    if request.method == "POST" and not ready:
        messages.error(request, "Cannot complete offboarding until all assets are returned.")
    return render(request, "assets/offboarding.html", {
        "employee": employee,
        "active": active,
        "ready": ready,
    })


@login_required
@permission_required("view_assets")
def asset_reports(request):
    fmt = request.GET.get("format", "html")
    report = request.GET.get("report", "register")
    assets = Asset.objects.filter(is_active=True).select_related("category", "branch")
    if report == "warranty":
        soon = timezone.now().date() + timezone.timedelta(days=90)
        assets = assets.filter(warranty_end__lte=soon).order_by("warranty_end")
    elif report == "assigned":
        assets = assets.filter(status=AssetStatus.ASSIGNED)
    if fmt == "csv":
        import csv
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="assets_{report}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Asset Number", "Name", "Category", "Status", "Branch", "Serial", "Warranty End"])
        for a in assets:
            writer.writerow([
                a.asset_number, a.name, a.category.name, a.get_status_display(),
                a.branch.name if a.branch else "", a.serial_number,
                a.warranty_end or "",
            ])
        return response
    return render(request, "assets/reports.html", {"assets": assets[:500], "report": report})
