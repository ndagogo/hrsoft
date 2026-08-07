from django import forms
from .models import Role, Permission


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name", "description", "dashboard_key", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Regional Manager"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "dashboard_key": forms.Select(
                attrs={"class": "form-select"},
                choices=[
                    ("admin", "Admin Dashboard"),
                    ("hr", "HR Manager Dashboard"),
                    ("manager", "Department Manager Dashboard"),
                    ("payroll", "Payroll Officer Dashboard"),
                    ("employee", "Employee Dashboard"),
                ],
            ),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }


class PermissionForm(forms.ModelForm):
    class Meta:
        model = Permission
        fields = ["name", "codename", "category", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "codename": forms.TextInput(attrs={"class": "form-control", "placeholder": "snake_case_codename"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }
