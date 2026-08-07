from django import forms
from .models import ProfileUpdateRequest, AttendanceCorrectionRequest, LoanRequest, TrainingRequest


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = ProfileUpdateRequest
        fields = ["field_name", "current_value", "requested_value", "reason"]
        widgets = {
            "field_name": forms.Select(attrs={"class": "form-select"}, choices=[
                ("phone_number", "Phone number"),
                ("address", "Address"),
                ("emergency_contact_name", "Emergency contact name"),
                ("emergency_contact_phone", "Emergency contact phone"),
                ("bank_name", "Bank name"),
                ("bank_account_number", "Bank account number"),
            ]),
            "current_value": forms.TextInput(attrs={"class": "form-control"}),
            "requested_value": forms.TextInput(attrs={"class": "form-control"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class AttendanceCorrectionForm(forms.ModelForm):
    class Meta:
        model = AttendanceCorrectionRequest
        fields = ["date", "current_status", "requested_check_in", "requested_check_out", "reason"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "current_status": forms.TextInput(attrs={"class": "form-control", "readonly": True}),
            "requested_check_in": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "requested_check_out": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class LoanRequestForm(forms.ModelForm):
    class Meta:
        model = LoanRequest
        fields = ["amount", "purpose", "repayment_months"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control"}),
            "purpose": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "repayment_months": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 36}),
        }


class TrainingRequestForm(forms.ModelForm):
    class Meta:
        model = TrainingRequest
        fields = ["course_title", "justification", "preferred_date"]
        widgets = {
            "course_title": forms.TextInput(attrs={"class": "form-control"}),
            "justification": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "preferred_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }
