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
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. HFDN Head Office",
            "id": "id_origin_label",
            "autocomplete": "off",
        }),
    )
    destination_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. New Haven",
            "id": "id_destination_label",
            "autocomplete": "off",
        }),
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
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "id": "id_estimated_distance_km"}),
    )
    estimated_duration_min = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "id": "id_estimated_duration_min"}),
    )
    origin_lat = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_origin_lat"}))
    origin_lng = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_origin_lng"}))
    destination_lat = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_destination_lat"}))
    destination_lng = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_destination_lng"}))
    route_geometry_json = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_route_geometry_json"}))
    route_provider = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_route_provider"}))

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

    def cleaned_route_geometry(self):
        import json
        raw = self.cleaned_data.get("route_geometry_json") or ""
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


class ShuttleRideForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    origin_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control", "id": "id_shuttle_origin_label", "autocomplete": "off",
        }),
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
        initial="Company shuttle",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    allow_carpool = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    origin_lat = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_shuttle_origin_lat"}))
    origin_lng = forms.DecimalField(required=False, widget=forms.HiddenInput(attrs={"id": "id_shuttle_origin_lng"}))
    estimated_distance_km = forms.DecimalField(
        required=False, min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "id": "id_shuttle_distance"}),
    )
    estimated_duration_min = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "id": "id_shuttle_duration"}),
    )
    route_geometry_json = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_shuttle_route_json"}))
    route_provider = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "id_shuttle_route_provider"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(is_active=True).exclude(
            status=VehicleStatus.RETIRED
        ).order_by("name")
        self.fields["driver"].queryset = Driver.objects.filter(status="active").select_related("employee__user")
        self.fields["driver"].empty_label = "Assign later / default"

    def clean_scheduled_departure(self):
        dt = self.cleaned_data["scheduled_departure"]
        if dt < timezone.now() - timedelta(minutes=5):
            raise forms.ValidationError("Departure time cannot be in the past.")
        return dt

    def cleaned_route_geometry(self):
        import json
        raw = self.cleaned_data.get("route_geometry_json") or ""
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


class ShuttlePassengerForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.Select(attrs={"class": "form-select shuttle-employee"}),
    )
    destination_label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control shuttle-destination", "autocomplete": "off",
        }),
    )
    destination_lat = forms.DecimalField(
        required=False, widget=forms.HiddenInput(attrs={"class": "shuttle-dest-lat"}),
    )
    destination_lng = forms.DecimalField(
        required=False, widget=forms.HiddenInput(attrs={"class": "shuttle-dest-lng"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = Employee.objects.filter(
            status="active"
        ).select_related("user").order_by("user__first_name", "user__last_name")
        self.fields["employee"].label_from_instance = (
            lambda obj: f"{obj.full_name} ({obj.employee_id})"
        )


def make_shuttle_passenger_formset(extra=3):
    return forms.formset_factory(ShuttlePassengerForm, extra=extra, can_delete=True)


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
