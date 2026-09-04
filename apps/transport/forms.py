from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.employees.models import Employee
from apps.organization.models import Branch

from .models import (
    Driver,
    JoinRequest,
    Ride,
    RideType,
    Vehicle,
    VehicleDocument,
    VehicleStatus,
    VehicleType,
)


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "name", "registration_number", "vehicle_type", "make", "model_name",
            "year", "color", "capacity", "branch", "status", "gps_device_id", "notes", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "registration_number": forms.TextInput(attrs={"class": "form-control"}),
            "vehicle_type": forms.Select(attrs={"class": "form-select"}),
            "make": forms.TextInput(attrs={"class": "form-control"}),
            "model_name": forms.TextInput(attrs={"class": "form-control"}),
            "year": forms.NumberInput(attrs={"class": "form-control"}),
            "color": forms.TextInput(attrs={"class": "form-control"}),
            "capacity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "branch": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "gps_device_id": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.order_by("name")
        self.fields["branch"].required = False


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = [
            "employee", "license_number", "license_expiry", "status",
            "default_vehicle", "phone_override", "notes",
        ]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "license_number": forms.TextInput(attrs={"class": "form-control"}),
            "license_expiry": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "default_vehicle": forms.Select(attrs={"class": "form-select"}),
            "phone_override": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.select_related("user").order_by(
            "user__first_name", "user__last_name"
        )
        self.fields["default_vehicle"].queryset = Vehicle.objects.filter(is_active=True)
        self.fields["default_vehicle"].required = False
        self.fields["license_expiry"].required = False


class RideRequestForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    origin_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. HFDN Head Office"}),
    )
    destination_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. New Haven"}),
    )
    scheduled_departure = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )
    scheduled_return = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )
    purpose = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    ride_type = forms.ChoiceField(
        choices=RideType.choices,
        initial=RideType.OFFICIAL,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    allow_carpool = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    estimated_distance_km = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.1"}),
    )
    estimated_duration_min = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(
            is_active=True,
        ).exclude(status=VehicleStatus.RETIRED).order_by("name")
        self.fields["driver"].queryset = Driver.objects.filter(status="active").select_related(
            "employee__user"
        )
        self.fields["driver"].empty_label = "Assign later / default"

    def clean_scheduled_departure(self):
        dt = self.cleaned_data["scheduled_departure"]
        if dt < timezone.now() - timedelta(minutes=5):
            raise forms.ValidationError("Departure time cannot be in the past.")
        return dt


class JoinRequestForm(forms.Form):
    destination_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Your drop-off location"}),
    )
    note = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
    )


class ReviewForm(forms.Form):
    note = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
    )


class VehicleDocumentForm(forms.ModelForm):
    class Meta:
        model = VehicleDocument
        fields = ["title", "document_type", "file", "expires_on", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "expires_on": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }
