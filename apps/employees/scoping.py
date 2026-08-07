"""
Department-scoped employee visibility.

Org-wide roles (HR, Admin, Payroll, etc.) see the full directory.
Heads of Department / Department Managers / Supervisors only see staff
in their own department (and departments they formally head).
"""

from django.db.models import Q

from apps.core.permissions import user_has_permission

from .models import Department, Employee

# Roles that may browse the full employee directory
ORG_WIDE_EMPLOYEE_ROLES = {
    "Admin",
    "HR Manager",
    "HR Officer",
    "Auditor",
    "Payroll Officer",
    "IT Administrator",
    "General Manager",
    "Reception",
}

# Roles that must be limited to their department
DEPARTMENT_SCOPED_ROLES = {
    "Department Manager",
    "Department Head",
    "Supervisor",
}


def _role_name(user) -> str:
    role = getattr(user, "role", None)
    return role.name if role else ""


def can_view_all_employees(user) -> bool:
    """True if the user may see every employee across the organization."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user_has_permission(user, "manage_employees"):
        return True
    name = _role_name(user)
    if name in ORG_WIDE_EMPLOYEE_ROLES:
        return True
    # Explicit department-scoped roles never get org-wide access via role name alone
    if name in DEPARTMENT_SCOPED_ROLES:
        return False
    # Fallback: view_employees without a known HOD role → treat as org-wide
    # only when they are not a department head / manager of people
    profile = getattr(user, "employee_profile", None)
    if profile and (
        Department.objects.filter(head=profile).exists()
        or Employee.objects.filter(manager=profile).exists()
    ):
        return False
    return user_has_permission(user, "view_employees")


def managed_department_ids(user) -> set[int]:
    """
    Departments this user is allowed to see when scoped:
    - Their own department
    - Any department where they are the formal head
    """
    ids: set[int] = set()
    profile = getattr(user, "employee_profile", None)
    if not profile:
        return ids
    if profile.department_id:
        ids.add(profile.department_id)
    ids.update(Department.objects.filter(head=profile).values_list("id", flat=True))
    return ids


def scoped_employee_queryset(user, qs=None):
    """Return employees visible to this user."""
    if qs is None:
        qs = Employee.objects.all()
    if can_view_all_employees(user):
        return qs
    dept_ids = managed_department_ids(user)
    if not dept_ids:
        return qs.none()
    profile = getattr(user, "employee_profile", None)
    return qs.filter(
        Q(department_id__in=dept_ids)
        | Q(manager=profile)
        | Q(pk=profile.pk if profile else None)
    ).distinct()


def scoped_department_queryset(user, qs=None):
    """Department filter options — HODs only see their own department(s)."""
    if qs is None:
        qs = Department.objects.all()
    if can_view_all_employees(user):
        return qs
    dept_ids = managed_department_ids(user)
    if not dept_ids:
        return qs.none()
    return qs.filter(pk__in=dept_ids)


def user_can_view_employee(user, employee: Employee) -> bool:
    if can_view_all_employees(user):
        return True
    if not employee:
        return False
    profile = getattr(user, "employee_profile", None)
    if profile and employee.pk == profile.pk:
        return True
    if profile and employee.manager_id == profile.pk:
        return True
    return employee.department_id in managed_department_ids(user)
