from django import forms
from .models import BiometricDevice, AttendanceRecord


class BiometricDeviceForm(forms.ModelForm):
    class Meta:
        model = BiometricDevice
        fields = [
            "name", "brand", "connection_mode", "ip_address", "port",
            "comm_key", "username", "password", "location", "serial_number",
            "webhook_token", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Main Gate Terminal"}),
            "brand": forms.Select(attrs={"class": "form-select", "id": "id_brand"}),
            "connection_mode": forms.Select(attrs={"class": "form-select"}),
            "ip_address": forms.TextInput(attrs={"class": "form-control", "placeholder": "192.168.1.201"}),
            "port": forms.NumberInput(attrs={"class": "form-control", "placeholder": "4370"}),
            "comm_key": forms.NumberInput(attrs={"class": "form-control", "placeholder": "0"}),
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "password": forms.PasswordInput(attrs={"class": "form-control"}, render_value=True),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "serial_number": forms.TextInput(attrs={"class": "form-control"}),
            "webhook_token": forms.TextInput(attrs={"class": "form-control", "placeholder": "Auto-generated if left blank"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.fields["brand"].initial = "zkteco"
            self.fields["port"].initial = 4370
            self.fields["connection_mode"].initial = "pull"
            self.fields["ip_address"].initial = "192.168.1.201"
            self.fields["comm_key"].initial = 0


class AttendanceOverrideForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ["check_in", "check_out", "status", "notes"]
        widgets = {
            "check_in": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "check_out": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
