"""Employee CSV/Excel import and export."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exports import build_export_response, read_uploaded_rows
from apps.rbac.models import Role
from .models import Department, Designation, Employee, EmploymentStatus, EmploymentType, Gender
from .utils import generate_employee_id

User = get_user_model()

IMPORT_DEFAULT_PASSWORD = "ChangeMe@1234"

EMPLOYEE_EXPORT_HEADERS = [
    "employee_id",
    "username",
    "first_name",
    "last_name",
    "email",
    "phone_number",
    "role",
    "department",
    "designation",
    "manager_employee_id",
    "gender",
    "date_of_birth",
    "date_joined",
    "employment_type",
    "status",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "basic_salary",
    "bank_name",
    "bank_account_number",
    "tax_id",
    "biometric_id",
    "leave_balance_days",
]

EMPLOYEE_IMPORT_REQUIRED = {"username", "first_name", "last_name", "email", "date_joined"}


def filter_employees(request):
    from .scoping import can_view_all_employees, scoped_department_queryset, scoped_employee_queryset

    qs = scoped_employee_queryset(
        request.user,
        Employee.objects.select_related(
            "user", "user__role", "department", "designation", "manager"
        ),
    )

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
        allowed = scoped_department_queryset(request.user)
        if can_view_all_employees(request.user) or allowed.filter(pk=dept).exists():
            qs = qs.filter(department_id=dept)

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    return qs.order_by("employee_id")


def employee_to_row(employee: Employee) -> list:
    user = employee.user
    return [
        employee.employee_id,
        user.username,
        user.first_name,
        user.last_name,
        user.email,
        user.phone_number,
        user.role.name if user.role else "",
        employee.department.name if employee.department else "",
        employee.designation.title if employee.designation else "",
        employee.manager.employee_id if employee.manager else "",
        employee.gender,
        _format_date(employee.date_of_birth),
        _format_date(employee.date_joined),
        employee.employment_type,
        employee.status,
        employee.address,
        employee.emergency_contact_name,
        employee.emergency_contact_phone,
        str(employee.basic_salary),
        employee.bank_name,
        employee.bank_account_number,
        employee.tax_id,
        employee.biometric_id or "",
        employee.leave_balance_days,
    ]


def export_employees_response(request, fmt: str):
    employees = filter_employees(request)
    rows = [employee_to_row(emp) for emp in employees]
    return build_export_response("employees", fmt, EMPLOYEE_EXPORT_HEADERS, rows)


def import_template_response(fmt: str):
    example = [
        "",
        "jane.doe",
        "Jane",
        "Doe",
        "jane.doe@company.com",
        "+2348012345678",
        "Employee",
        "Engineering",
        "Software Engineer",
        "",
        "F",
        "1990-05-15",
        timezone.now().date().isoformat(),
        "full_time",
        "active",
        "12 Main Street",
        "John Doe",
        "+2348098765432",
        "250000",
        "First Bank",
        "0123456789",
        "TAX-001",
        "BIO-1001",
        "21",
    ]
    return build_export_response("employee_import_template", fmt, EMPLOYEE_EXPORT_HEADERS, [example])


def import_employees_from_file(uploaded_file) -> dict:
    try:
        _, rows = read_uploaded_rows(uploaded_file)
    except ValueError as exc:
        return {"created": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}

    created = updated = skipped = 0
    errors = []

    for line_no, row in enumerate(rows, start=2):
        try:
            result = _import_single_row(row)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"Row {line_no}: {exc}")

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


@transaction.atomic
def _import_single_row(row: dict) -> str:
    normalized = {_normalize_key(k): ("" if v is None else str(v).strip()) for k, v in row.items()}
    missing = [field for field in EMPLOYEE_IMPORT_REQUIRED if not normalized.get(field)]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    username = normalized["username"]
    employee_id = normalized.get("employee_id")

    employee = None
    user = None
    if employee_id:
        employee = Employee.objects.select_related("user").filter(employee_id=employee_id).first()
        if employee:
            user = employee.user
    if not user:
        user = User.objects.filter(username=username).first()
        if user:
            employee = getattr(user, "employee_profile", None)

    if user and employee:
        _update_employee(user, employee, normalized)
        return "updated"

    if user and not employee:
        employee = Employee.objects.create(
            user=user,
            employee_id=employee_id or generate_employee_id(),
            date_joined=_parse_date(normalized["date_joined"]),
        )
        _update_employee(user, employee, normalized)
        return "created"

    if employee and not user:
        raise ValueError(f"Employee {employee_id} exists but has no linked user account.")

    role = _resolve_role(normalized.get("role"))
    if not role:
        raise ValueError("Role is required for new employees (e.g. 'Employee').")

    user = User(
        username=username,
        first_name=normalized["first_name"],
        last_name=normalized["last_name"],
        email=normalized["email"],
        phone_number=normalized.get("phone_number", ""),
        role=role,
        must_change_password=True,
        is_active=True,
        is_active_employee=True,
    )
    user.set_password(IMPORT_DEFAULT_PASSWORD)
    user.save()

    employee = Employee.objects.create(
        user=user,
        employee_id=employee_id or generate_employee_id(),
        date_joined=_parse_date(normalized["date_joined"]),
    )
    _update_employee(user, employee, normalized)
    return "created"


def _update_employee(user: User, employee: Employee, data: dict):
    user.first_name = data.get("first_name") or user.first_name
    user.last_name = data.get("last_name") or user.last_name
    user.email = data.get("email") or user.email
    if data.get("phone_number"):
        user.phone_number = data["phone_number"]
    role = _resolve_role(data.get("role"))
    if role:
        user.role = role

    employee.department = _resolve_department(data.get("department"))
    employee.designation = _resolve_designation(data.get("designation"), employee.department)
    employee.manager = _resolve_manager(data.get("manager_employee_id"))
    if data.get("gender") in dict(Gender.choices):
        employee.gender = data["gender"]
    if data.get("date_of_birth"):
        employee.date_of_birth = _parse_date(data["date_of_birth"])
    if data.get("date_joined"):
        employee.date_joined = _parse_date(data["date_joined"])
    if data.get("employment_type") in dict(EmploymentType.choices):
        employee.employment_type = data["employment_type"]
    if data.get("status") in dict(EmploymentStatus.choices):
        employee.status = data["status"]
        user.is_active_employee = data["status"] == EmploymentStatus.ACTIVE
        user.is_active = data["status"] == EmploymentStatus.ACTIVE
    for field in ("address", "emergency_contact_name", "emergency_contact_phone", "bank_name", "bank_account_number", "tax_id"):
        if data.get(field):
            setattr(employee, field, data[field])
    if data.get("basic_salary"):
        employee.basic_salary = _parse_decimal(data["basic_salary"])
    if data.get("biometric_id"):
        employee.biometric_id = data["biometric_id"] or None
    if data.get("leave_balance_days"):
        employee.leave_balance_days = int(data["leave_balance_days"])
    user.save()
    employee.save()


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


def _resolve_role(name: str):
    if not name:
        return None
    return Role.objects.filter(name__iexact=name.strip()).first()


def _resolve_department(name: str):
    if not name:
        return None
    return Department.objects.filter(Q(name__iexact=name) | Q(code__iexact=name)).first()


def _resolve_designation(title: str, department):
    if not title:
        return None
    qs = Designation.objects.filter(title__iexact=title)
    if department:
        match = qs.filter(department=department).first()
        if match:
            return match
    return qs.first()


def _resolve_manager(employee_id: str):
    if not employee_id:
        return None
    return Employee.objects.filter(employee_id=employee_id).first()


def _parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.")


def _parse_decimal(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid number '{value}'.") from exc


def _format_date(value) -> str:
    return value.isoformat() if value else ""
