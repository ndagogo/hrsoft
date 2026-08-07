from django import forms

from apps.employees.models import Employee, Department

from .models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetCondition,
    AssetMaintenance,
    AssetRequest,
    AssetStatus,
)


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = [
            "asset_number", "barcode", "rfid_tag", "name", "category",
            "brand", "model", "serial_number", "manufacturer",
            "purchase_date", "purchase_price", "vendor", "invoice_number",
            "warranty_start", "warranty_end", "amc_provider", "amc_expiry",
            "insurance_provider", "insurance_policy", "insurance_expiry",
            "condition", "branch", "location", "department", "notes",
            "next_maintenance_date",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "warranty_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "warranty_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amc_expiry": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "insurance_expiry": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "next_maintenance_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in self.Meta.widgets:
                field.widget.attrs.setdefault("class", "form-control")
        self.fields["category"].queryset = AssetCategory.objects.filter(is_active=True)


class AssignAssetForm(forms.Form):
    employee = forms.ModelChoiceField(queryset=Employee.objects.filter(user__is_active_employee=True))
    condition = forms.ChoiceField(choices=AssetCondition.choices)
    expected_return_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    accessories_issued = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control", "placeholder": "Mouse, Charger, Laptop Bag…"}),
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].widget.attrs["class"] = "form-select"


class ReturnAssetForm(forms.Form):
    condition_on_return = forms.ChoiceField(choices=AssetCondition.choices)
    inspection_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}))
    accessories_returned = forms.BooleanField(required=False, initial=True)


class MaintenanceForm(forms.ModelForm):
    class Meta:
        model = AssetMaintenance
        fields = ["problem", "technician", "vendor", "repair_cost", "notes"]
        widgets = {
            "problem": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("technician", "vendor", "repair_cost"):
            self.fields[name].widget.attrs["class"] = "form-control"


class AssetRequestForm(forms.ModelForm):
    class Meta:
        model = AssetRequest
        fields = ["category", "title", "justification"]
        widgets = {"justification": forms.Textarea(attrs={"rows": 4, "class": "form-control"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = AssetCategory.objects.filter(is_active=True)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "form-control")


class TransferAssetForm(forms.Form):
    transfer_type = forms.ChoiceField(choices=[
        ("department", "Change department / cost centre (keep with employee)"),
        ("employee", "Transfer to another employee"),
    ])
    to_employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(user__is_active_employee=True),
        required=False,
    )
    to_department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}))


class DisposeAssetForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}))
    method = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    salvage_value = forms.DecimalField(required=False, initial=0, widget=forms.NumberInput(attrs={"class": "form-control"}))
