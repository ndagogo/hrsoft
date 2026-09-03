"""
Mandatory application configuration for every environment.

Does not create demo users or wipe operational data. Safe to re-run
after deploys and after adding new permission codenames.

    python manage.py bootstrap_system
    python manage.py bootstrap_system --with-org
    python manage.py bootstrap_system --reset-roles
    python manage.py bootstrap_system --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.rbac.bootstrap import bootstrap_system


class Command(BaseCommand):
    help = (
        "Idempotent system bootstrap: RBAC permissions/roles, leave types, "
        "asset categories, default settings, and Admin role on superusers."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-org",
            action="store_true",
            help="Also create a company, HQ branch, and base departments if missing.",
        )
        parser.add_argument(
            "--reset-roles",
            action="store_true",
            help="Reset non-Admin system roles to catalog permission sets (overwrites Role Builder customisation).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apply changes inside a transaction and roll them back.",
        )
        parser.add_argument(
            "--company-name",
            default=None,
            help="Company name used with --with-org (defaults to COMPANY_NAME setting).",
        )
        parser.add_argument(
            "--company-code",
            default=None,
            help="Company code used with --with-org (default: HQ).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        stats = bootstrap_system(
            reset_roles=options["reset_roles"],
            with_org=options["with_org"],
            company_name=options["company_name"],
            company_code=options["company_code"],
        )
        prefix = "[dry-run] " if dry_run else ""
        if dry_run:
            transaction.set_rollback(True)

        self.stdout.write(
            f"{prefix}Permissions: {stats['permissions_created']} created, "
            f"{stats['permissions_updated']} updated."
        )
        self.stdout.write(
            f"{prefix}Roles: {stats['roles_created']} created, "
            f"{stats['roles_updated']} updated "
            f"({', '.join(sorted(stats['roles']))})."
        )
        self.stdout.write(f"{prefix}Leave types created: {stats['leave_types_created']}")
        self.stdout.write(f"{prefix}Asset categories created: {stats['asset_categories_created']}")
        self.stdout.write(f"{prefix}System settings created: {stats['settings_created']}")
        self.stdout.write(f"{prefix}Superusers linked to Admin: {stats['superusers_linked']}")
        if options["with_org"]:
            self.stdout.write(f"{prefix}Org skeleton created (new company): {stats['org_created']}")

        self.stdout.write(self.style.SUCCESS(
            f"{prefix}System bootstrap complete. Operational data was not modified."
        ))
