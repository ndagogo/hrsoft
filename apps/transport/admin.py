from django.contrib import admin

from . import models


@admin.register(models.Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("name", "registration_number", "vehicle_type", "capacity", "status", "is_active")
    list_filter = ("status", "vehicle_type", "is_active")
    search_fields = ("name", "registration_number")
    fields = (
        "name", "registration_number", "vehicle_type", "make", "model_name",
        "year", "color", "capacity", "branch", "status", "gps_device_id",
        "photo", "notes", "is_active",
    )


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
    list_display = (
        "name", "is_active", "allow_carpooling", "require_manager_approval",
        "max_route_deviation_percent", "geofence_radius_metres",
    )
    fields = (
        "name", "is_active",
        "require_manager_approval", "require_transport_approval", "require_driver_acceptance",
        "allow_carpooling", "max_route_deviation_percent",
        "geofence_radius_metres", "auto_start_enabled", "auto_arrival_enabled",
        "auto_complete_enabled", "auto_start_max_accuracy_m", "auto_start_min_speed_kmh",
        "min_booking_notice_hours", "estimated_cost_per_km",
        "require_cancel_reason_after_approval",
    )


admin.site.register(models.VehicleDocument)
admin.site.register(models.FuelEntry)
admin.site.register(models.MaintenanceRecord)
admin.site.register(models.RideStop)
admin.site.register(models.RideApprovalStep)
admin.site.register(models.RideEvent)
admin.site.register(models.LocationPing)
