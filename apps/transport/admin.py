from django.contrib import admin

from . import models


@admin.register(models.Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("name", "registration_number", "vehicle_type", "capacity", "status", "is_active")
    list_filter = ("status", "vehicle_type", "is_active")
    search_fields = ("name", "registration_number")


@admin.register(models.Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("employee", "license_number", "status", "default_vehicle")
    list_filter = ("status",)


@admin.register(models.Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ("reference", "status", "vehicle", "driver", "scheduled_departure", "seats_reserved")
    list_filter = ("status", "ride_type")
    search_fields = ("reference", "origin_label")


@admin.register(models.RidePassenger)
class RidePassengerAdmin(admin.ModelAdmin):
    list_display = ("ride", "employee", "destination_label", "status")
    list_filter = ("status",)


@admin.register(models.JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ("ride", "employee", "destination_label", "status")
    list_filter = ("status",)


@admin.register(models.TransportationPolicy)
class TransportationPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "allow_carpooling", "require_manager_approval")


admin.site.register(models.VehicleDocument)
admin.site.register(models.RideStop)
admin.site.register(models.RideApprovalStep)
admin.site.register(models.RideEvent)
admin.site.register(models.LocationPing)
