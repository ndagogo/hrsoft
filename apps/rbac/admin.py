from django.contrib import admin
from .models import Role, Permission, AuditLog


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("name", "codename", "category")
    list_filter = ("category",)
    search_fields = ("name", "codename")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "dashboard_key", "is_system_role", "member_count")
    filter_horizontal = ("permissions",)
    search_fields = ("name",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "path", "status_code", "ip_address", "timestamp")
    list_filter = ("action", "status_code")
    search_fields = ("path", "user__username")
    date_hierarchy = "timestamp"
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False
