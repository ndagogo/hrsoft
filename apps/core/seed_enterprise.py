"""Enterprise demo data for new HRMS modules."""

import random
from datetime import timedelta

from django.utils import timezone

from apps.organization.models import Company, Region, Branch, Unit
from apps.recruitment.models import Vacancy, Application, Interview, VacancyStatus, ApplicationStatus
from apps.performance.models import PerformanceReview, Goal, KPI, ReviewPeriod, ReviewStatus
from apps.training.models import Course, TrainingSchedule, TrainingEnrollment, EnrollmentStatus
from apps.assets.models import (
    Asset, AssetAssignment, AssetCategory, AssetHistory, AssetHistoryEvent,
    AssetStatus, AssetCondition,
)
from apps.documents.models import Document, DocumentCategory
from apps.visitors.models import Visitor, VisitorStatus
from apps.notifications.models import Notification, NotificationCategory
from apps.announcements.models import Announcement, AnnouncementPriority, AnnouncementStatus
from apps.system_settings.models import SystemSetting, Holiday, SettingCategory
from apps.employees.models import Department, Employee


EXTRA_PERMISSIONS = [
    ("view_recruitment", "View recruitment", "recruitment", "View vacancies and applications."),
    ("manage_recruitment", "Manage recruitment", "recruitment", "Create vacancies and manage hiring pipeline."),
    ("view_performance", "View performance", "performance", "View performance reviews and goals."),
    ("manage_performance", "Manage performance", "performance", "Create and manage performance reviews."),
    ("view_training", "View learning & development", "training", "View L&D catalogue, sessions, certificates and reports."),
    ("manage_training", "Manage learning & development", "training", "Manage courses, sessions, enrolments, competencies and approvals."),
    ("view_assets", "View assets", "assets", "View company asset inventory."),
    ("manage_assets", "Manage assets", "assets", "Assign and manage company assets."),
    ("approve_asset_requests", "Approve asset requests", "assets", "Approve employee asset requests (supervisor/IT/store)."),
    ("view_documents", "View documents", "documents", "View employee and company documents."),
    ("manage_documents", "Manage documents", "documents", "Upload and manage documents."),
    ("view_employee_documentation", "View employee documentation", "documents", "View academic, guarantor and other employment documents on employee profiles."),
    ("view_visitors", "View visitors", "visitors", "View visitor log and appointments."),
    ("manage_visitors", "Manage visitors", "visitors", "Register and manage visitors."),
    ("export_reports", "Export reports", "reports", "Export data to Excel, CSV and PDF."),
    ("import_data", "Import data", "system", "Bulk import employees, attendance and payroll data."),
    ("create_announcement", "Create announcements", "announcements", "Create company announcements and submit them for approval."),
    ("approve_announcement", "Approve announcements", "announcements", "Approve or reject pending company announcements."),
    ("view_organization", "View organization", "organization", "View companies, regions, branches and units."),
    ("manage_organization", "Manage organization", "organization", "Create, update and delete companies, regions, branches and units."),
]

EXTRA_ROLES = {
    "HR Officer": {
        "description": "Handles day-to-day HR operations and employee records.",
        "dashboard_key": "hr",
        "color": "#6366f1",
        "permissions": [
            "view_employees", "manage_employees", "view_attendance", "approve_leave",
            "approve_leave_hr", "view_assets",
            "view_recruitment", "view_training", "view_documents", "view_employee_documentation", "view_reports",
            "create_announcement",
        ],
    },
    "Department Head": {
        "description": "Leads a department — attendance, leave and team performance.",
        "dashboard_key": "manager",
        "color": "#0ea5e9",
        "permissions": ["view_employees", "view_attendance", "approve_leave", "view_performance", "view_reports"],
    },
    "Supervisor": {
        "description": "Supervises a team subset with leave approval rights.",
        "dashboard_key": "manager",
        "color": "#06b6d4",
        "permissions": ["view_employees", "view_attendance", "approve_leave"],
    },
    "Reception": {
        "description": "Front desk — visitor management and appointments.",
        "dashboard_key": "employee",
        "color": "#ec4899",
        "permissions": ["view_visitors", "manage_visitors", "view_employees"],
    },
    "Auditor": {
        "description": "Read-only access to reports, payroll and audit logs.",
        "dashboard_key": "admin",
        "color": "#64748b",
        "permissions": ["view_employees", "view_attendance", "view_payroll", "view_reports", "export_reports"],
    },
    "IT Administrator": {
        "description": "Manages system settings, devices and integrations.",
        "dashboard_key": "admin",
        "color": "#10b981",
        "permissions": [
            "manage_devices", "manage_system_settings", "view_employees",
            "view_assets", "manage_assets", "view_attendance",
        ],
    },
}

EXTRA_DEPARTMENTS = [
    ("Legal", "LEG", ["Legal Officer", "Legal Manager"]),
    ("Procurement", "PRO", ["Procurement Officer", "Procurement Manager"]),
    ("Quality Assurance", "QAS", ["QA Analyst", "QA Manager"]),
    ("Research & Development", "RND", ["Research Analyst", "R&D Manager"]),
    ("Administration", "ADM", ["Admin Officer", "Admin Manager"]),
    ("Security", "SEC", ["Security Officer", "Security Manager"]),
    ("Facilities", "FAC", ["Facilities Officer", "Facilities Manager"]),
    ("Business Development", "BIZ", ["BD Executive", "BD Manager"]),
    ("Compliance", "CMP", ["Compliance Officer", "Compliance Manager"]),
    ("Internal Audit", "AUD", ["Auditor", "Audit Manager"]),
    ("Corporate Communications", "COM", ["Comms Officer", "Comms Manager"]),
    ("Product", "PRD", ["Product Analyst", "Product Manager"]),
    ("Data & Analytics", "DAT", ["Data Analyst", "Analytics Manager"]),
    ("IT & Infrastructure", "ITI", ["IT Support", "IT Manager"]),
]


def seed_extra_permissions(perm_objs):
    from apps.rbac.models import Permission, PermissionCategory
    cat_map = {c.value: c for c in PermissionCategory}
    for codename, name, category, desc in EXTRA_PERMISSIONS:
        perm, _ = Permission.objects.update_or_create(
            codename=codename,
            defaults={"name": name, "category": cat_map.get(category, category), "description": desc},
        )
        perm_objs[codename] = perm
    return perm_objs


def seed_extra_roles(roles, perm_objs):
    from apps.rbac.models import Role
    for role_name, cfg in EXTRA_ROLES.items():
        role, _ = Role.objects.update_or_create(
            name=role_name,
            defaults={
                "description": cfg["description"],
                "dashboard_key": cfg["dashboard_key"],
                "color": cfg["color"],
                "is_system_role": True,
            },
        )
        role.permissions.set([perm_objs[c] for c in cfg["permissions"] if c in perm_objs])
        roles[role_name] = role
    # Refresh Admin with all permissions
    if "Admin" in roles:
        roles["Admin"].permissions.set(perm_objs.values())
    return roles


def seed_extra_departments(designations):
    from apps.employees.models import Designation
    for name, code, titles in EXTRA_DEPARTMENTS:
        dept, _ = Department.objects.update_or_create(name=name, defaults={"code": code})
        for i, title in enumerate(titles):
            desig, _ = Designation.objects.update_or_create(
                title=title, defaults={"department": dept, "level": i + 1}
            )
            designations.setdefault(name, []).append(desig)
    return designations


def seed_organization():
    company, _ = Company.objects.get_or_create(
        code="NBI", defaults={"name": "Northbridge Industries", "registration_number": "RC-123456", "email": "info@northbridge.demo"}
    )
    regions = []
    for name, code in [("South West", "SW"), ("South East", "SE"), ("North Central", "NC")]:
        r, _ = Region.objects.get_or_create(company=company, code=code, defaults={"name": name})
        regions.append(r)

    branches = []
    branch_data = [
        ("Lagos HQ", "LHQ", "Lagos", True, regions[0]),
        ("Abuja Office", "ABJ", "Abuja", False, regions[2]),
        ("Port Harcourt", "PHC", "Port Harcourt", False, regions[1]),
        ("Ibadan Branch", "IBD", "Ibadan", False, regions[0]),
        ("Kano Branch", "KAN", "Kano", False, regions[2]),
    ]
    for name, code, city, hq, region in branch_data:
        b, _ = Branch.objects.get_or_create(
            company=company, code=code,
            defaults={"name": name, "city": city, "is_head_office": hq, "region": region, "address": f"{city}, Nigeria"},
        )
        branches.append(b)

    hq = next((b for b in branches if b.is_head_office), branches[0])
    for dept in Department.objects.all()[:10]:
        dept.branch = hq
        dept.save()
        Unit.objects.get_or_create(department=dept, code="OPS", defaults={"name": f"{dept.code} Operations"})
    return company, branches


def seed_enterprise_modules(employees, roles, admin_user):
    today = timezone.now().date()
    depts = list(Department.objects.all())

    # Recruitment
    Vacancy.objects.all().delete()
    vacancies = []
    for title in ["Senior Software Engineer", "HR Officer", "Sales Executive", "QA Analyst", "Finance Manager"]:
        v = Vacancy.objects.create(
            title=title, department=random.choice(depts), description=f"We are hiring for {title}.",
            positions=random.randint(1, 3), status=VacancyStatus.OPEN,
            posted_date=today - timedelta(days=random.randint(5, 30)),
            created_by=admin_user,
            is_public=True,
            is_internal=True,
        )
        vacancies.append(v)

    Application.objects.all().delete()
    for v in vacancies:
        for _ in range(random.randint(3, 8)):
            Application.objects.create(
                vacancy=v,
                first_name=random.choice(["James", "Mary", "Ahmed", "Chioma", "Ibrahim"]),
                last_name=random.choice(["Okonkwo", "Bello", "Adebayo", "Musa", "Ogunleye"]),
                email=f"applicant{random.randint(1000,9999)}@email.com",
                status=random.choice(list(ApplicationStatus.values)),
                rating=round(random.uniform(2.5, 5.0), 1),
            )

    apps = list(Application.objects.filter(status=ApplicationStatus.INTERVIEW)[:5])
    Interview.objects.all().delete()
    for app in apps:
        Interview.objects.create(
            application=app,
            scheduled_at=timezone.now() + timedelta(days=random.randint(1, 14)),
            location="Conference Room A",
            completed=False,
        )

    # Performance
    KPI.objects.all().delete()
    for title in ["Customer Satisfaction", "Project Delivery", "Attendance Rate", "Sales Target", "Quality Score"]:
        KPI.objects.create(title=title, weight=random.randint(10, 30))

    Goal.objects.all().delete()
    PerformanceReview.objects.all().delete()
    for emp in random.sample(employees, min(40, len(employees))):
        Goal.objects.create(
            employee=emp, title=random.choice(["Complete certification", "Improve team KPI", "Reduce late arrivals"]),
            target_date=today + timedelta(days=random.randint(30, 180)),
            progress=random.randint(10, 90),
        )
        PerformanceReview.objects.create(
            employee=emp, period=ReviewPeriod.ANNUAL, year=today.year - 1,
            status=ReviewStatus.COMPLETED,
            self_rating=round(random.uniform(3, 5), 1),
            supervisor_rating=round(random.uniform(3, 5), 1),
            final_rating=round(random.uniform(3.5, 4.8), 1),
            promotion_recommended=random.random() < 0.1,
        )

    # Training
    Course.objects.all().delete()
    courses = []
    for title in ["Leadership Essentials", "Excel for HR", "Cybersecurity Awareness", "Project Management", "Customer Service"]:
        c = Course.objects.create(title=title, duration_hours=random.randint(4, 16), provider="Northbridge Academy", budget_cost=random.randint(50000, 200000))
        courses.append(c)

    TrainingSchedule.objects.all().delete()
    TrainingEnrollment.objects.all().delete()
    for c in courses[:3]:
        sched = TrainingSchedule.objects.create(
            course=c, start_date=today + timedelta(days=random.randint(10, 60)),
            end_date=today + timedelta(days=random.randint(61, 90)),
            location="Training Room 2", trainer="External Facilitator",
        )
        for emp in random.sample(employees, min(8, len(employees))):
            TrainingEnrollment.objects.create(
                schedule=sched, employee=emp,
                status=random.choice([EnrollmentStatus.ENROLLED, EnrollmentStatus.COMPLETED]),
            )

    # Assets
    from django.core.management import call_command
    call_command("setup_asset_categories")
    AssetHistory.objects.all().delete()
    AssetAssignment.objects.all().delete()
    Asset.objects.all().delete()
    cat_map = {c.code: c for c in AssetCategory.objects.all()}
    hq_branch = Branch.objects.filter(is_head_office=True).first() or Branch.objects.first()
    assets = []
    demo_assets = [
        ("laptop", "IT-00045", "Dell Latitude 7440", AssetStatus.ASSIGNED),
        ("desktop", "IT-00012", "HP ProDesk 400", AssetStatus.AVAILABLE),
        ("phone", "MOB-0012", "Samsung Galaxy A54", AssetStatus.ASSIGNED),
        ("id_card", "ID-0199", "Employee ID Card", AssetStatus.ASSIGNED),
        ("access_card", "ACC-0088", "Building Access Card", AssetStatus.ASSIGNED),
        ("office_key", "KEY-004", "Office Key", AssetStatus.ASSIGNED),
        ("sim_card", "SIM-0021", "Corporate SIM Card", AssetStatus.ASSIGNED),
        ("car", "VEH-0003", "Toyota Corolla Fleet", AssetStatus.AVAILABLE),
        ("ultrasound_laptop", "MED-0007", "Ultrasound Laptop", AssetStatus.ASSIGNED),
        ("barcode_scanner", "MED-0011", "Lab Barcode Scanner", AssetStatus.AVAILABLE),
        ("portable_ecg", "MED-0004", "Portable ECG", AssetStatus.MAINTENANCE),
        ("monitor", "IT-00089", "Dell 27\" Workstation Monitor", AssetStatus.ASSIGNED),
    ]
    for code, tag, name, status in demo_assets:
        cat = cat_map.get(code) or list(cat_map.values())[0]
        a = Asset.objects.create(
            asset_number=tag, name=name, category=cat,
            brand=name.split()[0], serial_number=f"SN{random.randint(100000, 999999)}",
            status=status if status != AssetStatus.ASSIGNED else AssetStatus.AVAILABLE,
            purchase_price=random.randint(50000, 800000),
            warranty_end=today + timedelta(days=random.randint(180, 900)),
            branch=hq_branch,
            condition=random.choice([AssetCondition.EXCELLENT, AssetCondition.GOOD]),
            approved_at=timezone.now(), registered_by=admin_user, approved_by=admin_user,
        )
        if status == AssetStatus.ASSIGNED:
            a.status = AssetStatus.AVAILABLE
            a.save()
        AssetHistory.objects.create(
            asset=a, event_type=AssetHistoryEvent.REGISTERED,
            summary=f"Registered: {name}", actor=admin_user,
        )
        AssetHistory.objects.create(
            asset=a, event_type=AssetHistoryEvent.APPROVED,
            summary="Approved for use", actor=admin_user,
        )
        assets.append((a, status))

    for a, intended in assets:
        if intended != AssetStatus.ASSIGNED:
            if intended == AssetStatus.MAINTENANCE:
                a.status = AssetStatus.MAINTENANCE
                a.save()
            continue
        emp = random.choice(employees)
        a.status = AssetStatus.ASSIGNED
        a.save()
        asn = AssetAssignment.objects.create(
            asset=a, employee=emp, assigned_date=today - timedelta(days=random.randint(30, 365)),
            department=emp.department, is_active=True,
            accessories_issued="Charger, Mouse" if "Laptop" in a.name or "Latitude" in a.name else "",
            condition_on_assign=AssetCondition.EXCELLENT,
        )
        AssetHistory.objects.create(
            asset=a, event_type=AssetHistoryEvent.ASSIGNED,
            summary=f"Assigned to {emp.full_name}", employee=emp, actor=admin_user,
        )

    # Documents
    Document.objects.all().delete()
    for emp in random.sample(employees, min(20, len(employees))):
        Document.objects.create(
            title=f"Employment Contract — {emp.employee_id}",
            category=DocumentCategory.CONTRACT, employee=emp, uploaded_by=admin_user,
            description="Signed employment agreement",
        )

    # Visitors
    Visitor.objects.all().delete()
    for _ in range(15):
        host = random.choice(employees)
        status = random.choice(list(VisitorStatus.values))
        Visitor.objects.create(
            full_name=f"{random.choice(['John', 'Jane', 'Ali', 'Grace'])} {random.choice(['Smith', 'Johnson', 'Williams'])}",
            company=random.choice(["Acme Corp", "Beta Ltd", "Gamma Inc", ""]),
            purpose=random.choice(["Business meeting", "Interview", "Delivery", "Site visit"]),
            host=host, status=status,
            check_in=timezone.now() - timedelta(hours=random.randint(1, 48)) if status != VisitorStatus.EXPECTED else None,
        )

    # Announcements
    Announcement.objects.all().delete()
    for title, content, priority in [
        ("Q2 Town Hall Meeting", "Join us for the quarterly town hall on Friday at 2 PM.", AnnouncementPriority.NORMAL),
        ("New Leave Policy", "Updated leave policy effective next month. Check HR portal.", AnnouncementPriority.HIGH),
        ("Office Closure — Public Holiday", "Office closed on Independence Day.", AnnouncementPriority.URGENT),
    ]:
        published = timezone.now() - timedelta(days=random.randint(1, 14))
        Announcement.objects.create(
            title=title,
            content=content,
            priority=priority,
            author=admin_user,
            status=AnnouncementStatus.APPROVED,
            published_at=published,
            submitted_at=published,
            approved_by=admin_user,
            approved_at=published,
            is_active=True,
        )

    # Notifications for admin
    if admin_user:
        Notification.objects.filter(user=admin_user).delete()
        for title, msg, cat in [
            ("Leave pending", "3 leave requests await your approval.", NotificationCategory.LEAVE),
            ("Payroll draft", "March payroll period is ready to process.", NotificationCategory.PAYROLL),
            ("New applicant", "5 new applications received today.", NotificationCategory.RECRUITMENT),
        ]:
            Notification.objects.create(user=admin_user, title=title, message=msg, category=cat, link="/leave/approvals/")

    # Settings & holidays
    SystemSetting.objects.all().delete()
    for key, value, cat in [
        ("workday_start", "09:00", SettingCategory.ATTENDANCE),
        ("workday_end", "17:00", SettingCategory.ATTENDANCE),
        ("tax_rate", "7.5", SettingCategory.PAYROLL),
        ("pension_rate", "8", SettingCategory.PAYROLL),
        ("annual_leave_days", "21", SettingCategory.LEAVE),
        ("company_email", "hr@northbridge.demo", SettingCategory.EMAIL),
    ]:
        SystemSetting.objects.get_or_create(key=key, defaults={"value": value, "category": cat})

    Holiday.objects.all().delete()
    for name, offset in [("New Year", 1), ("Workers Day", 120), ("Independence Day", 244), ("Christmas", 359)]:
        Holiday.objects.create(name=name, date=today.replace(month=1, day=1) + timedelta(days=offset), is_recurring=True)
