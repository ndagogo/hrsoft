from django import forms
from django.core.exceptions import ValidationError

from apps.organization.models import Branch

from .models import Employee, Department, Designation


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "description", "head", "branch"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. ENG"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "head": forms.Select(attrs={"class": "form-select"}),
            "branch": forms.Select(attrs={"class": "form-select"}),
        }


class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = ["title", "department", "level"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "department": forms.Select(attrs={"class": "form-select"}),
            "level": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10}),
        }


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "department", "designation", "manager", "branches", "passport_photo",
            "gender", "date_of_birth",
            "date_joined", "employment_type", "status", "address",
            "emergency_contact_name", "emergency_contact_phone", "basic_salary",
            "bank_name", "bank_account_number", "tax_id", "biometric_id",
        ]
        widgets = {
            "department": forms.Select(attrs={"class": "form-select"}),
            "designation": forms.Select(attrs={"class": "form-select"}),
            "manager": forms.Select(attrs={"class": "form-select"}),
            "branches": forms.SelectMultiple(attrs={"class": "form-select", "size": "4"}),
            "passport_photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "gender": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "date_joined": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "employment_type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "emergency_contact_name": forms.TextInput(attrs={"class": "form-control"}),
            "emergency_contact_phone": forms.TextInput(attrs={"class": "form-control"}),
            "basic_salary": forms.NumberInput(attrs={"class": "form-control"}),
            "bank_name": forms.TextInput(attrs={"class": "form-control"}),
            "bank_account_number": forms.TextInput(attrs={"class": "form-control"}),
            "tax_id": forms.TextInput(attrs={"class": "form-control"}),
            "biometric_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "ZKTeco User ID (e.g. 1, 2, 15)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].required = False
        self.fields["department"].required = False
        self.fields["designation"].required = False
        self.fields["biometric_id"].required = False
        self.fields["passport_photo"].required = False
        self.fields["branches"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["branches"].required = True
        self.fields["branches"].help_text = "Hold Ctrl (Windows) or Cmd (Mac) to select multiple branches."
        if self.instance and self.instance.pk:
            self.fields["manager"].queryset = Employee.objects.exclude(pk=self.instance.pk)

    def clean_branches(self):
        branches = self.cleaned_data.get("branches")
        if not branches or len(branches) < 1:
            raise ValidationError("Assign the employee to at least one branch.")
        return branches

    def clean_biometric_id(self):
        value = self.cleaned_data.get("biometric_id")
        return value or None
