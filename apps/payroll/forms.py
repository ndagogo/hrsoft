from django import forms
from .models import PayrollPeriod, Payslip


class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. July 2026"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }


class PayslipAdjustmentForm(forms.ModelForm):
    class Meta:
        model = Payslip
        fields = [
            "housing_allowance", "transport_allowance", "other_allowance",
            "tax_deduction", "pension_deduction", "other_deduction",
        ]
        widgets = {f: forms.NumberInput(attrs={"class": "form-control"}) for f in [
            "housing_allowance", "transport_allowance", "other_allowance",
            "tax_deduction", "pension_deduction", "other_deduction",
        ]}
