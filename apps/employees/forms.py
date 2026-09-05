from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.organization.models import Branch
from apps.rbac.models import Role

from .conflicts import assert_no_staff_conflict, find_staff_conflicts, normalize_email
from .models import Employee, Department, Designation, EmploymentType, Gender

User = get_user_model()


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

    def clean(self):
        cleaned = super().clean()
        bio = cleaned.get("biometric_id")
        if bio:
            exclude_id = self.instance.pk if self.instance and self.instance.pk else None
            match = find_staff_conflicts(
                biometric_id=bio,
                exclude_employee_id=exclude_id,
                check_open_invite=False,
                check_blocking_invite=False,
            )
            if match and match.matched_by == "biometric ID":
                self.add_error("biometric_id", match.message)
        return cleaned


class EmployeeInviteForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "colleague@company.com"}),
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    designation = forms.ModelChoiceField(
        queryset=Designation.objects.select_related("department"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branches = forms.ModelMultipleChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "4"}),
        help_text="Optional prefills applied when the invitee completes onboarding.",
    )
    employment_type = forms.ChoiceField(
        choices=EmploymentType.choices,
        initial=EmploymentType.FULL_TIME,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    manager = forms.ModelChoiceField(
        queryset=Employee.objects.select_related("user"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.all().order_by("name")
        self.fields["manager"].queryset = Employee.objects.select_related("user").order_by(
            "user__first_name", "user__last_name"
        )

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get("email"))
        try:
            assert_no_staff_conflict(
                email=email,
                check_open_invite=True,
                check_blocking_invite=True,
            )
        except ValidationError as exc:
            raise ValidationError(exc.messages[0] if getattr(exc, "messages", None) else str(exc))
        return email


class SelfOnboardForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name"}),
    )
    username = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}),
        help_text="Leave blank to use the part of your email before @.",
    )
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "tel"}),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    gender = forms.ChoiceField(
        choices=[("", "—")] + list(Gender.choices),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    address = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    emergency_contact_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    emergency_contact_phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    biometric_id = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional device User ID"}),
    )

    def __init__(self, *args, invite=None, **kwargs):
        self.invite = invite
        super().__init__(*args, **kwargs)
        if invite and not self.is_bound:
            local = (invite.email or "").split("@")[0]
            self.fields["username"].initial = local

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username and self.invite:
            username = (self.invite.email or "").split("@")[0]
        if not username:
            raise ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is already taken.")
        return username

    def clean_biometric_id(self):
        value = (self.cleaned_data.get("biometric_id") or "").strip()
        return value or None

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords don't match.")
        if p1:
            validate_password(p1)
        email = normalize_email(self.invite.email) if self.invite else None
        match = find_staff_conflicts(
            email=email,
            username=cleaned.get("username"),
            biometric_id=cleaned.get("biometric_id"),
            exclude_invite_id=self.invite.pk if self.invite else None,
            check_open_invite=False,
            check_blocking_invite=True,
        )
        if match:
            raise ValidationError(match.message)
        return cleaned
