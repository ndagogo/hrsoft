from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import permission_required, user_has_permission

from .forms import CompanyForm, RegionForm, BranchForm, UnitForm
from .models import Company, Branch, Region, Unit


@login_required
@permission_required("view_organization")
def org_overview(request):
    can_manage = user_has_permission(request.user, "manage_organization")
    return render(request, "organization/overview.html", {
        "companies": Company.objects.all(),
        "branches": Branch.objects.select_related("company", "region").all(),
        "regions": Region.objects.select_related("company").all(),
        "units": Unit.objects.select_related("department").all(),
        "branch_count": Branch.objects.count(),
        "region_count": Region.objects.count(),
        "unit_count": Unit.objects.count(),
        "can_manage": can_manage,
        "company_form": CompanyForm() if can_manage else None,
        "region_form": RegionForm() if can_manage else None,
        "branch_form": BranchForm() if can_manage else None,
        "unit_form": UnitForm() if can_manage else None,
    })


# --- Company -----------------------------------------------------------------

@login_required
@permission_required("manage_organization")
def company_create(request):
    if request.method == "POST":
        form = CompanyForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Company created.")
        else:
            messages.error(request, "Could not create company. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == "POST":
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            form.save()
            messages.success(request, "Company updated.")
        else:
            messages.error(request, "Could not update company. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def company_delete(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == "POST":
        branch_count = company.branches.count()
        if branch_count:
            messages.error(
                request,
                f"Cannot delete “{company.name}” — it still has {branch_count} branch(es). "
                "Remove or reassign branches first, or deactivate the company instead.",
            )
        else:
            name = company.name
            company.delete()
            messages.success(request, f"Company “{name}” deleted.")
    return redirect("organization:overview")


# --- Region ------------------------------------------------------------------

@login_required
@permission_required("manage_organization")
def region_create(request):
    if request.method == "POST":
        form = RegionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Region created.")
        else:
            messages.error(request, "Could not create region. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def region_edit(request, pk):
    region = get_object_or_404(Region, pk=pk)
    if request.method == "POST":
        form = RegionForm(request.POST, instance=region)
        if form.is_valid():
            form.save()
            messages.success(request, "Region updated.")
        else:
            messages.error(request, "Could not update region. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def region_delete(request, pk):
    region = get_object_or_404(Region, pk=pk)
    if request.method == "POST":
        branch_count = region.branches.count()
        if branch_count:
            messages.error(
                request,
                f"Cannot delete “{region.name}” — {branch_count} branch(es) still use it. "
                "Reassign those branches first.",
            )
        else:
            name = region.name
            region.delete()
            messages.success(request, f"Region “{name}” deleted.")
    return redirect("organization:overview")


# --- Branch ------------------------------------------------------------------

@login_required
@permission_required("manage_organization")
def branch_create(request):
    if request.method == "POST":
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Branch created.")
        else:
            messages.error(request, "Could not create branch. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, "Branch updated.")
        else:
            messages.error(request, "Could not update branch. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def branch_delete(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        emp_count = branch.employees.count()
        dept_count = branch.departments.count()
        if emp_count or dept_count:
            parts = []
            if emp_count:
                parts.append(f"{emp_count} employee(s)")
            if dept_count:
                parts.append(f"{dept_count} department(s)")
            messages.error(
                request,
                f"Cannot delete “{branch.name}” — still linked to {' and '.join(parts)}. "
                "Reassign them first, or deactivate the branch instead.",
            )
        else:
            name = branch.name
            branch.delete()
            messages.success(request, f"Branch “{name}” deleted.")
    return redirect("organization:overview")


# --- Unit --------------------------------------------------------------------

@login_required
@permission_required("manage_organization")
def unit_create(request):
    if request.method == "POST":
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Unit created.")
        else:
            messages.error(request, "Could not create unit. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def unit_edit(request, pk):
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        form = UnitForm(request.POST, instance=unit)
        if form.is_valid():
            form.save()
            messages.success(request, "Unit updated.")
        else:
            messages.error(request, "Could not update unit. Check the form fields.")
    return redirect("organization:overview")


@login_required
@permission_required("manage_organization")
def unit_delete(request, pk):
    unit = get_object_or_404(Unit, pk=pk)
    if request.method == "POST":
        name = unit.name
        unit.delete()
        messages.success(request, f"Unit “{name}” deleted.")
    return redirect("organization:overview")
