from django.core.management.base import BaseCommand

from apps.rbac.models import Permission, PermissionCategory, Role


PERMS = [
    ("create_announcement", "Create announcements", PermissionCategory.ANNOUNCEMENTS,
     "Create company announcements and submit them for approval."),
    ("approve_announcement", "Approve announcements", PermissionCategory.ANNOUNCEMENTS,
     "Approve or reject pending company announcements."),
]


class Command(BaseCommand):
    help = "Ensure announcement permissions exist and are assigned to Admin / HR Manager."

    def handle(self, *args, **options):
        created = []
        for codename, name, category, desc in PERMS:
            perm, was_created = Permission.objects.update_or_create(
                codename=codename,
                defaults={"name": name, "category": category, "description": desc},
            )
            if was_created:
                created.append(codename)

            for role_name in ("Admin", "HR Manager"):
                role = Role.objects.filter(name=role_name).first()
                if role:
                    role.permissions.add(perm)

            # Admin should keep all permissions
            admin = Role.objects.filter(name="Admin").first()
            if admin and admin.permissions.count() < Permission.objects.count():
                admin.permissions.set(Permission.objects.all())

        self.stdout.write(self.style.SUCCESS(
            f"Announcement permissions ready. Newly created: {created or 'none'}"
        ))
