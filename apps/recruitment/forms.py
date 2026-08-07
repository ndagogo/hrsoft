from django import forms
from django.contrib.auth import get_user_model

from apps.employees.models import Department

from .models import (
    Application,
    ApplicationNote,
    ApplicationSource,
    ApplicationStatus,
    Assessment,
    EmploymentType,
    Interview,
    InterviewRecommendation,
    InterviewScorecard,
    InterviewType,
    JobRequisition,
    OfferLetter,
    ReferenceCheck,
    Vacancy,
    VacancyStatus,
    WorkMode,
)

User = get_user_model()


def _bootstrap(form):
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control")
        else:
            widget.attrs.setdefault("class", "form-control")


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = JobRequisition
        fields = [
            "title",
            "department",
            "branch",
            "positions",
            "employment_type",
            "justification",
            "job_description",
            "requirements",
            "min_salary",
            "max_salary",
            "target_start_date",
            "is_replacement",
            "replacement_for",
        ]
        widgets = {
            "justification": forms.Textarea(attrs={"rows": 3}),
            "job_description": forms.Textarea(attrs={"rows": 4}),
            "requirements": forms.Textarea(attrs={"rows": 3}),
            "target_start_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields["department"].queryset = Department.objects.all()


class VacancyForm(forms.ModelForm):
    class Meta:
        model = Vacancy
        fields = [
            "title",
            "requisition",
            "department",
            "branch",
            "description",
            "requirements",
            "responsibilities",
            "positions",
            "employment_type",
            "work_mode",
            "min_salary",
            "max_salary",
            "show_salary",
            "closing_date",
            "is_internal",
            "is_public",
            "hiring_manager",
            "recruiter",
            "status",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "requirements": forms.Textarea(attrs={"rows": 3}),
            "responsibilities": forms.Textarea(attrs={"rows": 3}),
            "closing_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields["requisition"].queryset = JobRequisition.objects.filter(
            status__in=["approved", "fulfilled"]
        ).order_by("-created_at")
        self.fields["requisition"].required = False
        self.fields["hiring_manager"].queryset = User.objects.filter(is_active=True).order_by(
            "first_name", "username"
        )
        self.fields["recruiter"].queryset = self.fields["hiring_manager"].queryset
        self.fields["hiring_manager"].required = False
        self.fields["recruiter"].required = False


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            "vacancy",
            "first_name",
            "last_name",
            "email",
            "phone",
            "resume",
            "cover_letter",
            "linkedin_url",
            "current_employer",
            "current_title",
            "years_experience",
            "expected_salary",
            "notice_period_days",
            "source",
            "referral_name",
            "assigned_recruiter",
        ]
        widgets = {
            "cover_letter": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        vacancy = kwargs.pop("vacancy", None)
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields["vacancy"].queryset = Vacancy.objects.filter(
            status__in=[VacancyStatus.OPEN, VacancyStatus.DRAFT]
        )
        self.fields["assigned_recruiter"].queryset = User.objects.filter(is_active=True)
        self.fields["assigned_recruiter"].required = False
        if vacancy:
            self.fields["vacancy"].initial = vacancy
            self.fields["vacancy"].widget = forms.HiddenInput()


class PublicApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "resume",
            "cover_letter",
            "linkedin_url",
            "current_employer",
            "current_title",
            "years_experience",
            "expected_salary",
            "notice_period_days",
            "referral_name",
        ]
        widgets = {
            "cover_letter": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional cover letter"}),
            "resume": forms.ClearableFileInput(
                attrs={
                    "accept": ".pdf,.doc,.docx",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields["resume"].required = True
        self.fields["resume"].label = "Upload CV / Resume"
        self.fields["resume"].help_text = "Accepted formats: PDF, DOC, or DOCX."


class StatusChangeForm(forms.Form):
    status = forms.ChoiceField(choices=ApplicationStatus.choices)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}))
    rejection_reason = forms.CharField(required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].widget.attrs["class"] = "form-select"
        self.fields["rejection_reason"].widget.attrs["class"] = "form-control"


class NoteForm(forms.ModelForm):
    class Meta:
        model = ApplicationNote
        fields = ["body", "is_private"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class InterviewForm(forms.ModelForm):
    class Meta:
        model = Interview
        fields = [
            "interview_type",
            "round_number",
            "title",
            "scheduled_at",
            "duration_minutes",
            "location",
            "meeting_link",
            "panel_members",
            "notes",
        ]
        widgets = {
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields["panel_members"].queryset = User.objects.filter(is_active=True).order_by(
            "first_name", "username"
        )
        self.fields["panel_members"].required = False


class InterviewFeedbackForm(forms.ModelForm):
    class Meta:
        model = Interview
        fields = ["rating", "recommendation", "feedback", "completed"]
        widgets = {"feedback": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ScorecardForm(forms.ModelForm):
    class Meta:
        model = InterviewScorecard
        fields = [
            "technical_skills",
            "communication",
            "cultural_fit",
            "problem_solving",
            "overall",
            "recommendation",
            "comments",
        ]
        widgets = {"comments": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        for f in ("technical_skills", "communication", "cultural_fit", "problem_solving", "overall"):
            self.fields[f].widget.attrs.update({"min": 0, "max": 5})


class OfferForm(forms.ModelForm):
    class Meta:
        model = OfferLetter
        fields = [
            "salary_offered",
            "currency",
            "start_date",
            "employment_type",
            "probation_months",
            "benefits_summary",
            "offer_notes",
            "expires_on",
            "document",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "expires_on": forms.DateInput(attrs={"type": "date"}),
            "benefits_summary": forms.Textarea(attrs={"rows": 3}),
            "offer_notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = [
            "assessment_type",
            "title",
            "description",
            "due_date",
            "score",
            "max_score",
            "status",
            "result_notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "result_notes": forms.Textarea(attrs={"rows": 2}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ReferenceForm(forms.ModelForm):
    class Meta:
        model = ReferenceCheck
        fields = [
            "referee_name",
            "referee_title",
            "referee_company",
            "referee_email",
            "referee_phone",
            "relationship",
            "contacted_at",
            "feedback",
            "would_rehire",
            "rating",
        ]
        widgets = {
            "feedback": forms.Textarea(attrs={"rows": 3}),
            "contacted_at": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ReviewNoteForm(forms.Form):
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control", "placeholder": "Optional note"}),
    )
