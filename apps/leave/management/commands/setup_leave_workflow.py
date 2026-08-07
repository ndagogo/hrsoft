from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.leave.models import LeaveRequest, LeaveStatus
from apps.leave.workflow import initialize_approval_chain
from apps.rbac.models import Permission, PermissionCategory, Role


PERMS = [
    (
        "approve_leave_hr",
        "Approve leave (HR stage)",
        PermissionCategory.LEAVE,
        "Approve leave requests at the Human Resources stage.",
    ),
    (
        "approve_leave_gm",
        "Approve leave (GM stage)",
        PermissionCategory.LEAVE,
        "Final leave approval as General Manager.",
    ),
]

ROLE_PERMS = {
    "Admin": ["approve_leave", "approve_leave_hr", "approve_leave_gm"],
    "HR Manager": ["approve_leave", "approve_leave_hr"],
    "HR Officer": ["approve_leave", "approve_leave_hr"],
    "General Manager": ["approve_leave", "approve_leave_gm"],
    "Department Manager": ["approve_leave"],
    "Department Head": ["approve_leave"],
    "Supervisor": ["approve_leave"],
}


class Command(BaseCommand):
    help = "Ensure multi-stage leave permissions and General Manager role exist."

    def handle(self, *args, **options):
        for codename, name, category, desc in PERMS:
            Permission.objects.update_or_create(
                codename=codename,
                defaults={"name": name, "category": category, "description": desc},
            )

        gm, _ = Role.objects.update_or_create(
            name="General Manager",
            defaults={
                "description": "Final operational authority — final leave approvals and executive oversight.",
                "dashboard_key": "admin",
                "color": "#0f766e",
                "is_system_role": True,
            },
        )

        for role_name, codes in ROLE_PERMS.items():
            role = Role.objects.filter(name=role_name).first()
            if not role:
                continue
            for code in codes:
                perm = Permission.objects.filter(codename=code).first()
                if perm:
                    role.permissions.add(perm)

        admin = Role.objects.filter(name="Admin").first()
        if admin:
            admin.permissions.set(Permission.objects.all())

        pending = LeaveRequest.objects.filter(status=LeaveStatus.PENDING)
        backfilled = 0
        for lr in pending:
            if not lr.approval_steps.exists():
                initialize_approval_chain(lr, notify=False)
                backfilled += 1

        User = get_user_model()
        if not User.objects.filter(username="gm.manager").exists():
            user = User.objects.create_user(
                username="gm.manager",
                email="gm@northbridge.demo",
                password="Demo@1234",
                first_name="Chinedu",
                last_name="Okoro",
            )
            user.role = gm
            user.save(update_fields=["role"])
            self.stdout.write("Created demo user gm.manager / Demo@1234")

        self.stdout.write(self.style.SUCCESS(
            f"Leave workflow ready. Backfilled {backfilled} pending request(s)."
        ))
