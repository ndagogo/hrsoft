from django import forms
from django.core.exceptions import ValidationError

from apps.employees.models import Employee
from .models import LeaveRequest, LeaveType
from .standin import get_eligible_stand_in_candidates, validate_stand_in_candidate


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "stand_in_employee", "reason", "handover_notes"]
        widgets = {
            "leave_type": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "stand_in_employee": forms.Select(attrs={"class": "form-select"}),
            "reason": forms.Textarea(attrs={
                "class": "form-control", "rows": 3,
                "placeholder": "Briefly describe the reason for leave",
            }),
            "handover_notes": forms.Textarea(attrs={
                "class": "form-control", "rows": 3,
                "placeholder": "Ongoing tasks, key contacts, pending approvals…",
            }),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.fields["handover_notes"].required = False
        self.fields["stand_in_employee"].required = True
        self.fields["stand_in_employee"].empty_label = "Select a colleague from your department"
        if employee:
            start = self.data.get("start_date") or (self.instance.start_date if self.instance.pk else None)
            end = self.data.get("end_date") or (self.instance.end_date if self.instance.pk else None)
            self.fields["stand_in_employee"].queryset = get_eligible_stand_in_candidates(
                employee, start_date=start, end_date=end,
            )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            raise ValidationError("End date cannot be before the start date.")
        stand_in = cleaned.get("stand_in_employee")
        if self.employee and stand_in and start and end:
            ok, msg = validate_stand_in_candidate(self.employee, stand_in, start, end)
            if not ok:
                raise ValidationError(msg)
        elif self.employee and not stand_in:
            raise ValidationError("Please select a stand-in colleague from your department.")
        return cleaned


class StandInNomineeForm(forms.Form):
    stand_in_employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, leave_request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.leave_request = leave_request
        if leave_request:
            self.fields["stand_in_employee"].queryset = get_eligible_stand_in_candidates(
                leave_request.employee,
                leave_request.start_date,
                leave_request.end_date,
                exclude_request=leave_request,
            )
            self.fields["stand_in_employee"].empty_label = "Select another colleague"


class StandInResponseForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("accepted", "Accept"), ("declined", "Decline")],
        widget=forms.RadioSelect,
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}),
    )


class LeaveReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approved", "Approve"), ("rejected", "Reject")], widget=forms.RadioSelect)
    review_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional note"})
    )


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "default_days_per_year", "requires_approval", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "default_days_per_year": forms.NumberInput(attrs={"class": "form-control"}),
            "requires_approval": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }
