from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from apps.core.permissions import permission_required
from apps.accounts.forms import UserCreateForm, UserEditForm
from apps.assets.services import employee_active_assignments
from .models import Employee, Department, Designation, EmployeeInvite, InviteStatus, EmploymentStatus
from .forms import EmployeeForm, DepartmentForm, DesignationForm, EmployeeInviteForm, SelfOnboardForm
from .conflicts import StaffConflictError, cancel_open_invites_for_email
from .invites import (
    admit_staff,
    complete_self_onboard,
    create_and_send_invite,
    get_valid_pending_invite,
    reject_staff,
)
from .import_export import (
    IMPORT_DEFAULT_PASSWORD,
    export_employees_response,
    import_employees_from_file,
    import_template_response,
)
from .scoping import (
    can_view_all_employees,
    scoped_department_queryset,
    scoped_employee_queryset,
    user_can_view_employee,
)
from .utils import generate_employee_id


@login_required
@permission_required("view_employees")
def employee_list(request):
    qs = scoped_employee_queryset(
        request.user,
        Employee.objects.select_related("user", "department", "designation").prefetch_related("branches"),
    )
    departments = scoped_department_queryset(request.user)
    org_wide = can_view_all_employees(request.user)

    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(
            Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(employee_id__icontains=search)
            | Q(user__email__icontains=search)
        )

    dept = request.GET.get("department")
    if dept:
        # HODs cannot escape scope by picking another department in the URL
        if org_wide or departments.filter(pk=dept).exists():
            qs = qs.filter(department_id=dept)
        else:
            dept = ""

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    profile = getattr(request.user, "employee_profile", None)
    scope_label = ""
    if not org_wide and profile and profile.department:
        scope_label = profile.department.name

    pending_admissions = 0
    from apps.core.permissions import user_has_permission
    if user_has_permission(request.user, "manage_employees"):
        pending_admissions = EmployeeInvite.objects.filter(status=InviteStatus.SUBMITTED).count()

    context = {
        "page_obj": page_obj,
        "departments": departments,
        "search": search,
        "selected_department": dept or "",
        "selected_status": status or "",
        "total_count": qs.count(),
        "org_wide_directory": org_wide,
        "scope_label": scope_label,
        "pending_admissions": pending_admissions,
    }
    return render(request, "employees/list.html", context)


@login_required
@permission_required("view_employees")
def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related("user", "department", "designation", "manager").prefetch_related("branches"),
        pk=pk,
    )
    if not user_can_view_employee(request.user, employee):
        messages.error(request, "You can only view employees in your department.")
        return redirect("employees:list")
    leave_requests = employee.leave_requests.select_related("leave_type", "stand_in_employee__user").order_by("-created_at")[:5]
    asset_assignments = employee_active_assignments(employee)[:10]
    from apps.core.permissions import user_has_permission
    can_view_docs = (
        request.user.is_superuser
        or user_has_permission(request.user, "view_employee_documentation")
        or user_has_permission(request.user, "manage_documents")
        or user_has_permission(request.user, "manage_employees")
    )
    documents = employee.documents.all()[:10] if can_view_docs else []
    return render(request, "employees/detail.html", {
        "employee": employee,
        "leave_requests": leave_requests,
        "asset_assignments": asset_assignments,
        "can_view_docs": can_view_docs,
        "documents": documents,
    })


@login_required
@permission_required("manage_employees")
def employee_create(request):
    if request.method == "POST":
        user_form = UserCreateForm(request.POST, request.FILES)
        employee_form = EmployeeForm(request.POST, request.FILES)
        if user_form.is_valid() and employee_form.is_valid():
            user = user_form.save()
            employee = employee_form.save(commit=False)
            employee.user = user
            employee.employee_id = generate_employee_id()
            employee.save()
            employee_form.save_m2m()
            cancel_open_invites_for_email(
                user.email,
                reason="Cancelled after direct employee create.",
            )
            messages.success(request, f"{user.get_full_name()} was added as a new employee.")
            return redirect("employees:list")
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        user_form = UserCreateForm()
        employee_form = EmployeeForm()

    html = render_to_string("employees/_form_modal_body.html", {
        "user_form": user_form, "employee_form": employee_form, "mode": "create",
    }, request=request)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("modal"):
        return JsonResponse({"html": html, "success": False})
    return render(request, "employees/form_page.html", {"user_form": user_form, "employee_form": employee_form, "mode": "create"})


@login_required
@permission_required("manage_employees")
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        user_form = UserEditForm(request.POST, request.FILES, instance=employee.user)
        employee_form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if user_form.is_valid() and employee_form.is_valid():
            user_form.save()
            employee_form.save()
            messages.success(request, "Employee record updated.")
            return redirect("employees:detail", pk=pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        user_form = UserEditForm(instance=employee.user)
        employee_form = EmployeeForm(instance=employee)

    html = render_to_string("employees/_form_modal_body.html", {
        "user_form": user_form, "employee_form": employee_form, "mode": "edit", "employee": employee,
    }, request=request)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("modal"):
        return JsonResponse({"html": html, "success": False})
    return render(request, "employees/form_page.html", {
        "user_form": user_form, "employee_form": employee_form, "mode": "edit", "employee": employee,
    })


@login_required
@permission_required("manage_employees")
def employee_deactivate(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        employee.status = "terminated"
        employee.user.is_active = False
        employee.user.is_active_employee = False
        employee.user.save()
        employee.save()
        messages.success(request, f"{employee.full_name} has been offboarded.")
    return redirect("employees:list")


@login_required
@permission_required("view_employees")
def employee_export(request):
    fmt = request.GET.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"
    return export_employees_response(request, fmt)


@login_required
@permission_required("manage_employees")
def employee_import(request):
    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if not uploaded:
            messages.error(request, "Please choose a CSV or Excel file to import.")
            return redirect("employees:import")

        result = import_employees_from_file(uploaded)
        summary = (
            f"Import complete: {result['created']} created, "
            f"{result['updated']} updated, {result['skipped']} skipped."
        )
        if result["errors"]:
            messages.warning(request, summary)
            for error in result["errors"][:10]:
                messages.error(request, error)
            if len(result["errors"]) > 10:
                messages.error(request, f"...and {len(result['errors']) - 10} more errors.")
        else:
            messages.success(request, summary)
        return redirect("employees:list")

    return render(request, "employees/import.html", {
        "default_password": IMPORT_DEFAULT_PASSWORD,
    })


@login_required
@permission_required("manage_employees")
def employee_import_template(request):
    fmt = request.GET.get("format", "csv")
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"
    return import_template_response(fmt)


# --- Invites & admissions --------------------------------------------------

@login_required
@permission_required("manage_employees")
def employee_invite(request):
    if request.method == "POST":
        form = EmployeeInviteForm(request.POST)
        if form.is_valid():
            try:
                invite = create_and_send_invite(
                    request,
                    email=form.cleaned_data["email"],
                    role=form.cleaned_data.get("role"),
                    department=form.cleaned_data.get("department"),
                    designation=form.cleaned_data.get("designation"),
                    branches=form.cleaned_data.get("branches"),
                    employment_type=form.cleaned_data.get("employment_type"),
                    manager=form.cleaned_data.get("manager"),
                )
                messages.success(
                    request,
                    f"Invite sent to {invite.email}. They must complete onboarding before you can Admit Staff.",
                )
                return redirect("employees:list")
            except StaffConflictError as exc:
                messages.error(request, exc.messages[0] if exc.messages else str(exc))
            except Exception as exc:
                messages.error(request, f"Could not send invite: {exc}")
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = EmployeeInviteForm()

    html = render_to_string("employees/_invite_modal_body.html", {"form": form}, request=request)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("modal"):
        return JsonResponse({"html": html, "success": False})
    return render(request, "employees/invite_page.html", {"form": form})


@login_required
@permission_required("manage_employees")
def admissions_queue(request):
    invites = (
        EmployeeInvite.objects.filter(
            status__in=[InviteStatus.SUBMITTED, InviteStatus.CONFLICT, InviteStatus.PENDING]
        )
        .select_related("user", "employee", "department", "designation", "role", "invited_by")
        .prefetch_related("branches")
        .order_by("-submitted_at", "-created_at")
    )
    submitted = [i for i in invites if i.status == InviteStatus.SUBMITTED]
    conflicts = [i for i in invites if i.status == InviteStatus.CONFLICT]
    pending = [i for i in invites if i.status == InviteStatus.PENDING]
    pending_employees = Employee.objects.filter(
        status=EmploymentStatus.PENDING_ADMISSION
    ).select_related("user", "department", "designation")
    return render(request, "employees/admissions.html", {
        "submitted_invites": submitted,
        "conflict_invites": conflicts,
        "pending_invites": pending,
        "pending_employees": pending_employees,
    })


@login_required
@permission_required("manage_employees")
@require_POST
def admit_invite(request, pk):
    invite = get_object_or_404(EmployeeInvite, pk=pk)
    try:
        employee = admit_staff(invite)
        messages.success(request, f"{employee.full_name} has been admitted and can now sign in.")
    except StaffConflictError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
    return redirect("employees:admissions")


@login_required
@permission_required("manage_employees")
@require_POST
def reject_invite(request, pk):
    invite = get_object_or_404(EmployeeInvite, pk=pk)
    reject_staff(invite, reason=request.POST.get("reason", "Rejected by HR."))
    messages.success(request, f"Invite for {invite.email} was rejected.")
    return redirect("employees:admissions")


def invite_onboard(request, token):
    """Public self-onboarding form for an invite token."""
    invite = get_valid_pending_invite(token)
    if not invite:
        return render(request, "employees/onboarding_invalid.html", {
            "reason": "not_found",
        }, status=404)

    if invite.status == InviteStatus.EXPIRED:
        return render(request, "employees/onboarding_invalid.html", {"reason": "expired"})
    if invite.status == InviteStatus.SUBMITTED:
        return render(request, "employees/onboarding_invalid.html", {"reason": "already_submitted"})
    if invite.status == InviteStatus.ADMITTED:
        return render(request, "employees/onboarding_invalid.html", {"reason": "admitted"})
    if invite.status == InviteStatus.CANCELLED:
        return render(request, "employees/onboarding_invalid.html", {"reason": "cancelled"})
    if invite.status == InviteStatus.CONFLICT:
        return render(request, "employees/onboarding_invalid.html", {
            "reason": "conflict",
            "conflict_reason": invite.conflict_reason,
        })
    if invite.status != InviteStatus.PENDING:
        return render(request, "employees/onboarding_invalid.html", {"reason": "invalid"})

    if request.method == "POST":
        form = SelfOnboardForm(request.POST, invite=invite)
        if form.is_valid():
            try:
                complete_self_onboard(invite, form.cleaned_data)
                return render(request, "employees/onboarding_thanks.html", {"invite": invite})
            except StaffConflictError as exc:
                messages.error(request, exc.messages[0] if exc.messages else str(exc))
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = SelfOnboardForm(invite=invite)

    return render(request, "employees/onboarding_invite.html", {
        "invite": invite,
        "form": form,
    })


# --- Departments -----------------------------------------------------------

@login_required
@permission_required("manage_departments")
def department_list(request):
    departments = Department.objects.all().prefetch_related("employees")
    designations = Designation.objects.select_related("department").all()
    dept_form = DepartmentForm()
    desig_form = DesignationForm()
    return render(request, "employees/departments.html", {
        "departments": departments,
        "designations": designations,
        "dept_form": dept_form,
        "desig_form": desig_form,
    })


@login_required
@permission_required("manage_departments")
def department_create(request):
    if request.method == "POST":
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Department created.")
        else:
            messages.error(request, "Please correct the errors.")
    return redirect("employees:departments")


@login_required
@permission_required("manage_departments")
def department_edit(request, pk):
    department = get_object_or_404(Department, pk=pk)
    if request.method == "POST":
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            form.save()
            messages.success(request, "Department updated.")
        else:
            messages.error(request, "Please correct the errors.")
    return redirect("employees:departments")


@login_required
@permission_required("manage_departments")
def designation_create(request):
    if request.method == "POST":
        form = DesignationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Designation created.")
        else:
            messages.error(request, "Please correct the errors.")
    return redirect("employees:departments")
