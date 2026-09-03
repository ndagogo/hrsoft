"""
Idempotent application bootstrap: permissions, system roles, leave types,
asset categories, default settings, optional first-install org skeleton.

Never deletes attendance, leave requests, payroll, employees, or other
operational data. Safe to run on every deploy.
"""
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.rbac.catalog import (
    BASE_DEPARTMENTS,
    DEFAULT_SYSTEM_SETTINGS,
    LEAVE_TYPES,
    permission_catalog,
    system_roles,
)
from apps.rbac.models import Permission, Role


def bootstrap_system(*, reset_roles=False, with_org=False, company_name=None, company_code=None):
    """
    Apply mandatory HRMS configuration. Returns a stats dict.

    reset_roles: if True, non-Admin system roles are reset to catalog
        permission sets (demo / factory reset). Default is additive.
    with_org: create a company + HQ + base departments if missing.
    """
    stats = {
        "permissions_created": 0,
        "permissions_updated": 0,
        "roles_created": 0,
        "roles_updated": 0,
        "leave_types_created": 0,
        "asset_categories_created": 0,
        "settings_created": 0,
        "superusers_linked": 0,
        "org_created": False,
        "roles": {},
    }

    perm_objs, created_p, updated_p = _upsert_permissions()
    stats["permissions_created"] = created_p
    stats["permissions_updated"] = updated_p

    roles, created_r, updated_r = _upsert_roles(perm_objs, reset_roles=reset_roles)
    stats["roles_created"] = created_r
    stats["roles_updated"] = updated_r
    stats["roles"] = roles

    stats["leave_types_created"] = _upsert_leave_types()
    stats["asset_categories_created"] = _upsert_asset_categories()
    stats["settings_created"] = _upsert_system_settings()
    stats["superusers_linked"] = _link_superusers(roles.get("Admin"))

    if with_org:
        stats["org_created"] = _upsert_minimal_org(
            company_name=company_name,
            company_code=company_code,
        )

    return stats


def _upsert_permissions():
    perm_objs = {}
    created = updated = 0
    for codename, name, category, desc in permission_catalog():
        perm, was_created = Permission.objects.update_or_create(
            codename=codename,
            defaults={"name": name, "category": category, "description": desc},
        )
        perm_objs[codename] = perm
        if was_created:
            created += 1
        else:
            updated += 1
    return perm_objs, created, updated


def _upsert_roles(perm_objs, *, reset_roles):
    roles = {}
    created = updated = 0
    all_perms = list(Permission.objects.all())

    for role_name, cfg in system_roles().items():
        role, was_created = Role.objects.update_or_create(
            name=role_name,
            defaults={
                "description": cfg["description"],
                "dashboard_key": cfg["dashboard_key"],
                "color": cfg["color"],
                "is_system_role": True,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

        if cfg["permissions"] == "__all__":
            role.permissions.set(all_perms)
        else:
            defaults = [perm_objs[c] for c in cfg["permissions"] if c in perm_objs]
            if was_created or reset_roles:
                role.permissions.set(defaults)
            elif defaults:
                role.permissions.add(*defaults)
        roles[role_name] = role

    admin = roles.get("Admin")
    if admin:
        admin.permissions.set(Permission.objects.all())
    return roles, created, updated


def _upsert_leave_types():
    from apps.leave.models import LeaveType

    created = 0
    for name, days, approval, color in LEAVE_TYPES:
        _, was_created = LeaveType.objects.get_or_create(
            name=name,
            defaults={
                "default_days_per_year": days,
                "requires_approval": approval,
                "color": color,
            },
        )
        if was_created:
            created += 1
    return created


def _upsert_asset_categories():
    from apps.assets.management.commands.setup_asset_categories import CATEGORIES
    from apps.assets.models import AssetCategory

    created = 0
    for code, name, group in CATEGORIES:
        _, was_created = AssetCategory.objects.get_or_create(
            code=code, defaults={"name": name, "group": group},
        )
        if was_created:
            created += 1
    return created


def _upsert_system_settings():
    from apps.system_settings.models import SystemSetting

    created = 0
    for key, value, category, description in DEFAULT_SYSTEM_SETTINGS:
        _, was_created = SystemSetting.objects.get_or_create(
            key=key,
            defaults={"value": value, "category": category, "description": description},
        )
        if was_created:
            created += 1
    return created


def _link_superusers(admin_role):
    if not admin_role:
        return 0
    User = get_user_model()
    linked = 0
    for user in User.objects.filter(is_superuser=True):
        fields = []
        if user.role_id != admin_role.id:
            user.role = admin_role
            fields.append("role")
        if not user.is_staff:
            user.is_staff = True
            fields.append("is_staff")
        if fields:
            user.save(update_fields=fields)
            linked += 1
    return linked


def _upsert_minimal_org(*, company_name=None, company_code=None):
    """Create company + one HQ branch + base departments when missing."""
    from apps.employees.models import Department, Designation
    from apps.organization.models import Branch, Company, Region

    name = (company_name or getattr(settings, "COMPANY_NAME", None) or "Company").strip()
    code = (company_code or "HQ").strip().upper()[:20]

    company, company_created = Company.objects.get_or_create(
        code=code,
        defaults={"name": name},
    )
    region, _ = Region.objects.get_or_create(
        company=company, code="HQ", defaults={"name": "Head Office"},
    )
    branch, _ = Branch.objects.get_or_create(
        company=company,
        code="HQ",
        defaults={
            "name": "Head Office",
            "is_head_office": True,
            "region": region,
        },
    )
    if not branch.is_head_office:
        branch.is_head_office = True
        branch.region = branch.region or region
        branch.save(update_fields=["is_head_office", "region"])

    for dept_name, dept_code, titles in BASE_DEPARTMENTS:
        dept, _ = Department.objects.get_or_create(
            name=dept_name,
            defaults={"code": dept_code, "branch": branch},
        )
        if not dept.branch_id:
            dept.branch = branch
            dept.save(update_fields=["branch"])
        for i, title in enumerate(titles):
            Designation.objects.get_or_create(
                title=title, defaults={"department": dept, "level": i + 1},
            )

    return company_created
