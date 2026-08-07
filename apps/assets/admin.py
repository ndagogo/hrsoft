from django.contrib import admin

from .models import (
    Asset, AssetAssignment, AssetCategory, AssetHistory,
    AssetMaintenance, AssetRequest, AssetTransfer, AssetDisposal,
)


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "group", "is_active")
    list_filter = ("group", "is_active")


class AssetHistoryInline(admin.TabularInline):
    model = AssetHistory
    extra = 0
    readonly_fields = ("event_type", "summary", "actor", "created_at")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("asset_number", "name", "category", "status", "branch")
    list_filter = ("status", "category__group", "branch")
    search_fields = ("asset_number", "name", "serial_number", "barcode")
    inlines = [AssetHistoryInline]


admin.site.register(AssetAssignment)
admin.site.register(AssetMaintenance)
admin.site.register(AssetRequest)
admin.site.register(AssetTransfer)
admin.site.register(AssetDisposal)
