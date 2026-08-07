from django import forms

from apps.employees.models import Department

from .models import Company, Region, Branch, Unit


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name", "code", "registration_number", "tax_id",
            "address", "phone", "email", "website", "logo", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. HFDN"}),
            "registration_number": forms.TextInput(attrs={"class": "form-control"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://"}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ["company", "name", "code"]
        widgets = {
            "company": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. SW"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = [
            "company", "region", "name", "code", "address", "city", "state",
            "phone", "is_head_office", "is_active",
        ]
        widgets = {
            "company": forms.Select(attrs={"class": "form-select"}),
            "region": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. LHQ"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "is_head_office": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["region"].queryset = Region.objects.select_related("company").order_by("name")
        self.fields["region"].required = False

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        region = cleaned.get("region")
        if company and region and region.company_id != company.id:
            self.add_error("region", "Region must belong to the selected company.")
        return cleaned


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["department", "name", "code"]
        widgets = {
            "department": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. OPS"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.order_by("name")
