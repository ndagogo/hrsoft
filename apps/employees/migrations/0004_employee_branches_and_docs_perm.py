# Employee branches M2M + seed permission for documentation

import django.db.models.deletion
from django.db import migrations, models


def assign_default_branches(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    Branch = apps.get_model("organization", "Branch")
    hq = Branch.objects.filter(is_head_office=True).first() or Branch.objects.first()
    if not hq:
        return
    for emp in Employee.objects.all():
        if emp.branches.exists():
            continue
        # Prefer department branch when available
        branch = None
        if emp.department_id:
            dept = emp.department
            if dept and getattr(dept, "branch_id", None):
                branch = dept.branch
        emp.branches.add(branch or hq)


def seed_doc_permission(apps, schema_editor):
    Permission = apps.get_model("rbac", "Permission")
    Role = apps.get_model("rbac", "Role")
    perm, _ = Permission.objects.get_or_create(
        codename="view_employee_documentation",
        defaults={
            "name": "View employee documentation",
            "category": "documents",
            "description": "View academic, guarantor and other employment documents on employee profiles.",
        },
    )
    for role_name in ("Admin", "HR Manager", "HR Officer"):
        role = Role.objects.filter(name=role_name).first()
        if role:
            role.permissions.add(perm)
    admin = Role.objects.filter(name="Admin").first()
    if admin:
        # Ensure Admin still has all permissions including the new one
        admin.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0003_enterprise_upgrade"),
        ("organization", "0001_enterprise_upgrade"),
        ("rbac", "0004_announcement_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="branches",
            field=models.ManyToManyField(
                help_text="One or more branches this employee is assigned to. At least one is required.",
                related_name="employees",
                to="organization.branch",
            ),
        ),
        migrations.RunPython(assign_default_branches, migrations.RunPython.noop),
        migrations.RunPython(seed_doc_permission, migrations.RunPython.noop),
    ]
