from django import forms

from .models import Document, DocumentCategory, EMPLOYEE_UPLOAD_CATEGORIES


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "file", "description", "expiry_date", "is_confidential"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "is_confidential": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, employee_self_upload=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["expiry_date"].required = False
        self.fields["is_confidential"].required = False
        if employee_self_upload:
            self.fields["category"].choices = [
                (c.value, c.label) for c in DocumentCategory if c.value in EMPLOYEE_UPLOAD_CATEGORIES
            ]
            self.fields.pop("is_confidential", None)
