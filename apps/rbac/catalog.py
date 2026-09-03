"""
Canonical HRMS permission and system-role definitions.

bootstrap_system and seed_demo_data both read from here so production
installs and local demos cannot drift apart.
"""
from apps.rbac.models import PermissionCategory as Cat

# (codename, name, category, description)
CORE_PERMISSIONS = [
    ("view_employees", "View employees", Cat.EMPLOYEES, "Browse the employee directory and profiles."),
    ("manage_employees", "Manage employees", Cat.EMPLOYEES, "Create, edit and offboard employee records."),
    ("manage_departments", "Manage departments", Cat.EMPLOYEES, "Create and edit departments & designations."),
    ("view_attendance", "View attendance", Cat.ATTENDANCE, "View attendance records across the organisation."),
    ("manage_attendance", "Manage attendance", Cat.ATTENDANCE, "Manually override attendance records."),
    ("manage_devices", "Manage biometric devices", Cat.ATTENDANCE, "Register and configure HikVision / biometric devices."),
    ("approve_leave", "Approve leave requests", Cat.LEAVE, "Review and approve/reject leave requests."),
    ("manage_leave_types", "Manage leave types", Cat.LEAVE, "Configure the leave categories available to staff."),
    ("approve_leave_hr", "Approve leave (HR stage)", Cat.LEAVE, "Approve leave requests at the Human Resources stage."),
    ("approve_leave_gm", "Approve leave (GM stage)", Cat.LEAVE, "Final leave approval as General Manager."),
    ("view_payroll", "View payroll", Cat.PAYROLL, "View payroll periods and payslips."),
    ("manage_payroll", "Manage payroll", Cat.PAYROLL, "Run payroll and adjust payslips."),
    ("manage_roles", "Manage roles", Cat.RBAC, "Create roles and assign permissions to them."),
    ("view_reports", "View reports", Cat.REPORTS, "Access organisation-wide analytics and reports."),
    ("manage_system_settings", "Manage system settings", Cat.SYSTEM, "Configure platform-wide settings."),
    ("view_employee_documentation", "View employee documentation", Cat.DOCUMENTS, "View academic, guarantor and other employment documents on employee profiles."),
]

ENTERPRISE_PERMISSIONS = [
    ("view_recruitment", "View recruitment", Cat.RECRUITMENT, "View vacancies and applications."),
    ("manage_recruitment", "Manage recruitment", Cat.RECRUITMENT, "Create vacancies and manage hiring pipeline."),
    ("view_performance", "View performance", Cat.PERFORMANCE, "View performance reviews and goals."),
    ("manage_performance", "Manage performance", Cat.PERFORMANCE, "Create and manage performance reviews."),
    ("view_training", "View learning & development", Cat.TRAINING, "View L&D catalogue, sessions, certificates and reports."),
    ("manage_training", "Manage learning & development", Cat.TRAINING, "Manage courses, sessions, enrolments, competencies and approvals."),
    ("view_assets", "View assets", Cat.ASSETS, "View company asset inventory."),
    ("manage_assets", "Manage assets", Cat.ASSETS, "Assign and manage company assets."),
    ("approve_asset_requests", "Approve asset requests", Cat.ASSETS, "Approve employee asset requests (supervisor/IT/store)."),
    ("view_documents", "View documents", Cat.DOCUMENTS, "View employee and company documents."),
    ("manage_documents", "Manage documents", Cat.DOCUMENTS, "Upload and manage documents."),
    ("view_visitors", "View visitors", Cat.VISITORS, "View visitor log and appointments."),
    ("manage_visitors", "Manage visitors", Cat.VISITORS, "Register and manage visitors."),
    ("export_reports", "Export reports", Cat.REPORTS, "Export data to Excel, CSV and PDF."),
    ("import_data", "Import data", Cat.SYSTEM, "Bulk import employees, attendance and payroll data."),
    ("create_announcement", "Create announcements", Cat.ANNOUNCEMENTS, "Create company announcements and submit them for approval."),
    ("approve_announcement", "Approve announcements", Cat.ANNOUNCEMENTS, "Approve or reject pending company announcements."),
    ("view_organization", "View organization", Cat.ORGANIZATION, "View companies, regions, branches and units."),
    ("manage_organization", "Manage organization", Cat.ORGANIZATION, "Create, update and delete companies, regions, branches and units."),
]

CORE_ROLES = {
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

ENTERPRISE_ROLES = {
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

# (name, default_days_per_year, requires_approval, color)
LEAVE_TYPES = [
    ("Annual Leave", 21, True, "#0ea5e9"),
    ("Sick Leave", 10, True, "#f43f5e"),
    ("Maternity/Paternity Leave", 90, True, "#8b5cf6"),
    ("Compassionate Leave", 5, True, "#64748b"),
    ("Unpaid Leave", 0, True, "#94a3b8"),
]

# (key, value, category, description) — inserted only if the key is missing
DEFAULT_SYSTEM_SETTINGS = [
    ("workday_start", "09:00", "attendance", "Default workday start time."),
    ("workday_end", "17:00", "attendance", "Default workday end time."),
    ("tax_rate", "7.5", "payroll", "Default PAYE tax rate (%)."),
    ("pension_rate", "8", "payroll", "Default employee pension rate (%)."),
    ("annual_leave_days", "21", "leave", "Default annual leave entitlement (days)."),
]

# First-install org only (used with --with-org). Identity is code, not name.
BASE_DEPARTMENTS = [
    ("Human Resources", "HRD", ["HR Officer", "HR Manager"]),
    ("Finance", "FIN", ["Accountant", "Payroll Officer", "Finance Manager"]),
    ("Administration", "ADM", ["Admin Officer", "Admin Manager"]),
    ("Operations", "OPS", ["Operations Associate", "Operations Manager"]),
]


def permission_catalog():
    """Deduped permission tuples in catalog order."""
    seen = set()
    rows = []
    for row in CORE_PERMISSIONS + ENTERPRISE_PERMISSIONS:
        if row[0] in seen:
            continue
        seen.add(row[0])
        rows.append(row)
    return rows


def system_roles():
    """Merged system-role map. Core roles win on name clash."""
    merged = dict(ENTERPRISE_ROLES)
    merged.update(CORE_ROLES)
    return merged
