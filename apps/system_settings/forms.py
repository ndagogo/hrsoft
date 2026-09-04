from django import forms

from .models import Holiday, SystemSetting


class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ["key", "value", "category", "description"]
        widgets = {
            "key": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. company_name",
            }),
            "value": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_key(self):
        key = (self.cleaned_data.get("key") or "").strip().lower().replace(" ", "_")
        if not key:
            raise forms.ValidationError("Key is required.")
        return key


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["name", "date", "is_recurring", "branch"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "branch": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].required = False
        self.fields["branch"].empty_label = "All branches"
        try:
            from apps.organization.models import Branch
            self.fields["branch"].queryset = Branch.objects.order_by("name")
        except Exception:
            pass
