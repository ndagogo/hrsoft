from django import forms

from apps.employees.models import Department, Designation
from apps.organization.models import Branch

from .models import Announcement, AnnouncementPriority, AudienceType


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": "form-control", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(d, initial) for d in data]
        return [single_file_clean(data, initial)]


class AnnouncementForm(forms.ModelForm):
    attachments = MultipleFileField(required=False, label="Attachments")

    class Meta:
        model = Announcement
        fields = [
            "title",
            "content",
            "priority",
            "expires_at",
            "audience_type",
            "departments",
            "branches",
            "cadres",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Announcement title"}),
            "content": forms.Textarea(
                attrs={"class": "form-control", "rows": 6, "placeholder": "Write the announcement…"}
            ),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "expires_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "audience_type": forms.Select(attrs={"class": "form-select", "id": "id_audience_type"}),
            "departments": forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
            "branches": forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
            "cadres": forms.SelectMultiple(attrs={"class": "form-select", "size": "8"}),
        }
        labels = {
            "audience_type": "Broadcast audience",
            "departments": "Departments",
            "branches": "Branches",
            "cadres": "Cadres (job titles)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["priority"].choices = AnnouncementPriority.choices
        self.fields["audience_type"].choices = AudienceType.choices
        self.fields["expires_at"].required = False
        self.fields["expires_at"].help_text = "Optional. Leave blank for no expiry."
        self.fields["departments"].queryset = Department.objects.order_by("name")
        self.fields["departments"].required = False
        self.fields["departments"].help_text = "Hold Ctrl (Windows) or Cmd (Mac) to select multiple."
        self.fields["branches"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["branches"].required = False
        self.fields["branches"].help_text = "Hold Ctrl (Windows) or Cmd (Mac) to select multiple."
        self.fields["cadres"].queryset = Designation.objects.select_related("department").order_by(
            "department__name", "level", "title"
        )
        self.fields["cadres"].required = False
        self.fields["cadres"].help_text = (
            "Select one or more job titles (e.g. all Manager designations). "
            "Hold Ctrl / Cmd for multiple."
        )
        self.fields["cadres"].label_from_instance = (
            lambda obj: f"{obj.title} ({obj.department.code})"
        )

    def clean(self):
        cleaned = super().clean()
        audience = cleaned.get("audience_type") or AudienceType.ALL
        departments = cleaned.get("departments")
        branches = cleaned.get("branches")
        cadres = cleaned.get("cadres")

        if audience == AudienceType.DEPARTMENT and not departments:
            self.add_error("departments", "Select at least one department for this audience.")
        elif audience == AudienceType.BRANCH and not branches:
            self.add_error("branches", "Select at least one branch for this audience.")
        elif audience == AudienceType.CADRE and not cadres:
            self.add_error("cadres", "Select at least one cadre (job title) for this audience.")

        # Clear unused M2Ms so stale selections are not kept
        if audience != AudienceType.DEPARTMENT:
            cleaned["departments"] = []
        if audience != AudienceType.BRANCH:
            cleaned["branches"] = []
        if audience != AudienceType.CADRE:
            cleaned["cadres"] = []
        return cleaned


class AnnouncementReviewForm(forms.Form):
    note = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional review note"}),
    )
