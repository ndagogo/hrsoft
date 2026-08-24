from django import forms

from apps.employees.models import Department, Designation, Employee

from .models import (
    Competency,
    Course,
    CourseLesson,
    EmployeeCompetency,
    PositionCompetency,
    TrainingAssessment,
    TrainingAttendance,
    TrainingCategory,
    TrainingEnrollment,
    TrainingEvaluation,
    TrainingInstructor,
    TrainingProgram,
    TrainingProvider,
    TrainingRequest,
    TrainingSchedule,
    AssessmentType,
)

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".ogg"}
MAX_VIDEO_UPLOAD_MB = 500


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            "code", "title", "description", "category", "training_type", "delivery_method",
            "duration_hours", "difficulty", "provider_org", "provider", "default_instructor",
            "budget_cost", "currency", "prerequisites", "target_audience",
            "is_mandatory", "issues_certificate", "certificate_validity_months",
            "pass_mark", "max_attempts", "require_assessment", "require_full_attendance",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "prerequisites": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "target_audience": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif not field.widget.attrs.get("class"):
                css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                field.widget.attrs["class"] = css


class SessionForm(forms.ModelForm):
    class Meta:
        model = TrainingSchedule
        fields = [
            "course", "title", "start_date", "end_date", "start_time", "end_time",
            "location", "meeting_url", "instructor", "trainer", "max_participants",
            "status", "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("notes", "start_date", "end_date", "start_time", "end_time"):
                continue
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class TrainingRequestForm(forms.ModelForm):
    class Meta:
        model = TrainingRequest
        fields = ["course", "course_title", "reason", "expected_benefit", "preferred_date", "estimated_cost", "attachment"]
        widgets = {
            "preferred_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "reason": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "expected_benefit": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "course": forms.Select(attrs={"class": "form-select"}),
            "course_title": forms.TextInput(attrs={"class": "form-control"}),
            "estimated_cost": forms.NumberInput(attrs={"class": "form-control"}),
            "attachment": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(is_active=True, is_archived=False)
        self.fields["course"].required = False


class EnrollmentForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(status="active").select_related("user"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    schedule = forms.ModelChoiceField(
        queryset=TrainingSchedule.objects.select_related("course").filter(status="published"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = TrainingAttendance
        fields = ["session_date", "mark", "notes"]
        widgets = {
            "session_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "mark": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = TrainingAssessment
        fields = ["assessment_type", "score", "max_score", "notes"]
        widgets = {
            "assessment_type": forms.Select(attrs={"class": "form-select"}),
            "score": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "max_score": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


class EvaluationForm(forms.ModelForm):
    class Meta:
        model = TrainingEvaluation
        fields = [
            "instructor_quality", "course_content", "materials", "venue",
            "relevance", "practical_usefulness", "overall", "comments",
        ]
        widgets = {f: forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5})
                   for f in [
                       "instructor_quality", "course_content", "materials", "venue",
                       "relevance", "practical_usefulness", "overall",
                   ]}
        widgets["comments"] = forms.Textarea(attrs={"rows": 2, "class": "form-control"})


class CompetencyForm(forms.ModelForm):
    class Meta:
        model = Competency
        fields = ["name", "code", "description", "category", "max_level", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "category": forms.TextInput(attrs={"class": "form-control"}),
            "max_level": forms.NumberInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PositionCompetencyForm(forms.ModelForm):
    class Meta:
        model = PositionCompetency
        fields = ["designation", "competency", "required_level"]
        widgets = {
            "designation": forms.Select(attrs={"class": "form-select"}),
            "competency": forms.Select(attrs={"class": "form-select"}),
            "required_level": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
        }


class EmployeeCompetencyForm(forms.ModelForm):
    class Meta:
        model = EmployeeCompetency
        fields = ["employee", "competency", "current_level", "notes"]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "competency": forms.Select(attrs={"class": "form-select"}),
            "current_level": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 5}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = TrainingCategory
        fields = ["name", "code", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ProviderForm(forms.ModelForm):
    class Meta:
        model = TrainingProvider
        fields = ["name", "contact_person", "email", "phone", "website", "address", "rating", "is_active", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control", "rows": 2})
            else:
                field.widget.attrs["class"] = "form-control"


class InstructorForm(forms.ModelForm):
    class Meta:
        model = TrainingInstructor
        fields = [
            "name", "instructor_type", "employee", "organization", "email", "phone",
            "specialization", "qualifications", "daily_rate", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({"class": "form-control", "rows": 2})
            else:
                field.widget.attrs["class"] = "form-control"


class ProgramForm(forms.ModelForm):
    class Meta:
        model = TrainingProgram
        fields = ["code", "title", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CourseLessonForm(forms.ModelForm):
    class Meta:
        model = CourseLesson
        fields = [
            "title",
            "description",
            "sort_order",
            "video",
            "external_url",
            "duration_seconds",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "video": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov,.m4v"}
            ),
            "external_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://… (optional if uploading a file)"}
            ),
            "duration_seconds": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_published": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_video(self):
        video = self.cleaned_data.get("video")
        if not video:
            return video
        name = getattr(video, "name", "") or ""
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if ext and ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise forms.ValidationError(
                f"Unsupported video type '{ext}'. Use: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}."
            )
        size = getattr(video, "size", 0) or 0
        if size > MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"Video must be under {MAX_VIDEO_UPLOAD_MB} MB.")
        return video

    def clean(self):
        cleaned = super().clean()
        video = cleaned.get("video")
        external = (cleaned.get("external_url") or "").strip()
        if not video and not external and not (self.instance and self.instance.pk and self.instance.video):
            raise forms.ValidationError("Upload a video file or provide an external video URL.")
        return cleaned
