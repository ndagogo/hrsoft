"""
Populates the database with a realistic demo dataset:
  - the full permission catalog
  - 5 roles (Admin, HR Manager, Department Manager, Payroll Officer, Employee)
  - departments & designations
  - ~40 demo employees with logins
  - a demo HikVision device
  - 60 days of biometric attendance history (randomised, realistic)
  - leave types + a mix of pending/approved/rejected leave requests
  - 3 payroll periods, with the most recent processed

Run with: python manage.py seed_demo_data
Safe to re-run: it's idempotent for roles/permissions/departments, and
wipes + regenerates time-series data (attendance/leave/payroll) each time
so the demo always looks current relative to "today".
"""
import random
from datetime import timedelta, datetime, time as dtime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.rbac.models import Permission, Role, PermissionCategory
from apps.accounts.models import User
from apps.employees.models import Department, Designation, Employee, EmploymentType, EmploymentStatus, Gender
from apps.attendance.models import BiometricDevice, RawPunchLog, AttendanceRecord, AttendanceStatus, PunchSource
from apps.leave.models import LeaveType, LeaveRequest, LeaveStatus
from apps.payroll.models import PayrollPeriod, Payslip, PayrollStatus


FIRST_NAMES = [
    "Adaeze", "Tunde", "Ngozi", "Chinedu", "Folake", "Emeka", "Bisi", "Kunle", "Amara", "Segun",
    "Yemi", "Ifeoma", "Damilola", "Uche", "Funke", "Obinna", "Chiamaka", "Babatunde", "Ngozichukwu", "Olamide",
    "Grace", "David", "Sarah", "Michael", "Joy", "Daniel", "Faith", "Samuel", "Esther", "Victor",
    "Patience", "Emmanuel", "Blessing", "Joseph", "Comfort", "Peter", "Mercy", "Paul", "Gift", "Stephen",
]
LAST_NAMES = [
    "Okafor", "Adeyemi", "Eze", "Balogun", "Nwosu", "Bello", "Okoro", "Afolabi", "Chukwu", "Lawal",
    "Obi", "Adeleke", "Onyema", "Ogundipe", "Nnamdi", "Akinola", "Udo", "Olawale", "Igwe", "Sanni",
    "Anozie", "Babatunde", "Chukwuemeka", "Dauda", "Ekanem", "Fashola", "Garba", "Haruna", "Ikenna", "Jibrin",
]

DEPARTMENTS = [
    ("Engineering", "ENG", ["Software Engineer", "Senior Software Engineer", "Engineering Manager", "QA Engineer"]),
    ("Human Resources", "HRD", ["HR Officer", "HR Manager", "Recruiter"]),
    ("Finance", "FIN", ["Accountant", "Payroll Officer", "Finance Manager"]),
    ("Sales & Marketing", "SLM", ["Sales Executive", "Marketing Officer", "Sales Manager"]),
    ("Operations", "OPS", ["Operations Associate", "Operations Manager", "Logistics Coordinator"]),
    ("Customer Support", "SUP", ["Support Agent", "Support Team Lead"]),
]

PERMISSIONS = [
    ("view_employees", "View employees", PermissionCategory.EMPLOYEES, "Browse the employee directory and profiles."),
    ("manage_employees", "Manage employees", PermissionCategory.EMPLOYEES, "Create, edit and offboard employee records."),
    ("manage_departments", "Manage departments", PermissionCategory.EMPLOYEES, "Create and edit departments & designations."),

    ("view_attendance", "View attendance", PermissionCategory.ATTENDANCE, "View attendance records across the organisation."),
    ("manage_attendance", "Manage attendance", PermissionCategory.ATTENDANCE, "Manually override attendance records."),
    ("manage_devices", "Manage biometric devices", PermissionCategory.ATTENDANCE, "Register and configure HikVision / biometric devices."),

    ("approve_leave", "Approve leave requests", PermissionCategory.LEAVE, "Review and approve/reject leave requests."),
    ("manage_leave_types", "Manage leave types", PermissionCategory.LEAVE, "Configure the leave categories available to staff."),
    ("approve_leave_hr", "Approve leave (HR stage)", PermissionCategory.LEAVE, "Approve leave requests at the Human Resources stage."),
    ("approve_leave_gm", "Approve leave (GM stage)", PermissionCategory.LEAVE, "Final leave approval as General Manager."),

    ("view_payroll", "View payroll", PermissionCategory.PAYROLL, "View payroll periods and payslips."),
    ("manage_payroll", "Manage payroll", PermissionCategory.PAYROLL, "Run payroll and adjust payslips."),

    ("manage_roles", "Manage roles", PermissionCategory.RBAC, "Create roles and assign permissions to them."),

    ("view_reports", "View reports", PermissionCategory.REPORTS, "Access organisation-wide analytics and reports."),

    ("manage_system_settings", "Manage system settings", PermissionCategory.SYSTEM, "Configure platform-wide settings."),

    ("view_employee_documentation", "View employee documentation", PermissionCategory.DOCUMENTS, "View academic, guarantor and other employment documents on employee profiles."),
]

# Extended enterprise permissions merged at seed time
from apps.core.seed_enterprise import EXTRA_PERMISSIONS as _EXTRA_PERMS
_CATEGORY_MAP = {
    "employees": PermissionCategory.EMPLOYEES,
    "attendance": PermissionCategory.ATTENDANCE,
    "leave": PermissionCategory.LEAVE,
    "payroll": PermissionCategory.PAYROLL,
    "rbac": PermissionCategory.RBAC,
    "reports": PermissionCategory.REPORTS,
    "system": PermissionCategory.SYSTEM,
    "recruitment": PermissionCategory.RECRUITMENT,
    "performance": PermissionCategory.PERFORMANCE,
    "training": PermissionCategory.TRAINING,
    "assets": PermissionCategory.ASSETS,
    "documents": PermissionCategory.DOCUMENTS,
    "visitors": PermissionCategory.VISITORS,
    "organization": PermissionCategory.ORGANIZATION,
    "announcements": PermissionCategory.ANNOUNCEMENTS,
}
PERMISSIONS.extend([(c, n, _CATEGORY_MAP[cat], d) for c, n, cat, d in _EXTRA_PERMS])

ROLE_DEFINITIONS = {
    "Admin": {
        "description": "Full administrative access across the entire platform.",
        "dashboard_key": "admin",
        "color": "#111a2e",
        "permissions": "__all__",
    },
    "HR Manager": {
        "description": "Manages employee records, leave approvals and HR policy.",
        "dashboard_key": "hr",
        "color": "#8b5cf6",
        "permissions": [
            "view_employees", "manage_employees", "manage_departments",
            "view_organization", "manage_organization",
            "view_attendance", "manage_attendance",
            "approve_leave", "approve_leave_hr", "manage_leave_types",
            "view_payroll", "view_reports", "export_reports",
            "view_recruitment", "manage_recruitment",
            "view_performance", "view_training", "view_documents", "manage_documents",
            "view_employee_documentation",
            "view_visitors", "import_data",
            "create_announcement", "approve_announcement",
        ],
    },
    "Department Manager": {
        "description": "Oversees their department's team, attendance and leave approvals.",
        "dashboard_key": "manager",
        "color": "#14b8a6",
        "permissions": ["view_employees", "view_attendance", "approve_leave", "view_reports"],
    },
    "General Manager": {
        "description": "Final operational authority — final leave approvals and executive oversight.",
        "dashboard_key": "admin",
        "color": "#0f766e",
        "permissions": [
            "view_employees", "view_attendance", "view_payroll", "view_reports", "export_reports",
            "approve_leave", "approve_leave_gm", "approve_announcement", "create_announcement",
        ],
    },
    "Payroll Officer": {
        "description": "Processes payroll runs and manages payslip adjustments.",
        "dashboard_key": "payroll",
        "color": "#f5a524",
        "permissions": ["view_employees", "view_attendance", "view_payroll", "manage_payroll", "view_reports"],
    },
    "Employee": {
        "description": "Standard staff access: own attendance, leave and payslips.",
        "dashboard_key": "employee",
        "color": "#324269",
        "permissions": [],
    },
}

LEAVE_TYPES = [
    ("Annual Leave", 21, True, "#0ea5e9"),
    ("Sick Leave", 10, True, "#f43f5e"),
    ("Maternity/Paternity Leave", 90, True, "#8b5cf6"),
    ("Compassionate Leave", 5, True, "#64748b"),
    ("Unpaid Leave", 0, True, "#94a3b8"),
]


class Command(BaseCommand):
    help = "Populates the database with demo HR data: roles, employees, attendance, leave and payroll."

    def add_arguments(self, parser):
        parser.add_argument("--employees", type=int, default=250, help="Number of demo employees to create.")
        parser.add_argument("--days", type=int, default=365, help="Days of attendance history to generate.")
        parser.add_argument("--enterprise", action="store_true", default=True, help="Seed enterprise modules (org, recruitment, etc.).")

    @transaction.atomic
    def handle(self, *args, **options):
        n_employees = options["employees"]
        n_days = options["days"]

        self.stdout.write("Seeding permissions & roles…")
        roles = self._seed_permissions_and_roles()

        self.stdout.write("Seeding departments & designations…")
        designations = self._seed_departments()

        self.stdout.write("Seeding leave types…")
        leave_types = self._seed_leave_types()

        self.stdout.write("Seeding biometric device…")
        device = self._seed_device()

        self.stdout.write(f"Seeding {n_employees} employees…")
        employees = self._seed_employees(n_employees, roles, designations)

        self.stdout.write(f"Seeding {n_days} days of attendance…")
        self._seed_attendance(employees, device, n_days)

        self.stdout.write("Seeding leave requests…")
        self._seed_leave(employees, leave_types)

        self.stdout.write("Seeding payroll periods…")
        self._seed_payroll(employees)

        if options.get("enterprise", True):
            from apps.core.seed_enterprise import (
                seed_extra_permissions, seed_extra_roles, seed_extra_departments,
                seed_organization, seed_enterprise_modules,
            )
            self.stdout.write("Seeding enterprise permissions & roles…")
            perm_objs = {p.codename: p for p in Permission.objects.all()}
            perm_objs = seed_extra_permissions(perm_objs)
            roles = seed_extra_roles(roles, perm_objs)

            self.stdout.write("Seeding additional departments…")
            designations = seed_extra_departments(designations)

            self.stdout.write("Seeding organization structure…")
            seed_organization()

            self.stdout.write("Seeding enterprise modules…")
            admin_user = User.objects.filter(username="admin").first()
            seed_enterprise_modules(employees, roles, admin_user)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {len(employees)} employees created.\n"
            "Demo logins (password: Demo@1234):\n"
            "  admin / Demo@1234            (Admin - superuser)\n"
            "  hr.manager / Demo@1234       (HR Manager)\n"
            "  dept.manager / Demo@1234     (Department Manager / HOD)\n"
            "  gm.manager / Demo@1234       (General Manager — final leave approval)\n"
            "  payroll.officer / Demo@1234  (Payroll Officer)\n"
            "  employee1 / Demo@1234        (Employee)\n"
            "\nEnterprise data: 5 branches, 20+ departments, 10 roles,\n"
            "recruitment, performance, training, assets, documents, visitors.\n"
            f"Attendance history: {n_days} days. Run with --days 1095 for 3 years.\n"
        ))

    # ------------------------------------------------------------------
    def _seed_permissions_and_roles(self):
        perm_objs = {}
        for codename, name, category, desc in PERMISSIONS:
            perm, _ = Permission.objects.update_or_create(
                codename=codename, defaults={"name": name, "category": category, "description": desc}
            )
            perm_objs[codename] = perm

        roles = {}
        for role_name, cfg in ROLE_DEFINITIONS.items():
            role, _ = Role.objects.update_or_create(
                name=role_name,
                defaults={
                    "description": cfg["description"],
                    "dashboard_key": cfg["dashboard_key"],
                    "color": cfg["color"],
                    "is_system_role": True,
                },
            )
            if cfg["permissions"] == "__all__":
                role.permissions.set(perm_objs.values())
            else:
                role.permissions.set([perm_objs[c] for c in cfg["permissions"]])
            roles[role_name] = role
        return roles

    def _seed_departments(self):
        designations = {}
        for name, code, titles in DEPARTMENTS:
            dept, _ = Department.objects.update_or_create(name=name, defaults={"code": code})
            for i, title in enumerate(titles):
                desig, _ = Designation.objects.update_or_create(
                    title=title, defaults={"department": dept, "level": i + 1}
                )
                designations.setdefault(name, []).append(desig)
        return designations

    def _seed_leave_types(self):
        types = []
        for name, days, approval, color in LEAVE_TYPES:
            lt, _ = LeaveType.objects.update_or_create(
                name=name, defaults={"default_days_per_year": days, "requires_approval": approval, "color": color}
            )
            types.append(lt)
        return types

    def _seed_device(self):
        device, _ = BiometricDevice.objects.update_or_create(
            name="Main Gate Terminal",
            defaults=dict(
                brand="zkteco",
                connection_mode="pull",
                ip_address="192.168.1.201",
                port=4370,
                username="",
                password="",
                comm_key=0,
                location="Main Building - Ground Floor Entrance",
                serial_number="",
                webhook_token="demo-webhook-secret-token-001",
                is_active=True,
                last_sync_status="never",
                last_sync_message="Configured for ZKTeco TCP 4370 (static IP).",
                last_sync_at=None,
            ),
        )
        BiometricDevice.objects.update_or_create(
            name="Floor 3 Office Entrance",
            defaults=dict(
                brand="hikvision",
                connection_mode="push",
                ip_address="192.168.1.202",
                port=80,
                username="admin",
                password="HikDemo@2026",
                comm_key=0,
                location="Floor 3 - Engineering Wing",
                serial_number="DS-K1T331MFWX-DEMO0002",
                webhook_token="demo-webhook-secret-token-002",
                is_active=False,
                last_sync_status="ok",
                last_sync_message="Optional HikVision push terminal (disabled by default).",
                last_sync_at=timezone.now() - timedelta(minutes=11),
            ),
        )
        return device

    def _seed_employees(self, n, roles, designations):
        used_names = set()
        employees = []

        # Fixed, named demo accounts for each role (so login creds are predictable)
        fixed_accounts = [
            dict(username="admin", first="Ada", last="Admin", role=None, is_super=True, dept="Engineering", desig_idx=2),
            dict(username="hr.manager", first="Funke", last="Adeyemi", role="HR Manager", is_super=False, dept="Human Resources", desig_idx=1),
            dict(username="dept.manager", first="Tunde", last="Balogun", role="Department Manager", is_super=False, dept="Engineering", desig_idx=2),
            dict(username="gm.manager", first="Chinedu", last="Okoro", role="General Manager", is_super=False, dept="Administration", desig_idx=1),
            dict(username="payroll.officer", first="Ngozi", last="Eze", role="Payroll Officer", is_super=False, dept="Finance", desig_idx=1),
        ]

        today = timezone.now().date()

        for idx, acc in enumerate(fixed_accounts, start=1):
            user, created = User.objects.get_or_create(
                username=acc["username"],
                defaults=dict(
                    first_name=acc["first"], last_name=acc["last"],
                    email=f"{acc['username']}@northbridge.demo",
                    is_staff=acc["is_super"], is_superuser=acc["is_super"],
                    is_active=True, is_active_employee=True,
                ),
            )
            user.set_password("Demo@1234")
            if acc["role"]:
                user.role = roles[acc["role"]]
            user.save()

            dept = Department.objects.get(name=acc["dept"])
            desig = designations[acc["dept"]][acc["desig_idx"]]
            employee, _ = Employee.objects.update_or_create(
                user=user,
                defaults=dict(
                    employee_id=f"EMP-{idx:04d}",
                    department=dept, designation=desig,
                    gender=Gender.FEMALE if idx % 2 == 0 else Gender.MALE,
                    date_of_birth=today - timedelta(days=365 * random.randint(26, 45)),
                    date_joined=today - timedelta(days=random.randint(180, 1500)),
                    employment_type=EmploymentType.FULL_TIME,
                    status=EmploymentStatus.ACTIVE,
                    basic_salary=random.choice([280000, 350000, 420000, 550000]),
                    bank_name="GTBank", bank_account_number=f"00{random.randint(10000000,99999999)}",
                    tax_id=f"TIN-{random.randint(100000,999999)}",
                    biometric_id=str(1000 + idx),
                    biometric_enrolled=True, face_enrolled=True,
                    leave_balance_days=18,
                ),
            )
            employees.append(employee)
            used_names.add((acc["first"], acc["last"]))

        # Bulk of regular employees, role = Employee, spread across departments
        employee_role = roles["Employee"]
        last_emp = Employee.objects.order_by("-id").first()
        emp_idx = (last_emp.id + 1) if last_emp else len(fixed_accounts) + 1
        existing_count = Employee.objects.count()
        target_total = n + len(fixed_accounts)
        attempts = 0
        while existing_count < target_total and attempts < n * 5:
            attempts += 1
            first, last = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
            if (first, last) in used_names:
                continue
            used_names.add((first, last))

            dept_name, _, _ = random.choice(DEPARTMENTS)
            desig = random.choice(designations[dept_name])
            username = f"{first.lower()}.{last.lower()}"
            if User.objects.filter(username=username).exists():
                continue

            user = User.objects.create(
                username=username, first_name=first, last_name=last,
                email=f"{username}@northbridge.demo",
                is_active=True, is_active_employee=True, role=employee_role,
            )
            user.set_password("Demo@1234")
            user.save()

            employee = Employee.objects.create(
                user=user,
                employee_id=f"EMP-{emp_idx:04d}",
                department=Department.objects.get(name=dept_name),
                designation=desig,
                gender=random.choice([Gender.MALE, Gender.FEMALE]),
                date_of_birth=today - timedelta(days=365 * random.randint(22, 55)),
                date_joined=today - timedelta(days=random.randint(10, 2000)),
                employment_type=random.choices(
                    [EmploymentType.FULL_TIME, EmploymentType.CONTRACT, EmploymentType.INTERN],
                    weights=[80, 15, 5],
                )[0],
                status=EmploymentStatus.ACTIVE,
                basic_salary=random.choice([180000, 220000, 280000, 320000, 400000, 480000]),
                bank_name=random.choice(["GTBank", "Access Bank", "Zenith Bank", "UBA", "First Bank"]),
                bank_account_number=f"00{random.randint(10000000,99999999)}",
                tax_id=f"TIN-{random.randint(100000,999999)}",
                biometric_id=f"BIO-{emp_idx:06d}",
                biometric_enrolled=random.random() > 0.08,
                face_enrolled=random.random() > 0.1,
                fingerprint_enrolled=random.random() > 0.5,
                leave_balance_days=random.randint(8, 21),
            )
            employees.append(employee)
            emp_idx += 1
            existing_count += 1

        # Wire up a couple of department heads + managers now that employees exist
        eng = Department.objects.get(name="Engineering")
        eng_manager = Employee.objects.filter(department=eng, designation__title__icontains="Manager").first()
        if eng_manager:
            eng.head = eng_manager
            eng.save()
            Employee.objects.filter(department=eng).exclude(pk=eng_manager.pk).update(manager=eng_manager)

        for dept_name, _, _ in DEPARTMENTS:
            if dept_name == "Engineering":
                continue
            dept = Department.objects.get(name=dept_name)
            manager = Employee.objects.filter(department=dept, designation__title__icontains="Manager").first()
            if manager:
                dept.head = manager
                dept.save()
                Employee.objects.filter(department=dept).exclude(pk=manager.pk).update(manager=manager)

        return list(Employee.objects.select_related("user", "department").all())

    def _seed_attendance(self, employees, device, n_days):
        RawPunchLog.objects.all().delete()
        AttendanceRecord.objects.all().delete()

        today = timezone.now().date()

        for day_offset in range(n_days, -1, -1):
            day = today - timedelta(days=day_offset)
            is_weekend = day.weekday() >= 5

            for employee in employees:
                if employee.date_joined > day:
                    continue

                if is_weekend:
                    if random.random() < 0.04:  # rare weekend work
                        pass
                    else:
                        continue

                roll = random.random()
                if roll < 0.04:
                    AttendanceRecord.objects.create(employee=employee, date=day, status=AttendanceStatus.ABSENT, source=PunchSource.FACE)
                    continue
                if roll < 0.06:
                    AttendanceRecord.objects.create(employee=employee, date=day, status=AttendanceStatus.ON_LEAVE, source=PunchSource.MANUAL)
                    continue

                is_late = roll < 0.22
                base_hour, base_minute = (9, random.randint(11, 45)) if is_late else (8, random.randint(40, 59))
                check_in_dt = timezone.make_aware(datetime.combine(day, dtime(base_hour, base_minute, random.randint(0, 59))))

                work_hours = random.uniform(7.5, 9.2)
                check_out_dt = check_in_dt + timedelta(hours=work_hours)

                source = random.choices(
                    [PunchSource.FACE, PunchSource.FINGERPRINT, PunchSource.CARD],
                    weights=[70, 20, 10],
                )[0]

                RawPunchLog.objects.create(
                    device=device, employee=employee, device_employee_no=employee.biometric_id,
                    direction="in", source=source, timestamp=check_in_dt, matched=True,
                    raw_payload={"demo": True, "event": "checkIn"},
                )
                RawPunchLog.objects.create(
                    device=device, employee=employee, device_employee_no=employee.biometric_id,
                    direction="out", source=source, timestamp=check_out_dt, matched=True,
                    raw_payload={"demo": True, "event": "checkOut"},
                )

                late_minutes = max(0, int((check_in_dt - timezone.make_aware(datetime.combine(day, dtime(9, 0)))).total_seconds() / 60) - 10) if is_late else 0

                AttendanceRecord.objects.create(
                    employee=employee, date=day,
                    check_in=check_in_dt, check_out=check_out_dt,
                    status=AttendanceStatus.LATE if is_late else AttendanceStatus.PRESENT,
                    source=source,
                    worked_hours=round(work_hours, 2),
                    late_minutes=late_minutes,
                )

        # A handful of unmatched punches (bad enrolment / wrong device id) for realism on the devices page
        for _ in range(5):
            RawPunchLog.objects.create(
                device=device, employee=None, device_employee_no=str(random.randint(9000, 9999)),
                direction=random.choice(["in", "out"]), source=PunchSource.FACE,
                timestamp=timezone.now() - timedelta(hours=random.randint(1, 48)),
                matched=False, raw_payload={"demo": True, "note": "unrecognised employeeNo"},
            )

    def _seed_leave(self, employees, leave_types):
        LeaveRequest.objects.all().delete()
        today = timezone.now().date()
        hr_user = User.objects.filter(username="hr.manager").first()

        sample = random.sample(employees, min(18, len(employees)))
        for employee in sample:
            leave_type = random.choice(leave_types)
            status = random.choices(
                [LeaveStatus.PENDING, LeaveStatus.APPROVED, LeaveStatus.REJECTED],
                weights=[35, 50, 15],
            )[0]

            start_offset = random.randint(-40, 25)
            start = today + timedelta(days=start_offset)
            duration = random.randint(1, 7)
            end = start + timedelta(days=duration - 1)

            kwargs = dict(
                employee=employee, leave_type=leave_type,
                start_date=start, end_date=end,
                reason=random.choice([
                    "Family event out of town.",
                    "Medical appointment and recovery.",
                    "Personal travel.",
                    "Childcare responsibilities.",
                    "Rest and recuperation.",
                ]),
                status=status,
            )
            if status != LeaveStatus.PENDING:
                kwargs.update(
                    reviewed_by=hr_user, reviewed_at=timezone.now() - timedelta(days=random.randint(1, 20)),
                    review_note="Approved - enjoy your time off." if status == LeaveStatus.APPROVED else "Insufficient notice given for this period.",
                )
            LeaveRequest.objects.create(**kwargs)

    def _seed_payroll(self, employees):
        PayrollPeriod.objects.all().delete()
        today = timezone.now().date()
        admin_user = User.objects.filter(username="admin").first()

        month_starts = []
        cursor = today.replace(day=1)
        for _ in range(3):
            month_starts.append(cursor)
            prev_month = cursor - timedelta(days=1)
            cursor = prev_month.replace(day=1)
        month_starts.reverse()

        from calendar import monthrange
        for i, start in enumerate(month_starts):
            end = start.replace(day=monthrange(start.year, start.month)[1])
            is_latest = i == len(month_starts) - 1
            period = PayrollPeriod.objects.create(
                name=start.strftime("%B %Y"), start_date=start, end_date=end,
                status=PayrollStatus.PROCESSED if not is_latest else PayrollStatus.DRAFT,
                processed_by=admin_user if not is_latest else None,
                processed_at=timezone.now() - timedelta(days=20) if not is_latest else None,
            )
            if not is_latest:
                self._generate_payslips(period, employees)

    def _generate_payslips(self, period, employees):
        from decimal import Decimal
        TAX_RATE = Decimal("0.075")
        PENSION_RATE = Decimal("0.08")
        LATE_PENALTY = Decimal("1000")

        for employee in employees:
            records = AttendanceRecord.objects.filter(employee=employee, date__gte=period.start_date, date__lte=period.end_date)
            days_present = records.filter(status__in=[AttendanceStatus.PRESENT, AttendanceStatus.LATE]).count()
            days_late = records.filter(status=AttendanceStatus.LATE).count()
            days_absent = records.filter(status=AttendanceStatus.ABSENT).count()

            basic = employee.basic_salary
            slip = Payslip.objects.create(
                period=period, employee=employee,
                basic_salary=basic,
                housing_allowance=basic * Decimal("0.15"),
                transport_allowance=basic * Decimal("0.10"),
                other_allowance=0,
                tax_deduction=basic * TAX_RATE,
                pension_deduction=basic * PENSION_RATE,
                other_deduction=0,
                late_penalty_deduction=Decimal(days_late) * LATE_PENALTY,
                days_present=days_present, days_late=days_late, days_absent=days_absent,
            )
            slip.compute()
