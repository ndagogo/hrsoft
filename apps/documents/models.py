from django.conf import settings
from django.db import models


class DocumentCategory(models.TextChoices):
    CONTRACT = "contract", "Employment Contract"
    ACADEMIC = "academic", "Academic Certificate"
    GUARANTOR = "guarantor", "Guarantor Form"
    REFERENCE = "reference", "Reference Letter"
    CV = "cv", "CV / Resume"
    ID = "id", "Means of Identification"
    OFFER_LETTER = "offer_letter", "Offer Letter"
    APPOINTMENT = "appointment", "Appointment Letter"
    CERTIFICATE = "certificate", "Professional Certificate"
    MEDICAL = "medical", "Medical Report"
    BANK = "bank", "Bank Details Form"
    TAX = "tax", "Tax Document"
    NDA = "nda", "NDA"
    WARNING = "warning", "Warning"
    PROMOTION = "promotion", "Promotion"
    OTHER = "other", "Other"


# Categories employees may upload themselves
EMPLOYEE_UPLOAD_CATEGORIES = {
    DocumentCategory.ACADEMIC,
    DocumentCategory.GUARANTOR,
    DocumentCategory.REFERENCE,
    DocumentCategory.CV,
    DocumentCategory.ID,
    DocumentCategory.CERTIFICATE,
    DocumentCategory.MEDICAL,
    DocumentCategory.BANK,
    DocumentCategory.TAX,
    DocumentCategory.OTHER,
}


class Document(models.Model):
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=DocumentCategory.choices, default=DocumentCategory.OTHER)
    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, null=True, blank=True, related_name="documents"
    )
    file = models.FileField(upload_to="documents/%Y/%m/")
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    is_confidential = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
